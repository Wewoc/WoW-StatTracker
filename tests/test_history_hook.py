# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)
# History pages made by the import: which characters get a page, when pages are left alone, what a failure
# does to the import, and the links on the stats page. Runs with a fake plotly.js.

import hashlib
import json
import os
import re
import shutil
from pathlib import Path

import pytest

import app_info
import paths
import plotly_asset
import stat_history
import stat_parser
import wow_install
from stat_history import HistoryPageError

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
FAKE = b"/*! fake plotly */\r\nwindow.Plotly = {};\r\n"
OLD = 1_000_000_000_000_000_000          # an mtime in ns, long ago


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
    """A StatTracker.lua holding one scan per (key, scanned_at, deaths) given (one scan per character per file)."""
    chars = "".join(
        f'["{key}"] = {{ ["scannedAt"] = "{at}", ["scannedEpoch"] = 1, ["class"] = "Mage", ["level"] = 80, '
        f'["faction"] = "Alliance", ["stats"] = {{ [1] = "{deaths}" }}, ["playedTotal"] = 7200, ["playedLevel"] = 600 }},\n'
        for key, at, deaths in scans)
    return ('StatTrackerDB = {\n["version"] = 3,\n["meta"] = { [1] = { ["name"] = "Total deaths", ["cat"] = "Combat" } },\n'
            f'["chars"] = {{\n{chars}}},\n}}\n')


class Run:
    """One instance folder: run() imports a file with the given scans, with or without a pages folder."""

    def __init__(self, tmp_path):
        self.dir = tmp_path
        self.history = tmp_path / "history"
        self.html = tmp_path / "stats.html"

    def __call__(self, *scans, history=True):
        sv = self.dir / "StatTracker.lua"
        sv.write_text(lua(*scans), encoding="utf-8")
        args = ["--input", str(sv), "--db", str(self.dir / "x.db"), "--output", str(self.html)]
        if history:
            args += ["--history-dir", str(self.history)]
        stat_parser.main(args)

    def pages(self):
        return sorted(p.name for p in self.history.glob("history-*.html")) if self.history.is_dir() else []

    def page(self, key):
        return self.history / stat_history.page_name(key)

    def payload(self):
        line = next(l for l in self.html.read_text(encoding="utf-8").splitlines() if l.startswith("const DATA = "))
        return json.loads(line[len("const DATA = "):].rstrip(";"))

    def age_pages(self):
        for p in self.history.glob("history-*.html"):
            os.utime(p, ns=(OLD, OLD))

    def untouched(self, key):
        return self.page(key).stat().st_mtime_ns == OLD


@pytest.fixture
def run(tmp_path, res):
    return Run(tmp_path)


A, B = "Alice-Realm", "Bob-Realm"


def test_a_character_gets_a_page_from_its_second_scan_on(run):
    run((A, "2026-10-01 10:00:00", "10"), (B, "2026-10-01 11:00:00", "1"))
    assert run.pages() == [] and not run.history.exists() and "history" not in run.payload()
    run((A, "2026-10-02 10:00:00", "20"))
    assert run.pages() == [stat_history.page_name(A)]               # Bob has one scan: no page
    h = run.payload()["history"]
    assert h["dir"] == "history" and list(h["links"]) == [A] and h["links"][A]["scans"] == 2
    assert h["links"][A]["href"] == "history/" + stat_history.page_name(A)


def test_the_page_links_back_to_the_stats_page(run):
    run((A, "2026-10-01 10:00:00", "10"))
    run((A, "2026-10-02 10:00:00", "20"))
    page = run.page(A).read_text(encoding="utf-8")
    data = json.loads(next(l for l in page.splitlines() if l.startswith("const DATA = "))[len("const DATA = "):].rstrip(";"))
    assert data["back"] == "../stats.html"


def test_an_import_with_nothing_new_leaves_every_file_alone(run, capsys):
    run((A, "2026-10-01 10:00:00", "10"))
    run((A, "2026-10-02 10:00:00", "20"))
    run.age_pages()
    capsys.readouterr()
    run((A, "2026-10-02 10:00:00", "20"))                            # the same scan again
    assert run.untouched(A)
    assert "History:" not in capsys.readouterr().out


def test_only_the_characters_with_a_new_scan_get_a_new_page(run, capsys):
    for at, d in (("2026-10-01 10:00:00", "1"), ("2026-10-02 10:00:00", "2")):
        run((A, at, d))
        run((B, at, d))
    assert len(run.pages()) == 2
    run.age_pages()
    capsys.readouterr()
    run((A, "2026-10-03 10:00:00", "3"))
    assert run.page(B).stat().st_mtime_ns == OLD and run.page(A).stat().st_mtime_ns != OLD
    assert "History:  1 written" in capsys.readouterr().out
    assert run.payload()["history"]["links"][A]["scans"] == 3 and B in run.payload()["history"]["links"]


def test_a_missing_page_is_made_again(run):
    run((A, "2026-10-01 10:00:00", "1"))
    run((A, "2026-10-02 10:00:00", "2"))
    run.page(A).unlink()
    run((A, "2026-10-02 10:00:00", "2"))
    assert run.page(A).is_file()


