#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)
# group_rules.py
# StatTracker - the rules of the "Groups" block of the stats page, moved out of the page script (the same rules, now in one place
# that tests can reach): which group a character belongs to (class and race only by the language independent file name, never
# by the stored text), how a group is named, the figures of the group table (characters, average level, total played time, the
# rates per hour as sum of counters / sum of hours, a statistic added by hand as sum, average or maximum), the table with its
# total over the groups shown, and which statistics may be added. A figure that cannot be calculated has no value: nothing is
# guessed. The result is numbers, not text (texts and the number format belong to the block that shows them).
# Pure calculation, no I/O. Needs stat_derive (the id of the played time), collation (the order of names) and works on the shape of page_payload.build_payload().
# Sums are added one after the other like the page script did (sum() of Python adds floats in a compensated way: other last digits).

import math
from typing import Callable, NamedTuple

from rules import collation, stat_derive

GROUP_BY = ("class", "race", "faction", "realm")
AGGREGATES = ("sum", "avg", "max")


class Cell(NamedTuple):
    """One value of the group table. kind: "count", "level", "hours", "rate", "number" or "gold" (how it is shown). value None =
    no value. used/total: the characters that had a value / the characters of the group ("n of m" when used < total)."""
    kind: str
    value: object = None
    used: int = 0
    total: int = 0


class Figure(NamedTuple):
    """A column of the group table. label_key: the page text of a standard figure, label: the text of a rate or the name of a
    statistic added by hand; cat and agg are set for those; calc(members) gives the Cell of a group."""
    id: str
    calc: Callable
    label_key: str = ""
    label: str = ""
    cat: str = ""
    agg: str = ""


class Group(NamedTuple):
    key: object            # the file name, faction, realm, or None = unknown
    label: str
    members: list


class Row(NamedTuple):
    group: Group
    cells: list


class Table(NamedTuple):
    rows: list             # Row, in the order of the groups
    total: object          # the Cells over all characters of the groups shown, or None when no group is shown


# ------------------------------------------------------------------------------------------------ small helpers
def is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def add_up(values):
    total = 0
    for value in values:
        total += value
    return total


# ---------------------------------------------------------------------------------------------------------- groups
def group_key(char: dict, by: str):
    """The group of a character: the class or race file name, the faction or the realm; None when the data does not have it."""
    if by == "class":
        return char.get("class_file") or None
    if by == "race":
        return char.get("race_file") or None
    if by == "faction":
        return char.get("faction") or None
    key = char["key"]
    cut = key.find("-")                        # "Name-Realm": cut at the first hyphen, a realm name can contain one
    return key[cut + 1:] if 0 < cut < len(key) - 1 else None


def group_label(by: str, key, members: list, names: dict, factions: dict, unknown: str) -> str:
    """The name of a group. names: {"class": {file name: text}, "race": {...}} (payload "names"), factions: {faction: text}, unknown: the
    text for "no value". A file name this program does not know yet shows the text stored with the newest scan of the group."""
    if key is None:
        return unknown
    if by == "faction":
        return factions.get(key) or key
    if by == "realm":
        return key
    known = (names.get(by) or {}).get(key)
    if known:
        return known
    newest = max(members, key=lambda c: c.get("scanned_at") or "")
    return newest.get("class" if by == "class" else "race") or key


# the order of names as the browser sorts them (collation.key; the groups used an approximation of it before)
sort_key = collation.key


def build_groups(chars: list, by: str, names: dict, factions: dict, unknown: str) -> list:
    """The groups of the characters (in their order), the unknown group last, the others by name."""
    members_of = {}
    for char in chars:
        members_of.setdefault(group_key(char, by), []).append(char)
    groups = [Group(key, group_label(by, key, members, names, factions, unknown), members) for key, members in members_of.items()]
    groups.sort(key=lambda g: (g.key is None, sort_key(g.label)))
    return groups


# --------------------------------------------------------------------------------------------------------- figures
def _number_of(stat, key: str):
    """The number of a character in a statistic, or None."""
    cell = stat["v"].get(key) if stat else None
    return cell[1] if cell and is_number(cell[1]) else None


def standard_figures(stats: list, derived) -> list:
    """The figures every page has: characters, average level, total played time, and one rate per role of stat_derive (the rate of a
    group is the sum of the counters of its characters over the sum of their hours, not the mean of the rates)."""
    def count(members):
        return Cell("count", len(members), len(members), len(members))

    def level(members):
        values = [c["level"] for c in members if is_number(c.get("level"))]
        return Cell("level", add_up(values) / len(values), len(values), len(members)) if values else Cell("level")

    played_stat = next((s for s in stats if s["id"] == stat_derive.PLAYED_TOTAL_ID), None)

    def played(members):
        values = [s for s in (_number_of(played_stat, c["key"]) for c in members) if s is not None]
        return Cell("hours", add_up(values) / 3600, len(values), len(members)) if values else Cell("hours")

    figures = [Figure("chars", count, label_key="groups_fig_chars"), Figure("level", level, label_key="groups_fig_level"),
               Figure("played", played, label_key="groups_fig_played")]
    for role in (derived or {}).get("roles") or []:
        def rate(members, role=role):
            used = [r for r in (role["chars"].get(c["key"]) for c in members) if r and "rate" in r]
            hours = add_up(r["hours"] for r in used)
            if used and hours > 0:
                return Cell("rate", add_up(r["amount"] for r in used) / hours, len(used), len(members))
            return Cell("rate")
        figures.append(Figure("role_" + role["role"], rate, label=role["label"]))
    return figures


def _aggregate(agg: str, values: list):
    if agg == "sum":
        return add_up(values)
    if agg == "avg":
        return add_up(values) / len(values)
    return max(values)


def extra_figure(stat, stat_id: int, agg: str) -> Figure:
    """A statistic added by hand, combined over the group with `agg`. Only characters with a number for it count; a statistic whose
    texts are gold (payload "gold") is gold. `stat` is None when this page does not have the statistic any more: no value."""
    def calc(members):
        if stat is None:
            return Cell("number")
        values = [v for v in (_number_of(stat, m["key"]) for m in members) if v is not None]
        if not values:
            return Cell("number")
        return Cell("gold" if stat.get("gold") else "number", _aggregate(agg, values), len(values), len(members))
    return Figure(f"x{stat_id}_{agg}", calc, label=stat["name"] if stat else str(stat_id), cat=stat["cat"] if stat else "", agg=agg)


def offered_stats(stats: list, chars: list, query: str = "") -> list:
    """The statistics that can be added: no played time (it is a figure of its own), the name or category contains the query (any case),
    and at least one of the characters has a number for it."""
    wanted = query.strip().lower()
    keys = [c["key"] for c in chars]
    found = []
    for stat in stats:
        if stat["id"] < 0:
            continue
        if wanted and not (wanted in stat["name"].lower() or wanted in stat["cat"].lower()):
            continue
        if any(_number_of(stat, key) is not None for key in keys):
            found.append(stat)
    return found


# ----------------------------------------------------------------------------------------------------------- table
def build_table(groups: list, hidden: set, figures: list) -> Table:
    """One row per group that is not hidden, and the total over the characters of those groups."""
    shown = [g for g in groups if g.key not in hidden]
    rows = [Row(g, [f.calc(g.members) for f in figures]) for g in shown]
    if not shown:
        return Table(rows, None)
    members = [m for g in shown for m in g.members]
    return Table(rows, [f.calc(members) for f in figures])
