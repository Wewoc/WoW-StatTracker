# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)
# The Reputation block of the stats page (src/pages/blocks/reputation.py): what it shows, and how it answers the search and the ticked characters.
# The rules behind it are tested in test_rep_rules.py; here: the elements, the texts, the cells, the answers.

import json
import re

import pytest

from core import i18n
from pages.blocks import layout, reputation
from pages.blocks.view import View
from rules import numfmt
from test_blocks import assert_well_formed
from test_groups_block import make_payload


def rows_of(html):
    """[[cell text, ...], ...] of the rows of the reputation table (tags stripped)."""
    body = html.split("<tbody>")[1].split("</tbody>")[0]
    return [[re.sub(r"<[^>]+>", " ", c).split() for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row)] for row in re.findall(r"<tr>(.*?)</tr>", body)]


def table_of(html):
    return html.split('id="repWrap"')[1].split("</div>")[0]


def answer(payload, view, action="query", query="", slot=5):
    updates = reputation.handle(payload, view, slot, action, {"controls": {"query": query}})
    return {u["id"]: u for u in updates}


def block(lang="en", ticked=None):
    payload = make_payload(lang)
    view = View(payload)
    if ticked is not None:
        view.select(ticked)
    return payload, view, reputation.render(payload, view, slot=5)


# ------------------------------------------------------------------------------------------------------------------ the block
def test_the_block_has_the_elements_and_ids_of_the_old_page():
    _, _, html = block()
    for part in ('<details class="rates" id="rep">', '<summary id="repTitle">Reputation</summary>', 'id="repQ"', 'placeholder="Search faction …"', 'id="repNone"',
                 'id="repWrap"', '<table id="rpt">', 'id="repMissing"', 'id="repNote"'):
        assert part in html, part
    assert_well_formed(html)


def test_the_head_has_a_column_per_ticked_character_with_who_and_when():
    _, _, html = block()
    head = html.split("<thead>")[1].split("</thead>")[0]
    assert head.startswith("<tr><th>Faction</th><th>A-One<span class=\"small\">Mensch · Magier · 80</span><span class=\"small\">2026-10-01 10:00:00</span></th>")
    assert head.count("<th>") == 1 + 4                                                 # the faction column and the four ticked characters
    assert "<th>D-Four<span" in head and "Mensch" not in head.split("D-Four")[1]


def test_the_rows_follow_the_merged_order_and_the_headings_span_the_table():
    _, _, html = block()
    assert re.findall(r'<td colspan="5" class="(rcat|rsub)">([^<]*)</td>', html) == [("rcat", "The War Within"), ("rsub", "Delves")]
    names = [re.search(r'<td class="rname[^"]*">([^<]*)', r).group(1) for r in re.findall(r"<tr>(.*?)</tr>", html.split("<tbody>")[1]) if 'class="rname' in r]
    assert names == ["Faction One", "Friend Faction", "Renown Faction", "Faction Two"]


def test_a_cell_has_the_level_the_way_to_the_next_one_as_text_and_as_a_bar():
    _, _, html = block()
    assert ('<td class="rcell"><div><div>Neutral</div><span class="small">1,500 / 3,000</span><div class="rbar"><i style="width: 50%;"></i></div></div></td>'
            in html)
    assert '<div>Level 2 of 8</div><span class="small">50 / 100</span><div class="rbar"><i style="width: 50%;"></i></div>' in html


def test_a_character_without_a_faction_shows_dashes_and_one_without_a_list_too():
    _, _, html = block()
    friend_row = next(r for r in re.findall(r"<tr>(.*?)</tr>", html.split("<tbody>")[1]) if "Friend Faction" in r)
    assert friend_row.count('<td class="rcell">--</td>') == 3                          # B-Two has no such faction, C-Three and D-Four have no list


def test_an_account_wide_faction_is_one_cell_across_all_characters_from_the_newest_scan():
    _, _, html = block()
    row = next(r for r in re.findall(r"<tr>(.*?)</tr>", html.split("<tbody>")[1]) if "Renown Faction" in r)
    assert '<span class="small">account-wide</span>' in row and 'colspan="4"' in row and row.count('class="rcell"') == 1
    assert "Renown 7 of 20" in row                                                      # B-Two was scanned later than A-One (5 of 20)


def test_the_paragon_shows_the_round_and_the_reward_and_a_green_bar():
    _, _, html = block()
    assert '<span class="small">Paragon 5,000 / 10,000 · Reward waiting</span><div class="rbar par"><i style="width: 50%;"></i></div>' in html


def test_a_level_at_the_top_says_maximum_without_a_bar():
    _, _, html = block()
    assert '<div>Exalted</div><span class="small">Maximum</span></div>' in html


def test_the_numbers_follow_the_language_of_the_page():
    _, _, html = block("de")
    assert '<span class="small">1.500 / 3.000</span>' in html and "Stufe 2 von 8" in html and "Ohne Rufdaten" in html


