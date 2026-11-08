#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)
# main_window.py
# StatTracker - the main window (Qt): four tabs, a status bar, nothing else. "Settings" holds the game folder, version and
# account, the actions (install / uninstall the addon, read the data, open the page, Excel), the options, the design and
# the log; "Page" shows the stats page in the window (QWebEngineView); "Top 5" sets the tiles at the top of the page; "Characters" sets which
# characters the page, the history pages and the Excel file leave out (the rules are in rules/char_rules.py). The status bar shows what is going on and the state
# of the game folder, the data and the addon. The window only shows: what it does is in actions.py (the slow parts run in
# a thread, the result comes back to the window through the `dispatch` signal). Replaces the Tk window.

import html
import os
import threading
import webbrowser
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from PyQt6.QtCore import QTimer, QUrl, Qt, pyqtSignal
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWebChannel import QWebChannel
from PyQt6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile, QWebEngineScript
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWidgets import (QAbstractItemView, QApplication, QCheckBox, QComboBox, QCompleter, QFileDialog, QGridLayout, QGroupBox,
                             QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMainWindow, QPlainTextEdit, QPushButton, QScrollArea, QSpinBox,
                             QStackedWidget, QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget)

from app import actions, dialogs, page_bridge, qt_style
from app.suggest_list import ShowAllOnClick, SuggestionDelegate
from app.qwebengine_hardening import harden
from core import app_info, config, i18n, paths, theme, updater
from core.i18n import t
from game import wow_install
from rules import char_rules
from store import db_backup

TAB_SETTINGS, TAB_PAGE, TAB_TOP5, TAB_CHARS = 0, 1, 2, 3
LOCAL_SCHEMES = ("file", "about", "data", "blob", "qrc")


class StatPage(QWebEnginePage):
    """The page of the view: it follows links between the local pages (the history pages link to the stats page and back),
    sends a link to the internet to the browser of the system, and opens no windows of its own."""

    def acceptNavigationRequest(self, url, nav_type, is_main_frame):
        scheme = url.scheme()
        if scheme in LOCAL_SCHEMES:
            return True
        if scheme in ("http", "https"):
            QDesktopServices.openUrl(url)
        return False

    def createWindow(self, _type):
        return None


