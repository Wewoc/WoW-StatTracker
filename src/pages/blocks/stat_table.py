#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)
# stat_table.py
# StatTracker - the main block of the stats page: the filter row (search, category, "only differences", "hide empty"), the counter ("817 of 2069
# statistics") and the table with one row per statistic and one column per ticked character, the best value of a row marked. It replaces render() of the
# page script (same elements, ids and classes) and takes the place of the three places "filter row", "counter" and "table" of the first numbering (6, 7, 8):
# they share one state, so they are one block (place 8). The rules are in table_rules (which rows, in which order, which value is the best).
# render() gives the whole block as the View says (every character ticked, nothing typed and nothing sorted at the start; the ticked characters, the sorting and the
# controls of the shown page when the snapshot is written); handle() answers "filter" (the search was typed, a choice or a check box
# changed), "sort" (a column head was clicked) and "selection" (the ticked characters changed) with the two parts that change: the counter and the inside
# of the table. The values of the controls come with the message (controls: query, category, only_diff, hide_empty); only the sorting is kept here.
# The search box does not rebuild the table at every key (that took about a second): it asks for "suggest", a short list under the box (name, category,
# number of matches); the table follows when a suggestion is taken, Enter is pressed or the box is emptied ("query" in the controls is the text that was
# applied last, not the text that is in the box).
# Needs markup, view, table_rules.

from pages.blocks.markup import esc, fmt, ui
from pages.blocks.view import View
from rules import table_rules as rules

USES_SELECTION = True


class State:
    def __init__(self):
        self.sort_char = None        # the character whose numbers decide the order, or None
        self.sort_dir = -1           # -1: the biggest first


def new_state() -> State:
    return State()


def _small(char) -> str:
    """Who the character is and when it was scanned: two lines under the name (a line without text is left out)."""
    parts = ""
    for values in ((char.get("race"), char.get("class"), char.get("level")), (char.get("scanned_at"),)):
        text = " · ".join(str(v) for v in values if v)
        if text:
            parts += f'<span class="small">{esc(text)}</span>'
    return parts


def _head(payload, chars) -> str:
    cells = [f'<th data-action="sort" data-key="">{esc(ui(payload, "col_cat"))}</th>', f'<th data-action="sort" data-key="">{esc(ui(payload, "col_stat"))}</th>']
    cells += [f'<th class="num" data-action="sort" data-key="{esc(c["key"])}">{esc(c["key"])}{_small(c)}</th>' for c in chars]
    return "<thead><tr>" + "".join(cells) + "</tr></thead>"


def _row(stat, chars) -> str:
    cells = [stat["v"].get(c["key"]) for c in chars]
    best = rules.best_number(cells)
    tds = "".join(
        f'<td class="num{" best" if best is not None and cell and cell[1] == best else ""}">{esc(cell[0]) if cell else rules.DASH}</td>' for cell in cells)
    return f'<tr><td class="cat">{esc(stat["cat"])}</td><td>{esc(stat["name"])}</td>{tds}</tr>'


def _parts(payload, view, state, controls):
    """(the counter text, the inside of the table) for the ticked characters, the controls and the sorting."""
    stats = payload.get("stats") or []
    chars = view.chars()
    rows = rules.filter_stats(stats, [c["key"] for c in chars], (controls.get("query") or ""), controls.get("category") or "",
                              controls.get("only_diff") is True, controls.get("hide_empty") is not False)
    rows = rules.sort_stats(rows, state.sort_char, state.sort_dir)
    count = fmt(ui(payload, "count"), shown=len(rows), total=len(stats))
    return count, _head(payload, chars) + "<tbody>" + "".join(_row(stat, chars) for stat in rows) + "</tbody>"


def _updates(payload, view, state, controls) -> list:
    count, table = _parts(payload, view, state, controls)
    return [{"id": "count", "html": esc(count)}, {"id": "t", "html": table}]


def _suggestions(payload, view, controls, text) -> list:
    """The list under the search box for what has been typed: the statistics (name, category below), and a last line with the number of matches
    (or "No matches"). Nothing, and hidden, under two characters. `text` is what is in the box (not yet applied to the table)."""
    shown, total = rules.suggest(payload.get("stats") or [], [c["key"] for c in view.chars()], text, controls.get("category") or "",
                                 controls.get("only_diff") is True, controls.get("hide_empty") is not False)
    if len(text.strip()) < rules.SUGGEST_MIN:
        return [{"id": "qList", "html": "", "hidden": True}]
    items = "".join(f'<li role="option" data-value="{esc(s["name"])}">{esc(s["name"])}<span class="small">{esc(s["cat"])}</span></li>' for s in shown)
    last = fmt(ui(payload, "suggest_total"), n=total) if total else ui(payload, "suggest_none")
    return [{"id": "qList", "html": items + f'<li class="info">{esc(last)}</li>', "hidden": False}]


def render(payload, view=None, slot=None, **_) -> str:
    """The whole block: at the start every character ticked, nothing typed or chosen, "hide empty" on, no sorting; for a snapshot what the View holds (the
    controls as the page showed them). Empty text without characters."""
    if not payload.get("chars"):
        return ""
    view = view or View(payload)
    state = view.state(slot, new_state)
    controls = view.controls.get(slot) or {}
    count, table = _parts(payload, view, state, controls)
    query = str(controls.get("query") or "")
    value = f' value="{esc(query)}"' if query else ""
    cats = rules.categories(payload.get("stats") or [])
    chosen = controls.get("category") if controls.get("category") in cats else ""
    categories = "".join(f'<option value="{esc(c)}"{" selected" if c == chosen else ""}>{esc(c)}</option>' for c in cats)
    return (
        '<div class="bar">\n'
        '  <span class="sugg">'
        f'<input type="search" id="q" placeholder="{esc(ui(payload, "search"))}" autocomplete="off"{value} data-name="query" data-action="suggest" data-suggest="qList" '
        f'data-commit="filter" data-delay="80" data-committed="{esc(query)}">'
        '<ul id="qList" class="sugg-list" role="listbox" hidden></ul></span>\n'
        f'  <select id="cat" data-name="category" data-action="filter"><option value="">{esc(ui(payload, "all_cats"))}</option>{categories}</select>\n'
        f'  <label><input type="checkbox" id="diff"{" checked" if controls.get("only_diff") is True else ""} data-name="only_diff" data-action="filter"> <span id="lblDiff">{esc(ui(payload, "only_diff"))}</span></label>\n'
        f'  <label><input type="checkbox" id="hideEmpty"{"" if controls.get("hide_empty") is False else " checked"} data-name="hide_empty" data-action="filter"> <span id="lblEmpty">{esc(ui(payload, "hide_empty"))}</span></label>\n'
        '</div>\n'
        f'<div class="count" id="count">{esc(count)}</div>\n'
        f'<div class="wrap"><table id="t">{table}</table></div>')


def handle(payload, view, slot, action, args):
    """The counter and the table after `action` ("filter", "selection", or "sort" with the character in args["key"], empty for the first two heads)."""
    if action not in ("filter", "selection", "sort", "suggest") or not payload.get("chars"):
        return []
    state = view.state(slot, new_state)
    controls = args.get("controls") or {}
    if action == "suggest":
        return _suggestions(payload, view, controls, str(args.get("value") or ""))
    if action == "sort":
        state.sort_char, state.sort_dir = rules.next_sort(state.sort_char, state.sort_dir, args.get("key"))
    return _updates(payload, view, state, controls)
