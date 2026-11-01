#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)
# wow_install.py
# StatTracker - everything that touches a WoW installation, without UI:
# game versions, accounts, addon install/uninstall, .build.info.
#
# WoW folder = the folder containing _retail_ ... (and .build.info).
# Output files per game version live in data/ (see out_files()):
#   _retail_       -> wow_stats.db / stats.html
#   _anniversary_  -> wow_stats_anniversary.db / stats_anniversary.html   etc.
# The history pages of the characters go to a folder per game version (see history_dir()):
#   _retail_       -> history/        _anniversary_ -> history_anniversary/   etc.
# Tested: Retail works. BC Anniversary does not work (that game version provides no
# statistics). Everything else is untested.

import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path

import app_info
import paths
from i18n import t

ADDON_NAME = app_info.APP_NAME
DEFAULT_VARIANT = "_retail_"

WOW_CANDIDATES = (
    Path(r"C:\Program Files (x86)\World of Warcraft"),
    Path(r"C:\Program Files\World of Warcraft"),
)

# Folder name -> Product column in .build.info. Only wow (Retail) is tested; the
# other entries are assumptions. Unknown -> the interface number is left alone.
VARIANT_PRODUCT = {
    "_retail_": "wow",
    "_forever_": "wowf",
    "_classic_": "wow_classic",
    "_classic_era_": "wow_classic_era",
    "_classic_beta_": "wow_classic_beta",
    "_anniversary_": "wow_anniversary",
}


# ------------------------------------------------------------ folders / versions
def is_variant_name(name):
    return re.fullmatch(r"_.+_", name) is not None


def list_variants(root, enabled=None):
    """Game-version folders (_retail_, _anniversary_ ...) that contain a game (Interface or WTF).
    `enabled` (list of folder names) filters the result; None = everything found."""
    if not root or not root.is_dir():
        return []
    found = [d.name for d in root.iterdir()
             if d.is_dir() and is_variant_name(d.name) and ((d / "Interface").is_dir() or (d / "WTF").is_dir())]
    if enabled is not None:
        found = [n for n in found if n in enabled]
    found.sort(key=lambda n: (n != DEFAULT_VARIANT, n))
    return found


def resolve_root(path_text):
    """Accepts the WoW main folder OR a game-version folder (_retail_ ...) directly.
    Returns (root, variant_or_None) or (None, None)."""
    if not path_text.strip():
        return None, None
    p = Path(path_text.strip())
    if not p.is_dir():
        return None, None
    if is_variant_name(p.name):
        return p.parent, p.name
    if list_variants(p):
        return p, None
    return None, None


def guess_wow_dir():
    for c in WOW_CANDIDATES:
        if c.is_dir():
            return str(c)
    return ""


def list_accounts(game_dir):
    """Folders under WTF/Account (without the global SavedVariables folder).
    Accounts that already have a StatTracker.lua come first."""
    base = game_dir / "WTF" / "Account"
    if not base.is_dir():
        return []
    names = [d.name for d in base.iterdir() if d.is_dir() and d.name.lower() != "savedvariables"]
    names.sort(key=lambda n: (not saved_vars_path(game_dir, n).is_file(), n.lower()))
    return names


def saved_vars_path(game_dir, account):
    return game_dir / "WTF" / "Account" / account / "SavedVariables" / "StatTracker.lua"


def out_files(variant):
    """(db_path, html_path) per game version, in data/. Retail keeps the original names."""
    data = paths.data_dir()
    if variant == DEFAULT_VARIANT:
        return data / "wow_stats.db", data / "stats.html"
    n = variant.strip("_")
    return data / f"wow_stats_{n}.db", data / f"stats_{n}.html"


def history_dir(variant):
    """Folder of the history pages per game version, in data/ (next to the stats page it links to)."""
    data = paths.data_dir()
    if variant == DEFAULT_VARIANT:
        return data / "history"
    return data / f"history_{variant.strip('_')}"


# ------------------------------------------------------------- build info / toc
def parse_build_info(root):
    """Reads .build.info (pipe table). Returns {product: version} (first active row per product)."""
    path = root / ".build.info"
    try:
        lines = [l for l in path.read_text(encoding="utf-8", errors="replace").splitlines() if l.strip()]
    except OSError:
        return {}
    if len(lines) < 2:
        return {}
    cols = [c.split("!")[0] for c in lines[0].split("|")]
    if "Version" not in cols or "Product" not in cols:
        return {}
    iv, ip = cols.index("Version"), cols.index("Product")
    ia = cols.index("Active") if "Active" in cols else None
    result = {}
    for line in lines[1:]:
        f = line.split("|")
        if len(f) <= max(iv, ip):
            continue
        if ia is not None and len(f) > ia and f[ia] not in ("1", ""):
            continue
        result.setdefault(f[ip], f[iv])
    return result


def interface_number(version):
    """'12.1.5.70575' -> 120105 (major*10000 + minor*100 + patch). None for an unknown format."""
    m = re.match(r"(\d+)\.(\d+)\.(\d+)", version or "")
    if not m:
        return None
    a, b, c = map(int, m.groups())
    return a * 10000 + b * 100 + c


