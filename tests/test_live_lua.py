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
    function f:SetChecked(on) self.checked = on and true or false end
    function f:GetChecked() return self.checked or false end
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


# ---------------------------------------------------------------- the choice of rows (StatTrackerUI.settings.rows)
ROW_LABELS = [("107", {"Stat 107"}), ("1487", {"Stat 1487"}), ("60", {"Stat 60"}), ("98", {"Stat 98"}), ("328", {"Stat 328"}),
              ("gold", {"Session gold"}), ("played", {"Played time"}), ("rates", {"Rates"}), ("footer", {"Updated", "Last scan"})]


def shown_labels(lua):
    return [str(l.label) for l in window_lines(lua)]


def test_the_nine_keys_are_the_five_statistics_and_the_four_other_parts():
    lua = window_start()
    keys = [str(lua.eval("NS.Live.ROW_KEYS")[i]) for i in range(1, 10)]
    assert keys == [k for k, _ in ROW_LABELS]
    values = lua.eval("NS.Live.Values()")
    assert [str(int(e["id"])) for e in values.stats.values()] == keys[:5]      # the keys of the statistics are their ids


def test_every_row_is_shown_until_the_player_hides_it():
    lua = window_start()
    assert all(lua.eval(f'NS.Live.RowShown("{k}")') is True for k, _ in ROW_LABELS)
    assert lua.eval("type(StatTrackerUI.settings.rows)") == "nil"              # nothing is saved for the default


@pytest.mark.parametrize("key, labels", ROW_LABELS)
def test_a_hidden_row_is_gone_the_others_stay_and_the_open_window_shrinks_and_grows_back(key, labels):
    lua = window_start()
    lua.execute("NS.Live.OpenWindow()")
    before = shown_labels(lua)
    height = lua.eval("NS.Live.window.height")
    assert labels <= set(before)
    assert lua.eval(f'NS.Live.SetRowShown("{key}", false)') is True
    after = [label for label in before if label not in labels]
    assert shown_labels(lua) == after
    assert [left for left, _ in row_texts(lua)] == after                        # the drawn window changed at once, not at the next reading
    assert lua.eval("NS.Live.window.height") == height - 16 * len(labels)
    assert lua.globals().StatTrackerUI.settings.rows[key] is False and lua.eval(f'NS.Live.RowShown("{key}")') is False
    assert lua.eval(f'NS.Live.SetRowShown("{key}", true)') is True
    assert shown_labels(lua) == before and [left for left, _ in row_texts(lua)] == before
    assert lua.eval("NS.Live.window.height") == height and lua.globals().StatTrackerUI.settings.rows[key] is True


def test_the_rates_are_still_calculated_when_their_sources_are_hidden_and_hiding_them_removes_both_rows():
    lua = window_start(login=False)
    set_stats(lua, {107: "100"})
    lua.globals().MONEY = 5000
    do_login(lua)
    lua.execute("RunTimers(60)")
    lua.execute("NS.Live.OpenWindow()")
    set_stats(lua, {107: "110"})
    lua.globals().MONEY = 5100
    lua.execute('NS.Live.SetRowShown("107", false); NS.Live.SetRowShown("gold", false); RunTimers(65)')
    labels = shown_labels(lua)
    assert "Stat 107" not in labels and "Session gold" not in labels
    assert {"Gold per hour", "Stat 107 per hour"} <= set(labels)              # the rows are only not drawn, the values are still read
    lua.execute('NS.Live.SetRowShown("rates", false)')
    assert not {"Gold per hour", "Stat 107 per hour", "Rates"} & set(shown_labels(lua))


def test_with_every_row_hidden_only_the_head_stays_and_so_does_the_note_of_a_client_without_statistics():
    lua = window_start()
    lua.execute('for _, k in ipairs(NS.Live.ROW_KEYS) do NS.Live.SetRowShown(k, false) end')
    assert shown_labels(lua) == ["Alice-Realm"]
    lua = window_start(before="GetStatistic = nil")
    lua.execute('for _, k in ipairs(NS.Live.ROW_KEYS) do NS.Live.SetRowShown(k, false) end')
    assert shown_labels(lua) == ["Alice-Realm", "This client provides no statistics."]


