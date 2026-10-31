# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

import re
import string
from pathlib import Path

import pytest

import i18n

SRC = Path(__file__).resolve().parent.parent / "src"
NAME_PREFIXES = ("class_", "race_")


def _fields(text):
    return {name for _lit, name, _spec, _conv in string.Formatter().parse(text) if name is not None}


def test_every_key_has_both_languages():
    for key, entry in i18n._STRINGS.items():
        assert set(entry) == {"de", "en"}, key
        assert entry["de"].strip() and entry["en"].strip(), key


def test_placeholders_match_between_languages():
    for key, entry in i18n._STRINGS.items():
        assert _fields(entry["de"]) == _fields(entry["en"]), key


def _code_files():
    return [p for p in SRC.glob("*.py") if p.name != "i18n.py"]


def test_every_key_used_in_code_exists():
    literal = re.compile(r"""\bt\(\s*f?["']([A-Za-z0-9_{}]+)["']""")
    for path in _code_files():
        for key in literal.findall(path.read_text(encoding="utf-8")):
            if "{" in key:          # dynamic key (f-string), covered by test_dynamic_unit_keys
                continue
            assert key in i18n._STRINGS, f"{path.name}: unknown i18n key {key!r}"


def test_dynamic_unit_keys():
    for code in ("num", "gold", "hours", "text", "mix"):
        assert f"unit_{code}" in i18n._STRINGS


def test_every_key_is_used_somewhere():
    code = "\n".join(p.read_text(encoding="utf-8") for p in _code_files())
    template = (SRC / "template.html").read_text(encoding="utf-8")
    unused = []
    for key in i18n._STRINGS:
        if key.startswith("html_"):
            if f"UI.{key[len('html_'):]}" not in template:
                unused.append(key)
        elif key.startswith("unit_"):
            if 'f"unit_{' not in code:
                unused.append(key)
        elif key.startswith(NAME_PREFIXES):             # class_* / race_*: read through i18n.names(prefix, lang)
            prefix = next(p for p in NAME_PREFIXES if key.startswith(p))
            if f'names("{prefix}"' not in code:
                unused.append(key)
        elif f'"{key}"' not in code:
            unused.append(key)
    assert not unused, f"unused i18n keys: {unused}"


def test_t_formats_and_switches_language():
    i18n.set_language("de")
    assert i18n.t("btn_close") == "Schließen"
    i18n.set_language("en")
    assert i18n.t("btn_close") == "Close"
    assert i18n.t("update_none", version="1.2.3").endswith("(1.2.3).")


def test_unknown_key_is_visible_not_empty():
    assert i18n.t("no_such_key") == "[no_such_key]"


def test_unknown_language_falls_back_to_english():
    i18n.set_language("fr")
    assert i18n.get_language() == "en"


def test_html_strings_cover_the_template():
    template = (SRC / "template.html").read_text(encoding="utf-8")
    used = set(re.findall(r"UI\.(\w+)", template))
    for lang in ("de", "en"):
        provided = set(i18n.html_strings(lang))
        assert used <= provided, (lang, used - provided)


CLASS_FILES = {"WARRIOR", "PALADIN", "HUNTER", "ROGUE", "PRIEST", "DEATHKNIGHT", "SHAMAN", "MAGE",
               "WARLOCK", "MONK", "DRUID", "DEMONHUNTER", "EVOKER"}


@pytest.mark.parametrize("lang", ["de", "en"])
def test_names_hold_every_class_and_the_known_races(lang):
    classes, races = i18n.names("class_", lang), i18n.names("race_", lang)
    assert set(classes) == CLASS_FILES                      # the game has exactly these classes
    assert {"Human", "Orc", "NightElf", "Scourge", "BloodElf", "Dracthyr"} <= set(races)
    assert all(v and not v.startswith("[") for v in (*classes.values(), *races.values()))
    assert not any(k in classes or k in races for k in ("", "Mage "))


def test_names_are_neutral_and_differ_by_language():
    assert i18n.names("class_", "de")["DRUID"] == "Druide"          # not "Druidin"
    assert i18n.names("class_", "en")["DEATHKNIGHT"] == "Death Knight"
    assert i18n.names("race_", "de")["Scourge"] == "Untoter"


@pytest.mark.parametrize("lang", ["de", "en"])
def test_format_helpers_with_real_fields(lang):
    i18n.set_language(lang)
    # catches a placeholder that t() would silently leave unformatted
    assert "{" not in i18n.t("status_addon_outdated", installed="1", bundled="2")
    assert "{" not in i18n.t("duration_fmt", d=1, h=2, m=3, s=4)
