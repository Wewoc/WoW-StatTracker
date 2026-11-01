# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

import json
import re
import sqlite3
from datetime import datetime

import pytest

import app_info
import i18n
import stat_parser

SAMPLE = """
StatTrackerDB = {
	["version"] = 2,
	["auto"] = true,
	["meta"] = {
		[1] = { ["name"] = "Total deaths", ["cat"] = "Combat > Deaths" },
		[2] = { ["name"] = "Gold earned", ["cat"] = "Wealth" },
		[3] = { ["name"] = "Average per day", ["cat"] = "Wealth" },
	},
	["chars"] = {
		["Alice-Realm"] = {
			["scannedAt"] = "2026-10-01 10:00:00",
			["scannedEpoch"] = 1,
			["class"] = "Mage", ["level"] = 80, ["faction"] = "Alliance",
			["stats"] = { [1] = "1.234", [2] = "12g 5s 3c", [3] = "0.20" },
			["playedTotal"] = 90061, ["playedLevel"] = 3600,
		},
	},
}
"""


@pytest.fixture
def sv(tmp_path):
    p = tmp_path / "StatTracker.lua"
    p.write_text(SAMPLE, encoding="utf-8")
    return p


def run(sv, tmp_path, extra=()):
    stat_parser.main(["--input", str(sv), "--db", str(tmp_path / "x.db"),
                      "--output", str(tmp_path / "out" / "x.html"), *extra])


def test_lua_reader_handles_tables_strings_numbers():
    parsed = stat_parser.LuaReader(SAMPLE).parse_file()
    db = parsed["StatTrackerDB"]
    assert db["auto"] is True
    assert db["chars"]["Alice-Realm"]["level"] == 80
    assert db["meta"][1]["name"] == "Total deaths"


def test_lua_reader_reports_line_number_on_error():
    with pytest.raises(stat_parser.LuaError, match="line 2"):
        stat_parser.LuaReader("a = 1\n= 2").parse_file()


@pytest.mark.parametrize("text,expected", [
    ("1.234", 1234),
    ("12 345", 12345),
    ("0.20", 0.2),
    ("3,5", 3.5),
    ("12g 5s 3c", 120503),
    ("--", None),
    ("", None),
    ("5164 (Humanoid)", None),
    ("12 %", None),
])
def test_to_number(text, expected):
    assert stat_parser.to_number(text) == expected


def test_clean_text_converts_coin_icons():
    raw = "12|TInterface\\MoneyFrame\\UI-GoldIcon:0|t 5|TInterface\\MoneyFrame\\UI-SilverIcon:0|t"
    assert stat_parser.clean_text(raw) == "12g 5s"


def test_import_creates_db_and_html(sv, tmp_path, capsys):
    run(sv, tmp_path)
    out = capsys.readouterr().out
    assert "1 new" in out and "Source:" in out
    html = (tmp_path / "out" / "x.html").read_text(encoding="utf-8")
    assert "Total deaths" in html and "/*__DATA__*/" not in html

    conn = sqlite3.connect(tmp_path / "x.db")
    nums = dict(conn.execute("SELECT stat_id, value_num FROM stat_values"))
    assert nums[1] == 1234 and nums[2] == 120503 and nums[3] == 0.2
    assert nums[-1] == 90061 and nums[-2] == 3600


def test_second_import_skips_known_scan(sv, tmp_path, capsys):
    run(sv, tmp_path)
    capsys.readouterr()
    run(sv, tmp_path)
    assert "0 new, 1 already" in capsys.readouterr().out


def _scan_at(sv, tmp_path, scanned_at):
    sv.write_text(sample(scanned_at=scanned_at), encoding="utf-8")
    run(sv, tmp_path)


def test_a_gap_since_the_previous_scan_is_mentioned(sv, tmp_path, capsys):
    _scan_at(sv, tmp_path, "2026-10-01 10:00:00")
    assert "may be missing" not in capsys.readouterr().out          # first import: nothing to compare with
    _scan_at(sv, tmp_path, "2026-10-10 10:00:00")
    out = capsys.readouterr().out
    assert "9 days" in out and "Alice-Realm" in out and "may be missing" in out
    assert not any(line.startswith(("WARNING", "ERROR")) for line in out.splitlines())    # a note, not a failure


def test_a_short_gap_is_not_mentioned(sv, tmp_path, capsys):
    _scan_at(sv, tmp_path, "2026-10-01 10:00:00")
    _scan_at(sv, tmp_path, "2026-10-02 22:00:00")
    assert "may be missing" not in capsys.readouterr().out


