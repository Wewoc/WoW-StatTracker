# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)
# What the window does to delete characters (actions.delete_chars): the copy first, all of it or nothing, the history page and the page afterwards, and what
# a problem before or after the deleting does. The deleting itself is tested in test_char_delete.py.

import sqlite3

import pytest

from app import actions, stat_parser
from game import wow_install
from pages import outputs, stat_history
from store import db_backup
from test_char_delete import A, B, counts, scans_of
from test_char_rules_pipeline import data_of
from test_data_contract import NEW_PARTS, scan_lua
from test_history_hook import res  # noqa: F401  (a fixture: the templates and a fake plotly.js)


def make(instance, history=False):
    """A database and page for Retail from a file with two characters (equipment, reputation, and two scans each)."""
    chars = ", ".join(f'["{key}"] = {NEW_PARTS.replace("2026-10-01", "2026-10-0" + str(n + 1))}' for n, key in enumerate((A, B)))
    older = ", ".join(f'["{key}"] = {{ {scan_lua("2026-09-30 10:00:00")} }}' for key in (A, B))
    lua = instance / "StatTracker.lua"
    lua.write_text('StatTrackerDB = { version = 4, meta = { [1] = { name = "x", cat = "y" } }, repMeta = { [2696] = { name = "Amani" } }, '
                   f'history = {{ {older} }}, chars = {{ {chars} }} }}', encoding="utf-8")
    db, page = wow_install.out_files("_retail_")
    args = ["--input", str(lua), "--db", str(db), "--output", str(page)]
    if history:
        args += ["--history-dir", str(wow_install.history_dir("_retail_"))]
    stat_parser.main(args)
    return db, page


def counts_of(db):
    conn = sqlite3.connect(db)
    try:
        return counts(conn)
    finally:
        conn.close()


def chars_on(page):
    return [c["key"] for c in data_of(page.read_text(encoding="utf-8"))["chars"]]


def test_without_a_database_nothing_is_deleted_and_nothing_is_created(instance):
    ok, out, deleted = actions.delete_chars("_retail_", [A])
    db, page = wow_install.out_files("_retail_")
    assert ok is False and "no database for this game version" in out and deleted == [] and not db.exists() and not page.exists()


def test_the_characters_are_deleted_after_a_copy_and_the_page_is_written_again_without_them(instance):
    db, page = make(instance)
    before = counts_of(db)
    ok, out, deleted = actions.delete_chars("_retail_", [A])
    assert ok is True and deleted == [A]
    after = counts_of(db)
    assert after["scans"] == before["scans"] - 2 and scans_of(sqlite3.connect(db), A) == 0 and scans_of(sqlite3.connect(db), B) == 2
    copies = sorted(db_backup.delete_dir(db).glob("*.pre-delete.bak"))
    assert len(copies) == 1
    held = sqlite3.connect(copies[0])
    try:
        assert counts(held) == before                                                  # the copy holds the state before
    finally:
        held.close()
    assert out.count("Backup:") == 2 and "1 characters deleted (2 scans): A-One" in out    # the copy of the day (init_db) and the one before deleting
    assert chars_on(page) == [B] and A not in page.read_text(encoding="utf-8")


def test_only_the_keys_the_database_has_are_deleted_and_the_ones_it_has_not_change_nothing(instance):
    db, page = make(instance)
    ok, out, deleted = actions.delete_chars("_retail_", ["Nobody-Here", A, "Nobody-Here", "", None, 5])
    assert ok is True and deleted == [A] and chars_on(page) == [B]
    again_before = counts_of(db)
    ok, out, deleted = actions.delete_chars("_retail_", [A, "Nobody-Here"])               # A-One is gone already
    assert ok is True and deleted == [] and "None of the characters is in the database" in out
    assert counts_of(db) == again_before and len(list(db_backup.delete_dir(db).glob("*.bak"))) == 1       # no second copy for nothing
    assert actions.delete_chars("_retail_", [])[2] == []


def test_the_history_pages_of_the_deleted_characters_go_and_the_others_stay_and_stay_linked(instance, res):
    db, page = make(instance, history=True)
    history = wow_install.history_dir("_retail_")
    assert sorted(path.name for path in history.glob("history-*.html")) == sorted([stat_history.page_name(A), stat_history.page_name(B)])
    ok, out, deleted = actions.delete_chars("_retail_", [A])
    assert ok is True and deleted == [A]
    assert sorted(path.name for path in history.glob("history-*.html")) == [stat_history.page_name(B)]
    assert list(data_of(page.read_text(encoding="utf-8"))["history"]["links"]) == [B]


@pytest.fixture
def copied(instance):
    """A database in which the copy of the day exists already (so that the next copy that is asked for is the one before deleting)."""
    db, page = make(instance)
    actions.delete_chars("_retail_", [])
    assert list((db.parent / "backups" / "daily").glob("*.bak"))
    return db, page


