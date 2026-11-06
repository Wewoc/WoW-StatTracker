#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)
# db_schema.py
# StatTracker - the schema of the statistics database (SCHEMA_VERSION, MIGRATIONS, SCHEMA_SQL, the column lists of
# scan_gear and scan_reputation), check_schema, and init_db: the only way the database is opened for writing
# (it takes the copy via db_backup before the first change). Needs db_backup and i18n.
# Moved out of stat_parser.py; the rules are unchanged.

import sqlite3
import sys
from pathlib import Path

from core.i18n import t
from store import db_backup


# Schema version of the statistics database, kept in SQLite's PRAGMA user_version.
# 0 = no number written yet (databases of v0.1.x), 1 = the same layout, 2 = the layout below
# (scans gained class_file, race, race_file), 3 = the layout below (scans gained the specialization and item level,
# new tables scan_gear, rep_defs, scan_reputation). Changing the layout means a new entry in
# MIGRATIONS and a higher SCHEMA_VERSION; an old step is never edited.
# A database newer than SCHEMA_VERSION is refused untouched (fail-closed).
SCHEMA_VERSION = 3


def _migrate_0_to_1(conn):
    """Schema 0 has the same layout as schema 1: only the number is set (by init_db)."""


def _migrate_1_to_2(conn):
    """Schema 2 adds the stable class name and the race to every scan. Scans taken before stay
    NULL: they are never filled in from a later scan, because a race can change."""
    for column in ("class_file", "race", "race_file"):
        conn.execute(f"ALTER TABLE scans ADD COLUMN {column} TEXT")


# What schema 3 adds. One definition for a new file (SCHEMA_SQL) and for the migration of an old one, so that the two
# cannot drift apart (tests/test_db_schema.py compares a fresh with a migrated database).
SCAN_COLUMNS_V3 = (("spec_id", "INTEGER"), ("spec_name", "TEXT"), ("role", "TEXT"),
                   ("ilvl_total", "REAL"), ("ilvl_equipped", "REAL"))
TABLES_V3 = (
    """CREATE TABLE IF NOT EXISTS scan_gear (
            scan_id      INTEGER NOT NULL REFERENCES scans(scan_id),
            slot         INTEGER NOT NULL,
            item_id      INTEGER,
            name         TEXT,
            quality      INTEGER,
            ilvl         INTEGER,
            icon_id      INTEGER,
            enchant_id   INTEGER,
            enchant_text TEXT,
            upg_track_id INTEGER,
            upg_track    TEXT,
            upg_level    INTEGER,
            upg_max      INTEGER,
            sockets      INTEGER,
            gem_ids      TEXT,
            stats        TEXT,
            PRIMARY KEY (scan_id, slot)
        )""",
    """CREATE TABLE IF NOT EXISTS rep_defs (
            faction_id INTEGER PRIMARY KEY,
            name       TEXT NOT NULL
        )""",
    """CREATE TABLE IF NOT EXISTS scan_reputation (
            scan_id      INTEGER NOT NULL REFERENCES scans(scan_id),
            ord          INTEGER NOT NULL,
            faction_id   INTEGER NOT NULL,
            is_header    INTEGER NOT NULL DEFAULT 0,
            is_child     INTEGER NOT NULL DEFAULT 0,
            account_wide INTEGER NOT NULL DEFAULT 0,
            kind         TEXT,
            reaction     INTEGER,
            standing     INTEGER,
            lo           INTEGER,
            hi           INTEGER,
            level        INTEGER,
            max_level    INTEGER,
            renown       INTEGER,
            earned       INTEGER,
            need         INTEGER,
            max_renown   INTEGER,
            p_value      INTEGER,
            p_threshold  INTEGER,
            p_quest      INTEGER,
            p_pending    INTEGER,
            PRIMARY KEY (scan_id, ord)
        )""",
)


def _migrate_2_to_3(conn):
    """Schema 3 adds the specialization and item level to every scan and the tables of gear and reputation. Scans taken
    before stay NULL and have no rows there: nothing is filled in from a later scan."""
    for column, kind in SCAN_COLUMNS_V3:
        conn.execute(f"ALTER TABLE scans ADD COLUMN {column} {kind}")
    for statement in TABLES_V3:
        conn.execute(statement)


MIGRATIONS = {1: _migrate_0_to_1, 2: _migrate_1_to_2, 3: _migrate_2_to_3}      # target version -> step from the version before

