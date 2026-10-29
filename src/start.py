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

import paths  # noqa: E402
import updater  # noqa: E402

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
        from tkinter import messagebox
        messagebox.showerror("StatTracker", text[-1500:])
    except Exception:  # last resort: the error is in crash.log if writable
        pass


def main():
    import gui_app
    app = gui_app.App()
    app.report_callback_exception = log_crash
    if paths.is_frozen():
        # startup handshake for the self-updater (see updater_helper.ps1)
        app.after(SUCCESS_FLAG_DELAY_MS, lambda: updater.write_success_flag(paths.base_dir()))
    app.mainloop()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        log_crash(*sys.exc_info())
        sys.exit(1)
