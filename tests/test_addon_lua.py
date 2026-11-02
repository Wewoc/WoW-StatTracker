# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)
# Runs the real addon Lua code in an embedded Lua (lupa) against a faked WoW API with a
# virtual clock: the scan must be spread over ~10 seconds in small slices, announce
# "started" and "done" in chat, refuse a second scan while running, and store everything.
# Skipped without lupa (pip install lupa; listed in requirements-dev.txt).
# Note: lupa embeds Lua 5.4, WoW runs 5.1 - the addon only uses constructs common to both.

import re
import time
from pathlib import Path

import pytest

lupa = pytest.importorskip("lupa")

ADDON = Path(__file__).resolve().parent.parent / "addon" / "StatTracker" / "StatTracker.lua"

FAKE_WOW = r'''
NOW = 0
TIMERS = {}
C_Timer = { After = function(delay, fn) TIMERS[#TIMERS + 1] = { t = NOW + delay, fn = fn } end }
CALLS = 0
PER_TICK = {}
function RunTimers(stopWhenRequested)
    while #TIMERS > 0 and not (stopWhenRequested and REQUESTED) do
        table.sort(TIMERS, function(a, b) return a.t < b.t end)
        local tm = table.remove(TIMERS, 1)
        NOW = tm.t
        CALLS = 0
        tm.fn()
        PER_TICK[#PER_TICK + 1] = CALLS
    end
end
CHAT = {}
print = function(s) CHAT[#CHAT + 1] = { at = NOW, text = s } end
FRAMES = {}
function CreateFrame()
    local f = { events = {}, scripts = {} }
    function f:RegisterEvent(e) self.events[e] = true end
    function f:UnregisterEvent(e) self.events[e] = nil end
    function f:SetScript(n, fn) self.scripts[n] = fn end
    FRAMES[#FRAMES + 1] = f
    return f
end
function Fire(event, ...)
    for _, f in ipairs(FRAMES) do
        if f.events[event] and f.scripts.OnEvent then f.scripts.OnEvent(f, event, ...) end
    end
end
function GetLocale() return LOCALE end
function GetStatisticsCategoryList() return { 101, 102, 103 } end
function GetCategoryInfo(id) return "Cat" .. id, (id == 103) and 101 or 0 end
function GetCategoryNumAchievements(id) return 700 end
function GetAchievementInfo(cat, i) return cat * 10000 + i, "Stat " .. (cat * 10000 + i) end
function GetStatistic(id) CALLS = CALLS + 1; return tostring(id) end
function UnitName() return "Alice" end
function GetRealmName() return "Realm" end
function UnitClass() return "Mage", "MAGE", 8 end
function UnitRace() return "Human", "Human", 1 end
function UnitLevel() return 80 end
function UnitFactionGroup() return "Alliance" end
function RequestTimePlayed() REQUESTED = true end
function strlower(s) return string.lower(s) end
function strtrim(s) return (s:gsub("^%s+", ""):gsub("%s+$", "")) end
date = function(f) return os.date(f) end
time = os.time
SlashCmdList = {}
'''

TOTAL = 3 * 700


def run_addon(locale, tweak=""):
    """Loads the addon against the fake API; `tweak` is Lua run after the fake API (to break parts of it)."""
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    lua.execute(f'LOCALE = "{locale}"')
    lua.execute(FAKE_WOW)
    if tweak:
        lua.execute(tweak)
    loaded = lua.eval("function(src) return load(src, '=StatTracker.lua') end")(ADDON.read_text(encoding="utf-8"))
    assert not isinstance(loaded, tuple), f"Lua syntax error: {loaded}"
    loaded("StatTracker")
    lua.execute('Fire("ADDON_LOADED", "StatTracker")')
    lua.execute('SlashCmdList["STATTRACKER"]("")')
    lua.execute('SlashCmdList["STATTRACKER"]("")')           # second scan while one is running
    lua.execute("RunTimers(true)")                            # until the played time was requested
    lua.execute('Fire("TIME_PLAYED_MSG", 90061, 3600)')
    lua.execute("RunTimers()")
    return lua.globals()


@pytest.fixture(scope="module")
def en():
    return run_addon("enUS")


def chat(g):
    return [(float(e["at"]), str(e["text"])) for e in g.CHAT.values()]


def test_scan_is_spread_over_about_ten_seconds_in_small_slices(en):
    work = [c for c in en.PER_TICK.values() if c > 0]
    assert max(work) <= 21                      # ceil(2100 / (10 s / 0.1 s)) statistics per slice
    assert len(work) >= 90
    done_at = [at for at, text in chat(en) if "Stat sync done" in text][0]
    assert 9.5 <= done_at <= 10.5


