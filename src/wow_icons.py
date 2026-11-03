#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)
# wow_icons.py
# StatTracker - the item icons of the history pages: reads them from the local WoW installation
# (CascLib, local storage only) and keeps them as PNG files in data/icons/ (see wow_install.icons_dir()).
#
# Single owner of that folder: the only writer; stat_history only reads it. The game files are read, never
# changed. No texts: extract() returns what happened and the caller says it in the user's language.
# Fail-soft, the icons are an extra: a missing DLL, an installation that cannot be opened or a file that
# cannot be read ends in IconRun.error, never in an exception, and the slot symbols stay.
#
# Only the local storage functions of CascLib are bound here, the online functions of the library are never
# called and the program makes no network request for the icons (tests/test_wow_icons.py checks the names).
#
# Which icons: the caller names the file data ids it needs (the icon ids of the stored equipment); only those
# that are not in the folder yet are read, and the storage is not even opened if none is missing. A file that
# the installation does not have, or that is not a DXT icon, is remembered together with the game build
# (.unreadable.json) and tried again only when the build changes, so that it does not cost the few seconds
# of opening the storage at every import.

import ctypes
import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

import blp_decode
import casclib_asset
import wow_install

MAX_BLP_BYTES = 1 << 20                  # an icon is a few KB; a bigger file is not one
UNREADABLE_FILE = ".unreadable.json"
PNG_NAME = re.compile(r"(\d+)\.png")
OPEN_BY_FILEID = 3                       # CASC_OPEN_BY_FILEID: the "name" is a file data id
LOCALE_ALL = 0xFFFFFFFF
UNAVAILABLE = (2, 1007, 4350)            # not found, offline (CascLib's own code and the Windows one)
ID_LIMIT = 1 << 32


class IconError(Exception):
    """The icons cannot be read from the installation (DLL, storage or a file)."""


@dataclass
class IconRun:
    written: list = field(default_factory=list)       # ids stored now
    present: int = 0                                  # wanted ids that were in the folder already
    unreadable: list = field(default_factory=list)    # ids found not readable now (remembered for this build)
    skipped: int = 0                                  # wanted ids remembered as not readable for this build
    error: str = None                                 # why the run stopped early; None = it ran through


# ------------------------------------------------------------------ the game files
class GameFilesReader:
    """The local CASC storage of a WoW installation, read with CascLib.dll. One object per run; close() or
    `with`. Raises IconError if the DLL or the storage cannot be opened."""

    def __init__(self, game_dir, product, dll=None):
        if sys.platform != "win32":
            raise IconError("the game files can only be read on Windows")
        dll = Path(dll) if dll else casclib_asset.path()
        if not dll.is_file():
            raise IconError(f"{dll.name} not found at {dll}")
        try:
            lib = ctypes.WinDLL(str(dll))
        except OSError as exc:
            raise IconError(f"{dll.name} cannot be loaded ({exc})") from exc
        handle = ctypes.POINTER(ctypes.c_void_p)
        text = ctypes.c_wchar_p if casclib_asset.UNICODE else ctypes.c_char_p
        try:
            for name, argtypes in {
                "CascOpenStorage": [text, ctypes.c_uint32, handle],
                "CascCloseStorage": [ctypes.c_void_p],
                "CascOpenFile": [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32, handle],
                "CascGetFileSize64": [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulonglong)],
                "CascReadFile": [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32, ctypes.POINTER(ctypes.c_uint32)],
                "CascCloseFile": [ctypes.c_void_p],
            }.items():
                function = getattr(lib, name)
                function.argtypes = argtypes
                function.restype = ctypes.c_bool
            lib.GetCascError.argtypes = []
            lib.GetCascError.restype = ctypes.c_uint32
        except AttributeError as exc:
            raise IconError(f"{dll.name} is not the CascLib the program expects ({exc})") from exc
        self._lib = lib
        self._storage = ctypes.c_void_p()
        target = f"{game_dir}*{product}"          # "<WoW folder>*<product>", e.g. "...\World of Warcraft*wow"
        if not lib.CascOpenStorage(target if casclib_asset.UNICODE else os.fsencode(target), LOCALE_ALL,
                                   ctypes.byref(self._storage)):
            raise IconError(f"the game files in {game_dir} ({product}) cannot be opened "
                            f"(CascLib error {lib.GetCascError()})")

    def read(self, file_id):
        """The bytes of the file with this file data id, or None if the installation has no such file (or it is
        too big to be an icon). Raises IconError for any other failure."""
        lib = self._lib
        handle = ctypes.c_void_p()
        if not lib.CascOpenFile(self._storage, ctypes.c_void_p(file_id), 0, OPEN_BY_FILEID, ctypes.byref(handle)):
            code = lib.GetCascError()
            if code in UNAVAILABLE:
                return None
            raise IconError(f"file {file_id} cannot be opened (CascLib error {code})")
        try:
            size = ctypes.c_ulonglong(0)
            if not lib.CascGetFileSize64(handle, ctypes.byref(size)):
                raise IconError(f"the size of file {file_id} is unknown (CascLib error {lib.GetCascError()})")
            if not 0 < size.value <= MAX_BLP_BYTES:
                return None
            buffer = ctypes.create_string_buffer(size.value)
            done = ctypes.c_uint32(0)
            if not lib.CascReadFile(handle, buffer, size.value, ctypes.byref(done)) or done.value != size.value:
                raise IconError(f"file {file_id} cannot be read (CascLib error {lib.GetCascError()})")
            return buffer.raw
        finally:
            lib.CascCloseFile(handle)

    def close(self):
        if self._storage.value:
            self._lib.CascCloseStorage(self._storage)
            self._storage = ctypes.c_void_p()

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        self.close()


