# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)
# The history page: payload, the file stat_history.write_page makes, and what the template may not contain.
# Runs with a fake plotly.js (the pin is bent to its hash); one test uses the real bundle if it was fetched.

import hashlib
import json
import re
import shutil
from pathlib import Path

import pytest

import i18n
import paths
import plotly_asset
import stat_history
import stat_parser
from plotly_asset import PlotlyAssetError
from stat_history import HistoryPageError

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
FAKE = b"/*! fake plotly */\r\nwindow.Plotly = {};\r\n"
KEY = "Alice-Realm"
META = {1: {"name": "Total deaths", "cat": "Combat"},
        2: {"name": "</script><b>Odd name", "cat": "Combat"}}


@pytest.fixture
def site(tmp_path, monkeypatch):
    """A resource folder with the real history.html and a fake plotly.js, pinned to that fake."""
    res = tmp_path / "res"
    res.mkdir()
    shutil.copy2(SRC / stat_history.PAGE_TEMPLATE, res / stat_history.PAGE_TEMPLATE)
    (res / plotly_asset.FILENAME).write_bytes(FAKE)
    monkeypatch.setattr(paths, "resource_dir", lambda: res)
    monkeypatch.setattr(plotly_asset, "SHA256", hashlib.sha256(FAKE).hexdigest())
    return res


@pytest.fixture
def payload(tmp_path):
    conn = stat_parser.init_db(tmp_path / "x.db")
    for at, deaths in (("2026-10-01 10:00:00", "10"), ("2026-10-02 10:00:00", "20")):
        c = {"scannedAt": at, "scannedEpoch": 1, "class": "Mage", "level": 80, "faction": "Alliance",
             "stats": {1: deaths, 2: "5"}, "playedTotal": 3600, "playedLevel": 600}
        stat_parser.import_data(conn, {"meta": META, "chars": {KEY: c}})
    conn.close()
    ro = stat_history.open_readonly(tmp_path / "x.db")
    try:
        return stat_history.build_page_payload(ro, KEY)
    finally:
        ro.close()


def embedded(page_bytes):
    """The JSON the page carries: the text after 'const DATA = ' up to the semicolon."""
    line = next(l for l in page_bytes.decode("utf-8").splitlines() if l.startswith("const DATA = "))
    return line, json.loads(line[len("const DATA = "):].rstrip(";"))


@pytest.mark.parametrize("lang", ["de", "en"])
def test_payload_carries_the_history_the_texts_and_the_plotly_version(payload, lang, tmp_path):
    i18n.set_language(lang)
    ro = stat_history.open_readonly(tmp_path / "x.db")
    try:
        p = stat_history.build_page_payload(ro, KEY)
    finally:
        ro.close()
    assert p["lang"] == lang and p["plotly"] == plotly_asset.VERSION
    assert p["char"]["key"] == KEY and p["scans"] == ["2026-10-01 10:00:00", "2026-10-02 10:00:00"]
    assert p["ui"]["hist_title"] == i18n.raw("html_hist_title", lang)
    assert p["app"]["version"]


def test_an_unknown_character_has_no_payload(tmp_path, payload):
    ro = stat_history.open_readonly(tmp_path / "x.db")
    try:
        assert stat_history.build_page_payload(ro, "Nobody-Realm") is None
    finally:
        ro.close()


def test_the_page_carries_the_data_and_the_plotly_bundle_once(site, payload, tmp_path):
    out = tmp_path / "out" / "verlauf" / "alice.html"
    stat_history.write_page(payload, out)
    raw = out.read_bytes()
    assert raw.count(FAKE) == 1                                     # unchanged, line endings included
    assert raw.index(FAKE) < raw.index(b"const DATA = ")          # the library is there before the script that uses it
    assert stat_history.DATA_MARKER.encode() not in raw and stat_history.PLOTLY_MARKER.encode() not in raw
    assert embedded(raw)[1] == payload
    assert not list(out.parent.glob("*.part"))


def test_nothing_in_the_data_can_end_the_script(site, payload, tmp_path):
    out = tmp_path / "alice.html"
    stat_history.write_page(payload, out)
    line, data = embedded(out.read_bytes())
    assert "<" not in line
    assert any(s["name"] == "</script><b>Odd name" for s in data["stats"])     # and comes back intact


def test_the_template_is_refused_when_a_marker_is_missing_or_twice(site, payload, tmp_path):
    tpl = site / stat_history.PAGE_TEMPLATE
    text = tpl.read_text(encoding="utf-8")
    for broken in (text.replace(stat_history.DATA_MARKER, "null"),
                   text.replace(stat_history.PLOTLY_MARKER, ""),
                   text + stat_history.DATA_MARKER):
        tpl.write_text(broken, encoding="utf-8")
        with pytest.raises(HistoryPageError, match="exactly once"):
            stat_history.write_page(payload, tmp_path / "alice.html")
    assert not (tmp_path / "alice.html").exists()


def test_a_missing_template_is_reported(site, payload, tmp_path):
    (site / stat_history.PAGE_TEMPLATE).unlink()
    with pytest.raises(HistoryPageError, match="not readable"):
        stat_history.write_page(payload, tmp_path / "alice.html")


def test_a_missing_or_wrong_plotly_writes_nothing_and_keeps_the_old_page(site, payload, tmp_path):
    out = tmp_path / "alice.html"
    out.write_text("old page", encoding="utf-8")
    (site / plotly_asset.FILENAME).write_bytes(FAKE + b"tampered")
    with pytest.raises(PlotlyAssetError):
        stat_history.write_page(payload, out)
    (site / plotly_asset.FILENAME).unlink()
    with pytest.raises(PlotlyAssetError):
        stat_history.write_page(payload, out)
    assert out.read_text(encoding="utf-8") == "old page"
    assert not list(tmp_path.glob("*.part"))


def test_a_target_that_cannot_be_written_is_reported(site, payload, tmp_path):
    blocker = tmp_path / "blocker"
    blocker.write_text("a file, not a folder", encoding="utf-8")
    with pytest.raises(HistoryPageError, match="not writable"):
        stat_history.write_page(payload, blocker / "alice.html")


def test_the_template_asks_for_nothing_from_the_network():
    text = (SRC / stat_history.PAGE_TEMPLATE).read_text(encoding="utf-8")
    assert "http://" not in text and "https://" not in text
    for call in ("fetch(", "XMLHttpRequest", "import(", "WebSocket", "sendBeacon", "<link ", "<iframe", "<img "):
        assert call not in text, call
    assert not re.search(r"<script[^>]*\ssrc=", text)


def test_the_time_axis_is_numeric_so_no_month_is_named_in_the_wrong_language():
    text = (SRC / stat_history.PAGE_TEMPLATE).read_text(encoding="utf-8")
    assert "tickformatstops" in text and "hoverformat" in text
    assert "%b" not in text and "%B" not in text and "%a" not in text and "%A" not in text


def test_the_real_bundle_goes_into_a_real_page(payload, tmp_path, monkeypatch):
    if not (SRC / plotly_asset.FILENAME).is_file():
        pytest.skip("src/plotly.min.js not fetched (python compiler/plotly_fetch.py)")
    out = tmp_path / "alice.html"
    stat_history.write_page(payload, out)
    raw = out.read_bytes()
    assert len(raw) > 3_000_000
    assert raw.startswith(b"<!DOCTYPE html>") and b"plotly.js v" + plotly_asset.VERSION.encode() in raw
    assert embedded(raw)[1] == payload
