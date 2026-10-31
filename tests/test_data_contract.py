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