def test_an_import_without_a_new_scan_says_how_old_the_file_is(sv, tmp_path, capsys):
    run(sv, tmp_path)
    capsys.readouterr()
    run(sv, tmp_path)
    out = capsys.readouterr().out
    assert "Nothing new" in out and "2026-10-01 10:00:00" in out and "/reload" in out


def test_the_age_is_counted_in_whole_days_from_the_given_time():
    db = {"chars": {"A-B": {"scannedAt": "2026-10-10 10:00:00"}}}
    lines = stat_parser.import_notes(db, {}, 0, now=datetime(2026, 10, 13, 12, 0))
    assert len(lines) == 1 and "3 days old" in lines[0]
    behind = stat_parser.import_notes(db, {}, 0, now=datetime(2026, 10, 1))      # the clock is behind the scan
    assert "0 days old" in behind[0]


@pytest.mark.parametrize("db", [
    {}, {"chars": []}, {"chars": {"A-B": "text"}}, {"chars": {"A-B": {}}}, {"chars": {"A-B": {"scannedAt": "yesterday"}}},
])
def test_odd_data_gives_no_notes_and_no_error(db):
    assert stat_parser.import_notes(db, {"A-B": "2026-10-01 10:00:00"}, 1) == []
    assert stat_parser.import_notes(db, {}, 0) == []


def _payload_from_html(path):
    text = path.read_text(encoding="utf-8")
    m = re.search(r"const DATA = (\{.*?\});\n", text, re.S)
    return json.loads(m.group(1).replace("<\\/", "</"))


def test_payload_carries_language_and_ui_strings(sv, tmp_path):
    i18n.set_language("de")
    run(sv, tmp_path)
    data = _payload_from_html(tmp_path / "out" / "x.html")
    assert data["lang"] == "de"
    assert data["ui"]["title"] == "WoW-StatTracker"
    assert data["ui"]["footer_version"] == "Version {version}"
    assert data["app"] == {"version": app_info.APP_VERSION, "copyright": app_info.COPYRIGHT,
                           "license": app_info.LICENSE_NAME, "site": app_info.SITE_URL}
    played = {s["id"]: s for s in data["stats"]}[-1]
    assert played["name"] == "Gesamte Spielzeit"
    assert played["v"]["Alice-Realm"][0] == "1 Tage, 1 Std., 1 Min., 1 Sek."


def test_output_language_follows_current_language_even_for_old_rows(sv, tmp_path):
    i18n.set_language("de")
    run(sv, tmp_path)                 # rows written with German played labels
    i18n.set_language("en")
    run(sv, tmp_path)                 # same DB, English page
    data = _payload_from_html(tmp_path / "out" / "x.html")
    assert data["lang"] == "en"
    played = {s["id"]: s for s in data["stats"]}[-1]
    assert played["name"] == "Total time played"
    assert played["cat"] == "Character > Time played"
    assert played["v"]["Alice-Realm"][0] == "1 days, 1 h, 1 min, 1 s"   # DB text was German, page is English


def test_missing_played_time_warns(sv, tmp_path, capsys):
    sv.write_text(SAMPLE.replace('["playedTotal"] = 90061, ["playedLevel"] = 3600,', ""), encoding="utf-8")
    run(sv, tmp_path)
    assert "WARNING: Alice-Realm" in capsys.readouterr().out


def test_invalid_played_time_is_an_error(sv, tmp_path):
    sv.write_text(SAMPLE.replace('["playedTotal"] = 90061', '["playedTotal"] = -5'), encoding="utf-8")
    with pytest.raises(SystemExit) as exc:
        run(sv, tmp_path)
    assert "playedTotal" in str(exc.value)


def test_empty_db_variable_is_an_error(sv, tmp_path):
    sv.write_text("StatTrackerDB = { chars = {} }", encoding="utf-8")
    with pytest.raises(SystemExit):
        run(sv, tmp_path)


def test_missing_input_file(tmp_path):
    with pytest.raises(SystemExit) as exc:
        stat_parser.main(["--input", str(tmp_path / "nope.lua")])
    assert "not found" in str(exc.value)


def test_refresh_numbers_corrects_old_rows(sv, tmp_path):
    run(sv, tmp_path)
    conn = sqlite3.connect(tmp_path / "x.db")
    conn.execute("UPDATE stat_values SET value_num=20 WHERE stat_id=3")   # the old "0.20 -> 20" bug
    conn.commit()
    assert stat_parser.refresh_numbers(conn) == 1
    assert conn.execute("SELECT value_num FROM stat_values WHERE stat_id=3").fetchone()[0] == 0.2
    conn.close()


# ------------------------------------------------- class file, race, race file (data version 3)
RACE_FIELDS = '["classFile"] = "MAGE", ["race"] = "Human", ["raceFile"] = "Human",'


