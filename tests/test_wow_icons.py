# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)
# Reading the item icons from a WoW installation and keeping them in data/icons/ (wow_icons). The game files
# are replaced by an object that hands out BLP bytes: no test needs a game, a DLL (except the few that say so)
# or the network.

import json
import os
import re
import struct
import sys
from pathlib import Path

import pytest

from game import blp_decode
from game import casclib_asset
from game import wow_icons
from game import wow_install
from game.wow_icons import IconError

ROOT = Path(__file__).resolve().parent.parent
REAL_DLL = ROOT / "src" / casclib_asset.FILENAME
BUILD = "12.1.5.70575"           # the version in the .build.info of the fake WoW folder, product "wow"
needs_windows = pytest.mark.skipif(sys.platform != "win32", reason="CascLib.dll is a Windows library")


def icon_blp(color=0xF800):
    """A 4 x 4 BLP2 icon (one DXT1 block of one color), the smallest file the decoder accepts."""
    block = struct.pack("<HHI", color, color, 0)
    header = blp_decode.HEADER.pack(b"BLP2", 1, 2, 0, 0, 1, 4, 4)
    tables = struct.pack("<16I", 0x494, *([0] * 15)) + struct.pack("<16I", len(block), *([0] * 15))
    return header + tables + bytes(1024) + block


def icon_png(color=0xF800):
    return blp_decode.blp_to_png(icon_blp(color))


class FakeReader:
    """Stands in for the game files: id -> BLP bytes, a missing id is a file the installation does not have."""

    def __init__(self, files, fail_on=None):
        self.files, self.fail_on, self.reads, self.closed = files, fail_on, [], False

    def read(self, file_id):
        self.reads.append(file_id)
        if file_id == self.fail_on:
            raise IconError("the storage went away")
        return self.files.get(file_id)

    def close(self):
        self.closed = True


class Opener:
    """open_reader for extract(): hands out one reader and remembers how it was asked."""

    def __init__(self, reader=None, error=None):
        self.reader, self.error, self.calls = reader, error, []

    def __call__(self, game_dir, product):
        self.calls.append((Path(game_dir), product))
        if self.error:
            raise IconError(self.error)
        return self.reader


@pytest.fixture
def icons(tmp_path):
    return tmp_path / "icons"


def run(wanted, icons_dir, game_dir, opener, product="wow"):
    return wow_icons.extract(wanted, icons_dir, game_dir, product, open_reader=opener)


# ------------------------------------------------------------------ what gets stored
def test_the_missing_icons_are_read_converted_and_stored_as_png(fake_wow, icons):
    reader = FakeReader({10: icon_blp(0xF800), 20: icon_blp(0x07E0)})
    result = run([20, 10], icons, fake_wow, Opener(reader))
    assert result.written == [10, 20] and result.error is None and result.unreadable == []
    assert (icons / "10.png").read_bytes() == icon_png(0xF800)
    assert (icons / "20.png").read_bytes() == icon_png(0x07E0)
    assert reader.closed
    assert not list(icons.glob("*.part"))


def test_the_installation_is_asked_with_the_folder_and_the_product(fake_wow, icons):
    opener = Opener(FakeReader({1: icon_blp()}))
    run([1], icons, fake_wow, opener, product="wow")
    assert opener.calls == [(fake_wow, "wow")]


def test_an_icon_that_is_already_there_is_not_read_again(fake_wow, icons):
    icons.mkdir()
    (icons / "10.png").write_bytes(b"png of an earlier run")
    reader = FakeReader({10: icon_blp(), 20: icon_blp()})
    result = run([10, 20], icons, fake_wow, Opener(reader))
    assert reader.reads == [20] and result.written == [20] and result.present == 1
    assert (icons / "10.png").read_bytes() == b"png of an earlier run"


def test_the_storage_is_not_opened_when_nothing_is_missing(fake_wow, icons):
    icons.mkdir()
    (icons / "10.png").write_bytes(b"x")
    opener = Opener(FakeReader({}))
    result = run([10], icons, fake_wow, opener)
    assert opener.calls == [] and result.written == [] and result.present == 1
    assert run([], icons, fake_wow, opener).present == 0 and opener.calls == []


def test_only_real_file_data_ids_are_asked_for_and_each_once(fake_wow, icons):
    reader = FakeReader({5: icon_blp()})
    run([5, 5, 0, -3, True, "7", 2.5, None, 1 << 32], icons, fake_wow, Opener(reader))
    assert reader.reads == [5]


