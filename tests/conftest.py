# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)
# Shared fixtures: flat src/ imports, an isolated instance folder, a fixed language.

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "compiler"))

import i18n  # noqa: E402
import paths  # noqa: E402


@pytest.fixture(autouse=True)
def english():
    i18n.set_language("en")
    yield
    i18n.set_language("en")


@pytest.fixture
def instance(tmp_path, monkeypatch):
    """A temporary instance folder: paths.base_dir() points to it, the addon source is the real one."""
    monkeypatch.setattr(paths, "base_dir", lambda: tmp_path)
    (tmp_path / "addon").mkdir()
    import shutil
    shutil.copytree(ROOT / "addon" / "StatTracker", tmp_path / "addon" / "StatTracker")
    return tmp_path


def make_fake_wow(root):
    """A minimal WoW folder with _retail_ and _forever_ (one account each), a bare _classic_, and a .build.info."""
    for variant in ("_retail_", "_forever_"):
        (root / variant / "Interface" / "AddOns").mkdir(parents=True)
        (root / variant / "WTF" / "Account" / "ACC1" / "SavedVariables").mkdir(parents=True)
    (root / "_classic_" / "WTF").mkdir(parents=True)
    (root / ".build.info").write_text(
        "Branch!STRING:0|Active!DEC:1|Product!STRING:0|Version!STRING:0\n"
        "eu|1|wow|12.1.5.70575\n"
        "eu|1|wowf|1.600.1.1234\n", encoding="utf-8")
    return root


@pytest.fixture
def fake_wow(tmp_path):
    return make_fake_wow(tmp_path / "World of Warcraft")
