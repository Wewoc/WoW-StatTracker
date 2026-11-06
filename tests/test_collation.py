# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)
# rules/collation.key: the order of names of the stats page. The expectations are what the browser's localeCompare gives (the key was compared with
# the real browser for all 2 069 statistic names of a real database, 5 236 invented strings and every Latin-1/Latin Extended-A letter: no difference
# for what collation.CHECKED names).

import random

import pytest

from rules import collation


def ordered(items):
    return sorted(items, key=collation.key)


def test_small_before_capital_but_the_letter_decides_first():
    assert ordered(["B", "a", "A", "b"]) == ["a", "A", "b", "B"]


def test_the_punctuation_has_a_fixed_order_before_the_digits_and_the_letters():
    marks = list(collation.PUNCTUATION)
    shuffled = random.Random(3).sample(marks, len(marks))
    assert ordered(shuffled) == marks
    assert ordered(["a", "1", "$", " ", "Z", "9", "_"]) == [" ", "_", "$", "1", "9", "a", "Z"]


def test_a_comma_comes_before_a_bracket_as_in_the_names_of_the_game():
    names = ["Höchster Punktestand (Endlos)", "Höchster Punktestand (Endlos, Stufe 90)"]
    assert ordered(names) == [names[1], names[0]]


def test_digits_are_compared_one_by_one_not_as_numbers():
    assert ordered(["Stufe 10", "Stufe 9", "Stufe 1"]) == ["Stufe 1", "Stufe 10", "Stufe 9"]


def test_an_accent_makes_a_letter_come_after_the_plain_one_but_before_the_next_letter():
    assert ordered(["p", "ö", "o", "Ö"]) == ["o", "ö", "Ö", "p"]
    assert ordered(["eb", "éa", "ea", "e"]) == ["e", "ea", "éa", "eb"]


def test_the_accents_have_the_order_of_the_root_collation():
    assert ordered(["ě", "ê", "ĕ", "è", "é", "e"]) == ["e", "é", "è", "ĕ", "ê", "ě"]


def test_the_accent_decides_before_the_capital():
    assert ordered(["dÈ", "Dé"]) == ["Dé", "dÈ"]
    assert ordered(["'È", "'é"]) == ["'é", "'È"]


def test_sharp_s_counts_as_two_s():
    assert ordered(["st", "ß", "sr"]) == ["sr", "ß", "st"]


@pytest.mark.parametrize("letter,plain", [("ø", "o"), ("ł", "l"), ("đ", "d")])
def test_a_letter_with_a_stroke_follows_its_plain_letter(letter, plain):
    assert ordered([letter, plain + "z", plain]) == [plain, letter, plain + "z"]


def test_the_same_text_gives_the_same_key_and_the_key_can_be_compared_with_any_other():
    names = ["Anzahl /jubeln", "Anzahl /LOLs", "", " ", "ä", "A", "0", "ß", "x" * 40]
    assert ordered(names) == ordered(list(reversed(names)))
    assert collation.key("abc") == collation.key("abc") and collation.key("") < collation.key("a")
