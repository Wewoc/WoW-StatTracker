-- SPDX-License-Identifier: GPL-3.0-or-later
-- Copyright (C) 2026 Wewoc (github.com/wewoc)
-- StatTracker.lua (Retail)
-- Reads all statistics + played time of the logged-in character into StatTrackerDB.
--   /statscan        -> scan now
--   /statscan auto   -> auto-scan at login on/off (default: on)
-- The scan reads the statistics in slices over ~10 seconds (SCAN_SECONDS) so the game does
-- not freeze; chat shows "Stat sync started" and "Stat sync done".
-- Auto-scan: only on a real login (not on /reload or zone change), with a delay,
-- and not if this character's last scan is younger than AUTO_MIN_AGE.
-- SavedVariables are only written to disk by WoW on /reload or logout.
-- Chat messages are German on a German client (deDE), English otherwise.
--
-- Data structure (account-wide):
--   StatTrackerDB.version            = 2
--   StatTrackerDB.auto               = true/false
--   StatTrackerDB.meta[statID]       = { name = "...", cat = "category > subcategory" }
--   StatTrackerDB.chars["Name-Realm"] = {
--       scannedAt = "YYYY-MM-DD HH:MM:SS", scannedEpoch = time(),
--       class = "...", level = N, faction = "...",
--       stats = { [statID] = "value as text" },
--       playedTotal = seconds, playedLevel = seconds,   -- arrives shortly after the scan (TIME_PLAYED_MSG)
--   }

local ADDON = ...
local PREFIX = "|cff00ff00[StatTracker]|r "
local PLAYED_TIMEOUT = 10   -- seconds to wait for the played-time answer
local AUTO_DELAY = 10       -- seconds after login until the auto-scan
local AUTO_MIN_AGE = 600    -- seconds: skip the auto-scan if the last scan is younger
local SCAN_SECONDS = 10     -- the scan is spread over about this many seconds (no game freeze)
local SCAN_TICK = 0.1       -- seconds between two slices

local IS_DE = (GetLocale() == "deDE")
local function Tr(de, en) if IS_DE then return de end return en end

local function Say(msg) print(PREFIX .. msg) end

local loader = CreateFrame("Frame")
loader:RegisterEvent("ADDON_LOADED")
loader:SetScript("OnEvent", function(self, _, name)
    if name ~= ADDON then return end
    StatTrackerDB = StatTrackerDB or {}
    StatTrackerDB.version = 2
    StatTrackerDB.meta = StatTrackerDB.meta or {}
    StatTrackerDB.chars = StatTrackerDB.chars or {}
    if StatTrackerDB.auto == nil then StatTrackerDB.auto = true end
    self:UnregisterEvent("ADDON_LOADED")
end)

-- Build the category path "Parent > Child" (cached)
local function CategoryPath(catID, cache)
    if cache[catID] then return cache[catID] end
    local title, parentID = GetCategoryInfo(catID)
    local path = title or ("Cat_" .. catID)
    if parentID and parentID > 0 and parentID ~= catID then
        path = CategoryPath(parentID, cache) .. " > " .. path
    end
    cache[catID] = path
    return path
end

-- The ~2000 statistics are read in small slices spread over SCAN_SECONDS, so the game
-- does not freeze for a moment. Everything goes into local tables; the DB is only written
-- at the very end (no half state on error, /reload or logout during the scan).

