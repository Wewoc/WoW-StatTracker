-- SPDX-License-Identifier: GPL-3.0-or-later
-- Copyright (C) 2026 Wewoc (github.com/wewoc)
-- StatTrackerLive.lua (Retail and WoW Forever)
-- The live part of the addon: a few statistics of the logged-in character, read straight from the game, with the change
-- since the start of the session. It keeps its own SavedVariable StatTrackerUI and never writes StatTrackerDB (the data
-- of the scan stays as it is). StatTracker.lua is the scan and is not touched by this file.
--   /statlive        shows or hides the window (StatTrackerWindow.lua); without one it writes the text to the chat
--   /statlive text   writes the values in the chat (statistics, session gold, played time, rates per hour)
--   /statlive watch  switches a mode on or off that reads every few seconds and writes every change into the chat
--
-- StatTrackerUI (account-wide, in the same file as StatTrackerDB):
--   version  = 1
--   settings = { window = { point, rel, x, y, shown } }   the window (position, open or closed); more later (copy text, ...)
--   session  = { key = "Name-Realm", start = time(),  the current session of the logged-in character:
--                money = copper at the start,         a new login starts a new session, /reload goes on with it
--                stats = { [statID] = number },       the values at the start (filled in the first 90 seconds, see FillBaseline)
--                played = { total, epoch } }          the last answer about the played time: seconds, and time() of the answer
--
-- Rules (measured on Retail and on WoW Forever):
--   * statistics are read by id only and never enumerated (walking the categories costs seconds on Retail);
--   * a value that is missing or "--" is UNKNOWN, never 0;
--   * only finite numbers are saved (the program reads this file and stops on anything else, e.g. inf or nan);
--   * every API is checked before it is used, a missing one only switches off its part.

local ADDON, ns = ...
if type(ns) ~= "table" then ns = {} end
local Live = {}
ns.Live = Live

local PREFIX = "|cff00ff00[StatTracker]|r "
local UI_VERSION = 1
local BASELINE_WINDOW = 90                 -- seconds after the start of a session in which missing start values may still be filled
local BASELINE_READS = { 15, 45, 85 }      -- the statistics of a new login arrive a few seconds late: read again inside the window
local TICK_SECONDS = 5                     -- while the data is shown: one read every 5 seconds ...
local EVENT_DELAY = 2                      -- ... and one 2 seconds after a kill, a turned-in quest or a change of money
local RATE_MIN_AGE = 120                   -- rates per hour are shown after two minutes of session
local PLAYED_DELAY = 8                     -- seconds after a login until the played time is asked for (once, if nothing answered before)

-- The statistics shown (the ids exist on Retail and on WoW Forever): creatures killed, killing blows, deaths, quests
-- completed, gold received in total. The last one comes as a coin text, the others as plain numbers.
local STATS = {
    { id = 107 }, { id = 1487 }, { id = 60 }, { id = 98 }, { id = 328, coin = true },
}

local IS_DE = (type(GetLocale) == "function" and GetLocale() == "deDE")
local function Tr(de, en) if IS_DE then return de end return en end
local function Say(msg) print(PREFIX .. msg) end
local function Have(fn) return type(fn) == "function" end
local function Finite(x) return type(x) == "number" and x == x and x ~= math.huge and x ~= -math.huge end
local function Now() return time() end

local function After(delay, fn)             -- true when the timer was set
    if type(C_Timer) == "table" and Have(C_Timer.After) then
        C_Timer.After(delay, fn)
        return true
    end
    return false
end

-- ---------------------------------------------------------------------------------------------------- reading

-- "12|TInterface\MoneyFrame\UI-GoldIcon:0:0:2:0|t 7|TInterface\MoneyFrame\UI-SilverIcon:0:0:2:0|t" -> copper; nil without coin markup
local COIN_UNIT = { Gold = 10000, Silver = 100, Copper = 1 }
function Live.ParseCoins(text)
    if type(text) ~= "string" then return nil end
    local total, found = 0, false
    for amount, unit in string.gmatch(text, "([%d%.,]+)|TInterface\\MoneyFrame\\UI%-(%a+)Icon") do
        local n = tonumber((string.gsub(amount, "[%.,]", "")))        -- the separators of the client language
        local mult = COIN_UNIT[unit]
        if n and mult then
            total = total + n * mult
            found = true
        end
    end
    if found and Finite(total) then return total end
    return nil
