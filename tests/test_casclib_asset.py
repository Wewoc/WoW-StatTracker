# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)
# The pinned CascLib: what the pin says (casclib_asset). Building it is tested in test_casclib_build.

import re

import casclib_asset
import paths


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
