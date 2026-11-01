#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)
# plotly_asset.py
# StatTracker - the pinned Plotly bundle for the history pages: version, hash,
# location and a verified read. Leaf-Node: stdlib and paths only.
#
# plotly.min.js is not part of the repository. compiler/plotly_fetch.py downloads it
# from the CDN into src/ (build and CI only, never at runtime) and the build bundles it
# next to template.html. At runtime this module only reads the file and refuses to hand
# it out when it is missing or does not match SHA256 - there is no download and no
# fallback. Update VERSION, CDN_URL and SHA256 together, never one of them alone.
#
# plotly.js is MIT licensed; the license header stays in the file.

import hashlib

import paths

VERSION = "2.27.0"
CDN_URL = "https://cdn.plot.ly/plotly-2.27.0.min.js"
SHA256 = "7f4930eba8f8541dbec28dca5bd5f787f8eef1cde0369ac9657b70bed230b3e0"
FILENAME = "plotly.min.js"


class PlotlyAssetError(Exception):
    """The bundle is missing, unreadable, or does not match the pinned hash."""


def path():
    """Where the bundle lives: next to template.html (src/ from source, the bundle folder when frozen)."""
    return paths.resource_dir() / FILENAME


def sha256_of(data):
    return hashlib.sha256(data).hexdigest()


def read_verified():
    """The bundle as bytes, checked against SHA256. Raises PlotlyAssetError instead of returning
    anything unverified."""
    p = path()
    try:
        data = p.read_bytes()
    except OSError as exc:
        raise PlotlyAssetError(
            f"Plotly bundle not found at {p} ({exc}). Run: python compiler/plotly_fetch.py") from exc
    if sha256_of(data) != SHA256:
        raise PlotlyAssetError(
            f"Plotly bundle at {p} does not match the pinned SHA-256 of plotly.js {VERSION}. "
            f"Delete it and run: python compiler/plotly_fetch.py")
    return data


def script_tag():
    """The verified bundle as an inline <script> element."""
    return "<script>" + read_verified().decode("utf-8") + "</script>"
