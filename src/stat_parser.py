#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)
# stat_parser.py
# StatTracker parser.
#
# Reads WTF/Account/<ACCOUNT>/SavedVariables/StatTracker.lua, stores every scan in
# a SQLite database (with history) and builds a self-contained stats page from it
# (data embedded, no web server needed).
#
# Usage:
#     python stat_parser.py --input PATH\StatTracker.lua [--db FILE] [--output FILE]
# No external dependencies.

import argparse
import json
import re
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

import i18n
import paths
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
def init_db(path):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS scans (
            scan_id    INTEGER PRIMARY KEY AUTOINCREMENT,
            char_key   TEXT NOT NULL,
            scanned_at TEXT NOT NULL,
            class      TEXT,
            level      INTEGER,
            faction    TEXT,
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
    """)
    return conn


def import_data(conn, db):
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
    for key, c in chars.items():
        stats = c.get("stats")
        if not isinstance(stats, dict) or not stats or "scannedAt" not in c:
            sys.exit(t("parse_err_incomplete_char", key=key))
        cur = conn.execute(
            "INSERT OR IGNORE INTO scans(char_key,scanned_at,class,level,faction) VALUES(?,?,?,?,?)",
            (key, c["scannedAt"], c.get("class"), c.get("level"), c.get("faction")))
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
    conn.commit()
    return new, skipped


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
def build_payload(conn, lang=None):
    lang = lang or i18n.get_language()
    scans = conn.execute("""
        SELECT s.scan_id, s.char_key, s.scanned_at, s.class, s.level, s.faction
        FROM scans s
        WHERE s.scan_id = (SELECT scan_id FROM scans WHERE char_key = s.char_key
                           ORDER BY scanned_at DESC, scan_id DESC LIMIT 1)
        ORDER BY s.char_key""").fetchall()
    chars = [{"key": r[1], "scanned_at": r[2], "class": r[3], "level": r[4], "faction": r[5]}
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

    return {"generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "lang": lang,
            "ui": i18n.html_strings(lang),
            "chars": chars,
            "stats": sorted(defs.values(), key=lambda d: (d["cat"], d["name"]))}


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
    a = ap.parse_args(argv)

    src = find_input(a.input)
    try:
        parsed = LuaReader(src.read_text(encoding="utf-8")).parse_file()
    except LuaError as e:
        sys.exit(t("parse_err_read", path=src, error=e))
    if "StatTrackerDB" not in parsed:
        sys.exit(t("parse_err_no_db_var"))

    conn = init_db(a.db)
    try:
        new, skipped = import_data(conn, parsed["StatTrackerDB"])
        fixed = refresh_numbers(conn)
        payload = build_payload(conn)
    finally:
        conn.close()
    write_html(payload, Path(a.output))

    print(t("parse_out_source", path=src))
    print(t("parse_out_scans", new=new, skipped=skipped))
    if fixed:
        print(t("parse_out_numbers", count=fixed))
    print(t("parse_out_db", path=a.db))
    print(t("parse_out_html", path=a.output, chars=len(payload["chars"]), stats=len(payload["stats"])))


if __name__ == "__main__":
    main()
