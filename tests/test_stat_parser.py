# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

import json
import re
import sqlite3

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
