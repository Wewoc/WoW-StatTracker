# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)
# What the window does without any widget (src/app/actions.py): the options of an import, the other accounts, the status
# line parts, the update check and the update download. Needs no window and no display.

import http.client
import urllib.error

import pytest

from app import actions
from core import app_info
from core import updater
from game import wow_install
from conftest import make_fake_wow


# ------------------------------------------------------------------------- update check
def _check_with(monkeypatch, error=None, data=None):
    def fetch():
        if error:
            raise error
        return data
    monkeypatch.setattr(updater, "fetch_latest_release", fetch)
    return actions.fetch_release()


def test_a_repository_without_a_release_counts_as_up_to_date(monkeypatch):
    err = urllib.error.HTTPError("https://api.github.com/x", 404, "Not Found", None, None)
    assert _check_with(monkeypatch, error=err) == ("release", {})


def test_other_http_errors_are_reported(monkeypatch):
    err = urllib.error.HTTPError("https://api.github.com/x", 403, "rate limit", None, None)
    kind, message = _check_with(monkeypatch, error=err)
    assert kind == "update_error" and "403" in message


def test_network_errors_are_reported(monkeypatch):
    kind, message = _check_with(monkeypatch, error=OSError("offline"))
    assert kind == "update_error" and "offline" in message


def test_a_release_is_handed_on_as_it_is(monkeypatch):
    assert _check_with(monkeypatch, data={"tag_name": "v9.9.9"}) == ("release", {"tag_name": "v9.9.9"})


# ----------------------------------------------------------------------- update download
def _downloaded(monkeypatch, prepare, asset=True):
    """Runs the download with prepare_update replaced by `prepare`; returns the queue message."""
    monkeypatch.setattr(updater, "resolve_release_asset",
                        lambda data, name: f"https://example.invalid/{name}" if asset else None)
    monkeypatch.setattr(updater, "prepare_update", prepare)
    return actions.download_update({})


def _raising(error):
    def prepare(*_a, **_k):
        raise error
    return prepare


@pytest.mark.parametrize("error, text", [
    (RuntimeError("checksum differs"), "checksum differs"),
    (OSError("disk full"), "disk full"),
])
def test_known_download_errors_are_reported_as_they_are(monkeypatch, error, text):
    assert _downloaded(monkeypatch, _raising(error)) == ("update_failed", text)


@pytest.mark.parametrize("error", [http.client.IncompleteRead(b"abc"), EOFError("short"), ValueError("odd")])
def test_any_other_download_error_is_still_reported(monkeypatch, error):
    """A worker that dies silently would leave the update flag set and block every later check."""
    kind, message = _downloaded(monkeypatch, _raising(error))
    assert kind == "update_failed" and type(error).__name__ in message


def test_a_release_without_the_zip_is_reported(monkeypatch):
    kind, message = _downloaded(monkeypatch, _raising(AssertionError("must not run")), asset=False)
    assert kind == "update_failed" and app_info.ZIP_ASSET_NAME in message


def test_a_prepared_update_is_handed_on(monkeypatch):
    assert _downloaded(monkeypatch, lambda *a, **k: "payload-dir") == ("apply", "payload-dir")


# ------------------------------------------------------------------------- the import
def test_the_import_hands_the_folders_and_the_game_files_on(instance, fake_wow, monkeypatch):
    seen = []
    monkeypatch.setattr(actions, "run_parser", lambda *a, **k: seen.append(a) or (True, ""))
    monkeypatch.setattr(wow_install, "WOW_CANDIDATES", ())
    actions.import_saved_variables("a.lua", fake_wow, "_retail_", True)
    sv, db, html, history, icons, game, product = seen[-1]
    assert (db, html) == wow_install.out_files("_retail_")
    assert history == wow_install.history_dir("_retail_") and icons == wow_install.icons_dir("_retail_")
    assert game == fake_wow and product == "wow"
    actions.import_saved_variables("a.lua", fake_wow, "_retail_", False)       # the icons already there are still shown
    sv, db, html, history, icons, game, product = seen[-1]
    assert icons == wow_install.icons_dir("_retail_") and game is None and product is None