def test_chat_announces_start_and_done_and_refuses_a_second_scan(en):
    lines = chat(en)
    texts = [t for _at, t in lines]
    assert "Stat sync started" in texts[0] and lines[0][0] == 0
    assert any("already running" in t for t in texts)
    assert any(f"Stat sync done: {TOTAL} statistics" in t for t in texts)
    assert sum("Stat sync started" in t for t in texts) == 1


def test_everything_is_stored_with_the_played_time(en):
    db = en.StatTrackerDB
    rec = db.chars["Alice-Realm"]
    stored = {int(k): str(v) for k, v in rec.stats.items()}
    assert len(stored) == TOTAL
    assert all(stored[c * 10000 + i] == str(c * 10000 + i) for c in (101, 102, 103) for i in range(1, 701))
    assert rec["class"] == "Mage" and rec.level == 80 and rec.faction == "Alliance"
    assert rec.playedTotal == 90061 and rec.playedLevel == 3600
    assert db.meta[1030700].cat == "Cat101 > Cat103"


def test_class_file_race_and_race_file_are_stored_and_the_contract_version_is_4(en):
    db = en.StatTrackerDB
    rec = db.chars["Alice-Realm"]
    assert (rec.classFile, rec.race, rec.raceFile) == ("MAGE", "Human", "Human")
    assert rec["class"] == "Mage"                            # the localized class name stays as it was
    assert db.version == 4


def test_the_file_names_do_not_depend_on_the_client_language():
    g = run_addon("deDE", 'function UnitClass() return "Magier", "MAGE", 8 end '
                          'function UnitRace() return "Mensch", "Human", 1 end')
    rec = g.StatTrackerDB.chars["Alice-Realm"]
    assert (rec["class"], rec.classFile, rec.race, rec.raceFile) == ("Magier", "MAGE", "Mensch", "Human")


def test_a_missing_race_does_not_lose_the_scan():
    g = run_addon("enUS", "function UnitRace() return nil end")
    rec = g.StatTrackerDB.chars["Alice-Realm"]
    assert len(list(rec.stats.keys())) == TOTAL and rec.playedTotal == 90061
    assert rec.race is None and rec.raceFile is None
    assert (rec.classFile, rec["class"]) == ("MAGE", "Mage")


def _scan_failure(tweak, locale="enUS"):
    g = run_addon(locale, tweak)
    texts = [t for _at, t in chat(g)]
    # run_addon() issues /statscan twice: both must fail with the same plain message and
    # nothing else (no "started" line, no Lua error)
    assert len(texts) == 2 and len(set(texts)) == 1, texts
    assert "attempt to call" not in texts[0] and ".lua:" not in texts[0]
    assert not list(g.StatTrackerDB.chars.keys())    # nothing stored
    return texts[0]


def test_game_version_without_statistics_api_gets_a_plain_message():
    # e.g. BC Anniversary: the statistics functions do not exist
    text = _scan_failure("GetStatisticsCategoryList = nil")
    assert "This game version provides no statistics" in text


def test_game_version_with_empty_statistics_gets_the_same_message():
    assert "provides no statistics" in _scan_failure("function GetStatisticsCategoryList() return {} end")
    assert "provides no statistics" in _scan_failure("function GetCategoryNumAchievements() return 0 end")


def test_no_statistics_message_is_german_on_a_german_client():
    assert "stellt keine Statistiken bereit" in _scan_failure("GetStatisticsCategoryList = nil", "deDE")


def test_german_client_gets_german_messages():
    texts = [t for _at, t in chat(run_addon("deDE"))]
    assert "Stat-Sync gestartet" in texts[0]
    assert any("Stat-Sync fertig" in t for t in texts)
    assert any("laeuft bereits" in t for t in texts)


# ------------------------------------------------------------------ the ring of older scans (history)
# Several scans one after the other in ONE runtime, each at a clock of its own (UTC, so the texts do not
# depend on the machine). run_addon() above starts a fresh runtime for a single scan and cannot do this.

CLOCK_LUA = '''
CLOCK = 0
time = function() return CLOCK end
date = function(f) return os.date("!" .. f, CLOCK) end
'''
BASE_EPOCH = 1_790_000_000
DAY = 86_400


def at(epoch):
    return time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(epoch))


