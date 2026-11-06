# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)
# The tool behind the pictures of the program window (tools/make_window_shots.py). It runs in its own process: it starts a window of its own with its own
# settings and browser profile, which does not belong in the process of the window tests.

import importlib.util
import struct
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOOLS = ROOT / "tools"


def _demo(folder):
    spec = importlib.util.spec_from_file_location("make_demo", TOOLS / "make_demo.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.make(folder, "en")


PNG_SIGNATURE = bytes([137, 80, 78, 71, 13, 10, 26, 10])


def _size(path):
    header = path.read_bytes()[:24]
    assert header[:8] == PNG_SIGNATURE, path
    return struct.unpack(">II", header[16:24])


def test_the_tool_takes_the_two_pictures_of_the_window_from_the_demo_data(tmp_path):
    demo, out = tmp_path / "demo", tmp_path / "pictures"
    _demo(demo)
    done = subprocess.run([sys.executable, str(TOOLS / "make_window_shots.py"), "--demo", str(demo), "--out", str(out), "--lang", "en"],
                          capture_output=True, text=True, timeout=300)
    assert done.returncode == 0, done.stderr[-2000:]
    app, top5 = _size(out / "app-en.png"), _size(out / "top5-en.png")
    assert app[0] == top5[0] >= 1180 and app[1] > top5[1] > 300                       # the Top 5 picture is the same width and cut below the button
    assert sorted(p.name for p in out.iterdir()) == ["app-en.png", "top5-en.png"]


def test_the_tool_says_what_is_missing_instead_of_failing_in_the_window(tmp_path):
    done = subprocess.run([sys.executable, str(TOOLS / "make_window_shots.py"), "--demo", str(tmp_path / "none"), "--out", str(tmp_path / "x"), "--lang", "en"],
                          capture_output=True, text=True, timeout=300)
    assert done.returncode != 0 and "make_demo.py" in (done.stderr + done.stdout)


def test_nothing_of_the_machine_is_in_the_texts_the_tool_puts_into_the_window():
    source = (TOOLS / "make_window_shots.py").read_text(encoding="utf-8")
    for line in source.splitlines():
        if line.startswith(("NEUTRAL_GAME", "NEUTRAL_FILE")):
            assert "Users" not in line and "AppData" not in line and "Temp" not in line, line
