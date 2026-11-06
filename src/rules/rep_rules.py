#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)
# rep_rules.py
# StatTracker - the rules of the "Reputation" block of the stats page, moved out of the page script (the same rules, in one place that tests can
# reach): how the lists of several characters are merged into one order (a faction the order does not know yet is put right after the faction
# before it in the list it comes from), which factions are rows and which are headings (a heading stays only above a row that is shown), which
# entry of an account-wide faction counts (the newest scan), and what one cell says (the level, how far to the next one, the paragon round).
# Nothing is guessed: a level name the page does not know shows its number. The result is numbers and short codes, not texts (the texts, the
# number format and the bars belong to the block that shows them). Pure calculation, no I/O, standard library only.
# Works on the shape of page_payload.rep_payload(): {"defs": {faction id: name}, "chars": {char key: [entry, ...]}}.

import math
from typing import NamedTuple


class Row(NamedTuple):
    id: object
    name: str
    first: dict            # the entry of the first character that has this faction (kind of row, heading or not)
    wide: object           # the entry of an account-wide faction from the newest scan, or None
    type: str              # "cat" (heading), "sub" (sub heading) or "row"


class Cell(NamedTuple):
    """What a cell says. label: ("renown", n, max) | ("level", n, max) | ("name", text) | ("standing", n) | ("dash",) | ("empty",), with "?" for
    a number that is missing; detail: ("max",) or ("span", done, size) or None; share: 0..1 or None; paragon: (done, threshold, share, pending) or None."""
    label: tuple
    detail: object = None
    share: object = None
    paragon: object = None


def _known(value) -> bool:
    return value is not None


def _above(value, limit) -> bool:
    return value is not None and value > limit


def merge_order(lists: list) -> list:
    """The ids of the factions in one order, from the lists of the characters (each in the order of the game)."""
    order = []
    for entries in lists:
        at = -1
        for entry in entries:
            if entry["id"] in order:
                at = order.index(entry["id"])
            else:
                order.insert(at + 1, entry["id"])
                at += 1
    return order


def faction_name(defs: dict, faction_id) -> str:
    """The name of a faction, "#<id>" without one (ids may be numbers or, after a trip through JSON, texts)."""
    return (defs.get(faction_id) or defs.get(str(faction_id))) or f"#{faction_id}"


def build_rows(have: list, rep_chars: dict, defs: dict) -> list:
    """The rows in the merged order. have: the characters (dicts with "key" and "scanned_at") that have a list, in the order they are shown;
    rep_chars: {char key: list}. For an account-wide faction the entry of the character with the newest scan wins (the first one on a tie)."""
    by_char = {c["key"]: {e["id"]: e for e in rep_chars[c["key"]]} for c in have}
    rows = []
    for faction_id in merge_order([rep_chars[c["key"]] for c in have]):
        first, wide, wide_at = None, None, None
        for char in have:
            entry = by_char[char["key"]].get(faction_id)
            if entry is None:
                continue
            if first is None:
                first = entry
            if entry.get("aw") and (wide is None or (char.get("scanned_at") or "") > wide_at):
                wide, wide_at = entry, char.get("scanned_at") or ""
        heading = bool(first.get("hdr")) and not first.get("kind")
        kind = ("sub" if first.get("child") else "cat") if heading else "row"
        rows.append(Row(faction_id, faction_name(defs, faction_id), first, wide, kind))
    return rows


def visible_rows(rows: list, query: str = "") -> list:
    """The rows to show: those whose name contains the query (any case), and a heading only above a row that is shown."""
    wanted = query.strip().lower()
    shown, category, sub = [], None, None
    for row in rows:
        if row.type == "cat":
            category, sub = row, None
            continue
        if row.type == "sub":
            sub = row
            continue
        if wanted and wanted not in row.name.lower():
            continue
        if category:
            shown.append(category)
            category = None
        if sub:
            shown.append(sub)
            sub = None
        shown.append(row)
    return shown


def cell_of(entry: dict, standing_names: dict) -> Cell:
    """The cell of one entry. standing_names: {level number as text: name} (payload "names" of "standing")."""
    kind = entry.get("kind")
    label, detail, share = ("none",), None, None

    def span(low, high, at):
        return ("span", at - low, high - low), (at - low) / (high - low)

    if kind == "major":
        renown, top = entry.get("renown"), entry.get("max_renown")
        label = ("renown", "?" if renown is None else renown, "?" if top is None else top)
        if top is not None and renown is not None and renown >= top:
            detail = ("max",)
        elif _known(entry.get("earned")) and _above(entry.get("need"), 0):
            detail, share = span(0, entry["need"], entry["earned"])
    elif kind == "friend":
        level, top = entry.get("level"), entry.get("max_level")
        label = ("empty",) if level is None else ("level", level, "?" if top is None else top)
        if top is not None and level is not None and level >= top:
            detail = ("max",)
        elif _known(entry.get("standing")) and _known(entry.get("lo")) and _above(entry.get("hi"), entry["lo"]):
            detail, share = span(entry["lo"], entry["hi"], entry["standing"])
    elif kind == "std":
        reaction = entry.get("reaction")
        known = standing_names.get(str(reaction)) if reaction is not None else None
        label = ("name", known) if known else (("empty",) if reaction is None else ("standing", reaction))
        low, high = entry.get("lo"), entry.get("hi")
        if low is not None and high is not None and high <= low:
            detail = ("max",)
        elif _known(entry.get("standing")) and _known(low) and _above(high, low):
            detail, share = span(low, high, entry["standing"])
    paragon = None
    par = entry.get("par")
    if par and _above(par.get("threshold"), 0) and _known(par.get("value")):
        done = math.fmod(par["value"], par["threshold"])
        paragon = (done, par["threshold"], done / par["threshold"], bool(par.get("pending")))
    return Cell(label, detail, share, paragon)


def bar_percent(share) -> int:
    """The width of a bar in whole percent: the share held between 0 and 1, rounded half up (as the page script did)."""
    value = max(0.0, min(1.0, share)) * 100
    whole = math.floor(value)
    return int(whole + 1 if value - whole >= 0.5 else whole)
