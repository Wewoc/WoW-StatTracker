# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)
# Copies of the statistics database: a daily copy that rotates and a migration copy that stays,
# each in its own folder; a copy is whole or absent; a failure is a BackupError and leaves the
# original untouched. The second half: init_db takes them (once a day, always before a migration,
# never for a new or a too new database) and stops before the first change if it cannot.

import ast
import hashlib
import sqlite3
from datetime import date, datetime
from pathlib import Path

import pytest

import db_backup
import export_xlsx
import stat_parser
from db_backup import BackupError

SRC = Path(db_backup.__file__).parent
DAY = date(2026, 10, 31)


def make_db(path, user_version=1, scans=3):
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE scans (scan_id INTEGER PRIMARY KEY, char_key TEXT NOT NULL)")
    conn.executemany("INSERT INTO scans(char_key) VALUES (?)", [(f"Char{i}-Realm",) for i in range(scans)])
    conn.execute(f"PRAGMA user_version = {user_version}")
    conn.commit()
    return conn


def content(path):
    conn = sqlite3.connect(path)
    try:
        return (conn.execute("SELECT COUNT(*) FROM scans").fetchone()[0],
                conn.execute("PRAGMA user_version").fetchone()[0])
    finally:
        conn.close()


def names(folder):
    return sorted(p.name for p in folder.iterdir()) if folder.is_dir() else []


def touch_days(folder, stem, days):
    folder.mkdir(parents=True, exist_ok=True)
    for day in days:
        (folder / f"{stem}.2026-10-{day:02d}.bak").write_bytes(b"x")


def test_daily_backup_is_a_readable_copy_in_the_daily_folder(tmp_path):
    db = tmp_path / "wow_stats.db"
    conn = make_db(db, user_version=1, scans=3)
    target = db_backup.daily_backup(conn, db, today=DAY)
    conn.close()
    assert target == tmp_path / "backups" / "daily" / "wow_stats.2026-10-31.bak"
    assert content(target) == (3, 1)
    assert names(tmp_path / "backups" / "migration") == []


def test_a_second_daily_backup_on_the_same_day_makes_nothing(tmp_path):
    db = tmp_path / "wow_stats.db"
    conn = make_db(db, scans=1)
    first = db_backup.daily_backup(conn, db, today=DAY)
    conn.execute("INSERT INTO scans(char_key) VALUES ('Later-Realm')")
    conn.commit()
    assert db_backup.daily_backup(conn, db, today=DAY) is None
    assert content(first) == (1, 1)                     # still the state before the first import
    next_day = db_backup.daily_backup(conn, db, today=date(2026, 11, 1))
    conn.close()
    assert next_day.name == "wow_stats.2026-11-01.bak" and content(next_day) == (2, 1)


def test_migration_backup_goes_to_its_own_folder_and_holds_the_old_state(tmp_path):
    db = tmp_path / "wow_stats.db"
    conn = make_db(db, user_version=1)
    target = db_backup.migration_backup(conn, db, 2, now=datetime(2026, 10, 31, 14, 25, 1))
    conn.close()
    assert target == tmp_path / "backups" / "migration" / "wow_stats.20261031-142501.pre-v2.bak"
    assert content(target) == (3, 1)
    assert names(tmp_path / "backups" / "daily") == []


def test_migration_backup_is_written_every_time(tmp_path):
    db = tmp_path / "wow_stats.db"
    conn = make_db(db)
    db_backup.daily_backup(conn, db, today=DAY)
    first = db_backup.migration_backup(conn, db, 2, now=datetime(2026, 10, 31, 14, 25, 1))
    second = db_backup.migration_backup(conn, db, 2, now=datetime(2026, 10, 31, 14, 26, 0))
    conn.close()
    assert first != second and first.exists() and second.exists()


