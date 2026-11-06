#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)
# view.py
# StatTracker - what the blocks of one shown stats page share: the payload of the page, the characters ticked in the selection
# (all of them at the start), the state of every block that has one (by the number of its place), and, when the program
# offers it, the store of presets, and the values the controls of every block had when they last spoke (`controls`: place -> {name: value}; the
# blocks that show a search text or a choice write it into the page from here). A page that is only written (the tests) has a View of its own with
# no store; the snapshot is written from a copy of the View of the shown page (`snapshot()`). Leaf module: standard library only.
#
# The store of presets is any object with: name_max (int), load() -> list of {"name", "by", "off", "extras"}, save(list) -> bool.
# The window gives one (it keeps the presets in the settings file); blocks never write a file themselves.

import copy


class View:
    def __init__(self, payload: dict, presets=None):
        self.payload = payload
        self.presets = presets
        self.selected = [c["key"] for c in payload.get("chars") or []]
        self.states = {}
        self.controls = {}          # place number -> the values of its controls at the last message of the page

    def chars(self) -> list:
        """The ticked characters, in the order of the payload."""
        ticked = set(self.selected)
        return [c for c in self.payload.get("chars") or [] if c["key"] in ticked]

    def select(self, keys) -> None:
        """Sets the ticked characters; a key the page does not have is ignored."""
        known = {c["key"] for c in self.payload.get("chars") or []}
        wanted = set(keys or [])
        self.selected = [c["key"] for c in self.payload.get("chars") or [] if c["key"] in wanted and c["key"] in known]

    def state(self, slot, factory):
        """The state of the block at this place, made by `factory()` the first time."""
        if slot not in self.states:
            self.states[slot] = factory()
        return self.states[slot]

    def snapshot(self):
        """A copy of what the page shows now (ticked characters, the state and the controls of every block), apart from the original and without the
        store of presets (a written page cannot save them). Writing the page from the copy changes nothing in the shown page."""
        other = View(self.payload)
        other.selected = list(self.selected)
        other.states = copy.deepcopy(self.states)
        other.controls = copy.deepcopy(self.controls)
        return other
