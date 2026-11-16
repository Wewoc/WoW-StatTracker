# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)
# The real Qt main window in a temporary instance, without a screen (QT_QPA_PLATFORM=offscreen, set in conftest).
# One window is shared by the tests of this module (the embedded browser is slow to start); `window` resets it.
# What the window does is tested in test_actions.py; here only that it shows and wires it correctly. The look and the
# JavaScript of the pages are checked by hand.

import shutil
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from PyQt6.QtCore import QUrl, Qt
from PyQt6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile, QWebEngineSettings
from PyQt6.QtWebEngineWidgets import QWebEngineView

from app import actions, dialogs, main_window, qt_style
from conftest import ROOT, make_fake_wow
from core import app_info, config, i18n, paths, theme
from game import wow_install
from pages import outputs
from rules import char_names
from test_groups_block import make_payload


@pytest.fixture(scope="module")
def env(qapp, tmp_path_factory):
    mp = pytest.MonkeyPatch()
    base = tmp_path_factory.mktemp("instance")
    wow = make_fake_wow(tmp_path_factory.mktemp("wowroot") / "World of Warcraft")
    mp.setattr(paths, "base_dir", lambda: base)
    mp.setattr(wow_install, "WOW_CANDIDATES", ())
    (base / "addon").mkdir()
    shutil.copytree(ROOT / "addon" / "StatTracker", base / "addon" / "StatTracker")
    cfg, _ = config.load()
    cfg.update(wow_dir=str(wow), language="en", check_updates=False)
    config.save(cfg)
    win = main_window.MainWindow()
    win.show()
    yield SimpleNamespace(win=win, wow=wow, base=base)
    win.close()
    qapp.processEvents()
    mp.undo()


@pytest.fixture
def window(env, qtbot):
    """The shared window, set back to a known state before each test."""
    w = env.win
    w.tabs.setCurrentIndex(main_window.TAB_SETTINGS)              # first: a Top 5 tab left open would read its choices in a thread
    i18n.set_language("en")
    w.cfg.update(language="en", enabled_variants=["_retail_"], read_icons=True, check_updates=False, active_theme=1, group_presets=[], top5={}, char_rules={}, char_blacklist={})
    w._tile_choices, w._tile_key = None, None
    w._chars_key = None
    w.cmb_lang.setCurrentIndex(w.cmb_lang.findData("en"))
    w.retranslate()
    w.clear_log()
    w._update_open = False
    w.ed_wow.setText(str(env.wow))
    wow_install.uninstall_addon(env.wow, "_retail_")
    page = wow_install.out_files("_retail_")[1]
    page.unlink(missing_ok=True)
    w.refresh_variants(keep="_retail_")
    w.tabs.setCurrentIndex(main_window.TAB_SETTINGS)
    return w


def items(combo):
    return [combo.itemText(i) for i in range(combo.count())]


def as_shown(*keys):
    """The texts a character is shown with ("Name / Realm"): the lists of the window show these, the keys stay the data behind them."""
    return [char_names.display(key) for key in keys]


def wait_idle(qtbot, window):
    qtbot.waitUntil(lambda: not window._busy, timeout=10000)


# ----------------------------------------------------------------- what the window shows
def test_default_shows_retail_only(window):
    assert items(window.cmb_var) == ["_retail_"]
    assert window.cmb_var.currentText() == "_retail_" and window.cmb_acc.currentText() == "ACC1"
    assert "Addon: not installed" in window.status_text()
    assert [window.tabs.tabText(i) for i in range(window.tabs.count())] == ["Settings", "Page", "Top 5", "Characters"]


def test_enabling_another_version_adds_it_to_the_dropdown(window):
    window.cfg["enabled_variants"] = ["_retail_", "_forever_"]
    window.refresh_variants()
    assert items(window.cmb_var) == ["_retail_", "_forever_"]


def test_a_typed_in_disabled_version_is_reported(window, env):
    window.ed_wow.setText(str(env.wow / "_forever_"))
    assert window.root_and_variant() == (env.wow, None)
    assert "not enabled" in window.status_text()


def variant_boxes(window):
    """The check boxes of the game versions as they are now (they are made again after every change)."""
    return {window.variant_boxes.itemAt(i).widget().text(): window.variant_boxes.itemAt(i).widget()
            for i in range(window.variant_boxes.count())}


def test_a_version_that_was_not_tested_has_a_greyed_check_box_that_cannot_be_enabled(window):
    boxes = variant_boxes(window)
    assert boxes["_retail_"].isEnabled() and boxes["_forever_"].isEnabled() and boxes["_forever_"].toolTip() == ""
    assert "_classic_" in boxes                                                  # found in the game folder, but not tried with a real client
    assert not boxes["_classic_"].isEnabled() and not boxes["_classic_"].isChecked()
    assert boxes["_classic_"].toolTip() == "Untested: not available yet"


def test_an_untested_version_that_is_enabled_already_can_still_be_switched_off_and_is_never_taken_out_of_the_settings(window):
    window.cfg["enabled_variants"] = ["_retail_", "_classic_"]
    window.refresh_variants()
    assert window.cfg["enabled_variants"] == ["_retail_", "_classic_"]           # kept as it is
    box = variant_boxes(window)["_classic_"]
    assert box.isEnabled() and box.isChecked() and box.toolTip() == ""
    box.setChecked(False)
    assert window.cfg["enabled_variants"] == ["_retail_"]
    assert not variant_boxes(window)["_classic_"].isEnabled()                    # off now: it cannot be switched on again


def test_the_version_check_boxes_enable_a_version_and_keep_at_least_one(window, env, monkeypatch):
    errors = []
    monkeypatch.setattr(dialogs, "error", lambda parent, text: errors.append(text))
    boxes = variant_boxes(window)
    assert set(boxes) >= {"_retail_", "_forever_"} and boxes["_retail_"].isChecked() and not boxes["_forever_"].isChecked()
    boxes["_forever_"].setChecked(True)
    assert window.cfg["enabled_variants"] == ["_retail_", "_forever_"]
    assert config.load()[0]["enabled_variants"] == ["_retail_", "_forever_"]
    assert items(window.cmb_var) == ["_retail_", "_forever_"]
    variant_boxes(window)["_forever_"].setChecked(False)
    assert window.cfg["enabled_variants"] == ["_retail_"] and not errors
    variant_boxes(window)["_retail_"].setChecked(False)           # the last one cannot be switched off
    assert errors and window.cfg["enabled_variants"] == ["_retail_"]
    assert variant_boxes(window)["_retail_"].isChecked()


def test_the_options_are_saved(window):
    window.chk_updates.setChecked(True)
    window.chk_icons.setChecked(False)
    cfg = config.load()[0]
    assert cfg["check_updates"] is True and cfg["read_icons"] is False


def test_install_then_uninstall_through_the_window(window, env, monkeypatch):
    monkeypatch.setattr(dialogs, "ask_yes_no", lambda *a, **k: True)
    window.on_install()
    assert wow_install.addon_dir(env.wow, "_retail_").is_dir()
    installed = wow_install.toc_version(wow_install.addon_dir(env.wow, "_retail_") / "StatTracker.toc")      # the addon has its own version
    assert f"Addon: version {installed}" in window.status_text()
    window.on_uninstall()
    assert not wow_install.addon_dir(env.wow, "_retail_").exists()
    assert "Addon: not installed" in window.status_text()


def test_the_status_shows_a_wrong_interface_number_until_reinstalled(window, env):
    window.on_install()
    toc = wow_install.addon_dir(env.wow, "_retail_") / "StatTracker.toc"
    toc.write_text(toc.read_text(encoding="utf-8").replace("## Interface: 120105", "## Interface: 120000"), encoding="utf-8")
    window.update_status()
    assert "interface number does not match the game (installed 120000, game 120105)" in window.status_text()
    window.on_install()
    assert "Addon: version" in window.status_text()


def test_the_language_switch_keeps_the_log_and_changes_every_text(window):
    window.write("hello log")
    window.cmb_lang.setCurrentIndex(window.cmb_lang.findData("de"))
    window.on_language()
    assert i18n.get_language() == "de" and config.load()[0]["language"] == "de"
    assert "hello log" in window.log.toPlainText()
    assert "Addon: nicht installiert" in window.status_text()
    assert [window.tabs.tabText(i) for i in range(window.tabs.count())] == ["Einstellungen", "Seite", "Top 5", "Charaktere"]
    assert window.action_buttons[2].text() == "Einlesen + öffnen"
    window.cmb_lang.setCurrentIndex(window.cmb_lang.findData("en"))
    window.on_language()
    assert window.action_buttons[2].text() == "Read + open"


def test_the_design_is_chosen_in_the_window_and_applies_after_a_restart(window):
    window.cmb_theme.setCurrentIndex(window.cmb_theme.findData(3))
    window.on_theme()
    assert config.load()[0]["active_theme"] == 3
    assert "restart" in window.log.toPlainText()
    assert window.colors == theme.colors(1)                  # not changed on the spot
    assert window.cmb_theme.count() == len(theme.THEMES)


# ------------------------------------------------------------------------------ the import
def _fake_parser(monkeypatch, output="", gate=None, seen=None):
    def run(*args, **kwargs):
        if seen is not None:
            seen.append(args)
        if gate is not None:
            gate.wait(10)
        return True, output
    monkeypatch.setattr(actions, "run_parser", run)


