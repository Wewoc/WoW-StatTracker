-- SPDX-License-Identifier: GPL-3.0-or-later
-- Copyright (C) 2026 Wewoc (github.com/wewoc)
-- StatTrackerWindow.lua (Retail and WoW Forever)
-- The window of the live part: it shows what StatTrackerLive.lua reads (Live.Values()) and calculates nothing itself.
--   /statlive shows or hides it. While it is open the live part reads every few seconds (Live.SetActive), when it is closed nothing runs.
--   One row per value; a row is LIVE (the game gave a value), SNAPSHOT (no live value, the value of the last scan is shown dimmed
--   with "Scan") or UNKNOWN ("no value", never 0). The tooltip of a statistic row tells the value of the last scan and how old it is.
--   The scan (StatTrackerDB) is only READ here, to show its value and its age; nothing in this file writes it.
--   The title "StatTracker v<version>" sits above the rows. The corner at the bottom right changes the width (the height follows the rows).
--   The position, the width and whether it was open are kept in StatTrackerUI.settings.window = { point, rel, x, y, width, shown }.
-- Without a frame API (or when anything in building the window fails) the file does nothing and /statlive writes the chat text.

local ADDON, ns = ...
local Live = type(ns) == "table" and ns.Live
if type(Live) ~= "table" then return end

local WIDTH = 340                         -- the width until the player drags the corner (kept in the settings)
local MIN_WIDTH, MAX_WIDTH = 240, 700     -- what the corner allows; a saved width outside these is not used
local ROW_H = 16
local TOP = 26                            -- space above the first row (the close button sits there)
local RESTORE_DELAY = 2                  -- seconds after a login or /reload until a window that was open is opened again (the interface stands by then)
local PAD = 18                            -- space below the last row (the corner to drag sits there)
-- the anchors, and how much of a change of the width moves the left edge to the left (0 left anchor, 0.5 centre, 1 right):
-- the corner keeps the left edge where it is, so the offset of the window is moved by that share of the change
local ANCHORS = { TOPLEFT = 0, LEFT = 0, BOTTOMLEFT = 0, TOP = 0.5, CENTER = 0.5, BOTTOM = 0.5, TOPRIGHT = 1, RIGHT = 1, BOTTOMRIGHT = 1 }
local COLORS = {                          -- r, g, b per state
    HEAD = { 1, 0.82, 0 }, LIVE = { 1, 1, 1 }, SNAPSHOT = { 0.65, 0.65, 0.65 }, UNKNOWN = { 0.5, 0.5, 0.5 }, FOOT = { 0.55, 0.55, 0.55 },
}

local Tr, Say, Amount, Signed, Duration = Live.Tr, Live.Say, Live.Amount, Live.Signed, Live.Duration
local function Have(fn) return type(fn) == "function" end
local function Finite(x) return type(x) == "number" and x == x and x ~= math.huge and x ~= -math.huge end
local function Try(obj, method, ...)         -- a cosmetic call: a client without it just goes without
    if obj and Have(obj[method]) then pcall(obj[method], obj, ...) end
end

-- ---------------------------------------------------------------------------------------------------- the scan (read only)

-- The newest scan of the character: its statistic texts and when it was made, or nil. Only reads.
local function Scan(key)
    local db = StatTrackerDB
    if type(db) ~= "table" or type(db.chars) ~= "table" or not key then return nil end
    local rec = db.chars[key]
    if type(rec) ~= "table" or type(rec.stats) ~= "table" or not Finite(rec.scannedEpoch) then return nil end
    return rec
end

local function Age(seconds)                  -- 125 -> "vor 2 min" / "2 min ago"
    seconds = math.max(0, seconds)
    local text
    if seconds < 60 then text = string.format("%.0f s", math.floor(seconds))
    elseif seconds < 3600 then text = string.format("%.0f min", math.floor(seconds / 60))
    elseif seconds < 86400 then text = string.format("%.0f h", math.floor(seconds / 3600))
    else text = string.format("%.0f d", math.floor(seconds / 86400)) end
    return Tr("vor " .. text, text .. " ago")