def test_rotate_keeps_the_newest_seven_and_touches_nothing_else(tmp_path):
    db = tmp_path / "wow_stats.db"
    daily = tmp_path / "backups" / "daily"
    migration = tmp_path / "backups" / "migration"
    touch_days(daily, "wow_stats", range(1, 11))                 # 10 daily copies
    touch_days(daily, "wow_stats_anniversary", range(1, 4))      # another database
    (daily / "notes.txt").write_bytes(b"x")
    (daily / "wow_stats.20261031-142501.pre-v2.bak").write_bytes(b"x")   # wrong folder, not a daily name
    (daily / "wow_stats.2026-10-05.bak.part").write_bytes(b"x")
    touch_days(migration, "wow_stats", range(1, 11))             # more than seven, must stay
    before_migration = names(migration)

    assert db_backup.rotate(db) == []

    left = [n for n in names(daily) if n.startswith("wow_stats.2026-10-") and n.endswith(".bak")]
    assert left == [f"wow_stats.2026-10-{d:02d}.bak" for d in range(4, 11)]
    assert len([n for n in names(daily) if n.startswith("wow_stats_anniversary")]) == 3
    assert {"notes.txt", "wow_stats.20261031-142501.pre-v2.bak",
            "wow_stats.2026-10-05.bak.part"} <= set(names(daily))
    assert names(migration) == before_migration


def test_rotate_with_fewer_copies_than_the_limit_deletes_nothing(tmp_path):
    db = tmp_path / "wow_stats.db"
    touch_days(tmp_path / "backups" / "daily", "wow_stats", range(1, 4))
    assert db_backup.rotate(db) == []
    assert len(names(tmp_path / "backups" / "daily")) == 3


def test_rotate_without_a_folder_is_quiet(tmp_path):
    assert db_backup.rotate(tmp_path / "wow_stats.db") == []


