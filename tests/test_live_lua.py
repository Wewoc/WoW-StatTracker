# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)
# Runs the live part of the addon (StatTrackerLive.lua) in an embedded Lua (lupa) against a faked WoW API with a virtual
# clock: a login starts a session with the start values, /reload goes on with it, the values show the change since the
# start, a missing value is UNKNOWN (never 0), only finite numbers are saved, a missing API only switches off its part,
# and the file never writes the scan data (StatTrackerDB). Skipped without lupa (listed in requirements-dev.txt).
# Note: lupa embeds Lua 5.4, WoW runs 5.1 - the addon only uses constructs common to both.

import re
from pathlib import Path

import pytest

lupa = pytest.importorskip("lupa")

ADDON_DIR = Path(__file__).resolve().parent.parent / "addon" / "StatTracker"
LIVE = ADDON_DIR / "StatTrackerLive.lua"
WINDOW = ADDON_DIR / "StatTrackerWindow.lua"
OPTIONS = ADDON_DIR / "StatTrackerOptions.lua"
SCAN = ADDON_DIR / "StatTracker.lua"

FAKE_WOW = r'''
NOW = 1000
TIMERS = {}
function time() return NOW end
C_Timer = { After = function(delay, fn) TIMERS[#TIMERS + 1] = { t = NOW + delay, fn = fn } end }
function RunTimers(seconds)                       -- advances the clock and runs every timer that falls due
    local limit = NOW + seconds
    while true do
        table.sort(TIMERS, function(a, b) return a.t < b.t end)
        local nxt = TIMERS[1]
        if not nxt or nxt.t > limit then break end
        table.remove(TIMERS, 1)
        NOW = nxt.t
        nxt.fn()
    end
    NOW = limit
end
CHAT = {}
print = function(s) CHAT[#CHAT + 1] = s end
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
STATS = {}
MONEY = 0
function GetStatistic(id) return STATS[id] end
function GetAchievementInfo(a, b)                -- the real one takes an achievement id, or a category and an index
    if b then return a * 10000 + b, "Stat " .. (a * 10000 + b) end
    return a, "Stat " .. a
end
function GetMoney() return MONEY end
REQUESTS = 0
function RequestTimePlayed() REQUESTS = REQUESTS + 1 end
function UnitName() return "Alice" end
function GetRealmName() return "Realm" end
SlashCmdList = {}
function Serialize(v)                            -- a stable text of a table, to compare before and after
    if type(v) ~= "table" then return tostring(v) end
    local keys = {}
    for k in pairs(v) do keys[#keys + 1] = k end
    table.sort(keys, function(a, b) return tostring(a) < tostring(b) end)
    local parts = {}
    for _, k in ipairs(keys) do parts[#parts + 1] = tostring(k) .. "=" .. Serialize(v[k]) end
    return "{" .. table.concat(parts, ",") .. "}"
end
function NonFinite(v)
    if type(v) == "number" then return v ~= v or v == math.huge or v == -math.huge end
    if type(v) == "table" then
        for _, x in pairs(v) do if NonFinite(x) then return true end end
    end
    return false
end
'''

# what the scan (StatTracker.lua) needs on top, for the test that loads both files
SCAN_STUBS = r'''
function GetStatisticsCategoryList() return { 101 } end
function GetCategoryInfo(id) return "Cat" .. id, 0 end
function GetCategoryNumAchievements(id) return 3 end
function UnitClass() return "Mage", "MAGE", 8 end
function UnitRace() return "Human", "Human", 1 end
function UnitLevel() return 80 end
function UnitFactionGroup() return "Alliance" end
function RequestTimePlayed() C_Timer.After(0.1, function() Fire("TIME_PLAYED_MSG", 3600, 60) end) end     -- the answer comes a moment later
function strlower(s) return string.lower(s) end
function strtrim(s) return (s:gsub("^%s+", ""):gsub("%s+$", "")) end
date = function(f) return os.date(f) end
'''


# frames for the window (StatTrackerWindow.lua): they remember their points, shown state and scripts; Show and Hide run OnShow and OnHide
WINDOW_STUBS = r'''
MOVES = { start = 0, stop = 0 }
TIP = {}
GameTooltip = {
    SetOwner = function(self, owner) TIP = {} end,
    AddLine = function(self, text) TIP[#TIP + 1] = text end,
    Show = function(self) TIP.shown = true end,
    Hide = function(self) TIP.shown = false end,
}
BackdropTemplateMixin = {}
REGISTERED = {}
Settings = {
    RegisterCanvasLayoutCategory = function(panel, name) return { ID = 7, name = name, panel = panel } end,
    RegisterAddOnCategory = function(category) REGISTERED[#REGISTERED + 1] = category end,
}
C_AddOns = { GetAddOnMetadata = function(name, field) if name == 'StatTracker' and field == 'Version' then return TOC_VERSION end end }
TOC_VERSION = '9.9.9'
NO_ONSHOW = false                                 -- true: Show() does not call OnShow (what the game did for a window opened during a login)
CURSOR = { x = 0 }
SCALE = 1
function GetCursorPosition() return CURSOR.x, 0 end
date = function() return "12:34:56" end
local NOOPS = { "EnableMouse", "RegisterForDrag", "SetFrameStrata", "SetClampedToScreen", "SetMovable", "SetBackdrop",
                "SetBackdropColor", "SetBackdropBorderColor", "SetJustifyH", "SetWordWrap", "SetTextColor",
                "SetNormalTexture", "SetPushedTexture", "SetHighlightTexture", "SetAutoFocus", "SetCursorPosition", "ClearFocus" }
local function Methods(f)
    for _, n in ipairs(NOOPS) do f[n] = function() end end
    f.points = {}
    function f:SetPoint(p, rel, relp, x, y) self.points[#self.points + 1] = { p, rel, relp, x, y } end
    function f:ClearAllPoints() self.points = {} end
    function f:GetPoint()
        local p = self.points[1]
        if not p then return nil end
        return p[1], p[2], p[3], p[4], p[5]
    end
    function f:SetHeight(h) self.height = h end
    function f:SetText(t) self.text = t end
    function f:GetText() return self.text or '' end
    function f:HighlightText() self.highlights = (self.highlights or 0) + 1 end
    function f:GetEffectiveScale() return SCALE end
    function f:SetWidth(w) self.width = w end
    return f
end
function CreateFrame(kind, name, parent, template)
    local f = Methods({ kind = kind, events = {}, scripts = {}, shown = false, template = template })
    function f:RegisterEvent(e) self.events[e] = true end
    function f:UnregisterEvent(e) self.events[e] = nil end
    function f:SetScript(n, fn) self.scripts[n] = fn end
    function f:Show() self.shown = true if self.scripts.OnShow and not NO_ONSHOW then self.scripts.OnShow(self) end end
    function f:Hide() self.shown = false if self.scripts.OnHide and not NO_ONSHOW then self.scripts.OnHide(self) end end
    function f:IsShown() return self.shown end
    function f:StartMoving() MOVES.start = MOVES.start + 1 end
    function f:StopMovingOrSizing() MOVES.stop = MOVES.stop + 1 end
    function f:CreateFontString()
        local s = Methods({ text = "" })
        function s:SetText(t) self.text = t end
        function s:GetText() return self.text end
        return s
    end
    FRAMES[#FRAMES + 1] = f
    return f
end
UIParent = CreateFrame("Frame")
'''

SCAN_DB = '''StatTrackerDB = { version = 5, chars = { ["Alice-Realm"] = { scannedEpoch = 880, stats = {
    [107] = "90", [1487] = "--", [60] = "7", [328] = [=[%s]=] } } } }'''


