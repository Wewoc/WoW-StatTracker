#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)
# compiler/plotly_fetch.py
# Fetches the pinned plotly.js bundle (see src/plotly_asset.py) into src/plotly.min.js.
#
# Build and CI only - the program never downloads it. The download is checked against the
# pinned SHA-256 before anything is written; on a mismatch the existing file stays as it is
# and the run fails. A file that is already there and matches is left alone.
#
#     python compiler/plotly_fetch.py

import argparse
import os
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import plotly_asset  # noqa: E402
from plotly_asset import PlotlyAssetError  # noqa: E402


def _download(url):
    request = urllib.request.Request(url, headers={"User-Agent": "StatTracker-build"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()


def _matches(dest, sha256):
    try:
        return plotly_asset.sha256_of(dest.read_bytes()) == sha256
    except OSError:
        return False


def ensure(dest=None, url=None, sha256=None, download=_download):
    """Makes sure `dest` holds the pinned bundle. Returns True if it was downloaded, False if the
    file was already there and correct. Raises PlotlyAssetError on a refused URL, a failed download
    or a hash mismatch (the existing file is then untouched)."""
    dest = Path(dest) if dest else plotly_asset.path()
    url = url or plotly_asset.CDN_URL
    sha256 = sha256 or plotly_asset.SHA256

    if _matches(dest, sha256):
        return False
    if not url.lower().startswith("https://"):
        raise PlotlyAssetError(f"Refusing a non-https URL: {url}")
    try:
        data = download(url)
    except OSError as exc:
        raise PlotlyAssetError(f"Download of {url} failed: {exc}") from exc
    actual = plotly_asset.sha256_of(data)
    if actual != sha256:
        raise PlotlyAssetError(
            f"Downloaded file does not match the pinned SHA-256 (expected {sha256}, got {actual}). "
            f"If the version is bumped on purpose, change VERSION, CDN_URL and SHA256 in "
            f"src/plotly_asset.py together.")

    part = dest.with_name(dest.name + ".part")
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        part.write_bytes(data)
        os.replace(part, dest)
    except OSError as exc:
        part.unlink(missing_ok=True)
        raise PlotlyAssetError(f"Could not write {dest}: {exc}") from exc
    return True


def main():
    argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter).parse_args()
    try:
        downloaded = ensure()
    except PlotlyAssetError as exc:
        print(f"  [plotly] {exc}")
        raise SystemExit(1)
    word = "fetched and verified" if downloaded else "present and verified"
    print(f"  [plotly] plotly.js {plotly_asset.VERSION} {word}: {plotly_asset.path()}")


if __name__ == "__main__":
    main()
