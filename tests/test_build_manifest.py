# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

from pathlib import Path

import app_info
import build_manifest as manifest

ROOT = Path(__file__).resolve().parent.parent


def test_release_items_come_from_app_info():
    assert manifest.PROGRAM_ITEMS == app_info.PROGRAM_ITEMS
    assert manifest.ZIP_NAME == app_info.ZIP_ASSET_NAME
    assert manifest.CHECKSUM_NAME == app_info.ZIP_CHECKSUM_ASSET_NAME == "StatTracker.zip.sha256"


def test_all_bundled_and_shipped_sources_exist():
    for src, _dest in manifest.DATA_FILES:
        assert (ROOT / src).is_file(), src
    for rel in manifest.INFO_FILES + [manifest.LICENSE_FILE, manifest.ENTRY_POINT, "requirements.txt"]:
        assert (ROOT / rel).is_file(), rel
    assert (ROOT / manifest.ADDON_SRC / "StatTracker" / "StatTracker.toc").is_file()


def test_every_release_item_is_produced_by_the_build():
    produced = {app_info.EXE_NAME, "_internal",                       # PyInstaller onedir
                manifest.ADDON_SRC, manifest.INFO_DIR, manifest.LICENSE_FILE}   # build.copy_extras
    assert set(manifest.PROGRAM_ITEMS) == produced


def test_runtime_files_are_bundled():
    bundled = {Path(src).name for src, _ in manifest.DATA_FILES}
    assert {"template.html", "updater_helper.ps1"} <= bundled