def coin(gold=None, silver=None, copper=None):
    """A coin text as GetStatistic gives it: the amounts with the texture markup of the coin icons."""
    parts = [f"{amount}|TInterface\\MoneyFrame\\UI-{unit}Icon:0:0:2:0|t"
             for amount, unit in ((gold, "Gold"), (silver, "Silver"), (copper, "Copper")) if amount is not None]
    return " ".join(parts)


def load(lua, path):
    loaded = lua.eval("function(src, name) return load(src, '=' .. name) end")(path.read_text(encoding="utf-8"), path.name)
    assert not isinstance(loaded, tuple), f"Lua syntax error: {loaded}"
    return loaded


def start(locale="enUS", before="", login=True, scan=False, window=False):
    """A runtime with the fake API; `before` is Lua run after it (to break parts of it or to preset saved data).
    window=True also gives it frames and loads the window file."""
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    lua.execute(f'LOCALE = "{locale}"')
    lua.execute(FAKE_WOW)
    lua.execute("NS = {}")
    if scan:
        lua.execute(SCAN_STUBS)
    if window:
        lua.execute(WINDOW_STUBS)
    if before:
        lua.execute(before)
    if scan:
        load(lua, SCAN)("StatTracker", lua.globals().NS)
    load(lua, LIVE)("StatTracker", lua.globals().NS)
    if window:
        load(lua, WINDOW)("StatTracker", lua.globals().NS)
        load(lua, OPTIONS)("StatTracker", lua.globals().NS)
    lua.execute('Fire("ADDON_LOADED", "StatTracker")')
    if login:
        do_login(lua)
    return lua


def do_login(lua):
    lua.execute('Fire("PLAYER_ENTERING_WORLD", true, false)')


def reload_ui(lua, initial=False, window=False, settle=True):
    """What a /reload does: new Lua state of the addon, the saved variables stay; initial=True is a new login instead.
    A window that was open is opened again a moment later: with window=True the clock runs on until then (settle=False: not yet)."""
    lua.execute("FRAMES = {}; TIMERS = {}; CHAT = {}; NS = {}")
    load(lua, LIVE)("StatTracker", lua.globals().NS)
    if window:
        load(lua, WINDOW)("StatTracker", lua.globals().NS)
        load(lua, OPTIONS)("StatTracker", lua.globals().NS)
    lua.execute('Fire("ADDON_LOADED", "StatTracker")')
    lua.execute('Fire("PLAYER_ENTERING_WORLD", true, false)' if initial else 'Fire("PLAYER_ENTERING_WORLD", false, true)')
    if window and settle:
        lua.execute("RunTimers(2.5)")


def set_stats(lua, values):
    for key, value in values.items():
        lua.globals().STATS[key] = value


def entries(lua):
    values = lua.eval("NS.Live.Values()")
    return {int(e["id"]): e for e in values.stats.values()}, values


def chat_lines(lua):
    return [str(line) for line in lua.globals().CHAT.values()]


# ---------------------------------------------------------------- the saved variable and the session
def test_the_file_creates_its_saved_variable_and_nothing_else():
    lua = start()
    lua.execute("RunTimers(100)")
    g = lua.globals()
    assert g.StatTrackerUI.version == 1 and lua.eval("type(StatTrackerUI.settings)") == "table"
    assert g.StatTrackerDB is None                                   # the scan data is not this file's business


def test_a_login_starts_a_session_with_the_start_values():
    lua = start(login=False)
    set_stats(lua, {107: "100", 1487: "50", 60: "4", 98: "12", 328: coin(silver=21, copper=66)})
    lua.globals().MONEY = 5000
    do_login(lua)
    session = lua.globals().StatTrackerUI.session
    assert session.key == "Alice-Realm" and session.start == 1000 and session.money == 5000
    assert dict(session.stats.items()) == {107: 100, 1487: 50, 60: 4, 98: 12, 328: 2166}


def test_the_values_show_the_change_since_the_start():
    lua = start(login=False)
    set_stats(lua, {107: "100", 328: coin(silver=21, copper=66)})
    lua.globals().MONEY = 5000
    do_login(lua)
    lua.execute("RunTimers(20)")
    set_stats(lua, {107: "103", 328: coin(silver=21, copper=90)})
    lua.globals().MONEY = 7500
    e, values = entries(lua)
    assert e[107].number == 103 and e[107].delta == 3 and e[107].state == "LIVE"
    assert e[328].number == 2190 and e[328].delta == 24
    assert values.gold.now == 7500 and values.gold.delta == 2500
    assert values.session.key == "Alice-Realm" and values.session.age == 20


def test_a_missing_value_is_unknown_never_zero():
    lua = start(login=False)
    set_stats(lua, {107: "100", 1487: "--"})                          # 60 and 98: nothing at all
    do_login(lua)
    e, _ = entries(lua)
    for stat_id in (1487, 60, 98):
        assert e[stat_id].state == "UNKNOWN"
        assert e[stat_id].text is None and e[stat_id].number is None and e[stat_id].delta is None
    assert e[107].state == "LIVE"


def test_reload_goes_on_with_the_session_and_a_new_login_starts_a_new_one():
    lua = start(login=False)
    set_stats(lua, {107: "100"})
    do_login(lua)
    lua.execute("RunTimers(100)")
    started = lua.globals().StatTrackerUI.session.start
    reload_ui(lua)                                                    # /reload
    assert lua.globals().StatTrackerUI.session.start == started
    assert entries(lua)[1].session.age == 100
    set_stats(lua, {107: "130"})
    lua.execute("RunTimers(50)")
    reload_ui(lua, initial=True)                                      # a new login
    session = lua.globals().StatTrackerUI.session
    assert session.start == 1150 and session.stats[107] == 130


def test_a_session_of_another_character_is_not_taken_over():
    lua = start(login=False, before='StatTrackerUI = { version = 1, session = { key = "Bob-Realm", start = 1, stats = {} } }')
    lua.execute("Fire('PLAYER_ENTERING_WORLD', false, true)")         # a /reload, but the saved session is Bob's
    assert lua.globals().StatTrackerUI.session.key == "Alice-Realm"


def test_missing_start_values_are_filled_only_in_the_first_90_seconds():
    lua = start(login=False)
    set_stats(lua, {60: "4"})                                         # 107 is not there at the login
    do_login(lua)
    lua.execute("RunTimers(20)")
    assert lua.globals().StatTrackerUI.session.stats[107] is None
    set_stats(lua, {107: "100"})                                      # it arrives after 20 seconds
    lua.execute("RunTimers(30)")                                      # the read after 45 seconds fills it
    assert lua.globals().StatTrackerUI.session.stats[107] == 100
    lua.execute("RunTimers(100)")                                     # all reads done, the window is over
    set_stats(lua, {98: "12"})
    e, _ = entries(lua)
    assert lua.globals().StatTrackerUI.session.stats[98] is None      # a start value that shows up late would be wrong
    assert e[98].number == 12 and e[98].delta is None


# ---------------------------------------------------------------- reading
def test_coin_texts_are_turned_into_copper():
    parse = start().eval("NS.Live.ParseCoins")
    assert parse(coin(gold=12301, silver=7, copper=76)) == 123010776
    assert parse(coin(silver=21, copper=66)) == 2166
    assert parse(coin(gold="1.234")) == 12340000                      # a thousands separator of the client language
    assert parse("--") is None and parse("123") is None and parse(None) is None


