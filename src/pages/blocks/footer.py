#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)
# footer.py
# StatTracker - the last line of the stats page: version, link to the project page, copyright and licence (the values of app_info, handed
# over in the payload as "app"). It replaces renderFoot of the page script (same element, id and class). Left out (empty text) when the page has
# no characters (the page then shows only its notice) or the payload has no "app". Needs markup.

import re

from pages.blocks.markup import esc, fmt, ui


def render(payload, view=None, slot=None, **_) -> str:
    app = payload.get("app")
    if not payload.get("chars") or not app:
        return ""
    shown = re.sub(r"/$", "", re.sub(r"^https://", "", app["site"]))
    return (f'<div class="foot" id="foot">{esc(fmt(ui(payload, "footer_version"), version=app["version"]))} · '
            f'<a href="{esc(app["site"])}" target="_blank" rel="noopener noreferrer">{esc(shown)}</a>'
            f' · {esc(app["copyright"])} · {esc(app["license"])}</div>')