def test_the_choice_of_rows_comes_back_after_a_reload_and_a_hidden_row_is_not_drawn_at_the_first_reading():
    lua = window_start()
    lua.execute('NS.Live.OpenWindow(); NS.Live.SetRowShown("60", false); NS.Live.SetRowShown("footer", false)')
    reload_ui(lua, window=True)
    assert lua.eval("NS.Live.window:IsShown()") is True
    assert [left for left, _ in row_texts(lua)] == [l for l in shown_labels(lua)]
    assert "Stat 60" not in shown_labels(lua) and "Last scan" not in shown_labels(lua) and "Stat 98" in shown_labels(lua)


def test_a_choice_that_was_saved_in_the_file_hides_the_row_from_the_start():
    lua = window_start(login=False, before='StatTrackerUI = { version = 1, settings = { rows = { ["107"] = false } } }')
    do_login(lua)
    lua.execute("NS.Live.OpenWindow()")
    assert "Stat 107" not in shown_labels(lua) and "Stat 1487" in shown_labels(lua)


@pytest.mark.parametrize("saved", ['"garbage"', '{ ["107"] = "no" }', '{ ["107"] = 0 }', '{ ["107"] = true }', '{ [107] = false }', '{ nope = false }'])
def test_a_saved_choice_that_is_not_an_explicit_false_for_a_known_key_shows_everything(saved):
    lua = window_start(login=False, before=f'StatTrackerUI = {{ version = 1, settings = {{ rows = {saved} }} }}')
    do_login(lua)
    assert "Stat 107" in shown_labels(lua) and len(shown_labels(lua)) == 11


def test_a_damaged_choice_is_replaced_when_a_row_is_hidden():
    lua = window_start(login=False, before='StatTrackerUI = { version = 1, settings = { rows = "garbage" } }')
    do_login(lua)
    assert lua.eval('NS.Live.SetRowShown("98", false)') is True
    assert lua.eval("type(StatTrackerUI.settings.rows)") == "table" and "Stat 98" not in shown_labels(lua)
    assert lua.eval("NonFinite(StatTrackerUI)") is False


def test_an_unknown_key_changes_nothing_and_is_not_saved():
    lua = window_start()
    before = lua.eval("Serialize(StatTrackerUI)")
    assert lua.eval('NS.Live.SetRowShown("nope", false)') is False and lua.eval('NS.Live.SetRowShown(107, false)') is False
    assert lua.eval("Serialize(StatTrackerUI)") == before and len(shown_labels(lua)) == 11


def test_a_file_of_a_newer_addon_is_neither_written_nor_obeyed_for_the_rows():
    lua = start(login=False, window=True, before='StatTrackerUI = { version = 99, settings = { rows = { ["107"] = false } } }')
    before = lua.eval("Serialize(StatTrackerUI)")
    do_login(lua)
    assert lua.eval('NS.Live.RowShown("107")') is True
    assert lua.eval('NS.Live.SetRowShown("60", false)') is False
    assert lua.eval("Serialize(StatTrackerUI)") == before and "Stat 107" in shown_labels(lua)


def test_the_chat_text_ignores_the_choice_of_rows():
    lua = window_start()
    lua.execute('NS.Live.SetRowShown("107", false); NS.Live.SetRowShown("gold", false); NS.Live.SetRowShown("played", false)')
    lua.execute('SlashCmdList["STATLIVE"]("text")')
    text = "\n".join(chat_lines(lua))
    assert "Stat 107" in text and "Played time" in text


# ---------------------------------------------------------------- the colours (green and red against the average of the character)
# The scan of the character: 100 hours played; averages per hour: 1000 (107), 5 (1487), 0.1 (60), 2 (98) and 10000 copper (328).
def tint_db(played="360000", stats=None, epoch=880):
    stats = {107: "100000", 1487: "500", 60: "10", 98: "200", 328: coin(gold=100), **(stats or {})}
    body = ", ".join(f"[{k}] = [=[{v}]=]" for k, v in stats.items())
    played_field = f"playedTotal = {played}, " if played is not None else ""
    return f'StatTrackerDB = {{ version = 5, chars = {{ ["Alice-Realm"] = {{ scannedEpoch = {epoch}, {played_field}stats = {{ {body} }} }} }} }}'


