#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)
# stat_parser.py
# StatTracker parser.
#
# Reads WTF/Account/<ACCOUNT>/SavedVariables/StatTracker.lua, stores every scan in
# a SQLite database (with history) and builds a self-contained stats page from it
# (data embedded, no web server needed). Before it writes to an existing database it takes a
# copy of it (db_backup). With --history-dir it also keeps the history pages of the characters
# up to date (stat_history, imported late in update_history_pages) and links them from the page;
# with --icons-dir as well, those pages show the item icons that folder holds, and with --game-dir and
# --product the import first reads the icons of the stored equipment that the folder lacks from the game
# files (wow_icons, imported late in update_icons); the characters whose icons are new get their page written.
#
# Usage:
#     python stat_parser.py --input PATH\StatTracker.lua [--db FILE] [--output FILE] [--history-dir DIR]
#                           [--icons-dir DIR [--game-dir WOW_FOLDER --product wow]]
# No external dependencies.

import argparse
import json
import math
import os
import re
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

import app_info
import db_backup
import i18n
import paths
import stat_derive
from i18n import t

DEFAULT_WTF = Path(r"C:\Program Files (x86)\World of Warcraft\_retail_\WTF\Account")


# ---------------------------------------------------------------- Lua-Reader
class LuaError(Exception):
    pass


class LuaReader:
    """Minimal reader for what WoW writes into SavedVariables:
    assignments to tables, strings, numbers, true/false/nil, comments."""

    ESC = {"n": "\n", "t": "\t", "r": "\r", "a": "\a", "b": "\b",
           "f": "\f", "v": "\v", "\\": "\\", '"': '"', "'": "'", "\n": "\n"}
    NUM = re.compile(r"-?(?:0[xX][0-9a-fA-F]+|\d+\.?\d*(?:[eE][+-]?\d+)?|\.\d+)")
    NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")

    def __init__(self, text):
        self.s = text
        self.i = 0

    def err(self, msg):
        line = self.s.count("\n", 0, self.i) + 1
        raise LuaError(f"line {line}: {msg}")

    def ws(self):
        s, n = self.s, len(self.s)
        while self.i < n:
            c = s[self.i]
            if c.isspace():
                self.i += 1
            elif s.startswith("--", self.i):
                j = s.find("\n", self.i)
                self.i = n if j == -1 else j + 1
            else:
                break

    def parse_file(self):
        out = {}
        while True:
            self.ws()
            if self.i >= len(self.s):
                return out
            m = self.NAME.match(self.s, self.i)
            if not m:
                self.err("variable name expected")
            self.i = m.end()
            self.ws()
            if self.s[self.i:self.i + 1] != "=":
                self.err("'=' expected")
            self.i += 1
            out[m.group()] = self.value()

    def value(self):
        self.ws()
        s = self.s
        c = s[self.i:self.i + 1]
        if c == "{":
            return self.table()
        if c in ('"', "'"):
            return self.string()
        m = self.NUM.match(s, self.i)
        if m:
            self.i = m.end()
            t_ = m.group()
            if t_.lower().lstrip("-").startswith("0x"):
                return int(t_, 16)
            f = float(t_)
            return int(f) if f.is_integer() and "." not in t_ and "e" not in t_.lower() else f
        for lit, val in (("true", True), ("false", False), ("nil", None)):
            if s.startswith(lit, self.i):
                self.i += len(lit)
                return val
        self.err(f"unexpected character {c!r}")

    def string(self):
        s = self.s
        q = s[self.i]
        self.i += 1
        buf = []
        while True:
            if self.i >= len(s):
                self.err("string not terminated")
            c = s[self.i]
            if c == q:
                self.i += 1
                return "".join(buf)
            if c == "\\":
                self.i += 1
                e = s[self.i]
                if e.isdigit():
                    m = re.compile(r"\d{1,3}").match(s, self.i)
                    buf.append(chr(int(m.group())))
                    self.i = m.end()
                    continue
                buf.append(self.ESC.get(e, e))
                self.i += 1
            else:
                buf.append(c)
                self.i += 1

    def table(self):
        self.i += 1  # {
        result = {}
        pos = 1
        while True:
            self.ws()
            c = self.s[self.i:self.i + 1]
            if c == "":
                self.err("table not terminated")
            if c == "}":
                self.i += 1
                return result
            if c == "[":
                self.i += 1
                key = self.value()
                self.ws()
                if self.s[self.i:self.i + 1] != "]":
                    self.err("']' expected")
                self.i += 1
                self.ws()
                if self.s[self.i:self.i + 1] != "=":
                    self.err("'=' expected")
                self.i += 1
                result[key] = self.value()
            else:
                m = self.NAME.match(self.s, self.i)
                after = self.s[m.end():].lstrip()[:1] if m else ""
                if m and after == "=" and m.group() not in ("true", "false", "nil"):
                    self.i = m.end()
                    self.ws()
                    self.i += 1  # =
                    result[m.group()] = self.value()
                else:
                    result[pos] = self.value()
                    pos += 1
            self.ws()
            if self.s[self.i:self.i + 1] in (",", ";"):
                self.i += 1


# ------------------------------------------------------------ value evaluation
def clean_text(text):
    """WoW escapes (coin icons, colors) -> readable text."""
    text = re.sub(r"\|T[^|]*?(Gold|Silver|Copper)Icon[^|]*?\|t",
                  lambda m: {"Gold": "g", "Silver": "s", "Copper": "c"}[m.group(1)], text)
    text = re.sub(r"\|T.*?\|t", "", text)
    text = re.sub(r"\|c[0-9a-fA-F]{8}", "", text).replace("|r", "")
    return text.strip()


