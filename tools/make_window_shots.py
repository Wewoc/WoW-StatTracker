#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)
"""Pictures of the program window with the invented demo data of tools/make_demo.py (docs/images/app-*.png and top5-*.png).
Developer tool (not part of the release). It starts the real window without a screen (the Qt "offscreen" platform) in a temporary instance folder that
holds the demo database and page of one language, and saves two pictures: the Settings tab (app-<lang>.png, with a few invented lines in the log) and
the Top 5 tab with the five demo tiles (top5-<lang>.png, cut below the button). Nothing of the machine shows in them: the game folder, the account and the status line are
replaced by invented, neutral texts before the picture is taken.

Usage (from the repository root, after python tools/make_demo.py --out <demo folder>):
  python tools/make_window_shots.py --demo <demo folder> --out <folder for the pictures>            # both languages
  python tools/make_window_shots.py --demo <demo folder> --out <folder> --lang de
The pictures are made at 1.5 times the size of the window (like the pages: the landing page shows them smaller). Fonts: on Windows the system
fonts are used (the offscreen platform has none of its own).
"""
import argparse
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_SCALE_FACTOR", "1.5")
if sys.platform == "win32" and Path(r"C:\Windows\Fonts").is_dir():
    os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))
from PyQt6.QtCore import QCoreApplication, QEvent, QPoint  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from app import main_window  # noqa: E402
from core import app_info, config, i18n, paths  # noqa: E402
from core.i18n import t  # noqa: E402
from game import wow_install  # noqa: E402
import make_demo  # noqa: E402

LANGS = make_demo.LANGS
WINDOW_SIZE = (1180, 720)                                    # as wide as the window opens, a little lower (the log has room to spare)
NEUTRAL_GAME = r"C:\Games\World of Warcraft"                  # what the window shows as the game folder
NEUTRAL_FILE = r"C:\Games\World of Warcraft\_retail_\WTF\Account\DEMO\SavedVariables\StatTracker.lua"
LOG = (                                                       # invented lines for the log (keys of i18n, neutral paths)
    ("parse_out_source", {"path": NEUTRAL_FILE}, None),
    ("parse_out_scans", {"new": 5, "skipped": 0}, None),
    ("parse_out_html", {"path": r"data\stats.html", "chars": 5, "stats": None}, None),
    ("log_parse_ok", {}, "ok"),
)


def _settle(app):
    """Lets the window finish what it does later (widgets it removed are really gone) before a picture is taken."""
    for _ in range(5):
        app.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        time.sleep(0.05)


def _wait(app, condition, seconds=30):
    end = time.time() + seconds
    while time.time() < end:
        app.processEvents()
        if condition():
            return
        time.sleep(0.05)
    raise SystemExit("the window did not get ready")


def _instance(demo, lang, base):
    """A temporary instance folder with the demo database and page of `lang`, a game folder to point at, and settings with the demo tiles."""
    folder = Path(demo) / lang
    if not (folder / "demo.db").is_file() or not (folder / "stats.html").is_file():
        raise SystemExit(f"no demo data for '{lang}' in {demo}: run tools/make_demo.py --out <folder> first")
    data = base / "data"
    data.mkdir(parents=True)
    shutil.copyfile(folder / "demo.db", data / "wow_stats.db")
    shutil.copyfile(folder / "stats.html", data / "stats.html")
    game = base / "World of Warcraft"
    (game / "_retail_" / "Interface" / "AddOns").mkdir(parents=True)
    (game / "_retail_" / "WTF" / "Account" / "DEMO" / "SavedVariables").mkdir(parents=True)
    (game / ".build.info").write_text("Branch!STRING:0|Active!DEC:1|Product!STRING:0|Version!STRING:0\neu|1|wow|12.1.5.70575\n", encoding="utf-8")
    cfg = config.defaults()
    cfg.update(language=lang, wow_dir=str(game), variant="_retail_", enabled_variants=["_retail_"], accounts={"_retail_": "DEMO"},
               check_updates=False, read_icons=True, active_theme=1, top5=[dict(tile) for tile in make_demo.DEMO_TOP5])
    config.save(cfg)
    return game


def _neutral(window, stats):
    """The texts that would show the machine, replaced by invented ones: the game folder, the log, the status line."""
    window.ed_wow.blockSignals(True)
    window.ed_wow.setText(NEUTRAL_GAME)
    window.ed_wow.blockSignals(False)
    window.chk_updates.blockSignals(True)                         # the picture shows the usual setting; the window was started with the check off (it must not ask the net)
    window.chk_updates.setChecked(True)
    window.chk_updates.blockSignals(False)
    window.clear_log()
    for key, values, tag in LOG:
        window.write(t(key, **{k: (stats if v is None else v) for k, v in values.items()}), tag)
    parts = [t("status_game", path=NEUTRAL_GAME + r"\_retail_"), t("status_data_present", ts="2026-10-28 19:44:10"),
             t("status_addon_ok", version=app_info.APP_VERSION), t("status_html_present", name="stats.html")]
    window.lbl_status.setText("  |  ".join(parts))                # the permanent label of the status bar (update_status writes it)


def shoot(demo, lang, out, app):
    """Saves app-<lang>.png and top5-<lang>.png into `out`; returns their paths."""
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    base = Path(tempfile.mkdtemp())
    previous_base = paths.base_dir
    paths.base_dir = lambda: base
    i18n.set_language(lang)
    try:
        game = _instance(demo, lang, base)
        window = main_window.MainWindow()
        window.resize(*WINDOW_SIZE)
        window.show()
        _settle(app)
        stats = len(make_demo.payload_of((base / "data" / "stats.html").read_text(encoding="utf-8"))["stats"])
        _neutral(window, stats)
        _settle(app)
        first = out / f"app-{lang}.png"
        window.grab().save(str(first))
        window.ed_wow.blockSignals(True)                          # the tab reads from the real (temporary) game folder: the neutral text is only for the picture
        window.ed_wow.setText(str(game))
        window.ed_wow.blockSignals(False)
        window.tabs.setCurrentIndex(main_window.TAB_TOP5)
        _wait(app, lambda: window._tile_choices is not None and not window._busy)
        _neutral(window, stats)
        _settle(app)
        second = out / f"top5-{lang}.png"
        picture = window.grab()                                   # cut below the button: the rest of the tab is empty
        bottom = window.btn_top5.mapTo(window, QPoint(0, 0)).y() + window.btn_top5.height() + 24
        picture.copy(0, 0, picture.width(), int(bottom * picture.devicePixelRatio())).save(str(second))
        return first, second
    finally:
        paths.base_dir = previous_base


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--demo", required=True, help="the --out folder of tools/make_demo.py (with <lang>/demo.db and <lang>/stats.html)")
    ap.add_argument("--out", required=True, help="folder for the pictures (outside the repository, then copy them to docs/images/)")
    ap.add_argument("--lang", choices=LANGS + ("both",), default="both")
    a = ap.parse_args(argv)
    app = QApplication(sys.argv[:1])
    for lang in (LANGS if a.lang == "both" else (a.lang,)):
        for path in shoot(a.demo, lang, a.out, app):
            print(path)
    sys.stdout.flush()
    os._exit(0)                       # the embedded browser does not like being taken down in the middle of a script


if __name__ == "__main__":
    main()
