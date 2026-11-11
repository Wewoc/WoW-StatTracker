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
from pathlib import Path

from app import stat_parser
from core import app_info
from core import paths
from core import updater
from core.i18n import t
from export import export_xlsx
from game import wow_install
from pages import outputs, page_payload, stat_history
from pages.blocks import top5
from rules import char_names, char_rules
from store import db_backup, db_schema, importer


def run_parser(sv_file, db_path, html_path, history_dir=None, icons_dir=None, game_dir=None, product=None, top5=None, rules=None, skip=None):
    """Runs stat_parser.main() and returns (ok, output_text). history_dir: where the history pages go
    (none are made if it is not given). icons_dir: the folder whose item icons the pages show; with game_dir
    (the WoW folder) and product as well, the import also reads the icons it lacks from the game files. top5: the tiles of the
    Top 5 block (config.top5, a list; the page has none if it is empty or not given). rules: the rules of this game version that keep characters off
    the stats page (config.char_rules[variant], a list; nobody is kept off if it is empty or not given). skip: the keys of the characters that were deleted
    on purpose (config.char_blacklist[variant], a list): the import does not store them (none are left out if it is empty or not given)."""
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
    if rules:
        args += ["--hide", json.dumps(rules, ensure_ascii=False)]
    if skip:
        args += ["--skip", json.dumps(skip, ensure_ascii=False)]
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


def tile_choices(variant, rules=None):
    """What the settings of the Top 5 offer for the data of this game version (top5.choices on a payload made from its database, in the language of the
    program), or None when there is no database yet. `rules`: the rules that keep characters off the page (a character they name is not offered);
    without them every character is. A database newer than this program raises SystemExit with the usual message."""
    db_path = wow_install.out_files(variant)[0]
    if not db_path.is_file():
        return None
    conn = stat_history.open_readonly(db_path)
    try:
        return top5.choices(page_payload.build_payload(conn, rules=rules))
    finally:
        conn.close()


def ignore_choices(variant):
    """What the settings for the characters kept off the outputs offer for the data of this game version, read from its database **without** any rule (a
    character or group that a rule keeps off could not be taken back otherwise): {"values": {"char" / "class" / "race" / "faction" / "realm": [(value,
    label)]}, "chars": the characters as the page has them (key, level, faction, class and race file name ...)}, or None when there is no database yet.
    A database newer than this program raises SystemExit with the usual message."""
    db_path = wow_install.out_files(variant)[0]
    if not db_path.is_file():
        return None
    conn = stat_history.open_readonly(db_path)
    try:
        payload = page_payload.build_payload(conn)
        return {"values": top5.choices(payload)["values"], "chars": payload["chars"]}
    finally:
        conn.close()


def rebuild_page(variant, top5_tiles, rules=None):
    """Writes the stats page of this game version again from its database with these tiles and these rules for the characters kept off the page
    (outputs.rebuild_outputs: no import, nothing written to the database): returns (ok, output text)."""
    buf = io.StringIO()
    db_path, html_path = wow_install.out_files(variant)
    try:
        _payload, lines = outputs.rebuild_outputs(db_path, html_path, wow_install.history_dir(variant), wow_install.icons_dir(variant), top5=top5_tiles, rules=rules)
        buf.write("".join(line + "\n" for line in lines))
        return True, buf.getvalue()
    except SystemExit as e:                  # a database newer than this program
        return False, f"{e.code}\n"
    except sqlite3.OperationalError as e:    # no database
        return False, t("log_parse_unexpected", error=f"{type(e).__name__}: {e}") + "\n"
    except Exception as e:  # unexpected: show loudly, never swallow
        return False, t("log_parse_unexpected", error=f"{type(e).__name__}: {e}") + "\n"