def to_number(text):
    """Comparable number or None.
    - number with 1-2 decimals ('0.20', '3,5') -> float
    - whole number, thousands groups of exactly 3 digits ('1.234', '12 345') -> int
    - gold/silver/copper ('12g 3s 4c') -> copper
    - anything else (durations, percent, '--') -> None (text comparison only)"""
    s = clean_text(text)
    if s in ("", "--"):
        return None
    m = re.fullmatch(r"(\d+)[.,](\d{1,2})", s)
    if m:
        return float(f"{m.group(1)}.{m.group(2)}")
    if re.fullmatch(r"\d+|\d{1,3}(?:[.,\s\u00a0\u202f]\d{3})+", s):
        return int(re.sub(r"\D", "", s))
    if re.fullmatch(r"(?:\d[\d.,]*\s*[gsc]\s*)+", s):
        mult = {"g": 10000, "s": 100, "c": 1}
        total = 0
        for num, unit in re.findall(r"(\d[\d.,]*)\s*([gsc])", s):
            total += int(re.sub(r"\D", "", num)) * mult[unit]
        return total
    return None


# Played time (from TIME_PLAYED_MSG) is kept as pseudo statistics with negative IDs,
# so the DB and the pages need no schema change. Names are translated at output
# time (played_labels), whatever language the DB rows were written in.
PLAYED_STATS = (
    (-1, "playedTotal", "played_total"),
    (-2, "playedLevel", "played_level"),
)
PLAYED_CATEGORY_KEY = "played_category"


def played_labels():
    """{stat_id: (name, category)} for the played-time pseudo statistics, current language."""
    return {sid: (t(key), t(PLAYED_CATEGORY_KEY)) for sid, _field, key in PLAYED_STATS}


def fmt_duration(sec):
    d, rest = divmod(int(sec), 86400)
    h, rest = divmod(rest, 3600)
    m, s = divmod(rest, 60)
    return t("duration_fmt", d=d, h=h, m=m, s=s)


# ------------------------------------------------------------------------ DB
# Schema version of the statistics database, kept in SQLite's PRAGMA user_version.
# 0 = no number written yet (databases of v0.1.x), 1 = the same layout, 2 = the layout below
# (scans gained class_file, race, race_file), 3 = the layout below (scans gained the specialization and item level,
# new tables scan_gear, rep_defs, scan_reputation). Changing the layout means a new entry in
# MIGRATIONS and a higher SCHEMA_VERSION; an old step is never edited.
# A database newer than SCHEMA_VERSION is refused untouched (fail-closed).
SCHEMA_VERSION = 3


def _migrate_0_to_1(conn):
    """Schema 0 has the same layout as schema 1: only the number is set (by init_db)."""


def _migrate_1_to_2(conn):
    """Schema 2 adds the stable class name and the race to every scan. Scans taken before stay
    NULL: they are never filled in from a later scan, because a race can change."""
    for column in ("class_file", "race", "race_file"):
        conn.execute(f"ALTER TABLE scans ADD COLUMN {column} TEXT")


# What schema 3 adds. One definition for a new file (SCHEMA_SQL) and for the migration of an old one, so that the two
# cannot drift apart (tests/test_db_schema.py compares a fresh with a migrated database).
SCAN_COLUMNS_V3 = (("spec_id", "INTEGER"), ("spec_name", "TEXT"), ("role", "TEXT"),
                   ("ilvl_total", "REAL"), ("ilvl_equipped", "REAL"))
TABLES_V3 = (
    """CREATE TABLE IF NOT EXISTS scan_gear (
            scan_id      INTEGER NOT NULL REFERENCES scans(scan_id),
            slot         INTEGER NOT NULL,
            item_id      INTEGER,
            name         TEXT,
            quality      INTEGER,
            ilvl         INTEGER,
            icon_id      INTEGER,
            enchant_id   INTEGER,
            enchant_text TEXT,
            upg_track_id INTEGER,
            upg_track    TEXT,
            upg_level    INTEGER,
            upg_max      INTEGER,
            sockets      INTEGER,
            gem_ids      TEXT,
            stats        TEXT,
            PRIMARY KEY (scan_id, slot)
        )""",
    """CREATE TABLE IF NOT EXISTS rep_defs (
            faction_id INTEGER PRIMARY KEY,
            name       TEXT NOT NULL
        )""",
    """CREATE TABLE IF NOT EXISTS scan_reputation (
            scan_id      INTEGER NOT NULL REFERENCES scans(scan_id),
            ord          INTEGER NOT NULL,
            faction_id   INTEGER NOT NULL,
            is_header    INTEGER NOT NULL DEFAULT 0,
            is_child     INTEGER NOT NULL DEFAULT 0,
            account_wide INTEGER NOT NULL DEFAULT 0,
            kind         TEXT,
            reaction     INTEGER,
            standing     INTEGER,
            lo           INTEGER,
            hi           INTEGER,
            level        INTEGER,
            max_level    INTEGER,
            renown       INTEGER,
            earned       INTEGER,
            need         INTEGER,
            max_renown   INTEGER,
            p_value      INTEGER,
            p_threshold  INTEGER,
            p_quest      INTEGER,
            p_pending    INTEGER,
            PRIMARY KEY (scan_id, ord)
        )""",
)


