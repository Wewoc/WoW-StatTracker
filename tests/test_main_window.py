# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)
# The real Qt main window in a temporary instance, without a screen (QT_QPA_PLATFORM=offscreen, set in conftest).
# One window is shared by the tests of this module (the embedded browser is slow to start); `window` resets it.
# What the window does is tested in test_actions.py; here only that it shows and wires it correctly. The look and the
# JavaScript of the pages are checked by hand.

import shutil
import threading
import time
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
    w.cfg.update(language="en", enabled_variants=["_retail_"], read_icons=True, check_updates=False, active_theme=1, group_presets=[], top5=[])
    w._tile_choices, w._tile_key = None, None
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


def wait_idle(qtbot, window):
    qtbot.waitUntil(lambda: not window._busy, timeout=10000)


# ----------------------------------------------------------------- what the window shows
def test_default_shows_retail_only(window):
    assert items(window.cmb_var) == ["_retail_"]
    assert window.cmb_var.currentText() == "_retail_" and window.cmb_acc.currentText() == "ACC1"
    assert "Addon: not installed" in window.status_text()
    assert [window.tabs.tabText(i) for i in range(window.tabs.count())] == ["Settings", "Page", "Top 5"]


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
    assert f"Addon: version {app_info.APP_VERSION}" in window.status_text()
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
    assert [window.tabs.tabText(i) for i in range(window.tabs.count())] == ["Einstellungen", "Seite", "Top 5"]
    assert window.action_buttons[1].text() == "2. Daten einlesen"
    window.cmb_lang.setCurrentIndex(window.cmb_lang.findData("en"))
    window.on_language()
    assert window.action_buttons[1].text() == "2. Read data"


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


# ------------------------------------------------------------------------------ the page
def _page_file():
    return wow_install.out_files("_retail_")[1]


def test_without_a_page_the_tab_shows_the_hint(window):
    window.load_page()
    assert window.stack.currentWidget() is window.placeholder
    assert "no stats page" in window.placeholder.text()


def test_open_without_a_page_says_so_and_stays_on_the_settings_tab(window, monkeypatch):
    shown = []
    monkeypatch.setattr(dialogs, "info", lambda parent, text: shown.append(text))
    window.on_open()
    assert shown and window.tabs.currentIndex() == main_window.TAB_SETTINGS


def test_open_shows_the_page_in_the_page_tab_and_runs_its_script(window, qtbot):
    page = _page_file()
    page.parent.mkdir(parents=True, exist_ok=True)
    page.write_text("<html><body><script>document.title = 'page ' + (1 + 1);</script></body></html>", encoding="utf-8")
    try:
        window.on_open()
        assert window.tabs.currentIndex() == main_window.TAB_PAGE and window.stack.currentWidget() is window.view
        qtbot.waitUntil(lambda: window.view.title() == "page 2", timeout=15000)
    finally:
        page.unlink(missing_ok=True)


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
    page = window._page
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
        window._page_url = ""
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
    window.cfg["top5"] = [{"stat": 2, "agg": "sum", "by": "all", "value": ""}]
    shown = []
    monkeypatch.setattr(main_window.dialogs, "info", lambda _parent, text: shown.append(text))
    window.tabs.setCurrentIndex(main_window.TAB_TOP5)
    wait_idle(qtbot, window)
    assert "no data for this game version" in window.lbl_top5.text() and window._tile_choices is None
    window.btn_top5.click()
    assert shown == ["There is no data for this game version yet. Read the data first."]
    assert window.cfg["top5"] == [{"stat": 2, "agg": "sum", "by": "all", "value": ""}]       # not cleared by a tab that offered nothing


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
    assert items(row.value) == ["Alice-Realm", "Bob-Realm"]                       # nothing of the class that was chosen before stays in the list
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
    assert window.cfg["top5"] == wanted and config.load()[0]["top5"] == wanted
    qtbot.waitUntil(lambda: 'id="top5"' in page.read_text(encoding="utf-8") and not window._busy, timeout=20000)
    text = page.read_text(encoding="utf-8")
    block = text.split('id="top5"')[1].split('<div data-slot="1">')[0]
    assert "Gold earned" in block and "Class: Mage" in block and "12.05" in block and "Quests done" in block
    log = window.log.toPlainText()
    assert "Top 5 saved: 2 tiles." in log and "Page written again" in log


