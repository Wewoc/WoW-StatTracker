# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)
# The rules that keep characters off the stats page on their way from the settings (config.char_rules) into the page: the argument --hide of the import
# (the window hands over the rules of the game version, the parser reads no settings file) and the page that is written again from the database
# (outputs.rebuild_outputs). The database is never changed by them.

import json
import re
import sqlite3

import pytest

from app import stat_parser
from pages import outputs
from test_char_rules import REP, scan

HIDE_A = [{"type": "char", "value": "A-One"}]


@pytest.fixture
def sv(tmp_path):
    p = tmp_path / "StatTracker.lua"
    p.write_text('StatTrackerDB = { version = 4, meta = { [1] = { name = "Kills", cat = "Combat" } }, repMeta = { [2696] = { name = "Amani" } }, '
                 'chars = { ["A-One"] = %s, ["B-Two"] = %s } }' % (scan(80, "5", REP), scan(70, "7")), encoding="utf-8")
    return p


def run(sv, tmp_path, *extra):
    stat_parser.main(["--input", str(sv), "--db", str(tmp_path / "x.db"), "--output", str(tmp_path / "out" / "x.html"), *extra])
    return (tmp_path / "out" / "x.html").read_text(encoding="utf-8")


def data_of(text):
    return json.loads(re.search(r"const DATA = (.*?);\s*const \$ =", text, re.S).group(1).replace("<\\/", "</"))


def keys_of(text):
    return [c["key"] for c in data_of(text)["chars"]]


def test_without_the_argument_nobody_is_kept_off_the_page(sv, tmp_path):
    assert keys_of(run(sv, tmp_path)) == ["A-One", "B-Two"]


def test_the_import_keeps_off_the_page_the_characters_the_rules_name(sv, tmp_path):
    text = run(sv, tmp_path, "--hide", json.dumps(HIDE_A))
    assert keys_of(text) == ["B-Two"] and "A-One" not in text and "Amani" not in text        # nor anything else of it: its reputation list was the only one


def test_the_import_keeps_off_the_page_the_characters_under_a_level(sv, tmp_path):
    text = run(sv, tmp_path, "--hide", json.dumps([{"type": "level_below", "value": "75"}]))
    assert keys_of(text) == ["A-One"]                                                  # B-Two is level 70
    assert keys_of(run(sv, tmp_path, "--hide", json.dumps([{"type": "level_below", "value": "70"}]))) == ["A-One", "B-Two"]


def test_a_rule_for_excel_only_does_not_touch_the_page(sv, tmp_path):
    text = run(sv, tmp_path, "--hide", json.dumps([{"type": "char", "value": "A-One", "for": ["excel"]}]))
    assert keys_of(text) == ["A-One", "B-Two"]


def test_the_page_written_again_from_the_database_takes_the_rules_it_is_given_and_the_database_stays_as_it_is(sv, tmp_path):
    run(sv, tmp_path)
    db, html = tmp_path / "x.db", tmp_path / "out" / "again.html"

    def counts():
        conn = sqlite3.connect(db)
        try:
            return [conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in ("scans", "stat_values", "scan_reputation")]
        finally:
            conn.close()
    before = counts()
    payload, _ = outputs.rebuild_outputs(db, html, rules=HIDE_A)
    assert [c["key"] for c in payload["chars"]] == ["B-Two"] and "A-One" not in html.read_text(encoding="utf-8")
    payload, _ = outputs.rebuild_outputs(db, html)                                          # no rule: the character is back, nothing was lost
    assert [c["key"] for c in payload["chars"]] == ["A-One", "B-Two"] and "A-One" in html.read_text(encoding="utf-8")
    assert counts() == before


def test_rules_that_are_not_shaped_like_one_are_dropped_and_a_text_that_is_no_json_gives_a_warning(sv, tmp_path, capsys):
    text = run(sv, tmp_path, "--hide", json.dumps([HIDE_A[0], "x", {"type": "char"}, {"value": "B-Two"}]))
    assert keys_of(text) == ["B-Two"] and "WARNING" not in capsys.readouterr().out
    text = run(sv, tmp_path, "--hide", json.dumps({"type": "char", "value": "A-One"}))      # not a list: no rules, no warning (the shape is only checked)
    assert keys_of(text) == ["A-One", "B-Two"] and "WARNING" not in capsys.readouterr().out
    text = run(sv, tmp_path, "--hide", "{not json")
    assert keys_of(text) == ["A-One", "B-Two"]
    assert "WARNING: the rules that hide characters are not valid JSON and are not applied" in capsys.readouterr().out


def test_the_parser_reads_no_settings_file_for_the_rules_either(sv, tmp_path, monkeypatch):
    """A settings file of the machine must not keep a character off a page that was asked for without rules."""
    from core import config
    monkeypatch.setattr(config, "load", lambda: (_ for _ in ()).throw(AssertionError("the parser must not read the settings")))
    assert keys_of(run(sv, tmp_path)) == ["A-One", "B-Two"]
