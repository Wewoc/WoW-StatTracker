# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)
# Guard for what gets published: no private names, e-mail addresses or local paths,
# and no instance data (databases, generated pages, config) anywhere in the checkout.
# Patterns are built from fragments so this file does not match itself.

import fnmatch
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

SCOPE_DIRS = ["src", "tests", "compiler", "tools", "addon", "docs", ".github"]
SCOPE_FILES = ["README.md", "README.de.md", "CHANGELOG.md", "requirements.txt", "requirements-dev.txt", ".gitignore"]
TEXT_SUFFIXES = {".py", ".md", ".txt", ".bat", ".json", ".toml", ".cfg", ".ini", ".yml", ".yaml",
                 ".ps1", ".lua", ".toc", ".html", ""}

FORBIDDEN = {
    "private first name": (r"\bTi" + r"mo\b", 0),
    "private e-mail": (r"[\w.]+@(?:g" + r"mail|g" + r"mx|w" + r"eb)\.", re.IGNORECASE),
    "private mailbox name": (r"haus" + r"deswahns", re.IGNORECASE),
    "local path (user)": (r"[A-Z]:[\\/]+Us" + r"ers", 0),
    "local path (projects)": (r"[A-Z]:[\\/]+(?:Git" + r"hub|Spi" + r"ele|W" + r"oW)\b", 0),
}

NEVER_SHIPPED = ["wow_stats*.db", "stats*.html", "history-*.html", "*.xlsx", "*.bak", "config.json", "gui_config.json",
                 "crash.log", "*.zip", "*.sha256"]
SKIP_DIRS = {".git", ".venv-build", "build", "dist", "data", "__pycache__", ".pytest_cache"}


def _scope():
    found = []
    for directory in SCOPE_DIRS:
        base = ROOT / directory
        if base.is_dir():
            found += [p for p in base.rglob("*")
                      if p.is_file() and "__pycache__" not in p.parts and p.suffix in TEXT_SUFFIXES]
    found += [ROOT / n for n in SCOPE_FILES if (ROOT / n).is_file()]
    return found


def test_the_guard_actually_scans_something():
    assert len(_scope()) >= 30


@pytest.mark.parametrize("label", list(FORBIDDEN))
def test_published_files_carry_no_private_reference(label):
    pattern, flags = FORBIDDEN[label]
    regex = re.compile(pattern, flags)
    hits = []
    for path in _scope():
        for number, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            if regex.search(line):
                hits.append(f"{path.relative_to(ROOT)}:{number}")
    assert not hits, f"{label}: {hits[:10]}"


def test_no_instance_data_in_the_checkout():
    offenders = []
    for path in ROOT.rglob("*"):
        rel_parts = path.relative_to(ROOT).parts
        if any(part in SKIP_DIRS for part in rel_parts) or not path.is_file():
            continue
        if any(fnmatch.fnmatch(path.name, pattern) for pattern in NEVER_SHIPPED):
            offenders.append("/".join(rel_parts))
    assert not offenders, offenders


def test_every_python_file_has_the_license_header():
    missing = []
    for path in list((ROOT / "src").glob("*.py")) + list((ROOT / "compiler").glob("*.py")) \
            + list((ROOT / "tests").glob("*.py")) + list((ROOT / "tools").glob("*.py")):
        head = path.read_text(encoding="utf-8").splitlines()[:3]
        if not any("SPDX-License-Identifier: GPL-3.0-or-later" in line for line in head):
            missing.append(path.name)
    assert not missing, missing
