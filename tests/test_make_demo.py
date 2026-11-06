# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)
# The demo data generator behind the landing page screenshots (tools/make_demo.py):
# deterministic, shows every kind of rate result, and uses nothing but invented names.

import hashlib
import html
import importlib.util
import json
import re
import shutil
import struct
import zlib
from pathlib import Path

import pytest

from core import i18n
from core import paths
from game import wow_icons
from pages import plotly_asset
from pages import stat_history
from rules import stat_derive, table_rules
from store import importer
from store import lua_reader

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


@pytest.mark.parametrize("lang", ["en", "de"])
def test_demo_reputation_is_invented_and_leaves_the_last_character_without(tmp_path, lang):
    rep = _data(make_demo.make(tmp_path, lang))["rep"]
    last = make_demo.CHARS[-1]["key"]
    assert last not in rep["chars"] and len(rep["chars"]) == len(make_demo.CHARS) - 1
    index = make_demo.LANGS.index(lang)
    assert rep["defs"] == {str(fid): names[index] for fid, _kind, _aw, *names in make_demo.REP_DEMO}
    wide = [[e for e in entries if e.get("aw")] for entries in rep["chars"].values()]
    assert wide[0] and all(w == wide[0] for w in wide)                  # account-wide: the same for every character
    assert len({len(entries) for entries in rep["chars"].values()}) > 1  # the others differ per character
    kinds = {e.get("kind") for entries in rep["chars"].values() for e in entries}
    assert kinds == {None, "std", "friend", "major"} and any("par" in e for es in rep["chars"].values() for e in es)


def _demo_scans(lang, k=None, snapshots=1):
    """{char key: read_scan result} of the demo file, read the way the importer reads it."""
    db = lua_reader.LuaReader(make_demo.build_lua(lang, k, snapshots)).parse_file()["StatTrackerDB"]
    return {key: importer.read_scan(c) for key, c in db["chars"].items()}


@pytest.mark.parametrize("lang", ["en", "de"])
def test_demo_gear_is_complete_and_leaves_the_last_character_without(lang):
    scans = _demo_scans(lang)
    last = make_demo.CHARS[-1]["key"]
    assert scans[last]["gear"] == [] and scans[last]["spec_id"] is None and scans[last]["ilvl_equipped"] is None
    roles = set()
    for key, scan in scans.items():
        if key == last:
            continue
        assert scan["skipped"] == 0 and len(scan["gear"]) == len(make_demo.GEAR_SLOTS), key
        assert all(g["name"] and g["quality"] and g["ilvl"] and g["stats"] for g in scan["gear"]), key
        assert scan["spec_name"] and scan["ilvl_equipped"] and scan["ilvl_total"] >= scan["ilvl_equipped"], key
        roles.add(scan["role"])
    assert roles == {"TANK", "HEALER", "DAMAGER"}
    rings = [g for s in scans.values() for g in s["gear"] if g["slot"] in (11, 12)]
    assert rings and all(g["sockets"] == 1 and g["gem_ids"] for g in rings)         # a socket with a gem, as in the game
    assert any(g["upg_track"] and g["enchant_text"] for s in scans.values() for g in s["gear"])


def test_demo_gear_of_the_older_scans_differs_for_a_comparison():
    old, final = _demo_scans("en", 0, 10)["Mirella-Dawnspire"], _demo_scans("en")["Mirella-Dawnspire"]
    by = lambda scan: {g["slot"]: g for g in scan["gear"]}
    assert 17 not in by(old) and 17 in by(final)                                    # no off hand yet
    assert by(old)[13]["name"] != by(final)[13]["name"] and by(old)[13]["item_id"] != by(final)[13]["item_id"]
    assert by(old)[11]["enchant_text"] is None and by(final)[11]["enchant_text"]    # the ring was enchanted later
    assert by(old)[3]["ilvl"] == by(final)[3]["ilvl"] and by(old)[6]["ilvl"] < by(final)[6]["ilvl"]   # only the even slots rose
    assert old["ilvl_equipped"] < final["ilvl_equipped"]
    assert any(g["gem_ids"] == [0] for g in old["gear"])                           # one ring still without a gem
    assert _demo_scans("de")["Mirella-Dawnspire"]["spec_name"] == "Frost"
    assert _demo_scans("de")["Selwyn-Moonvale"]["spec_name"] != _demo_scans("en")["Selwyn-Moonvale"]["spec_name"]


