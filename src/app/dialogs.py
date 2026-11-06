#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)
# dialogs.py
# StatTracker - the small modal dialogs of the window: message, question, folder choice, "update available", "about".
# Each takes the parent window; the texts come from i18n at call time, so a language switch needs no rebuild here.
# They are plain functions so that tests can replace them (the window never calls QMessageBox directly).

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QDialog, QFileDialog, QHBoxLayout, QLabel, QMessageBox, QPushButton, QVBoxLayout

from core import app_info
from core.i18n import t


def info(parent, text):
    QMessageBox.information(parent, t("dlg_title"), text)


def error(parent, text):
    QMessageBox.critical(parent, t("dlg_title"), text)


def ask_yes_no(parent, text) -> bool:
    """A yes/no question; "no" is the preselected answer (it is used before something is removed)."""
    answer = QMessageBox.question(parent, t("dlg_title"), text,
                                  QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                  QMessageBox.StandardButton.No)
    return answer == QMessageBox.StandardButton.Yes


def pick_folder(parent, start: str) -> str:
    """The folder chosen by the user, or "" when the dialog was cancelled."""
    return QFileDialog.getExistingDirectory(parent, t("browse_title"), start or "")


def ask_update(parent, title, current, can_apply):
    """The update popup: returns "update", "github" or None (later)."""
    box = QMessageBox(parent)
    box.setWindowTitle(t("update_title"))
    box.setText(t("update_text", title=title, current=current))
    update = box.addButton(t("btn_update_now"), QMessageBox.ButtonRole.AcceptRole) if can_apply else None
    github = box.addButton(t("btn_open_github"), QMessageBox.ButtonRole.ActionRole)
    later = box.addButton(t("btn_later"), QMessageBox.ButtonRole.RejectRole)
    box.setDefaultButton(later)
    box.exec()
    clicked = box.clickedButton()
    if update is not None and clicked is update:
        return "update"
    if clicked is github:
        return "github"
    return None


def show_about(parent, on_check_updates):
    """The about box; its button for the update check closes it and calls `on_check_updates`."""
    win = QDialog(parent)
    win.setWindowTitle(t("about_title"))
    lay = QVBoxLayout(win)
    title = QLabel(app_info.APP_NAME)
    title.setObjectName("title")
    lay.addWidget(title)
    version = QLabel(t("footer_version", version=app_info.APP_VERSION))
    version.setObjectName("hint")
    lay.addWidget(version)
    desc = QLabel(t("about_desc"))
    desc.setWordWrap(True)
    desc.setMinimumWidth(420)
    lay.addWidget(desc)
    caption = t("about_repo")
    repo = QLabel(f"{caption} <a href='{app_info.REPO_URL}'>{app_info.REPO_URL}</a>")
    repo.setOpenExternalLinks(True)
    repo.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
    lay.addWidget(repo)
    if not app_info.REPO_CONFIRMED:
        note = QLabel(t("about_repo_placeholder"))
        note.setWordWrap(True)
        note.setObjectName("hint")
        lay.addWidget(note)
    lay.addWidget(QLabel(app_info.COPYRIGHT))
    licence = QLabel(t("about_license", license=app_info.LICENSE_NAME))
    licence.setWordWrap(True)
    lay.addWidget(licence)
    row = QHBoxLayout()
    row.addStretch()
    check = QPushButton(t("btn_check_updates"))
    close = QPushButton(t("btn_close"))
    row.addWidget(check)
    row.addWidget(close)
    lay.addLayout(row)
    close.clicked.connect(win.accept)

    def check_now():
        win.accept()
        on_check_updates()
    check.clicked.connect(check_now)
    win.exec()