def test_only_png_files_named_by_their_id_count_as_icons_in_the_folder(icons):
    icons.mkdir()
    for name in ("12.png", "345.png", "345.png.part", ".unreadable.json", "abc.png", "12.jpg", "-1.png"):
        (icons / name).write_bytes(b"x")
    assert wow_icons.present(icons) == {12, 345}
    assert wow_icons.present(icons / "no-such-folder") == set()


# ------------------------------------------------------------ what cannot be read
def test_a_file_the_installation_does_not_have_is_remembered_with_the_build(fake_wow, icons):
    reader = FakeReader({1: icon_blp()})
    result = run([1, 2], icons, fake_wow, Opener(reader))
    assert result.written == [1] and result.unreadable == [2] and result.error is None
    assert json.loads((icons / ".unreadable.json").read_text(encoding="utf-8")) == {"build": BUILD, "ids": [2]}


def test_a_file_that_is_not_a_dxt_icon_is_remembered_too(fake_wow, icons):
    palette_blp = bytearray(icon_blp())
    palette_blp[8] = 1                                     # encoding 1: palette, not DXT
    result = run([3], icons, fake_wow, Opener(FakeReader({3: bytes(palette_blp)})))
    assert result.written == [] and result.unreadable == [3] and not (icons / "3.png").exists()


def test_a_remembered_file_is_not_tried_again_for_the_same_build(fake_wow, icons):
    run([2], icons, fake_wow, Opener(FakeReader({})))
    opener = Opener(FakeReader({2: icon_blp()}))
    result = run([2], icons, fake_wow, opener)
    assert opener.calls == [] and result.skipped == 1 and result.written == []


def test_a_new_game_build_tries_the_remembered_files_again(fake_wow, icons):
    run([2], icons, fake_wow, Opener(FakeReader({})))
    (fake_wow / ".build.info").write_text(
        "Branch!STRING:0|Active!DEC:1|Product!STRING:0|Version!STRING:0\neu|1|wow|12.1.5.99999\n", encoding="utf-8")
    reader = FakeReader({2: icon_blp()})
    result = run([2], icons, fake_wow, Opener(reader))
    assert reader.reads == [2] and result.written == [2] and result.skipped == 0


def test_the_memory_keeps_the_ids_of_earlier_runs_of_the_same_build(fake_wow, icons):
    run([2], icons, fake_wow, Opener(FakeReader({})))
    run([2, 4], icons, fake_wow, Opener(FakeReader({})))
    assert json.loads((icons / ".unreadable.json").read_text(encoding="utf-8"))["ids"] == [2, 4]


def test_without_a_known_build_nothing_is_remembered(tmp_path, icons):
    no_build_info = tmp_path / "empty wow folder"
    no_build_info.mkdir()
    reader = FakeReader({})
    result = run([2], icons, no_build_info, Opener(reader))
    assert result.unreadable == [2] and not (icons / ".unreadable.json").exists()
    assert run([2], icons, no_build_info, Opener(FakeReader({}))).skipped == 0


@pytest.mark.parametrize("content", ["not json", "[1, 2]", '{"build": "12.1.5.70575", "ids": "x"}', ""])
def test_a_damaged_memory_file_counts_as_empty(fake_wow, icons, content):
    icons.mkdir()
    (icons / ".unreadable.json").write_text(content, encoding="utf-8")
    assert wow_icons.known_unreadable(icons, BUILD) == set()
    assert run([2], icons, fake_wow, Opener(FakeReader({2: icon_blp()}))).written == [2]


def test_the_memory_ignores_entries_that_are_not_ids(icons):
    icons.mkdir()
    (icons / ".unreadable.json").write_text(json.dumps({"build": BUILD, "ids": [5, "x", True, -1, None, 7]}), encoding="utf-8")
    assert wow_icons.known_unreadable(icons, BUILD) == {5, 7}


# ----------------------------------------------------------------- what goes wrong
def test_an_installation_that_cannot_be_opened_is_a_message_not_an_exception(fake_wow, icons):
    result = run([1, 2], icons, fake_wow, Opener(error="the game files cannot be opened"))
    assert result.error == "the game files cannot be opened" and result.written == []
    assert not icons.exists()


