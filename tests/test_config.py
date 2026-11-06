# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

import json

from core import config


def test_default_enables_retail_only(instance):
    cfg, warning = config.load()
    assert warning is None
    assert cfg["enabled_variants"] == ["_retail_"]
    assert cfg["check_updates"] is True
    assert cfg["language"] in config.LANGUAGES


def test_save_and_load_roundtrip(instance):
    cfg, _ = config.load()
    cfg.update(language="de", wow_dir="X", enabled_variants=["_retail_", "_forever_"], check_updates=False)
    cfg["accounts"]["_retail_"] = "ACC1"
    config.save(cfg)
    assert (instance / "data" / "config.json").is_file()
    again, warning = config.load()
    assert warning is None
    assert again["language"] == "de"
    assert again["enabled_variants"] == ["_retail_", "_forever_"]
    assert again["accounts"] == {"_retail_": "ACC1"}
    assert again["check_updates"] is False


def test_corrupt_file_is_moved_aside_not_overwritten(instance):
    path = config.config_path()
    path.parent.mkdir(parents=True)
    path.write_text("{ not json", encoding="utf-8")
    cfg, warning = config.load()
    assert warning and "config.json" in warning
    assert cfg["enabled_variants"] == ["_retail_"]
    assert not path.exists()
    assert (path.parent / "config.json.broken").read_text(encoding="utf-8") == "{ not json"


def test_invalid_values_fall_back_to_defaults(instance):
    path = config.config_path()
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({
        "language": "fr", "enabled_variants": ["retail", 5, "_ok_"], "check_updates": "yes",
        "accounts": {"_retail_": 3, "_ok_": "A"}}), encoding="utf-8")
    cfg, warning = config.load()
    assert warning is None
    assert cfg["language"] in config.LANGUAGES
    assert cfg["enabled_variants"] == ["_ok_"]
    assert cfg["check_updates"] is True
    assert cfg["accounts"] == {"_ok_": "A"}


def test_all_variants_invalid_keeps_retail_default(instance):
    path = config.config_path()
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"enabled_variants": ["nope"]}), encoding="utf-8")
    cfg, _ = config.load()
    assert cfg["enabled_variants"] == ["_retail_"]


def test_reading_icons_is_on_by_default_and_only_a_real_bool_changes_it(instance):
    cfg, _ = config.load()
    assert cfg["read_icons"] is True
    cfg["read_icons"] = False
    config.save(cfg)
    assert config.load()[0]["read_icons"] is False
    config.config_path().write_text(json.dumps({"read_icons": "no"}), encoding="utf-8")
    assert config.load()[0]["read_icons"] is True
    config.config_path().write_text(json.dumps({"read_icons": 0}), encoding="utf-8")
    assert config.load()[0]["read_icons"] is True


def test_the_theme_is_the_default_until_a_known_number_is_set(instance):
    cfg, _ = config.load()
    assert cfg["active_theme"] == 1
    cfg["active_theme"] = 3
    config.save(cfg)
    assert config.load()[0]["active_theme"] == 3
    for bad in (99, 0, -1, "2", 2.0, True, None):          # unknown, wrong type, a bool is no number
        config.config_path().write_text(json.dumps({"active_theme": bad}), encoding="utf-8")
        assert config.load()[0]["active_theme"] == 1, bad


GOOD = {"name": "mine", "by": "race", "off": ["level"], "extras": [{"id": 107, "agg": "sum"}]}


def test_there_are_no_presets_until_one_is_saved_and_a_good_one_survives_the_file(instance):
    cfg, _ = config.load()
    assert cfg["group_presets"] == []
    cfg["group_presets"] = [GOOD]
    config.save(cfg)
    assert config.load()[0]["group_presets"] == [GOOD]


def test_presets_that_are_not_shaped_like_one_are_dropped_and_the_rest_stays(instance):
    junk = [GOOD, "text", None, 5, {"name": "", "by": "x", "off": [], "extras": []}, {"name": "n" * 41, "by": "x", "off": [], "extras": []},
            {"name": "no by", "off": [], "extras": []}, {"name": "off not a list", "by": "x", "off": "level", "extras": []},
            {"name": "extras not a list", "by": "x", "off": [], "extras": {}}, dict(GOOD), {"name": "n" * 40, "by": "class", "off": [], "extras": []}]
    config.config_path().parent.mkdir(parents=True, exist_ok=True)
    config.config_path().write_text(json.dumps({"group_presets": junk}), encoding="utf-8")
    names = [p["name"] for p in config.load()[0]["group_presets"]]
    assert names == ["mine", "n" * 40]                                  # the duplicate name, the empty and the long ones are gone


