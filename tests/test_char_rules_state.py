# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)
# The list of rules the settings window shows and changes (src/rules/char_rules.py): add a rule, take rules away, which targets a rule is for, all without
# any widget.

import copy

import pytest

from rules import char_rules

CHARS = [
    {"key": "A-One", "class_file": "MAGE", "race_file": "Human", "faction": "Alliance", "level": 80},
    {"key": "B-Two", "class_file": "DRUID", "race_file": "NightElf", "faction": "Alliance", "level": 19},
    {"key": "C-Three", "class_file": None, "race_file": None, "faction": "Horde", "level": 45},
]


def rule(kind, value, **more):
    return {"type": kind, "value": value, **more}


# ---------------------------------------------------------------- the targets of a rule
def test_the_targets_of_a_rule_are_those_it_applies_to_in_their_order():
    assert char_rules.targets_of(rule("class", "MAGE")) == ("page", "excel")
    assert char_rules.targets_of(rule("class", "MAGE", **{"for": ["excel"]})) == ("excel",)
    assert char_rules.targets_of(rule("class", "MAGE", **{"for": ["excel", "page"]})) == ("page", "excel")
    assert char_rules.targets_of(rule("class", "MAGE", **{"for": []})) == ()
    assert char_rules.targets_of(rule("class", "MAGE", **{"for": "page"})) == ()
    assert char_rules.targets_of("text") == () and char_rules.targets_of(None) == ()


# ---------------------------------------------------------------- adding a rule
def test_a_rule_is_added_at_the_end_with_the_shortest_form_that_says_its_targets():
    old = [rule("char", "A-One")]
    assert char_rules.add_rule(old, "class", "MAGE", ["page", "excel"]) == [rule("char", "A-One"), rule("class", "MAGE")]
    assert char_rules.add_rule(old, "class", "MAGE", ["excel", "page"]) == [rule("char", "A-One"), rule("class", "MAGE")]       # the order given does not matter
    assert char_rules.add_rule([], "race", "Orc", ["page"]) == [rule("race", "Orc", **{"for": ["page"]})]
    assert char_rules.add_rule([], "faction", "Horde", ("excel",)) == [rule("faction", "Horde", **{"for": ["excel"]})]
    assert char_rules.add_rule(None, "realm", "Realm", {"page"}) == [rule("realm", "Realm", **{"for": ["page"]})]


def test_the_empty_value_is_a_value_the_group_unknown():
    assert char_rules.add_rule([], "class", "", ["page", "excel"]) == [rule("class", "")]
    assert char_rules.hidden_keys(CHARS, char_rules.add_rule([], "class", "", ["page"]), "page") == {"C-Three"}


def test_the_same_type_and_value_is_one_rule_that_takes_the_targets_of_both_and_keeps_its_place():
    old = [rule("class", "MAGE", **{"for": ["page"]}), rule("char", "A-One")]
    merged = char_rules.add_rule(old, "class", "MAGE", ["excel"])
    assert merged == [rule("class", "MAGE"), rule("char", "A-One")]
    assert char_rules.add_rule(merged, "class", "MAGE", ["page"]) == merged            # nothing new: nothing changes
    assert char_rules.add_rule(old, "class", "MAGE", ["page"]) == old
    assert char_rules.add_rule(old, "class", "DRUID", ["excel"]) == old + [rule("class", "DRUID", **{"for": ["excel"]})]       # another value is another rule


def test_a_rule_that_did_nothing_before_is_replaced_by_the_new_one():
    for weird in ({"for": []}, {"for": "page"}):
        assert char_rules.add_rule([rule("class", "MAGE", **weird)], "class", "MAGE", ["excel"]) == [rule("class", "MAGE", **{"for": ["excel"]})]


@pytest.mark.parametrize("value", ["20", " 20 ", "020"])
def test_a_level_is_kept_as_a_whole_number_as_text(value):
    assert char_rules.add_rule([], "level_below", value, ["page", "excel"]) == [rule("level_below", str(int(value)))]


