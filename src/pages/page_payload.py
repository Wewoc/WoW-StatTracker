#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)
# page_payload.py
# StatTracker - the data of the stats page: build_payload (the newest scan of every character, the statistics,
# the rates of stat_derive, the reputation list, the texts of the page; a statistic with a coin text has "gold": true),
# derived_payload and rep_payload.
# Reads the statistics database through the connection it is given and writes nothing. Needs stat_values,
# stat_derive, i18n and app_info. Moved out of stat_parser.py; the rules are unchanged.

from datetime import datetime

from core import app_info
from core import i18n
from rules import stat_derive
from store import stat_values


def derived_payload(stats, chars, lang):
    """Rates per played hour (stat_derive) with the display texts of `lang` filled in:
    "label" per role, "why" next to every "reason"."""
    derived = stat_derive.compute(stats, [c["key"] for c in chars])
    for role in derived["roles"]:
        role["label"] = i18n.raw(role.pop("label_key"), lang)
        for res in (*role["chars"].values(), role["total"]):
            if "reason" in res:
                res["why"] = i18n.raw(stat_derive.REASON_KEYS[res["reason"]], lang)
    return derived


REP_PAYLOAD_NUMBERS = ("reaction", "standing", "lo", "hi", "level", "max_level", "renown", "earned", "need", "max_renown")
REP_PAYLOAD_PARAGON = (("value", "p_value"), ("threshold", "p_threshold"), ("quest", "p_quest"), ("pending", "p_pending"))


def rep_payload(conn, scan_to_char):
    """The reputation list of the newest scan of every character that has one, for the stats page:
    {"defs": {faction id: name}, "chars": {char key: [entry, ...]}} with the entries in the order of the game, or None
    when no character has a list. An entry carries only what is set: "id", "hdr"/"child"/"aw" (1), "kind", the numbers of
    its kind and "par" (paragon). A character whose newest scan has no list is not in "chars": an older scan is never
    used in its place (the page says "no value")."""
    columns = ", ".join(REP_PAYLOAD_NUMBERS + tuple(column for _, column in REP_PAYLOAD_PARAGON))
    chars = {}
    for row in conn.execute("SELECT scan_id, faction_id, is_header, is_child, account_wide, kind, " + columns
                            + " FROM scan_reputation ORDER BY scan_id, ord"):
        key = scan_to_char.get(row[0])
        if key is None:
            continue
        entry = {"id": row[1]}
        entry.update({name: 1 for name, flag in zip(("hdr", "child", "aw"), row[2:5]) if flag})
        if row[5]:
            entry["kind"] = row[5]
        values = dict(zip(REP_PAYLOAD_NUMBERS + tuple(name for name, _ in REP_PAYLOAD_PARAGON), row[6:]))
        entry.update({name: values[name] for name in REP_PAYLOAD_NUMBERS if values[name] is not None})
        par = {name: values[name] for name, _ in REP_PAYLOAD_PARAGON if values[name] is not None}
        if par:
            entry["par"] = par
        chars.setdefault(key, []).append(entry)
    if not chars:
        return None
    used = {entry["id"] for entries in chars.values() for entry in entries}
    defs = {faction: name for faction, name in conn.execute("SELECT faction_id, name FROM rep_defs") if faction in used}
    return {"defs": defs, "chars": chars}


def build_payload(conn, lang=None, history=None, top5=None):
    """The data of the stats page. history: the links to the history pages (update_history_pages),
    left out of the payload when there are none. top5: the tiles of the Top 5 block (config.top5), left out when there are none."""
    lang = lang or i18n.get_language()
    scans = conn.execute("""
        SELECT s.scan_id, s.char_key, s.scanned_at, s.class, s.level, s.faction,
               s.class_file, s.race, s.race_file
        FROM scans s
        WHERE s.scan_id = (SELECT scan_id FROM scans WHERE char_key = s.char_key
                           ORDER BY scanned_at DESC, scan_id DESC LIMIT 1)
        ORDER BY s.char_key""").fetchall()
    chars = [{"key": r[1], "scanned_at": r[2], "class": r[3], "level": r[4], "faction": r[5],
              "class_file": r[6], "race": r[7], "race_file": r[8]}
             for r in scans]
    scan_to_char = {r[0]: r[1] for r in scans}

    defs = {r[0]: {"id": r[0], "name": r[1], "cat": r[2], "v": {}}
            for r in conn.execute("SELECT stat_id,name,category FROM stat_defs")}
    for sid, (name, cat) in stat_values.played_labels().items():
        if sid in defs:
            defs[sid]["name"], defs[sid]["cat"] = name, cat
    for scan_id, stat_id, text, num in conn.execute(
            "SELECT scan_id,stat_id,value_text,value_num FROM stat_values"):
        if scan_id in scan_to_char and stat_id in defs:
            if stat_id < 0 and num is not None:   # played time: text from the seconds, in the output language
                text = stat_values.fmt_duration(num)
            defs[stat_id]["v"][scan_to_char[scan_id]] = [text, num]
            if stat_values.is_coin_text(text):
                defs[stat_id]["gold"] = True       # the page shows a statistic with a coin text in gold (set once per statistic)

    payload = {"generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
               "lang": lang,
               "ui": i18n.html_strings(lang),
               "names": {"class": i18n.names("class_", lang), "race": i18n.names("race_", lang),
                         "standing": i18n.names("standing_", lang)},
               "app": {"version": app_info.APP_VERSION, "copyright": app_info.COPYRIGHT,
                       "license": app_info.LICENSE_NAME, "site": app_info.SITE_URL},
               "chars": chars,
               "stats": sorted(defs.values(), key=lambda d: (d["cat"], d["name"])),
               "derived": derived_payload(list(defs.values()), chars, lang)}
    rep = rep_payload(conn, scan_to_char)
    if rep:
        payload["rep"] = rep
    if history:
        payload["history"] = history
    if top5:
        payload["top5"] = [dict(tile) for tile in top5]
    return payload
