# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)
# The data version of StatTracker.lua (StatTrackerDB.version): a file with a higher or an unreadable
# number is refused before the database is opened (no copy, no change, no page), a missing number
# and every number up to DATA_VERSION pass.

import hashlib

import pytest

import i18n
import stat_parser
from stat_parser import DATA_VERSION


def lua_file(folder, version_line='["version"] = 2,'):
    path = folder / "StatTracker.lua"
    path.write_text('StatTrackerDB = {' + version_line + ' meta = { [1] = { name = "x", cat = "y" } }, '
                    'chars = { ["A-B"] = { scannedAt = "2026-10-02 10:00:00", stats = { [1] = "5" } } } }',
                    encoding="utf-8")
    return path


def run(folder, version_line):
    lua = lua_file(folder, version_line)
    args = ["--input", str(lua), "--db", str(folder / "wow_stats.db"), "--output", str(folder / "out.html")]
    stat_parser.main(args)
    return lua


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.mark.parametrize("version_line", [
    "",                                  # no number: hand-made file
    '["version"] = nil,',                # nil is the same as absent
    '["version"] = 0,',
    '["version"] = 1,',
    '["version"] = 2,',                  # the addon of 0.1.x
    f'["version"] = {DATA_VERSION},',
])
def test_missing_and_known_versions_are_imported(tmp_path, version_line, capsys):
    run(tmp_path, version_line)
    assert "1 new" in capsys.readouterr().out
    assert (tmp_path / "out.html").exists()


@pytest.mark.parametrize("version_line", [
    f'["version"] = {DATA_VERSION + 1},',
    '["version"] = 99,',
    f'["version"] = {DATA_VERSION}.5,',      # not a whole number
    '["version"] = "2",',                    # text
    '["version"] = true,',
    '["version"] = {},',
])
def test_a_newer_or_unreadable_version_is_refused_before_anything_is_written(tmp_path, version_line):
    with pytest.raises(SystemExit) as exc:
        run(tmp_path, version_line)
    message = str(exc.value)
    assert str(tmp_path / "StatTracker.lua") in message and str(DATA_VERSION) in message
    assert not (tmp_path / "wow_stats.db").exists()          # not even created
    assert not (tmp_path / "out.html").exists()
    assert not (tmp_path / "backups").exists()


def test_a_refused_file_leaves_an_existing_database_untouched_and_takes_no_copy(tmp_path):
    db = tmp_path / "wow_stats.db"
    stat_parser.init_db(db).close()
    before = digest(db)
    with pytest.raises(SystemExit):
        run(tmp_path, f'["version"] = {DATA_VERSION + 1},')
    assert digest(db) == before
    assert not (tmp_path / "backups").exists()


def test_the_message_exists_in_both_languages(tmp_path):
    messages = {}
    for lang in ("de", "en"):
        i18n.set_language(lang)
        with pytest.raises(SystemExit) as exc:
            run(tmp_path, '["version"] = 99,')
        messages[lang] = str(exc.value)
    assert messages["de"] != messages["en"]
    assert "Datenformat" in messages["de"] and "data format" in messages["en"]
    assert all("99" in m and str(DATA_VERSION) in m for m in messages.values())


def test_check_accepts_a_table_without_a_version_and_ignores_other_shapes():
    stat_parser.check_data_version({"chars": {}}, "x.lua")
    stat_parser.check_data_version("not a table", "x.lua")     # import_data reports that case as before


# ------------------------------------------------------------------ version 4: older scans (history) and the new parts
import sqlite3

from stat_parser import LuaReader


def scan_lua(at, extra="", played=True):
    """One scan as the addon writes it, as Lua text."""
    played_text = " playedTotal = 3600, playedLevel = 60," if played else ""
    return f'{{ scannedAt = "{at}", level = 80,{played_text} stats = {{ [1] = "5" }},{extra} }}'


