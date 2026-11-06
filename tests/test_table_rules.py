# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)
# The rules of the main table (rules/table_rules.py): which statistics are shown, in which order, which value is the best, what a click on a column
# head does. The same rules were compared with the old page script on the real data (random combinations, see changelog).

import pytest

from rules import table_rules as rules


def stat(stat_id, name, cat, **cells):
    """cells: char key -> (text, number) or None for no entry; the keys of a statistic are written A, B, C (the characters A-One ...)."""
    return {"id": stat_id, "name": name, "cat": cat, "v": {k: list(v) for k, v in cells.items() if v is not None}}


STATS = [
    stat(1, "Kills", "Combat", A=("10", 10), B=("5", 5), C=("--", None)),
    stat(2, "Deaths", "Combat", A=("--", None), B=("--", None), C=None),
    stat(3, "Gold", "Wealth", A=("1g", 10000), B=("1g", 10000), C=("1g", 10000)),
    stat(4, "Title", "Misc", A=("Hero", None), B=("Hero", None)),
    stat(5, "Zeros", "Misc", A=("0", 0), B=("0", 0)),
]
KEYS = ["A", "B", "C"]


def ids(stats):
    return [s["id"] for s in stats]


# ---------------------------------------------------------------------------------------------------------------------- empty
@pytest.mark.parametrize("cell,empty", [(None, True), ([], True), (["--", None], True), (["", None], True), (["0", 0], False), (["x", None], False), (["-", 1], False)])
def test_a_cell_is_empty_without_an_entry_or_with_nothing_or_a_dash_in_it(cell, empty):
    assert rules.is_empty(cell) is empty


# ------------------------------------------------------------------------------------------------------------------ categories
def test_the_categories_are_listed_once_in_the_plain_order_of_the_characters():
    stats = [stat(1, "a", "b"), stat(2, "b", "B"), stat(3, "c", "ä"), stat(4, "d", "a"), stat(5, "e", "b")]
    assert rules.categories(stats) == ["B", "a", "b", "ä"]


# --------------------------------------------------------------------------------------------------------------------- filter
def test_nothing_is_taken_away_when_nothing_is_asked_but_the_rows_that_are_empty_for_everybody():
    assert ids(rules.filter_stats(STATS, KEYS, hide_empty=True)) == [1, 3, 4, 5]
    assert ids(rules.filter_stats(STATS, KEYS, hide_empty=False)) == [1, 2, 3, 4, 5]


def test_a_row_is_empty_only_for_the_ticked_characters():
    assert ids(rules.filter_stats(STATS, ["C"], hide_empty=True)) == [3]                 # C has an entry only for Gold ("--" and none are empty)


def test_without_a_character_ticked_every_row_is_empty():
    assert rules.filter_stats(STATS, [], hide_empty=True) == []
    assert ids(rules.filter_stats(STATS, [], hide_empty=False)) == [1, 2, 3, 4, 5]


def test_the_category_has_to_be_the_one_chosen():
    assert ids(rules.filter_stats(STATS, KEYS, category="Misc")) == [4, 5]
    assert rules.filter_stats(STATS, KEYS, category="misc") == []                           # a choice, not a search


@pytest.mark.parametrize("query,found", [("kill", [1]), ("  KILL ", [1]), ("combat", [1]), ("wealth", [3]), ("o", [1, 3, 5]), ("zzz", []), ("", [1, 3, 4, 5])])
def test_the_search_looks_in_name_and_category_in_any_case(query, found):
    assert ids(rules.filter_stats(STATS, KEYS, query=query)) == found


def test_only_differences_keeps_the_rows_where_the_shown_texts_are_not_all_the_same():
    assert ids(rules.filter_stats(STATS, KEYS, only_diff=True)) == [1, 4, 5]              # Gold is the same for all three; Title and Zeros have no entry for C
    assert ids(rules.filter_stats(STATS, ["A", "B"], only_diff=True)) == [1]               # Gold, Title and Zeros are the same for A and B
    assert ids(rules.filter_stats(STATS, ["A", "C"], only_diff=True)) == [1, 4, 5]         # "Hero" and "0" against no entry (a dash)


def test_only_differences_means_nothing_for_one_character():
    assert ids(rules.filter_stats(STATS, ["A"], only_diff=True)) == [1, 3, 4, 5]


def test_the_differences_are_in_the_texts_not_in_the_numbers():
    stats = [stat(1, "x", "c", A=("1,0", 1), B=("1.0", 1))]
    assert ids(rules.filter_stats(stats, ["A", "B"], only_diff=True)) == [1]


def test_the_dash_text_and_a_missing_entry_count_as_the_same():
    stats = [stat(1, "x", "c", A=("--", None), B=None), stat(2, "y", "c", A=("--", None), B=("1", 1))]
    assert ids(rules.filter_stats(stats, ["A", "B"], only_diff=True, hide_empty=False)) == [2]


# ----------------------------------------------------------------------------------------------------------------------- sort
def test_descending_order_of_one_character():
    assert ids(rules.sort_stats(STATS, "A", -1)) == [3, 1, 5, 2, 4]            # 10000, 10, 0, then the two without a number by name: Deaths, Title


def test_ascending_order_puts_the_missing_numbers_first_by_name():
    assert ids(rules.sort_stats(STATS, "A", 1)) == [2, 4, 5, 1, 3]


