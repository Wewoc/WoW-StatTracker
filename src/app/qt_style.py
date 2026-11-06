#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)
# qt_style.py
# StatTracker - the one style sheet of the window, made from a colour scheme of core/theme.py (so the whole look follows
# the scheme, and a new scheme needs no change here). Pure text in, text out: no Qt import, no project import.
# Widgets that need a special look carry an object name (log, hint, link, primary) and are styled by it here.
# page_script is the other half: the script that gives the pages shown in the window the same colours.

import json


def stylesheet(c: dict, text_accent: str = "") -> str:
    """The style sheet for a colour scheme `c` (the roles of core/theme.py). `text_accent` is the accent as a text colour
    (core/theme.readable_accent: the plain accent can be too dark to read on a dark surface); without it the accent itself."""
    text_accent = text_accent or c['accent']
    return f"""
QWidget {{ background: {c['bg']}; color: {c['text']}; font-family: 'Segoe UI'; font-size: 9pt; font-weight: normal; }}
QLabel {{ background: transparent; }}
QLabel#hint {{ color: {c['text2']}; }}
QLabel#title {{ font-size: 14pt; font-weight: bold; }}
QLabel#status {{ color: {c['text2']}; background: transparent; padding: 0 6px; }}
QLabel#placeholder {{ color: {c['text2']}; font-size: 10pt; }}
QCheckBox {{ background: transparent; spacing: 6px; }}
QGroupBox {{ background: {c['bg2']}; border: 1px solid {c['bg3']}; border-radius: 4px; margin-top: 30px; padding: 10px 8px 6px 8px; font-size: 12pt; font-weight: bold; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 6px 6px 6px; color: {text_accent}; background: transparent; }}
QPushButton {{ background: {c['bg3']}; color: {c['text']}; border: none; border-radius: 2px; padding: 5px 12px; }}
QPushButton:hover {{ background: {c['accent2']}; }}
QPushButton:disabled {{ color: {c['text2']}; background: {c['bg2']}; }}
QPushButton#primary {{ background: {c['accent']}; }}
QPushButton#primary:hover {{ background: {c['accent2']}; }}
QPushButton#link {{ background: transparent; color: {c['text2']}; padding: 2px 6px; }}
QPushButton#link:hover {{ color: {c['text']}; background: transparent; }}
QLineEdit, QComboBox {{ background: {c['bg3']}; color: {c['text']}; border: none; padding: 4px; }}
QComboBox::drop-down {{ border: none; width: 18px; }}
QComboBox QAbstractItemView {{ background: {c['bg3']}; color: {c['text']}; selection-background-color: {c['accent2']}; border: none; }}
QTabWidget::pane {{ border: none; background: {c['bg']}; }}
QTabBar::tab {{ background: {c['bg3']}; color: {c['text2']}; padding: 6px 18px; border: none; }}
QTabBar::tab:selected {{ background: {c['bg']}; color: {c['text']}; border-bottom: 2px solid {c['accent']}; }}
QTabBar::tab:hover {{ color: {c['text']}; }}
QPlainTextEdit#log {{ background: {c['bg0']}; color: {c['text']}; border: none; padding: 4px; font-family: Consolas; font-size: 9pt; }}
QStatusBar {{ background: {c['bg3']}; color: {c['text2']}; }}
QStatusBar::item {{ border: none; }}
QScrollBar:vertical {{ background: {c['bg']}; width: 10px; }}
QScrollBar::handle:vertical {{ background: {c['bg3']}; min-height: 20px; border-radius: 4px; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QToolTip {{ background: {c['bg3']}; color: {c['text']}; border: 1px solid {c['accent']}; padding: 4px; }}
QMessageBox, QDialog {{ background: {c['bg']}; }}
"""


def page_script(variables: dict) -> str:
    """JavaScript for the browser view, run when a document is created (before the page's own scripts): sets the CSS
    variables (--bg, --gold, ...) on the root element, which wins over the defaults in the page. The root element may not
    exist yet at that moment, then an observer sets them as soon as it does."""
    return ("(function () {\n"
            f"  var vars = {json.dumps(variables, sort_keys=True)};\n"
            "  function apply() {\n"
            "    var root = document.documentElement;\n"
            "    if (!root) { return false; }\n"
            "    for (var name in vars) { root.style.setProperty(name, vars[name]); }\n"
            "    return true;\n"
            "  }\n"
            "  if (!apply()) {\n"
            "    new MutationObserver(function (_changes, observer) { if (apply()) { observer.disconnect(); } })\n"
            "      .observe(document, {childList: true});\n"
            "  }\n"
            "})();\n")
