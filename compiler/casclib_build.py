#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)
# compiler/casclib_build.py
# Builds the pinned CascLib (see src/casclib_asset.py) into src/CascLib.dll.
#
# Build and CI only - the program never builds or downloads it. The source comes from GitHub over
# https with git, at the pinned commit; the commit is checked before anything is built. A DLL that is
# already in place and passes the checks (x64, every export the program calls) is left alone. The
# build needs git, CMake and a C++ compiler (Visual Studio Build Tools); without them the script says
# so and fails, and compiler/build.py then builds without icons unless --require-casclib is given.
#
#     python compiler/casclib_build.py

import argparse
import os
import shutil
import struct
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import casclib_asset  # noqa: E402

WORK_DIR = ROOT / "build" / "casclib"
MACHINE_X64 = 0x8664
PE32_PLUS = 0x20B
OUTPUT_TAIL_LINES = 40


class CasclibBuildError(Exception):
    """The DLL could not be built, or what is there is not the DLL the program needs."""


# ------------------------------------------------------------------ reading a DLL
def pe_exports(data):
    """(machine, [exported names]) of a PE file given as bytes. Raises CasclibBuildError."""
    try:
        if data[:2] != b"MZ":
            raise CasclibBuildError("not a Windows executable (no MZ header)")
        pe = struct.unpack_from("<I", data, 0x3C)[0]
        if data[pe:pe + 4] != b"PE\0\0":
            raise CasclibBuildError("not a Windows executable (no PE signature)")
        machine, sections, _stamp, _symbols, _count, optional_size, _flags = struct.unpack_from("<HHIIIHH", data, pe + 4)
        optional = pe + 24
        magic = struct.unpack_from("<H", data, optional)[0]
        directories = optional + (112 if magic == PE32_PLUS else 96)
        export_rva, export_size = struct.unpack_from("<II", data, directories)
        table = optional + optional_size
        spans = []
        for n in range(sections):
            _name, size, rva, raw_size, raw_ptr = struct.unpack_from("<8sIIII", data, table + 40 * n)
            spans.append((rva, max(size, raw_size), raw_ptr))

        def offset(rva):
            for start, length, raw in spans:
                if start <= rva < start + length:
                    return raw + rva - start
            raise CasclibBuildError("export table points outside every section")

        if not export_rva or not export_size:
            return machine, []
        (_c, _t, _maj, _min, _name_rva, _base, _functions, name_count, _addr, names_rva, _ords) = \
            struct.unpack_from("<IIHHIIIIIII", data, offset(export_rva))
        names = []
        for n in range(name_count):
            start = offset(struct.unpack_from("<I", data, offset(names_rva) + 4 * n)[0])
            names.append(data[start:data.index(b"\0", start)].decode("ascii"))
        return machine, names
    except (struct.error, ValueError, UnicodeDecodeError) as exc:
        raise CasclibBuildError(f"damaged or unreadable Windows executable ({exc})") from exc


def check_dll(dll):
    """Raises CasclibBuildError unless `dll` is an x64 DLL that exports everything the program calls."""
    try:
        data = Path(dll).read_bytes()
    except OSError as exc:
        raise CasclibBuildError(f"{dll} cannot be read ({exc})") from exc
    machine, names = pe_exports(data)
    if machine != MACHINE_X64:
        raise CasclibBuildError(f"{dll} is not an x64 build (machine {machine:#06x})")
    missing = [name for name in casclib_asset.EXPORTS if name not in names]
    if missing:
        raise CasclibBuildError(f"{dll} lacks the exports {', '.join(missing)}")


# ---------------------------------------------------------------------- building
def _run(args):
    """Runs a command and returns its output. Raises CasclibBuildError with the end of the output."""
    command = [str(a) for a in args]
    try:
        proc = subprocess.run(command, capture_output=True, text=True)
    except OSError as exc:
        raise CasclibBuildError(f"{command[0]} could not be started ({exc})") from exc
    if proc.returncode != 0:
        tail = "\n".join((proc.stdout + proc.stderr).strip().splitlines()[-OUTPUT_TAIL_LINES:])
        raise CasclibBuildError(f"{' '.join(command[:3])} failed (exit code {proc.returncode}):\n{tail}")
    return proc.stdout


def _valid(dest):
    try:
        check_dll(dest)
        return True
    except CasclibBuildError:
        return False


def ensure(dest=None, work=None, run=_run, which=shutil.which):
    """Makes sure `dest` holds the pinned CascLib. Returns True if it was built, False if a correct file
    was already there. Raises CasclibBuildError (a file that is there stays untouched on a failure)."""
    dest = Path(dest) if dest else casclib_asset.path()
    if _valid(dest):
        return False
    tools = {name: which(name) for name in ("git", "cmake")}
    missing = [name for name, found in tools.items() if not found]
    if missing:
        raise CasclibBuildError(
            f"{' and '.join(missing)} not found on PATH. Building CascLib needs git, CMake and the Visual Studio "
            f"Build Tools (C++ workload); CI has them. A CascLib.dll copied to {dest} works as well.")

    work = Path(work) if work else WORK_DIR
    source, output = work / "src", work / "out"
    shutil.rmtree(work, ignore_errors=True)
    source.mkdir(parents=True)
    git = tools["git"]
    run([git, "init", "--quiet", source])
    run([git, "-C", source, "remote", "add", "origin", casclib_asset.REPO_URL])
    run([git, "-C", source, "fetch", "--quiet", "--depth", "1", "origin", casclib_asset.COMMIT])
    run([git, "-C", source, "checkout", "--quiet", "FETCH_HEAD"])
    head = run([git, "-C", source, "rev-parse", "HEAD"]).strip()
    if head != casclib_asset.COMMIT:
        raise CasclibBuildError(f"fetched commit {head} is not the pinned {casclib_asset.COMMIT}")

    # CMake 4 rejects the "cmake_minimum_required(VERSION 3.2)" of CascLib without the policy minimum.
    # Every argument is its own list item: through a shell, -DNAME=3.5 would be split at the dot.
    run([tools["cmake"], "-S", source, "-B", output, "-A", "x64", "-DCMAKE_POLICY_VERSION_MINIMUM=3.5",
         "-DCASC_BUILD_SHARED_LIB=ON", "-DCASC_BUILD_STATIC_LIB=OFF",
         f"-DCASC_UNICODE={'ON' if casclib_asset.UNICODE else 'OFF'}"])
    run([tools["cmake"], "--build", output, "--config", "Release"])

    built = sorted(output.rglob(casclib_asset.FILENAME))
    if len(built) != 1:
        raise CasclibBuildError(f"expected one {casclib_asset.FILENAME} under {output}, found {len(built)}")
    check_dll(built[0])

    part = dest.with_name(dest.name + ".part")
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(built[0], part)
        os.replace(part, dest)
    except OSError as exc:
        part.unlink(missing_ok=True)
        raise CasclibBuildError(f"Could not write {dest}: {exc}") from exc
    return True


def main():
    argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter).parse_args()
    try:
        built = ensure()
    except CasclibBuildError as exc:
        print(f"  [casclib] {exc}")
        raise SystemExit(1)
    word = "built and verified" if built else "present and verified"
    print(f"  [casclib] CascLib {casclib_asset.VERSION} {word}: {casclib_asset.path()}")


if __name__ == "__main__":
    main()