def test_numbers_with_separators_and_everything_that_is_no_number():
    lua = start()
    parse = lua.eval("NS.Live.ParseNumber")
    assert parse("11560") == 11560 and parse("11.560") == 11560 and parse("1,234") == 1234 and parse("-5") == -5
    for bad in ("--", "", "abc", "1e999", "12 g"):
        assert parse(bad) is None
    assert parse(None) is None and parse(42) == 42
    assert lua.eval("NS.Live.ParseNumber(math.huge)") is None and lua.eval("NS.Live.ParseNumber(0/0)") is None


@pytest.mark.parametrize("bad", ["math.huge", "-math.huge", "0/0"])
def test_only_finite_numbers_are_saved(bad):
    lua = start(login=False)
    lua.execute(f"GetMoney = function() return {bad} end")
    set_stats(lua, {107: "1e999", 1487: "99"})
    do_login(lua)
    lua.execute("RunTimers(100)")
    entries(lua)
    session = lua.globals().StatTrackerUI.session
    assert session.money is None and session.stats[107] is None and session.stats[1487] == 99
    assert lua.eval("NonFinite(StatTrackerUI)") is False


# ---------------------------------------------------------------- a client without parts of the API
def test_missing_apis_switch_off_their_part_without_an_error():
    lua = start(login=False, before="GetStatistic = nil; GetMoney = nil; GetAchievementInfo = nil; C_Timer = nil; RequestTimePlayed = nil")
    do_login(lua)                                                     # an error in a handler would raise here
    lua.execute('NS.Live.SetActive("window", true); Fire("PARTY_KILL")')      # without C_Timer nothing runs by itself, and nothing breaks
    lua.execute('SlashCmdList["STATLIVE"]("")')
    assert any("no statistics" in line for line in chat_lines(lua))
    assert lua.globals().StatTrackerUI.session.key == "Alice-Realm"
    assert lua.eval("NS.Live.Values()").available is False


def test_without_a_character_name_there_is_no_session_and_no_error():
    lua = start(login=False, before="UnitName = nil")
    do_login(lua)
    assert lua.globals().StatTrackerUI.session is None
    lua.execute('SlashCmdList["STATLIVE"]("")')


# ---------------------------------------------------------------- the saved data of other parts
def test_the_live_file_never_writes_the_scan_data():
    lua = start(login=False, before='StatTrackerDB = { version = 5, chars = { ["A-B"] = { scannedAt = "x", stats = { [1] = "5" } } } }')
    before = lua.eval("Serialize(StatTrackerDB)")
    set_stats(lua, {107: "100"})
    do_login(lua)
    lua.execute("RunTimers(100)")
    lua.execute('SlashCmdList["STATLIVE"]("")')
    assert lua.eval("Serialize(StatTrackerDB)") == before


def test_the_live_file_does_not_even_mention_the_scan_data_in_its_code():
    code = "\n".join(line for line in LIVE.read_text(encoding="utf-8").splitlines() if not line.lstrip().startswith("--"))
    assert "StatTrackerDB" not in code


def test_a_file_written_by_a_newer_addon_is_left_alone():
    lua = start(login=False, before='StatTrackerUI = { version = 99, session = { key = "X", start = 5 } }')
    before = lua.eval("Serialize(StatTrackerUI)")
    do_login(lua)
    lua.execute("RunTimers(100)")
    assert lua.eval("Serialize(StatTrackerUI)") == before
    assert lua.eval("NS.Live.Values()").session is None


# ---------------------------------------------------------------- the chat
@pytest.mark.parametrize("locale, header, none, gold", [
    ("enUS", "Live (Alice-Realm, for 2 min):", "no value", "Session gold: +0 g 25 s 0 c"),
    ("deDE", "Live (Alice-Realm, seit 2 min):", "kein Wert", "Session-Gold: +0 g 25 s 0 c"),
])
def test_the_chat_status_lists_the_values_and_their_change(locale, header, none, gold):
    lua = start(locale, login=False)
    set_stats(lua, {107: "100", 1487: "50", 98: "12", 328: coin(silver=21, copper=66)})     # 60 has no value
    lua.globals().MONEY = 5000
    do_login(lua)
    lua.execute("RunTimers(125)")
    set_stats(lua, {107: "103", 328: coin(silver=21, copper=90)})
    lua.globals().MONEY = 7500
    lua.execute('SlashCmdList["STATLIVE"]("")')
    text = "\n".join(chat_lines(lua))
    assert header in text and "Stat 107: 103 (+3)" in text and f"Stat 60: {none}" in text
    assert "Stat 328: 0 g 21 s 90 c (+0 g 0 s 24 c)" in text and gold in text


@pytest.mark.parametrize("before, shown", [
    ('function UnitName() return "Alice", "Smith" end', "Alice Smith / Realm"),          # WoW Forever: the second value is the surname
    ('function UnitName() return "Alice" end', "Alice-Realm"),                           # Retail: no surname, the key as before
    ('function UnitName() return "Alice", "Realm" end', "Alice-Realm"),                  # the realm is no surname
    ('function UnitName() return "Alice", "" end', "Alice-Realm"),
    ('function UnitName() return "Alice", "RealmX" end function GetNormalizedRealmName() return "RealmX" end', "Alice-Realm"),
])
def test_the_name_shown_follows_the_surname_only_when_there_is_one(before, shown):
    lua = start(login=False, before=before)
    do_login(lua)
    lua.execute('SlashCmdList["STATLIVE"]("")')
    assert f"Live ({shown}, for 0 min):" in "\n".join(chat_lines(lua))
    assert lua.globals().StatTrackerUI.session.key == "Alice-Realm"            # the key stays what the scan stores
    assert lua.eval("NS.Live.Values()").session.display == shown


# ---------------------------------------------------------------- the played time
def test_the_played_time_is_asked_once_after_the_login_and_then_estimated():
    lua = start()
    lua.execute("RunTimers(7)")
    assert lua.globals().REQUESTS == 0
    lua.execute("RunTimers(2)")                                       # 8 seconds after the login
    assert lua.globals().REQUESTS == 1
    lua.execute('Fire("TIME_PLAYED_MSG", 1000, 100)')
    lua.execute("RunTimers(60)")
    played = lua.eval("NS.Live.Values()").played
    assert played.base == 1000 and played.total == 1060 and played.estimate is True
    lua.execute("RunTimers(600)")
    assert lua.globals().REQUESTS == 1                                # never again while there is a base


def test_every_answer_about_the_played_time_sets_the_base_again():
    lua = start()
    lua.execute('Fire("TIME_PLAYED_MSG", 1000, 100)')
    lua.execute("RunTimers(60)")
    lua.execute('Fire("TIME_PLAYED_MSG", 5000, 10)')                  # the scan's answer or a manual /played
    played = lua.eval("NS.Live.Values()").played
    assert played.base == 5000 and played.total == 5000 and played.estimate is False


def test_reload_keeps_the_played_time_base_and_does_not_ask_again():
    lua = start()
    lua.execute("RunTimers(8)")
    lua.execute('Fire("TIME_PLAYED_MSG", 1000, 100)')
    reload_ui(lua)
    lua.execute("RunTimers(60)")
    assert lua.globals().REQUESTS == 1
    assert lua.eval("NS.Live.Values()").played.base == 1000


def test_a_reload_without_a_base_asks_once():
    lua = start()
    reload_ui(lua)
    lua.execute("RunTimers(9)")
    assert lua.globals().REQUESTS == 1                                # the login's timer was gone with the old state, the reload's one counts


