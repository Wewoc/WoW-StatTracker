# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)
# compiler/addon_zip.py: the files of an addon release for the repository StatTracker-Addon. The tag must be addon-v<version of the .toc>, the ZIP holds
# the folder StatTracker/ with the files of addon/StatTracker as they are (no extended interface line), the same files give the same bytes, the
# checksum file is "<hash>  <name>", the notes come from addon/CHANGELOG.md, and nothing is written when anything is wrong.

import hashlib
import importlib.util
import shutil
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("addon_zip", ROOT / "compiler" / "addon_zip.py")
addon_zip = importlib.util.module_from_spec(spec)
spec.loader.exec_module(addon_zip)
SRC = ROOT / "addon" / "StatTracker"
TOC = SRC / "StatTracker.toc"


def repo_version():
    return addon_zip.addon_package.toc_value(TOC.read_text(encoding="utf-8"), "Version")


@pytest.fixture
def tag():
    return f"addon-v{repo_version()}"


def test_the_four_files_are_written_for_the_current_version(tmp_path, tag):
    out = tmp_path / "out"
    assert addon_zip.build(ROOT, out, tag) == repo_version()
    assert sorted(p.name for p in out.iterdir()) == sorted(
        ["StatTracker-addon.zip", "StatTracker-addon.zip.sha256", "release-notes.md", "release-name.txt"])
    assert (out / "release-name.txt").read_text(encoding="utf-8") == f"Addon {repo_version()}\n"


