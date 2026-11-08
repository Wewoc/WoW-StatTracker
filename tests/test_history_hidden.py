# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)
# The history pages of characters that the rules keep off the output: no page, no link, a page that exists is deleted, it comes back when the rule
# goes, and nothing else in the folder is touched. Runs with a fake plotly.js (the setup of test_history_hook.py).

import json
import sqlite3
from pathlib import Path

import pytest

from app import stat_parser
from pages import outputs, page_payload, stat_history
from test_history_hook import A, B, OLD, Run, lua, res  # noqa: F401  (res is a fixture)

T1, T2 = "2026-10-01 10:00:00", "2026-10-02 10:00:00"


class RunHide(Run):
    """Run, with rules for the characters kept off the page (the argument --hide)."""

    def __call__(self, *scans, rules=None, history=True):
        sv = self.dir / "StatTracker.lua"
        sv.write_text(lua(*scans), encoding="utf-8")
        args = ["--input", str(sv), "--db", str(self.dir / "x.db"), "--output", str(self.html)]
        if history:
            args += ["--history-dir", str(self.history)]
        if rules is not None:
            args += ["--hide", json.dumps(rules)]
        stat_parser.main(args)


@pytest.fixture
def run(tmp_path, res):  # noqa: F811
    return RunHide(tmp_path)


def hide(key, **more):
    return {"type": "char", "value": key, **more}


def two_pages(run):
    """Alice and Bob with two scans each: two history pages."""
    for at, deaths in ((T1, "1"), (T2, "2")):
        run((A, at, deaths), (B, at, deaths))
    assert run.pages() == sorted([stat_history.page_name(A), stat_history.page_name(B)])


def test_a_character_kept_off_the_page_gets_no_history_page_and_no_link(run):
    run((A, T1, "1"), (B, T1, "1"))
    run((A, T2, "2"), (B, T2, "2"), rules=[hide(A)])
    assert run.pages() == [stat_history.page_name(B)]
    payload = run.payload()
    assert [c["key"] for c in payload["chars"]] == [B] and list(payload["history"]["links"]) == [B]
    assert "Alice" not in run.html.read_text(encoding="utf-8")                # not in the data of the page either: no name, no file name


def test_a_page_that_exists_is_deleted_when_the_rule_comes_and_nothing_else_is_touched(run, capsys):
    two_pages(run)
    run.age_pages()
    capsys.readouterr()
    run((A, T2, "2"), rules=[hide(A)])                                      # nothing new in the file: only the rule is new
    assert run.pages() == [stat_history.page_name(B)] and run.untouched(B)
    assert (run.history / stat_history.GENERATOR_FILE).is_file()
    assert "History:  1 removed, character hidden" in capsys.readouterr().out
    assert list(run.payload()["history"]["links"]) == [B]


def test_the_page_comes_back_when_the_rule_goes_without_a_new_scan(run):
    two_pages(run)
    run((A, T2, "2"), rules=[hide(A)])
    run.age_pages()
    run((A, T2, "2"))                                                       # no rule any more, the same scan again
    assert run.page(A).is_file() and run.untouched(B)
    assert sorted(run.payload()["history"]["links"]) == [A, B]


def test_a_run_with_nothing_to_delete_leaves_every_file_alone(run, capsys):
    two_pages(run)
    run((A, T2, "2"), rules=[hide(A)])
    run.age_pages()
    capsys.readouterr()
    run((A, T2, "2"), rules=[hide(A)])                                      # the same rule again: the page is gone already
    assert run.untouched(B) and "removed" not in capsys.readouterr().out


def test_a_page_that_cannot_be_deleted_is_a_warning_and_the_import_goes_on(run, capsys, monkeypatch):
    two_pages(run)
    real = Path.unlink

    def stubborn(self, *args, **kwargs):
        if self.name == stat_history.page_name(A):
            raise PermissionError("locked")
        return real(self, *args, **kwargs)
    run.age_pages()
    capsys.readouterr()
    monkeypatch.setattr(Path, "unlink", stubborn)
    run((A, T2, "2"), rules=[hide(A)])                                      # does not raise
    out = capsys.readouterr().out
    assert "WARNING: history page of Alice-Realm not removed: locked" in out and "removed, character hidden" not in out
    assert run.page(A).is_file() and run.untouched(B)
    assert list(run.payload()["history"]["links"]) == [B]                   # kept off the page: no link, even though the file is still there


