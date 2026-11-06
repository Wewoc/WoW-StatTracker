#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)
# table_rules.py
# StatTracker - the rules of the main table of the stats page (one row per statistic, one column per ticked character), moved out of the page script:
# which statistics are shown (the search in name and category, the category, "only differences", "hide empty"), in which order (by the number of one
# character, descending first, then by name), which value of a row is the best one (marked when the ticked characters all have a number and not all
# the same), what a click on a column head does to the sorting, and the categories of the choice list. Nothing is guessed: a missing value is a dash.
# Pure calculation, no I/O. Works on the shape of page_payload.build_payload()["stats"]: [{"id", "name", "cat", "v": {char key: [text, number]}}].

from functools import lru_cache

from rules import collation

SUGGEST_MIN = 2              # fewer characters than this suggest nothing
SUGGEST_LIMIT = 12           # how many statistics the list of suggestions holds
EMPTY = "--"                 # what the game shows for a counter that never fired (and what the page shows for no entry at all)
DASH = "–"              # what a cell shows when the character has no entry for the statistic


def is_empty(cell) -> bool:
    """No entry, or the entry says "--" or nothing."""
    return not cell or cell[0] == EMPTY or cell[0] == ""


def categories(stats: list) -> list:
    """The categories of the statistics for the choice list, in the order of the page script (plain order of the characters by their UTF-16 units)."""
    return sorted({s["cat"] for s in stats}, key=lambda text: text.encode("utf-16-be"))


def filter_stats(stats: list, char_keys: list, query: str = "", category: str = "", only_diff: bool = False, hide_empty: bool = True) -> list:
    """The statistics to show, in the order they have. query: any case, looked for in name and category; category: "" for all; only_diff: the shown
    texts of the ticked characters are not all the same (with one character everything is shown); hide_empty: not every ticked character has an empty cell."""
    wanted = query.strip().lower()
    kept = []
    for stat in stats:
        if category and stat["cat"] != category:
            continue
        if wanted and not (wanted in stat["name"].lower() or wanted in stat["cat"].lower()):
            continue
        cells = [stat["v"].get(key) for key in char_keys]
        if hide_empty and all(is_empty(cell) for cell in cells):
            continue
        if only_diff and len(char_keys) > 1 and len({cell[0] if cell else EMPTY for cell in cells}) < 2:
            continue
        kept.append(stat)
    return kept


def sort_stats(stats: list, char_key, direction: int = -1) -> list:
    """The statistics sorted by the number of one character (direction -1: the biggest first, 1: the smallest first), a missing number last when
    descending and first when ascending; the same numbers by name. Without a character: the order stays."""
    if not char_key:
        return list(stats)

    def number(stat):
        cell = stat["v"].get(char_key)
        return cell[1] if cell and cell[1] is not None else float("-inf")
    return sorted(stats, key=lambda s: (number(s) if direction > 0 else -number(s), collation.key(s["name"])))


def best_number(cells: list):
    """The biggest number of a row, when it is worth marking: several characters, every one has a number, and the numbers are not all the same."""
    numbers = [cell[1] if cell else None for cell in cells]
    if len(cells) > 1 and all(n is not None for n in numbers) and len(set(numbers)) > 1:
        return max(numbers)
    return None


def next_sort(char_key, direction: int, clicked):
    """(character, direction) after a click on a column head. The head of the same character turns the direction round; another character starts
    descending; the heads "Category" and "Statistic" (clicked is empty) take the sorting off (what the page script did, quirk of the direction included)."""
    clicked = clicked or None
    if char_key == clicked:
        return char_key, -direction
    return clicked, -1



@lru_cache(maxsize=None)
def _name_key(name: str):
    return collation.key(name)


def suggest(stats: list, char_keys: list, text: str, category: str = "", only_diff: bool = False, hide_empty: bool = True, limit: int = SUGGEST_LIMIT):
    """(the statistics to suggest, how many match) for what has been typed in the search box: the ones the table would show for this text with the
    other settings (so a suggestion is never a row that then is not there), the names that begin with the text first, then those that only contain it
    (in name or category), each group in the order of the browser. Nothing under SUGGEST_MIN characters."""
    wanted = text.strip().lower()
    if len(wanted) < SUGGEST_MIN:
        return [], 0
    found = filter_stats(stats, char_keys, text, category, only_diff, hide_empty)
    found.sort(key=lambda s: (not s["name"].lower().startswith(wanted), _name_key(s["name"])))
    return found[:limit], len(found)
