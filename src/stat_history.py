#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)
# stat_history.py
# StatTracker - the history of one character: every stored scan as one column of values
# per statistic, as plain data, and the stand-alone history page made from it.
#
# Reads the statistics database, never writes it: open_readonly() opens it read-only (no
# init_db, so no backup, no migration, no new file) after stat_parser.check_schema. Raw values
# as stored (value_num), no rates, no reset detection, no smoothing.
# write_page() puts the data and the pinned plotly.js (plotly_asset) into history.html and
# writes that one file; write_pages() decides which characters need a new page (a new scan, no
# page yet, or pages from another program version). Both are the only writers of the history pages.
# Needs stat_parser (schema check, names of the played-time statistics), plotly_asset, i18n,
# paths and app_info. stat_parser imports this module late, inside main(), because it needs
# stat_parser itself.

import hashlib
import json
import os
import re
import sqlite3
from datetime import datetime
from pathlib import Path

import app_info
import i18n
import paths
import plotly_asset
import stat_parser

# Text of a coin amount ('12g 5s 3c'); the same shape stat_parser.to_number turns into copper.
COIN_TEXT = re.compile(r"(?:\d[\d.,]*\s*[gsc]\s*)+")

RACE_COLUMNS = ("class_file", "race", "race_file")     # scans.* since schema 2

PAGE_TEMPLATE = "history.html"                  # bundled next to template.html
DATA_MARKER = "/*__DATA__*/null"                # replaced by the page data (JSON)
PLOTLY_MARKER = "<!--__PLOTLY__-->"             # replaced by the inline plotly.js <script>

PAGE_PREFIX = "history-"                        # file names: history-<name>-<hash>.html
NAME_PART_MAX = 40
GENERATOR_FILE = ".generator"                   # in the pages folder: the program version that wrote the pages
MIN_SCANS = 2                                   # a character needs this many scans to get a page


class HistoryPageError(Exception):
    """The history page cannot be made: template missing or without its markers, file not writable.
    (A missing or wrong plotly.js raises plotly_asset.PlotlyAssetError.)"""


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


def build_page_payload(conn, char_key, back=None):
    """build_history() plus what the page needs besides the numbers: texts in the current language,
    the program data for the footer, the plotly.js version, and `back`, the link to the stats page
    (relative, already URL-quoted; None = no link). None if the database has no scan of the
    character."""
    history = build_history(conn, char_key)
    if history is None:
        return None
    lang = i18n.get_language()
    return {**history,
            "generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "lang": lang,
            "ui": i18n.html_strings(lang),
            "app": {"version": app_info.APP_VERSION, "copyright": app_info.COPYRIGHT,
                    "license": app_info.LICENSE_NAME, "site": app_info.SITE_URL},
            "plotly": plotly_asset.VERSION,
            "back": back}


def write_page(payload, out_path):
    """Writes the history page: history.html with the payload and the verified plotly.js inside.
    All or nothing - the file is written next to its target and renamed. Raises HistoryPageError, or
    PlotlyAssetError if plotly.js is missing or does not match its pin; nothing is written then."""
    tpl_path = paths.resource_dir() / PAGE_TEMPLATE
    try:
        tpl = tpl_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise HistoryPageError(f"History page template not readable: {tpl_path} ({exc})") from exc
    for marker in (DATA_MARKER, PLOTLY_MARKER):
        if tpl.count(marker) != 1:
            raise HistoryPageError(f"Marker {marker} must occur exactly once in {tpl_path}")
    script = plotly_asset.script_tag()
    # '<' as <: valid JSON, and nothing in the data can end the script or open a comment
    data = json.dumps(payload, ensure_ascii=False).replace("<", r"\u003c")
    page = tpl.replace(DATA_MARKER, data).replace(PLOTLY_MARKER, script)

    out_path = Path(out_path)
    part = out_path.with_name(out_path.name + ".part")
    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        part.write_bytes(page.encode("utf-8"))      # bytes: the embedded plotly.js keeps its line endings
        os.replace(part, out_path)
    except OSError as exc:
        part.unlink(missing_ok=True)
        raise HistoryPageError(f"History page not writable: {out_path} ({exc})") from exc


def history_counts(conn):
    """{char_key: number of stored scans} for every character in the database."""
    return dict(conn.execute("SELECT char_key, COUNT(*) FROM scans GROUP BY char_key"))


def page_name(char_key):
    """File name of the history page of a character: its name made safe for a file system, plus a
    short hash of the exact key, so that names which differ only in case, an apostrophe or an umlaut
    can never meet in one file."""
    part = "".join(ch if ch.isalnum() else "_" for ch in char_key)[:NAME_PART_MAX]
    return f"{PAGE_PREFIX}{part}-{hashlib.sha256(char_key.encode('utf-8')).hexdigest()[:8]}.html"


def _generator_version(folder):
    try:
        return (Path(folder) / GENERATOR_FILE).read_text(encoding="utf-8").strip()
    except OSError:
        return None


def write_pages(conn, folder, changed, back_href=None):
    """Brings the history pages in `folder` up to date. A character with at least MIN_SCANS scans
    gets a page if it is in `changed` (a scan was imported just now), if its page is missing, or if
    the pages were written by another program version (then all are written again). Nothing is
    written for the rest, so an import that brings nothing new leaves every file alone.

    Returns {"links": {char_key: {"file", "scans"}}   the pages that exist now (an old page stays linked
                                                       if writing the new one failed)
             "written": [char_key, ...],
             "failed": [(char_key or None, message), ...]}   None: all pages (plotly.js is missing or wrong)
    One character failing does not stop the others; a missing plotly.js stops all writing. Only the
    expected errors of one page are caught here (HistoryPageError, OSError, sqlite3.Error); the caller
    decides what a failure means for the import."""
    folder = Path(folder)
    changed = set(changed)
    eligible = {key: n for key, n in history_counts(conn).items() if n >= MIN_SCANS}
    everything = bool(eligible) and _generator_version(folder) != app_info.APP_VERSION
    links, written, failed = {}, [], []
    blocked = False
    for key in sorted(eligible):
        target = folder / page_name(key)
        if not blocked and (everything or key in changed or not target.is_file()):
            try:
                write_page(build_page_payload(conn, key, back_href), target)
                written.append(key)
            except plotly_asset.PlotlyAssetError as exc:
                failed.append((None, str(exc)))
                blocked = True
            except (HistoryPageError, OSError, sqlite3.Error) as exc:
                failed.append((key, str(exc)))
        if target.is_file():
            links[key] = {"file": target.name, "scans": eligible[key]}
    if everything and not failed:
        try:
            (folder / GENERATOR_FILE).write_text(app_info.APP_VERSION, encoding="utf-8")
        except OSError as exc:
            failed.append((None, str(exc)))
    return {"links": links, "written": written, "failed": failed}
