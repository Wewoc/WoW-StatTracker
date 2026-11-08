# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)
# The data side of deleting characters from the database: importer.delete_chars (all or nothing), the copy before it (db_backup.delete_backup), the
# history page of a deleted character (stat_history.remove_page) and the blacklist that keeps the import from reading a deleted character again
# (importer.import_data(skip=...), the argument --skip, config.char_blacklist).

import json
import sqlite3
from datetime import datetime
from pathlib import Path

import pytest

from app import stat_parser
from store import db_backup, importer
from pages import stat_history
from test_data_contract import NEW_PARTS, scan_lua

A, B = "A-One", "B-Two"
TABLES = ("scans", "stat_values", "scan_gear", "scan_reputation", "stat_defs", "rep_defs")


def write_file(folder, keys=(A, B)):
    """StatTracker.lua with the characters `keys`: every one has equipment and a reputation list, A-One an older scan as well."""
    chars = ", ".join(f'["{key}"] = {NEW_PARTS.replace("2026-10-01", "2026-10-0" + str(n + 1))}' for n, key in enumerate(keys))
    history = f'history = {{ ["{A}"] = {{ {scan_lua("2026-09-30 10:00:00")} }} }},' if A in keys else ""
    path = folder / "StatTracker.lua"
    path.write_text('StatTrackerDB = { version = 4, meta = { [1] = { name = "x", cat = "y" } }, '
                    f'repMeta = {{ [2696] = {{ name = "Amani" }}, [2698] = {{ name = "Midnight" }} }}, {history} chars = {{ {chars} }} }}', encoding="utf-8")
    return path


def run(folder, lua, *extra):
    stat_parser.main(["--input", str(lua), "--db", str(folder / "wow_stats.db"), "--output", str(folder / "stats.html"), *extra])


@pytest.fixture
def database(tmp_path):
    lua = write_file(tmp_path)
    run(tmp_path, lua)
    conn = sqlite3.connect(tmp_path / "wow_stats.db")
    yield SimpleNamespace(conn=conn, folder=tmp_path, lua=lua, db=tmp_path / "wow_stats.db")
    conn.close()


class SimpleNamespace:
    def __init__(self, **fields):
        self.__dict__.update(fields)


def counts(conn):
    return {table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in TABLES}


def scans_of(conn, key):
    return conn.execute("SELECT COUNT(*) FROM scans WHERE char_key = ?", (key,)).fetchone()[0]


def rows_of(conn, key):
    """The rows of every table that belong to the scans of this character."""
    ids = "(SELECT scan_id FROM scans WHERE char_key = ?)"
    return {table: conn.execute(f"SELECT COUNT(*) FROM {table} WHERE scan_id IN {ids}", (key,)).fetchone()[0]
            for table in ("stat_values", "scan_gear", "scan_reputation")}


# ---------------------------------------------------------------- deleting
def test_deleting_a_character_removes_all_its_scans_and_everything_that_hangs_on_them(database):
    conn = database.conn
    assert scans_of(conn, A) == 2 and all(rows_of(conn, A).values()) and all(rows_of(conn, B).values())
    before, rows_b = counts(conn), rows_of(conn, B)
    assert importer.delete_chars(conn, [A]) == 2
    assert scans_of(conn, A) == 0 and rows_of(conn, A) == {"stat_values": 0, "scan_gear": 0, "scan_reputation": 0}
    assert scans_of(conn, B) == 1 and rows_of(conn, B) == rows_b                      # the other character is untouched
    after = counts(conn)
    assert after["stat_defs"] == before["stat_defs"] and after["rep_defs"] == before["rep_defs"]      # the names belong to no character
    assert conn.execute("SELECT COUNT(*) FROM stat_values WHERE scan_id NOT IN (SELECT scan_id FROM scans)").fetchone()[0] == 0     # nothing is left hanging


def test_nothing_is_written_for_a_key_the_database_does_not_have_and_what_is_no_key_is_ignored(database):
    before = counts(database.conn)
    assert importer.delete_chars(database.conn, ["Nobody-Here"]) == 0
    assert importer.delete_chars(database.conn, []) == 0 and importer.delete_chars(database.conn, None) == 0
    assert importer.delete_chars(database.conn, [None, 5, ["A-One"]]) == 0
    assert counts(database.conn) == before


def test_several_characters_and_a_key_given_twice_are_deleted_in_one_go(database):
    assert importer.delete_chars(database.conn, [A, B, A]) == 3
    assert counts(database.conn)["scans"] == 0 and counts(database.conn)["stat_values"] == 0


