# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)
# The main block of the stats page (src/pages/blocks/stat_table.py): the filter row, the counter and the table, and how they answer the search, the
# choices, a click on a column head and the ticked characters. The rules behind it are tested in test_table_rules.py.

import json
import re

from pages.blocks import layout, stat_table
from pages.blocks.view import View
from test_blocks import assert_well_formed
from test_groups_block import make_payload

SLOT = 8
BAD = "Bad &lt;b&gt;&quot;name&quot;&lt;/b&gt;"     # the statistic with markup in its name, as the page writes it into a cell


def block(lang="en", ticked=None):
    payload = make_payload(lang)
    view = View(payload)
    if ticked is not None:
        view.select(ticked)
    return payload, view, stat_table.render(payload, view, slot=SLOT)


def answer(payload, view, action="filter", **args):
    return {u["id"]: u for u in stat_table.handle(payload, view, SLOT, action, args)}


def names(html):
    return re.findall(r'<td class="cat">.*?</td><td>(.*?)</td>', html)


def counter(updates):
    return updates["count"]["html"]


# ----------------------------------------------------------------------------------------------------------------------- shown
def test_the_block_has_the_elements_and_ids_of_the_old_page_in_the_old_order():
    _, _, html = block()
    ids = ["id=\"q\"", 'id="cat"', 'id="diff"', 'id="lblDiff"', 'id="hideEmpty"', 'id="lblEmpty"', 'id="count"', 'id="t"']
    positions = [html.index(i) for i in ids]
    assert positions == sorted(positions) and html.count('class="bar"') == 1 and html.count('class="wrap"') == 1
    assert_well_formed(html)


def test_the_controls_start_as_the_page_had_them():
    _, _, html = block()
    assert 'placeholder="Search statistics ..."' in html and 'id="hideEmpty" checked' in html
    assert 'id="diff" data-name' in html and "checked" not in re.search(r'<input type="checkbox" id="diff"[^>]*>', html).group(0)
    assert '<span id="lblDiff">differences only</span>' in html and '<span id="lblEmpty">hide empty</span>' in html


def test_the_choice_of_categories_has_all_and_then_every_category_once_in_plain_order():
    _, _, html = block()
    options = re.findall(r"<option value=\"(.*?)\">(.*?)</option>", html.split('id="cat"')[1].split("</select>")[0])
    assert options == [("", "All categories"), ("Combat", "Combat"), ("M&amp;M", "M&amp;M"), ("Misc", "Misc"), ("Time", "Time"), ("Wealth", "Wealth")]


def test_the_counter_says_how_many_of_all_are_shown_in_the_language_of_the_page():
    assert 'id="count">5 of 5 statistics<' in block("en")[2] and 'id="count">5 von 5 Statistiken<' in block("de")[2]


def test_the_head_has_the_two_fixed_columns_and_one_per_ticked_character_that_can_be_clicked():
    _, _, html = block()
    head = html.split("<thead>")[1].split("</thead>")[0]
    assert head.startswith('<tr><th data-action="sort" data-key="">Category</th><th data-action="sort" data-key="">Statistic</th>')
    assert '<th class="num" data-action="sort" data-key="A-One">A-One<span class="small">Mensch · Magier · 80</span><span class="small">2026-10-01 10:00:00</span></th>' in head
    assert head.count("<th") == 2 + 4


def test_a_row_has_the_category_the_name_and_a_cell_per_character_with_a_dash_for_no_entry():
    _, _, html = block()
    assert '<tr><td class="cat">Time</td><td>Played</td><td class="num">x</td><td class="num">x</td><td class="num">x</td><td class="num">–</td></tr>' in html
    assert names(html) == ["Played", "Creatures killed", "Gold earned", "Only text", BAD]


def test_the_best_value_of_a_row_is_marked_when_everybody_has_a_number_and_they_differ():
    _, _, html = block(ticked=["A-One", "B-Two"])
    assert '<td>Creatures killed</td><td class="num best">1.000</td><td class="num">500</td>' in html
    assert '<td>Gold earned</td><td class="num best">5g</td><td class="num">1g</td>' in html
    assert '<td>Played</td><td class="num">x</td><td class="num">x</td>' in html                    # the same number twice: nothing is best
    assert html.count("best") == 2


