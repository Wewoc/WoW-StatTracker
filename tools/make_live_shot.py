#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)
"""Picture of the live window of the addon (docs/images/live-en.png and live-de.png): an ILLUSTRATION, not a screenshot of the game.
Developer tool (not part of the release; it needs lupa and PyQt6, so run it with the build venv).

What it does: the real addon files (StatTrackerLive.lua, StatTrackerWindow.lua) run in an embedded Lua against the faked game API of
tests/test_live_lua.py (the one place that fakes it) with INVENTED values of the demo character Mirella-Dawnspire (tools/make_demo.py): a login,
a played-time answer, 47 minutes of play with some kills and gold. The rows (texts, states, order, the title with the version of the .toc) are what
`Live.WindowLines` returns for them, so the words and numbers are those the addon writes. Only the drawing is not the game's: Qt paints a dark frame,
the rows and the corner on a plain background, with a system font. Nothing of a real character or of the game is in the picture.

Usage (from the repository root):
  .venv-build/Scripts/python.exe tools/make_live_shot.py --out <folder>            # live-en.png and live-de.png
  .venv-build/Scripts/python.exe tools/make_live_shot.py --out <folder> --lang de
Then copy the pictures to docs/images/ (the captions and alt texts say "illustration").
"""
import argparse
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
if sys.platform == "win32" and Path(r"C:\Windows\Fonts").is_dir():
    os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from PyQt6.QtCore import QPointF, QRectF, Qt  # noqa: E402
from PyQt6.QtGui import QBrush, QColor, QFont, QGuiApplication, QImage, QLinearGradient, QPainter, QPen  # noqa: E402

import test_live_lua as lua_env  # noqa: E402  (the faked game API; importing it needs lupa)
from game import wow_install  # noqa: E402

CHAR_NAME, CHAR_REALM = "Mirella", "Dawnspire"      # the demo character of make_demo.CHARS
LANGS = ("en", "de")
LOCALE = {"en": "enUS", "de": "deDE"}
NAMES = {                                            # the statistic names the game gives (the ids of StatTrackerLive.lua)
    "en": {107: "Creatures killed", 1487: "Total killing blows", 60: "Total deaths", 98: "Quests completed", 328: "Total gold acquired"},
    "de": {107: "Kreaturen getötet", 1487: "Todesstöße insgesamt", 60: "Tode insgesamt", 98: "Quests abgeschlossen", 328: "Erhaltenes Gold insgesamt"},
}

LOGIN = 1_793_000_000                                # the virtual clock of the fake game (seconds)
PLAYED_TOTAL, PLAYED_LEVEL = 2_583_885, 180_871      # what the game answers to /played (the demo character: 29 days 21 hours)
AT_LOGIN = {107: 4139, 1487: 3247, 60: 36, 98: 808}  # invented statistic values at the login ...
NOW_VALUES = {107: 4210, 1487: 3305, 60: 37, 98: 812}   # ... and 47 minutes later
GOLD_AT_LOGIN = (18420, 12, 40)                      # gold, silver, copper of "Total gold acquired" (a coin text in the game)
GOLD_NOW = (18552, 52, 55)
MONEY_AT_LOGIN = 25_120_000                          # copper in the bag
SESSION_MINUTES = 47
LAST_SCAN_HOURS = 3
CLOCK = "21:14:08"

# the window of StatTrackerWindow.lua: width 340, a row 16 high, 26 above the first row and 18 below the last
WIDTH, ROW_H, TOP, PAD = 340, 16, 26, 18
COLORS = {"HEAD": (255, 209, 0), "LIVE": (255, 255, 255), "SNAPSHOT": (166, 166, 166), "UNKNOWN": (128, 128, 128), "FOOT": (140, 140, 140)}
SCALE = 2                                            # the picture is made at twice the size of the window
MARGIN = 28
_APP = None


def _before(lang):
    names = ", ".join(f"[{i}] = {name!r}".replace("'", '"') for i, name in NAMES[lang].items())
    version = wow_install.toc_version(lua_env.ADDON_DIR / "StatTracker.toc") or "0"
    return f'''
NOW = {LOGIN}
TOC_VERSION = "{version}"
function UnitName() return "{CHAR_NAME}" end
function GetRealmName() return "{CHAR_REALM}" end
local names = {{ {names} }}
function GetAchievementInfo(id) return id, names[id] end
date = function() return "{CLOCK}" end
StatTrackerDB = {{ version = 5, chars = {{ ["{CHAR_NAME}-{CHAR_REALM}"] = {{ scannedEpoch = {LOGIN - LAST_SCAN_HOURS * 3600}, stats = {{}} }} }} }}
'''


