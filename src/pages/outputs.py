#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)
# outputs.py
# StatTracker - the files an import leaves behind besides the database: the stats page (write_html, which first fills
# the numbered places of the page with their blocks, pages/blocks/layout.py; write_snapshot writes the page as the window shows it now,
# for the browser), the item icons
# (update_icons, read through wow_icons) and the history pages (update_history_pages, written by stat_history).
# The icons and the history pages are extras: a failure there becomes a warning line and never stops the import
# or the stats page. build_outputs makes all of them in their order (icons, history pages, stats page) for a connection;
# rebuild_outputs does the same from the database alone, without the SavedVariables file and without writing to the
# database. Needs page_payload, layout, paths, i18n, stat_history and wow_icons. Moved out of stat_parser.py; rules unchanged.

import json
import os
import sys
from pathlib import Path
from urllib.parse import quote

from core import paths
from core.i18n import t
from game import wow_icons
from pages import page_payload
from pages import stat_history
from pages.blocks import layout


def write_html(payload, out_path, view=None):
    """Writes the stats page: the blocks filled as `view` says (a new View, everything ticked and nothing typed, when not given), then the data."""
    tpl_path = paths.resource_dir() / "template.html"
    if not tpl_path.exists():
        sys.exit(t("parse_err_template_missing", path=tpl_path))
    tpl = tpl_path.read_text(encoding="utf-8")
    marker = "/*__DATA__*/null"
    if marker not in tpl:
        sys.exit(t("parse_err_marker_missing"))
    tpl = layout.fill(tpl, payload, view)   # the blocks written by Python (pages/blocks), before the data goes in
    data = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(tpl.replace(marker, data), encoding="utf-8")


def write_snapshot(view, out_path, when):
    """Writes the stats page as the window shows it now (the ticked characters, the state and the controls of the blocks in `view`): the same blocks, in
    a file that works without the program. The page does not talk to Python there, so its controls are locked (the script of the page does that when it
    finds no bridge) and a line in the head says it is a snapshot (payload field `snapshot`, `when` is the time as text). The View given is not changed."""
    write_html(dict(view.payload, snapshot={"when": when}), out_path, view.snapshot())


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


def build_outputs(conn, html_path, changed, history_dir=None, icons_dir=None, game_dir=None, product=None, top5=None):
    """Everything an import leaves besides the database, in its order: the item icons the folder lacks (only with a
    history folder, an icons folder, the game folder and the product), the history pages (of the characters in `changed`,
    those without a page and, after a program update, all), the stats page. The connection is only read (it may be
    read-only). `top5`: the tiles of the Top 5 block (config.top5). Returns (payload, lines to print): the warnings and notes of the icons
    and the history pages."""
    icon_lines = []
    if history_dir and icons_dir and game_dir and product:
        icon_chars, icon_lines = update_icons(conn, icons_dir, game_dir, product)
        changed = set(changed) | icon_chars
    history, history_lines = (update_history_pages(conn, history_dir, html_path, changed, icons_dir)
                              if history_dir else (None, []))
    payload = page_payload.build_payload(conn, history=history, top5=top5)
    write_html(payload, Path(html_path))
    return payload, icon_lines + history_lines


def rebuild_outputs(db_path, html_path, history_dir=None, icons_dir=None, top5=None):
    """Writes the stats page (and the pages that are missing or from another program version) again from the database
    alone: no SavedVariables file, no import, no copy, no migration, nothing written to the database. A database newer
    than this program exits with the usual message; a missing file raises sqlite3.OperationalError. The game files
    are not read (icons already in the folder are shown). `top5`: the tiles of the Top 5 block. Returns (payload, lines to print)."""
    conn = stat_history.open_readonly(db_path)
    try:
        return build_outputs(conn, html_path, set(), history_dir, icons_dir, top5=top5)
    finally:
        conn.close()