TINT_START = {107: "5000", 1487: "1000", 60: "3", 98: "50", 328: coin(gold=5)}
# what ten hours of play at exactly the average add (the default of `now`: every statistic is neutral unless a test moves it)
TINT_NEUTRAL = {107: "15000", 1487: "1050", 60: "4", 98: "70", 328: coin(gold=15)}


def tint_start(now, seconds=36000, colored=True, locale="enUS", db=None):
    """A character that logged in with TINT_START, played `seconds` (ten hours) and now has the values `now` (the rest neutral)."""
    lua = window_start(locale, scan_db=False, before=tint_db() if db is None else db, login=False)
    set_stats(lua, TINT_START)
    do_login(lua)
    lua.execute(f"RunTimers({seconds})")
    set_stats(lua, {**TINT_NEUTRAL, **now})
    if colored:
        assert lua.eval("NS.Live.SetColored(true)") is True
    return lua


def by_label(lua):
    return {str(l.label): l for l in window_lines(lua)}


def test_the_colours_are_off_by_default_and_then_nothing_changes():
    lua = tint_start({107: "16000", 60: "9"}, colored=False)
    assert lua.eval("NS.Live.IsColored()") is False and lua.eval("type(StatTrackerUI.settings.colored)") == "nil"
    for line in window_lines(lua):
        assert line.tone is None and not str(line.value).endswith((" ^", " v")) and "\n" not in str(line.tip or "")
    assert by_label(lua)["Stat 107"].value == "16000 (+11000)"


@pytest.mark.parametrize("delta, tone, mark, percent", [          # ten hours at 1000 an hour is 10000
    (11000, "GOOD", " ^", "+10"), (10999, None, "", None), (10000, None, "", None), (9001, None, "", None), (9000, "BAD", " v", "-10"),
    (0, "BAD", " v", "-100"), (20000, "GOOD", " ^", "+100"),
])
def test_a_statistic_is_green_or_red_from_ten_percent_above_or_below_the_average_and_exactly_ten_counts(delta, tone, mark, percent):
    lua = tint_start({107: str(5000 + delta)})
    line = by_label(lua)["Stat 107"]
    assert line.tone == tone and str(line.value) == f"{5000 + delta} (+{delta}){mark}"
    if tone is None:
        assert "\n" not in str(line.tip)
    else:
        word = "Above" if tone == "GOOD" else "Below"
        assert str(line.tip).endswith(f"\n{word} your average ({percent} %)")
    assert all(l.tone is None for label, l in by_label(lua).items() if label != "Stat 107")     # the others are exactly at their averages


def test_deaths_are_the_other_way_round_fewer_than_the_average_is_green():
    fewer = by_label(tint_start({60: "3"}))["Stat 60"]                          # no death in ten hours, the average is one in ten hours
    assert (fewer.tone, str(fewer.value)) == ("GOOD", "3 (+0) v")
    more = by_label(tint_start({60: "5"}))["Stat 60"]                           # two deaths: twice the average
    assert (more.tone, str(more.value)) == ("BAD", "5 (+2) ^")


def test_the_gold_statistic_is_compared_in_copper():
    up = by_label(tint_start({328: coin(gold=17)}))["Stat 328"]                 # 120000 copper in ten hours against 100000
    assert up.tone == "GOOD" and str(up.value).endswith(" ^") and str(up.tip).endswith("\nAbove your average (+20 %)")
    down = by_label(tint_start({328: coin(gold=9)}))["Stat 328"]                # 40000 copper
    assert down.tone == "BAD" and str(down.value).endswith(" v")


def test_a_session_of_ten_minutes_is_compared_and_a_shorter_one_is_not():
    now = {107: "5200"}                                                          # 200 in ten minutes = 1200 an hour
    assert by_label(tint_start(now, seconds=600))["Stat 107"].tone == "GOOD"
    assert by_label(tint_start(now, seconds=599))["Stat 107"].tone is None


NO_COLOUR = {
    "no scan": dict(db=""),
    "no played time": dict(db=tint_db(played=None)),
    "played time 0": dict(db=tint_db(played="0")),
    "negative played time": dict(db=tint_db(played="-5")),
    "played time is text": dict(db=tint_db(played='"x"')),
    "average of 0": dict(db=tint_db(stats={107: "0"})),
    "no value in the scan": dict(db=tint_db(stats={107: "--"})),
    "text in the scan": dict(db=tint_db(stats={107: "many"})),
}


