#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)
# char_picker.py
# StatTracker - the character selection of the stats page (place 4): one button ("Select all" while a character is unticked, "Deselect all"
# when all are ticked) and one check box per character. It replaces the code of the page script that built the same elements (same ids:
# `chars`, `toggleAll`, `chk_<key>`; same classes). The ticked characters themselves live in the page (the boxes) and in View.selected; the
# page script tells Python when they change (STT.selection -> bridge.select) and the blocks that depend on them answer (USES_SELECTION).
# This block answers with the text of its button. The button asks for "pick_all": Python says which boxes to set (every box on, or every
# box off when all are on) and the text of the button; the page then reports the new selection like for any other tick. Empty text when the
# page has no characters. Needs markup.

from pages.blocks.markup import esc, ui

USES_SELECTION = True


def _label(payload, all_ticked) -> str:
    return ui(payload, "deselect_all") if all_ticked else ui(payload, "select_all")


def render(payload, view=None, slot=None, **_) -> str:
    keys = [c["key"] for c in payload.get("chars") or []]
    if not keys:
        return ""
    ticked = set(view.selected) if view is not None else set(keys)
    boxes = "".join(
        f'<label><input type="checkbox" id="chk_{esc(key)}" data-pick data-name="{esc(key)}"{" checked" if key in ticked else ""}> {esc(key)}</label>'
        for key in keys)
    return (f'<div class="bar chars" id="chars"><button type="button" id="toggleAll" data-action="pick_all" data-then="selection">'
            f'{esc(_label(payload, all(key in ticked for key in keys)))}</button>{boxes}</div>')


def handle(payload, view, slot, action, args) -> list:
    keys = [c["key"] for c in payload.get("chars") or []]
    if action == "pick_all":
        # the boxes as the page shows them (controls): all on -> all off, anything else -> all on
        boxes = args.get("controls") or {}
        now = not all(boxes.get(key) is True for key in keys)
        return [{"id": f"chk_{key}", "checked": now} for key in keys] + [{"id": "toggleAll", "html": esc(_label(payload, now))}]
    if action == "selection":                           # the ticked characters changed (a box, or "pick_all" above)
        return [{"id": "toggleAll", "html": esc(_label(payload, all(key in view.selected for key in keys)))}]
    return []