def test_the_other_accounts_with_a_data_file_are_named(tmp_path):
    wow = make_fake_wow(tmp_path / "World of Warcraft")
    for name in ("ACC2", "ACC3", "NODATA"):
        path = wow_install.saved_vars_path(wow / "_retail_", name)
        path.parent.mkdir(parents=True, exist_ok=True)
        if name != "NODATA":
            path.write_text("StatTrackerDB = {}", encoding="utf-8")
    wow_install.saved_vars_path(wow / "_retail_", "ACC1").write_text("StatTrackerDB = {}", encoding="utf-8")
    assert sorted(actions.other_accounts(wow, "_retail_", "ACC1")) == ["ACC2", "ACC3"]
    assert sorted(actions.other_accounts(wow, "_retail_", "ACC2")) == ["ACC1", "ACC3"]


# ------------------------------------------------------------------------ the status line
def test_the_status_line_names_the_game_the_data_of_every_version_and_the_addon(instance, fake_wow, monkeypatch):
    monkeypatch.setattr(wow_install, "WOW_CANDIDATES", ())
    both = ["_retail_", "_forever_"]
    parts = actions.status_parts(fake_wow, both, "", "_retail_")
    assert parts[0] == f"Game: {fake_wow}" and "no account" in parts[1].lower()
    assert any("Addon: not installed" in p for p in parts)
    wow_install.saved_vars_path(fake_wow / "_retail_", "ACC1").write_text("x", encoding="utf-8")
    data = actions.status_parts(fake_wow, both, "ACC1", "_retail_")[1]
    assert data.startswith("Data: _retail_ 20") and data.endswith(" · _forever_ missing")      # the time of the file, then the version without one
    wow_install.install_addon(fake_wow, "_retail_")
    installed = wow_install.toc_version(wow_install.addon_dir(fake_wow, "_retail_") / "StatTracker.toc")      # the addon has its own version
    assert any(f"Addon: version {installed}" in p for p in actions.status_parts(fake_wow, both, "ACC1", "_retail_"))
    assert any("Addon: not installed" in p for p in actions.status_parts(fake_wow, both, "ACC1", "_forever_"))     # the addon part follows the version asked for


def test_the_import_hands_the_tiles_of_the_top_5_on_as_an_argument(instance, fake_wow, monkeypatch):
    seen = []
    monkeypatch.setattr(actions, "run_parser", lambda *a, **k: seen.append((a, k)) or (True, ""))
    monkeypatch.setattr(wow_install, "WOW_CANDIDATES", ())
    tiles = [{"stat": 328, "agg": "sum", "by": "class", "value": "MAGE"}]
    actions.import_saved_variables("a.lua", fake_wow, "_retail_", True, tiles)
    assert seen[-1][1] == {"top5": tiles, "rules": None, "skip": None}
    actions.import_saved_variables("a.lua", fake_wow, "_retail_", True)
    assert seen[-1][1] == {"top5": None, "rules": None, "skip": None}


def test_the_import_hands_the_rules_for_the_characters_kept_off_the_page_on(instance, fake_wow, monkeypatch):
    seen = []
    monkeypatch.setattr(actions, "run_parser", lambda *a, **k: seen.append(k) or (True, ""))
    monkeypatch.setattr(wow_install, "WOW_CANDIDATES", ())
    rules = [{"type": "char", "value": "Zoë-Realm"}]
    actions.import_saved_variables("a.lua", fake_wow, "_retail_", True, None, rules)
    assert seen[-1] == {"top5": None, "rules": rules, "skip": None}


def test_the_import_hands_the_blacklist_of_the_game_version_on(instance, fake_wow, monkeypatch):
    seen = []
    monkeypatch.setattr(actions, "run_parser", lambda *a, **k: seen.append(k) or (True, ""))
    monkeypatch.setattr(wow_install, "WOW_CANDIDATES", ())
    actions.import_saved_variables("a.lua", fake_wow, "_retail_", True, None, None, ["Zoë-Realm"])
    assert seen[-1] == {"top5": None, "rules": None, "skip": ["Zoë-Realm"]}


def test_the_parser_gets_the_skip_argument_only_when_there_are_deleted_characters(monkeypatch, tmp_path):
    import json
    given = []
    monkeypatch.setattr(actions.stat_parser, "main", lambda argv: given.append(argv))
    actions.run_parser("a.lua", tmp_path / "x.db", tmp_path / "x.html")
    actions.run_parser("a.lua", tmp_path / "x.db", tmp_path / "x.html", skip=[])
    assert all("--skip" not in argv for argv in given)
    actions.run_parser("a.lua", tmp_path / "x.db", tmp_path / "x.html", skip=["Zoë-Realm", "B-Two"])
    argv = given[-1]
    assert json.loads(argv[argv.index("--skip") + 1]) == ["Zoë-Realm", "B-Two"] and "--hide" not in argv