def run_scans(scans, locale="enUS", tweak="", before_load=""):
    """scans: a list of dicts {"epoch": ..., "played": seconds, "name": character name (default Alice)}.
    before_load: Lua run before the addon loads (to pre-fill StatTrackerDB like a file from an earlier session)."""
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    lua.execute(f'LOCALE = "{locale}"')
    lua.execute(FAKE_WOW)
    lua.execute(CLOCK_LUA)
    if tweak:
        lua.execute(tweak)
    if before_load:
        lua.execute(before_load)
    loaded = lua.eval("function(src) return load(src, '=StatTracker.lua') end")(ADDON.read_text(encoding="utf-8"))
    assert not isinstance(loaded, tuple), f"Lua syntax error: {loaded}"
    loaded("StatTracker")
    lua.execute('Fire("ADDON_LOADED", "StatTracker")')
    for scan in scans:
        lua.execute(f'CLOCK = {scan["epoch"]}; REQUESTED = false; '
                    f'function UnitName() return "{scan.get("name", "Alice")}" end')
        lua.execute('SlashCmdList["STATTRACKER"]("")')
        lua.execute("RunTimers(true)")
        lua.execute(f'Fire("TIME_PLAYED_MSG", {scan["played"]}, 60)')
        lua.execute("RunTimers()")
    return lua.globals()


def history_max():
    found = re.findall(r"^local HISTORY_MAX = (\d+)\b", ADDON.read_text(encoding="utf-8"), re.MULTILINE)
    assert len(found) == 1
    return int(found[0])


def history_of(g, key="Alice-Realm"):
    """The history entries of a character as a list of (scannedAt, playedTotal), newest first."""
    entries = g.StatTrackerDB.history[key]
    return [(str(entries[i].scannedAt), entries[i].playedTotal) for i in range(1, len(entries) + 1)]


def test_the_database_has_the_tables_of_version_4_after_loading():
    g = run_scans([])
    db = g.StatTrackerDB
    assert db.version == 4
    assert list(db.history.keys()) == [] and list(db.repMeta.keys()) == []


def test_each_scan_moves_the_one_before_into_the_history_with_its_played_time():
    scans = [{"epoch": BASE_EPOCH + i * DAY, "played": 1000 * (i + 1)} for i in range(3)]
    g = run_scans(scans)
    db = g.StatTrackerDB
    assert str(db.chars["Alice-Realm"].scannedAt) == at(scans[2]["epoch"]) and db.chars["Alice-Realm"].playedTotal == 3000
    assert history_of(g) == [(at(scans[1]["epoch"]), 2000), (at(scans[0]["epoch"]), 1000)]    # newest first
    assert len(list(db.history["Alice-Realm"][1].stats.keys())) == TOTAL                      # the full scan moved


def test_the_history_is_cut_to_one_less_than_the_ring_size():
    n = history_max() + 3
    scans = [{"epoch": BASE_EPOCH + i * DAY, "played": 100 * (i + 1)} for i in range(n)]
    g = run_scans(scans)
    kept = history_of(g)
    assert len(kept) == history_max() - 1
    assert kept[0] == (at(scans[n - 2]["epoch"]), 100 * (n - 1))        # the one before the newest comes first
    assert kept[-1][0] == at(scans[n - history_max()]["epoch"])         # the older ones fell off the end
    assert str(g.StatTrackerDB.chars["Alice-Realm"].scannedAt) == at(scans[n - 1]["epoch"])


def test_a_scan_in_the_same_second_replaces_the_one_before_instead_of_doubling_it():
    g = run_scans([{"epoch": BASE_EPOCH, "played": 1}, {"epoch": BASE_EPOCH, "played": 2}])
    db = g.StatTrackerDB
    assert list(db.history.keys()) == []
    assert db.chars["Alice-Realm"].playedTotal == 2


def test_an_entry_already_first_in_the_history_is_not_pushed_again():
    key = '"Alice-Realm"'
    before = (f'StatTrackerDB = {{ version = 4, meta = {{}}, chars = {{ [{key}] = {{ scannedAt = "{at(BASE_EPOCH)}", stats = {{}} }} }}, '
              f'history = {{ [{key}] = {{ {{ scannedAt = "{at(BASE_EPOCH)}", stats = {{}} }} }} }} }}')
    g = run_scans([{"epoch": BASE_EPOCH + DAY, "played": 5}], before_load=before)
    assert history_of(g) == [(at(BASE_EPOCH), None)]