class MainWindow(QMainWindow):
    dispatch = pyqtSignal(object)          # runs a callable on the GUI thread (used by the worker threads)

    def __init__(self):
        super().__init__()
        self.cfg, warning = config.load()
        i18n.set_language(self.cfg["language"])
        self.colors = theme.colors(self.cfg["active_theme"])
        QApplication.instance().setStyleSheet(qt_style.stylesheet(self.colors, theme.readable_accent(self.colors)))
        self._log_lines = []             # [(line, tag)]: the log keeps its lines when the language changes
        self._texts = []                 # (widget, method, key): the texts that follow a language switch
        self._update_open = False        # update dialog open or update under way: no second dialog or download
        self._busy = False               # a slow action runs: the action buttons are off
        self._refreshing = False         # a drop-down is being filled: its change signals are not user choices
        self._page_url = ""
        self._tile_choices = None        # what the Top 5 tab offers (actions.tile_choices) and for which data it was read
        self._tile_key = None
        self._chars_key = None           # for which data, game versions and language the Characters tab was built (None: build it again)
        self._chars_buttons = []         # the apply buttons of the blocks of the Characters tab (they are also in action_buttons and go with the blocks)
        self._chars_drafts = {}          # {game version: draft of its block "Ignore"} that the next build of the blocks keeps (after deleting characters)
        self._chars_notes = {}           # {game version: text} that the next build of the blocks shows in its block "Delete"
        self.dispatch.connect(lambda fn: fn())

        self.setMinimumSize(920, 640)
        self.resize(1180, 820)
        self._build()
        self.ed_wow.setText(self.cfg["wow_dir"] or wow_install.guess_wow_dir())
        self.refresh_variants(keep=self.cfg["variant"])
        self.retranslate()
        self.status_message(t("status_ready"))
        if warning:
            self.write(t("warn_config_broken", detail=warning), "err")
        if self.cfg["check_updates"]:
            QTimer.singleShot(1500, lambda: self.check_updates(manual=False))

    # ------------------------------------------------------------ construction
    def _text(self, widget, method, key):
        """Registers a text for the language switch (retranslate) and sets it now."""
        self._texts.append((widget, method, key))
        getattr(widget, method)(t(key))
        return widget

    def _build(self):
        self.tabs = QTabWidget()
        self.setCentralWidget(self.tabs)
        self.tabs.addTab(self._build_settings_tab(), "")
        self.tabs.addTab(self._build_page_tab(), "")
        self.tabs.addTab(self._build_top5_tab(), "")
        self.tabs.addTab(self._build_chars_tab(), "")
        self.tabs.currentChanged.connect(self._tab_changed)
        self.lbl_status = QLabel()
        self.lbl_status.setObjectName("status")
        self.statusBar().addPermanentWidget(self.lbl_status)

    def _build_settings_tab(self):
        tab = QWidget()
        lay = QVBoxLayout(tab)
        lay.setContentsMargins(12, 10, 12, 8)

        head = QHBoxLayout()
        title = QLabel(app_info.APP_NAME)
        title.setObjectName("title")
        head.addWidget(title)
        head.addStretch()
        head.addWidget(self._text(QLabel(), "setText", "lbl_language"))
        self.cmb_lang = QComboBox()
        for code, name in i18n.LANGUAGES.items():
            self.cmb_lang.addItem(name, code)
        self.cmb_lang.setCurrentIndex(self.cmb_lang.findData(self.cfg["language"]))
        self.cmb_lang.activated.connect(lambda _i: self.on_language())
        head.addWidget(self.cmb_lang)
        lay.addLayout(head)

        top = QHBoxLayout()
        top.addWidget(self._build_game_group(), 3)
        top.addWidget(self._build_options_group(), 2)
        lay.addLayout(top)
        lay.addWidget(self._build_actions_group())
        lay.addLayout(self._build_log())
        lay.addLayout(self._build_footer())
        return tab

    def _build_game_group(self):
        box = QGroupBox()
        self._text(box, "setTitle", "grp_game")
        grid = QGridLayout(box)
        grid.setColumnStretch(1, 1)
        grid.addWidget(self._text(QLabel(), "setText", "lbl_wow_folder"), 0, 0)
        self.ed_wow = QLineEdit()
        self.ed_wow.textChanged.connect(lambda _t: self.refresh_variants())
        grid.addWidget(self.ed_wow, 0, 1)
        grid.addWidget(self._text(QPushButton(), "setText", "btn_browse"), 0, 2)
        self._browse = grid.itemAtPosition(0, 2).widget()
        self._browse.clicked.connect(self.browse_wow)
        grid.addWidget(self._text(QLabel(), "setText", "lbl_variant"), 1, 0)
        self.cmb_var = QComboBox()
        self.cmb_var.currentTextChanged.connect(lambda _t: None if self._refreshing else self.refresh_accounts())
        grid.addWidget(self.cmb_var, 1, 1)
        grid.addWidget(self._text(QLabel(), "setText", "lbl_account"), 2, 0)
        self.cmb_acc = QComboBox()
        self.cmb_acc.currentTextChanged.connect(lambda _t: None if self._refreshing else self.update_status())
        grid.addWidget(self.cmb_acc, 2, 1)
        reload_btn = self._text(QPushButton(), "setText", "btn_reload")
        reload_btn.clicked.connect(lambda: self.refresh_variants(keep=self.cmb_var.currentText()))
        grid.addWidget(reload_btn, 2, 2)
        return box

    def _build_options_group(self):
        box = QGroupBox()
        self._text(box, "setTitle", "grp_options")
        lay = QVBoxLayout(box)
        lay.addWidget(self._text(QLabel(), "setText", "settings_variants"))
        notice = self._text(QLabel(), "setText", "settings_variants_hint")
        notice.setObjectName("notice")
        notice.setWordWrap(True)
        lay.addWidget(notice)
        self.variant_boxes = QVBoxLayout()
        lay.addLayout(self.variant_boxes)
        self.chk_updates = self._text(QCheckBox(), "setText", "settings_check_updates")
        self.chk_updates.setChecked(self.cfg["check_updates"])
        self.chk_updates.toggled.connect(self.on_options)
        lay.addWidget(self.chk_updates)
        self.chk_icons = self._text(QCheckBox(), "setText", "settings_read_icons")
        self.chk_icons.setChecked(self.cfg["read_icons"])
        self.chk_icons.toggled.connect(self.on_options)
        lay.addWidget(self.chk_icons)
        icons_hint = self._text(QLabel(), "setText", "settings_read_icons_hint")
        icons_hint.setObjectName("hint")
        icons_hint.setWordWrap(True)
        lay.addWidget(icons_hint)
        row = QHBoxLayout()
        row.addWidget(self._text(QLabel(), "setText", "lbl_theme"))
        self.cmb_theme = QComboBox()
        for number, name in theme.names().items():
            self.cmb_theme.addItem(name, number)
        self.cmb_theme.setCurrentIndex(max(0, self.cmb_theme.findData(self.cfg["active_theme"])))
        self.cmb_theme.activated.connect(lambda _i: self.on_theme())
        row.addWidget(self.cmb_theme, 1)
        lay.addLayout(row)
        return box

    def _build_top5_tab(self):
        """The five rows of the Top 5 tiles (the tiles themselves are written by pages/blocks/top5.py): statistic, how the value is combined, for whom."""
        tab = QWidget()
        lay = QVBoxLayout(tab)
        lay.setContentsMargins(12, 10, 12, 8)
        intro = self._text(QLabel(), "setText", "top5_intro")
        intro.setObjectName("hint")
        intro.setWordWrap(True)
        lay.addWidget(intro)
        box = QGroupBox()
        self._text(box, "setTitle", "top5_group")
        grid = QGridLayout(box)
        grid.setColumnStretch(1, 4)
        grid.setColumnStretch(4, 2)
        for column, key in ((1, "top5_col_stat"), (2, "top5_col_agg"), (3, "top5_col_scope"), (4, "top5_col_value")):
            grid.addWidget(self._text(QLabel(), "setText", key), 0, column)
        self.tile_rows = []
        for n in range(config.TOP5_MAX):
            row = SimpleNamespace(stat=self._searchable(QComboBox(), first=1, two_lines=True), agg=QComboBox(), scope=QComboBox(), value=self._searchable(QComboBox(), open_on_click=True))
            row.scope.currentIndexChanged.connect(lambda _i, number=n: self._tile_scope_changed(number))
            grid.addWidget(QLabel(str(n + 1)), n + 1, 0)
            for column, widget in enumerate((row.stat, row.agg, row.scope, row.value), start=1):
                grid.addWidget(widget, n + 1, column)
            self.tile_rows.append(row)
        lay.addWidget(box)
        bar = QHBoxLayout()
        self.btn_top5 = self._text(QPushButton(), "setText", "top5_apply")
        self.btn_top5.setObjectName("primary")
        self.btn_top5.clicked.connect(self.on_top5_apply)
        self.action_buttons.append(self.btn_top5)                    # off while a slow action runs, like the others
        bar.addWidget(self.btn_top5)
        self.lbl_top5 = QLabel()
        self.lbl_top5.setObjectName("hint")
        bar.addWidget(self.lbl_top5, 1)
        lay.addLayout(bar)
        lay.addStretch()
        self._label_tile_combos()
        return tab

    def _build_actions_group(self):
        box = QGroupBox()
        self._text(box, "setTitle", "grp_actions")
        row = QHBoxLayout(box)
        self.action_buttons = []
        for key, handler, primary in (("btn_install", self.on_install, False), ("btn_parse", self.on_parse, False),
                                      ("btn_open", self.on_open, False), ("btn_parse_open", self.on_parse_open, True),
                                      ("btn_export", self.on_export, False), ("btn_uninstall", self.on_uninstall, False)):
            button = self._text(QPushButton(), "setText", key)
            if primary:
                button.setObjectName("primary")
            button.clicked.connect(lambda _checked=False, h=handler: h())
            self.action_buttons.append(button)
            row.addWidget(button)
        return box

    def _build_log(self):
        lay = QVBoxLayout()
        bar = QHBoxLayout()
        bar.addWidget(self._text(QLabel(), "setText", "log_title"))
        bar.addStretch()
        clear = self._text(QPushButton(), "setText", "btn_clear_log")
        clear.setObjectName("link")
        clear.setCursor(Qt.CursorShape.PointingHandCursor)
        clear.clicked.connect(self.clear_log)
        bar.addWidget(clear)
        lay.addLayout(bar)
        self.log = QPlainTextEdit()
        self.log.setObjectName("log")
        self.log.setReadOnly(True)
        self.log.setMinimumHeight(140)
        lay.addWidget(self.log, 1)
        return lay

    def _build_footer(self):
        row = QHBoxLayout()
        self.lbl_footer = QLabel()
        self.lbl_footer.setOpenExternalLinks(True)
        row.addWidget(self.lbl_footer)
        row.addStretch()
        about = self._text(QPushButton(), "setText", "btn_about")
        about.clicked.connect(self.on_about)
        row.addWidget(about)
        check = self._text(QPushButton(), "setText", "btn_check_updates")
        check.clicked.connect(lambda: self.check_updates(manual=True))
        row.addWidget(check)
        return row

    def _build_page_tab(self):
        tab = QWidget()
        lay = QVBoxLayout(tab)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        bar = QHBoxLayout()
        bar.setContentsMargins(8, 4, 8, 4)
        reload_btn = self._text(QPushButton(), "setText", "btn_reload")
        reload_btn.clicked.connect(lambda: self.load_page(force=True))
        bar.addWidget(reload_btn)
        browser = self._text(QPushButton(), "setText", "btn_open_browser")
        browser.clicked.connect(self.open_in_browser)
        bar.addWidget(browser)
        bar.addStretch()
        lay.addLayout(bar)
        self.stack = QStackedWidget()
        self.placeholder = QLabel()
        self.placeholder.setObjectName("placeholder")
        self.placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.placeholder.setWordWrap(True)
        self._text(self.placeholder, "setText", "page_missing")
        self.stack.addWidget(self.placeholder)
        self._profile = QWebEngineProfile("StatTracker")       # keeps its storage (what a page keeps in the browser) in data/
        storage = paths.data_dir() / "webview"
        self._profile.setPersistentStoragePath(str(storage))
        self._profile.setCachePath(str(storage / "cache"))
        self._profile.downloadRequested.connect(self._download)
        self.view = QWebEngineView()
        self._page = StatPage(self._profile, self.view)
        self.view.setPage(self._page)
        harden(self.view)
        self._page.scripts().insert(self._colour_script())
        self._bridge = page_bridge.PageBridge(page_bridge.ConfigPresets(self.cfg), self)      # the blocks of the page that Python writes
        self._channel = QWebChannel(self)
        self._channel.registerObject("bridge", self._bridge)
        self._page.setWebChannel(self._channel)
        channel_script = self._channel_script()
        if channel_script is not None:
            self._page.scripts().insert(channel_script)
        self.stack.addWidget(self.view)
        lay.addWidget(self.stack, 1)
        return tab

    def _channel_script(self):
        """The script of Qt that lets a page talk to the bridge (qwebchannel.js), or None when it cannot be read: the page then
        stays as it was written (its controls are disabled)."""
        source = page_bridge.channel_script_source()
        if not source:
            return None
        script = QWebEngineScript()
        script.setName("statTrackerChannel")
        script.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentCreation)
        script.setWorldId(QWebEngineScript.ScriptWorldId.MainWorld)
        script.setRunsOnSubFrames(False)
        script.setSourceCode(source)
        return script

    def _colour_script(self):
        """The script that gives the pages the colours of the chosen scheme (see qt_style.page_script)."""
        script = QWebEngineScript()
        script.setName("statTrackerColours")
        script.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentCreation)
        script.setWorldId(QWebEngineScript.ScriptWorldId.MainWorld)
        script.setRunsOnSubFrames(False)
        script.setSourceCode(qt_style.page_script(theme.page_variables(self.cfg["active_theme"])))
        return script

    def retranslate(self):
        """Sets every text again in the current language (language switch, start)."""
        self.setWindowTitle(t("window_title"))
        for widget, method, key in self._texts:
            getattr(widget, method)(t(key))
        self.tabs.setTabText(TAB_SETTINGS, t("tab_settings"))
        self.tabs.setTabText(TAB_TOP5, t("tab_top5"))
        self.tabs.setTabText(TAB_PAGE, t("tab_page"))
        self.tabs.setTabText(TAB_CHARS, t("tab_chars"))
        self._label_tile_combos()
        self._tile_key = None                      # the names of the choices are in the language of the program: read them again when the tab is shown
        self._chars_key = None
        self._tab_changed(self.tabs.currentIndex())
        repo = app_info.REPO_URL
        self.lbl_footer.setText(
            f"{html.escape(t('footer_version', version=app_info.APP_VERSION))} &nbsp;·&nbsp; "
            f"<a style='color:{self.colors['accent']}' href='{repo}'>{html.escape(repo.replace('https://', ''))}</a>"
            f" &nbsp;·&nbsp; {html.escape(app_info.COPYRIGHT)} &nbsp;·&nbsp; {html.escape(app_info.LICENSE_NAME)}")
        self.update_status()

    # ----------------------------------------------------------------- the Top 5 tab
    def _searchable(self, combo, first=0, two_lines=False, open_on_click=False):
        """A drop-down in which one types a part of the name: a list under the box shows every entry that contains it (not the "inline" completion of a
        combo box, which pasted the whole entry behind what was typed), and with Enter or when the box is left a text that fits exactly one entry becomes that
        whole entry (`first`: the entries before it, like "none", are no choice). `two_lines`: the list shows name and category apart (suggest_list).
        `open_on_click`: a click into the box opens the list with every entry (for a box with a few choices, which would show no list until one types)."""
        combo.setEditable(True)
        combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        completer = combo.completer()
        completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        completer.setFilterMode(Qt.MatchFlag.MatchContains)
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        completer.setMaxVisibleItems(10)
        if two_lines:
            combo._suggestions = SuggestionDelegate(completer.popup())          # kept here: the popup does not own it
            completer.popup().setItemDelegate(combo._suggestions)
        if open_on_click:
            combo._open_on_click = ShowAllOnClick(combo)                      # kept here, like the delegate: Python must not drop it
        combo.lineEdit().editingFinished.connect(lambda: self._settle(combo, first))
        return combo

    def _settle(self, combo, first):
        index = self._resolve(combo, first)
        if index >= 0 and index != combo.currentIndex():
            combo.setCurrentIndex(index)

    @staticmethod
    def _resolve(combo, first=0):
        """The index of the entry the box means, or -1: the entry that is chosen, the entry with exactly this text (any case), or the one and only
        entry that contains the text. A text that fits several entries or none is not resolved (nothing is guessed). `first`: entries before it are no choice."""
        text = combo.currentText().strip()
        if not text:
            return -1
        current = combo.currentIndex()
        if current >= first and combo.itemText(current) == text:
            return current
        exact = [i for i in range(first, combo.count()) if combo.itemText(i).casefold() == text.casefold()]
        if len(exact) == 1:
            return exact[0]
        found = [i for i in range(first, combo.count()) if text.casefold() in combo.itemText(i).casefold()]
        return found[0] if len(found) == 1 and not exact else -1

    def _label_tile_combos(self):
        """The names in the drop-downs for the function and the scope, in the language of the program (the choice stays)."""
        aggs = (("sum", t("html_groups_agg_sum")), ("avg", t("html_groups_agg_avg")), ("max", t("html_groups_agg_max")))
        scopes = (("all", t("html_top5_all")), ("class", t("html_groups_by_class")), ("race", t("html_groups_by_race")),
                  ("faction", t("html_groups_by_faction")), ("realm", t("html_groups_by_realm")), ("char", t("top5_scope_char")))
        for row in self.tile_rows:
            for combo, items in ((row.agg, aggs), (row.scope, scopes)):
                keep = combo.currentData()
                combo.blockSignals(True)
                combo.clear()
                for data, label in items:
                    combo.addItem(label, data)
                combo.setCurrentIndex(max(0, combo.findData(keep)))
                combo.blockSignals(False)

    def _tile_scope_changed(self, number, keep=None):
        """Fills the drop-down of the choice (which class, race, ... or character) for the scope of a row; `keep` is the value of a tile to show (None: the
        first one, as when a person chooses another scope: what was chosen for the old scope means nothing for the new one)."""
        row = self.tile_rows[number]
        by = row.scope.currentData()
        offered = (self._tile_choices or {}).get("values", {}).get(by, []) if by != "all" else []
        row.value.blockSignals(True)
        row.value.clear()
        for value, label in offered:
            row.value.addItem(label, value)
        index = row.value.findData(keep) if keep is not None else -1
        if index < 0 and keep and by != "all":                           # a tile that names something this data does not have (any more) keeps it
            row.value.addItem(keep, keep)
            index = row.value.count() - 1
        row.value.setCurrentIndex(max(0, index))
        row.value.setEnabled(by != "all" and row.value.count() > 0)
        row.value.blockSignals(False)

    def _show_tiles(self, tiles):
        """Puts the tiles of the settings into the rows (a row without a tile is empty)."""
        for number, row in enumerate(self.tile_rows):
            tile = tiles[number] if number < len(tiles) else None
            row.stat.setCurrentIndex(0)
            if tile is None:
                row.agg.setCurrentIndex(0)
                row.scope.blockSignals(True)
                row.scope.setCurrentIndex(0)
                row.scope.blockSignals(False)
                self._tile_scope_changed(number)
                continue
            index = row.stat.findData(tile["stat"])
            if index < 0:                                                 # a statistic this data does not have (any more): shown by its number, kept
                row.stat.addItem(f"#{tile['stat']}", tile["stat"])
                index = row.stat.count() - 1
            row.stat.setCurrentIndex(index)
            row.agg.setCurrentIndex(max(0, row.agg.findData(tile["agg"])))
            row.scope.blockSignals(True)
            row.scope.setCurrentIndex(max(0, row.scope.findData(tile["by"])))
            row.scope.blockSignals(False)
            self._tile_scope_changed(number, keep=tile["value"])

    def _tab_changed(self, index):
        """Reads what the Top 5 tab or the Characters tab offers (in a thread) the first time it is shown and whenever the data, the game version or the
        language changed."""
        if index == TAB_CHARS:
            self._chars_load()
            return
        if index != TAB_TOP5 or self._busy:
            return
        _root, variant = self.root_and_variant()
        if not variant:
            self.lbl_top5.setText(t("top5_no_data"))
            return
        db_path = wow_install.out_files(variant)[0]
        key = (variant, db_path.stat().st_mtime_ns if db_path.is_file() else None, i18n.get_language())
        if key == self._tile_key:
            return

        rules = list(self.cfg["char_rules"].get(variant, []))

        def work():
            try:
                return actions.tile_choices(variant, rules)
            except (SystemExit, Exception) as exc:                        # a database newer than this program, or a broken one: say it, do not hang
                return exc
        self.run_in_thread(work, lambda result: self._tile_choices_loaded(result, key), t("status_busy_choices"))

    def _tile_choices_loaded(self, result, key):
        failed = isinstance(result, BaseException)
        if failed:
            self.write(str(result.code if isinstance(result, SystemExit) else f"{type(result).__name__}: {result}"), "err")
        self._tile_choices = None if (failed or result is None) else result
        self._tile_key = None if self._tile_choices is None else key
        self.lbl_top5.setText(t("top5_no_data") if self._tile_choices is None else "")
        stats = (self._tile_choices or {}).get("stats", [])
        for row in self.tile_rows:
            row.stat.blockSignals(True)
            row.stat.clear()
            row.stat.addItem(t("top5_none"), None)
            for stat_id, label in stats:
                row.stat.addItem(label, stat_id)
                name, category = (self._tile_choices or {}).get("parts", {}).get(stat_id, (None, ""))
                if name is not None:                                      # the list under the box shows the name and, below it, the category
                    row.stat.setItemData(row.stat.count() - 1, name, SuggestionDelegate.NAME)
                    row.stat.setItemData(row.stat.count() - 1, category, SuggestionDelegate.DETAIL)
            row.stat.blockSignals(False)
        self._show_tiles(self.cfg["top5"])

    def _collect_tiles(self):
        """(the tiles the rows describe, [(row number, "stat" or "value")] for the rows that could not be read). A row without a statistic is skipped; a
        typed text is taken when it fits one entry (and the box then shows the whole entry), otherwise the row stays out and is reported."""
        tiles, invalid = [], []
        for number, row in enumerate(self.tile_rows, start=1):
            text = row.stat.currentText().strip()
            if not text or text == t("top5_none"):
                continue
            index = self._resolve(row.stat, first=1)
            if index < 0:
                invalid.append((number, "stat"))
                continue
            row.stat.setCurrentIndex(index)
            by = row.scope.currentData() or "all"
            value = ""
            if by != "all":
                at = self._resolve(row.value)
                if at < 0:
                    invalid.append((number, "value"))
                    continue
                row.value.setCurrentIndex(at)
                value = row.value.itemData(at) or ""
            tiles.append({"stat": row.stat.itemData(index), "agg": row.agg.currentData() or "sum", "by": by, "value": value})
        return tiles, invalid

    def on_top5_apply(self):
        """Saves the tiles in the settings and writes the page of the chosen game version again (from its database, in a thread)."""
        if self._busy:
            return
        if self._tile_choices is None:                                    # nothing was read (no data): the rows are empty, saving would clear the tiles
            dialogs.info(self, t("top5_no_data"))
            return
        tiles, invalid = self._collect_tiles()
        problems = [t("top5_row_invalid" if kind == "stat" else "top5_value_invalid", n=number) for number, kind in invalid]
        for text in problems:
            self.write(text, "err")
        self.cfg["top5"] = config.clean_top5(tiles)
        self.save()
        saved = t("log_top5_saved", count=len(self.cfg["top5"]))
        self.write(saved, "ok")
        self.lbl_top5.setText(" ".join([saved] + problems))                 # also here: the log is on the other tab
        _root, variant = self.root_and_variant()
        if not variant or not wow_install.out_files(variant)[0].is_file():
            return
        saved = list(self.cfg["top5"])
        rules = list(self.cfg["char_rules"].get(variant, []))
        self.run_in_thread(lambda: actions.rebuild_page(variant, saved, rules), self._page_rebuilt, t("status_busy_top5"))

    def _page_rebuilt(self, result, variant=None):
        """The page of `variant` (None: the chosen game version) was written again: the lines it printed, then the page in the window is loaded again."""
        ok, out = result
        for line in out.strip().splitlines():
            self.write(line, "err" if (not ok or line.startswith(("FEHLER", "WARNUNG", "ERROR", "WARNING"))) else None)
        if not ok:
            self.write(t("log_top5_page_fail"), "err")
            return
        path = wow_install.out_files(variant)[1] if variant else self.html_path()
        self.write(t("log_top5_page", path=path), "ok")
        self.load_page(force=True)

    # ----------------------------------------------------------------- the Characters tab
    CHAR_KINDS = (("class", "html_groups_by_class"), ("race", "html_groups_by_race"), ("faction", "html_groups_by_faction"),
                  ("realm", "html_groups_by_realm"), ("char", "top5_scope_char"), (char_rules.LEVEL_BELOW, "chars_kind_level"))

    def _build_chars_tab(self):
        """The Characters tab: a choice of the game version and, below it, the block "Ignore" of that version (one per enabled game version, built when the
        tab is shown, see _chars_loaded). What a rule keeps out, and how a list of rules changes, is rules/char_rules.py: the window shows and asks."""
        tab = QWidget()
        lay = QVBoxLayout(tab)
        lay.setContentsMargins(12, 10, 12, 8)
        intro = self._text(QLabel(), "setText", "chars_intro")
        intro.setObjectName("hint")
        intro.setWordWrap(True)
        lay.addWidget(intro)
        row = QHBoxLayout()
        row.addWidget(self._text(QLabel(), "setText", "chars_variant"))
        self.cmb_chars_variant = QComboBox()
        self.cmb_chars_variant.currentIndexChanged.connect(self._chars_show)
        row.addWidget(self.cmb_chars_variant)
        row.addStretch()
        lay.addLayout(row)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self.chars_stack = QStackedWidget()
        scroll.setWidget(self.chars_stack)
        lay.addWidget(scroll, 1)
        self.char_tiles = []
        return tab

    def _chars_show(self, index):
        """Shows the block of the game version that is chosen (the other blocks keep what was set in them)."""
        if 0 <= index < self.chars_stack.count():
            self.chars_stack.setCurrentIndex(index)

    def _chars_variants(self):
        """The enabled game versions, Retail first."""
        return sorted(self.cfg["enabled_variants"], key=lambda name: (name != wow_install.DEFAULT_VARIANT, name))

    def _chars_load(self):
        """Reads (in a thread) what the blocks offer, the first time the tab is shown and whenever the data, the game versions or the language changed."""
        if self._busy:
            return
        variants = self._chars_variants()
        stamps = tuple((name, path.stat().st_mtime_ns if path.is_file() else None) for name in variants for path in [wow_install.out_files(name)[0]])
        key = (stamps, i18n.get_language())
        if key == self._chars_key:
            return

        def work():
            found = {}
            for variant in variants:
                try:
                    found[variant] = actions.ignore_choices(variant)
                except (SystemExit, Exception) as exc:                        # a database newer than this program, or a broken one: say it, do not hang
                    found[variant] = exc
            return found
        self.run_in_thread(work, lambda result: self._chars_loaded(result, key), t("status_busy_chars_read"))

    def _chars_loaded(self, found, key):
        failed = False
        for result in found.values():
            if isinstance(result, BaseException):
                failed = True
                self.write(str(result.code if isinstance(result, SystemExit) else f"{type(result).__name__}: {result}"), "err")
        self._chars_key = None if failed else key             # a failed read is tried again the next time the tab is shown
        self._chars_rebuild(found)

    def _chars_rebuild(self, found):
        """Builds the blocks again: the old ones go (a list that was changed and not applied goes with them), and so do their apply buttons."""
        self.action_buttons = [button for button in self.action_buttons if button not in self._chars_buttons]
        self._chars_buttons = []
        while self.chars_stack.count():
            widget = self.chars_stack.widget(0)
            self.chars_stack.removeWidget(widget)
            widget.deleteLater()
        keep = self.cmb_chars_variant.currentText()
        self.char_tiles = []
        self.cmb_chars_variant.blockSignals(True)
        self.cmb_chars_variant.clear()
        for variant in self._chars_variants():
            tile = self._chars_tile(variant, found.get(variant))
            if variant in self._chars_drafts and tile.table is not None:     # after deleting characters: a list of "Ignore" that was not applied stays
                tile.draft = list(self._chars_drafts[variant])
                self._chars_refresh(tile)
            if variant in self._chars_notes and tile.del_message is not None:
                tile.del_message.setText(self._chars_notes[variant])
            self.char_tiles.append(tile)
            self.chars_stack.addWidget(tile.panel)
            self.cmb_chars_variant.addItem(variant)
        self.cmb_chars_variant.setCurrentIndex(max(0, self.cmb_chars_variant.findText(keep)))
        self.cmb_chars_variant.blockSignals(False)
        self._chars_show(self.cmb_chars_variant.currentIndex())
        self._chars_drafts, self._chars_notes = {}, {}

    def _chars_tile(self, variant, result):
        """The block "Ignore" of one game version: the form on top (type, value, targets, add), the list of the rules below it, the counter and "Apply".
        `result` is what actions.ignore_choices read: None = no data yet, an exception = not readable. `rules` is what is saved, `draft` the list as it stands
        now: adding and taking away change the draft, "Apply" saves it."""
        box = QGroupBox(t("chars_group", variant=variant))
        panel = QWidget()                                                  # the page of this game version in the stack: the block "Ignore", then "Delete"
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(0, 0, 0, 0)
        panel_layout.addWidget(box)
        tile = SimpleNamespace(variant=variant, box=box, panel=panel, chars=[], values={}, rules=[], draft=[], kind=None, value=None, level=None, page=None,
                               excel=None, add=None, table=None, remove=None, counter=None, pending=None, save=None, message=None,
                               del_box=None, del_char=None, del_add=None, del_table=None, del_remove=None, del_preview=None, del_message=None, del_save=None,
                               del_list=[], by_key={}, bl_table=None, bl_remove=None, bl_note=None, bl_message=None)
        lay = QVBoxLayout(box)
        if result is None or isinstance(result, BaseException):
            note = QLabel(t("top5_no_data") if result is None else t("chars_read_failed"))
            note.setObjectName("hint")
            note.setWordWrap(True)
            lay.addWidget(note)
            return tile
        tile.chars = result["chars"]
        tile.values = {kind: list(result["values"].get(kind, [])) for kind, _key in self.CHAR_KINDS if kind != char_rules.LEVEL_BELOW}
        tile.rules = list(self.cfg["char_rules"].get(variant, []))
        tile.draft = list(tile.rules)

        form = QHBoxLayout()
        form.addWidget(QLabel(t("chars_kind")))
        tile.kind = QComboBox()
        for kind, key in self.CHAR_KINDS:
            tile.kind.addItem(t(key), kind)
        form.addWidget(tile.kind)
        form.addWidget(QLabel(t("chars_value")))
        tile.value = self._searchable(QComboBox(), open_on_click=True)
        form.addWidget(tile.value, 1)
        tile.level = QSpinBox()
        tile.level.setRange(1, 999)
        tile.level.setValue(20)
        form.addWidget(tile.level)
        form.addWidget(QLabel(t("chars_for")))
        tile.page = QCheckBox(t("chars_col_page"))
        tile.page.setChecked(True)
        tile.excel = QCheckBox(t("chars_col_excel"))
        tile.excel.setChecked(True)
        form.addWidget(tile.page)
        form.addWidget(tile.excel)
        tile.add = QPushButton(t("chars_add"))
        form.addWidget(tile.add)
        lay.addLayout(form)

        lay.addWidget(QLabel(t("chars_list_title")))
        tile.table = QTableWidget(0, 5)
        tile.table.setHorizontalHeaderLabels(["", t("chars_list_kind"), t("chars_list_value"), t("chars_list_for"), t("chars_col_count")])
        tile.table.verticalHeader().setVisible(False)
        tile.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        tile.table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        header = tile.table.horizontalHeader()
        for column, mode in enumerate((QHeaderView.ResizeMode.ResizeToContents, QHeaderView.ResizeMode.ResizeToContents, QHeaderView.ResizeMode.Stretch,
                                       QHeaderView.ResizeMode.ResizeToContents, QHeaderView.ResizeMode.ResizeToContents)):
            header.setSectionResizeMode(column, mode)
        tile.table.setMinimumHeight(150)
        lay.addWidget(tile.table, 1)
        bar = QHBoxLayout()
        tile.remove = QPushButton(t("chars_remove"))
        bar.addWidget(tile.remove)
        bar.addStretch()
        lay.addLayout(bar)
        tile.counter = QLabel()
        tile.counter.setWordWrap(True)
        lay.addWidget(tile.counter)
        apply_row = QHBoxLayout()
        tile.save = QPushButton(t("chars_apply"))
        tile.save.setObjectName("primary")
        tile.save.setEnabled(not self._busy)
        self.action_buttons.append(tile.save)                              # off while a slow action runs, like the others
        self._chars_buttons.append(tile.save)
        apply_row.addWidget(tile.save)
        tile.pending = QLabel()                                            # "not applied yet" while the draft differs from what is saved
        tile.pending.setObjectName("notice")
        apply_row.addWidget(tile.pending, 1)
        lay.addLayout(apply_row)
        tile.message = QLabel()                                            # the result of the last click, on the tab itself: the log is on the other one
        tile.message.setObjectName("hint")
        tile.message.setWordWrap(True)
        lay.addWidget(tile.message)
        note = QLabel(t("chars_apply_note"))
        note.setObjectName("hint")
        note.setWordWrap(True)
        lay.addWidget(note)

        tile.kind.currentIndexChanged.connect(lambda _i, tile=tile: self._chars_kind_changed(tile))
        for check in (tile.page, tile.excel):
            check.toggled.connect(lambda _on, tile=tile: self._chars_add_state(tile))
        tile.add.clicked.connect(lambda _checked=False, tile=tile: self._chars_add(tile))
        tile.remove.clicked.connect(lambda _checked=False, tile=tile: self._chars_remove(tile))
        tile.save.clicked.connect(lambda _checked=False, tile=tile: self._chars_apply(tile))
        self._chars_kind_changed(tile)
        self._chars_add_state(tile)
        self._chars_refresh(tile)
        panel_layout.addWidget(self._chars_delete_box(tile))
        panel_layout.addStretch()
        return tile

    def _chars_kind_changed(self, tile):
        """The form for the type that is chosen: a list of the entries of the data, or a number for "level under" (the box for the value starts empty)."""
        kind = tile.kind.currentData()
        level = kind == char_rules.LEVEL_BELOW
        tile.value.setVisible(not level)
        tile.level.setVisible(level)
        tile.value.clear()
        if not level:
            for value, label in tile.values[kind]:
                tile.value.addItem(label, value)
            tile.value.setCurrentIndex(-1)
        tile.message.setText("")

    def _chars_add_state(self, tile):
        tile.add.setEnabled(tile.page.isChecked() or tile.excel.isChecked())        # a rule for no target would do nothing

    def _chars_add(self, tile):
        """Adds the rule of the form to the draft (char_rules.add_rule: the same type and value is one rule with both targets)."""
        kind = tile.kind.currentData()
        if kind == char_rules.LEVEL_BELOW:
            value = str(tile.level.value())
        else:
            index = self._resolve(tile.value)
            if index < 0:                                                  # a text that fits no entry or several: nothing is guessed
                tile.message.setText(t("chars_value_invalid"))
                return
            value = tile.value.itemData(index)
        targets = [name for name, check in (("page", tile.page), ("excel", tile.excel)) if check.isChecked()]
        tile.message.setText("")
        tile.draft = char_rules.add_rule(tile.draft, kind, value, targets)
        self._chars_refresh(tile)

    def _chars_remove(self, tile):
        """Takes the rules that are ticked in the list out of the draft."""
        marked = [row for row in range(tile.table.rowCount()) if tile.table.item(row, 0).checkState() == Qt.CheckState.Checked]
        tile.message.setText("")
        tile.draft = char_rules.remove_rules(tile.draft, marked)
        self._chars_refresh(tile)

    def _chars_label(self, tile, rule):
        """(type, value) of a rule as the list shows them, in the language of the program; what the data does not know is shown as it is."""
        kind, value = rule.get("type"), rule.get("value")
        names = dict(self.CHAR_KINDS)
        kind_text = t(names[kind]) if kind in names else str(kind)
        if kind in tile.values:
            value_text = dict(tile.values[kind]).get(value, t("html_groups_unknown") if value == "" else str(value))
        else:
            value_text = str(value)
        return kind_text, value_text

    def _chars_refresh(self, tile):
        """The list, the counter and the "not applied" note for the draft as it stands."""
        table = tile.table
        names = {"page": t("chars_col_page"), "excel": t("chars_col_excel")}
        table.setRowCount(0)
        for item in tile.draft:
            rule = item if isinstance(item, dict) else {}
            row = table.rowCount()
            table.insertRow(row)
            kind_text, value_text = self._chars_label(tile, rule)
            targets = ", ".join(names[target] for target in char_rules.targets_of(rule))
            for column, text in enumerate(("", kind_text, value_text, targets or "–", str(len(char_rules.named_by(tile.chars, rule))))):
                cell = QTableWidgetItem(text)
                flags = Qt.ItemFlag.ItemIsEnabled
                if column == 0:
                    flags |= Qt.ItemFlag.ItemIsUserCheckable
                    cell.setCheckState(Qt.CheckState.Unchecked)
                if column == 4:
                    cell.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                cell.setFlags(flags)
                table.setItem(row, column, cell)
        counts = {target: len(char_rules.hidden_keys(tile.chars, tile.draft, target)) for target in char_rules.TARGETS}
        tile.counter.setText(t("chars_counter", page=counts["page"], excel=counts["excel"], total=len(tile.chars)))
        tile.pending.setText(t("chars_pending") if tile.draft != tile.rules else "")
        tile.remove.setEnabled(bool(tile.draft))

    def _chars_delete_box(self, tile):
        """The block "Delete" of one game version (only built for one with data): the form (one character), the list of the characters marked for deleting
        and the blacklist. Nothing is deleted here: this part only fills and shows the lists."""
        box = QGroupBox(t("chars_del_group", variant=tile.variant))
        tile.del_box = box
        tile.del_list = []
        tile.by_key = {c["key"]: c for c in tile.chars}
        lay = QVBoxLayout(box)
        note = QLabel(t("chars_del_note"))
        note.setObjectName("hint")
        note.setWordWrap(True)
        lay.addWidget(note)

        form = QHBoxLayout()
        form.addWidget(QLabel(t("chars_del_char")))
        tile.del_char = self._searchable(QComboBox(), open_on_click=True)
        for key, label in tile.values.get("char", []):
            tile.del_char.addItem(label, key)
        tile.del_char.setCurrentIndex(-1)
        form.addWidget(tile.del_char, 1)
        tile.del_add = QPushButton(t("chars_del_add"))
        form.addWidget(tile.del_add)
        lay.addLayout(form)

        lay.addWidget(QLabel(t("chars_del_list_title")))
        tile.del_table = QTableWidget(0, 4)
        tile.del_table.setHorizontalHeaderLabels(["", t("chars_del_char"), t("chars_del_col_class"), t("chars_del_col_level")])
        self._chars_table_style(tile.del_table, stretch=1, height=110)
        lay.addWidget(tile.del_table)
        bar = QHBoxLayout()
        tile.del_remove = QPushButton(t("chars_remove"))
        bar.addWidget(tile.del_remove)
        bar.addStretch()
        lay.addLayout(bar)
        tile.del_preview = QLabel()
        lay.addWidget(tile.del_preview)
        apply_row = QHBoxLayout()
        tile.del_save = QPushButton(t("chars_apply"))
        tile.del_save.setObjectName("primary")
        tile.del_save.setEnabled(not self._busy)
        self.action_buttons.append(tile.del_save)                          # off while a slow action runs, like the others
        self._chars_buttons.append(tile.del_save)
        apply_row.addWidget(tile.del_save)
        apply_row.addStretch()
        lay.addLayout(apply_row)
        tile.del_message = QLabel()
        tile.del_message.setObjectName("hint")
        tile.del_message.setWordWrap(True)
        lay.addWidget(tile.del_message)

        lay.addWidget(QLabel(t("chars_bl_title")))
        tile.bl_table = QTableWidget(0, 2)
        tile.bl_table.setHorizontalHeaderLabels(["", t("chars_del_char")])
        self._chars_table_style(tile.bl_table, stretch=1, height=90)
        lay.addWidget(tile.bl_table)
        tile.bl_note = QLabel()
        tile.bl_note.setObjectName("hint")
        lay.addWidget(tile.bl_note)
        bl_bar = QHBoxLayout()
        tile.bl_remove = QPushButton(t("chars_bl_remove"))
        bl_bar.addWidget(tile.bl_remove)
        bl_bar.addStretch()
        lay.addLayout(bl_bar)
        tile.bl_message = QLabel()
        tile.bl_message.setObjectName("hint")
        tile.bl_message.setWordWrap(True)
        lay.addWidget(tile.bl_message)

        tile.del_add.clicked.connect(lambda _checked=False, tile=tile: self._del_add(tile))
        tile.del_remove.clicked.connect(lambda _checked=False, tile=tile: self._del_remove(tile))
        tile.del_save.clicked.connect(lambda _checked=False, tile=tile: self._del_apply(tile))
        tile.bl_remove.clicked.connect(lambda _checked=False, tile=tile: self._bl_remove(tile))
        self._del_refresh(tile)
        self._bl_refresh(tile)
        return box

    @staticmethod
    def _chars_table_style(table, stretch, height):
        """A table that only shows (no editing, no selection), a tick box in the first column, the column `stretch` takes the room."""
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        header = table.horizontalHeader()
        for column in range(table.columnCount()):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.Stretch if column == stretch else QHeaderView.ResizeMode.ResizeToContents)
        table.setMinimumHeight(height)

    @staticmethod
    def _chars_fill_rows(table, rows):
        """Fills a table with rows of texts and puts a tick box (not ticked) in front of every one."""
        table.setRowCount(0)
        for texts in rows:
            row = table.rowCount()
            table.insertRow(row)
            for column, text in enumerate(("",) + tuple(texts)):
                cell = QTableWidgetItem(text)
                flags = Qt.ItemFlag.ItemIsEnabled
                if column == 0:
                    flags |= Qt.ItemFlag.ItemIsUserCheckable
                    cell.setCheckState(Qt.CheckState.Unchecked)
                cell.setFlags(flags)
                table.setItem(row, column, cell)

    @staticmethod
    def _chars_marked(table):
        return [row for row in range(table.rowCount()) if table.item(row, 0).checkState() == Qt.CheckState.Checked]

    def _del_add(self, tile):
        """Puts the character of the form on the list of those marked for deleting (a character once)."""
        index = self._resolve(tile.del_char)
        if index < 0:                                                      # a text that fits no character or several: nothing is guessed
            tile.del_message.setText(t("chars_value_invalid"))
            return
        key = tile.del_char.itemData(index)
        tile.del_message.setText("")
        if key not in tile.del_list:
            tile.del_list.append(key)
        tile.del_char.setCurrentIndex(-1)
        self._del_refresh(tile)

    def _del_remove(self, tile):
        marked = set(self._chars_marked(tile.del_table))
        tile.del_message.setText("")
        tile.del_list = [key for row, key in enumerate(tile.del_list) if row not in marked]
        self._del_refresh(tile)

    def _del_refresh(self, tile):
        rows = []
        for key in tile.del_list:
            char = tile.by_key.get(key, {})
            rows.append((key, str(char.get("class") or ""), "" if char.get("level") is None else str(char["level"])))
        self._chars_fill_rows(tile.del_table, rows)
        tile.del_preview.setText(t("chars_del_preview", count=len(tile.del_list)))
        tile.del_remove.setEnabled(bool(tile.del_list))

    def _del_apply(self, tile):
        """Deletes the characters of the list, after asking: the question names the number and the characters ("No" is the preselected answer). Then, in
        this order: the keys go on the blacklist and that is saved (if it cannot be saved nothing is deleted: a deleted character would come back with
        the next import), actions.delete_chars runs in a thread (copy, deleting, history pages, the page again), and when it did not delete anything
        the keys come off the blacklist again."""
        if self._busy:
            return
        variant, keys = tile.variant, list(tile.del_list)
        if not keys:
            tile.del_message.setText(t("chars_del_empty"))
            return
        names = "\n".join(keys[:12]) + (("\n" + t("chars_del_more", count=len(keys) - 12)) if len(keys) > 12 else "")
        folder = db_backup.delete_dir(wow_install.out_files(variant)[0])
        if not dialogs.ask_yes_no(self, t("chars_del_ask", count=len(keys), variant=variant, names=names, folder=folder)):
            tile.del_message.setText(t("chars_del_cancelled"))
            return
        before = self.cfg["char_blacklist"].get(variant)
        self.cfg["char_blacklist"][variant] = config.clean_key_list(list(before or []) + keys)
        try:
            config.save(self.cfg)
        except OSError as exc:
            self._bl_set(variant, before)
            self.write(t("err_config_save", error=exc), "err")
            tile.del_message.setText(t("chars_del_blacklist_failed"))
            self._bl_refresh(tile)
            return
        top5 = list(self.cfg["top5"])
        rules = list(self.cfg["char_rules"].get(variant, []))
        self.run_in_thread(lambda: actions.delete_chars(variant, keys, top5, rules),
                           lambda result: self._deleted(result, tile, before), t("status_busy_delete"))

    def _bl_set(self, variant, keys):
        """Puts the blacklist of a game version in the settings of the window as it was (None: it had no entry)."""
        if keys is None:
            self.cfg["char_blacklist"].pop(variant, None)
        else:
            self.cfg["char_blacklist"][variant] = keys

    def _deleted(self, result, tile, before):
        ok, out, deleted = result
        for line in out.strip().splitlines():
            self.write(line, "err" if (not ok or line.startswith(("FEHLER", "WARNUNG", "ERROR", "WARNING"))) else None)
        variant = tile.variant
        if not ok:                                       # nothing was deleted: the keys come off the blacklist again
            self._bl_set(variant, before)
            try:
                config.save(self.cfg)
                tile.del_message.setText(t("chars_del_failed"))
            except OSError as exc:
                self.write(t("err_config_save", error=exc), "err")
                tile.del_message.setText(t("chars_del_stuck"))
            self._bl_refresh(tile)
            return
        done = t("log_chars_deleted", variant=variant, count=len(deleted))
        self.write(done, "ok")
        self._tile_key = None                            # the Top 5 tab reads what it offers again
        self._chars_drafts = {each.variant: list(each.draft) for each in self.char_tiles if each.table is not None and each.draft != each.rules}
        self._chars_notes = {variant: done}
        self._chars_key = None                           # the data changed: the blocks are built again, with the drafts of "Ignore" kept
        self.load_page(force=True)
        self._chars_load()

    def _bl_keys(self, tile):
        return list(self.cfg["char_blacklist"].get(tile.variant, []))

    def _bl_refresh(self, tile):
        keys = self._bl_keys(tile)
        self._chars_fill_rows(tile.bl_table, [(key,) for key in keys])
        tile.bl_note.setText("" if keys else t("chars_bl_empty"))
        tile.bl_remove.setEnabled(bool(keys))

    def _bl_remove(self, tile):
        """Takes the ticked characters off the blacklist and saves that at once (nothing is deleted or read by this: the next import reads them again).
        If the settings cannot be written, the blacklist stays as it was."""
        keys = self._bl_keys(tile)
        marked = {keys[row] for row in self._chars_marked(tile.bl_table)}
        if not marked:
            return
        kept = [key for key in keys if key not in marked]
        old = self.cfg["char_blacklist"].get(tile.variant)
        if kept:
            self.cfg["char_blacklist"][tile.variant] = kept
        else:
            self.cfg["char_blacklist"].pop(tile.variant, None)
        try:
            config.save(self.cfg)
        except OSError as exc:
            if old is None:
                self.cfg["char_blacklist"].pop(tile.variant, None)
            else:
                self.cfg["char_blacklist"][tile.variant] = old
            self.write(t("err_config_save", error=exc), "err")
            return
        message = t("chars_bl_removed", count=len(marked))
        self.write(message, "ok")
        tile.bl_message.setText(message)
        self._bl_refresh(tile)

    def _chars_apply(self, tile):
        """Saves the list of one game version in the settings and writes its page again (from its database, in a thread): the rules stay in the list
        until they are taken out. The page of another game version follows at its next import, the Excel file at the next export; the Top 5 tab reads
        its choices again."""
        if self._busy:
            return
        variant = tile.variant
        rules = config.clean_rule_list(tile.draft)
        if rules:
            self.cfg["char_rules"][variant] = rules
        else:
            self.cfg["char_rules"].pop(variant, None)
        tile.rules, tile.draft = list(rules), list(rules)
        self.save()
        self._tile_key = None
        saved = t("log_chars_saved", variant=variant, count=len(rules))
        self.write(saved, "ok")
        tile.message.setText(saved)
        self._chars_refresh(tile)
        if not wow_install.out_files(variant)[0].is_file():
            return
        top5 = list(self.cfg["top5"])
        self.run_in_thread(lambda: actions.rebuild_page(variant, top5, list(rules)), lambda result: self._page_rebuilt(result, variant), t("status_busy_top5"))

    # ----------------------------------------------------------------- log and status
    def write(self, text, tag=None):
        line = f"[{datetime.now():%H:%M:%S}] {text}"
        self._log_lines.append((line, tag))
        color = {"err": self.colors["red"], "ok": self.colors["green"]}.get(tag, self.colors["text"])
        self.log.appendHtml(f"<span style='color:{color}; white-space:pre-wrap'>{html.escape(line)}</span>")

    def clear_log(self):
        self._log_lines.clear()
        self.log.clear()

    def status_message(self, text):
        self.statusBar().showMessage(text)

    def status_text(self):
        """The status line of the game folder, the data and the addon (right side of the status bar)."""
        return self.lbl_status.text()

    # ----------------------------------------------------------------- helpers
    def root_and_variant(self):
        """(root, variant). variant is None if nothing usable is selected or the selected game version is not enabled.
        A typed-in version folder wins over the drop-down."""
        root, forced = wow_install.resolve_root(self.ed_wow.text())
        if not root:
            return None, None
        variant = forced or self.cmb_var.currentText()
        if not variant or variant not in self.cfg["enabled_variants"]:
            return root, None
        return root, variant

    def game_dir(self):
        root, variant = self.root_and_variant()
        return (root / variant) if (root and variant) else None

    def save(self):
        root, variant = self.root_and_variant()
        self.cfg["wow_dir"] = str(root) if root else self.ed_wow.text().strip()
        if variant:
            self.cfg["variant"] = variant
            self.cfg["accounts"][variant] = self.cmb_acc.currentText()
        try:
            config.save(self.cfg)
        except OSError as e:
            self.write(t("err_config_save", error=e), "err")

    def browse_wow(self):
        chosen = dialogs.pick_folder(self, self.ed_wow.text())
        if chosen:
            self.ed_wow.setText(str(Path(chosen)))

    def _fill(self, combo, items, wanted):
        """Fills a drop-down without telling the window about it; selects `wanted` if it is there, else the first."""
        self._refreshing = True
        try:
            combo.clear()
            combo.addItems(items)
            if wanted in items:
                combo.setCurrentText(wanted)
            elif items:
                combo.setCurrentIndex(0)
        finally:
            self._refreshing = False

    def refresh_variants(self, keep=""):
        keep = keep or self.cmb_var.currentText()
        root, forced = wow_install.resolve_root(self.ed_wow.text())
        variants = wow_install.list_variants(root, self.cfg["enabled_variants"]) if root else []
        self._fill(self.cmb_var, variants, forced or keep)
        self._refresh_variant_boxes(root)
        self.refresh_accounts()

    def _refresh_variant_boxes(self, root):
        """One check box per game version found in the folder (and per enabled one that is not found any more)."""
        while self.variant_boxes.count():
            item = self.variant_boxes.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        detected = wow_install.list_variants(root) if root else []
        for name in dict.fromkeys(list(detected) + list(self.cfg["enabled_variants"])):
            box = QCheckBox(name)
            box.setChecked(name in self.cfg["enabled_variants"])
            box.toggled.connect(lambda _on, n=name: self.on_variant_toggled(n))
            self.variant_boxes.addWidget(box)

    def refresh_accounts(self):
        game = self.game_dir()
        accounts = wow_install.list_accounts(game) if game else []
        self._fill(self.cmb_acc, accounts, self.cfg["accounts"].get(self.cmb_var.currentText(), ""))
        self.update_status()
        self.load_page()

    def update_status(self):
        root, variant = self.root_and_variant()
        if not root:
            text = t("status_invalid_root")
        elif not variant:
            _r, forced = wow_install.resolve_root(self.ed_wow.text())
            shown = forced or self.cmb_var.currentText()
            text = t("status_variant_disabled", variant=shown) if shown else t("status_invalid_root")
        else:
            text = "  |  ".join(actions.status_parts(root, variant, self.cmb_acc.currentText()))
        self.lbl_status.setText(text)
        self.lbl_status.setToolTip(text)

    def need_root(self):
        root, variant = self.root_and_variant()
        if not root:
            dialogs.error(self, t("err_invalid_root"))
            return None, None
        if not variant:
            dialogs.error(self, t("status_variant_disabled", variant=self.cmb_var.currentText() or "?"))
            return None, None
        return root, variant

    def set_busy(self, busy, message=""):
        self._busy = busy
        for button in self.action_buttons:
            button.setEnabled(not busy)
        self.status_message(message if busy else t("status_ready"))

    def run_in_thread(self, work, done, message):
        """Runs `work()` in a thread and then `done(result)` on the GUI thread; the action buttons are off meanwhile."""
        self.set_busy(True, message)

        def worker():
            result = work()
            self.dispatch.emit(lambda: self._finished(done, result))
        threading.Thread(target=worker, daemon=True).start()

    def _finished(self, done, result):
        self.set_busy(False)
        done(result)

    # ----------------------------------------------------------------- actions
    def on_language(self):
        code = self.cmb_lang.currentData()
        if not code or code == i18n.get_language():
            return
        i18n.set_language(code)
        self.cfg["language"] = code
        self.save()
        self.retranslate()

    def on_variant_toggled(self, name):
        """A check box of an enabled game version: at least one version stays enabled."""
        root, _forced = wow_install.resolve_root(self.ed_wow.text())
        chosen = [self.variant_boxes.itemAt(i).widget() for i in range(self.variant_boxes.count())]
        enabled = [b.text() for b in chosen if b.isChecked()]
        if not enabled:
            dialogs.error(self, t("settings_none_selected"))
            self._refresh_variant_boxes(root)
            return
        self.cfg["enabled_variants"] = enabled
        self.save()
        self.refresh_variants(keep=self.cmb_var.currentText())

    def on_options(self, _checked=None):
        self.cfg["check_updates"] = self.chk_updates.isChecked()
        self.cfg["read_icons"] = self.chk_icons.isChecked()
        self.save()

    def on_theme(self):
        number = self.cmb_theme.currentData()
        if number == self.cfg["active_theme"]:
            return
        self.cfg["active_theme"] = number
        self.save()
        self.write(t("theme_restart"))
        self.status_message(t("theme_restart"))

    def on_about(self):
        dialogs.show_about(self, lambda: self.check_updates(manual=True))

    def on_install(self):
        root, variant = self.need_root()
        if not root:
            return
        try:
            res = wow_install.install_addon(root, variant)
        except (RuntimeError, OSError) as e:
            self.write(t("err_install_failed", error=e), "err")
            dialogs.error(self, t("err_install_failed", error=e))
            return
        self.save()
        self.write(t("log_install_ok", dest=res.dest), "ok")
        if res.number is not None:
            self.write(t("log_interface_set", number=res.number, version=res.version, product=res.product), "ok")
        else:
            self.write(t("log_interface_unset", product=res.product), "err")
        self.write(t("log_install_reload"))
        self.update_status()

    def on_uninstall(self):
        root, variant = self.need_root()
        if not root:
            return
        dest = wow_install.addon_dir(root, variant)
        if not dialogs.ask_yes_no(self, t("confirm_uninstall", dest=dest)):
            return
        remove_vars = False
        if wow_install.saved_vars_files(root / variant):
            remove_vars = dialogs.ask_yes_no(self, t("confirm_uninstall_vars"))
        try:
            res = wow_install.uninstall_addon(root, variant, remove_saved_vars=remove_vars)
        except (RuntimeError, OSError) as e:
            self.write(t("err_uninstall_failed", error=e), "err")
            dialogs.error(self, t("err_uninstall_failed", error=e))
            return
        if res.removed_addon:
            self.write(t("log_uninstall_ok", dest=dest), "ok")
        else:
            self.write(t("log_uninstall_none", dest=dest))
        if remove_vars:
            self.write(t("log_uninstall_vars", count=len(res.removed_files)))
        self.write(t("log_uninstall_kept", path=paths.data_dir()))
        self.update_status()

    def on_parse(self, open_after=False):
        """Reads the data file of the chosen account (in a thread); the log and the page follow when it is done."""
        if self._busy:
            return
        root, variant = self.need_root()
        if not root:
            return
        account = self.cmb_acc.currentText()
        if not account:
            dialogs.error(self, t("err_no_account"))
            return
        sv = wow_install.saved_vars_path(root / variant, account)
        if not sv.is_file():
            msg = t("err_no_data_file", path=sv)
            self.write(msg.replace("\n\n", " ").replace("\n", " "), "err")
            dialogs.error(self, msg)
            return
        self.save()
        read_icons = self.cfg["read_icons"]
        top5 = list(self.cfg["top5"])
        rules = list(self.cfg["char_rules"].get(variant, []))
        skip = list(self.cfg["char_blacklist"].get(variant, []))
        self.run_in_thread(lambda: actions.import_saved_variables(sv, root, variant, read_icons, top5, rules, skip),
                           lambda result: self._parsed(result, root, variant, account, open_after),
                           t("status_busy_parse"))

    def _parsed(self, result, root, variant, account, open_after):
        ok, out = result
        self._tile_key = None                          # new data: the Top 5 tab reads what it offers again
        self._chars_key = None                         # and the Characters tab
        for line in out.strip().splitlines():
            self.write(line, "err" if (not ok or line.startswith(("FEHLER", "WARNUNG", "ERROR", "WARNING"))) else None)
        self.write(t("log_parse_ok") if ok else t("log_parse_fail"), "ok" if ok else "err")
        if ok:
            others = actions.other_accounts(root, variant, account)
            if others:
                self.write(t("log_other_accounts", accounts=", ".join(others)))
        self.update_status()
        if ok:
            self.load_page(force=True)
            if open_after:
                self.on_open()

    def on_parse_open(self):
        self.on_parse(open_after=True)

    def html_path(self):
        _root, variant = self.root_and_variant()
        return wow_install.out_files(variant)[1] if variant else None

    def on_open(self):
        """Shows the stats page of the chosen game version in the Page tab."""
        _root, variant = self.root_and_variant()
        if not variant:
            dialogs.error(self, t("err_no_variant"))
            return
        page = self.html_path()
        if not page.is_file():
            dialogs.info(self, t("info_no_html", name=page.name))
            return
        self.load_page(force=True)
        self.tabs.setCurrentIndex(TAB_PAGE)
        self.write(t("log_opened", path=page))

    def open_in_browser(self):
        """Opens the stats page in the browser: a snapshot of what the window shows now (selection, filters, sorting; the controls are locked there
        because the browser has no connection to the program). Without a page shown in the window, the stats page file itself is opened."""
        page = self.html_path()
        if page is None or not page.is_file():
            dialogs.info(self, t("info_no_html", name=page.name if page else "stats.html"))
            return
        view = self._bridge.view
        if view is not None:
            _root, variant = self.root_and_variant()
            try:
                page = actions.write_snapshot(view, variant)
            except OSError as e:
                self.write(t("log_snapshot_fail", error=e), "err")
                return
        if not webbrowser.open(page.as_uri()):
            self.write(t("log_browser_fail", path=page), "err")
        else:
            self.write(t("log_opened", path=page))

    def load_page(self, force=False):
        """Shows the stats page of the chosen game version (or the hint that there is none yet). Without `force` a page
        that is already shown is left alone."""
        page = self.html_path()
        if page is None or not page.is_file():
            self._page_url = ""
            self.stack.setCurrentWidget(self.placeholder)
            return
        url = QUrl.fromLocalFile(str(page))
        if force or url.toString() != self._page_url:
            self._page_url = url.toString()
            if force and self.view.url() == url:
                self.view.reload()
            else:
                self.view.setUrl(url)
        self.stack.setCurrentWidget(self.view)

    def _download(self, request):
        """A download the page asks for (the save button of a chart): the user chooses where it goes."""
        name = QFileDialog.getSaveFileName(self, t("dlg_title"), request.downloadFileName())[0]
        if not name:
            request.cancel()
            return
        target = Path(name)
        request.setDownloadDirectory(str(target.parent))
        request.setDownloadFileName(target.name)
        request.accept()

    def on_export(self):
        if self._busy:
            return
        rules = {variant: list(variant_rules) for variant, variant_rules in self.cfg["char_rules"].items()}       # every game version: one workbook holds them all
        self.run_in_thread(lambda: actions.run_export(rules), self._exported, t("status_busy_export"))

    def _exported(self, result):
        ok, out, path = result
        for line in out.strip().splitlines():
            self.write(line, None if ok else "err")
        if not ok:
            self.write(t("log_export_fail"), "err")
            dialogs.error(self, out.strip())
            return
        self.write(t("log_export_ok"), "ok")
        try:
            if hasattr(os, "startfile"):
                os.startfile(str(path))                       # Windows: the default program (Excel)
            elif not webbrowser.open(path.as_uri()):
                self.write(t("log_file_open_fail", path=path), "err")
        except OSError as e:
            self.write(t("log_file_open_fail", path=e), "err")

    # ------------------------------------------------------------------ updates
    def check_updates(self, manual=False):
        if not app_info.REPO_CONFIRMED:
            if manual:
                dialogs.info(self, t("update_repo_placeholder"))
            return

        def worker():
            message = (*actions.fetch_release(), manual)
            self.dispatch.emit(lambda: self.on_message(message))
        threading.Thread(target=worker, daemon=True).start()

    def on_message(self, message):
        """The result of an update worker: ("release", data, manual), ("update_error", text, manual),
        ("update_failed", text) or ("apply", payload)."""
        kind = message[0]
        if kind == "release":
            self._on_release(message[1], message[2])
        elif kind == "update_error":
            if message[2]:                    # silent at start (offline use is normal), loud when asked for
                dialogs.error(self, t("update_check_failed", error=message[1]))
        elif kind == "update_failed":
            self._update_open = False
            self.set_busy(False)
            self.write(t("update_failed", error=message[1]), "err")
        elif kind == "apply":
            self._apply_update(message[1])

    def _on_release(self, data, manual):
        tag = str(data.get("tag_name", "")).strip()
        if not app_info.is_newer(tag, app_info.APP_VERSION):
            if manual:
                dialogs.info(self, t("update_none", version=app_info.APP_VERSION))
            return
        if self._update_open:                 # the check at start and a manual one can both bring a release
            return
        can_apply = paths.is_frozen()
        if not can_apply:
            self.write(t("update_not_frozen", url=app_info.RELEASES_URL))
        choice = None
        self._update_open = True
        try:
            choice = dialogs.ask_update(self, str(data.get("name") or tag), app_info.APP_VERSION, can_apply)
        finally:
            self._update_open = choice == "update"     # stays set until the update fails or the program restarts
        if choice == "update":
            self._start_update(data, tag)
        elif choice == "github":
            webbrowser.open(app_info.RELEASES_URL)

    def _start_update(self, data, tag):
        self.write(t("update_downloading", version=tag))
        self.status_message(t("status_busy_update"))

        def worker():
            message = actions.download_update(data)
            self.dispatch.emit(lambda: self.on_message(message))
        threading.Thread(target=worker, daemon=True).start()

    def _apply_update(self, payload):
        self.write(t("update_applying"), "ok")
        try:
            updater.launch_helper(paths.base_dir(), payload, [os.getpid()], restart=True)
        except (RuntimeError, OSError) as exc:
            self._update_open = False
            self.write(t("update_failed", error=exc), "err")
            return
        QTimer.singleShot(300, self.close)    # the helper waits for this process to exit

    # ------------------------------------------------------------------ closing
    def closeEvent(self, event):
        """The view and its page go before the profile they belong to (Qt wants that order)."""
        self._page.setWebChannel(None)
        self.view.deleteLater()
        self._page.deleteLater()
        self._profile.deleteLater()
        super().closeEvent(event)
