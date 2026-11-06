#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)
# casclib_asset.py
# StatTracker - the pinned CascLib for reading item icons from a local WoW installation:
# version, source commit, file name and location. Leaf-Node: stdlib and paths only.
#
# CascLib.dll is not part of the repository. compiler/casclib_build.py builds it from the pinned
# commit into src/ (build and CI only, never at runtime) and the build bundles it next to
# template.html. At runtime wow_icons only loads the file from path(); the program neither
# builds nor downloads anything. Update VERSION and COMMIT together, never one of them alone.
#
# CascLib is MIT licensed (Copyright (c) Ladislav Zezula); the notice is in both READMEs.

from core import paths

VERSION = "3.0"
REPO_URL = "https://github.com/ladislav-zezula/CascLib"
COMMIT = "4971d363e665551ac4142f541e5f2d71f1cda653"       # the commit of the tag "3.0"
FILENAME = "CascLib.dll"
UNICODE = True                                            # CASC_UNICODE: the DLL takes UTF-16 paths

# What wow_icons calls. The build refuses a DLL that lacks one of them; the online storage and
# download functions of the library are deliberately not in this list and never called.
EXPORTS = ("CascOpenStorage", "CascCloseStorage", "CascOpenFile", "CascGetFileSize64", "CascReadFile",
           "CascCloseFile", "GetCascError")


def path():
    """Where the DLL lives: next to template.html (src/ from source, the bundle folder when frozen)."""
    return paths.resource_dir() / FILENAME
