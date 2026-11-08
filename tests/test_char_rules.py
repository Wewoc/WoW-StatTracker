# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)
# The rules that keep characters out of the outputs (src/rules/char_rules.py) and their first use: the data of the stats page (page_payload.build_payload).

import copy
import sqlite3

import pytest

from app import stat_parser
from pages import page_payload
from rules import char_rules

CHARS = [
    {"key": "A-One", "class_file": "MAGE", "race_file": "Human", "faction": "Alliance", "level": 80},
    {"key": "B-Two", "class_file": "MAGE", "race_file": "Human", "faction": "Alliance", "level": 19},
    {"key": "C-Three", "class_file": None, "race_file": None, "faction": None, "level": None},
]


def rule(value, **more):
    return {"type": "char", "value": value, **more}


def hidden(rules, target="page"):
    return char_rules.hidden_keys(CHARS, rules, target)


# ---------------------------------------------------------------- the rules
def test_a_rule_of_the_type_char_keeps_that_character_out_and_no_other():
    assert hidden([rule("B-Two")]) == {"B-Two"}
    assert hidden([rule("A-One"), rule("C-Three")]) == {"A-One", "C-Three"}              # several rules: the characters of all of them
    assert hidden([rule("Nobody-Here")]) == set() and hidden([rule("")]) == set()      # a key the data does not have names nobody


def test_a_rule_without_for_applies_to_every_target_and_a_list_to_exactly_those_in_it():
    assert hidden([rule("A-One")], "page") == hidden([rule("A-One")], "excel") == {"A-One"}
    assert hidden([rule("A-One", **{"for": ["excel"]})], "page") == set()
    assert hidden([rule("A-One", **{"for": ["excel"]})], "excel") == {"A-One"}
    assert hidden([rule("A-One", **{"for": ["page"]})], "excel") == set()
    assert hidden([rule("A-One", **{"for": ["page", "excel"]})], "excel") == {"A-One"}
    assert hidden([rule("A-One", **{"for": []})], "page") == set() and hidden([rule("A-One", **{"for": []})], "excel") == set()


def test_nobody_is_kept_out_without_rules_or_for_a_target_this_program_does_not_know():
    assert hidden(None) == set() and hidden([]) == set()
    assert hidden([rule("A-One")], "pdf") == set() and hidden([rule("A-One")], None) == set()
    assert char_rules.TARGETS == ("page", "excel")


def test_an_entry_that_is_no_rule_or_of_a_type_this_program_does_not_know_names_nobody():
    junk = ["text", None, 5, {}, {"value": "A-One"}, {"type": "guild", "value": "A-One"}, {"type": None, "value": "A-One"},
            {"type": "char", "value": "A-One", "for": "page"}]                      # "for" that is no list: applies to no target
    assert hidden(junk) == set()
    assert hidden(junk + [rule("B-Two")]) == {"B-Two"}                              # the good one still counts


def typed(kind, value, **more):
    return {"type": kind, "value": value, **more}


def test_the_types_that_name_a_group_hit_the_characters_of_that_group():
    assert hidden([typed("class", "MAGE")]) == {"A-One", "B-Two"} and hidden([typed("class", "DRUID")]) == set()
    assert hidden([typed("race", "Human")]) == {"A-One", "B-Two"} and hidden([typed("race", "Orc")]) == set()
    assert hidden([typed("faction", "Alliance")]) == {"A-One", "B-Two"} and hidden([typed("faction", "Horde")]) == set()
    assert hidden([typed("realm", "Two")]) == {"B-Two"} and hidden([typed("realm", "Realm")]) == set()            # the realm follows the first hyphen
    assert char_rules.TYPES == ("char", "class", "race", "faction", "realm", "level_below")


def test_the_empty_value_names_the_characters_without_that_value_and_a_real_value_never_does():
    for kind in ("class", "race", "faction"):
        assert hidden([typed(kind, "")]) == {"C-Three"}
    assert hidden([typed("class", None)]) == {"C-Three"}
    assert hidden([typed("class", "mage")]) == set()                                  # not by the text of another case
    assert hidden([typed("class", "DRUID"), typed("race", "Orc"), typed("faction", "Horde")]) == set()     # "C-Three" has none of these values


