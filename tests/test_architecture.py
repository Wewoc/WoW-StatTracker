# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)
# Guards for rules that only held because nobody broke them. Reads files, writes nothing:
#  - StatTrackerDB.version in the addon is the data version the parser knows (works without lupa),
#  - the release workflow publishes the asset names the updater looks for (app_info is the source),
#  - the leaf modules import only what the invariants allow,
#  - a module uses only the file-writing calls it is meant to (GUI and leaf modules use none).

import ast
import re
import sys
from pathlib import Path

import pytest

import app_info
from stat_parser import DATA_VERSION

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
LUA = ROOT / "addon" / "StatTracker" / "StatTracker.lua"
RELEASE_WORKFLOW = ROOT / ".github" / "workflows" / "release.yml"

# A code line only: the comment in the file header ("--   StatTrackerDB.version = N") starts with "--".
LUA_VERSION_LINE = re.compile(r"^[ \t]*StatTrackerDB\.version[ \t]*=[ \t]*(\d+)[ \t]*$", re.MULTILINE)


def test_the_addon_data_version_is_the_one_the_parser_knows():
    found = LUA_VERSION_LINE.findall(LUA.read_text(encoding="utf-8"))
    assert len(found) == 1, f"expected one 'StatTrackerDB.version = N' line, found {len(found)}"
    assert int(found[0]) == DATA_VERSION


def test_the_release_workflow_publishes_the_assets_the_updater_looks_for():
    lines = {line.strip() for line in RELEASE_WORKFLOW.read_text(encoding="utf-8").splitlines()}
    assert f"dist/{app_info.ZIP_ASSET_NAME}" in lines
    assert f"dist/{app_info.ZIP_CHECKSUM_ASSET_NAME}" in lines


# module -> project modules it may import (everything else must come from the standard library)
LEAF_MODULES = {
    "app_info": set(),
    "paths": {"app_info"},
    "plotly_asset": {"paths"},
    "i18n": set(),
}


def imported_modules(path):
    """Top-level names of every import in the file, including those inside functions and try blocks.
    A relative import is reported as '.'."""
    names = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            names.add("." if node.level else node.module.split(".")[0])
    return names


@pytest.mark.parametrize("module", sorted(LEAF_MODULES))
def test_leaf_modules_import_only_what_the_invariants_allow(module):
    allowed = set(sys.stdlib_module_names) | LEAF_MODULES[module]
    unexpected = imported_modules(SRC / f"{module}.py") - allowed
    assert not unexpected, f"{module}.py imports {sorted(unexpected)}"


# File-writing calls that can be told apart by name alone. Not covered: the Excel file (wb.save cannot be
# told from the GUI's own save()), and where a module writes - only what it writes with.
WRITE_METHODS = {"write_text", "write_bytes", "unlink", "mkdir", "touch", "rmdir", "executescript", "commit",
                 "extractall"}
WRITE_MODULE_CALLS = {"os": {"replace", "rename", "remove", "makedirs", "startfile", "unlink", "rmdir"},
                      "shutil": None,                      # None: every function of the module
                      "sqlite3": {"connect"},
                      "subprocess": {"Popen", "run", "call"}}


def opens_for_writing(call, mode_position):
    """open(path, mode) has the mode second, Path.open(mode) first; either may be a keyword."""
    mode = call.args[mode_position] if len(call.args) > mode_position else \
        next((k.value for k in call.keywords if k.arg == "mode"), None)
    return isinstance(mode, ast.Constant) and isinstance(mode.value, str) and any(c in mode.value for c in "wax+")


def write_primitives(path):
    found = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name) and func.id == "open":
            if opens_for_writing(node, 1):
                found.add("open(write)")
        elif isinstance(func, ast.Attribute):
            if isinstance(func.value, ast.Name) and func.value.id in WRITE_MODULE_CALLS:
                only = WRITE_MODULE_CALLS[func.value.id]
                if only is None or func.attr in only:
                    found.add(f"{func.value.id}.{func.attr}")
            elif func.attr in WRITE_METHODS:
                found.add(func.attr)
            elif func.attr == "open" and opens_for_writing(node, 0):
                found.add("open(write)")
    return found


# module -> the write calls it may use; a module that is not listed uses none. Whoever changes who
# writes what (CLAUDE.md, "Single Owner") changes this table in the same step.
ALLOWED_WRITES = {
    "config": {"mkdir", "os.replace", "write_text"},
    "db_backup": {"mkdir", "os.replace", "sqlite3.connect", "unlink"},
    "export_xlsx": {"mkdir", "sqlite3.connect"},
    "gui_app": {"os.startfile"},                           # opens a file, writes nothing
    "start": {"mkdir", "open(write)"},
    "stat_history": {"mkdir", "os.replace", "sqlite3.connect", "unlink", "write_bytes", "write_text"},
    "stat_parser": {"commit", "executescript", "mkdir", "sqlite3.connect", "write_text"},
    "updater": {"extractall", "mkdir", "open(write)", "shutil.copy2", "shutil.copyfileobj", "shutil.rmtree",
                "subprocess.Popen", "touch", "unlink"},
    "wow_install": {"shutil.copytree", "shutil.rmtree", "unlink", "write_text"},
}


def test_the_write_table_names_only_existing_modules():
    assert sorted(set(ALLOWED_WRITES) - {p.stem for p in SRC.glob("*.py")}) == []


def test_modules_use_only_the_file_writing_calls_they_are_meant_to():
    unexpected = {}
    for path in sorted(SRC.glob("*.py")):
        extra = write_primitives(path) - ALLOWED_WRITES.get(path.stem, set())
        if extra:
            unexpected[path.name] = sorted(extra)
    assert not unexpected, unexpected
