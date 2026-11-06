# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)
# The blocks of the stats page (src/pages/blocks): the helpers, the history-links block, the table that says which block fills
# which numbered place of the page, and the guards that keep the page, that table and the block modules in step.

import re
from html.parser import HTMLParser
from pathlib import Path

import pytest

from core import i18n
from pages import outputs
from pages.blocks import history_links, layout, markup

SRC = Path(__file__).resolve().parent.parent / "src"
BLOCKS = SRC / "pages" / "blocks"
NOT_BLOCKS = {"__init__", "layout", "markup", "view", "cells"}              # the modules of the folder that are no block
PAGES = {"template.html": SRC / "template.html", "history.html": SRC / "history.html"}


def make_payload(lang="en", keys=("A-One", "B-Two", "C-Three"), links=None, directory="history"):
    payload = {"lang": lang, "ui": i18n.html_strings(lang), "chars": [{"key": k} for k in keys], "stats": []}
    if links is not None:
        payload["history"] = {"dir": directory, "links": links}
    return payload


class Balanced(HTMLParser):
    """Collects a start/end tag mismatch (void elements have no end tag)."""
    VOID = {"br", "hr", "img", "input", "meta", "link"}

    def __init__(self):
        super().__init__()
        self.stack, self.errors = [], []

    def handle_starttag(self, tag, attrs):
        if tag not in self.VOID:
            self.stack.append(tag)

    def handle_endtag(self, tag):
        if not self.stack or self.stack.pop() != tag:
            self.errors.append(tag)


def assert_well_formed(text):
    parser = Balanced()
    parser.feed(text)
    assert parser.errors == [] and parser.stack == [], (parser.errors, parser.stack)


# ------------------------------------------------------------------------------------------------ markup
def test_esc_makes_text_and_attribute_values_safe():
    assert markup.esc('<a href="x">&\'</a>') == "&lt;a href=&quot;x&quot;&gt;&amp;&#x27;&lt;/a&gt;"
    assert markup.esc(3) == "3"


def test_fmt_fills_the_marks_and_empties_unknown_ones():
    assert markup.fmt("{n} of {total} ({x})", n=2, total=5) == "2 of 5 ()"
    assert markup.fmt(None, n=1) == "" and markup.fmt("no marks") == "no marks"


def test_ui_gives_the_text_or_nothing():
    assert markup.ui({"ui": {"a": "A"}}, "a") == "A"
    assert markup.ui({"ui": {"a": "A"}}, "b") == "" and markup.ui({}, "a") == ""


# -------------------------------------------------------------------------------------- the history block
LINKS = {"B-Two": {"href": "history/history-B-Two-1.html", "scans": 3}, "A-One": {"href": "history/history-A-One-2.html", "scans": 2}}


def test_the_block_links_the_characters_in_the_order_of_the_page_and_names_the_scans():
    html = history_links.render(make_payload(links=LINKS))
    assert html.index(">A-One<") < html.index(">B-Two<") and "C-Three" not in html.split('id="historyNote"')[0]
    assert '<a class="hlink" href="history/history-A-One-2.html">A-One<span> (2)</span></a>' in html
    assert '<a class="hlink" href="history/history-B-Two-1.html">B-Two<span> (3)</span></a>' in html
    assert_well_formed(html)


def test_the_block_keeps_the_ids_and_classes_the_style_sheet_knows():
    html = history_links.render(make_payload(links=LINKS))
    for part in ('<details class="rates" id="history">', 'id="historyTitle"', '<div class="gbar" id="historyLinks">',
                 '<div class="note" id="historyNote">'):
        assert part in html


def test_the_note_names_the_folder_and_the_characters_without_a_page():
    ui = i18n.html_strings("en")
    html = history_links.render(make_payload(links=LINKS, directory="my history"))
    note = markup.fmt(ui["hist_links_note"], dir="my history") + " " + markup.fmt(ui["hist_links_missing"], n=1)
    assert f'<div class="note" id="historyNote">{markup.esc(note)}</div>' in html
    assert f'<summary id="historyTitle">{markup.esc(ui["hist_links_title"])}</summary>' in html


def test_no_note_about_missing_pages_when_every_character_has_one():
    links = {k: {"href": f"h/{k}.html", "scans": 2} for k in ("A-One", "B-Two", "C-Three")}
    ui = i18n.html_strings("en")
    html = history_links.render(make_payload(links=links))
    assert f'<div class="note" id="historyNote">{markup.esc(markup.fmt(ui["hist_links_note"], dir="history"))}</div>' in html


@pytest.mark.parametrize("payload", [make_payload(), make_payload(links={}), make_payload(links={"Z-Other": {"href": "x", "scans": 2}}),
                                     {"chars": [], "ui": {}}, {}])
