# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)
# The history of one character (stat_history): order, gaps, units, and that reading never writes.

import hashlib
import sqlite3

import pytest

import i18n
import stat_history
import stat_parser

META = {1: {"name": "Total deaths", "cat": "Combat"},
        2: {"name": "Gold earned", "cat": "Wealth"},
        3: {"name": "Average per day", "cat": "Wealth"},
        4: {"name": "Favourite mount", "cat": "Collections"}}
KEY = "Alice-Realm"


def scan(at, stats, played=None, level=80, race=None):
    c = {"scannedAt": at, "scannedEpoch": 1, "class": "Mage", "level": level, "faction": "Alliance",
         "stats": stats}
    if played is not None:
        c["playedTotal"], c["playedLevel"] = played, played // 10
    if race:
        c.update(classFile="MAGE", race="Human", raceFile=race)
    return c


def make_db(path, scans, key=KEY):
    """A database made the way the importer makes it: one import per scan, in the given order."""
    conn = stat_parser.init_db(path)
    for c in scans:
        stat_parser.import_data(conn, {"meta": META, "chars": {key: c}})
    conn.close()
    return path


def history(path, key=KEY):
    conn = stat_history.open_readonly(path)
    try:
        return stat_history.build_history(conn, key)
    finally:
        conn.close()


def by_id(result):
    return {s["id"]: s for s in result["stats"]}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_scans_come_oldest_first_and_every_column_follows_that_order(tmp_path):
    db = make_db(tmp_path / "x.db", [
        scan("2026-10-03 10:00:00", {1: "30"}, level=82),
        scan("2026-10-01 10:00:00", {1: "10"}, level=80),
        scan("2026-10-02 10:00:00", {1: "20"}, level=81)])
    h = history(db)
    assert h["scans"] == ["2026-10-01 10:00:00", "2026-10-02 10:00:00", "2026-10-03 10:00:00"]
    assert h["level"] == [80, 81, 82]
    assert by_id(h)[1]["v"] == [10, 20, 30]


def test_a_gap_or_a_dash_is_none_and_a_text_only_statistic_is_left_out(tmp_path):
    db = make_db(tmp_path / "x.db", [
        scan("2026-10-01 10:00:00", {1: "10", 2: "1g 0s 0c", 4: "Kodo"}),
        scan("2026-10-02 10:00:00", {1: "20", 4: "Kodo"}),
        scan("2026-10-03 10:00:00", {1: "--", 2: "2g 0s 0c"})])
    stats = by_id(history(db))
    assert stats[1]["v"] == [10, 20, None]
    assert stats[2]["v"] == [10000, None, 20000]
    assert 4 not in stats and 3 not in stats


def test_stats_are_sorted_by_category_and_name(tmp_path):
    db = make_db(tmp_path / "x.db", [scan("2026-10-01 10:00:00", {1: "1", 2: "1g", 3: "0.20"})])
    assert [s["name"] for s in history(db)["stats"]] == ["Total deaths", "Average per day", "Gold earned"]


def test_units(tmp_path):
    db = make_db(tmp_path / "x.db", [scan("2026-10-01 10:00:00", {1: "1.234", 2: "12g 5s 3c", 3: "0.20"}, played=3600)])
    units = {i: s["unit"] for i, s in by_id(history(db)).items()}
    assert units == {1: "number", 2: "gold", 3: "number", -1: "seconds", -2: "seconds"}
    assert by_id(history(db))[2]["v"] == [120503]


def test_a_statistic_that_is_a_coin_text_only_sometimes_is_not_gold(tmp_path):
    db = make_db(tmp_path / "x.db", [scan("2026-10-01 10:00:00", {1: "12g"}), scan("2026-10-02 10:00:00", {1: "1.234"})])
    assert by_id(history(db))[1]["unit"] == "number"


def test_coin_texts_are_the_ones_to_number_reads_as_copper():
    for text in ("12g 5s 3c", "5s 3c", "3c", "1.234g"):
        assert stat_history.COIN_TEXT.fullmatch(text)
        assert stat_parser.to_number(text) is not None
    for text in ("1.234", "0.20", "--", "Kodo", "3 d 4 h"):
        assert not stat_history.COIN_TEXT.fullmatch(text)


def test_played_time_is_in_seconds_and_named_in_the_current_language(tmp_path):
    db = make_db(tmp_path / "x.db", [scan("2026-10-01 10:00:00", {1: "1"}, played=7200),
                                     scan("2026-10-02 10:00:00", {1: "2"}, played=10800)])
    i18n.set_language("en")
    en = by_id(history(db))[-1]
    i18n.set_language("de")
    de = by_id(history(db))[-1]
    assert en["v"] == de["v"] == [7200, 10800]
    assert de["name"] == stat_parser.played_labels()[-1][0]
    assert en["name"] != de["name"]