def file_lua(folder, newest, older=(), key="A-B", version=4, history=None):
    """StatTracker.lua with `newest` in chars and `older` (newest first, as the addon keeps them) in history."""
    ring = ""
    if history is not None:
        ring = f" history = {history},"
    elif older:
        ring = f' history = {{ ["{key}"] = {{ {", ".join(older)} }} }},'
    path = folder / "StatTracker.lua"
    path.write_text(f'StatTrackerDB = {{ version = {version}, meta = {{ [1] = {{ name = "x", cat = "y" }} }},{ring} '
                    f'chars = {{ ["{key}"] = {newest} }} }}', encoding="utf-8")
    return path


def import_file(folder, lua):
    stat_parser.main(["--input", str(lua), "--db", str(folder / "wow_stats.db"), "--output", str(folder / "out.html")])


def scans_in(folder):
    conn = sqlite3.connect(folder / "wow_stats.db")
    try:
        return conn.execute("SELECT scan_id, char_key, scanned_at FROM scans ORDER BY scan_id").fetchall()
    finally:
        conn.close()


def test_a_file_with_history_imports_every_scan_oldest_first(tmp_path, capsys):
    lua = file_lua(tmp_path, scan_lua("2026-10-03 10:00:00"),
                   [scan_lua("2026-10-02 10:00:00"), scan_lua("2026-10-01 10:00:00")])   # newest first, like the addon
    import_file(tmp_path, lua)
    assert "3 new, 0 already" in capsys.readouterr().out
    assert [row[2] for row in scans_in(tmp_path)] == ["2026-10-01 10:00:00", "2026-10-02 10:00:00", "2026-10-03 10:00:00"]
    conn = sqlite3.connect(tmp_path / "wow_stats.db")
    played = conn.execute("SELECT COUNT(*) FROM stat_values WHERE stat_id < 0").fetchone()[0]
    conn.close()
    assert played == 3 * 2                                           # every scan has its played time


def test_importing_the_same_file_again_changes_nothing(tmp_path, capsys):
    lua = file_lua(tmp_path, scan_lua("2026-10-03 10:00:00"), [scan_lua("2026-10-02 10:00:00")])
    import_file(tmp_path, lua)
    capsys.readouterr()
    import_file(tmp_path, lua)
    assert "0 new, 2 already" in capsys.readouterr().out
    assert [row[2] for row in scans_in(tmp_path)] == ["2026-10-02 10:00:00", "2026-10-03 10:00:00"]


def test_a_scan_that_is_in_chars_and_in_history_is_stored_once(tmp_path):
    lua = file_lua(tmp_path, scan_lua("2026-10-03 10:00:00"), [scan_lua("2026-10-03 10:00:00")])
    import_file(tmp_path, lua)
    assert len(scans_in(tmp_path)) == 1


def test_the_order_in_the_history_does_not_matter(tmp_path):
    lua = file_lua(tmp_path, scan_lua("2026-10-03 10:00:00"),
                   [scan_lua("2026-10-01 10:00:00"), scan_lua("2026-10-02 10:00:00")])   # oldest first this time
    import_file(tmp_path, lua)
    assert [row[2] for row in scans_in(tmp_path)] == ["2026-10-01 10:00:00", "2026-10-02 10:00:00", "2026-10-03 10:00:00"]


def test_a_version_3_file_without_history_imports_as_before(tmp_path, capsys):
    lua = file_lua(tmp_path, scan_lua("2026-10-03 10:00:00"), version=3)
    import_file(tmp_path, lua)
    assert "1 new, 0 already" in capsys.readouterr().out


def test_a_character_known_only_from_history_is_imported_too(tmp_path):
    lua = file_lua(tmp_path, scan_lua("2026-10-03 10:00:00"),
                   history='{ ["C-D"] = { ' + scan_lua("2026-10-01 10:00:00") + ' } }')
    import_file(tmp_path, lua)
    assert sorted({row[1] for row in scans_in(tmp_path)}) == ["A-B", "C-D"]


