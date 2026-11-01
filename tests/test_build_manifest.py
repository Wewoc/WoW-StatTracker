# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

from pathlib import Path

import pytest

import app_info
import build
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
    assert {"template.html", "history.html", "updater_helper.ps1", plotly_asset.FILENAME} <= bundled


def test_fetched_files_are_kept_apart_from_the_checked_in_ones():
    fetched = {Path(src).name for src, _ in manifest.FETCHED_FILES}
    assert fetched == {plotly_asset.FILENAME}
    assert not fetched & {Path(src).name for src, _ in manifest.DATA_FILES}


def fake_bundle(tmp_path, skip_file=None, skip_module=None, toc="ok"):
    """A finished PyInstaller folder reduced to what the check reads: the data files in _internal and the
    module table of the work folder."""
    dist = tmp_path / "dist" / "StatTracker"
    inside = dist / build.CONTENTS_DIR
    inside.mkdir(parents=True)
    for src, _dest in manifest.DATA_FILES + manifest.FETCHED_FILES:
        if Path(src).name != skip_file:
            (inside / Path(src).name).write_text("x", encoding="utf-8")
    modules = sorted(build.expected_modules(ROOT) - {skip_module})
    toc_path = tmp_path / "PYZ-00.toc"
    if toc == "ok":
        toc_path.write_text(repr(("x.pyz", [(m, f"/x/{m}.py", "PYMODULE") for m in modules])), encoding="utf-8")
    elif toc == "garbage":
        toc_path.write_text("not a table", encoding="utf-8")
    return dist, toc_path


def test_a_complete_bundle_has_no_problems(tmp_path):
    dist, toc = fake_bundle(tmp_path)
    assert build.bundle_problems(ROOT, dist, toc) == []


@pytest.mark.parametrize("name", ["template.html", "history.html", "updater_helper.ps1", plotly_asset.FILENAME])
def test_a_data_file_missing_from_the_bundle_is_reported(tmp_path, name):
    dist, toc = fake_bundle(tmp_path, skip_file=name)
    problems = build.bundle_problems(ROOT, dist, toc)
    assert len(problems) == 1 and name in problems[0]


@pytest.mark.parametrize("module", ["stat_history", "stat_parser", "export_xlsx", "updater", "openpyxl", "ctypes"])
def test_a_module_missing_from_the_bundle_is_reported(tmp_path, module):
    """Imports inside functions are the ones PyInstaller can miss; a bundle without them starts and then fails."""
    dist, toc = fake_bundle(tmp_path, skip_module=module)
    problems = build.bundle_problems(ROOT, dist, toc)
    assert len(problems) == 1 and module in problems[0]


def test_the_entry_script_is_not_expected_in_the_module_table():
    assert Path(manifest.ENTRY_POINT).stem not in build.expected_modules(ROOT)
    assert {"stat_history", "openpyxl"} <= build.expected_modules(ROOT)


@pytest.mark.parametrize("toc", ["garbage", "absent"])
def test_an_unreadable_module_table_fails_loudly(tmp_path, toc):
    dist, toc_path = fake_bundle(tmp_path, toc=toc)
    problems = build.bundle_problems(ROOT, dist, toc_path)
    assert problems and "module table" in problems[-1]


def test_fetched_files_exist_once_they_were_fetched():
    missing = [src for src, _ in manifest.FETCHED_FILES if not (ROOT / src).is_file()]
    if missing:
        pytest.skip(f"not fetched yet ({', '.join(missing)}): python compiler/plotly_fetch.py")
