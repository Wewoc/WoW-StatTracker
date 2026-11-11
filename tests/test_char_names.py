# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)
# rules/char_names.py: how a character is shown ("Name / Realm"); the key is only split for the text, never changed. Also that the pages and the history pages
# carry the label and that a payload made by hand without one still shows the key.

import pytest

from pages.blocks import char_picker, rates, stat_table
from pages.blocks.markup import label
from rules import char_names


@pytest.mark.parametrize("key, name, realm, shown", [
    ("Catless-CAMWOW EU4 Realm 3 PvE", "Catless", "CAMWOW EU4 Realm 3 PvE", "Catless / CAMWOW EU4 Realm 3 PvE"),
    ("Alice-Realm", "Alice", "Realm", "Alice / Realm"),
    ("Name-Realm-With-Dashes", "Name", "Realm-With-Dashes", "Name / Realm-With-Dashes"),     # split at the FIRST "-": a realm name can have one
    ("NoRealm", "NoRealm", "", "NoRealm"),
    ("-Realm", "-Realm", "", "-Realm"),                                                        # nothing before the dash: nothing is split
    ("Name-", "Name-", "", "Name-"),
    ("", "", "", ""),
])
def test_a_key_is_split_at_the_first_dash_and_shown_as_name_and_realm(key, name, realm, shown):
    assert char_names.split_key(key) == (name, realm)
    assert char_names.display(key) == shown


@pytest.mark.parametrize("key, surname, shown", [
    ("Catless-CAMWOW EU4 Realm 3 PvE", "Everbeen", "Catless Everbeen / CAMWOW EU4 Realm 3 PvE"),
    ("Catless-CAMWOW EU4 Realm 3 PvE", None, "Catless / CAMWOW EU4 Realm 3 PvE"),
    ("Catless-CAMWOW EU4 Realm 3 PvE", "", "Catless / CAMWOW EU4 Realm 3 PvE"),
    ("Catless-CAMWOW EU4 Realm 3 PvE", "  ", "Catless / CAMWOW EU4 Realm 3 PvE"),
    ("Catless-CAMWOW EU4 Realm 3 PvE", 5, "Catless / CAMWOW EU4 Realm 3 PvE"),            # not a text: no surname
    ("NoRealm", "Everbeen", "NoRealm Everbeen"),
])
def test_the_surname_of_the_newest_scan_follows_the_name(key, surname, shown):
    assert char_names.display(key, surname) == shown


def test_the_separator_is_one_place():
    assert char_names.SEPARATOR == " / " and char_names.display("A-B") == "A" + char_names.SEPARATOR + "B"


def test_a_block_shows_the_label_and_keeps_the_key_as_the_data():
    payload = {"chars": [{"key": "Alice-Realm", "label": "Alice / Realm", "class": "Mage", "level": 80}], "ui": {}}
    html = char_picker.render(payload)
    assert "Alice / Realm</label>" in html and 'data-name="Alice-Realm"' in html and 'id="chk_Alice-Realm"' in html
    assert 'data-key="Alice-Realm">Alice / Realm' in stat_table._head(payload, payload["chars"])


def test_a_payload_made_by_hand_without_a_label_shows_the_key():
    char = {"key": "Alice-Realm"}
    assert label(char) == "Alice-Realm" and label({"key": "A-B", "label": ""}) == "A-B"
    assert "Alice-Realm</label>" in char_picker.render({"chars": [char], "ui": {}})