def test_demo_is_deterministic():
    assert make_demo.build_lua("en") == make_demo.build_lua("en")
    assert make_demo.build_lua("de") != make_demo.build_lua("en")


def test_screenshot_variants_leave_the_real_page_alone(tmp_path):
    folder = make_demo.make(tmp_path, "en")
    page = (folder / "stats.html").read_text(encoding="utf-8")
    shots = {name: (folder / name).read_text(encoding="utf-8") for name in ("shot-stats.html", "shot-rates.html", "shot-compare.html", "shot-groups.html")}
    assert "  STT.start();\n" in page and all("  STT.start();\n" not in text for text in shots.values())     # only the copies are not locked
    assert 'id="rates" open' not in page and 'id="groups" open' not in page
    assert 'id="rates" open' in shots["shot-rates.html"] and 'id="groups" open' in shots["shot-groups.html"]
    assert not (folder / "_shot.html").exists()


def test_the_comparison_picture_has_one_character_off_and_the_table_sorted_by_another(tmp_path):
    folder = make_demo.make(tmp_path, "en")
    shot = (folder / "shot-compare.html").read_text(encoding="utf-8")
    assert re.search(r'id="chk_Selwyn-Moonvale" data-pick data-name="Selwyn-Moonvale">', shot)                  # not checked
    assert re.search(r'id="chk_Korvak-Ironmaw" data-pick data-name="Korvak-Ironmaw" checked>', shot)
    assert "<th class=\"num\" data-action=\"sort\" data-key=\"Selwyn-Moonvale\">" not in shot             # no column for it
    keys = [c["key"] for c in make_demo.payload_of(shot)["chars"] if c["key"] != "Selwyn-Moonvale"]
    stats = make_demo.payload_of(shot)["stats"]
    expected = [s["name"] for s in table_rules.sort_stats(table_rules.filter_stats(stats, keys, "", "", False, True), "Korvak-Ironmaw", -1)]
    shown = [html.unescape(name) for name in re.findall(r'<td class="cat">.*?</td><td>(.*?)</td>', shot.split('id="t"')[1])]
    assert shown == expected and len(shown) > 10


def test_the_groups_picture_is_by_faction_with_two_added_statistics(tmp_path):
    folder = make_demo.make(tmp_path, "en")
    shot = (folder / "shot-groups.html").read_text(encoding="utf-8")
    assert '<option value="faction" selected>' in shot
    assert "Jumps (Sum)" in shot and "Total gold acquired (Average)" in shot


def test_the_demo_has_five_top_tiles_and_the_page_shows_them_above_everything(tmp_path):
    folder = make_demo.make(tmp_path, "en")
    data = _data(folder)
    assert data["top5"] == list(make_demo.DEMO_TOP5) and len(data["top5"]) == 5
    page = (folder / "stats.html").read_text(encoding="utf-8")
    assert page.count('<div class="tile">') == 5 and page.index('id="top5"') < page.index('id="rates"')
    block = page.split('id="top5"')[1].split('<div data-slot="1">')[0]
    for name in ("Total gold acquired", "Creatures killed", "Total deaths", "Jumps"):
        assert name in block, name
    assert "Class: Paladin" in block and "Faction: Alliance" in block and "Mirella-Dawnspire" in block


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