def test_an_error_while_deleting_leaves_the_database_as_it_was(database):
    class Fails:
        """The connection, but the delete of the reputation of B-Two fails: A-One has been deleted by then."""

        def __init__(self, conn):
            self.conn = conn

        def execute(self, sql, params=()):
            if "scan_reputation" in sql and params == (B,):
                raise sqlite3.OperationalError("boom")
            return self.conn.execute(sql, params)

        def commit(self):
            self.conn.commit()

        def rollback(self):
            self.conn.rollback()
    before = counts(database.conn)
    with pytest.raises(sqlite3.OperationalError, match="boom"):
        importer.delete_chars(Fails(database.conn), [A, B])
    assert counts(database.conn) == before                                              # all or nothing
    database.conn.close()
    reopened = sqlite3.connect(database.db)
    try:
        assert counts(reopened) == before and scans_of(reopened, A) == 2                # and it was not committed behind the back
    finally:
        reopened.close()


def test_a_character_that_was_deleted_comes_back_with_the_next_import_unless_it_is_on_the_blacklist(database):
    importer.delete_chars(database.conn, [A])
    database.conn.close()
    run(database.folder, database.lua)
    again = sqlite3.connect(database.db)
    try:
        assert scans_of(again, A) == 2                                                  # that is why the blacklist exists
        importer.delete_chars(again, [A])
    finally:
        again.close()
    run(database.folder, database.lua, "--skip", json.dumps([A]))
    kept = sqlite3.connect(database.db)
    try:
        assert scans_of(kept, A) == 0 and scans_of(kept, B) == 1
    finally:
        kept.close()


# ---------------------------------------------------------------- the copy before
def test_the_copy_before_deleting_holds_the_database_as_it_is_and_is_never_rotated(database):
    folder = database.folder
    stamp = datetime(2026, 11, 8, 15, 30, 5)
    target = db_backup.delete_backup(database.conn, database.db, now=stamp)
    assert target == folder / "backups" / "delete" / "wow_stats.20261108-153005.pre-delete.bak"
    copy = sqlite3.connect(target)
    try:
        assert counts(copy) == counts(database.conn)
    finally:
        copy.close()
    importer.delete_chars(database.conn, [A, B])
    assert counts(sqlite3.connect(target))["scans"] == 3                                 # the copy keeps what was deleted afterwards
    assert db_backup.delete_backup(database.conn, database.db, now=stamp) == target       # the same second: the copy of that very state
    other = db_backup.delete_backup(database.conn, database.db, now=datetime(2026, 11, 8, 15, 31, 0))
    assert other != target and target.exists() and other.exists()
    for day in range(1, 12):                                                            # the rotation of the daily copies never touches it
        daily = folder / "backups" / "daily"
        daily.mkdir(parents=True, exist_ok=True)
        (daily / f"wow_stats.2026-10-{day:02d}.bak").write_bytes(b"x")
    db_backup.rotate(database.db)
    assert target.exists() and other.exists()


def test_a_damaged_database_gets_no_copy_and_so_nothing_may_be_deleted(tmp_path):
    class Broken:
        def execute(self, *_args):
            raise sqlite3.DatabaseError("database disk image is malformed")
    with pytest.raises(db_backup.DamagedDatabase):
        db_backup.delete_backup(Broken(), tmp_path / "wow_stats.db")
    assert not (tmp_path / "backups").exists()


def test_a_copy_that_cannot_be_written_is_an_error(database, monkeypatch):
    def refuse(_conn, _target):
        raise db_backup.BackupError("disk full")
    monkeypatch.setattr(db_backup, "_write_copy", refuse)
    with pytest.raises(db_backup.BackupError, match="disk full"):
        db_backup.delete_backup(database.conn, database.db)


# ---------------------------------------------------------------- the history page of a deleted character
def test_the_history_page_of_a_character_is_deleted_by_its_exact_name_only(tmp_path):
    page, other, notes = tmp_path / stat_history.page_name(A), tmp_path / "history-A_One-deadbeef.html", tmp_path / "notes.txt"
    for path in (page, other, notes):
        path.write_text("x", encoding="utf-8")
    assert stat_history.remove_page(tmp_path, A) is True
    assert not page.exists() and other.exists() and notes.exists()
    assert stat_history.remove_page(tmp_path, A) is False and stat_history.remove_page(tmp_path / "missing", A) is False


