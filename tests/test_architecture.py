# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)
# Guards for rules that only held because nobody broke them. Reads files, writes nothing:
#  - StatTrackerDB.version in the addon is the data version the parser knows (works without lupa),
#  - the release workflow publishes the asset names the updater looks for (app_info is the source),
#  - the leaf modules import only what the invariants allow,
#  - the modules of src/ depend on each other in one direction only: no import cycle, no import hidden inside a function,
#  - a module uses only the file-writing calls it is meant to (GUI and leaf modules use none).

import ast
import re
import sys
from pathlib import Path

import pytest

from core import app_info
from store.importer import DATA_VERSION

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
# every module of src/ by name (the folders are packages: src/core/paths.py is "paths" here, "core.paths" for Python)
SRC_FILES = {p.stem: p for p in sorted(SRC.rglob("*.py")) if p.stem != "__init__" and "__pycache__" not in p.parts}
PACKAGES = {p.name for p in SRC.iterdir() if p.is_dir() and (p / "__init__.py").is_file()}
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
    "blp_decode": set(),
    "casclib_asset": {"paths"},
    "i18n": set(),
    "lua_reader": set(),
    "stat_derive": set(),
    "db_backup": set(),
    "stat_values": {"i18n"},
    "numfmt": set(),                       # the rules of the stats page blocks: calculation only, no files, no project module but stat_derive
    "collation": set(),
    "table_rules": {"collation"},
    "group_rules": {"stat_derive", "collation"},
    "rep_rules": set(),
    "markup": set(),                       # the blocks of the stats page (pages/blocks): they read the payload and use nothing else
    "view": set(),
    "history_links": {"markup"},
    "cells": {"markup", "numfmt"},
    "tile_rules": {"group_rules"},
    "top5": {"markup", "cells", "group_rules", "tile_rules"},
    "groups": {"markup", "view", "cells", "group_rules", "numfmt"},
    "rates": {"markup", "numfmt"},
    "reputation": {"markup", "view", "numfmt", "rep_rules"},
    "footer": {"markup"},
    "char_picker": {"markup"},
    "stat_table": {"markup", "view", "table_rules"},
    "layout": {"history_links", "char_picker", "top5", "groups", "rates", "reputation", "stat_table", "footer", "view"},           # a new block module is added here and in layout.INDEX/MODULES
}


def _nested(parts):
    """True for a package inside a project package (pages.blocks): its modules are named by the part after it."""
    return len(parts) > 1 and parts[0] in PACKAGES and (SRC / parts[0] / parts[1] / "__init__.py").is_file()


def _names(node):
    """The modules an import statement names: for a project package (`from core import paths`, `import core.paths`) the
    modules inside it, otherwise the top-level name (standard library, third party)."""
    if isinstance(node, ast.Import):
        found = set()
        for alias in node.names:
            parts = alias.name.split(".")
            if _nested(parts):
                if len(parts) > 2:
                    found.add(parts[2])
            else:
                found.add(parts[1] if parts[0] in PACKAGES and len(parts) > 1 else parts[0])
        return found
    if node.level:
        return {"."}
    parts = node.module.split(".")
    if _nested(parts):
        return {parts[2]} if len(parts) > 2 else {alias.name for alias in node.names}
    if parts[0] in PACKAGES:
        return {parts[1]} if len(parts) > 1 else {alias.name for alias in node.names}
    return {parts[0]}


def imported_modules(path):
    """Names of every import in the file, including those inside functions and try blocks; a project module is named
    by its file (paths, not core.paths). A relative import is reported as '.'."""
    names = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names |= _names(node)
    return names


@pytest.mark.parametrize("module", sorted(LEAF_MODULES))
def test_leaf_modules_import_only_what_the_invariants_allow(module):
    allowed = set(sys.stdlib_module_names) | LEAF_MODULES[module]
    unexpected = imported_modules(SRC_FILES[module]) - allowed
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
    "db_schema": {"executescript", "mkdir", "sqlite3.connect"},       # init_db: the only way a database is opened for writing
    "export_xlsx": {"mkdir", "sqlite3.connect"},
    "main_window": {"os.startfile"},                       # opens the Excel file, writes nothing
    "importer": {"commit"},                                # import_data and refresh_numbers commit once at the end
    "outputs": {"mkdir", "write_text"},                    # write_html: the stats page
    "start": {"mkdir", "open(write)"},
    "stat_history": {"mkdir", "os.replace", "sqlite3.connect", "unlink", "write_bytes", "write_text"},
    "updater": {"extractall", "mkdir", "open(write)", "shutil.copy2", "shutil.copyfileobj", "shutil.rmtree",
                "subprocess.Popen", "touch", "unlink"},
    "wow_icons": {"mkdir", "os.replace", "unlink", "write_bytes", "write_text"},      # data/icons/ and its memory file
    "wow_install": {"shutil.copytree", "shutil.rmtree", "unlink", "write_text"},
}