def test_pages_of_another_program_version_are_all_written_again(run):
    for at, d in (("2026-10-01 10:00:00", "1"), ("2026-10-02 10:00:00", "2")):
        run((A, at, d))
        run((B, at, d))
    marker = run.history / stat_history.GENERATOR_FILE
    assert marker.read_text(encoding="utf-8") == app_info.APP_VERSION
    marker.write_text("0.0.1", encoding="utf-8")
    run.age_pages()
    run((A, "2026-10-02 10:00:00", "2"))                              # nothing new
    assert not run.untouched(A) and not run.untouched(B)
    assert marker.read_text(encoding="utf-8") == app_info.APP_VERSION


def test_without_a_pages_folder_nothing_is_made(run):
    run((A, "2026-10-01 10:00:00", "1"), history=False)
    run((A, "2026-10-02 10:00:00", "2"), history=False)
    assert not run.history.exists() and "history" not in run.payload()


def test_a_missing_plotly_is_a_warning_and_the_import_still_works(run, res, capsys):
    run((A, "2026-10-01 10:00:00", "1"))
    (res / plotly_asset.FILENAME).unlink()
    run((A, "2026-10-02 10:00:00", "2"))
    out = capsys.readouterr().out
    assert "WARNING: history pages not written" in out and "plotly_fetch.py" in out
    assert run.pages() == [] and "history" not in run.payload()
    assert not (run.history / stat_history.GENERATOR_FILE).exists()
    import sqlite3
    conn = sqlite3.connect(run.dir / "x.db")
    try:
        assert conn.execute("SELECT COUNT(*) FROM scans").fetchone()[0] == 2
    finally:
        conn.close()
    assert run.html.is_file()


def test_an_old_page_stays_linked_when_the_new_one_cannot_be_made(run, res, capsys):
    run((A, "2026-10-01 10:00:00", "1"))
    run((A, "2026-10-02 10:00:00", "2"))
    before = run.page(A).read_bytes()
    (res / plotly_asset.FILENAME).write_bytes(FAKE + b"tampered")
    run((A, "2026-10-03 10:00:00", "3"))
    assert "WARNING" in capsys.readouterr().out
    assert run.page(A).read_bytes() == before
    assert A in run.payload()["history"]["links"]


def test_one_character_failing_does_not_stop_the_others(run, monkeypatch, capsys):
    for at, d in (("2026-10-01 10:00:00", "1"), ("2026-10-02 10:00:00", "2")):
        run((A, at, d))
    real = stat_history.write_page

    def flaky(payload, out_path):
        if payload["char"]["key"] == B:
            raise HistoryPageError("disk full")
        return real(payload, out_path)

    monkeypatch.setattr(stat_history, "write_page", flaky)
    for at, d in (("2026-10-01 10:00:00", "1"), ("2026-10-02 10:00:00", "2")):
        run((B, at, d))
    out = capsys.readouterr().out
    assert f"WARNING: history page of {B} not written: disk full" in out
    assert run.page(A).is_file() and not run.page(B).exists()
    assert list(run.payload()["history"]["links"]) == [A]


def test_an_unexpected_error_in_the_pages_does_not_cost_the_import(run, monkeypatch, capsys):
    run((A, "2026-10-01 10:00:00", "1"))
    monkeypatch.setattr(stat_history, "write_pages", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("bug")))
    run((A, "2026-10-02 10:00:00", "2"))
    assert "WARNING: history pages not written: RuntimeError: bug" in capsys.readouterr().out
    assert run.html.is_file() and "history" not in run.payload()


def test_on_another_drive_the_pages_are_made_but_not_linked(run, monkeypatch):
    run((A, "2026-10-01 10:00:00", "1"))

    def other_drive(*_a, **_k):
        raise ValueError("path is on mount 'D:', start on mount 'C:'")

    monkeypatch.setattr(os.path, "relpath", other_drive)
    run((A, "2026-10-02 10:00:00", "2"))
    assert run.page(A).is_file() and "history" not in run.payload()


def test_page_names_are_safe_stable_and_never_meet():
    keys = ["Alice-Realm", "alice-realm", "Aeli-Kul'tiras", "Äli-Burning Blade", "A/B\\C:D-Realm", "x" * 300 + "-Realm"]
    names = [stat_history.page_name(k) for k in keys]
    assert names == [stat_history.page_name(k) for k in keys]
    assert len({n.lower() for n in names}) == len(keys)            # also on a case-blind file system
    for name in names:
        assert re.fullmatch(r"history-[^/\\:*?\"<>|']{1,%d}-[0-9a-f]{8}\.html" % stat_history.NAME_PART_MAX, name), name


def test_the_history_folder_per_game_version(instance):
    data = instance / "data"
    assert wow_install.history_dir("_retail_") == data / "history"
    assert wow_install.history_dir("_forever_") == data / "history_forever"
    assert wow_install.history_dir("_anniversary_").parent == data


def test_the_window_passes_the_folder_on(run):
    gui_app = pytest.importorskip("gui_app")
    run((A, "2026-10-01 10:00:00", "1"))
    (run.dir / "StatTracker.lua").write_text(lua((A, "2026-10-02 10:00:00", "2")), encoding="utf-8")
    ok, out = gui_app.run_parser(run.dir / "StatTracker.lua", run.dir / "x.db", run.html, run.history)
    assert ok, out
    assert run.pages() == [stat_history.page_name(A)]
    ok, out = gui_app.run_parser(run.dir / "StatTracker.lua", run.dir / "x.db", run.html)      # no folder: no pages made
    assert ok and "History:" not in out