def rebuild_pages(jobs):
    """Writes the stats pages of several game versions again (rebuild_page for each): `jobs` is [(game version, tiles, rules)], the result
    [(game version, ok, output text)] in the same order. One version that fails never stops the others, and nothing is raised: whatever goes
    wrong becomes the text of its entry (the window runs this in a thread and must always get an answer)."""
    results = []
    for variant, tiles, rules in jobs:
        try:
            ok, text = rebuild_page(variant, tiles, rules)
        except Exception as e:  # rebuild_page catches almost everything itself; this is the net below it
            ok, text = False, t("log_parse_unexpected", error=f"{type(e).__name__}: {e}") + "\n"
        results.append((variant, ok, text))
    return results


def delete_chars(variant, keys, top5_tiles=None, rules=None):
    """Deletes characters from the database of this game version, for good, and returns (ok, output text, the keys that were deleted). In this order: the
    database is opened (db_schema.init_db: the copy of the day, a migration if it is old, a newer one stops here), the keys it does not have are left out,
    a copy is made (db_backup.delete_backup), the scans are deleted in one transaction (importer.delete_chars), the history pages of the characters are
    removed and the page is written again with `top5_tiles` and `rules`. `ok` is False only when nothing was deleted (no database, a damaged or too
    new one, no copy possible, an error while deleting: all of them have changed nothing); a problem after the deleting is a warning in the text, the
    characters are gone and the keys come back. The caller puts the keys on the blacklist (config.char_blacklist) BEFORE it calls this and takes them off
    again when `ok` is False: a deleted character would come back with the next import otherwise. Runs in a thread; no widget is touched."""
    buf = io.StringIO()
    db_path, html_path = wow_install.out_files(variant)
    if not db_path.is_file():
        return False, t("del_err_no_db") + "\n", []
    wanted = list(dict.fromkeys(key for key in keys or () if isinstance(key, str) and key))
    try:
        with contextlib.redirect_stdout(buf):
            conn = db_schema.init_db(db_path)
        try:
            known = {row[0] for row in conn.execute("SELECT DISTINCT char_key FROM scans")}
            present = [key for key in wanted if key in known]
            if not present:
                buf.write(t("del_note_none") + "\n")
                return True, buf.getvalue(), []
            try:
                copy = db_backup.delete_backup(conn, db_path)
            except db_backup.DamagedDatabase as exc:
                found = "; ".join(exc.problems)
                return False, buf.getvalue() + t("parse_err_db_damaged", folder=db_backup.daily_dir(db_path).parent, found=found) + "\n", []
            except db_backup.BackupError as exc:
                return False, buf.getvalue() + t("parse_err_backup_failed", error=exc) + "\n", []
            buf.write(t("parse_out_backup", path=copy) + "\n")
            scans = importer.delete_chars(conn, present)
        finally:
            conn.close()
    except SystemExit as exc:                    # a database newer than this program
        return False, buf.getvalue() + f"{exc.code}\n", []
    except Exception as exc:  # unexpected: show loudly, never swallow (the deleting was one transaction: nothing changed)
        return False, buf.getvalue() + t("log_parse_unexpected", error=f"{type(exc).__name__}: {exc}") + "\n", []
    buf.write(t("del_out_deleted", count=len(present), scans=scans, keys=", ".join(present)) + "\n")
    history_dir = wow_install.history_dir(variant)
    for key in present:
        try:
            stat_history.remove_page(history_dir, key)
        except OSError as exc:
            buf.write(t("del_warn_page_remove", key=key, error=exc) + "\n")
    try:
        _payload, lines = outputs.rebuild_outputs(db_path, html_path, history_dir, wow_install.icons_dir(variant), top5=top5_tiles, rules=rules)
        buf.write("".join(line + "\n" for line in lines))
    except (SystemExit, Exception) as exc:
        buf.write(t("del_warn_page", error=exc.code if isinstance(exc, SystemExit) else f"{type(exc).__name__}: {exc}") + "\n")
    return True, buf.getvalue(), present


def write_snapshot(view, variant):
    """Writes the snapshot of the stats page of `view` (what the window shows now) for this game version and returns its path."""
    path = wow_install.snapshot_file(variant)
    outputs.write_snapshot(view, path, datetime.now().strftime("%Y-%m-%d %H:%M"))
    return path