def test_characters_keep_separate_histories():
    scans = [{"epoch": BASE_EPOCH, "played": 1, "name": "Alice"}, {"epoch": BASE_EPOCH + DAY, "played": 2, "name": "Bob"},
             {"epoch": BASE_EPOCH + 2 * DAY, "played": 3, "name": "Alice"}]
    g = run_scans(scans)
    assert history_of(g, "Alice-Realm") == [(at(BASE_EPOCH), 1)]
    assert list(g.StatTrackerDB.history.keys()) == ["Alice-Realm"]       # Bob has only one scan, so no history yet
    assert g.StatTrackerDB.chars["Bob-Realm"].playedTotal == 2


def test_a_file_of_version_3_is_kept_and_its_scan_becomes_the_first_history_entry():
    old = (f'StatTrackerDB = {{ version = 3, auto = false, meta = {{ [7] = {{ name = "x", cat = "y" }} }}, chars = {{ ["Alice-Realm"] = '
           f'{{ scannedAt = "{at(BASE_EPOCH)}", stats = {{ [7] = "5" }}, playedTotal = 99 }} }} }}')
    g = run_scans([{"epoch": BASE_EPOCH + DAY, "played": 100}], before_load=old)
    db = g.StatTrackerDB
    assert db.version == 4 and db.auto is False and db.meta[7].name == "x"
    assert history_of(g) == [(at(BASE_EPOCH), 99)]
    assert db.history["Alice-Realm"][1].stats[7] == "5"


def test_a_broken_earlier_entry_is_not_moved_into_the_history():
    broken = 'StatTrackerDB = { meta = {}, chars = { ["Alice-Realm"] = "not a table" } }'
    g = run_scans([{"epoch": BASE_EPOCH, "played": 1}], before_load=broken)
    assert list(g.StatTrackerDB.history.keys()) == []
    assert g.StatTrackerDB.chars["Alice-Realm"].playedTotal == 1


# ------------------------------------------------------------------ specialization, item level, gear
# A faked part of the retail API. Not in FAKE_WOW on purpose: the scans above run against a game that has none of
# it, which must stay as good as before (a missing function is no error and no chat line).
GEAR_API = r'''
GetSpecialization = function() return 2 end
GetSpecializationInfo = function(index) return 72, "Fury", "text", 132347, "DAMAGER", 1 end
PlayerUtil = { GetCurrentSpecID = function() return 72 end }
GetAverageItemLevel = function() return 276.5, 275.25, 270 end
TooltipUtil = { SurfaceArgs = function() end }

ITEMS = {
  [3]  = { id = 209894, name = "Mantle of Embers", quality = 4, ilvl = 269, icon = 5178362, enchant = 8028,
           enchantLine = "Enchanted: Shoulders - Thalassian Recovery |A:Professions-ChatIcon-Quality-12-Tier1:20:20|a",
           stats = { ITEM_MOD_STAMINA_SHORT = 1374, RESISTANCE0_NAME = 52, ITEM_MOD_HASTE_RATING_SHORT = 63 },
           upgrade = { trackStringID = 971, trackString = "Adventurer", currentLevel = 2, maxLevel = 6 } },
  [11] = { id = 100011, name = "Ring of Sockets", quality = 3, ilvl = 279, icon = 111, sockets = 1, gems = { 213743 },
           stats = { ITEM_MOD_STAMINA_SHORT = 1159, EMPTY_SOCKET_PRISMATIC = 1 } },
  [12] = { id = 100012, name = "Second Ring", quality = 2, ilvl = 270, icon = 112, sockets = 2, gems = { nil, 5 } },
  [19] = { id = 5976, name = "Guild Tabard", quality = 1, ilvl = 1, icon = 113 },
}
BY_ID = {}
for slot, it in pairs(ITEMS) do BY_ID[it.id] = it end
function ItemOfLink(link) return BY_ID[tonumber(link:match("item:(%d+)"))] end

GetInventoryItemID = function(unit, slot) return ITEMS[slot] and ITEMS[slot].id end
GetInventoryItemTexture = function(unit, slot) return ITEMS[slot] and ITEMS[slot].icon end
GetInventoryItemLink = function(unit, slot)
    local it = ITEMS[slot]
    if not it then return nil end
    return "|cnIQ" .. it.quality .. ":|Hitem:" .. it.id .. ":" .. (it.enchant or "") .. "::::::::83:103|h[" .. it.name .. "]|h|r"
end
LOAD_AT = 0          -- virtual second from which item names are known
C_Item = {
  GetItemInfo = function(link)
      local it = ItemOfLink(link)
      if not it or NOW < LOAD_AT then return nil end
      return it.name, link, it.quality, it.ilvl
  end,
  GetDetailedItemLevelInfo = function(link) local it = ItemOfLink(link); return it and it.ilvl end,
  GetItemStats = function(link) local it = ItemOfLink(link); return it and it.stats or {} end,
  GetItemUpgradeInfo = function(link) local it = ItemOfLink(link); return it and it.upgrade end,
  GetItemNumSockets = function(link) local it = ItemOfLink(link); return it and it.sockets or 0 end,
  GetItemGemID = function(link, i) local it = ItemOfLink(link); return it and it.gems and it.gems[i] end,
}
C_TooltipInfo = {
  GetInventoryItem = function(unit, slot)
      local it = ITEMS[slot]
      local lines = { { type = 22, leftText = it.name } }
      if it.enchantLine then lines[#lines + 1] = { type = 15, leftText = it.enchantLine } end
      return { lines = lines }
  end,
}
'''
ONE_SCAN = [{"epoch": BASE_EPOCH, "played": 1}]


