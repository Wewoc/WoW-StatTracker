# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)
# The rules of the Top 5 tiles (src/rules/tile_rules.py): which characters a scope names and the value of a tile.

from rules import group_rules, tile_rules

CHARS = [
    {"key": "A-One", "class_file": "MAGE", "race_file": "Human", "faction": "Alliance"},
    {"key": "B-Two", "class_file": "MAGE", "race_file": "Human", "faction": "Alliance"},
    {"key": "C-Three", "class_file": "DRUID", "race_file": "NightElf", "faction": "Alliance"},
    {"key": "D-Four", "class_file": None, "race_file": None, "faction": None},
    {"key": "E-Re-Alm", "class_file": "ROGUE", "race_file": "Orc", "faction": "Horde"},
]
STATS = {
    107: {"id": 107, "name": "Kills", "cat": "Combat", "v": {"A-One": ["1.000", 1000], "B-Two": ["500", 500], "C-Three": ["--", None], "E-Re-Alm": ["300", 300]}},
    328: {"id": 328, "name": "Gold", "cat": "Wealth", "gold": True, "v": {"A-One": ["5g", 50000], "B-Two": ["1g", 10000]}},
    -1: {"id": -1, "name": "Played", "cat": "Time", "v": {"A-One": ["x", 7200], "B-Two": ["x", 3600], "D-Four": ["x", 1800]}},
    5: {"id": 5, "name": "Text only", "cat": "Misc", "v": {"A-One": ["a", None]}},
}


def keys(by, value):
    return [c["key"] for c in tile_rules.members(CHARS, by, value)]


def tile(**values):
    return {"stat": 107, "agg": "sum", "by": "all", "value": "", **values}


def value(**values):
    return tile_rules.cell(STATS, tile(**values), CHARS)


def test_every_scope_names_its_characters_in_the_order_of_the_page():
    assert keys("all", "") == [c["key"] for c in CHARS]
    assert keys("class", "MAGE") == ["A-One", "B-Two"] and keys("race", "NightElf") == ["C-Three"]
    assert keys("faction", "Alliance") == ["A-One", "B-Two", "C-Three"] and keys("faction", "Horde") == ["E-Re-Alm"]
    assert keys("realm", "Realm") == [] and keys("realm", "Re-Alm") == ["E-Re-Alm"]           # the realm is what follows the first hyphen
    assert keys("char", "B-Two") == ["B-Two"] and keys("char", "Nobody") == []


def test_the_group_unknown_has_the_empty_value_and_a_character_is_never_taken_for_it_by_its_text():
    assert keys("class", "") == ["D-Four"] and keys("race", "") == ["D-Four"] and keys("faction", "") == ["D-Four"]
    assert keys("class", None) == ["D-Four"] and keys("class", "mage") == []


def test_a_scope_this_program_does_not_know_names_nobody():
    assert keys("guild", "x") == [] and keys(None, "x") == [] and keys("all", None) == [c["key"] for c in CHARS]


def test_the_value_is_sum_average_or_maximum_over_the_characters_with_a_number():
    assert value(agg="sum") == group_rules.Cell("number", 1800, 3, 5)                          # C-Three has "--" and D-Four has nothing
    assert value(agg="avg") == group_rules.Cell("number", 600, 3, 5)
    assert value(agg="max") == group_rules.Cell("number", 1000, 3, 5)
    assert value(by="class", value="MAGE") == group_rules.Cell("number", 1500, 2, 2)
    assert value(by="char", value="E-Re-Alm") == group_rules.Cell("number", 300, 1, 1)


def test_a_tile_has_the_same_value_as_a_statistic_added_to_the_groups_block():
    for agg in group_rules.AGGREGATES:
        for members in (CHARS, CHARS[:2], CHARS[2:3]):
            assert group_rules.extra_figure(STATS[107], 107, agg).calc(members) == tile_rules.cell(STATS, tile(agg=agg), members)


def test_a_statistic_with_coin_texts_is_gold_and_a_played_time_is_hours():
    assert value(stat=328, agg="sum") == group_rules.Cell("gold", 60000, 2, 5)
    assert value(stat=-1, agg="sum") == group_rules.Cell("hours", 3.5, 3, 5)
    assert value(stat=-1, agg="max", by="char", value="A-One") == group_rules.Cell("hours", 2.0, 1, 1)


def test_there_is_no_value_instead_of_an_invented_number():
    for case in (dict(stat=5), dict(stat=999), dict(by="char", value="C-Three"), dict(by="class", value="DRUID"), dict(by="class", value="WARLOCK"),
                 dict(by="char", value="Nobody"), dict(by="guild", value="x"), dict(agg="median"), dict(agg=None), dict(by=None)):
        cell = value(**case)
        assert cell.value is None and cell.used == 0, case


def test_a_tile_without_characters_on_the_page_has_no_value():
    assert tile_rules.cell(STATS, tile(), []).value is None
