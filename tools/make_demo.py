#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)
"""Invented demo data for the landing page screenshots (docs/images/).
Developer tool (not part of the release). Nothing here comes from a real character:
the names, realms and numbers are made up and the numbers are deterministic, so the
same pictures can be made again after the stats page changes.

Per language (the statistic names come from the client, so each language gets its own
database) it writes a SavedVariables-style StatTracker.lua, runs the normal stat_parser
on it and also writes four variants of the page for the screenshots:
  shot-stats.html    the page as it is
  shot-rates.html    the same, with the rates block opened
  shot-compare.html  one character deselected, sorted by the first character
  shot-groups.html   the Groups block opened: by faction, two more statistics added

With --snapshots N (N > 1) every character gets N scans, three days apart, the last one being
exactly the single scan of the default run. They are imported one after the other like the program
does, so the page also gets its History block and <folder>/<lang>/history/ holds the history pages,
plus
  history/shot-history.html   the history page of one character, four statistics as an index
  history/shot-character.html the same page with the Character block opened (the equipment of the newest scan)
The counters grow along curves of their own, so the lines on a history page differ. The default
(--snapshots 1) makes no history and the same pages as before. Four of the five characters also carry invented
equipment and a specialization (GEAR_BY_CHAR), which changes over the snapshots for the Character block of the
history pages; the last character has none. Those pages show invented placeholder icons (a colored tile per
slot, made here into <folder>/<lang>/icons/), unless --icons-from-game WOW_FOLDER is given: then the pages show the pictures
of the game for sixteen fixed ids (GAME_ICON_IDS), read from that WoW installation into the same folder, which therefore has to lie
outside the repository; only the finished screenshot goes into docs/images/.

Usage (from the repository root):
  python tools/make_demo.py --out <folder>             # both languages
  python tools/make_demo.py --out <folder> --lang de
  python tools/make_demo.py --out <folder> --snapshots 12
Then one picture per page, 1920 x 1140 (see docs/DEVELOPMENT.md, "Landing page"). The history pages
need plotly.js: run python compiler/plotly_fetch.py once.
"""
import argparse
import colorsys
import contextlib
import io
import random
import shutil
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import blp_decode  # noqa: E402
import i18n  # noqa: E402
import stat_history  # noqa: E402
import stat_parser  # noqa: E402
import wow_icons  # noqa: E402

LANGS = ("en", "de")
MAX_SNAPSHOTS = 60
SNAPSHOT_DAYS = 3                  # between two scans of the history demo
HISTORY_CHAR = "Mirella-Dawnspire"

# Invented characters. 'weight' scales the generic counters, 'played' is the total played time
# in seconds; the last one has too little played time on purpose (the page then says why
# there is no rate).
CHARS = (
    dict(key="Korvak-Ironmaw", cls=("Warrior", "Krieger"), level=74, faction=("Horde", "Horde"),
         cls_file="WARRIOR", race=("Orc", "Orc"), race_file="Orc",
         at="2026-10-26 19:42:10", epoch=1793043730, played=1503997, level_played=105279, weight=0.55,
         mount="Ashen Warwolf"),
    dict(key="Mirella-Dawnspire", cls=("Mage", "Magier"), level=80, faction=("Alliance", "Alliance"),
         cls_file="MAGE", race=("Human", "Mensch"), race_file="Human",
         at="2026-10-25 19:41:10", epoch=1792957270, played=2583885, level_played=180871, weight=1.0,
         mount="Cloudweaver Drake"),
    dict(key="Selwyn-Moonvale", cls=("Druid", "Druide"), level=58, faction=("Alliance", "Alliance"),
         cls_file="DRUID", race=("Night Elf", "Nachtelfe"), race_file="NightElf",
         at="2026-10-27 19:43:10", epoch=1793130190, played=579555, level_played=40568, weight=0.25,
         mount="Moonlit Stag"),
    dict(key="Thalrin-Sunhaven", cls=("Paladin", "Paladin"), level=80, faction=("Horde", "Horde"),
         cls_file="PALADIN", race=("Blood Elf", "Blutelf"), race_file="BloodElf",
         at="2026-10-24 19:40:10", epoch=1792870810, played=3619171, level_played=253341, weight=1.3,
         mount="Sunmane Charger"),
    dict(key="Pippa-Brightwater", cls=("Priest", "Priester"), level=9, faction=("Alliance", "Alliance"),
         cls_file="PRIEST", race=("Dwarf", "Zwerg"), race_file="Dwarf",
         at="2026-10-28 19:44:10", epoch=1793216650, played=2520, level_played=2520, weight=0.004,
         mount="Brightwater Pony"),
)