def sample(fields="", scanned_at="2026-10-01 10:00:00", version=3):
    """SAMPLE with other scan time, data version and extra fields on the character."""
    text = SAMPLE.replace('["version"] = 2', f'["version"] = {version}')
    text = text.replace('"2026-10-01 10:00:00"', f'"{scanned_at}"')
    return text.replace('["faction"] = "Alliance",', f'["faction"] = "Alliance", {fields}')


def race_rows(tmp_path):
    conn = sqlite3.connect(tmp_path / "x.db")
    try:
        return conn.execute("SELECT scanned_at, class_file, race, race_file FROM scans ORDER BY scanned_at").fetchall()
    finally:
        conn.close()


def test_class_file_race_and_race_file_are_stored_and_reach_the_page(sv, tmp_path):
    sv.write_text(sample(RACE_FIELDS), encoding="utf-8")
    run(sv, tmp_path)
    assert race_rows(tmp_path) == [("2026-10-01 10:00:00", "MAGE", "Human", "Human")]
    char = _payload_from_html(tmp_path / "out" / "x.html")["chars"][0]
    assert (char["class"], char["class_file"], char["race"], char["race_file"]) == ("Mage", "MAGE", "Human", "Human")


@pytest.mark.parametrize("lang,mage,undead", [("de", "Magier", "Untoter"), ("en", "Mage", "Undead")])
def test_payload_carries_class_and_race_names_in_the_page_language(sv, tmp_path, lang, mage, undead):
    i18n.set_language(lang)
    sv.write_text(sample(RACE_FIELDS), encoding="utf-8")
    run(sv, tmp_path)
    names = _payload_from_html(tmp_path / "out" / "x.html")["names"]
    assert names["class"]["MAGE"] == mage and names["race"]["Scourge"] == undead
    assert "class_MAGE" not in names["class"]                # keyed by the file name, without the key prefix


def test_a_scan_from_an_older_addon_has_no_race(sv, tmp_path):
    run(sv, tmp_path)                                         # SAMPLE: version 2, no new fields
    assert race_rows(tmp_path) == [("2026-10-01 10:00:00", None, None, None)]
    char = _payload_from_html(tmp_path / "out" / "x.html")["chars"][0]
    assert (char["class_file"], char["race"], char["race_file"]) == (None, None, None)


def test_a_known_scan_is_never_filled_in_later(sv, tmp_path, capsys):
    run(sv, tmp_path)                                         # the scan is stored without a race
    capsys.readouterr()
    sv.write_text(sample(RACE_FIELDS), encoding="utf-8")      # same scan time, now with a race
    run(sv, tmp_path)
    assert "0 new, 1 already" in capsys.readouterr().out
    assert race_rows(tmp_path) == [("2026-10-01 10:00:00", None, None, None)]


def test_every_scan_keeps_the_race_it_had_and_the_page_shows_the_latest(sv, tmp_path):
    sv.write_text(sample(RACE_FIELDS), encoding="utf-8")
    run(sv, tmp_path)
    changed = RACE_FIELDS.replace('"Human"', '"Orc"').replace('"MAGE"', '"WARLOCK"')    # a race change
    sv.write_text(sample(changed, scanned_at="2026-10-05 10:00:00"), encoding="utf-8")
    run(sv, tmp_path)
    assert race_rows(tmp_path) == [("2026-10-01 10:00:00", "MAGE", "Human", "Human"),
                                   ("2026-10-05 10:00:00", "WARLOCK", "Orc", "Orc")]
    char = _payload_from_html(tmp_path / "out" / "x.html")["chars"][0]
    assert (char["class_file"], char["race"], char["race_file"]) == ("WARLOCK", "Orc", "Orc")


def test_a_value_of_the_wrong_type_or_an_empty_one_becomes_null(sv, tmp_path):
    odd = '["classFile"] = 5, ["race"] = true, ["raceFile"] = "  ",'
    sv.write_text(sample(odd), encoding="utf-8")
    run(sv, tmp_path)                                         # no abort for display data
    assert race_rows(tmp_path) == [("2026-10-01 10:00:00", None, None, None)]


def test_localized_race_and_stable_file_are_kept_apart(sv, tmp_path):
    german = '["classFile"] = "MAGE", ["race"] = "Mensch", ["raceFile"] = "Human",'
    sv.write_text(sample(german).replace('["class"] = "Mage"', '["class"] = "Magier"'), encoding="utf-8")
    run(sv, tmp_path)
    char = _payload_from_html(tmp_path / "out" / "x.html")["chars"][0]
    assert (char["class"], char["class_file"], char["race"], char["race_file"]) == ("Magier", "MAGE", "Mensch", "Human")
