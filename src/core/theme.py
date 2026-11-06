#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)
# theme.py
# StatTracker - the colour schemes of the window, in one table (single source of truth). Same idea as the theme table of
# Garmin Local Archive: a complete scheme per number, the active one is stored in the settings (config: active_theme) and
# chosen in the window; a change takes effect after a restart. Leaf module: standard library only. The stats page and the
# history pages follow the scheme too: their colours are CSS variables, and the window sets them to the values of
# page_variables() before a page runs (the files themselves keep the original look, PAGE_ORIGINAL, as the default).
#
# Colour roles (the same in every scheme):
#   bg0      deepest background (the log console)
#   bg       main background (window)
#   bg2      raised surface (cards, groups)
#   bg3      dividers, tab bar, third layer
#   accent   primary: active tab, buttons, links, focus
#   accent2  secondary: hover state of accent
#   text     main text
#   text2    secondary text, labels
#   green    success / OK
#   yellow   warning
#   red      error
#
# A new scheme: copy a dict, give it the next free number and register it in THEMES; it then shows up in the window's
# dropdown by itself.

DEFAULT_THEME = 1

THEME_1 = {
    "name": "Monochrome + Rust Accent (default)",
    "bg0": "#0a0b0c", "bg": "#111214", "bg2": "#191b1e", "bg3": "#232629",
    "accent": "#c76a3f", "accent2": "#9c5330", "text": "#e8e9eb", "text2": "#9a9ea3",
    "green": "#4ecca3", "yellow": "#f5c542", "red": "#e94560",
}
THEME_2 = {
    "name": "Violet",
    "bg0": "#0a0a1a", "bg": "#12101f", "bg2": "#1a1729", "bg3": "#231f38",
    "accent": "#a259f7", "accent2": "#6e3fcf", "text": "#eaeaea", "text2": "#a0a0b0",
    "green": "#4ecca3", "yellow": "#f5a623", "red": "#e94560",
}
THEME_3 = {
    "name": "Amber & Copper",
    "bg0": "#0d0a08", "bg": "#161210", "bg2": "#201a17", "bg3": "#2b231e",
    "accent": "#d98a3d", "accent2": "#b56c28", "text": "#f0e6da", "text2": "#b8a894",
    "green": "#4ecca3", "yellow": "#f5c542", "red": "#e94560",
}
THEME_4 = {
    "name": "Olive & Sand",
    "bg0": "#0e0f0a", "bg": "#14150f", "bg2": "#1c1e15", "bg3": "#262919",
    "accent": "#a9b34d", "accent2": "#818c37", "text": "#eeeadb", "text2": "#aeaa96",
    "green": "#4ecca3", "yellow": "#f5c542", "red": "#e94560",
}
THEME_5 = {
    "name": "Toxic",
    "bg0": "#0a0c0b", "bg": "#121513", "bg2": "#262c2a", "bg3": "#3a423e",
    "accent": "#7a9e00", "accent2": "#6b8c00", "text": "#e4e8e5", "text2": "#9aa39d",
    "green": "#4ecca3", "yellow": "#f5c542", "red": "#e94560",
}
THEME_6 = {
    "name": "Ice Blue",
    "bg0": "#0a0c0b", "bg": "#121513", "bg2": "#262c2a", "bg3": "#3a423e",
    "accent": "#1f6488", "accent2": "#184e69", "text": "#e4e8e5", "text2": "#9aa39d",
    "green": "#4ecca3", "yellow": "#f5c542", "red": "#e94560",
}

THEMES = {1: THEME_1, 2: THEME_2, 3: THEME_3, 4: THEME_4, 5: THEME_5, 6: THEME_6}
ROLES = ("bg0", "bg", "bg2", "bg3", "accent", "accent2", "text", "text2", "green", "yellow", "red")


def is_known(number) -> bool:
    """True for the number of a registered scheme (a bool is not a number)."""
    return isinstance(number, int) and not isinstance(number, bool) and number in THEMES


def colors(number) -> dict:
    """The scheme with this number; an unknown number gives the default scheme (never an error)."""
    return THEMES[number] if is_known(number) else THEMES[DEFAULT_THEME]


def names() -> dict:
    """{number: name} for the dropdown, in the order of the numbers."""
    return {number: scheme["name"] for number, scheme in sorted(THEMES.items())}


# ----------------------------------------------------------------------------------------- the colours of the pages
# The colours the pages had before they followed the scheme (dark grey with gold): the defaults in the :root of src/template.html
# (stats page) and src/history.html (history pages), written down here as the backup of the original look and compared with
# the pages by tests/test_theme.py. Without a program window around them (a file opened in a browser) a page looks like this.
PAGE_ORIGINAL = {
    "--bg": "#121212", "--panel": "#1b1b1b", "--line": "#2e2e2e", "--fg": "#e0e0e0", "--dim": "#8a8a8a",
    "--gold": "#f4c430", "--best": "#5dd16b",
    "--field": "#101010", "--head": "#1e1e1e", "--hover": "#1a1a1a", "--track": "#2a2a2a",       # the stats page only
    "--card": "#161616", "--warn": "#e0a050",                                                     # the history pages only
}

# Which role of the scheme becomes which variable (text sits on --bg, --panel, --head, --hover, --field and --card; --line and
# --track only draw lines and bars, so they take the lighter bg3). "--gold" (the accent: headings, table heads, hover) is not listed: it is
# used as a text colour, so it is the readable variant of the accent (readable_accent).
PAGE_ROLES = {
    "--bg": "bg", "--panel": "bg2", "--line": "bg3", "--fg": "text", "--dim": "text2", "--best": "green",
    "--field": "bg0", "--head": "bg2", "--hover": "bg2", "--track": "bg3", "--card": "bg2", "--warn": "yellow",
}
MIN_TEXT_CONTRAST = 4.5          # WCAG: normal text


def _rgb(color):
    return [int(color[i:i + 2], 16) for i in (1, 3, 5)]


def _luminance(color):
    lin = [c / 255 / 12.92 if c / 255 <= 0.03928 else ((c / 255 + 0.055) / 1.055) ** 2.4 for c in _rgb(color)]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def contrast(a, b) -> float:
    """The WCAG contrast ratio of two colours (1 to 21)."""
    hi, lo = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def _mix(a, b, share):
    """`a` moved towards `b` by `share` (0 = a, 1 = b), as "#rrggbb"."""
    return "#" + "".join(f"{round(x + (y - x) * share):02x}" for x, y in zip(_rgb(a), _rgb(b)))


def readable_accent(scheme) -> str:
    """The accent as a text colour: unchanged when it reads well on the three surfaces (bg, bg2, bg3), otherwise moved
    towards the text colour in steps of 5 % until it does. (Ice Blue is too dark as it is: 1.6 on bg3.)"""
    surfaces = (scheme["bg"], scheme["bg2"], scheme["bg3"])
    for step in range(21):
        color = _mix(scheme["accent"], scheme["text"], step / 20)
        if min(contrast(color, surface) for surface in surfaces) >= MIN_TEXT_CONTRAST:
            return color if step else scheme["accent"]
    return scheme["text"]


def page_variables(number) -> dict:
    """The CSS variables of the pages for the scheme with this number (an unknown number gives the default scheme)."""
    scheme = colors(number)
    variables = {name: scheme[role] for name, role in PAGE_ROLES.items()}
    variables["--gold"] = readable_accent(scheme)
    return variables
