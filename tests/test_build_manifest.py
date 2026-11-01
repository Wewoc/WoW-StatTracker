# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

from pathlib import Path

import pytest

import app_info
import build_manifest as manifest
import plotly_asset

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
    bundled = {Path(src).name for src, _ in manifest.DATA_FILES + manifest.FETCHED_FILES}
    assert {"template.html", "updater_helper.ps1", plotly_asset.FILENAME} <= bundled


def test_fetched_files_are_kept_apart_from_the_checked_in_ones():
    fetched = {Path(src).name for src, _ in manifest.FETCHED_FILES}
    assert fetched == {plotly_asset.FILENAME}
    assert not fetched & {Path(src).name for src, _ in manifest.DATA_FILES}


def test_fetched_files_exist_once_they_were_fetched():
    missing = [src for src, _ in manifest.FETCHED_FILES if not (ROOT / src).is_file()]
    if missing:
        pytest.skip(f"not fetched yet ({', '.join(missing)}): python compiler/plotly_fetch.py")