def newest(g):
    return g.StatTrackerDB.chars["Alice-Realm"]


def chat_texts(g):
    return [t for _at, t in chat(g)]


def test_a_game_without_these_functions_stores_the_scan_as_before_and_says_nothing():
    g = run_scans(ONE_SCAN)
    rec = newest(g)
    assert len(list(rec.stats.keys())) == TOTAL and rec.playedTotal == 1
    assert all(rec[field] is None for field in ("specID", "specName", "role", "ilvlTotal", "ilvlEquipped", "gear", "rep"))
    assert not any("not read" in t for t in chat_texts(g))


def test_specialization_and_item_level_are_stored():
    rec = newest(run_scans(ONE_SCAN, tweak=GEAR_API))
    assert (rec.specID, rec.specName, rec.role) == (72, "Fury", "DAMAGER")
    assert (rec.ilvlTotal, rec.ilvlEquipped) == (276.5, 275.25)


def test_the_specialization_id_falls_back_to_the_info_of_the_active_index():
    rec = newest(run_scans(ONE_SCAN, tweak=GEAR_API + "PlayerUtil = nil"))
    assert rec.specID == 72 and rec.role == "DAMAGER"


def test_only_equipped_slots_are_stored_with_what_the_game_tells():
    gear = newest(run_scans(ONE_SCAN, tweak=GEAR_API)).gear
    assert sorted(int(k) for k in gear.keys()) == [3, 11, 12, 19]
    item = gear[3]
    assert (item.itemID, item.name, item.quality, item.ilvl, item.iconID) == (209894, "Mantle of Embers", 4, 269, 5178362)
    assert item.stats["ITEM_MOD_STAMINA_SHORT"] == 1374 and item.stats["RESISTANCE0_NAME"] == 52
    assert item.enchantID == 8028
    assert item.enchantText == "Shoulders - Thalassian Recovery"          # prefix and inline icon are gone
    up = item.upgrade
    assert (up.trackID, up.track, up.level, up.max) == (971, "Adventurer", 2, 6)
    assert item.sockets is None and item.link is None                      # the link is only a helper


def test_an_item_without_enchantment_upgrade_or_stats_has_none_of_those_fields():
    gear = newest(run_scans(ONE_SCAN, tweak=GEAR_API)).gear
    tabard = gear[19]
    assert (tabard.itemID, tabard.name, tabard.ilvl) == (5976, "Guild Tabard", 1)
    assert all(tabard[f] is None for f in ("enchantID", "enchantText", "upgrade", "stats", "sockets", "gems"))
    ring = gear[11]
    assert ring.enchantID is None and ring.enchantText is None             # an empty second field is no enchantment


def test_sockets_store_gem_ids_with_zero_for_an_empty_one():
    gear = newest(run_scans(ONE_SCAN, tweak=GEAR_API)).gear
    assert gear[11].sockets == 1 and gear[11].gems[1] == 213743
    assert gear[12].sockets == 2 and (gear[12].gems[1], gear[12].gems[2]) == (0, 5)


def test_missing_item_names_are_waited_for_and_stored_when_they_arrive():
    g = run_scans(ONE_SCAN, tweak=GEAR_API + "LOAD_AT = 12")               # known 2 s after the statistics are read
    assert newest(g).gear[3].name == "Mantle of Embers"
    done = [at for at, text in chat(g) if "Stat sync done" in text][0]
    assert 12 <= done <= 13


def test_names_that_never_arrive_are_left_out_after_five_seconds_not_stored_empty():
    g = run_scans(ONE_SCAN, tweak=GEAR_API + "LOAD_AT = 1000")
    rec = newest(g)
    done = [at for at, text in chat(g) if "Stat sync done" in text][0]
    assert 14.9 <= done <= 15.6                                            # 10 s of statistics + 5 s of waiting
    assert len(list(rec.stats.keys())) == TOTAL and rec.playedTotal == 1   # the scan is whole anyway
    assert rec.gear[3].name is None and rec.gear[3].itemID == 209894 and rec.gear[3].stats is not None