def test_a_rule_that_would_name_everybody_is_no_rule():
    assert hidden([typed("all", "")]) == set()


def test_level_below_names_the_characters_under_the_level_of_their_newest_scan():
    assert hidden([typed("level_below", "20")]) == {"B-Two"}                          # 19 is under 20
    assert hidden([typed("level_below", "19")]) == set()                              # 19 is not under 19
    assert hidden([typed("level_below", "81")]) == {"A-One", "B-Two"}                 # "C-Three" has no level: never named
    assert hidden([typed("level_below", " 20 ")]) == {"B-Two"} and hidden([typed("level_below", "0")]) == set()


@pytest.mark.parametrize("value", ["", "abc", "-5", "1.5", "²", "20x", None, 20, 20.0, True, [20]])
def test_a_level_that_is_no_whole_number_as_text_names_nobody(value):
    assert hidden([typed("level_below", value)]) == set()


def test_a_level_that_is_no_number_in_the_data_is_never_named():
    chars = [{"key": "X-One", "level": "20"}, {"key": "Y-Two", "level": True}, {"key": "Z-Three"}, {"key": "W-Four", "level": 5}]
    assert char_rules.hidden_keys(chars, [typed("level_below", "50")], "page") == {"W-Four"}


def test_the_new_types_follow_for_like_the_first_one():
    for kind, value in (("class", "MAGE"), ("faction", "Alliance"), ("level_below", "20")):
        assert hidden([typed(kind, value, **{"for": ["excel"]})], "page") == set()
        assert hidden([typed(kind, value, **{"for": ["excel"]})], "excel") != set()
        assert hidden([typed(kind, value, **{"for": []})], "excel") == set()


def test_named_by_gives_the_characters_of_one_rule_in_their_order_whatever_its_targets():
    assert [c["key"] for c in char_rules.named_by(CHARS, typed("class", "MAGE", **{"for": []}))] == ["A-One", "B-Two"]
    assert char_rules.named_by(CHARS, typed("guild", "x")) == [] and char_rules.named_by(CHARS, {}) == []


def test_the_rules_and_the_characters_are_not_changed():
    rules, chars = [rule("A-One", **{"for": ["page"]})], copy.deepcopy(CHARS)
    before = copy.deepcopy(rules)
    char_rules.hidden_keys(chars, rules, "page")
    assert rules == before and chars == CHARS


# ---------------------------------------------------------------- the data of the page
def scan(level, value, extra=""):
    return ('{ scannedAt = "2026-10-01 10:00:00", level = %d, class = "Mage", faction = "Alliance", playedTotal = 3600, playedLevel = 60, '
            'stats = { [1] = "%s" },%s }' % (level, value, extra))


REP = ' rep = { { id = 2698, ord = 1, hdr = true }, { id = 2696, ord = 2, kind = "std", reaction = 5, standing = 3000, lo = 3000, hi = 9000 } },'


@pytest.fixture
def conn(tmp_path):
    """A database with two characters: A-One (with a reputation list) and B-Two."""
    lua = tmp_path / "StatTracker.lua"
    lua.write_text('StatTrackerDB = { version = 4, meta = { [1] = { name = "Kills", cat = "Combat" } }, repMeta = { [2696] = { name = "Amani" } }, '
                   'chars = { ["A-One"] = %s, ["B-Two"] = %s } }' % (scan(80, "5", REP), scan(70, "7")), encoding="utf-8")
    stat_parser.main(["--input", str(lua), "--db", str(tmp_path / "x.db"), "--output", str(tmp_path / "x.html")])
    connection = sqlite3.connect(tmp_path / "x.db")
    yield connection
    connection.close()


def payload(conn, rules=None):
    result = page_payload.build_payload(conn, "en", rules=rules)
    result.pop("generated")                              # the minute it was made
    return result


