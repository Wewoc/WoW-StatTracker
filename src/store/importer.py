#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)
# importer.py
# StatTracker - reads the scans out of the parsed SavedVariables table (read_scan, scans_by_char), stores them
# (import_data, refresh_numbers) and says what the import found (import_notes). DATA_VERSION and check_data_version
# are the contract with the addon. Needs db_schema, stat_values and i18n.
# Moved out of stat_parser.py; the rules are unchanged.

import json
import math
import sys
from datetime import datetime

from core.i18n import t
from store import db_schema
from store import stat_values


# The contract between the addon and this parser is StatTrackerDB.version (header of
# StatTracker.lua). The addon writes it for the whole file, so it is a ceiling, not a mark on
# a single scan: a file with a higher number than DATA_VERSION is refused, a missing number is
# accepted (hand-made files, older tests). Raising it goes with the change of the fields.
DATA_VERSION = 4


def check_data_version(db, path):
    """Exits with a message if the data version of the file is higher than this program
    knows or is not a whole number; a missing one passes. main() calls it before the database
    is opened, so a refused file leaves no copy and no change behind."""
    found = db.get("version") if isinstance(db, dict) else None
    if found is None:
        return
    if isinstance(found, bool) or not isinstance(found, int) or found > DATA_VERSION:
        sys.exit(t("parse_err_data_too_new", path=path, found=found, known=DATA_VERSION))


def _name_or_none(value):
    """Display text from the addon (class file, race): a non-empty string, otherwise NULL.
    A scan from an older addon has none; a wrong type is not worth stopping the import for."""
    return value.strip() if isinstance(value, str) and value.strip() else None