RUN_UNTIL = """
function RunUntil(limit)
    while #TIMERS > 0 do
        table.sort(TIMERS, function(a, b) return a.t < b.t end)
        if TIMERS[1].t > limit then break end
        local tm = table.remove(TIMERS, 1)
        NOW = tm.t
        CALLS = 0
        tm.fn()
    end
end
"""


def test_no_second_scan_starts_while_the_names_are_awaited():
    g = run_scans([], tweak=GEAR_API + "LOAD_AT = 1000" + RUN_UNTIL)
    g.SlashCmdList["STATTRACKER"]("")
    g.RunUntil(12)                                                         # the statistics are read, the wait is on
    assert g.StatTrackerDB.chars["Alice-Realm"] is None                    # nothing stored yet
    before = len(chat_texts(g))
    g.SlashCmdList["STATTRACKER"]("")
    assert "already running" in chat_texts(g)[before]
    g.RunUntil(100)                                                        # the wait ends, the scan is stored
    assert g.StatTrackerDB.chars["Alice-Realm"] is not None


def test_an_error_in_one_gear_function_drops_that_slot_but_never_the_statistics():
    broken = GEAR_API + 'local ok = C_Item.GetItemStats; C_Item.GetItemStats = function(l) if l:find("209894") then error("boom") end return ok(l) end'
    g = run_scans(ONE_SCAN, tweak=broken)
    rec = newest(g)
    assert len(list(rec.stats.keys())) == TOTAL and rec.playedTotal == 1
    assert sorted(int(k) for k in rec.gear.keys()) == [11, 12, 19]        # the slot with the error is gone
    assert any("Gear not read" in t and "boom" in t for t in chat_texts(g))
    assert (rec.specID, rec.ilvlTotal) == (72, 276.5)                      # the other parts are untouched


def test_an_error_in_the_item_level_or_the_specialization_leaves_only_that_part_out():
    g = run_scans(ONE_SCAN, tweak=GEAR_API + 'GetAverageItemLevel = function() error("ilvl boom") end')
    rec = newest(g)
    assert rec.ilvlTotal is None and rec.gear is not None and rec.specID == 72
    assert any("Item level not read" in t for t in chat_texts(g))
    g = run_scans(ONE_SCAN, tweak=GEAR_API + 'GetSpecialization = function() error("spec boom") end')
    assert newest(g).specID is None and newest(g).gear is not None
    assert any("Specialization not read" in t for t in chat_texts(g))


def test_the_messages_are_german_on_a_german_client():
    g = run_scans(ONE_SCAN, locale="deDE", tweak=GEAR_API + 'GetAverageItemLevel = function() error("x") end')
    assert any("Itemlevel nicht gelesen" in t and "Statistiken sind gespeichert" in t for t in chat_texts(g))


def test_a_character_without_a_specialization_gets_no_specialization_fields():
    rec = newest(run_scans(ONE_SCAN, tweak=GEAR_API + "GetSpecialization = function() return nil end; PlayerUtil = nil"))
    assert all(rec[f] is None for f in ("specID", "specName", "role")) and rec.gear is not None


def test_gear_moves_into_the_history_with_its_scan():
    g = run_scans([{"epoch": BASE_EPOCH, "played": 1}, {"epoch": BASE_EPOCH + DAY, "played": 2}], tweak=GEAR_API)
    older = g.StatTrackerDB.history["Alice-Realm"][1]
    assert older.gear[3].name == "Mantle of Embers" and older.specID == 72


