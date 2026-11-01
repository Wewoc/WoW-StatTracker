# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)
# The pinned Plotly bundle: verified read (plotly_asset) and the build-time fetch (plotly_fetch).
# Nothing here uses the network: downloads are replaced by a function.

import hashlib
import re
from pathlib import Path

import pytest

import paths
import plotly_asset
import plotly_fetch
from plotly_asset import PlotlyAssetError

ROOT = Path(__file__).resolve().parent.parent
FAKE = b"/*! fake plotly */\r\nwindow.Plotly = {};\r\n"
HTTPS = "https://example.test/plotly.js"


@pytest.fixture
def pinned(tmp_path, monkeypatch):
    """resource_dir() is a temp folder and the pin is the hash of FAKE."""
    monkeypatch.setattr(paths, "resource_dir", lambda: tmp_path)
    monkeypatch.setattr(plotly_asset, "SHA256", hashlib.sha256(FAKE).hexdigest())
    return tmp_path


def _no_download(_url):
    raise AssertionError("must not download")


def test_the_pin_is_well_formed():
    assert re.fullmatch(r"[0-9a-f]{64}", plotly_asset.SHA256)
    assert plotly_asset.CDN_URL.startswith("https://")
    assert plotly_asset.VERSION in plotly_asset.CDN_URL
    assert plotly_asset.FILENAME == "plotly.min.js"


def test_path_is_resolved_at_call_time(pinned):
    assert plotly_asset.path() == pinned / plotly_asset.FILENAME


def test_script_tag_wraps_the_verified_bundle_unchanged(pinned):
    (pinned / plotly_asset.FILENAME).write_bytes(FAKE)
    assert plotly_asset.script_tag() == "<script>" + FAKE.decode("utf-8") + "</script>"


def test_a_missing_bundle_is_refused_with_the_fix_named(pinned):
    with pytest.raises(PlotlyAssetError, match="plotly_fetch.py"):
        plotly_asset.read_verified()


def test_a_bundle_with_the_wrong_hash_is_refused(pinned):
    (pinned / plotly_asset.FILENAME).write_bytes(FAKE + b"tampered")
    with pytest.raises(PlotlyAssetError, match="SHA-256"):
        plotly_asset.script_tag()


def test_fetch_writes_the_verified_download(pinned):
    dest = pinned / plotly_asset.FILENAME
    assert plotly_fetch.ensure(url=HTTPS, download=lambda _u: FAKE) is True
    assert dest.read_bytes() == FAKE
    assert not (pinned / (plotly_asset.FILENAME + ".part")).exists()
    assert plotly_asset.read_verified() == FAKE


def test_fetch_leaves_a_correct_file_alone(pinned):
    (pinned / plotly_asset.FILENAME).write_bytes(FAKE)
    assert plotly_fetch.ensure(download=_no_download) is False


def test_fetch_replaces_a_stale_file(pinned):
    dest = pinned / plotly_asset.FILENAME
    dest.write_bytes(b"stale")
    assert plotly_fetch.ensure(url=HTTPS, download=lambda _u: FAKE) is True
    assert dest.read_bytes() == FAKE


def test_fetch_refuses_a_hash_mismatch_and_keeps_the_existing_file(pinned):
    dest = pinned / plotly_asset.FILENAME
    dest.write_bytes(b"stale")
    with pytest.raises(PlotlyAssetError, match="does not match"):
        plotly_fetch.ensure(url=HTTPS, download=lambda _u: b"something else")
    assert dest.read_bytes() == b"stale"
    assert not (pinned / (plotly_asset.FILENAME + ".part")).exists()


def test_fetch_writes_nothing_on_a_mismatch_without_an_existing_file(pinned):
    with pytest.raises(PlotlyAssetError):
        plotly_fetch.ensure(url=HTTPS, download=lambda _u: b"something else")
    assert not (pinned / plotly_asset.FILENAME).exists()


def test_fetch_refuses_a_non_https_url(pinned):
    with pytest.raises(PlotlyAssetError, match="non-https"):
        plotly_fetch.ensure(url="http://example.test/plotly.js", download=_no_download)


def test_a_failed_download_is_reported_not_raised_raw(pinned):
    def broken(_url):
        raise OSError("no route")
    with pytest.raises(PlotlyAssetError, match="no route"):
        plotly_fetch.ensure(url=HTTPS, download=broken)


def test_the_real_bundle_matches_the_pin_when_it_was_fetched():
    real = ROOT / "src" / plotly_asset.FILENAME
    if not real.is_file():
        pytest.skip("src/plotly.min.js not fetched (python compiler/plotly_fetch.py)")
    assert plotly_asset.read_verified()
