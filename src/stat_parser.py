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
# up to date (stat_history, imported late in update_history_pages) and links them from the page.
#
# Usage:
#     python stat_parser.py --input PATH\StatTracker.lua [--db FILE] [--output FILE] [--history-dir DIR]
# No external dependencies.

import argparse
import json
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
# (scans gained class_file, race, race_file). Changing the layout means a new entry in
# MIGRATIONS and a higher SCHEMA_VERSION; an old step is never edited.
# A database newer than SCHEMA_VERSION is refused untouched (fail-closed).
SCHEMA_VERSION = 2


def _migrate_0_to_1(conn):
    """Schema 0 has the same layout as schema 1: only the number is set (by init_db)."""


def _migrate_1_to_2(conn):
    """Schema 2 adds the stable class name and the race to every scan. Scans taken before stay
    NULL: they are never filled in from a later scan, because a race can change."""
    for column in ("class_file", "race", "race_file"):
        conn.execute(f"ALTER TABLE scans ADD COLUMN {column} TEXT")


MIGRATIONS = {1: _migrate_0_to_1, 2: _migrate_1_to_2}      # target version -> step from the version before

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
            UNIQUE (char_key, scanned_at)
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
DATA_VERSION = 3


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


def import_data(conn, db):
    """Stores the scans of the file. Returns (new, skipped, changed): the number of new scans, the
    number already in the database, and the keys of the characters that got a new scan."""
    meta = db.get("meta")
    chars = db.get("chars")
    if not isinstance(meta, dict) or not isinstance(chars, dict) or not chars:
        sys.exit(t("parse_err_no_chars"))

    for sid, m in meta.items():
        conn.execute("INSERT INTO stat_defs(stat_id,name,category) VALUES(?,?,?) "
                     "ON CONFLICT(stat_id) DO UPDATE SET name=excluded.name, category=excluded.category",
                     (int(sid), str(m.get("name", "")), str(m.get("cat", ""))))

    for sid, (name, cat) in played_labels().items():
        conn.execute("INSERT INTO stat_defs(stat_id,name,category) VALUES(?,?,?) "
                     "ON CONFLICT(stat_id) DO UPDATE SET name=excluded.name, category=excluded.category",
                     (sid, name, cat))

    new = skipped = 0
    changed = []
    for key, c in chars.items():
        stats = c.get("stats")
        if not isinstance(stats, dict) or not stats or "scannedAt" not in c:
            sys.exit(t("parse_err_incomplete_char", key=key))
        cur = conn.execute(
            "INSERT OR IGNORE INTO scans(char_key,scanned_at,class,level,faction,class_file,race,race_file) "
            "VALUES(?,?,?,?,?,?,?,?)",
            (key, c["scannedAt"], c.get("class"), c.get("level"), c.get("faction"),
             _name_or_none(c.get("classFile")), _name_or_none(c.get("race")), _name_or_none(c.get("raceFile"))))
        if cur.rowcount == 0:
            skipped += 1
            continue
        scan_id = cur.lastrowid
        conn.executemany(
            "INSERT INTO stat_values(scan_id,stat_id,value_text,value_num) VALUES(?,?,?,?)",
            [(scan_id, int(sid), clean_text(str(v)), to_number(str(v))) for sid, v in stats.items()])

        if any(field not in c for _sid, field, _key in PLAYED_STATS):
            print(t("parse_warn_no_played", key=key, at=c["scannedAt"]))
        for sid, field, _key in PLAYED_STATS:
            if field not in c:
                continue
            sec = c[field]
            if isinstance(sec, bool) or not isinstance(sec, (int, float)) or sec < 0:
                sys.exit(t("parse_err_played_invalid", key=key, field=field, value=sec))
            conn.execute("INSERT INTO stat_values(scan_id,stat_id,value_text,value_num) VALUES(?,?,?,?)",
                         (scan_id, sid, fmt_duration(sec), int(sec)))
        new += 1
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
               "names": {"class": i18n.names("class_", lang), "race": i18n.names("race_", lang)},
               "app": {"version": app_info.APP_VERSION, "copyright": app_info.COPYRIGHT,
                       "license": app_info.LICENSE_NAME, "site": app_info.SITE_URL},
               "chars": chars,
               "stats": sorted(defs.values(), key=lambda d: (d["cat"], d["name"])),
               "derived": derived_payload(list(defs.values()), chars, lang)}
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


# ------------------------------------------------------------- history pages
def update_history_pages(conn, history_dir, html_path, changed):
    """Brings the history pages of the characters up to date (stat_history.write_pages) and returns
    (links for the stats page or None, lines to print). A failure here never stops the import or the
    stats page: it becomes a warning line, and the page then links only the pages that exist."""
    import stat_history          # late: stat_history imports this module
    folder, page = Path(history_dir), Path(html_path)
    try:
        rel = Path(os.path.relpath(folder, page.parent))
        back = quote(Path(os.path.relpath(page, folder)).as_posix())
    except ValueError:           # another drive: there is no relative link
        rel = back = None
    try:
        result = stat_history.write_pages(conn, folder, changed, back)
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
        new, skipped, changed = import_data(conn, parsed["StatTrackerDB"])
        fixed = refresh_numbers(conn)
        history, history_lines = (update_history_pages(conn, a.history_dir, a.output, changed)
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
    for line in history_lines:
        print(line)


if __name__ == "__main__":
    main()
