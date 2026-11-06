# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)
# The icons at import: stat_parser reads the item icons the stored equipment needs (wow_icons.extract, replaced here by
# a function that records the call and writes files) and the pages of the characters with new icons are written again,
# without a new scan. No test needs a game, the DLL or the network.

import hashlib
import os
import shutil
from pathlib import Path

import pytest

from app import actions
from app import stat_parser
from core import paths
from game import wow_icons
from game.wow_icons import IconRun
from pages import outputs
from pages import plotly_asset
from pages import stat_history
from store import db_schema
from store import importer

SRC = Path(__file__).resolve().parent.parent / "src"
FAKE = b"/*! fake plotly */\r\nwindow.Plotly = {};\r\n"
OLD = 1_000_000_000_000_000_000          # an mtime in ns, long ago
PNG = stat_history.PNG_SIGNATURE + b"a fake icon"
A, B = "Alice-Realm", "Bob-Realm"


@pytest.fixture
def res(tmp_path, monkeypatch):
    """A resource folder with both real templates and a fake plotly.js, pinned to that fake."""
    folder = tmp_path / "res"
    folder.mkdir()
    for name in ("template.html", stat_history.PAGE_TEMPLATE):
        shutil.copy2(SRC / name, folder / name)
    (folder / plotly_asset.FILENAME).write_bytes(FAKE)
    monkeypatch.setattr(paths, "resource_dir", lambda: folder)
    monkeypatch.setattr(plotly_asset, "SHA256", hashlib.sha256(FAKE).hexdigest())
    return folder


def lua(*scans):
    """A StatTracker.lua with one scan per (key, scanned_at, icon id); each character wears one item."""
    chars = "".join(
        f'["{key}"] = {{ ["scannedAt"] = "{at}", ["scannedEpoch"] = 1, ["class"] = "Mage", ["level"] = 80, '
        f'["faction"] = "Alliance", ["stats"] = {{ [1] = "1" }}, ["playedTotal"] = 7200, ["playedLevel"] = 600, '
        f'["gear"] = {{ [1] = {{ ["itemID"] = {icon}, ["name"] = "Helm", ["quality"] = 4, ["ilvl"] = 600, '
        f'["iconID"] = {icon} }} }} }},\n' for key, at, icon in scans)
    return ('StatTrackerDB = {\n["version"] = 4,\n["meta"] = { [1] = { ["name"] = "Total deaths", ["cat"] = "Combat" } },\n'
            f'["chars"] = {{\n{chars}}},\n}}\n')


class Extract:
    """Stands in for wow_icons.extract: records what it was asked, stores the icons it "reads" and reports them."""

    def __init__(self, folder, readable=(), unreadable=(), error=None):
        self.folder, self.readable, self.unreadable, self.error = folder, set(readable), list(unreadable), error
        self.calls = []

    def __call__(self, wanted, icons_dir, game_dir, product, **_):
        self.calls.append((sorted(wanted), Path(icons_dir), Path(game_dir), product))
        have = wow_icons.present(icons_dir)
        written = sorted(i for i in set(wanted) & self.readable if i not in have)
        for icon_id in written:
            Path(icons_dir).mkdir(parents=True, exist_ok=True)
            wow_icons.icon_path(icons_dir, icon_id).write_bytes(PNG)
        return IconRun(written=written, unreadable=self.unreadable, error=self.error)


class Imports:
    """One instance folder: __call__ imports a file with the given scans and the options named."""

    def __init__(self, tmp_path):
        self.dir, self.history, self.icons = tmp_path, tmp_path / "history", tmp_path / "icons"
        self.game, self.html = tmp_path / "World of Warcraft", tmp_path / "stats.html"

    def __call__(self, *scans, icons=True, game=True):
        sv = self.dir / "StatTracker.lua"
        sv.write_text(lua(*scans), encoding="utf-8")
        args = ["--input", str(sv), "--db", str(self.dir / "x.db"), "--output", str(self.html), "--history-dir", str(self.history)]
        if icons:
            args += ["--icons-dir", str(self.icons)]
        if game:
            args += ["--game-dir", str(self.game), "--product", "wow"]
        stat_parser.main(args)

    def page(self, key):
        return self.history / stat_history.page_name(key)

    def age_pages(self):
        for p in self.history.glob("history-*.html"):
            os.utime(p, ns=(OLD, OLD))

    def untouched(self, key):
        return self.page(key).stat().st_mtime_ns == OLD

    def embeds_icons(self, key):
        return b'"icons"' in self.page(key).read_bytes()


