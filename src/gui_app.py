#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)
# gui_app.py
# StatTracker - main window: pick game version + account, install/uninstall the
# addon, read the data, open the stats page, export to Excel, check for updates.
# Logic lives in wow_install / stat_parser / export_xlsx / updater; this file is UI only.

import contextlib
import io
import os
import queue
import threading
import tkinter as tk
import urllib.error
import webbrowser
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import app_info
import config
import export_xlsx
import gui_dialogs
import i18n
import paths
import stat_parser
import updater
import wow_install
from i18n import t


# ============================================================ logic helpers (no widgets)
def run_parser(sv_file, db_path, html_path):
    """Runs stat_parser.main() and returns (ok, output_text)."""
    buf = io.StringIO()
    ok = True
    try:
        with contextlib.redirect_stdout(buf):
            stat_parser.main(["--input", str(sv_file), "--db", str(db_path), "--output", str(html_path)])
    except SystemExit as e:
        if e.code not in (None, 0):
            ok = False
            buf.write(str(e.code) + "\n")
    except Exception as e:  # unexpected: show loudly, never swallow
        ok = False
        buf.write(t("log_parse_unexpected", error=f"{type(e).__name__}: {e}") + "\n")
    return ok, buf.getvalue()


def run_export():
    """Runs export_xlsx.export() and returns (ok, output_text, xlsx_path)."""
    buf = io.StringIO()
    out = export_xlsx.default_out()
    ok = True
    try:
        buf.write("\n".join(export_xlsx.export(out)) + "\n")
    except SystemExit as e:
        ok = False
        buf.write(str(e.code) + "\n")
    except Exception as e:  # unexpected: show loudly, never swallow
        ok = False
        buf.write(t("log_parse_unexpected", error=f"{type(e).__name__}: {e}") + "\n")
    return ok, buf.getvalue(), out


