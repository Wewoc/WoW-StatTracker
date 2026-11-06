#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)
# history_links.py
# StatTracker - the block "Verlaeufe / History" of the stats page: one link per character that has a history page (written
# next to the stats page by stat_history), and a note that says a link is only as good as the folder beside the page. The
# block is left out (empty text) when the payload holds no links. It replaces the script that built the same elements in
# the page (setupHistory): same elements, ids and classes, so the style sheet of the page is unchanged. Needs markup.

from pages.blocks.markup import esc, fmt, ui


def render(payload, view=None, slot=None, **_) -> str:
    """The block as HTML, or "" when no character has a history page. Reads the payload only (a block has no state
    and no action: `view` and `slot` are there because every block is called the same way)."""
    history = payload.get("history") or {}
    links = history.get("links") or {}
    keys = [c["key"] for c in payload.get("chars") or []]
    linked = [key for key in keys if key in links]
    if not linked:
        return ""
    anchors = "".join(
        f'<a class="hlink" href="{esc(links[key]["href"])}">{esc(key)}<span> ({esc(links[key]["scans"])})</span></a>'
        for key in linked)
    missing = len(keys) - len(linked)
    note = fmt(ui(payload, "hist_links_note"), dir=history.get("dir", ""))
    if missing:
        note += " " + fmt(ui(payload, "hist_links_missing"), n=missing)
    return ('<details class="rates" id="history">\n'
            f'  <summary id="historyTitle">{esc(ui(payload, "hist_links_title"))}</summary>\n'
            f'  <div class="gbar" id="historyLinks">{anchors}</div>\n'
            f'  <div class="note" id="historyNote">{esc(note)}</div>\n'
            '</details>')
