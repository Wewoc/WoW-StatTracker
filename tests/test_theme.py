# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)
# The colour schemes of the window: every scheme is complete and made of valid colours, an unknown number is the default.

import re
from pathlib import Path

import pytest

from core import theme

SRC = Path(__file__).resolve().parent.parent / "src"
PAGES = {"stats page": SRC / "template.html", "history page": SRC / "history.html"}


@pytest.mark.parametrize("number", sorted(theme.THEMES))
def test_every_scheme_has_every_role_and_a_name_and_valid_colours(number):
    scheme = theme.THEMES[number]
    assert set(scheme) == set(theme.ROLES) | {"name"}
    assert scheme["name"].strip()
    for role in theme.ROLES:
        assert re.fullmatch(r"#[0-9a-fA-F]{6}", scheme[role]), (number, role)


def test_the_default_scheme_exists_and_unknown_numbers_fall_back_to_it():
    assert theme.DEFAULT_THEME in theme.THEMES
    for bad in (0, 99, -1, "1", None, True, 1.0):
        assert theme.colors(bad) is theme.THEMES[theme.DEFAULT_THEME], bad
    assert theme.colors(2) is theme.THEMES[2]


def test_the_names_for_the_dropdown_follow_the_numbers():
    names = theme.names()
    assert list(names) == sorted(theme.THEMES) and all(names.values())


def test_a_scheme_text_stays_readable_on_its_background():
    """Contrast of the main text on the window and on the raised surface (WCAG ratio, at least 7)."""
    def luminance(hex_color):
        rgb = [int(hex_color[i:i + 2], 16) / 255 for i in (1, 3, 5)]
        lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
        return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]

    def ratio(a, b):
        hi, lo = sorted((luminance(a), luminance(b)), reverse=True)
        return (hi + 0.05) / (lo + 0.05)
    for number, scheme in theme.THEMES.items():
        assert ratio(scheme["text"], scheme["bg"]) >= 7, number
        assert ratio(scheme["text"], scheme["bg2"]) >= 7, number


# ------------------------------------------------------------------------------ the colours of the pages
def root_variables(path):
    """{--name: value} of the :root block of a page (the defaults the page has without a program window)."""
    text = path.read_text(encoding="utf-8")
    block = re.search(r":root\s*\{([^}]*)\}", text).group(1)
    return dict(re.findall(r"(--[a-z]+)\s*:\s*(#[0-9a-fA-F]{6})", block))


@pytest.mark.parametrize("page", sorted(PAGES))
def test_the_page_defaults_are_the_documented_original_colours(page):
    """theme.PAGE_ORIGINAL is the backup of the original look: whoever changes a default in a page changes it there too."""
    found = root_variables(PAGES[page])
    assert found and all(theme.PAGE_ORIGINAL[name] == value for name, value in found.items()), page


def test_every_documented_original_colour_is_a_default_in_some_page():
    used = {name for page in PAGES.values() for name in root_variables(page)}
    assert used == set(theme.PAGE_ORIGINAL)


@pytest.mark.parametrize("page", sorted(PAGES))
def test_the_pages_write_no_colour_outside_their_variables(page):
    """A colour written into the CSS or the script would stay when the scheme changes. Allowed: the :root defaults and the two
    palettes with a meaning of their own (the lines of the chart, the quality of an item)."""
    for number, line in enumerate(PAGES[page].read_text(encoding="utf-8").splitlines(), 1):
        stripped = line.strip()
        if stripped.startswith((":root", "--")) or stripped.startswith(("const COLORS", "const QUALITY_COLOR")):
            continue
        assert not re.search(r"#[0-9a-fA-F]{3,8}\b", line), f"{PAGES[page].name}:{number}: {stripped[:80]}"


def test_every_variable_the_pages_use_has_a_default_and_a_role():
    used = set()
    for path in PAGES.values():
        used |= set(re.findall(r"var\((--[a-z]+)\)", path.read_text(encoding="utf-8")))
        used |= set(re.findall(r"css\(\"(--[a-z]+)\"\)", path.read_text(encoding="utf-8")))
    assert used <= set(theme.PAGE_ORIGINAL), used - set(theme.PAGE_ORIGINAL)
    assert set(theme.PAGE_ROLES) | {"--gold"} == set(theme.PAGE_ORIGINAL)


@pytest.mark.parametrize("number", sorted(theme.THEMES))
def test_a_scheme_gives_every_variable_a_valid_colour(number):
    variables = theme.page_variables(number)
    assert set(variables) == set(theme.PAGE_ORIGINAL)
    assert all(re.fullmatch(r"#[0-9a-f]{6}", value) for value in variables.values())


@pytest.mark.parametrize("number", sorted(theme.THEMES))
def test_the_page_text_colours_read_well_on_the_surfaces_they_sit_on(number):
    scheme, variables = theme.THEMES[number], theme.page_variables(number)
    for surface in ("--bg", "--panel", "--head", "--hover", "--field", "--card"):
        for text in ("--fg", "--dim", "--gold"):
            assert theme.contrast(variables[text], variables[surface]) >= theme.MIN_TEXT_CONTRAST, (number, text, surface)
    assert theme.contrast(variables["--best"], variables["--bg"]) >= theme.MIN_TEXT_CONTRAST


def test_an_accent_that_reads_well_stays_and_one_that_does_not_is_lightened():
    amber, ice = theme.THEMES[3], theme.THEMES[6]
    assert theme.readable_accent(amber) == amber["accent"]
    lightened = theme.readable_accent(ice)
    assert lightened != ice["accent"] and theme.contrast(lightened, ice["bg3"]) >= theme.MIN_TEXT_CONTRAST
    assert theme.contrast(ice["accent"], ice["bg3"]) < 3                 # the reason: the plain accent is unreadable there


def test_an_unknown_number_gives_the_default_look():
    assert theme.page_variables(99) == theme.page_variables(theme.DEFAULT_THEME)
