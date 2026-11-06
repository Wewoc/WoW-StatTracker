# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)
# The Top 5 tiles at the top of the stats page (src/pages/blocks/top5.py, place 10).

import re
from pathlib import Path

from pages import outputs
from pages.blocks import layout, top5
from pages.blocks.view import View
from test_blocks import assert_well_formed
from test_groups_block import make_payload

GOLD = {"stat": 328, "agg": "sum", "by": "all", "value": ""}
KILLS_MAGE = {"stat": 107, "agg": "avg", "by": "class", "value": "MAGE"}


def block(lang="en", *tiles):
    payload = make_payload(lang)
    payload["top5"] = list(tiles)
    return payload, top5.render(payload, View(payload), slot=10)


def parts(html):
    """[(name, sub, value, scope, small)] of every tile."""
    found = []
    for tile in html.split('<div class="tile">')[1:]:
        name = re.search(r'<div class="tname">(.*?)(?:<span class="small">(.*?)</span>)?</div>', tile)
        found.append((name.group(1), name.group(2) or "", re.search(r'<div class="tval">(.*?)</div>', tile).group(1),
                      re.search(r'<div class="tscope">(.*?)</div>', tile).group(1), (re.search(r'<div class="small">(.*?)</div>', tile) or [None, ""])[1]))
    return found


def test_a_tile_shows_the_statistic_one_value_and_who_it_is_about():
    _, html = block("en", GOLD)
    assert html.startswith('<div class="tiles" id="top5"><div class="tile">') and html.endswith("</div></div>")
    assert parts(html) == [("Gold earned", "Wealth · Sum", "6.00 g", "All characters", "2 of 4 characters")]
    assert_well_formed(html)


def test_the_tiles_come_in_the_order_they_were_set_with_the_text_of_the_function_and_the_scope():
    _, html = block("en", KILLS_MAGE, {"stat": -1, "agg": "sum", "by": "faction", "value": "Alliance"},
                    {"stat": 107, "agg": "max", "by": "char", "value": "A-One"}, {"stat": 107, "agg": "sum", "by": "race", "value": "Human"})
    found = parts(html)
    assert [f[0] for f in found] == ["Creatures killed", "Played", "Creatures killed", "Creatures killed"]
    assert found[0][1:4] == ("Combat · Average", "750", "Class: Magier") and found[1][1:4] == ("Time · Sum", "7.0 h", "Faction: Alliance")
    assert found[2][1:4] == ("Combat", "1,000", "A-One")                                   # one character: the function says nothing
    assert found[3][1:4] == ("Combat · Sum", "1,500", "Race: Mensch")             # the names of the classes and races are those of the payload


def test_the_texts_follow_the_language_of_the_page_and_the_numbers_too():
    _, html = block("de", {"stat": 107, "agg": "sum", "by": "all", "value": ""}, {"stat": 328, "agg": "sum", "by": "faction", "value": "Alliance"})
    found = parts(html)
    assert found[0][2:4] == ("1.500", "Alle Charaktere") and found[0][1] == "Combat · Summe"
    assert found[1][3] == "Fraktion: Allianz"


def test_a_group_that_nobody_plays_still_has_its_name_and_an_unknown_one_is_called_unknown():
    _, html = block("en", {"stat": 107, "agg": "sum", "by": "class", "value": "WARLOCK"}, {"stat": 107, "agg": "sum", "by": "class", "value": "DRUID"},
                    {"stat": 107, "agg": "sum", "by": "class", "value": ""}, {"stat": 107, "agg": "sum", "by": "realm", "value": "Four"})
    found = parts(html)
    assert found[0][2:5] == ("–", "Class: WARLOCK", "no value")             # no name for the file name this program does not know
    assert found[1][3] == "Class: Druide" and found[2][3] == "Class: unknown" and found[3][3] == "Realm: Four"


def test_a_value_that_is_missing_for_some_characters_says_how_many_had_one():
    _, html = block("en", {"stat": 107, "agg": "sum", "by": "all", "value": ""})
    assert parts(html)[0][4] == "2 of 4 characters"
    _, html = block("en", KILLS_MAGE)
    assert parts(html)[0][4] == ""                                               # both mages had one


