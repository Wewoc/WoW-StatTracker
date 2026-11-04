# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)
# Building the pinned CascLib (compiler/casclib_build.py). No test starts git, CMake or a compiler: the
# commands are replaced by a function that records them. The reading of a DLL is tested on a PE image
# made here, and on the real DLL when one is in src/ (CI builds it before the tests).

import struct
import sys
from pathlib import Path

import pytest

import casclib_asset
import casclib_build
from casclib_build import CasclibBuildError

ROOT = Path(__file__).resolve().parent.parent
REAL_DLL = ROOT / "src" / casclib_asset.FILENAME
ALL_EXPORTS = list(casclib_asset.EXPORTS) + ["CascFindFirstFile", "CascCdnDownload"]


def make_pe(names, machine=0x8664):
    """A minimal PE32+ image with one section that holds an export table naming `names`."""
    section_rva, raw_ptr, count = 0x1000, 0x400, len(names)
    funcs = section_rva + 40
    names_at = funcs + 4 * count
    ordinals = names_at + 4 * count
    strings = ordinals + 2 * count
    blob, pointers, cursor = b"", [], strings
    for name in names:
        pointers.append(cursor)
        encoded = name.encode("ascii") + b"\0"
        blob += encoded
        cursor += len(encoded)
    export = struct.pack("<IIHHIIIIIII", 0, 0, 0, 0, strings, 1, count, count, funcs, names_at, ordinals)
    export += b"".join(struct.pack("<I", 0x2000) for _ in names)
    export += b"".join(struct.pack("<I", p) for p in pointers)
    export += b"".join(struct.pack("<H", i) for i in range(count))
    export += blob
    optional = bytearray(112 + 16 * 8)
    struct.pack_into("<H", optional, 0, 0x20B)
    struct.pack_into("<II", optional, 112, section_rva, len(export))
    headers = (b"PE\0\0" + struct.pack("<HHIIIHH", machine, 1, 0, 0, 0, len(optional), 0x2000) + bytes(optional)
               + struct.pack("<8sIIIIIIHHI", b".edata", len(export), section_rva, len(export), raw_ptr, 0, 0, 0, 0, 0))
    image = bytearray(raw_ptr)
    image[0:2] = b"MZ"
    struct.pack_into("<I", image, 0x3C, 0x40)
    image[0x40:0x40 + len(headers)] = headers
    return bytes(image) + export


# ------------------------------------------------------------------ reading a DLL
def test_the_exports_and_the_machine_of_a_pe_image_are_read():
    machine, names = casclib_build.pe_exports(make_pe(["Alpha", "Beta", "GetCascError"]))
    assert machine == 0x8664 and names == ["Alpha", "Beta", "GetCascError"]


def test_an_image_without_exports_has_an_empty_list():
    assert casclib_build.pe_exports(make_pe([]))[1] == []


@pytest.mark.parametrize("data", [b"", b"MZ", b"not a dll at all" * 20, b"MZ" + bytes(0x3A) + b"\xf0\xff\xff\x7f" + bytes(40)])
def test_what_is_not_a_pe_image_is_refused(data):
    with pytest.raises(CasclibBuildError):
        casclib_build.pe_exports(data)


def test_a_truncated_image_is_refused():
    with pytest.raises(CasclibBuildError):
        casclib_build.pe_exports(make_pe(["Alpha", "Beta"])[:0x400 + 50])


def test_a_dll_with_every_export_the_program_calls_passes(tmp_path):
    dll = tmp_path / "CascLib.dll"
    dll.write_bytes(make_pe(ALL_EXPORTS))
    casclib_build.check_dll(dll)


def test_a_dll_that_lacks_an_export_is_named_in_the_error(tmp_path):
    dll = tmp_path / "CascLib.dll"
    dll.write_bytes(make_pe([n for n in ALL_EXPORTS if n != "CascReadFile"]))
    with pytest.raises(CasclibBuildError, match="CascReadFile"):
        casclib_build.check_dll(dll)


def test_a_32_bit_dll_is_refused(tmp_path):
    dll = tmp_path / "CascLib.dll"
    dll.write_bytes(make_pe(ALL_EXPORTS, machine=0x14C))
    with pytest.raises(CasclibBuildError, match="x64"):
        casclib_build.check_dll(dll)


def test_a_missing_dll_is_an_error_not_an_exception_of_another_kind(tmp_path):
    with pytest.raises(CasclibBuildError):
        casclib_build.check_dll(tmp_path / "absent.dll")


@pytest.mark.skipif(not REAL_DLL.is_file(), reason="src/CascLib.dll is not built: python compiler/casclib_build.py")
def test_the_real_dll_passes_the_check_and_loads():
    casclib_build.check_dll(REAL_DLL)
    if sys.platform != "win32":
        pytest.skip("the DLL loads on Windows only")
    import ctypes
    library = ctypes.WinDLL(str(REAL_DLL))
    for name in casclib_asset.EXPORTS:
        assert getattr(library, name)
    library.GetCascError.restype = ctypes.c_uint32
    assert isinstance(library.GetCascError(), int)


