# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

import pytest

from app import stat_parser
from core import i18n
from export import export_xlsx

openpyxl = pytest.importorskip("openpyxl")

SAMPLE = """
StatTrackerDB = {
	["meta"] = {
		[1] = { ["name"] = "Total deaths", ["cat"] = "Combat" },
		[2] = { ["name"] = "Gold earned", ["cat"] = "Wealth" },
		[3] = { ["name"] = "Race", ["cat"] = "Misc" },
		[4] = { ["name"] = "Empty", ["cat"] = "Misc" },
	},
	["chars"] = {
		["Alice-Realm"] = { ["scannedAt"] = "2026-10-01 10:00:00", ["class"] = "Mage", ["level"] = 80,
			["stats"] = { [1] = "10", [2] = "12g 5s 3c", [3] = "Elf", [4] = "--" },
			["playedTotal"] = 7200, ["playedLevel"] = 60 },
		["Bob-Realm"] = { ["scannedAt"] = "2026-10-02 10:00:00", ["class"] = "Rogue", ["level"] = 70,
			["stats"] = { [1] = "25", [2] = "1g", [3] = "5164 (Humanoid)", [4] = "--" },
			["playedTotal"] = 3600, ["playedLevel"] = 60 },
	},
}
"""


@pytest.fixture
def populated(instance, tmp_path):
    lua = tmp_path / "StatTracker.lua"
    lua.write_text(SAMPLE, encoding="utf-8")
    stat_parser.main(["--input", str(lua), "--db", str(instance / "data" / "wow_stats.db"),
                      "--output", str(instance / "data" / "stats.html")])
    return instance


def rows_by_name(ws):
    return {r[1].value: r for r in ws.iter_rows(min_row=2)}


def test_export_writes_one_sheet_with_units_and_values(populated):
    export_xlsx.export()
    wb = openpyxl.load_workbook(populated / "data" / "stattracker.xlsx")
    assert wb.sheetnames == ["Retail"]
    ws = wb["Retail"]
    assert [c.value for c in ws[1]][:4] == ["Category", "Statistic", "Unit", "Differs"]
    rows = rows_by_name(ws)
    assert "Empty" not in rows                                    # all '--' -> left out
    assert rows["Gold earned"][2].value == "Gold"
    assert rows["Gold earned"][4].value == pytest.approx(12.0503)  # 12g 5s 3c = 120503 copper
    assert rows["Total deaths"][2].value == "Number"
    assert rows["Total deaths"][3].value == "yes"
    assert rows["Race"][2].value == "Text"
    hours = rows["Total time played"]
    assert hours[2].value == "Hours" and hours[4].value == 2.0


def test_export_language_follows_gui_language(populated):
    i18n.set_language("de")
    export_xlsx.export()
    ws = openpyxl.load_workbook(populated / "data" / "stattracker.xlsx")["Retail"]
    assert [c.value for c in ws[1]][:4] == ["Kategorie", "Statistik", "Einheit", "Unterschied"]
    rows = rows_by_name(ws)
    assert rows["Gesamte Spielzeit"][2].value == "Std."
    assert rows["Total deaths"][3].value == "ja"


def test_best_value_is_highlighted_only_when_all_numeric(populated):
    export_xlsx.export()
    ws = openpyxl.load_workbook(populated / "data" / "stattracker.xlsx")["Retail"]
    deaths = rows_by_name(ws)["Total deaths"]
    assert deaths[5].fill.fgColor.rgb.endswith("C6EFCE")           # Bob 25 > Alice 10
    assert not deaths[4].fill.fgColor.rgb.endswith("C6EFCE")


POISONED = """
StatTrackerDB = {
	["meta"] = {
		[1] = { ["name"] = "=1+1", ["cat"] = "=Evil" },
		[2] = { ["name"] = "Note", ["cat"] = "Misc" },
	},
	["chars"] = {
		["=Evil-Realm"] = { ["scannedAt"] = "2026-10-01 10:00:00", ["class"] = "Mage", ["level"] = 80,
			["stats"] = { [1] = "=SUM(A1:A2)", [2] = "=HYPERLINK(1)" },
			["playedTotal"] = 7200, ["playedLevel"] = 60 },
	},
}
"""