def test_the_other_types_keep_history_pages_off_too(run):
    two_pages(run)
    run.age_pages()
    run((A, T2, "2"), rules=[{"type": "faction", "value": "Horde"}])                  # both are Alliance: nobody is named
    assert run.untouched(A) and run.untouched(B)
    run((A, T2, "2"), rules=[{"type": "faction", "value": "Alliance"}])
    assert run.pages() == [] and "history" not in run.payload()                       # both named: no page, no link, no field
    run((A, T2, "2"), rules=[{"type": "level_below", "value": "81"}])                 # both are level 80
    assert run.pages() == []
    run((A, T2, "2"))
    assert len(run.pages()) == 2


def test_a_rule_for_excel_only_deletes_nothing(run):
    two_pages(run)
    run.age_pages()
    run((A, T2, "2"), rules=[hide(A, **{"for": ["excel"]})])
    assert run.untouched(A) and run.untouched(B) and sorted(run.payload()["history"]["links"]) == [A, B]


def test_only_the_exact_page_of_a_character_of_the_database_is_deleted(run):
    two_pages(run)
    other = run.history / "history-Alice-Realm-deadbeef.html"                # a name that looks like Alice's page, but is not
    notes = run.history / "notes.txt"
    other.write_text("x", encoding="utf-8")
    notes.write_text("y", encoding="utf-8")
    run.age_pages()
    run((A, T2, "2"), rules=[hide("Nobody-Here")])                          # a key the database does not know
    assert run.untouched(A) and run.untouched(B)
    run((A, T2, "2"), rules=[hide(A)])
    assert not run.page(A).exists() and run.page(B).is_file()
    assert other.read_text(encoding="utf-8") == "x" and notes.read_text(encoding="utf-8") == "y"


def test_write_pages_deletes_the_pages_of_the_keys_it_is_given_if_the_database_has_them(run):
    two_pages(run)
    conn = sqlite3.connect(run.dir / "x.db")
    try:
        result = stat_history.write_pages(conn, run.history, set(), hidden={A, "Ghost-Realm"})
        assert result["removed"] == [A] and result["remove_failed"] == [] and sorted(result["links"]) == [B]
        assert result["written"] == [] and not run.page(A).exists() and run.page(B).is_file()
        again = stat_history.write_pages(conn, run.history, set(), hidden={A})
        assert again["removed"] == [] and again["written"] == []
        assert sorted(stat_history.write_pages(conn, run.history, set())["links"]) == [A, B]    # no hidden: Alice's page is made again
    finally:
        conn.close()


def test_hidden_keys_reads_the_newest_scans_and_names_nobody_without_rules(run):
    two_pages(run)
    conn = sqlite3.connect(run.dir / "x.db")
    try:
        assert page_payload.hidden_keys(conn, [hide(A)]) == {A}
        assert page_payload.hidden_keys(conn, [hide(A), hide(B)]) == {A, B}
        assert page_payload.hidden_keys(conn, None) == set() and page_payload.hidden_keys(conn, []) == set()
        assert page_payload.hidden_keys(conn, [hide(A)], "excel") == {A}                     # a rule without "for" applies to both
        assert page_payload.hidden_keys(conn, [hide(A, **{"for": ["page"]})], "excel") == set()
    finally:
        conn.close()


def test_the_page_written_again_from_the_database_follows_the_rules_too(run):
    two_pages(run)
    payload, lines = outputs.rebuild_outputs(run.dir / "x.db", run.html, run.history, rules=[hide(A)])
    assert run.pages() == [stat_history.page_name(B)] and list(payload["history"]["links"]) == [B]
    assert any("removed" in line for line in lines)
    payload, _ = outputs.rebuild_outputs(run.dir / "x.db", run.html, run.history)
    assert sorted(payload["history"]["links"]) == [A, B] and run.page(A).is_file()
