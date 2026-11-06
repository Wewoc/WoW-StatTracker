# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)
# The history page: payload, the file stat_history.write_page makes, and what the template may not contain.
# Runs with a fake plotly.js (the pin is bent to its hash); one test uses the real bundle if it was fetched.

import base64
import hashlib
import json
import re
import shutil
from pathlib import Path

import pytest

from core import i18n
from core import paths
from game import wow_icons
from pages import outputs
from pages import plotly_asset
from pages import stat_history
from pages.plotly_asset import PlotlyAssetError
from pages.stat_history import HistoryPageError
from store import db_schema
from store import importer

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
    conn = db_schema.init_db(tmp_path / "x.db")
    for at, deaths in (("2026-10-01 10:00:00", "10"), ("2026-10-02 10:00:00", "20")):
        c = {"scannedAt": at, "scannedEpoch": 1, "class": "Mage", "level": 80, "faction": "Alliance",
             "stats": {1: deaths, 2: "5"}, "playedTotal": 3600, "playedLevel": 600}
        importer.import_data(conn, {"meta": META, "chars": {KEY: c}})
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
    assert p["names"]["slot"]["1"] == i18n.raw("slot_1", lang)
    assert p["names"]["stat"]["ITEM_MOD_VERSATILITY"] == i18n.raw("itemstat_ITEM_MOD_VERSATILITY", lang)
    assert p["names"]["track"]["972"] == i18n.raw("track_972", lang)


def test_an_unknown_character_has_no_payload(tmp_path, payload):
    ro = stat_history.open_readonly(tmp_path / "x.db")
    try:
        assert stat_history.build_page_payload(ro, "Nobody-Realm") is None
    finally:
        ro.close()


def test_the_item_levels_reach_the_page_data_with_their_decimals(tmp_path):
    conn = db_schema.init_db(tmp_path / "ilvl.db")
    for at, equipped in (("2026-10-01 10:00:00", 598.25), ("2026-10-02 10:00:00", 601.5)):
        c = {"scannedAt": at, "scannedEpoch": 1, "class": "Mage", "level": 80, "faction": "Alliance", "stats": {1: "1"},
             "ilvlTotal": 603.75, "ilvlEquipped": equipped}
        importer.import_data(conn, {"meta": META, "chars": {KEY: c}})
    conn.close()
    ro = stat_history.open_readonly(tmp_path / "ilvl.db")
    try:
        p = stat_history.build_page_payload(ro, KEY)
    finally:
        ro.close()
    assert [g["ilvl_equipped"] for g in p["gear"]] == [598.25, 601.5]       # the database keeps them, the page too
    assert [g["ilvl_total"] for g in p["gear"]] == [603.75, 603.75]
    template = (SRC / stat_history.PAGE_TEMPLATE).read_text(encoding="utf-8")
    assert '"ilvl_equipped"' in template and '"ilvl_total"' in template        # the fields the template draws
    assert "ilvlNote" in template and "UI.hist_ilvl_note" in template          # the text that tells them apart


def test_the_character_block_shows_exactly_the_slots_that_have_a_name():
    template = (SRC / stat_history.PAGE_TEMPLATE).read_text(encoding="utf-8")
    shown = set()
    for name in ("SLOTS_LEFT", "SLOTS_RIGHT", "SLOTS_BOTTOM"):
        shown |= {int(n) for n in re.search(rf"const {name} = \[([\d, ]+)\]", template).group(1).split(",")}
    named = {int(k) for k in i18n.names("slot_", "en")}
    assert shown == named and 4 not in shown and 19 not in shown            # no shirt, no tabard
    order = re.search(r"const STAT_ORDER = \[([^\]]+)\]", template).group(1)
    assert set(re.findall(r'"(\w+)"', order)) == set(i18n.names("itemstat_", "en"))        # every named stat has its place
    icons = {int(n) for n in re.findall(r"^\s+(\d+): '<", template, re.M)}
    assert named <= icons                                                  # a symbol for every slot, drawn in the page


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


