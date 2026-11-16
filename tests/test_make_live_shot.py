# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)
# The picture of the live window (tools/make_live_shot.py, docs/images/live-*.png): the rows come out of the real addon files run in
# an embedded Lua with invented values, so the words are the addon's; the picture is an illustration and shows nothing of a real character.
# Skipped without lupa or PyQt6.

import importlib.util
import re
from pathlib import Path

import pytest

pytest.importorskip("lupa")
pytest.importorskip("PyQt6")

ROOT = Path(__file__).resolve().parent.parent
TOOL = ROOT / "tools" / "make_live_shot.py"
spec = importlib.util.spec_from_file_location("make_live_shot", TOOL)
make_live_shot = importlib.util.module_from_spec(spec)
spec.loader.exec_module(make_live_shot)


def toc_version():
    return re.search(r"(?m)^## Version:\s*(\S+)", (ROOT / "addon" / "StatTracker" / "StatTracker.toc").read_text(encoding="utf-8")).group(1)


@pytest.mark.parametrize("lang", ["en", "de"])
def test_the_rows_are_what_the_addon_writes_for_the_invented_session(lang):
    title, rows = make_live_shot.window_content(lang)
    assert title == "StatTracker v" + toc_version()
    assert rows[0] == {"label": "Mirella-Dawnspire", "value": "", "state": "HEAD"}
    live = [r for r in rows if r["state"] == "LIVE"]
    assert len(live) == 9                                            # five statistics, session gold, played time, two rates
    assert not any(r["state"] in ("UNKNOWN", "SNAPSHOT") for r in rows)
    assert [r["state"] for r in rows[-2:]] == ["FOOT", "FOOT"]
    values = {r["label"]: r["value"] for r in rows}
    assert values[make_live_shot.NAMES[lang][107]] == "4210 (+71)"
    assert values[make_live_shot.NAMES[lang][60]] == "37 (+1)"
    assert "(+132 g 40 s 15 c)" in values[make_live_shot.NAMES[lang][328]]
    assert ("(geschaetzt)" if lang == "de" else "(estimated)") in "".join(v for v in values.values())


def test_the_picture_names_only_the_invented_demo_character():
    _, rows = make_live_shot.window_content("en")
    key = rows[0]["label"]
    assert key in (ROOT / "tools" / "make_demo.py").read_text(encoding="utf-8")    # one of the invented characters of the demo data


def test_the_picture_is_a_png_of_the_size_of_the_window_and_is_made_the_same_every_time(tmp_path):
    title, rows = make_live_shot.window_content("en")
    a, b = tmp_path / "a.png", tmp_path / "b.png"
    width, height = make_live_shot.draw(title, rows, a)
    make_live_shot.draw(title, rows, b)
    data = a.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n" and data == b.read_bytes()
    window_height = make_live_shot.TOP + len(rows) * make_live_shot.ROW_H + make_live_shot.PAD
    assert (width, height) == ((make_live_shot.WIDTH + 2 * make_live_shot.MARGIN) * make_live_shot.SCALE,
                               (window_height + 2 * make_live_shot.MARGIN) * make_live_shot.SCALE)


def test_the_tool_writes_both_languages(tmp_path):
    assert make_live_shot.main(["--out", str(tmp_path)]) == 0
    assert sorted(p.name for p in tmp_path.iterdir()) == ["live-de.png", "live-en.png"]