def test_the_char_block_is_the_latest_scan(tmp_path):
    db = make_db(tmp_path / "x.db", [scan("2026-10-01 10:00:00", {1: "1"}, level=79, race="Human"),
                                     scan("2026-10-02 10:00:00", {1: "2"}, level=80, race="Gnome")])
    assert history(db)["char"] == {"key": KEY, "class": "Mage", "level": 80, "faction": "Alliance",
                                   "class_file": "MAGE", "race": "Human", "race_file": "Gnome"}


def test_only_the_scans_of_the_asked_character_count(tmp_path):
    db = make_db(tmp_path / "x.db", [scan("2026-10-01 10:00:00", {1: "1"})])
    make_db(db, [scan("2026-10-02 10:00:00", {1: "9"})], key="Bob-Realm")
    assert history(db)["scans"] == ["2026-10-01 10:00:00"]
    assert by_id(history(db, "Bob-Realm"))[1]["v"] == [9]


def test_an_unknown_character_has_no_history(tmp_path):
    db = make_db(tmp_path / "x.db", [scan("2026-10-01 10:00:00", {1: "1"})])
    assert history(db, "Nobody-Realm") is None


def test_a_single_scan_is_a_history_of_length_one(tmp_path):
    h = history(make_db(tmp_path / "x.db", [scan("2026-10-01 10:00:00", {1: "5"})]))
    assert h["scans"] == ["2026-10-01 10:00:00"] and by_id(h)[1]["v"] == [5]


def test_reading_writes_nothing(tmp_path):
    db = make_db(tmp_path / "x.db", [scan("2026-10-01 10:00:00", {1: "1"}), scan("2026-10-02 10:00:00", {1: "2"})])
    before = (digest(db), db.stat().st_mtime_ns, sorted(p.name for p in tmp_path.iterdir()))
    conn = stat_history.open_readonly(db)
    try:
        stat_history.build_history(conn, KEY)
        with pytest.raises(sqlite3.OperationalError):
            conn.execute("DELETE FROM scans")
    finally:
        conn.close()
    assert (digest(db), db.stat().st_mtime_ns, sorted(p.name for p in tmp_path.iterdir())) == before
    assert not (tmp_path / "backups").exists()


def test_a_missing_file_is_not_created(tmp_path):
    with pytest.raises(sqlite3.OperationalError):
        stat_history.open_readonly(tmp_path / "missing.db")
    assert list(tmp_path.iterdir()) == []


def test_a_database_from_a_newer_program_is_refused_untouched(tmp_path):
    db = tmp_path / "x.db"
    conn = sqlite3.connect(db)
    conn.execute(f"PRAGMA user_version = {stat_parser.SCHEMA_VERSION + 1}")
    conn.commit()
    conn.close()
    before = digest(db)
    with pytest.raises(SystemExit):
        stat_history.open_readonly(db)
    assert digest(db) == before


def test_a_database_from_before_schema_2_is_readable_without_migrating_it(tmp_path):
    db = tmp_path / "old.db"
    conn = sqlite3.connect(db)
    conn.executescript("""
        CREATE TABLE scans (scan_id INTEGER PRIMARY KEY AUTOINCREMENT, char_key TEXT NOT NULL,
            scanned_at TEXT NOT NULL, class TEXT, level INTEGER, faction TEXT, UNIQUE (char_key, scanned_at));
        CREATE TABLE stat_defs (stat_id INTEGER PRIMARY KEY, name TEXT NOT NULL, category TEXT NOT NULL);
        CREATE TABLE stat_values (scan_id INTEGER NOT NULL, stat_id INTEGER NOT NULL, value_text TEXT NOT NULL,
            value_num INTEGER, PRIMARY KEY (scan_id, stat_id));
        INSERT INTO scans VALUES (1, 'Alice-Realm', '2026-10-01 10:00:00', 'Mage', 80, 'Alliance');
        INSERT INTO stat_defs VALUES (1, 'Total deaths', 'Combat');
        INSERT INTO stat_values VALUES (1, 1, '1.234', 1234);
    """)
    conn.commit()
    conn.close()
    before = digest(db)
    h = history(db)
    assert h["char"] == {"key": KEY, "class": "Mage", "level": 80, "faction": "Alliance",
                         "class_file": None, "race": None, "race_file": None}
    assert by_id(h)[1]["v"] == [1234]
    assert digest(db) == before