@pytest.mark.parametrize("case", list(NO_COLOUR))
def test_without_an_average_there_is_no_colour_no_mark_and_no_made_up_number(case):
    lua = tint_start({107: "16000"}, **NO_COLOUR[case])
    line = by_label(lua)["Stat 107"]
    assert line.tone is None and str(line.value) == "16000 (+11000)" and "\n" not in str(line.tip)


def test_without_a_session_or_without_a_live_value_there_is_no_colour():
    lua = tint_start({107: "16000"})
    lua.execute("StatTrackerUI.session = nil")
    assert all(l.tone is None for l in window_lines(lua))                       # no start values: no change, so no comparison
    lua = tint_start({107: "16000", 98: None})                                   # 98: nothing live, the value of the scan is shown dimmed
    lines = by_label(lua)
    assert lines["Stat 98"].state == "SNAPSHOT" and lines["Stat 98"].tone is None and lines["Stat 107"].tone == "GOOD"


def test_only_the_statistic_rows_are_coloured_and_a_hidden_row_stays_hidden():
    lua = tint_start({107: "16000", 1487: "1060"})
    lines = by_label(lua)
    assert {label for label, l in lines.items() if l.tone} == {"Stat 107", "Stat 1487"}
    assert all(l.tone is None for label, l in lines.items() if not label.startswith("Stat "))     # gold, played time, rates, footer
    lua.execute('NS.Live.SetRowShown("107", false)')
    lines = by_label(lua)
    assert "Stat 107" not in lines and lines["Stat 1487"].tone == "GOOD"
    lua.execute('SlashCmdList["STATLIVE"]("text")')
    assert not any(line.rstrip().endswith((" ^", " v")) for line in chat_lines(lua))     # the chat text is not touched


def test_switching_the_colours_redraws_an_open_window_and_only_the_value_changes_colour():
    lua = tint_start({107: "16000"}, colored=False)
    lua.execute("NS.Live.OpenWindow()")
    lua.execute('''
        for _, r in ipairs(NS.Live.window.rows) do
            r.left.SetTextColor = function(self, ...) self.color = { ... } end
            r.right.SetTextColor = function(self, ...) self.color = { ... } end
        end
        function ColorOf(text, side)
            for _, r in ipairs(NS.Live.window.rows) do
                if r.left.text == text then return r[side].color[1], r[side].color[2], r[side].color[3] end
            end
        end''')
    assert lua.eval("NS.Live.SetColored(true)") is True
    assert lua.eval("ColorOf('Stat 107', 'right')") == (0.25, 0.9, 0.25) and lua.eval("ColorOf('Stat 107', 'left')") == (1, 1, 1)
    assert dict(row_texts(lua))["Stat 107"] == "16000 (+11000) ^"
    assert lua.eval("ColorOf('Stat 1487', 'right')") == (1, 1, 1)
    lua.execute("NS.Live.SetColored(false)")
    assert lua.eval("ColorOf('Stat 107', 'right')") == (1, 1, 1) and dict(row_texts(lua))["Stat 107"] == "16000 (+11000)"
    lua.execute("NS.Live.SetColored(true)")
    lua.execute("NS.Live.SetRowShown('107', false)")
    assert "Stat 107" not in dict(row_texts(lua))


def test_the_red_is_red_and_the_setting_is_saved_as_a_plain_true_and_stays_after_a_reload():
    lua = tint_start({107: "5500"})
    assert lua.globals().StatTrackerUI.settings.colored is True and lua.eval("NonFinite(StatTrackerUI)") is False
    assert by_label(lua)["Stat 107"].tone == "BAD"
    lua.execute("NS.Live.OpenWindow()")
    reload_ui(lua, window=True)
    assert lua.eval("NS.Live.IsColored()") is True and by_label(lua)["Stat 107"].tone == "BAD"
    lua.execute("NS.Live.SetColored(false)")
    assert lua.globals().StatTrackerUI.settings.colored is False


@pytest.mark.parametrize("saved", ["false", '"yes"', "1", "{}"])
def test_only_an_explicit_true_switches_the_colours_on(saved):
    lua = window_start(login=False, before=f'StatTrackerUI = {{ version = 1, settings = {{ colored = {saved} }} }}')
    do_login(lua)
    assert lua.eval("NS.Live.IsColored()") is False


