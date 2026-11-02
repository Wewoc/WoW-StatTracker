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
--   StatTrackerDB.version            = 4
--   StatTrackerDB.auto               = true/false
--   StatTrackerDB.meta[statID]       = { name = "...", cat = "category > subcategory" }
--   StatTrackerDB.repMeta[factionID] = { name = "..." }       -- last known (localized) faction name
--   StatTrackerDB.history["Name-Realm"] = { <scan>, <scan>, ... }
--       the scans before the newest one, newest first, at most HISTORY_MAX - 1 of them
--   StatTrackerDB.chars["Name-Realm"] = <scan>, the newest scan:
--       scannedAt = "YYYY-MM-DD HH:MM:SS", scannedEpoch = time(),
--       class = "...", level = N, faction = "...",
--       classFile = "MAGE", race = "...", raceFile = "Human",   -- classFile/raceFile are language independent
--       stats = { [statID] = "value as text" },
--       playedTotal = seconds, playedLevel = seconds,   -- arrives shortly after the scan (TIME_PLAYED_MSG)
--       -- all of the following are optional: a part that cannot be read is left out, the scan stays valid
--       specID = 72, specName = "...", role = "DAMAGER",
--       ilvlTotal = N, ilvlEquipped = N,                -- GetAverageItemLevel()
--       gear = { [slot 1..19] = { itemID, name, quality, ilvl, iconID, stats = { ITEM_MOD_... = N },
--                 enchantID, enchantText, upgrade = { trackID, track, level, max }, sockets, gems = { id or 0 } } },

local ADDON = ...
local PREFIX = "|cff00ff00[StatTracker]|r "
local PLAYED_TIMEOUT = 10   -- seconds to wait for the played-time answer
local AUTO_DELAY = 10       -- seconds after login until the auto-scan
local AUTO_MIN_AGE = 600    -- seconds: skip the auto-scan if the last scan is younger
local SCAN_SECONDS = 10     -- the scan is spread over about this many seconds (no game freeze)
local SCAN_TICK = 0.1       -- seconds between two slices
local HISTORY_MAX = 5       -- scans kept per character: the newest one plus HISTORY_MAX - 1 older ones
local NAME_WAIT = 5         -- seconds to wait at most for item names the game has not loaded yet
local NAME_POLL = 0.5       -- seconds between two looks at those names
local ENCHANT_LINE = 15     -- tooltip line type of the enchantment line (seen in game, 12.1.5)
local GEAR_SLOTS = 19       -- inventory slots 1..19 (18 is unused); empty ones are left out

local IS_DE = (GetLocale() == "deDE")
local function Tr(de, en) if IS_DE then return de end return en end

local function Say(msg) print(PREFIX .. msg) end