# Statistics with a rate (real stat IDs, see stat_derive.ROLES). Per character in the order of
# CHARS: events or gold per played hour; the counter is rate x hours. 0 is shown as "--" like
# the game does for a counter that never fired.
RATE_STATS = (
    # (stat_id, kind, en name, de name, en category, de category, rates)
    (107, "count", "Creatures killed", "Kreaturen getötet", "Combat", "Kampf", (45, 62, 30, 55, 40)),
    (588, "count", "Total honorable kills", "Ehrenhafte Siege insgesamt", "Combat", "Kampf", (1.8, 0, 0.4, 3.6, 0)),
    (60, "count", "Total deaths", "Tode insgesamt", "Combat", "Kampf", (0.35, 0.18, 0.12, 0.42, 0)),
    (328, "gold", "Total gold acquired", "Erhaltenes Gold insgesamt", "Wealth", "Wohlstand", (95, 160, 40, 210, 15)),
)

# Other statistics; the value is base x character weight x a fixed jitter (IDs are invented).
GENERIC = (
    # (kind, en name, de name, en category, de category, base)
    ("count", "Emotes used", "Verwendete Emotes", "Character", "Charakter", 1200),
    ("count", "Hearthstone uses", "Benutzungen des Ruhesteins", "Character", "Charakter", 260),
    ("count", "Jumps", "Sprünge", "Character", "Charakter", 38000),
    ("count", "Flight paths taken", "Bereiste Flugrouten", "Character", "Charakter", 540),
    ("count", "Dungeons entered", "Betretene Instanzen", "Character", "Charakter", 320),
    ("count", "Pets collected", "Gesammelte Haustiere", "Character", "Charakter", 240),
    ("count", "Critical hits", "Kritische Treffer", "Combat", "Kampf", 90000),
    ("count", "Enemies defeated", "Besiegte Gegner", "Combat", "Kampf", 46000),
    ("count", "Highest hit dealt", "Höchster verursachter Schaden", "Combat", "Kampf", 1700000),
    ("count", "Battlegrounds won", "Gewonnene Schlachtfelder", "Combat", "Kampf", 200),
    ("count", "Duels won", "Gewonnene Duelle", "Combat", "Kampf", 50),
    ("count", "Fish caught", "Gefangene Fische", "Crafting", "Handwerk", 550),
    ("count", "Herbs gathered", "Gesammelte Kräuter", "Crafting", "Handwerk", 5000),
    ("count", "Ore mined", "Abgebauter Erz", "Crafting", "Handwerk", 3200),
    ("count", "Items crafted", "Hergestellte Gegenstände", "Crafting", "Handwerk", 1700),
    ("count", "Quests completed", "Abgeschlossene Quests", "Quests", "Quests", 2600),
    ("count", "Auction house sales", "Verkäufe im Auktionshaus", "Wealth", "Wohlstand", 1600),
    ("gold", "Gold spent at vendors", "Gold bei Händlern ausgegeben", "Wealth", "Wohlstand", 126000),
    ("gold", "Gold earned from quests", "Durch Quests verdientes Gold", "Quests", "Quests", 53000),
    ("gold", "Highest single sale", "Höchster Einzelverkauf", "Wealth", "Wohlstand", 52000),
)
# Invented reputation, written in the format of the addon (data version 4). Account-wide entries are the same for every
# character; of the others a character knows a faction when (faction index + character index) % 3 != 0, and its standing
# varies. The last character has no list at all (the page then names it as without data).
REP_DEMO = (
    # (faction id, kind, account-wide, en name, de name)
    (9100, "cat", False, "Old Roads", "Alte Pfade"),
    (9101, "std", False, "Ashfall Wardens", "Aschenfall-Wächter"),
    (9102, "std", False, "Lantern Guild", "Laternengilde"),
    (9103, "friend", True, "Greywater Pact", "Graswasser-Pakt"),
    (9110, "cat", False, "Far Shores", "Ferne Küsten"),
    (9111, "major", True, "Tide Court", "Gezeitenhof"),
    (9112, "major", True, "Salt Caravans", "Salzkarawanen"),
    (9113, "std", False, "Reef Scouts", "Riffspäher"),
)
REP_BANDS = {4: (0, 3000), 5: (3000, 9000), 6: (9000, 21000), 7: (21000, 42000), 8: (42000, 42000)}
# Invented equipment and specialization, written in the format of the addon (data version 4). The last character has
# none at all (its history page then has no Character block). Over the snapshots the older scans differ: the items of
# the even slots were a little lower, the trinket in slot 13 was another one, the off hand was missing and the rings
# were not enchanted yet, so the comparison of two scans has something to show.
GEAR_BY_CHAR = {
    # key: (spec id, en name, de name, role, main stat, item level of the final scan, extra item level in the bags)
    "Korvak-Ironmaw": (71, "Arms", "Waffen", "DAMAGER", "ITEM_MOD_STRENGTH_SHORT", 255, 0.0),
    "Mirella-Dawnspire": (64, "Frost", "Frost", "DAMAGER", "ITEM_MOD_INTELLECT_SHORT", 276, 1.25),
    "Selwyn-Moonvale": (104, "Guardian", "Wächter", "TANK", "ITEM_MOD_AGILITY_SHORT", 205, 2.5),
    "Thalrin-Sunhaven": (65, "Holy", "Heilig", "HEALER", "ITEM_MOD_INTELLECT_SHORT", 280, 0.0),
}
GEAR_SLOTS = (1, 2, 3, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17)
ICON_ID_BASE = 130000              # the demo items' icon id is this plus the slot
# For the Character picture of the landing page (--icons-from-game): the file data ids of the pictures of one real set
# of sixteen items, one per slot. Only numbers: the pictures are read from a WoW installation when the demo is made,
# stay in the output folder and never go into the repository; only the finished screenshot does.
GAME_ICON_IDS = {1: 133111, 2: 632840, 3: 135102, 5: 132639, 6: 7082300, 7: 457953, 8: 7082301, 9: 132607,
                 10: 7082304, 11: 133661, 12: 629698, 13: 643912, 14: 643421, 15: 622728, 16: 801001, 17: 464338}
