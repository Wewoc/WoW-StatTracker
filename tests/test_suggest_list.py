# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)
# The look of the list of suggestions of the window (src/app/suggest_list.py): two lines for an entry that carries a name and a detail.

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtGui import QImage, QPainter, QStandardItem, QStandardItemModel
from PyQt6.QtWidgets import QStyleOptionViewItem

from app.suggest_list import SuggestionDelegate


def model(*entries):
    items = QStandardItemModel()
    for text, name, detail in entries:
        item = QStandardItem(text)
        if name is not None:
            item.setData(name, SuggestionDelegate.NAME)
        if detail is not None:
            item.setData(detail, SuggestionDelegate.DETAIL)
        items.appendRow(item)
    return items


def option(qapp):
    opt = QStyleOptionViewItem()
    opt.font = qapp.font()
    opt.rect = opt.rect.adjusted(0, 0, 300, 40)
    return opt


def test_an_entry_with_a_detail_is_taller_than_one_without_and_a_plain_text_keeps_the_usual_size(qapp):
    items = model(("Gold (Wealth)", "Gold", "Wealth"), ("Gold only", "Gold", None), ("plain", None, None))
    delegate = SuggestionDelegate()
    opt = option(qapp)
    two, one, plain = (delegate.sizeHint(opt, items.index(row, 0)) for row in range(3))
    assert two.height() > one.height() > 0 and plain == super(SuggestionDelegate, delegate).sizeHint(opt, items.index(2, 0))
    assert isinstance(two, QSize)


def test_painting_draws_something_for_every_kind_of_entry_and_does_not_fail(qapp):
    items = model(("Gold (Wealth)", "Gold", "Wealth"), ("Gold only", "Gold", None), ("plain", None, None), ("Long", "x" * 400, "y" * 400))
    delegate = SuggestionDelegate()
    for row in range(4):
        image = QImage(300, 44, QImage.Format.Format_ARGB32)
        image.fill(Qt.GlobalColor.white)
        painter = QPainter(image)
        opt = option(qapp)
        delegate.paint(painter, opt, items.index(row, 0))
        painter.end()
        assert any(image.pixelColor(x, y) != Qt.GlobalColor.white for x in range(0, 300, 3) for y in range(0, 44)), row
