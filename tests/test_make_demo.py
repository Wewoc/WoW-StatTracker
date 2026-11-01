# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)
# The demo data generator behind the landing page screenshots (tools/make_demo.py):
# deterministic, shows every kind of rate result, and uses nothing but invented names.

import hashlib
import importlib.util
import json
import re
import shutil
from pathlib import Path

import pytest

import i18n
import paths
import plotly_asset
import stat_derive
import stat_history

SRC = Path(__file__).resolve().parent.parent / "src"
TOOL = Path(__file__).resolve().parent.parent / "tools" / "make_demo.py"
spec = importlib.util.spec_from_file_location("make_demo", TOOL)
make_demo = importlib.util.module_from_spec(spec)
spec.loader.exec_module(make_demo)


def _data(folder):
    text = (folder / "stats.html").read_text(encoding="utf-8")
    return json.loads(re.search(r"const DATA = (\{.*?\});\n", text, re.S).group(1).replace("<\\/", "</"))


@pytest.mark.parametrize("lang", ["en", "de"])
def test_demo_page_shows_a_rate_a_zero_and_a_reason(tmp_path, lang):
    folder = make_demo.make(tmp_path, lang)
    data = _data(folder)
    assert data["lang"] == lang
    assert [c["key"] for c in data["chars"]] == sorted(c["key"] for c in make_demo.CHARS)

    roles = {r["role"]: r for r in data["derived"]["roles"]}
    assert set(roles) == {r.key for r in stat_derive.ROLES}
    for role in roles.values():
        assert role["chars"]["Pippa-Brightwater"]["reason"] == "too_little_played"
        assert (role["total"]["used"], role["total"]["of"]) == (4, 5)
        assert all("rate" in role["chars"][c] for c in
                   ("Korvak-Ironmaw", "Mirella-Dawnspire", "Selwyn-Moonvale", "Thalrin-Sunhaven"))
    assert roles["kills_pvp"]["chars"]["Mirella-Dawnspire"]["rate"] == 0      # "--" shown as 0


@pytest.mark.parametrize("lang", ["en", "de"])
def test_demo_rates_are_close_to_the_invented_ones(tmp_path, lang):
    roles = {r["role"]: r for r in _data(make_demo.make(tmp_path, lang))["derived"]["roles"]}
    by_stat = {"kills_pve": 107, "kills_pvp": 588, "deaths": 60, "gold": 328}
    for stat in make_demo.RATE_STATS:
        role = next(k for k, v in by_stat.items() if v == stat[0])
        for char, wanted in zip(make_demo.CHARS[:4], stat[6][:4]):
            assert roles[role]["chars"][char["key"]]["rate"] == pytest.approx(wanted, rel=0.02, abs=0.02)


@pytest.mark.parametrize("lang", ["en", "de"])
def test_demo_characters_carry_class_file_and_race(tmp_path, lang):
    data = _data(make_demo.make(tmp_path, lang))
    by_key = {c["key"]: c for c in data["chars"]}
    for demo in make_demo.CHARS:
        char = by_key[demo["key"]]
        assert (char["class_file"], char["race_file"]) == (demo["cls_file"], demo["race_file"])
        assert char["race"] == demo["race"][make_demo.LANGS.index(lang)]
        assert demo["cls_file"] in data["names"]["class"] and demo["race_file"] in data["names"]["race"]
        assert demo["faction"][0] == demo["faction"][1]     # the addon stores the English faction name, whatever the client


def test_demo_is_deterministic():
    assert make_demo.build_lua("en") == make_demo.build_lua("en")
    assert make_demo.build_lua("de") != make_demo.build_lua("en")


def test_screenshot_variants_leave_the_real_page_alone(tmp_path):
    folder = make_demo.make(tmp_path, "en")
    page = (folder / "stats.html").read_text(encoding="utf-8")
    assert 'class="rates" open' not in page and "sortChar = \"Korvak" not in page
    assert 'class="rates" open' in (folder / "shot-rates.html").read_text(encoding="utf-8")
    assert 'sortChar = "Korvak-Ironmaw"' in (folder / "shot-compare.html").read_text(encoding="utf-8")
    assert '$("groups").open = true' not in page
    assert '$("groups").open = true' in (folder / "shot-groups.html").read_text(encoding="utf-8")


def test_language_is_restored(tmp_path):
    i18n.set_language("en")
    make_demo.make(tmp_path, "de")
    assert i18n.get_language() == "en"


# ------------------------------------------------------------------ --snapshots: history demo
FAKE_PLOTLY = b"/*! fake plotly */\n"
SNAPSHOTS = 4