# ------------------------------------------------------------------ reputation
# A faked reputation list that really hides the children of a collapsed category, so that expanding and putting
# back can be seen. The list entries of a friendship and of a major faction carry WRONG numbers on purpose: the
# values must come from the functions of that kind.
REP_API = r'''
REP_DEFS = {
  { id = 2698, name = "Midnight", header = true },
  { id = 2696, name = "Amani", aw = true, reaction = 5, standing = 3000, lo = 3000, hi = 9000 },
  { id = 2744, name = "Valeera", aw = true, reaction = 8, standing = 41248, lo = 1, hi = 2,
    friend = { standing = 250754, lo = 245747, hi = 264497, level = 22, maxLevel = 80 } },
  { id = 2640, name = "Renown Folk", aw = true, reaction = 4, standing = 11, lo = 0, hi = 1,
    major = { level = 7, earned = 2069, need = 2500, max = 20 } },
  { id = 1000, name = "Classic", header = true, collapsed = true },
  { id = 1001, name = "Stormwind", child = true, reaction = 6, standing = 7000, lo = 3000, hi = 9000 },
  { id = 1002, name = "Ironforge", child = true, reaction = 8, standing = 42000, lo = 42000, hi = 42000,
    paragon = { value = 100, threshold = 7500, quest = 93566, pending = false } },
  { id = 3000, name = "Header With Rep", header = true, withRep = true, reaction = 5, standing = 3500, lo = 3000, hi = 9000 },
}
EXPAND_CALLS, COLLAPSE_CALLS, IN_COMBAT = 0, 0, false
function RepVisible()
    local out, hidden = {}, false
    for _, d in ipairs(REP_DEFS) do
        if d.header then hidden = false end
        if not hidden then out[#out + 1] = d end
        if d.header and d.collapsed then hidden = true end
    end
    return out
end
function RepFind(id) for _, d in ipairs(REP_DEFS) do if d.id == id then return d end end end
function CollapsedNames()
    local names = {}
    for _, d in ipairs(REP_DEFS) do if d.collapsed then names[#names + 1] = d.name end end
    return table.concat(names, ",")
end
InCombatLockdown = function() return IN_COMBAT end
C_Reputation = {
  GetNumFactions = function() return #RepVisible() end,
  GetFactionDataByIndex = function(i)
      local d = RepVisible()[i]
      if not d then return nil end
      return { factionID = d.id, name = d.name, isHeader = d.header or false, isHeaderWithRep = d.withRep or false,
               isChild = d.child or false, isAccountWide = d.aw or false, isCollapsed = d.collapsed or false,
               reaction = d.reaction, currentStanding = d.standing, currentReactionThreshold = d.lo,
               nextReactionThreshold = d.hi }
  end,
  ExpandAllFactionHeaders = function()
      EXPAND_CALLS = EXPAND_CALLS + 1
      for _, d in ipairs(REP_DEFS) do d.collapsed = false end
  end,
  CollapseFactionHeader = function(i)
      COLLAPSE_CALLS = COLLAPSE_CALLS + 1
      local d = RepVisible()[i]
      if d and d.header then d.collapsed = true end
  end,
  IsMajorFaction = function(id) return RepFind(id).major ~= nil end,
  IsFactionParagon = function(id) return true end,               -- true for far too many: not to be used
  IsFactionParagonForCurrentPlayer = function(id) return RepFind(id).paragon ~= nil end,
  GetFactionParagonInfo = function(id) local p = RepFind(id).paragon; return p.value, p.threshold, p.quest, p.pending end,
}
C_GossipInfo = {
  GetFriendshipReputation = function(id)
      local f = RepFind(id).friend
      if not f then return { friendshipFactionID = 0 } end
      return { friendshipFactionID = id, standing = f.standing, reactionThreshold = f.lo, nextThreshold = f.hi }
  end,
  GetFriendshipReputationRanks = function(id) local f = RepFind(id).friend; return { currentLevel = f.level, maxLevel = f.maxLevel } end,
}
C_MajorFactions = {
  GetMajorFactionData = function(id)
      local m = RepFind(id).major
      return { renownLevel = m.level, renownReputationEarned = m.earned, renownLevelThreshold = m.need, maxLevel = m.max }
  end,
}
'''


def rep_of(g):
    rep = newest(g).rep
    return {int(e.id): e for e in (rep[i] for i in range(1, len(rep) + 1))}


def test_the_reputation_list_is_read_with_the_values_of_each_kind():
    g = run_scans(ONE_SCAN, tweak=REP_API)
    rep = newest(g).rep
    assert [int(rep[i].ord) for i in range(1, len(rep) + 1)] == list(range(1, 9))      # the order of the game
    entries = rep_of(g)

    header = entries[2698]                                                    # a category without reputation
    assert header.hdr is True and header.kind is None and header.standing is None
    amani = entries[2696]                                                     # standard
    assert (amani.kind, amani.reaction, amani.standing, amani.lo, amani.hi, amani.aw) == ("std", 5, 3000, 3000, 9000, True)
    valeera = entries[2744]                                                   # friendship: NOT the list numbers
    assert valeera.kind == "friend"
    assert (valeera.standing, valeera.lo, valeera.hi, valeera.level, valeera.maxLevel) == (250754, 245747, 264497, 22, 80)
    assert valeera.reaction is None
    renown = entries[2640]                                                    # major faction: NOT the list numbers
    assert renown.kind == "major"
    assert (renown.renown, renown.earned, renown.need, renown.maxRenown) == (7, 2069, 2500, 20)
    assert renown.standing is None
    child = entries[1001]
    assert child.child is True and child.aw is None and child.paragon is None   # "IsFactionParagon" alone does not count
    paragon = entries[1002].paragon
    assert (paragon.value, paragon.threshold, paragon.quest, paragon.pending) == (100, 7500, 93566, False)
    with_rep = entries[3000]                                                  # a category WITH reputation is also an entry
    assert with_rep.hdr is True and with_rep.kind == "std" and with_rep.standing == 3500