# ===================================================================== UI
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.cfg, warning = config.load()
        i18n.set_language(self.cfg["language"])
        self.title(t("window_title"))
        self.geometry("880x620")
        self.minsize(720, 520)

        self.var_wow = tk.StringVar(value=self.cfg["wow_dir"] or wow_install.guess_wow_dir())
        self.var_variant = tk.StringVar(value=self.cfg["variant"])
        self.var_acc = tk.StringVar(value="")
        self.var_status = tk.StringVar()
        self.var_lang = tk.StringVar(value=i18n.LANGUAGES[self.cfg["language"]])

        self._log_lines = []          # [(line, tag)] - replayed after a language switch
        self._queue = queue.Queue()   # results from worker threads (update check / download)

        self._build()
        self.refresh_variants(keep=self.var_variant.get())
        self.var_wow.trace_add("write", lambda *_: self.refresh_variants())
        self.var_variant.trace_add("write", lambda *_: self.refresh_accounts())
        self.var_acc.trace_add("write", lambda *_: self.update_status())

        if warning:
            self.write(t("warn_config_broken", detail=warning), "err")
        self.after(200, self._poll_queue)
        if self.cfg["check_updates"]:
            self.after(1500, lambda: self.check_updates(manual=False))

    # ------------------------------------------------------------ construction
    def _build(self):
        pad = {"padx": 8, "pady": 4}

        header = ttk.Frame(self)
        header.pack(fill="x", padx=8, pady=(8, 0))
        ttk.Label(header, text=app_info.APP_NAME, font=("Segoe UI", 14, "bold")).pack(side="left")
        self.cmb_lang = ttk.Combobox(header, textvariable=self.var_lang, state="readonly", width=10,
                                     values=list(i18n.LANGUAGES.values()))
        self.cmb_lang.pack(side="right")
        self.cmb_lang.bind("<<ComboboxSelected>>", lambda _e: self.after_idle(self.on_language))
        ttk.Label(header, text=t("lbl_language")).pack(side="right", padx=6)

        top = ttk.Frame(self)
        top.pack(fill="x", padx=8, pady=4)
        top.columnconfigure(1, weight=1)

        ttk.Label(top, text=t("lbl_wow_folder")).grid(row=0, column=0, sticky="w", **pad)
        ttk.Entry(top, textvariable=self.var_wow).grid(row=0, column=1, sticky="ew", **pad)
        ttk.Button(top, text=t("btn_browse"), command=self.browse_wow).grid(row=0, column=2, **pad)

        ttk.Label(top, text=t("lbl_variant")).grid(row=1, column=0, sticky="w", **pad)
        self.cmb_var = ttk.Combobox(top, textvariable=self.var_variant, state="readonly")
        self.cmb_var.grid(row=1, column=1, sticky="ew", **pad)
        ttk.Button(top, text=t("btn_settings"), command=self.on_settings).grid(row=1, column=2, **pad)

        ttk.Label(top, text=t("lbl_account")).grid(row=2, column=0, sticky="w", **pad)
        self.cmb = ttk.Combobox(top, textvariable=self.var_acc, state="readonly")
        self.cmb.grid(row=2, column=1, sticky="ew", **pad)
        ttk.Button(top, text=t("btn_reload"),
                   command=lambda: self.refresh_variants(keep=self.var_variant.get())).grid(row=2, column=2, **pad)

        ttk.Label(top, textvariable=self.var_status, wraplength=820, justify="left",
                  foreground="#555").grid(row=3, column=0, columnspan=3, sticky="w", **pad)

        btns = ttk.Frame(self)
        btns.pack(fill="x", padx=8)
        ttk.Button(btns, text=t("btn_install"), command=self.on_install).pack(side="left", padx=4, pady=4)
        ttk.Button(btns, text=t("btn_parse"), command=self.on_parse).pack(side="left", padx=4, pady=4)
        ttk.Button(btns, text=t("btn_open"), command=self.on_open).pack(side="left", padx=4, pady=4)
        ttk.Button(btns, text=t("btn_parse_open"), command=self.on_parse_open).pack(side="right", padx=4, pady=4)
        ttk.Button(btns, text=t("btn_export"), command=self.on_export).pack(side="right", padx=4, pady=4)
        ttk.Button(btns, text=t("btn_uninstall"), command=self.on_uninstall).pack(side="right", padx=4, pady=4)

        foot = ttk.Frame(self)
        foot.pack(side="bottom", fill="x", padx=8, pady=(0, 8))
        ttk.Label(foot, text=t("footer_version", version=app_info.APP_VERSION)).pack(side="left")
        ttk.Label(foot, text="  ·  ").pack(side="left")
        gui_dialogs.link_label(foot, app_info.REPO_URL.replace("https://", ""), app_info.REPO_URL).pack(side="left")
        ttk.Label(foot, text=f"  ·  {app_info.COPYRIGHT}  ·  {app_info.LICENSE_NAME}").pack(side="left")
        ttk.Button(foot, text=t("btn_about"), command=self.on_about).pack(side="right", padx=(6, 0))
        ttk.Button(foot, text=t("btn_check_updates"),
                   command=lambda: self.check_updates(manual=True)).pack(side="right")

        frame = ttk.Frame(self)
        frame.pack(fill="both", expand=True, padx=8, pady=8)
        self.log = tk.Text(frame, height=12, wrap="word", state="disabled", font=("Consolas", 9))
        sb = ttk.Scrollbar(frame, command=self.log.yview)
        self.log.configure(yscrollcommand=sb.set)
        self.log.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.log.tag_configure("err", foreground="#c00000")
        self.log.tag_configure("ok", foreground="#007a00")

    def _rebuild(self):
        """Rebuilds all widgets (language switch). Variables and the log survive."""
        for child in self.winfo_children():
            child.destroy()
        self.title(t("window_title"))
        self._build()
        for line, tag in self._log_lines:
            self._insert(line, tag)
        self.refresh_variants(keep=self.var_variant.get())

    # ----------------------------------------------------------------- helpers
    def _insert(self, line, tag=None):
        self.log.configure(state="normal")
        self.log.insert("end", line + "\n", tag)
        self.log.see("end")
        self.log.configure(state="disabled")

    def write(self, text, tag=None):
        line = f"[{datetime.now():%H:%M:%S}] {text}"
        self._log_lines.append((line, tag))
        self._insert(line, tag)

    def root_and_variant(self):
        """(root, variant). variant is None if nothing usable is selected or the
        selected game version is not enabled. A typed-in version folder wins over the dropdown."""
        root, forced = wow_install.resolve_root(self.var_wow.get())
        if not root:
            return None, None
        variant = forced or self.var_variant.get()
        if not variant or variant not in self.cfg["enabled_variants"]:
            return root, None
        return root, variant

    def game_dir(self):
        root, variant = self.root_and_variant()
        return (root / variant) if (root and variant) else None

    def save(self):
        root, variant = self.root_and_variant()
        self.cfg["wow_dir"] = str(root) if root else self.var_wow.get().strip()
        if variant:
            self.cfg["variant"] = variant
            self.cfg["accounts"][variant] = self.var_acc.get()
        try:
            config.save(self.cfg)
        except OSError as e:
            self.write(t("err_config_save", error=e), "err")

    def browse_wow(self):
        d = filedialog.askdirectory(title=t("browse_title"), initialdir=self.var_wow.get() or None)
        if d:
            self.var_wow.set(str(Path(d)))

    def refresh_variants(self, keep=""):
        keep = keep or self.var_variant.get()
        root, forced = wow_install.resolve_root(self.var_wow.get())
        variants = wow_install.list_variants(root, self.cfg["enabled_variants"]) if root else []
        self.cmb_var["values"] = variants
        wanted = forced or keep
        if wanted in variants:
            self.var_variant.set(wanted)
        elif variants:
            self.var_variant.set(variants[0])
        else:
            self.var_variant.set("")
        self.refresh_accounts()

    def refresh_accounts(self):
        game = self.game_dir()
        accounts = wow_install.list_accounts(game) if game else []
        self.cmb["values"] = accounts
        remembered = self.cfg["accounts"].get(self.var_variant.get(), "")
        if remembered in accounts:
            self.var_acc.set(remembered)
        elif accounts:
            self.var_acc.set(accounts[0])
        else:
            self.var_acc.set("")
        self.update_status()

    def update_status(self):
        root, variant = self.root_and_variant()
        if not root:
            self.var_status.set(t("status_invalid_root"))
            return
        if not variant:
            _r, forced = wow_install.resolve_root(self.var_wow.get())
            shown = forced or self.var_variant.get()
            self.var_status.set(t("status_variant_disabled", variant=shown) if shown
                                else t("status_invalid_root"))
            return
        parts = [t("status_game", path=root / variant)]
        acc = self.var_acc.get()
        if acc:
            sv = wow_install.saved_vars_path(root / variant, acc)
            if sv.is_file():
                ts = datetime.fromtimestamp(sv.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
                parts.append(t("status_data_present", ts=ts))
            else:
                parts.append(t("status_data_missing"))
        else:
            parts.append(t("status_no_account"))
        status = wow_install.addon_status(root, variant)
        if status[0] == "missing":
            parts.append(t("status_addon_missing"))
        elif status[0] == "ok":
            parts.append(t("status_addon_ok", version=status[1]))
        elif status[0] == "outdated":
            parts.append(t("status_addon_outdated", installed=status[1], bundled=status[2]))
        elif status[0] == "interface":
            parts.append(t("status_addon_interface", installed=status[1], expected=status[2]))
        else:
            parts.append(t("status_addon_unknown"))
        html = wow_install.out_files(variant)[1]
        parts.append(t("status_html_present" if html.is_file() else "status_html_missing", name=html.name))
        self.var_status.set("  |  ".join(parts))

    def need_root(self):
        root, variant = self.root_and_variant()
        if not root:
            messagebox.showerror(t("dlg_title"), t("err_invalid_root"))
            return None, None
        if not variant:
            messagebox.showerror(t("dlg_title"), t("status_variant_disabled",
                                                   variant=self.var_variant.get() or "?"))
            return None, None
        return root, variant

    # ----------------------------------------------------------------- actions
    def on_language(self):
        code = next((k for k, v in i18n.LANGUAGES.items() if v == self.var_lang.get()), None)
        if not code or code == i18n.get_language():
            return
        i18n.set_language(code)
        self.cfg["language"] = code
        self.save()
        self._rebuild()

    def on_settings(self):
        root, _forced = wow_install.resolve_root(self.var_wow.get())
        detected = wow_install.list_variants(root) if root else []
        result = gui_dialogs.ask_settings(self, detected, self.cfg["enabled_variants"],
                                          self.cfg["check_updates"])
        if not result:
            return
        self.cfg["enabled_variants"], self.cfg["check_updates"] = result
        self.save()
        self.refresh_variants(keep=self.var_variant.get())

    def on_about(self):
        gui_dialogs.show_about(self, lambda: self.check_updates(manual=True))

    def on_install(self):
        root, variant = self.need_root()
        if not root:
            return
        try:
            res = wow_install.install_addon(root, variant)
        except (RuntimeError, OSError) as e:
            self.write(t("err_install_failed", error=e), "err")
            messagebox.showerror(t("dlg_title"), t("err_install_failed", error=e))
            return
        self.save()
        self.write(t("log_install_ok", dest=res.dest), "ok")
        if res.number is not None:
            self.write(t("log_interface_set", number=res.number, version=res.version, product=res.product), "ok")
        else:
            self.write(t("log_interface_unset", product=res.product), "err")
        self.write(t("log_install_reload"))
        self.update_status()

    def on_uninstall(self):
        root, variant = self.need_root()
        if not root:
            return
        dest = wow_install.addon_dir(root, variant)
        if not messagebox.askyesno(t("dlg_title"), t("confirm_uninstall", dest=dest),
                                   icon="warning", default="no"):
            return
        remove_vars = False
        if wow_install.saved_vars_files(root / variant):
            remove_vars = messagebox.askyesno(t("dlg_title"), t("confirm_uninstall_vars"),
                                              icon="warning", default="no")
        try:
            res = wow_install.uninstall_addon(root, variant, remove_saved_vars=remove_vars)
        except (RuntimeError, OSError) as e:
            self.write(t("err_uninstall_failed", error=e), "err")
            messagebox.showerror(t("dlg_title"), t("err_uninstall_failed", error=e))
            return
        if res.removed_addon:
            self.write(t("log_uninstall_ok", dest=dest), "ok")
        else:
            self.write(t("log_uninstall_none", dest=dest))
        if remove_vars:
            self.write(t("log_uninstall_vars", count=len(res.removed_files)))
        self.write(t("log_uninstall_kept", path=paths.data_dir()))
        self.update_status()

    def on_parse(self, open_after=False):
        root, variant = self.need_root()
        if not root:
            return False
        acc = self.var_acc.get()
        if not acc:
            messagebox.showerror(t("dlg_title"), t("err_no_account"))
            return False
        sv = wow_install.saved_vars_path(root / variant, acc)
        if not sv.is_file():
            msg = t("err_no_data_file", path=sv)
            self.write(msg.replace("\n\n", " ").replace("\n", " "), "err")
            messagebox.showerror(t("dlg_title"), msg)
            return False
        self.save()
        db_path, html_path = wow_install.out_files(variant)
        ok, out = run_parser(sv, db_path, html_path)
        for line in out.strip().splitlines():
            self.write(line, "err" if (not ok or line.startswith(("FEHLER", "WARNUNG", "ERROR", "WARNING"))) else None)
        self.write(t("log_parse_ok") if ok else t("log_parse_fail"), "ok" if ok else "err")
        self.update_status()
        if ok and open_after:
            self.on_open()
        return ok

    def on_open(self):
        _root, variant = self.root_and_variant()
        if not variant:
            messagebox.showerror(t("dlg_title"), t("err_no_variant"))
            return
        html = wow_install.out_files(variant)[1]
        if not html.is_file():
            messagebox.showinfo(t("dlg_title"), t("info_no_html", name=html.name))
            return
        if not webbrowser.open(html.as_uri()):
            self.write(t("log_browser_fail", path=html), "err")
        else:
            self.write(t("log_opened", path=html))

    def on_parse_open(self):
        self.on_parse(open_after=True)

    def on_export(self):
        ok, out, path = run_export()
        for line in out.strip().splitlines():
            self.write(line, None if ok else "err")
        if not ok:
            self.write(t("log_export_fail"), "err")
            messagebox.showerror(t("dlg_title"), out.strip())
            return
        self.write(t("log_export_ok"), "ok")
        try:
            if hasattr(os, "startfile"):
                os.startfile(str(path))  # Windows: default program (Excel)
            elif not webbrowser.open(path.as_uri()):
                self.write(t("log_file_open_fail", path=path), "err")
        except OSError as e:
            self.write(t("log_file_open_fail", path=e), "err")

    # ------------------------------------------------------------------ updates
    def check_updates(self, manual=False):
        if not app_info.REPO_CONFIRMED:
            if manual:
                messagebox.showinfo(t("dlg_title"), t("update_repo_placeholder"))
            return

        def worker():
            try:
                data = updater.fetch_latest_release()
            except urllib.error.HTTPError as exc:
                if exc.code == 404:   # no release published yet: nothing newer than this version
                    self._queue.put(("release", {}, manual))
                else:
                    self._queue.put(("update_error", str(exc), manual))
                return
            except Exception as exc:  # thread boundary: any failure (offline, rate limit ...) is reported, never raised
                self._queue.put(("update_error", str(exc), manual))
                return
            self._queue.put(("release", data, manual))

        threading.Thread(target=worker, daemon=True).start()

    def _poll_queue(self):
        try:
            while True:
                item = self._queue.get_nowait()
                kind = item[0]
                if kind == "release":
                    self._on_release(item[1], item[2])
                elif kind == "update_error":
                    if item[2]:  # silent at start (offline use is normal), loud when asked for
                        messagebox.showerror(t("dlg_title"), t("update_check_failed", error=item[1]))
                elif kind == "update_failed":
                    self.write(t("update_failed", error=item[1]), "err")
                elif kind == "apply":
                    self._apply_update(item[1])
        except queue.Empty:
            pass
        self.after(200, self._poll_queue)

    def _on_release(self, data, manual):
        tag = str(data.get("tag_name", "")).strip()
        if not app_info.is_newer(tag, app_info.APP_VERSION):
            if manual:
                messagebox.showinfo(t("dlg_title"), t("update_none", version=app_info.APP_VERSION))
            return
        can_apply = paths.is_frozen()
        if not can_apply:
            self.write(t("update_not_frozen", url=app_info.RELEASES_URL))
        choice = gui_dialogs.ask_update(self, str(data.get("name") or tag), app_info.APP_VERSION, can_apply)
        if choice == "update":
            self._start_update(data, tag)
        elif choice == "github":
            webbrowser.open(app_info.RELEASES_URL)

    def _start_update(self, data, tag):
        self.write(t("update_downloading", version=tag))

        def worker():
            zip_url = updater.resolve_release_asset(data, app_info.ZIP_ASSET_NAME)
            checksum_url = updater.resolve_release_asset(data, app_info.ZIP_CHECKSUM_ASSET_NAME)
            if not zip_url:
                self._queue.put(("update_failed", t("update_no_asset", asset=app_info.ZIP_ASSET_NAME)))
                return
            try:
                payload = updater.prepare_update(paths.base_dir(), zip_url, checksum_url)
            except (RuntimeError, OSError) as exc:
                self._queue.put(("update_failed", str(exc)))
                return
            self._queue.put(("apply", payload))

        threading.Thread(target=worker, daemon=True).start()

    def _apply_update(self, payload):
        self.write(t("update_applying"), "ok")
        try:
            updater.launch_helper(paths.base_dir(), payload, [os.getpid()], restart=True)
        except (RuntimeError, OSError) as exc:
            self.write(t("update_failed", error=exc), "err")
            return
        self.after(300, self.destroy)  # the helper waits for this process to exit

