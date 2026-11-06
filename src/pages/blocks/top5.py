#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)
# top5.py
# StatTracker - the "Top 5" tiles at the top of the stats page (place 10): up to five tiles, each with the name of a statistic, one value for it and
# the scope it was combined over ("Gold earned", "12,345 g", "Class: Mage"). The tiles come from the settings of the program (config.top5, handed over in
# the payload as "top5"); the value is calculated by tile_rules from the newest scan of every character, the way the Groups block calculates a statistic added
# by hand. A tile only shows: no state, no action, it does not follow the ticked characters (a block with a selection of its own stands above the
# selection). Left out (empty text) when no tile is set or the page has no characters. `choices` is what the settings of the window offer for a
# tile (the statistics with a number, and the characters / classes / races / factions / realms with their names), read from the same payload. Needs markup, cells,
# tile_rules, group_rules.

from pages.blocks import cells
from pages.blocks.markup import esc, ui
from rules import group_rules, tile_rules


def _scope(payload, tile, found) -> str:
    """Who the value is about: "All characters", the character, or "Class: Mage" (the text of the grouping and of the group)."""
    by, value = tile.get("by"), tile.get("value") or ""
    if by == "all":
        return ui(payload, "top5_all")
    if by == "char":
        return value
    if by in group_rules.GROUP_BY:
        # a group without any character (a class that nobody plays any more) still has a name; the stand-in member only keeps group_label from failing
        label = group_rules.group_label(by, value or None, found or [{}], payload.get("names") or {}, cells.factions(payload), ui(payload, "groups_unknown"))
        return f"{cells.by_labels(payload)[by]}: {label}"
    return f"{by}: {value}"


def _tile(payload, stats, chars, tile) -> str:
    stat = stats.get(tile.get("stat"))
    found = tile_rules.members(chars, tile.get("by"), tile.get("value"))
    text, small = cells.cell_text(payload, tile_rules.cell(stats, tile, chars))
    agg = "" if tile.get("by") == "char" else cells.agg_labels(payload).get(tile.get("agg"), "")        # one character: the function changes nothing
    sub = " · ".join(part for part in ((stat or {}).get("cat"), agg) if part)
    name = stat["name"] if stat else f"#{tile.get('stat')}"
    sub_html = f'<span class="small">{esc(sub)}</span>' if sub else ""
    small_html = f'<div class="small">{esc(small)}</div>' if small else ""
    return ('<div class="tile">'
            f'<div class="tname">{esc(name)}{sub_html}</div>'
            f'<div class="tval">{esc(text)}</div>'
            f'<div class="tscope">{esc(_scope(payload, tile, found))}</div>'
            f'{small_html}'
            '</div>')


def choices(payload) -> dict:
    """What a tile may name, from the payload of a page: {"stats": [(id, "Name (Category)")] (only statistics some character has a number for, the played
    times included), "parts": {id: (name, category)} for those, "values": {"char": [(key, key)], "class" / "race" / "faction" / "realm": [(value, name)]}}.
    The value "" is the group "unknown"."""
    chars = payload.get("chars") or []

    def has_number(stat):
        return any(group_rules.is_number((stat["v"].get(c["key"]) or [None, None])[1]) for c in chars)

    offered = [s for s in payload.get("stats") or [] if has_number(s)]
    stats = [(s["id"], f'{s["name"]} ({s["cat"]})') for s in offered]
    values = {"char": [(c["key"], c["key"]) for c in chars]}
    for by in group_rules.GROUP_BY:
        groups = group_rules.build_groups(chars, by, payload.get("names") or {}, cells.factions(payload), ui(payload, "groups_unknown"))
        values[by] = [("" if group.key is None else group.key, group.label) for group in groups]
    return {"stats": stats, "parts": {s["id"]: (s["name"], s["cat"]) for s in offered}, "values": values}


def render(payload, view=None, slot=None, **_) -> str:
    tiles = [t for t in payload.get("top5") or [] if isinstance(t, dict)]
    chars = payload.get("chars") or []
    if not tiles or not chars:
        return ""
    stats = {s["id"]: s for s in payload.get("stats") or []}
    return '<div class="tiles" id="top5">' + "".join(_tile(payload, stats, chars, tile) for tile in tiles) + "</div>"
