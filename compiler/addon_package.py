#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)
"""Prepares the addon for CurseForge (the BigWigs packager runs on the result, see .github/workflows/addon-release.yml).

    python compiler/addon_package.py --out stage [--tag addon-v0.2.4]

- the tag (when given) must be addon-v<version of the .toc>;
- the changelog of the file page is made of the lines of the chapter "## <version>" of addon/CHANGELOG.md (none = stop: an addon release needs its lines);
- <out>/StatTracker/ gets a copy of addon/StatTracker with the interface line of the .toc extended by the number of WoW Forever
  (the .toc in the repository stays as it is: only the copy the program installs gets its number from .build.info), a .pkgmeta
  (folder name and the changelog) and CHANGELOG.md; the folder is made a small Git repository with one commit and the tag <version>
  (the packager needs a checkout and takes the version of the file from the tag).
Standard library only; it does not import the product code and it never uploads anything.
"""
import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ADDON_NAME = "StatTracker"
FOREVER_INTERFACE = "16001"             # WoW Forever runs on the retail client with its own interface number (seen in game)
TAG_PREFIX = "addon-v"


class PackageError(Exception):
    pass


def toc_value(toc_text, key):
    m = re.search(rf"(?m)^## {re.escape(key)}:[ \t]*(.*?)[ \t]*\r?$", toc_text)
    return m.group(1) if m else None


def check_tag(tag, version):
    """The tag of an addon release is addon-v<version of the .toc>."""
    if tag != f"{TAG_PREFIX}{version}":
        raise PackageError(f"tag {tag!r} != {TAG_PREFIX}{version} (the version of the .toc)")


def changelog_lines(changelog_text, version):
    """The '- ' lines of the chapter '## <version>' of addon/CHANGELOG.md, without the '- '; at least one."""
    chapter = re.search(rf"(?ms)^## {re.escape(version)}[ \t]*\r?$(.*?)(?=^## |\Z)", changelog_text)
    found = re.findall(r"(?m)^- (.+?)[ \t\r]*$", chapter.group(1)) if chapter else []
    if not found:
        raise PackageError(f"addon/CHANGELOG.md has no chapter '## {version}' with lines '- ...'")
    return found


def extended_interface(toc_text):
    """The interface numbers of the .toc plus the one of WoW Forever (once)."""
    current = toc_value(toc_text, "Interface")
    if not current or not re.fullmatch(r"\d+(?:[ \t]*,[ \t]*\d+)*", current):
        raise PackageError(f"no usable '## Interface:' line in the .toc: {current!r}")
    numbers = [n.strip() for n in current.split(",")]
    if FOREVER_INTERFACE not in numbers:
        numbers.append(FOREVER_INTERFACE)
    return ", ".join(numbers)


def stage(root, out):
    """Builds <out>/StatTracker; returns the version of the .toc."""
    src = Path(root) / "addon" / ADDON_NAME
    toc_path = src / f"{ADDON_NAME}.toc"
    toc_text = toc_path.read_text(encoding="utf-8")
    version = toc_value(toc_text, "Version")
    if not version or not re.fullmatch(r"\d+(?:\.\d+)*", version):
        raise PackageError(f"no usable '## Version:' line in the .toc: {version!r}")
    lines = changelog_lines((Path(root) / "addon" / "CHANGELOG.md").read_text(encoding="utf-8"), version)

    dest = Path(out) / ADDON_NAME
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(src, dest, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    new_toc, n = re.subn(r"(?m)^## Interface:.*$", lambda m: f"## Interface: {extended_interface(toc_text)}", toc_text, count=1)
    if n != 1:
        raise PackageError("the .toc has no '## Interface:' line")
    (dest / f"{ADDON_NAME}.toc").write_text(new_toc, encoding="utf-8", newline="\n")
    (dest / "CHANGELOG.md").write_text(f"# {ADDON_NAME} {version}\n\n" + "\n".join(f"- {line}" for line in lines) + "\n",
                                       encoding="utf-8", newline="\n")
    (dest / ".pkgmeta").write_text(f"package-as: {ADDON_NAME}\n\nmanual-changelog:\n  filename: CHANGELOG.md\n  markup-type: markdown\n",
                                   encoding="utf-8", newline="\n")
    return version


def init_git(dest, version):
    """Makes the staged folder a small Git repository with one commit and the tag <version>: the packager needs a checkout (it looks
    for .git in the folder it is given) and takes the version of the file from the tag at HEAD."""
    dest = str(dest)
    quiet = ["-c", "user.name=StatTracker release", "-c", "user.email=release@invalid", "-c", "commit.gpgsign=false", "-c", "tag.gpgsign=false",
             "-c", "core.autocrlf=false"]
    for args in (["init", "-q"], ["add", "-A"], quiet + ["commit", "-q", "-m", f"{ADDON_NAME} {version}"],
                 quiet + ["tag", "-a", version, "-m", f"{ADDON_NAME} {version}"]):
        result = subprocess.run(["git", "-C", dest] + args, capture_output=True, text=True)
        if result.returncode != 0:
            raise PackageError(f"git {' '.join(args[-2:])} failed: {result.stderr.strip() or result.stdout.strip()}")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", required=True, type=Path, help="folder that gets StatTracker/ (for the packager)")
    ap.add_argument("--tag", help="the tag of the release (must be addon-v<version>)")
    args = ap.parse_args(argv)
    try:
        toc_text = (ROOT / "addon" / ADDON_NAME / f"{ADDON_NAME}.toc").read_text(encoding="utf-8")
        version = toc_value(toc_text, "Version")
        if args.tag:
            check_tag(args.tag, version)
        version = stage(ROOT, args.out)
        init_git(args.out / ADDON_NAME, version)
    except (PackageError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"addon {version} staged (Git repository, tag {version}) in {args.out / ADDON_NAME}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