# ------------------------------------------------------------------ the item icons on the page
def gear_db(tmp_path):
    """A database whose character wore one item with the icon id 1001 in both scans."""
    conn = db_schema.init_db(tmp_path / "gear.db")
    for at in ("2026-10-01 10:00:00", "2026-10-02 10:00:00"):
        c = {"scannedAt": at, "scannedEpoch": 1, "class": "Mage", "level": 80, "faction": "Alliance", "stats": {1: "1"},
             "gear": {1: {"itemID": 1, "name": "Helm", "quality": 4, "ilvl": 600, "iconID": 1001}}}
        importer.import_data(conn, {"meta": META, "chars": {KEY: c}})
    return conn


def icons_folder(tmp_path):
    folder = tmp_path / "icons"
    folder.mkdir()
    wow_icons.icon_path(folder, 1001).write_bytes(stat_history.PNG_SIGNATURE + bytes(range(256)))
    wow_icons.icon_path(folder, 1002).write_bytes(stat_history.PNG_SIGNATURE + b"another character's item")
    return folder


def test_the_page_carries_the_icons_of_its_character_and_nothing_else(site, tmp_path):
    conn = gear_db(tmp_path)
    page = tmp_path / "out" / "a.html"
    stat_history.write_page(stat_history.build_page_payload(conn, KEY, icons_dir=icons_folder(tmp_path)), page)
    _line, data = embedded(page.read_bytes())
    assert list(data["icons"]) == ["1001"]
    uri = data["icons"]["1001"]
    assert uri == stat_history.ICON_URI_PREFIX + base64.b64encode(stat_history.PNG_SIGNATURE + bytes(range(256))).decode()
    assert page.read_bytes().count(b"</script") == 2                # the data cannot end its script (plotly's and the page's)


def test_the_icons_folder_reaches_the_pages_through_the_import_hook(site, tmp_path):
    conn = gear_db(tmp_path)
    folder = tmp_path / "hist"
    links, lines = outputs.update_history_pages(conn, folder, tmp_path / "stats.html", {KEY}, icons_folder(tmp_path))
    assert list(links["links"]) == [KEY] and not [l for l in lines if "WARN" in l.upper()]
    _line, data = embedded((folder / stat_history.page_name(KEY)).read_bytes())
    assert list(data["icons"]) == ["1001"]


def test_without_an_icons_folder_the_page_has_no_icons_field(site, tmp_path):
    conn = gear_db(tmp_path)
    folder = tmp_path / "hist"
    outputs.update_history_pages(conn, folder, tmp_path / "stats.html", {KEY})
    _line, data = embedded((folder / stat_history.page_name(KEY)).read_bytes())
    assert "icons" not in data and data["gear"]


def test_the_template_shows_an_icon_only_from_the_page_data_and_checks_its_shape():
    template = (SRC / stat_history.PAGE_TEMPLATE).read_text(encoding="utf-8")
    assert "DATA.icons" in template and "style.backgroundImage" in template and "<img " not in template
    assert "gIconsNote" in template and "UI.hist_gear_icons_note" in template          # the credit for the pictures
    pattern = re.compile(re.search(r"const ICON_URI = /(.+)/;", template).group(1).replace("\\/", "/"))
    good = stat_history.ICON_URI_PREFIX + base64.b64encode(stat_history.PNG_SIGNATURE + bytes(range(255))).decode("ascii")
    assert "+" in good and "/" in good[len(stat_history.ICON_URI_PREFIX):] and good.endswith("=")
    assert pattern.fullmatch(good)
    for bad in ("data:image/svg+xml;base64,AAAA", 'data:image/png;base64,AA")', "data:image/png;base64,AA AA",
                "data:image/png;base64,AA\n", "javascript:alert(1)", "https://example.test/a.png", "data:image/png;base64,",
                "data:image/png,AAAA", good + ")"):
        assert not pattern.fullmatch(bad), bad