def window_content(lang):
    """(title, rows) of the window after the invented session; rows are dicts with label, value and state."""
    lua = lua_env.start(LOCALE[lang], before=_before(lang), login=False, window=True)
    lua_env.set_stats(lua, {**AT_LOGIN, 328: lua_env.coin(*GOLD_AT_LOGIN)})
    lua.globals().MONEY = MONEY_AT_LOGIN
    lua_env.do_login(lua)
    lua.execute(f'Fire("TIME_PLAYED_MSG", {PLAYED_TOTAL}, {PLAYED_LEVEL})')
    lua.execute("RunTimers(1500)")
    lua_env.set_stats(lua, {**NOW_VALUES, 328: lua_env.coin(*GOLD_NOW)})
    lua.globals().MONEY = MONEY_AT_LOGIN + (GOLD_NOW[0] - GOLD_AT_LOGIN[0]) * 10000 + (GOLD_NOW[1] - GOLD_AT_LOGIN[1]) * 100 \
        + (GOLD_NOW[2] - GOLD_AT_LOGIN[2])
    lua.execute(f"RunTimers({SESSION_MINUTES * 60 - 1500})")
    rows = lua.eval("NS.Live.WindowLines(NS.Live.Values())")
    out = []
    for i in range(1, len(rows) + 1):
        row = rows[i]
        out.append({"label": str(row["label"]), "value": str(row["value"]), "state": str(row["state"])})
    return str(lua.eval("NS.Live.WindowTitle()")), out


def draw(title, rows, path):
    """Paint the window on a plain background and save it as a PNG."""
    global _APP
    if QGuiApplication.instance() is None:
        _APP = QGuiApplication([])           # kept in a variable: an application that is not referenced is deleted at once and the process dies
    height = TOP + len(rows) * ROW_H + PAD
    full_w, full_h = WIDTH + 2 * MARGIN, height + 2 * MARGIN
    image = QImage(full_w * SCALE, full_h * SCALE, QImage.Format.Format_ARGB32)
    p = QPainter(image)
    p.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.TextAntialiasing)
    p.scale(SCALE, SCALE)
    back = QLinearGradient(0, 0, 0, full_h)                  # a plain background, nothing of the game
    back.setColorAt(0, QColor(58, 52, 44))
    back.setColorAt(1, QColor(30, 27, 23))
    p.fillRect(QRectF(0, 0, full_w, full_h), QBrush(back))
    frame = QRectF(MARGIN, MARGIN, WIDTH, height)
    p.setBrush(QColor(8, 8, 10, 235))
    p.setPen(QPen(QColor(120, 120, 120), 1.2))
    p.drawRoundedRect(frame, 5, 5)

    font = QFont("Segoe UI")
    font.setPixelSize(11)
    p.setFont(font)
    p.setPen(QColor(240, 240, 240))
    p.drawText(QPointF(MARGIN + 9, MARGIN + 17), title)
    for n, row in enumerate(rows):
        base = MARGIN + TOP + n * ROW_H
        p.setPen(QColor(*COLORS.get(row["state"], COLORS["LIVE"])))
        box = QRectF(MARGIN + 9, base, WIDTH - 18, ROW_H)
        p.drawText(box, int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), row["label"])
        p.drawText(box, int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter), row["value"])
    close = QRectF(MARGIN + WIDTH - 22, MARGIN + 4, 16, 16)     # the close button
    p.setBrush(QColor(150, 70, 20))
    p.setPen(QPen(QColor(230, 150, 60), 1))
    p.drawRoundedRect(close, 3, 3)
    p.setPen(QPen(QColor(255, 235, 200), 1.6))
    p.drawLine(QPointF(close.left() + 4.5, close.top() + 4.5), QPointF(close.right() - 4.5, close.bottom() - 4.5))
    p.drawLine(QPointF(close.left() + 4.5, close.bottom() - 4.5), QPointF(close.right() - 4.5, close.top() + 4.5))
    p.setPen(QPen(QColor(150, 150, 150), 1))                     # the corner that changes the width
    right, bottom = MARGIN + WIDTH - 4, MARGIN + height - 4
    for step in (4, 8, 12):
        p.drawLine(QPointF(right - step, bottom), QPointF(right, bottom - step))
    p.end()
    path.parent.mkdir(parents=True, exist_ok=True)
    if not image.save(str(path), "PNG"):
        raise OSError(f"could not write {path}")
    return image.width(), image.height()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--out", required=True, type=Path, help="folder for the pictures")
    parser.add_argument("--lang", choices=LANGS, help="one language (default: both)")
    args = parser.parse_args(argv)
    for lang in ([args.lang] if args.lang else LANGS):
        title, rows = window_content(lang)
        size = draw(title, rows, args.out / f"live-{lang}.png")
        print(f"live-{lang}.png {size[0]} x {size[1]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