def test_texts_from_the_game_file_never_become_formulas(instance, tmp_path):
    """openpyxl stores a text that starts with '=' as a formula; the export only writes data."""
    lua = tmp_path / "StatTracker.lua"
    lua.write_text(POISONED, encoding="utf-8")
    stat_parser.main(["--input", str(lua), "--db", str(instance / "data" / "wow_stats.db"),
                      "--output", str(instance / "data" / "stats.html")])
    export_xlsx.export()
    ws = openpyxl.load_workbook(instance / "data" / "stattracker.xlsx")["Retail"]
    cells = [c for row in ws.iter_rows() for c in row if c.value is not None]
    assert [c.coordinate for c in cells if c.data_type == "f"] == []
    values = {c.value for c in cells}
    assert {"=1+1", "=Evil", "=SUM(A1:A2)", "=HYPERLINK(1)"} <= values       # kept as they are, as text
    assert any(str(v).startswith("=Evil-Realm") for v in values)             # the column header


def test_export_without_databases_is_a_clear_error(instance):
    with pytest.raises(SystemExit) as exc:
        export_xlsx.export()
    assert "Read the data first" in str(exc.value)


def test_sheet_title():
    from pathlib import Path
    assert export_xlsx.sheet_title(Path("wow_stats.db")) == "Retail"
    assert export_xlsx.sheet_title(Path("wow_stats_classic_era.db")) == "Classic Era"


# ------------------------------------------------------------------------------ the characters the rules keep out of the file
ALICE, BOB = "Alice-Realm", "Bob-Realm"


def rule(key, **more):
    return {"type": "char", "value": key, **more}


def sheet(instance, name="Retail"):
    return openpyxl.load_workbook(instance / "data" / "stattracker.xlsx")[name]


def header_keys(ws):
    return [str(cell.value).split("\n")[0] for cell in ws[1]][4:]


def test_a_character_the_function_names_is_left_out_of_the_sheet(populated):
    seen = []

    def hidden(db, chars):
        seen.append((db.name, [c["key"] for c in chars]))
        return {ALICE}
    info = export_xlsx.export(hidden=hidden)
    assert seen == [("wow_stats.db", [ALICE, BOB])]
    ws = sheet(populated)
    assert header_keys(ws) == [BOB]
    assert not any("Alice" in str(c.value) for row in ws.iter_rows() for c in row if c.value is not None)
    deaths = rows_by_name(ws)["Total deaths"]
    assert deaths[4].value == 25 and not deaths[4].fill.fgColor.rgb.endswith("C6EFCE")       # one character left: nothing is "best"
    assert any("1 characters hidden" in line for line in info) and any("1 characters, " in line for line in info)


def test_without_the_function_every_character_stays(populated):
    export_xlsx.export()
    assert header_keys(sheet(populated)) == [ALICE, BOB]
    export_xlsx.export(hidden=lambda db, chars: set())
    assert header_keys(sheet(populated)) == [ALICE, BOB]


def test_with_every_character_left_out_nothing_is_written_and_the_message_says_why(populated):
    with pytest.raises(SystemExit) as exc:
        export_xlsx.export(hidden=lambda db, chars: {c["key"] for c in chars})
    assert "all characters are hidden" in str(exc.value) and "no database contains scans" not in str(exc.value)
    assert not (populated / "data" / "stattracker.xlsx").exists()


def test_a_sheet_whose_characters_are_all_left_out_is_skipped_and_the_others_stay(populated, tmp_path):
    lua = tmp_path / "second.lua"
    lua.write_text(SAMPLE, encoding="utf-8")
    stat_parser.main(["--input", str(lua), "--db", str(populated / "data" / "wow_stats_anniversary.db"),
                      "--output", str(populated / "data" / "stats_anniversary.html")])
    info = export_xlsx.export(hidden=lambda db, chars: {c["key"] for c in chars} if db.name == "wow_stats_anniversary.db" else set())
    wb = openpyxl.load_workbook(populated / "data" / "stattracker.xlsx")
    assert wb.sheetnames == ["Retail"] and header_keys(wb["Retail"]) == [ALICE, BOB]
    assert any("wow_stats_anniversary.db: all characters hidden, skipped" in line for line in info)


def test_the_database_gives_the_fields_the_rules_read(instance, tmp_path):
    lua = tmp_path / "StatTracker.lua"
    lua.write_text('StatTrackerDB = { version = 3, meta = { [1] = { name = "x", cat = "y" } }, chars = { ["A-B"] = { scannedAt = "2026-10-01 10:00:00", '
                   'class = "Mage", classFile = "MAGE", race = "Human", raceFile = "Human", level = 80, faction = "Alliance", stats = { [1] = "5" } } } }',
                   encoding="utf-8")
    db = instance / "data" / "wow_stats.db"
    stat_parser.main(["--input", str(lua), "--db", str(db), "--output", str(instance / "data" / "stats.html")])
    chars, _ = export_xlsx.load_db(db)
    assert [(c["key"], c["level"], c["faction"], c["class_file"], c["race_file"]) for c in chars] == [("A-B", 80, "Alliance", "MAGE", "Human")]


