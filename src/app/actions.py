#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)
# actions.py
# StatTracker - what the main window does, without any widget: run the import (run_parser), the Excel export
# (run_export), the status line, the update check and the update download. The window (Qt, src/app/main_window.py)
# only shows the results and runs the slow parts in threads. Moved out of the Tk window; the rules are unchanged.

import contextlib
import io
import json
import sqlite3
import urllib.error
from datetime import datetime

from app import stat_parser
from core import app_info
from core import paths
from core import updater
from core.i18n import t
from export import export_xlsx
from game import wow_install
from pages import outputs, page_payload, stat_history
from pages.blocks import top5


def run_parser(sv_file, db_path, html_path, history_dir=None, icons_dir=None, game_dir=None, product=None, top5=None):
    """Runs stat_parser.main() and returns (ok, output_text). history_dir: where the history pages go
    (none are made if it is not given). icons_dir: the folder whose item icons the pages show; with game_dir
    (the WoW folder) and product as well, the import also reads the icons it lacks from the game files. top5: the tiles of the
    Top 5 block (config.top5, a list; the page has none if it is empty or not given)."""
    buf = io.StringIO()
    ok = True
    args = ["--input", str(sv_file), "--db", str(db_path), "--output", str(html_path)]
    if history_dir:
        args += ["--history-dir", str(history_dir)]
        if icons_dir:
            args += ["--icons-dir", str(icons_dir)]
            if game_dir and product:
                args += ["--game-dir", str(game_dir), "--product", str(product)]
    if top5:
        args += ["--top5", json.dumps(top5, ensure_ascii=False)]
    try:
        with contextlib.redirect_stdout(buf):
            stat_parser.main(args)
    except SystemExit as e:
        if e.code not in (None, 0):
            ok = False
            buf.write(str(e.code) + "\n")
    except Exception as e:  # unexpected: show loudly, never swallow
        ok = False
        buf.write(t("log_parse_unexpected", error=f"{type(e).__name__}: {e}") + "\n")
    return ok, buf.getvalue()


def tile_choices(variant):
    """What the settings of the Top 5 offer for the data of this game version (top5.choices on a payload made from its database, in the language of the
    program), or None when there is no database yet. A database newer than this program raises SystemExit with the usual message."""
    db_path = wow_install.out_files(variant)[0]
    if not db_path.is_file():
        return None
    conn = stat_history.open_readonly(db_path)
    try:
        return top5.choices(page_payload.build_payload(conn))
    finally:
        conn.close()


def rebuild_page(variant, top5_tiles):
    """Writes the stats page of this game version again from its database with these tiles (outputs.rebuild_outputs: no import, nothing written to the
    database): returns (ok, output text)."""
    buf = io.StringIO()
    db_path, html_path = wow_install.out_files(variant)
    try:
        _payload, lines = outputs.rebuild_outputs(db_path, html_path, wow_install.history_dir(variant), wow_install.icons_dir(variant), top5=top5_tiles)
        buf.write("".join(line + "\n" for line in lines))
        return True, buf.getvalue()
    except SystemExit as e:                  # a database newer than this program
        return False, f"{e.code}\n"
    except sqlite3.OperationalError as e:    # no database
        return False, t("log_parse_unexpected", error=f"{type(e).__name__}: {e}") + "\n"
    except Exception as e:  # unexpected: show loudly, never swallow
        return False, t("log_parse_unexpected", error=f"{type(e).__name__}: {e}") + "\n"


def write_snapshot(view, variant):
    """Writes the snapshot of the stats page of `view` (what the window shows now) for this game version and returns its path."""
    path = wow_install.snapshot_file(variant)
    outputs.write_snapshot(view, path, datetime.now().strftime("%Y-%m-%d %H:%M"))
    return path


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


def import_saved_variables(sv_file, root, variant, read_icons, top5=None):
    """Reads the SavedVariables file of one game version into its database and pages: returns (ok, output).
    The icons already in data/ are always shown; the game files are read only with the option on (and a known product). top5: the tiles of the
    Top 5 block (the settings of the window)."""
    db_path, html_path = wow_install.out_files(variant)
    product = wow_install.VARIANT_PRODUCT.get(variant) if read_icons else None
    return run_parser(sv_file, db_path, html_path, wow_install.history_dir(variant),
                      wow_install.icons_dir(variant), root if product else None, product, top5=top5)


def other_accounts(root, variant, account):
    """The other accounts of this game version that have a data file of their own (they are not read)."""
    return [a for a in wow_install.list_accounts(root / variant)
            if a != account and wow_install.saved_vars_path(root / variant, a).is_file()]


def status_parts(root, variant, account):
    """The parts of the status line for a usable game folder and version (the window joins them)."""
    parts = [t("status_game", path=root / variant)]
    if account:
        sv = wow_install.saved_vars_path(root / variant, account)
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
    return parts


def fetch_release():
    """The latest release for the update check, as a queue message: ("release", data) (data is {} when no release is
    published yet: nothing newer than this version) or ("update_error", text)."""
    try:
        data = updater.fetch_latest_release()
    except urllib.error.HTTPError as exc:
        if exc.code == 404:   # no release published yet: nothing newer than this version
            return ("release", {})
        return ("update_error", str(exc))
    except Exception as exc:  # thread boundary: any failure (offline, rate limit ...) is reported, never raised
        return ("update_error", str(exc))
    return ("release", data)


def download_update(data):
    """Downloads and checks the update of a release, as a queue message: ("apply", payload) or ("update_failed", text)."""
    try:
        zip_url = updater.resolve_release_asset(data, app_info.ZIP_ASSET_NAME)
        checksum_url = updater.resolve_release_asset(data, app_info.ZIP_CHECKSUM_ASSET_NAME)
        if not zip_url:
            return ("update_failed", t("update_no_asset", asset=app_info.ZIP_ASSET_NAME))
        payload = updater.prepare_update(paths.base_dir(), zip_url, checksum_url)
    except (RuntimeError, OSError) as exc:
        return ("update_failed", str(exc))
    except Exception as exc:  # thread boundary: a worker that dies silently leaves the update flag set
        return ("update_failed", f"{type(exc).__name__}: {exc}")
    return ("apply", payload)
