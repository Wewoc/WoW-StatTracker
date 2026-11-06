# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)
# The notices of the software of others that the release carries (THIRD_PARTY_LICENSES.md, LICENSE-LGPL-3.0.txt): the Qt stack of the window must be named
# with its licenses, the LGPL text must travel with the release, and the versions named must be those the requirements allow.

import re
from pathlib import Path

import build_manifest as manifest

ROOT = Path(__file__).resolve().parent.parent
NOTICES = (ROOT / "THIRD_PARTY_LICENSES.md").read_text(encoding="utf-8")


def test_the_qt_stack_is_named_with_its_licenses_and_where_its_source_is():
    for part in ("PyQt6", "PyQt6-WebEngine", "GPL v3", "GNU Lesser General Public License v3", "Qt WebEngine", "Chromium", "LICENSE-LGPL-3.0.txt",
                 "https://download.qt.io/official_releases/qt/", "sip", "BSD 2-Clause"):
        assert part in NOTICES, part
    assert "unmodified" in NOTICES                                  # the claim has to stay true: the build only leaves files out (build_manifest.TRIM_GLOBS)


def test_the_versions_named_are_the_ones_the_requirements_allow():
    wanted = re.search(r"PyQt6>=(\d+\.\d+),<(\d+\.\d+)", (ROOT / "requirements.txt").read_text(encoding="utf-8"))
    low, high = wanted.groups()
    assert f"version {low}." in NOTICES and f"Qt {low}." in NOTICES                  # e.g. "version 6.11.0" (PyQt6) and "Qt 6.11.2" (the source of Qt)
    assert high != low


def test_the_lgpl_text_is_in_the_repository_and_goes_into_the_info_folder_of_the_release():
    text = (ROOT / "LICENSE-LGPL-3.0.txt").read_text(encoding="utf-8")
    assert "GNU LESSER GENERAL PUBLIC LICENSE" in text and "Version 3, 29 June 2007" in text
    assert "LICENSE-LGPL-3.0.txt" in manifest.INFO_FILES and "THIRD_PARTY_LICENSES.md" in manifest.INFO_FILES


def test_other_software_that_is_in_the_release_is_named():
    for part in ("Python 3.13", "PyInstaller", "openpyxl", "et_xmlfile", "MIT license", "CascLib", "plotly.js"):
        assert part in NOTICES, part


def test_both_readmes_point_to_the_notices_for_the_window():
    for name in ("README.md", "README.de.md"):
        text = (ROOT / name).read_text(encoding="utf-8")
        assert "PyQt6" in text and "Qt WebEngine" in text and "LICENSE-LGPL-3.0.txt" in text and "THIRD_PARTY_LICENSES.md" in text, name
