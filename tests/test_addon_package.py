# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)
# compiler/addon_package.py: what goes to CurseForge. The tag must be addon-v<version of the .toc>, the changelog of the file page comes from
# the lines of the chapter "## <version>" of addon/CHANGELOG.md (the current version must have some, so an addon release cannot be made without them), the
# staged .toc lists the interface number of WoW Forever as well and the .toc in the repository stays as it is.

import importlib.util
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("addon_package", ROOT / "compiler" / "addon_package.py")
addon_package = importlib.util.module_from_spec(spec)
spec.loader.exec_module(addon_package)
TOC = ROOT / "addon" / "StatTracker" / "StatTracker.toc"


def repo_version():
    return addon_package.toc_value(TOC.read_text(encoding="utf-8"), "Version")


def test_the_tag_must_be_addon_v_and_the_version_of_the_toc():
    addon_package.check_tag("addon-v0.2.4", "0.2.4")
    for bad in ("v0.2.4", "addon-v0.2.5", "addon-0.2.4", "addon-v0.2.4-beta", ""):
        with pytest.raises(addon_package.PackageError):
            addon_package.check_tag(bad, "0.2.4")


def test_the_changelog_lines_of_one_addon_version_are_the_lines_of_its_chapter():
    text = ("# Changelog\n\n- an introduction line before the first chapter\n\n"
            "## 0.2.5\n\n- Fixed: a bug \n\n## 0.2.4\n\n- New: a window\n  not a line of its own\n- New: a page \n\n"
            "## 0.2.40\n\n- not this one\n\n## 0.2.3\n\n- older\n")
    assert addon_package.changelog_lines(text, "0.2.4") == ["New: a window", "New: a page"]
    assert addon_package.changelog_lines(text, "0.2.5") == ["Fixed: a bug"]          # the first chapter ends at the next heading too
    assert addon_package.changelog_lines(text, "0.2.3") == ["older"]                 # and the last one at the end of the text
    for missing in ("0.9.9", "0.2"):
        with pytest.raises(addon_package.PackageError):
            addon_package.changelog_lines(text, missing)
    with pytest.raises(addon_package.PackageError):                                   # a chapter without lines is no changelog
        addon_package.changelog_lines("## 0.2.4\n\nno list here\n\n## 0.2.3\n\n- older\n", "0.2.4")


def test_changelog_lines_with_windows_line_ends_have_no_carriage_return():
    text = "## 0.2.4\r\n\r\n- New: a window\r\n- New: a page\r\n"
    assert addon_package.changelog_lines(text, "0.2.4") == ["New: a window", "New: a page"]


def test_the_current_addon_version_has_changelog_lines():
    lines = addon_package.changelog_lines((ROOT / "addon" / "CHANGELOG.md").read_text(encoding="utf-8"), repo_version())
    assert lines and all(line.strip() for line in lines)


@pytest.mark.parametrize("current, expected", [("120105", "120105, 16001"), ("120105, 16001", "120105, 16001"),
                                                ("110207,120105", "110207, 120105, 16001")])
def test_the_interface_line_gets_the_number_of_forever_once(current, expected):
    assert addon_package.extended_interface(f"## Interface: {current}\n## Title: X\n") == expected


@pytest.mark.parametrize("text", ["## Title: X\n", "## Interface: abc\n", "## Interface:\n"])
def test_an_unusable_interface_line_stops(text):
    with pytest.raises(addon_package.PackageError):
        addon_package.extended_interface(text)


def test_the_staged_addon_has_the_files_the_extended_toc_and_the_package_files(tmp_path):
    before = TOC.read_text(encoding="utf-8")
    version = addon_package.stage(ROOT, tmp_path)
    assert version == repo_version()
    dest = tmp_path / "StatTracker"
    toc = (dest / "StatTracker.toc").read_text(encoding="utf-8")
    assert "## Interface: 120105, 16001" in toc or addon_package.FOREVER_INTERFACE in addon_package.toc_value(toc, "Interface")
    assert addon_package.toc_value(toc, "X-Curse-Project-ID") == "1810842"
    for lua in (ROOT / "addon" / "StatTracker").glob("*.lua"):
        assert (dest / lua.name).read_bytes() == lua.read_bytes()
    assert (dest / ".pkgmeta").read_text(encoding="utf-8").startswith("package-as: StatTracker\n")
    changelog = (dest / "CHANGELOG.md").read_text(encoding="utf-8")
    assert changelog.startswith(f"# StatTracker {version}\n\n- ") and "Addon" not in changelog.split("\n")[0]
    assert TOC.read_text(encoding="utf-8") == before                    # the .toc in the repository is not touched


def test_the_staging_is_repeatable_and_leaves_nothing_old_behind(tmp_path):
    addon_package.stage(ROOT, tmp_path)
    (tmp_path / "StatTracker" / "old.txt").write_text("x", encoding="utf-8")
    addon_package.stage(ROOT, tmp_path)
    assert not (tmp_path / "StatTracker" / "old.txt").exists()


@pytest.mark.skipif(shutil.which("git") is None, reason="git is needed")
def test_the_staged_folder_is_a_git_checkout_tagged_with_the_version(tmp_path):
    version = addon_package.stage(ROOT, tmp_path)
    dest = tmp_path / "StatTracker"
    addon_package.init_git(dest, version)
    assert (dest / ".git").is_dir()
    git = lambda *a: subprocess.run(["git", "-C", str(dest)] + list(a), capture_output=True, text=True).stdout.strip()
    assert git("tag", "--points-at", "HEAD") == version
    assert git("describe", "--tags", "--abbrev=0") == version
    assert git("status", "--porcelain") == ""                                       # everything is committed
    tracked = git("ls-files").splitlines()
    assert "StatTracker.toc" in tracked and ".pkgmeta" in tracked and "CHANGELOG.md" in tracked


@pytest.mark.skipif(shutil.which("git") is None, reason="git is needed")
def test_the_command_line_makes_the_checkout_too(tmp_path):
    assert addon_package.main(["--out", str(tmp_path)]) == 0
    assert (tmp_path / "StatTracker" / ".git").is_dir()


def test_the_command_line_stops_with_a_wrong_tag_and_writes_nothing(tmp_path, capsys):
    assert addon_package.main(["--out", str(tmp_path), "--tag", "addon-v9.9.9"]) == 1
    assert "tag" in capsys.readouterr().err and not (tmp_path / "StatTracker").exists()
    assert addon_package.main(["--out", str(tmp_path), "--tag", f"addon-v{repo_version()}"]) == 0
    assert (tmp_path / "StatTracker" / "StatTracker.toc").is_file()
