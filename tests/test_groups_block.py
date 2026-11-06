# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)
# The Groups block of the stats page (src/pages/blocks/groups.py): what it shows, and what each action of the page changes.
# The numbers behind it are tested in test_group_rules.py; here: the text, the elements, the answers to clicks, the presets.

import json
import re

import pytest

from core import i18n
from pages.blocks import groups, layout
from pages.blocks.view import View
from rules import stat_derive

SLOT = 2


def make_payload(lang="en"):
    chars = [
        {"key": "A-One", "class": "Magier", "class_file": "MAGE", "race": "Mensch", "race_file": "Human", "faction": "Alliance", "level": 80,
         "scanned_at": "2026-10-01 10:00:00"},
        {"key": "B-Two", "class": "Magier", "class_file": "MAGE", "race": "Mensch", "race_file": "Human", "faction": "Alliance", "level": 60,
         "scanned_at": "2026-10-02 10:00:00"},
        {"key": "C-Three", "class": "Druide", "class_file": "DRUID", "race": "Nachtelf", "race_file": "NightElf", "faction": "Alliance", "level": 70,
         "scanned_at": "2026-10-03 10:00:00"},
        {"key": "D-Four", "class": "", "class_file": None, "race": "", "race_file": None, "faction": None, "level": None, "scanned_at": "2026-10-04 10:00:00"},
    ]
    stats = [
        {"id": -1, "name": "Played", "cat": "Time", "v": {"A-One": ["x", 7200], "B-Two": ["x", 7200], "C-Three": ["x", 3600 * 3]}},
        {"id": 107, "name": "Creatures killed", "cat": "Combat", "v": {"A-One": ["1.000", 1000], "B-Two": ["500", 500], "C-Three": ["--", None]}},
        {"id": 328, "name": "Gold earned", "cat": "Wealth", "gold": True, "v": {"A-One": ["5g", 50000], "B-Two": ["1g", 10000]}},
        {"id": 5, "name": "Only text", "cat": "Misc", "v": {"A-One": ["a", None]}},
        {"id": 6, "name": 'Bad <b>"name"</b>', "cat": "M&M", "v": {"A-One": ["1", 1]}},
    ]
    derived = stat_derive.compute(stats, [c["key"] for c in chars])
    for role in derived["roles"]:
        role["label"] = role["role"]
    rep = {"defs": {10: "The War Within", 15: "Delves", 11: "Faction One", 12: "Friend Faction", 13: "Renown Faction", 14: "Faction Two"},
           "chars": {
               "A-One": [{"id": 10, "hdr": 1}, {"id": 15, "hdr": 1, "child": 1},
                         {"id": 11, "kind": "std", "reaction": 4, "standing": 1500, "lo": 0, "hi": 3000},
                         {"id": 12, "kind": "friend", "level": 2, "max_level": 8, "standing": 50, "lo": 0, "hi": 100},
                         {"id": 13, "kind": "major", "aw": 1, "renown": 5, "max_renown": 20, "earned": 150, "need": 2500}],
               "B-Two": [{"id": 10, "hdr": 1}, {"id": 15, "hdr": 1, "child": 1},
                         {"id": 11, "kind": "std", "reaction": 8, "standing": 21000, "lo": 21000, "hi": 21000},
                         {"id": 13, "kind": "major", "aw": 1, "renown": 7, "max_renown": 20, "earned": 300, "need": 2500},
                         {"id": 14, "kind": "std", "reaction": 4, "standing": 10, "lo": 0, "hi": 20,
                          "par": {"value": 25000, "threshold": 10000, "pending": 1}}]}}
    return {"lang": lang, "ui": i18n.html_strings(lang), "chars": chars, "stats": stats, "derived": derived, "rep": rep,
            "names": {"class": {"MAGE": "Magier", "DRUID": "Druide"}, "race": {"Human": "Mensch", "NightElf": "Nachtelf"},
                      "standing": i18n.names("standing_", lang)}}


class Store:
    """The store of presets the window gives (in memory)."""
    name_max = 12

    def __init__(self, items=(), ok=True):
        self.items, self.ok, self.saves = list(items), ok, 0

    def load(self):
        return [dict(p) for p in self.items]

    def save(self, items):
        self.saves += 1
        if self.ok:
            self.items = [dict(p) for p in items]
        return self.ok


def page(payload=None, store=None):
    payload = payload or make_payload()
    view = View(payload, presets=store)
    return payload, view, groups.render(payload, view, slot=SLOT)