@pytest.mark.parametrize("history, message", [
    ('{ ["A-B"] = { { scannedAt = "2026-10-01 10:00:00" } } }', "older scan no. 1 of 'A-B'"),               # no statistics
    ('{ ["A-B"] = { ' + scan_lua("2026-10-01 10:00:00") + ', { stats = { [1] = "5" } } } }', "older scan no. 2 of 'A-B'"),  # no time
    ('{ ["A-B"] = "text" }', "list of older scans of 'A-B'"),
    ('{ ["A-B"] = { name = ' + scan_lua("2026-10-01 10:00:00") + ' } }', "list of older scans of 'A-B'"),    # not positional
    ('{ ["A-B"] = { 5 } }', "older scan no. 1 of 'A-B'"),
    ('"text"', "'history' in the file"),
    ('5', "'history' in the file"),
])
def test_a_broken_history_stops_the_import_before_anything_is_stored(tmp_path, history, message):
    lua = file_lua(tmp_path, scan_lua("2026-10-03 10:00:00"), history=history)
    with pytest.raises(SystemExit) as exc:
        import_file(tmp_path, lua)
    assert message in str(exc.value)
    assert scans_in(tmp_path) == []                                  # not even the good newest scan


def test_both_languages_have_the_messages_of_the_history(tmp_path):
    for lang in ("de", "en"):
        i18n.set_language(lang)
        lua = file_lua(tmp_path, scan_lua("2026-10-03 10:00:00"), history='{ ["A-B"] = { 5 } }')
        with pytest.raises(SystemExit) as exc:
            import_file(tmp_path, lua)
        assert ("Älterer Scan" if lang == "de" else "older scan") in str(exc.value)


def test_a_history_entry_without_played_time_is_reported_like_a_newest_scan(tmp_path, capsys):
    lua = file_lua(tmp_path, scan_lua("2026-10-03 10:00:00"), [scan_lua("2026-10-02 10:00:00", played=False)])
    import_file(tmp_path, lua)
    out = capsys.readouterr().out
    assert out.count("no played time") == 1 and "no played time in the scan from 2026-10-02 10:00:00" in out


def test_import_data_names_a_character_whose_only_new_scan_is_in_the_history(tmp_path):
    conn = stat_parser.init_db(tmp_path / "x.db")
    newest = {"scannedAt": "2026-10-03 10:00:00", "stats": {1: "5"}}
    older = {"scannedAt": "2026-10-02 10:00:00", "stats": {1: "5"}}
    db = {"meta": {1: {"name": "x", "cat": "y"}}, "chars": {"A-B": newest}}
    assert stat_parser.import_data(conn, db) == (1, 0, ["A-B"])
    db["history"] = {"A-B": {1: older}}
    assert stat_parser.import_data(conn, db) == (1, 1, ["A-B"])      # only the history brought something new
    assert stat_parser.import_data(conn, db) == (0, 2, [])
    conn.close()


# --- read_scan: the parts added by version 4 are optional and checked, a wrong type is NULL, never a stop
def read(table_text):
    return stat_parser.read_scan(LuaReader("X = " + table_text).parse_file()["X"])


NEW_PARTS = '''{ scannedAt = "2026-10-01 10:00:00", stats = { [1] = "5" },
  specID = 72, specName = "Fury", role = "DAMAGER", ilvlTotal = 276.5, ilvlEquipped = 275,
  gear = { [3] = { itemID = 209894, name = "Mantle", quality = 4, ilvl = 269, iconID = 5178362,
                   stats = { ITEM_MOD_STAMINA_SHORT = 1374, RESISTANCE0_NAME = 52 }, enchantID = 8028, enchantText = "Shoulders - X",
                   upgrade = { trackID = 971, track = "Adventurer", level = 2, max = 6 } },
           [11] = { itemID = 100011, sockets = 2, gems = { 0, 5 } } },
  rep = { { id = 2698, ord = 1, hdr = true },
          { id = 2696, ord = 2, aw = true, kind = "std", reaction = 5, standing = 3000, lo = 3000, hi = 9000 },
          { id = 2744, ord = 3, aw = true, kind = "friend", standing = 250754, lo = 245747, hi = 264497, level = 22, maxLevel = 80 },
          { id = 2640, ord = 4, child = true, kind = "major", renown = 7, earned = 2069, need = 2500, maxRenown = 20,
            paragon = { value = 100, threshold = 7500, quest = 93566, pending = false } } } }'''


