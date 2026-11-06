#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)
# main_window.py
# StatTracker - the main window (Qt): two tabs, a status bar, nothing else. "Settings" holds the game folder, version and
# account, the actions (install / uninstall the addon, read the data, open the page, Excel), the options, the design and
# the log; "Page" shows the stats page in the window (QWebEngineView). The status bar shows what is going on and the state
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
from PyQt6.QtWidgets import (QApplication, QCheckBox, QComboBox, QCompleter, QFileDialog, QGridLayout, QGroupBox, QHBoxLayout,
                             QLabel, QLineEdit, QMainWindow, QPlainTextEdit, QPushButton, QStackedWidget, QTabWidget,
                             QVBoxLayout, QWidget)

from app import actions, dialogs, page_bridge, qt_style
from app.suggest_list import ShowAllOnClick, SuggestionDelegate
from app.qwebengine_hardening import harden
from core import app_info, config, i18n, paths, theme, updater
from core.i18n import t
from game import wow_install

TAB_SETTINGS, TAB_PAGE, TAB_TOP5 = 0, 1, 2
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
        self._label_tile_combos()
        self._tile_key = None                      # the names of the choices are in the language of the program: read them again when the tab is shown
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
        """Reads what the Top 5 tab offers (in a thread) the first time it is shown and whenever the data, the game version or the language changed."""
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

        def work():
            try:
                return actions.tile_choices(variant)
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
        self.run_in_thread(lambda: actions.rebuild_page(variant, saved), self._page_rebuilt, t("status_busy_top5"))

    def _page_rebuilt(self, result):
        ok, out = result
        for line in out.strip().splitlines():
            self.write(line, "err" if (not ok or line.startswith(("FEHLER", "WARNUNG", "ERROR", "WARNING"))) else None)
        if not ok:
            self.write(t("log_top5_page_fail"), "err")
            return
        self.write(t("log_top5_page", path=self.html_path()), "ok")
        self.load_page(force=True)

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
        self.run_in_thread(lambda: actions.import_saved_variables(sv, root, variant, read_icons, top5),
                           lambda result: self._parsed(result, root, variant, account, open_after),
                           t("status_busy_parse"))

    def _parsed(self, result, root, variant, account, open_after):
        ok, out = result
        self._tile_key = None                          # new data: the Top 5 tab reads what it offers again
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
        self.run_in_thread(actions.run_export, self._exported, t("status_busy_export"))

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
