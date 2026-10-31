# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

import ast
import json
import re
from pathlib import Path

import pytest

import i18n
import stat_derive
import stat_parser
from stat_derive import MIN_PLAYED_SECONDS, PLAYED_TOTAL_ID, ROLES, Role

HOUR = 3600
SRC = Path(__file__).resolve().parent.parent / "src"


def stats_for(**chars):
    """payload["stats"] shape from {char_key: {stat_id: (text, number)}}."""
    by_id = {}
    for key, cells in chars.items():
        for sid, cell in cells.items():
            by_id.setdefault(sid, {})[key] = list(cell)
    return [{"id": sid, "v": v} for sid, v in by_id.items()]


def char(hours, **counters):
    """Cells of one scan: played time in hours plus counters by role name (number or '--')."""
    ids = {"kills_pve": 107, "kills_pvp": 588, "deaths": 60, "gold": 328}
    cells = {}
    if hours is not None:
        cells[PLAYED_TOTAL_ID] = ("x", int(hours * HOUR))
    for name, value in counters.items():
        cells[ids[name]] = ("--", None) if value == "--" else (str(value), value)
    return cells


def role(key):
    return next(r for r in ROLES if r.key == key)


def one(data, key="kills_pve", who="A"):
    result = stat_derive.compute(stats_for(**data), list(data))
    return next(r for r in result["roles"] if r["role"] == key)["chars"][who]


def test_rate_is_counter_per_played_hour():
    r = one({"A": char(100, kills_pve=1000)})
    assert r["rate"] == pytest.approx(10.0)
    assert r["hours"] == pytest.approx(100) and r["amount"] == 1000


def test_gold_is_converted_from_copper():
    r = one({"A": char(10, gold=5_000_000)}, key="gold")      # 500 gold in 10 hours
    assert r["rate"] == pytest.approx(50.0)
    assert r["amount"] == pytest.approx(500)


def test_zero_counter_is_a_real_zero():
    assert one({"A": char(10, deaths=0)}, key="deaths")["rate"] == 0


def test_minimum_played_time_is_inclusive():
    just_below = {PLAYED_TOTAL_ID: ("x", MIN_PLAYED_SECONDS - 1), 107: ("5", 5)}
    exactly = {PLAYED_TOTAL_ID: ("x", MIN_PLAYED_SECONDS), 107: ("5", 5)}
    assert one({"A": just_below}) == {"reason": "too_little_played"}
    assert one({"A": exactly})["rate"] == pytest.approx(5.0)


def test_custom_minimum_can_be_passed():
    data = {"A": char(2, kills_pve=10)}
    result = stat_derive.compute(stats_for(**data), ["A"], min_played=3 * HOUR)
    assert result["min_played_seconds"] == 3 * HOUR
    assert result["roles"][0]["chars"]["A"] == {"reason": "too_little_played"}


@pytest.mark.parametrize("played", [None, 0, -5, True, float("nan")])
def test_missing_or_invalid_played_time_gives_no_value(played):
    cells = {107: ("5", 5)}
    if played is not None:
        cells[PLAYED_TOTAL_ID] = ("x", played)
    assert one({"A": cells}) == {"reason": "no_played"}


def test_character_without_any_values_is_reported_not_dropped():
    result = stat_derive.compute(stats_for(A=char(10, kills_pve=100)), ["A", "B"])
    kills = result["roles"][0]
    assert kills["chars"]["B"] == {"reason": "no_played"}
    assert kills["total"]["of"] == 2 and kills["total"]["used"] == 1


def test_missing_or_non_numeric_stat_gives_no_value():
    assert one({"A": char(10)}) == {"reason": "no_stat"}                     # id absent
    cells = char(10)
    cells[107] = ("5164 (Humanoid)", None)                                   # text only
    assert one({"A": cells}) == {"reason": "no_stat"}


def test_negative_counter_is_rejected():
    cells = char(10)
    cells[107] = ("-3", -3)
    assert one({"A": cells}) == {"reason": "no_stat"}


