# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)
# Runs the REAL updater_helper.ps1 against temporary folders. The point of these
# tests: the swap replaces the program items and never touches data/.

import shutil
import subprocess
from pathlib import Path

import pytest

HELPER = Path(__file__).resolve().parent.parent / "src" / "updater_helper.ps1"
POWERSHELL = shutil.which("powershell") or shutil.which("pwsh")

ITEMS = ["StatTracker.exe", "_internal", "addon", "info", "LICENSE"]


def test_helper_is_plain_ascii():
    HELPER.read_bytes().decode("ascii")      # raises UnicodeDecodeError on any non-ASCII byte


pytestmark_ps = pytest.mark.skipif(POWERSHELL is None, reason="PowerShell not available")


def write_tree(root: Path, content: str, items=ITEMS):
    root.mkdir(parents=True, exist_ok=True)
    for item in items:
        p = root / item
        if item in ("_internal", "addon", "info"):
            p.mkdir(exist_ok=True)
            (p / "file.txt").write_text(content, encoding="utf-8")
        else:
            p.write_text(content, encoding="utf-8")


def run_helper(exe_dir, payload, items, extra=(), timeout=120):
    cmd = [POWERSHELL, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(HELPER),
           "-ExeDir", str(exe_dir), "-PayloadDir", str(payload),
           "-PendingRoot", str(exe_dir / "_update_pending"), "-Items", ",".join(items), *extra]
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                          timeout=timeout, stdin=subprocess.DEVNULL)


@pytest.fixture
def instance_dirs(tmp_path):
    exe_dir = tmp_path / "app with space"
    write_tree(exe_dir, "old")
    (exe_dir / "data").mkdir()
    (exe_dir / "data" / "wow_stats.db").write_text("history", encoding="utf-8")
    (exe_dir / "data" / "config.json").write_text("{}", encoding="utf-8")
    payload = exe_dir / "_update_pending" / "StatTracker"
    write_tree(payload, "new")
    return exe_dir, payload


@pytestmark_ps
def test_swap_replaces_program_items_and_keeps_data(instance_dirs):
    exe_dir, payload = instance_dirs
    res = run_helper(exe_dir, payload, ITEMS)
    assert res.returncode == 0, res.stdout + res.stderr
    for item in ITEMS:
        p = exe_dir / item
        text = (p / "file.txt" if p.is_dir() else p).read_text(encoding="utf-8")
        assert text == "new", item
    assert (exe_dir / "data" / "wow_stats.db").read_text(encoding="utf-8") == "history"
    assert (exe_dir / "data" / "config.json").is_file()
    # the old version is kept as a rollback net; leftovers are cleaned up
    assert (exe_dir / "_update_backup" / "StatTracker.exe").read_text(encoding="utf-8") == "old"
    assert not (exe_dir / "_update_pending").exists()
    assert not (exe_dir / "_update_helper.lock").exists()


@pytestmark_ps
def test_incomplete_payload_changes_nothing(instance_dirs):
    exe_dir, payload = instance_dirs
    (payload / "LICENSE").unlink()
    res = run_helper(exe_dir, payload, ITEMS)
    assert res.returncode != 0
    assert "incomplete" in (res.stdout + res.stderr)
    for item in ITEMS:
        p = exe_dir / item
        assert (p / "file.txt" if p.is_dir() else p).read_text(encoding="utf-8") == "old", item
    assert (exe_dir / "data" / "wow_stats.db").read_text(encoding="utf-8") == "history"
    assert not (exe_dir / "_update_helper.lock").exists()


@pytestmark_ps
def test_wait_pids_that_are_already_gone_do_not_block(instance_dirs):
    exe_dir, payload = instance_dirs
    res = run_helper(exe_dir, payload, ITEMS, extra=["-WaitPids", "999999"])
    assert res.returncode == 0, res.stdout + res.stderr


FAKE_OK = '@echo off\r\ntype nul > "%~dp0_update_success.flag"\r\n'
FAKE_BROKEN = "@echo off\r\nexit /b 3\r\n"


def write_gui_tree(root: Path, gui_text: str, lib_text: str):
    root.mkdir(parents=True, exist_ok=True)
    (root / "fake.bat").write_bytes(gui_text.encode("ascii"))     # bytes: no newline translation
    (root / "_internal").mkdir(exist_ok=True)
    (root / "_internal" / "file.txt").write_text(lib_text, encoding="utf-8")


@pytestmark_ps
def test_restart_with_handshake_succeeds(tmp_path):
    exe_dir = tmp_path / "app"
    write_gui_tree(exe_dir, FAKE_BROKEN, "old")
    (exe_dir / "data").mkdir()
    (exe_dir / "data" / "wow_stats.db").write_text("history", encoding="utf-8")
    payload = exe_dir / "_update_pending" / "StatTracker"
    write_gui_tree(payload, FAKE_OK, "new")

    res = run_helper(exe_dir, payload, ["fake.bat", "_internal"],
                     extra=["-RestartGui", "-GuiExeName", "fake.bat", "-HideGuiWindow",
                            "-SuccessTimeoutSeconds", "20", "-MaxLaunchAttempts", "2"])
    assert res.returncode == 0, res.stdout + res.stderr
    assert (exe_dir / "_internal" / "file.txt").read_text(encoding="utf-8") == "new"
    assert not (exe_dir / "_update_success.flag").exists()      # consumed by the helper
    assert (exe_dir / "data" / "wow_stats.db").read_text(encoding="utf-8") == "history"


@pytestmark_ps
def test_new_version_that_never_starts_is_rolled_back(tmp_path):
    exe_dir = tmp_path / "app"
    write_gui_tree(exe_dir, FAKE_OK, "old")           # the OLD gui would signal success
    (exe_dir / "data").mkdir()
    (exe_dir / "data" / "wow_stats.db").write_text("history", encoding="utf-8")
    payload = exe_dir / "_update_pending" / "StatTracker"
    write_gui_tree(payload, FAKE_BROKEN, "new")       # the NEW gui exits without a flag

    res = run_helper(exe_dir, payload, ["fake.bat", "_internal"],
                     extra=["-RestartGui", "-GuiExeName", "fake.bat", "-HideGuiWindow",
                            "-SuccessTimeoutSeconds", "3", "-MaxLaunchAttempts", "2"])
    assert res.returncode != 0
    assert "rolled back" in (res.stdout + res.stderr)
    assert (exe_dir / "_internal" / "file.txt").read_text(encoding="utf-8") == "old"
    assert (exe_dir / "fake.bat").read_bytes() == FAKE_OK.encode("ascii")
    assert (exe_dir / "data" / "wow_stats.db").read_text(encoding="utf-8") == "history"
