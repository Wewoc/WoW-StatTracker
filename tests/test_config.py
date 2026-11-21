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


def test_a_file_with_a_byte_order_mark_is_read_not_moved_aside(instance):
    """Some editors (older Notepad) save UTF-8 with a BOM; the file is fine and must keep its settings."""
    path = config.config_path()
    path.parent.mkdir(parents=True)
    path.write_bytes(b"\xef\xbb\xbf" + json.dumps({"language": "de", "check_updates": False}).encode("utf-8"))
    cfg, warning = config.load()
    assert warning is None and cfg["language"] == "de" and cfg["check_updates"] is False
    assert path.exists() and not (path.parent / "config.json.broken").exists()
    config.save(cfg)
    assert not path.read_bytes().startswith(b"\xef\xbb\xbf")                         # the next save writes without a BOM
    assert config.load() == (cfg, None)


def test_a_broken_file_with_a_byte_order_mark_is_still_moved_aside(instance):
    path = config.config_path()
    path.parent.mkdir(parents=True)
    path.write_bytes(b"\xef\xbb\xbf{ not json")
    cfg, warning = config.load()
    assert warning and cfg["enabled_variants"] == ["_retail_"]
    assert not path.exists() and (path.parent / "config.json.broken").exists()


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
    assert cfg["top5"] == {}
    cfg["top5"] = {"_retail_": [TILE, {"stat": -1, "agg": "max", "by": "all", "value": ""}], "_forever_": [TILE]}
    config.save(cfg)
    assert config.load()[0]["top5"] == cfg["top5"]                           # the tiles are kept per game version


def test_tiles_that_are_not_shaped_like_one_are_dropped_and_the_rest_stays_in_order(instance):
    junk = [TILE, "text", None, 5, {"agg": "sum", "by": "all"}, {"stat": True, "agg": "sum", "by": "all", "value": ""}, {"stat": 1.5, "agg": "sum", "by": "all"},
            {"stat": "1", "agg": "sum", "by": "all"}, {"stat": 1, "agg": 3, "by": "all"}, {"stat": 1, "agg": "sum", "by": None},
            {"stat": 1, "agg": "sum", "by": "all", "value": 4}, {"stat": 2, "agg": "avg", "by": "char", "value": "A-B", "more": 1}, {"stat": 3, "agg": "median", "by": "guild"}]
    config.config_path().parent.mkdir(parents=True, exist_ok=True)
    config.config_path().write_text(json.dumps({"top5": {"_forever_": junk}}), encoding="utf-8")
    assert config.load()[0]["top5"] == {"_forever_": [TILE, {"stat": 2, "agg": "avg", "by": "char", "value": "A-B"},
                                                      {"stat": 3, "agg": "median", "by": "guild", "value": ""}]}       # only the shape is checked here, a missing value is empty


def test_at_most_five_tiles_per_version_are_kept_and_what_is_not_a_map_of_lists_gives_none(instance):
    config.config_path().parent.mkdir(parents=True, exist_ok=True)
    many = [{"stat": i, "agg": "sum", "by": "all", "value": ""} for i in range(config.TOP5_MAX + 3)]
    config.config_path().write_text(json.dumps({"top5": {"_retail_": many}}), encoding="utf-8")
    assert [t["stat"] for t in config.load()[0]["top5"]["_retail_"]] == list(range(config.TOP5_MAX)) and config.TOP5_MAX == 5
    for bad in ("text", 7, None, {"a": [TILE]}, {"retail": [TILE]}, {"_retail_": "text"}, {"_retail_": []}, {7: [TILE]}):    # a key must be a game version folder name, a version without tiles has no entry
        config.config_path().write_text(json.dumps({"top5": bad}), encoding="utf-8")
        assert config.load()[0]["top5"] == {}


def test_a_plain_list_of_tiles_from_before_is_the_tiles_of_retail(instance):
    config.config_path().parent.mkdir(parents=True, exist_ok=True)
    config.config_path().write_text(json.dumps({"top5": [TILE, {"stat": 9, "agg": "sum", "by": "all", "value": ""}]}), encoding="utf-8")
    cfg, _ = config.load()
    assert cfg["top5"] == {"_retail_": [TILE, {"stat": 9, "agg": "sum", "by": "all", "value": ""}]}
    config.save(cfg)                                                           # saved again in the new form
    assert json.loads(config.config_path().read_text(encoding="utf-8"))["top5"] == cfg["top5"]
    config.config_path().write_text(json.dumps({"top5": []}), encoding="utf-8")
    assert config.load()[0]["top5"] == {}


