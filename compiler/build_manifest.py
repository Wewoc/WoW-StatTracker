#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)
# compiler/build_manifest.py - single source of truth for the PyInstaller build.
#
# No logic: build.py reads this. Names and the list of release items come from
# src/app_info.py (also read by the updater at runtime), so build and updater
# can never disagree about what a release contains.

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import app_info  # noqa: E402
import plotly_asset  # noqa: E402

APP_NAME = app_info.APP_NAME
ENTRY_POINT = "src/start.py"

# Added to PyInstaller's analysis path so the flat modules (config, wow_install, ...)
# resolve the same way start.py's runtime sys.path.insert() does.
EXTRA_PATHS = ["src"]

# Read-only assets bundled into the build (PyInstaller --add-data): (source, target folder inside the bundle).
DATA_FILES = [
    ("src/template.html", "."),
    ("src/history.html", "."),
    ("src/updater_helper.ps1", "."),
]

# Bundled like DATA_FILES but not in the repository: compiler/plotly_fetch.py puts them in
# place (the build runs it first).
FETCHED_FILES = [
    ("src/" + plotly_asset.FILENAME, "."),
]

# Modules that are only imported inside functions or try/except (found anyway,
# listed for certainty).
HIDDEN_IMPORTS = ["openpyxl"]

# Shipped next to the exe (see app_info.PROGRAM_ITEMS):
ADDON_SRC = "addon"                     # -> <dist>/addon/StatTracker/
INFO_DIR = "info"
INFO_FILES = ["README.md", "README.de.md", "CHANGELOG.md"]   # -> <dist>/info/
LICENSE_FILE = "LICENSE"                # -> <dist>/LICENSE

ZIP_NAME = app_info.ZIP_ASSET_NAME
CHECKSUM_NAME = app_info.ZIP_CHECKSUM_ASSET_NAME
PROGRAM_ITEMS = list(app_info.PROGRAM_ITEMS)
