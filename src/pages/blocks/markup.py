#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)
# markup.py
# StatTracker - the small helpers every block of the stats page uses to write HTML: esc (text and attribute values are
# escaped here and nowhere else), fmt ("{name}" placeholders of the page texts, like the fmt of the page script), plain (a number as
# text) and ui (a page text of the payload, "" when it is missing). Leaf module: standard library only.

import html
import re

_PLACEHOLDER = re.compile(r"\{(\w+)\}")


def esc(value) -> str:
    """Text or attribute value made safe for HTML (&, <, >, and both quotes)."""
    return html.escape(str(value), quote=True)


def fmt(text, **values) -> str:
    """Fills the {name} marks of a page text; a mark without a value becomes empty (as in the page script)."""
    return _PLACEHOLDER.sub(lambda m: str(values.get(m.group(1), "")), text or "")


def plain(number) -> str:
    """A number as the page script wrote it into a text (1 and not 1.0)."""
    return str(int(number)) if float(number).is_integer() else str(number)


def ui(payload, name) -> str:
    """The page text `name` of the payload ("ui" holds the html_* texts of i18n in the language of the page)."""
    return (payload.get("ui") or {}).get(name) or ""