@pytest.fixture
def imports(tmp_path, res):
    return Imports(tmp_path)


def database(tmp_path, *scans):
    conn = db_schema.init_db(tmp_path / "hook.db")
    for key, at, icon in scans:
        c = {"scannedAt": at, "scannedEpoch": 1, "class": "Mage", "level": 80, "faction": "Alliance", "stats": {1: "1"},
             "gear": {1: {"itemID": icon, "name": "Helm", "quality": 4, "ilvl": 600, "iconID": icon}}}
        importer.import_data(conn, {"meta": {1: {"name": "Total deaths", "cat": "Combat"}}, "chars": {key: c}})
    return conn


# ------------------------------------------------------------------ update_icons
def test_the_icon_ids_of_the_stored_equipment_are_asked_for_and_the_characters_with_new_icons_named(tmp_path):
    conn = database(tmp_path, (A, "2026-10-01 10:00:00", 1001), (A, "2026-10-02 10:00:00", 1002), (B, "2026-10-01 10:00:00", 2002))
    extract = Extract(tmp_path / "icons", readable=[2002], unreadable=[7, 8])
    chars, lines = outputs.update_icons(conn, tmp_path / "icons", tmp_path / "wow", "wow", extract)
    assert extract.calls == [([1001, 1002, 2002], tmp_path / "icons", tmp_path / "wow", "wow")]
    assert chars == {B}
    assert any(l.startswith("Icons:") and "1 read" in l for l in lines)
    assert any(l.startswith("Note:") and "2 item icons" in l for l in lines)
    assert not [l for l in lines if "WARNING" in l]


def test_two_characters_with_the_same_item_both_get_their_page_written(tmp_path):
    conn = database(tmp_path, (A, "2026-10-01 10:00:00", 1001), (B, "2026-10-01 10:00:00", 1001))
    chars, _lines = outputs.update_icons(conn, tmp_path / "icons", tmp_path / "wow", "wow", Extract(tmp_path / "icons", readable=[1001]))
    assert chars == {A, B}


def test_nothing_new_means_no_characters_and_no_line(tmp_path):
    conn = database(tmp_path, (A, "2026-10-01 10:00:00", 1001))
    assert outputs.update_icons(conn, tmp_path / "icons", tmp_path / "wow", "wow", Extract(tmp_path / "icons")) == (set(), [])


def test_a_run_that_stops_early_is_a_warning_and_what_it_stored_still_counts(tmp_path):
    conn = database(tmp_path, (A, "2026-10-01 10:00:00", 1001))
    extract = Extract(tmp_path / "icons", readable=[1001], error="the game files cannot be opened")
    chars, lines = outputs.update_icons(conn, tmp_path / "icons", tmp_path / "wow", "wow", extract)
    assert chars == {A}
    assert lines[-1] == "WARNING: item icons not read: the game files cannot be opened"


def test_a_bug_in_the_reading_is_a_warning_line_and_never_an_exception(tmp_path):
    conn = database(tmp_path, (A, "2026-10-01 10:00:00", 1001))

    def broken(*_a, **_k):
        raise RuntimeError("boom")
    chars, lines = outputs.update_icons(conn, tmp_path / "icons", tmp_path / "wow", "wow", broken)
    assert chars == set() and lines == ["WARNING: item icons not read: RuntimeError: boom"]


def test_the_german_lines_are_german(tmp_path):
    from core import i18n
    i18n.set_language("de")
    conn = database(tmp_path, (A, "2026-10-01 10:00:00", 1001))
    _chars, lines = outputs.update_icons(conn, tmp_path / "icons", tmp_path / "wow", "wow",
                                             Extract(tmp_path / "icons", readable=[1001], unreadable=[5]))
    assert lines[0].startswith("Icons:") and "gelesen" in lines[0] and lines[1].startswith("Hinweis:")


