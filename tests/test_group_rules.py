# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)
# The rules of the Groups block (rules/group_rules.py): which group a character is in, how a group is named, the figures of the
# table, the total, and which statistics may be added. The numbers are what the page script calculated before (the same rules,
# compared with it on the real data when the block was moved).

import pytest

from rules import group_rules as rules
from rules import stat_derive

NAMES = {"class": {"MAGE": "Magier", "DRUID": "Druide"}, "race": {"Human": "Mensch"}}
FACTIONS = {"Alliance": "Allianz", "Horde": "Horde"}
UNKNOWN = "unbekannt"


def char(key, class_file="MAGE", race_file="Human", faction="Alliance", level=80, scanned_at="2026-10-01 10:00:00", **extra):
    return {"key": key, "class_file": class_file, "race_file": race_file, "faction": faction, "level": level,
            "scanned_at": scanned_at, "class": "Magier", "race": "Mensch", **extra}


def stat(stat_id, name, cat, values, **extra):
    return {"id": stat_id, "name": name, "cat": cat, "v": {k: list(v) for k, v in values.items()}, **extra}


CHARS = [char("A-One", level=80), char("B-Two", level=60), char("C-Three", class_file="DRUID", race_file="NightElf", faction="Horde", level=70),
         char("D-Four", class_file=None, race_file=None, faction=None, level=None)]


# ------------------------------------------------------------------------------------------------------ the group of a character
@pytest.mark.parametrize("by,key", [("class", "MAGE"), ("race", "Human"), ("faction", "Alliance"), ("realm", "One")])
def test_group_key_reads_the_file_names_and_never_the_stored_text(by, key):
    assert rules.group_key(char("A-One"), by) == key


@pytest.mark.parametrize("by", ["class", "race", "faction"])
def test_a_character_without_the_value_is_unknown_not_guessed(by):
    assert rules.group_key(CHARS[3], by) is None
    assert rules.group_key(char("A-B", class_file="", race_file="", faction=""), by) is None


@pytest.mark.parametrize("key,realm", [("Name-Realm", "Realm"), ("Name-Kil'jaeden-X", "Kil'jaeden-X"), ("NoRealm", None),
                                       ("-Realm", None), ("Name-", None)])
def test_the_realm_is_cut_at_the_first_hyphen(key, realm):
    assert rules.group_key(char(key), "realm") == realm


# ----------------------------------------------------------------------------------------------------------------- the name
def label(by, key, members=(), names=NAMES):
    return rules.group_label(by, key, list(members), names, FACTIONS, UNKNOWN)


def test_a_group_is_named_from_the_tables_of_the_page():
    assert label("class", "MAGE") == "Magier" and label("race", "Human") == "Mensch"
    assert label("faction", "Alliance") == "Allianz" and label("faction", "Neutral") == "Neutral"
    assert label("realm", "Kil'jaeden") == "Kil'jaeden" and label("class", None) == UNKNOWN


def test_a_file_name_the_page_does_not_know_shows_the_text_of_the_newest_scan():
    old = char("A-One", class_file="NEWCLASS", scanned_at="2026-01-01 10:00:00", **{})
    new = char("B-Two", class_file="NEWCLASS", scanned_at="2026-09-01 10:00:00", **{})
    old["class"], new["class"] = "Alt", "Neu"
    assert label("class", "NEWCLASS", [old, new]) == "Neu" and label("class", "NEWCLASS", [new, old]) == "Neu"
    new["class"] = ""
    assert label("class", "NEWCLASS", [old, new]) == "NEWCLASS"


# ---------------------------------------------------------------------------------------------------------------- the groups
def test_the_groups_are_sorted_by_name_with_unknown_last_and_keep_the_order_of_the_characters():
    groups = rules.build_groups(CHARS, "class", NAMES, FACTIONS, UNKNOWN)
    assert [g.label for g in groups] == ["Druide", "Magier", UNKNOWN]
    assert [c["key"] for c in groups[1].members] == ["A-One", "B-Two"] and groups[2].key is None


