# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)
# The bridge between the shown stats page and the blocks (src/app/page_bridge.py): the messages of the page, the answers, what happens with
# a message that is wrong, and the store of presets that lives in the settings. The page itself talking to it is tested in test_main_window.py.

import json
import sys

import pytest

from app import page_bridge
from core import config
from pages.blocks import layout
from test_groups_block import make_payload

PRESET = {"name": "mine", "by": "race", "off": ["level"], "extras": [{"id": 107, "agg": "sum"}]}


@pytest.fixture
def bridge(qapp, instance):
    cfg, _ = config.load()
    return page_bridge.PageBridge(page_bridge.ConfigPresets(cfg)), cfg


def attached(bridge_and_cfg):
    bridge, cfg = bridge_and_cfg
    bridge.attach(json.dumps(make_payload()))
    return bridge, cfg


def ids(answer):
    return {u["id"]: u for u in json.loads(answer)}


# ------------------------------------------------------------------------------------------------------------- the script of Qt
def test_the_script_of_qt_for_the_pages_can_be_read(qapp):
    source = page_bridge.channel_script_source()
    assert "QWebChannel = function" in source or "var QWebChannel" in source or "function QWebChannel" in source
    assert len(source) > 2000


# ---------------------------------------------------------------------------------------------------------- the store of presets
def test_the_presets_are_kept_in_the_settings_file(bridge):
    store = bridge[0].presets
    assert store.load() == [] and store.name_max == config.PRESET_NAME_MAX
    assert store.save([PRESET]) is True
    assert store.load() == [PRESET] and config.load()[0]["group_presets"] == [PRESET]


def test_what_the_store_hands_out_is_a_copy(bridge):
    store = bridge[0].presets
    store.save([PRESET])
    store.load()[0]["off"].append("changed")
    assert store.load() == [PRESET]


def test_the_store_cleans_what_it_is_given_and_says_when_the_file_cannot_be_written(bridge, monkeypatch):
    store, cfg = bridge[0].presets, bridge[1]
    store.save([PRESET, "junk", {"name": "", "by": "x", "off": [], "extras": []}])
    assert [p["name"] for p in store.load()] == ["mine"]

    def broken(_cfg):
        raise OSError("disk full")
    monkeypatch.setattr(config, "save", broken)
    assert store.save([]) is False and [p["name"] for p in store.load()] == ["mine"] and cfg["group_presets"][0]["name"] == "mine"


# --------------------------------------------------------------------------------------------------------------------- attach
def test_attach_answers_with_the_presets_of_the_program(bridge):
    bridge[0].presets.save([PRESET])
    answer = ids(bridge[0].attach(json.dumps(make_payload())))
    assert answer["presetBox"]["hidden"] is False and 'value="mine"' in answer["presetSel"]["html"]


@pytest.mark.parametrize("bad", ["", "not json", "[]", "{}", '{"chars": 5}', "null", "42"])
def test_attach_with_data_that_is_no_page_answers_nothing_and_leaves_no_page_attached(bridge, bad):
    attached(bridge)
    assert bridge[0].attach(bad) == "[]" and bridge[0].view is None


# ------------------------------------------------------------------------------------------------------------------------- act
def test_act_gives_the_parts_of_the_block_that_changed(bridge):
    b, _ = attached(bridge)
    answer = ids(b.act(2, "by", json.dumps({"value": "race", "controls": {}})))
    assert {"groupPick", "groupsWrap"} <= set(answer) and "Mensch" in answer["groupsWrap"]["html"]


def test_the_state_of_the_block_stays_between_two_messages(bridge):
    b, _ = attached(bridge)
    b.act(2, "by", json.dumps({"value": "race"}))
    answer = ids(b.act(2, "group", json.dumps({"key": "Human", "checked": False})))
    assert "Mensch" not in answer["groupsWrap"]["html"] and "Nachtelf" in answer["groupsWrap"]["html"]


def test_a_new_attach_starts_with_a_new_state(bridge):
    b, _ = attached(bridge)
    b.act(2, "by", json.dumps({"value": "race"}))
    b.attach(json.dumps(make_payload()))
    assert b.view.states[2].by == "class"
    answer = ids(b.act(2, "group", json.dumps({"key": "MAGE", "checked": False})))
    assert "Druide" in answer["groupsWrap"]["html"]                 # grouped by class again


@pytest.mark.parametrize("place,args", [(2, "not json"), (2, "[]"), (2, "42"), (2, ""), (99, "{}"), (-1, "{}")])
def test_a_message_that_should_not_have_been_sent_is_answered_with_nothing(bridge, place, args):
    b, _ = attached(bridge)
    assert b.act(place, "by", args) == "[]"


def test_a_message_before_any_page_is_attached_is_answered_with_nothing(bridge):
    b, _ = bridge
    assert b.act(2, "by", "{}") == "[]" and b.select("[]", "{}") == "{}"


def test_an_unknown_action_of_a_block_changes_nothing(bridge):
    b, _ = attached(bridge)
    assert b.act(2, "no_such_action", "{}") == "[]"
    assert b.act(3, "anything", "{}") == "[]"                        # a block without actions


# ----------------------------------------------------------------------------------------------------------------------- select
def test_select_gives_the_blocks_that_depend_on_the_characters_their_changes(bridge):
    b, _ = attached(bridge)
    answer = json.loads(b.select(json.dumps(["A-One", "B-Two"]), json.dumps({"2": {"query": "", "xstat": ""}})))
    updates = {u["id"]: u for u in answer["2"]}
    assert "Magier (2)" in updates["groupPick"]["html"] and "Druide" not in updates["groupPick"]["html"]
    assert b.view.selected == ["A-One", "B-Two"]


@pytest.mark.parametrize("keys,controls", [("not json", "{}"), ("{}", "{}"), ("[]", "not json"), ("[]", "[]")])
def test_select_with_a_wrong_message_answers_nothing(bridge, keys, controls):
    b, _ = attached(bridge)
    assert b.select(keys, controls) == "{}"


def test_keys_that_are_not_text_are_left_out(bridge):
    b, _ = attached(bridge)
    b.select(json.dumps(["A-One", 5, None, "Nobody-Here"]), "{}")
    assert b.view.selected == ["A-One"]


# ---------------------------------------------------------------------------------------------------------------- errors of the program
def test_a_bug_in_a_block_is_reported_and_the_page_gets_nothing(bridge, monkeypatch):
    b, _ = attached(bridge)
    reported = []
    monkeypatch.setattr(sys, "excepthook", lambda *exc: reported.append(exc))

    def broken(*_args, **_kwargs):
        raise RuntimeError("bug")
    monkeypatch.setattr(layout, "dispatch", broken)
    assert b.act(2, "by", "{}") == "[]"
    assert len(reported) == 1 and reported[0][0] is RuntimeError
