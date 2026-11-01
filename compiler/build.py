#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)
# compiler/build.py
# Builds StatTracker as a --onedir PyInstaller package (StatTracker.exe) plus the
# release ZIP and its SHA256 file.
#
# --onedir instead of --onefile: faster start, fewer antivirus false positives, and
# the self-updater can swap the files cleanly.
#
# dist/StatTracker/ is disposable build output (wiped before every build). The
# hand-off unit is dist/StatTracker.zip + dist/StatTracker.zip.sha256 - upload both
# to the GitHub release (the updater needs the checksum file).
#
# Run from the project root:
#     python compiler/build.py
#     python compiler/build.py --no-zip
#     python compiler/build.py --no-venv     # use the current Python (CI installs the requirements itself)

import argparse
import ast
import hashlib
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import build_manifest as manifest
import plotly_asset  # noqa: E402  (build_manifest puts src/ on the path)
import plotly_fetch


# PyInstaller 6 puts --add-data files and libraries into this folder inside the onedir.
CONTENTS_DIR = "_internal"
# Imported inside a function (config.default_language): PyInstaller finds it, the bundle check makes sure.
LAZY_STDLIB = ("ctypes",)


def expected_modules(root: Path) -> set:
    """Modules the bundle has to hold: every module of src/ except the entry script, the hidden imports of
    the manifest and the standard library modules that are only imported inside a function."""
    own = {p.stem for p in (root / "src").glob("*.py")} - {Path(manifest.ENTRY_POINT).stem}
    return own | set(manifest.HIDDEN_IMPORTS) | set(LAZY_STDLIB)


def bundle_problems(root: Path, dist_dir: Path, toc_path: Path) -> list:
    """What the finished PyInstaller folder lacks, as readable lines (empty: complete). Looks for the bundled
    data files in _internal and for the modules in the module table PyInstaller leaves in its work folder
    (PYZ-00.toc): an import inside a function is the kind PyInstaller can miss, and a bundle without it
    starts normally and fails when the function runs."""
    problems = []
    for src, dest in (*manifest.DATA_FILES, *manifest.FETCHED_FILES):
        target = dist_dir / CONTENTS_DIR / dest / Path(src).name
        if not target.is_file():
            problems.append(f"data file {Path(src).name} is not in the bundle (expected {target})")
    try:
        table = ast.literal_eval(toc_path.read_text(encoding="utf-8"))
        in_bundle = {name for name, _path, kind in table[1] if kind == "PYMODULE"}
    except (OSError, ValueError, SyntaxError, IndexError, TypeError) as exc:
        return problems + [f"module table {toc_path} cannot be read ({exc}); PyInstaller may have changed its format"]
    problems += [f"module {name} is not in the bundle" for name in sorted(expected_modules(root) - in_bundle)]
    return problems


def check_bundle(root: Path, dist_dir: Path):
    problems = bundle_problems(root, dist_dir, root / "build" / manifest.APP_NAME / "PYZ-00.toc")
    if problems:
        print("  [build] The bundle is incomplete:")
        for line in problems:
            print(f"    - {line}")
        raise SystemExit(1)
    print("  bundle checked: data files and modules are present.")


def check_source(root: Path):
    required = [manifest.ENTRY_POINT, "requirements.txt", manifest.LICENSE_FILE,
                manifest.ADDON_SRC, *manifest.INFO_FILES,
                *(src for src, _ in manifest.DATA_FILES), *(src for src, _ in manifest.FETCHED_FILES)]
    missing = [name for name in required if not (root / name).exists()]
    if missing:
        print(f"  [build] Not a StatTracker checkout (missing {', '.join(missing)}): {root}")
        raise SystemExit(1)


def ensure_plotly():
    """The pinned plotly.js bundle must be in src/ (fetched and hash-checked if missing)."""
    print("\n[0/4] Checking the Plotly bundle ...")
    try:
        downloaded = plotly_fetch.ensure()
    except plotly_asset.PlotlyAssetError as exc:
        print(f"  [build] {exc}")
        raise SystemExit(1)
    print(f"  plotly.js {plotly_asset.VERSION} {'fetched and verified' if downloaded else 'present and verified'}.")