def _migrate_2_to_3(conn):
    """Schema 3 adds the specialization and item level to every scan and the tables of gear and reputation. Scans taken
    before stay NULL and have no rows there: nothing is filled in from a later scan."""
    for column, kind in SCAN_COLUMNS_V3:
        conn.execute(f"ALTER TABLE scans ADD COLUMN {column} {kind}")
    for statement in TABLES_V3:
        conn.execute(statement)


MIGRATIONS = {1: _migrate_0_to_1, 2: _migrate_1_to_2, 3: _migrate_2_to_3}      # target version -> step from the version before

SCHEMA_SQL = """
        CREATE TABLE IF NOT EXISTS scans (
            scan_id    INTEGER PRIMARY KEY AUTOINCREMENT,
            char_key   TEXT NOT NULL,
            scanned_at TEXT NOT NULL,
            class      TEXT,
            level      INTEGER,
            faction    TEXT,
            class_file TEXT,
            race       TEXT,
            race_file  TEXT,
{scan_columns_v3}            UNIQUE (char_key, scanned_at)
        );
        CREATE TABLE IF NOT EXISTS stat_defs (
            stat_id  INTEGER PRIMARY KEY,
            name     TEXT NOT NULL,
            category TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS stat_values (
            scan_id    INTEGER NOT NULL REFERENCES scans(scan_id),
            stat_id    INTEGER NOT NULL,
            value_text TEXT NOT NULL,
            value_num  INTEGER,
            PRIMARY KEY (scan_id, stat_id)
        );
"""
SCHEMA_SQL = SCHEMA_SQL.replace("{scan_columns_v3}", "".join(f"            {c} {k},\n" for c, k in SCAN_COLUMNS_V3))
SCHEMA_SQL += ";\n".join(TABLES_V3) + ";\n"


def schema_version(conn):
    return conn.execute("PRAGMA user_version").fetchone()[0]


def check_schema(conn, path):
    """Exits with a message if the database is newer than this program knows; otherwise
    returns its version. Everything that opens a statistics database calls this first."""
    found = schema_version(conn)
    if found > SCHEMA_VERSION:
        sys.exit(t("parse_err_db_too_new", path=path, found=found, known=SCHEMA_VERSION))
    return found


def _in_transaction(conn, work):
    """Runs work() as one transaction: all or nothing. The connection keeps its normal
    transaction handling afterwards (import_data relies on it to commit only at the end)."""
    previous = conn.isolation_level
    conn.isolation_level = None            # BEGIN/COMMIT are issued here, not by sqlite3
    try:
        conn.execute("BEGIN")
        try:
            work()
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise
    finally:
        conn.isolation_level = previous


def _back_up(conn, path, found):
    """A copy of an existing database before anything is written to it: before a migration
    (found < SCHEMA_VERSION) one that is kept for good, otherwise the copy of the day. If it
    cannot be written, exits with a message and nothing has been changed (fail-closed). Old daily
    copies that cannot be deleted only produce a warning."""
    try:
        if found < SCHEMA_VERSION:
            made = db_backup.migration_backup(conn, path, SCHEMA_VERSION)
        else:
            made = db_backup.daily_backup(conn, path)
    except db_backup.DamagedDatabase as exc:
        sys.exit(t("parse_err_db_damaged", folder=db_backup.daily_dir(path).parent, found="; ".join(exc.problems)))
    except db_backup.BackupError as exc:
        sys.exit(t("parse_err_backup_failed", error=exc))
    if made:
        print(t("parse_out_backup", path=made))
    if found >= SCHEMA_VERSION:
        failed = db_backup.rotate(path)
        if failed:
            print(t("parse_warn_backup_rotate", paths=", ".join(map(str, failed))))


def init_db(path):
    """Opens (or creates) the statistics database at its current schema version.
    New or empty file: created at SCHEMA_VERSION. Older database: copied (db_backup), then
    migrated step by step, each step its own transaction, the number raised at the end of it.
    Current database: copied once a day. Newer database: exits with a message and has not
    written anything. A copy that cannot be written stops everything before the first change."""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        found = check_schema(conn, path)
        has_tables = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='scans'").fetchone() is not None
        if not has_tables:
            conn.executescript(f"BEGIN;{SCHEMA_SQL}PRAGMA user_version = {SCHEMA_VERSION};COMMIT;")
        else:
            _back_up(conn, path, found)
            for target in range(found + 1, SCHEMA_VERSION + 1):
                _in_transaction(conn, lambda: (MIGRATIONS[target](conn),
                                               conn.execute(f"PRAGMA user_version = {target}")))
    except BaseException:
        conn.close()
        raise
    return conn


# The contract between the addon and this parser is StatTrackerDB.version (header of
# StatTracker.lua). The addon writes it for the whole file, so it is a ceiling, not a mark on
# a single scan: a file with a higher number than DATA_VERSION is refused, a missing number is
# accepted (hand-made files, older tests). Raising it goes with the change of the fields.
DATA_VERSION = 4


def check_data_version(db, path):
    """Exits with a message if the data version of the file is higher than this program
    knows or is not a whole number; a missing one passes. main() calls it before the database
    is opened, so a refused file leaves no copy and no change behind."""
    found = db.get("version") if isinstance(db, dict) else None
    if found is None:
        return
    if isinstance(found, bool) or not isinstance(found, int) or found > DATA_VERSION:
        sys.exit(t("parse_err_data_too_new", path=path, found=found, known=DATA_VERSION))


def _name_or_none(value):
    """Display text from the addon (class file, race): a non-empty string, otherwise NULL.
    A scan from an older addon has none; a wrong type is not worth stopping the import for."""
    return value.strip() if isinstance(value, str) and value.strip() else None