def test_a_row_whose_statistic_is_not_in_the_list_stays_empty_and_is_reported(window, qtbot, stats_data):
    open_top5(window, qtbot)
    pick(window.tile_rows[0].stat, GOLD_LABEL)
    window.tile_rows[1].stat.setCurrentText("not a statistic")
    window.btn_top5.click()
    assert window.cfg["top5"] == [{"stat": 2, "agg": "sum", "by": "all", "value": ""}]
    assert "Top 5, row 2: the statistic does not fit exactly one entry" in window.log.toPlainText()
    assert "Top 5 saved: 1 tiles. Top 5, row 2:" in window.lbl_top5.text()                 # said on the tab itself, where the person is looking
    qtbot.waitUntil(lambda: not window._busy, timeout=20000)


def test_tiles_of_the_settings_are_shown_in_the_rows_and_one_that_names_something_missing_is_kept(window, qtbot, stats_data):
    window.cfg["top5"] = [{"stat": 2, "agg": "avg", "by": "char", "value": "Bob-Realm"}, {"stat": 999, "agg": "max", "by": "class", "value": "WARLOCK"}]
    open_top5(window, qtbot)
    first, second = window.tile_rows[:2]
    assert (first.stat.currentText(), first.agg.currentData(), first.scope.currentData(), first.value.currentData()) == (GOLD_LABEL, "avg", "char", "Bob-Realm")
    assert (second.stat.currentText(), second.stat.currentData(), second.scope.currentData(), second.value.currentData()) == ("#999", 999, "class", "WARLOCK")
    assert window.tile_rows[2].stat.currentText() == "– none –" and not window.tile_rows[2].value.isEnabled()
    window.btn_top5.click()
    assert window.cfg["top5"][1] == {"stat": 999, "agg": "max", "by": "class", "value": "WARLOCK"}        # saving does not lose what the data lacks
    qtbot.waitUntil(lambda: not window._busy, timeout=20000)


def test_the_choices_are_read_again_only_when_the_data_the_game_version_or_the_language_changed(window, qtbot, stats_data, monkeypatch):
    calls = []
    real = main_window.actions.tile_choices
    monkeypatch.setattr(main_window.actions, "tile_choices", lambda variant: calls.append(variant) or real(variant))
    open_top5(window, qtbot)
    window.tabs.setCurrentIndex(main_window.TAB_SETTINGS)
    window.tabs.setCurrentIndex(main_window.TAB_TOP5)
    assert calls == ["_retail_"]
    window._tile_key = None                                                        # as after an import
    window.tabs.setCurrentIndex(main_window.TAB_SETTINGS)
    window.tabs.setCurrentIndex(main_window.TAB_TOP5)
    qtbot.waitUntil(lambda: len(calls) == 2 and not window._busy, timeout=20000)


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
    assert window.cfg["top5"] == [{"stat": 3, "agg": "sum", "by": "all", "value": ""}, {"stat": 2, "agg": "sum", "by": "all", "value": ""}]
    assert first.stat.currentText() == "Quests done (Quests)" and second.stat.currentText() == GOLD_LABEL
    assert window.lbl_top5.text() == "Top 5 saved: 2 tiles."
    qtbot.waitUntil(lambda: not window._busy, timeout=20000)


def test_a_typed_text_that_fits_several_entries_or_none_is_not_guessed(window, qtbot, stats_data):
    open_top5(window, qtbot)
    window.tile_rows[0].stat.setCurrentText("e")                                         # fits many
    window.tile_rows[1].stat.setCurrentText("zzzz")                                      # fits none
    pick(window.tile_rows[2].stat, GOLD_LABEL)
    window.btn_top5.click()
    assert window.cfg["top5"] == [{"stat": 2, "agg": "sum", "by": "all", "value": ""}]
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
    assert window.cfg["top5"] == [{"stat": 2, "agg": "sum", "by": "class", "value": "MAGE"}] and row.value.currentText() == "Mage"
    qtbot.waitUntil(lambda: not window._busy, timeout=20000)
    row.value.setCurrentText("warlock")
    window.btn_top5.click()
    assert window.cfg["top5"] == [] and "Top 5, row 1: the choice does not fit exactly one entry" in window.lbl_top5.text()
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
