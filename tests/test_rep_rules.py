# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)
# The rules of the Reputation block (rules/rep_rules.py): the merged order of the factions, the rows and headings, which entry of an account-wide
# faction counts, what one cell says, the width of a bar. (The same rules were compared with the old page script on the real data: 625 cells,
# 3 000 invented entries, 275 orders.)

import pytest

from rules import rep_rules as rules


def entry(faction_id, **fields):
    return {"id": faction_id, **fields}


def ids(entries):
    return [e["id"] for e in entries]


def char(key, scanned_at="2026-10-01 10:00:00"):
    return {"key": key, "scanned_at": scanned_at}


# ------------------------------------------------------------------------------------------------------------------------- order
def test_one_list_keeps_its_order():
    assert rules.merge_order([[entry(3), entry(1), entry(2)]]) == [3, 1, 2]


def test_a_faction_the_order_does_not_know_goes_right_after_the_one_before_it_in_its_own_list():
    assert rules.merge_order([[entry(1), entry(2), entry(3)], [entry(1), entry(9), entry(3)]]) == [1, 9, 2, 3]
    assert rules.merge_order([[entry(1), entry(2)], [entry(7), entry(8), entry(1), entry(9)]]) == [7, 8, 1, 9, 2]


def test_the_first_list_decides_where_the_order_agrees_and_a_shared_faction_moves_the_place_to_insert():
    assert rules.merge_order([[entry(1), entry(2), entry(3)], [entry(3), entry(4)]]) == [1, 2, 3, 4]
    assert rules.merge_order([[entry(2), entry(1)], [entry(1), entry(2)]]) == [2, 1]


def test_no_lists_no_order():
    assert rules.merge_order([]) == [] and rules.merge_order([[]]) == []


# --------------------------------------------------------------------------------------------------------------------- names
@pytest.mark.parametrize("defs,key,name", [({5: "Five"}, 5, "Five"), ({"5": "Five"}, 5, "Five"), ({}, 5, "#5"), ({5: ""}, 5, "#5"), ({"5": None}, 5, "#5")])
def test_a_faction_is_named_from_the_table_and_without_a_name_by_its_number(defs, key, name):
    assert rules.faction_name(defs, key) == name


# -------------------------------------------------------------------------------------------------------------------- rows
LISTS = {
    "A-One": [entry(1, hdr=1), entry(2, hdr=1, child=1), entry(3, kind="std"), entry(4, kind="major", aw=1)],
    "B-Two": [entry(1, hdr=1), entry(2, hdr=1, child=1), entry(3, kind="std"), entry(4, kind="major", aw=1, renown=9), entry(5, kind="std")],
}
DEFS = {1: "Category", 2: "Sub", 3: "Three", 4: "Four", 5: "Five"}


def test_the_rows_have_the_merged_order_and_a_type():
    rows = rules.build_rows([char("A-One"), char("B-Two")], LISTS, DEFS)
    assert [(r.id, r.name, r.type) for r in rows] == [(1, "Category", "cat"), (2, "Sub", "sub"), (3, "Three", "row"), (4, "Four", "row"), (5, "Five", "row")]


def test_a_heading_is_an_entry_with_the_heading_flag_and_no_kind():
    lists = {"A-One": [entry(1, hdr=1, kind="major"), entry(2)]}
    rows = rules.build_rows([char("A-One")], lists, {1: "A", 2: "B"})
    assert [r.type for r in rows] == ["row", "row"]                  # a faction with a heading flag and a kind (a main faction) is a row


def test_the_first_character_that_has_a_faction_gives_its_entry():
    rows = rules.build_rows([char("A-One"), char("B-Two")], LISTS, DEFS)
    assert rows[4].first is LISTS["B-Two"][4] and rows[2].first is LISTS["A-One"][2]


def test_an_account_wide_faction_takes_the_entry_of_the_newest_scan_and_the_first_on_a_tie():
    older, newer = char("A-One", "2026-10-01 10:00:00"), char("B-Two", "2026-10-02 10:00:00")
    assert rules.build_rows([older, newer], LISTS, DEFS)[3].wide is LISTS["B-Two"][3]
    assert rules.build_rows([newer, older], LISTS, DEFS)[3].wide is LISTS["B-Two"][3]
    tie = [char("A-One"), char("B-Two")]
    assert rules.build_rows(tie, LISTS, DEFS)[3].wide is LISTS["A-One"][3]
    assert rules.build_rows(tie, LISTS, DEFS)[2].wide is None


def test_a_faction_without_a_name_in_the_table_shows_its_number():
    assert rules.build_rows([char("A-One")], {"A-One": [entry(9)]}, {})[0].name == "#9"


# ----------------------------------------------------------------------------------------------------------------------- shown
def names(rows):
    return [r.name for r in rows]


def test_without_a_search_every_row_and_heading_is_shown():
    rows = rules.build_rows([char("A-One"), char("B-Two")], LISTS, DEFS)
    assert names(rules.visible_rows(rows)) == ["Category", "Sub", "Three", "Four", "Five"]


