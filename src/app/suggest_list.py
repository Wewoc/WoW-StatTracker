#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)
# suggest_list.py
# StatTracker - how the list of suggestions under a search box of the window looks: every entry shows its name on one line and, smaller and dimmer on a
# second line, what it belongs to (the category of a statistic), like the suggestions under the search box of the stats page. An entry that carries no such
# parts (a plain text) is drawn the usual way. The parts are put into the item with setItemData(index, text, SuggestionDelegate.NAME / .DETAIL).
# ShowAllOnClick: a click into a search box opens the list with every entry (a box with a few choices would show no list until one types). Needs PyQt6.

from PyQt6.QtCore import QEvent, QObject, QSize, Qt, QTimer
from PyQt6.QtGui import QFont, QFontMetrics, QPalette
from PyQt6.QtWidgets import QApplication, QStyle, QStyledItemDelegate, QStyleOptionViewItem

PAD_X, PAD_Y = 8, 3


class SuggestionDelegate(QStyledItemDelegate):
    NAME = Qt.ItemDataRole.UserRole + 1
    DETAIL = Qt.ItemDataRole.UserRole + 2

    @staticmethod
    def _small(font: QFont) -> QFont:
        small = QFont(font)
        if font.pointSizeF() > 0:
            small.setPointSizeF(max(6.0, font.pointSizeF() * 0.85))
        elif font.pixelSize() > 0:
            small.setPixelSize(max(8, int(font.pixelSize() * 0.85)))
        return small

    def sizeHint(self, option, index):
        size = super().sizeHint(option, index)
        if index.data(self.NAME) is None:
            return size
        lines = 2 if index.data(self.DETAIL) else 1
        height = QFontMetrics(option.font).height() + (QFontMetrics(self._small(option.font)).height() if lines == 2 else 0)
        return QSize(size.width(), height + 2 * PAD_Y)

    def paint(self, painter, option, index):
        name, detail = index.data(self.NAME), index.data(self.DETAIL)
        if name is None:
            super().paint(painter, option, index)
            return
        shown = QStyleOptionViewItem(option)
        self.initStyleOption(shown, index)
        shown.text = ""                                                        # the background and the highlight of the entry, no text
        style = shown.widget.style() if shown.widget else QApplication.style()
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, shown, painter, shown.widget)
        chosen = bool(option.state & QStyle.StateFlag.State_Selected)
        area = option.rect.adjusted(PAD_X, PAD_Y, -PAD_X, -PAD_Y)
        painter.save()
        painter.setFont(option.font)
        painter.setPen(option.palette.color(QPalette.ColorRole.HighlightedText if chosen else QPalette.ColorRole.Text))
        metrics = QFontMetrics(option.font)
        painter.drawText(area, int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop), metrics.elidedText(str(name), Qt.TextElideMode.ElideRight, area.width()))
        if detail:
            small = self._small(option.font)
            painter.setFont(small)
            painter.setPen(option.palette.color(QPalette.ColorRole.HighlightedText if chosen else QPalette.ColorRole.PlaceholderText))
            painter.drawText(area.adjusted(0, metrics.height(), 0, 0), int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop),
                             QFontMetrics(small).elidedText(str(detail), Qt.TextElideMode.ElideRight, area.width()))
        painter.restore()


class ShowAllOnClick(QObject):
    """A click into the line of an editable combo box opens the list of its completer with every entry, not only with those that fit what is typed
    (the style sheet of the window has no arrow on a combo box, so without this a box shows no list until one types). Typing then narrows the list."""

    def __init__(self, combo):
        super().__init__(combo)                       # lives as long as the combo box
        self._combo = combo
        combo.lineEdit().installEventFilter(self)

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.MouseButtonPress and self._combo.count() > 0:
            QTimer.singleShot(0, self._show)          # after the click has set the focus: a popup shown before it would be closed again
        return False

    def _show(self):
        completer = self._combo.completer()
        completer.setCompletionPrefix("")
        completer.complete()