def test_the_new_parts_are_read_as_written():
    scan = read(NEW_PARTS)
    assert (scan["spec_id"], scan["spec_name"], scan["role"], scan["ilvl_total"], scan["ilvl_equipped"]) == (72, "Fury", "DAMAGER", 276.5, 275)
    gear = {row["slot"]: row for row in scan["gear"]}
    assert sorted(gear) == [3, 11]
    assert (gear[3]["item_id"], gear[3]["name"], gear[3]["ilvl"], gear[3]["enchant_id"], gear[3]["upg_track_id"], gear[3]["upg_max"]) == \
        (209894, "Mantle", 269, 8028, 971, 6)
    assert gear[3]["stats"] == {"ITEM_MOD_STAMINA_SHORT": 1374, "RESISTANCE0_NAME": 52}
    assert gear[11]["sockets"] == 2 and gear[11]["gem_ids"] == [0, 5] and gear[11]["enchant_id"] is None
    rep = scan["rep"]
    assert [row["ord"] for row in rep] == [1, 2, 3, 4]                            # the order of the game
    assert (rep[0]["is_header"], rep[0]["kind"], rep[0]["standing"]) == (1, None, None)
    assert (rep[1]["kind"], rep[1]["account_wide"], rep[1]["reaction"], rep[1]["hi"]) == ("std", 1, 5, 9000)
    assert (rep[2]["kind"], rep[2]["standing"], rep[2]["level"], rep[2]["max_level"], rep[2]["reaction"]) == ("friend", 250754, 22, 80, None)
    assert (rep[3]["kind"], rep[3]["renown"], rep[3]["max_renown"], rep[3]["is_child"], rep[3]["p_value"], rep[3]["p_pending"]) == \
        ("major", 7, 20, 1, 100, 0)
    assert scan["skipped"] == 0


def test_a_scan_of_version_3_has_none_of_the_new_parts():
    scan = read('{ scannedAt = "2026-10-01 10:00:00", stats = { [1] = "5" } }')
    assert scan["spec_id"] is None and scan["ilvl_total"] is None and scan["gear"] == [] and scan["rep"] == [] and scan["skipped"] == 0


def test_a_wrong_type_is_null_and_a_bool_is_no_number():
    scan = read('''{ scannedAt = "x", stats = { [1] = "5" }, specID = "72", specName = 5, role = "", ilvlTotal = true,
                      ilvlEquipped = "276", gear = { [3] = { itemID = 1, quality = true, ilvl = "269", name = 7,
                      stats = { A = "no", B = 2, [5] = 3 }, upgrade = "no", sockets = "2", gems = { 1, "x" } } } }''')
    assert (scan["spec_id"], scan["spec_name"], scan["role"], scan["ilvl_total"], scan["ilvl_equipped"]) == (None,) * 5
    (item,) = scan["gear"]
    assert (item["quality"], item["ilvl"], item["name"], item["sockets"], item["upg_track_id"], item["gem_ids"]) == (None,) * 6
    assert item["stats"] == {"B": 2}                                              # only text keys with numbers stay
    assert scan["skipped"] == 0                                                   # nothing was dropped, only NULL


def test_unusable_gear_and_reputation_entries_are_skipped_and_counted():
    scan = read('''{ scannedAt = "x", stats = { [1] = "5" },
        gear = { [0] = { itemID = 1 }, [20] = { itemID = 2 }, ["x"] = { itemID = 3 }, [4] = "text", [5] = { name = "no id" },
                 [6] = { itemID = true }, [7] = { itemID = 7 } },
        rep = { { id = 1, ord = 1 }, { ord = 2 }, { id = 3 }, { id = 4, ord = 4, kind = "other" }, { id = 5, ord = 1 },
                { id = 0, ord = 6 }, "text", { id = 8, ord = 8, kind = "std", reaction = 4 } } }''')
    assert [row["slot"] for row in scan["gear"]] == [7]
    assert [row["ord"] for row in scan["rep"]] == [1, 8]
    assert scan["skipped"] == 6 + 6                                               # six gear entries, six reputation entries


