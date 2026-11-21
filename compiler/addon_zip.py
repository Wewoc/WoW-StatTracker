#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)
"""Builds the files of an addon release for the repository StatTracker-Addon (the workflow there runs this on a checkout of this repository at the tag).

    python compiler/addon_zip.py --out dist --tag addon-v0.2.5 [--commit <sha>]

- the tag must be addon-v<version of the .toc> (and nothing but digits and dots after "addon-v");
- <out>/StatTracker-addon.zip: one folder StatTracker/ with the content of addon/StatTracker exactly as in the repository (the interface line
  of the .toc is NOT extended: that is only done for CurseForge, see addon_package.py; the program sets the number of the installed copy itself);
  the same files give the same bytes (sorted entries, fixed time stamps), so the checksum can be checked again by anyone;
- <out>/StatTracker-addon.zip.sha256 ("<hash>  <name>"), <out>/release-notes.md (the lines of the chapter of the version in addon/CHANGELOG.md
  and a line with the source: this repository, the tag and the commit) and <out>/release-name.txt;
- nothing is written when anything is wrong (tag, version, changelog chapter, commit).
Standard library only (plus addon_package.py of this folder); it does not import the product code and it never uploads anything.
"""
import argparse
import hashlib
import io
import re
import sys
import zipfile
from pathlib import Path

import addon_package

ROOT = Path(__file__).resolve().parent.parent
ADDON_NAME = addon_package.ADDON_NAME
ZIP_NAME = "StatTracker-addon.zip"
CHECKSUM_NAME = ZIP_NAME + ".sha256"
NOTES_NAME = "release-notes.md"
RELEASE_NAME_FILE = "release-name.txt"
SOURCE_URL = "https://github.com/Wewoc/WoW-StatTracker"
TAG_RE = re.compile(r"addon-v\d+(?:\.\d+)+")
COMMIT_RE = re.compile(r"[0-9a-f]{7,40}")
ZIP_TIME = (1980, 1, 1, 0, 0, 0)        # the earliest time a ZIP can hold: the same files give the same bytes


class ZipError(Exception):
    pass


def addon_files(src):
    """The files of the addon folder as (name in the ZIP, path), sorted; no __pycache__, no .pyc."""
    found = []
    for path in sorted(Path(src).rglob("*")):
        rel = path.relative_to(src)
        if not path.is_file() or "__pycache__" in rel.parts or path.suffix == ".pyc":
            continue
        found.append((f"{ADDON_NAME}/{rel.as_posix()}", path))
    return found


def make_zip(src):
    """The bytes of the ZIP: the folder StatTracker/ with the files of `src`, reproducible."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, path in addon_files(src):
            info = zipfile.ZipInfo(name, date_time=ZIP_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            info.create_system = 3                                  # Unix: the same value on every machine
            archive.writestr(info, path.read_bytes(), compresslevel=9)
    return buffer.getvalue()


def release_notes(lines, tag, commit=None):
    """The text of the release: the lines of the changelog chapter and where the files come from."""
    source = f"Source: {SOURCE_URL} at the tag `{tag}`" + (f" (commit `{commit}`)" if commit else "") + "."
    return "\n".join(f"- {line}" for line in lines) + f"\n\n{source}\n"


def build(root, out, tag, commit=None):
    """Writes the four files into `out` and returns the version of the .toc. Raises ZipError (nothing is written then)."""
    if not TAG_RE.fullmatch(tag):
        raise ZipError(f"tag {tag!r} is not of the form addon-v<number>(.<number>)+")
    if commit is not None and not COMMIT_RE.fullmatch(commit):
        raise ZipError(f"commit {commit!r} is not a hexadecimal commit id")
    root = Path(root)
    src = root / "addon" / ADDON_NAME
    try:
        toc_text = (src / f"{ADDON_NAME}.toc").read_text(encoding="utf-8-sig")
        version = addon_package.toc_value(toc_text, "Version")
        if not version or not re.fullmatch(r"\d+(?:\.\d+)*", version):
            raise ZipError(f"no usable '## Version:' line in the .toc: {version!r}")
        addon_package.check_tag(tag, version)
        lines = addon_package.changelog_lines((root / "addon" / "CHANGELOG.md").read_text(encoding="utf-8-sig"), version)
        if not addon_files(src):
            raise ZipError(f"no files in {src}")
        data = make_zip(src)
    except (addon_package.PackageError, OSError) as exc:
        raise ZipError(str(exc)) from exc
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    (out / ZIP_NAME).write_bytes(data)
    (out / CHECKSUM_NAME).write_text(f"{hashlib.sha256(data).hexdigest()}  {ZIP_NAME}\n", encoding="ascii", newline="\n")
    (out / NOTES_NAME).write_text(release_notes(lines, tag, commit), encoding="utf-8", newline="\n")
    (out / RELEASE_NAME_FILE).write_text(f"Addon {version}\n", encoding="utf-8", newline="\n")
    return version


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", required=True, type=Path, help="folder that gets the four files")
    ap.add_argument("--tag", required=True, help="the tag of the release (addon-v<version of the .toc>)")
    ap.add_argument("--commit", help="the commit of the tag (named in the release notes)")
    args = ap.parse_args(argv)
    try:
        version = build(ROOT, args.out, args.tag, args.commit)
    except ZipError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"addon {version}: {args.out / ZIP_NAME} written (with checksum, notes and name)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