ICON_IDS = {slot: ICON_ID_BASE + slot for slot in GEAR_SLOTS}      # what the demo items carry; make() swaps it for a run
GEAR_NAMES = {      # slot: (en, de); nothing here is a real item
    1: ("Helm of Ashen Oaths", "Helm der Aschenschwüre"),
    2: ("Lantern Pendant", "Laternenanhänger"),
    3: ("Spaulders of the Old Roads", "Schulterstücke der Alten Pfade"),
    5: ("Reefplate Cuirass", "Riffplatten-Brustpanzer"),
    6: ("Saltweave Girdle", "Salzgewebe-Gürtel"),
    7: ("Greaves of the Tide Court", "Beinschienen des Gezeitenhofs"),
    8: ("Caravan Treads", "Karawanentritte"),
    9: ("Bracers of Grey Water", "Armschienen des Graswassers"),
    10: ("Gauntlets of Quiet Sparks", "Stulpen der stillen Funken"),
    11: ("Ember Band", "Glutband"),
    12: ("Signet of the Scouts", "Siegelring der Späher"),
    13: ("Wardens' Hourglass", "Sanduhr der Wächter"),
    14: ("Idol of the Far Shore", "Idol der Fernen Küste"),
    15: ("Cloak of Drifting Salt", "Umhang des treibenden Salzes"),
    16: ("Lantern-Keeper's Blade", "Klinge des Laternenhüters"),
    17: ("Aegis of the Pact", "Aigis des Paktes"),
}
OLD_TRINKET = ("Cracked Hourglass", "Rissige Sanduhr")            # slot 13 in the older scans
GEAR_ENCHANT = {11: ("Ring - Ember Surge", "Ring - Glutwelle"), 12: ("Ring - Quiet Edge", "Ring - Stille Schneide"),
                16: ("Weapon - Lantern Flame", "Waffe - Laternenflamme")}