def test_without_an_answer_there_is_no_played_time_never_zero():
    lua = start()
    lua.execute("RunTimers(100)")
    assert lua.eval("NS.Live.Values()").played is None
    lua.execute('SlashCmdList["STATLIVE"]("")')
    assert any("Played time: no value" in line for line in chat_lines(lua))


@pytest.mark.parametrize("bad", ["1/0", "-1/0", "0/0", "-5", '"abc"', "nil"])
def test_an_answer_that_is_not_a_good_number_is_ignored(bad):
    lua = start()
    lua.execute(f'Fire("TIME_PLAYED_MSG", {bad}, 5)')
    assert lua.eval("NS.Live.Values()").played is None
    assert lua.eval("NonFinite(StatTrackerUI)") is False


# ---------------------------------------------------------------- rates, the reading while the data is shown, watch
def test_rates_per_hour_appear_after_two_minutes():
    lua = start(login=False)
    set_stats(lua, {107: "100"})
    lua.globals().MONEY = 5000
    do_login(lua)
    lua.execute("RunTimers(100)")
    set_stats(lua, {107: "110"})
    lua.globals().MONEY = 5100
    assert lua.eval("NS.Live.Values()").rates.ready is False
    lua.execute("RunTimers(25)")                                      # 125 seconds into the session
    rates = lua.eval("NS.Live.Values()").rates
    assert rates.ready is True and rates.kills == pytest.approx(288.0) and rates.gold == pytest.approx(2880.0)


def test_the_reading_runs_every_five_seconds_only_while_something_wants_it():
    lua = start()
    lua.execute("POLLS = 0; NS.Live.onUpdate = function() POLLS = POLLS + 1 end")
    lua.execute("RunTimers(30)")
    assert lua.globals().POLLS == 0                                   # nobody shows the data
    lua.execute('NS.Live.SetActive("window", true)')
    assert lua.globals().POLLS == 1                                   # the first read at once
    lua.execute('NS.Live.SetActive("window", true)')                  # asking twice does not start a second loop
    lua.execute("RunTimers(30)")
    assert lua.globals().POLLS == 7
    lua.execute('NS.Live.SetActive("watch", true); NS.Live.SetActive("window", false)')     # still wanted by the other one
    lua.execute("RunTimers(10)")
    assert lua.globals().POLLS == 9
    lua.execute('NS.Live.SetActive("watch", false)')
    lua.execute("RunTimers(30)")
    assert lua.globals().POLLS == 9                                   # nobody wants it any more


def test_events_trigger_one_read_two_seconds_later_and_only_while_the_reading_is_wanted():
    lua = start()
    lua.execute("POLLS = 0; NS.Live.onUpdate = function() POLLS = POLLS + 1 end")
    lua.execute('Fire("PARTY_KILL"); RunTimers(5)')
    assert lua.globals().POLLS == 0
    lua.execute('NS.Live.SetActive("window", true)')                  # one read at once, the next tick is 5 seconds away
    lua.execute('Fire("PARTY_KILL"); Fire("QUEST_TURNED_IN"); Fire("PLAYER_MONEY")')
    lua.execute("RunTimers(1.9)")
    assert lua.globals().POLLS == 1
    lua.execute("RunTimers(0.2)")
    assert lua.globals().POLLS == 2                                   # three events, one read
    lua.execute('Fire("PARTY_KILL"); RunTimers(2.1)')
    assert lua.globals().POLLS == 3


def test_a_client_that_refuses_an_event_still_gets_the_others():
    refuse = ('local plain = CreateFrame '
              'function CreateFrame(...) local f = plain(...) local reg = f.RegisterEvent '
              'function f:RegisterEvent(e) if e == "PARTY_KILL" then error("unknown event") end reg(self, e) end return f end')
    lua = start(before=refuse)
    lua.execute("POLLS = 0; NS.Live.onUpdate = function() POLLS = POLLS + 1 end")
    lua.execute('NS.Live.SetActive("window", true); Fire("QUEST_TURNED_IN"); RunTimers(2.5)')
    assert lua.globals().POLLS == 2


def test_watch_writes_each_change_to_the_chat_and_stops_when_switched_off():
    lua = start(login=False)
    set_stats(lua, {107: "100"})
    do_login(lua)
    lua.execute('SlashCmdList["STATLIVE"]("watch")')
    assert any("Watching on" in line for line in chat_lines(lua))
    set_stats(lua, {107: "103"})
    lua.execute("RunTimers(5)")
    assert any("Stat 107: 100 -> 103 (+3)" in line for line in chat_lines(lua))
    lua.execute('SlashCmdList["STATLIVE"]("WATCH ")')                 # case and spaces do not matter
    assert any("Watching off" in line for line in chat_lines(lua))
    count = len(chat_lines(lua))
    set_stats(lua, {107: "110"})
    lua.execute("RunTimers(30)")
    assert len(chat_lines(lua)) == count


@pytest.mark.parametrize("locale, played, note, gold, kills", [
    ("enUS", "Played time: 0d 1h 3m", "(estimated)", "Gold per hour: +0 g 28 s 80 c", "Stat 107 per hour: 288.0"),
    ("deDE", "Spielzeit: 0d 1h 3m", "(geschaetzt)", "Gold pro Stunde: +0 g 28 s 80 c", "Stat 107 pro Stunde: 288.0"),
])
def test_the_chat_status_shows_the_played_time_and_the_rates(locale, played, note, gold, kills):
    lua = start(locale, login=False)
    set_stats(lua, {107: "100"})
    lua.globals().MONEY = 5000
    do_login(lua)
    lua.execute("RunTimers(10)")
    lua.execute('Fire("TIME_PLAYED_MSG", 3700, 100)')                 # second 10 of the session
    lua.execute("RunTimers(115)")                                     # second 125
    set_stats(lua, {107: "110"})
    lua.globals().MONEY = 5100
    lua.execute('SlashCmdList["STATLIVE"]("")')
    text = "\n".join(chat_lines(lua))
    assert played in text and note in text and gold in text and kills in text


@pytest.mark.parametrize("locale, text", [("enUS", "Rates after 2 min of session"), ("deDE", "Raten ab 2 min Sitzungsdauer")])
def test_before_two_minutes_the_status_says_when_the_rates_come(locale, text):
    lua = start(locale)
    lua.execute("RunTimers(60)")
    lua.execute('SlashCmdList["STATLIVE"]("")')
    assert text in "\n".join(chat_lines(lua))


# ---------------------------------------------------------------- together with the scan
def test_the_scan_and_the_live_file_load_together_and_do_not_disturb_each_other():
    lua = start(login=False, scan=True)
    set_stats(lua, {107: "100"})
    do_login(lua)
    lua.execute("RunTimers(60)")                                      # the auto-scan starts after 10 seconds, takes about 10, then asks for the played time
    g = lua.globals()
    assert g.StatTrackerDB.version == 5 and g.StatTrackerDB.chars["Alice-Realm"].playedTotal == 3600
    assert g.StatTrackerUI.session.key == "Alice-Realm" and g.StatTrackerUI.session.stats[107] == 100
    assert lua.eval('StatTrackerDB.session == nil and StatTrackerUI.chars == nil')
    assert lua.eval("NS.Live.Values()").played.base == 3600           # the answer to the scan's request is also this file's base