def patch_toc_interface(toc_path, number):
    text = toc_path.read_text(encoding="utf-8")
    new, n = re.subn(r"(?m)^## Interface:.*$", f"## Interface: {number}", text, count=1)
    if n != 1:
        raise RuntimeError(t("err_toc_interface", path=toc_path))
    toc_path.write_text(new, encoding="utf-8")


def toc_version(toc_path):
    """The '## Version:' value of a .toc file, or None."""
    try:
        text = Path(toc_path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    m = re.search(r"(?m)^## Version:\s*(\S+)", text)
    return m.group(1) if m else None


def toc_interface(toc_path):
    """The numbers of the '## Interface:' line of a .toc file (it may list several), or None."""
    try:
        text = Path(toc_path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    m = re.search(r"(?m)^## Interface:[ \t]*([\d, \t]+)", text)
    numbers = [int(n) for n in re.findall(r"\d+", m.group(1))] if m else []
    return numbers or None


def expected_interface(root, variant):
    """The interface number the installed copy should carry (from .build.info), or None if unknown."""
    product = VARIANT_PRODUCT.get(variant)
    return interface_number(parse_build_info(root).get(product)) if product else None


# ------------------------------------------------------------------ install
@dataclass
class InstallResult:
    dest: Path
    number: int = None      # interface number written into the copy (None = not set)
    version: str = None
    product: str = None


def addon_dir(root, variant):
    return root / variant / "Interface" / "AddOns" / ADDON_NAME


def install_addon(root, variant, addon_src=None):
    """Copies the addon to <root>/<variant>/Interface/AddOns and sets the interface
    number in the COPY from .build.info. Raises RuntimeError (translated message)."""
    src = Path(addon_src) if addon_src else paths.addon_src()
    if not (src / "StatTracker.toc").is_file() or not (src / "StatTracker.lua").is_file():
        raise RuntimeError(t("err_addon_source", path=src))
    addons = root / variant / "Interface" / "AddOns"
    if not addons.is_dir():
        raise RuntimeError(t("err_addons_dir", path=addons))
    dest = addons / ADDON_NAME
    shutil.copytree(src, dest, dirs_exist_ok=True)
    for name in ("StatTracker.toc", "StatTracker.lua"):  # check: copy exists and has the same size
        if (dest / name).stat().st_size != (src / name).stat().st_size:
            raise RuntimeError(t("err_copy_failed", path=dest / name))

    product = VARIANT_PRODUCT.get(variant)
    version = parse_build_info(root).get(product) if product else None
    number = interface_number(version)
    result = InstallResult(dest=dest, version=version, product=product)
    if number is not None:
        patch_toc_interface(dest / "StatTracker.toc", number)
        result.number = number
    return result


def addon_status(root, variant, addon_src=None):
    """('missing',) | ('ok', ver) | ('outdated', installed, bundled) | ('interface', installed, expected)
    | ('unknown',). 'unknown' = installed but a version cannot be compared. 'interface' = same version,
    but the installed .toc does not carry the interface number of the game build (.build.info), so WoW
    shows the addon as out of date; only reported when both numbers are known."""
    dest = addon_dir(root, variant)
    if not (dest / "StatTracker.toc").is_file():
        return ("missing",)
    installed = toc_version(dest / "StatTracker.toc")
    bundled = toc_version((Path(addon_src) if addon_src else paths.addon_src()) / "StatTracker.toc")
    if not installed or not bundled:
        return ("unknown",)
    if installed != bundled:
        return ("outdated", installed, bundled)
    expected = expected_interface(root, variant)
    carried = toc_interface(dest / "StatTracker.toc")
    if expected is not None and carried and expected not in carried:
        return ("interface", carried[0], expected)
    return ("ok", installed)


# ---------------------------------------------------------------- uninstall
@dataclass
class UninstallResult:
    removed_addon: bool = False
    removed_files: list = field(default_factory=list)


def _looks_like_addon_dir(dest):
    """Safety check before anything is deleted: exactly AddOns/StatTracker with our .toc, no link."""
    return (dest.name == ADDON_NAME and dest.parent.name.lower() == "addons"
            and dest.is_dir() and not dest.is_symlink()
            and (dest / "StatTracker.toc").is_file())


def saved_vars_files(game_dir):
    """All StatTracker.lua (+ .bak) files of all accounts."""
    found = []
    base = game_dir / "WTF" / "Account"
    if not base.is_dir():
        return found
    for acc in base.iterdir():
        if not acc.is_dir() or acc.name.lower() == "savedvariables":
            continue
        for name in ("StatTracker.lua", "StatTracker.lua.bak"):
            p = acc / "SavedVariables" / name
            if p.is_file():
                found.append(p)
    return found


def uninstall_addon(root, variant, remove_saved_vars=False):
    """Removes <root>/<variant>/Interface/AddOns/StatTracker. With remove_saved_vars
    also the addon's SavedVariables files in WTF. NEVER touches the local database
    or generated pages in data/."""
    result = UninstallResult()
    dest = addon_dir(root, variant)
    if dest.exists():
        if not _looks_like_addon_dir(dest):
            raise RuntimeError(t("err_uninstall_unsafe", path=dest))
        shutil.rmtree(dest)
        result.removed_addon = True
    if remove_saved_vars:
        for p in saved_vars_files(root / variant):
            p.unlink()
            result.removed_files.append(p)
    return result
