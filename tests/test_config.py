# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

import json

import config


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
