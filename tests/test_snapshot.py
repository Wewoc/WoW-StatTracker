# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)
# The snapshot of the stats page ("Open in browser"): the same blocks written again from what the shown page holds (the ticked characters, the state of the
# blocks and the values their controls last had), in a file that works without the program. Tests of the View (copy, controls), of the blocks that write
# controls into the page, of outputs.write_snapshot and of the name of the file; the window and the browser are tested in test_main_window.py.

import json
import re
from pathlib import Path

from core import i18n
from game import wow_install
from pages import outputs
from pages.blocks import layout, reputation, stat_table
from pages.blocks.view import View
from test_groups_block import make_payload

TEMPLATE = (Path(__file__).resolve().parent.parent / "src" / "template.html").read_text(encoding="utf-8")


class Store:
    name_max = 40

    def load(self):
        return [{"name": "p", "by": "race", "off": [], "extras": []}]

    def save(self, items):
        return True


def controls_of(**values):
    return {"controls": values}


def session():
    """A page as a person used it: two characters ticked, a search and a category in the table, sorted by a character, grouped by race with an extra
    statistic, a search in the reputation. Returns (view, the last answer of each block as {place: {id: update}})."""
    payload = make_payload()
    view = View(payload, presets=Store())
    last = {}

    def keep(place, updates):
        last[place] = {u["id"]: u for u in updates}

    answers = layout.select(view, ["A-One", "B-Two"], {})
    for place, updates in answers.items():
        keep(place, updates)
    keep(8, layout.dispatch(view, 8, "filter", controls_of(query="e", category="", only_diff=False, hide_empty=True)))
    keep(8, layout.dispatch(view, 8, "sort", {"key": "A-One", **controls_of(query="e", category="", only_diff=False, hide_empty=True)}))
    keep(2, layout.dispatch(view, 2, "by", {"value": "race", **controls_of(by="race", query="", xstat="", xagg="sum", preset="", name="")}))
    keep(2, layout.dispatch(view, 2, "add", controls_of(by="race", query="", xstat="107", xagg="max", preset="", name="")))
    keep(5, layout.dispatch(view, 5, "query", controls_of(query="friend")))
    return view, last


def inner(html, element):
    return re.search(rf'<div[^>]* id="{element}"[^>]*>(.*?)</div>', html, re.S).group(1)


# ----------------------------------------------------------------------------------------------------------------------- the View
def test_the_copy_of_a_view_is_apart_from_the_original_and_has_no_store_of_presets():
    view, _ = session()
    other = view.snapshot()
    assert other.selected == ["A-One", "B-Two"] and other.presets is None and view.presets is not None
    assert other.controls == view.controls and other.controls is not view.controls
    other.select(["C-Three"])
    other.controls[8]["query"] = "changed"
    other.states[8].sort_char = None
    assert view.selected == ["A-One", "B-Two"] and view.controls[8]["query"] == "e" and view.states[8].sort_char == "A-One"


def test_the_layout_remembers_the_controls_of_every_block_that_spoke():
    view, _ = session()
    assert view.controls[8]["query"] == "e" and view.controls[5] == {"query": "friend"} and view.controls[2]["xstat"] == "107"
    layout.select(view, ["A-One"], {"8": {"query": "zz"}, "99": {"x": 1}, "x": {"y": 2}, "5": "no dict"})
    assert view.controls[8] == {"query": "zz"} and view.controls[5] == {"query": "friend"} and set(view.controls) == {2, 5, 8}


# ------------------------------------------------------------------------------------------------ blocks write the controls into the page
def test_the_table_block_writes_the_controls_it_was_given_into_its_elements():
    payload = make_payload()
    view = View(payload)
    view.controls[8] = {"query": 'ed "x"', "category": "Wealth", "only_diff": True, "hide_empty": False}
    html = stat_table.render(payload, view, slot=8)
    assert 'value="ed &quot;x&quot;"' in html and 'data-committed="ed &quot;x&quot;"' in html
    assert '<option value="Wealth" selected>Wealth</option>' in html and html.count(" selected>") == 1
    assert re.search(r'<input type="checkbox" id="diff" checked data-name', html)
    assert re.search(r'<input type="checkbox" id="hideEmpty" data-name', html)
    assert 'id="count">0 of 5 statistics<' in html


def test_a_category_the_page_does_not_have_selects_nothing():
    payload = make_payload()
    view = View(payload)
    view.controls[8] = {"category": "Gone"}
    assert " selected>" not in stat_table.render(payload, view, slot=8)


def test_the_reputation_block_writes_the_search_text_into_its_box_and_filters_by_it():
    payload = make_payload()
    view = View(payload)
    view.controls[5] = {"query": 'friend"'}
    html = reputation.render(payload, view, slot=5)
    assert 'value="friend&quot;"' in html and 'id="repNone"' in html
    view.controls[5] = {"query": "friend"}
    wrap = reputation.render(payload, view, slot=5).split('id="repWrap"')[1].split('id="repMissing"')[0]
    assert "Friend Faction" in wrap and "Faction One" not in wrap and "Renown Faction" not in wrap


def test_without_controls_the_blocks_write_the_same_as_before():
    payload = make_payload()
    assert layout.fill(TEMPLATE, payload, View(payload)) == layout.fill(TEMPLATE, payload, View(payload).snapshot()) == layout.fill(TEMPLATE, payload)
    assert 'value="' not in stat_table.render(payload, View(payload), slot=8).split('id="cat"')[0].split('id="q"')[1]