def test_a_file_of_a_newer_addon_is_neither_written_nor_obeyed_for_the_colours():
    lua = start(login=False, window=True, before='StatTrackerUI = { version = 99, settings = { colored = true } }')
    before = lua.eval("Serialize(StatTrackerUI)")
    do_login(lua)
    assert lua.eval("NS.Live.IsColored()") is False and lua.eval("NS.Live.SetColored(true)") is False
    assert lua.eval("Serialize(StatTrackerUI)") == before


def test_the_tooltip_lines_in_german():
    up = by_label(tint_start({107: "17000"}, locale="deDE"))["Stat 107"]
    assert str(up.tip).endswith("\nUeber deinem Schnitt (+20 %)")
    down = by_label(tint_start({107: "11000"}, locale="deDE"))["Stat 107"]
    assert str(down.tip).endswith("\nUnter deinem Schnitt (-40 %)")


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


# ---------------------------------------------------------------- locking the position (/statlive lock)
def try_drag(lua):
    """A drag of the window and of one of its rows, as the game fires it; returns how many StartMoving calls came through."""
    lua.execute("MOVES.start = 0")
    lua.execute("local w = NS.Live.window; w.scripts.OnDragStart(w); w.scripts.OnDragStop(w)")
    lua.execute("local r = NS.Live.window.rows[2]; r.scripts.OnDragStart(r); r.scripts.OnDragStop(r)")
    return lua.globals().MOVES.start


def test_a_locked_window_does_not_move_when_it_or_a_row_is_dragged():
    lua = window_start()
    lua.execute("NS.Live.OpenWindow()")
    assert try_drag(lua) == 2                                         # unlocked: both start a move, as before
    lua.execute('SlashCmdList["STATLIVE"]("lock")')
    assert lua.globals().StatTrackerUI.settings.window.locked is True and lua.eval("NS.Live.IsLocked()") is True
    assert any("Window locked" in line for line in chat_lines(lua))
    assert try_drag(lua) == 0
    lua.execute('SlashCmdList["STATLIVE"]("UNLOCK ")')                # case and spaces do not matter
    assert lua.globals().StatTrackerUI.settings.window.locked is False and lua.eval("NS.Live.IsLocked()") is False
    assert any("Window unlocked" in line for line in chat_lines(lua))
    assert try_drag(lua) == 2


def test_the_lock_is_saved_with_the_position_and_survives_a_reload():
    lua = window_start()
    lua.execute("NS.Live.OpenWindow()")
    lua.execute('SlashCmdList["STATLIVE"]("lock")')
    lua.execute('local w = NS.Live.window; w.points = { { "RIGHT", UIParent, "RIGHT", -10, -20 } }; w.scripts.OnDragStop(w)')
    saved = lua.globals().StatTrackerUI.settings.window
    assert (saved.locked, saved.point, saved.x) == (True, "RIGHT", -10)       # saving the position keeps the lock
    reload_ui(lua, window=True)
    assert lua.eval("NS.Live.window:IsShown()") is True and lua.eval("NS.Live.IsLocked()") is True
    assert try_drag(lua) == 0


def test_the_window_can_be_locked_before_it_was_ever_opened():
    lua = window_start()
    assert lua.eval("NS.Live.window") is None
    lua.execute('SlashCmdList["STATLIVE"]("lock")')
    assert lua.eval("NS.Live.window") is None                         # the command builds nothing
    lua.execute("NS.Live.OpenWindow()")
    assert try_drag(lua) == 0
    saved = lua.globals().StatTrackerUI.settings.window
    assert saved.locked is True and saved.shown is True               # opening the window kept the lock


def test_the_corner_still_changes_the_width_of_a_locked_window():
    lua = window_start()
    lua.execute("NS.Live.OpenWindow()")
    lua.execute('SlashCmdList["STATLIVE"]("lock")')
    drag_corner(lua, 1000, 1100)
    assert lua.eval("NS.Live.window.width") == 440
    saved = lua.globals().StatTrackerUI.settings.window
    assert (saved.width, saved.locked) == (440, True)


