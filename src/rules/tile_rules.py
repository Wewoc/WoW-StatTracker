#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)
# tile_rules.py
# StatTracker - the rules of the "Top 5" tiles at the top of the stats page. A tile is {"stat": statistic id, "agg": "sum" | "avg" | "max",
# "by": "all" | "class" | "race" | "faction" | "realm" | "char", "value": the class or race file name, the faction, the realm or the character, "" for
# "all"}: one statistic, combined over the characters of one scope. The value comes from the newest scan of every character (the shape of
# page_payload.build_payload()["stats"]); the calculation is the one of a statistic added by hand to the Groups block (group_rules.extra_figure:
# only characters with a number count, "n of m", no value instead of an invented number), so both blocks agree. The played times (negative ids,
# seconds) are shown in hours. For the group "unknown" (a character without class or race file name, or without faction) the value is "".
# The characters of a tile come from ONE place, `members`: a later filter ("hide", "ignore", see ROADMAP.md) is added there and no tile changes.
# Pure calculation, no I/O. Needs group_rules.

from rules import group_rules

SCOPES = ("all", "class", "race", "faction", "realm", "char")
AGGREGATES = group_rules.AGGREGATES


def members(chars: list, by, value) -> list:
    """The characters (of `chars`, in their order) that a scope names; none for a scope this program does not know."""
    value = value or ""
    if by == "all":
        return list(chars)
    if by == "char":
        return [c for c in chars if c["key"] == value]
    if by in group_rules.GROUP_BY:
        return [c for c in chars if (group_rules.group_key(c, by) or "") == value]
    return []


def cell(stats_by_id: dict, tile: dict, chars: list) -> group_rules.Cell:
    """The value of a tile as a Cell (see group_rules): no value for a tile whose function or scope is not known, or a statistic this page
    does not have; an hour value for a played time."""
    by, agg, stat_id = tile.get("by"), tile.get("agg"), tile.get("stat")
    if by not in SCOPES or agg not in AGGREGATES:
        return group_rules.Cell("number")
    stat = stats_by_id.get(stat_id)
    result = group_rules.extra_figure(stat, stat_id, agg).calc(members(chars, by, tile.get("value")))
    if stat is not None and stat["id"] < 0 and result.value is not None:
        return result._replace(kind="hours", value=result.value / 3600)
    return result
