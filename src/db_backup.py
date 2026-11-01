#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)
# db_backup.py
# StatTracker - copies of the statistics database. Stdlib only, no project imports: it
# takes an open connection and returns paths; the caller prints the messages.
#
#   <folder of the db>/backups/daily/      one copy per calendar day, the newest KEEP_DAILY are kept
#   <folder of the db>/backups/migration/  one copy before a schema migration, never deleted here
#
# A copy is written through sqlite3's backup API into a .part file and renamed when complete,
# so a file with the final name is always a whole database. Every failure to write a copy is a
# BackupError (the caller stops before it changes anything); a failure to delete an old copy is
# only reported (rotate). Before a copy is written the database gets a quick integrity check; a
# damaged one is a DamagedDatabase (a BackupError): no copy of the damage, no rotation of good ones.

import glob
import os
import re
import sqlite3
from datetime import date, datetime
from pathlib import Path

KEEP_DAILY = 7
BACKUP_DIRNAME = "backups"
DAILY_DIRNAME = "daily"
MIGRATION_DIRNAME = "migration"
SUFFIX = ".bak"
PART_SUFFIX = ".part"


class BackupError(Exception):
    """A copy of the database could not be written; the message names the file and the cause."""


class DamagedDatabase(BackupError):
    """The database failed its integrity check, so no copy was made: a copy would hold the damage, and the
    rotation that follows would push the last good copies out. `problems` are the lines of the check."""

    def __init__(self, path, problems):
        super().__init__(f"{path}: {'; '.join(problems)}")
        self.problems = problems


def damage(conn, limit=5):
    """What PRAGMA quick_check finds in the open database: the first `limit` lines, [] if it is intact.
    A database so damaged that the check itself fails is reported with that error."""
    try:
        rows = [str(row[0]) for row in conn.execute("PRAGMA quick_check")]
    except sqlite3.DatabaseError as exc:
        return [str(exc)]
    return [] if rows == ["ok"] else rows[:limit]


def daily_dir(db_path):
    return Path(db_path).parent / BACKUP_DIRNAME / DAILY_DIRNAME


def migration_dir(db_path):
    return Path(db_path).parent / BACKUP_DIRNAME / MIGRATION_DIRNAME


def _remove_leftovers(folder, stem):
    """Deletes unfinished .part files of this database (an earlier run was cut off)."""
    for part in Path(folder).glob(f"{glob.escape(stem)}.*{PART_SUFFIX}"):
        try:
            part.unlink()
        except OSError:
            pass


def _write_copy(conn, target):
    """Copies the open database to target; target only appears once the copy is complete."""
    part = target.with_name(target.name + PART_SUFFIX)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        dest = sqlite3.connect(part)
        try:
            conn.backup(dest)
        finally:
            dest.close()
        os.replace(part, target)
    except (OSError, sqlite3.Error) as exc:
        try:
            part.unlink()
        except OSError:
            pass
        raise BackupError(f"{target}: {exc}") from exc


def _require_intact(conn, db_path):
    problems = damage(conn)
    if problems:
        raise DamagedDatabase(db_path, problems)


def daily_backup(conn, db_path, today=None):
    """The copy of the day: <stem>.YYYY-MM-DD.bak in backups/daily/. Returns its path, or None if
    there already is one for this day (it holds the state before the first import of the day)."""
    path = Path(db_path)
    folder = daily_dir(path)
    _remove_leftovers(folder, path.stem)
    target = folder / f"{path.stem}.{(today or date.today()).isoformat()}{SUFFIX}"
    if target.exists():
        return None
    _require_intact(conn, path)
    _write_copy(conn, target)
    return target


def migration_backup(conn, db_path, target_version, now=None):
    """The copy before a migration: <stem>.YYYYMMDD-HHMMSS.pre-v<N>.bak in backups/migration/.
    Always written, never rotated. Returns its path."""
    path = Path(db_path)
    folder = migration_dir(path)
    _remove_leftovers(folder, path.stem)
    stamp = (now or datetime.now()).strftime("%Y%m%d-%H%M%S")
    target = folder / f"{path.stem}.{stamp}.pre-v{target_version}{SUFFIX}"
    if target.exists():                 # same second: this is the copy of that very state
        return target
    _require_intact(conn, path)
    _write_copy(conn, target)
    return target


def rotate(db_path, keep=KEEP_DAILY):
    """Deletes the oldest daily copies of this database beyond the newest `keep`. Only files named
    exactly <stem>.YYYY-MM-DD.bak in backups/daily/ are considered; backups/migration/ and every
    other file stay. Never raises: returns the paths that could not be deleted (or listed)."""
    path = Path(db_path)
    folder = daily_dir(path)
    pattern = re.compile(rf"{re.escape(path.stem)}\.\d{{4}}-\d{{2}}-\d{{2}}{re.escape(SUFFIX)}")
    try:
        found = sorted(p for p in folder.iterdir() if p.is_file() and pattern.fullmatch(p.name))
    except FileNotFoundError:
        return []
    except OSError:
        return [folder]
    failed = []
    for old in found[:max(len(found) - max(keep, 1), 0)]:
        try:
            old.unlink()
        except OSError:
            failed.append(old)
    return failed
