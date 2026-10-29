# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)
# Runs the real addon Lua code in an embedded Lua (lupa) against a faked WoW API with a
# virtual clock: the scan must be spread over ~10 seconds in small slices, announce
# "started" and "done" in chat, refuse a second scan while running, and store everything.
# Skipped without lupa (pip install lupa; listed in requirements-dev.txt).
# Note: lupa embeds Lua 5.4, WoW runs 5.1 - the addon only uses constructs common to both.

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
function UnitClass() return "Mage" end
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