def test_rotate_reports_a_file_it_cannot_delete_and_goes_on(tmp_path, monkeypatch):
    db = tmp_path / "wow_stats.db"
    daily = tmp_path / "backups" / "daily"
    touch_days(daily, "wow_stats", range(1, 10))
    real_unlink = Path.unlink

    def stubborn(self, *args, **kwargs):
        if self.name == "wow_stats.2026-10-01.bak":
            raise PermissionError("in use")
        return real_unlink(self, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", stubborn)
    failed = db_backup.rotate(db)
    assert failed == [daily / "wow_stats.2026-10-01.bak"]
    assert "wow_stats.2026-10-02.bak" not in names(daily)


def test_an_unfinished_part_file_is_removed_by_the_next_backup(tmp_path):
    db = tmp_path / "wow_stats.db"
    daily = tmp_path / "backups" / "daily"
    daily.mkdir(parents=True)
    (daily / "wow_stats.2026-10-30.bak.part").write_bytes(b"cut off")
    (daily / "wow_stats_anniversary.2026-10-30.bak.part").write_bytes(b"other database")
    conn = make_db(db)
    db_backup.daily_backup(conn, db, today=DAY)
    conn.close()
    assert names(daily) == ["wow_stats.2026-10-31.bak", "wow_stats_anniversary.2026-10-30.bak.part"]


def test_a_folder_that_cannot_be_made_is_a_backup_error_and_the_original_is_untouched(tmp_path):
    db = tmp_path / "wow_stats.db"
    conn = make_db(db)
    before = hashlib.sha256(db.read_bytes()).hexdigest()
    (tmp_path / "backups").write_bytes(b"a file where the folder should be")
    with pytest.raises(BackupError) as exc:
        db_backup.daily_backup(conn, db, today=DAY)
    with pytest.raises(BackupError):
        db_backup.migration_backup(conn, db, 2)
    conn.close()
    assert "backups" in str(exc.value)
    assert hashlib.sha256(db.read_bytes()).hexdigest() == before


def test_a_failed_copy_leaves_neither_the_final_file_nor_a_part_file(tmp_path, monkeypatch):
    db = tmp_path / "wow_stats.db"
    conn = make_db(db)

    def refuse(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(db_backup.os, "replace", refuse)
    with pytest.raises(BackupError) as exc:
        db_backup.daily_backup(conn, db, today=DAY)
    conn.close()
    assert "disk full" in str(exc.value)
    assert names(tmp_path / "backups" / "daily") == []


def test_the_module_imports_only_the_standard_library():
    tree = ast.parse((SRC / "db_backup.py").read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module.split(".")[0])
    assert imported <= {"glob", "os", "re", "sqlite3", "datetime", "pathlib"}


# ------------------------------------------------------------- wired into init_db
def lua_with_scan(path, scanned_at):
    path.write_text('StatTrackerDB = { meta = { [1] = { name = "x", cat = "y" } }, chars = { ["A-B"] = '
                    f'{{ scannedAt = "{scanned_at}", stats = {{ [1] = "5" }} }} }} }}', encoding="utf-8")
    return path


def existing_db(folder, name="wow_stats.db"):
    """A database that already holds a scan, at the current schema version, without any copy yet."""
    db = folder / name
    stat_parser.init_db(db).close()
    conn = sqlite3.connect(db)
    conn.execute("INSERT INTO scans(char_key, scanned_at) VALUES ('A-B', '2026-10-01 10:00:00')")
    conn.commit()
    conn.close()
    return db


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def content_scans(path):
    conn = sqlite3.connect(path)
    try:
        return conn.execute("SELECT COUNT(*) FROM scans").fetchone()[0]
    finally:
        conn.close()


def test_a_new_database_gets_no_backup(tmp_path):
    stat_parser.init_db(tmp_path / "wow_stats.db").close()
    assert not (tmp_path / "backups").exists()


def test_an_existing_database_is_copied_once_a_day_and_the_copy_is_reported(tmp_path, capsys):
    db = existing_db(tmp_path)
    stat_parser.init_db(db).close()
    daily = tmp_path / "backups" / "daily"
    (copy,) = list(daily.iterdir())
    assert copy.name == f"wow_stats.{date.today().isoformat()}.bak"
    assert content(copy) == (1, stat_parser.SCHEMA_VERSION)
    assert f"Backup:   {copy}" in capsys.readouterr().out
    stat_parser.init_db(db).close()                          # same day: nothing new, nothing printed
    assert names(daily) == [copy.name]
    assert "Backup:" not in capsys.readouterr().out
    assert names(tmp_path / "backups" / "migration") == []


def test_before_a_migration_a_permanent_copy_with_the_old_state_is_made(tmp_path, monkeypatch, capsys):
    db = existing_db(tmp_path)                               # schema 1, one scan
    monkeypatch.setattr(stat_parser, "SCHEMA_VERSION", 2)
    monkeypatch.setattr(stat_parser, "MIGRATIONS", {1: lambda conn: None, 2: lambda conn: None})
    stat_parser.init_db(db).close()
    (copy,) = list((tmp_path / "backups" / "migration").iterdir())
    assert copy.name.startswith("wow_stats.") and copy.name.endswith(".pre-v2.bak")
    assert content(copy) == (1, 1)                           # the state before the migration
    assert content(db) == (1, 2)
    assert not (tmp_path / "backups" / "daily").exists()     # one copy per run
    assert f"Backup:   {copy}" in capsys.readouterr().out


def test_the_migration_copy_survives_a_failing_migration(tmp_path, monkeypatch):
    def broken(conn):
        raise RuntimeError("boom")

    db = existing_db(tmp_path)
    monkeypatch.setattr(stat_parser, "SCHEMA_VERSION", 2)
    monkeypatch.setattr(stat_parser, "MIGRATIONS", {1: lambda conn: None, 2: broken})
    with pytest.raises(RuntimeError, match="boom"):
        stat_parser.init_db(db)
    (copy,) = list((tmp_path / "backups" / "migration").iterdir())
    assert content(copy) == (1, 1) and content(db) == (1, 1)


def test_a_database_from_a_newer_program_gets_no_backup_and_stays_untouched(tmp_path):
    db = existing_db(tmp_path)
    conn = sqlite3.connect(db)
    conn.execute(f"PRAGMA user_version = {stat_parser.SCHEMA_VERSION + 1}")
    conn.close()
    before = digest(db)
    with pytest.raises(SystemExit):
        stat_parser.init_db(db)
    assert digest(db) == before and not (tmp_path / "backups").exists()


def test_old_daily_copies_are_rotated_by_the_import(tmp_path):
    db = existing_db(tmp_path)
    daily = tmp_path / "backups" / "daily"
    daily.mkdir(parents=True)
    for day in range(1, 9):
        (daily / f"wow_stats.2020-01-{day:02d}.bak").write_bytes(b"x")
    migration = tmp_path / "backups" / "migration"
    migration.mkdir()
    (migration / "wow_stats.20200101-000000.pre-v1.bak").write_bytes(b"x")
    stat_parser.init_db(db).close()
    kept = {f"wow_stats.2020-01-{d:02d}.bak" for d in range(3, 9)}      # 8 old + today = 9, newest 7 stay
    assert set(names(daily)) == kept | {f"wow_stats.{date.today().isoformat()}.bak"}
    assert names(migration) == ["wow_stats.20200101-000000.pre-v1.bak"]


def test_a_rotation_problem_is_only_a_warning(tmp_path, monkeypatch, capsys):
    db = existing_db(tmp_path)
    stuck = tmp_path / "backups" / "daily" / "wow_stats.2020-01-01.bak"
    monkeypatch.setattr(db_backup, "rotate", lambda path: [stuck])
    conn = stat_parser.init_db(db)
    conn.close()
    out = capsys.readouterr().out
    assert "WARNING: old backups could not be deleted" in out and str(stuck) in out


def test_a_backup_that_cannot_be_written_stops_the_import_before_any_change(tmp_path):
    db = tmp_path / "wow_stats.db"
    page = tmp_path / "stats.html"
    stat_parser.main(["--input", str(lua_with_scan(tmp_path / "first.lua", "2026-10-01 10:00:00")),
                      "--db", str(db), "--output", str(page)])
    page.unlink()
    (tmp_path / "backups").write_bytes(b"a file where the folder should be")
    before = digest(db)
    newer = lua_with_scan(tmp_path / "second.lua", "2026-10-02 10:00:00")     # would add a scan
    with pytest.raises(SystemExit) as exc:
        stat_parser.main(["--input", str(newer), "--db", str(db), "--output", str(page)])
    assert str(exc.value).startswith("ERROR: the backup of the database failed")
    assert digest(db) == before and not page.exists()
    assert content_scans(db) == 1


def test_the_first_import_into_a_new_database_and_a_repeat_work_as_before(tmp_path):
    db = tmp_path / "wow_stats.db"
    page = tmp_path / "stats.html"
    lua = lua_with_scan(tmp_path / "StatTracker.lua", "2026-10-01 10:00:00")
    args = ["--input", str(lua), "--db", str(db), "--output", str(page)]
    stat_parser.main(args)
    assert not (tmp_path / "backups").exists()               # nothing to save yet
    stat_parser.main(args)
    assert content_scans(db) == 1 and page.exists()
    assert len(names(tmp_path / "backups" / "daily")) == 1


def test_the_excel_export_ignores_the_backup_folders_and_makes_no_copy(tmp_path):
    db = existing_db(tmp_path)
    stat_parser.init_db(db).close()                          # makes backups/daily/<today>.bak
    (tmp_path / "backups" / "daily" / "wow_stats_stray.db").write_bytes(b"x")   # even a stray .db there
    (tmp_path / "backups" / "migration").mkdir()
    (tmp_path / "backups" / "migration" / "wow_stats.20200101-000000.pre-v2.bak").write_bytes(b"x")
    assert export_xlsx.find_dbs(tmp_path) == [db]
    before = names(tmp_path / "backups" / "daily")
    export_xlsx.load_db(db)
    assert names(tmp_path / "backups" / "daily") == before