def _int_or_none(value):
    """A whole number from the addon, otherwise NULL. A bool is not a number."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return None


def _number_or_none(value):
    """A finite number from the addon (item level 276.5), otherwise NULL."""
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return None
    return value


def _flag(value):
    """The marks of the addon (category, sub category, account wide) are true or absent."""
    return 1 if value is True else 0


def _sequence(value):
    """The values of a positional Lua table in their order. LuaReader returns every table as a dict, a positional
    one with the keys 1..n; anything else (text, a key that is not a whole number) is not a sequence: None."""
    if not isinstance(value, dict) or not all(isinstance(k, int) and not isinstance(k, bool) for k in value):
        return None
    return [value[k] for k in sorted(value)]


GEAR_SLOTS = range(1, 20)                       # inventory slots the addon reads
REP_KINDS = ("std", "friend", "major")
# the numbers an entry of each kind carries: column name -> field of the addon
REP_FIELDS = {"std": {"reaction": "reaction", "standing": "standing", "lo": "lo", "hi": "hi"},
              "friend": {"standing": "standing", "lo": "lo", "hi": "hi", "level": "level", "max_level": "maxLevel"},
              "major": {"renown": "renown", "earned": "earned", "need": "need", "max_renown": "maxRenown"}}


def _item_stats(value):
    """{ITEM_MOD_...: number} without what is not a text key with a number."""
    if not isinstance(value, dict):
        return None
    stats = {k: v for k, v in value.items() if isinstance(k, str) and _number_or_none(v) is not None}
    return stats or None


def _read_gear(value):
    """(rows, skipped): the equipped items of a scan. A slot outside 1..19, an entry that is not a table or has no item id
    is skipped and counted (a nil gap is no entry); a field of the wrong type is NULL."""
    if value is None:
        return [], 0
    if not isinstance(value, dict):
        return [], 1
    rows, skipped = [], 0
    for slot, item in sorted(value.items(), key=lambda kv: str(kv[0])):
        if item is None:
            continue                                        # WoW writes a gap in the table as "nil,": an empty slot, not an error
        item_id = _int_or_none(item.get("itemID")) if isinstance(item, dict) else None
        if _int_or_none(slot) not in GEAR_SLOTS or item_id is None:
            skipped += 1
            continue
        up = item.get("upgrade") if isinstance(item.get("upgrade"), dict) else {}
        gems = _sequence(item.get("gems")) if item.get("gems") is not None else None
        if gems is not None and any(_int_or_none(g) is None for g in gems):
            gems = None                                     # one unreadable id would shift the others: all or nothing
        rows.append({"slot": _int_or_none(slot), "item_id": item_id,
                     "name": _name_or_none(item.get("name")), "quality": _int_or_none(item.get("quality")),
                     "ilvl": _int_or_none(item.get("ilvl")), "icon_id": _int_or_none(item.get("iconID")),
                     "enchant_id": _int_or_none(item.get("enchantID")),
                     "enchant_text": _name_or_none(item.get("enchantText")),
                     "upg_track_id": _int_or_none(up.get("trackID")), "upg_track": _name_or_none(up.get("track")),
                     "upg_level": _int_or_none(up.get("level")), "upg_max": _int_or_none(up.get("max")),
                     "sockets": _int_or_none(item.get("sockets")),
                     "gem_ids": None if gems is None else [_int_or_none(g) for g in gems],
                     "stats": _item_stats(item.get("stats"))})
    return rows, skipped


def _read_rep(value):
    """(rows, skipped): the reputation list of a scan in the order of the game. An entry without a faction id or
    position, with a position seen before, or of an unknown kind is skipped and counted."""
    if value is None:
        return [], 0
    entries = _sequence(value)
    if entries is None:
        return [], 1
    rows, skipped, seen = [], 0, set()
    for e in entries:
        faction = _int_or_none(e.get("id")) if isinstance(e, dict) else None
        ord_ = _int_or_none(e.get("ord")) if isinstance(e, dict) else None
        kind = e.get("kind") if isinstance(e, dict) else None
        if faction is None or faction <= 0 or ord_ is None or ord_ < 1 or ord_ in seen \
                or (kind is not None and kind not in REP_KINDS):
            skipped += 1
            continue
        seen.add(ord_)
        row = {"ord": ord_, "faction_id": faction, "is_header": _flag(e.get("hdr")), "is_child": _flag(e.get("child")),
               "account_wide": _flag(e.get("aw")), "kind": kind}
        for column in ("reaction", "standing", "lo", "hi", "level", "max_level", "renown", "earned", "need", "max_renown",
                       "p_value", "p_threshold", "p_quest", "p_pending"):
            row[column] = None
        for column, field in REP_FIELDS.get(kind, {}).items():
            row[column] = _int_or_none(e.get(field))
        par = e.get("paragon")
        if isinstance(par, dict):
            row.update(p_value=_int_or_none(par.get("value")), p_threshold=_int_or_none(par.get("threshold")),
                       p_quest=_int_or_none(par.get("quest")),
                       p_pending=None if not isinstance(par.get("pending"), bool) else int(par["pending"]))
        rows.append(row)
    return rows, skipped


def read_scan(c):
    """One scan of the file (the entry of `chars`, or one of `history`) as checked values, or None when it is not a
    scan at all (no table, no statistics, no scan time). The parts added by version 4 are optional: a field of the
    wrong type is NULL, an unusable gear or reputation entry is skipped and counted in "skipped"."""
    stats = c.get("stats") if isinstance(c, dict) else None
    if not isinstance(stats, dict) or not stats or "scannedAt" not in c:
        return None
    gear, skipped_gear = _read_gear(c.get("gear"))
    rep, skipped_rep = _read_rep(c.get("rep"))
    return {"at": c["scannedAt"], "class": c.get("class"), "level": c.get("level"), "faction": c.get("faction"),
            "class_file": _name_or_none(c.get("classFile")), "race": _name_or_none(c.get("race")),
            "race_file": _name_or_none(c.get("raceFile")), "stats": stats, "raw": c,
            "spec_id": _int_or_none(c.get("specID")), "spec_name": _name_or_none(c.get("specName")),
            "role": _name_or_none(c.get("role")), "ilvl_total": _number_or_none(c.get("ilvlTotal")),
            "ilvl_equipped": _number_or_none(c.get("ilvlEquipped")),
            "gear": gear, "rep": rep, "skipped": skipped_gear + skipped_rep}


def scans_by_char(db):
    """{char key: [scan, ...] oldest first}: the newest scan of `chars` and the older ones of `history`, all checked by
    read_scan. Anything that is not a scan stops the import (it has not touched the database yet)."""
    chars, history = db.get("chars"), db.get("history")
    if history is not None and not isinstance(history, dict):
        sys.exit(t("parse_err_history_table"))
    found = {}
    for key, c in chars.items():
        scan = read_scan(c)
        if scan is None:
            sys.exit(t("parse_err_incomplete_char", key=key))
        found.setdefault(key, []).append(scan)
    for key, entries in (history or {}).items():
        sequence = _sequence(entries)
        if sequence is None:
            sys.exit(t("parse_err_history_list", key=key))
        for n, c in enumerate(sequence, 1):
            scan = read_scan(c)
            if scan is None:
                sys.exit(t("parse_err_incomplete_history", key=key, n=n))
            found.setdefault(key, []).append(scan)
    for scans in found.values():
        scans.sort(key=lambda s: str(s["at"]))             # oldest first, so the numbers in the database follow the time
    return found


def _json_or_none(value):
    return None if value is None else json.dumps(value, sort_keys=True, separators=(",", ":"))




def store_details(conn, scan_id, scan):
    """The gear and the reputation list of a scan that was just inserted (never of one that was already there)."""
    conn.executemany(
        f"INSERT INTO scan_gear(scan_id,{','.join(db_schema.GEAR_COLUMNS)}) VALUES(?{',?' * len(db_schema.GEAR_COLUMNS)})",
        [(scan_id, *(_json_or_none(row[c]) if c in ("gem_ids", "stats") else row[c] for c in db_schema.GEAR_COLUMNS))
         for row in scan["gear"]])
    conn.executemany(
        f"INSERT INTO scan_reputation(scan_id,{','.join(db_schema.REP_COLUMNS)}) VALUES(?{',?' * len(db_schema.REP_COLUMNS)})",
        [(scan_id, *(row[c] for c in db_schema.REP_COLUMNS)) for row in scan["rep"]])


def import_data(conn, db):
    """Stores the scans of the file: the newest of every character and the older ones in `history`. Returns
    (new, skipped, changed): the number of new scans, the number already in the database, and the keys of the
    characters that got a new scan."""
    meta = db.get("meta")
    chars = db.get("chars")
    if not isinstance(meta, dict) or not isinstance(chars, dict) or not chars:
        sys.exit(t("parse_err_no_chars"))
    by_char = scans_by_char(db)

    for sid, m in meta.items():
        conn.execute("INSERT INTO stat_defs(stat_id,name,category) VALUES(?,?,?) "
                     "ON CONFLICT(stat_id) DO UPDATE SET name=excluded.name, category=excluded.category",
                     (int(sid), str(m.get("name", "")), str(m.get("cat", ""))))

    for sid, (name, cat) in stat_values.played_labels().items():
        conn.execute("INSERT INTO stat_defs(stat_id,name,category) VALUES(?,?,?) "
                     "ON CONFLICT(stat_id) DO UPDATE SET name=excluded.name, category=excluded.category",
                     (sid, name, cat))

    for faction, entry in (db.get("repMeta") if isinstance(db.get("repMeta"), dict) else {}).items():
        faction_id = _int_or_none(faction)
        name = _name_or_none(entry.get("name")) if isinstance(entry, dict) else None
        if faction_id and faction_id > 0 and name:
            conn.execute("INSERT INTO rep_defs(faction_id,name) VALUES(?,?) "
                         "ON CONFLICT(faction_id) DO UPDATE SET name=excluded.name", (faction_id, name))

    new = skipped = 0
    changed = []
    for key, scans in by_char.items():
        for scan in scans:
            c = scan["raw"]
            cur = conn.execute(
                "INSERT OR IGNORE INTO scans(char_key,scanned_at,class,level,faction,class_file,race,race_file,"
                "spec_id,spec_name,role,ilvl_total,ilvl_equipped) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (key, scan["at"], scan["class"], scan["level"], scan["faction"],
                 scan["class_file"], scan["race"], scan["race_file"],
                 scan["spec_id"], scan["spec_name"], scan["role"], scan["ilvl_total"], scan["ilvl_equipped"]))
            if cur.rowcount == 0:
                skipped += 1
                continue
            scan_id = cur.lastrowid
            conn.executemany(
                "INSERT INTO stat_values(scan_id,stat_id,value_text,value_num) VALUES(?,?,?,?)",
                [(scan_id, int(sid), stat_values.clean_text(str(v)), stat_values.to_number(str(v))) for sid, v in scan["stats"].items()])

            if any(field not in c for _sid, field, _key in stat_values.PLAYED_STATS):
                print(t("parse_warn_no_played", key=key, at=scan["at"]))
            for sid, field, _key in stat_values.PLAYED_STATS:
                if field not in c:
                    continue
                sec = c[field]
                if isinstance(sec, bool) or not isinstance(sec, (int, float)) or sec < 0:
                    sys.exit(t("parse_err_played_invalid", key=key, field=field, value=sec))
                conn.execute("INSERT INTO stat_values(scan_id,stat_id,value_text,value_num) VALUES(?,?,?,?)",
                             (scan_id, sid, stat_values.fmt_duration(sec), int(sec)))
            store_details(conn, scan_id, scan)
            if scan["skipped"]:
                print(t("parse_warn_scan_details", key=key, at=scan["at"], count=scan["skipped"]))
            new += 1
            if key not in changed:
                changed.append(key)
    conn.commit()
    return new, skipped, changed


def refresh_numbers(conn):
    """Recomputes value_num of all stored statistic values by the current rules
    (corrects old data after a rule change in stat_values.to_number). Played time (stat_id < 0)
    is left alone. Returns the number of corrected values."""
    changed = 0
    rows = conn.execute("SELECT scan_id,stat_id,value_text,value_num FROM stat_values WHERE stat_id >= 0").fetchall()
    for scan_id, stat_id, text, num in rows:
        new = stat_values.to_number(text)
        if new != num:
            conn.execute("UPDATE stat_values SET value_num=? WHERE scan_id=? AND stat_id=?",
                         (new, scan_id, stat_id))
            changed += 1
    conn.commit()
    return changed


# The addon keeps only a limited number of the latest scans per character (one in a file of version 3, a ring of
# them since version 4), so a scan made between two imports can be gone for good. Which ones were lost cannot be
# known; from this many days between the previous scan in the database and the oldest scan in the file that is newer
# the import says so. A file that reaches back to the previous scan (or beyond) proves nothing is missing.
GAP_NOTE_DAYS = 2
SCAN_TIME_FORMAT = "%Y-%m-%d %H:%M:%S"


def last_scan_times(conn):
    """{char_key: time of the newest scan in the database}. Read before the import."""
    return dict(conn.execute("SELECT char_key, MAX(scanned_at) FROM scans GROUP BY char_key"))


def _scan_time(text):
    try:
        return datetime.strptime(str(text), SCAN_TIME_FORMAT)
    except ValueError:
        return None


def _file_scan_times(db):
    """{char key: [time of every scan of the file, oldest first]}: the newest one of `chars` and the older ones of
    `history`. What is not a scan with a readable time is left out (import_data reports it)."""
    chars = db.get("chars") if isinstance(db, dict) else None
    if not isinstance(chars, dict):
        return {}
    history = db.get("history")
    found = {}
    for key, c in chars.items():
        entries = [c] + (_sequence((history or {}).get(key)) or [] if isinstance(history, dict) else [])
        times = sorted(at for at in (_scan_time(e.get("scannedAt")) for e in entries if isinstance(e, dict)) if at)
        if times:
            found[key] = times
    return found


def import_notes(db, before, new, now=None):
    """Lines about the age of the data after an import: how old the newest scan is when nothing new
    came, or that scans may be missing when days lie between the previous scan of a character in the
    database (`before`, from last_scan_times) and the oldest scan of the file that is newer. A file that reaches
    back to the previous scan or beyond has nothing missing in between. Anything odd in the data is
    left to import_data to report: no note then."""
    times = _file_scan_times(db)
    if not times:
        return []
    if new == 0:
        newest = max(at[-1] for at in times.values())
        days = max(0, ((now or datetime.now()) - newest).days)
        return [t("parse_note_no_new", at=newest.strftime(SCAN_TIME_FORMAT), days=days)]
    worst = None
    for key, scans in times.items():
        previous = _scan_time(before.get(key))
        if not previous or scans[0] <= previous:
            continue
        days = (scans[0] - previous).days
        if worst is None or days > worst[0]:
            worst = (days, key, scans[0])
    if worst and worst[0] >= GAP_NOTE_DAYS:
        return [t("parse_note_gap", days=worst[0], key=worst[1], at=worst[2].strftime(SCAN_TIME_FORMAT))]
    return []