def test_faction_names_go_to_rep_meta():
    meta = run_scans(ONE_SCAN, tweak=REP_API).StatTrackerDB.repMeta
    assert meta[2696].name == "Amani" and meta[2698].name == "Midnight"


def test_collapsed_categories_are_expanded_for_the_read_and_put_back_exactly():
    g = run_scans(ONE_SCAN, tweak=REP_API + "BEFORE = CollapsedNames(); VISIBLE_BEFORE = #RepVisible()")
    assert (g.EXPAND_CALLS, g.COLLAPSE_CALLS) == (1, 1)
    assert g.CollapsedNames() == "Classic" == g.BEFORE
    assert len(g.RepVisible()) == g.VISIBLE_BEFORE                           # the player sees what they saw before
    assert 1001 in rep_of(g)                                                  # the hidden children were read


def test_nothing_is_expanded_when_no_category_is_collapsed():
    g = run_scans(ONE_SCAN, tweak=REP_API + "REP_DEFS[5].collapsed = false")
    assert (g.EXPAND_CALLS, g.COLLAPSE_CALLS) == (0, 0)
    assert 1001 in rep_of(g)


def test_nothing_is_expanded_in_combat_and_the_reputation_is_left_out():
    g = run_scans(ONE_SCAN, tweak=REP_API + "IN_COMBAT = true")
    assert (g.EXPAND_CALLS, g.COLLAPSE_CALLS) == (0, 0) and g.CollapsedNames() == "Classic"
    rec = newest(g)
    assert rec.rep is None and len(list(rec.stats.keys())) == TOTAL and rec.gear is None
    assert any("not read in combat" in t for t in chat_texts(g))
    assert any("im Kampf" in t for t in chat_texts(run_scans(ONE_SCAN, locale="deDE", tweak=REP_API + "IN_COMBAT = true")))


def test_the_categories_are_put_back_even_when_expanding_raises():
    boom = REP_API + 'local expand = C_Reputation.ExpandAllFactionHeaders; C_Reputation.ExpandAllFactionHeaders = function() expand(); error("expand boom") end'
    g = run_scans(ONE_SCAN, tweak=boom)
    assert g.CollapsedNames() == "Classic"                                    # put back although the read failed
    rec = newest(g)
    assert rec.rep is None and len(list(rec.stats.keys())) == TOTAL and rec.playedTotal == 1
    assert any("Reputation not read" in t and "expand boom" in t for t in chat_texts(g))


def test_the_categories_are_put_back_when_reading_one_entry_fails():
    broken = REP_API + 'local get = C_GossipInfo.GetFriendshipReputation; C_GossipInfo.GetFriendshipReputation = function(id) if id == 2744 then error("friend boom") end return get(id) end'
    g = run_scans(ONE_SCAN, tweak=broken)
    entries = rep_of(g)
    assert 2744 not in entries and 2696 in entries and 1001 in entries        # only the failing entry is missing
    assert g.CollapsedNames() == "Classic"
    assert any("Reputation not read" in t and "friend boom" in t for t in chat_texts(g))
    assert len(list(newest(g).stats.keys())) == TOTAL


def test_one_failing_collapse_does_not_stop_the_others():
    two = REP_API + 'REP_DEFS[8].collapsed = true; local c = C_Reputation.CollapseFactionHeader; ' \
                    'C_Reputation.CollapseFactionHeader = function(i) if RepVisible()[i].id == 3000 then error("no") end c(i) end'
    g = run_scans(ONE_SCAN, tweak=two)
    assert g.CollapsedNames() == "Classic"                                    # 3000 could not be put back, 1000 was


def test_reputation_moves_into_the_history_with_its_scan():
    g = run_scans([{"epoch": BASE_EPOCH, "played": 1}, {"epoch": BASE_EPOCH + DAY, "played": 2}], tweak=REP_API)
    older = g.StatTrackerDB.history["Alice-Realm"][1]
    assert older.rep[2].id == 2696 and older.rep[2].kind == "std"
