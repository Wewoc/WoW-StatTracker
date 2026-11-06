#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)
# start.py
# StatTracker - entry point. Run from source: python src/start.py

import sys
import traceback
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from core import paths  # noqa: E402
from core import updater  # noqa: E402

SUCCESS_FLAG_DELAY_MS = 800  # after the window has been drawn


def log_crash(exc_type, exc, tb):
    """A windowed exe has no console: write the traceback to data/crash.log and tell the user."""
    text = "".join(traceback.format_exception(exc_type, exc, tb))
    try:
        paths.data_dir().mkdir(parents=True, exist_ok=True)
        with open(paths.data_dir() / "crash.log", "a", encoding="utf-8") as f:
            f.write(f"--- {datetime.now():%Y-%m-%d %H:%M:%S} ---\n{text}\n")
    except OSError:
        pass
    try:
        from PyQt6.QtWidgets import QApplication, QMessageBox
        if QApplication.instance() is not None:
            QMessageBox.critical(None, "StatTracker", text[-1500:])
    except Exception:  # last resort: the error is in crash.log if writable
        pass


def main():
    from app import main_window      # first: QtWebEngine has to be imported before the QApplication exists
    from PyQt6.QtCore import QTimer
    from PyQt6.QtWidgets import QApplication
    sys.excepthook = log_crash       # an error inside a slot is reported (crash.log, dialog) and the window goes on
    qapp = QApplication(sys.argv)    # with the program name: the browser engine refuses an empty argument list
    qapp.setApplicationName("StatTracker")
    window = main_window.MainWindow()
    window.show()
    if paths.is_frozen():
        # startup handshake for the self-updater (see updater_helper.ps1)
        QTimer.singleShot(SUCCESS_FLAG_DELAY_MS, lambda: updater.write_success_flag(paths.base_dir()))
    return qapp.exec()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        log_crash(*sys.exc_info())
        sys.exit(1)