def test_reputation_that_is_not_a_positional_table_counts_as_one_skipped_part():
    scan = read('{ scannedAt = "x", stats = { [1] = "5" }, rep = { a = { id = 1, ord = 1 } }, gear = "text" }')
    assert scan["rep"] == [] and scan["gear"] == [] and scan["skipped"] == 2


def test_skipped_details_are_reported_once_with_the_scan_time(tmp_path, capsys):
    extra = ' rep = { { id = 1, ord = 1 }, { ord = 2 } }, gear = { [0] = { itemID = 1 } },'
    lua = file_lua(tmp_path, scan_lua("2026-10-03 10:00:00", extra=extra))
    import_file(tmp_path, lua)
    assert "2 details (gear, reputation) in the scan from 2026-10-03 10:00:00" in capsys.readouterr().out
    import_file(tmp_path, lua)                                                    # already stored: not warned again
    assert "(gear, reputation)" not in capsys.readouterr().out


# --- what a version 4 file leaves in the database
def import_parts(folder, newest, older=(), rep_meta='{ [2696] = { name = "Amani" }, [2698] = { name = "Midnight" } }'):
    ring = f' history = {{ ["A-B"] = {{ {", ".join(older)} }} }},' if older else ""
    path = folder / "StatTracker.lua"
    path.write_text(f'StatTrackerDB = {{ version = 4, meta = {{ [1] = {{ name = "x", cat = "y" }} }}, repMeta = {rep_meta},{ring} '
                    f'chars = {{ ["A-B"] = {newest} }} }}', encoding="utf-8")
    import_file(folder, path)
    return sqlite3.connect(folder / "wow_stats.db")


def test_the_new_parts_of_a_scan_are_stored(tmp_path):
    conn = import_parts(tmp_path, NEW_PARTS)
    assert conn.execute("SELECT spec_id, spec_name, role, ilvl_total, ilvl_equipped FROM scans").fetchall() == \
        [(72, "Fury", "DAMAGER", 276.5, 275.0)]
    gear = {r[0]: r for r in conn.execute("SELECT slot, item_id, name, ilvl, enchant_id, enchant_text, upg_track_id, upg_track, "
                                          "upg_level, upg_max, sockets, gem_ids, stats FROM scan_gear")}
    assert sorted(gear) == [3, 11]
    assert gear[3] == (3, 209894, "Mantle", 269, 8028, "Shoulders - X", 971, "Adventurer", 2, 6, None, None,
                       '{"ITEM_MOD_STAMINA_SHORT":1374,"RESISTANCE0_NAME":52}')       # the keys sorted, no spaces
    assert gear[11][10:] == (2, "[0,5]", None)
    rep = conn.execute("SELECT ord, faction_id, is_header, is_child, account_wide, kind, reaction, standing, lo, hi, level, max_level, "
                       "renown, earned, need, max_renown, p_value, p_threshold, p_quest, p_pending FROM scan_reputation ORDER BY ord").fetchall()
    assert [r[0] for r in rep] == [1, 2, 3, 4]
    assert rep[0] == (1, 2698, 1, 0, 0, None) + (None,) * 14
    assert rep[1] == (2, 2696, 0, 0, 1, "std", 5, 3000, 3000, 9000) + (None,) * 10
    assert rep[2] == (3, 2744, 0, 0, 1, "friend", None, 250754, 245747, 264497, 22, 80) + (None,) * 8
    assert rep[3] == (4, 2640, 0, 1, 0, "major") + (None,) * 6 + (7, 2069, 2500, 20, 100, 7500, 93566, 0)
    assert dict(conn.execute("SELECT faction_id, name FROM rep_defs")) == {2696: "Amani", 2698: "Midnight"}
    conn.close()