def ensure_build_venv(root: Path) -> Path:
    """Creates (if missing) or reuses a project-local .venv-build/, installs
    requirements.txt + PyInstaller into it, returns its python. Project-local on
    purpose: whatever else is installed globally stays out of PyInstaller's analysis."""
    print("\n[1/4] Checking build venv ...")
    venv_dir = root / ".venv-build"
    venv_python = venv_dir / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    if not venv_python.exists():
        print(f"  Not found at {venv_dir} - creating ...")
        subprocess.check_call([sys.executable, "-m", "venv", str(venv_dir)])
    else:
        print(f"  Reusing existing venv: {venv_dir}")
    subprocess.check_call([str(venv_python), "-m", "pip", "install", "-q", "-r", str(root / "requirements.txt")])
    subprocess.check_call([str(venv_python), "-m", "pip", "install", "-q", "pyinstaller"])
    print("  Build venv ready.")
    return venv_python


def build_exe(root: Path, python: Path, dist_dir: Path):
    print("\n[2/4] Building EXE (--onedir) ...")
    if dist_dir.exists():
        print(f"  Clearing previous build output: {dist_dir}")
        shutil.rmtree(dist_dir)

    sep = ";" if sys.platform == "win32" else ":"
    args = []
    for src, dest in (*manifest.DATA_FILES, *manifest.FETCHED_FILES):
        args += ["--add-data", f"{root / src}{sep}{dest}"]
    for h in manifest.HIDDEN_IMPORTS:
        args += ["--hidden-import", h]
    for p in manifest.EXTRA_PATHS:
        args += ["--paths", str(root / p)]

    cmd = [
        str(python), "-m", "PyInstaller",
        "--onedir", "--noconsole", "--noconfirm",
        "--name", manifest.APP_NAME,
        "--distpath", str(root / "dist"),
        "--workpath", str(root / "build"),
        "--specpath", str(Path(__file__).parent),
        *args,
        str(root / manifest.ENTRY_POINT),
    ]
    if subprocess.run(cmd, cwd=str(root)).returncode != 0:
        print("\n  [build] PyInstaller failed - see output above.")
        raise SystemExit(1)
    if not dist_dir.exists():
        print(f"  [build] PyInstaller reported success but {dist_dir} does not exist.")
        raise SystemExit(1)


def copy_extras(root: Path, dist_dir: Path):
    """Addon, documentation and LICENSE next to the exe (runs after build_exe, which wipes dist_dir)."""
    print("\n[3/4] Copying addon and documentation ...")
    shutil.copytree(root / manifest.ADDON_SRC, dist_dir / manifest.ADDON_SRC,
                    ignore=shutil.ignore_patterns("__pycache__"))
    info = dist_dir / manifest.INFO_DIR
    info.mkdir(parents=True, exist_ok=True)
    for rel in manifest.INFO_FILES:
        shutil.copy2(root / rel, info / Path(rel).name)
    shutil.copy2(root / manifest.LICENSE_FILE, dist_dir / manifest.LICENSE_FILE)

    missing = [name for name in manifest.PROGRAM_ITEMS if not (dist_dir / name).exists()]
    if missing:
        print(f"  [build] Release is missing {', '.join(missing)} (manifest vs. build output).")
        raise SystemExit(1)
    print("  addon/, info/, LICENSE copied; all release items present.")
    check_bundle(root, dist_dir)


def build_zip(dist_dir: Path):
    """ZIP with one top folder (StatTracker/), plus <zip>.sha256 ("<hex>  <name>")."""
    zip_path = dist_dir.parent / manifest.ZIP_NAME
    print(f"\n[4/4] Creating {zip_path.name} ...")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(dist_dir.rglob("*")):
            if f.is_file():
                zf.write(f, f.relative_to(dist_dir.parent))
    digest = hashlib.sha256(zip_path.read_bytes()).hexdigest()
    checksum_path = dist_dir.parent / manifest.CHECKSUM_NAME
    checksum_path.write_text(f"{digest}  {zip_path.name}\n", encoding="ascii")
    print(f"  -> {zip_path}\n  -> {checksum_path}")


def main():
    ap = argparse.ArgumentParser(description="Build StatTracker as a --onedir PyInstaller package.")
    ap.add_argument("--no-zip", action="store_true", help="Skip creating the release ZIP and checksum.")
    ap.add_argument("--no-venv", action="store_true",
                    help="Use the current Python instead of .venv-build/ (PyInstaller and requirements must be installed).")
    args = ap.parse_args()

    root = Path(__file__).resolve().parent.parent
    ensure_plotly()
    check_source(root)
    python = Path(sys.executable) if args.no_venv else ensure_build_venv(root)

    dist_dir = root / "dist" / manifest.APP_NAME
    build_exe(root, python, dist_dir)
    copy_extras(root, dist_dir)
    if not args.no_zip:
        build_zip(dist_dir)
    print(f"\n  Build finished: {dist_dir}")


if __name__ == "__main__":
    main()
