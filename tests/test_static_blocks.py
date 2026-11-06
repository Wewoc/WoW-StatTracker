# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)
# The blocks of the stats page that only show (no actions): the rates per hour (src/pages/blocks/rates.py) and the last line
# (footer.py), and the helpers they share (markup.plain, numfmt.rate).

import re

import pytest

from core import app_info, i18n
from pages import outputs
from pages.blocks import footer, layout, markup, rates
from rules import numfmt, stat_derive
from test_blocks import assert_well_formed
from test_groups_block import make_payload


def with_reasons(payload):
    """The payload as page_payload makes it: the results without a rate carry the text of their reason ("why")."""
    for role in payload["derived"]["roles"]:
        for result in (*role["chars"].values(), role["total"]):
            if "reason" in result:
                result["why"] = "why " + result["reason"]
    return payload


def with_app(payload):
    payload["app"] = {"version": "9.9.9", "copyright": "(c) 2026 Somebody", "license": "GPL <3>", "site": "https://example.org/project/"}
    return payload


# ------------------------------------------------------------------------------------------------------------ helpers
@pytest.mark.parametrize("number,text", [(1, "1"), (1.0, "1"), (3600 / 3600, "1"), (1.5, "1.5"), (0.25, "0.25"), (24.0, "24")])
def test_plain_writes_a_whole_number_without_decimals(number, text):
    assert markup.plain(number) == text


@pytest.mark.parametrize("value,lang,text", [
    (0, "en", "0"), (100, "en", "100"), (1234.5, "en", "1,235"), (1234.5, "de", "1.235"),
    (99.99, "en", "100.0"), (12.345, "en", "12.3"), (12.345, "de", "12,3"),
    (9.999, "en", "10.00"), (0.5, "en", "0.50"), (0.1, "de", "0,10"), (0.05, "en", "0.050"), (0.0004, "en", "0.000"),
])
def test_a_rate_has_fewer_decimals_the_bigger_it_is(value, lang, text):
    assert numfmt.rate(value, lang) == text


# --------------------------------------------------------------------------------------------------------------- rates
def rates_html(lang="en", payload=None):
    return rates.render(payload or with_reasons(make_payload(lang)))


def test_the_rates_block_has_the_elements_and_ids_of_the_old_page():
    html = rates_html()
    for part in ('<details class="rates" id="rates">', '<summary id="ratesTitle">Rates per hour played</summary>', '<table id="rt">',
                 '<div class="note" id="ratesNote">', '<tr class="total">'):
        assert part in html, part
    assert_well_formed(html)


def test_the_head_has_the_character_column_and_one_column_per_role():
    html = rates_html()
    head = re.search(r"<thead><tr>(.*?)</tr></thead>", html).group(1)
    labels = [r.key for r in stat_derive.ROLES]
    assert head.startswith("<th>Character</th>") and re.findall(r'<th class="num">(.*?)</th>', head) == labels


def test_the_total_row_comes_first_and_then_one_row_per_character_in_the_order_of_the_page():
    html = rates_html()
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", html.split("<tbody>")[1])
    assert [re.match(r"<td>(.*?)(<span|</td>)", r).group(1) for r in rows] == ["Total", "A-One", "B-Two", "C-Three", "D-Four"]
    assert '<td>A-One<span class="small">Mensch · Magier · 80</span></td>' in html
    assert '<td>D-Four<span class="small"></span></td>' in html                       # no race, class or level: the small text stays, empty


def test_the_total_says_how_many_characters_it_is_made_of_and_a_character_row_does_not():
    payload = with_reasons(make_payload())
    html = rates_html(payload=payload)
    total = re.search(r'<tr class="total">(.*?)</tr>', html).group(1)
    assert "of 4 characters" in total
    rows = re.findall(r"<tr>(.*?)</tr>", html.split("<tbody>")[1])
    assert "characters" not in "".join(rows)


def test_a_rate_is_written_in_the_language_of_the_page_and_a_missing_one_shows_a_dash_and_the_reason():
    payload = with_reasons(make_payload("de"))
    html = rates.render(payload)
    kills = next(r for r in payload["derived"]["roles"] if r["role"] == "kills_pve")
    first = kills["chars"]["A-One"]["rate"]
    assert f'<td class="num">{numfmt.rate(first, "de")}</td>' in html
    assert '<td class="num">–<span class="small">why no_stat</span></td>' in html


def test_the_note_names_the_minimum_of_played_hours_and_the_texts_follow_the_language():
    assert "1 h" in rates_html().split('id="ratesNote">')[1].split("</div>")[0]
    assert "Raten pro Spielstunde" in rates_html("de") and "Rates per hour played" in rates_html("en")


@pytest.mark.parametrize("change", [lambda p: p.update(chars=[]), lambda p: p["derived"].update(roles=[]), lambda p: p.pop("derived"), lambda p: p.update(derived=None)])
def test_without_characters_or_rates_the_block_is_left_out(change):
    payload = with_reasons(make_payload())
    change(payload)
    assert rates.render(payload) == ""


def test_markup_in_a_name_or_a_label_cannot_break_out_of_the_block():
    payload = with_reasons(make_payload())
    payload["chars"][0]["key"] = "<b>x</b>-R"
    payload["chars"][0]["class"] = "<script>"
    payload["derived"]["roles"][0]["label"] = '"><img src=x>'
    payload["derived"]["roles"][0]["chars"]["<b>x</b>-R"] = {"reason": "no_stat", "why": "<i>why</i>"}
    html = rates.render(payload)
    assert "<b>" not in html and "<script>" not in html and "<img" not in html and "<i>" not in html
    assert_well_formed(html)


# ------------------------------------------------------------------------------------------------------------- footer
def test_the_footer_has_the_version_the_link_the_copyright_and_the_licence():
    html = footer.render(with_app(make_payload()))
    assert html.startswith('<div class="foot" id="foot">Version 9.9.9 · <a href="https://example.org/project/" target="_blank" rel="noopener noreferrer">example.org/project</a>')
    assert html.endswith(" · (c) 2026 Somebody · GPL &lt;3&gt;</div>")
    assert_well_formed(html)


def test_the_footer_follows_the_language():
    de = i18n.html_strings("de")["footer_version"]
    assert footer.render(with_app(make_payload("de"))).startswith(f'<div class="foot" id="foot">{markup.fmt(de, version="9.9.9")}')


def test_the_footer_is_left_out_without_characters_or_without_the_values_of_the_program():
    assert footer.render(make_payload()) == ""
    assert footer.render(with_app({**make_payload(), "chars": []})) == ""


def test_the_footer_shows_what_the_program_says_about_itself():
    payload = make_payload()
    payload["app"] = {"version": app_info.APP_VERSION, "copyright": app_info.COPYRIGHT, "license": app_info.LICENSE_NAME, "site": app_info.SITE_URL}
    html = footer.render(payload)
    assert app_info.APP_VERSION in html and app_info.LICENSE_NAME in html and app_info.SITE_URL in html


# ----------------------------------------------------------------------------------------------------- in the written page
def test_the_written_page_has_both_blocks_in_their_places(tmp_path):
    out = tmp_path / "stats.html"
    outputs.write_html(with_app(with_reasons(make_payload())), out)
    page = out.read_text(encoding="utf-8")
    assert '<div data-slot="1"><details class="rates" id="rates">' in page and '<div data-slot="9"><div class="foot" id="foot">' in page
    assert page.index('data-slot="1"') < page.index('data-slot="2"') < page.index('data-slot="3"') < page.index('data-slot="9"')
    assert [layout.INDEX[n][0] for n in (1, 9)] == ["rates", "footer"]