def test_names_and_texts_with_markup_cannot_break_out_of_the_block():
    _, _, html = block()
    assert "<b>" not in html and "M&amp;M" in html
    assert_well_formed(html)


def test_without_characters_there_is_no_block():
    payload = make_payload()
    payload["chars"] = []
    assert stat_table.render(payload, View(payload), slot=SLOT) == "" and stat_table.handle(payload, View(payload), SLOT, "filter", {}) == []


# ------------------------------------------------------------------------------------------------------------------ the answers
def test_an_answer_has_the_counter_and_the_inside_of_the_table_and_the_table_is_the_one_the_block_starts_with():
    payload, view, html = block()
    updates = answer(payload, view)
    assert set(updates) == {"count", "t"} and counter(updates) == "5 of 5 statistics"
    assert f'<table id="t">{updates["t"]["html"]}</table>' in html


def test_a_search_narrows_the_rows_in_name_and_category():
    payload, view, _ = block()
    updates = answer(payload, view, controls={"query": "KILL "})
    assert counter(updates) == "1 of 5 statistics" and names(updates["t"]["html"]) == ["Creatures killed"]
    assert names(answer(payload, view, controls={"query": "wealth"})["t"]["html"]) == ["Gold earned"]
    assert counter(answer(payload, view, controls={"query": "zzz"})) == "0 of 5 statistics"


def test_a_category_narrows_the_rows_and_all_categories_gives_them_back():
    payload, view, _ = block()
    assert names(answer(payload, view, controls={"category": "M&M"})["t"]["html"]) == [BAD]
    assert counter(answer(payload, view, controls={"category": ""})) == "5 of 5 statistics"


def test_only_differences_leaves_out_the_rows_that_read_the_same_for_every_ticked_character():
    payload, view, _ = block(ticked=["A-One", "B-Two"])
    updates = answer(payload, view, controls={"only_diff": True})
    assert names(updates["t"]["html"]) == ["Creatures killed", "Gold earned", "Only text", BAD] and counter(updates) == "4 of 5 statistics"


def test_hide_empty_is_on_unless_the_page_says_it_is_off():
    payload, view, _ = block(ticked=["D-Four"])
    assert counter(answer(payload, view, controls={})) == "0 of 5 statistics"
    assert counter(answer(payload, view, controls={"hide_empty": True})) == "0 of 5 statistics"
    off = answer(payload, view, controls={"hide_empty": False})
    assert counter(off) == "5 of 5 statistics" and off["t"]["html"].count('<td class="num">–</td>') == 5


def test_a_click_on_a_column_head_sorts_by_that_character_the_biggest_first_then_the_other_way_then_off():
    payload, view, _ = block()
    first = answer(payload, view, "sort", key="A-One", controls={})
    assert names(first["t"]["html"]) == ["Gold earned", "Played", "Creatures killed", BAD, "Only text"]
    again = answer(payload, view, "sort", key="A-One", controls={})
    assert names(again["t"]["html"]) == ["Only text", BAD, "Creatures killed", "Played", "Gold earned"]
    other = answer(payload, view, "sort", key="B-Two", controls={})
    assert names(other["t"]["html"])[0] == "Gold earned" and names(other["t"]["html"])[:3] == ["Gold earned", "Played", "Creatures killed"]
    off = answer(payload, view, "sort", key="", controls={})
    assert names(off["t"]["html"]) == ["Played", "Creatures killed", "Gold earned", "Only text", BAD]


def test_the_sorting_stays_when_a_filter_changes():
    payload, view, _ = block()
    answer(payload, view, "sort", key="A-One", controls={})
    updates = answer(payload, view, controls={"query": "l"})
    assert names(updates["t"]["html"]) == ["Gold earned", "Played", "Creatures killed", "Only text"]          # "l" is in these names, not in the last one