def test_dash_is_zero_only_for_roles_that_allow_it():
    # '--' = counter never fired (seen in real data for PvP kills and deaths)
    assert one({"A": char(10, kills_pvp="--")}, key="kills_pvp")["rate"] == 0
    assert one({"A": char(10, deaths="--")}, key="deaths")["rate"] == 0
    assert one({"A": char(10, kills_pve="--")}, key="kills_pve") == {"reason": "no_stat"}
    assert one({"A": char(10, gold="--")}, key="gold") == {"reason": "no_stat"}


def test_dash_does_not_help_without_played_time():
    assert one({"A": char(None, deaths="--")}, key="deaths") == {"reason": "no_played"}


def test_alias_list_uses_the_first_id_with_a_number():
    aliases = (Role("x", (10, 20), "k", "count", 1, False),)

    def rate(cells):
        cells = {PLAYED_TOTAL_ID: ("x", HOUR), **cells}
        return stat_derive.compute(stats_for(A=cells), ["A"], roles=aliases)["roles"][0]["chars"]["A"]

    assert rate({10: ("4", 4), 20: ("9", 9)})["rate"] == 4        # both present: first wins
    assert rate({20: ("9", 9)})["rate"] == 9                      # first absent: second counts
    assert rate({10: ("--", None), 20: ("9", 9)})["rate"] == 9    # a number beats a dash
    assert rate({10: ("x (y)", None)}) == {"reason": "no_stat"}


def test_alias_with_dash_on_a_dash_role_is_zero():
    aliases = (Role("x", (10, 20), "k", "count", 1, True),)
    cells = {PLAYED_TOTAL_ID: ("x", HOUR), 20: ("--", None)}
    r = stat_derive.compute(stats_for(A=cells), ["A"], roles=aliases)["roles"][0]["chars"]["A"]
    assert r["rate"] == 0


def test_account_rate_is_sum_over_sum_not_mean_of_rates():
    data = {"A": char(1, kills_pve=10), "B": char(10, kills_pve=1000)}     # 10/h and 100/h
    total = stat_derive.compute(stats_for(**data), ["A", "B"])["roles"][0]["total"]
    assert total["rate"] == pytest.approx(1010 / 11)                      # a mean would give 55
    assert (total["used"], total["of"]) == (2, 2)


def test_account_rate_skips_unusable_characters_and_says_how_many():
    data = {"A": char(10, kills_pve=100), "B": char(0.5, kills_pve=999), "C": char(10)}
    total = stat_derive.compute(stats_for(**data), ["A", "B", "C"])["roles"][0]["total"]
    assert total["rate"] == pytest.approx(10.0)
    assert (total["used"], total["of"]) == (1, 3)


def test_account_rate_without_usable_characters_has_a_reason():
    total = stat_derive.compute(stats_for(A=char(0.5, kills_pve=9)), ["A"])["roles"][0]["total"]
    assert total == {"used": 0, "of": 1, "reason": "no_chars"}
    assert "rate" not in total


def test_empty_input_does_not_crash():
    result = stat_derive.compute([], [])
    assert [r["role"] for r in result["roles"]] == [r.key for r in ROLES]
    assert all(r["total"]["reason"] == "no_chars" for r in result["roles"])


def test_unknown_characters_in_stats_are_ignored():
    stats = stats_for(A=char(10, kills_pve=100), Other=char(10, kills_pve=1))
    assert stat_derive.compute(stats, ["A"])["roles"][0]["total"]["of"] == 1


def test_accepts_tuples_and_lists_as_cells():
    cells = {PLAYED_TOTAL_ID: ["x", HOUR], 107: ("7", 7)}
    assert one({"A": cells})["rate"] == 7


# ---- the role table is the single source and agrees with the rest of the project
def test_role_table_is_well_formed():
    keys = [r.key for r in ROLES]
    assert len(keys) == len(set(keys))
    ids = [sid for r in ROLES for sid in r.ids]
    assert len(ids) == len(set(ids)), "a statistic ID belongs to one role only"
    assert all(isinstance(sid, int) and sid > 0 for sid in ids)     # negative IDs are played time
    assert all(r.unit in ("count", "gold") and r.scale >= 1 for r in ROLES)


def test_played_total_id_matches_the_parser():
    sid, field, _key = stat_parser.PLAYED_STATS[0]
    assert (sid, field) == (PLAYED_TOTAL_ID, "playedTotal")