def _int_or_none(value):
    """A whole number from the addon, otherwise NULL. A bool is not a number."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return None


def _number_or_none(value):
    """A finite number from the addon (item level 276.5), otherwise NULL."""
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return None
    return value


def _flag(value):
    """The marks of the addon (category, sub category, account wide) are true or absent."""
    return 1 if value is True else 0


def _sequence(value):
    """The values of a positional Lua table in their order. LuaReader returns every table as a dict, a positional
    one with the keys 1..n; anything else (text, a key that is not a whole number) is not a sequence: None."""
    if not isinstance(value, dict) or not all(isinstance(k, int) and not isinstance(k, bool) for k in value):
        return None
    return [value[k] for k in sorted(value)]


GEAR_SLOTS = range(1, 20)                       # inventory slots the addon reads
REP_KINDS = ("std", "friend", "major")
# the numbers an entry of each kind carries: column name -> field of the addon
REP_FIELDS = {"std": {"reaction": "reaction", "standing": "standing", "lo": "lo", "hi": "hi"},
              "friend": {"standing": "standing", "lo": "lo", "hi": "hi", "level": "level", "max_level": "maxLevel"},
              "major": {"renown": "renown", "earned": "earned", "need": "need", "max_renown": "maxRenown"}}


def _item_stats(value):
    """{ITEM_MOD_...: number} without what is not a text key with a number."""
    if not isinstance(value, dict):
        return None
    stats = {k: v for k, v in value.items() if isinstance(k, str) and _number_or_none(v) is not None}
    return stats or None


def _read_gear(value):
    """(rows, skipped): the equipped items of a scan. A slot outside 1..19, an entry that is not a table or has no item id
    is skipped and counted (a nil gap is no entry); a field of the wrong type is NULL."""
    if value is None:
        return [], 0
    if not isinstance(value, dict):
        return [], 1
    rows, skipped = [], 0
    for slot, item in sorted(value.items(), key=lambda kv: str(kv[0])):
        if item is None:
            continue                                        # WoW writes a gap in the table as "nil,": an empty slot, not an error
        item_id = _int_or_none(item.get("itemID")) if isinstance(item, dict) else None
        if _int_or_none(slot) not in GEAR_SLOTS or item_id is None:
            skipped += 1
            continue
        up = item.get("upgrade") if isinstance(item.get("upgrade"), dict) else {}
        gems = _sequence(item.get("gems")) if item.get("gems") is not None else None
        if gems is not None and any(_int_or_none(g) is None for g in gems):
            gems = None                                     # one unreadable id would shift the others: all or nothing
        rows.append({"slot": _int_or_none(slot), "item_id": item_id,
                     "name": _name_or_none(item.get("name")), "quality": _int_or_none(item.get("quality")),
                     "ilvl": _int_or_none(item.get("ilvl")), "icon_id": _int_or_none(item.get("iconID")),
                     "enchant_id": _int_or_none(item.get("enchantID")),
                     "enchant_text": _name_or_none(item.get("enchantText")),
                     "upg_track_id": _int_or_none(up.get("trackID")), "upg_track": _name_or_none(up.get("track")),
                     "upg_level": _int_or_none(up.get("level")), "upg_max": _int_or_none(up.get("max")),
                     "sockets": _int_or_none(item.get("sockets")),
                     "gem_ids": None if gems is None else [_int_or_none(g) for g in gems],
                     "stats": _item_stats(item.get("stats"))})
    return rows, skipped


def _read_rep(value):
    """(rows, skipped): the reputation list of a scan in the order of the game. An entry without a faction id or
    position, with a position seen before, or of an unknown kind is skipped and counted."""
    if value is None:
        return [], 0
    entries = _sequence(value)
    if entries is None:
        return [], 1
    rows, skipped, seen = [], 0, set()
    for e in entries:
        faction = _int_or_none(e.get("id")) if isinstance(e, dict) else None
        ord_ = _int_or_none(e.get("ord")) if isinstance(e, dict) else None
        kind = e.get("kind") if isinstance(e, dict) else None
        if faction is None or faction <= 0 or ord_ is None or ord_ < 1 or ord_ in seen \
                or (kind is not None and kind not in REP_KINDS):
            skipped += 1
            continue
        seen.add(ord_)
        row = {"ord": ord_, "faction_id": faction, "is_header": _flag(e.get("hdr")), "is_child": _flag(e.get("child")),
               "account_wide": _flag(e.get("aw")), "kind": kind}
        for column in ("reaction", "standing", "lo", "hi", "level", "max_level", "renown", "earned", "need", "max_renown",
                       "p_value", "p_threshold", "p_quest", "p_pending"):
            row[column] = None
        for column, field in REP_FIELDS.get(kind, {}).items():
            row[column] = _int_or_none(e.get(field))
        par = e.get("paragon")
        if isinstance(par, dict):
            row.update(p_value=_int_or_none(par.get("value")), p_threshold=_int_or_none(par.get("threshold")),
                       p_quest=_int_or_none(par.get("quest")),
                       p_pending=None if not isinstance(par.get("pending"), bool) else int(par["pending"]))
        rows.append(row)
    return rows, skipped


def read_scan(c):
    """One scan of the file (the entry of `chars`, or one of `history`) as checked values, or None when it is not a
    scan at all (no table, no statistics, no scan time). The parts added by version 4 are optional: a field of the
    wrong type is NULL, an unusable gear or reputation entry is skipped and counted in "skipped"."""
    stats = c.get("stats") if isinstance(c, dict) else None
    if not isinstance(stats, dict) or not stats or "scannedAt" not in c:
        return None
    gear, skipped_gear = _read_gear(c.get("gear"))
    rep, skipped_rep = _read_rep(c.get("rep"))
    return {"at": c["scannedAt"], "class": c.get("class"), "level": c.get("level"), "faction": c.get("faction"),
            "class_file": _name_or_none(c.get("classFile")), "race": _name_or_none(c.get("race")),
            "race_file": _name_or_none(c.get("raceFile")), "stats": stats, "raw": c,
            "spec_id": _int_or_none(c.get("specID")), "spec_name": _name_or_none(c.get("specName")),
            "role": _name_or_none(c.get("role")), "ilvl_total": _number_or_none(c.get("ilvlTotal")),
            "ilvl_equipped": _number_or_none(c.get("ilvlEquipped")),
            "gear": gear, "rep": rep, "skipped": skipped_gear + skipped_rep}


def scans_by_char(db):
    """{char key: [scan, ...] oldest first}: the newest scan of `chars` and the older ones of `history`, all checked by
    read_scan. Anything that is not a scan stops the import (it has not touched the database yet)."""
    chars, history = db.get("chars"), db.get("history")
    if history is not None and not isinstance(history, dict):
        sys.exit(t("parse_err_history_table"))
    found = {}
    for key, c in chars.items():
        scan = read_scan(c)
        if scan is None:
            sys.exit(t("parse_err_incomplete_char", key=key))
        found.setdefault(key, []).append(scan)
    for key, entries in (history or {}).items():
        sequence = _sequence(entries)
        if sequence is None:
            sys.exit(t("parse_err_history_list", key=key))
        for n, c in enumerate(sequence, 1):
            scan = read_scan(c)
            if scan is None:
                sys.exit(t("parse_err_incomplete_history", key=key, n=n))
            found.setdefault(key, []).append(scan)
    for scans in found.values():
        scans.sort(key=lambda s: str(s["at"]))             # oldest first, so the numbers in the database follow the time
    return found


def _json_or_none(value):
    return None if value is None else json.dumps(value, sort_keys=True, separators=(",", ":"))


GEAR_COLUMNS = ("slot", "item_id", "name", "quality", "ilvl", "icon_id", "enchant_id", "enchant_text", "upg_track_id",
                "upg_track", "upg_level", "upg_max", "sockets", "gem_ids", "stats")
REP_COLUMNS = ("ord", "faction_id", "is_header", "is_child", "account_wide", "kind", "reaction", "standing", "lo", "hi",
               "level", "max_level", "renown", "earned", "need", "max_renown", "p_value", "p_threshold", "p_quest", "p_pending")


def store_details(conn, scan_id, scan):
    """The gear and the reputation list of a scan that was just inserted (never of one that was already there)."""
    conn.executemany(
        f"INSERT INTO scan_gear(scan_id,{','.join(GEAR_COLUMNS)}) VALUES(?{',?' * len(GEAR_COLUMNS)})",
        [(scan_id, *(_json_or_none(row[c]) if c in ("gem_ids", "stats") else row[c] for c in GEAR_COLUMNS))
         for row in scan["gear"]])
    conn.executemany(
        f"INSERT INTO scan_reputation(scan_id,{','.join(REP_COLUMNS)}) VALUES(?{',?' * len(REP_COLUMNS)})",
        [(scan_id, *(row[c] for c in REP_COLUMNS)) for row in scan["rep"]])


def import_data(conn, db):
    """Stores the scans of the file: the newest of every character and the older ones in `history`. Returns
    (new, skipped, changed): the number of new scans, the number already in the database, and the keys of the
    characters that got a new scan."""
    meta = db.get("meta")
    chars = db.get("chars")
    if not isinstance(meta, dict) or not isinstance(chars, dict) or not chars:
        sys.exit(t("parse_err_no_chars"))
    by_char = scans_by_char(db)

    for sid, m in meta.items():
        conn.execute("INSERT INTO stat_defs(stat_id,name,category) VALUES(?,?,?) "
                     "ON CONFLICT(stat_id) DO UPDATE SET name=excluded.name, category=excluded.category",
                     (int(sid), str(m.get("name", "")), str(m.get("cat", ""))))

    for sid, (name, cat) in played_labels().items():
        conn.execute("INSERT INTO stat_defs(stat_id,name,category) VALUES(?,?,?) "
                     "ON CONFLICT(stat_id) DO UPDATE SET name=excluded.name, category=excluded.category",
                     (sid, name, cat))

    for faction, entry in (db.get("repMeta") if isinstance(db.get("repMeta"), dict) else {}).items():
        faction_id = _int_or_none(faction)
        name = _name_or_none(entry.get("name")) if isinstance(entry, dict) else None
        if faction_id and faction_id > 0 and name:
            conn.execute("INSERT INTO rep_defs(faction_id,name) VALUES(?,?) "
                         "ON CONFLICT(faction_id) DO UPDATE SET name=excluded.name", (faction_id, name))

    new = skipped = 0
    changed = []
    for key, scans in by_char.items():
        for scan in scans:
            c = scan["raw"]
            cur = conn.execute(
                "INSERT OR IGNORE INTO scans(char_key,scanned_at,class,level,faction,class_file,race,race_file,"
                "spec_id,spec_name,role,ilvl_total,ilvl_equipped) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (key, scan["at"], scan["class"], scan["level"], scan["faction"],
                 scan["class_file"], scan["race"], scan["race_file"],
                 scan["spec_id"], scan["spec_name"], scan["role"], scan["ilvl_total"], scan["ilvl_equipped"]))
            if cur.rowcount == 0:
                skipped += 1
                continue
            scan_id = cur.lastrowid
            conn.executemany(
                "INSERT INTO stat_values(scan_id,stat_id,value_text,value_num) VALUES(?,?,?,?)",
                [(scan_id, int(sid), clean_text(str(v)), to_number(str(v))) for sid, v in scan["stats"].items()])

            if any(field not in c for _sid, field, _key in PLAYED_STATS):
                print(t("parse_warn_no_played", key=key, at=scan["at"]))
            for sid, field, _key in PLAYED_STATS:
                if field not in c:
                    continue
                sec = c[field]
                if isinstance(sec, bool) or not isinstance(sec, (int, float)) or sec < 0:
                    sys.exit(t("parse_err_played_invalid", key=key, field=field, value=sec))
                conn.execute("INSERT INTO stat_values(scan_id,stat_id,value_text,value_num) VALUES(?,?,?,?)",
                             (scan_id, sid, fmt_duration(sec), int(sec)))
            store_details(conn, scan_id, scan)
            if scan["skipped"]:
                print(t("parse_warn_scan_details", key=key, at=scan["at"], count=scan["skipped"]))
            new += 1
            if key not in changed:
                changed.append(key)
    conn.commit()
    return new, skipped, changed


def refresh_numbers(conn):
    """Recomputes value_num of all stored statistic values by the current rules
    (corrects old data after a rule change in to_number). Played time (stat_id < 0)
    is left alone. Returns the number of corrected values."""
    changed = 0
    rows = conn.execute("SELECT scan_id,stat_id,value_text,value_num FROM stat_values WHERE stat_id >= 0").fetchall()
    for scan_id, stat_id, text, num in rows:
        new = to_number(text)
        if new != num:
            conn.execute("UPDATE stat_values SET value_num=? WHERE scan_id=? AND stat_id=?",
                         (new, scan_id, stat_id))
            changed += 1
    conn.commit()
    return changed


# The addon keeps only a limited number of the latest scans per character (one in a file of version 3, a ring of
# them since version 4), so a scan made between two imports can be gone for good. Which ones were lost cannot be
# known; from this many days between the previous scan in the database and the oldest scan in the file that is newer
# the import says so. A file that reaches back to the previous scan (or beyond) proves nothing is missing.
GAP_NOTE_DAYS = 2
SCAN_TIME_FORMAT = "%Y-%m-%d %H:%M:%S"


def last_scan_times(conn):
    """{char_key: time of the newest scan in the database}. Read before the import."""
    return dict(conn.execute("SELECT char_key, MAX(scanned_at) FROM scans GROUP BY char_key"))


def _scan_time(text):
    try:
        return datetime.strptime(str(text), SCAN_TIME_FORMAT)
    except ValueError:
        return None


def _file_scan_times(db):
    """{char key: [time of every scan of the file, oldest first]}: the newest one of `chars` and the older ones of
    `history`. What is not a scan with a readable time is left out (import_data reports it)."""
    chars = db.get("chars") if isinstance(db, dict) else None
    if not isinstance(chars, dict):
        return {}
    history = db.get("history")
    found = {}
    for key, c in chars.items():
        entries = [c] + (_sequence((history or {}).get(key)) or [] if isinstance(history, dict) else [])
        times = sorted(at for at in (_scan_time(e.get("scannedAt")) for e in entries if isinstance(e, dict)) if at)
        if times:
            found[key] = times
    return found


def import_notes(db, before, new, now=None):
    """Lines about the age of the data after an import: how old the newest scan is when nothing new
    came, or that scans may be missing when days lie between the previous scan of a character in the
    database (`before`, from last_scan_times) and the oldest scan of the file that is newer. A file that reaches
    back to the previous scan or beyond has nothing missing in between. Anything odd in the data is
    left to import_data to report: no note then."""
    times = _file_scan_times(db)
    if not times:
        return []
    if new == 0:
        newest = max(at[-1] for at in times.values())
        days = max(0, ((now or datetime.now()) - newest).days)
        return [t("parse_note_no_new", at=newest.strftime(SCAN_TIME_FORMAT), days=days)]
    worst = None
    for key, scans in times.items():
        previous = _scan_time(before.get(key))
        if not previous or scans[0] <= previous:
            continue
        days = (scans[0] - previous).days
        if worst is None or days > worst[0]:
            worst = (days, key, scans[0])
    if worst and worst[0] >= GAP_NOTE_DAYS:
        return [t("parse_note_gap", days=worst[0], key=worst[1], at=worst[2].strftime(SCAN_TIME_FORMAT))]
    return []


# ---------------------------------------------------------------------- HTML
def derived_payload(stats, chars, lang):
    """Rates per played hour (stat_derive) with the display texts of `lang` filled in:
    "label" per role, "why" next to every "reason"."""
    derived = stat_derive.compute(stats, [c["key"] for c in chars])
    for role in derived["roles"]:
        role["label"] = i18n.raw(role.pop("label_key"), lang)
        for res in (*role["chars"].values(), role["total"]):
            if "reason" in res:
                res["why"] = i18n.raw(stat_derive.REASON_KEYS[res["reason"]], lang)
    return derived


REP_PAYLOAD_NUMBERS = ("reaction", "standing", "lo", "hi", "level", "max_level", "renown", "earned", "need", "max_renown")
REP_PAYLOAD_PARAGON = (("value", "p_value"), ("threshold", "p_threshold"), ("quest", "p_quest"), ("pending", "p_pending"))


def rep_payload(conn, scan_to_char):
    """The reputation list of the newest scan of every character that has one, for the stats page:
    {"defs": {faction id: name}, "chars": {char key: [entry, ...]}} with the entries in the order of the game, or None
    when no character has a list. An entry carries only what is set: "id", "hdr"/"child"/"aw" (1), "kind", the numbers of
    its kind and "par" (paragon). A character whose newest scan has no list is not in "chars": an older scan is never
    used in its place (the page says "no value")."""
    columns = ", ".join(REP_PAYLOAD_NUMBERS + tuple(column for _, column in REP_PAYLOAD_PARAGON))
    chars = {}
    for row in conn.execute("SELECT scan_id, faction_id, is_header, is_child, account_wide, kind, " + columns
                            + " FROM scan_reputation ORDER BY scan_id, ord"):
        key = scan_to_char.get(row[0])
        if key is None:
            continue
        entry = {"id": row[1]}
        entry.update({name: 1 for name, flag in zip(("hdr", "child", "aw"), row[2:5]) if flag})
        if row[5]:
            entry["kind"] = row[5]
        values = dict(zip(REP_PAYLOAD_NUMBERS + tuple(name for name, _ in REP_PAYLOAD_PARAGON), row[6:]))
        entry.update({name: values[name] for name in REP_PAYLOAD_NUMBERS if values[name] is not None})
        par = {name: values[name] for name, _ in REP_PAYLOAD_PARAGON if values[name] is not None}
        if par:
            entry["par"] = par
        chars.setdefault(key, []).append(entry)
    if not chars:
        return None
    used = {entry["id"] for entries in chars.values() for entry in entries}
    defs = {faction: name for faction, name in conn.execute("SELECT faction_id, name FROM rep_defs") if faction in used}
    return {"defs": defs, "chars": chars}


def build_payload(conn, lang=None, history=None):
    """The data of the stats page. history: the links to the history pages (update_history_pages),
    left out of the payload when there are none."""
    lang = lang or i18n.get_language()
    scans = conn.execute("""
        SELECT s.scan_id, s.char_key, s.scanned_at, s.class, s.level, s.faction,
               s.class_file, s.race, s.race_file
        FROM scans s
        WHERE s.scan_id = (SELECT scan_id FROM scans WHERE char_key = s.char_key
                           ORDER BY scanned_at DESC, scan_id DESC LIMIT 1)
        ORDER BY s.char_key""").fetchall()
    chars = [{"key": r[1], "scanned_at": r[2], "class": r[3], "level": r[4], "faction": r[5],
              "class_file": r[6], "race": r[7], "race_file": r[8]}
             for r in scans]
    scan_to_char = {r[0]: r[1] for r in scans}

    defs = {r[0]: {"id": r[0], "name": r[1], "cat": r[2], "v": {}}
            for r in conn.execute("SELECT stat_id,name,category FROM stat_defs")}
    for sid, (name, cat) in played_labels().items():
        if sid in defs:
            defs[sid]["name"], defs[sid]["cat"] = name, cat
    for scan_id, stat_id, text, num in conn.execute(
            "SELECT scan_id,stat_id,value_text,value_num FROM stat_values"):
        if scan_id in scan_to_char and stat_id in defs:
            if stat_id < 0 and num is not None:   # played time: text from the seconds, in the output language
                text = fmt_duration(num)
            defs[stat_id]["v"][scan_to_char[scan_id]] = [text, num]

    payload = {"generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
               "lang": lang,
               "ui": i18n.html_strings(lang),
               "names": {"class": i18n.names("class_", lang), "race": i18n.names("race_", lang),
                         "standing": i18n.names("standing_", lang)},
               "app": {"version": app_info.APP_VERSION, "copyright": app_info.COPYRIGHT,
                       "license": app_info.LICENSE_NAME, "site": app_info.SITE_URL},
               "chars": chars,
               "stats": sorted(defs.values(), key=lambda d: (d["cat"], d["name"])),
               "derived": derived_payload(list(defs.values()), chars, lang)}
    rep = rep_payload(conn, scan_to_char)
    if rep:
        payload["rep"] = rep
    if history:
        payload["history"] = history
    return payload


def write_html(payload, out_path):
    tpl_path = paths.resource_dir() / "template.html"
    if not tpl_path.exists():
        sys.exit(t("parse_err_template_missing", path=tpl_path))
    tpl = tpl_path.read_text(encoding="utf-8")
    marker = "/*__DATA__*/null"
    if marker not in tpl:
        sys.exit(t("parse_err_marker_missing"))
    data = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(tpl.replace(marker, data), encoding="utf-8")


# ------------------------------------------------------------- item icons
ICON_CHUNK = 500                 # ids per query (SQLite limits the number of parameters)


def _chars_with_icons(conn, icon_ids):
    """The characters that wore an item with one of these icon ids in any stored scan."""
    ids, chars = sorted(icon_ids), set()
    for start in range(0, len(ids), ICON_CHUNK):
        part = ids[start:start + ICON_CHUNK]
        marks = ",".join("?" * len(part))
        chars.update(r[0] for r in conn.execute(
            f"SELECT DISTINCT s.char_key FROM scan_gear g JOIN scans s ON s.scan_id = g.scan_id "
            f"WHERE g.icon_id IN ({marks})", part))
    return chars


def update_icons(conn, icons_dir, game_dir, product, extract=None):
    """Reads the item icons of the stored equipment from the game files (wow_icons.extract: only those the
    folder does not have yet) and returns (the characters whose icons are new, lines to print). Those characters
    get their history page written again even without a new scan. A failure here never stops the import: the
    icons are an extra, it becomes a warning line and the pages keep their slot symbols. `extract` is for tests."""
    import wow_icons             # late: it loads ctypes and wow_install only when icons are wanted
    try:
        ids = [r[0] for r in conn.execute("SELECT DISTINCT icon_id FROM scan_gear WHERE icon_id IS NOT NULL")]
        run = (extract or wow_icons.extract)(ids, icons_dir, game_dir, product)
        chars = _chars_with_icons(conn, run.written) if run.written else set()
    except Exception as exc:     # a bug or an odd installation must not cost the import
        return set(), [t("parse_warn_icons", error=f"{type(exc).__name__}: {exc}")]
    lines = []
    if run.written:
        lines.append(t("parse_out_icons", count=len(run.written), path=icons_dir))
    if run.unreadable:
        lines.append(t("parse_note_icons_missing", count=len(run.unreadable)))
    if run.error:
        lines.append(t("parse_warn_icons", error=run.error))
    return chars, lines


# ------------------------------------------------------------- history pages
def update_history_pages(conn, history_dir, html_path, changed, icons_dir=None):
    """Brings the history pages of the characters up to date (stat_history.write_pages) and returns
    (links for the stats page or None, lines to print). A failure here never stops the import or the
    stats page: it becomes a warning line, and the page then links only the pages that exist.
    `icons_dir`: the folder whose item icons the pages embed (None = pages without icons)."""
    import stat_history          # late: stat_history imports this module
    folder, page = Path(history_dir), Path(html_path)
    try:
        rel = Path(os.path.relpath(folder, page.parent))
        back = quote(Path(os.path.relpath(page, folder)).as_posix())
    except ValueError:           # another drive: there is no relative link
        rel = back = None
    try:
        result = stat_history.write_pages(conn, folder, changed, back, icons_dir)
    except Exception as exc:     # not worth losing the import for: the pages are an extra
        return None, [t("parse_warn_history", error=f"{type(exc).__name__}: {exc}")]
    lines = []
    if result["written"]:
        lines.append(t("parse_out_history", count=len(result["written"]), path=folder))
    for key, error in result["failed"]:
        lines.append(t("parse_warn_history", error=error) if key is None
                     else t("parse_warn_history_char", key=key, error=error))
    if rel is None or not result["links"]:
        return None, lines
    links = {key: {"href": quote((rel / item["file"]).as_posix()), "scans": item["scans"]}
             for key, item in result["links"].items()}
    return {"dir": rel.as_posix(), "links": links}, lines


# ---------------------------------------------------------------------- Main
def find_input(arg):
    if arg:
        p = Path(arg)
        if not p.is_file():
            sys.exit(t("parse_err_file_missing", path=p))
        return p
    found = sorted(DEFAULT_WTF.glob("*/SavedVariables/StatTracker.lua")) if DEFAULT_WTF.exists() else []
    if len(found) == 1:
        return found[0]
    if not found:
        sys.exit(t("parse_err_default_path"))
    sys.exit(t("parse_err_multi_accounts", paths="\n  ".join(map(str, found))))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--input", help="path to StatTracker.lua (SavedVariables)")
    ap.add_argument("--db", default=str(paths.data_dir() / "wow_stats.db"))
    ap.add_argument("--output", default=str(paths.data_dir() / "stats.html"))
    ap.add_argument("--history-dir", help="folder for the history pages of the characters (no pages if not given)")
    ap.add_argument("--icons-dir", help="folder with the item icons the history pages show (no icons if not given; "
                                        "only used together with --history-dir)")
    ap.add_argument("--game-dir", help="the WoW folder (with .build.info): with --product, --icons-dir and --history-dir "
                                       "the import also reads the item icons it lacks from the game files")
    ap.add_argument("--product", help="the product of the game version in .build.info, e.g. wow (see --game-dir)")
    a = ap.parse_args(argv)

    src = find_input(a.input)
    try:
        parsed = LuaReader(src.read_text(encoding="utf-8")).parse_file()
    except LuaError as e:
        sys.exit(t("parse_err_read", path=src, error=e))
    if "StatTrackerDB" not in parsed:
        sys.exit(t("parse_err_no_db_var"))
    check_data_version(parsed["StatTrackerDB"], src)

    conn = init_db(a.db)
    try:
        before = last_scan_times(conn)
        new, skipped, changed = import_data(conn, parsed["StatTrackerDB"])
        fixed = refresh_numbers(conn)
        icon_lines = []
        if a.history_dir and a.icons_dir and a.game_dir and a.product:
            icon_chars, icon_lines = update_icons(conn, a.icons_dir, a.game_dir, a.product)
            changed = set(changed) | icon_chars
        history, history_lines = (update_history_pages(conn, a.history_dir, a.output, changed, a.icons_dir)
                                  if a.history_dir else (None, []))
        payload = build_payload(conn, history=history)
    finally:
        conn.close()
    write_html(payload, Path(a.output))

    print(t("parse_out_source", path=src))
    print(t("parse_out_scans", new=new, skipped=skipped))
    if fixed:
        print(t("parse_out_numbers", count=fixed))
    print(t("parse_out_db", path=a.db))
    print(t("parse_out_html", path=a.output, chars=len(payload["chars"]), stats=len(payload["stats"])))
    for line in icon_lines:
        print(line)
    for line in history_lines:
        print(line)
    for line in import_notes(parsed["StatTrackerDB"], before, new):
        print(line)


if __name__ == "__main__":
    main()
