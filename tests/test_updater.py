# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

import hashlib
import zipfile
from pathlib import Path

import pytest

import app_info
import paths
import updater


@pytest.fixture
def allow_files(monkeypatch):
    monkeypatch.setattr(updater, "ALLOWED_SCHEMES", ("https", "file"))


def make_release(folder: Path, skip=(), top="StatTracker", checksum=None, name="StatTracker.zip"):
    """Writes a release ZIP (+ checksum file) into folder; returns (zip_url, checksum_url)."""
    folder.mkdir(parents=True, exist_ok=True)
    zip_path = folder / name
    with zipfile.ZipFile(zip_path, "w") as zf:
        for item in app_info.PROGRAM_ITEMS:
            if item in skip:
                continue
            prefix = f"{top}/" if top else ""
            if item in ("_internal", "addon", "info"):
                zf.writestr(f"{prefix}{item}/file.txt", "new")
            else:
                zf.writestr(f"{prefix}{item}", "new")
    digest = checksum or hashlib.sha256(zip_path.read_bytes()).hexdigest()
    sum_path = folder / (name + ".sha256")
    sum_path.write_text(f"{digest}  {name}\n", encoding="ascii")
    return zip_path.as_uri(), sum_path.as_uri()


def test_resolve_release_asset_is_exact():
    release = {"assets": [
        {"name": "StatTracker.zip.sha256", "browser_download_url": "https://x/sum"},
        {"name": "StatTracker.zip", "browser_download_url": "https://x/zip"},
    ]}
    assert updater.resolve_release_asset(release, "StatTracker.zip") == "https://x/zip"
    assert updater.resolve_release_asset(release, "Stat") is None
    assert updater.resolve_release_asset({}, "StatTracker.zip") is None


def test_prepare_update_extracts_and_returns_payload(tmp_path, allow_files):
    base = tmp_path / "app"
    base.mkdir()
    zip_url, sum_url = make_release(tmp_path / "rel")
    payload = updater.prepare_update(base, zip_url, sum_url)
    assert payload == base / "_update_pending" / "StatTracker"
    for item in app_info.PROGRAM_ITEMS:
        assert (payload / item).exists()
    assert not (base / "_update_pending" / "update.zip").exists()


def test_prepare_update_accepts_a_flat_zip(tmp_path, allow_files):
    base = tmp_path / "app"
    base.mkdir()
    zip_url, sum_url = make_release(tmp_path / "rel", top="")
    payload = updater.prepare_update(base, zip_url, sum_url)
    assert payload == base / "_update_pending"


def test_checksum_mismatch_discards_everything(tmp_path, allow_files):
    base = tmp_path / "app"
    base.mkdir()
    zip_url, sum_url = make_release(tmp_path / "rel", checksum="0" * 64)
    with pytest.raises(RuntimeError, match="Checksum mismatch"):
        updater.prepare_update(base, zip_url, sum_url)
    assert not (base / "_update_pending").exists()


def test_missing_checksum_refuses_fail_closed(tmp_path, allow_files):
    base = tmp_path / "app"
    base.mkdir()
    zip_url, _ = make_release(tmp_path / "rel")
    with pytest.raises(RuntimeError, match="checksum"):
        updater.prepare_update(base, zip_url, None)
    assert not (base / "_update_pending").exists()


def test_incomplete_package_is_refused(tmp_path, allow_files):
    base = tmp_path / "app"
    base.mkdir()
    zip_url, sum_url = make_release(tmp_path / "rel", skip=("LICENSE",))
    with pytest.raises(RuntimeError, match="LICENSE"):
        updater.prepare_update(base, zip_url, sum_url)
    assert not (base / "_update_pending").exists()


def test_not_a_zip_is_refused(tmp_path, allow_files):
    base = tmp_path / "app"
    base.mkdir()
    bad = tmp_path / "rel"
    bad.mkdir()
    (bad / "StatTracker.zip").write_bytes(b"this is not a zip")
    digest = hashlib.sha256(b"this is not a zip").hexdigest()
    (bad / "StatTracker.zip.sha256").write_text(digest, encoding="ascii")
    with pytest.raises(RuntimeError, match="not a valid ZIP"):
        updater.prepare_update(base, (bad / "StatTracker.zip").as_uri(), (bad / "StatTracker.zip.sha256").as_uri())
    assert not (base / "_update_pending").exists()


def test_leftover_pending_folder_is_cleaned_first(tmp_path, allow_files):
    base = tmp_path / "app"
    (base / "_update_pending").mkdir(parents=True)
    (base / "_update_pending" / "stale.txt").write_text("old", encoding="utf-8")
    zip_url, sum_url = make_release(tmp_path / "rel")
    updater.prepare_update(base, zip_url, sum_url)
    assert not (base / "_update_pending" / "stale.txt").exists()


def test_only_https_is_accepted_by_default(tmp_path):
    base = tmp_path / "app"
    base.mkdir()
    zip_url, sum_url = make_release(tmp_path / "rel")        # file:// URLs
    with pytest.raises(RuntimeError, match="Refused download address"):
        updater.prepare_update(base, zip_url, sum_url)
    assert not (base / "_update_pending").exists()
    with pytest.raises(RuntimeError):
        updater.fetch_latest_release("http://example.invalid/x")


def test_user_data_is_never_in_the_release_items():
    assert "data" not in app_info.PROGRAM_ITEMS


def test_write_success_flag(tmp_path):
    updater.write_success_flag(tmp_path)
    assert (tmp_path / updater.UPDATE_SUCCESS_FLAG_NAME).is_file()
    updater.write_success_flag(tmp_path / "does-not-exist")   # must not raise


def test_helper_script_is_bundled_next_to_the_sources():
    assert (paths.resource_dir() / "updater_helper.ps1").is_file()
