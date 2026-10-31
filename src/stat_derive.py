#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)
# stat_derive.py
# Derived statistics: rates per hour of played time, from the newest scan of each character.
#
# Pure calculation: no UI, no database or file access, no project imports (stdlib only).
# It takes the shape of stat_parser.build_payload()["stats"] and returns plain data; the
# caller looks up the texts (label keys, reason codes). Nothing derived is stored,
# value_text in the database stays the source.
#
# Principle: never invent a number. A rate that cannot be computed carries a reason
# code instead of a value:
#   no_played          the scan has no (valid) total played time
#   too_little_played  less played time than the minimum, the rate would be noise
#   no_stat            the statistic is missing or not numeric in this scan
#   no_chars           (account total) no character was usable

import math
from typing import NamedTuple

# Total played time is stored as a pseudo statistic with this ID (stat_parser.PLAYED_STATS;
# a test keeps both in step). Its value_num is in seconds.
PLAYED_TOTAL_ID = -1
MIN_PLAYED_SECONDS = 3600
EMPTY_TEXT = "--"          # what the game shows for a counter that never fired


class Role(NamedTuple):
    key: str            # role name
    ids: tuple          # alias list of stat_ids, newest first (see ROLES)
    label_key: str      # i18n key of the display name (looked up by the caller)
    unit: str           # "count" or "gold"
    scale: int          # raw value / scale = unit shown (copper -> gold)
    dash_is_zero: bool  # "--" counts as 0 (counter that never fired), otherwise "no value"


# Single source for "which statistic means what". Several IDs per role cover an ID that
# Blizzard changes: per scan the first ID with a number counts. New IDs are added by hand,
# never matched by name (names depend on the client language).
# dash_is_zero is only set where "--" was actually seen in real data (PvP kills, deaths).
ROLES = (
    Role("kills_pve", (107,), "derive_kills_pve", "count", 1, False),     # Creatures killed
    Role("kills_pvp", (588,), "derive_kills_pvp", "count", 1, True),      # Honorable kills, total
    Role("deaths", (60,), "derive_deaths", "count", 1, True),             # Total deaths
    Role("gold", (328,), "derive_gold", "gold", 10000, False),            # Gold acquired, total (copper)
)

# i18n keys of the reason codes (see the header); the caller looks the texts up.
REASON_KEYS = {
    "no_played": "derive_reason_no_played",
    "too_little_played": "derive_reason_too_little_played",
    "no_stat": "derive_reason_no_stat",
    "no_chars": "derive_reason_no_chars",
}


def _is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _counter(role, cells):
    """Counter value of a role in one scan, or None.
    cells: {stat_id: (text, number)}. The first alias ID with a number >= 0 counts; if none
    has one and the role allows it, an '--' on any alias counts as 0."""
    dash = False
    for sid in role.ids:
        cell = cells.get(sid)
        if cell is None:
            continue
        text, num = cell[0], cell[1]
        if _is_number(num) and num >= 0:
            return num
        if str(text).strip() == EMPTY_TEXT:
            dash = True
    return 0 if dash and role.dash_is_zero else None


def _char_rate(role, cells, min_played):
    played = cells.get(PLAYED_TOTAL_ID)
    seconds = played[1] if played is not None else None
    if not _is_number(seconds) or seconds <= 0:
        return {"reason": "no_played"}
    if seconds < min_played:
        return {"reason": "too_little_played"}
    count = _counter(role, cells)
    if count is None:
        return {"reason": "no_stat"}
    amount = count / role.scale
    hours = seconds / 3600
    return {"rate": amount / hours, "amount": amount, "hours": hours}


def _total(per_char):
    """Account rate = sum of counters / sum of hours over the usable characters
    (not the mean of the rates: long-played characters weigh more)."""
    usable = [r for r in per_char.values() if "rate" in r]
    result = {"used": len(usable), "of": len(per_char)}
    hours = sum(r["hours"] for r in usable)
    if not usable or hours <= 0:
        result["reason"] = "no_chars"
    else:
        result["rate"] = sum(r["amount"] for r in usable) / hours
    return result


def compute(stats, char_keys, roles=ROLES, min_played=MIN_PLAYED_SECONDS):
    """Rates per played hour for every role and character.

    stats: list of {"id": stat_id, "v": {char_key: [text, number]}} (payload["stats"]).
    char_keys: the characters to report, in order.
    Returns {"min_played_seconds": n, "roles": [{"role", "label_key", "unit",
    "chars": {char_key: {"rate", "amount", "hours"} or {"reason"}},
    "total": {"rate", "used", "of"} or {"reason", "used", "of"}}]}."""
    by_char = {key: {} for key in char_keys}
    for stat in stats:
        for key, cell in stat["v"].items():
            if key in by_char:
                by_char[key][stat["id"]] = cell

    out = []
    for role in roles:
        per_char = {key: _char_rate(role, by_char[key], min_played) for key in char_keys}
        out.append({"role": role.key, "label_key": role.label_key, "unit": role.unit,
                    "chars": per_char, "total": _total(per_char)})
    return {"min_played_seconds": min_played, "roles": out}