def test_the_parser_gets_the_hide_argument_only_when_there_are_rules(monkeypatch, tmp_path):
    import json
    given = []
    monkeypatch.setattr(actions.stat_parser, "main", lambda argv: given.append(argv))
    actions.run_parser("a.lua", tmp_path / "x.db", tmp_path / "x.html")
    actions.run_parser("a.lua", tmp_path / "x.db", tmp_path / "x.html", rules=[])
    assert all("--hide" not in argv for argv in given)
    rules = [{"type": "char", "value": "Zoë-Realm", "for": ["page"]}]
    actions.run_parser("a.lua", tmp_path / "x.db", tmp_path / "x.html", rules=rules)
    argv = given[-1]
    assert json.loads(argv[argv.index("--hide") + 1]) == rules and "--top5" not in argv


def test_the_parser_gets_the_argument_only_when_there_are_tiles(monkeypatch, tmp_path):
    import json
    given = []
    monkeypatch.setattr(actions.stat_parser, "main", lambda argv: given.append(argv))
    actions.run_parser("a.lua", tmp_path / "x.db", tmp_path / "x.html")
    actions.run_parser("a.lua", tmp_path / "x.db", tmp_path / "x.html", top5=[])
    assert all("--top5" not in argv for argv in given)
    tiles = [{"stat": 328, "agg": "sum", "by": "char", "value": "Zoë-Realm"}]
    actions.run_parser("a.lua", tmp_path / "x.db", tmp_path / "x.html", top5=tiles)
    argv = given[-1]
    assert json.loads(argv[argv.index("--top5") + 1]) == tiles


# ------------------------------------------------------------------------------------------------------------ the Top 5
def _database(instance):
    """A database and page for Retail made by the parser from the small sample file of its tests."""
    from app import stat_parser
    from test_stat_parser import SAMPLE
    source = instance / "StatTracker.lua"
    source.write_text(SAMPLE, encoding="utf-8")
    db, page = wow_install.out_files("_retail_")
    stat_parser.main(["--input", str(source), "--db", str(db), "--output", str(page)])
    return db, page


def test_the_choices_of_the_tiles_need_a_database(instance):
    assert actions.tile_choices("_retail_") is None


def test_the_choices_of_the_tiles_come_from_the_database(instance):
    _database(instance)
    found = actions.tile_choices("_retail_")
    labels = dict(found["stats"])
    assert labels[2] == "Gold earned (Wealth)" and -1 in labels and set(found["values"]) == {"char", "class", "race", "faction", "realm"}
    assert found["values"]["char"] == [("Alice-Realm", "Alice / Realm")] and found["values"]["faction"] == [("Alliance", "Alliance")]


def test_the_choices_for_the_rules_need_a_database(instance):
    assert actions.ignore_choices("_retail_") is None


def test_the_choices_for_the_rules_come_from_the_database_and_know_no_rule(instance):
    from core import config
    _database(instance)
    found = actions.ignore_choices("_retail_")
    assert set(found["values"]) == {"char", "class", "race", "faction", "realm"}
    assert found["values"]["char"] == [("Alice-Realm", "Alice / Realm")] and found["values"]["faction"] == [("Alliance", "Alliance")]
    assert [(c["key"], c["level"], c["faction"]) for c in found["chars"]] == [("Alice-Realm", 80, "Alliance")]
    cfg, _ = config.load()
    cfg["char_rules"] = {"_retail_": [{"type": "char", "value": "Alice-Realm"}]}
    config.save(cfg)
    assert actions.ignore_choices("_retail_") == found                               # a rule never takes an entry out of its own list


def test_a_database_newer_than_the_program_stops_the_choices_for_the_rules_too(instance):
    import sqlite3
    db, _page = _database(instance)
    conn = sqlite3.connect(db)
    conn.execute("PRAGMA user_version = 999")
    conn.commit()
    conn.close()
    with pytest.raises(SystemExit):
        actions.ignore_choices("_retail_")


def test_the_choices_leave_out_a_character_the_rules_keep_off_the_page(instance):
    _database(instance)
    found = actions.tile_choices("_retail_", [{"type": "char", "value": "Alice-Realm"}])
    assert found["values"]["char"] == [] and found["stats"] == []
    assert actions.tile_choices("_retail_", [{"type": "char", "value": "Bob-Realm"}])["values"]["char"] == [("Alice-Realm", "Alice / Realm")]
    assert actions.tile_choices("_retail_", [])["values"]["char"] == [("Alice-Realm", "Alice / Realm")]