def unchanged(db, page, before, text):
    assert counts_of(db) == before and page.read_text(encoding="utf-8") == text
    assert not db_backup.delete_dir(db).exists() or not list(db_backup.delete_dir(db).glob("*.bak"))


def test_a_copy_that_cannot_be_written_stops_everything_before_the_first_change(copied, monkeypatch):
    db, page = copied
    before, text = counts_of(db), page.read_text(encoding="utf-8")

    def refuse(_conn, _target):
        raise db_backup.BackupError("disk full")
    monkeypatch.setattr(db_backup, "_write_copy", refuse)
    ok, out, deleted = actions.delete_chars("_retail_", [A])
    assert ok is False and deleted == [] and "backup of the database failed" in out and "nothing was changed" in out
    unchanged(db, page, before, text)


def test_a_damaged_database_gets_no_deleting(copied, monkeypatch):
    db, page = copied
    before, text = counts_of(db), page.read_text(encoding="utf-8")
    monkeypatch.setattr(db_backup, "damage", lambda _conn, limit=5: ["row 3 missing from index"])
    ok, out, deleted = actions.delete_chars("_retail_", [A])
    assert ok is False and deleted == [] and "integrity check" in out and "row 3 missing from index" in out
    unchanged(db, page, before, text)


def test_a_database_newer_than_the_program_is_not_touched(instance):
    db, page = make(instance)
    conn = sqlite3.connect(db)
    conn.execute("PRAGMA user_version = 999")
    conn.commit()
    conn.close()
    before, text = counts_of(db), page.read_text(encoding="utf-8")
    ok, out, deleted = actions.delete_chars("_retail_", [A])
    assert ok is False and deleted == [] and "999" in out
    unchanged(db, page, before, text)


def test_an_error_while_deleting_changes_nothing_and_is_said(copied, monkeypatch):
    db, page = copied
    before, text = counts_of(db), page.read_text(encoding="utf-8")

    def boom(_conn, _keys):
        raise sqlite3.OperationalError("boom")
    monkeypatch.setattr(actions.importer, "delete_chars", boom)
    ok, out, deleted = actions.delete_chars("_retail_", [A])
    assert ok is False and deleted == [] and "OperationalError: boom" in out
    assert counts_of(db) == before and page.read_text(encoding="utf-8") == text


def test_a_history_page_that_cannot_be_deleted_is_a_warning_and_the_characters_are_deleted(instance, res, monkeypatch):
    db, page = make(instance, history=True)

    def locked(_folder, _key):
        raise PermissionError("locked")
    monkeypatch.setattr(actions.stat_history, "remove_page", locked)
    ok, out, deleted = actions.delete_chars("_retail_", [A, B])
    assert ok is True and deleted == [A, B] and scans_of(sqlite3.connect(db), A) == 0
    assert "history page of A-One not deleted: locked" in out and "history page of B-Two not deleted: locked" in out       # the second one is tried too


def test_a_page_that_cannot_be_written_again_is_a_warning_and_the_keys_are_still_given_back(instance, monkeypatch):
    db, page = make(instance)

    def broken(*_args, **_kwargs):
        raise RuntimeError("boom")
    monkeypatch.setattr(actions.outputs, "rebuild_outputs", broken)
    ok, out, deleted = actions.delete_chars("_retail_", [A])
    assert ok is True and deleted == [A] and "WARNING: the page could not be written again after deleting: RuntimeError: boom" in out
    assert scans_of(sqlite3.connect(db), A) == 0                                          # they are gone, so the caller must keep them on the blacklist


def test_the_tiles_and_the_rules_reach_the_page_that_is_written_again(instance):
    db, page = make(instance)
    tiles = [{"stat": 2, "agg": "sum", "by": "all", "value": ""}]
    ok, out, deleted = actions.delete_chars("_retail_", [A], tiles, [{"type": "class", "value": "NOBODY"}])
    assert ok is True and data_of(page.read_text(encoding="utf-8"))["top5"] == tiles and chars_on(page) == [B]
    ok, out, deleted = actions.delete_chars("_retail_", [B], None, [{"type": "char", "value": B}])         # kept off the page as well: nothing left to show
    assert ok is True and deleted == [B] and chars_on(page) == []


def test_the_function_makes_the_page_with_rebuild_outputs_and_not_with_an_import(instance, monkeypatch):
    db, page = make(instance)
    seen = []
    real = outputs.rebuild_outputs
    monkeypatch.setattr(actions.outputs, "rebuild_outputs", lambda *a, **k: seen.append((a, k)) or real(*a, **k))
    actions.delete_chars("_retail_", [A], [], [])
    assert len(seen) == 1 and seen[0][0][0] == db and seen[0][1] == {"top5": [], "rules": []}