local loader = CreateFrame("Frame")
loader:RegisterEvent("ADDON_LOADED")
loader:SetScript("OnEvent", function(self, _, name)
    if name ~= ADDON then return end
    StatTrackerDB = StatTrackerDB or {}
    StatTrackerDB.version = 4
    StatTrackerDB.meta = StatTrackerDB.meta or {}
    StatTrackerDB.repMeta = StatTrackerDB.repMeta or {}
    StatTrackerDB.chars = StatTrackerDB.chars or {}
    StatTrackerDB.history = StatTrackerDB.history or {}
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

-- The scan that is about to be replaced moves to the front of the character's history, which is cut to
-- HISTORY_MAX - 1 entries. A scan with the same time as the new one (or as the first history entry) is not kept twice.
local function PushHistory(key, old, newAt)
    if type(old) ~= "table" or not old.scannedAt or old.scannedAt == newAt then return end
    StatTrackerDB.history = StatTrackerDB.history or {}
    local list = StatTrackerDB.history[key]
    if type(list) ~= "table" then
        list = {}
        StatTrackerDB.history[key] = list
    end
    if list[1] and list[1].scannedAt == old.scannedAt then return end
    table.insert(list, 1, old)
    for i = #list, HISTORY_MAX, -1 do list[i] = nil end
end

local scanning = false   -- true from the start of a scan until it is stored; a second scan is refused

-- Everything below that reads more than the statistics (specialization, item level, gear) is optional: a function
-- the game version does not have is skipped without a word, an error in one part is reported in chat and the part
-- is left out. The statistics are never lost because of it.
local function Collect(de, en, fn, ...)
    local ok, err = pcall(fn, ...)
    if not ok then
        Say("|cffff0000" .. Tr(de .. " nicht gelesen:", en .. " not read:") .. "|r " .. tostring(err) .. " " ..
            Tr("Statistiken sind gespeichert.", "Statistics are saved."))
    end
end

local function NonEmpty(value)
    if type(value) == "string" and value ~= "" then return value end
end

-- Specialization: the id comes from PlayerUtil if there, else from the specialization info of the active index.
local function CollectSpec(into)
    local getIndex = GetSpecialization or (C_SpecializationInfo and C_SpecializationInfo.GetSpecialization)
    local getInfo = GetSpecializationInfo or (C_SpecializationInfo and C_SpecializationInfo.GetSpecializationInfo)
    if type(getIndex) ~= "function" or type(getInfo) ~= "function" then return end
    local index = getIndex()
    if type(index) ~= "number" then return end
    local id, name, _, _, role = getInfo(index)
    local current = PlayerUtil and PlayerUtil.GetCurrentSpecID and PlayerUtil.GetCurrentSpecID()
    if type(current) == "number" and current > 0 then id = current end
    if type(id) == "number" and id > 0 then into.specID = id end
    into.specName = NonEmpty(name)
    into.role = NonEmpty(role)
end

local function CollectItemLevel(into)
    if type(GetAverageItemLevel) ~= "function" then return end
    local total, equipped = GetAverageItemLevel()
    if type(total) == "number" then into.ilvlTotal = total end
    if type(equipped) == "number" then into.ilvlEquipped = equipped end
end

-- The fields of the item string of a link (between "|Hitem:" and "|h"), empty fields included:
-- 1 = item id, 2 = enchantment id.
local function ItemFields(link)
    local fields = {}
    local text = link:match("|Hitem:([^|]*)|h")
    if text then
        for part in (text .. ":"):gmatch("([^:]*):") do fields[#fields + 1] = part end
    end
    return fields
end

local function ItemInfo(link)
    local fn = (C_Item and C_Item.GetItemInfo) or GetItemInfo
    if type(fn) ~= "function" then return end
    return fn(link)
end

local function Trim(text)
    return (text:gsub("^%s+", ""):gsub("%s+$", ""))
end

-- The text of the enchantment line of the equipped item ("Enchanted: Shoulders - X" without the prefix), if any.
local function EnchantText(slot)
    if not (C_TooltipInfo and type(C_TooltipInfo.GetInventoryItem) == "function") then return end
    local data = C_TooltipInfo.GetInventoryItem("player", slot)
    if type(data) ~= "table" or type(data.lines) ~= "table" then return end
    local surface = TooltipUtil and TooltipUtil.SurfaceArgs
    if surface then pcall(surface, data) end
    for _, line in ipairs(data.lines) do
        if surface then pcall(surface, line) end
        if line.type == ENCHANT_LINE and type(line.leftText) == "string" then
            local text = line.leftText
            text = (text:gsub("|A:[^|]*|a", ""))               -- inline icons
            text = (text:gsub("|cn[^:]*:", ""))                -- named colour codes
            text = (text:gsub("|c%x%x%x%x%x%x%x%x", ""))       -- colour codes
            text = (text:gsub("|r", ""))
            text = (text:gsub("^[^:]*:%s*", ""))               -- the localized prefix "Enchanted:"
            return NonEmpty(Trim(text))
        end
    end
end

-- Everything about one equipped item. Each value is taken only if it has the expected type; an item the game
-- has not loaded yet has no name and goes on the waiting list.
local function ReadItem(item, slot)
    local texture = GetInventoryItemTexture and GetInventoryItemTexture("player", slot)
    if type(texture) == "number" then item.iconID = texture end
    local link = GetInventoryItemLink and GetInventoryItemLink("player", slot)
    if type(link) ~= "string" then return end
    item.link = link                                          -- removed before the scan is stored

    local name, _, quality, baseLevel = ItemInfo(link)
    item.name = NonEmpty(name)
    if type(quality) == "number" then item.quality = quality end
    local level = C_Item and C_Item.GetDetailedItemLevelInfo and C_Item.GetDetailedItemLevelInfo(link)
    if type(level) ~= "number" then level = baseLevel end
    if type(level) == "number" then item.ilvl = level end

    if C_Item and C_Item.GetItemStats then
        local stats = C_Item.GetItemStats(link)
        if type(stats) == "table" then
            local copy = {}
            for k, v in pairs(stats) do
                if type(k) == "string" and type(v) == "number" then copy[k] = v end
            end
            if next(copy) then item.stats = copy end
        end
    end

    local enchant = tonumber(ItemFields(link)[2])
    if enchant and enchant > 0 then
        item.enchantID = enchant
        item.enchantText = EnchantText(slot)
    end

    local upgrade = C_Item and C_Item.GetItemUpgradeInfo and C_Item.GetItemUpgradeInfo(link)
    if type(upgrade) == "table" and type(upgrade.maxLevel) == "number" and upgrade.maxLevel > 0
       and type(upgrade.currentLevel) == "number" then
        item.upgrade = { trackID = upgrade.trackStringID, track = NonEmpty(upgrade.trackString),
                         level = upgrade.currentLevel, max = upgrade.maxLevel }
    end

    local sockets = C_Item and C_Item.GetItemNumSockets and C_Item.GetItemNumSockets(link)
    if type(sockets) == "number" and sockets > 0 then
        item.sockets = sockets
        item.gems = {}                                         -- gem ids, 0 = empty (not yet seen filled in game)
        local gemId = C_Item.GetItemGemID
        for i = 1, sockets do
            local id = gemId and gemId(link, i)
            item.gems[i] = (type(id) == "number") and id or 0
        end
    end
end

-- Reads the 19 slots. Items without a name yet are added to `waiting` and asked for again later.
local function CollectGear(into, waiting)
    if type(GetInventoryItemID) ~= "function" then return end
    local gear, failed = {}, nil
    for slot = 1, GEAR_SLOTS do
        local id = GetInventoryItemID("player", slot)
        if type(id) == "number" then
            local item = { itemID = id }
            local ok, err = pcall(ReadItem, item, slot)
            if ok then
                gear[slot] = item
                if not item.name and item.link then
                    waiting[#waiting + 1] = item
                    if C_Item and C_Item.RequestLoadItemDataByID then pcall(C_Item.RequestLoadItemDataByID, id) end
                end
            else
                failed = failed or err                         -- this slot is left out, the others stay
            end
        end
    end
    if next(gear) then into.gear = gear end
    if failed then error(failed, 0) end
end

-- One look at the items that still have no name; the ones that have one now leave the list.
local function FillNames(waiting)
    for i = #waiting, 1, -1 do
        local name = ItemInfo(waiting[i].link)
        if NonEmpty(name) then
            waiting[i].name = name
            table.remove(waiting, i)
        end
    end
end

local function DropLinks(into)
    if into.gear then
        for _, item in pairs(into.gear) do item.link = nil end
    end
end

-- Store the finished scan, then ask for the played time (TIME_PLAYED_MSG). The record exists before the request,
-- because the answer is written into it.
local function StoreScan(key, st, extra)
    scanning = false
    DropLinks(extra)
    PushHistory(key, StatTrackerDB.chars[key], st.scannedAt)
    local rec = {
        scannedAt = st.scannedAt,
        scannedEpoch = st.scannedEpoch,
        class = st.class,
        level = st.level,
        faction = st.faction,
        classFile = st.classFile,
        race = st.race,
        raceFile = st.raceFile,
        stats = st.stats,
    }
    for field, value in pairs(extra) do rec[field] = value end
    StatTrackerDB.chars[key] = rec
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

-- The statistics are read. Collect the rest; if item names are missing wait for them up to NAME_WAIT seconds
-- (`scanning` stays true, a /reload during the wait loses the scan, like one during the scan itself), then store.
local function FinishScan(key, st)
    st.scannedAt = date("%Y-%m-%d %H:%M:%S")
    st.scannedEpoch = time()
    local extra, waiting = {}, {}
    Collect("Spezialisierung", "Specialization", CollectSpec, extra)
    Collect("Itemlevel", "Item level", CollectItemLevel, extra)
    Collect("Ausruestung", "Gear", CollectGear, extra, waiting)

    if #waiting == 0 then
        StoreScan(key, st, extra)
        return
    end
    local waited = 0
    local function look()
        pcall(FillNames, waiting)
        waited = waited + NAME_POLL
        if #waiting == 0 or waited >= NAME_WAIT then
            StoreScan(key, st, extra)                          -- names still missing stay nil, never ""
        else
            C_Timer.After(NAME_POLL, look)
        end
    end
    C_Timer.After(NAME_POLL, look)
end

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
    -- the second return value of UnitClass/UnitRace is the language independent file name
    local className, classFile = UnitClass("player")
    local raceName, raceFile = UnitRace("player")
    local st = {
        tasks = tasks, ti = 1, ai = 1, stats = {}, meta = {}, count = 0,
        class = className, level = UnitLevel("player"), faction = UnitFactionGroup("player"),
        classFile = classFile, race = raceName, raceFile = raceFile,
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
        if st.count == 0 then
            scanning = false
            Say("|cffff0000" .. Tr("Scan fehlgeschlagen:", "Scan failed:") .. "|r " ..
                Tr("keine Statistik gelesen (0 Eintraege)", "no statistic read (0 entries)"))
            return
        end
        local finishOk, finishErr = pcall(FinishScan, key, st)
        if not finishOk then
            scanning = false
            Say("|cffff0000" .. Tr("Scan fehlgeschlagen:", "Scan failed:") .. "|r " .. tostring(finishErr))
        end
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