def test_accents_and_capitals_do_not_decide_the_order_first():
    assert sorted(["Zebra", "Ärger", "apfel", "Apfel", "Ärzte"], key=rules.sort_key) == ["apfel", "Apfel", "Ärger", "Ärzte", "Zebra"]
    assert sorted(["Mönch", "Magier", "Mohr", "Paladin"], key=rules.sort_key) == ["Magier", "Mohr", "Mönch", "Paladin"]


# --------------------------------------------------------------------------------------------------------------------- figures
PLAYED = stat(-1, "Played", "Time", {"A-One": ("x", 7200), "B-Two": ("x", 3600), "C-Three": ("x", None)})
STATS = [PLAYED,
         stat(107, "Creatures killed", "Combat", {"A-One": ("1.000", 1000), "B-Two": ("500", 500), "C-Three": ("--", None)}),
         stat(328, "Gold", "Wealth", {"A-One": ("5g", 50000), "B-Two": ("1g", 10000)}, gold=True),
         stat(5, "Text", "Misc", {"A-One": ("a", None), "B-Two": ("b", None)})]


def derived():
    data = stat_derive.compute(STATS, [c["key"] for c in CHARS])
    for role in data["roles"]:
        role["label"] = role["role"].upper()
    return data


def figures():
    return {f.id: f for f in rules.standard_figures(STATS, derived())}


def test_the_standard_figures_and_one_rate_per_role():
    assert list(figures()) == ["chars", "level", "played"] + ["role_" + r.key for r in stat_derive.ROLES]
    assert figures()["role_gold"].label == "GOLD" and figures()["chars"].label_key == "groups_fig_chars"


def test_the_character_count_has_no_missing_part():
    assert rules.Cell("count", 2, 2, 2) == figures()["chars"].calc(CHARS[:2])


def test_the_average_level_counts_only_characters_with_a_level():
    cell = figures()["level"].calc(CHARS)
    assert cell == rules.Cell("level", (80 + 60 + 70) / 3, 3, 4)
    assert figures()["level"].calc([CHARS[3]]) == rules.Cell("level")           # no value, not 0


def test_the_played_time_is_the_sum_of_the_hours_of_those_who_have_it():
    assert figures()["played"].calc(CHARS) == rules.Cell("hours", 3.0, 2, 4)
    assert figures()["played"].calc([CHARS[2]]) == rules.Cell("hours")


def test_a_page_without_played_time_has_no_value_for_it():
    without = {f.id: f for f in rules.standard_figures([s for s in STATS if s["id"] != -1], derived())}
    assert without["played"].calc(CHARS) == rules.Cell("hours")


def test_a_rate_is_the_sum_of_the_counters_over_the_sum_of_the_hours_not_the_mean_of_the_rates():
    stats = [stat(-1, "Played", "T", {"A-One": ("x", 3600 * 10), "B-Two": ("x", 3600 * 100)}),
             stat(107, "Kills", "C", {"A-One": ("x", 100), "B-Two": ("x", 100)})]
    data = stat_derive.compute(stats, ["A-One", "B-Two"])
    for role in data["roles"]:
        role["label"] = role["role"]
    cell = {f.id: f for f in rules.standard_figures(stats, data)}["role_kills_pve"].calc([{"key": "A-One"}, {"key": "B-Two"}])
    assert cell == rules.Cell("rate", 200 / 110, 2, 2) and cell.value != (10 + 1) / 2


def test_a_rate_without_a_usable_character_has_no_value():
    assert figures()["role_kills_pve"].calc([CHARS[2], CHARS[3]]) == rules.Cell("rate")


def test_the_rate_says_how_many_characters_it_is_made_of():
    cell = figures()["role_kills_pve"].calc(CHARS)
    assert (cell.kind, cell.used, cell.total) == ("rate", 2, 4)