def test_a_search_keeps_the_rows_that_contain_it_in_any_case_and_the_headings_above_them():
    rows = rules.build_rows([char("A-One"), char("B-Two")], LISTS, DEFS)
    assert names(rules.visible_rows(rows, " FIVE ")) == ["Category", "Sub", "Five"]
    assert names(rules.visible_rows(rows, "o")) == ["Category", "Sub", "Four"]
    assert rules.visible_rows(rows, "nothing") == []


def test_a_heading_without_a_row_to_show_is_dropped_and_a_new_heading_replaces_the_one_before():
    lists = {"A-One": [entry(1, hdr=1), entry(2), entry(3, hdr=1), entry(4, hdr=1, child=1), entry(5)]}
    rows = rules.build_rows([char("A-One")], lists, {1: "Cat 1", 2: "Aaa", 3: "Cat 2", 4: "Sub 2", 5: "Bbb"})
    assert names(rules.visible_rows(rows, "bbb")) == ["Cat 2", "Sub 2", "Bbb"]
    assert names(rules.visible_rows(rows, "aaa")) == ["Cat 1", "Aaa"]


# ------------------------------------------------------------------------------------------------------------------- cells
STANDING = {"4": "Neutral", "8": "Exalted"}


def cell(**fields):
    return rules.cell_of(fields, STANDING)


def test_a_standard_faction_shows_the_level_name_and_the_way_to_the_next_level():
    result = cell(kind="std", reaction=4, standing=1500, lo=0, hi=3000)
    assert result.label == ("name", "Neutral") and result.detail == ("span", 1500, 3000) and result.share == 0.5


def test_a_level_name_the_page_does_not_know_shows_its_number_and_a_missing_one_a_dash():
    assert cell(kind="std", reaction=9).label == ("standing", 9)
    assert cell(kind="std", reaction=None).label == ("empty",) and cell(kind="std").label == ("empty",)


def test_a_standard_faction_at_the_top_says_maximum_and_has_no_bar():
    result = cell(kind="std", reaction=8, standing=21000, lo=21000, hi=21000)
    assert result.detail == ("max",) and result.share is None
    assert cell(kind="std", reaction=8, lo=5, hi=3).detail == ("max",)


def test_a_standard_faction_with_a_gap_in_its_numbers_has_no_bar():
    for fields in ({"standing": 5, "lo": 0}, {"standing": 5, "hi": 10}, {"lo": 0, "hi": 10}, {"standing": None, "lo": 0, "hi": 10}):
        result = cell(kind="std", reaction=4, **fields)
        assert result.detail is None and result.share is None, fields


def test_a_friendship_shows_the_level_of_the_maximum_and_the_way_to_the_next_one():
    result = cell(kind="friend", level=2, max_level=8, standing=50, lo=0, hi=100)
    assert result.label == ("level", 2, 8) and result.detail == ("span", 50, 100) and result.share == 0.5
    assert cell(kind="friend", level=8, max_level=8).detail == ("max",)
    assert cell(kind="friend", level=9, max_level=8).detail == ("max",)
    assert cell(kind="friend", level=3).label == ("level", 3, "?")
    assert cell(kind="friend").label == ("empty",)


def test_a_main_faction_shows_the_renown_and_the_way_to_the_next_level():
    result = cell(kind="major", renown=5, max_renown=20, earned=150, need=2500)
    assert result.label == ("renown", 5, 20) and result.detail == ("span", 150, 2500) and result.share == 150 / 2500
    assert cell(kind="major", renown=20, max_renown=20, earned=1, need=2500).detail == ("max",)
    assert cell(kind="major").label == ("renown", "?", "?")
    assert cell(kind="major", renown=3, max_renown=20, earned=1, need=0).detail is None


def test_a_heading_or_an_unknown_kind_has_an_empty_cell():
    for fields in ({}, {"kind": "other", "standing": 5, "lo": 0, "hi": 10}, {"hdr": 1}):
        result = cell(**fields)
        assert result.label == ("none",) and result.detail is None and result.share is None


def test_the_paragon_round_is_the_value_after_the_full_rounds():
    result = cell(kind="std", reaction=8, par={"value": 25000, "threshold": 10000, "pending": 1})
    assert result.paragon == (5000.0, 10000, 0.5, True)
    assert cell(kind="std", reaction=8, par={"value": 5, "threshold": 10}).paragon == (5.0, 10, 0.5, False)


def test_no_paragon_without_a_threshold_or_a_value():
    for par in ({"value": 5}, {"threshold": 10}, {"value": 5, "threshold": 0}, {"value": 5, "threshold": None}, {"value": None, "threshold": 10}, {}):
        assert cell(kind="std", reaction=8, par=par).paragon is None, par
    assert cell(kind="std", reaction=8).paragon is None


# ----------------------------------------------------------------------------------------------------------------------- bars
@pytest.mark.parametrize("share,percent", [(0, 0), (1, 100), (0.5, 50), (0.004, 0), (0.005, 1), (0.0049999, 0), (0.994999, 99), (0.995, 100), (-3, 0), (7, 100),
                                           (0.125, 13), (0.375, 38)])
def test_a_bar_is_whole_percent_rounded_half_up_and_held_between_empty_and_full(share, percent):
    assert rules.bar_percent(share) == percent
