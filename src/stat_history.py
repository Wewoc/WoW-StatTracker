#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)
# stat_history.py
# StatTracker - the history of one character: every stored scan as one column of values
# per statistic, as plain data for the history page.
#
# Reads the statistics database, never writes it: open_readonly() opens it read-only (no
# init_db, so no backup, no migration, no new file) after stat_parser.check_schema. Needs
# stat_parser (schema check, names of the played-time statistics) and nothing else of the
# project. Raw values as stored (value_num), no rates, no reset detection, no smoothing.

import re
import sqlite3
from pathlib import Path

import stat_parser

# Text of a coin amount ('12g 5s 3c'); the same shape stat_parser.to_number turns into copper.
COIN_TEXT = re.compile(r"(?:\d[\d.,]*\s*[gsc]\s*)+")

RACE_COLUMNS = ("class_file", "race", "race_file")     # scans.* since schema 2


def open_readonly(db_path):
    """Read-only connection to an existing statistics database, schema checked (a database newer
    than this program exits with the usual message). A missing file raises sqlite3.OperationalError
    instead of being created."""
    path = Path(db_path)
    conn = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    try:
        stat_parser.check_schema(conn, path)
    except BaseException:
        conn.close()
        raise
    return conn


def _unit(stat_id, all_coin):
    if stat_id < 0:
        return "seconds"          # played time (stat_parser.PLAYED_STATS), value_num in seconds
    return "gold" if all_coin else "number"      # gold values are copper


def build_history(conn, char_key):
    """The history of one character, or None if the database has no scan of it:
        {"char":  {key, class, level, faction, class_file, race, race_file}   latest scan; the race
                                                                               fields are None before schema 2
         "scans": [scanned_at, ...]                     oldest first, as stored
         "level": [level, ...]                          one per scan
         "stats": [{id, name, cat, unit, v}, ...]}      sorted like the stats page; v has one entry per
                                                        scan: value_num, or None where the scan has no
                                                        number (missing, or text such as '--')
    Only statistics with at least one number for this character are listed. unit is "seconds" for
    played time, "gold" if every number came from a coin text, otherwise "number". Names of the played
    time statistics are in the current language."""
    have = {r[1] for r in conn.execute("PRAGMA table_info(scans)")}
    race = [c for c in RACE_COLUMNS if c in have]
    columns = ", ".join(["scan_id", "scanned_at", "class", "level", "faction", *race])
    scans = conn.execute(f"SELECT {columns} FROM scans WHERE char_key=? ORDER BY scanned_at, scan_id",
                         (char_key,)).fetchall()
    if not scans:
        return None
    position = {row[0]: i for i, row in enumerate(scans)}
    latest = dict(zip(["scan_id", "scanned_at", "class", "level", "faction", *race], scans[-1]))

    defs = {r[0]: (r[1], r[2]) for r in conn.execute("SELECT stat_id,name,category FROM stat_defs")}
    for sid, label in stat_parser.played_labels().items():
        if sid in defs:
            defs[sid] = label

    values, all_coin = {}, {}
    for scan_id, stat_id, text, num in conn.execute(
            "SELECT v.scan_id, v.stat_id, v.value_text, v.value_num FROM stat_values v "
            "JOIN scans s ON s.scan_id = v.scan_id WHERE s.char_key=?", (char_key,)):
        if num is None or stat_id not in defs:
            continue
        values.setdefault(stat_id, [None] * len(scans))[position[scan_id]] = num
        coin = bool(COIN_TEXT.fullmatch(stat_parser.clean_text(text)))
        all_coin[stat_id] = all_coin.get(stat_id, True) and coin

    stats = [{"id": sid, "name": defs[sid][0], "cat": defs[sid][1], "unit": _unit(sid, all_coin[sid]), "v": v}
             for sid, v in values.items()]
    stats.sort(key=lambda s: (s["cat"], s["name"]))
    return {"char": {"key": char_key, "class": latest["class"], "level": latest["level"],
                     "faction": latest["faction"], **{c: latest.get(c) for c in RACE_COLUMNS}},
            "scans": [row[1] for row in scans],
            "level": [row[3] for row in scans],
            "stats": stats}
