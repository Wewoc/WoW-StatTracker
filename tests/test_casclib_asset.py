# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)
# The pinned CascLib: what the pin says (casclib_asset). Building it is tested in test_casclib_build.

import re
from pathlib import Path

from core import paths
from game import casclib_asset

ROOT = Path(__file__).resolve().parent.parent


def test_the_pin_names_one_commit_of_an_https_repository():
    assert re.fullmatch(r"[0-9a-f]{40}", casclib_asset.COMMIT)
    assert casclib_asset.REPO_URL.startswith("https://")
    assert re.fullmatch(r"\d+(\.\d+)*", casclib_asset.VERSION)


def test_the_dll_lives_next_to_the_other_bundled_files(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "resource_dir", lambda: tmp_path)
    assert casclib_asset.path() == tmp_path / "CascLib.dll"


def test_the_program_calls_only_the_local_storage_functions():
    """The library also has an online storage and a CDN download; the program never uses them."""
    forbidden = [name for name in casclib_asset.EXPORTS if "Online" in name or "Cdn" in name]
    assert forbidden == []
    assert {"CascOpenStorage", "CascOpenFile", "CascReadFile", "CascCloseFile"} <= set(casclib_asset.EXPORTS)


def test_the_license_text_that_ships_names_the_pinned_version_and_carries_the_mit_notice():
    """CascLib.dll is in the release, so the MIT notice has to go with it (info/THIRD_PARTY_LICENSES.md)."""
    text = (ROOT / "THIRD_PARTY_LICENSES.md").read_text(encoding="utf-8")
    assert casclib_asset.COMMIT in text and f"version {casclib_asset.VERSION}" in text and casclib_asset.REPO_URL in text
    assert "Copyright (c) 2014 Ladislav Zezula" in text and "The MIT License (MIT)" in text
    assert "The above copyright notice and this permission notice shall be included in all" in text