GEAR_TRACKS = {971: ("Adventurer", "Abenteurer"), 972: ("Veteran", "Veteran"), 973: ("Champion", "Champion")}
GEAR_SECONDARY = ("ITEM_MOD_CRIT_RATING_SHORT", "ITEM_MOD_HASTE_RATING_SHORT", "ITEM_MOD_MASTERY_RATING_SHORT",
                  "ITEM_MOD_VERSATILITY")
GEAR_TERTIARY = {2: ("ITEM_MOD_CR_AVOIDANCE_SHORT", 35), 8: ("ITEM_MOD_CR_SPEED_SHORT", 40),
                 9: ("ITEM_MOD_CR_LIFESTEAL_SHORT", 28)}
GEAR_ARMOR_SLOTS = (1, 3, 5, 6, 7, 8, 9, 10, 15)
GEAR_GEM = 90301                    # an invented gem id
MOUNT = ("Favourite mount", "Lieblingsreittier", "Character", "Charakter")
GENERIC_FIRST_ID = 9001            # far away from the real IDs used above

COMPARE_JS = ('$("chk_Selwyn-Moonvale").checked = false; '
              'sortChar = "Korvak-Ironmaw"; sortDir = -1; render();')
# the demo statistics 9003 (Jumps, a counter) and 328 (Total gold acquired, shown in gold)
GROUPS_JS = ('$("groups").open = true; $("groupBy").value = "faction"; '
             '[["9003", "sum"], ["328", "avg"]].forEach(p => { $("xstat").value = p[0]; $("xagg").value = p[1]; '
             '$("xadd").click(); }); renderGroups();')
# on the history page: Creatures killed (107), Total deaths (60), Total gold acquired (328) and Jumps (9003), as an index
HISTORY_JS = ('chosen.clear(); [107, 60, 328, 9003].forEach(id => chosen.add(id)); '
              '$("mode").value = "index"; renderList(); renderChart();')
# on the same page: the Character block opened (the newest scan, compared with the one before)
CHARACTER_JS = '$("gear").open = true;'


def _number(n, i):
    """Thousands separator of the client language (i: 0 = en, 1 = de)."""
    return f"{n:,}".replace(",", "." if i else ",")


def _count_text(n, i):
    return "--" if n == 0 else _number(n, i)


def _gold_text(copper, i):
    gold, rest = divmod(copper, 10000)
    silver, cop = divmod(rest, 100)
    return f"{_number(gold, i)}g {silver}s {cop}c" if gold else f"{silver}s {cop}c"


def _jitter(stat_id, char_index):
    return random.Random(f"{stat_id}:{char_index}").uniform(0.8, 1.25)


def _share(stat_id, char_index, k, snapshots):
    """Fraction of its final value a counter has reached at snapshot k (0-based) of `snapshots`. The last
    snapshot is the final value; before it every counter grows along a curve of its own (a fixed exponent
    per statistic and character), so the lines on a history page differ."""
    if k == snapshots - 1:
        return 1.0
    exponent = random.Random(f"grow:{stat_id}:{char_index}").uniform(0.8, 1.4)
    return ((k + 1) / snapshots) ** exponent


