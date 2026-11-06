#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)
# page_bridge.py
# StatTracker - the bridge between the stats page shown in the window and the blocks of pages/blocks. The page (the script STT of
# template.html) calls it through QWebChannel: attach (once, with the data of the page), act (an action of a block, a click or a
# change), select (the ticked characters changed). The answers are JSON texts: the parts of the blocks that changed. ConfigPresets is
# the store of presets the blocks use: the list lives in the settings (config.group_presets) and is written by core.config.
# channel_script_source gives the script of Qt (qwebchannel.js) that the window puts into the pages that it shows.
# A bad message from a page (no JSON, an unknown place) is answered with nothing; an error of the program is reported through
# sys.excepthook (the window shows it) and answered with nothing, so a page never waits for a reply. Needs layout, view, config.

import json
import sys

from PyQt6.QtCore import QFile, QIODevice, QObject, pyqtSlot
from PyQt6.QtWebChannel import QWebChannel  # noqa: F401  (imported so that the resource of Qt below is there)

from core import config
from pages.blocks import layout
from pages.blocks.view import View

CHANNEL_RESOURCE = ":/qtwebchannel/qwebchannel.js"


def channel_script_source() -> str:
    """The text of qwebchannel.js that comes with Qt; "" when it cannot be read (the pages then stay as they were written)."""
    resource = QFile(CHANNEL_RESOURCE)
    if not resource.open(QIODevice.OpenModeFlag.ReadOnly):
        return ""
    try:
        return bytes(resource.readAll()).decode("utf-8")
    finally:
        resource.close()


class ConfigPresets:
    """The store of presets of the Groups block: the list in the settings of the window (`cfg`, the dict the window keeps)."""
    name_max = config.PRESET_NAME_MAX

    def __init__(self, cfg: dict):
        self._cfg = cfg

    def load(self) -> list:
        return [{"name": p["name"], "by": p["by"], "off": list(p["off"]), "extras": [dict(e) for e in p["extras"]]}
                for p in self._cfg.get("group_presets") or []]

    def save(self, items: list) -> bool:
        """Writes the list into the settings file; on a failure the list stays as it was and False is returned."""
        before = self._cfg.get("group_presets") or []
        self._cfg["group_presets"] = config.clean_presets(items)
        try:
            config.save(self._cfg)
        except OSError:
            self._cfg["group_presets"] = before
            return False
        return True


def _loads(text):
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        return None


class PageBridge(QObject):
    """What the page calls. One page at a time: attach starts a new View (the state of the blocks) for the page that is shown."""

    def __init__(self, presets, parent=None):
        super().__init__(parent)
        self.presets = presets
        self.view = None

    def _answer(self, work) -> str:
        try:
            return json.dumps(work(), ensure_ascii=False)
        except Exception:                                  # a bug: the window reports it, the page gets nothing
            sys.excepthook(*sys.exc_info())
            return "[]"

    @pyqtSlot(str, result=str)
    def attach(self, payload_json):
        """The page hands over its data (once per load). Answer: the parts of the blocks that change with what the program offers."""
        payload = _loads(payload_json)
        if not (isinstance(payload, dict) and isinstance(payload.get("chars"), list)):
            self.view = None
            return "[]"
        self.view = View(payload, presets=self.presets)
        return self._answer(lambda: [u for updates in layout.attach(self.view).values() for u in updates])

    @pyqtSlot(int, str, str, result=str)
    def act(self, place, action, args_json):
        """An action of the block at a place of the page. Answer: a list of {id, html?, hidden?, disabled?}."""
        args = _loads(args_json)
        if self.view is None or not isinstance(args, dict) or place not in layout.INDEX:
            return "[]"                                    # no page attached, or a message the page should not have sent
        return self._answer(lambda: layout.dispatch(self.view, place, action, args))

    @pyqtSlot(str, str, result=str)
    def select(self, keys_json, controls_json):
        """The ticked characters changed (a list of keys; controls: {place: values of its controls}). Answer: {place: updates}."""
        keys, controls = _loads(keys_json), _loads(controls_json)
        if self.view is None or not isinstance(keys, list) or not isinstance(controls, dict):
            return "{}"
        return self._answer(lambda: layout.select(self.view, [k for k in keys if isinstance(k, str)], controls))
