#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)
# numfmt.py
# StatTracker - numbers with a fixed count of decimals as the stats page shows them in German and in English: the same text as
# the page script made with toLocaleString(lang, {minimumFractionDigits: d, maximumFractionDigits: d}). The browser rounds on
# the shortest decimal text of the number (1.005 gives 1.01) and half away from zero, so this does the same; a test compares it
# with the real browser. Pure calculation, standard library only.

import math
from decimal import ROUND_HALF_UP, Decimal, localcontext

SEPARATORS = {"de": (".", ","), "en": (",", ".")}      # (thousands, decimal); any other language is shown as English


def fixed(value, digits: int, lang: str = "en") -> str:
    """`value` with exactly `digits` decimals, grouped by thousands, in the number format of `lang`. A negative number keeps
    its minus even when it rounds to zero ("-0.0"), as the browser does. NaN and infinity are errors (the page never has them)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"not a finite number: {value!r}")
    negative = value < 0 or (isinstance(value, float) and math.copysign(1.0, value) < 0)
    with localcontext() as context:
        context.prec = 100
        rounded = Decimal(repr(abs(value))).quantize(Decimal(1).scaleb(-digits), rounding=ROUND_HALF_UP)
    whole, _, fraction = format(rounded, "f").partition(".")
    thousands, decimal = SEPARATORS.get(lang, SEPARATORS["en"])
    text = f"{int(whole):,}".replace(",", thousands)
    if fraction:
        text += decimal + fraction
    return "-" + text if negative else text


def rate(value, lang: str = "en") -> str:
    """A rate per hour: no decimals from 100 on (and for 0), one from 10, two from 0.1, three below."""
    digits = 0 if value == 0 or value >= 100 else 1 if value >= 10 else 2 if value >= 0.1 else 3
    return fixed(value, digits, lang)


def number(value, lang: str = "en") -> str:
    """The number as `toLocaleString(lang)` writes it without options: grouped by thousands, up to three decimals, no trailing zeros."""
    text = fixed(value, 3, lang)
    decimal = SEPARATORS.get(lang, SEPARATORS["en"])[1]
    if decimal in text:
        text = text.rstrip("0").rstrip(decimal)
    return text
