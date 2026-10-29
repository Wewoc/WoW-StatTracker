#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)
"""Spot check: show selected statistics per character, to compare with the game.
Developer tool (not part of the release). Output is German; the default picks
use exact names from the German retail client - for other clients use --search.

Usage (from the repository root):
  python tools/check_stats.py                       # default picks from data/wow_stats.db
  python tools/check_stats.py --random 10           # + 10 random statistics with a value
  python tools/check_stats.py --search Tode --search Gold    # search statistic and category names
  python tools/check_stats.py --char Name           # only characters whose name contains this
  python tools/check_stats.py --db data/wow_stats_<version>.db

Shows per character: display text (as in game), stored number, scan time.
At the end: consistency check of ALL values (text <-> stored number), deviations marked with '!'.
Note: values are from scan time; e.g. gold in game may have changed since.
Read-only, changes nothing.
"""
import argparse
import random
import re
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import paths  # noqa: E402

DEFAULT_PICKS = [  # exact names from the German retail client
    "Gesamte Spielzeit", "Tode insgesamt", "Quests abgeschlossen", "Erhaltenes Gold insgesamt",
    "Durchschnittlich abgeschlossene Quests pro Tag", "Bereiste Flugrouten",
    "Anzahl der Nutzungen des Ruhesteins", "Entzauberte Gegenstände",
]
PLAYED_IDS = (-1, -2)
EMPTY = ("--", "")


def expected_num(text):
    """Independent expectation for the number of a display text (stricter than the parser).
    '0.04' -> 0.04 (1-2 decimals = decimal), '1.234' -> 1234 (3 digits = thousands),
    '12g 5s 3c' -> copper. Otherwise None."""
    t = text.strip()
    if t in EMPTY:
        return None
    m = re.fullmatch(r"(\d+)[.,](\d{1,2})", t)
    if m:
        return float(f"{m.group(1)}.{m.group(2)}")
    if re.fullmatch(r"\d+|\d{1,3}(?:[.,\s  ]\d{3})+", t):
        return int(re.sub(r"\D", "", t))
    if re.fullmatch(r"(?:\d[\d.,]*\s*[gsc]\s*)+", t):
        mult = {"g": 10000, "s": 100, "c": 1}
        return sum(int(re.sub(r"\D", "", n)) * mult[u] for n, u in re.findall(r"(\d[\d.,]*)\s*([gsc])", t))
    return None


def same(a, b):
    if a is None or b is None:
        return a is b
    return abs(float(a) - float(b)) < 1e-9


def load(db_path):
    conn = sqlite3.connect(db_path)
    scans = conn.execute("""
        SELECT s.scan_id, s.char_key, s.scanned_at, s.class, s.level FROM scans s
        WHERE s.scan_id = (SELECT scan_id FROM scans WHERE char_key = s.char_key
                           ORDER BY scanned_at DESC, scan_id DESC LIMIT 1)
        ORDER BY s.char_key""").fetchall()
    defs = {r[0]: (r[1], r[2]) for r in conn.execute("SELECT stat_id,name,category FROM stat_defs")}
    vals = {}
    ids = {s[0]: s[1] for s in scans}
    for scan_id, stat_id, text, num in conn.execute("SELECT scan_id,stat_id,value_text,value_num FROM stat_values"):
        if scan_id in ids:
            vals.setdefault(stat_id, {})[ids[scan_id]] = (text, num)
    conn.close()
    return scans, defs, vals


def main():
    try:
        sys.stdout.reconfigure(errors="replace")
    except AttributeError:
        pass
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default=str(paths.data_dir() / "wow_stats.db"))
    ap.add_argument("--search", action="append", default=[], help="search text (repeatable)")
    ap.add_argument("--random", type=int, default=0, metavar="N", help="N random statistics with a value")
    ap.add_argument("--seed", type=int, default=None, help="random seed (reproducible)")
    ap.add_argument("--char", default="", help="filter by character name (substring)")
    ap.add_argument("--limit", type=int, default=12, help="max. hits per search (default 12)")
    a = ap.parse_args()

    if not Path(a.db).is_file():
        sys.exit(f"ERROR: database not found: {a.db}")
    scans, defs, vals = load(a.db)
    if not scans:
        sys.exit("ERROR: no scans in the database.")

    chars = [s for s in scans if a.char.lower() in s[1].lower()]
    if not chars:
        sys.exit(f"ERROR: no character matches '{a.char}'.")
    keys = [c[1] for c in chars]

    print("Characters (newest scan):")
    for _sid, key, at, cls, lvl in chars:
        print(f"  {key:28} {str(cls or ''):14} Level {lvl}   scan {at}")
    print()

    def has_value(sid):
        return any(vals.get(sid, {}).get(k, ("--",))[0] not in EMPTY for k in keys)

    picks = []  # (stat_id, reason)
    by_name = {}
    for sid, (name, _cat) in defs.items():
        by_name.setdefault(name, []).append(sid)

    if not a.search and not a.random:
        for name in DEFAULT_PICKS:
            if name in by_name:
                picks += [(s, "default") for s in by_name[name] if has_value(s)]
            else:
                print(f"(default statistic '{name}' not found - other client language or game?)")
    for term in a.search:
        hits = [s for s, (n, c) in sorted(defs.items(), key=lambda kv: (kv[1][1], kv[1][0]))
                if (term.lower() in n.lower() or term.lower() in c.lower()) and has_value(s)]
        if not hits:
            print(f"(search '{term}': no statistic with a value)")
        for s in hits[:a.limit]:
            picks.append((s, f"search '{term}'"))
        if len(hits) > a.limit:
            print(f"(search '{term}': {len(hits)} hits, {a.limit} shown - raise --limit)")
    if a.random:
        pool = [s for s in defs if s >= 0 and has_value(s)]
        rng = random.Random(a.seed)
        picks += [(s, "random") for s in rng.sample(pool, min(a.random, len(pool)))]

    seen = set()
    for sid, why in picks:
        if sid in seen:
            continue
        seen.add(sid)
        name, cat = defs[sid]
        print(f"[{why}] {cat} > {name}")
        for k in keys:
            text, num = vals.get(sid, {}).get(k, ("(no entry)", None))
            flag = ""
            if sid not in PLAYED_IDS and text not in EMPTY and not text.startswith("("):
                if not same(expected_num(text), num):
                    flag = f"  ! number {num} does not match text (expected {expected_num(text)})"
            print(f"    {k:28} {text:34} number={num}{flag}")
        print()

    # consistency check over all values of the shown characters
    total = bad = 0
    examples = []
    for sid, per in vals.items():
        if sid in PLAYED_IDS:
            continue
        for k in keys:
            if k not in per:
                continue
            text, num = per[k]
            if text in EMPTY:
                continue
            total += 1
            exp = expected_num(text)
            if not same(exp, num):
                bad += 1
                if len(examples) < 12:
                    examples.append((defs.get(sid, ("?", ""))[0], k, text, num, exp))
    print(f"Consistency check: {total} values, {bad} deviations between text and stored number")
    for name, k, text, num, exp in examples:
        print(f"  ! {name} | {k} | text '{text}' | stored {num} | expected {exp}")
    if bad > len(examples):
        print(f"  ... and {bad - len(examples)} more")


if __name__ == "__main__":
    main()