def test_there_is_no_blacklist_until_a_character_is_deleted_and_it_survives_the_file(instance):
    cfg, _ = config.load()
    assert cfg["char_blacklist"] == {}
    cfg["char_blacklist"] = {"_retail_": ["A-B", "Zoë-Realm"], "_forever_": ["C-D"]}
    config.save(cfg)
    assert config.load()[0]["char_blacklist"] == cfg["char_blacklist"]


def test_what_is_no_key_is_dropped_from_the_blacklist_and_every_key_stays_once(instance):
    junk = {"_retail_": ["A-B", "A-B", "", None, 5, ["C-D"], "E-F"], "_forever_": [None, ""], "_classic_": "no list", "retail": ["A-B"], "": ["A-B"],
            5: ["A-B"], "_x": ["A-B"], "_anniversary_": {"A-B": 1}}
    config.config_path().parent.mkdir(parents=True, exist_ok=True)
    config.config_path().write_text(json.dumps({"char_blacklist": junk}), encoding="utf-8")
    assert config.load()[0]["char_blacklist"] == {"_retail_": ["A-B", "E-F"]}           # no key left for a version: no entry


def test_the_blacklist_is_cut_at_its_maximum_and_what_is_no_dict_gives_none(instance):
    config.config_path().parent.mkdir(parents=True, exist_ok=True)
    many = [f"C{i}-R" for i in range(config.CHAR_BLACKLIST_MAX + 20)]
    config.config_path().write_text(json.dumps({"char_blacklist": {"_retail_": many}}), encoding="utf-8")
    assert config.load()[0]["char_blacklist"]["_retail_"] == many[:config.CHAR_BLACKLIST_MAX] and config.CHAR_BLACKLIST_MAX == 5000
    for bad in (["A-B"], "text", 7, None):
        config.config_path().write_text(json.dumps({"char_blacklist": bad}), encoding="utf-8")
        assert config.load()[0]["char_blacklist"] == {}
    assert config.clean_key_list(["A-B", "A-B", "", 5]) == ["A-B"] and config.clean_key_list("A-B") == []


RULE = {"type": "char", "value": "A-B"}


def test_there_are_no_char_rules_until_some_are_set_and_good_ones_survive_the_file(instance):
    cfg, _ = config.load()
    assert cfg["char_rules"] == {}
    cfg["char_rules"] = {"_retail_": [RULE, {"type": "char", "value": "C-D", "for": ["page"]}], "_forever_": [{"type": "char", "value": "E-F", "for": []}]}
    config.save(cfg)
    assert config.load()[0]["char_rules"] == cfg["char_rules"]


def test_rules_that_are_not_shaped_like_one_are_dropped_and_the_rest_stays_in_order(instance):
    junk = {"_retail_": [RULE, "text", None, 5, {"type": "char"}, {"value": "x"}, {"type": 1, "value": "x"}, {"type": "char", "value": 7},
                         {"type": "char", "value": "", "more": 1}, {"type": "class", "value": "MAGE", "for": "page"},
                         {"type": "char", "value": "G-H", "for": ["excel", 3, None]}],
            "_forever_": ["nothing", {"type": "char"}],                              # no rule left: no entry
            "retail": [RULE], "": [RULE], 5: [RULE], "_x": [RULE],                   # not a game version folder name
            "_classic_": "no list", "_anniversary_": {"type": "char", "value": "x"}}
    config.config_path().parent.mkdir(parents=True, exist_ok=True)
    config.config_path().write_text(json.dumps({"char_rules": junk}), encoding="utf-8")
    assert config.load()[0]["char_rules"] == {"_retail_": [
        RULE, {"type": "char", "value": ""}, {"type": "class", "value": "MAGE"}, {"type": "char", "value": "G-H", "for": ["excel"]}]}


def test_a_value_may_be_empty_but_not_missing_and_a_for_that_is_no_list_is_left_out(instance):
    assert config.clean_rule_list([{"type": "race", "value": ""}, {"type": "race"}, {"type": "race", "value": "Orc", "for": None}]) == \
        [{"type": "race", "value": ""}, {"type": "race", "value": "Orc"}]


def test_at_most_char_rules_max_rules_are_kept_per_version_and_what_is_not_a_dict_gives_none(instance):
    config.config_path().parent.mkdir(parents=True, exist_ok=True)
    many = [{"type": "char", "value": f"C{i}-R"} for i in range(config.CHAR_RULES_MAX + 20)]
    config.config_path().write_text(json.dumps({"char_rules": {"_retail_": many}}), encoding="utf-8")
    kept = config.load()[0]["char_rules"]["_retail_"]
    assert kept == many[:config.CHAR_RULES_MAX] and config.CHAR_RULES_MAX == 500
    for bad in ([RULE], "text", 7, None):
        config.config_path().write_text(json.dumps({"char_rules": bad}), encoding="utf-8")
        assert config.load()[0]["char_rules"] == {}
