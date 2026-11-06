#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)
# rates.py
# StatTracker - the block "Rates per hour played" of the stats page: one row per character (and a total row on top) with the rates of
# stat_derive (kills, honorable kills, deaths, gold per hour). A rate that cannot be calculated shows a dash and the reason. The numbers
# come from the payload ("derived", worked out by page_payload with stat_derive); this block only writes them, in the number format of the
# page language. It replaces renderRates of the page script (same elements, ids and classes). Static: it does not change with the characters
# ticked above. Left out (empty text) when the page has no characters or no rates. Needs markup and numfmt.

from pages.blocks.markup import esc, fmt, plain, ui
from rules import numfmt

DASH = "–"


def _cell(payload, result, is_total) -> str:
    """A rate; the total also says how many characters it is made of. Without a rate: a dash and the reason."""
    if result and "rate" in result:
        text = numfmt.rate(result["rate"], payload.get("lang") or "en")
        small = fmt(ui(payload, "rates_total_of"), used=result.get("used"), of=result.get("of")) if is_total else ""
    else:
        text, small = DASH, (result or {}).get("why") or ""
    return f'<td class="num">{esc(text)}' + (f'<span class="small">{esc(small)}</span>' if small else "") + "</td>"


def render(payload, view=None, slot=None, **_) -> str:
    chars = payload.get("chars") or []
    derived = payload.get("derived") or {}
    roles = derived.get("roles") or []
    if not chars or not roles:
        return ""
    head = f'<th>{esc(ui(payload, "rates_col_char"))}</th>' + "".join(f'<th class="num">{esc(r["label"])}</th>' for r in roles)
    rows = [f'<tr class="total"><td>{esc(ui(payload, "rates_total"))}</td>' + "".join(_cell(payload, r["total"], True) for r in roles) + "</tr>"]
    for char in chars:
        who = " · ".join(str(part) for part in (char.get("race"), char.get("class"), char.get("level")) if part)
        rows.append(f'<tr><td>{esc(char["key"])}<span class="small">{esc(who)}</span></td>'
                    + "".join(_cell(payload, r["chars"].get(char["key"]), False) for r in roles) + "</tr>")
    hours = plain(derived.get("min_played_seconds", 3600) / 3600)
    return (
        '<details class="rates" id="rates">\n'
        f'  <summary id="ratesTitle">{esc(ui(payload, "rates_title"))}</summary>\n'
        f'  <div class="rwrap"><table id="rt"><thead><tr>{head}</tr></thead><tbody>{"".join(rows)}</tbody></table></div>\n'
        f'  <div class="note" id="ratesNote">{esc(fmt(ui(payload, "rates_note"), hours=hours))}</div>\n'
        '</details>')
