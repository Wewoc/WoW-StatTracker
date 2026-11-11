# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)
# Guards for the public documentation: the things that drifted in the past because nothing
# checked them (a new module missing from the layout, one README ahead of the other, a
# version without its changelog chapter). Only files that are in the repository are read.

import re
from pathlib import Path

from core import app_info

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"


def _read(name):
    return (ROOT / name).read_text(encoding="utf-8")


def test_every_module_is_named_in_the_layout_of_development_md():
    """A module directly in a src/ folder must appear in the Layout block of docs/DEVELOPMENT.md.

    The modules of src/pages/blocks/ are described as a group there (one module each, and
    layout.py), so they are not listed one by one.
    """
    text = _read("docs/DEVELOPMENT.md")
    layout = text.split("## Layout", 1)[1].split("```", 2)[1]
    missing = []
    for path in sorted(SRC.glob("*/*.py")):
        if path.name == "__init__.py":
            continue
        if not re.search(rf"\b{re.escape(path.stem)}\b", layout):
            missing.append(f"{path.parent.name}/{path.name}")
    assert not missing, f"not in the Layout of docs/DEVELOPMENT.md: {missing}"


def test_changelog_starts_with_the_current_version():
    first = re.search(r"^## (\S+)", _read("CHANGELOG.md"), re.M)
    assert first and first.group(1) == app_info.APP_VERSION, (first and first.group(1), app_info.APP_VERSION)


def test_both_readmes_have_the_same_structure():
    """Same number of headings on the same lines' levels: a new section must come in both languages."""
    def levels(name):
        return [len(m.group(1)) for m in re.finditer(r"^(#{1,6}) ", _read(name), re.M)]
    assert levels("README.md") == levels("README.de.md")