end

-- "11560", "11.560", "1,234" -> number; nil for "--", text, nil, inf and nan
function Live.ParseNumber(text)
    if type(text) == "number" then
        if Finite(text) then return text end
        return nil
    end
    if type(text) ~= "string" then return nil end
    local digits = string.gsub(text, "[%.,%s]", "")
    if digits == "" or string.find(digits, "[^%d%-]") then return nil end
    local n = tonumber(digits)
    if Finite(n) then return n end
    return nil
end

local function ReadStat(id)                  -- the text of the statistic, or nil (API missing, error, no value)
    if not Have(GetStatistic) then return nil end
    local ok, value = pcall(GetStatistic, id)
    if not ok or value == nil then return nil end
    value = tostring(value)
    if value == "" or value == "--" then return nil end
    return value
end

local function Reading(def)                  -- text, number (the number is nil when the text is no number or coin amount)
    local text = ReadStat(def.id)
    if text == nil then return nil, nil end
    if def.coin then return text, Live.ParseCoins(text) end
    return text, Live.ParseNumber(text)
end

local names = {}
local function StatName(id)                  -- the name the game gives the statistic (always in the language of the client)
    if names[id] then return names[id] end
    local name
    if Have(GetAchievementInfo) then
        local ok, _, n = pcall(GetAchievementInfo, id)
        if ok and type(n) == "string" and n ~= "" then name = n end
    end
    names[id] = name or ("#" .. id)
    return names[id]
end

local function ReadMoney()
    if not Have(GetMoney) then return nil end
    local ok, value = pcall(GetMoney)
    if ok and Finite(value) then return value end
    return nil
end

local function CharKey()                     -- the same key the scan uses
    if not (Have(UnitName) and Have(GetRealmName)) then return nil end
    local name, realm = UnitName("player"), GetRealmName()
    if not name or not realm then return nil end
    return name .. "-" .. realm
end

-- The second value of UnitName("player") is the realm of a player from another realm and nil for your own; on WoW Forever it carries the
-- surname that is shown with the character ("Name Surname"). Same rule as the scan: nothing but a non-empty text that is not the realm.
local function Surname(second)
    if type(second) ~= "string" or second == "" then return nil end
    if Have(GetRealmName) and second == GetRealmName() then return nil end
    if Have(GetNormalizedRealmName) and second == GetNormalizedRealmName() then return nil end
    return second
end

-- The name shown for the logged-in character. With a surname (WoW Forever) like the pages of the program: "Name Surname / Realm";
-- without one (Retail) the key as it is. The key itself ("Name-Realm", what the scan stores) never changes.
local function DisplayName(key)
    if not Have(UnitName) then return key end
    local name, second = UnitName("player")
    local surname = Surname(second)
    if not name or not surname then return key end
    local realm = Have(GetRealmName) and GetRealmName() or nil
    if type(realm) == "string" and realm ~= "" then return name .. " " .. surname .. " / " .. realm end
    return name .. " " .. surname
end

-- ---------------------------------------------------------------------------------------------------- saved data

local function InitSaved()
    if type(StatTrackerUI) ~= "table" then StatTrackerUI = {} end
    local ui = StatTrackerUI
    if type(ui.version) == "number" and ui.version > UI_VERSION then
        Live.frozen = true                   -- written by a newer addon: read nothing into it, change nothing
        return
    end
    ui.version = UI_VERSION
    if type(ui.settings) ~= "table" then ui.settings = {} end
end

