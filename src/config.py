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

import json
import os
import re
import sys

import paths

LANGUAGES = ("de", "en")
DEFAULT_VARIANT = "_retail_"
VARIANT_RE = re.compile(r"_.+_")


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
    }


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
