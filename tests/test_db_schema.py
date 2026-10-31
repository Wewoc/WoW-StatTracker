# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)
# The version of the statistics database (PRAGMA user_version): a new database gets the current
# number, a v0.1.x database (no number) is stamped without losing a row, a database from a newer
# program is refused untouched, and a migration is all or nothing.

import hashlib
import sqlite3

import pytest

import export_xlsx
import stat_parser
from stat_parser import SCHEMA_VERSION

# The layout of v0.1.0 to v0.1.2, written out here on purpose: the test must not follow the code.
V01_LAYOUT = """
    CREATE TABLE scans (
        scan_id    INTEGER PRIMARY KEY AUTOINCREMENT,
        char_key   TEXT NOT NULL,
        scanned_at TEXT NOT NULL,
        class      TEXT,
        level      INTEGER,
        faction    TEXT,
        UNIQUE (char_key, scanned_at)
    );
    CREATE TABLE stat_defs (
        stat_id  INTEGER PRIMARY KEY,
        name     TEXT NOT NULL,
        category TEXT NOT NULL
    );
    CREATE TABLE stat_values (
        scan_id    INTEGER NOT NULL REFERENCES scans(scan_id),
        stat_id    INTEGER NOT NULL,
        value_text TEXT NOT NULL,
        value_num  INTEGER,
        PRIMARY KEY (scan_id, stat_id)
    );
    INSERT INTO scans VALUES (1, 'Alice-Realm', '2026-10-01 10:00:00', 'Mage', 80, 'Alliance');
    INSERT INTO stat_defs VALUES (1, 'Total deaths', 'Combat');
    INSERT INTO stat_values VALUES (1, 1, '1.234', 1234);
"""


# The columns of the v0.1 layout: a later schema may add columns, the old ones must stay as they were.
V01_COLUMNS = {"scans": "scan_id, char_key, scanned_at, class, level, faction",
               "stat_defs": "stat_id, name, category",
               "stat_values": "scan_id, stat_id, value_text, value_num"}


def rows(path):
    conn = sqlite3.connect(path)
    try:
        return [conn.execute(f"SELECT {cols} FROM {t} ORDER BY 1, 2").fetchall()
                for t, cols in V01_COLUMNS.items()]
    finally:
        conn.close()


def columns(path, table="scans"):
    conn = sqlite3.connect(path)
    try:
        return [(r[1], r[2]) for r in conn.execute(f"PRAGMA table_info({table})")]
    finally:
        conn.close()


def version(path):
    conn = sqlite3.connect(path)
    try:
        return conn.execute("PRAGMA user_version").fetchone()[0]
    finally:
        conn.close()


def make_v01(path, user_version=0):
    conn = sqlite3.connect(path)
    conn.executescript(V01_LAYOUT)
    conn.execute(f"PRAGMA user_version = {user_version}")
    conn.commit()
    conn.close()
    return path


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_every_version_up_to_the_current_one_has_a_migration():
    assert SCHEMA_VERSION >= 1
    assert set(stat_parser.MIGRATIONS) == set(range(1, SCHEMA_VERSION + 1))


def test_new_database_gets_the_current_version(tmp_path):
    db = tmp_path / "new.db"
    conn = stat_parser.init_db(db)
    assert stat_parser.schema_version(conn) == SCHEMA_VERSION
    conn.close()
    assert version(db) == SCHEMA_VERSION
    assert rows(db) == [[], [], []]


def test_empty_existing_file_counts_as_new(tmp_path):
    db = tmp_path / "empty.db"
    db.touch()
    stat_parser.init_db(db).close()
    assert version(db) == SCHEMA_VERSION and rows(db) == [[], [], []]


def test_v01_database_is_stamped_and_keeps_every_row(tmp_path):
    db = make_v01(tmp_path / "old.db")
    assert version(db) == 0
    before = rows(db)
    stat_parser.init_db(db).close()
    assert version(db) == SCHEMA_VERSION
    assert before[2] == [(1, 1, "1.234", 1234)]          # the fixture really holds a value
    assert rows(db) == before


def migration_copies(folder):
    target = folder / "backups" / "migration"
    return sorted(target.iterdir()) if target.is_dir() else []


def test_schema_1_gets_the_race_columns_and_every_old_scan_stays_empty(tmp_path):
    db = make_v01(tmp_path / "v1.db", user_version=1)
    before = rows(db)
    stat_parser.init_db(db).close()
    assert version(db) == 2
    assert rows(db) == before                                # the old columns are untouched
    assert [c for c, _t in columns(db)][-3:] == ["class_file", "race", "race_file"]
    conn = sqlite3.connect(db)
    assert conn.execute("SELECT class_file, race, race_file FROM scans").fetchall() == [(None, None, None)]
    conn.close()
    (copy,) = migration_copies(tmp_path)                     # the copy holds the state before
    assert copy.name.endswith(".pre-v2.bak") and version(copy) == 1
    assert "race" not in [c for c, _t in columns(copy)]


def test_schema_0_takes_both_steps_and_leaves_one_permanent_copy(tmp_path):
    db = make_v01(tmp_path / "v0.db")
    stat_parser.init_db(db).close()
    assert version(db) == 2
    (copy,) = migration_copies(tmp_path)
    assert copy.name.endswith(".pre-v2.bak") and version(copy) == 0
    assert not (tmp_path / "backups" / "daily").exists()


def test_a_migrated_database_has_the_same_columns_as_a_new_one(tmp_path):
    stat_parser.init_db(tmp_path / "new.db").close()
    stat_parser.init_db(make_v01(tmp_path / "old.db")).close()
    for table in ("scans", "stat_defs", "stat_values"):
        assert columns(tmp_path / "old.db", table) == columns(tmp_path / "new.db", table)