def test_levels_of_different_numbers_are_different_rules():
    rules = char_rules.add_rule(char_rules.add_rule([], "level_below", "20", ["page"]), "level_below", "50", ["excel"])
    assert rules == [rule("level_below", "20", **{"for": ["page"]}), rule("level_below", "50", **{"for": ["excel"]})]
    assert char_rules.hidden_keys(CHARS, rules, "page") == {"B-Two"} and char_rules.hidden_keys(CHARS, rules, "excel") == {"B-Two", "C-Three"}


@pytest.mark.parametrize("kind, value, targets", [
    ("guild", "x", ["page"]), ("all", "", ["page"]), (None, "x", ["page"]), ("class", None, ["page"]), ("class", 5, ["page"]), ("class", ["MAGE"], ["page"]),
    ("class", "MAGE", []), ("class", "MAGE", None), ("class", "MAGE", ["pdf"]), ("level_below", "0", ["page"]), ("level_below", "", ["page"]),
    ("level_below", "abc", ["page"]), ("level_below", "-5", ["page"]), ("level_below", "1.5", ["page"]), ("level_below", None, ["page"]), ("level_below", 20, ["page"])])
def test_nothing_is_added_for_what_is_no_rule(kind, value, targets):
    old = [rule("char", "A-One")]
    assert char_rules.add_rule(old, kind, value, targets) == old


def test_a_target_that_is_unknown_is_left_out_of_the_rule():
    assert char_rules.add_rule([], "class", "MAGE", ["page", "pdf"]) == [rule("class", "MAGE", **{"for": ["page"]})]


def test_what_is_added_acts_on_each_target_as_it_says():
    for targets, page, excel in ((["page", "excel"], True, True), (["page"], True, False), (["excel"], False, True)):
        rules = char_rules.add_rule([], "class", "MAGE", targets)
        assert (char_rules.hidden_keys(CHARS, rules, "page") == {"A-One"}, char_rules.hidden_keys(CHARS, rules, "excel") == {"A-One"}) == (page, excel)


def test_adding_never_changes_the_list_given():
    old = [rule("class", "MAGE", **{"for": ["page"]}), "text"]
    before = copy.deepcopy(old)
    char_rules.add_rule(old, "class", "MAGE", ["excel"])
    char_rules.add_rule(old, "race", "Orc", ["page"])
    assert old == before


def test_rules_that_are_not_shown_stay_where_they_are_when_one_is_added():
    other = [rule("guild", "x"), "text", rule("class", "GHOST", **{"for": ["excel"]}), rule("level_below", "many")]
    assert char_rules.add_rule(other, "class", "MAGE", ["page"]) == other + [rule("class", "MAGE", **{"for": ["page"]})]


# ---------------------------------------------------------------- taking rules away
def test_rules_are_taken_away_by_their_position_and_the_others_keep_their_order():
    rules = [rule("char", "A-One"), rule("class", "MAGE"), rule("race", "Orc"), rule("faction", "Horde")]
    assert char_rules.remove_rules(rules, [1, 3]) == [rule("char", "A-One"), rule("race", "Orc")]
    assert char_rules.remove_rules(rules, []) == rules and char_rules.remove_rules(rules, None) == rules
    assert char_rules.remove_rules(rules, [0, 1, 2, 3]) == []
    assert char_rules.remove_rules(rules, [7, -1, 2]) == [rule("char", "A-One"), rule("class", "MAGE"), rule("faction", "Horde")]    # a position the list lacks counts for nothing
    assert char_rules.remove_rules(None, [0]) == []


def test_taking_rules_away_never_changes_the_list_given_and_a_set_of_positions_works_too():
    rules = [rule("char", "A-One"), rule("class", "MAGE")]
    before = copy.deepcopy(rules)
    assert char_rules.remove_rules(rules, {0}) == [rule("class", "MAGE")]
    assert rules == before


def test_a_rule_that_was_added_and_taken_away_again_leaves_the_list_as_it_was():
    old = [rule("char", "A-One")]
    assert char_rules.remove_rules(char_rules.add_rule(old, "class", "MAGE", ["page"]), [1]) == old