def _scan_values(c, k, snapshots):
    """(scanned_at, epoch, level, played, level_played) of character c at snapshot k; the last snapshot
    is its final scan, the ones before lie SNAPSHOT_DAYS apart and have less played time."""
    back = snapshots - 1 - k
    if back == 0:
        return c["at"], c["epoch"], c["level"], c["played"], c["level_played"]
    share = (k + 1) / snapshots
    at = datetime.strptime(c["at"], "%Y-%m-%d %H:%M:%S") - timedelta(days=SNAPSHOT_DAYS * back)
    return (at.strftime("%Y-%m-%d %H:%M:%S"), c["epoch"] - 86400 * SNAPSHOT_DAYS * back,
            max(1, c["level"] - back // 4), max(1, round(c["played"] * share)),
            max(1, round(c["level_played"] * share)))


def _tables(i, k=0, snapshots=1):
    """(meta, stats): meta = {id: (name, category)}, stats = [{id: text}] per character, as of snapshot k."""
    meta = {}
    stats = [{} for _ in CHARS]
    for sid, kind, en, de, cat_en, cat_de, rates in RATE_STATS:
        meta[sid] = ((en, de)[i], (cat_en, cat_de)[i])
        for n, c in enumerate(CHARS):
            amount = rates[n] * c["played"] / 3600 * _share(sid, n, k, snapshots)
            stats[n][sid] = (_gold_text(round(amount * 10000), i) if kind == "gold"
                             else _count_text(round(amount), i))
    for j, (kind, en, de, cat_en, cat_de, base) in enumerate(GENERIC):
        sid = GENERIC_FIRST_ID + j
        meta[sid] = ((en, de)[i], (cat_en, cat_de)[i])
        for n, c in enumerate(CHARS):
            value = base * c["weight"] * _jitter(sid, n) * _share(sid, n, k, snapshots)
            stats[n][sid] = (_gold_text(round(value * 10000), i) if kind == "gold"
                             else _count_text(round(value), i))
    sid = GENERIC_FIRST_ID + len(GENERIC)
    meta[sid] = (MOUNT[i], MOUNT[2 + i])
    for n, c in enumerate(CHARS):
        stats[n][sid] = c["mount"]
    return meta, stats


def _lua_str(text):
    assert '"' not in text and "\\" not in text, text
    return f'"{text}"'


def _rep_lines(n):
    """The `rep` table of character n as Lua lines; none for the last character."""
    if n == len(CHARS) - 1:
        return []
    lines, ord_ = ['\t\t\t["rep"] = {'], 0
    for f, (fid, kind, aw, _en, _de) in enumerate(REP_DEMO):
        if kind == "std" and (n + f) % 3 == 0:
            continue                                    # this character never met the faction
        ord_ += 1
        head = f'["id"] = {fid}, ["ord"] = {ord_}' + (', ["aw"] = true' if aw else "")
        if kind == "cat":
            body = ', ["hdr"] = true'
        elif kind == "std":
            reaction = 4 + (n + f) % 5
            lo, hi = REP_BANDS[reaction]
            standing = lo + (hi - lo) * ((n * 7 + f * 3) % 10) // 10
            body = (f', ["kind"] = "std", ["reaction"] = {reaction}, ["standing"] = {standing}, ["lo"] = {lo}, ["hi"] = {hi}'
                    + (', ["paragon"] = { ["value"] = 13950, ["threshold"] = 10000, ["quest"] = 70001, ["pending"] = true }'
                       if reaction == 8 else ""))
        elif kind == "friend":
            body = ', ["kind"] = "friend", ["standing"] = 6200, ["lo"] = 4200, ["hi"] = 8400, ["level"] = 5, ["maxLevel"] = 8'
        elif fid == 9111:
            body = ', ["kind"] = "major", ["renown"] = 14, ["earned"] = 1200, ["need"] = 2500, ["maxRenown"] = 20'
        else:
            body = (', ["kind"] = "major", ["renown"] = 20, ["earned"] = 0, ["need"] = 2500, ["maxRenown"] = 20, '
                    '["paragon"] = { ["value"] = 4200, ["threshold"] = 7500, ["quest"] = 70002, ["pending"] = false }')
        lines.append(f"\t\t\t\t{{ {head}{body} }},")
    return lines + ["\t\t\t},"]


def _gear_items(g, i, back):
    """{slot: item fields} of a character with GEAR_BY_CHAR entry g, `back` scans before its final one (0 = final)."""
    _spec, _en, _de, _role, main, final, _bag = g
    drop = 2 * ((back + 2) // 3)                       # item level the even slots gained since
    items = {}
    for slot in GEAR_SLOTS:
        if slot == 17 and back >= 8:
            continue                                   # no off hand yet
        old_trinket = slot == 13 and back >= 4
        ilvl = final + (slot * 5) % 7 - 3 - (drop if slot % 2 == 0 else 0) - (14 if old_trinket else 0)
        stats = {main: round(ilvl * 0.33), "ITEM_MOD_STAMINA_SHORT": round(ilvl * 5.2)}
        stats[GEAR_SECONDARY[slot % 4]] = round(ilvl * 0.2)
        stats[GEAR_SECONDARY[(slot + 1) % 4]] = round(ilvl * 0.12)
        if slot in GEAR_TERTIARY:
            stats[GEAR_TERTIARY[slot][0]] = GEAR_TERTIARY[slot][1]
        if slot in GEAR_ARMOR_SLOTS:
            stats["RESISTANCE0_NAME"] = round(ilvl * 0.18)
        if slot == 16:
            stats["ITEM_MOD_DAMAGE_PER_SECOND_SHORT"] = round(ilvl * 0.11)
        item = {"itemID": 91000 + slot * 10 + old_trinket, "name": (OLD_TRINKET if old_trinket else GEAR_NAMES[slot])[i],
                "quality": 4 if slot % 3 else 3, "ilvl": ilvl, "iconID": ICON_IDS[slot], "stats": stats}
        if slot in GEAR_ENCHANT and not (slot in (11, 12) and back >= 6):
            item["enchantID"], item["enchantText"] = 7000 + slot, GEAR_ENCHANT[slot][i]
        if slot % 3:
            track = 971 + slot % 3
            item["upgrade"] = {"trackID": track, "track": GEAR_TRACKS[track][i], "level": 1 + slot % 5, "max": 6}
        if slot in (11, 12):
            item["sockets"] = 1
            item["gems"] = [0 if (slot == 12 and back >= 5) else GEAR_GEM]
            stats["EMPTY_SOCKET_PRISMATIC"] = 1
        items[slot] = item
    return items


def placeholder_icon(slot):
    """An invented 64 x 64 picture for the demo items: a tile with a lighter diamond, its color from the slot.
    Nothing of the game: the pictures of the landing page never carry a Blizzard icon."""
    red, green, blue = (int(c * 255) for c in colorsys.hsv_to_rgb((slot * 0.173) % 1.0, 0.55, 0.62))
    pixels = bytearray()
    for y in range(64):
        for x in range(64):
            if min(x, y, 63 - x, 63 - y) < 2:
                pixels += bytes((20, 20, 20, 255))
                continue
            lift = 1.5 if abs(x - 31.5) + abs(y - 31.5) < 14 else 1.0
            shade = 0.75 + 0.25 * y / 63                       # darker towards the bottom
            pixels += bytes(min(255, int(c * lift * shade)) for c in (red, green, blue)) + b"\xff"
    return blp_decode.to_png(64, 64, bytes(pixels))


def make_placeholder_icons(folder):
    """One placeholder PNG per demo slot in `folder`, named like the icons of the program (wow_icons.icon_path)."""
    Path(folder).mkdir(parents=True, exist_ok=True)
    for slot in GEAR_SLOTS:
        wow_icons.icon_path(folder, ICON_ID_BASE + slot).write_bytes(placeholder_icon(slot))


def read_game_icons(folder, game_dir, product="wow"):
    """The pictures of GAME_ICON_IDS, read from the WoW installation into `folder` (wow_icons: local files, read only).
    Stops with a message if one is missing: a picture with a few symbols among real icons would look like a bug."""
    wanted = set(GAME_ICON_IDS.values())
    run = wow_icons.extract(wanted, folder, game_dir, product)
    missing = sorted(wanted - wow_icons.present(folder))
    if run.error or missing:
        raise SystemExit("The pictures of the game could not be read: "
                         + (run.error or "missing " + ", ".join(str(i) for i in missing)))


def _lua_value(v):
    if isinstance(v, dict):
        return "{ " + ", ".join(f'["{k}"] = {_lua_value(x)}' for k, x in v.items()) + " }"
    if isinstance(v, list):
        return "{ " + ", ".join(f"[{n}] = {_lua_value(x)}" for n, x in enumerate(v, 1)) + " }"
    return _lua_str(v) if isinstance(v, str) else repr(v)


def _gear_lines(c, i, back):
    """Specialization, item levels and the `gear` table of a character as Lua lines; none for a character without."""
    g = GEAR_BY_CHAR.get(c["key"])
    if g is None:
        return []
    items = _gear_items(g, i, back)
    equipped = round(sum(it["ilvl"] for it in items.values()) / len(GEAR_SLOTS), 2)
    lines = [f'\t\t\t["specID"] = {g[0]}, ["specName"] = {_lua_str(g[1 + i])}, ["role"] = {_lua_str(g[3])},',
             f'\t\t\t["ilvlTotal"] = {round(equipped + g[6], 2)}, ["ilvlEquipped"] = {equipped},', '\t\t\t["gear"] = {']
    lines += [f"\t\t\t\t[{slot}] = {_lua_value(item)}," for slot, item in items.items()]
    return lines + ["\t\t\t},"]


def build_lua(lang, k=None, snapshots=1):
    """The demo SavedVariables file (StatTrackerDB) for one language: snapshot k (0-based) of `snapshots`,
    by default the final one, which is the single scan of a run without --snapshots."""
    i = LANGS.index(lang)
    k = snapshots - 1 if k is None else k
    meta, stats = _tables(i, k, snapshots)
    out = ["StatTrackerDB = {", '\t["version"] = 4,', '\t["auto"] = true,', '\t["meta"] = {']
    for sid, (name, cat) in meta.items():
        out.append(f'\t\t[{sid}] = {{ ["name"] = {_lua_str(name)}, ["cat"] = {_lua_str(cat)} }},')
    out += ["\t},", '\t["repMeta"] = {']
    out += [f'\t\t[{fid}] = {{ ["name"] = {_lua_str(names[i])} }},' for fid, _kind, _aw, *names in REP_DEMO]
    out += ["\t},", '\t["chars"] = {']
    for n, (c, values) in enumerate(zip(CHARS, stats)):
        at, epoch, level, played, level_played = _scan_values(c, k, snapshots)
        out += [f'\t\t[{_lua_str(c["key"])}] = {{',
                f'\t\t\t["scannedAt"] = {_lua_str(at)}, ["scannedEpoch"] = {epoch},',
                f'\t\t\t["class"] = {_lua_str(c["cls"][i])}, ["level"] = {level}, '
                f'["faction"] = {_lua_str(c["faction"][i])},',
                f'\t\t\t["classFile"] = {_lua_str(c["cls_file"])}, ["race"] = {_lua_str(c["race"][i])}, '
                f'["raceFile"] = {_lua_str(c["race_file"])},',
                '\t\t\t["stats"] = {']
        out += [f"\t\t\t\t[{sid}] = {_lua_str(text)}," for sid, text in values.items()]
        out += ["\t\t\t},",
                f'\t\t\t["playedTotal"] = {played}, ["playedLevel"] = {level_played},',
                *_gear_lines(c, i, snapshots - 1 - k),
                *_rep_lines(n),
                "\t\t},"]
    out += ["\t},", "}", ""]
    return "\n".join(out)


def shot_variants(html):
    """The screenshot pages made from the generated one: {file name: html}. Only these copies
    get the extra lines; the real template is not touched."""
    rates = html.replace('<details class="rates"', '<details class="rates" open', 1)
    compare = html.replace("init();\n</script>", f"init();\n{COMPARE_JS}\n</script>", 1)
    groups = html.replace("init();\n</script>", f"init();\n{GROUPS_JS}\n</script>", 1)
    assert rates != html and compare != html and groups != html, "template changed: adjust shot_variants"
    return {"shot-stats.html": html, "shot-rates.html": rates, "shot-compare.html": compare,
            "shot-groups.html": groups}


def history_shot(html, js=HISTORY_JS):
    """The history page of one character with `js` run after init(): by default four statistics picked, as
    an index (a copy for the screenshot, the page itself is not touched)."""
    tail = "init();\n</script>"
    i = html.rindex(tail)
    return html[:i] + f"init();\n{js}\n</script>" + html[i + len(tail):]


def _import(args, show_all):
    """One normal import. The output is shown only for the last of several (and any warning)."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        stat_parser.main(args)
    for line in buf.getvalue().splitlines():
        if show_all or line.startswith(("WARNING", "WARNUNG")):
            print(line)


def make(out_dir, lang, snapshots=1, game=None):
    """Writes the demo for one language into <out_dir>/<lang>/ and returns that folder. With snapshots > 1
    the characters get that many scans, imported one after the other, and the history pages, which show
    invented placeholder tiles for the items; with `game` = (WoW folder, product) they show the pictures of the
    game for GAME_ICON_IDS instead, read from that installation into <out_dir>/<lang>/icons/."""
    folder = Path(out_dir) / lang
    folder.mkdir(parents=True, exist_ok=True)
    lua = folder / "StatTracker.lua"
    db = folder / "demo.db"
    history = folder / "history"
    icons = folder / "icons"
    if db.exists():
        db.unlink()                     # always from scratch: same input, same pages
    for leftover in (history, icons, folder / "backups"):
        shutil.rmtree(leftover, ignore_errors=True)
    page = folder / "stats.html"
    previous = i18n.get_language()
    base_ids = dict(ICON_IDS)
    i18n.set_language(lang)
    try:
        if snapshots > 1:
            if game:
                ICON_IDS.update(GAME_ICON_IDS)
                read_game_icons(icons, *game)
            else:
                make_placeholder_icons(icons)
        for k in range(snapshots):
            lua.write_text(build_lua(lang, k, snapshots), encoding="utf-8")
            args = ["--input", str(lua), "--db", str(db), "--output", str(page)]
            if snapshots > 1:
                args += ["--history-dir", str(history), "--icons-dir", str(icons)]
            _import(args, show_all=k == snapshots - 1)
    finally:
        i18n.set_language(previous)
        ICON_IDS.clear()
        ICON_IDS.update(base_ids)
    for name, text in shot_variants(page.read_text(encoding="utf-8")).items():
        (folder / name).write_text(text, encoding="utf-8")
    shot_source = history / stat_history.page_name(HISTORY_CHAR)
    if snapshots > 1 and shot_source.is_file():
        source = shot_source.read_text(encoding="utf-8")
        (history / "shot-history.html").write_text(history_shot(source), encoding="utf-8")
        (history / "shot-character.html").write_text(history_shot(source, CHARACTER_JS), encoding="utf-8")
    return folder


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", required=True, help="folder for the demo files (outside the repository)")
    ap.add_argument("--lang", choices=LANGS + ("both",), default="both")
    ap.add_argument("--snapshots", type=int, default=1,
                    help=f"scans per character, 1 to {MAX_SNAPSHOTS} (default 1; more also makes the history pages)")
    ap.add_argument("--icons-from-game", metavar="WOW_FOLDER",
                    help="show the pictures of the game instead of placeholder tiles on the history pages: read from this "
                         "WoW installation into <out>/<lang>/icons/ (needs --snapshots 2 or more; keep --out outside the repository)")
    ap.add_argument("--product", default="wow", help="the product of the game version in .build.info (default wow)")
    a = ap.parse_args(argv)
    if not 1 <= a.snapshots <= MAX_SNAPSHOTS:
        ap.error(f"--snapshots must be between 1 and {MAX_SNAPSHOTS}")
    if a.icons_from_game and a.snapshots < 2:
        ap.error("--icons-from-game needs --snapshots 2 or more: the pictures are for the history pages")
    game = (a.icons_from_game, a.product) if a.icons_from_game else None
    for lang in (LANGS if a.lang == "both" else (a.lang,)):
        print(make(a.out, lang, a.snapshots, game))


if __name__ == "__main__":
    main()