# ---------------------------------------------------------------- the files of the addon
def test_every_file_of_the_toc_exists_and_both_variables_are_declared():
    toc = (ADDON_DIR / "StatTracker.toc").read_text(encoding="utf-8")
    files = [line.strip() for line in toc.splitlines() if line.strip() and not line.startswith("#")]
    assert files == ["StatTracker.lua", "StatTrackerLive.lua", "StatTrackerWindow.lua", "StatTrackerOptions.lua"]     # the scan, the live part, its window, its options page
    assert all((ADDON_DIR / name).is_file() for name in files)
    assert sorted(p.name for p in ADDON_DIR.glob("*.lua")) == sorted(files)     # no Lua file the toc does not list
    declared = re.search(r"(?m)^## SavedVariables:\s*(.+)$", toc).group(1)
    assert [name.strip() for name in declared.split(",")] == ["StatTrackerDB", "StatTrackerUI"]


# ---------------------------------------------------------------- the window (StatTrackerWindow.lua)
def window_lines(lua):
    table = lua.eval("NS.Live.WindowLines(NS.Live.Values())")
    return [table[i] for i in range(1, len(table) + 1)]


def row_texts(lua):
    """What the drawn rows say: (left, right) per visible row."""
    rows = lua.eval("NS.Live.window.rows")
    return [(rows[i].left.text, rows[i].right.text) for i in range(1, len(rows) + 1) if rows[i].shown]


def window_start(locale="enUS", scan_db=True, before="", login=True):
    db = SCAN_DB % coin(gold=1, silver=2, copper=3) if scan_db else ""
    return start(locale, before=db + "\n" + before, login=login, window=True)


def test_the_rows_show_live_values_with_their_change_and_the_value_of_the_last_scan_in_the_tooltip():
    lua = window_start(login=False)
    set_stats(lua, {107: "100"})
    do_login(lua)
    lua.execute("RunTimers(20)")
    set_stats(lua, {107: "103"})
    lines = {str(l.label): l for l in window_lines(lua)}
    assert lines["Stat 107"].value == "103 (+3)" and lines["Stat 107"].state == "LIVE"
    assert lines["Stat 107"].tip == "Last scan: 90, 2 min ago"
    assert lines["Alice-Realm"].state == "HEAD"


def test_a_statistic_without_a_live_value_shows_the_scan_dimmed_and_without_any_value_it_is_unknown_never_zero():
    lua = window_start(login=False)
    set_stats(lua, {107: "100"})                                      # 60, 98 and 328: nothing live
    do_login(lua)
    lines = {str(l.label): l for l in window_lines(lua)}
    assert (lines["Stat 60"].value, lines["Stat 60"].state) == ("7 (Scan)", "SNAPSHOT")
    assert lines["Stat 60"].tip == "Last scan: 7, 2 min ago"
    assert (lines["Stat 328"].value, lines["Stat 328"].state) == ("1 g 2 s 3 c (Scan)", "SNAPSHOT")      # a coin text, as in the live part
    assert (lines["Stat 1487"].value, lines["Stat 1487"].state) == ("no value", "UNKNOWN")             # the scan has "--" there
    assert (lines["Stat 98"].value, lines["Stat 98"].state, lines["Stat 98"].tip) == ("no value", "UNKNOWN", "No scan yet")
    assert not any(str(l.value) in ("0", "0 (Scan)") for l in window_lines(lua))


def test_without_any_scan_the_tooltips_say_so_and_the_footer_says_none_yet():
    lua = window_start(scan_db=False)
    lines = window_lines(lua)
    assert all(l.tip == "No scan yet" for l in lines if str(l.label).startswith("Stat "))
    assert (lines[-1].label, lines[-1].value) == ("Last scan", "none yet")
    assert (lines[-2].label, lines[-2].value) == ("Updated", "12:34:56")


@pytest.mark.parametrize("locale, label, age, played", [("enUS", "Last scan", "2 min ago", "Played time"),
                                                          ("deDE", "Letzter Scan", "vor 2 min", "Spielzeit")])
def test_the_texts_follow_the_language_of_the_client(locale, label, age, played):
    lua = window_start(locale)
    lines = window_lines(lua)
    assert (lines[-1].label, lines[-1].value) == (label, age)
    assert any(l.label == played for l in lines)
    assert any(str(l.tip).startswith("Letzter Scan: ") for l in lines) == (locale == "deDE")


def test_the_rates_rows_come_after_two_minutes_and_the_window_grows_with_its_rows():
    lua = window_start(login=False)
    set_stats(lua, {107: "100"})
    lua.globals().MONEY = 5000
    do_login(lua)
    lua.execute("RunTimers(60)")
    before = window_lines(lua)
    assert [(l.label, l.value) for l in before if l.label == "Rates"] == [("Rates", "after 2 min")]
    lua.execute("NS.Live.OpenWindow()")
    first_height = lua.eval("NS.Live.window.height")
    set_stats(lua, {107: "110"})
    lua.globals().MONEY = 5100
    lua.execute("RunTimers(65)")                                      # second 125: the next read draws the rates
    after = window_lines(lua)
    assert len(after) == len(before) + 1 and {"Gold per hour", "Stat 107 per hour"} <= {str(l.label) for l in after}
    assert lua.eval("NS.Live.window.height") == first_height + 16


def test_a_client_without_statistics_shows_one_line_and_no_error():
    lua = window_start(before="GetStatistic = nil")
    lines = window_lines(lua)
    assert [str(l.label) for l in lines][1] == "This client provides no statistics."


def test_statlive_shows_and_hides_the_window_and_the_reading_runs_only_while_it_is_open():
    lua = window_start(login=False)
    set_stats(lua, {107: "100"})
    do_login(lua)
    assert lua.eval("NS.Live.window") is None                         # nothing built before it is wanted
    lua.execute('SlashCmdList["STATLIVE"]("")')
    assert lua.eval("NS.Live.window:IsShown()") is True
    assert ("Stat 107", "100 (+0)") in row_texts(lua)
    set_stats(lua, {107: "104"})
    lua.execute("RunTimers(5)")
    assert ("Stat 107", "104 (+4)") in row_texts(lua)                 # the 5 second reading redraws it
    lua.execute('SlashCmdList["STATLIVE"]("")')
    assert lua.eval("NS.Live.window:IsShown()") is False
    set_stats(lua, {107: "999"})
    lua.execute("RunTimers(30)")
    assert ("Stat 107", "999 (+899)") not in row_texts(lua)           # closed: nobody reads and nothing redraws
    lua.execute("POLLS = 0; local poll = NS.Live.Poll; NS.Live.Poll = function() POLLS = POLLS + 1 return poll() end")
    lua.execute("RunTimers(30)")
    assert lua.globals().POLLS == 0                                   # really nothing is read in the background
    assert not any("Live (" in line for line in chat_lines(lua))      # the window replaces the chat text


def test_statlive_text_still_writes_the_chat_and_opens_no_window():
    lua = window_start()
    lua.execute('SlashCmdList["STATLIVE"]("text")')
    assert any("Live (Alice-Realm" in line for line in chat_lines(lua))
    assert lua.eval("NS.Live.window") is None


def test_the_close_button_closes_the_window_and_stops_the_reading():
    lua = window_start()
    lua.execute("NS.Live.OpenWindow()")
    lua.execute("NS.Live.window.close.scripts.OnClick()")
    assert lua.eval("NS.Live.window:IsShown()") is False
    assert lua.globals().StatTrackerUI.settings.window.shown is False
    lua.execute("RunTimers(1)")
    assert lua.eval("NS.Live.window:IsShown()") is False