def test_the_history_pages_carry_the_demo_gear_except_for_the_last_character(tmp_path, fake_plotly):
    folder = make_demo.make(tmp_path / "out", "en", 6)
    mirella = _history_of(folder, make_demo.HISTORY_CHAR)["gear"]
    assert len(mirella) == 6 and all(entry and len(entry["items"]) >= 15 for entry in mirella)
    assert mirella[0]["ilvl_equipped"] < mirella[-1]["ilvl_equipped"] and mirella[-1]["spec_name"] == "Frost"
    assert _history_of(folder, make_demo.CHARS[-1]["key"])["gear"] is None


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
    character = (folder / "history" / "shot-character.html").read_text(encoding="utf-8")
    assert make_demo.CHARACTER_JS in character and make_demo.HISTORY_JS not in character
    assert character.replace(make_demo.CHARACTER_JS + "\n", "") == real              # a copy, only the opening added


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


# ------------------------------------------------------------------ the placeholder icons
def _embedded_icons(folder, key):
    page = (folder / "history" / stat_history.page_name(key)).read_text(encoding="utf-8")
    line = next(l for l in page.splitlines() if l.startswith("const DATA = "))
    return json.loads(line[len("const DATA = "):].rstrip(";")).get("icons")


def test_the_demo_icons_are_invented_64_pixel_tiles_one_per_slot_and_the_same_every_time(tmp_path):
    images = {slot: make_demo.placeholder_icon(slot) for slot in make_demo.GEAR_SLOTS}
    assert len(set(images.values())) == len(make_demo.GEAR_SLOTS)            # each slot has its own color
    assert make_demo.placeholder_icon(5) == images[5]
    for png in images.values():
        assert png.startswith(stat_history.PNG_SIGNATURE)
        width, height = struct.unpack(">II", png[16:24])
        assert (width, height) == (64, 64)
        assert len(zlib.decompress(png[png.index(b"IDAT") + 4:png.index(b"IEND") - 8])) == 64 * (64 * 4 + 1)
    make_demo.make_placeholder_icons(tmp_path / "icons")
    assert wow_icons.present(tmp_path / "icons") == {make_demo.ICON_ID_BASE + s for s in make_demo.GEAR_SLOTS}


def test_every_demo_item_has_the_icon_id_of_its_slot():
    items = make_demo._gear_items(make_demo.GEAR_BY_CHAR[make_demo.CHARS[0]["key"]], 0, 0)
    assert {it["iconID"] for it in items.values()} == {make_demo.ICON_ID_BASE + s for s in items}


def test_the_demo_history_pages_show_the_placeholders_and_a_character_without_gear_none(tmp_path, fake_plotly):
    folder = make_demo.make(tmp_path / "out", "en", 3)
    expected = {str(make_demo.ICON_ID_BASE + s) for s in make_demo.GEAR_SLOTS}
    assert set(_embedded_icons(folder, make_demo.HISTORY_CHAR)) == expected
    assert _embedded_icons(folder, make_demo.CHARS[-1]["key"]) is None


def test_one_snapshot_makes_no_icons_and_a_new_run_starts_without_old_ones(tmp_path, fake_plotly):
    assert not (make_demo.make(tmp_path / "one", "en") / "icons").exists()
    folder = make_demo.make(tmp_path / "out", "en", 3)
    stale = folder / "icons" / "999.png"
    stale.write_bytes(b"left over")
    make_demo.make(tmp_path / "out", "en", 3)
    assert not stale.exists()


# --------------------------------------------------- the pictures of the game for the Character picture
GAME_PNG = stat_history.PNG_SIGNATURE + b"a stand-in for a picture of the game"