@pytest.mark.parametrize("saved", ["false", '"yes"', "1", "{}"])
def test_only_an_explicit_true_counts_as_locked(saved):
    lua = window_start(login=False, before=f'StatTrackerUI = {{ version = 1, settings = {{ window = {{ locked = {saved} }} }} }}')
    do_login(lua)
    lua.execute("NS.Live.OpenWindow()")
    assert lua.eval("NS.Live.IsLocked()") is False and try_drag(lua) == 2


def test_a_file_of_a_newer_addon_is_not_written_by_the_lock_command_and_does_not_lock():
    lua = start(login=False, window=True, before='StatTrackerUI = { version = 99, settings = { window = { locked = true } } }')
    before = lua.eval("Serialize(StatTrackerUI)")
    do_login(lua)
    assert lua.eval("NS.Live.IsLocked()") is False                    # read nothing from a file of a newer version
    lua.execute('SlashCmdList["STATLIVE"]("lock")')
    assert lua.eval("Serialize(StatTrackerUI)") == before
    assert any("Settings not available" in line for line in chat_lines(lua))


def test_a_damaged_window_entry_is_replaced_by_the_lock_command():
    lua = window_start(login=False, before='StatTrackerUI = { version = 1, settings = { window = "garbage" } }')
    do_login(lua)
    lua.execute('SlashCmdList["STATLIVE"]("lock")')
    assert lua.eval("type(StatTrackerUI.settings.window)") == "table" and lua.eval("NS.Live.IsLocked()") is True
    assert lua.eval("NonFinite(StatTrackerUI)") is False


def test_the_lock_commands_in_german():
    lua = window_start("deDE")
    lua.execute('SlashCmdList["STATLIVE"]("lock"); SlashCmdList["STATLIVE"]("unlock")')
    text = "\n".join(chat_lines(lua))
    assert "Fenster gesperrt" in text and "Fenster freigegeben" in text


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


# ---------------------------------------------------------------- the settings of the window on that page (check boxes)
# boxes[1] locks, boxes[2] colours, boxes[3..11] are the rows in the order of NS.Live.ROW_KEYS (107, 1487, 60, 98, 328, gold, played, rates, footer)
def show_page(lua):
    lua.execute("local p = NS.Live.optionsPanel; p.scripts.OnShow(p)")


def box_checked(lua, i):
    return lua.eval(f"NS.Live.optionsPanel.boxes[{i}]:GetChecked()")


def click_box(lua, i):
    """What a click does: the game turns the box over, then calls OnClick."""
    lua.execute(f"local b = NS.Live.optionsPanel.boxes[{i}]; b:SetChecked(not b:GetChecked()); b.scripts.OnClick(b)")


def captions(lua):
    return [str(lua.eval(f"NS.Live.optionsPanel.boxes[{i}].caption.text")) for i in range(1, 12)]


def test_the_page_has_eleven_check_boxes_two_for_the_window_and_nine_for_the_rows():
    lua = window_start()
    assert lua.eval("#NS.Live.optionsPanel.boxes") == 11
    assert captions(lua)[:2] == ["Lock the window (position)", "Colour the numbers (green/red)"]
    assert captions(lua)[7:] == ["Session gold", "Played time", "Rates per hour", "Footer (updated, last scan)"]
    assert captions(lua)[2:7] == [f"Statistic {k}" for k in (107, 1487, 60, 98, 328)]         # until the page is shown and the game names them
    assert all(lua.eval(f"NS.Live.optionsPanel.boxes[{i}].kind") == "CheckButton" for i in range(1, 12))


def test_the_boxes_sit_in_two_columns_and_the_link_hangs_below_the_last_one():
    lua = window_start()
    points = [lua.eval(f"NS.Live.optionsPanel.boxes[{i}].points[1]") for i in range(1, 12)]
    assert [(p[4], p[5]) for p in points[:2]] == [(0, -4), (290, -4)]                          # the two window boxes side by side
    assert [(p[4], p[5]) for p in points[2:7]] == [(0, -4 - 24 * row) for row in range(5)]     # the five statistics, left column
    assert [(p[4], p[5]) for p in points[7:]] == [(290, -4 - 24 * row) for row in range(4)]    # the other four, right column
    assert lua.eval("NS.Live.optionsPanel.linkLabel.points[1][2] == NS.Live.optionsPanel.boxes[7]")
    assert lua.eval("NS.Live.optionsPanel.appRows[1].points[1][2] == NS.Live.optionsPanel.link")      # still below the link field


