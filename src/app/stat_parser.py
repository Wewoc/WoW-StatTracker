#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)
# stat_parser.py
# StatTracker parser: the command line and the order of the steps (main).
#
# Reads WTF/Account/<ACCOUNT>/SavedVariables/StatTracker.lua (lua_reader), stores every scan in a SQLite database
# with history (db_schema opens it and takes the copy first, importer stores the scans) and builds a self-contained
# stats page from it (page_payload makes the data, outputs writes the page; data embedded, no web server needed).
# With --history-dir it also keeps the history pages of the characters up to date (outputs.update_history_pages,
# written by stat_history) and links them from the page; with --icons-dir as well, those pages show the item icons
# that folder holds, and with --game-dir and --product the import first reads the icons of the stored equipment that
# the folder lacks from the game files (outputs.update_icons, read by wow_icons); the characters whose icons are
# new get their page written.
#
# --top5 gives the tiles of the Top 5 block (a JSON list, config.top5; the window hands over its settings); without it the page has no tiles.
#
# Usage:
#     python stat_parser.py --input PATH\StatTracker.lua [--db FILE] [--output FILE] [--history-dir DIR]
#                           [--icons-dir DIR [--game-dir WOW_FOLDER --product wow]] [--top5 JSON]
# No external dependencies.

import argparse
import json
import sys
from pathlib import Path

from core import config, paths
from core.i18n import t
from pages import outputs
from store import db_schema
from store import importer
from store import lua_reader

DEFAULT_WTF = Path(r"C:\Program Files (x86)\World of Warcraft\_retail_\WTF\Account")


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


def read_tiles(text):
    """(the tiles of the Top 5 block from the JSON text of --top5, lines to print): none and no line without the argument; a text that is no
    JSON gives no tiles and a warning (the tiles are an extra: they never stop an import)."""
    if not text:
        return None, []
    try:
        return config.clean_top5(json.loads(text)), []
    except ValueError as exc:
        return None, [t("parse_warn_top5", error=exc)]


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
    ap.add_argument("--top5", help="the tiles of the Top 5 block as a JSON list (config.top5; no tiles if not given)")
    a = ap.parse_args(argv)

    tiles, tile_lines = read_tiles(a.top5)
    src = find_input(a.input)
    try:
        parsed = lua_reader.LuaReader(src.read_text(encoding="utf-8")).parse_file()
    except lua_reader.LuaError as e:
        sys.exit(t("parse_err_read", path=src, error=e))
    if "StatTrackerDB" not in parsed:
        sys.exit(t("parse_err_no_db_var"))
    importer.check_data_version(parsed["StatTrackerDB"], src)

    conn = db_schema.init_db(a.db)
    try:
        before = importer.last_scan_times(conn)
        new, skipped, changed = importer.import_data(conn, parsed["StatTrackerDB"])
        fixed = importer.refresh_numbers(conn)
        payload, lines = outputs.build_outputs(conn, a.output, changed, a.history_dir, a.icons_dir, a.game_dir, a.product, top5=tiles)
    finally:
        conn.close()

    print(t("parse_out_source", path=src))
    print(t("parse_out_scans", new=new, skipped=skipped))
    if fixed:
        print(t("parse_out_numbers", count=fixed))
    print(t("parse_out_db", path=a.db))
    print(t("parse_out_html", path=a.output, chars=len(payload["chars"]), stats=len(payload["stats"])))
    for line in tile_lines + lines:
        print(line)
    for line in importer.import_notes(parsed["StatTrackerDB"], before, new):
        print(line)


if __name__ == "__main__":
    main()
