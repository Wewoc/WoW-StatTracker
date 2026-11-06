# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)
# The history of one character (stat_history): order, gaps, units, and that reading never writes.

import base64
import hashlib
import sqlite3

import pytest

from core import i18n
from game import wow_icons
from pages import stat_history
from store import db_schema
from store import importer
from store import stat_values

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


def gear_scan(at, items, ilvl=(600.5, 598.25), spec=(250, "Blood", "TANK")):
    """A scan with the parts of data contract 4: specialization, item level and equipped items ({slot: item})."""
    c = scan(at, {1: "1"})
    c.update(specID=spec[0], specName=spec[1], role=spec[2], ilvlTotal=ilvl[0], ilvlEquipped=ilvl[1], gear=items)
    return c


def item(item_id, name, ilvl, **extra):
    return {"itemID": item_id, "name": name, "quality": 4, "ilvl": ilvl, "iconID": item_id + 1000, **extra}


def make_db(path, scans, key=KEY):
    """A database made the way the importer makes it: one import per scan, in the given order."""
    conn = db_schema.init_db(path)
    for c in scans:
        importer.import_data(conn, {"meta": META, "chars": {key: c}})
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
        assert stat_values.COIN_TEXT.fullmatch(text)
        assert stat_values.to_number(text) is not None
    for text in ("1.234", "0.20", "--", "Kodo", "3 d 4 h"):
        assert not stat_values.COIN_TEXT.fullmatch(text)


def test_played_time_is_in_seconds_and_named_in_the_current_language(tmp_path):
    db = make_db(tmp_path / "x.db", [scan("2026-10-01 10:00:00", {1: "1"}, played=7200),
                                     scan("2026-10-02 10:00:00", {1: "2"}, played=10800)])
    i18n.set_language("en")
    en = by_id(history(db))[-1]
    i18n.set_language("de")
    de = by_id(history(db))[-1]
    assert en["v"] == de["v"] == [7200, 10800]
    assert de["name"] == stat_values.played_labels()[-1][0]
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
    conn.execute(f"PRAGMA user_version = {db_schema.SCHEMA_VERSION + 1}")
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
    assert h["gear"] is None                        # no specialization columns, no gear table: no gear block
    assert digest(db) == before


def test_a_database_at_schema_2_has_no_gear_block(tmp_path):
    db = make_db(tmp_path / "x.db", [scan("2026-10-01 10:00:00", {1: "1"})])
    conn = sqlite3.connect(db)
    for table in ("scan_gear", "scan_reputation", "rep_defs"):
        conn.execute(f"DROP TABLE {table}")
    for column in db_schema.SCAN_COLUMNS_V3:
        conn.execute(f"ALTER TABLE scans DROP COLUMN {column[0]}")
    conn.execute("PRAGMA user_version = 2")
    conn.commit()
    conn.close()
    h = history(db)
    assert h["gear"] is None and by_id(h)[1]["v"] == [1]


def test_gear_comes_per_scan_oldest_first_with_the_items_by_slot(tmp_path):
    db = make_db(tmp_path / "x.db", [
        gear_scan("2026-10-02 10:00:00", {10: item(2, "Gloves", 610), 1: item(1, "Helm", 620,
                  enchantText="Enchant X", sockets=1, gems={1: 240870}, stats={"ITEM_MOD_CRIT_RATING_SHORT": 120},
                  upgrade={"trackID": 972, "track": "Veteran", "level": 2, "max": 6})}, ilvl=(605.0, 603.5)),
        gear_scan("2026-10-01 10:00:00", {1: item(1, "Old helm", 600)})])
    gear = history(db)["gear"]
    assert [g["ilvl_total"] for g in gear] == [600.5, 605.0]                      # same order as "scans"
    assert (gear[1]["spec_id"], gear[1]["spec_name"], gear[1]["role"], gear[1]["ilvl_equipped"]) == (250, "Blood", "TANK", 603.5)
    assert [i["slot"] for i in gear[1]["items"]] == [1, 10] and [i["name"] for i in gear[0]["items"]] == ["Old helm"]
    helm = gear[1]["items"][0]
    assert (helm["item_id"], helm["quality"], helm["ilvl"], helm["icon_id"]) == (1, 4, 620, 1001)
    assert (helm["enchant_text"], helm["sockets"], helm["gem_ids"]) == ("Enchant X", 1, [240870])
    assert helm["stats"] == {"ITEM_MOD_CRIT_RATING_SHORT": 120}
    assert (helm["upg_track_id"], helm["upg_track"], helm["upg_level"], helm["upg_max"]) == (972, "Veteran", 2, 6)
    assert gear[1]["items"][1]["gem_ids"] is None and gear[1]["items"][1]["stats"] is None      # not given: None


def test_a_scan_without_gear_data_is_none_and_so_is_a_history_without_any(tmp_path):
    db = make_db(tmp_path / "x.db", [scan("2026-10-01 10:00:00", {1: "1"}),
                                     gear_scan("2026-10-02 10:00:00", {1: item(1, "Helm", 620)})])
    gear = history(db)["gear"]
    assert gear[0] is None and gear[1]["items"][0]["name"] == "Helm"
    plain = make_db(tmp_path / "y.db", [scan("2026-10-01 10:00:00", {1: "1"}), scan("2026-10-02 10:00:00", {1: "2"})])
    assert history(plain)["gear"] is None                                         # schema 3, but nothing collected


