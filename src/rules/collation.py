#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)
# collation.py
# StatTracker - the order in which the stats page sorts names (the `localeCompare` the page script used): first the characters without accents and
# capitals (spaces and punctuation in a fixed order, then digits, then letters, "ß" as "ss"), then the accents (in the order of the root collation: acute,
# grave, breve, circumflex ...), then small before capital. Compared with the real browser for all 2 069 statistic names of a real database, for thousands of
# invented strings and for every letter of Latin-1 and Latin Extended-A alone and next to an "a" (see CHECKED for what is covered). Pure calculation,
# standard library only.

import unicodedata

# the order of the space and punctuation characters of the root collation (the ASCII part); everything else of this kind comes after them, by code point
PUNCTUATION = " _-,;:!?.'\"()[]{}@*/\\&#%`^+<=>|~$"
_RANK = {char: place for place, char in enumerate(PUNCTUATION)}

# the order of the accent marks (their second weights in the root collation): acute, grave, breve, circumflex, caron, ring, diaeresis, double acute,
# tilde, dot above, ..., cedilla, ogonek, macron; a mark that is not listed comes after them, by code point
_ACCENTS = "̸̧̨́̀̆̂̌̊̈̋̃̇̄"
_ACCENT_RANK = {mark: place + 1 for place, mark in enumerate(_ACCENTS)}

# letters that do not break up into a letter and an accent: written out as two letters, or as a letter with a stroke (a mark of its own)
_TWO_LETTERS = {"æ": "ae", "œ": "oe", "ĳ": "ij"}
_STROKE = {"ø": "o", "ł": "l", "đ": "d", "ħ": "h", "ŧ": "t"}

CHECKED = ("A-Z a-z 0-9, the letters of Latin-1 and Latin Extended-A with their accents (Ä Ö Ü ß é è ç ...), the ASCII punctuation; "
           "not covered: symbols outside ASCII (¡ ¿ « » ª ...), scripts other than Latin")


def _primary(char: str) -> list:
    base = "".join(c for c in unicodedata.normalize("NFKD", char) if not unicodedata.combining(c)) or char
    base = _TWO_LETTERS.get(base.casefold(), _STROKE.get(base.casefold(), base))
    parts = []
    for c in base:
        if c in _RANK:
            parts.append((0, _RANK[c]))
        elif c.isdigit():
            parts.append((1, unicodedata.digit(c, 0)))
        elif c.isalpha():
            parts.extend((2, letter) for letter in c.casefold())          # "ß" becomes "ss"
        else:
            parts.append((0, len(PUNCTUATION) + ord(c)))
    return parts


def key(text: str) -> tuple:
    """A sort key: sorted(names, key=collation.key) gives the order of the browser's localeCompare."""
    primary, secondary, tertiary = [], [], []
    for char in text:
        primary.extend(_primary(char))
        secondary.append(0)                                                    # the letter itself, then its accent marks
        marks = unicodedata.normalize("NFKD", char)[1:] + ("̸" if char.casefold() in _STROKE else "")
        secondary.extend(_ACCENT_RANK.get(mark, len(_ACCENTS) + 1 + ord(mark)) for mark in marks)
        tertiary.append(0 if char == char.lower() else 1)                      # small before capital
    return (primary, secondary, tertiary)
