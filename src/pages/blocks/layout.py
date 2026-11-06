#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)
# layout.py
# StatTracker - which block fills which place of the stats page. The page (src/template.html) only holds numbered places,
# <div data-slot="3"></div>; INDEX says what stands in place 3 (the name of a block module and its arguments), MODULES
# knows the modules. A number is the identity of a place and says nothing about what stands there: moving a block to another
# place is one line of INDEX, moving a place is a change of the page. The numbers were given in the order the blocks had
# when the layout began (1 rates, 2 groups, 3 history links, 4 character selection, 5 reputation, 6 filter row, 7 counter,
# 8 table, 9 footer; 10 Top 5 came later, at the top of the page); a block that is moved into this table keeps its number. Places 6 (filter row) and 7 (counter) are part of place 8: they share its
# state, so one block writes the three; the numbers 6 and 7 are not given again. tests/test_blocks.py keeps the page, INDEX and
# MODULES in step. A block module has render(payload, view, slot, **args) -> HTML text and reads the payload only; one with state or
# actions also has handle(payload, view, slot, action, args) -> updates (see groups.py) and, if it depends on the ticked characters,
# USES_SELECTION = True. `view` (view.py) holds what the blocks of one shown page share.
# Needs the block modules and view; called by outputs.write_html (fill) and by the window (dispatch, select).

import re

from pages.blocks import char_picker, footer, groups, history_links, rates, reputation, stat_table, top5
from pages.blocks.view import View

# place number -> (block module name, arguments for its render); every place of the page has an entry here
INDEX = {
    1: ("rates", {}),
    2: ("groups", {}),
    3: ("history_links", {}),
    4: ("char_picker", {}),
    5: ("reputation", {}),
    8: ("stat_table", {}),
    9: ("footer", {}),
    10: ("top5", {}),
}

MODULES = {
    "rates": rates,
    "history_links": history_links,
    "groups": groups,
    "char_picker": char_picker,
    "reputation": reputation,
    "stat_table": stat_table,
    "footer": footer,
    "top5": top5,
}

SLOT = re.compile(r'<div data-slot="(\d+)"></div>')


def _entry(number: int):
    if number not in INDEX:
        raise LookupError(f"place {number} of the page has no entry in layout.INDEX")
    name, args = INDEX[number]
    return MODULES[name], args


def fill(template: str, payload: dict, view=None) -> str:
    """The page text with every numbered place filled by its block. A place of the page that INDEX does not know is an
    error of the program (the tests catch it), not of the data. `view`: what the blocks share (a new one when not given)."""
    view = view or View(payload)

    def put(match):
        number = int(match.group(1))
        module, args = _entry(number)
        return f'<div data-slot="{number}">{module.render(payload, view, slot=number, **args)}</div>'
    return SLOT.sub(put, template)


def dispatch(view, slot: int, action: str, args: dict) -> list:
    """The answer of the block at `slot` to an action of the page: the parts of the block that changed (a list of
    {"id", "html"?, "hidden"?, "disabled"?}); nothing for a block that has no actions."""
    module, _args = _entry(slot)
    if isinstance(args.get("controls"), dict):
        view.controls[slot] = args["controls"]                   # what the controls of the block show now (the snapshot writes them again)
    handler = getattr(module, "handle", None)
    return handler(view.payload, view, slot, action, args) if handler else []


def attach(view) -> dict:
    """The page is shown in the window and has handed over its data: {place number: updates} for the blocks that change with
    what the program offers (the presets of the Groups block)."""
    answers = {}
    for number, (name, _args) in INDEX.items():
        handler = getattr(MODULES[name], "handle", None)
        if handler:
            answers[number] = handler(view.payload, view, number, "attach", {})
    return answers


def select(view, keys, controls=None) -> dict:
    """The ticked characters changed: sets them and returns {place number: updates} for the blocks that depend on them.
    `controls`: {place number as text: the values of the controls of that block}."""
    view.select(keys)
    controls = {str(number): values for number, values in (controls or {}).items() if isinstance(values, dict)}      # a block gets a dict or nothing
    for number, values in controls.items():
        if number.isdigit() and int(number) in INDEX:
            view.controls[int(number)] = values
    answers = {}
    for number, (name, _args) in INDEX.items():
        module = MODULES[name]
        if getattr(module, "USES_SELECTION", False):
            answers[number] = module.handle(view.payload, view, number, "selection", {"controls": controls.get(str(number)) or {}})
    return answers