def test_the_block_is_empty_when_no_character_has_a_page(payload):
    assert history_links.render(payload) == ""


def test_a_name_or_a_link_with_markup_cannot_break_out_of_the_block():
    key = '<script>alert(1)</script>-R"x'
    html = history_links.render(make_payload(keys=(key,), links={key: {"href": 'a"><b>.html', "scans": 2}}))
    assert "<script>" not in html and "<b>" not in html
    assert_well_formed(html)


def test_the_texts_follow_the_language_of_the_payload():
    de = history_links.render(make_payload("de", links=LINKS))
    en = history_links.render(make_payload("en", links=LINKS))
    assert i18n.html_strings("de")["hist_links_title"] in de and i18n.html_strings("en")["hist_links_title"] in en
    assert de != en


# ------------------------------------------------------------------------------------------------ layout
def test_fill_puts_each_block_into_its_numbered_place_and_leaves_the_rest_alone():
    page = '<p>before</p>\n<div data-slot="3"></div>\n<p>after</p>'
    out = layout.fill(page, make_payload(links=LINKS))
    assert out.startswith('<p>before</p>\n<div data-slot="3"><details class="rates" id="history">')
    assert out.endswith("</details></div>\n<p>after</p>")


def test_a_place_whose_block_has_nothing_to_show_stays_empty():
    assert layout.fill('<div data-slot="3"></div>', make_payload()) == '<div data-slot="3"></div>'


def test_a_page_without_places_is_not_changed():
    assert layout.fill("<p>no places</p>", make_payload(links=LINKS)) == "<p>no places</p>"


def test_a_place_without_an_entry_is_an_error_of_the_program():
    with pytest.raises(LookupError, match="place 99"):
        layout.fill('<div data-slot="99"></div>', make_payload())


def test_the_arguments_of_an_entry_reach_the_block(monkeypatch):
    seen = []

    class Fake:
        @staticmethod
        def render(payload, view, slot=None, **args):
            seen.append((slot, args))
            return "<i>fake</i>"
    monkeypatch.setitem(layout.INDEX, 7, ("fake", {"n": 2}))
    monkeypatch.setitem(layout.MODULES, "fake", Fake)
    assert layout.fill('<div data-slot="7"></div>', {}) == '<div data-slot="7"><i>fake</i></div>' and seen == [(7, {"n": 2})]


# ------------------------------------------------------------------------------------------------ guards
PLACE_FORM = re.compile(r'<div data-slot="(\d+)"></div>')


def test_the_places_of_the_page_and_the_entries_of_the_index_are_the_same_numbers():
    page = PAGES["template.html"].read_text(encoding="utf-8")
    numbers = [int(n) for n in PLACE_FORM.findall(page)]
    assert page.count("data-slot=") == len(numbers), "a place is written <div data-slot=\"N\"></div> and nothing else"
    assert len(numbers) == len(set(numbers)), "a number stands once on the page"
    assert sorted(numbers) == sorted(layout.INDEX), "every place needs an INDEX entry and every entry a place"
    assert "data-slot=" not in PAGES["history.html"].read_text(encoding="utf-8")


def test_every_entry_names_a_known_block_and_every_block_is_used():
    names = {name for name, _args in layout.INDEX.values()}
    assert names <= set(layout.MODULES), names - set(layout.MODULES)
    assert set(layout.MODULES) <= names, "a block module nobody places"


def test_every_block_file_is_registered_under_its_own_name_and_can_render():
    files = {p.stem for p in BLOCKS.glob("*.py")} - NOT_BLOCKS
    assert files == set(layout.MODULES)
    for name, module in layout.MODULES.items():
        assert module.__name__.rsplit(".", 1)[-1] == name and callable(module.render)


def test_a_block_reads_the_payload_and_writes_nothing():
    for path in BLOCKS.glob("*.py"):
        source = path.read_text(encoding="utf-8")
        assert not re.search(r"\b(open|write_text|write_bytes|print)\(", source), path.name


# ------------------------------------------------------------------------------------ in the written page
def test_write_html_puts_the_block_into_its_place_before_the_data(tmp_path):
    out = tmp_path / "stats.html"
    outputs.write_html(make_payload(links=LINKS), out)
    page = out.read_text(encoding="utf-8")
    assert '<div data-slot="3"><details class="rates" id="history">' in page
    assert "/*__DATA__*/null" not in page and '"hist_links_title"' in page          # the data went in, too


def test_write_html_leaves_the_place_empty_without_links(tmp_path):
    out = tmp_path / "stats.html"
    outputs.write_html(make_payload(), out)
    assert '<div data-slot="3"></div>' in out.read_text(encoding="utf-8")