def test_a_failing_read_stops_the_run_but_keeps_what_was_stored(fake_wow, icons):
    reader = FakeReader({1: icon_blp(), 2: icon_blp(), 3: icon_blp()}, fail_on=2)
    result = run([1, 2, 3], icons, fake_wow, Opener(reader))
    assert result.written == [1] and result.error == "the storage went away"
    assert reader.reads == [1, 2] and reader.closed
    assert (icons / "1.png").is_file() and not list(icons.glob("*.part"))


def test_an_icons_folder_that_cannot_be_written_is_a_message(fake_wow, tmp_path):
    blocker = tmp_path / "blocker"
    blocker.write_text("a file where the folder should be", encoding="utf-8")
    reader = FakeReader({1: icon_blp()})
    result = run([1], blocker / "icons", fake_wow, Opener(reader))
    assert result.error and "not writable" in result.error and result.written == []
    assert reader.closed


def test_the_files_written_by_a_run_leave_no_partial_file_behind(fake_wow, icons, monkeypatch):
    def failing_replace(_source, _target):
        raise OSError("disk full")
    monkeypatch.setattr(wow_icons.os, "replace", failing_replace)
    result = run([1], icons, fake_wow, Opener(FakeReader({1: icon_blp()})))
    assert result.error and not list(icons.glob("*.part")) and not (icons / "1.png").exists()


# ---------------------------------------------------------------- build and folders
def test_the_game_build_comes_from_the_build_info(fake_wow, tmp_path):
    assert wow_icons.game_build(fake_wow, "wow") == BUILD
    assert wow_icons.game_build(fake_wow, "wowf") == "1.600.1.1234"
    assert wow_icons.game_build(fake_wow, "no_such_product") is None
    assert wow_icons.game_build(tmp_path / "nowhere", "wow") is None


def test_the_icons_folder_per_game_version(instance):
    data = instance / "data"
    assert wow_install.icons_dir("_retail_") == data / "icons"
    assert wow_install.icons_dir("_forever_") == data / "icons_forever"
    assert wow_install.icons_dir("_anniversary_").parent == data


# ----------------------------------------------------------- the rule: no network
def test_only_the_local_storage_functions_of_the_library_are_named():
    """The library also has an online storage and a CDN download. The program never calls them: every
    CascLib function this module names is one of casclib_asset.EXPORTS."""
    source = (ROOT / "src" / "game" / "wow_icons.py").read_text(encoding="utf-8")
    named = set(re.findall(r"\b(?:Casc(?:Open|Close|Get|Read|Set|Find|Add|Import|Cdn)\w*|GetCascError|SetCascError)\b", source))
    assert named and named <= set(casclib_asset.EXPORTS), sorted(named - set(casclib_asset.EXPORTS))


def test_the_module_opens_no_network_connection():
    source = (ROOT / "src" / "game" / "wow_icons.py").read_text(encoding="utf-8")
    for word in ("socket", "urllib", "http", "requests", "ssl"):
        assert not re.search(rf"^\s*(?:import|from)\s+{word}\b", source, re.MULTILINE), word


# --------------------------------------------------- the DLL (Windows; some need the built file)
@needs_windows
def test_a_missing_dll_is_an_icon_error(tmp_path):
    with pytest.raises(IconError, match="not found"):
        wow_icons.GameFilesReader(tmp_path, "wow", dll=tmp_path / "CascLib.dll")


@needs_windows
def test_a_file_that_is_not_a_dll_is_an_icon_error(tmp_path):
    fake = tmp_path / "CascLib.dll"
    fake.write_bytes(b"this is not a library")
    with pytest.raises(IconError, match="cannot be loaded"):
        wow_icons.GameFilesReader(tmp_path, "wow", dll=fake)


@needs_windows
def test_a_dll_without_the_functions_is_an_icon_error(tmp_path):
    other = Path(os.environ["SystemRoot"]) / "System32" / "version.dll"
    with pytest.raises(IconError, match="not the CascLib"):
        wow_icons.GameFilesReader(tmp_path, "wow", dll=other)


@needs_windows
@pytest.mark.skipif(not REAL_DLL.is_file(), reason="src/CascLib.dll is not built: python compiler/casclib_build.py")
def test_a_folder_without_a_game_is_an_icon_error_with_the_real_dll(tmp_path):
    with pytest.raises(IconError, match="cannot be opened"):
        wow_icons.GameFilesReader(tmp_path, "wow", dll=REAL_DLL)
    result = wow_icons.extract([1], tmp_path / "icons", tmp_path, "wow")      # the default reader, the pinned DLL path
    assert result.written == [] and result.error