def act(payload, view, action, **args):
    return {u["id"]: u for u in groups.handle(payload, view, SLOT, action, args)}


def table_rows(html):
    """[[cell text, ...], ...] of the rows of the group table (tags stripped, the small texts joined to the cell)."""
    body = html.split("<tbody>")[1].split("</tbody>")[0]
    return [[re.sub(r"<[^>]+>", " ", cell).split() for cell in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row)]
            for row in re.findall(r"<tr[^>]*>(.*?)</tr>", body)]


def labels(rows):
    return [" ".join(r[0]) for r in rows]


# ----------------------------------------------------------------------------------------------------- what the block shows
def test_the_block_has_the_elements_and_ids_of_the_old_page():
    _, _, html = page()
    for part in ('<details class="rates groups" id="groups">', 'id="groupsTitle"', 'id="groupBy"', 'id="groupPick"', 'id="figures"', 'id="xq"',
                 'id="xstat"', 'id="xagg"', 'id="xadd"', 'id="extraChips"', 'id="extraNote"', 'id="groupsNone"', 'id="groupsWrap"',
                 '<table id="gt">', 'id="groupsNote"', 'id="presetBox"'):
        assert part in html, part


def test_at_the_start_every_character_is_ticked_and_the_first_grouping_is_class():
    payload, view, html = page()
    assert '<option value="class" selected>Class</option>' in html
    pick = html.split('id="groupPick">')[1].split("</div>")[0]
    assert pick.count("<input") == 3 and pick.count(" checked") == 3              # Druide, Magier, unknown
    assert "Magier (2)" in pick and "unknown (1)" in pick
    rows = table_rows(html)
    assert labels(rows) == ["Druide", "Magier", "unknown", "Total"]
    assert 'class="total"' in html and html.count("<tr") == 1 + 4


def test_the_first_table_row_values_in_the_page_language():
    en = table_rows(page(make_payload("en"))[2])
    de = table_rows(page(make_payload("de"))[2])
    assert en[1][1] == ["2"] and en[1][2] == ["70.0"]                           # Magier: 2 characters, average level of 80 and 60
    assert de[1][2] == ["70,0"] and de[1][3] == ["4,0", "Std."]                  # 4 hours of played time (two characters of 2 h)
    assert de[3][3][:2] == ["7,0", "Std."]                                       # the total: 2 + 2 + 3 hours, the fourth has none


def test_the_total_row_counts_all_groups_shown():
    rows = table_rows(page()[2])
    total = rows[-1]
    assert total[1] == ["4"]                                                      # four characters
    assert total[2][0] == "70.0" and "of" in total[2]                             # level of three of them: "3 of 4 characters"


def test_a_missing_value_shows_a_dash_and_no_value():
    payload, view, html = page()
    unknown = table_rows(html)[2]
    assert unknown[2][0] == "–" and "no" in unknown[2] and "value" in unknown[2]


def test_the_texts_come_from_the_payload_in_its_language():
    html_de = page(make_payload("de"))[2]
    assert "Gruppieren nach" in html_de and "Angezeigte Gruppen" in html_de and "Kennzahlen" in html_de
    assert "Group by" in page(make_payload("en"))[2]