def test_dragging_moves_the_window_and_saves_the_position_and_the_next_login_puts_it_back():
    lua = window_start()
    lua.execute("NS.Live.OpenWindow()")
    assert lua.eval("NS.Live.window.points[1][1]") == "CENTER"        # the first time: the middle
    lua.execute('local w = NS.Live.window; w.scripts.OnDragStart(w); w.points = { { "RIGHT", UIParent, "RIGHT", -384.5, -151.5 } }; w.scripts.OnDragStop(w)')
    assert lua.globals().MOVES.start == 1 and lua.globals().MOVES.stop == 1
    saved = lua.globals().StatTrackerUI.settings.window
    assert (saved.point, saved.rel, saved.x, saved.y, saved.shown) == ("RIGHT", "RIGHT", -384.5, -151.5, True)
    reload_ui(lua, window=True)                                       # a /reload with the window open: it comes back, there
    assert lua.eval("NS.Live.window:IsShown()") is True
    assert lua.eval("NS.Live.window.points[1][1] .. NS.Live.window.points[1][4]") == "RIGHT-384.5"
    set_stats(lua, {107: "110"})
    lua.execute("RunTimers(5)")                                       # and it reads again
    assert any(left == "Stat 107" and right.startswith("110") for left, right in row_texts(lua))


def test_a_row_moves_the_window_as_well():
    lua = window_start()
    lua.execute("NS.Live.OpenWindow()")
    lua.execute("local r = NS.Live.window.rows[2]; r.scripts.OnDragStart(r); r.scripts.OnDragStop(r)")
    assert lua.globals().MOVES.start == 1 and lua.globals().MOVES.stop == 1


def test_a_window_that_was_closed_or_never_opened_does_not_come_back():
    lua = window_start()
    reload_ui(lua, window=True)
    assert lua.eval("NS.Live.window") is None                         # never opened
    lua.execute("NS.Live.OpenWindow(); NS.Live.CloseWindow()")
    reload_ui(lua, window=True)
    assert lua.eval("NS.Live.window") is None


def test_a_reload_that_hides_the_frame_by_itself_does_not_lose_the_open_state():
    lua = window_start()
    lua.execute("NS.Live.OpenWindow()")
    lua.execute("NS.Live.window:Hide()")                              # the game may hide frames while it tears the interface down
    assert lua.globals().StatTrackerUI.settings.window.shown is True
    reload_ui(lua, window=True)
    assert lua.eval("NS.Live.window:IsShown()") is True


@pytest.mark.parametrize("saved", [
    '{ point = "NOWHERE", rel = "CENTER", x = 1, y = 2, shown = true }',
    '{ point = "CENTER", rel = "CENTER", x = 1/0, y = 2, shown = true }',
    '{ point = "CENTER", rel = "CENTER", x = 0/0, y = 2, shown = true }',
    '{ point = "CENTER", rel = "CENTER", x = 1, y = "2", shown = true }',
    '{ point = "CENTER", rel = "CENTER", x = 1e7, y = 2, shown = true }',
    '"garbage"',
])
def test_a_damaged_saved_position_falls_back_to_the_middle(saved):
    lua = window_start(login=False, before=f'StatTrackerUI = {{ version = 1, settings = {{ window = {saved} }} }}')
    do_login(lua)
    lua.execute("NS.Live.OpenWindow()")
    assert lua.eval("NS.Live.window.points[1][1]") == "CENTER" and lua.eval("NS.Live.window.points[1][4]") == 0


def test_a_position_that_is_not_finite_is_never_saved():
    lua = window_start()
    lua.execute("NS.Live.OpenWindow()")
    lua.execute('local w = NS.Live.window; w.points = { { "CENTER", UIParent, "CENTER", 0/0, 1/0 } }; w.scripts.OnDragStop(w)')
    lua.execute("NS.Live.CloseWindow()")
    assert lua.eval("NonFinite(StatTrackerUI)") is False
    saved = lua.globals().StatTrackerUI.settings.window
    assert (saved.x, saved.y) == (0, 0)                               # the last good position stays, nothing non-finite replaces it


def test_the_window_never_writes_the_scan_data_and_never_assigns_to_it_in_its_code():
    lua = window_start(login=False)
    before = lua.eval("Serialize(StatTrackerDB)")
    set_stats(lua, {107: "100"})
    do_login(lua)
    lua.execute('SlashCmdList["STATLIVE"](""); RunTimers(30); SlashCmdList["STATLIVE"]("")')
    assert lua.eval("Serialize(StatTrackerDB)") == before
    code = "\n".join(line for line in WINDOW.read_text(encoding="utf-8").splitlines() if not line.lstrip().startswith("--"))
    assert not re.search(r"StatTrackerDB\s*=[^=]", code) and not re.search(r"StatTrackerDB[\.\[][^\n]*[^=~<>]=[^=]", code)


def test_a_file_written_by_a_newer_addon_is_left_alone_by_the_window_too():
    lua = start(login=False, window=True, before='StatTrackerUI = { version = 99, settings = { window = { shown = true } } }')
    before = lua.eval("Serialize(StatTrackerUI)")
    do_login(lua)
    assert lua.eval("NS.Live.window") is None                         # not restored from a file of a newer version
    lua.execute('SlashCmdList["STATLIVE"](""); NS.Live.CloseWindow()')    # it still opens by hand, but writes nothing
    assert lua.eval("Serialize(StatTrackerUI)") == before


def test_a_client_that_cannot_build_the_window_falls_back_to_the_chat_text():
    lua = window_start(before="UIParent = nil")
    lua.execute('SlashCmdList["STATLIVE"]("")')
    text = "\n".join(chat_lines(lua))
    assert "Window not possible" in text and "Live (Alice-Realm" in text


def test_a_missing_part_of_the_frame_api_only_costs_that_part():
    lua = window_start(before='local plain = CreateFrame '
                              'function CreateFrame(...) local f = plain(...) f.SetBackdrop = nil f.RegisterForDrag = nil '
                              'f.SetClampedToScreen = nil f.SetFrameStrata = nil return f end')
    lua.execute('SlashCmdList["STATLIVE"]("")')
    assert lua.eval("NS.Live.window:IsShown()") is True and row_texts(lua)


def test_without_the_window_file_statlive_still_writes_the_chat_text():
    lua = start()
    lua.execute('SlashCmdList["STATLIVE"]("")')
    assert any("Live (Alice-Realm" in line for line in chat_lines(lua))


# ---------------------------------------------------------------- the corner that changes the width
def drag_corner(lua, start_x, end_x, button="LeftButton"):
    lua.execute(f'CURSOR.x = {start_x}; local g = NS.Live.window.grip; g.scripts.OnMouseDown(g, "{button}")')
    lua.execute(f"CURSOR.x = {end_x}; local g = NS.Live.window.grip; if g.scripts.OnUpdate then g.scripts.OnUpdate(g, 0.01) end")
    lua.execute("local g = NS.Live.window.grip; g.scripts.OnMouseUp(g)")


def test_the_window_starts_340_wide_and_the_default_is_not_saved_as_a_choice():
    lua = window_start()
    lua.execute("NS.Live.OpenWindow()")
    assert lua.eval("NS.Live.window.width") == 340 and lua.eval("NS.Live.window.grip ~= nil")
    assert lua.globals().StatTrackerUI.settings.window.width is None


def test_dragging_the_corner_changes_the_width_and_saves_it():
    lua = window_start()
    lua.execute("NS.Live.OpenWindow()")
    drag_corner(lua, 1000, 1100)
    assert lua.eval("NS.Live.window.width") == 440
    assert lua.globals().StatTrackerUI.settings.window.width == 440