def test_a_scan_with_only_a_specialization_still_has_an_entry(tmp_path):
    c = scan("2026-10-01 10:00:00", {1: "1"})
    c.update(specID=62, specName="Arcane", role="DAMAGER")
    entry = history(make_db(tmp_path / "x.db", [c]))["gear"][0]
    assert (entry["spec_id"], entry["items"], entry["ilvl_total"]) == (62, [], None)


def test_unreadable_json_in_a_gear_row_leaves_only_that_field_empty(tmp_path):
    db = make_db(tmp_path / "x.db", [gear_scan("2026-10-01 10:00:00", {1: item(1, "Helm", 620, gems={1: 5},
                                                                          stats={"ITEM_MOD_CRIT_RATING_SHORT": 1})})])
    conn = sqlite3.connect(db)
    conn.execute("UPDATE scan_gear SET stats='{broken', gem_ids='{\"a\": 1}'")        # not JSON / not a list
    conn.commit()
    conn.close()
    helm = history(db)["gear"][0]["items"][0]
    assert helm["stats"] is None and helm["gem_ids"] is None and helm["name"] == "Helm"


# ------------------------------------------------------------------ the item icons of a page
PNG = stat_history.PNG_SIGNATURE + b"fake png data"


def icon_db(tmp_path):
    """A database whose character wore the items 1 and 2 (icon ids 1001 and 1002) and one without an icon."""
    return make_db(tmp_path / "icons.db", [
        gear_scan("2026-10-01 10:00:00", {1: item(1, "Helm", 600), 2: item(2, "Neck", 598)}),
        gear_scan("2026-10-02 10:00:00", {1: item(1, "Helm", 600), 3: {"itemID": 3, "name": "No icon", "quality": 4, "ilvl": 1}}),
    ])


def payload_with_icons(db, icons_dir):
    conn = stat_history.open_readonly(db)
    try:
        return stat_history.build_page_payload(conn, KEY, icons_dir=icons_dir)
    finally:
        conn.close()


def put_icon(folder, icon_id, data=PNG):
    folder.mkdir(parents=True, exist_ok=True)
    wow_icons.icon_path(folder, icon_id).write_bytes(data)


def test_the_icons_of_the_items_a_character_wore_are_embedded_as_data_uris(tmp_path):
    icons = tmp_path / "icons"
    for icon_id in (1001, 1002, 1003):                 # 1003 belongs to an item this character never wore
        put_icon(icons, icon_id, PNG + str(icon_id).encode())
    found = payload_with_icons(icon_db(tmp_path), icons)["icons"]
    assert sorted(found) == ["1001", "1002"]
    for icon_id, uri in found.items():
        assert uri == "data:image/png;base64," + base64.b64encode(PNG + icon_id.encode()).decode("ascii")


def test_no_icons_field_without_a_folder_without_files_or_for_a_character_without_gear(tmp_path):
    db = icon_db(tmp_path)
    assert "icons" not in payload_with_icons(db, None)
    assert "icons" not in payload_with_icons(db, tmp_path / "no-such-folder")
    empty = tmp_path / "empty"
    empty.mkdir()
    assert "icons" not in payload_with_icons(db, empty)
    put_icon(tmp_path / "icons", 1001)
    plain = make_db(tmp_path / "plain.db", [scan("2026-10-01 10:00:00", {1: "1"}), scan("2026-10-02 10:00:00", {1: "2"})])
    assert "icons" not in payload_with_icons(plain, tmp_path / "icons")


def test_a_file_that_is_not_a_png_too_big_or_unreadable_is_left_out(tmp_path):
    icons = tmp_path / "icons"
    put_icon(icons, 1001, b"GIF89a not a png")
    put_icon(icons, 1002, PNG + bytes(stat_history.MAX_ICON_BYTES))
    wow_icons.icon_path(icons, 1003).mkdir()           # a folder where the file should be
    assert "icons" not in payload_with_icons(icon_db(tmp_path), icons)
    put_icon(icons, 1001)
    assert list(payload_with_icons(icon_db(tmp_path), icons)["icons"]) == ["1001"]


def test_the_icon_ids_come_from_the_items_of_every_scan_and_ignore_what_is_no_id():
    gear = [None, {"items": [{"icon_id": 5}, {"icon_id": None}, {}, {"icon_id": True}, {"icon_id": "7"}]}, {"items": [{"icon_id": 5}, {"icon_id": 9}]}]
    assert stat_history.icon_ids(gear) == {5, 9}
    assert stat_history.icon_ids(None) == set()


def test_reading_the_icons_leaves_the_database_alone(tmp_path):
    db = icon_db(tmp_path)
    before = digest(db)
    put_icon(tmp_path / "icons", 1001)
    payload_with_icons(db, tmp_path / "icons")
    assert digest(db) == before
