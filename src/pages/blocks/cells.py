#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)
# cells.py
# StatTracker - what the blocks that show figures of groups of characters (the Groups block and the Top 5 tiles) share: the text of a value
# (`cell_text`: the number in the number format of the page, "n of m characters" when characters had no value, the dash and "no value" when there is
# none), the labels of the groupings, of the functions (sum, average, maximum) and of the factions. A value comes as a `group_rules.Cell`; the
# texts are the html_* texts of the payload ("ui"). Not a block (no place, no render). Needs markup, numfmt.

from pages.blocks.markup import fmt, ui
from rules import numfmt

DASH = "–"                     # what a cell without a value shows


def number(payload, value, digits) -> str:
    """A number in the number format of the language of the page."""
    return numfmt.fixed(value, digits, payload.get("lang") or "en")


def by_labels(payload) -> dict:
    return {"class": ui(payload, "groups_by_class"), "race": ui(payload, "groups_by_race"),
            "faction": ui(payload, "groups_by_faction"), "realm": ui(payload, "groups_by_realm")}


def agg_labels(payload) -> dict:
    return {"sum": ui(payload, "groups_agg_sum"), "avg": ui(payload, "groups_agg_avg"), "max": ui(payload, "groups_agg_max")}


def factions(payload) -> dict:
    return {"Alliance": ui(payload, "faction_Alliance"), "Horde": ui(payload, "faction_Horde"), "Neutral": ui(payload, "faction_Neutral")}


def cell_text(payload, cell):
    """(main text, small text) of a table cell: the value and "n of m" when characters are missing, or the dash and "no value"."""
    if cell.value is None:
        return DASH, ui(payload, "groups_no_value")
    if cell.kind == "count":
        text = number(payload, cell.value, 0)
    elif cell.kind == "level":
        text = number(payload, cell.value, 1)
    elif cell.kind == "hours":
        text = fmt(ui(payload, "groups_hours"), n=number(payload, cell.value, 1))
    elif cell.kind == "rate":
        text = numfmt.rate(cell.value, payload.get("lang") or "en")
    elif cell.kind == "gold":
        text = fmt(ui(payload, "groups_gold"), n=number(payload, cell.value / 10000, 2))
    else:
        text = number(payload, cell.value, 0 if float(cell.value).is_integer() else 2)
    small = fmt(ui(payload, "rates_total_of"), used=cell.used, of=cell.total) if cell.used < cell.total else ""
    return text, small