-- Missing start values are filled while the session is young: the statistics of a new login are not all there at the first
-- instant. After the window nothing is filled any more (a value that shows up later would be a wrong start value).
function Live.FillBaseline()
    local s = type(StatTrackerUI) == "table" and StatTrackerUI.session
    if Live.frozen or type(s) ~= "table" or type(s.stats) ~= "table" then return end
    if not Finite(s.start) or Now() - s.start > BASELINE_WINDOW then return end
    for _, def in ipairs(STATS) do
        if s.stats[def.id] == nil then
            local _, number = Reading(def)
            if number ~= nil then s.stats[def.id] = number end
        end
    end
    if s.money == nil then
        local money = ReadMoney()
        if money ~= nil then s.money = money end
    end
end

local function NewSession(key)
    StatTrackerUI.session = { key = key, start = Now(), stats = {} }
    Live.FillBaseline()
end

-- Played time: the game answers RequestTimePlayed with TIME_PLAYED_MSG (seconds in total, seconds at this level). Any answer, also the
-- scan's or a manual /played, is the new base; in between the time is the base plus the seconds since the answer (an estimate, measured
-- accurate to about a second over half an hour). Asked for once after a login, and never while a base exists.
local function PlayedBase()                  -- the saved base (or nil), and the session it belongs to (or nil)
    local s = type(StatTrackerUI) == "table" and not Live.frozen and StatTrackerUI.session
    if type(s) ~= "table" then return nil end
    local p = s.played
    if type(p) == "table" and Finite(p.total) and Finite(p.epoch) then return p, s end
    return nil, s
end

local function OnPlayed(total)
    local _, s = PlayedBase()
    if not s or not Finite(total) or total < 0 then return end
    s.played = { total = total, epoch = Now() }
end

local function AskForPlayedTime()
    local base, s = PlayedBase()
    if base or not s or not Have(RequestTimePlayed) then return end
    pcall(RequestTimePlayed)
end

local firstEnter = true
local function OnEnter(initial, reloading)
    if initial == nil and reloading == nil then initial = firstEnter end      -- a client that passes no arguments
    firstEnter = false
    if not (initial or reloading) then return end                             -- a zone change
    local key = CharKey()
    if not key or Live.frozen or type(StatTrackerUI) ~= "table" then return end
    local s = StatTrackerUI.session
    if initial or type(s) ~= "table" or s.key ~= key or not Finite(s.start) then
        NewSession(key)                                                       -- a login, or a session that is not this character's
    else
        Live.FillBaseline()                                                   -- /reload: the session goes on
    end
    for _, delay in ipairs(BASELINE_READS) do After(delay, Live.FillBaseline) end
    After(PLAYED_DELAY, AskForPlayedTime)
end

-- ---------------------------------------------------------------------------------------------------- the values