SCHEMA_SQL = """
        CREATE TABLE IF NOT EXISTS scans (
            scan_id    INTEGER PRIMARY KEY AUTOINCREMENT,
            char_key   TEXT NOT NULL,
            scanned_at TEXT NOT NULL,
            class      TEXT,
            level      INTEGER,
            faction    TEXT,
            class_file TEXT,
            race       TEXT,
            race_file  TEXT,
{scan_columns_v3}            UNIQUE (char_key, scanned_at)
        );
        CREATE TABLE IF NOT EXISTS stat_defs (
            stat_id  INTEGER PRIMARY KEY,
            name     TEXT NOT NULL,
            category TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS stat_values (
            scan_id    INTEGER NOT NULL REFERENCES scans(scan_id),
            stat_id    INTEGER NOT NULL,
            value_text TEXT NOT NULL,
            value_num  INTEGER,
            PRIMARY KEY (scan_id, stat_id)
        );
"""
SCHEMA_SQL = SCHEMA_SQL.replace("{scan_columns_v3}", "".join(f"            {c} {k},\n" for c, k in SCAN_COLUMNS_V3))
SCHEMA_SQL += ";\n".join(TABLES_V3) + ";\n"


def schema_version(conn):
    return conn.execute("PRAGMA user_version").fetchone()[0]


def check_schema(conn, path):
    """Exits with a message if the database is newer than this program knows; otherwise
    returns its version. Everything that opens a statistics database calls this first."""
    found = schema_version(conn)
    if found > SCHEMA_VERSION:
        sys.exit(t("parse_err_db_too_new", path=path, found=found, known=SCHEMA_VERSION))
    return found


def _in_transaction(conn, work):
    """Runs work() as one transaction: all or nothing. The connection keeps its normal
    transaction handling afterwards (import_data relies on it to commit only at the end)."""
    previous = conn.isolation_level
    conn.isolation_level = None            # BEGIN/COMMIT are issued here, not by sqlite3
    try:
        conn.execute("BEGIN")
        try:
            work()
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise
    finally:
        conn.isolation_level = previous


def _back_up(conn, path, found):
    """A copy of an existing database before anything is written to it: before a migration
    (found < SCHEMA_VERSION) one that is kept for good, otherwise the copy of the day. If it
    cannot be written, exits with a message and nothing has been changed (fail-closed). Old daily
    copies that cannot be deleted only produce a warning."""
    try:
        if found < SCHEMA_VERSION:
            made = db_backup.migration_backup(conn, path, SCHEMA_VERSION)
        else:
            made = db_backup.daily_backup(conn, path)
    except db_backup.DamagedDatabase as exc:
        sys.exit(t("parse_err_db_damaged", folder=db_backup.daily_dir(path).parent, found="; ".join(exc.problems)))
    except db_backup.BackupError as exc:
        sys.exit(t("parse_err_backup_failed", error=exc))
    if made:
        print(t("parse_out_backup", path=made))
    if found >= SCHEMA_VERSION:
        failed = db_backup.rotate(path)
        if failed:
            print(t("parse_warn_backup_rotate", paths=", ".join(map(str, failed))))


def init_db(path):
    """Opens (or creates) the statistics database at its current schema version.
    New or empty file: created at SCHEMA_VERSION. Older database: copied (db_backup), then
    migrated step by step, each step its own transaction, the number raised at the end of it.
    Current database: copied once a day. Newer database: exits with a message and has not
    written anything. A copy that cannot be written stops everything before the first change."""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        found = check_schema(conn, path)
        has_tables = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='scans'").fetchone() is not None
        if not has_tables:
            conn.executescript(f"BEGIN;{SCHEMA_SQL}PRAGMA user_version = {SCHEMA_VERSION};COMMIT;")
        else:
            _back_up(conn, path, found)
            for target in range(found + 1, SCHEMA_VERSION + 1):
                _in_transaction(conn, lambda: (MIGRATIONS[target](conn),
                                               conn.execute(f"PRAGMA user_version = {target}")))
    except BaseException:
        conn.close()
        raise
    return conn


# The columns the importer writes into scan_gear and scan_reputation (and stat_history reads back).
GEAR_COLUMNS = ("slot", "item_id", "name", "quality", "ilvl", "icon_id", "enchant_id", "enchant_text", "upg_track_id",
                "upg_track", "upg_level", "upg_max", "sockets", "gem_ids", "stats")
REP_COLUMNS = ("ord", "faction_id", "is_header", "is_child", "account_wide", "kind", "reaction", "standing", "lo", "hi",
               "level", "max_level", "renown", "earned", "need", "max_renown", "p_value", "p_threshold", "p_quest", "p_pending")