def test_the_parts_of_a_preset_are_cleaned(instance):
    odd = {"name": "p", "by": "class", "off": ["level", 3, None, "played"],
           "extras": [{"id": 5, "agg": "sum"}, {"id": True, "agg": "sum"}, {"id": -1, "agg": "sum"}, {"id": 5.5, "agg": "sum"}, {"id": "5", "agg": "sum"},
                      {"id": 6, "agg": 1}, {"id": 7}, "x", {"id": 8, "agg": "max", "more": 1}]}
    config.config_path().parent.mkdir(parents=True, exist_ok=True)
    config.config_path().write_text(json.dumps({"group_presets": [odd]}), encoding="utf-8")
    preset = config.load()[0]["group_presets"][0]
    assert preset["off"] == ["level", "played"]
    assert preset["extras"] == [{"id": 5, "agg": "sum"}, {"id": 8, "agg": "max"}]


def test_a_list_that_is_not_a_list_gives_no_presets_and_a_very_long_one_is_cut(instance):
    config.config_path().parent.mkdir(parents=True, exist_ok=True)
    for bad in ({"a": 1}, "text", 7, None):
        config.config_path().write_text(json.dumps({"group_presets": bad}), encoding="utf-8")
        assert config.load()[0]["group_presets"] == []
    many = [{"name": f"p{i}", "by": "class", "off": [], "extras": []} for i in range(config.PRESETS_MAX + 20)]
    config.config_path().write_text(json.dumps({"group_presets": many}), encoding="utf-8")
    assert len(config.load()[0]["group_presets"]) == config.PRESETS_MAX


TILE = {"stat": 328, "agg": "sum", "by": "class", "value": "MAGE"}


def test_there_are_no_tiles_until_some_are_set_and_good_ones_survive_the_file(instance):
    cfg, _ = config.load()
    assert cfg["top5"] == []
    cfg["top5"] = [TILE, {"stat": -1, "agg": "max", "by": "all", "value": ""}]
    config.save(cfg)
    assert config.load()[0]["top5"] == cfg["top5"]


def test_tiles_that_are_not_shaped_like_one_are_dropped_and_the_rest_stays_in_order(instance):
    junk = [TILE, "text", None, 5, {"agg": "sum", "by": "all"}, {"stat": True, "agg": "sum", "by": "all", "value": ""}, {"stat": 1.5, "agg": "sum", "by": "all"},
            {"stat": "1", "agg": "sum", "by": "all"}, {"stat": 1, "agg": 3, "by": "all"}, {"stat": 1, "agg": "sum", "by": None},
            {"stat": 1, "agg": "sum", "by": "all", "value": 4}, {"stat": 2, "agg": "avg", "by": "char", "value": "A-B", "more": 1}, {"stat": 3, "agg": "median", "by": "guild"}]
    config.config_path().parent.mkdir(parents=True, exist_ok=True)
    config.config_path().write_text(json.dumps({"top5": junk}), encoding="utf-8")
    assert config.load()[0]["top5"] == [TILE, {"stat": 2, "agg": "avg", "by": "char", "value": "A-B"},
                                       {"stat": 3, "agg": "median", "by": "guild", "value": ""}]       # only the shape is checked here, a missing value is empty


def test_at_most_five_tiles_are_kept_and_a_list_that_is_not_a_list_gives_none(instance):
    config.config_path().parent.mkdir(parents=True, exist_ok=True)
    many = [{"stat": i, "agg": "sum", "by": "all", "value": ""} for i in range(config.TOP5_MAX + 3)]
    config.config_path().write_text(json.dumps({"top5": many}), encoding="utf-8")
    assert [t["stat"] for t in config.load()[0]["top5"]] == list(range(config.TOP5_MAX)) and config.TOP5_MAX == 5
    for bad in ({"a": 1}, "text", 7, None):
        config.config_path().write_text(json.dumps({"top5": bad}), encoding="utf-8")
        assert config.load()[0]["top5"] == []
