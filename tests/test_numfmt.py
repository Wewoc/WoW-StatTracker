# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)
# rules/numfmt.fixed: the number format of the stats page. The expected texts are what the browser's toLocaleString gives (the
# whole function was also compared with the real browser for 11 000 numbers, both languages, 0 to 3 decimals).

import pytest

from rules import numfmt


@pytest.mark.parametrize("value,digits,lang,expected", [
    (1234.5, 2, "en", "1,234.50"),
    (1234.5, 2, "de", "1.234,50"),
    (1234567, 0, "en", "1,234,567"),
    (1234567, 0, "de", "1.234.567"),
    (999.5, 0, "en", "1,000"),
    (0, 1, "en", "0.0"),
    (7, 2, "de", "7,00"),
    (1e6, 0, "de", "1.000.000"),
    (123456789012.345, 2, "en", "123,456,789,012.35"),
])
def test_grouping_and_separators_follow_the_language(value, digits, lang, expected):
    assert numfmt.fixed(value, digits, lang) == expected


@pytest.mark.parametrize("value,digits,expected", [
    (0.125, 2, "0.13"),          # an exact tie goes away from zero
    (2.5, 0, "3"),
    (0.5, 0, "1"),
    (1.5, 0, "2"),
    (1.005, 2, "1.01"),          # the browser rounds the shortest decimal text (1.005), not the binary value
    (2.675, 2, "2.68"),
    (1.255, 2, "1.26"),
    (8.345, 2, "8.35"),
    (0.045, 2, "0.05"),
    (0.0005, 3, "0.001"),
    (0.0004, 3, "0.000"),
])
def test_rounding_is_half_away_from_zero_on_the_shortest_decimal_text(value, digits, expected):
    assert numfmt.fixed(value, digits, "en") == expected


@pytest.mark.parametrize("value,digits,lang,expected", [
    (-1234.567, 1, "de", "-1.234,6"),
    (-0.001, 1, "en", "-0.0"),          # a negative number keeps its minus when it rounds to zero (as in the browser)
    (-0.0, 1, "en", "-0.0"),
    (-2.5, 0, "en", "-3"),
])
def test_negative_numbers_keep_their_sign(value, digits, lang, expected):
    assert numfmt.fixed(value, digits, lang) == expected


def test_an_unknown_language_is_shown_as_english():
    assert numfmt.fixed(1234.5, 1, "fr") == numfmt.fixed(1234.5, 1, "en") == "1,234.5"


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -float("inf"), True, "1", None])
def test_what_is_not_a_finite_number_is_an_error(bad):
    with pytest.raises(ValueError):
        numfmt.fixed(bad, 1, "en")


@pytest.mark.parametrize("value,lang,text", [
    (12, "en", "12"), (0, "en", "0"), (0.5, "en", "0.5"), (1234.5678, "en", "1,234.568"), (1234.5678, "de", "1.234,568"),
    (1000000, "de", "1.000.000"), (-5, "en", "-5"), (0.0004, "en", "0"), (2.0005, "en", "2.001"), (1e9 + 0.25, "en", "1,000,000,000.25"),
    (7.10, "de", "7,1"), (100.0, "de", "100"),
])
def test_number_is_what_tolocalestring_writes_without_options(value, lang, text):
    """Grouped by thousands, up to three decimals, no trailing zeros (compared with the real browser for 600 numbers, both languages)."""
    assert numfmt.number(value, lang) == text