def test_the_note_names_the_minimum_of_played_hours():
    payload = make_payload()
    html = page(payload)[2]
    assert str(int(payload["derived"]["min_played_seconds"] // 3600)) + " h" in html.split('id="groupsNote">')[1]


def test_names_and_texts_with_markup_cannot_break_out_of_the_block():
    payload = make_payload()
    payload["chars"][0]["key"] = '<img src=x>-R"1'
    payload["stats"][0]["v"] = {'<img src=x>-R"1': ["x", 7200]}
    payload["names"]["class"]["MAGE"] = "<script>alert(1)</script>"
    html = page(payload)[2]
    assert "<script>" not in html and "<img" not in html and "<b>" not in html
    updates = groups.handle(payload, View(payload), SLOT, "add", {"controls": {"xstat": "6", "xagg": "sum"}})
    assert "<b>" not in "".join(u.get("html", "") for u in updates)


def test_the_page_without_presets_hides_the_row_and_with_a_store_shows_it():
    assert 'id="presetBox" hidden>' in page()[2]
    html = page(store=Store([{"name": "mine", "by": "race", "off": [], "extras": []}]))[2]
    assert '<div id="presetBox">' in html and '<option value="mine">mine</option>' in html and 'maxlength="12"' in html
    assert "disabled" in html.split('id="presetDel"')[1].split(">")[0]


def test_what_is_in_the_block_is_the_same_every_time():
    payload = make_payload()
    assert groups.render(payload, View(payload), slot=SLOT) == groups.render(payload, View(payload), slot=SLOT)


# --------------------------------------------------------------------------------------------------- the answers to the page
def test_another_grouping_changes_the_pick_and_the_table_only():
    payload, view, _ = page()
    updates = act(payload, view, "by", value="race")
    assert set(updates) == {"groupPick", "groupsNone", "groupsWrap"}
    assert labels(table_rows(updates["groupsWrap"]["html"])) == ["Mensch", "Nachtelf", "unknown", "Total"]
    assert "Mensch (2)" in updates["groupPick"]["html"]
    assert act(payload, view, "by", value="nonsense") and view.states[SLOT].by == "race"          # an unknown grouping is ignored


def test_the_faction_and_the_realm_are_groupings_too():
    payload, view, _ = page()
    rows = table_rows(act(payload, view, "by", value="faction")["groupsWrap"]["html"])
    assert labels(rows) == ["Alliance", "unknown", "Total"]
    rows = table_rows(act(payload, view, "by", value="realm")["groupsWrap"]["html"])
    assert labels(rows) == ["Four", "One", "Three", "Two", "Total"]


def test_unticking_a_group_takes_it_out_of_the_rows_and_the_total_and_ticking_it_again_brings_it_back():
    payload, view, _ = page()
    rows = table_rows(act(payload, view, "group", key="MAGE", checked=False)["groupsWrap"]["html"])
    assert labels(rows) == ["Druide", "unknown", "Total"] and rows[-1][1] == ["2"]
    rows = table_rows(act(payload, view, "group", key="MAGE", checked=True)["groupsWrap"]["html"])
    assert labels(rows) == ["Druide", "Magier", "unknown", "Total"]


def test_the_unknown_group_is_unticked_by_an_empty_key():
    payload, view, _ = page()
    rows = table_rows(act(payload, view, "group", key="", checked=False)["groupsWrap"]["html"])
    assert "unknown" not in labels(rows) and view.states[SLOT].hidden["class"] == {None}


def test_the_unticked_groups_are_remembered_per_grouping():
    payload, view, _ = page()
    act(payload, view, "group", key="MAGE", checked=False)
    act(payload, view, "by", value="race")
    assert "Mensch" in labels(table_rows(act(payload, view, "by", value="race")["groupsWrap"]["html"]))
    assert "Magier" not in labels(table_rows(act(payload, view, "by", value="class")["groupsWrap"]["html"]))


def test_unticking_a_figure_takes_its_column_out():
    payload, view, _ = page()
    html = act(payload, view, "figure", id="level", checked=False)["groupsWrap"]["html"]
    assert "Avg. level" not in html and "Characters" in html
    assert 'id="fig_level"' in groups.render(payload, view, slot=SLOT) and " checked" not in re.search(r'<input[^>]*id="fig_level"[^>]*>', groups.render(payload, view, slot=SLOT)).group(0)


def test_a_search_narrows_the_statistics_that_can_be_added_and_keeps_the_one_chosen():
    payload, view, _ = page()
    update = act(payload, view, "query", controls={"query": "", "xstat": "328"})["xstat"]["html"]
    assert update.count("<option") == 3 and '<option value="328" selected>Gold earned (Wealth)</option>' in update      # 107, 328, 6 (not the text, not -1)
    narrowed = act(payload, view, "query", controls={"query": "gold", "xstat": "107"})["xstat"]["html"]
    assert narrowed.count("<option") == 1 and "selected" not in narrowed                                         # the chosen one is gone: the first stays


def test_adding_a_statistic_adds_a_chip_and_a_column_and_a_duplicate_does_nothing():
    payload, view, _ = page()
    updates = act(payload, view, "add", controls={"xstat": "107", "xagg": "sum"})
    assert set(updates) == {"extraChips", "groupsNone", "groupsWrap"}
    assert updates["extraChips"]["hidden"] is False and "Creatures killed (Sum)" in updates["extraChips"]["html"]
    assert act(payload, view, "add", controls={"xstat": "107", "xagg": "sum"}) == {}
    assert act(payload, view, "add", controls={"xstat": "107", "xagg": "avg"})["extraChips"]["html"].count('class="chip"') == 2


def test_the_added_statistic_is_combined_for_the_group():
    payload, view, _ = page()
    rows = table_rows(act(payload, view, "add", controls={"xstat": "107", "xagg": "sum"})["groupsWrap"]["html"])
    assert labels(rows) == ["Druide", "Magier", "unknown", "Total"]
    assert rows[1][-1] == ["1,500"]                                                 # Magier: 1000 + 500
    assert rows[0][-1][0] == "–"                                               # Druide: no number
    assert rows[-1][-1][:1] == ["1,500"] and "of" in rows[-1][-1]


def test_a_gold_statistic_is_shown_in_gold_and_a_wrong_value_is_not_added():
    payload, view, _ = page()
    rows = table_rows(act(payload, view, "add", controls={"xstat": "328", "xagg": "sum"})["groupsWrap"]["html"])
    assert rows[1][-1][:2] == ["6.00", "g"]                                         # 60000 copper = 6 gold
    for controls in ({"xstat": "", "xagg": "sum"}, {"xstat": "x", "xagg": "sum"}, {"xstat": "107", "xagg": "median"}, {"xstat": "-1", "xagg": "sum"}, {}):
        assert act(payload, view, "add", controls=controls) == {}


def test_a_statistic_added_can_be_removed_and_the_chip_row_hides_when_empty():
    payload, view, _ = page()
    act(payload, view, "add", controls={"xstat": "107", "xagg": "sum"})
    updates = act(payload, view, "remove", index=0)
    assert updates["extraChips"] == {"id": "extraChips", "html": "", "hidden": True}
    assert "Creatures" not in updates["groupsWrap"]["html"]
    assert act(payload, view, "remove", index=5)["extraChips"]["hidden"] is True        # out of range: nothing happens, no error


def test_changing_the_ticked_characters_changes_the_pick_the_choices_and_the_table():
    payload, view, _ = page()
    answers = layout_select(payload, view, ["A-One", "B-Two"])
    updates = {u["id"]: u for u in answers[SLOT]}
    assert "Magier (2)" in updates["groupPick"]["html"] and "Druide" not in updates["groupPick"]["html"]
    assert labels(table_rows(updates["groupsWrap"]["html"])) == ["Magier", "Total"]
    assert updates["xstat"]["html"].count("<option") == 3                      # 107, 328, 6: these two have numbers
    only_druid = {u["id"]: u for u in layout_select(payload, view, ["C-Three"])[SLOT]}
    assert only_druid["xstat"]["html"] == ""                                   # the druid has no number in any statistic: nothing to add


def test_with_no_character_ticked_the_table_is_replaced_by_a_notice():
    payload, view, _ = page()
    updates = {u["id"]: u for u in layout_select(payload, view, [])[SLOT]}
    assert updates["groupsNone"] == {"id": "groupsNone", "html": "No characters selected.", "hidden": False}
    assert updates["groupsWrap"]["hidden"] is True and updates["groupPick"]["html"].count("<input") == 0


def test_an_unknown_action_changes_nothing():
    payload, view, _ = page()
    assert groups.handle(payload, view, SLOT, "nonsense", {}) == []
    assert groups.handle(payload, view, SLOT, "preset_save", {}) == []                # no store: no presets


def test_every_answer_can_be_sent_as_json():
    payload, view, _ = page(store=Store())
    for action, args in (("by", {"value": "race"}), ("group", {"key": "", "checked": False}), ("figure", {"id": "chars", "checked": False}),
                         ("add", {"controls": {"xstat": "107", "xagg": "max"}}), ("query", {"controls": {"query": "x"}}),
                         ("preset_save", {"controls": {"name": "p"}}), ("preset_apply", {"controls": {"preset": "p"}})):
        json.dumps(groups.handle(payload, view, SLOT, action, args))


def layout_select(payload, view, keys, controls=None):
    """What layout.select gives for this block (the block is put in a place of the index for the call)."""
    saved = (dict(layout.INDEX), dict(layout.MODULES))
    layout.INDEX[SLOT] = ("groups", {})
    try:
        return layout.select(view, keys, controls)
    finally:
        layout.INDEX.clear()
        layout.INDEX.update(saved[0])


# ------------------------------------------------------------------------------------------------------------ the presets
def test_a_preset_remembers_the_grouping_the_figures_and_the_statistics_added():
    store = Store()
    payload, view, _ = page(store=store)
    act(payload, view, "by", value="race")
    act(payload, view, "figure", id="level", checked=False)
    act(payload, view, "add", controls={"xstat": "107", "xagg": "max"})
    updates = act(payload, view, "preset_save", controls={"name": "  my set  "})
    assert store.items == [{"name": "my set", "by": "race", "off": ["level"], "extras": [{"id": 107, "agg": "max"}]}]
    assert '<option value="my set" selected>my set</option>' in updates["presetSel"]["html"]
    assert updates["presetDel"] == {"id": "presetDel", "disabled": False} and updates["presetMsg"]["html"] == ""


def test_a_preset_with_the_same_name_is_replaced_and_the_name_is_cut_to_the_length_of_the_store():
    store = Store([{"name": "x" * 12, "by": "class", "off": [], "extras": []}])
    payload, view, _ = page(store=store)
    act(payload, view, "by", value="faction")
    act(payload, view, "preset_save", controls={"name": "x" * 30})
    assert len(store.items) == 1 and store.items[0]["by"] == "faction" and store.items[0]["name"] == "x" * 12


def test_an_empty_name_saves_nothing():
    store = Store()
    payload, view, _ = page(store=store)
    assert groups.handle(payload, view, SLOT, "preset_save", {"controls": {"name": "   "}}) == [] and store.saves == 0


def test_a_preset_that_cannot_be_saved_says_so_and_changes_nothing():
    store = Store(ok=False)
    payload, view, _ = page(store=store)
    updates = act(payload, view, "preset_save", controls={"name": "p"})
    assert updates["presetMsg"]["html"] == i18n.html_strings("en")["groups_preset_failed"] and store.items == []
    assert "<option value=\"p\"" not in updates["presetSel"]["html"]


def test_applying_a_preset_sets_the_grouping_the_figures_and_the_statistics_added_and_keeps_the_groups_unticked():
    store = Store([{"name": "p", "by": "race", "off": ["level", "no_such_figure"], "extras": [{"id": 107, "agg": "avg"}, {"id": 99999, "agg": "sum"},
                                                                                          {"id": 107, "agg": "avg"}, {"id": 107, "agg": "median"}, "junk"]}])
    payload, view, _ = page(store=store)
    act(payload, view, "group", key="MAGE", checked=False)
    updates = act(payload, view, "preset_apply", controls={"preset": "p"})
    state = view.states[SLOT]
    assert state.by == "race" and state.figures_off == {"level"} and state.extras == [(107, "avg")]
    assert state.hidden["class"] == {"MAGE"}
    assert '<option value="race" selected>Race</option>' in updates["groupBy"]["html"]
    assert "Avg. level" not in updates["groupsWrap"]["html"] and "Creatures killed (Average)" in updates["extraChips"]["html"]
    assert 'value="p" selected' in updates["presetSel"]["html"] and updates["presetDel"]["disabled"] is False
    fig_level = re.search(r'<input[^>]*id="fig_level"[^>]*>', updates["figures"]["html"]).group(0)
    assert " checked" not in fig_level


def test_choosing_no_preset_changes_the_block_not_and_disables_delete():
    store = Store([{"name": "p", "by": "race", "off": [], "extras": []}])
    payload, view, _ = page(store=store)
    updates = act(payload, view, "preset_apply", controls={"preset": ""})
    assert view.states[SLOT].by == "class" and updates["presetDel"]["disabled"] is True


def test_deleting_a_preset_removes_it_and_chooses_none():
    store = Store([{"name": "p", "by": "race", "off": [], "extras": []}, {"name": "q", "by": "class", "off": [], "extras": []}])
    payload, view, _ = page(store=store)
    updates = act(payload, view, "preset_delete", controls={"preset": "p"})
    assert [p["name"] for p in store.items] == ["q"] and '<option value="p"' not in updates["presetSel"]["html"]
    assert updates["presetDel"]["disabled"] is True
    assert groups.handle(payload, view, SLOT, "preset_delete", {"controls": {"preset": ""}}) == []


def test_a_preset_that_cannot_be_deleted_says_so():
    store = Store([{"name": "p", "by": "race", "off": [], "extras": []}], ok=False)
    payload, view, _ = page(store=store)
    assert act(payload, view, "preset_delete", controls={"preset": "p"})["presetMsg"]["html"] == i18n.html_strings("en")["groups_preset_failed"]
