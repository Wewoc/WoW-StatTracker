#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)
# app_info.py
# StatTracker - single source for name, version, repository, license and the
# list of files that make up a release. Leaf-Node: stdlib only, no project
# imports (compiler/build_manifest.py imports it too).

APP_NAME = "StatTracker"
APP_VERSION = "0.1.0"  # must equal "## Version:" in addon/StatTracker/StatTracker.toc (tests check it)

# Repository (github.com/Wewoc/WoW-StatTracker). The product, exe, release assets and the
# addon keep the name "StatTracker"; only the GitHub repository is called WoW-StatTracker.
# REPO_CONFIRMED is the switch for the update check: while it is False no request is sent
# and the About window says the repository link is a placeholder (use it for forks/tests).
REPO_OWNER = "Wewoc"
REPO_NAME = "WoW-StatTracker"
REPO_CONFIRMED = True

REPO_URL = f"https://github.com/{REPO_OWNER}/{REPO_NAME}"
RELEASES_URL = f"{REPO_URL}/releases/latest"
LATEST_API_URL = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/releases/latest"

COPYRIGHT = "© 2026 Wewoc"
LICENSE_NAME = "GNU GPL v3"

# Release layout (see compiler/build_manifest.py, src/updater.py).
EXE_NAME = f"{APP_NAME}.exe"
DATA_DIRNAME = "data"
ZIP_ASSET_NAME = f"{APP_NAME}.zip"
ZIP_CHECKSUM_ASSET_NAME = ZIP_ASSET_NAME + ".sha256"
# Everything the updater replaces. Deliberately NOT data/: user data
# (database, config, generated pages) is never part of a release and never
# touched by an update.
PROGRAM_ITEMS = [EXE_NAME, "_internal", "addon", "info", "LICENSE"]


def parse_version(text: str):
    """'v1.2.3' / '1.2.3' -> (1, 2, 3); None if not a plain dotted number."""
    try:
        parts = tuple(int(p) for p in str(text).strip().lstrip("vV").split("."))
    except ValueError:
        return None
    return parts or None


def is_newer(latest: str, current: str) -> bool:
    """True only if `latest` is a well-formed, strictly higher version than
    `current`. Unparseable input counts as 'not newer', never as 'newer': an
    update can be applied automatically, so doubt must not trigger one."""
    a, b = parse_version(latest), parse_version(current)
    if a is None or b is None:
        return False
    return a > b