def test_the_page_is_written_again_without_the_characters_the_rules_keep_off_it(instance):
    _db, page = _database(instance)
    assert "Alice-Realm" in page.read_text(encoding="utf-8")
    ok, _out = actions.rebuild_page("_retail_", [], [{"type": "char", "value": "Alice-Realm"}])
    assert ok is True and "Alice-Realm" not in page.read_text(encoding="utf-8")
    ok, _out = actions.rebuild_page("_retail_", [], [])                                # taking the rule away brings the character back
    assert ok is True and "Alice-Realm" in page.read_text(encoding="utf-8")


def test_a_database_newer_than_the_program_stops_the_choices_with_the_usual_message(instance):
    import sqlite3
    db, _page = _database(instance)
    conn = sqlite3.connect(db)
    conn.execute("PRAGMA user_version = 999")
    conn.commit()
    conn.close()
    with pytest.raises(SystemExit):
        actions.tile_choices("_retail_")
    ok, out = actions.rebuild_page("_retail_", [])
    assert ok is False and out.strip()


def test_the_page_is_written_again_with_the_tiles(instance):
    _db, page = _database(instance)
    tiles = [{"stat": 2, "agg": "sum", "by": "all", "value": ""}]
    ok, out = actions.rebuild_page("_retail_", tiles)
    text = page.read_text(encoding="utf-8")
    assert ok is True and 'id="top5"' in text and "Gold earned" in text.split('id="top5"')[1].split('<div data-slot="1">')[0]
    ok, _out = actions.rebuild_page("_retail_", [])
    assert ok is True and 'id="top5"' not in page.read_text(encoding="utf-8")


def test_writing_the_page_again_without_a_database_is_reported_and_creates_nothing(instance):
    ok, out = actions.rebuild_page("_retail_", [])
    db, page = wow_install.out_files("_retail_")
    assert ok is False and "OperationalError" in out and not db.exists() and not page.exists()


def _database_of(instance, variant):
    """A database and page for this game version, made by the parser from the small sample file of its tests."""
    from app import stat_parser
    from test_stat_parser import SAMPLE
    source = instance / "StatTracker.lua"
    source.write_text(SAMPLE, encoding="utf-8")
    db, page = wow_install.out_files(variant)
    stat_parser.main(["--input", str(source), "--db", str(db), "--output", str(page)])
    return db, page


def test_the_pages_of_several_game_versions_are_written_again_in_order(instance):
    _r_db, r_page = _database_of(instance, "_retail_")
    _f_db, f_page = _database_of(instance, "_forever_")
    r_page.unlink()
    f_page.unlink()
    results = actions.rebuild_pages([("_retail_", [], []), ("_forever_", [], [])])
    assert [(variant, ok) for variant, ok, _text in results] == [("_retail_", True), ("_forever_", True)]
    assert r_page.is_file() and f_page.is_file()


def test_one_version_that_fails_does_not_stop_the_others(instance):
    import sqlite3
    r_db, _r_page = _database_of(instance, "_retail_")
    _f_db, f_page = _database_of(instance, "_forever_")
    f_page.unlink()
    conn = sqlite3.connect(r_db)
    conn.execute("PRAGMA user_version = 999")                       # newer than the program: Retail stops with the usual message
    conn.commit()
    conn.close()
    results = actions.rebuild_pages([("_retail_", [], []), ("_forever_", [], [])])
    assert results[0][0] == "_retail_" and results[0][1] is False and results[0][2].strip()
    assert results[1][:2] == ("_forever_", True) and f_page.is_file()


def test_an_unexpected_error_becomes_the_text_of_its_entry(instance, monkeypatch):
    def broken(variant, tiles, rules=None):
        if variant == "_retail_":
            raise RuntimeError("boom")
        return True, ""
    monkeypatch.setattr(actions, "rebuild_page", broken)
    results = actions.rebuild_pages([("_retail_", [], []), ("_forever_", [], [])])
    assert results[0][1] is False and "RuntimeError: boom" in results[0][2] and results[1] == ("_forever_", True, "")


def test_no_jobs_give_no_results():
    assert actions.rebuild_pages([]) == []
