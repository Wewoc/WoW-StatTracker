# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)
# The entry script: a crash is written to data/crash.log (a windowed exe has no console).

import sys

import pytest
from PyQt6.QtWidgets import QMessageBox

import start


@pytest.fixture(autouse=True)
def no_dialog(monkeypatch):
    """log_crash shows a dialog when a QApplication exists (the window tests make one): it must not block the test."""
    shown = []
    monkeypatch.setattr(QMessageBox, "critical", lambda *args: shown.append(args))
    return shown


def test_a_crash_is_written_to_the_crash_log(instance, no_dialog):
    try:
        raise ValueError("boom in a slot")
    except ValueError:
        start.log_crash(*sys.exc_info())
    text = (instance / "data" / "crash.log").read_text(encoding="utf-8")
    assert "ValueError: boom in a slot" in text and text.startswith("--- ")
    assert len(no_dialog) in (0, 1)                 # told to the user when a window exists, never a hang


def test_a_second_crash_is_appended(instance):
    for message in ("first", "second"):
        try:
            raise RuntimeError(message)
        except RuntimeError:
            start.log_crash(*sys.exc_info())
    text = (instance / "data" / "crash.log").read_text(encoding="utf-8")
    assert text.index("RuntimeError: first") < text.index("RuntimeError: second") and text.count("--- ") == 2