# ------------------------------------------------------------------ the import
def test_new_icons_make_the_page_of_a_character_without_a_new_scan_and_only_those(imports, monkeypatch, capsys):
    imports((A, "2026-10-01 10:00:00", 1001), (B, "2026-10-01 10:00:00", 1001), icons=False, game=False)
    imports((A, "2026-10-02 10:00:00", 1001), icons=False, game=False)            # A has two scans: a page, without icons
    imports((B, "2026-10-02 10:00:00", 1001), icons=False, game=False)
    assert not imports.embeds_icons(A) and not imports.embeds_icons(B)
    imports.age_pages()

    extract = Extract(imports.icons, readable=[1001])
    monkeypatch.setattr(wow_icons, "extract", extract)
    capsys.readouterr()
    imports((A, "2026-10-02 10:00:00", 1001))                         # nothing new in the file, but icons are
    assert imports.embeds_icons(A) and imports.embeds_icons(B)        # both wear the item: both pages are written again
    assert "Icons:    1 read" in capsys.readouterr().out
    assert extract.calls == [([1001], imports.icons, imports.game, "wow")]

    imports.age_pages()
    imports((A, "2026-10-02 10:00:00", 1001))                         # the icon is in the folder: nothing to write
    assert imports.untouched(A) and imports.untouched(B)


def test_a_character_whose_icons_are_not_new_keeps_its_page(imports, monkeypatch):
    imports((A, "2026-10-01 10:00:00", 1001), (B, "2026-10-01 10:00:00", 2002), icons=False, game=False)
    imports((A, "2026-10-02 10:00:00", 1001), (B, "2026-10-02 10:00:00", 2002), icons=False, game=False)
    imports.age_pages()
    monkeypatch.setattr(wow_icons, "extract", Extract(imports.icons, readable=[2002]))
    imports((A, "2026-10-02 10:00:00", 1001), (B, "2026-10-02 10:00:00", 2002))
    assert imports.untouched(A) and not imports.untouched(B)


@pytest.mark.parametrize("missing", ["game", "icons"])
def test_the_game_files_are_read_only_with_all_the_options_given(imports, monkeypatch, missing):
    imports((A, "2026-10-01 10:00:00", 1001), icons=False, game=False)
    extract = Extract(imports.icons, readable=[1001])
    monkeypatch.setattr(wow_icons, "extract", extract)
    imports((A, "2026-10-02 10:00:00", 1001), icons=missing != "icons", game=missing != "game")
    assert extract.calls == []


def test_without_a_pages_folder_nothing_is_read(imports, monkeypatch, tmp_path):
    extract = Extract(imports.icons, readable=[1001])
    monkeypatch.setattr(wow_icons, "extract", extract)
    sv = tmp_path / "StatTracker.lua"
    sv.write_text(lua((A, "2026-10-01 10:00:00", 1001)), encoding="utf-8")
    stat_parser.main(["--input", str(sv), "--db", str(tmp_path / "y.db"), "--output", str(tmp_path / "s.html"),
                      "--icons-dir", str(imports.icons), "--game-dir", str(imports.game), "--product", "wow"])
    assert extract.calls == [] and not imports.icons.exists()


def test_a_failing_reader_costs_neither_the_import_nor_the_page(imports, monkeypatch, capsys):
    imports((A, "2026-10-01 10:00:00", 1001), icons=False, game=False)

    def broken(*_a, **_k):
        raise RuntimeError("no DLL today")
    monkeypatch.setattr(wow_icons, "extract", broken)
    capsys.readouterr()
    imports((A, "2026-10-02 10:00:00", 1001))
    out = capsys.readouterr().out
    assert "WARNING: item icons not read: RuntimeError: no DLL today" in out
    assert imports.page(A).is_file() and "Scans:" in out


# ------------------------------------------------------------------ the window
def test_the_window_passes_the_icon_options_on(monkeypatch):
    seen = []
    monkeypatch.setattr(actions.stat_parser, "main", lambda args: seen.append(args))
    base = ["--input", "a.lua", "--db", "x.db", "--output", "s.html"]
    actions.run_parser("a.lua", "x.db", "s.html", "hist", "icons", "wow folder", "wow")
    assert seen[-1] == base + ["--history-dir", "hist", "--icons-dir", "icons", "--game-dir", "wow folder", "--product", "wow"]
    actions.run_parser("a.lua", "x.db", "s.html", "hist", "icons")
    assert seen[-1] == base + ["--history-dir", "hist", "--icons-dir", "icons"]
    actions.run_parser("a.lua", "x.db", "s.html", "hist", "icons", "wow folder", None)          # product unknown: nothing to read
    assert "--game-dir" not in seen[-1]
    actions.run_parser("a.lua", "x.db", "s.html", None, "icons", "wow folder", "wow")           # no pages: icons make no sense
    assert seen[-1] == base