def test_changing_the_ticked_characters_changes_the_columns_and_the_rows():
    payload, view, _ = block()
    answers = layout.select(view, ["B-Two"], {"8": {"query": ""}})
    updates = {u["id"]: u for u in answers[8]}
    assert len(re.findall(r"<th[ >]", updates["t"]["html"])) == 3 and counter(updates) == "3 of 5 statistics"
    assert names(updates["t"]["html"]) == ["Played", "Creatures killed", "Gold earned"]
    assert {u["id"] for u in layout.select(View(payload), [], {})[8]} == {"count", "t"}
    assert counter({u["id"]: u for u in layout.select(view, [], {})[8]}) == "0 of 5 statistics"


def test_an_unknown_action_changes_nothing_and_every_answer_can_be_sent_as_json():
    payload, view, _ = block()
    assert stat_table.handle(payload, view, SLOT, "no_such_action", {}) == []
    for action, args in (("filter", {"controls": {"query": "a"}}), ("sort", {"key": "A-One"}), ("selection", {})):
        json.dumps(stat_table.handle(payload, view, SLOT, action, args))


# ------------------------------------------------------------------------------------------------------------- the suggestions
def suggest(payload, view, text, **controls):
    updates = stat_table.handle(payload, view, SLOT, "suggest", {"value": text, "controls": controls})
    assert [u["id"] for u in updates] == ["qList"]                                               # only the list: the table is not rebuilt
    return updates[0]


def test_the_search_box_has_a_list_under_it_and_asks_for_suggestions_not_for_the_table():
    _, _, html = block()
    box = re.search(r'<span class="sugg">(.*?)</span>', html).group(1)
    assert 'id="q"' in box and 'autocomplete="off"' in box and 'data-action="suggest"' in box and 'data-suggest="qList"' in box and 'data-commit="filter"' in box
    assert 'data-committed=""' in box and '<ul id="qList" class="sugg-list" role="listbox" hidden></ul>' in box


def test_the_suggestions_are_the_statistics_with_their_category_and_a_line_with_the_number_of_matches():
    payload, view, _ = block()
    update = suggest(payload, view, "ed")
    assert update["hidden"] is False
    assert re.findall(r'<li role="option" data-value="(.*?)">', update["html"]) == ["Creatures killed", "Gold earned", "Played"]
    assert '<li role="option" data-value="Gold earned">Gold earned<span class="small">Wealth</span></li>' in update["html"]
    assert update["html"].endswith('<li class="info">Matches: 3 \u2013 Enter shows them all in the table</li>')


def test_under_two_characters_the_list_is_hidden_and_empty():
    payload, view, _ = block()
    assert suggest(payload, view, "e") == {"id": "qList", "html": "", "hidden": True}
    assert suggest(payload, view, "  ") == {"id": "qList", "html": "", "hidden": True}


def test_without_a_match_the_list_says_so():
    payload, view, _ = block()
    assert suggest(payload, view, "zz") == {"id": "qList", "html": '<li class="info">No matches</li>', "hidden": False}


def test_the_list_follows_the_settings_of_the_page_and_the_ticked_characters():
    payload, view, _ = block()
    assert re.findall(r'data-value="(.*?)"', suggest(payload, view, "ed", category="Wealth")["html"]) == ["Gold earned"]
    view.select(["C-Three"])
    assert re.findall(r'data-value="(.*?)"', suggest(payload, view, "ed")["html"]) == ["Played"]       # C-Three has an entry only for this one
    assert len(re.findall(r'data-value="', suggest(payload, view, "ed", hide_empty=False)["html"])) == 3


def test_a_name_with_markup_cannot_break_out_of_the_list():
    payload, view, _ = block()
    html = suggest(payload, view, "bad")["html"]
    assert "<b>" not in html and 'data-value="Bad &lt;b&gt;&quot;name&quot;&lt;/b&gt;"' in html


def test_the_table_still_follows_the_text_that_was_applied_not_the_text_in_the_box():
    payload, view, _ = block()
    updates = answer(payload, view, controls={"query": "wealth"})                                  # what the page hands over: the committed text
    assert names(updates["t"]["html"]) == ["Gold earned"]


def test_a_suggestion_can_be_sent_as_json_and_without_characters_there_is_nothing():
    payload, view, _ = block()
    json.dumps(suggest(payload, view, "ed"))
    payload["chars"] = []
    assert stat_table.handle(payload, view, SLOT, "suggest", {"value": "ed"}) == []
