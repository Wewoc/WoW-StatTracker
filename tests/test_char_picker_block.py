# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)
# The character selection of the stats page (place 4, src/pages/blocks/char_picker.py): the boxes and the button, the answer to "pick_all" and
# to a changed selection, and how it works together with layout.select.

from core import i18n
from pages.blocks import char_picker, layout
from pages.blocks.view import View
from test_blocks import assert_well_formed, make_payload

KEYS = ("A-One", "B-Two", "C-Three")


def ui(lang, name):
    return i18n.html_strings(lang)[name]


def test_every_character_gets_a_box_and_all_start_ticked():
    html = char_picker.render(make_payload(), View(make_payload()), slot=4)
    for key in KEYS:
        assert f'<label><input type="checkbox" id="chk_{key}" data-pick data-name="{key}" checked> {key}</label>' in html
    assert html.index("A-One") < html.index("B-Two") < html.index("C-Three")
    assert html.startswith('<div class="bar chars" id="chars"><button type="button" id="toggleAll" data-action="pick_all" data-then="selection">')
    assert f">{ui('en', 'deselect_all')}</button>" in html                       # everything is ticked: the button takes all off
    assert_well_formed(html)


def test_the_block_shows_the_selection_of_the_view():
    payload = make_payload()
    view = View(payload)
    view.select(["B-Two"])
    html = char_picker.render(payload, view, slot=4)
    assert 'id="chk_B-Two" data-pick data-name="B-Two" checked>' in html
    assert 'id="chk_A-One" data-pick data-name="A-One">' in html and 'id="chk_C-Three" data-pick data-name="C-Three">' in html
    assert f">{ui('en', 'select_all')}</button>" in html


def test_without_a_view_all_are_ticked():
    assert char_picker.render(make_payload()).count(" checked>") == 3


def test_the_texts_follow_the_language_of_the_payload():
    assert f">{ui('de', 'deselect_all')}</button>" in char_picker.render(make_payload("de"))
    assert ui("de", "deselect_all") != ui("en", "deselect_all")


def test_a_page_without_characters_has_nothing_in_this_place():
    assert char_picker.render(make_payload(keys=())) == "" and char_picker.render({}) == ""


def test_a_name_with_markup_cannot_break_out_of_the_block():
    key = '<img src=x onerror=alert(1)>-R"1\''
    payload = make_payload(keys=(key,))
    html = char_picker.render(payload, View(payload), slot=4)
    assert "<img" not in html and '"1\'' not in html
    assert_well_formed(html)


def boxes(**ticked):
    return {"controls": {key.replace("_", "-"): on for key, on in ticked.items()}}


def test_pick_all_with_a_box_unticked_ticks_all_and_the_button_offers_the_opposite():
    payload = make_payload()
    updates = char_picker.handle(payload, View(payload), 4, "pick_all", boxes(A_One=True, B_Two=False, C_Three=True))
    assert updates == [{"id": "chk_A-One", "checked": True}, {"id": "chk_B-Two", "checked": True}, {"id": "chk_C-Three", "checked": True},
                       {"id": "toggleAll", "html": ui("en", "deselect_all")}]


def test_pick_all_with_all_ticked_unticks_all():
    payload = make_payload()
    updates = char_picker.handle(payload, View(payload), 4, "pick_all", boxes(A_One=True, B_Two=True, C_Three=True))
    assert [u["checked"] for u in updates[:3]] == [False, False, False]
    assert updates[3] == {"id": "toggleAll", "html": ui("en", "select_all")}


def test_pick_all_with_nothing_ticked_or_missing_values_ticks_all():
    payload = make_payload()
    for controls in ({}, boxes(A_One=False, B_Two=False, C_Three=False), {"controls": None}, {"controls": {"A-One": "yes"}}):
        updates = char_picker.handle(payload, View(payload), 4, "pick_all", controls)
        assert [u["checked"] for u in updates[:3]] == [True, True, True], controls


def test_the_ids_of_the_answer_are_the_ids_of_the_boxes():
    key = "Zoë 'x'-Realm"
    payload = make_payload(keys=(key,))
    updates = char_picker.handle(payload, View(payload), 4, "pick_all", {"controls": {key: True}})
    assert updates[0] == {"id": f"chk_{key}", "checked": False}                  # raw: the page looks the element up by this id


def test_the_button_text_follows_a_changed_selection():
    payload = make_payload()
    view = View(payload)
    view.select(["A-One"])
    assert char_picker.handle(payload, view, 4, "selection", {}) == [{"id": "toggleAll", "html": ui("en", "select_all")}]
    view.select(list(KEYS))
    assert char_picker.handle(payload, view, 4, "selection", {}) == [{"id": "toggleAll", "html": ui("en", "deselect_all")}]


def test_the_text_of_the_button_is_escaped():
    payload = make_payload()
    payload["ui"] = dict(payload["ui"], select_all="<b>all</b>")
    view = View(payload)
    view.select([])
    assert char_picker.handle(payload, view, 4, "selection", {}) == [{"id": "toggleAll", "html": "&lt;b&gt;all&lt;/b&gt;"}]
    assert "<b>" not in char_picker.render(payload, view, slot=4)


def test_an_unknown_action_and_attach_answer_nothing():
    payload = make_payload()
    assert char_picker.handle(payload, View(payload), 4, "attach", {}) == [] and char_picker.handle(payload, View(payload), 4, "nope", {}) == []


def test_the_layout_places_it_at_four_and_asks_it_when_the_selection_changes():
    assert layout.INDEX[4] == ("char_picker", {}) and layout.MODULES["char_picker"] is char_picker
    payload = make_payload()
    view = View(payload)
    answers = layout.select(view, ["A-One", "B-Two"], {})
    assert answers[4] == [{"id": "toggleAll", "html": ui("en", "select_all")}] and view.selected == ["A-One", "B-Two"]
    assert layout.dispatch(view, 4, "pick_all", {"controls": {"A-One": True, "B-Two": True, "C-Three": False}})[-1]["html"] == ui("en", "deselect_all")
    assert layout.fill('<div data-slot="4"></div>', payload).count('data-pick') == 3
