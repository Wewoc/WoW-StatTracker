#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)
# gui_dialogs.py
# StatTracker - small modal dialogs: settings, about, update available.
# Each takes the parent window and the texts come from i18n at call time, so a
# language switch needs no rebuild here.

import tkinter as tk
import webbrowser
from tkinter import messagebox, ttk

import app_info
from i18n import t


def _modal(parent, title):
    win = tk.Toplevel(parent)
    win.title(title)
    win.transient(parent)
    win.resizable(False, False)
    win.grab_set()
    return win


def _center(win, parent):
    win.update_idletasks()
    x = parent.winfo_rootx() + (parent.winfo_width() - win.winfo_width()) // 2
    y = parent.winfo_rooty() + (parent.winfo_height() - win.winfo_height()) // 3
    win.geometry(f"+{max(x, 0)}+{max(y, 0)}")


def link_label(parent, text, url, **kw):
    """Clickable link label that opens `url` in the browser."""
    lbl = tk.Label(parent, text=text, fg="#1a5fb4", cursor="hand2", **kw)
    lbl.configure(font=("Segoe UI", 9, "underline"))
    lbl.bind("<Button-1>", lambda _e: webbrowser.open(url))
    return lbl


def ask_settings(parent, detected_variants, enabled_variants, check_updates):
    """Settings dialog. Returns (enabled_variants, check_updates) or None if cancelled."""
    win = _modal(parent, t("settings_title"))
    body = ttk.Frame(win, padding=12)
    body.pack(fill="both", expand=True)

    ttk.Label(body, text=t("settings_variants"), font=("Segoe UI", 9, "bold")).pack(anchor="w")
    ttk.Label(body, text=t("settings_variants_hint"), wraplength=380, justify="left",
              foreground="#555").pack(anchor="w", pady=(0, 6))

    names = list(dict.fromkeys(list(detected_variants) + list(enabled_variants)))
    vars_ = {}
    for name in names:
        v = tk.BooleanVar(value=name in enabled_variants)
        vars_[name] = v
        ttk.Checkbutton(body, text=name, variable=v).pack(anchor="w", padx=12)

    upd = tk.BooleanVar(value=check_updates)
    ttk.Checkbutton(body, text=t("settings_check_updates"), variable=upd).pack(anchor="w", pady=(12, 0))

    result = {}

    def on_ok():
        chosen = [n for n, v in vars_.items() if v.get()]
        if not chosen:
            messagebox.showerror(t("dlg_title"), t("settings_none_selected"), parent=win)
            return
        result["value"] = (chosen, upd.get())
        win.destroy()

    row = ttk.Frame(body)
    row.pack(fill="x", pady=(14, 0))
    ttk.Button(row, text=t("btn_ok"), command=on_ok).pack(side="right")
    ttk.Button(row, text=t("btn_cancel"), command=win.destroy).pack(side="right", padx=6)

    _center(win, parent)
    win.wait_window()
    return result.get("value")


def show_about(parent, on_check_updates):
    win = _modal(parent, t("about_title"))
    body = ttk.Frame(win, padding=14)
    body.pack(fill="both", expand=True)

    ttk.Label(body, text=app_info.APP_NAME, font=("Segoe UI", 14, "bold")).pack(anchor="w")
    ttk.Label(body, text=t("footer_version", version=app_info.APP_VERSION),
              foreground="#555").pack(anchor="w", pady=(0, 8))
    ttk.Label(body, text=t("about_desc"), wraplength=420, justify="left").pack(anchor="w", pady=(0, 8))

    row = ttk.Frame(body)
    row.pack(anchor="w")
    ttk.Label(row, text=t("about_repo") + " ").pack(side="left")
    link_label(row, app_info.REPO_URL, app_info.REPO_URL).pack(side="left")
    if not app_info.REPO_CONFIRMED:
        ttk.Label(body, text=t("about_repo_placeholder"), wraplength=420, justify="left",
                  foreground="#a05000").pack(anchor="w", pady=(4, 0))

    ttk.Label(body, text=app_info.COPYRIGHT).pack(anchor="w", pady=(8, 0))
    ttk.Label(body, text=t("about_license", license=app_info.LICENSE_NAME),
              wraplength=420, justify="left").pack(anchor="w")

    btns = ttk.Frame(body)
    btns.pack(fill="x", pady=(14, 0))
    ttk.Button(btns, text=t("btn_close"), command=win.destroy).pack(side="right")

    def check():
        win.destroy()
        on_check_updates()

    ttk.Button(btns, text=t("btn_check_updates"), command=check).pack(side="right", padx=6)

    _center(win, parent)
    win.wait_window()


def ask_update(parent, title, current, can_apply):
    """Update popup. Returns 'update', 'github' or None (later)."""
    win = _modal(parent, t("update_title"))
    body = ttk.Frame(win, padding=14)
    body.pack(fill="both", expand=True)
    ttk.Label(body, text=t("update_text", title=title, current=current),
              justify="left").pack(anchor="w", pady=(0, 12))

    result = {}

    def pick(value):
        result["value"] = value
        win.destroy()

    row = ttk.Frame(body)
    row.pack(fill="x")
    ttk.Button(row, text=t("btn_later"), command=lambda: pick(None)).pack(side="right")
    ttk.Button(row, text=t("btn_open_github"), command=lambda: pick("github")).pack(side="right", padx=6)
    if can_apply:
        ttk.Button(row, text=t("btn_update_now"), command=lambda: pick("update")).pack(side="right")

    win.protocol("WM_DELETE_WINDOW", lambda: pick(None))
    _center(win, parent)
    win.wait_window()
    return result.get("value")