def test_the_same_numbers_are_ordered_by_name_whatever_the_direction():
    stats = [stat(1, "b", "c", A=("1", 1)), stat(2, "a", "c", A=("1", 1)), stat(3, "C", "c", A=("1", 1))]
    assert ids(rules.sort_stats(stats, "A", -1)) == [2, 1, 3] and ids(rules.sort_stats(stats, "A", 1)) == [2, 1, 3]


def test_a_character_that_is_not_ticked_can_still_decide_the_order():
    assert ids(rules.sort_stats(STATS, "C", -1))[0] == 3


def test_without_a_character_the_order_stays_and_the_list_is_a_copy():
    result = rules.sort_stats(STATS, None)
    assert ids(result) == [1, 2, 3, 4, 5] and result is not STATS
    assert ids(rules.sort_stats(STATS, "")) == [1, 2, 3, 4, 5]


def test_names_that_tie_are_ordered_like_the_browser_does():
    stats = [stat(1, "Höchster (Endlos)", "c", A=("0", 0)), stat(2, "Höchster (Endlos, Stufe 90)", "c", A=("0", 0)), stat(3, "Hoch", "c", A=("0", 0))]
    assert ids(rules.sort_stats(stats, "A", -1)) == [3, 2, 1]


# ----------------------------------------------------------------------------------------------------------------------- best
@pytest.mark.parametrize("cells,best", [
    ([["1", 1], ["3", 3], ["2", 2]], 3),
    ([["1", 1], ["1", 1]], None),                       # all the same: nothing to mark
    ([["1", 1], None], None),                           # one has no entry
    ([["1", 1], ["x", None]], None),                    # one has no number
    ([["5", 5]], None),                                 # one character: nothing to compare with
    ([["0", 0], ["0", 0], ["2", 2]], 2),
    ([["0", 0], ["-1", -1]], 0),                        # zero is a number
    ([], None),
])
def test_the_best_value_is_marked_only_when_everybody_has_a_number_and_they_differ(cells, best):
    assert rules.best_number(cells) == best


# ------------------------------------------------------------------------------------------------------------------ next sort
@pytest.mark.parametrize("current,clicked,result", [
    ((None, -1), "A", ("A", -1)),             # a first click: descending
    (("A", -1), "A", ("A", 1)),               # the same head again: the other way
    (("A", 1), "A", ("A", -1)),
    (("A", 1), "B", ("B", -1)),               # another head: descending again
    (("A", 1), "", (None, -1)),               # "Category" or "Statistic": no sorting
    (("A", -1), None, (None, -1)),
    ((None, -1), "", (None, 1)),              # nothing to take off: the direction turns (as the page script did; not visible)
])
def test_a_click_on_a_column_head(current, clicked, result):
    assert rules.next_sort(*current, clicked) == result


# --------------------------------------------------------------------------------------------------------------------- suggest
def named(*names, cat="Combat"):
    return [stat(i + 1, name, cat, A=("1", 1), B=("2", 2)) for i, name in enumerate(names)]


def suggested(stats, text, **options):
    found, total = rules.suggest(stats, ["A", "B"], text, **options)
    return [s["name"] for s in found], total


@pytest.mark.parametrize("text", ["", " ", "a", " a ", "  "])
def test_less_than_two_characters_suggest_nothing(text):
    assert rules.suggest(named("Alpha", "Beta"), ["A", "B"], text) == ([], 0)


def test_the_names_that_begin_with_the_text_come_first_then_those_that_contain_it_each_in_the_order_of_the_browser():
    stats = named("Arena kills", "Killstreak", "Kills in arena", "Deaths")
    assert suggested(stats, "kill") == (["Kills in arena", "Killstreak", "Arena kills"], 3)


def test_a_match_in_the_category_is_suggested_after_the_names():
    stats = [stat(1, "Zeta", "Wealth > Gold", A=("1", 1)), stat(2, "Gold earned", "Misc", A=("1", 1)), stat(3, "Alpha", "Misc", A=("1", 1))]
    assert suggested(stats, "gold") == (["Gold earned", "Zeta"], 2)


def test_the_text_is_taken_in_any_case_and_without_spaces_around_it():
    assert suggested(named("Kills", "Deaths"), "  KILL ") == (["Kills"], 1)


def test_the_list_holds_at_most_the_limit_and_the_total_says_how_many_match():
    stats = named(*[f"Test {n:02d}" for n in range(30)])
    names, total = suggested(stats, "test")
    assert total == 30 and len(names) == rules.SUGGEST_LIMIT and names == [f"Test {n:02d}" for n in range(12)]
    assert len(rules.suggest(stats, ["A", "B"], "test", limit=3)[0]) == 3


def test_a_suggestion_is_never_a_row_the_table_would_not_show():
    stats = [stat(1, "Kills", "Combat", A=("--", None), B=None), stat(2, "Kills 2", "Wealth", A=("5", 5), B=("5", 5))]
    assert suggested(stats, "kills") == (["Kills 2"], 1)                                          # the first one is empty for both characters
    assert suggested(stats, "kills", hide_empty=False) == (["Kills", "Kills 2"], 2)
    assert suggested(stats, "kills", category="Combat", hide_empty=False) == (["Kills"], 1)
    assert suggested(stats, "kills", only_diff=True, hide_empty=False) == ([], 0)                  # "--" against nothing reads the same, 5 and 5 too: neither differs
    assert rules.suggest(stats, [], "kills", hide_empty=False)[1] == 2