def test_the_width_follows_the_ui_scale_of_the_window():
    lua = window_start()
    lua.execute("NS.Live.OpenWindow()")
    lua.execute("SCALE = 0.5")                                        # 100 screen pixels are 200 units of the window
    drag_corner(lua, 1000, 1100)
    assert lua.eval("NS.Live.window.width") == 540


@pytest.mark.parametrize("end_x, expected", [(100000, 700), (-100000, 240)])
def test_the_width_stays_between_its_limits(end_x, expected):
    lua = window_start()
    lua.execute("NS.Live.OpenWindow()")
    drag_corner(lua, 1000, end_x)
    assert lua.eval("NS.Live.window.width") == expected


@pytest.mark.parametrize("anchor, x, new_x", [("CENTER", 0, 50), ("RIGHT", -384.5, -284.5), ("TOPLEFT", 20, 20), ("BOTTOMRIGHT", -5, 95)])
def test_the_left_edge_stays_where_it_is_when_the_width_changes(anchor, x, new_x):
    lua = window_start()
    lua.execute("NS.Live.OpenWindow()")
    lua.execute(f'local w = NS.Live.window; w.points = {{ {{ "{anchor}", UIParent, "{anchor}", {x}, -10 }} }}')
    drag_corner(lua, 1000, 1100)
    point = lua.eval("NS.Live.window.points[1]")
    assert (point[1], point[4], point[5]) == (anchor, new_x, -10)


def test_the_saved_width_comes_back_after_a_reload():
    lua = window_start()
    lua.execute("NS.Live.OpenWindow()")
    drag_corner(lua, 1000, 1100)
    reload_ui(lua, window=True)
    assert lua.eval("NS.Live.window.width") == 440


@pytest.mark.parametrize("saved", ["1/0", "0/0", "10", "99999", '"wide"', "true"])
def test_a_saved_width_that_is_not_usable_gives_the_default(saved):
    lua = window_start(login=False, before=f'StatTrackerUI = {{ version = 1, settings = {{ window = {{ width = {saved} }} }} }}')
    do_login(lua)
    lua.execute("NS.Live.OpenWindow()")
    assert lua.eval("NS.Live.window.width") == 340


def test_letting_go_of_the_mouse_ends_the_dragging():
    lua = window_start()
    lua.execute("NS.Live.OpenWindow()")
    drag_corner(lua, 1000, 1100)
    assert lua.eval("NS.Live.window.grip.scripts.OnUpdate") is None
    lua.execute("CURSOR.x = 5000")
    assert lua.eval("NS.Live.window.width") == 440


def test_only_the_left_mouse_button_drags_the_corner():
    lua = window_start()
    lua.execute("NS.Live.OpenWindow()")
    drag_corner(lua, 1000, 1100, button="RightButton")
    assert lua.eval("NS.Live.window.width") == 340


def test_a_cursor_position_that_is_not_a_number_is_ignored():
    lua = window_start()
    lua.execute("NS.Live.OpenWindow()")
    lua.execute('CURSOR.x = 1000; local g = NS.Live.window.grip; g.scripts.OnMouseDown(g, "LeftButton"); CURSOR.x = 0/0; g.scripts.OnUpdate(g, 0.01)')
    assert lua.eval("NS.Live.window.width") == 340
    assert lua.eval("NonFinite(StatTrackerUI)") is False


def test_a_client_without_the_cursor_function_leaves_the_width_alone():
    lua = window_start(before="")
    lua.execute("NS.Live.OpenWindow(); GetCursorPosition = nil")
    lua.execute('local g = NS.Live.window.grip; g.scripts.OnMouseDown(g, "LeftButton"); g.scripts.OnMouseUp(g)')
    assert lua.eval("NS.Live.window.width") == 340


# ---------------------------------------------------------------- a window opened during a login (the window of a /reload showed no rows)
def test_a_window_whose_onshow_the_game_does_not_call_still_draws_and_reads():
    lua = window_start(login=False)
    set_stats(lua, {107: "100"})
    do_login(lua)
    lua.execute("RunTimers(3)")                                       # the moment in which a saved window would come back has passed
    lua.execute("NO_ONSHOW = true")
    lua.execute("NS.Live.OpenWindow()")
    assert ("Stat 107", "100 (+0)") in row_texts(lua)                 # drawn without OnShow
    set_stats(lua, {107: "104"})
    lua.execute("RunTimers(5)")
    assert ("Stat 107", "104 (+4)") in row_texts(lua)                 # and the reading runs
    lua.execute("NS.Live.CloseWindow()")
    lua.execute("POLLS = 0; local poll = NS.Live.Poll; NS.Live.Poll = function() POLLS = POLLS + 1 return poll() end; RunTimers(30)")
    assert lua.globals().POLLS == 0                                   # closing stops it without OnHide as well


def test_a_restored_window_shows_its_rows_even_when_the_game_does_not_call_onshow():
    lua = window_start()
    lua.execute("NS.Live.OpenWindow()")
    lua.execute("NO_ONSHOW = true")
    reload_ui(lua, window=True)
    assert lua.eval("NS.Live.window:IsShown()") is True
    assert any(left == "Stat 107" for left, _ in row_texts(lua))


def test_a_window_that_was_open_comes_back_a_moment_after_the_login_not_in_the_middle_of_it():
    lua = window_start()
    lua.execute("NS.Live.OpenWindow()")
    reload_ui(lua, window=True, settle=False)
    assert lua.eval("NS.Live.window") is None
    lua.execute("RunTimers(1.5)")
    assert lua.eval("NS.Live.window") is None
    lua.execute("RunTimers(1)")
    assert lua.eval("NS.Live.window:IsShown()") is True and row_texts(lua)


def test_a_client_without_timers_restores_the_window_at_once():
    lua = window_start()
    lua.execute("NS.Live.OpenWindow()")
    lua.execute("FRAMES = {}; TIMERS = {}; CHAT = {}; NS = {}; C_Timer = nil")
    load(lua, LIVE)("StatTracker", lua.globals().NS)
    load(lua, WINDOW)("StatTracker", lua.globals().NS)
    lua.execute('Fire("ADDON_LOADED", "StatTracker"); Fire("PLAYER_ENTERING_WORLD", false, true)')
    assert lua.eval("NS.Live.window:IsShown()") is True


def test_an_error_while_drawing_is_told_once_in_the_chat_and_does_not_stop_the_window():
    lua = window_start()
    lua.execute('NS.Live.WindowLines = function() error("boom") end')
    lua.execute("NS.Live.OpenWindow()")                               # raises nothing
    assert lua.eval("NS.Live.window:IsShown()") is True
    told = [line for line in chat_lines(lua) if "error while drawing" in line and "boom" in line]
    assert len(told) == 1
    lua.execute("RunTimers(20)")                                      # four more readings: still one message
    assert len([line for line in chat_lines(lua) if "error while drawing" in line]) == 1


def test_an_error_while_restoring_the_window_is_told_in_the_chat():
    lua = window_start()
    lua.execute("NS.Live.OpenWindow()")
    lua.execute("FRAMES = {}; TIMERS = {}; CHAT = {}; NS = {}")
    load(lua, LIVE)("StatTracker", lua.globals().NS)
    load(lua, WINDOW)("StatTracker", lua.globals().NS)
    lua.execute('Fire("ADDON_LOADED", "StatTracker"); UIParent = nil; Fire("PLAYER_ENTERING_WORLD", false, true); RunTimers(3)')
    assert any("error while opening" in line for line in chat_lines(lua))