def test_the_write_table_names_only_existing_modules():
    assert sorted(set(ALLOWED_WRITES) - set(SRC_FILES)) == []


def test_modules_use_only_the_file_writing_calls_they_are_meant_to():
    unexpected = {}
    for path in SRC_FILES.values():
        extra = write_primitives(path) - ALLOWED_WRITES.get(path.stem, set())
        if extra:
            unexpected[path.name] = sorted(extra)
    assert not unexpected, unexpected


# ---------------------------------------------------------------- one direction only
PROJECT = set(SRC_FILES)
# module -> project modules it may import inside a function (none otherwise). start.py loads the window only when it runs.
LATE_IMPORTS = {"start": {"main_window"}}


def top_level_imports(path):
    """Project modules imported at the top of the file (directly in the module body)."""
    found = set()
    for node in ast.parse(path.read_text(encoding="utf-8")).body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            found |= _names(node)
    return found & PROJECT


def test_no_module_hides_an_import_inside_a_function():
    """A late import is how a cycle is hidden: the cycle between stat_parser and stat_history was one."""
    late = {}
    for path in SRC_FILES.values():
        extra = (imported_modules(path) & PROJECT) - top_level_imports(path) - LATE_IMPORTS.get(path.stem, set()) - {path.stem}
        if extra:
            late[path.name] = sorted(extra)
    assert not late, late


def test_the_modules_of_src_have_no_import_cycle():
    graph = {name: top_level_imports(p) - {name} for name, p in SRC_FILES.items()}
    for start_module, late_modules in LATE_IMPORTS.items():
        graph[start_module] |= late_modules
    state, stack = {}, []

    def visit(name):
        if state.get(name) == "done":
            return None
        if state.get(name) == "open":
            return stack[stack.index(name):] + [name]
        state[name] = "open"
        stack.append(name)
        for other in sorted(graph[name]):
            cycle = visit(other)
            if cycle:
                return cycle
        stack.pop()
        state[name] = "done"
        return None

    for name in sorted(graph):
        cycle = visit(name)
        assert not cycle, " -> ".join(cycle)


def test_only_the_window_logic_calls_the_parser():
    """stat_parser orders the steps of an import; the window reaches it through actions only (tools/make_demo.py is no module of src/)."""
    users = sorted(name for name, p in SRC_FILES.items() if "stat_parser" in imported_modules(p) and name != "stat_parser")
    assert users == ["actions"], users


def test_every_module_name_is_unique_and_every_folder_is_a_package():
    """The checks above key the modules by file name; two files of one name in two folders would hide one of them."""
    files = [p for p in SRC.rglob("*.py") if p.stem != "__init__" and "__pycache__" not in p.parts]
    assert len(files) == len(SRC_FILES)
    folders = [p for p in SRC.iterdir() if p.is_dir() and p.name != "__pycache__" and any(p.rglob("*.py"))]
    assert sorted(p.name for p in folders if p.name not in PACKAGES) == []
    nested = {p.parent for p in SRC.rglob("*.py") if "__pycache__" not in p.parts and p.parent != SRC}
    assert sorted(str(d.relative_to(SRC)) for d in nested if not (d / "__init__.py").is_file()) == []


# folder -> the other folders it may import from (a folder may always import from itself). Low to high:
# core and rules stand alone; store and game need core; pages shows what store, game and rules hold; export needs
# store; app (the window and the order of the steps) may use everything. start.py, the entry script, is not a folder.
FOLDER_MAY_USE = {
    "core": set(),
    "rules": set(),
    "store": {"core"},
    "game": {"core"},
    "pages": {"core", "store", "game", "rules"},
    "export": {"core", "store"},
    "app": {"core", "store", "game", "rules", "pages", "export"},
}


def test_the_folders_depend_on_each_other_in_one_direction_only():
    assert set(FOLDER_MAY_USE) == PACKAGES, "a new folder needs a line in FOLDER_MAY_USE"
    folder_of = {name: p.relative_to(SRC).parts[0] for name, p in SRC_FILES.items() if len(p.relative_to(SRC).parts) > 1}
    wrong = []
    for name, path in SRC_FILES.items():
        if name not in folder_of:
            continue                                                   # start.py
        for other in sorted(imported_modules(path) & PROJECT):
            target = folder_of.get(other)
            if target and target != folder_of[name] and target not in FOLDER_MAY_USE[folder_of[name]]:
                wrong.append(f"{folder_of[name]}/{name} imports {target}/{other}")
    assert not wrong, wrong
