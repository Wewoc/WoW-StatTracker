#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)
# qwebengine_hardening.py
# StatTracker - conservative settings for the embedded browser view (same idea and same list as in Garmin Local Archive).
# The view shows only pages this program wrote itself (the stats page and the history pages, data embedded): it needs no
# access from a local page to other files or to remote addresses, no pop-up windows, no plug-ins and no clipboard access
# from the page. JavaScript itself stays on (the pages draw with it). Leaf module: PyQt6 only, no project imports.


def harden(view) -> None:
    """Applies the settings to a QWebEngineView that is already constructed (settings() needs a real view). Safe to call
    more than once."""
    from PyQt6.QtWebEngineCore import QWebEngineSettings
    attributes = QWebEngineSettings.WebAttribute
    settings = view.settings()
    for name, value in (("LocalContentCanAccessFileUrls", False), ("LocalContentCanAccessRemoteUrls", False),
                        ("JavascriptCanOpenWindows", False), ("PluginsEnabled", False),
                        ("JavascriptCanAccessClipboard", False)):
        settings.setAttribute(getattr(attributes, name), value)