# ---------------------------------------------------------------- the title
def test_the_title_shows_the_name_and_the_version_the_game_tells():
    lua = window_start()
    lua.execute("NS.Live.OpenWindow()")
    assert lua.eval("NS.Live.window.title.text") == "StatTracker v9.9.9"


def test_the_title_shows_the_version_of_the_toc():
    version = re.search(r"(?m)^## Version:\s*(\S+)", (ADDON_DIR / "StatTracker.toc").read_text(encoding="utf-8")).group(1)
    lua = window_start(before=f"TOC_VERSION = '{version}'")
    lua.execute("NS.Live.OpenWindow()")
    assert lua.eval("NS.Live.window.title.text") == f"StatTracker v{version}"


@pytest.mark.parametrize("before", ["C_AddOns = nil", "TOC_VERSION = nil", "TOC_VERSION = ''", "TOC_VERSION = 5",
                                    "TOC_VERSION = '1.0 |cffff0000x'", "C_AddOns.GetAddOnMetadata = function() error('no') end"])
def test_without_a_usable_version_the_title_is_the_name_alone(before):
    lua = window_start(before=before)
    lua.execute("NS.Live.OpenWindow()")
    assert lua.eval("NS.Live.window.title.text") == "StatTracker"


def test_a_client_with_only_the_old_metadata_function_still_shows_the_version():
    lua = window_start(before="C_AddOns = nil; GetAddOnMetadata = function(name, field) return '1.2.3' end")
    lua.execute("NS.Live.OpenWindow()")
    assert lua.eval("NS.Live.window.title.text") == "StatTracker v1.2.3"


# ---------------------------------------------------------------- the page in Options -> Addons (StatTrackerOptions.lua)
def options_texts(lua):
    rows = lua.eval("NS.Live.optionsPanel.rows")
    return [rows[i].text for i in range(1, len(rows) + 1)]


def test_the_page_is_registered_in_the_addon_options_with_title_explanation_and_link():
    lua = window_start()
    assert lua.eval("#REGISTERED") == 1 and lua.eval("REGISTERED[1].name") == "StatTracker"
    assert lua.eval("REGISTERED[1].panel == NS.Live.optionsPanel")
    assert lua.eval("NS.Live.optionsPanel.title.text") == "StatTracker v9.9.9"
    text = "\n".join(options_texts(lua))
    assert "/statlive (" in text and "/statlive text" in text and "/statlive watch" in text and "macro" in text
    assert lua.eval("NS.Live.optionsPanel.link:GetText()") == "https://wewoc.github.io/WoW-StatTracker/"


def test_the_explanation_is_in_german_for_a_german_client():
    lua = window_start("deDE")
    text = "\n".join(options_texts(lua))
    assert "Fenster ein-/ausblenden: /statlive" in text and "Makro" in text and "Ecke unten rechts" in text
    assert "Projektseite" in lua.eval("NS.Live.optionsPanel.linkLabel.text")


def app_texts(lua):
    rows = lua.eval("NS.Live.optionsPanel.appRows")
    return [rows[i].text for i in range(1, len(rows) + 1)]


def test_the_page_tells_what_the_app_is_and_what_it_is_good_for_below_the_link():
    lua = window_start()
    texts = app_texts(lua)
    assert len(texts) == 3 and texts[0] == "The StatTracker app:"
    assert "reads this addon's saved data" in texts[1] and "history charts" in texts[1]
    assert "Benefit" in texts[2] and "works without the app" in texts[2]
    assert "Windows" not in "".join(texts)                           # not mentioned: every WoW addon user has it
    assert lua.eval("NS.Live.optionsPanel.appRows[1].points[1][2] == NS.Live.optionsPanel.link")      # hangs below the link field


def test_the_app_explanation_is_in_german_for_a_german_client_and_all_texts_are_ascii():
    lua = window_start("deDE")
    texts = app_texts(lua)
    assert texts[0] == "Die StatTracker-App:"
    assert "Nutzen" in texts[2] and "ohne die App" in texts[2]
    assert all(text.isascii() for text in texts + options_texts(lua))
    assert OPTIONS.read_text(encoding="utf-8").isascii()


def test_the_link_on_the_page_is_the_landing_page_of_the_app():
    from core import app_info
    lua = window_start()
    assert lua.eval("NS.Live.optionsPanel.link:GetText()") == app_info.SITE_URL
    assert app_info.SITE_URL in OPTIONS.read_text(encoding="utf-8")


def test_the_link_field_is_for_copying_only_what_is_typed_into_it_is_put_back():
    lua = window_start()
    lua.execute("local f = NS.Live.optionsPanel.link; f.text = 'https://evil.example/'; f.scripts.OnTextChanged(f, true)")
    assert lua.eval("NS.Live.optionsPanel.link:GetText()") == "https://wewoc.github.io/WoW-StatTracker/"
    lua.execute("local f = NS.Live.optionsPanel.link; f.text = 'x'; f.scripts.OnTextChanged(f, false)")     # not typed by the player: left alone
    assert lua.eval("NS.Live.optionsPanel.link:GetText()") == "x"


def test_clicking_into_the_link_field_marks_the_whole_link():
    lua = window_start()
    lua.execute("local f = NS.Live.optionsPanel.link; f.scripts.OnEditFocusGained(f)")
    assert lua.eval("NS.Live.optionsPanel.link.highlights") == 1


@pytest.mark.parametrize("before", ["Settings = nil", "Settings.RegisterCanvasLayoutCategory = nil", "Settings.RegisterAddOnCategory = nil"])
def test_a_client_without_the_settings_api_gets_no_page_and_no_message(before):
    lua = window_start(before=before)
    assert lua.eval("NS.Live.optionsPanel") is None
    assert not any("Options page" in line for line in chat_lines(lua))
    lua.execute('SlashCmdList["STATLIVE"]("")')
    assert lua.eval("NS.Live.window:IsShown()") is True              # the window does not depend on the page


def test_a_failing_registration_is_told_once_and_the_window_still_works():
    lua = window_start(before="Settings.RegisterCanvasLayoutCategory = function() error('refused') end")
    told = [line for line in chat_lines(lua) if "Options page: error" in line and "refused" in line]
    assert len(told) == 1
    lua.execute('SlashCmdList["STATLIVE"]("")')
    assert lua.eval("NS.Live.window:IsShown()") is True


def test_the_page_reads_and_writes_no_saved_data():
    code = "\n".join(line for line in OPTIONS.read_text(encoding="utf-8").splitlines() if not line.lstrip().startswith("--"))
    assert "StatTrackerDB" not in code and "StatTrackerUI" not in code
    lua = window_start(login=False)
    before = lua.eval("Serialize(StatTrackerDB)")
    do_login(lua)
    assert lua.eval("Serialize(StatTrackerDB)") == before


def test_the_page_is_built_when_this_addon_has_loaded_not_when_another_one_has():
    lua = window_start()
    lua.execute("FRAMES = {}; REGISTERED = {}; NS = {}")
    load(lua, LIVE)("StatTracker", lua.globals().NS)
    load(lua, WINDOW)("StatTracker", lua.globals().NS)
    load(lua, OPTIONS)("StatTracker", lua.globals().NS)
    lua.execute('Fire("ADDON_LOADED", "SomethingElse")')
    assert lua.eval("#REGISTERED") == 0
    lua.execute('Fire("ADDON_LOADED", "StatTracker"); Fire("ADDON_LOADED", "StatTracker")')
    assert lua.eval("#REGISTERED") == 1                              # and once only