def test_a_history_page_that_cannot_be_deleted_is_an_error_for_the_caller(tmp_path, monkeypatch):
    page = tmp_path / stat_history.page_name(A)
    page.write_text("x", encoding="utf-8")

    def locked(self, *args, **kwargs):
        raise PermissionError("locked")
    monkeypatch.setattr(Path, "unlink", locked)
    with pytest.raises(PermissionError):
        stat_history.remove_page(tmp_path, A)


# ---------------------------------------------------------------- the blacklist in the import
def stored(folder):
    conn = sqlite3.connect(folder / "wow_stats.db")
    try:
        return sorted(row[0] for row in conn.execute("SELECT DISTINCT char_key FROM scans"))
    finally:
        conn.close()


def test_the_import_does_not_store_a_character_on_the_blacklist_and_says_so(tmp_path, capsys):
    run(tmp_path, write_file(tmp_path), "--skip", json.dumps([A]))
    out = capsys.readouterr().out
    assert stored(tmp_path) == [B] and "1 characters are on the list of deleted ones and were not imported: A-One" in out
    run(tmp_path, write_file(tmp_path))
    assert stored(tmp_path) == [A, B]                                                   # no blacklist: it is stored


def test_the_import_with_a_blacklist_that_names_every_character_stores_none_and_does_not_fail(tmp_path):
    run(tmp_path, write_file(tmp_path), "--skip", json.dumps([A, B]))
    assert stored(tmp_path) == []
    assert (tmp_path / "stats.html").is_file()


def test_a_blacklist_that_is_no_json_is_a_warning_and_the_characters_are_stored(tmp_path, capsys):
    run(tmp_path, write_file(tmp_path), "--skip", "{not json")
    assert stored(tmp_path) == [A, B]
    assert "WARNING: the list of deleted characters is not valid JSON and is not applied" in capsys.readouterr().out


def test_a_blacklist_that_is_no_list_or_holds_no_keys_leaves_everything_in(tmp_path, capsys):
    run(tmp_path, write_file(tmp_path), "--skip", json.dumps({"A-One": 1}))
    assert stored(tmp_path) == [A, B]
    run(tmp_path, write_file(tmp_path), "--skip", json.dumps([None, 5, "", ["A-One"]]))
    assert stored(tmp_path) == [A, B] and "list of deleted characters" not in capsys.readouterr().out       # the shape is only checked, no warning


def test_the_scans_of_a_blacklisted_character_are_still_checked(tmp_path):
    lua = write_file(tmp_path)
    lua.write_text(lua.read_text(encoding="utf-8").replace('["A-One"] = { scannedAt', '["A-One"] = { broken = 1, nothing', 1), encoding="utf-8")
    with pytest.raises(SystemExit):                                                      # a file that is wrong is wrong whatever the blacklist says
        run(tmp_path, lua, "--skip", json.dumps([A]))
    assert not (tmp_path / "wow_stats.db").exists() or stored(tmp_path) == []


def test_skipped_keys_names_the_blacklisted_characters_of_the_file_sorted():
    db = {"chars": {B: {}, A: {}, "C-Three": {}}}
    assert importer.skipped_keys(db, [B, "Nobody-Here", A]) == [A, B]
    assert importer.skipped_keys(db, []) == [] and importer.skipped_keys(db, None) == [] and importer.skipped_keys({}, [A]) == []
    assert importer.skipped_keys({"chars": "x"}, [A]) == [] and importer.skipped_keys(None, [A]) == []


def test_the_notes_about_the_age_of_the_data_ignore_a_blacklisted_character():
    db = {"chars": {A: {"scannedAt": "2026-10-01 10:00:00"}, B: {"scannedAt": "2026-10-20 10:00:00"}}}
    now = datetime(2026, 10, 30, 12, 0, 0)
    assert "2026-10-20 10:00:00" in importer.import_notes(db, {}, 0, now=now)[0]
    assert "2026-10-01 10:00:00" in importer.import_notes(db, {}, 0, now=now, skip=[B])[0]     # only A-One counts: it is older
    assert importer.import_notes(db, {}, 0, now=now, skip=[A, B]) == []                         # nothing left to say


def test_deleting_is_the_only_new_write_of_the_importer_and_the_modules_stay_in_their_folders():
    """The write table of tests/test_architecture.py allows the importer 'commit', the backup module 'unlink' and 'mkdir', stat_history 'unlink'."""
    from test_architecture import ALLOWED_WRITES
    assert ALLOWED_WRITES["importer"] == {"commit"} and "unlink" in ALLOWED_WRITES["stat_history"] and "mkdir" in ALLOWED_WRITES["db_backup"]