# ------------------------------------------------------------------------------------------- the page as the shown page had it
def test_the_snapshot_shows_what_the_last_answers_of_the_blocks_put_into_the_page():
    view, last = session()
    page = layout.fill(TEMPLATE, view.payload, view.snapshot())
    assert inner(page, "count") == last[8]["count"]["html"]
    assert re.search(r'<table id="t">(.*?)</table>', page, re.S).group(1) == last[8]["t"]["html"]
    assert re.search(r'<table id="rpt">(.*?)</table>', page, re.S).group(1) == re.search(r'<table id="rpt">(.*?)</table>', last[5]["repWrap"]["html"], re.S).group(1)
    assert last[2]["groupsWrap"]["html"] in page and last[2]["extraChips"]["html"] in page and last[2]["extraChips"]["hidden"] is False
    assert '<option value="race" selected>Race</option>' in page
    assert inner(page, "chars").count(" checked>") == 2 and 'id="chk_A-One" data-pick data-name="A-One" checked>' in page
    assert 'id="chk_C-Three" data-pick data-name="C-Three">' in page and ">Select all</button>" in page


def test_the_snapshot_has_no_row_of_presets_and_the_shown_page_keeps_its_own():
    view, _ = session()
    page = layout.fill(TEMPLATE, view.payload, view.snapshot())
    assert re.search(r'<div id="presetBox" hidden>', page)
    live = layout.fill(TEMPLATE, view.payload, view)
    assert '<div id="presetBox">' in live and "p</option>" in live


def test_writing_a_snapshot_changes_nothing_in_the_view():
    view, _ = session()
    before = (list(view.selected), json.dumps(view.controls, sort_keys=True), view.states[8].sort_char, view.states[2].by)
    layout.fill(TEMPLATE, view.payload, view.snapshot())
    assert (list(view.selected), json.dumps(view.controls, sort_keys=True), view.states[8].sort_char, view.states[2].by) == before


# ----------------------------------------------------------------------------------------------------------------------------- the file
def test_write_snapshot_writes_the_blocks_as_shown_and_says_it_is_a_snapshot(tmp_path):
    view, _ = session()
    out = tmp_path / "stats_snapshot.html"
    outputs.write_snapshot(view, out, "2026-11-05 21:30")
    text = out.read_text(encoding="utf-8")
    data = json.loads(re.search(r"const DATA = (.*?);\s*const \$ =", text, re.S).group(1).replace("<\\/", "</"))
    assert data["snapshot"] == {"when": "2026-11-05 21:30"} and data["chars"] == view.payload["chars"]
    assert "UI.snapshot" in text and i18n.html_strings("en")["snapshot"] in text
    assert 'id="chk_C-Three" data-pick data-name="C-Three">' in text and re.search(r'<div id="presetBox" hidden>', text)
    assert "snapshot" not in view.payload                                            # the payload of the shown page is not changed


def test_the_ordinary_page_has_no_snapshot_field(tmp_path):
    out = tmp_path / "stats.html"
    outputs.write_html(make_payload(), out)
    assert '"snapshot": {' not in out.read_text(encoding="utf-8")                  # (the text of the line is in the page texts, the time is not)


def test_the_page_script_adds_the_line_only_for_a_snapshot_with_a_text():
    assert 'if (DATA.snapshot && UI.snapshot) $("gen").textContent += " · " + fmt(UI.snapshot, DATA.snapshot);' in TEMPLATE


def test_the_texts_of_the_snapshot_exist_in_both_languages_with_the_same_marks():
    for lang in ("de", "en"):
        assert "{when}" in i18n.html_strings(lang)["snapshot"]
    assert i18n.html_strings("de")["snapshot"] != i18n.html_strings("en")["snapshot"]
    assert "{error}" in i18n._STRINGS["log_snapshot_fail"]["de"] and "{error}" in i18n._STRINGS["log_snapshot_fail"]["en"]


def test_the_snapshot_file_sits_next_to_the_stats_page_of_each_game_version():
    assert wow_install.snapshot_file("_retail_").name == "stats_snapshot.html"
    assert wow_install.snapshot_file("_anniversary_").name == "stats_anniversary_snapshot.html"
    for variant in ("_retail_", "_anniversary_"):
        assert wow_install.snapshot_file(variant).parent == wow_install.out_files(variant)[1].parent


def test_the_groups_block_writes_the_choice_for_a_statistic_to_add_into_its_elements():
    from pages.blocks import groups
    payload = make_payload()
    view = View(payload)
    view.controls[2] = {"query": 'cre"', "xstat": "107", "xagg": "avg"}
    html = groups.render(payload, view, slot=2)
    assert 'value="cre&quot;"' in html.split('id="xq"')[1].split(">")[0]
    assert '<option value="avg" selected>' in html.split('id="xagg"')[1].split("</select>")[0]
    view.controls[2] = {"query": "cre", "xstat": "107", "xagg": "avg"}
    html = groups.render(payload, view, slot=2)
    assert '<option value="107" selected>Creatures killed (Combat)</option>' in html and "Gold earned" not in html.split('id="xstat"')[1].split("</select>")[0]
    view.controls[2] = {"xagg": "bogus"}
    assert '<option value="sum" selected>' in groups.render(payload, view, slot=2)