def test_every_text_key_exists_in_both_languages():
    assert set(stat_derive.REASON_KEYS) == {"no_played", "too_little_played", "no_stat", "no_chars"}
    keys = [r.label_key for r in ROLES] + list(stat_derive.REASON_KEYS.values())
    for key in keys:
        assert set(i18n._STRINGS[key]) == {"de", "en"}, key


# ---- end to end: Lua file -> database -> page
LUA = """
StatTrackerDB = {
	["version"] = 2,
	["meta"] = {
		[107] = { ["name"] = "Creatures killed", ["cat"] = "Kills" },
		[588] = { ["name"] = "Total honorable kills", ["cat"] = "Kills" },
		[60] = { ["name"] = "Total deaths", ["cat"] = "Deaths" },
		[328] = { ["name"] = "Total gold acquired", ["cat"] = "Wealth" },
	},
	["chars"] = {
		["Alice-Realm"] = {
			["scannedAt"] = "2026-10-01 10:00:00", ["scannedEpoch"] = 1,
			["class"] = "Mage", ["level"] = 80, ["faction"] = "Alliance",
			["stats"] = { [107] = "1.000", [588] = "--", [60] = "50", [328] = "500g" },
			["playedTotal"] = 360000, ["playedLevel"] = 3600,
		},
		["Bob-Realm"] = {
			["scannedAt"] = "2026-10-01 11:00:00", ["scannedEpoch"] = 2,
			["class"] = "Rogue", ["level"] = 10, ["faction"] = "Horde",
			["stats"] = { [107] = "30", [588] = "--", [60] = "--", [328] = "2g" },
		},
	},
}
"""


def _page_data(tmp_path, lang):
    i18n.set_language(lang)
    src = tmp_path / "StatTracker.lua"
    src.write_text(LUA, encoding="utf-8")
    out = tmp_path / "out.html"
    stat_parser.main(["--input", str(src), "--db", str(tmp_path / "x.db"), "--output", str(out)])
    text = out.read_text(encoding="utf-8")
    return json.loads(re.search(r"const DATA = (\{.*?\});\n", text, re.S).group(1).replace("<\\/", "</"))


def test_page_carries_rates_with_texts_in_the_page_language(tmp_path):
    derived = _page_data(tmp_path, "de")["derived"]
    roles = {r["role"]: r for r in derived["roles"]}
    assert derived["min_played_seconds"] == MIN_PLAYED_SECONDS
    assert roles["kills_pve"]["label"] == "Kreaturen getötet pro Std."
    assert "label_key" not in roles["kills_pve"]

    alice, bob = roles["kills_pve"]["chars"]["Alice-Realm"], roles["kills_pve"]["chars"]["Bob-Realm"]
    assert alice["rate"] == pytest.approx(10.0)                          # 1000 kills in 100 h
    assert bob["reason"] == "no_played" and bob["why"] == "keine Spielzeit"
    assert roles["gold"]["chars"]["Alice-Realm"]["rate"] == pytest.approx(5.0)    # 500 gold in 100 h
    assert roles["kills_pvp"]["chars"]["Alice-Realm"]["rate"] == 0       # "--" = never fired
    assert roles["deaths"]["total"]["rate"] == pytest.approx(0.5)        # 50 deaths / 100 h
    assert (roles["deaths"]["total"]["used"], roles["deaths"]["total"]["of"]) == (1, 2)


def test_page_texts_follow_the_language(tmp_path):
    roles = {r["role"]: r for r in _page_data(tmp_path, "en")["derived"]["roles"]}
    assert roles["deaths"]["label"] == "Deaths per hour"
    assert roles["deaths"]["chars"]["Bob-Realm"]["why"] == "no played time"


def test_template_renders_the_derived_block():
    tpl = (SRC / "template.html").read_text(encoding="utf-8")
    assert "DATA.derived" in tpl and 'id="rates"' in tpl


def test_module_is_a_stdlib_leaf():
    tree = ast.parse((SRC / "stat_derive.py").read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module.split(".")[0])
    project = {p.stem for p in SRC.glob("*.py")}
    assert not imported & project, imported & project