end

-- The title: "StatTracker v0.2.4" (the version of the .toc, which the game tells; without it just the name).
function Live.WindowTitle()
    local version
    local getter = (type(C_AddOns) == "table" and C_AddOns.GetAddOnMetadata) or GetAddOnMetadata
    if Have(getter) then
        local ok, v = pcall(getter, ADDON, "Version")
        if ok and type(v) == "string" and string.find(v, "^[%w%.%-_+]+$") then version = v end
    end
    if version then return "StatTracker v" .. version end
    return "StatTracker"
end

-- ---------------------------------------------------------------------------------------------------- the lines

-- The rows of the window for the values v: { { label, value, state, tip }, ... }; state is HEAD, LIVE, SNAPSHOT, UNKNOWN or FOOT.
-- A pure function of v, the scan and the clock (the tests read the rows, the window only draws them).
function Live.WindowLines(v)
    local lines = {}
    local function add(label, value, state, tip)
        lines[#lines + 1] = { label = label, value = value or "", state = state or "LIVE", tip = tip }
    end
    local key = v.session and v.session.key or Live.CharKey()
    local rec = Scan(key)
    add(v.session and v.session.display or Tr("Keine Session", "No session"), "", "HEAD")
    if not v.available then
        add(Tr("Dieser Client liefert keine Statistiken.", "This client provides no statistics."), "", "UNKNOWN")
        return lines
    end
    local none = Tr("kein Wert", "no value")
    for _, e in ipairs(v.stats) do
        local scanText = rec and rec.stats[e.id]
        if scanText == "--" or scanText == "" then scanText = nil end
        local scanShown
        if scanText ~= nil then
            scanText = tostring(scanText)
            local number
            if e.coin then number = Live.ParseCoins(scanText) else number = Live.ParseNumber(scanText) end
            scanShown = (number ~= nil) and Amount(number, e.coin) or scanText
        end
        local tip
        if scanShown then tip = Tr("Letzter Scan: ", "Last scan: ") .. scanShown .. ", " .. Age(v.time - rec.scannedEpoch)
        else tip = Tr("Noch kein Scan", "No scan yet") end
        if e.state == "LIVE" then
            local value = (e.number ~= nil) and Amount(e.number, e.coin) or e.text
            if e.delta ~= nil then value = value .. " (" .. Signed(e.delta, e.coin) .. ")" end
            add(e.label, value, "LIVE", tip)
        elseif scanShown then
            add(e.label, scanShown .. " (Scan)", "SNAPSHOT", tip)
        else
            add(e.label, none, "UNKNOWN", tip)
        end
    end
    if v.gold and v.gold.delta ~= nil then add(Tr("Session-Gold", "Session gold"), Signed(v.gold.delta, true), "LIVE")
    else add(Tr("Session-Gold", "Session gold"), none, "UNKNOWN") end
    if v.played then
        local note = v.played.estimate and (" " .. Tr("(geschaetzt)", "(estimated)")) or ""
        add(Tr("Spielzeit", "Played time"), Duration(v.played.total) .. note, "LIVE")
    else
        add(Tr("Spielzeit", "Played time"), none, "UNKNOWN")
    end
    if v.rates.ready then
        if v.rates.gold ~= nil then add(Tr("Gold pro Stunde", "Gold per hour"), Signed(v.rates.gold, true), "LIVE") end
        if v.rates.kills ~= nil then
            add(v.rates.killsLabel .. Tr(" pro Stunde", " per hour"), string.format("%.1f", v.rates.kills), "LIVE")
        end
    elseif v.session then
        add(Tr("Raten", "Rates"), string.format(Tr("ab %.0f min", "after %.0f min"), v.rates.minAge / 60), "UNKNOWN")
    end
    local clock = Have(date) and date("%H:%M:%S", v.time) or ""
    add(Tr("Aktualisiert", "Updated"), clock, "FOOT")
    add(Tr("Letzter Scan", "Last scan"), rec and Age(v.time - rec.scannedEpoch) or Tr("noch keiner", "none yet"), "FOOT")
    return lines
end

-- ---------------------------------------------------------------------------------------------------- saved position

local function Settings()                    -- StatTrackerUI.settings, or nil (no file yet, or written by a newer addon: left alone)
    if Live.frozen or type(StatTrackerUI) ~= "table" or type(StatTrackerUI.settings) ~= "table" then return nil end
    return StatTrackerUI.settings
end

local win                                    -- the frame, built when it is first needed
local width = WIDTH                          -- its width now
local widthSet = false                       -- true once the player chose a width (only that is saved: a changed default then reaches everybody else)

local function WidthOk(w) return Finite(w) and w >= MIN_WIDTH and w <= MAX_WIDTH end
local function Clamp(w)
    if not Finite(w) then return nil end
    return math.max(MIN_WIDTH, math.min(MAX_WIDTH, w))
end

local function SaveWindow(shownKnown, shown)
    local s = Settings()
    if not s or not win then return end
    local w = type(s.window) == "table" and s.window or {}
    local ok, point, _, rel, x, y = pcall(win.GetPoint, win)
    if ok and ANCHORS[point] and ANCHORS[rel] and Finite(x) and Finite(y) then
        w.point, w.rel, w.x, w.y = point, rel, x, y
    end
    if widthSet and WidthOk(width) then w.width = width end
    if shownKnown then w.shown = shown and true or false end
    s.window = w
end

local function ApplyPosition()
    win:ClearAllPoints()
    local s = Settings()
    local w = s and s.window
    if type(w) == "table" and WidthOk(w.width) then width, widthSet = w.width, true end
    if type(w) == "table" and ANCHORS[w.point] and ANCHORS[w.rel] and Finite(w.x) and Finite(w.y)
       and math.abs(w.x) < 10000 and math.abs(w.y) < 10000 then
        win:SetPoint(w.point, UIParent, w.rel, w.x, w.y)
    else
        win:SetPoint("CENTER", UIParent, "CENTER", 0, 0)
    end
end

-- ---------------------------------------------------------------------------------------------------- the frame

local function StartMove() Try(win, "StartMoving") end
local function StopMove() Try(win, "StopMovingOrSizing") SaveWindow(false) end

-- The corner at the bottom right changes the width only (the height follows the rows). It reads the mouse itself instead of using the
-- game's sizing, so it is the same on every client; the left edge stays where it is.
local function SetWidthTo(w)
    local c = Clamp(w)
    if not c or c == width then return end
    local delta = c - width
    width, widthSet = c, true
    win:SetWidth(c)
    local ok, point, rel, relPoint, x, y = pcall(win.GetPoint, win)
    if ok and ANCHORS[point] and Finite(x) and Finite(y) then
        win:ClearAllPoints()
        win:SetPoint(point, rel or UIParent, relPoint or point, x + ANCHORS[point] * delta, y)
    end
end

local function BuildGrip(f)
    local g = CreateFrame("Button", nil, f)
    g:SetWidth(14)
    g:SetHeight(14)
    g:SetPoint("BOTTOMRIGHT", f, "BOTTOMRIGHT", -4, 4)
    Try(g, "EnableMouse", true)
    Try(g, "SetNormalTexture", "Interface\\ChatFrame\\UI-ChatIM-SizeGrabber-Up")
    Try(g, "SetPushedTexture", "Interface\\ChatFrame\\UI-ChatIM-SizeGrabber-Down")
    Try(g, "SetHighlightTexture", "Interface\\ChatFrame\\UI-ChatIM-SizeGrabber-Highlight")
    g:SetScript("OnMouseDown", function(self, button)
        if button ~= "LeftButton" or not Have(GetCursorPosition) then return end
        local startX = GetCursorPosition()
        local scale = Have(f.GetEffectiveScale) and f:GetEffectiveScale() or 1
        if not Finite(scale) or scale <= 0 then scale = 1 end
        local startWidth = width
        if not Finite(startX) then return end
        self:SetScript("OnUpdate", function()
            local x = GetCursorPosition()
            if Finite(x) then SetWidthTo(startWidth + (x - startX) / scale) end
        end)
    end)
    g:SetScript("OnMouseUp", function(self)
        self:SetScript("OnUpdate", nil)
        SaveWindow(false)
    end)
    g:SetScript("OnEnter", function(self)
        if type(GameTooltip) ~= "table" then return end
        pcall(function()
            GameTooltip:SetOwner(self, "ANCHOR_RIGHT")
            GameTooltip:AddLine(Tr("Breite aendern (ziehen)", "Change the width (drag)"), 1, 1, 1)
            GameTooltip:Show()
        end)
    end)
    g:SetScript("OnLeave", function() if type(GameTooltip) == "table" then pcall(GameTooltip.Hide, GameTooltip) end end)
    return g
end

local function Row(i)
    local r = win.rows[i]
    if r then return r end
    r = CreateFrame("Frame", nil, win)
    r:SetHeight(ROW_H)
    r:SetPoint("TOPLEFT", win, "TOPLEFT", 8, -(TOP + (i - 1) * ROW_H))
    r:SetPoint("TOPRIGHT", win, "TOPRIGHT", -8, -(TOP + (i - 1) * ROW_H))
    Try(r, "EnableMouse", true)
    Try(r, "RegisterForDrag", "LeftButton")                   -- a row with a mouse of its own must still move the window
    r:SetScript("OnDragStart", StartMove)
    r:SetScript("OnDragStop", StopMove)
    r.right = r:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
    r.right:SetPoint("RIGHT", r, "RIGHT", 0, 0)
    Try(r.right, "SetJustifyH", "RIGHT")
    r.left = r:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
    r.left:SetPoint("LEFT", r, "LEFT", 0, 0)
    r.left:SetPoint("RIGHT", r.right, "LEFT", -6, 0)
    Try(r.left, "SetJustifyH", "LEFT")
    Try(r.left, "SetWordWrap", false)
    r:SetScript("OnEnter", function(self)
        if not self.tip or type(GameTooltip) ~= "table" then return end
        pcall(function()
            GameTooltip:SetOwner(self, "ANCHOR_RIGHT")
            GameTooltip:AddLine(self.label or "", 1, 1, 1)
            GameTooltip:AddLine(self.tip, 0.7, 0.7, 0.7)
            GameTooltip:Show()
        end)
    end)
    r:SetScript("OnLeave", function() if type(GameTooltip) == "table" then pcall(GameTooltip.Hide, GameTooltip) end end)
    win.rows[i] = r
    return r
end

local function Render(v)
    if not win then return end
    local lines = Live.WindowLines(v or Live.Values())
    for i, line in ipairs(lines) do
        local r = Row(i)
        local c = COLORS[line.state] or COLORS.LIVE
        r.label, r.tip = line.label, line.tip
        r.left:SetText(line.label)
        r.right:SetText(line.value)
        Try(r.left, "SetTextColor", c[1], c[2], c[3])
        Try(r.right, "SetTextColor", c[1], c[2], c[3])
        r:Show()
    end
    for i = #lines + 1, #win.rows do win.rows[i]:Hide() end
    win:SetHeight(TOP + #lines * ROW_H + PAD)
end

-- An error while drawing must not vanish (the live part calls this inside a pcall): it is told once in the chat.
local drawError = false
local function SafeRender(v)
    local ok, err = pcall(Render, v)
    if not ok and not drawError then
        drawError = true
        Say(Tr("Fenster: Fehler beim Zeichnen: ", "Window: error while drawing: ") .. tostring(err))
    end
end

local function Build()
    if win then return end
    if not (Have(CreateFrame) and UIParent) then error("no frame API") end
    local f = CreateFrame("Frame", nil, UIParent, BackdropTemplateMixin and "BackdropTemplate" or nil)
    win = f
    f.rows = {}
    width, widthSet = WIDTH, false
    f:SetHeight(TOP + PAD)
    ApplyPosition()                          -- also reads the saved width into `width`
    f:SetWidth(width)
    Try(f, "SetFrameStrata", "MEDIUM")
    Try(f, "SetClampedToScreen", true)
    Try(f, "SetMovable", true)
    Try(f, "EnableMouse", true)
    Try(f, "RegisterForDrag", "LeftButton")
    f:SetScript("OnDragStart", StartMove)
    f:SetScript("OnDragStop", StopMove)
    Try(f, "SetBackdrop", { bgFile = "Interface\\Tooltips\\UI-Tooltip-Background", edgeFile = "Interface\\Tooltips\\UI-Tooltip-Border",
                            edgeSize = 12, insets = { left = 3, right = 3, top = 3, bottom = 3 } })
    Try(f, "SetBackdropColor", 0, 0, 0, 0.8)
    Try(f, "SetBackdropBorderColor", 0.6, 0.6, 0.6, 1)
    -- while it is shown the live part reads; the saved "open" is written by Open and Close only (a /reload may hide frames by itself)
    f:SetScript("OnShow", function() Live.SetActive("window", true) SafeRender() end)
    f:SetScript("OnHide", function() Live.SetActive("window", false) end)
    f.title = f:CreateFontString(nil, "OVERLAY", "GameFontHighlight")        -- in the space above the rows, left of the close button
    f.title:SetPoint("TOPLEFT", f, "TOPLEFT", 10, -9)
    f.title:SetText(Live.WindowTitle())
    f.close = CreateFrame("Button", nil, f, "UIPanelCloseButton")
    f.close:SetPoint("TOPRIGHT", f, "TOPRIGHT", 2, 2)
    f.close:SetScript("OnClick", function() Live.CloseWindow() end)
    f.grip = BuildGrip(f)
    Live.onUpdate = function(v) if win and win:IsShown() then SafeRender(v) end end
    Live.window = f
end

-- Open and Close switch the reading on and off themselves (the first reading draws): they do not rely on OnShow and OnHide, which the game may not call when a
-- window is opened while the interface is still being built (a window restored at a login showed no rows).
function Live.OpenWindow()
    Build()
    win:Show()
    Live.SetActive("window", true)                              -- the first reading, which draws
    SaveWindow(true, true)
end

function Live.CloseWindow()
    if not win then return end
    win:Hide()
    Live.SetActive("window", false)
    SaveWindow(true, false)
end

function Live.ToggleWindow()
    local ok, err = pcall(function()
        if win and win:IsShown() then Live.CloseWindow() else Live.OpenWindow() end
    end)
    if not ok then                                              -- no window on this client: the chat text as before
        Say(Tr("Fenster nicht moeglich: ", "Window not possible: ") .. tostring(err))
        Live.PrintStatus()
    end
end

-- ---------------------------------------------------------------------------------------------------- restore after a login or /reload

local restored = false
if Have(CreateFrame) then
    local function Restore()
        local s = Settings()
        if not (s and type(s.window) == "table" and s.window.shown == true) then return end
        local ok, err = pcall(Live.OpenWindow)
        if not ok then Say(Tr("Fenster: Fehler beim Oeffnen: ", "Window: error while opening: ") .. tostring(err)) end
    end
    local frame = CreateFrame("Frame")
    frame:RegisterEvent("PLAYER_ENTERING_WORLD")
    frame:SetScript("OnEvent", function()
        if restored then return end                             -- later events are zone changes
        restored = true
        if type(C_Timer) == "table" and Have(C_Timer.After) then
            C_Timer.After(RESTORE_DELAY, Restore)               -- not in the middle of the login
        else
            Restore()
        end
    end)
end