def run_export(rules_by_variant=None):
    """Runs export_xlsx.export() and returns (ok, output_text, xlsx_path). rules_by_variant: {game version: rules} (config.char_rules): the characters
    the rules of a version keep out of the Excel file (target "excel") are left out of the sheet of that version, found by the name of its database
    file (wow_install.out_files); a database without rules keeps every character."""
    buf = io.StringIO()
    out = export_xlsx.default_out()
    ok = True
    rules_by_db = {wow_install.out_files(variant)[0].name: rules for variant, rules in (rules_by_variant or {}).items() if rules}

    def hidden(db_path, chars):
        return char_rules.hidden_keys(chars, rules_by_db.get(Path(db_path).name), "excel")
    try:
        buf.write("\n".join(export_xlsx.export(out, hidden=hidden if rules_by_db else None, label=lambda c: char_names.display(c["key"], c.get("surname")))) + "\n")
    except SystemExit as e:
        ok = False
        buf.write(str(e.code) + "\n")
    except Exception as e:  # unexpected: show loudly, never swallow
        ok = False
        buf.write(t("log_parse_unexpected", error=f"{type(e).__name__}: {e}") + "\n")
    return ok, buf.getvalue(), out


def import_saved_variables(sv_file, root, variant, read_icons, top5=None, rules=None, skip=None):
    """Reads the SavedVariables file of one game version into its database and pages: returns (ok, output).
    The icons already in data/ are always shown; the game files are read only with the option on (and a known product). top5: the tiles of the
    Top 5 block (the settings of the window). rules: the rules of this game version that keep characters off the stats page (the settings of the window).
    skip: the keys of the characters of this game version that were deleted on purpose and are not read again (the settings of the window)."""
    db_path, html_path = wow_install.out_files(variant)
    product = wow_install.VARIANT_PRODUCT.get(variant) if read_icons else None
    return run_parser(sv_file, db_path, html_path, wow_install.history_dir(variant),
                      wow_install.icons_dir(variant), root if product else None, product, top5=top5, rules=rules, skip=skip)


def import_all(jobs):
    """Reads the SavedVariables file of several game versions (import_saved_variables for each): `jobs` is [(game version, data file, game folder,
    read_icons, tiles, rules, skip)], the result [(game version, ok, output text)] in the same order. One version that fails never stops the others,
    and nothing is raised: whatever goes wrong becomes the text of its entry (the window runs this in a thread and must always get an answer)."""
    results = []
    for variant, sv_file, root, read_icons, tiles, rules, skip in jobs:
        try:
            ok, text = import_saved_variables(sv_file, root, variant, read_icons, tiles, rules, skip)
        except Exception as e:  # run_parser catches almost everything itself; this is the net below it
            ok, text = False, t("log_parse_unexpected", error=f"{type(e).__name__}: {e}") + "\n"
        results.append((variant, ok, text))
    return results


def other_accounts(root, variant, account):
    """The other accounts of this game version that have a data file of their own (they are not read)."""
    return [a for a in wow_install.list_accounts(root / variant)
            if a != account and wow_install.saved_vars_path(root / variant, a).is_file()]


def status_parts(root, variants, account, variant):
    """The parts of the status line for a usable game folder (the window joins them): the game folder; for every game version that is read, whether
    it has the data file of the account and when it was written; the state of the addon in `variant`, the game version the addon buttons act on."""
    parts = [t("status_game", path=root)]
    if not account:
        parts.append(t("status_no_account"))
    elif variants:
        items = []
        for name in variants:
            sv = wow_install.saved_vars_path(root / name, account)
            if sv.is_file():
                items.append(t("status_data_item", variant=name, ts=datetime.fromtimestamp(sv.stat().st_mtime).strftime("%Y-%m-%d %H:%M")))
            else:
                items.append(t("status_data_item_missing", variant=name))
        parts.append(t("status_data_all", items=" · ".join(items)))
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