-- { time, available, session = { key, display, start, age }, gold = { now, delta }, stats = { { id, label, text, number, coin, delta, state } },
--   played = { total, base, age, estimate }, rates = { ready, minAge, gold, kills, killsLabel } }
-- state is "LIVE" (the game gave a value) or "UNKNOWN" (no value: never shown as 0); played is missing until the game has answered;
-- the rates (per hour: copper, creatures killed) are there once the session is RATE_MIN_AGE seconds old
function Live.Values()
    Live.FillBaseline()
    local s = type(StatTrackerUI) == "table" and not Live.frozen and StatTrackerUI.session or nil
    if type(s) ~= "table" or s.key ~= CharKey() then s = nil end
    local out = { time = Now(), available = Have(GetStatistic), stats = {} }
    if s then out.session = { key = s.key, display = DisplayName(s.key), start = s.start, age = Now() - s.start } end
    local money = ReadMoney()
    if money ~= nil then
        out.gold = { now = money }
        if s and s.money ~= nil then out.gold.delta = money - s.money end
    end
    for _, def in ipairs(STATS) do
        local text, number = Reading(def)
        local entry = { id = def.id, label = StatName(def.id), text = text, number = number, coin = def.coin,
                        state = (text ~= nil) and "LIVE" or "UNKNOWN" }
        if number ~= nil and s and type(s.stats) == "table" and s.stats[def.id] ~= nil then
            entry.delta = number - s.stats[def.id]
        end
        out.stats[#out.stats + 1] = entry
    end
    local base = PlayedBase()
    if base then
        local age = math.max(0, Now() - base.epoch)
        out.played = { total = base.total + age, base = base.total, age = age, estimate = age >= 2 }
    end
    out.rates = { minAge = RATE_MIN_AGE, ready = false }
    if out.session and out.session.age >= RATE_MIN_AGE then
        local hours = out.session.age / 3600
        out.rates.ready = true
        if out.gold and out.gold.delta ~= nil then out.rates.gold = out.gold.delta / hours end
        for _, entry in ipairs(out.stats) do
            if entry.id == 107 and entry.delta ~= nil then
                out.rates.kills, out.rates.killsLabel = entry.delta / hours, entry.label
            end
        end
    end
    return out
end

-- ---------------------------------------------------------------------------------------------------- chat

local function Coins(copper)                 -- copper >= 0
    return string.format("%.0f g %.0f s %.0f c", math.floor(copper / 10000), math.floor((copper % 10000) / 100), copper % 100)
end

local function Amount(value, coin)
    if coin then return Coins(value) end
    return string.format("%.0f", value)
end

local function Signed(delta, coin)
    if delta < 0 then return "-" .. Amount(-delta, coin) end
    return "+" .. Amount(delta, coin)
end

local function Duration(seconds)             -- 3815 -> "0d 1h 3m" (the same abbreviations in every language)
    local s = math.floor(seconds)
    return string.format("%.0fd %.0fh %.0fm", math.floor(s / 86400), math.floor((s % 86400) / 3600), math.floor((s % 3600) / 60))
end

-- what the window (StatTrackerWindow.lua) shares with the chat: the same texts and number formats
Live.Tr, Live.Say, Live.Amount, Live.Signed, Live.Duration = Tr, Say, Amount, Signed, Duration
Live.CharKey = CharKey

function Live.PrintStatus()
    local v = Live.Values()
    if not v.available then
        Say(Tr("Dieser Client liefert keine Statistiken.", "This client provides no statistics."))
        return
    end
    if v.session then
        Say(string.format(Tr("Live (%s, seit %.0f min):", "Live (%s, for %.0f min):"), v.session.display, v.session.age / 60))
    else
        Say(Tr("Live (keine Session):", "Live (no session):"))
    end
    for _, e in ipairs(v.stats) do
        local value
        if e.number ~= nil then value = Amount(e.number, e.coin)
        elseif e.text ~= nil then value = e.text
        else value = Tr("kein Wert", "no value") end
        local delta = ""
        if e.delta ~= nil then delta = " (" .. Signed(e.delta, e.coin) .. ")" end
        Say("  " .. e.label .. ": " .. value .. delta)
    end
    if v.gold and v.gold.delta ~= nil then
        Say("  " .. Tr("Session-Gold: ", "Session gold: ") .. Signed(v.gold.delta, true))
    end
    if v.played then
        local note = ""
        if v.played.estimate then note = " " .. Tr("(geschaetzt)", "(estimated)") end
        Say("  " .. Tr("Spielzeit: ", "Played time: ") .. Duration(v.played.total) .. note)
    else
        Say("  " .. Tr("Spielzeit: ", "Played time: ") .. Tr("kein Wert", "no value"))
    end
    if v.rates.ready then
        if v.rates.gold ~= nil then Say("  " .. Tr("Gold pro Stunde: ", "Gold per hour: ") .. Signed(v.rates.gold, true)) end
        if v.rates.kills ~= nil then
            Say("  " .. v.rates.killsLabel .. " " .. Tr("pro Stunde: ", "per hour: ") .. string.format("%.1f", v.rates.kills))
        end
    elseif v.session then
        Say("  " .. string.format(Tr("Raten ab %.0f min Sitzungsdauer", "Rates after %.0f min of session"), v.rates.minAge / 60))
    end
end

-- ---------------------------------------------------------------------------------------------------- reading while the data is shown

-- Something that shows the data (the window of a later step, or /statlive watch) switches the reading on under its own name. It runs while
-- at least one of them wants it: one read every TICK_SECONDS, and one EVENT_DELAY seconds after a kill, a turned-in quest or a change of
-- money (the statistics follow those within a few seconds, measured). Without C_Timer nothing runs by itself.
local wants = {}
local active = false
local tickGen = 0
local pendingRead = false
local last = {}                              -- id -> { text, number } of the last read: what the next one is compared with

local function Show(text, number, coin)
    if number ~= nil then return Amount(number, coin) end
    return text or Tr("kein Wert", "no value")
end

function Live.Poll()
    local v = Live.Values()
    for _, e in ipairs(v.stats) do
        local old = last[e.id]
        if old and old.text ~= e.text and Live.watching then
            local line = "  " .. e.label .. ": " .. Show(old.text, old.number, e.coin) .. " -> " .. Show(e.text, e.number, e.coin)
            if old.number ~= nil and e.number ~= nil then line = line .. " (" .. Signed(e.number - old.number, e.coin) .. ")" end
            Say(line)
        end
        last[e.id] = { text = e.text, number = e.number }
    end
    Live.last = v
    if Have(Live.onUpdate) then pcall(Live.onUpdate, v) end          -- the window of a later step hooks in here
    return v
end

local function ScheduleTick(gen)
    After(TICK_SECONDS, function()
        if gen ~= tickGen or not active then return end
        Live.Poll()
        ScheduleTick(gen)
    end)
end

local function Refresh()                     -- is the reading wanted by anybody?
    local on = false
    for _, wanted in pairs(wants) do
        if wanted then on = true end
    end
    if on == active then return end
    active = on
    tickGen = tickGen + 1                    -- a tick that is still waiting from an earlier switch-on ends by itself
    if on then
        Live.Poll()                          -- the first read: what the next change is compared with
        ScheduleTick(tickGen)
    end
end

function Live.SetActive(who, on)
    wants[who] = on and true or false
    Refresh()
end

local function ScheduleRead()                -- several events within the delay are one read
    if pendingRead then return end
    pendingRead = true
    local set = After(EVENT_DELAY, function()
        pendingRead = false
        if active then Live.Poll() end
    end)
    if not set then pendingRead = false end
end

-- ---------------------------------------------------------------------------------------------------- events and command

local frame = CreateFrame("Frame")
frame:RegisterEvent("ADDON_LOADED")
frame:RegisterEvent("PLAYER_ENTERING_WORLD")
for _, event in ipairs({ "PARTY_KILL", "QUEST_TURNED_IN", "PLAYER_MONEY", "TIME_PLAYED_MSG" }) do
    pcall(frame.RegisterEvent, frame, event)       -- an event the client does not know must not stop the others
end
frame:SetScript("OnEvent", function(self, event, arg1, arg2)
    if event == "ADDON_LOADED" then
        if arg1 ~= ADDON then return end
        InitSaved()
        self:UnregisterEvent("ADDON_LOADED")
    elseif event == "PLAYER_ENTERING_WORLD" then
        OnEnter(arg1, arg2)
    elseif event == "TIME_PLAYED_MSG" then
        OnPlayed(arg1)
    elseif active then                             -- PARTY_KILL, QUEST_TURNED_IN, PLAYER_MONEY
        ScheduleRead()
    end
end)

SLASH_STATLIVE1 = "/statlive"
if type(SlashCmdList) == "table" then
    SlashCmdList["STATLIVE"] = function(msg)
        local arg = string.lower(string.match(msg or "", "^%s*(.-)%s*$"))
        if arg == "watch" then
            Live.watching = not Live.watching
            Live.SetActive("watch", Live.watching)
            if Live.watching then
                Say(Tr("Beobachtung an: jede Aenderung steht im Chat (/statlive watch schaltet aus).",
                       "Watching on: every change is written to the chat (/statlive watch switches it off)."))
            else
                Say(Tr("Beobachtung aus.", "Watching off."))
            end
        elseif arg == "" and Have(Live.ToggleWindow) then
            Live.ToggleWindow()                                -- the window (a client without one falls back to the chat)
        else
            Live.PrintStatus()                                 -- "text", and anything else as before
        end
    end
end