def test_reading_one_account_names_the_other_accounts_with_data(window, env, qtbot, monkeypatch):
    """Every account has its own file; the others are not read and would silently lose their scans."""
    made = []
    for name in ("ACC1", "ACC2", "ACC3"):
        path = wow_install.saved_vars_path(env.wow / "_retail_", name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("StatTrackerDB = {}", encoding="utf-8")
        made.append(path)
    try:
        _fake_parser(monkeypatch)
        window.on_parse()
        wait_idle(qtbot, window)
        note = [line for line in window.log.toPlainText().splitlines() if "Note:" in line]
        assert len(note) == 1 and "ACC2" in note[0] and "ACC3" in note[0] and "ACC1" not in note[0]
    finally:
        for path in made:
            if path.parent.parent.name == "ACC1":
                path.unlink(missing_ok=True)
            else:
                shutil.rmtree(path.parent.parent, ignore_errors=True)


def test_the_import_passes_the_icon_options_on(window, env, qtbot, monkeypatch):
    path = wow_install.saved_vars_path(env.wow / "_retail_", "ACC1")
    path.write_text("StatTrackerDB = {}", encoding="utf-8")
    try:
        seen = []
        _fake_parser(monkeypatch, seen=seen)
        window.cfg["read_icons"] = True
        window.on_parse()
        wait_idle(qtbot, window)
        history, icons, game, product = seen[-1][3:]
        assert history == wow_install.history_dir("_retail_") and icons == wow_install.icons_dir("_retail_")
        assert game == env.wow and product == "wow"
        window.cfg["read_icons"] = False                         # the icons already there are still shown
        window.on_parse()
        wait_idle(qtbot, window)
        assert seen[-1][5:] == (None, None)
    finally:
        path.unlink(missing_ok=True)


def test_while_the_import_runs_the_buttons_are_off_and_the_status_says_so(window, env, qtbot, monkeypatch):
    path = wow_install.saved_vars_path(env.wow / "_retail_", "ACC1")
    path.write_text("StatTrackerDB = {}", encoding="utf-8")
    gate = threading.Event()
    try:
        _fake_parser(monkeypatch, gate=gate)
        window.on_parse()
        assert window._busy and not any(b.isEnabled() for b in window.action_buttons)
        assert window.statusBar().currentMessage() == "Reading data ..."
        window.on_parse()                                         # a second click while it runs does nothing
        gate.set()
        wait_idle(qtbot, window)
        assert all(b.isEnabled() for b in window.action_buttons)
        assert window.statusBar().currentMessage() == "Ready."
        assert window.log.toPlainText().count("Read successfully.") == 1
    finally:
        gate.set()
        path.unlink(missing_ok=True)


def test_reading_without_a_data_file_says_so_and_starts_nothing(window, monkeypatch):
    errors = []
    monkeypatch.setattr(dialogs, "error", lambda parent, text: errors.append(text))
    _fake_parser(monkeypatch, gate=None, seen=(called := []))
    window.on_parse()
    assert not window._busy and errors and not called


def _both_versions(window):
    window.cfg["enabled_variants"] = ["_retail_", "_forever_"]
    window.refresh_variants()


def _data_files(env, *variants, account="ACC1"):
    files = []
    for variant in variants:
        path = wow_install.saved_vars_path(env.wow / variant, account)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("StatTrackerDB = {}", encoding="utf-8")
        files.append(path)
    return files


def _recording_parser(monkeypatch, fail=()):
    """run_parser that records (database file name, keyword arguments); the versions in `fail` (their database file) fail."""
    seen = []

    def run(*args, **kwargs):
        seen.append((Path(args[1]), kwargs))
        return (Path(args[1]) not in fail), ("Boom" if Path(args[1]) in fail else "")
    monkeypatch.setattr(actions, "run_parser", run)
    return seen


def test_reading_reads_every_enabled_version_with_its_own_rules(window, env, qtbot, monkeypatch):
    files = _data_files(env, "_retail_", "_forever_")
    rule = {"type": "char", "value": "Other-Realm"}
    try:
        seen = _recording_parser(monkeypatch)
        _both_versions(window)
        window.cfg["char_rules"] = {"_forever_": [rule]}
        window.on_parse()
        wait_idle(qtbot, window)
        assert [db for db, _kw in seen] == [wow_install.out_files("_retail_")[0], wow_install.out_files("_forever_")[0]]
        assert seen[0][1]["rules"] == [] and seen[1][1]["rules"] == [rule]
        text = window.log.toPlainText()
        assert "Game version _retail_:" in text and "Game version _forever_:" in text and text.count("Read successfully.") == 2
    finally:
        for path in files:
            path.unlink(missing_ok=True)


def test_a_version_without_a_data_file_of_the_account_is_left_out_and_named(window, env, qtbot, monkeypatch):
    files = _data_files(env, "_retail_")
    try:
        seen = _recording_parser(monkeypatch)
        _both_versions(window)
        window.on_parse()
        wait_idle(qtbot, window)
        assert [db for db, _kw in seen] == [wow_install.out_files("_retail_")[0]]
        assert "_forever_: no data file for the account ACC1, not read." in window.log.toPlainText()
    finally:
        for path in files:
            path.unlink(missing_ok=True)


def test_with_no_data_file_at_all_the_dialog_names_every_place_and_nothing_starts(window, env, monkeypatch):
    errors = []
    monkeypatch.setattr(dialogs, "error", lambda parent, text: errors.append(text))
    seen = _recording_parser(monkeypatch)
    _both_versions(window)
    window.on_parse()
    assert not window._busy and not seen and len(errors) == 1
    assert str(wow_install.saved_vars_path(env.wow / "_retail_", "ACC1")) in errors[0]
    assert str(wow_install.saved_vars_path(env.wow / "_forever_", "ACC1")) in errors[0]


def test_one_version_that_fails_does_not_stop_the_other_and_the_page_opens(window, env, qtbot, monkeypatch):
    files = _data_files(env, "_retail_", "_forever_")
    try:
        _recording_parser(monkeypatch, fail=(wow_install.out_files("_retail_")[0],))
        _both_versions(window)
        window.on_parse_open()
        wait_idle(qtbot, window)
        text = window.log.toPlainText()
        assert text.count("Reading failed.") == 1 and text.count("Read successfully.") == 1 and "Boom" in text
        assert window.tabs.currentIndex() == main_window.TAB_PAGE                  # one version was read: the Page tab opens
    finally:
        for path in files:
            path.unlink(missing_ok=True)


def test_when_nothing_could_be_read_the_page_tab_does_not_open(window, env, qtbot, monkeypatch):
    files = _data_files(env, "_retail_")
    try:
        _recording_parser(monkeypatch, fail=(wow_install.out_files("_retail_")[0],))
        window.on_parse_open()
        wait_idle(qtbot, window)
        assert window.tabs.currentIndex() == main_window.TAB_SETTINGS
    finally:
        for path in files:
            path.unlink(missing_ok=True)


def test_a_typed_in_version_folder_reads_only_that_version(window, env, qtbot, monkeypatch):
    files = _data_files(env, "_retail_", "_forever_")
    try:
        seen = _recording_parser(monkeypatch)
        _both_versions(window)
        window.ed_wow.setText(str(env.wow / "_forever_"))
        window.on_parse()
        wait_idle(qtbot, window)
        assert [db for db, _kw in seen] == [wow_install.out_files("_forever_")[0]]
    finally:
        for path in files:
            path.unlink(missing_ok=True)


def test_one_account_for_all_versions_is_listed_chosen_and_kept(window, env):
    saved = dict(window.cfg["accounts"])
    extra = _data_files(env, "_forever_", account="ZZZ")                       # an account only Forever has, with data
    try:
        _both_versions(window)
        assert items(window.cmb_acc) == ["ZZZ", "ACC1"]                         # joined over the versions, the one with data first
        window.cmb_acc.setCurrentText("ACC1")
        window.save()
        assert window.cfg["accounts"] == {"_retail_": "ACC1", "_forever_": "ACC1"}
        window.cmb_acc.setCurrentText("ZZZ")
        window.save()
        assert window.cfg["accounts"] == {"_retail_": "ACC1", "_forever_": "ZZZ"}  # kept for the versions that have it only
        window.cmb_acc.clear()                                                  # nothing chosen: the saved one comes back
        window.refresh_accounts()
        assert window.cmb_acc.currentText() == "ACC1"
        window.cfg["accounts"] = {"_forever_": "ZZZ"}
        window.cmb_acc.clear()
        window.refresh_accounts()
        assert window.cmb_acc.currentText() == "ZZZ"
    finally:
        window.cfg["accounts"] = saved
        shutil.rmtree(extra[0].parent.parent, ignore_errors=True)


def test_the_drop_down_for_the_addon_does_not_change_the_accounts(window):
    _both_versions(window)
    before = (items(window.cmb_acc), window.cmb_acc.currentText())
    window.cmb_var.setCurrentText("_forever_")
    assert (items(window.cmb_acc), window.cmb_acc.currentText()) == before


def _group_title(widget):
    parent = widget.parent()
    while parent is not None and not isinstance(parent, main_window.QGroupBox):
        parent = parent.parent()
    return parent.title() if parent is not None else None


def test_the_version_and_the_addon_buttons_are_one_group_and_the_reading_buttons_another(window):
    install, uninstall, read, export = window.action_buttons[:4]
    assert [b.text() for b in (install, uninstall, read, export)] == ["Install / update addon", "Uninstall addon", "Read + open", "Export to Excel"]
    assert [_group_title(w) for w in (window.cmb_var, install, uninstall)] == ["Addon", "Addon", "Addon"]
    assert [_group_title(w) for w in (read, export)] == ["Actions", "Actions"]
    assert _group_title(window.cmb_acc) == "Game" and _group_title(window.ed_wow) == "Game"          # the game group has no version box any more


def test_the_addon_buttons_act_on_the_chosen_version_only(window, env, monkeypatch):
    monkeypatch.setattr(dialogs, "ask_yes_no", lambda *a, **k: True)
    _both_versions(window)
    try:
        window.cmb_var.setCurrentText("_forever_")
        window.on_install()
        assert wow_install.addon_dir(env.wow, "_forever_").is_dir() and not wow_install.addon_dir(env.wow, "_retail_").exists()
        assert "Addon: version" in window.status_text()
        window.cmb_var.setCurrentText("_retail_")
        assert "Addon: not installed" in window.status_text()                    # the status follows the chosen version
        window.cmb_var.setCurrentText("_forever_")
        window.on_uninstall()
        assert not wow_install.addon_dir(env.wow, "_forever_").exists()
    finally:
        wow_install.uninstall_addon(env.wow, "_forever_")


def test_the_status_line_shows_the_data_of_every_version(window, env):
    files = _data_files(env, "_retail_")
    try:
        _both_versions(window)
        text = window.status_text()
        assert f"Game: {env.wow}" in text and "Data: _retail_ 20" in text and "_forever_ missing" in text
        assert "stats" not in text                                               # the pages are tabs now: no part for the page file
    finally:
        for path in files:
            path.unlink(missing_ok=True)


# ------------------------------------------------------------------------------ the page
def _page_file():
    return wow_install.out_files("_retail_")[1]


def retail_tab(window):
    return window.page_views["_retail_"]


def test_without_a_page_the_tab_shows_the_hint(window):
    tab = retail_tab(window)
    window.tabs.setCurrentIndex(main_window.TAB_PAGE)             # a page is loaded when its tab is shown
    assert tab.stack.currentWidget() is tab.placeholder
    assert "no stats page" in tab.placeholder.text()


def test_open_without_a_page_shows_the_page_tab_with_the_hint(window, monkeypatch):
    shown = []
    monkeypatch.setattr(dialogs, "info", lambda parent, text: shown.append(text))          # no dialog any more: the tab says it
    window.on_open()
    tab = retail_tab(window)
    assert not shown and window.tabs.currentIndex() == main_window.TAB_PAGE
    assert tab.stack.currentWidget() is tab.placeholder and "no stats page" in tab.placeholder.text()


def test_open_shows_the_page_in_the_page_tab_and_runs_its_script(window, qtbot):
    page = _page_file()
    page.parent.mkdir(parents=True, exist_ok=True)
    page.write_text("<html><body><script>document.title = 'page ' + (1 + 1);</script></body></html>", encoding="utf-8")
    try:
        window.on_open()
        tab = retail_tab(window)
        assert window.tabs.currentIndex() == main_window.TAB_PAGE and tab.stack.currentWidget() is tab.view
        qtbot.waitUntil(lambda: window.view.title() == "page 2", timeout=15000)
    finally:
        page.unlink(missing_ok=True)


def picker_items(picker):
    return [picker.combo.itemText(i) for i in range(picker.combo.count())]


def write_small_page(variant, title):
    page = wow_install.out_files(variant)[1]
    page.parent.mkdir(parents=True, exist_ok=True)
    page.write_text(f"<html><body><script>document.title = {title!r};</script></body></html>", encoding="utf-8")
    return page


def test_the_page_tab_has_one_page_per_enabled_version(window):
    assert picker_items(window.pick_page) == ["_retail_"] and window.page_stack.count() == 1
    retail = retail_tab(window)
    window.cfg["enabled_variants"] = ["_forever_", "_retail_"]
    window.refresh_variants()
    assert picker_items(window.pick_page) == picker_items(window.pick_chars) == ["_retail_", "_forever_"]      # Retail first, the same list in both tabs
    assert window.page_stack.count() == 2
    window.cfg["enabled_variants"] = ["_retail_"]
    window.refresh_variants()
    assert picker_items(window.pick_page) == ["_retail_"] and list(window.page_views) == ["_retail_"] and window.page_stack.count() == 1
    assert retail_tab(window) is retail                                         # the page that stays is not made again


def test_every_game_version_shows_its_own_page(window, qtbot):
    retail_page, forever_page = write_small_page("_retail_", "retail page"), write_small_page("_forever_", "forever page")
    try:
        window.cfg["enabled_variants"] = ["_retail_", "_forever_"]
        window.refresh_variants()
        window.on_open()                                                         # the Page tab: the page that is on view (Retail) loads
        assert window.page_stack.currentWidget() is window.page_views["_retail_"]
        qtbot.waitUntil(lambda: window.view.title() == "retail page", timeout=15000)
        window.pick_page.combo.setCurrentText("_forever_")                       # chosen in the box of the Page tab
        assert window.page_stack.currentWidget() is window.page_views["_forever_"]
        qtbot.waitUntil(lambda: window.view.title() == "forever page", timeout=15000)
        assert window.page_views["_retail_"].view.title() == "retail page"      # the other page keeps what it shows
        window.cmb_var.setCurrentText("_retail_")                                # the box of the addon does not choose the page, and opening leaves it as it is
        window.on_open()
        assert window.page_stack.currentWidget() is window.page_views["_forever_"]
    finally:
        retail_page.unlink(missing_ok=True)
        forever_page.unlink(missing_ok=True)


def test_a_page_is_loaded_when_its_tab_is_shown(window, qtbot):
    page = write_small_page("_retail_", "shown late")
    try:
        tab = retail_tab(window)
        window.load_page(force=True, variant="_retail_")                         # the Settings tab is on view: the page waits
        assert tab.pending and tab.forced
        window.tabs.setCurrentIndex(main_window.TAB_PAGE)
        assert not tab.pending
        qtbot.waitUntil(lambda: window.view.title() == "shown late", timeout=15000)
    finally:
        page.unlink(missing_ok=True)


def test_loading_marks_only_the_page_of_that_version(window):
    window.cfg["enabled_variants"] = ["_retail_", "_forever_"]
    window.refresh_variants()
    retail, forever = window.page_views["_retail_"], window.page_views["_forever_"]
    retail.pending = forever.pending = False
    window.load_page(force=True, variant="_forever_")
    assert forever.pending and not retail.pending
    window.load_page()
    assert retail.pending


def test_the_choice_of_the_game_version_is_one_for_the_page_and_the_characters_tab(window):
    _both_versions(window)
    assert window.pick_page.current() == window.pick_chars.current() == "_retail_"
    window.pick_chars.combo.setCurrentText("_forever_")                          # chosen in the Characters tab: the Page tab follows
    assert window.pick_page.current() == "_forever_" and window.page_stack.currentWidget() is window.page_views["_forever_"]
    window.pick_page.combo.setCurrentText("_retail_")                            # and the other way round
    assert window.pick_chars.current() == "_retail_" and window.page_stack.currentWidget() is window.page_views["_retail_"]
    window.cmb_var.setCurrentText("_forever_")                                   # the box of the addon is another choice
    assert window.pick_page.current() == window.pick_chars.current() == "_retail_"


def test_the_chosen_version_falls_back_to_the_first_when_it_is_not_enabled_any_more(window):
    _both_versions(window)
    window.pick_page.combo.setCurrentText("_forever_")
    window.cfg["enabled_variants"] = ["_retail_"]
    window.refresh_variants()
    assert window._version == window.pick_page.current() == window.pick_chars.current() == "_retail_"


def test_the_boxes_of_the_game_version_are_wide_enough_for_the_longest_name(window):
    for picker in (window.pick_page, window.pick_chars):
        assert picker.combo.sizeAdjustPolicy() == main_window.QComboBox.SizeAdjustPolicy.AdjustToContents
        assert picker.combo.minimumContentsLength() >= len("_anniversary_")


def test_open_in_browser_opens_the_page_of_the_chosen_version(window, monkeypatch):
    page = write_small_page("_forever_", "forever page")
    try:
        window.cfg["enabled_variants"] = ["_retail_", "_forever_"]
        window.refresh_variants()
        window.pick_page.combo.setCurrentText("_forever_")                       # not loaded (the Settings tab is on view): no snapshot, the file itself
        opened = []
        monkeypatch.setattr(main_window.webbrowser, "open", lambda url: opened.append(url) or True)
        window.open_in_browser()
        assert opened and opened[0].endswith("stats_forever.html")
    finally:
        page.unlink(missing_ok=True)


def make_data_of(env, variant):
    """A database and page for this game version, made by the parser from the small sample file of the Top 5 tests (two characters)."""
    from app import stat_parser
    db, page = wow_install.out_files(variant)
    source = env.base / "TopFive.lua"
    source.write_text(TOP5_LUA, encoding="utf-8")
    stat_parser.main(["--input", str(source), "--db", str(db), "--output", str(page)])
    return db, page


def test_the_pages_of_the_enabled_versions_are_made_from_their_databases(window, qtbot, stats_data):
    _db, page = stats_data
    page.unlink()
    tab = retail_tab(window)
    window.build_pages()
    assert window._busy and tab.building                                        # written in a thread; the hint stands meanwhile
    assert tab.placeholder.text() == "The page is being made ..." and tab.stack.currentWidget() is tab.placeholder
    wait_idle(qtbot, window)
    assert page.is_file() and not tab.building
    assert "Pages made: _retail_" in window.log.toPlainText()
    window.tabs.setCurrentIndex(main_window.TAB_PAGE)                           # the page loads when its tab is shown
    qtbot.waitUntil(lambda: window.view.url().isLocalFile() and Path(window.view.url().toLocalFile()) == page, timeout=15000)


def test_without_a_database_no_page_is_made(window):
    wow_install.out_files("_retail_")[0].unlink(missing_ok=True)
    window.build_pages()
    assert not window._busy and not retail_tab(window).building


def test_a_page_that_could_not_be_made_is_reported_and_stays_as_it_was(window):
    tab = retail_tab(window)
    tab.set_building(True)
    window._pages_built([("_retail_", False, "Boom\n"), ("_gone_", False, "")])    # a version that is not enabled any more is skipped quietly
    text = window.log.toPlainText()
    assert not tab.building and tab.placeholder.text().startswith("There is no stats page")
    assert "Boom" in text and "The page of _retail_ could not be made." in text and "Pages made" not in text


def test_a_page_that_is_being_made_is_not_loaded(window):
    tab = retail_tab(window)
    tab.set_building(True)
    try:
        window.load_page(force=True, variant="_retail_")
        window.tabs.setCurrentIndex(main_window.TAB_PAGE)
        assert tab.pending and tab.stack.currentWidget() is tab.placeholder     # nothing was loaded
    finally:
        tab.set_building(False)


def test_enabling_a_version_makes_its_page_from_its_database(window, env, qtbot):
    db, page = make_data_of(env, "_forever_")
    page.unlink()
    try:
        variant_boxes(window)["_forever_"].setChecked(True)
        assert window.page_views["_forever_"].building
        wait_idle(qtbot, window)
        assert page.is_file() and not window.page_views["_forever_"].building
    finally:
        page.unlink(missing_ok=True)
        db.unlink(missing_ok=True)


def test_the_view_is_hardened(window):
    attributes = QWebEngineSettings.WebAttribute
    settings = window.view.settings()
    for name in ("LocalContentCanAccessFileUrls", "LocalContentCanAccessRemoteUrls", "JavascriptCanOpenWindows",
                 "PluginsEnabled", "JavascriptCanAccessClipboard"):
        assert not settings.testAttribute(getattr(attributes, name)), name
    assert settings.testAttribute(attributes.JavascriptEnabled)


def test_the_page_follows_local_links_and_sends_internet_links_to_the_browser(window, monkeypatch):
    opened = []
    monkeypatch.setattr(main_window.QDesktopServices, "openUrl", lambda url: opened.append(url.toString()))
    link = QWebEnginePage.NavigationType.NavigationTypeLinkClicked
    page = window.view.page()
    assert page.acceptNavigationRequest(QUrl("file:///C:/x/history/history-a.html"), link, True) is True
    assert page.acceptNavigationRequest(QUrl("https://example.org/"), link, True) is False
    assert opened == ["https://example.org/"]
    assert page.acceptNavigationRequest(QUrl("ftp://example.org/"), link, True) is False and len(opened) == 1
    assert page.createWindow(QWebEnginePage.WebWindowType.WebBrowserTab) is None


# ------------------------------------------------------------------------------- updates
def _release_with_dialog(window, monkeypatch, choice):
    shown, started = [], []
    monkeypatch.setattr(dialogs, "ask_update", lambda *a, **k: shown.append(a) or choice)
    monkeypatch.setattr(window, "_start_update", lambda data, tag: started.append(tag))
    return {"tag_name": "v9.9.9", "name": "StatTracker 9.9.9"}, shown, started


def test_overlapping_update_checks_open_only_one_dialog(window, monkeypatch):
    """The check at start and a manual check both bring a release; the second must not open a second dialog."""
    data, shown, started = _release_with_dialog(window, monkeypatch, "update")
    window._on_release(data, False)
    window._on_release(data, True)
    assert len(shown) == 1 and started == ["v9.9.9"]


def test_the_update_dialog_can_be_reopened_after_later(window, monkeypatch):
    data, shown, started = _release_with_dialog(window, monkeypatch, None)
    window._on_release(data, True)
    window._on_release(data, True)
    assert len(shown) == 2 and not started


def test_the_update_check_is_passive_while_the_repository_is_unconfirmed(window, monkeypatch):
    monkeypatch.setattr(app_info, "REPO_CONFIRMED", False)
    monkeypatch.setattr(actions, "fetch_release", lambda: pytest.fail("no request may be sent"))
    shown = []
    monkeypatch.setattr(dialogs, "info", lambda parent, text: shown.append(text))
    window.check_updates(manual=True)
    assert shown and "placeholder" in shown[0]


def test_a_check_runs_in_a_thread_and_the_result_comes_back_to_the_window(window, qtbot, monkeypatch):
    monkeypatch.setattr(app_info, "REPO_CONFIRMED", True)
    monkeypatch.setattr(actions, "fetch_release", lambda: ("release", {"tag_name": "v0.0.1"}))
    shown = []
    monkeypatch.setattr(dialogs, "info", lambda parent, text: shown.append(text))
    window.check_updates(manual=True)
    qtbot.waitUntil(lambda: bool(shown), timeout=5000)
    assert "up to date" in shown[0] or app_info.APP_VERSION in shown[0]


def test_a_failed_download_releases_the_update_flag(window):
    window._update_open = True
    window.on_message(("update_failed", "x"))
    assert window._update_open is False
    assert "x" in window.log.toPlainText()


def test_a_check_error_is_loud_only_when_asked_for(window, monkeypatch):
    shown = []
    monkeypatch.setattr(dialogs, "error", lambda parent, text: shown.append(text))
    window.on_message(("update_error", "offline", False))
    assert not shown
    window.on_message(("update_error", "offline", True))
    assert shown and "offline" in shown[0]


def test_a_worker_that_fails_inside_the_handler_does_not_end_the_window(window, monkeypatch):
    def boom(_payload):
        raise RuntimeError("handler failed")
    monkeypatch.setattr(window, "_apply_update", boom)
    with pytest.raises(RuntimeError):                            # still loud: the entry script reports it (crash.log)
        window.on_message(("apply", "x"))
    window.on_message(("update_failed", "later"))                # and the window keeps handling messages
    assert "later" in window.log.toPlainText()


# ------------------------------------------------------------------- the colours of the pages
def test_the_script_names_every_variable_and_waits_for_the_root_element():
    variables = theme.page_variables(2)
    source = qt_style.page_script(variables)
    assert all(f'"{name}": "{value}"' in source for name, value in variables.items())
    assert "MutationObserver" in source and "setProperty" in source


def test_a_page_in_the_window_gets_the_colours_of_the_scheme_before_its_own_script_runs(window, qtbot):
    """The page reads --bg and --gold while it is parsed (like the chart of a history page does) and shows what it saw."""
    page = _page_file()
    page.parent.mkdir(parents=True, exist_ok=True)
    page.write_text("<html><head><style>:root { --bg:#123456; --gold:#654321; }</style></head><body><script>"
                    "var s = getComputedStyle(document.documentElement);"
                    "document.title = s.getPropertyValue('--bg').trim() + ' ' + s.getPropertyValue('--gold').trim();"
                    "</script></body></html>", encoding="utf-8")
    try:
        window.on_open()
        wanted = theme.page_variables(window.cfg["active_theme"])
        qtbot.waitUntil(lambda: window.view.title() == f"{wanted['--bg']} {wanted['--gold']}", timeout=15000)
        assert wanted["--bg"] != "#123456"                         # the scheme won over the default of the page
    finally:
        page.unlink(missing_ok=True)


# ------------------------------------------------------------------- the titles of the groups
def test_the_group_titles_use_the_readable_accent_when_given_and_the_accent_otherwise():
    ice = theme.THEMES[6]
    readable = theme.readable_accent(ice)
    assert readable != ice["accent"]                                   # Ice Blue: the plain accent is too dark for text
    assert f"color: {readable};" in qt_style.stylesheet(ice, readable).split("QGroupBox::title")[1].split("\n")[0]
    assert f"color: {ice['accent']};" in qt_style.stylesheet(ice).split("QGroupBox::title")[1].split("\n")[0]


def test_the_window_gives_the_style_sheet_the_readable_accent(window):
    sheet = main_window.QApplication.instance().styleSheet()
    wanted = theme.readable_accent(window.colors)
    assert f"color: {wanted};" in sheet.split("QGroupBox::title")[1].split("\n")[0]


def test_the_group_titles_are_big_and_bold_but_the_text_inside_the_groups_is_not(window):
    """Qt ignores a font set on QGroupBox::title: the font of the title is the font of the box (S18). The widgets in the box
    inherit it unless the general rule says otherwise."""
    boxes = window.findChildren(main_window.QGroupBox)
    assert boxes and all(box.font().pointSizeF() == 12 and box.font().bold() for box in boxes)
    inside = window.findChildren(main_window.QCheckBox) + window.findChildren(main_window.QLabel)
    assert inside and not any(widget.font().bold() for widget in inside if widget.objectName() != "title")


# ------------------------------------------------------------------- the blocks of the page (Python) in the window
def js(view, qtbot, code, timeout=15000):
    """Runs a script in the page of `view` and gives its result."""
    box = []
    view.page().runJavaScript(code, lambda result: box.append(result))
    qtbot.waitUntil(lambda: bool(box), timeout=timeout)
    return box[0]


def wait_js(view, qtbot, expression, wanted=True, timeout=20000):
    end = time.monotonic() + timeout / 1000
    got = None
    while time.monotonic() < end:
        got = js(view, qtbot, expression)
        if got == wanted:
            return
        qtbot.wait(100)
    raise AssertionError(f"{expression!r} was {got!r}, not {wanted!r}")


def change(element, value):
    return (f"(() => {{ const e = document.getElementById('{element}'); e.value = {value!r}; "
            "e.dispatchEvent(new Event('change', {bubbles: true})); })()")


def click(element):
    return f"document.getElementById('{element}').click()"


FIRST_GROUP = "(document.querySelector('#gt tbody tr td') || {}).textContent"


@pytest.fixture
def shown(window, qtbot):
    """The stats page of a small payload, open in the window, with the bridge attached."""
    page = _page_file()
    outputs.write_html(make_payload(), page)
    try:
        with qtbot.waitSignal(window.view.loadFinished, timeout=20000):          # the page of a test before must be gone first
            window.view.setUrl(QUrl("about:blank"))
        retail_tab(window).url = ""
        with qtbot.waitSignal(window.view.loadFinished, timeout=20000):
            window.on_open()
        wait_js(window.view, qtbot, "typeof STT !== 'undefined' && STT.ready")
        yield window
    finally:
        page.unlink(missing_ok=True)


def test_the_page_starts_with_the_block_written_by_python(shown, qtbot):
    assert js(shown.view, qtbot, FIRST_GROUP) == "Druide"
    assert js(shown.view, qtbot, "document.getElementById('groupBy').value") == "class"
    assert js(shown.view, qtbot, "document.getElementById('presetBox').hidden") is False       # the program offers presets


def test_choosing_another_grouping_in_the_page_is_answered_by_python(shown, qtbot):
    shown.view.page().runJavaScript(change("groupBy", "race"))
    wait_js(shown.view, qtbot, FIRST_GROUP, "Mensch")
    assert "Nachtelf" in js(shown.view, qtbot, "document.getElementById('groupPick').textContent")


def test_a_statistic_is_added_and_removed_with_the_buttons_of_the_page(shown, qtbot):
    page = shown.view.page()
    page.runJavaScript(change("xstat", "107"))
    page.runJavaScript(click("xadd"))
    wait_js(shown.view, qtbot, "document.getElementById('extraChips').hidden", False)
    assert "Creatures killed (Sum)" in js(shown.view, qtbot, "document.getElementById('extraChips').textContent")
    assert "1,500" in js(shown.view, qtbot, "document.getElementById('gt').textContent")
    page.runJavaScript("document.querySelector('#extraChips button').click()")
    wait_js(shown.view, qtbot, "document.getElementById('extraChips').hidden", True)
    assert "Creatures" not in js(shown.view, qtbot, "document.getElementById('gt').textContent")


def test_unticking_a_character_above_changes_the_groups(shown, qtbot):
    shown.view.page().runJavaScript(
        "(() => { const c = document.getElementById('chk_A-One'); c.checked = false; c.dispatchEvent(new Event('change', {bubbles: true})); })()")
    wait_js(shown.view, qtbot, "document.getElementById('groupPick').textContent.includes('Magier (1)')")
    assert js(shown.view, qtbot, "document.getElementById('groupsNone').hidden") is True


def test_with_no_character_ticked_the_page_says_so(shown, qtbot):
    shown.view.page().runJavaScript("document.getElementById('toggleAll').click()")
    wait_js(shown.view, qtbot, "document.getElementById('groupsNone').hidden", False)
    assert js(shown.view, qtbot, "document.getElementById('groupsWrap').hidden") is True


PICKS = "[...document.querySelectorAll('input[data-pick]')]"
TOGGLE = "document.getElementById('toggleAll').textContent"


def test_the_selection_button_says_what_it_does_next_and_sets_the_boxes(shown, qtbot):
    assert js(shown.view, qtbot, TOGGLE) == "Deselect all" and js(shown.view, qtbot, PICKS + ".length") == 4
    assert js(shown.view, qtbot, PICKS + ".every(e => e.checked)") is True
    shown.view.page().runJavaScript("document.getElementById('toggleAll').click()")
    wait_js(shown.view, qtbot, PICKS + ".every(e => !e.checked)", True)
    assert js(shown.view, qtbot, TOGGLE) == "Select all"
    shown.view.page().runJavaScript("document.getElementById('toggleAll').click()")
    wait_js(shown.view, qtbot, PICKS + ".every(e => e.checked)", True)
    assert js(shown.view, qtbot, TOGGLE) == "Deselect all"


def test_ticking_a_single_box_changes_the_text_of_the_button_through_python(shown, qtbot):
    page = shown.view.page()
    page.runJavaScript("(() => { const c = document.getElementById('chk_A-One'); c.checked = false; c.dispatchEvent(new Event('change', {bubbles: true})); })()")
    wait_js(shown.view, qtbot, TOGGLE, "Select all")
    page.runJavaScript("document.getElementById('toggleAll').click()")                  # one is off: the button ticks all
    wait_js(shown.view, qtbot, PICKS + ".every(e => e.checked)", True)
    wait_js(shown.view, qtbot, TOGGLE, "Deselect all")


def _in_plain_view(qtbot, path, check):
    """Loads a file in a view without the bridge (as a browser would) and runs `check(view)`."""
    profile = QWebEngineProfile()
    view = QWebEngineView()
    web_page = QWebEnginePage(profile, view)
    view.setPage(web_page)
    try:
        view.setUrl(QUrl.fromLocalFile(str(path)))
        wait_js(view, qtbot, "typeof STT !== 'undefined'")
        check(view)
    finally:
        view.deleteLater()
        web_page.deleteLater()
        profile.deleteLater()


def test_open_in_browser_opens_a_snapshot_of_what_the_window_shows(shown, qtbot, monkeypatch):
    opened = []
    monkeypatch.setattr(main_window.webbrowser, "open", lambda uri: opened.append(uri) or True)
    page = shown.view.page()
    page.runJavaScript("(() => { const c = document.getElementById('chk_A-One'); c.checked = false; c.dispatchEvent(new Event('change', {bubbles: true})); })()")
    wait_js(shown.view, qtbot, "document.getElementById('groupPick').textContent.includes('Magier (1)')")
    page.runJavaScript(change("cat", "Wealth"))
    wait_js(shown.view, qtbot, "document.getElementById('count').textContent", "1 of 5 statistics")
    page.runJavaScript(change("groupBy", "race"))
    wait_js(shown.view, qtbot, "document.getElementById('groupBy').value", "race")
    wait_js(shown.view, qtbot, "document.getElementById('groupPick').textContent.includes('Nachtelf')")
    page.runJavaScript(typed("repQ", "two"))
    wait_js(shown.view, qtbot, "document.querySelectorAll('#rpt tbody tr').length", 3)
    snapshot = wow_install.snapshot_file("_retail_")
    try:
        shown.open_in_browser()
        assert opened == [snapshot.as_uri()] and snapshot.name == "stats_snapshot.html" and snapshot.is_file()

        def check(view):
            assert js(view, qtbot, "document.getElementById('count').textContent") == "1 of 5 statistics"
            assert js(view, qtbot, "document.getElementById('chk_A-One').checked") is False
            assert js(view, qtbot, "document.getElementById('chk_B-Two').checked") is True
            assert js(view, qtbot, "document.getElementById('cat').value") == "Wealth"
            assert js(view, qtbot, "document.getElementById('groupBy').value") == "race"
            assert js(view, qtbot, "document.getElementById('repQ').value") == "two"
            assert js(view, qtbot, "document.querySelectorAll('#rpt tbody tr').length") == 3
            assert js(view, qtbot, "document.getElementById('toggleAll').textContent") == "Select all"
            assert js(view, qtbot, "[...document.querySelectorAll('[data-slot] [data-action], input[data-pick]')].every(e => e.disabled)") is True
            assert js(view, qtbot, "document.getElementById('presetBox').hidden") is True
            assert js(view, qtbot, "document.getElementById('gen').textContent").count("Snapshot of ") == 1
        _in_plain_view(qtbot, snapshot, check)
        assert js(shown.view, qtbot, "document.getElementById('presetBox').hidden") is False          # the shown page is as it was
        assert "Opened:" in shown.log.toPlainText()
    finally:
        snapshot.unlink(missing_ok=True)


def test_open_in_browser_without_a_shown_page_opens_the_page_file(shown, qtbot, monkeypatch):
    opened = []
    monkeypatch.setattr(main_window.webbrowser, "open", lambda uri: opened.append(uri) or True)
    monkeypatch.setattr(shown._bridge, "view", None)
    shown.open_in_browser()
    assert opened == [_page_file().as_uri()] and not wow_install.snapshot_file("_retail_").exists()


def test_open_in_browser_says_when_the_snapshot_cannot_be_written(shown, qtbot, monkeypatch):
    opened = []
    monkeypatch.setattr(main_window.webbrowser, "open", lambda uri: opened.append(uri) or True)

    def fail(view, variant):
        raise OSError("disk full")
    monkeypatch.setattr(actions, "write_snapshot", fail)
    shown.open_in_browser()
    assert opened == [] and "The snapshot could not be written: disk full" in shown.log.toPlainText()


def test_a_preset_is_saved_in_the_settings_and_shows_in_the_page(shown, qtbot):
    page = shown.view.page()
    page.runJavaScript(change("groupBy", "faction"))
    wait_js(shown.view, qtbot, FIRST_GROUP, "Alliance")
    page.runJavaScript(change("presetName", "my preset"))
    page.runJavaScript(click("presetSave"))
    wait_js(shown.view, qtbot, "[...document.querySelectorAll('#presetSel option')].map(o => o.value).includes('my preset')")
    assert [p["name"] for p in shown.cfg["group_presets"]] == ["my preset"] and shown.cfg["group_presets"][0]["by"] == "faction"
    assert [p["name"] for p in config.load()[0]["group_presets"]] == ["my preset"]             # and in the settings file
    page.runJavaScript(change("groupBy", "realm"))
    wait_js(shown.view, qtbot, FIRST_GROUP, "Four")
    page.runJavaScript(change("presetSel", "my preset"))
    wait_js(shown.view, qtbot, FIRST_GROUP, "Alliance")                                       # the preset brought the grouping back
    assert js(shown.view, qtbot, "document.getElementById('groupBy').value") == "faction"


def test_loading_the_page_again_starts_the_blocks_again(shown, qtbot):
    shown.view.page().runJavaScript(change("groupBy", "race"))
    wait_js(shown.view, qtbot, FIRST_GROUP, "Mensch")
    shown.load_page(force=True)
    qtbot.wait(300)
    wait_js(shown.view, qtbot, "typeof STT !== 'undefined' && STT.ready")
    assert js(shown.view, qtbot, FIRST_GROUP) == "Druide"
    shown.view.page().runJavaScript(change("groupBy", "faction"))
    wait_js(shown.view, qtbot, FIRST_GROUP, "Alliance")


def test_a_page_opened_without_the_window_has_its_controls_disabled_and_its_first_state(window, qtbot, tmp_path):
    """In a browser (here: a view without the bridge) the blocks stay as written; nothing can be clicked that would do nothing."""
    page = tmp_path / "stats.html"
    outputs.write_html(make_payload(), page)
    profile = QWebEngineProfile()                          # kept in a name: the page needs it for as long as it lives
    view = QWebEngineView()
    web_page = QWebEnginePage(profile, view)
    view.setPage(web_page)
    try:
        view.setUrl(QUrl.fromLocalFile(str(page)))
        wait_js(view, qtbot, "typeof STT !== 'undefined'")
        assert js(view, qtbot, "[...document.querySelectorAll('[data-slot] [data-action]')].every(e => e.disabled)") is True
        assert js(view, qtbot, "[...document.querySelectorAll('input[data-pick]')].every(e => e.disabled)") is True        # the boxes of the selection, too
        assert js(view, qtbot, FIRST_GROUP) == "Druide"
    finally:                                               # the view and its page before the profile, as the window does
        view.deleteLater()
        web_page.deleteLater()
        profile.deleteLater()


def typed(element, text):
    return (f"(() => {{ const e = document.getElementById('{element}'); e.value = {text!r}; e.dispatchEvent(new Event('input', {{bubbles: true}})); }})()")


def test_the_reputation_search_is_answered_by_python(shown, qtbot):
    rows = "document.querySelectorAll('#rpt tbody tr').length"
    assert js(shown.view, qtbot, rows) == 6                                      # the heading, the sub heading and four factions
    shown.view.page().runJavaScript(typed("repQ", "friend"))
    wait_js(shown.view, qtbot, rows, 3)                                          # the heading, the sub heading and the faction
    shown.view.page().runJavaScript(typed("repQ", "zzz"))
    wait_js(shown.view, qtbot, "document.getElementById('repNone').hidden", False)
    assert js(shown.view, qtbot, "document.getElementById('repNone').textContent") == "No faction matches the search."
    shown.view.page().runJavaScript(typed("repQ", ""))
    wait_js(shown.view, qtbot, rows, 6)


def test_unticking_a_character_above_changes_the_reputation_table(shown, qtbot):
    heads = "document.querySelectorAll('#rpt thead th').length"
    assert js(shown.view, qtbot, heads) == 5                                     # the faction column and four characters
    shown.view.page().runJavaScript(
        "(() => { const c = document.getElementById('chk_A-One'); c.checked = false; c.dispatchEvent(new Event('change', {bubbles: true})); })()")
    wait_js(shown.view, qtbot, heads, 4)
    assert "Friend Faction" not in js(shown.view, qtbot, "document.getElementById('rpt').textContent")      # only A-One had it


NAMES = "[...document.querySelectorAll('#t tbody tr td:nth-child(2)')].map(td => td.textContent).join('|')"
COUNT = "document.getElementById('count').textContent"
BAD_NAME = 'Bad <b>"name"</b>'


def test_a_click_on_a_column_head_sorts_the_table_and_the_head_statistic_takes_it_off(shown, qtbot):
    heads = "document.querySelectorAll('#t thead th')"
    plain = f"Played|Creatures killed|Gold earned|Only text|{BAD_NAME}"
    assert js(shown.view, qtbot, NAMES) == plain
    shown.view.page().runJavaScript(heads + "[2].click()")                                     # the column of A-One: the biggest number first
    wait_js(shown.view, qtbot, NAMES, f"Gold earned|Played|Creatures killed|{BAD_NAME}|Only text")
    shown.view.page().runJavaScript(heads + "[2].click()")
    wait_js(shown.view, qtbot, NAMES, f"Only text|{BAD_NAME}|Creatures killed|Played|Gold earned")
    shown.view.page().runJavaScript(heads + "[1].click()")
    wait_js(shown.view, qtbot, NAMES, plain)


def test_the_category_and_the_two_check_boxes_work_in_the_window(shown, qtbot):
    shown.view.page().runJavaScript(change("cat", "Wealth"))
    wait_js(shown.view, qtbot, COUNT, "1 of 5 statistics")
    shown.view.page().runJavaScript(change("cat", ""))
    wait_js(shown.view, qtbot, COUNT, "5 of 5 statistics")
    shown.view.page().runJavaScript("document.getElementById('toggleAll').click()")             # no character ticked: every row is empty
    wait_js(shown.view, qtbot, COUNT, "0 of 5 statistics")
    shown.view.page().runJavaScript("document.getElementById('hideEmpty').click()")             # a real click: the browser fires input and change
    wait_js(shown.view, qtbot, COUNT, "5 of 5 statistics")
    shown.view.page().runJavaScript("document.getElementById('toggleAll').click()")
    wait_js(shown.view, qtbot, "document.querySelectorAll('#t thead th').length", 6)


def key(element, name):
    return (f"document.getElementById('{element}').dispatchEvent(new KeyboardEvent('keydown', {{key: {name!r}, bubbles: true, cancelable: true}}))")


LIST_OPEN = "!document.getElementById('qList').hidden"
ITEMS = "document.querySelectorAll('#qList li[data-value]').length"
ACTIVE = "(document.querySelector('#qList li.active') || {}).textContent"
BOX = "document.getElementById('q').value"
INFO = "(document.querySelector('#qList li.info') || {}).textContent"


def test_typing_in_the_search_box_shows_suggestions_and_leaves_the_table_alone(shown, qtbot):
    shown.view.page().runJavaScript(typed("q", "ed"))
    wait_js(shown.view, qtbot, ITEMS, 3)
    assert js(shown.view, qtbot, LIST_OPEN) is True and js(shown.view, qtbot, COUNT) == "5 of 5 statistics"
    assert js(shown.view, qtbot, INFO) == "Matches: 3 – Enter shows them all in the table"
    assert js(shown.view, qtbot, "document.querySelector('#qList li[data-value]').textContent") == "Creatures killedCombat"


def test_enter_applies_the_text_to_the_table_and_closes_the_list(shown, qtbot):
    shown.view.page().runJavaScript(typed("q", "ed"))
    wait_js(shown.view, qtbot, ITEMS, 3)
    shown.view.page().runJavaScript(key("q", "Enter"))
    wait_js(shown.view, qtbot, COUNT, "3 of 5 statistics")
    assert js(shown.view, qtbot, LIST_OPEN) is False and js(shown.view, qtbot, "document.getElementById('q').dataset.committed") == "ed"


def test_the_arrow_keys_choose_a_suggestion_and_enter_takes_it(shown, qtbot):
    page = shown.view.page()
    page.runJavaScript(typed("q", "ed"))
    wait_js(shown.view, qtbot, ITEMS, 3)
    page.runJavaScript(key("q", "ArrowDown"))
    wait_js(shown.view, qtbot, ACTIVE, "Creatures killedCombat")
    page.runJavaScript(key("q", "ArrowDown"))
    wait_js(shown.view, qtbot, ACTIVE, "Gold earnedWealth")
    page.runJavaScript(key("q", "ArrowUp"))
    wait_js(shown.view, qtbot, ACTIVE, "Creatures killedCombat")
    page.runJavaScript(key("q", "Enter"))
    wait_js(shown.view, qtbot, COUNT, "1 of 5 statistics")
    assert js(shown.view, qtbot, BOX) == "Creatures killed" and js(shown.view, qtbot, NAMES) == "Creatures killed"


def test_a_click_on_a_suggestion_takes_it(shown, qtbot):
    page = shown.view.page()
    page.runJavaScript(typed("q", "ed"))
    wait_js(shown.view, qtbot, ITEMS, 3)
    page.runJavaScript("document.querySelectorAll('#qList li[data-value]')[1].dispatchEvent(new MouseEvent('mousedown', {bubbles: true, cancelable: true}))")
    wait_js(shown.view, qtbot, COUNT, "1 of 5 statistics")
    assert js(shown.view, qtbot, BOX) == "Gold earned" and js(shown.view, qtbot, LIST_OPEN) is False


def test_escape_closes_the_list_without_applying_the_text(shown, qtbot):
    page = shown.view.page()
    page.runJavaScript(typed("q", "ed"))
    wait_js(shown.view, qtbot, ITEMS, 3)
    page.runJavaScript(key("q", "Escape"))
    wait_js(shown.view, qtbot, LIST_OPEN, False)
    qtbot.wait(300)
    assert js(shown.view, qtbot, COUNT) == "5 of 5 statistics" and js(shown.view, qtbot, BOX) == "ed"


def test_a_click_outside_closes_the_list(shown, qtbot):
    shown.view.page().runJavaScript(typed("q", "ed"))
    wait_js(shown.view, qtbot, LIST_OPEN, True)
    shown.view.page().runJavaScript("document.getElementById('count').dispatchEvent(new MouseEvent('mousedown', {bubbles: true}))")
    wait_js(shown.view, qtbot, LIST_OPEN, False)


def test_emptying_the_box_takes_the_filter_off_at_once(shown, qtbot):
    page = shown.view.page()
    page.runJavaScript(typed("q", "ed"))
    wait_js(shown.view, qtbot, ITEMS, 3)
    page.runJavaScript(key("q", "Enter"))
    wait_js(shown.view, qtbot, COUNT, "3 of 5 statistics")
    page.runJavaScript(typed("q", ""))
    wait_js(shown.view, qtbot, COUNT, "5 of 5 statistics")


def test_text_that_was_typed_but_not_applied_is_not_used_by_the_other_controls(shown, qtbot):
    page = shown.view.page()
    page.runJavaScript(typed("q", "zz"))
    wait_js(shown.view, qtbot, INFO, "No matches")
    page.runJavaScript(change("cat", "Wealth"))
    wait_js(shown.view, qtbot, COUNT, "1 of 5 statistics")                       # the box says "zz", the table still follows the text applied last (none)


def test_a_late_answer_does_not_open_the_list_again_after_enter(shown, qtbot):
    page = shown.view.page()
    page.runJavaScript(typed("q", "ed") + ";" + key("q", "Enter"))                 # Enter before the suggestions have been asked for
    wait_js(shown.view, qtbot, COUNT, "3 of 5 statistics")
    qtbot.wait(500)
    assert js(shown.view, qtbot, LIST_OPEN) is False


# ------------------------------------------------------------------------------------------------------------ the Top 5 tab
TOP5_LUA = """
StatTrackerDB = {
	["version"] = 3,
	["meta"] = {
		[1] = { ["name"] = "Total deaths", ["cat"] = "Combat > Deaths" },
		[2] = { ["name"] = "Gold earned", ["cat"] = "Wealth" },
		[3] = { ["name"] = "Quests done", ["cat"] = "Quests" },
	},
	["chars"] = {
		["Alice-Realm"] = {
			["scannedAt"] = "2026-10-01 10:00:00", ["scannedEpoch"] = 1, ["class"] = "Mage", ["classFile"] = "MAGE", ["race"] = "Human", ["raceFile"] = "Human",
			["level"] = 80, ["faction"] = "Alliance", ["stats"] = { [1] = "1.234", [2] = "12g 5s 3c", [3] = "10" }, ["playedTotal"] = 90061, ["playedLevel"] = 3600,
		},
		["Bob-Realm"] = {
			["scannedAt"] = "2026-10-02 10:00:00", ["scannedEpoch"] = 2, ["class"] = "Druid", ["classFile"] = "DRUID", ["race"] = "Night Elf", ["raceFile"] = "NightElf",
			["level"] = 70, ["faction"] = "Alliance", ["stats"] = { [1] = "10", [2] = "1g", [3] = "--" }, ["playedTotal"] = 3600, ["playedLevel"] = 600,
		},
	},
}
"""
GOLD_LABEL = "Gold earned (Wealth)"


@pytest.fixture
def stats_data(env, qtbot):
    """A small database and page for Retail in the instance (two characters: a mage and a druid)."""
    from app import stat_parser
    db, page = wow_install.out_files("_retail_")
    source = env.base / "TopFive.lua"
    source.write_text(TOP5_LUA, encoding="utf-8")
    stat_parser.main(["--input", str(source), "--db", str(db), "--output", str(page)])
    yield db, page
    env.win.view.setUrl(QUrl("about:blank"))                      # the page of the window must let go of the file first (Windows locks it)
    for _ in range(50):
        try:
            page.unlink(missing_ok=True)
            break
        except PermissionError:
            qtbot.wait(100)
    db.unlink(missing_ok=True)


def open_top5(window, qtbot):
    window.tabs.setCurrentIndex(main_window.TAB_TOP5)
    qtbot.waitUntil(lambda: not window._busy and window._tile_choices is not None, timeout=20000)


def pick(combo, text):
    index = combo.findText(text)
    assert index >= 0, (text, items(combo)[:10])
    combo.setCurrentIndex(index)


def _two_versions_with_data(window, env):
    """Retail (the stats_data database) and Forever (a database of its own) enabled."""
    forever_db, forever_page = make_data_of(env, "_forever_")
    window.cfg["enabled_variants"] = ["_retail_", "_forever_"]
    window.refresh_variants()
    return forever_db, forever_page


def _forget(*files):
    for path in files:
        path.unlink(missing_ok=True)


def test_the_top5_tab_has_the_choice_of_the_game_version_that_the_other_tabs_have(window, env, qtbot, stats_data):
    forever_db, forever_page = _two_versions_with_data(window, env)
    try:
        assert picker_items(window.pick_top5) == ["_retail_", "_forever_"] and window.pick_top5.current() == "_retail_"
        window.pick_top5.combo.setCurrentText("_forever_")                      # chosen in the Top 5 tab: the others follow
        assert window.pick_page.current() == window.pick_chars.current() == "_forever_"
        window.cmb_var.setCurrentText("_retail_")                               # the box of the addon is another choice
        assert window.pick_top5.current() == "_forever_"
    finally:
        _forget(forever_db, forever_page)


def test_the_tiles_are_kept_per_game_version_and_a_switch_reads_the_other_one(window, env, qtbot, stats_data):
    forever_db, forever_page = _two_versions_with_data(window, env)
    retail_tile = {"stat": 2, "agg": "sum", "by": "all", "value": ""}
    forever_tile = {"stat": 3, "agg": "max", "by": "all", "value": ""}
    window.cfg["top5"] = {"_retail_": [retail_tile], "_forever_": [forever_tile]}
    try:
        open_top5(window, qtbot)
        assert window._tile_variant == "_retail_" and window.tile_rows[0].stat.currentData() == 2
        window.pick_top5.combo.setCurrentText("_forever_")
        qtbot.waitUntil(lambda: not window._busy and window._tile_variant == "_forever_", timeout=20000)
        assert (window.tile_rows[0].stat.currentData(), window.tile_rows[0].agg.currentData()) == (3, "max")
        assert window.lbl_top5.text() == ""                                      # nothing was changed in Retail: nothing to say
    finally:
        _forget(forever_db, forever_page)


def test_saving_in_one_game_version_leaves_the_tiles_of_the_other_alone_and_writes_only_its_page(window, env, qtbot, stats_data):
    forever_db, forever_page = _two_versions_with_data(window, env)
    retail_tile = {"stat": 2, "agg": "sum", "by": "all", "value": ""}
    window.cfg["top5"] = {"_retail_": [retail_tile]}
    retail_page = stats_data[1]
    try:
        open_top5(window, qtbot)
        window.pick_top5.combo.setCurrentText("_forever_")
        qtbot.waitUntil(lambda: not window._busy and window._tile_variant == "_forever_", timeout=20000)
        retail_before = retail_page.read_text(encoding="utf-8")
        pick(window.tile_rows[0].stat, "Quests done (Quests)")
        window.btn_top5.click()
        qtbot.waitUntil(lambda: not window._busy, timeout=20000)
        assert window.cfg["top5"] == {"_retail_": [retail_tile], "_forever_": [{"stat": 3, "agg": "sum", "by": "all", "value": ""}]}
        assert config.load()[0]["top5"] == window.cfg["top5"]
        assert 'id="top5"' in forever_page.read_text(encoding="utf-8") and retail_page.read_text(encoding="utf-8") == retail_before     # only the page of Forever was written
        assert "Top 5 saved (_forever_): 1 tiles." in window.log.toPlainText()
        pick(window.tile_rows[0].stat, "– none –")                              # taking the last tile away: the version has no entry any more
        window.btn_top5.click()
        qtbot.waitUntil(lambda: not window._busy, timeout=20000)
        assert window.cfg["top5"] == {"_retail_": [retail_tile]}
    finally:
        _forget(forever_db, forever_page)


def test_a_switch_drops_what_was_changed_and_not_saved_and_says_so(window, env, qtbot, stats_data):
    forever_db, forever_page = _two_versions_with_data(window, env)
    try:
        open_top5(window, qtbot)
        pick(window.tile_rows[0].stat, GOLD_LABEL)                              # changed in Retail, not saved
        window.pick_top5.combo.setCurrentText("_forever_")
        qtbot.waitUntil(lambda: not window._busy and window._tile_variant == "_forever_", timeout=20000)
        assert window.lbl_top5.text() == "Changes to the other game version that were not saved were dropped."
        assert window.cfg["top5"] == {} and window.tile_rows[0].stat.currentText() == "– none –"
    finally:
        _forget(forever_db, forever_page)


def test_saving_never_goes_into_a_version_the_rows_do_not_show(window, env, qtbot, stats_data):
    forever_db, forever_page = _two_versions_with_data(window, env)
    try:
        open_top5(window, qtbot)
        pick(window.tile_rows[0].stat, GOLD_LABEL)
        window._version = "_forever_"                                           # the choice moved while the rows could not be read (the window was busy)
        window.btn_top5.click()
        qtbot.waitUntil(lambda: not window._busy and window._tile_variant == "_forever_", timeout=20000)
        assert window.cfg["top5"] == {}                                         # nothing was saved: the rows were read for the chosen version first
    finally:
        _forget(forever_db, forever_page)


def test_every_game_version_gets_its_own_tiles_when_the_data_is_read_and_when_the_pages_are_made(window, env, qtbot, monkeypatch):
    files = _data_files(env, "_retail_", "_forever_")
    retail_tile = {"stat": 2, "agg": "sum", "by": "all", "value": ""}
    forever_tile = {"stat": 3, "agg": "max", "by": "all", "value": ""}
    try:
        seen = _recording_parser(monkeypatch)
        _both_versions(window)
        window.cfg["top5"] = {"_retail_": [retail_tile], "_forever_": [forever_tile]}
        window.on_parse()
        wait_idle(qtbot, window)
        assert [kw["top5"] for _db, kw in seen] == [[retail_tile], [forever_tile]]
        jobs = []
        monkeypatch.setattr(actions, "rebuild_pages", lambda given: jobs.extend(given) or [])
        make_data_of(env, "_retail_")
        make_data_of(env, "_forever_")
        window.build_pages()
        wait_idle(qtbot, window)
        assert [(variant, tiles) for variant, tiles, _rules in jobs] == [("_retail_", [retail_tile]), ("_forever_", [forever_tile])]
    finally:
        _forget(*files, *wow_install.out_files("_retail_"), *wow_install.out_files("_forever_"))


def test_a_character_is_shown_as_name_and_realm_and_the_key_stays_the_data_behind_it(window, qtbot, stats_data):
    open_top5(window, qtbot)
    row = window.tile_rows[0]
    pick(row.scope, "Character")
    assert items(row.value) == as_shown("Alice-Realm", "Bob-Realm")             # the text the person sees
    assert [row.value.itemData(i) for i in range(row.value.count())] == ["Alice-Realm", "Bob-Realm"]          # the key is what a tile stores
    pick(row.stat, GOLD_LABEL)
    row.value.setCurrentText("Bob / Realm")                                       # a part of the text shown is enough when it fits one entry
    window.btn_top5.click()
    qtbot.waitUntil(lambda: not window._busy, timeout=20000)
    assert window.cfg["top5"] == {"_retail_": [{"stat": 2, "agg": "sum", "by": "char", "value": "Bob-Realm"}]}
    pick(row.scope, "All characters")                                             # the rows are shared by the tests: leave them empty
    row.stat.setCurrentIndex(0)


def test_the_top5_tab_has_five_rows_with_the_names_in_the_language_of_the_program(window):
    assert len(window.tile_rows) == 5 and window.btn_top5.text() == "Save and write the page again"
    row = window.tile_rows[0]
    assert items(row.agg) == ["Sum", "Average", "Maximum"]
    assert items(row.scope) == ["All characters", "Class", "Race", "Faction", "Realm", "Character"]
    window.cmb_lang.setCurrentIndex(window.cmb_lang.findData("de"))
    window.on_language()
    assert items(row.agg) == ["Summe", "Durchschnitt", "Maximum"] and items(row.scope)[0] == "Alle Charaktere" and row.scope.currentData() == "all"
    assert window.tabs.tabText(main_window.TAB_TOP5) == "Top 5" and window.btn_top5.text() == "Speichern und Seite neu schreiben"


def test_without_data_the_tab_says_so_and_saving_changes_nothing(window, qtbot, monkeypatch):
    wow_install.out_files("_retail_")[0].unlink(missing_ok=True)
    window.cfg["top5"] = {"_retail_": [{"stat": 2, "agg": "sum", "by": "all", "value": ""}]}
    shown = []
    monkeypatch.setattr(main_window.dialogs, "info", lambda _parent, text: shown.append(text))
    window.tabs.setCurrentIndex(main_window.TAB_TOP5)
    wait_idle(qtbot, window)
    assert "no data for this game version" in window.lbl_top5.text() and window._tile_choices is None
    window.btn_top5.click()
    assert shown == ["There is no data for this game version yet. Read the data first."]
    assert window.cfg["top5"] == {"_retail_": [{"stat": 2, "agg": "sum", "by": "all", "value": ""}]}       # not cleared by a tab that offered nothing


def test_the_rows_offer_the_statistics_with_a_number_and_the_choices_of_the_data(window, qtbot, stats_data):
    open_top5(window, qtbot)
    row = window.tile_rows[0]
    offered = items(row.stat)
    assert offered[0] == "– none –" and GOLD_LABEL in offered and "Total deaths (Combat > Deaths)" in offered and any(o.startswith("Total time played") for o in offered)
    assert "Quests done (Quests)" in offered and window.lbl_top5.text() == ""
    assert not row.value.isEnabled()                                              # "all characters": nothing to choose
    pick(row.scope, "Class")
    assert row.value.isEnabled() and items(row.value) == ["Druid", "Mage"]
    pick(row.scope, "Character")
    assert items(row.value) == as_shown("Alice-Realm", "Bob-Realm")                       # nothing of the class that was chosen before stays in the list
    pick(row.scope, "Faction")
    assert items(row.value) == ["Alliance"]
    pick(row.scope, "All characters")
    assert not row.value.isEnabled()


def test_saving_stores_the_tiles_in_the_settings_and_writes_the_page_again(window, qtbot, stats_data):
    _db, page = stats_data
    open_top5(window, qtbot)
    first, second = window.tile_rows[0], window.tile_rows[1]
    pick(first.stat, GOLD_LABEL)
    pick(first.scope, "Class")
    pick(first.value, "Mage")
    pick(second.stat, "Quests done (Quests)")
    pick(second.agg, "Maximum")
    window.btn_top5.click()
    wanted = [{"stat": 2, "agg": "sum", "by": "class", "value": "MAGE"}, {"stat": 3, "agg": "max", "by": "all", "value": ""}]
    assert window.cfg["top5"] == {"_retail_": wanted} and config.load()[0]["top5"] == {"_retail_": wanted}
    qtbot.waitUntil(lambda: 'id="top5"' in page.read_text(encoding="utf-8") and not window._busy, timeout=20000)
    text = page.read_text(encoding="utf-8")
    block = text.split('id="top5"')[1].split('<div data-slot="1">')[0]
    assert "Gold earned" in block and "Class: Mage" in block and "12.05" in block and "Quests done" in block
    log = window.log.toPlainText()
    assert "Top 5 saved (_retail_): 2 tiles." in log and "Page written again" in log


def test_a_row_whose_statistic_is_not_in_the_list_stays_empty_and_is_reported(window, qtbot, stats_data):
    open_top5(window, qtbot)
    pick(window.tile_rows[0].stat, GOLD_LABEL)
    window.tile_rows[1].stat.setCurrentText("not a statistic")
    window.btn_top5.click()
    assert window.cfg["top5"] == {"_retail_": [{"stat": 2, "agg": "sum", "by": "all", "value": ""}]}
    assert "Top 5, row 2: the statistic does not fit exactly one entry" in window.log.toPlainText()
    assert "Top 5 saved (_retail_): 1 tiles. Top 5, row 2:" in window.lbl_top5.text()                 # said on the tab itself, where the person is looking
    qtbot.waitUntil(lambda: not window._busy, timeout=20000)


def test_tiles_of_the_settings_are_shown_in_the_rows_and_one_that_names_something_missing_is_kept(window, qtbot, stats_data):
    window.cfg["top5"] = {"_retail_": [{"stat": 2, "agg": "avg", "by": "char", "value": "Bob-Realm"}, {"stat": 999, "agg": "max", "by": "class", "value": "WARLOCK"}]}
    open_top5(window, qtbot)
    first, second = window.tile_rows[:2]
    assert (first.stat.currentText(), first.agg.currentData(), first.scope.currentData(), first.value.currentData()) == (GOLD_LABEL, "avg", "char", "Bob-Realm")
    assert (second.stat.currentText(), second.stat.currentData(), second.scope.currentData(), second.value.currentData()) == ("#999", 999, "class", "WARLOCK")
    assert window.tile_rows[2].stat.currentText() == "– none –" and not window.tile_rows[2].value.isEnabled()
    window.btn_top5.click()
    assert window.cfg["top5"]["_retail_"][1] == {"stat": 999, "agg": "max", "by": "class", "value": "WARLOCK"}        # saving does not lose what the data lacks
    qtbot.waitUntil(lambda: not window._busy, timeout=20000)


def test_the_choices_are_read_again_only_when_the_data_the_game_version_or_the_language_changed(window, qtbot, stats_data, monkeypatch):
    calls = []
    real = main_window.actions.tile_choices
    monkeypatch.setattr(main_window.actions, "tile_choices", lambda variant, rules=None: calls.append(variant) or real(variant, rules))
    open_top5(window, qtbot)
    window.tabs.setCurrentIndex(main_window.TAB_SETTINGS)
    window.tabs.setCurrentIndex(main_window.TAB_TOP5)
    assert calls == ["_retail_"]
    window._tile_key = None                                                        # as after an import
    window.tabs.setCurrentIndex(main_window.TAB_SETTINGS)
    window.tabs.setCurrentIndex(main_window.TAB_TOP5)
    qtbot.waitUntil(lambda: len(calls) == 2 and not window._busy, timeout=20000)


def test_the_top5_tab_does_not_offer_a_character_the_rules_keep_off_the_page(window, qtbot, stats_data):
    window.cfg["char_rules"] = {"_retail_": [{"type": "char", "value": "Bob-Realm"}]}
    open_top5(window, qtbot)
    row = window.tile_rows[0]
    pick(row.scope, "Character")
    assert items(row.value) == as_shown("Alice-Realm")


def test_saving_the_tiles_writes_the_page_without_the_characters_the_rules_keep_off_it(window, qtbot, stats_data):
    _db, page = stats_data
    assert "Bob-Realm" in page.read_text(encoding="utf-8")
    window.cfg["char_rules"] = {"_retail_": [{"type": "char", "value": "Bob-Realm"}]}
    open_top5(window, qtbot)
    pick(window.tile_rows[0].stat, GOLD_LABEL)
    window.btn_top5.click()
    qtbot.waitUntil(lambda: 'id="top5"' in page.read_text(encoding="utf-8") and not window._busy, timeout=20000)
    text = page.read_text(encoding="utf-8")
    assert "Alice-Realm" in text and "Bob-Realm" not in text


def test_reading_the_data_hands_the_rules_of_the_game_version_to_the_import(window, env, qtbot, monkeypatch):
    path = wow_install.saved_vars_path(env.wow / "_retail_", "ACC1")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("StatTrackerDB = {}", encoding="utf-8")
    seen = []
    monkeypatch.setattr(actions, "run_parser", lambda *a, **k: seen.append(k) or (True, ""))
    rule = {"type": "char", "value": "Bob-Realm", "for": ["page"]}
    window.cfg["char_rules"] = {"_retail_": [rule], "_forever_": [{"type": "char", "value": "Other-Realm"}]}
    window.cfg["char_blacklist"] = {"_retail_": ["Deleted-Realm"], "_forever_": ["Other-Realm"]}
    try:
        window.on_parse()
        wait_idle(qtbot, window)
        assert seen[-1]["rules"] == [rule]                                          # the rules of this game version only
        assert seen[-1]["skip"] == ["Deleted-Realm"]                                # and the deleted characters of this game version only
    finally:
        path.unlink(missing_ok=True)


# ------------------------------------------------------------------------------------------------------------ the Characters tab
def open_chars(window, qtbot):
    window.tabs.setCurrentIndex(main_window.TAB_CHARS)
    qtbot.waitUntil(lambda: not window._busy and window._chars_key is not None, timeout=20000)
    return window.char_tiles


def tile_of(window, variant="_retail_"):
    return next(tile for tile in window.char_tiles if tile.variant == variant)


def list_rows(tile):
    """What the list shows: [type, value, targets, hits] per rule."""
    table = tile.table
    return [[table.item(row, column).text() for column in (1, 2, 3, 4)] for row in range(table.rowCount())]


def fill_form(tile, kind, value=None, page=True, excel=True):
    tile.kind.setCurrentIndex(tile.kind.findData(kind))
    if kind == "level_below":
        tile.level.setValue(int(value))
    elif value is not None:
        tile.value.setCurrentIndex(tile.value.findText(value))
    tile.page.setChecked(page)
    tile.excel.setChecked(excel)


def add_rule(tile, kind, value=None, page=True, excel=True):
    fill_form(tile, kind, value, page, excel)
    tile.add.click()


def mark(tile, *rows):
    for row in rows:
        tile.table.item(row, 0).setCheckState(Qt.CheckState.Checked)


def page_text(page):
    return page.read_text(encoding="utf-8")


def wait_page(window, qtbot, page, check):
    qtbot.waitUntil(lambda: not window._busy and check(page_text(page)), timeout=20000)


def apply_and_wait(window, qtbot, tile):
    tile.save.click()
    qtbot.waitUntil(lambda: not window._busy, timeout=20000)


MAGE_PAGE = {"type": "class", "value": "MAGE", "for": ["page"]}


def test_the_characters_tab_is_the_fourth_and_is_named_in_both_languages(window):
    assert window.tabs.count() == 4 and main_window.TAB_CHARS == 3
    assert window.tabs.tabText(main_window.TAB_CHARS) == "Characters"
    window.cmb_lang.setCurrentIndex(window.cmb_lang.findData("de"))
    window.on_language()
    assert window.tabs.tabText(main_window.TAB_CHARS) == "Charaktere"


def test_without_data_the_block_of_a_game_version_says_so_and_has_no_form(window, qtbot):
    wow_install.out_files("_retail_")[0].unlink(missing_ok=True)
    tiles = open_chars(window, qtbot)
    assert [tile.variant for tile in tiles] == ["_retail_"] and tiles[0].table is None and tiles[0].add is None and tiles[0].save is None
    assert tiles[0].box.title() == "Ignore – _retail_"
    assert "no data for this game version" in tiles[0].box.findChild(main_window.QLabel).text()


def test_a_choice_of_the_game_version_shows_the_block_of_each_enabled_one_and_each_keeps_what_was_set_in_it(window, qtbot, stats_data):
    window.cfg["enabled_variants"] = ["_forever_", "_retail_"]
    tiles = open_chars(window, qtbot)
    assert [tile.variant for tile in tiles] == ["_retail_", "_forever_"] and picker_items(window.pick_chars) == ["_retail_", "_forever_"]
    assert window.chars_stack.currentWidget() is tiles[0].panel and tiles[1].table is None            # this one has no database
    add_rule(tiles[0], "class", "Mage")
    window.pick_chars.combo.setCurrentText("_forever_")
    assert window.chars_stack.currentWidget() is tiles[1].panel
    window.pick_chars.combo.setCurrentText("_retail_")
    assert window.chars_stack.currentWidget() is tiles[0].panel and list_rows(tiles[0]) == [["Class", "Mage", "Page, Excel", "1"]]


def test_the_form_offers_the_types_and_the_entries_of_the_data(window, qtbot, stats_data):
    tile = open_chars(window, qtbot)[0]
    assert items(tile.kind) == ["Class", "Race", "Faction", "Realm", "Character", "Level under"]
    assert tile.kind.currentData() == "class" and items(tile.value) == ["Druid", "Mage"] and tile.value.currentText() == ""      # nothing is chosen for the person
    tile.kind.setCurrentIndex(tile.kind.findData("race"))
    assert items(tile.value) == ["Human", "Night Elf"]
    tile.kind.setCurrentIndex(tile.kind.findData("faction"))
    assert items(tile.value) == ["Alliance"]
    tile.kind.setCurrentIndex(tile.kind.findData("char"))
    assert items(tile.value) == as_shown("Alice-Realm", "Bob-Realm")
    tile.kind.setCurrentIndex(tile.kind.findData("level_below"))
    assert tile.value.isHidden() and not tile.level.isHidden() and tile.level.value() == 20
    tile.kind.setCurrentIndex(tile.kind.findData("class"))
    assert not tile.value.isHidden() and tile.level.isHidden()


def test_the_saved_rules_are_the_list_with_their_targets_and_the_characters_they_hit(window, qtbot, stats_data):
    ghost = {"type": "char", "value": "Ghost-Realm"}
    window.cfg["char_rules"] = {"_retail_": [MAGE_PAGE, {"type": "class", "value": "DRUID"}, {"type": "level_below", "value": "75", "for": ["excel"]}, ghost]}
    tile = open_chars(window, qtbot)[0]
    assert list_rows(tile) == [["Class", "Mage", "Page", "1"], ["Class", "Druid", "Page, Excel", "1"], ["Level under", "75", "Excel", "1"],
                               ["Character", "Ghost / Realm", "Page, Excel", "0"]]                 # a rule for a character the data lacks is seen, with 0 hits
    assert tile.counter.text() == "Page: 2 of 2 hidden · Excel: 1 of 2" and tile.pending.text() == ""


def test_adding_a_rule_puts_it_in_the_list_and_the_counter_but_saves_nothing(window, qtbot, stats_data):
    tile = open_chars(window, qtbot)[0]
    add_rule(tile, "class", "Mage")
    assert list_rows(tile) == [["Class", "Mage", "Page, Excel", "1"]]
    assert tile.counter.text() == "Page: 1 of 2 hidden · Excel: 1 of 2" and tile.pending.text() == "Changed, not applied yet."
    add_rule(tile, "class", "Druid", excel=False)
    add_rule(tile, "level_below", "75", page=False)
    assert list_rows(tile) == [["Class", "Mage", "Page, Excel", "1"], ["Class", "Druid", "Page", "1"], ["Level under", "75", "Excel", "1"]]
    assert window.cfg["char_rules"] == {} and config.load()[0]["char_rules"] == {}                   # nothing is saved before "Apply"


def test_the_same_type_and_value_is_one_rule_with_the_targets_of_both(window, qtbot, stats_data):
    window.cfg["char_rules"] = {"_retail_": [MAGE_PAGE]}
    tile = open_chars(window, qtbot)[0]
    add_rule(tile, "class", "Mage", page=False, excel=True)
    assert list_rows(tile) == [["Class", "Mage", "Page, Excel", "1"]]
    add_rule(tile, "class", "Mage")
    assert list_rows(tile) == [["Class", "Mage", "Page, Excel", "1"]]                                # the same again: still one


def test_a_rule_for_no_target_cannot_be_added(window, qtbot, stats_data):
    tile = open_chars(window, qtbot)[0]
    fill_form(tile, "class", "Mage", page=False, excel=False)
    assert not tile.add.isEnabled()
    tile.excel.setChecked(True)
    assert tile.add.isEnabled()


def test_a_value_that_fits_no_entry_is_not_added_and_the_person_is_told(window, qtbot, stats_data):
    tile = open_chars(window, qtbot)[0]
    tile.add.click()                                                                                 # nothing chosen
    assert list_rows(tile) == [] and "does not fit an entry" in tile.message.text()
    tile.value.setCurrentText("nothing like it")
    tile.add.click()
    assert list_rows(tile) == [] and tile.pending.text() == ""
    tile.value.setCurrentText("mag")                                                                 # a part of one name is enough, like in the Top 5 tab
    tile.add.click()
    assert list_rows(tile) == [["Class", "Mage", "Page, Excel", "1"]] and tile.message.text() == ""


def test_the_ticked_rules_are_taken_out_of_the_list_and_the_others_stay(window, qtbot, stats_data):
    other = {"type": "race", "value": "Human"}
    window.cfg["char_rules"] = {"_retail_": [MAGE_PAGE, other, {"type": "char", "value": "Ghost-Realm"}]}
    tile = open_chars(window, qtbot)[0]
    mark(tile, 0, 2)
    tile.remove.click()
    assert list_rows(tile) == [["Race", "Human", "Page, Excel", "1"]] and tile.pending.text() == "Changed, not applied yet."
    assert window.cfg["char_rules"] == {"_retail_": [MAGE_PAGE, other, {"type": "char", "value": "Ghost-Realm"}]}      # not saved yet
    mark(tile, 0)
    tile.remove.click()
    assert list_rows(tile) == [] and not tile.remove.isEnabled()


def test_the_note_that_the_list_is_not_applied_goes_when_it_is_the_saved_one_again(window, qtbot, stats_data):
    window.cfg["char_rules"] = {"_retail_": [MAGE_PAGE]}
    tile = open_chars(window, qtbot)[0]
    assert tile.pending.text() == ""
    add_rule(tile, "class", "Druid")
    assert tile.pending.text() == "Changed, not applied yet."
    mark(tile, 1)
    tile.remove.click()
    assert tile.pending.text() == ""


def test_applying_saves_the_list_and_writes_its_page_again_without_the_characters_and_the_rules_stay_in_the_list(window, qtbot, stats_data):
    _db, page = stats_data
    assert "Alice-Realm" in page_text(page) and "Bob-Realm" in page_text(page)
    tile = open_chars(window, qtbot)[0]
    add_rule(tile, "class", "Mage", excel=False)
    tile.save.click()
    wanted = {"_retail_": [MAGE_PAGE]}
    assert window.cfg["char_rules"] == wanted and config.load()[0]["char_rules"] == wanted
    wait_page(window, qtbot, page, lambda text: "Alice-Realm" not in text)
    assert "Bob-Realm" in page_text(page)
    log = window.log.toPlainText()
    assert "Ignore saved (_retail_): 1 rules." in log and "Page written again" in log
    assert tile.message.text() == "Ignore saved (_retail_): 1 rules." and tile.pending.text() == ""
    assert list_rows(tile) == [["Class", "Mage", "Page", "1"]]                                       # it stays until it is taken out


def test_the_targets_of_a_rule_are_saved_as_they_were_set(window, qtbot, stats_data):
    tile = open_chars(window, qtbot)[0]
    for page_on, excel_on, expected in ((True, True, {"type": "class", "value": "MAGE"}), (True, False, MAGE_PAGE),
                                        (False, True, {"type": "class", "value": "MAGE", "for": ["excel"]})):
        tile.draft = []
        add_rule(tile, "class", "Mage", page=page_on, excel=excel_on)
        apply_and_wait(window, qtbot, tile)
        assert window.cfg["char_rules"] == {"_retail_": [expected]}


def test_taking_every_rule_out_and_applying_brings_the_characters_back_to_the_page(window, qtbot, stats_data):
    _db, page = stats_data
    tile = open_chars(window, qtbot)[0]
    add_rule(tile, "class", "Mage")
    tile.save.click()
    wait_page(window, qtbot, page, lambda text: "Alice-Realm" not in text)
    mark(tile, 0)
    tile.remove.click()
    assert window.cfg["char_rules"] != {} and "Alice-Realm" not in page_text(page)                   # taken out, not applied: nothing changed yet
    tile.save.click()
    wait_page(window, qtbot, page, lambda text: "Alice-Realm" in text)                              # the database never lost her
    assert window.cfg["char_rules"] == {} and config.load()[0]["char_rules"] == {}


def test_rules_of_other_kinds_stay_in_their_place_when_a_rule_is_added_and_applied(window, qtbot, stats_data):
    ghost, odd, other = {"type": "char", "value": "Ghost-Realm"}, {"type": "guild", "value": "x"}, {"type": "class", "value": "ROGUE", "for": ["excel"]}
    window.cfg["char_rules"] = {"_retail_": [ghost, odd, other]}
    tile = open_chars(window, qtbot)[0]
    assert list_rows(tile)[1] == ["guild", "x", "Page, Excel", "0"]                                  # what the program does not know is shown as it is
    add_rule(tile, "class", "Mage", excel=False)
    apply_and_wait(window, qtbot, tile)
    assert config.load()[0]["char_rules"] == {"_retail_": [ghost, odd, other, MAGE_PAGE]}


def test_a_level_is_a_rule_of_its_targets(window, qtbot, stats_data):
    _db, page = stats_data
    tile = open_chars(window, qtbot)[0]
    add_rule(tile, "level_below", "75", excel=False)                                                 # Bob is level 70
    tile.save.click()
    assert window.cfg["char_rules"] == {"_retail_": [{"type": "level_below", "value": "75", "for": ["page"]}]}
    wait_page(window, qtbot, page, lambda text: "Bob-Realm" not in text)
    assert "Alice-Realm" in page_text(page)


def test_applying_makes_the_top5_tab_read_what_it_offers_again(window, qtbot, stats_data):
    tile = open_chars(window, qtbot)[0]
    window._tile_key = ("something", "read before")
    add_rule(tile, "class", "Mage")
    apply_and_wait(window, qtbot, tile)
    assert window._tile_key is None


def test_applying_one_game_version_writes_only_its_page_and_leaves_the_other_block_alone(window, env, qtbot, stats_data):
    from app import stat_parser
    forever_db, forever_page = wow_install.out_files("_forever_")
    stat_parser.main(["--input", str(env.base / "TopFive.lua"), "--db", str(forever_db), "--output", str(forever_page)])
    try:
        _db, retail_page = stats_data
        window.cfg["enabled_variants"] = ["_retail_", "_forever_"]
        retail, forever = open_chars(window, qtbot)
        add_rule(retail, "class", "Mage")                                                            # not applied
        add_rule(forever, "class", "Druid", excel=False)
        apply_and_wait(window, qtbot, forever)
        assert window.cfg["char_rules"] == {"_forever_": [{"type": "class", "value": "DRUID", "for": ["page"]}]}
        wait_page(window, qtbot, forever_page, lambda text: "Bob-Realm" not in text)
        assert "Alice-Realm" in page_text(forever_page) and "Alice-Realm" in page_text(retail_page) and "Bob-Realm" in page_text(retail_page)
        assert "stats_forever.html" in window.log.toPlainText()                                      # the log names the page that was written
        assert list_rows(retail) == [["Class", "Mage", "Page, Excel", "1"]] and retail.pending.text() == "Changed, not applied yet."
    finally:
        forever_db.unlink(missing_ok=True)
        forever_page.unlink(missing_ok=True)


def test_a_new_language_builds_the_blocks_again_with_its_names(window, qtbot, stats_data):
    window.cfg["char_rules"] = {"_retail_": [{"type": "class", "value": "DRUID"}]}
    tile = open_chars(window, qtbot)[0]
    assert tile.box.title() == "Ignore – _retail_" and list_rows(tile)[0][:2] == ["Class", "Druid"]
    window.cmb_lang.setCurrentIndex(window.cmb_lang.findData("de"))
    window.on_language()
    qtbot.waitUntil(lambda: not window._busy and window._chars_key is not None and window.char_tiles[0].box.title() == "Ignorieren – _retail_", timeout=20000)
    assert list_rows(window.char_tiles[0])[0][0] == "Klasse" and list_rows(window.char_tiles[0])[0][1].startswith("Druid")


def test_the_blocks_are_read_again_only_when_the_data_the_game_versions_or_the_language_changed(window, qtbot, stats_data, monkeypatch):
    calls = []
    real = main_window.actions.ignore_choices
    monkeypatch.setattr(main_window.actions, "ignore_choices", lambda variant: calls.append(variant) or real(variant))
    open_chars(window, qtbot)
    window.tabs.setCurrentIndex(main_window.TAB_SETTINGS)
    window.tabs.setCurrentIndex(main_window.TAB_CHARS)
    assert calls == ["_retail_"]
    window._chars_key = None                                                                         # as after an import
    window.tabs.setCurrentIndex(main_window.TAB_SETTINGS)
    window.tabs.setCurrentIndex(main_window.TAB_CHARS)
    qtbot.waitUntil(lambda: len(calls) == 2 and not window._busy, timeout=20000)
    window.cfg["enabled_variants"] = ["_retail_", "_forever_"]                                       # another game version: read again
    window.tabs.setCurrentIndex(main_window.TAB_SETTINGS)
    window.tabs.setCurrentIndex(main_window.TAB_CHARS)
    qtbot.waitUntil(lambda: len(calls) == 4 and not window._busy, timeout=20000)


def test_a_database_that_cannot_be_read_is_said_in_the_log_and_the_block_and_read_again_next_time(window, qtbot, stats_data, monkeypatch):
    def broken(variant):
        raise SystemExit("ERROR: too new")
    monkeypatch.setattr(main_window.actions, "ignore_choices", broken)
    window.tabs.setCurrentIndex(main_window.TAB_CHARS)
    qtbot.waitUntil(lambda: not window._busy and len(window.char_tiles) == 1, timeout=20000)
    assert window._chars_key is None and "ERROR: too new" in window.log.toPlainText()
    assert window.char_tiles[0].table is None and "could not be read" in window.char_tiles[0].box.findChild(main_window.QLabel).text()


def test_building_the_blocks_again_leaves_no_block_behind(window, qtbot, stats_data):
    open_chars(window, qtbot)
    window._chars_rebuild({"_retail_": None})
    window._chars_rebuild({"_retail_": None})
    qtbot.wait(50)
    assert len(window.char_tiles) == 1 and window.chars_stack.count() == 1 and picker_items(window.pick_chars) == ["_retail_"]


def test_the_apply_buttons_are_off_while_a_slow_action_runs_and_none_is_left_behind_by_a_new_build(window, qtbot, stats_data):
    tile = open_chars(window, qtbot)[0]
    plain = [button for button in window.action_buttons if button not in window._chars_buttons]
    assert window._chars_buttons == [tile.save, tile.del_save] and all(button in window.action_buttons for button in window._chars_buttons)
    window.set_busy(True, "x")
    assert not tile.save.isEnabled() and not tile.del_save.isEnabled()
    window.set_busy(False)
    assert tile.save.isEnabled() and tile.del_save.isEnabled()
    window._chars_rebuild({"_retail_": None})
    window._chars_rebuild({"_retail_": None})
    assert window._chars_buttons == [] and window.action_buttons == plain                            # a block without data has no button, the old ones are gone
    window.set_busy(True, "x")                                                                       # no error from a button that was deleted
    window.set_busy(False)


def test_a_settings_file_that_cannot_be_written_is_said_and_the_page_is_still_written_again(window, qtbot, stats_data, monkeypatch):
    _db, page = stats_data

    def refuse(_cfg):
        raise OSError("disk full")
    monkeypatch.setattr(main_window.config, "save", refuse)
    tile = open_chars(window, qtbot)[0]
    add_rule(tile, "class", "Mage")
    tile.save.click()
    assert "disk full" in window.log.toPlainText()
    wait_page(window, qtbot, page, lambda text: "Alice-Realm" not in text)


# ------------------------------------------------------------------------------------------------------------ the block "Delete"
def del_rows(tile):
    """What the list of the characters marked for deleting shows: [character, class, level] per row."""
    table = tile.del_table
    return [[table.item(row, column).text() for column in (1, 2, 3)] for row in range(table.rowCount())]


def bl_rows(tile):
    return [tile.bl_table.item(row, 1).text() for row in range(tile.bl_table.rowCount())]


def mark_in(table, *rows):
    for row in rows:
        table.item(row, 0).setCheckState(Qt.CheckState.Checked)


def pick_char(tile, key):
    tile.del_char.setCurrentIndex(tile.del_char.findData(key))
    tile.del_add.click()


def test_a_surname_in_the_data_is_shown_in_the_lists_and_the_key_stays_the_data_behind_it(window, qtbot, stats_data):
    import sqlite3
    db, _page = stats_data
    conn = sqlite3.connect(db)
    conn.execute("UPDATE scans SET surname = 'Everbeen' WHERE char_key = 'Alice-Realm'")
    conn.commit()
    conn.close()
    tile = open_chars(window, qtbot)[0]
    assert items(tile.del_char) == ["Alice Everbeen / Realm", "Bob / Realm"]
    pick_char(tile, "Alice-Realm")
    assert del_rows(tile) == [["Alice Everbeen / Realm", "Mage", "80"]] and tile.del_list == ["Alice-Realm"]


def test_the_block_delete_stands_under_ignore_for_a_game_version_with_data_only(window, qtbot, stats_data):
    window.cfg["enabled_variants"] = ["_retail_", "_forever_"]
    retail, forever = open_chars(window, qtbot)
    assert retail.del_box.title() == "Delete – _retail_" and forever.del_box is None and forever.del_table is None     # no data: nothing to delete
    layout = retail.panel.layout()
    assert layout.itemAt(0).widget() is retail.box and layout.itemAt(1).widget() is retail.del_box


def test_the_form_offers_the_characters_of_the_data_and_the_list_shows_what_was_picked(window, qtbot, stats_data):
    tile = open_chars(window, qtbot)[0]
    assert items(tile.del_char) == as_shown("Alice-Realm", "Bob-Realm") and tile.del_char.currentText() == ""        # nothing is chosen for the person
    assert del_rows(tile) == [] and tile.del_preview.text() == "This list deletes 0 characters." and not tile.del_remove.isEnabled()
    pick_char(tile, "Bob-Realm")
    assert del_rows(tile) == [["Bob / Realm", "Druid", "70"]] and tile.del_preview.text() == "This list deletes 1 characters."
    assert tile.del_char.currentText() == ""                                                                  # ready for the next one
    pick_char(tile, "Bob-Realm")                                                                              # a character once
    assert del_rows(tile) == [["Bob / Realm", "Druid", "70"]]
    pick_char(tile, "Alice-Realm")
    assert del_rows(tile) == [["Bob / Realm", "Druid", "70"], ["Alice / Realm", "Mage", "80"]] and tile.del_remove.isEnabled()


def test_the_ticked_characters_are_taken_off_the_list_and_nothing_else_happens(window, qtbot, stats_data):
    tile = open_chars(window, qtbot)[0]
    pick_char(tile, "Alice-Realm")
    pick_char(tile, "Bob-Realm")
    mark_in(tile.del_table, 0)
    tile.del_remove.click()
    assert del_rows(tile) == [["Bob / Realm", "Druid", "70"]] and tile.del_preview.text() == "This list deletes 1 characters."
    assert window.cfg["char_blacklist"] == {} and config.load()[0]["char_blacklist"] == {}                  # nothing is saved, nothing is deleted
    assert scans_in_data("_retail_") == 2


def scans_in_data(variant):
    import sqlite3
    conn = sqlite3.connect(wow_install.out_files(variant)[0])
    try:
        return conn.execute("SELECT COUNT(DISTINCT char_key) FROM scans").fetchone()[0]
    finally:
        conn.close()


def test_a_text_that_fits_no_character_is_not_added_and_a_part_of_a_name_is_enough_when_it_fits_one(window, qtbot, stats_data):
    tile = open_chars(window, qtbot)[0]
    tile.del_add.click()                                                                                      # nothing chosen
    assert del_rows(tile) == [] and "does not fit an entry" in tile.del_message.text()
    tile.del_char.setCurrentText("nobody like it")
    tile.del_add.click()
    assert del_rows(tile) == []
    tile.del_char.setCurrentText("ali")
    tile.del_add.click()
    assert del_rows(tile) == [["Alice / Realm", "Mage", "80"]] and tile.del_message.text() == ""


def test_a_character_the_list_names_but_the_data_does_not_have_shows_without_class_and_level(window, qtbot, stats_data):
    tile = open_chars(window, qtbot)[0]
    tile.del_list = ["Ghost-Realm"]
    window._del_refresh(tile)
    assert del_rows(tile) == [["Ghost / Realm", "", ""]]


def test_the_blacklist_of_the_game_version_is_listed(window, qtbot, stats_data):
    window.cfg["char_blacklist"] = {"_retail_": ["Gone-Realm", "Other-Realm"], "_forever_": ["Forever-Realm"]}
    tile = open_chars(window, qtbot)[0]
    assert bl_rows(tile) == as_shown("Gone-Realm", "Other-Realm") and tile.bl_note.text() == "" and tile.bl_remove.isEnabled()
    window.cfg["char_blacklist"] = {}
    window._bl_refresh(tile)
    assert bl_rows(tile) == [] and tile.bl_note.text() == "The blacklist is empty." and not tile.bl_remove.isEnabled()


def test_the_ticked_entries_leave_the_blacklist_and_that_is_saved_at_once(window, qtbot, stats_data):
    window.cfg["char_blacklist"] = {"_retail_": ["Gone-Realm", "Other-Realm", "Third-Realm"], "_forever_": ["Forever-Realm"]}
    tile = open_chars(window, qtbot)[0]
    mark_in(tile.bl_table, 0, 2)
    tile.bl_remove.click()
    wanted = {"_retail_": ["Other-Realm"], "_forever_": ["Forever-Realm"]}
    assert window.cfg["char_blacklist"] == wanted and config.load()[0]["char_blacklist"] == wanted
    assert bl_rows(tile) == as_shown("Other-Realm") and "2 entries removed from the blacklist" in tile.bl_message.text()
    assert "2 entries removed" in window.log.toPlainText() and "read again" in tile.bl_message.text()
    mark_in(tile.bl_table, 0)
    tile.bl_remove.click()
    assert window.cfg["char_blacklist"] == {"_forever_": ["Forever-Realm"]} and bl_rows(tile) == [] and tile.bl_note.text() == "The blacklist is empty."


def test_nothing_ticked_changes_nothing(window, qtbot, stats_data):
    window.cfg["char_blacklist"] = {"_retail_": ["Gone-Realm"]}
    tile = open_chars(window, qtbot)[0]
    tile.bl_remove.click()
    assert window.cfg["char_blacklist"] == {"_retail_": ["Gone-Realm"]} and bl_rows(tile) == as_shown("Gone-Realm") and tile.bl_message.text() == ""


def test_a_blacklist_that_cannot_be_saved_stays_as_it_was(window, qtbot, stats_data, monkeypatch):
    window.cfg["char_blacklist"] = {"_retail_": ["Gone-Realm", "Other-Realm"]}
    tile = open_chars(window, qtbot)[0]

    def refuse(_cfg):
        raise OSError("disk full")
    monkeypatch.setattr(main_window.config, "save", refuse)
    mark_in(tile.bl_table, 0)
    tile.bl_remove.click()
    assert window.cfg["char_blacklist"] == {"_retail_": ["Gone-Realm", "Other-Realm"]} and "disk full" in window.log.toPlainText()
    assert bl_rows(tile) == as_shown("Gone-Realm", "Other-Realm")


def test_the_delete_block_has_its_own_names_in_german(window, qtbot, stats_data):
    open_chars(window, qtbot)
    window.cmb_lang.setCurrentIndex(window.cmb_lang.findData("de"))
    window.on_language()
    qtbot.waitUntil(lambda: not window._busy and window._chars_key is not None and window.char_tiles[0].box.title() == "Ignorieren – _retail_", timeout=20000)
    tile = window.char_tiles[0]
    assert tile.del_box.title() == "Löschen – _retail_" and tile.del_preview.text() == "Diese Liste löscht 0 Charaktere." and tile.bl_note.text() == "Die Blacklist ist leer."


# ------------------------------------------------------------------------------------------------------------ deleting characters
def ask(monkeypatch, answer):
    """Replaces the question of the window by an answer and returns the list of the questions that were asked."""
    texts = []
    monkeypatch.setattr(main_window.dialogs, "ask_yes_no", lambda parent, text: texts.append(text) or answer)
    return texts


def spy_delete(monkeypatch, result=None):
    """Replaces actions.delete_chars by a function that notes its arguments and what config.json holds at that very moment, and then returns `result`
    (None: does the real deleting)."""
    calls = []
    real = main_window.actions.delete_chars

    def wrapper(variant, keys, top5=None, rules=None):
        calls.append({"variant": variant, "keys": list(keys), "top5": top5, "rules": rules, "on_disk": config.load()[0]["char_blacklist"]})
        return result if result is not None else real(variant, keys, top5, rules)
    monkeypatch.setattr(main_window.actions, "delete_chars", wrapper)
    return calls


def wait_rebuilt(window, qtbot, check):
    qtbot.waitUntil(lambda: not window._busy and window._chars_key is not None and check(window.char_tiles[0]), timeout=20000)


def delete_dir():
    return wow_install.out_files("_retail_")[0].parent / "backups" / "delete"


def delete_copies():
    """How many copies before deleting exist (the instance is shared by the tests of this module, so tests compare before and after)."""
    return len(list(delete_dir().glob("*.pre-delete.bak"))) if delete_dir().exists() else 0


def test_an_empty_delete_list_asks_nothing_and_does_nothing(window, qtbot, stats_data, monkeypatch):
    questions, calls = ask(monkeypatch, True), spy_delete(monkeypatch)
    tile = open_chars(window, qtbot)[0]
    tile.del_save.click()
    assert tile.del_message.text() == "The delete list is empty." and questions == [] and calls == []


def test_the_question_names_the_number_and_the_characters_and_no_deletes_nothing_and_changes_nothing(window, qtbot, stats_data, monkeypatch):
    questions, calls = ask(monkeypatch, False), spy_delete(monkeypatch)
    tile = open_chars(window, qtbot)[0]
    copies = delete_copies()
    pick_char(tile, "Alice-Realm")
    pick_char(tile, "Bob-Realm")
    tile.del_save.click()
    assert len(questions) == 1 and "Delete 2 characters for good from the database of _retail_" in questions[0]
    assert "Alice / Realm\nBob / Realm" in questions[0] and str(delete_dir()) in questions[0] and "blacklist" in questions[0]
    assert calls == [] and window.cfg["char_blacklist"] == {} and config.load()[0]["char_blacklist"] == {}
    assert del_rows(tile) != [] and len(del_rows(tile)) == 2 and tile.del_message.text() == "Cancelled, nothing was deleted."
    assert scans_in_data("_retail_") == 2 and delete_copies() == copies                              # no copy for a deleting that did not happen


def test_the_question_lists_twelve_names_and_says_how_many_more(window, qtbot, stats_data, monkeypatch):
    questions = ask(monkeypatch, False)
    tile = open_chars(window, qtbot)[0]
    tile.del_list = [f"C{n:02d}-R" for n in range(14)]
    tile.del_save.click()
    assert "C11 / R" in questions[0] and "C12 / R" not in questions[0] and "... and 2 more" in questions[0] and "Delete 14 characters" in questions[0]


def test_after_yes_the_keys_are_on_the_blacklist_before_deleting_and_the_characters_are_gone(window, qtbot, stats_data, monkeypatch):
    _db, page = stats_data
    ask(monkeypatch, True)
    calls = spy_delete(monkeypatch)
    tile = open_chars(window, qtbot)[0]
    copies = delete_copies()
    pick_char(tile, "Alice-Realm")
    window._tile_key = ("read before",)
    tile.del_save.click()
    wait_rebuilt(window, qtbot, lambda built: built.del_list == [] and items(built.del_char) == as_shown("Bob-Realm"))
    assert calls[0]["variant"] == "_retail_" and calls[0]["keys"] == ["Alice-Realm"]
    assert calls[0]["on_disk"] == {"_retail_": ["Alice-Realm"]}                                       # saved BEFORE the deleting began
    assert window.cfg["char_blacklist"] == {"_retail_": ["Alice-Realm"]} and config.load()[0]["char_blacklist"] == {"_retail_": ["Alice-Realm"]}
    assert scans_in_data("_retail_") == 1 and delete_copies() == copies + 1
    wait_page(window, qtbot, page, lambda text: "Alice-Realm" not in text)
    assert "Bob-Realm" in page_text(page)
    built = window.char_tiles[0]
    assert bl_rows(built) == as_shown("Alice-Realm") and built.del_message.text() == "Deleted (_retail_): 1 characters."
    log = window.log.toPlainText()
    assert "Deleted (_retail_): 1 characters." in log and "characters deleted (1 scans): Alice-Realm" in log
    assert window._tile_key is None


def test_the_tiles_and_the_rules_of_the_game_version_reach_the_deleting(window, qtbot, stats_data, monkeypatch):
    ask(monkeypatch, True)
    calls = spy_delete(monkeypatch, result=(True, "", ["Alice-Realm"]))
    tiles = [{"stat": 2, "agg": "sum", "by": "all", "value": ""}]
    rules = [{"type": "char", "value": "Ghost-Realm"}]
    window.cfg["top5"], window.cfg["char_rules"] = {"_retail_": tiles}, {"_retail_": rules, "_forever_": [{"type": "char", "value": "Other-Realm"}]}
    tile = open_chars(window, qtbot)[0]
    pick_char(tile, "Alice-Realm")
    tile.del_save.click()
    qtbot.waitUntil(lambda: not window._busy and window._chars_key is not None, timeout=20000)
    assert calls[0]["top5"] == tiles and calls[0]["rules"] == rules                                  # the rules of this game version only


def test_a_key_that_is_on_the_blacklist_already_is_not_put_there_twice(window, qtbot, stats_data, monkeypatch):
    ask(monkeypatch, True)
    calls = spy_delete(monkeypatch, result=(True, "", ["Alice-Realm"]))
    window.cfg["char_blacklist"] = {"_retail_": ["Old-Realm", "Alice-Realm"]}
    tile = open_chars(window, qtbot)[0]
    pick_char(tile, "Alice-Realm")
    tile.del_save.click()
    qtbot.waitUntil(lambda: not window._busy and window._chars_key is not None, timeout=20000)
    assert calls[0]["on_disk"] == {"_retail_": ["Old-Realm", "Alice-Realm"]}


def test_when_nothing_was_deleted_the_keys_come_off_the_blacklist_again(window, qtbot, stats_data, monkeypatch):
    ask(monkeypatch, True)
    calls = spy_delete(monkeypatch, result=(False, "ERROR: the backup of the database failed, nothing was changed.\n", []))
    window.cfg["char_blacklist"] = {"_retail_": ["Old-Realm"]}
    tile = open_chars(window, qtbot)[0]
    pick_char(tile, "Alice-Realm")
    tile.del_save.click()
    qtbot.waitUntil(lambda: not window._busy, timeout=20000)
    assert calls[0]["on_disk"] == {"_retail_": ["Old-Realm", "Alice-Realm"]}
    assert window.cfg["char_blacklist"] == {"_retail_": ["Old-Realm"]} and config.load()[0]["char_blacklist"] == {"_retail_": ["Old-Realm"]}
    assert "the backup of the database failed" in window.log.toPlainText()
    assert tile.del_message.text() == "Nothing was deleted, the blacklist is as it was (see the log)." and bl_rows(tile) == as_shown("Old-Realm")
    assert del_rows(tile) == [["Alice / Realm", "Mage", "80"]] and scans_in_data("_retail_") == 2          # the list stays, nothing is gone


def test_a_blacklist_that_had_no_entry_has_none_again_after_a_failure(window, qtbot, stats_data, monkeypatch):
    ask(monkeypatch, True)
    spy_delete(monkeypatch, result=(False, "ERROR: x\n", []))
    tile = open_chars(window, qtbot)[0]
    pick_char(tile, "Alice-Realm")
    tile.del_save.click()
    qtbot.waitUntil(lambda: not window._busy, timeout=20000)
    assert window.cfg["char_blacklist"] == {} and config.load()[0]["char_blacklist"] == {}


def test_a_blacklist_that_cannot_be_saved_stops_the_deleting_before_it_starts(window, qtbot, stats_data, monkeypatch):
    ask(monkeypatch, True)
    calls = spy_delete(monkeypatch)
    window.cfg["char_blacklist"] = {"_retail_": ["Old-Realm"]}
    tile = open_chars(window, qtbot)[0]

    def refuse(_cfg):
        raise OSError("disk full")
    monkeypatch.setattr(main_window.config, "save", refuse)
    copies = delete_copies()
    pick_char(tile, "Alice-Realm")
    tile.del_save.click()
    assert calls == [] and scans_in_data("_retail_") == 2 and delete_copies() == copies
    assert window.cfg["char_blacklist"] == {"_retail_": ["Old-Realm"]} and "disk full" in window.log.toPlainText()
    assert tile.del_message.text() == "The blacklist could not be saved, nothing was deleted." and len(del_rows(tile)) == 1


def test_a_blacklist_that_cannot_be_set_back_is_said_plainly(window, qtbot, stats_data, monkeypatch):
    ask(monkeypatch, True)
    spy_delete(monkeypatch, result=(False, "ERROR: x\n", []))
    tile = open_chars(window, qtbot)[0]
    real, state = main_window.config.save, {"calls": 0}

    def flaky(cfg):
        state["calls"] += 1
        if state["calls"] >= 2:                                                                       # the first save (the keys on the blacklist) works
            raise OSError("disk full")
        real(cfg)
    monkeypatch.setattr(main_window.config, "save", flaky)
    pick_char(tile, "Alice-Realm")
    tile.del_save.click()
    qtbot.waitUntil(lambda: not window._busy, timeout=20000)
    assert "disk full" in window.log.toPlainText() and "still on it although nothing was deleted" in tile.del_message.text()
    assert window.cfg["char_blacklist"] == {}                                                         # in memory it is as it was


def test_a_list_of_ignore_that_was_not_applied_survives_the_deleting(window, qtbot, stats_data, monkeypatch):
    ask(monkeypatch, True)
    tile = open_chars(window, qtbot)[0]
    add_rule(tile, "class", "Mage", excel=False)
    pick_char(tile, "Alice-Realm")                                                                    # she is the mage
    tile.del_save.click()
    wait_rebuilt(window, qtbot, lambda built: built.del_list == [] and items(built.del_char) == as_shown("Bob-Realm"))
    built = window.char_tiles[0]
    assert list_rows(built) == [["Class", "MAGE", "Page", "0"]]                                       # still there, hits nobody, and shown as it is: the data has no mage now
    assert built.pending.text() == "Changed, not applied yet." and window.cfg["char_rules"] == {}


def test_a_list_of_ignore_that_was_applied_is_not_taken_for_a_draft(window, qtbot, stats_data, monkeypatch):
    ask(monkeypatch, True)
    window.cfg["char_rules"] = {"_retail_": [MAGE_PAGE]}
    tile = open_chars(window, qtbot)[0]
    pick_char(tile, "Bob-Realm")
    tile.del_save.click()
    wait_rebuilt(window, qtbot, lambda built: built.del_list == [] and items(built.del_char) == as_shown("Alice-Realm"))
    built = window.char_tiles[0]
    assert list_rows(built) == [["Class", "Mage", "Page", "1"]] and built.pending.text() == ""


def test_while_a_slow_action_runs_the_apply_button_of_the_block_delete_does_nothing(window, qtbot, stats_data, monkeypatch):
    questions = ask(monkeypatch, True)
    tile = open_chars(window, qtbot)[0]
    pick_char(tile, "Alice-Realm")
    window.set_busy(True, "x")
    assert not tile.del_save.isEnabled()
    window._del_apply(tile)                                                                           # even called directly: nothing
    window.set_busy(False)
    assert questions == [] and scans_in_data("_retail_") == 2


def test_the_excel_export_hands_the_rules_of_every_game_version_on(window, qtbot, monkeypatch):
    from pathlib import Path
    given, shown = [], []
    monkeypatch.setattr(actions, "run_export", lambda rules=None: given.append(rules) or (True, "", Path("x.xlsx")))
    monkeypatch.setattr(window, "_exported", lambda result: shown.append(result))          # not the real one: it would open Excel
    first, second = {"type": "char", "value": "Bob-Realm", "for": ["excel"]}, {"type": "char", "value": "Other-Realm"}
    window.cfg["char_rules"] = {"_retail_": [first], "_forever_": [second]}
    window.on_export()
    qtbot.waitUntil(lambda: bool(shown) and not window._busy, timeout=10000)
    assert given == [{"_retail_": [first], "_forever_": [second]}]


def test_the_save_button_is_off_while_a_slow_action_runs(window):
    window.set_busy(True, "x")
    assert not window.btn_top5.isEnabled()
    window.set_busy(False)
    assert window.btn_top5.isEnabled()


def test_a_typed_part_of_a_name_is_taken_when_it_fits_one_entry_and_the_box_then_shows_the_whole_entry(window, qtbot, stats_data):
    open_top5(window, qtbot)
    first, second = window.tile_rows[0], window.tile_rows[1]
    first.stat.setCurrentText("quests don")                                              # typed, no entry of the list chosen
    second.stat.setCurrentText("GOLD EARNED (wealth)")                                   # the whole name in another case
    window.btn_top5.click()
    assert window.cfg["top5"] == {"_retail_": [{"stat": 3, "agg": "sum", "by": "all", "value": ""}, {"stat": 2, "agg": "sum", "by": "all", "value": ""}]}
    assert first.stat.currentText() == "Quests done (Quests)" and second.stat.currentText() == GOLD_LABEL
    assert window.lbl_top5.text() == "Top 5 saved (_retail_): 2 tiles."
    qtbot.waitUntil(lambda: not window._busy, timeout=20000)


def test_a_typed_text_that_fits_several_entries_or_none_is_not_guessed(window, qtbot, stats_data):
    open_top5(window, qtbot)
    window.tile_rows[0].stat.setCurrentText("e")                                         # fits many
    window.tile_rows[1].stat.setCurrentText("zzzz")                                      # fits none
    pick(window.tile_rows[2].stat, GOLD_LABEL)
    window.btn_top5.click()
    assert window.cfg["top5"] == {"_retail_": [{"stat": 2, "agg": "sum", "by": "all", "value": ""}]}
    assert "row 1" in window.lbl_top5.text() and "row 2" in window.lbl_top5.text() and "row 3" not in window.lbl_top5.text()
    qtbot.waitUntil(lambda: not window._busy, timeout=20000)


def test_the_choice_of_a_row_is_a_search_box_too_and_a_text_that_fits_nothing_is_reported(window, qtbot, stats_data):
    open_top5(window, qtbot)
    row = window.tile_rows[0]
    pick(row.stat, GOLD_LABEL)
    pick(row.scope, "Class")
    assert row.value.isEditable() and row.value.completer().filterMode() == Qt.MatchFlag.MatchContains
    row.value.setCurrentText("mag")
    window.btn_top5.click()
    assert window.cfg["top5"] == {"_retail_": [{"stat": 2, "agg": "sum", "by": "class", "value": "MAGE"}]} and row.value.currentText() == "Mage"
    qtbot.waitUntil(lambda: not window._busy, timeout=20000)
    row.value.setCurrentText("warlock")
    window.btn_top5.click()
    assert window.cfg["top5"] == {} and "Top 5, row 1: the choice does not fit exactly one entry" in window.lbl_top5.text()
    qtbot.waitUntil(lambda: not window._busy, timeout=20000)


def test_a_part_of_a_name_becomes_the_whole_entry_when_enter_is_pressed_or_the_box_is_left(window, qtbot, stats_data):
    open_top5(window, qtbot)
    row = window.tile_rows[0]
    row.stat.setCurrentText("quests don")
    row.stat.lineEdit().editingFinished.emit()                                           # Enter, or the box loses the focus
    assert row.stat.currentText() == "Quests done (Quests)" and row.stat.currentData() == 3
    row.stat.setCurrentText("e")                                                         # fits many: nothing is chosen for the person
    row.stat.lineEdit().editingFinished.emit()
    assert row.stat.currentText() == "e"
    row.stat.setCurrentText("")
    row.stat.lineEdit().editingFinished.emit()
    assert row.stat.currentText() == ""


def test_typing_in_a_search_box_leaves_the_text_alone_and_the_list_is_a_popup_list(window, qtbot, stats_data):
    """The "inline" completion of a combo box pasted the whole entry behind what was typed ("eis" + "Reisen ausgegebenes Gold ...") and the row was lost."""
    from PyQt6.QtTest import QTest
    from PyQt6.QtWidgets import QCompleter
    open_top5(window, qtbot)
    for combo in (window.tile_rows[0].stat, window.tile_rows[0].value):
        assert combo.completer().completionMode() == QCompleter.CompletionMode.PopupCompletion
    line = window.tile_rows[1].stat.lineEdit()
    line.clear()
    QTest.keyClicks(line, "quests")
    assert line.text() == "quests" and not line.hasSelectedText()
    pick(window.tile_rows[1].scope, "Class")
    value = window.tile_rows[1].value.lineEdit()
    value.clear()
    QTest.keyClicks(value, "mag")
    assert value.text() == "mag" and not value.hasSelectedText()
    window.tile_rows[1].stat.lineEdit().editingFinished.emit()
    assert window.tile_rows[1].stat.currentData() == 3


def test_the_list_under_the_statistic_shows_the_name_and_below_it_the_category(window, qtbot, stats_data):
    from app.suggest_list import SuggestionDelegate
    open_top5(window, qtbot)
    row = window.tile_rows[0]
    popup = row.stat.completer().popup()
    assert isinstance(popup.itemDelegate(), SuggestionDelegate) and not isinstance(row.value.completer().popup().itemDelegate(), SuggestionDelegate)
    index = row.stat.findText(GOLD_LABEL)
    assert row.stat.itemData(index, SuggestionDelegate.NAME) == "Gold earned" and row.stat.itemData(index, SuggestionDelegate.DETAIL) == "Wealth"
    assert row.stat.itemData(0, SuggestionDelegate.NAME) is None                                  # "none" is a plain text


def test_a_click_into_the_choice_opens_the_list_with_every_entry_and_typing_narrows_it(window, qtbot, stats_data):
    from PyQt6.QtTest import QTest
    open_top5(window, qtbot)
    row = window.tile_rows[0]
    pick(row.scope, "Class")
    popup = row.value.completer().popup()
    assert not popup.isVisible()
    QTest.mouseClick(row.value.lineEdit(), Qt.MouseButton.LeftButton)
    qtbot.waitUntil(popup.isVisible, timeout=5000)
    assert popup.model().rowCount() == 2 == row.value.count()                              # Druid, Mage: the whole list although a name is shown
    popup.hide()
    row.value.lineEdit().clear()
    QTest.keyClicks(row.value.lineEdit(), "mag")
    qtbot.waitUntil(lambda: popup.isVisible() and popup.model().rowCount() == 1, timeout=5000)
    popup.hide()


def test_a_click_into_the_statistic_does_not_open_a_list_of_hundreds(window, qtbot, stats_data):
    from PyQt6.QtTest import QTest
    open_top5(window, qtbot)
    popup = window.tile_rows[0].stat.completer().popup()
    popup.hide()
    QTest.mouseClick(window.tile_rows[0].stat.lineEdit(), Qt.MouseButton.LeftButton)
    qtbot.wait(300)
    assert not popup.isVisible()


# ------------------------------------------------------------------------------------------------------------ closing (keep this test LAST: it closes the shared window)
def test_closing_the_window_with_the_page_tab_shown_raises_nothing(window, env, qtbot):
    """The sub tabs are destroyed while they are still in the tab widget: that must not call a method of a half destroyed tab (found by hand, 2026-11-10)."""
    from PyQt6.QtCore import QCoreApplication, QEvent
    window.cfg["enabled_variants"] = ["_retail_", "_forever_"]
    window.refresh_variants()
    window.tabs.setCurrentIndex(main_window.TAB_PAGE)
    with qtbot.capture_exceptions() as exceptions:
        env.win.close()
        for _ in range(10):
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            qtbot.wait(20)
    assert exceptions == []