# ---------------------------------------------------------------------------------------------------------- statistics by hand
def extra(stat_id, agg):
    return rules.extra_figure(next(s for s in STATS if s["id"] == stat_id), stat_id, agg)


@pytest.mark.parametrize("agg,expected", [("sum", 1500), ("avg", 750), ("max", 1000)])
def test_a_statistic_is_combined_with_the_chosen_function(agg, expected):
    assert extra(107, agg).calc(CHARS) == rules.Cell("number", expected, 2, 4)


def test_only_characters_with_a_number_count_and_none_gives_no_value():
    assert extra(5, "sum").calc(CHARS) == rules.Cell("number")
    assert extra(107, "sum").calc([CHARS[2]]) == rules.Cell("number")


def test_a_booleans_and_text_are_no_numbers():
    odd = stat(9, "Odd", "M", {"A-One": ("t", True), "B-Two": ("t", "12")})
    assert rules.extra_figure(odd, 9, "sum").calc(CHARS[:2]) == rules.Cell("number")


def test_a_gold_statistic_stays_gold_and_keeps_its_copper_value():
    cell = extra(328, "sum").calc(CHARS)
    assert cell == rules.Cell("gold", 60000, 2, 4)


def test_the_label_the_id_and_the_category_of_a_statistic_by_hand():
    figure = extra(107, "avg")
    assert (figure.id, figure.label, figure.cat, figure.agg) == ("x107_avg", "Creatures killed", "Combat", "avg")


def test_a_statistic_this_page_does_not_have_any_more_has_no_value():
    figure = rules.extra_figure(None, 4711, "sum")
    assert (figure.id, figure.label, figure.cat) == ("x4711_sum", "4711", "") and figure.calc(CHARS) == rules.Cell("number")


def test_sums_are_added_one_after_the_other_like_the_page_script_did():
    assert rules.add_up([0.1] * 10) == 0.9999999999999999       # sum() of Python would give 1.0
    assert rules.add_up([]) == 0


# ----------------------------------------------------------------------------------------------------- what can be added
def test_the_statistics_that_can_be_added_have_a_number_for_a_ticked_character():
    found = [s["id"] for s in rules.offered_stats(STATS, CHARS)]
    assert found == [107, 328]                       # no played time, no text, nothing that nobody has a number for
    assert [s["id"] for s in rules.offered_stats(STATS, [CHARS[2]])] == []
    assert [s["id"] for s in rules.offered_stats(STATS, [CHARS[1]])] == [107, 328]


@pytest.mark.parametrize("query,found", [("", [107, 328]), ("CREAT", [107]), ("  wealth ", [328]), ("combat", [107]), ("nothing", [])])
def test_the_search_looks_at_name_and_category_in_any_case(query, found):
    assert [s["id"] for s in rules.offered_stats(STATS, CHARS, query)] == found


# --------------------------------------------------------------------------------------------------------------------- table
def table(hidden=()):
    groups = rules.build_groups(CHARS, "class", NAMES, FACTIONS, UNKNOWN)
    return rules.build_table(groups, set(hidden), [figures()["chars"], figures()["level"]])


def test_the_table_has_a_row_per_group_and_a_total_over_all_of_them():
    result = table()
    assert [r.group.label for r in result.rows] == ["Druide", "Magier", UNKNOWN]
    assert result.rows[1].cells == [rules.Cell("count", 2, 2, 2), rules.Cell("level", 70.0, 2, 2)]
    assert result.total == [rules.Cell("count", 4, 4, 4), rules.Cell("level", 70.0, 3, 4)]


def test_a_hidden_group_leaves_the_rows_and_the_total():
    result = table(hidden={"MAGE", None})
    assert [r.group.label for r in result.rows] == ["Druide"]
    assert result.total == [rules.Cell("count", 1, 1, 1), rules.Cell("level", 70.0, 1, 1)]


def test_when_every_group_is_hidden_there_is_no_total():
    result = table(hidden={"MAGE", "DRUID", None})
    assert result.rows == [] and result.total is None