-- Cheap first pass: the category list with the entry count of each (no statistic read yet).
local function BuildTasks()
    -- Some game versions (e.g. BC Anniversary) have no statistics at all: say so plainly
    -- instead of showing a raw Lua error. error(..., 0) = no file/line prefix.
    local NO_STATS = Tr("Diese Spielversion stellt keine Statistiken bereit - StatTracker funktioniert hier nicht.",
                        "This game version provides no statistics - StatTracker does not work here.")
    if type(GetStatisticsCategoryList) ~= "function" or type(GetCategoryNumAchievements) ~= "function"
       or type(GetAchievementInfo) ~= "function" or type(GetStatistic) ~= "function" then
        error(NO_STATS, 0)
    end
    local cats = GetStatisticsCategoryList()
    if type(cats) ~= "table" or #cats == 0 then
        error(NO_STATS, 0)
    end

    local pathCache, tasks, total = {}, {}, 0
    for _, catID in ipairs(cats) do
        local num = GetCategoryNumAchievements(catID) or 0
        tasks[#tasks + 1] = { catID = catID, num = num, path = CategoryPath(catID, pathCache) }
        total = total + num
    end

    if total == 0 then
        error(NO_STATS, 0)
    end
    return tasks, total
end

-- Reads up to `budget` statistics, continuing where `st` left off. Returns true when all are read.
local function ScanStep(st, budget)
    while budget > 0 do
        local task = st.tasks[st.ti]
        if not task then return true end
        if st.ai > task.num then
            st.ti, st.ai = st.ti + 1, 1
        else
            local id, name = GetAchievementInfo(task.catID, st.ai)
            if id then
                st.stats[id] = GetStatistic(id) or "--"
                st.meta[id] = { name = name or ("Stat_" .. id), cat = task.path }
                st.count = st.count + 1
            end
            st.ai = st.ai + 1
            budget = budget - 1
        end
    end
    return st.tasks[st.ti] == nil
end

-- Played time: RequestTimePlayed() triggers TIME_PLAYED_MSG (total seconds, seconds this level).
-- pendingKey is only set during a running request; a manual /played is ignored.
local pendingKey = nil

local played = CreateFrame("Frame")
played:RegisterEvent("TIME_PLAYED_MSG")
played:SetScript("OnEvent", function(_, _, total, levelTime)
    if not pendingKey then return end
    local rec = StatTrackerDB.chars[pendingKey]
    local key = pendingKey
    pendingKey = nil
    if not rec then return end
    rec.playedTotal = total
    rec.playedLevel = levelTime
    Say(Tr("Spielzeit fuer " .. key .. " erfasst. Daten werden bei /reload oder Logout geschrieben.",
           "Played time for " .. key .. " recorded. Data is written on /reload or logout."))
end)

-- Store the finished scan, then ask for the played time (TIME_PLAYED_MSG).
local function FinishScan(key, st)
    StatTrackerDB.chars[key] = {
        scannedAt = date("%Y-%m-%d %H:%M:%S"),
        scannedEpoch = time(),
        class = st.class,
        level = st.level,
        faction = st.faction,
        stats = st.stats,
    }
    for id, m in pairs(st.meta) do
        StatTrackerDB.meta[id] = m
    end

    Say(Tr("Stat-Sync fertig: " .. st.count .. " Statistiken fuer " .. key .. " erfasst. Warte auf Spielzeit ...",
           "Stat sync done: " .. st.count .. " statistics recorded for " .. key .. ". Waiting for played time ..."))

    pendingKey = key
    RequestTimePlayed()
    C_Timer.After(PLAYED_TIMEOUT, function()
        if pendingKey == key then
            pendingKey = nil
            Say("|cffff0000" .. Tr("Keine Spielzeit-Antwort fuer " .. key .. ".",
                                   "No played-time answer for " .. key .. ".") .. "|r " ..
                Tr("Statistiken sind gespeichert, Spielzeit fehlt. /statscan wiederholen.",
                   "Statistics are saved, played time is missing. Repeat /statscan."))
        end
    end)
end

local scanning = false   -- true while a (spread-out) scan is running; a second one is refused

local function ScanAllStats()
    if not StatTrackerDB or not StatTrackerDB.chars then
        Say("|cffff0000" .. Tr("DB nicht initialisiert.", "DB not initialized.") .. "|r")
        return
    end
    if scanning then
        Say(Tr("Stat-Sync laeuft bereits.", "Stat sync is already running."))
        return
    end

    local ok, tasks, total = pcall(BuildTasks)
    if not ok then
        Say("|cffff0000" .. Tr("Scan fehlgeschlagen:", "Scan failed:") .. "|r " .. tostring(tasks))
        return
    end

    local key = UnitName("player") .. "-" .. GetRealmName()
    local st = {
        tasks = tasks, ti = 1, ai = 1, stats = {}, meta = {}, count = 0,
        class = UnitClass("player"), level = UnitLevel("player"), faction = UnitFactionGroup("player"),
    }
    local perTick = math.max(1, math.ceil(total / (SCAN_SECONDS / SCAN_TICK)))

    scanning = true
    Say(Tr("Stat-Sync gestartet fuer " .. key .. " (ca. " .. SCAN_SECONDS .. " Sek., bitte nicht /reload vor 'fertig') ...",
           "Stat sync started for " .. key .. " (about " .. SCAN_SECONDS .. " s, please do not /reload before 'done') ..."))

    local function tick()
        local stepOk, finished = pcall(ScanStep, st, perTick)
        if not stepOk then
            scanning = false
            Say("|cffff0000" .. Tr("Scan fehlgeschlagen:", "Scan failed:") .. "|r " .. tostring(finished))
            return
        end
        if not finished then
            C_Timer.After(SCAN_TICK, tick)
            return
        end
        scanning = false
        if st.count == 0 then
            Say("|cffff0000" .. Tr("Scan fehlgeschlagen:", "Scan failed:") .. "|r " ..
                Tr("keine Statistik gelesen (0 Eintraege)", "no statistic read (0 entries)"))
            return
        end
        FinishScan(key, st)
    end
    C_Timer.After(SCAN_TICK, tick)
end

-- Auto-scan only on a real login (isInitialLogin), not on /reload or zone change
local autoFrame = CreateFrame("Frame")
autoFrame:RegisterEvent("PLAYER_ENTERING_WORLD")
autoFrame:SetScript("OnEvent", function(_, _, isInitialLogin)
    if not isInitialLogin then return end
    if not StatTrackerDB or not StatTrackerDB.auto then return end
    C_Timer.After(AUTO_DELAY, function()
        local key = UnitName("player") .. "-" .. GetRealmName()
        local rec = StatTrackerDB.chars[key]
        if rec and rec.scannedEpoch and (time() - rec.scannedEpoch) < AUTO_MIN_AGE then
            Say(Tr("Auto-Scan uebersprungen: letzter Scan von " .. key .. " ist juenger als " ..
                       (AUTO_MIN_AGE / 60) .. " Min. (/statscan scannt trotzdem)",
                   "Auto-scan skipped: the last scan of " .. key .. " is younger than " ..
                       (AUTO_MIN_AGE / 60) .. " min. (/statscan scans anyway)"))
            return
        end
        ScanAllStats()
    end)
end)

SLASH_STATTRACKER1 = "/statscan"
SlashCmdList["STATTRACKER"] = function(msg)
    msg = strlower(strtrim(msg or ""))
    if msg == "" then
        ScanAllStats()
    elseif msg == "auto" then
        StatTrackerDB.auto = not StatTrackerDB.auto
        Say(Tr("Auto-Scan beim Login: ", "Auto-scan at login: ") ..
            (StatTrackerDB.auto and "|cff00ff00" .. Tr("AN", "ON") .. "|r"
                                or "|cffff0000" .. Tr("AUS", "OFF") .. "|r"))
    else
        Say(Tr("/statscan = jetzt scannen, /statscan auto = Auto-Scan beim Login ein/aus (aktuell " ..
                   (StatTrackerDB.auto and "AN" or "AUS") .. ")",
               "/statscan = scan now, /statscan auto = auto-scan at login on/off (currently " ..
                   (StatTrackerDB.auto and "ON" or "OFF") .. ")"))
    end
end