def test_the_payload_without_rules_is_what_it_was_and_both_characters_are_in_it(conn):
    assert [c["key"] for c in payload(conn)["chars"]] == ["A-One", "B-Two"]
    assert payload(conn, []) == payload(conn, None) == payload(conn)


def test_a_character_the_rules_keep_off_the_page_is_in_no_part_of_the_payload(conn):
    result = payload(conn, [rule("A-One")])
    assert [c["key"] for c in result["chars"]] == ["B-Two"]
    assert all(set(stat["v"]) <= {"B-Two"} for stat in result["stats"]) and any("B-Two" in stat["v"] for stat in result["stats"])
    assert all(set(role["chars"]) <= {"B-Two"} for role in result["derived"]["roles"])
    assert "rep" not in result                           # the only reputation list was A-One's
    assert "A-One" not in repr(result)


def test_the_other_types_keep_characters_off_the_page_by_what_the_database_holds(conn):
    def keys(rules):
        return [c["key"] for c in payload(conn, rules)["chars"]]
    assert keys([typed("level_below", "75")]) == ["A-One"]                            # B-Two is level 70
    assert keys([typed("faction", "Alliance")]) == [] and keys([typed("faction", "Horde")]) == ["A-One", "B-Two"]
    assert keys([typed("realm", "One")]) == ["B-Two"]
    assert keys([typed("class", "MAGE")]) == ["A-One", "B-Two"]                       # the file has no class file name: a real value names nobody
    assert keys([typed("class", "")]) == []                                           # the group "unknown" is both of them


def test_the_reputation_of_the_other_character_stays(conn):
    result = payload(conn, [rule("B-Two")])
    assert [c["key"] for c in result["chars"]] == ["A-One"] and list(result["rep"]["chars"]) == ["A-One"]


def test_a_rule_for_excel_only_changes_nothing_on_the_page_and_a_rule_for_the_page_does(conn):
    assert payload(conn, [rule("A-One", **{"for": ["excel"]})]) == payload(conn)
    assert [c["key"] for c in payload(conn, [rule("A-One", **{"for": ["page"]})])["chars"]] == ["B-Two"]


def test_with_every_character_kept_off_the_page_the_payload_has_none_and_does_not_fail(conn):
    result = payload(conn, [rule("A-One"), rule("B-Two")])
    assert result["chars"] == [] and all(stat["v"] == {} for stat in result["stats"]) and "rep" not in result


HISTORY = {"dir": "history", "links": {"A-One": {"href": "history-A_One-11111111.html", "scans": 2},
                                       "B-Two": {"href": "history-B_Two-22222222.html", "scans": 3}}}


def test_the_links_of_a_character_kept_off_the_page_are_not_in_the_data_of_the_page_either(conn):
    result = page_payload.build_payload(conn, "en", history=HISTORY, rules=[rule("A-One")])
    assert result["history"] == {"dir": "history", "links": {"B-Two": HISTORY["links"]["B-Two"]}}
    assert "A-One" not in repr(result) and "A_One" not in repr(result)
    assert set(HISTORY["links"]) == {"A-One", "B-Two"}                                   # the links that were handed in are not changed


def test_without_a_link_left_the_payload_has_no_history_and_without_rules_it_keeps_what_it_was_given(conn):
    assert "history" not in page_payload.build_payload(conn, "en", history=HISTORY, rules=[rule("A-One"), rule("B-Two")])
    assert page_payload.build_payload(conn, "en", history=HISTORY)["history"] == HISTORY
    assert page_payload.build_payload(conn, "en", history=HISTORY, rules=[rule("A-One", **{"for": ["excel"]})])["history"] == HISTORY


def test_the_database_is_not_changed_by_the_rules(conn):
    before = conn.execute("SELECT COUNT(*) FROM scans").fetchone()[0], conn.execute("SELECT COUNT(*) FROM stat_values").fetchone()[0]
    payload(conn, [rule("A-One"), rule("B-Two")])
    assert (conn.execute("SELECT COUNT(*) FROM scans").fetchone()[0], conn.execute("SELECT COUNT(*) FROM stat_values").fetchone()[0]) == before