@pytest.fixture
def fake_plotly(tmp_path, monkeypatch):
    """The real templates and a fake plotly.js, pinned to the fake: the history pages need no fetched file."""
    res = tmp_path / "res"
    res.mkdir()
    for name in ("template.html", stat_history.PAGE_TEMPLATE):
        shutil.copy2(SRC / name, res / name)
    (res / plotly_asset.FILENAME).write_bytes(FAKE_PLOTLY)
    monkeypatch.setattr(paths, "resource_dir", lambda: res)
    monkeypatch.setattr(plotly_asset, "SHA256", hashlib.sha256(FAKE_PLOTLY).hexdigest())


def _history_of(folder, key):
    conn = stat_history.open_readonly(folder / "demo.db")
    try:
        return stat_history.build_history(conn, key)
    finally:
        conn.close()


def test_one_snapshot_makes_no_history(tmp_path):
    folder = make_demo.make(tmp_path, "en")
    assert not (folder / "history").exists() and not (folder / "backups").exists()
    assert "history" not in _data(folder)


def test_the_last_snapshot_is_exactly_the_single_scan():
    for lang in ("en", "de"):
        assert make_demo.build_lua(lang, SNAPSHOTS - 1, SNAPSHOTS) == make_demo.build_lua(lang)
        assert make_demo.build_lua(lang, 0, SNAPSHOTS) != make_demo.build_lua(lang)
        assert make_demo.build_lua(lang, 1, SNAPSHOTS) == make_demo.build_lua(lang, 1, SNAPSHOTS)


def test_snapshots_make_a_history_page_per_character_and_link_them(tmp_path, fake_plotly):
    folder = make_demo.make(tmp_path / "out", "en", SNAPSHOTS)
    assert len(list((folder / "history").glob("history-*.html"))) == len(make_demo.CHARS)
    links = _data(folder)["history"]["links"]
    assert sorted(links) == sorted(c["key"] for c in make_demo.CHARS)
    assert all(item["scans"] == SNAPSHOTS for item in links.values())
    assert (folder / "history" / "shot-history.html").is_file()


def test_the_history_runs_up_in_time_and_no_counter_falls(tmp_path, fake_plotly):
    folder = make_demo.make(tmp_path / "out", "en", SNAPSHOTS)
    for demo in make_demo.CHARS:
        h = _history_of(folder, demo["key"])
        assert len(h["scans"]) == SNAPSHOTS
        assert h["scans"] == sorted(set(h["scans"])) and h["scans"][-1] == demo["at"]
        assert h["level"] == sorted(h["level"]) and h["level"][-1] == demo["level"]
        for stat in h["stats"]:
            numbers = [v for v in stat["v"] if v is not None]
            assert numbers == sorted(numbers), (demo["key"], stat["name"])


def test_the_lines_of_one_character_do_not_grow_alike(tmp_path, fake_plotly):
    folder = make_demo.make(tmp_path / "out", "en", 8)
    stats = {s["id"]: s["v"] for s in _history_of(folder, make_demo.HISTORY_CHAR)["stats"]}
    curves = [[v / series[-1] for v in series] for series in (stats[107], stats[60], stats[328], stats[9003])]
    assert all(c[-1] == 1 for c in curves)
    assert max(abs(a - b) for a, b in zip(curves[0], curves[1])) > 0.01
    assert max(abs(a - b) for a, b in zip(curves[2], curves[3])) > 0.01


def test_the_history_screenshot_page_is_a_copy_with_the_picks(tmp_path, fake_plotly):
    folder = make_demo.make(tmp_path / "out", "en", SNAPSHOTS)
    real = (folder / "history" / stat_history.page_name(make_demo.HISTORY_CHAR)).read_text(encoding="utf-8")
    shot = (folder / "history" / "shot-history.html").read_text(encoding="utf-8")
    assert make_demo.HISTORY_JS not in real and make_demo.HISTORY_JS in shot
    assert shot.replace(make_demo.HISTORY_JS + "\n", "") == real


def test_running_again_starts_from_scratch(tmp_path, fake_plotly):
    make_demo.make(tmp_path / "out", "en", SNAPSHOTS)
    folder = make_demo.make(tmp_path / "out", "en", SNAPSHOTS)
    assert len(_history_of(folder, make_demo.HISTORY_CHAR)["scans"]) == SNAPSHOTS
    assert len(list((folder / "backups").rglob("*.bak"))) == 1          # the one copy of this run, none left from the first
    assert len(list((folder / "history").glob("history-*.html"))) == len(make_demo.CHARS)


@pytest.mark.parametrize("value", ["0", str(make_demo.MAX_SNAPSHOTS + 1), "-3"])
def test_the_number_of_snapshots_is_checked(tmp_path, value):
    with pytest.raises(SystemExit):
        make_demo.main(["--out", str(tmp_path), "--lang", "en", "--snapshots", value])
    assert not (tmp_path / "en").exists()
