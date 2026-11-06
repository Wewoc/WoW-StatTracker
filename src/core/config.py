#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)
# config.py
# StatTracker - the one reader/writer of data/config.json (single owner).
#
#   language          "de" | "en"        (first start: the Windows UI language)
#   enabled_variants  ["_retail_", ...]  game versions offered in the GUI; default: Retail only
#   wow_dir           WoW main folder (the one containing _retail_ ...)
#   variant           last selected game version
#   accounts          {variant: account folder name}
#   check_updates     look for a new release at start (needs REPO_CONFIRMED)
#   read_icons        when importing, read the item icons of the stored equipment from the game files
#                     of the WoW installation (default on; off = icons already in data/ are still shown)
#   active_theme      number of the colour scheme of the window (core/theme.py; default 1, unknown numbers fall back)
#   group_presets     the presets of the Groups block of the stats page: [{name, by, off: [figure ids], extras: [{id, agg}]}];
#                     only the shape is checked here (what a preset may name is checked when it is applied)
#   top5              the tiles of the Top 5 block at the top of the stats page: [{stat: statistic id, agg: "sum"|"avg"|"max",
#                     by: "all"|"class"|"race"|"faction"|"realm"|"char", value: the scope as text, "" for all}], at most TOP5_MAX;
#                     only the shape is checked here (tile_rules and the block know what a tile may name); empty = no block

import json
import os
import re
import sys

from core import paths, theme

LANGUAGES = ("de", "en")
DEFAULT_VARIANT = "_retail_"
VARIANT_RE = re.compile(r"_.+_")
PRESET_NAME_MAX = 40       # longest name of a preset of the Groups block
PRESETS_MAX = 100          # a longer list is not one a person made
TOP5_MAX = 5               # tiles of the Top 5 block


def config_path():
    return paths.data_dir() / "config.json"


def default_language() -> str:
    """German if the Windows UI language is German, otherwise English."""
    if sys.platform == "win32":
        try:
            import ctypes
            lang_id = ctypes.windll.kernel32.GetUserDefaultUILanguage()
            if (lang_id & 0x3FF) == 0x07:  # LANG_GERMAN
                return "de"
        except (AttributeError, OSError):
            pass
    return "en"


def defaults() -> dict:
    return {
        "language": default_language(),
        "enabled_variants": [DEFAULT_VARIANT],
        "wow_dir": "",
        "variant": DEFAULT_VARIANT,
        "accounts": {},
        "check_updates": True,
        "read_icons": True,
        "active_theme": theme.DEFAULT_THEME,
        "group_presets": [],
        "top5": [],
    }


def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def clean_presets(raw) -> list:
    """The presets of the Groups block that are shaped like one: a unique name of 1 to PRESET_NAME_MAX characters, a grouping
    (text), the ids of the figures unticked (texts) and the statistics added ({"id": whole number >= 0, "agg": text}). Whatever
    is not shaped like that is dropped; at most PRESETS_MAX are kept."""
    if not isinstance(raw, list):
        return []
    names, clean = set(), []
    for item in raw:
        if not isinstance(item, dict):
            continue
        name, by, off, extras = item.get("name"), item.get("by"), item.get("off"), item.get("extras")
        if not (isinstance(name, str) and 0 < len(name) <= PRESET_NAME_MAX and name not in names and isinstance(by, str)
                and isinstance(off, list) and isinstance(extras, list)):
            continue
        names.add(name)
        clean.append({"name": name, "by": by, "off": [i for i in off if isinstance(i, str)],
                      "extras": [{"id": e["id"], "agg": e["agg"]} for e in extras
                                 if isinstance(e, dict) and _is_int(e.get("id")) and e["id"] >= 0 and isinstance(e.get("agg"), str)]})
    return clean[:PRESETS_MAX]


def clean_top5(raw) -> list:
    """The tiles of the Top 5 block that are shaped like one: a statistic (whole number), a function, a scope and its value (texts; the value
    may be empty). Whatever is not shaped like that is dropped; at most TOP5_MAX are kept, in their order."""
    if not isinstance(raw, list):
        return []
    clean = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        stat, agg, by, value = item.get("stat"), item.get("agg"), item.get("by"), item.get("value", "")
        if _is_int(stat) and isinstance(agg, str) and isinstance(by, str) and isinstance(value, str):
            clean.append({"stat": stat, "agg": agg, "by": by, "value": value})
    return clean[:TOP5_MAX]


def _sanitize(raw: dict) -> dict:
    cfg = defaults()
    if raw.get("language") in LANGUAGES:
        cfg["language"] = raw["language"]
    variants = raw.get("enabled_variants")
    if isinstance(variants, list):
        clean = [v for v in variants if isinstance(v, str) and VARIANT_RE.fullmatch(v)]
        if clean:
            cfg["enabled_variants"] = list(dict.fromkeys(clean))
    if isinstance(raw.get("wow_dir"), str):
        cfg["wow_dir"] = raw["wow_dir"]
    if isinstance(raw.get("variant"), str):
        cfg["variant"] = raw["variant"]
    if isinstance(raw.get("accounts"), dict):
        cfg["accounts"] = {k: v for k, v in raw["accounts"].items()
                           if isinstance(k, str) and isinstance(v, str)}
    if isinstance(raw.get("check_updates"), bool):
        cfg["check_updates"] = raw["check_updates"]
    if isinstance(raw.get("read_icons"), bool):
        cfg["read_icons"] = raw["read_icons"]
    if theme.is_known(raw.get("active_theme")):
        cfg["active_theme"] = raw["active_theme"]
    cfg["group_presets"] = clean_presets(raw.get("group_presets"))
    cfg["top5"] = clean_top5(raw.get("top5"))
    return cfg


def load():
    """Returns (config, warning). A missing file gives the defaults and no warning.
    An unreadable/corrupt file is moved to config.json.broken (never silently
    overwritten) and reported via `warning`."""
    path = config_path()
    if not path.is_file():
        return defaults(), None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("not a JSON object")
    except (OSError, ValueError) as exc:
        broken = path.with_name(path.name + ".broken")
        try:
            os.replace(path, broken)
        except OSError:
            broken = path
        return defaults(), f"{path.name}: {exc} -> {broken.name}"
    return _sanitize(raw), None


def save(cfg: dict) -> None:
    """Atomic write (temp file + replace); raises OSError on failure."""
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)
