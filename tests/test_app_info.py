# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

import re
from pathlib import Path

import pytest

import app_info
import wow_install

ROOT = Path(__file__).resolve().parent.parent


@pytest.mark.parametrize("latest,current,expected", [
    ("v0.2.0", "0.1.0", True),
    ("0.1.1", "0.1.0", True),
    ("1.0.0", "0.9.9", True),
    ("0.1.0", "0.1.0", False),
    ("0.0.9", "0.1.0", False),
    ("0.10.0", "0.9.0", True),        # numeric, not string comparison
    ("v0.2", "0.1.0", True),
    ("nightly", "0.1.0", False),      # unparseable is never "newer"
    ("0.2.0", "dev", False),
    ("", "0.1.0", False),
])
def test_is_newer(latest, current, expected):
    assert app_info.is_newer(latest, current) is expected


def test_addon_version_matches_app_version():
    toc = ROOT / "addon" / "StatTracker" / "StatTracker.toc"
    assert wow_install.toc_version(toc) == app_info.APP_VERSION


def test_version_is_plain_dotted_number():
    assert re.fullmatch(r"\d+\.\d+\.\d+", app_info.APP_VERSION)


def test_urls_are_derived_from_one_repo():
    assert app_info.REPO_URL.endswith(f"{app_info.REPO_OWNER}/{app_info.REPO_NAME}")
    assert app_info.LATEST_API_URL.startswith("https://api.github.com/repos/")
    assert app_info.RELEASES_URL.startswith(app_info.REPO_URL)


def test_repository_is_the_published_one_everywhere():
    assert app_info.REPO_URL == "https://github.com/Wewoc/WoW-StatTracker"
    assert app_info.REPO_CONFIRMED is True
    stale = re.compile(r"github\.com/Wewoc/StatTracker\b|repos/Wewoc/StatTracker\b")
    files = [ROOT / n for n in ("README.md", "README.de.md", "CHANGELOG.md", "docs/index.html", "docs/DEVELOPMENT.md",
                                "addon/StatTracker/StatTracker.toc")]
    files += list((ROOT / "src").glob("*.py")) + list((ROOT / ".github").rglob("*.yml"))
    for path in files:
        assert not stale.search(path.read_text(encoding="utf-8")), f"old repository name in {path.name}"
    for name in ("README.md", "README.de.md", "docs/index.html", "addon/StatTracker/StatTracker.toc"):
        assert app_info.REPO_URL in (ROOT / name).read_text(encoding="utf-8"), name


def test_release_items_never_include_user_data():
    assert app_info.EXE_NAME in app_info.PROGRAM_ITEMS
    assert app_info.DATA_DIRNAME not in app_info.PROGRAM_ITEMS
    assert "data" not in app_info.PROGRAM_ITEMS


def test_author_in_toc_is_wewoc():
    text = (ROOT / "addon" / "StatTracker" / "StatTracker.toc").read_text(encoding="utf-8")
    assert "## Author: Wewoc" in text