def test_the_characters_without_a_list_are_named_in_a_note():
    payload, _, html = block()
    note = html.split('id="repMissing">')[1].split("</div>")[0]
    assert note == "Without reputation data (the last scan is not from the current addon): C-Three, D-Four"
    _, _, only = block(ticked=["A-One", "B-Two"])
    assert only.split('id="repMissing">')[1].startswith("</div>")


def test_the_note_of_the_block_and_the_title_come_from_the_texts_of_the_page():
    _, _, html = block()
    assert i18n.html_strings("en")["rep_note"] in html.replace("&#x27;", "'")


def test_a_page_without_reputation_has_no_block():
    payload = make_payload()
    del payload["rep"]
    assert reputation.render(payload, View(payload), slot=5) == ""
    payload["rep"] = {}
    assert reputation.render(payload, View(payload), slot=5) == ""
    assert reputation.handle(payload, View(payload), 5, "query", {}) == []


def test_the_names_of_the_factions_work_with_numbers_and_with_texts_as_keys():
    payload = make_payload()
    as_text = json.loads(json.dumps(payload))                                          # what the bridge gets: keys are texts
    assert reputation.render(payload, View(payload), slot=5) == reputation.render(as_text, View(as_text), slot=5)


def test_a_name_with_markup_cannot_break_out_of_the_block():
    payload = make_payload()
    payload["rep"]["defs"][11] = '<script>alert(1)</script>"'
    payload["names"]["standing"]["4"] = "<b>x</b>"
    payload["chars"][0]["key"] = "<i>x</i>-R"
    payload["rep"]["chars"]["<i>x</i>-R"] = payload["rep"]["chars"].pop("A-One")
    html = reputation.render(payload, View(payload), slot=5)
    assert "<script>" not in html and "<b>" not in html and "<i>x" not in html
    assert_well_formed(html)


# ------------------------------------------------------------------------------------------------------------------- answers
def test_a_search_narrows_the_rows_and_keeps_the_headings_above_them():
    payload, view, _ = block()
    updates = answer(payload, view, query="renown")
    names = [r[0] for r in rows_of(updates["repWrap"]["html"])]
    assert names == [["The", "War", "Within"], ["Delves"], ["Renown", "Faction", "account-wide"]]
    assert updates["repNone"]["hidden"] is True and updates["repWrap"]["hidden"] is False


def test_a_search_without_a_match_says_so_and_hides_the_table():
    payload, view, _ = block()
    updates = answer(payload, view, query="zzz")
    assert updates["repNone"] == {"id": "repNone", "html": "No faction matches the search.", "hidden": False}
    assert updates["repWrap"]["hidden"] is True and "<tr>" not in updates["repWrap"]["html"]


def test_the_search_ignores_case_and_spaces_around_it():
    payload, view, _ = block()
    assert answer(payload, view, query="  FACTION two ")["repWrap"]["html"] == answer(payload, view, query="faction two")["repWrap"]["html"]


def test_with_no_character_ticked_the_block_says_so():
    payload, view, _ = block(ticked=[])
    updates = answer(payload, view, "selection")
    assert updates["repNone"] == {"id": "repNone", "html": "No character selected.", "hidden": False} and updates["repWrap"]["hidden"] is True
    assert updates["repMissing"]["html"] == ""


def test_only_characters_without_a_list_give_no_table_and_a_note_but_no_notice():
    payload, view, _ = block(ticked=["C-Three"])
    updates = answer(payload, view, "selection")
    assert updates["repNone"]["hidden"] is True and updates["repWrap"]["hidden"] is True and "C-Three" in updates["repMissing"]["html"]


def test_unticking_a_character_takes_its_column_out_and_the_rows_only_it_had():
    payload, view, _ = block()
    layout_answers = layout.select(view, ["B-Two"], {"5": {"query": ""}})
    updates = {u["id"]: u for u in layout_answers[5]}
    names = [" ".join(r[0]) for r in rows_of(updates["repWrap"]["html"])]
    assert "Friend Faction" not in names and "Faction Two" in names and updates["repWrap"]["html"].count("<th>") == 2
    assert "A-One" not in updates["repWrap"]["html"].split("<tbody>")[0]


def test_an_unknown_action_changes_nothing_and_every_answer_can_be_sent_as_json():
    payload, view, _ = block()
    assert reputation.handle(payload, view, 5, "no_such_action", {}) == []
    for action in ("query", "selection"):
        json.dumps(reputation.handle(payload, view, 5, action, {"controls": {"query": "a"}}))
    assert reputation.handle(payload, view, 5, "query", {}) == reputation.handle(payload, view, 5, "query", {"controls": {"query": ""}})


def test_the_numbers_in_a_cell_use_the_format_of_the_page_language():
    payload = make_payload("de")
    view = View(payload)
    assert numfmt.number(1500, "de") in reputation.render(payload, view, slot=5)
