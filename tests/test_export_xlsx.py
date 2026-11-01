# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

import pytest

import export_xlsx
import i18n
import stat_parser

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
