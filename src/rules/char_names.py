#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)
# char_names.py
# StatTracker - how a character is shown to the person (the surname, when the scan has one, follows the name): the key of a character is "Name-Realm" (the addon writes UnitName and GetRealmName); the pages, the
# history pages, the Excel file and the window show "Name / Realm" instead. The one place that knows this: split_key and display. Only the text that is shown
# changes, the key stays what the database, the blacklist, the rules and the file names of the history pages use. Pure calculation: standard library only,
# no files.

SEPARATOR = " / "


def split_key(key) -> tuple:
    """(name, realm) of a key. A character name has no "-" but a realm name can, so the key is split at the FIRST one; a key without one, or with
    nothing on one side of it, is all name (and no realm)."""
    text = str(key)
    name, sep, realm = text.partition("-")
    if sep and name and realm:
        return name, realm
    return text, ""


def display(key, surname=None) -> str:
    """The text a character is shown with: "Name / Realm", or the key itself when it has no realm part. `surname` (the last name the addon wrote with the
    scan, data contract 5; None or empty for an older scan) follows the name: "Name Surname / Realm"."""
    name, realm = split_key(key)
    if isinstance(surname, str) and surname.strip() and name:
        name = f"{name} {surname.strip()}"
    return f"{name}{SEPARATOR}{realm}" if realm else name
