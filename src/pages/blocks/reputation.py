#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)
# reputation.py
# StatTracker - the block "Reputation" of the stats page: the last scan of every ticked character, the factions in the order of the game
# (merged, see rep_rules), a search for a faction, the account-wide factions once across all characters, and in every cell the level, how far to
# the next one (a bar) and the paragon round. It replaces setupRep/renderRep/repCell of the page script (same elements, ids and classes).
# The block is left out (empty text) when the payload has no reputation. render() gives the whole block with every character ticked; handle()
# answers "query" (the search was typed in) and "selection" (the ticked characters changed) with the parts that changed:
# repNone, repWrap and repMissing. No state of its own: the search text comes with the message (a snapshot writes it again from View.controls). Needs markup, view, rep_rules, numfmt.

from pages.blocks.markup import esc, fmt, plain, ui
from pages.blocks.view import View
from rules import numfmt
from rules import rep_rules as rules

USES_SELECTION = True
EMPTY = "--"                                  # what the page shows for a missing entry (the same sign as the statistics table)


def _num(payload, value) -> str:
    return numfmt.number(value, payload.get("lang") or "en")


def _count(value) -> str:
    return value if isinstance(value, str) else plain(value)


def _bar(share, extra="") -> str:
    return f'<div class="rbar{" " + extra if extra else ""}"><i style="width: {rules.bar_percent(share)}%;"></i></div>'


def _label(payload, label) -> str:
    kind = label[0]
    if kind == "renown":
        return fmt(ui(payload, "rep_renown"), n=_count(label[1]), max=_count(label[2]))
    if kind == "level":
        return fmt(ui(payload, "rep_level"), n=_count(label[1]), max=_count(label[2]))
    if kind == "name":
        return label[1]
    if kind == "standing":
        return fmt(ui(payload, "rep_standing_n"), n=_count(label[1]))
    return EMPTY if kind == "empty" else ""


def _cell(payload, entry) -> str:
    """The inside of one cell: the level, how far to the next one (text and bar), and the paragon progress when there is one."""
    cell = rules.cell_of(entry, (payload.get("names") or {}).get("standing") or {})
    detail = ""
    if cell.detail:
        detail = ui(payload, "rep_max") if cell.detail[0] == "max" else f"{_num(payload, cell.detail[1])} / {_num(payload, cell.detail[2])}"
    parts = [f"<div>{esc(_label(payload, cell.label))}</div>"]
    if detail:
        parts.append(f'<span class="small">{esc(detail)}</span>')
    if cell.share is not None:
        parts.append(_bar(cell.share))
    if cell.paragon:
        done, threshold, share, pending = cell.paragon
        text = fmt(ui(payload, "rep_paragon"), value=_num(payload, done), threshold=_num(payload, threshold))
        if pending:
            text += " · " + ui(payload, "rep_paragon_ready")
        parts.append(f'<span class="small">{esc(text)}</span>')
        parts.append(_bar(share, "par"))
    return "<div>" + "".join(parts) + "</div>"


def _head(payload, chars) -> str:
    cells = [f'<th>{esc(ui(payload, "rep_col_faction"))}</th>']
    for char in chars:
        small = ""
        for parts in ((char.get("race"), char.get("class"), char.get("level")), (char.get("scanned_at"),)):
            text = " · ".join(str(p) for p in parts if p)
            if text:
                small += f'<span class="small">{esc(text)}</span>'
        cells.append(f'<th>{esc(char["key"])}{small}</th>')
    return "<tr>" + "".join(cells) + "</tr>"


def _body(payload, chars, rep_chars, shown) -> str:
    lists = {c["key"]: {e["id"]: e for e in rep_chars[c["key"]]} for c in chars if c["key"] in rep_chars}
    rows = []
    for row in shown:
        if row.type != "row":
            css = "rcat" if row.type == "cat" else "rsub"
            rows.append(f'<tr><td colspan="{len(chars) + 1}" class="{css}">{esc(row.name)}</td></tr>')
            continue
        name_class = "rname" + (" rhead" if row.first.get("hdr") else "")
        account = f'<span class="small">{esc(ui(payload, "rep_account"))}</span>' if row.wide else ""
        cells = [f'<td class="{name_class}">{esc(row.name)}{account}</td>']
        if row.wide:
            cells.append(f'<td class="rcell" colspan="{len(chars)}">{_cell(payload, row.wide)}</td>')
        else:
            for char in chars:
                entry = lists.get(char["key"], {}).get(row.id)
                cells.append(f'<td class="rcell">{_cell(payload, entry) if entry else EMPTY}</td>')
        rows.append("<tr>" + "".join(cells) + "</tr>")
    return "".join(rows)


def _updates(payload, view, query=""):
    rep = payload["rep"]
    rep_chars = rep["chars"]
    chars = view.chars()
    have = [c for c in chars if c["key"] in rep_chars]
    shown = rules.visible_rows(rules.build_rows(have, rep_chars, rep.get("defs") or {}), query)
    if not chars:
        none = ui(payload, "rep_none_selected")
    else:
        none = ui(payload, "rep_no_match") if have and not shown else ""
    missing = [c["key"] for c in chars if c["key"] not in rep_chars]
    table = ('<table id="rpt"><thead>' + _head(payload, chars) + "</thead><tbody>" + _body(payload, chars, rep_chars, shown) + "</tbody></table>"
             if shown else '<table id="rpt"><thead></thead><tbody></tbody></table>')
    return [{"id": "repNone", "html": esc(none), "hidden": not none},
            {"id": "repWrap", "html": table, "hidden": not shown},
            {"id": "repMissing", "html": esc(fmt(ui(payload, "rep_missing"), names=", ".join(missing)) if missing else "")}]


def render(payload, view=None, slot=None, **_) -> str:
    """The whole block with the characters ticked in `view` (all of them at the start) and the search text its controls last held; empty text
    when the page has no reputation."""
    rep = payload.get("rep")
    if not rep or rep.get("chars") is None:
        return ""
    view = view or View(payload)
    query = str((view.controls.get(slot) or {}).get("query") or "")
    value = f' value="{esc(query)}"' if query else ""
    parts = {u["id"]: u for u in _updates(payload, view, query)}
    return (
        '<details class="rates" id="rep">\n'
        f'  <summary id="repTitle">{esc(ui(payload, "rep_title"))}</summary>\n'
        f'  <div class="gbar"><input type="search" id="repQ" data-name="query" data-action="query" placeholder="{esc(ui(payload, "rep_search"))}"{value}></div>\n'
        f'  <div class="gnone" id="repNone"{" hidden" if parts["repNone"]["hidden"] else ""}>{parts["repNone"]["html"]}</div>\n'
        f'  <div class="rwrap" id="repWrap"{" hidden" if parts["repWrap"]["hidden"] else ""}>{parts["repWrap"]["html"]}</div>\n'
        f'  <div class="note" id="repMissing">{parts["repMissing"]["html"]}</div>\n'
        f'  <div class="note" id="repNote">{esc(ui(payload, "rep_note"))}</div>\n'
        '</details>')


def handle(payload, view, slot, action, args):
    """The parts of the block that change after `action` ("query": the search text is in controls["query"]; "selection": the ticked characters)."""
    rep = payload.get("rep")
    if not rep or rep.get("chars") is None or action not in ("query", "selection"):
        return []
    return _updates(payload, view, (args.get("controls") or {}).get("query") or "")