class FakeGame:
    """Stands in for wow_icons.extract: writes a file for every id it is asked for, except `skip`, or reports `error`."""

    def __init__(self, skip=(), error=None):
        self.skip, self.error, self.calls = set(skip), error, []

    def __call__(self, wanted, icons_dir, game_dir, product, **_):
        self.calls.append((set(wanted), Path(icons_dir), Path(game_dir), product))
        written = sorted(set(wanted) - self.skip)
        for icon_id in written:
            Path(icons_dir).mkdir(parents=True, exist_ok=True)
            wow_icons.icon_path(icons_dir, icon_id).write_bytes(GAME_PNG)
        return wow_icons.IconRun(written=written, error=self.error)


def test_the_game_icon_ids_are_one_real_id_for_each_demo_slot():
    ids = make_demo.GAME_ICON_IDS
    assert set(ids) == set(make_demo.GEAR_SLOTS) and len(set(ids.values())) == len(ids)
    assert all(isinstance(i, int) and i > 0 for i in ids.values())
    assert not set(ids.values()) & {make_demo.ICON_ID_BASE + s for s in make_demo.GEAR_SLOTS}      # none is a placeholder id


def test_with_the_game_option_the_demo_uses_the_real_ids_and_makes_no_placeholders(tmp_path, fake_plotly, monkeypatch):
    fake = FakeGame()
    monkeypatch.setattr(wow_icons, "extract", fake)
    folder = make_demo.make(tmp_path / "out", "en", 3, game=(tmp_path / "wow", "wow"))
    real = set(make_demo.GAME_ICON_IDS.values())
    assert set(_embedded_icons(folder, make_demo.HISTORY_CHAR)) == {str(i) for i in real}
    assert wow_icons.present(folder / "icons") == real                      # nothing but the pictures of the game
    assert fake.calls == [(real, folder / "icons", tmp_path / "wow", "wow")]
    assert _embedded_icons(folder, make_demo.CHARS[-1]["key"]) is None


def test_the_ids_of_the_demo_items_are_back_after_a_run_with_game_pictures_and_after_a_failed_one(tmp_path, fake_plotly, monkeypatch):
    base = dict(make_demo.ICON_IDS)
    monkeypatch.setattr(wow_icons, "extract", FakeGame())
    make_demo.make(tmp_path / "ok", "en", 3, game=(tmp_path / "wow", "wow"))
    assert make_demo.ICON_IDS == base
    monkeypatch.setattr(wow_icons, "extract", FakeGame(skip=[make_demo.GAME_ICON_IDS[1]]))
    with pytest.raises(SystemExit, match="missing"):
        make_demo.make(tmp_path / "bad", "en", 3, game=(tmp_path / "wow", "wow"))
    assert make_demo.ICON_IDS == base
    placeholders = make_demo.make(tmp_path / "plain", "en", 3)              # a later run without the option is as before
    assert set(_embedded_icons(placeholders, make_demo.HISTORY_CHAR)) == {str(make_demo.ICON_ID_BASE + s) for s in make_demo.GEAR_SLOTS}


def test_a_game_that_cannot_be_read_stops_the_demo_with_its_message(tmp_path, fake_plotly, monkeypatch):
    monkeypatch.setattr(wow_icons, "extract", FakeGame(error="the game files cannot be opened"))
    with pytest.raises(SystemExit, match="cannot be opened"):
        make_demo.make(tmp_path / "out", "en", 3, game=(tmp_path / "wow", "wow"))


def test_the_command_line_hands_the_game_folder_on_and_needs_history_pages_for_it(tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(make_demo, "make", lambda out, lang, snapshots=1, game=None: seen.append((lang, snapshots, game)) or tmp_path)
    make_demo.main(["--out", str(tmp_path), "--lang", "en", "--snapshots", "3", "--icons-from-game", "W", "--product", "wowf"])
    make_demo.main(["--out", str(tmp_path), "--lang", "de", "--snapshots", "3"])
    assert seen == [("en", 3, ("W", "wowf")), ("de", 3, None)]
    with pytest.raises(SystemExit) as stop:
        make_demo.main(["--out", str(tmp_path), "--icons-from-game", "W"])               # one snapshot: no history pages
    assert stop.value.code == 2