def test_an_old_database_without_the_columns_is_read_with_none_for_them(tmp_path):
    from test_db_schema import make_v01
    chars, _ = export_xlsx.load_db(make_v01(tmp_path / "wow_stats.db"))
    assert chars and all(c["class_file"] is None and c["race_file"] is None and "faction" in c for c in chars)


def three_characters(instance, tmp_path):
    """Mia (Mage, 80), Dru (Druid, 15), Old (60, scanned before the class file names existed: none)."""
    lua = tmp_path / "StatTracker.lua"
    lua.write_text('StatTrackerDB = { version = 3, meta = { [1] = { name = "x", cat = "y" } }, chars = { '
                   '["Mia-Realm"] = { scannedAt = "2026-10-01 10:00:00", class = "Mage", classFile = "MAGE", level = 80, faction = "Alliance", stats = { [1] = "5" } }, '
                   '["Dru-Realm"] = { scannedAt = "2026-10-01 10:00:00", class = "Druid", classFile = "DRUID", level = 15, faction = "Alliance", stats = { [1] = "7" } }, '
                   '["Old-Realm"] = { scannedAt = "2026-10-01 10:00:00", class = "Rogue", level = 60, faction = "Horde", stats = { [1] = "9" } } } }',
                   encoding="utf-8")
    stat_parser.main(["--input", str(lua), "--db", str(instance / "data" / "wow_stats.db"), "--output", str(instance / "data" / "stats.html")])


def test_every_type_of_rule_reaches_the_excel_file(instance, tmp_path):
    from app import actions
    three_characters(instance, tmp_path)
    expected = {("level_below", "20"): ["Mia / Realm", "Old / Realm"], ("class", "MAGE"): ["Dru / Realm", "Old / Realm"],      # the columns carry "Name / Realm"
                ("class", ""): ["Dru / Realm", "Mia / Realm"], ("faction", "Horde"): ["Dru / Realm", "Mia / Realm"],
                ("realm", "Realm"): None, ("char", "Mia-Realm"): ["Dru / Realm", "Old / Realm"]}
    for (kind, value), shown in expected.items():
        ok, out, _path = actions.run_export({"_retail_": [{"type": kind, "value": value, "for": ["excel"]}]})
        if shown is None:                                                                # the realm of all three: nothing is left
            assert ok is False and "all characters are hidden" in out
        else:
            assert ok is True and header_keys(sheet(instance)) == shown, (kind, value)
    ok, _out, _path = actions.run_export({"_retail_": [{"type": "level_below", "value": "20", "for": ["page"]}]})
    assert ok is True and header_keys(sheet(instance)) == ["Dru / Realm", "Mia / Realm", "Old / Realm"]


# ------------------------------------------------------------------------------ the same through the window's action
def test_the_action_leaves_out_the_characters_the_rules_of_the_version_name_for_excel(populated):
    from app import actions
    ok, out, _path = actions.run_export({"_retail_": [rule(ALICE, **{"for": ["excel"]})]})
    assert ok is True and header_keys(sheet(populated)) == ["Bob / Realm"] and "1 characters hidden" in out
    ok, out, _path = actions.run_export({"_retail_": [rule(ALICE)]})                       # no "for": the page and Excel
    assert ok is True and header_keys(sheet(populated)) == ["Bob / Realm"]


def test_the_action_leaves_every_character_in_when_no_rule_is_meant_for_this_sheet(populated):
    from app import actions
    for rules in (None, {}, {"_retail_": []}, {"_retail_": [rule(ALICE, **{"for": ["page"]})]}, {"_forever_": [rule(ALICE)]}):
        ok, out, _path = actions.run_export(rules)
        assert ok is True and header_keys(sheet(populated)) == ["Alice / Realm", "Bob / Realm"] and "hidden" not in out


def test_the_action_reports_that_everything_is_hidden(populated):
    from app import actions
    ok, out, _path = actions.run_export({"_retail_": [rule(ALICE), rule(BOB)]})
    assert ok is False and "all characters are hidden" in out and not (populated / "data" / "stattracker.xlsx").exists()