def game_build(game_dir, product):
    """The version of `product` in the .build.info of the WoW folder (e.g. '12.1.5.70688'); None if unknown."""
    return wow_install.parse_build_info(Path(game_dir)).get(product)


# ------------------------------------------------------------------ the folder
def _is_id(value):
    return isinstance(value, int) and not isinstance(value, bool) and 0 < value < ID_LIMIT


def present(icons_dir):
    """The ids that have a PNG in the folder (nothing else in it counts)."""
    try:
        names = os.listdir(icons_dir)
    except OSError:
        return set()
    return {int(m.group(1)) for m in map(PNG_NAME.fullmatch, names) if m}


def known_unreadable(icons_dir, build):
    """The ids remembered as not readable for exactly this game build. Empty if none is remembered, the build
    is another one, it is not known, or the file is damaged."""
    if not build:
        return set()
    try:
        data = json.loads((Path(icons_dir) / UNREADABLE_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    if not isinstance(data, dict) or data.get("build") != build or not isinstance(data.get("ids"), list):
        return set()
    return {i for i in data["ids"] if _is_id(i)}


def _write_atomic(target, write):
    part = target.with_name(target.name + ".part")
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        write(part)
        os.replace(part, target)
    except OSError:
        part.unlink(missing_ok=True)
        raise


def _store(icons_dir, icon_id, png):
    target = Path(icons_dir) / f"{icon_id}.png"
    _write_atomic(target, lambda part: part.write_bytes(png))


def _remember(icons_dir, build, ids):
    target = Path(icons_dir) / UNREADABLE_FILE
    text = json.dumps({"build": build, "ids": sorted(ids)})
    _write_atomic(target, lambda part: part.write_text(text, encoding="utf-8"))


# ------------------------------------------------------------------ the run
def extract(wanted, icons_dir, game_dir, product, open_reader=GameFilesReader):
    """Reads the icons in `wanted` (file data ids) that the folder does not have yet from the installation and
    stores them as PNG. `open_reader(game_dir, product)` gives an object with read(id) and close(); tests give
    their own. Returns an IconRun and never raises for what can go wrong with the installation or the folder."""
    run = IconRun()
    icons_dir = Path(icons_dir)
    ids = sorted({i for i in wanted if _is_id(i)})
    have = present(icons_dir)
    build = game_build(game_dir, product)
    known = known_unreadable(icons_dir, build)
    run.present = sum(1 for i in ids if i in have)
    run.skipped = sum(1 for i in ids if i not in have and i in known)
    missing = [i for i in ids if i not in have and i not in known]
    if not missing:
        return run

    try:
        reader = open_reader(game_dir, product)
    except IconError as exc:
        run.error = str(exc)
        return run
    found_unreadable = set()
    try:
        for icon_id in missing:
            data = reader.read(icon_id)
            png = None
            if data is not None:
                try:
                    png = blp_decode.blp_to_png(data)
                except blp_decode.BlpError:
                    png = None
            if png is None:
                found_unreadable.add(icon_id)
                continue
            _store(icons_dir, icon_id, png)
            run.written.append(icon_id)
    except IconError as exc:
        run.error = str(exc)
    except OSError as exc:
        run.error = f"the icons folder {icons_dir} is not writable ({exc})"
    finally:
        reader.close()

    run.unreadable = sorted(found_unreadable)
    if found_unreadable and build:
        try:
            _remember(icons_dir, build, known | found_unreadable)
        except OSError as exc:
            run.error = run.error or f"the icons folder {icons_dir} is not writable ({exc})"
    return run