def test_the_boxes_show_what_is_saved_when_the_page_is_shown_and_the_statistics_get_their_names():
    lua = window_start()
    lua.execute('NS.Live.SetLocked(true); NS.Live.SetColored(true); NS.Live.SetRowShown("60", false); NS.Live.SetRowShown("footer", false)')
    show_page(lua)
    assert [box_checked(lua, i) for i in range(1, 12)] == [True, True, True, True, False, True, True, True, True, True, False]
    assert captions(lua)[2:7] == ["Stat 107", "Stat 1487", "Stat 60", "Stat 98", "Stat 328"]


def test_the_boxes_show_what_is_saved_right_after_loading_even_before_the_page_is_shown():
    lua = window_start(login=False, before='StatTrackerUI = { version = 1, settings = { colored = true, window = { locked = true }, rows = { ["98"] = false } } }')
    do_login(lua)
    assert [box_checked(lua, i) for i in range(1, 12)] == [True, True, True, True, True, False, True, True, True, True, True]


def test_a_command_in_the_chat_shows_in_the_boxes_the_next_time_the_page_is_shown():
    lua = window_start()
    show_page(lua)
    assert box_checked(lua, 1) is False
    lua.execute('SlashCmdList["STATLIVE"]("lock")')
    show_page(lua)
    assert box_checked(lua, 1) is True
    lua.execute('SlashCmdList["STATLIVE"]("unlock")')
    show_page(lua)
    assert box_checked(lua, 1) is False


def test_clicking_the_lock_locks_the_window_and_clicking_again_releases_it():
    lua = window_start()
    lua.execute("NS.Live.OpenWindow()")
    click_box(lua, 1)
    assert lua.eval("NS.Live.IsLocked()") is True and lua.globals().StatTrackerUI.settings.window.locked is True
    assert try_drag(lua) == 0
    click_box(lua, 1)
    assert lua.eval("NS.Live.IsLocked()") is False and try_drag(lua) == 2


def test_clicking_a_row_hides_it_in_the_open_window_and_clicking_again_brings_it_back():
    lua = window_start()
    lua.execute("NS.Live.OpenWindow()")
    show_page(lua)                                                                             # the boxes are filled when the page is shown
    click_box(lua, 3)                                                                          # the first statistic, 107
    assert "Stat 107" not in dict(row_texts(lua)) and lua.globals().StatTrackerUI.settings.rows["107"] is False
    click_box(lua, 10)                                                                         # rates
    assert "Rates" not in dict(row_texts(lua))
    click_box(lua, 3)
    assert "Stat 107" in dict(row_texts(lua)) and lua.globals().StatTrackerUI.settings.rows["107"] is True


def test_clicking_the_colour_box_switches_the_colours_on_and_off():
    lua = tint_start({107: "16000"}, colored=False)
    assert by_label(lua)["Stat 107"].tone is None
    click_box(lua, 2)
    assert by_label(lua)["Stat 107"].tone == "GOOD" and lua.globals().StatTrackerUI.settings.colored is True
    click_box(lua, 2)
    assert by_label(lua)["Stat 107"].tone is None and lua.globals().StatTrackerUI.settings.colored is False


def test_in_a_file_of_a_newer_addon_the_box_goes_back_the_chat_says_so_and_nothing_is_written():
    lua = start(login=False, window=True, before='StatTrackerUI = { version = 99, settings = {} }')
    before = lua.eval("Serialize(StatTrackerUI)")
    do_login(lua)
    show_page(lua)
    for i in (1, 2, 3, 9):
        click_box(lua, i)
        assert box_checked(lua, i) is (i == 3 or i == 9)                                        # back to what it was: the rows on, lock and colours off
    assert sum("Settings not available" in line for line in chat_lines(lua)) == 4
    assert lua.eval("Serialize(StatTrackerUI)") == before


def test_a_box_that_cannot_save_goes_back_and_the_problem_is_told_once():
    lua = window_start()
    show_page(lua)
    lua.execute("NS.Live.SetRowShown = function() error('boom') end")
    click_box(lua, 3)
    click_box(lua, 4)
    assert box_checked(lua, 3) is True and box_checked(lua, 4) is True
    assert sum("Options page: error" in line and "boom" in line for line in chat_lines(lua)) == 1


