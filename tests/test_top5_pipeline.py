# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)
# The tiles of the Top 5 block on their way from the settings (config.top5) into the stats page: the argument --top5 of the import (the window hands
# over its settings, the parser reads no settings file), the page that is written again from the database (outputs.rebuild_outputs) and the data of the page.

import json
import re

import pytest

from app import stat_parser
from pages import outputs
from test_stat_parser import SAMPLE

GOLD = {"stat": 2, "agg": "sum", "by": "all", "value": ""}
PLAYED = {"stat": -1, "agg": "max", "by": "char", "value": "Alice-Realm"}


@pytest.fixture
def sv(tmp_path):
    p = tmp_path / "StatTracker.lua"
    p.write_text(SAMPLE, encoding="utf-8")
    return p


def run(sv, tmp_path, *extra):
    stat_parser.main(["--input", str(sv), "--db", str(tmp_path / "x.db"), "--output", str(tmp_path / "out" / "x.html"), *extra])
    return (tmp_path / "out" / "x.html").read_text(encoding="utf-8")


def data_of(text):
    return json.loads(re.search(r"const DATA = (.*?);\s*const \$ =", text, re.S).group(1).replace("<\\/", "</"))


def test_without_the_argument_the_page_has_no_block_and_no_field(sv, tmp_path):
    text = run(sv, tmp_path)
    assert 'id="top5"' not in text and "top5" not in data_of(text)


def test_the_import_writes_the_tiles_it_is_given_into_the_page(sv, tmp_path):
    text = run(sv, tmp_path, "--top5", json.dumps([GOLD, PLAYED]))
    assert data_of(text)["top5"] == [GOLD, PLAYED]
    block = text.split('id="top5"')[1].split('<div data-slot="1">')[0]
    assert "Gold earned" in block and "12.05" in block and "Alice-Realm" in block and "25.0" in block       # 12g 5s 3c = 12.05 g, 90061 s = 25.0 h


def test_the_page_written_again_from_the_database_takes_the_tiles_it_is_given(sv, tmp_path):
    run(sv, tmp_path)
    html = tmp_path / "out" / "again.html"
    payload, _ = outputs.rebuild_outputs(tmp_path / "x.db", html, top5=[PLAYED])
    assert payload["top5"] == [PLAYED] and 'id="top5"' in html.read_text(encoding="utf-8") and "Gold earned" not in html.read_text(encoding="utf-8").split('id="top5"')[1].split('id="rates"')[0]
    payload, _ = outputs.rebuild_outputs(tmp_path / "x.db", html)
    assert "top5" not in payload and 'id="top5"' not in html.read_text(encoding="utf-8")


def test_the_tiles_in_the_payload_are_copies(sv, tmp_path):
    run(sv, tmp_path)
    tiles = [dict(GOLD)]
    payload, _ = outputs.rebuild_outputs(tmp_path / "x.db", tmp_path / "out" / "again.html", top5=tiles)
    payload["top5"][0]["stat"] = 99
    assert tiles == [GOLD]


def test_tiles_that_are_not_shaped_like_one_are_dropped_and_a_text_that_is_no_json_gives_a_warning(sv, tmp_path, capsys):
    text = run(sv, tmp_path, "--top5", json.dumps([GOLD, "x", {"stat": "no"}]))
    assert data_of(text)["top5"] == [GOLD] and "top5" not in capsys.readouterr().out
    text = run(sv, tmp_path, "--top5", json.dumps({"stat": 2}))
    assert 'id="top5"' not in text and "WARNING" not in capsys.readouterr().out
    text = run(sv, tmp_path, "--top5", "{not json")
    assert 'id="top5"' not in text and "top5" not in data_of(text)
    assert "WARNING: the tiles of the Top 5 are not valid JSON" in capsys.readouterr().out


def test_the_parser_reads_no_settings_file(sv, tmp_path, monkeypatch):
    """A settings file of the machine must not change a page that was asked for without tiles."""
    from core import config
    monkeypatch.setattr(config, "load", lambda: (_ for _ in ()).throw(AssertionError("the parser must not read the settings")))
    assert 'id="top5"' not in run(sv, tmp_path)