def test_a_scan_without_the_new_parts_leaves_them_empty_next_to_one_with_them(tmp_path):
    conn = import_parts(tmp_path, NEW_PARTS, older=[scan_lua("2026-09-01 10:00:00")])
    old = conn.execute("SELECT spec_id, spec_name, role, ilvl_total, ilvl_equipped FROM scans WHERE scanned_at < '2026-10'").fetchall()
    assert old == [(None,) * 5]
    ids = {r[0]: r[1] for r in conn.execute("SELECT scan_id, scanned_at FROM scans")}
    holders = {ids[r[0]] for r in conn.execute("SELECT DISTINCT scan_id FROM scan_gear UNION SELECT DISTINCT scan_id FROM scan_reputation")}
    assert holders == {"2026-10-01 10:00:00"}
    conn.close()


def test_the_gear_and_reputation_of_an_older_scan_in_the_history_are_stored_with_it(tmp_path):
    older = NEW_PARTS.replace("2026-10-01 10:00:00", "2026-09-01 10:00:00").replace("specID = 72", "specID = 73")
    conn = import_parts(tmp_path, NEW_PARTS, older=[older])
    per_scan = conn.execute("SELECT s.scanned_at, s.spec_id, (SELECT COUNT(*) FROM scan_gear g WHERE g.scan_id = s.scan_id), "
                            "(SELECT COUNT(*) FROM scan_reputation r WHERE r.scan_id = s.scan_id) FROM scans s ORDER BY s.scanned_at").fetchall()
    assert per_scan == [("2026-09-01 10:00:00", 73, 2, 4), ("2026-10-01 10:00:00", 72, 2, 4)]
    conn.close()


def test_importing_again_adds_no_row(tmp_path):
    conn = import_parts(tmp_path, NEW_PARTS, older=[scan_lua("2026-09-01 10:00:00")])
    counts = lambda: [conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in ("scans", "scan_gear", "scan_reputation", "rep_defs")]
    first = counts()
    conn.close()
    conn = import_parts(tmp_path, NEW_PARTS, older=[scan_lua("2026-09-01 10:00:00")])
    assert counts() == first == [2, 2, 4, 2]
    conn.close()


def test_a_scan_that_was_stored_without_the_parts_is_never_filled_in_later(tmp_path):
    conn = import_parts(tmp_path, scan_lua("2026-10-01 10:00:00"))                  # the same scan time, no parts
    conn.close()
    conn = import_parts(tmp_path, NEW_PARTS)                                        # now the file has them for that time
    assert conn.execute("SELECT spec_id FROM scans").fetchall() == [(None,)]
    assert conn.execute("SELECT COUNT(*) FROM scan_gear").fetchone()[0] == 0
    conn.close()


def test_a_faction_name_is_updated_at_every_import(tmp_path):
    import_parts(tmp_path, NEW_PARTS).close()
    conn = import_parts(tmp_path, scan_lua("2026-10-05 10:00:00"), rep_meta='{ [2696] = { name = "Amani Tribe" }, [5] = "no", [0] = { name = "zero" } }')
    assert dict(conn.execute("SELECT faction_id, name FROM rep_defs")) == {2696: "Amani Tribe", 2698: "Midnight"}   # junk is ignored
    conn.close()


def test_a_file_without_rep_meta_still_imports(tmp_path):
    path = tmp_path / "StatTracker.lua"
    path.write_text('StatTrackerDB = { version = 4, meta = { [1] = { name = "x", cat = "y" } }, chars = { ["A-B"] = ' + NEW_PARTS + ' } }',
                    encoding="utf-8")
    import_file(tmp_path, path)
    conn = sqlite3.connect(tmp_path / "wow_stats.db")
    assert conn.execute("SELECT COUNT(*) FROM rep_defs").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM scan_reputation").fetchone()[0] == 4
    conn.close()