def test_the_two_window_boxes_explain_themselves_in_a_tooltip_and_the_row_boxes_do_not():
    lua = window_start()
    lua.execute("local b = NS.Live.optionsPanel.boxes[1]; b.scripts.OnEnter(b)")
    assert lua.globals().TIP[1] == "Lock the window (position)" and "by mistake" in lua.globals().TIP[2] and lua.globals().TIP.shown is True
    lua.execute("local b = NS.Live.optionsPanel.boxes[1]; b.scripts.OnLeave(b)")
    assert lua.globals().TIP.shown is False
    lua.execute("local b = NS.Live.optionsPanel.boxes[2]; b.scripts.OnEnter(b)")
    tip = str(lua.globals().TIP[2])
    assert "10 minutes" in tip and "10 %" in tip and "deaths" in tip and "^" in tip
    assert lua.eval("NS.Live.optionsPanel.boxes[3].scripts.OnEnter") is None


def test_the_boxes_and_the_new_line_speak_german_for_a_german_client():
    lua = window_start("deDE")
    assert captions(lua)[:2] == ["Fenster sperren (Position)", "Zahlen einfaerben (gruen/rot)"]
    assert captions(lua)[7:] == ["Session-Gold", "Spielzeit", "Raten pro Stunde", "Fusszeile (Aktualisiert, Letzter Scan)"]
    assert "Fenster sperren: /statlive lock, freigeben: /statlive unlock." in options_texts(lua)
    lua.execute("local b = NS.Live.optionsPanel.boxes[2]; b.scripts.OnEnter(b)")
    assert "Gruen oder rot" in str(lua.globals().TIP[2]) and all(c.isascii() for c in captions(lua) + [str(lua.globals().TIP[2])])


def test_the_english_page_names_the_lock_commands():
    assert "Lock the window: /statlive lock, release it: /statlive unlock." in options_texts(window_start())


def test_without_the_window_part_the_page_has_no_boxes_and_the_rest_stays():
    lua = window_start()
    lua.execute("FRAMES = {}; REGISTERED = {}; NS = {}")
    load(lua, LIVE)("StatTracker", lua.globals().NS)
    load(lua, OPTIONS)("StatTracker", lua.globals().NS)                                        # the window file is not loaded
    lua.execute('Fire("ADDON_LOADED", "StatTracker")')
    assert lua.eval("NS.Live.optionsPanel ~= nil") is True and lua.eval("NS.Live.optionsPanel.boxes") is None
    assert lua.eval("NS.Live.optionsPanel.link:GetText()") == "https://wewoc.github.io/WoW-StatTracker/"
    assert lua.eval("NS.Live.optionsPanel.linkLabel.points[1][2] == NS.Live.optionsPanel.rows[#NS.Live.optionsPanel.rows]")
    show_page(lua)                                                                             # showing it works without the boxes, too
    assert not any("Options page" in line for line in chat_lines(lua))


def test_a_client_that_cannot_build_a_check_button_loses_only_the_boxes():
    lua = window_start(before='local plain = CreateFrame; function CreateFrame(kind, ...) if kind == "CheckButton" then error("no check buttons") end '
                              'return plain(kind, ...) end')
    assert sum("Options page: error" in line and "no check buttons" in line for line in chat_lines(lua)) == 1
    assert lua.eval("NS.Live.optionsPanel.link:GetText()") == "https://wewoc.github.io/WoW-StatTracker/" and len(app_texts(lua)) == 3
    lua.execute('SlashCmdList["STATLIVE"]("")')
    assert lua.eval("NS.Live.window:IsShown()") is True


def test_the_page_still_touches_no_saved_variable_itself():
    code = "\n".join(line for line in OPTIONS.read_text(encoding="utf-8").splitlines() if not line.lstrip().startswith("--"))
    assert "StatTrackerDB" not in code and "StatTrackerUI" not in code and "settings.rows" not in code
    lua = window_start(login=False)
    before = lua.eval("Serialize(StatTrackerDB)")
    do_login(lua)
    show_page(lua)
    click_box(lua, 1)
    assert lua.eval("Serialize(StatTrackerDB)") == before and lua.eval("NonFinite(StatTrackerUI)") is False
