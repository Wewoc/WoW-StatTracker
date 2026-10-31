# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)
# The demo data generator behind the landing page screenshots (tools/make_demo.py):
# deterministic, shows every kind of rate result, and uses nothing but invented names.

import importlib.util
import json
import re
from pathlib import Path

import pytest

import i18n
import stat_derive

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


def test_demo_is_deterministic():
    assert make_demo.build_lua("en") == make_demo.build_lua("en")
    assert make_demo.build_lua("de") != make_demo.build_lua("en")


def test_screenshot_variants_leave_the_real_page_alone(tmp_path):
    folder = make_demo.make(tmp_path, "en")
    page = (folder / "stats.html").read_text(encoding="utf-8")
    assert 'class="rates" open' not in page and "sortChar = \"Korvak" not in page
    assert 'class="rates" open' in (folder / "shot-rates.html").read_text(encoding="utf-8")
    assert 'sortChar = "Korvak-Ironmaw"' in (folder / "shot-compare.html").read_text(encoding="utf-8")


def test_language_is_restored(tmp_path):
    i18n.set_language("en")
    make_demo.make(tmp_path, "de")
    assert i18n.get_language() == "en"