def test_opening_again_changes_nothing(tmp_path):
    db = make_v01(tmp_path / "old.db")
    stat_parser.init_db(db).close()
    first = digest(db)
    stat_parser.init_db(db).close()
    assert digest(db) == first


def test_database_from_a_newer_program_is_refused_untouched(tmp_path):
    db = make_v01(tmp_path / "future.db", user_version=SCHEMA_VERSION + 1)
    before = digest(db)
    with pytest.raises(SystemExit) as exc:
        stat_parser.init_db(db)
    message = str(exc.value)
    assert str(db) in message and str(SCHEMA_VERSION + 1) in message and str(SCHEMA_VERSION) in message
    assert digest(db) == before
    assert version(db) == SCHEMA_VERSION + 1


def test_main_refuses_a_newer_database_before_it_writes_anything(tmp_path):
    db = make_v01(tmp_path / "future.db", user_version=SCHEMA_VERSION + 5)
    lua = tmp_path / "StatTracker.lua"
    lua.write_text('StatTrackerDB = { meta = { [1] = { name = "x", cat = "y" } }, chars = { ["A-B"] = '
                   '{ scannedAt = "2026-10-02 10:00:00", stats = { [1] = "5" } } } }', encoding="utf-8")
    page = tmp_path / "out.html"
    before = digest(db)
    with pytest.raises(SystemExit) as exc:
        stat_parser.main(["--input", str(lua), "--db", str(db), "--output", str(page)])
    assert "schema" in str(exc.value).lower()
    assert digest(db) == before and not page.exists()


def test_connection_keeps_its_normal_transaction_handling(tmp_path):
    # import_data commits only at its end; a migration must not leave the connection in autocommit
    for db in (tmp_path / "new.db", make_v01(tmp_path / "old.db")):
        conn = stat_parser.init_db(db)
        assert conn.isolation_level == ""
        conn.close()


def test_migrations_run_in_order_and_each_raises_the_number(tmp_path, monkeypatch):
    order = []
    monkeypatch.setattr(stat_parser, "SCHEMA_VERSION", 3)
    monkeypatch.setattr(stat_parser, "MIGRATIONS", {
        1: lambda conn: order.append(1),
        2: lambda conn: order.append(2),
        3: lambda conn: order.append(3),
    })
    db = make_v01(tmp_path / "old.db")
    stat_parser.init_db(db).close()
    assert order == [1, 2, 3] and version(db) == 3


def test_failed_migration_rolls_back_and_keeps_the_last_good_version(tmp_path, monkeypatch):
    def broken(conn):
        conn.execute("CREATE TABLE half_done (x)")
        conn.execute("DELETE FROM stat_values")
        raise RuntimeError("boom")

    monkeypatch.setattr(stat_parser, "SCHEMA_VERSION", 2)
    monkeypatch.setattr(stat_parser, "MIGRATIONS", {1: lambda conn: None, 2: broken})
    db = make_v01(tmp_path / "old.db")
    before = rows(db)
    with pytest.raises(RuntimeError, match="boom"):
        stat_parser.init_db(db)
    assert version(db) == 1                               # step 1 is complete, step 2 left no trace
    assert rows(db) == before
    conn = sqlite3.connect(db)
    assert conn.execute("SELECT name FROM sqlite_master WHERE name='half_done'").fetchone() is None
    conn.close()


def test_excel_export_reads_unstamped_and_current_databases_without_writing(tmp_path):
    for number in (0, SCHEMA_VERSION):
        db = make_v01(tmp_path / f"wow_stats_v{number}.db", user_version=number)
        before = digest(db)
        chars, stats = export_xlsx.load_db(db)
        assert [c["key"] for c in chars] == ["Alice-Realm"]
        assert digest(db) == before and version(db) == number     # reading never stamps


def test_excel_export_refuses_a_newer_database_untouched(tmp_path):
    db = make_v01(tmp_path / "wow_stats.db", user_version=SCHEMA_VERSION + 1)
    before = digest(db)
    with pytest.raises(SystemExit) as exc:
        export_xlsx.load_db(db)
    assert str(db) in str(exc.value) and str(SCHEMA_VERSION + 1) in str(exc.value)
    assert digest(db) == before


def test_whole_export_stops_when_one_database_is_too_new(tmp_path):
    pytest.importorskip("openpyxl")
    make_v01(tmp_path / "wow_stats.db")
    newer = make_v01(tmp_path / "wow_stats_anniversary.db", user_version=SCHEMA_VERSION + 1)
    out = tmp_path / "out.xlsx"
    with pytest.raises(SystemExit) as exc:
        export_xlsx.export(out, tmp_path)
    assert newer.name in str(exc.value) or str(newer) in str(exc.value)
    assert not out.exists()                                   # no half workbook


def test_import_is_unchanged_on_a_stamped_database(tmp_path):
    db = make_v01(tmp_path / "old.db")
    lua = tmp_path / "StatTracker.lua"
    lua.write_text('StatTrackerDB = { meta = { [1] = { name = "x", cat = "y" } }, chars = { ["A-B"] = '
                   '{ scannedAt = "2026-10-02 10:00:00", stats = { [1] = "5" } } } }', encoding="utf-8")
    page = tmp_path / "out.html"
    args = ["--input", str(lua), "--db", str(db), "--output", str(page)]
    stat_parser.main(args)
    stat_parser.main(args)                                # idempotent as before
    conn = sqlite3.connect(db)
    assert conn.execute("SELECT COUNT(*) FROM scans").fetchone()[0] == 2     # the old scan + the new one
    conn.close()
    assert version(db) == SCHEMA_VERSION
