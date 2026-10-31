#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)
"""Invented demo data for the landing page screenshots (docs/images/).
Developer tool (not part of the release). Nothing here comes from a real character:
the names, realms and numbers are made up and the numbers are deterministic, so the
same pictures can be made again after the stats page changes.

Per language (the statistic names come from the client, so each language gets its own
database) it writes a SavedVariables-style StatTracker.lua, runs the normal stat_parser
on it and also writes three variants of the page for the screenshots:
  shot-stats.html    the page as it is
  shot-rates.html    the same, with the rates block opened
  shot-compare.html  one character deselected, sorted by the first character

Usage (from the repository root):
  python tools/make_demo.py --out <folder>             # both languages
  python tools/make_demo.py --out <folder> --lang de
Then one picture per page, 1920 x 1140 (see docs/DEVELOPMENT.md, "Landing page").
"""
import argparse
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import i18n  # noqa: E402
import stat_parser  # noqa: E402

LANGS = ("en", "de")

# Invented characters. 'weight' scales the generic counters, 'played' is the total played time
# in seconds; the last one has too little played time on purpose (the page then says why
# there is no rate).
CHARS = (
    dict(key="Korvak-Ironmaw", cls=("Warrior", "Krieger"), level=74, faction=("Horde", "Horde"),
         at="2026-10-26 19:42:10", epoch=1793043730, played=1503997, level_played=105279, weight=0.55,
         mount="Ashen Warwolf"),
    dict(key="Mirella-Dawnspire", cls=("Mage", "Magier"), level=80, faction=("Alliance", "Allianz"),
         at="2026-10-25 19:41:10", epoch=1792957270, played=2583885, level_played=180871, weight=1.0,
         mount="Cloudweaver Drake"),
    dict(key="Selwyn-Moonvale", cls=("Druid", "Druide"), level=58, faction=("Alliance", "Allianz"),
         at="2026-10-27 19:43:10", epoch=1793130190, played=579555, level_played=40568, weight=0.25,
         mount="Moonlit Stag"),
    dict(key="Thalrin-Sunhaven", cls=("Paladin", "Paladin"), level=80, faction=("Horde", "Horde"),
         at="2026-10-24 19:40:10", epoch=1792870810, played=3619171, level_played=253341, weight=1.3,
         mount="Sunmane Charger"),
    dict(key="Pippa-Brightwater", cls=("Priest", "Priester"), level=9, faction=("Alliance", "Allianz"),
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
MOUNT = ("Favourite mount", "Lieblingsreittier", "Character", "Charakter")
GENERIC_FIRST_ID = 9001            # far away from the real IDs used above

COMPARE_JS = ('$("chk_Selwyn-Moonvale").checked = false; '
              'sortChar = "Korvak-Ironmaw"; sortDir = -1; render();')


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


def _tables(i):
    """(meta, stats): meta = {id: (name, category)}, stats = [{id: text}] per character."""
    meta = {}
    stats = [{} for _ in CHARS]
    for sid, kind, en, de, cat_en, cat_de, rates in RATE_STATS:
        meta[sid] = ((en, de)[i], (cat_en, cat_de)[i])
        for n, c in enumerate(CHARS):
            amount = rates[n] * c["played"] / 3600
            stats[n][sid] = (_gold_text(round(amount * 10000), i) if kind == "gold"
                             else _count_text(round(amount), i))
    for k, (kind, en, de, cat_en, cat_de, base) in enumerate(GENERIC):
        sid = GENERIC_FIRST_ID + k
        meta[sid] = ((en, de)[i], (cat_en, cat_de)[i])
        for n, c in enumerate(CHARS):
            value = base * c["weight"] * _jitter(sid, n)
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


def build_lua(lang):
    """The demo SavedVariables file (StatTrackerDB) for one language."""
    i = LANGS.index(lang)
    meta, stats = _tables(i)
    out = ["StatTrackerDB = {", '\t["version"] = 2,', '\t["auto"] = true,', '\t["meta"] = {']
    for sid, (name, cat) in meta.items():
        out.append(f'\t\t[{sid}] = {{ ["name"] = {_lua_str(name)}, ["cat"] = {_lua_str(cat)} }},')
    out += ["\t},", '\t["chars"] = {']
    for c, values in zip(CHARS, stats):
        out += [f'\t\t[{_lua_str(c["key"])}] = {{',
                f'\t\t\t["scannedAt"] = {_lua_str(c["at"])}, ["scannedEpoch"] = {c["epoch"]},',
                f'\t\t\t["class"] = {_lua_str(c["cls"][i])}, ["level"] = {c["level"]}, '
                f'["faction"] = {_lua_str(c["faction"][i])},',
                '\t\t\t["stats"] = {']
        out += [f"\t\t\t\t[{sid}] = {_lua_str(text)}," for sid, text in values.items()]
        out += ["\t\t\t},",
                f'\t\t\t["playedTotal"] = {c["played"]}, ["playedLevel"] = {c["level_played"]},',
                "\t\t},"]
    out += ["\t},", "}", ""]
    return "\n".join(out)


def shot_variants(html):
    """The screenshot pages made from the generated one: {file name: html}. Only these copies
    get the extra lines; the real template is not touched."""
    rates = html.replace('<details class="rates"', '<details class="rates" open', 1)
    compare = html.replace("init();\n</script>", f"init();\n{COMPARE_JS}\n</script>", 1)
    assert rates != html and compare != html, "template changed: adjust shot_variants"
    return {"shot-stats.html": html, "shot-rates.html": rates, "shot-compare.html": compare}


def make(out_dir, lang):
    """Writes the demo for one language into <out_dir>/<lang>/ and returns that folder."""
    folder = Path(out_dir) / lang
    folder.mkdir(parents=True, exist_ok=True)
    lua = folder / "StatTracker.lua"
    lua.write_text(build_lua(lang), encoding="utf-8")
    db = folder / "demo.db"
    if db.exists():
        db.unlink()                     # always from scratch: same input, same pages
    page = folder / "stats.html"
    previous = i18n.get_language()
    i18n.set_language(lang)
    try:
        stat_parser.main(["--input", str(lua), "--db", str(db), "--output", str(page)])
    finally:
        i18n.set_language(previous)
    for name, text in shot_variants(page.read_text(encoding="utf-8")).items():
        (folder / name).write_text(text, encoding="utf-8")
    return folder


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", required=True, help="folder for the demo files (outside the repository)")
    ap.add_argument("--lang", choices=LANGS + ("both",), default="both")
    a = ap.parse_args(argv)
    for lang in (LANGS if a.lang == "both" else (a.lang,)):
        print(make(a.out, lang))


if __name__ == "__main__":
    main()
