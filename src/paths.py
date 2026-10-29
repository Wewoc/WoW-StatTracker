#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)
# paths.py
# StatTracker - sole source for directory resolution (portable mode).
# Leaf-Node: only app_info.
#
#   base_dir()      instance folder: next to StatTracker.exe when frozen,
#                   the repository root when run from source
#   data_dir()      <base>/data - config, databases, generated pages, Excel
#   resource_dir()  read-only bundled files (template.html, updater helper)
#   addon_src()     the addon folder that gets copied into WoW
#
# Every module derives its paths from here, at call time (never cached at
# import), so tests can redirect base_dir() to a temporary folder.

import sys
from pathlib import Path

import app_info


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def base_dir() -> Path:
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def data_dir() -> Path:
    return base_dir() / app_info.DATA_DIRNAME


def resource_dir() -> Path:
    if is_frozen():
        return Path(getattr(sys, "_MEIPASS", base_dir() / "_internal"))
    return Path(__file__).resolve().parent


def addon_src() -> Path:
    return base_dir() / "addon" / app_info.APP_NAME