def test_a_statistic_the_page_does_not_have_and_a_tile_this_program_cannot_read_show_no_value():
    _, html = block("en", {"stat": 999, "agg": "sum", "by": "all", "value": ""}, {"stat": 107, "agg": "median", "by": "guild", "value": "x"})
    found = parts(html)
    assert found[0][0] == "#999" and found[0][2] == "–" and found[1][2] == "–" and found[1][3] == "guild: x"


def test_the_tiles_do_not_follow_the_ticked_characters():
    payload, html = block("en", GOLD)
    view = View(payload)
    view.select(["C-Three"])
    assert top5.render(payload, view, slot=10) == html
    assert not hasattr(top5, "handle") and not getattr(top5, "USES_SELECTION", False)


def test_the_block_is_empty_without_tiles_or_characters_and_ignores_what_is_not_a_tile():
    payload = make_payload()
    assert top5.render(payload, View(payload), slot=10) == ""
    payload["top5"] = ["x", None, 3]
    assert top5.render(payload, View(payload), slot=10) == ""
    payload["top5"] = [GOLD]
    payload["chars"] = []
    assert top5.render(payload, View(payload), slot=10) == ""


def test_a_name_with_markup_cannot_break_out_of_the_block():
    payload = make_payload()
    payload["chars"][0]["key"] = '<i>x</i>-R"1'
    payload["stats"][4]["v"] = {'<i>x</i>-R"1': ["1", 1]}
    payload["top5"] = [{"stat": 6, "agg": "sum", "by": "char", "value": '<i>x</i>-R"1'}, {"stat": 6, "agg": "sum", "by": "realm", "value": '"<b>'}]
    html = top5.render(payload, View(payload), slot=10)
    assert "<i>" not in html and "<b>" not in html and "&lt;b&gt;&quot;name&quot;&lt;/b&gt;" in html
    assert_well_formed(html)


def test_the_page_has_the_place_at_its_top_and_the_layout_fills_it():
    template = (layout.__file__ and open(layout.__file__.replace("pages\\blocks\\layout.py", "template.html").replace("pages/blocks/layout.py", "template.html"), encoding="utf-8").read())
    assert layout.INDEX[10] == ("top5", {}) and layout.MODULES["top5"] is top5
    assert template.index('data-slot="10"') < template.index('data-slot="1"')
    payload = make_payload()
    payload["top5"] = [GOLD]
    assert 'id="top5"' in layout.fill('<div data-slot="10"></div>', payload)
    assert layout.fill('<div data-slot="10"></div>', make_payload()) == '<div data-slot="10"></div>'


def test_write_html_carries_the_tiles_in_the_page_and_in_the_data(tmp_path):
    payload = make_payload()
    payload["top5"] = [GOLD]
    out = tmp_path / "stats.html"
    outputs.write_html(payload, out)
    text = out.read_text(encoding="utf-8")
    assert 'id="top5"' in text and '"top5": [{"stat": 328' in text


def test_the_settings_are_offered_the_statistics_with_a_number_and_the_names_of_the_data():
    payload = make_payload("en")
    found = top5.choices(payload)
    assert [i for i, _ in found["stats"]] == [-1, 107, 328, 6]                              # "Only text" has no number for anybody
    assert dict(found["stats"])[107] == "Creatures killed (Combat)" and dict(found["stats"])[328] == "Gold earned (Wealth)"
    assert found["parts"][107] == ("Creatures killed", "Combat") and set(found["parts"]) == {-1, 107, 328, 6}
    assert found["values"]["char"] == [(c["key"], c["key"]) for c in payload["chars"]]
    assert found["values"]["class"] == [("DRUID", "Druide"), ("MAGE", "Magier"), ("", "unknown")]       # the group without a class last, named "unknown"
    assert found["values"]["faction"] == [("Alliance", "Alliance"), ("", "unknown")]
    assert ("", "unknown") in found["values"]["race"] and "realm" in found["values"]


def test_the_offer_of_a_page_without_characters_is_empty():
    found = top5.choices({"chars": [], "stats": [], "ui": {}})
    assert found["stats"] == [] and found["parts"] == {} and all(values == [] for values in found["values"].values())