def test_the_zip_holds_the_folder_with_the_files_of_the_addon_exactly_as_they_are(tmp_path, tag):
    addon_zip.build(ROOT, tmp_path, tag)
    with zipfile.ZipFile(tmp_path / "StatTracker-addon.zip") as archive:
        assert archive.testzip() is None
        names = archive.namelist()
        assert names == sorted(names) and all(n.startswith("StatTracker/") for n in names)
        assert all(".." not in n.split("/") and not n.startswith("/") and "\\" not in n for n in names)
        expected = {f"StatTracker/{p.relative_to(SRC).as_posix()}": p for p in SRC.rglob("*")
                    if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc"}
        assert set(names) == set(expected)
        for name, path in expected.items():
            assert archive.read(name) == path.read_bytes(), name
        toc = archive.read("StatTracker/StatTracker.toc").decode("utf-8")
    assert addon_zip.addon_package.FOREVER_INTERFACE not in (addon_zip.addon_package.toc_value(toc, "Interface") or "")
    assert toc == TOC.read_bytes().decode("utf-8")                    # the interface line is the one of the repository (CurseForge extends it, this does not)
    assert "CHANGELOG" not in " ".join(names)                         # the changelog is not part of the installed folder


def test_the_same_files_give_the_same_bytes_and_the_checksum_is_the_one_of_the_zip(tmp_path, tag):
    addon_zip.build(ROOT, tmp_path / "one", tag)
    addon_zip.build(ROOT, tmp_path / "two", tag)
    first = (tmp_path / "one" / "StatTracker-addon.zip").read_bytes()
    assert first == (tmp_path / "two" / "StatTracker-addon.zip").read_bytes()
    line = (tmp_path / "one" / "StatTracker-addon.zip.sha256").read_text(encoding="ascii")
    assert line == f"{hashlib.sha256(first).hexdigest()}  StatTracker-addon.zip\n"
    with zipfile.ZipFile(tmp_path / "one" / "StatTracker-addon.zip") as archive:
        assert {i.date_time for i in archive.infolist()} == {(1980, 1, 1, 0, 0, 0)}


def test_the_notes_are_the_lines_of_the_chapter_and_name_the_source(tmp_path, tag):
    addon_zip.build(ROOT, tmp_path, tag, commit="0123456789abcdef0123456789abcdef01234567")
    notes = (tmp_path / "release-notes.md").read_text(encoding="utf-8")
    lines = addon_zip.addon_package.changelog_lines((ROOT / "addon" / "CHANGELOG.md").read_text(encoding="utf-8"), repo_version())
    assert notes.startswith("".join(f"- {line}\n" for line in lines))
    assert notes.endswith(f"Source: https://github.com/Wewoc/WoW-StatTracker at the tag `{tag}` (commit `0123456789abcdef0123456789abcdef01234567`).\n")
    addon_zip.build(ROOT, tmp_path / "plain", tag)
    assert (tmp_path / "plain" / "release-notes.md").read_text(encoding="utf-8").endswith(f"at the tag `{tag}`.\n")


@pytest.mark.parametrize("bad", ["v0.2.4", "addon-v9.9.9", "addon-0.2.4", "addon-v0.2.4-beta", "addon-v", "addon-v1", "ADDON-V0.2.4", "",
                                 "addon-v0.2.4\nmore", "../addon-v0.2.4", "addon-v0.2.4 ", "refs/tags/addon-v0.2.4", "main"])
def test_a_wrong_tag_stops_and_writes_nothing(tmp_path, bad):
    with pytest.raises(addon_zip.ZipError):
        addon_zip.build(ROOT, tmp_path / "out", bad)
    assert not (tmp_path / "out").exists()


@pytest.mark.parametrize("bad", ["", "xyz", "012345", "ABCDEF1234", "abc", "0123456789abcdef0123456789abcdef012345678", "main; rm -rf /"])
def test_a_wrong_commit_stops_and_writes_nothing(tmp_path, tag, bad):
    with pytest.raises(addon_zip.ZipError):
        addon_zip.build(ROOT, tmp_path / "out", tag, commit=bad)
    assert not (tmp_path / "out").exists()


def copy_repo(tmp_path):
    root = tmp_path / "repo"
    shutil.copytree(ROOT / "addon", root / "addon")
    return root


def test_a_version_without_a_changelog_chapter_stops_and_writes_nothing(tmp_path):
    root = copy_repo(tmp_path)
    toc = root / "addon" / "StatTracker" / "StatTracker.toc"
    toc.write_text(toc.read_text(encoding="utf-8").replace(f"## Version: {repo_version()}", "## Version: 9.9.9"), encoding="utf-8")
    with pytest.raises(addon_zip.ZipError, match="9.9.9"):
        addon_zip.build(root, tmp_path / "out", "addon-v9.9.9")
    assert not (tmp_path / "out").exists()


def test_a_missing_changelog_or_toc_stops_and_writes_nothing(tmp_path, tag):
    root = copy_repo(tmp_path)
    (root / "addon" / "CHANGELOG.md").unlink()
    with pytest.raises(addon_zip.ZipError):
        addon_zip.build(root, tmp_path / "out", tag)
    with pytest.raises(addon_zip.ZipError):
        addon_zip.build(tmp_path / "nowhere", tmp_path / "out", tag)
    assert not (tmp_path / "out").exists()


def test_caches_are_left_out_and_a_toc_with_a_byte_order_mark_is_read(tmp_path, tag):
    root = copy_repo(tmp_path)
    cache = root / "addon" / "StatTracker" / "__pycache__"
    cache.mkdir()
    (cache / "x.cpython-313.pyc").write_bytes(b"x")
    (root / "addon" / "StatTracker" / "stray.pyc").write_bytes(b"x")
    toc = root / "addon" / "StatTracker" / "StatTracker.toc"
    toc.write_bytes(b"\xef\xbb\xbf" + toc.read_bytes())
    addon_zip.build(root, tmp_path / "out", tag)
    with zipfile.ZipFile(tmp_path / "out" / "StatTracker-addon.zip") as archive:
        assert not [n for n in archive.namelist() if "pycache" in n or n.endswith(".pyc")]
        assert archive.read("StatTracker/StatTracker.toc").startswith(b"\xef\xbb\xbf")     # the file goes in as it is


def test_the_command_line_writes_the_files_or_stops_with_a_message(tmp_path, tag, capsys):
    assert addon_zip.main(["--out", str(tmp_path / "ok"), "--tag", tag, "--commit", "abcdef1"]) == 0
    assert (tmp_path / "ok" / "StatTracker-addon.zip").is_file()
    assert addon_zip.main(["--out", str(tmp_path / "bad"), "--tag", "addon-v9.9.9"]) == 1
    assert "tag" in capsys.readouterr().err and not (tmp_path / "bad").exists()
    with pytest.raises(SystemExit):                                   # the tag is required: no guessing it from the .toc
        addon_zip.main(["--out", str(tmp_path / "none")])
