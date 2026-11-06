#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)
# stat_values.py
# StatTracker - how the text of a statistic becomes a number (clean_text, to_number) and how the played time is kept
# (PLAYED_STATS: pseudo statistics with negative IDs; played_labels, fmt_duration). Needs i18n only.
# Moved out of stat_parser.py; the rules are unchanged.

import re

from core.i18n import t


def clean_text(text):
    """WoW escapes (coin icons, colors) -> readable text."""
    text = re.sub(r"\|T[^|]*?(Gold|Silver|Copper)Icon[^|]*?\|t",
                  lambda m: {"Gold": "g", "Silver": "s", "Copper": "c"}[m.group(1)], text)
    text = re.sub(r"\|T.*?\|t", "", text)
    text = re.sub(r"\|c[0-9a-fA-F]{8}", "", text).replace("|r", "")
    return text.strip()


# Text of a coin amount ('12g 5s 3c'): the shape to_number turns into copper. The one place of this rule; the stats page (payload
# field "gold") and the history pages (stat_history) take it from here.
COIN_TEXT = re.compile(r"(?:\d[\d.,]*\s*[gsc]\s*)+")


def is_coin_text(text) -> bool:
    """True when the stored text of a statistic is a coin amount (the page shows such a statistic in gold)."""
    return bool(COIN_TEXT.fullmatch(str(text).strip()))


def to_number(text):
    """Comparable number or None.
    - number with 1-2 decimals ('0.20', '3,5') -> float
    - whole number, thousands groups of exactly 3 digits ('1.234', '12 345') -> int
    - gold/silver/copper ('12g 3s 4c') -> copper
    - anything else (durations, percent, '--') -> None (text comparison only)"""
    s = clean_text(text)
    if s in ("", "--"):
        return None
    m = re.fullmatch(r"(\d+)[.,](\d{1,2})", s)
    if m:
        return float(f"{m.group(1)}.{m.group(2)}")
    if re.fullmatch(r"\d+|\d{1,3}(?:[.,\s\u00a0\u202f]\d{3})+", s):
        return int(re.sub(r"\D", "", s))
    if COIN_TEXT.fullmatch(s):
        mult = {"g": 10000, "s": 100, "c": 1}
        total = 0
        for num, unit in re.findall(r"(\d[\d.,]*)\s*([gsc])", s):
            total += int(re.sub(r"\D", "", num)) * mult[unit]
        return total
    return None


# Played time (from TIME_PLAYED_MSG) is kept as pseudo statistics with negative IDs,
# so the DB and the pages need no schema change. Names are translated at output
# time (played_labels), whatever language the DB rows were written in.
PLAYED_STATS = (
    (-1, "playedTotal", "played_total"),
    (-2, "playedLevel", "played_level"),
)
PLAYED_CATEGORY_KEY = "played_category"


def played_labels():
    """{stat_id: (name, category)} for the played-time pseudo statistics, current language."""
    return {sid: (t(key), t(PLAYED_CATEGORY_KEY)) for sid, _field, key in PLAYED_STATS}


def fmt_duration(sec):
    d, rest = divmod(int(sec), 86400)
    h, rest = divmod(rest, 3600)
    m, s = divmod(rest, 60)
    return t("duration_fmt", d=d, h=h, m=m, s=s)