# ---------------------------------------------------------------------- building
class Recorder:
    """Stands in for git and CMake: records every command, answers `rev-parse`, and lets the build
    command put a DLL where CMake would."""

    def __init__(self, head=casclib_asset.COMMIT, dll=b"built dll", fail_on=None, build_dll=True):
        self.calls, self.head, self.dll, self.fail_on, self.build_dll = [], head, dll, fail_on, build_dll

    def __call__(self, args):
        command = [str(a) for a in args]
        self.calls.append(command)
        if self.fail_on and self.fail_on in command:
            raise CasclibBuildError(f"{self.fail_on} failed")
        if "rev-parse" in command:
            return self.head + "\n"
        if "--build" in command and self.build_dll:
            target = Path(command[command.index("--build") + 1]) / "Release" / casclib_asset.FILENAME
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(self.dll)
        return ""


@pytest.fixture
def tools():
    return lambda name: f"C:/tools/{name}.exe"


@pytest.fixture
def accept_dlls(monkeypatch):
    """The checks of a built file are tested above; here every non-empty file passes."""
    def fake_check(path):
        try:
            content = Path(path).read_bytes()
        except OSError as exc:
            raise CasclibBuildError(f"{path} cannot be read") from exc
        if not content:
            raise CasclibBuildError("empty")
    monkeypatch.setattr(casclib_build, "check_dll", fake_check)


def test_a_correct_dll_that_is_there_is_left_alone(tmp_path, tools, accept_dlls):
    dest = tmp_path / "CascLib.dll"
    dest.write_bytes(b"already there")
    run = Recorder()
    assert casclib_build.ensure(dest, tmp_path / "work", run=run, which=tools) is False
    assert run.calls == [] and dest.read_bytes() == b"already there"


def test_the_pinned_commit_is_fetched_over_https_and_built_as_x64_release(tmp_path, tools, accept_dlls):
    dest, run = tmp_path / "CascLib.dll", Recorder()
    assert casclib_build.ensure(dest, tmp_path / "work", run=run, which=tools) is True
    assert dest.read_bytes() == b"built dll" and not dest.with_name("CascLib.dll.part").exists()

    fetch = next(c for c in run.calls if "fetch" in c)
    assert fetch[-2:] == ["origin", casclib_asset.COMMIT] and "--depth" in fetch
    remote = next(c for c in run.calls if "remote" in c)
    assert remote[-1] == casclib_asset.REPO_URL and remote[-1].startswith("https://")

    configure = next(c for c in run.calls if "-S" in c)
    # each option is one list item: through a shell, -DNAME=3.5 is split at the dot (PowerShell)
    assert "-DCMAKE_POLICY_VERSION_MINIMUM=3.5" in configure
    assert configure[configure.index("-A") + 1] == "x64"
    assert "-DCASC_BUILD_SHARED_LIB=ON" in configure and "-DCASC_BUILD_STATIC_LIB=OFF" in configure
    assert f"-DCASC_UNICODE={'ON' if casclib_asset.UNICODE else 'OFF'}" in configure
    build = next(c for c in run.calls if "--build" in c)
    assert build[build.index("--config") + 1] == "Release"


def test_a_wrong_commit_stops_the_build_before_cmake_runs(tmp_path, tools, accept_dlls):
    dest, run = tmp_path / "CascLib.dll", Recorder(head="0" * 40)
    with pytest.raises(CasclibBuildError, match="pinned"):
        casclib_build.ensure(dest, tmp_path / "work", run=run, which=tools)
    assert not any("-S" in c for c in run.calls) and not dest.exists()


@pytest.mark.parametrize("failing", ["fetch", "--build"])
def test_a_failing_command_leaves_no_dll_behind(tmp_path, tools, accept_dlls, failing):
    dest, run = tmp_path / "CascLib.dll", Recorder(fail_on=failing)
    with pytest.raises(CasclibBuildError):
        casclib_build.ensure(dest, tmp_path / "work", run=run, which=tools)
    assert not dest.exists() and not dest.with_name("CascLib.dll.part").exists()


def test_a_build_that_produces_no_dll_is_an_error(tmp_path, tools, accept_dlls):
    with pytest.raises(CasclibBuildError, match="found 0"):
        casclib_build.ensure(tmp_path / "CascLib.dll", tmp_path / "work", run=Recorder(build_dll=False), which=tools)


def test_a_dll_that_fails_the_check_is_not_installed(tmp_path, tools, accept_dlls):
    dest = tmp_path / "CascLib.dll"
    with pytest.raises(CasclibBuildError, match="empty"):
        casclib_build.ensure(dest, tmp_path / "work", run=Recorder(dll=b""), which=tools)
    assert not dest.exists()


def test_a_damaged_dll_that_is_there_is_replaced(tmp_path, tools, accept_dlls):
    dest = tmp_path / "CascLib.dll"
    dest.write_bytes(b"")
    assert casclib_build.ensure(dest, tmp_path / "work", run=Recorder(), which=tools) is True
    assert dest.read_bytes() == b"built dll"


@pytest.mark.parametrize("absent", ["git", "cmake"])
def test_missing_tools_are_named_and_nothing_is_run(tmp_path, accept_dlls, absent):
    run = Recorder()
    with pytest.raises(CasclibBuildError, match=absent):
        casclib_build.ensure(tmp_path / "CascLib.dll", tmp_path / "work", run=run,
                             which=lambda name: None if name == absent else f"C:/tools/{name}.exe")
    assert run.calls == []


def test_a_command_that_cannot_start_is_an_error_of_the_build(tmp_path):
    with pytest.raises(CasclibBuildError):
        casclib_build._run([tmp_path / "no-such-program.exe"])
