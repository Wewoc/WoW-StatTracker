-- SPDX-License-Identifier: GPL-3.0-or-later
-- Copyright (C) 2026 Wewoc (github.com/wewoc)
-- StatTrackerOptions.lua (Retail and WoW Forever)
-- The page "StatTracker" in the game's Options -> Addons: the title with the version, a short explanation (with the commands that show and
-- hide or lock the window), the settings of the window as check boxes (locked, coloured, which rows are shown), the link to the project page
-- in a field to copy from, and below it what the desktop app is and what it is good for.
-- It keeps no saved data of its own: the check boxes read and write through Live.IsLocked / SetLocked, Live.RowShown / SetRowShown and
-- Live.IsColored / SetColored (StatTrackerWindow.lua). A check box is built from plain textures, not from a template of the client (those
-- differ between Retail and Forever); the statistics are named with Live.StatLabel when the page is shown, not before.
-- Everything is built inside pcall at ADDON_LOADED. A client without the settings API gets no page and nothing else changes; a step that
-- fails is told once in the chat (the window and /statlive do not depend on this page).

local ADDON, ns = ...
local Live = type(ns) == "table" and ns.Live
if type(Live) ~= "table" then return end

local URL = "https://wewoc.github.io/WoW-StatTracker/"      -- the landing page; tests/test_live_lua.py keeps it equal to app_info.SITE_URL
local Tr, Say = Live.Tr, Live.Say
local function Have(fn) return type(fn) == "function" end
local function Try(obj, method, ...)
    if obj and Have(obj[method]) then pcall(obj[method], obj, ...) end
end

-- ASCII only, like the other texts of the addon
local function Lines()
    return {
        Tr("StatTracker zeigt die Statistiken des aktuellen Charakters live in einem kleinen Fenster.",
           "StatTracker shows the statistics of the current character live in a small window."),
        Tr("Fenster ein-/ausblenden: /statlive (laesst sich auch als Makro auf eine Taste legen).",
           "Show or hide the window: /statlive (it can also be put in a macro on a key)."),
        Tr("Werte im Chat: /statlive text. Aenderungen mitlesen: /statlive watch.",
           "Values in the chat: /statlive text. Follow every change: /statlive watch."),
        Tr("Fenster sperren: /statlive lock, freigeben: /statlive unlock.",
           "Lock the window: /statlive lock, release it: /statlive unlock."),
        Tr("Die Breite des Fensters aenderst du an der Ecke unten rechts.",
           "Change the width of the window at its bottom right corner."),
    }
end

-- What the app is and what it is good for: the first line is a heading, the others are paragraphs (ASCII only)
local function AppLines()
    return {
        Tr("Die StatTracker-App:", "The StatTracker app:"),
        Tr("Die App liest die gespeicherten Daten dieses Addons ein und baut daraus eine Statistik-Seite: alle Charaktere nebeneinander, Raten pro Spielstunde, Gruppen (Klasse, Rasse, Realm), Top 5 und Verlaufsdiagramme.",
           "The app reads this addon's saved data and builds a statistics page from it: all characters side by side, rates per hour played, groups (class, race, realm), Top 5 and history charts."),
        Tr("Nutzen: Das Spiel zeigt nur den aktuellen Stand. Die App behaelt die Scans und zeigt, wie sich deine Charaktere ueber Wochen entwickeln und wie sie im Vergleich stehen. Alles bleibt auf deinem Rechner. Das Addon laeuft auch ohne die App.",
           "Benefit: the game only shows the current state. The app keeps the scans and shows how your characters develop over weeks and how they compare. Everything stays on your computer. The addon also works without the app."),
    }
end

-- ---------------------------------------------------------------------------------------------------- the settings of the window

local told = false
local function Problem(err)                  -- told once, the page goes on without that part
    if told then return end
    told = true
    Say(Tr("Optionenseite: Fehler: ", "Options page: error: ") .. tostring(err))
end

-- A check box from plain textures with its text beside it. get() says whether it is on; set(on) saves and returns true, or false when the
-- setting may not be written (a file of a newer addon): the box then goes back to what it was and the chat says so.
local function Checkbox(parent, text, get, set, tip)
    local cb = CreateFrame("CheckButton", nil, parent)
    cb:SetWidth(24)
    cb:SetHeight(24)
    Try(cb, "SetNormalTexture", "Interface\\Buttons\\UI-CheckBox-Up")
    Try(cb, "SetPushedTexture", "Interface\\Buttons\\UI-CheckBox-Down")
    Try(cb, "SetHighlightTexture", "Interface\\Buttons\\UI-CheckBox-Highlight", "ADD")
    Try(cb, "SetCheckedTexture", "Interface\\Buttons\\UI-CheckBox-Check")
    Try(cb, "SetDisabledCheckedTexture", "Interface\\Buttons\\UI-CheckBox-Check-Disabled")
    cb.caption = parent:CreateFontString(nil, "ARTWORK", "GameFontHighlight")
    cb.caption:SetPoint("LEFT", cb, "RIGHT", 2, 0)
    cb.caption:SetText(text)
    cb.get = get
    cb:SetScript("OnClick", function(self)
        local want = self:GetChecked() and true or false
        local ok, saved = pcall(set, want)
        if not (ok and saved) then
            self:SetChecked(not want)
            if ok then Say(Tr("Einstellungen nicht verfuegbar (Datei eines neueren Addons).", "Settings not available (file of a newer addon).")) end
            if not ok then Problem(saved) end
        end
    end)
    if tip then
        cb:SetScript("OnEnter", function(self)
            if type(GameTooltip) ~= "table" then return end
            pcall(function()
                GameTooltip:SetOwner(self, "ANCHOR_RIGHT")
                GameTooltip:AddLine(text, 1, 1, 1)
                GameTooltip:AddLine(tip, 0.7, 0.7, 0.7, true)
                GameTooltip:Show()
            end)
        end)
        cb:SetScript("OnLeave", function() if type(GameTooltip) == "table" then pcall(GameTooltip.Hide, GameTooltip) end end)
    end
    return cb
end

local function RefreshStates(panel)          -- every box shows what is saved
    for _, cb in ipairs(panel.boxes or {}) do cb:SetChecked(cb.get() and true or false) end
end

-- The check boxes of the window under `above`; returns the box the next part of the page hangs below (the last of the left column), or nil
-- when this client has no window part (then the page has no such block).
local function BuildSettings(panel, above)
    if not (Have(Live.SetLocked) and Have(Live.SetRowShown) and Have(Live.SetColored) and Have(Live.IsLocked)
            and Have(Live.IsColored) and Have(Live.RowShown) and type(Live.ROW_KEYS) == "table") then return nil end
    panel.boxes = {}
    local function Heading(text, anchor, gap)
        local h = panel:CreateFontString(nil, "ARTWORK", "GameFontNormal")
        h:SetPoint("TOPLEFT", anchor, "BOTTOMLEFT", 0, gap)
        h:SetText(text)
        return h
    end
    local function Place(cb, head, column, row)
        cb:SetPoint("TOPLEFT", head, "BOTTOMLEFT", column * 290, -4 - row * 24)
        panel.boxes[#panel.boxes + 1] = cb
        return cb
    end
    local head = Heading(Tr("Fenster", "Window"), above, -18)
    Place(Checkbox(panel, Tr("Fenster sperren (Position)", "Lock the window (position)"), Live.IsLocked, Live.SetLocked,
        Tr("Haelt das Fenster an seinem Platz, damit du es nicht aus Versehen verschiebst. Die Breite aenderst du weiter an der Ecke unten rechts.",
           "Keeps the window where it is, so you do not drag it by mistake. You still change the width at the bottom right corner.")), head, 0, 0)
    panel.colorBox = Place(Checkbox(panel, Tr("Zahlen einfaerben (gruen/rot)", "Colour the numbers (green/red)"), Live.IsColored, Live.SetColored,
        Tr("Gruen oder rot, wenn deine Rate in dieser Sitzung (Aenderung pro Stunde) mindestens 10 % ueber oder unter deinem Durchschnitt liegt. Der Durchschnitt kommt aus dem letzten Scan, verglichen wird ab 10 Minuten Sitzung; bei den Toden ist es umgekehrt. Dazu ^ (ueber) oder v (unter dem Durchschnitt) hinter dem Wert.",
           "Green or red when your rate in this session (change per hour) is at least 10 % above or below your average. The average comes from the last scan, and the comparison starts after 10 minutes of session; for deaths it is the other way round. Also ^ (above) or v (below the average) behind the value.")), head, 1, 0)
    head = Heading(Tr("Zeilen im Fenster", "Rows in the window"), panel.boxes[1], -14)
    -- the statistics first (their names come when the page is shown), then the other four; five rows in the left column, four in the right
    local other = {
        gold = Tr("Session-Gold", "Session gold"), played = Tr("Spielzeit", "Played time"), rates = Tr("Raten pro Stunde", "Rates per hour"),
        footer = Tr("Fusszeile (Aktualisiert, Letzter Scan)", "Footer (updated, last scan)"),
    }
    panel.statBoxes = {}
    local left, right, last = 0, 0, nil
    for _, key in ipairs(Live.ROW_KEYS) do
        local label = other[key]
        if not label then label = Tr("Statistik ", "Statistic ") .. key end
        local cb = Checkbox(panel, label, function() return Live.RowShown(key) end, function(on) return Live.SetRowShown(key, on) end)
        if other[key] then
            Place(cb, head, 1, right)
            right = right + 1
        else
            last = Place(cb, head, 0, left)
            left = left + 1
            panel.statBoxes[key] = cb
        end
    end
    RefreshStates(panel)                     -- right from the start, not only when the page is shown
    return last
end

-- The boxes show what is saved (a command in the chat may have changed it) and the statistics their names from the game.
local function RefreshSettings(panel)
    if not panel.boxes then return end
    RefreshStates(panel)
    if Have(Live.StatLabel) then
        for key, cb in pairs(panel.statBoxes) do
            local name = Live.StatLabel(tonumber(key))
            if type(name) == "string" and name ~= "" then cb.caption:SetText(name) end
        end
    end
end

local function Build()
    if type(Settings) ~= "table" or not Have(Settings.RegisterCanvasLayoutCategory) or not Have(Settings.RegisterAddOnCategory) then return end
    if not (Have(CreateFrame) and UIParent) then return end
    local panel = CreateFrame("Frame", nil, UIParent)
    panel.name = "StatTracker"
    panel.rows = {}

    local title = panel:CreateFontString(nil, "ARTWORK", "GameFontNormalLarge")
    title:SetPoint("TOPLEFT", panel, "TOPLEFT", 16, -16)
    title:SetText(Have(Live.WindowTitle) and Live.WindowTitle() or "StatTracker")
    panel.title = title

    local previous = title
    for i, text in ipairs(Lines()) do
        local line = panel:CreateFontString(nil, "ARTWORK", "GameFontHighlight")
        line:SetPoint("TOPLEFT", previous, "BOTTOMLEFT", 0, i == 1 and -14 or -6)
        line:SetPoint("RIGHT", panel, "RIGHT", -16, 0)
        Try(line, "SetJustifyH", "LEFT")
        line:SetText(text)
        panel.rows[#panel.rows + 1] = line
        previous = line
    end

    local ok, last = pcall(BuildSettings, panel, previous)       -- a failure here costs only this block
    if not ok then Problem(last) elseif last then previous = last end
    panel:SetScript("OnShow", function(self)
        local shown, err = pcall(RefreshSettings, self)
        if not shown then Problem(err) end
    end)

    local label = panel:CreateFontString(nil, "ARTWORK", "GameFontHighlight")
    label:SetPoint("TOPLEFT", previous, "BOTTOMLEFT", 0, -22)
    label:SetText(Tr("Projektseite (anklicken, Strg+C zum Kopieren):", "Project page (click, Ctrl+C to copy):"))
    panel.linkLabel = label

    local field = CreateFrame("EditBox", nil, panel, "InputBoxTemplate")
    field:SetPoint("TOPLEFT", label, "BOTTOMLEFT", 6, -8)
    field:SetWidth(360)
    field:SetHeight(22)
    Try(field, "SetAutoFocus", false)
    field:SetText(URL)
    Try(field, "SetCursorPosition", 0)
    field:SetScript("OnEditFocusGained", function(self) Try(self, "HighlightText") end)
    field:SetScript("OnTextChanged", function(self, user)         -- a field to copy from: whatever is typed into it is put back
        if user and self:GetText() ~= URL then
            self:SetText(URL)
            Try(self, "HighlightText")
        end
    end)
    field:SetScript("OnEscapePressed", function(self) Try(self, "ClearFocus") end)
    panel.link = field

    panel.appRows = {}
    local above = field
    for i, text in ipairs(AppLines()) do
        local line = panel:CreateFontString(nil, "ARTWORK", i == 1 and "GameFontNormal" or "GameFontHighlight")
        if i == 1 then line:SetPoint("TOPLEFT", above, "BOTTOMLEFT", -6, -26)
        else line:SetPoint("TOPLEFT", above, "BOTTOMLEFT", 0, -6) end
        line:SetPoint("RIGHT", panel, "RIGHT", -16, 0)
        Try(line, "SetJustifyH", "LEFT")
        line:SetText(text)
        panel.appRows[#panel.appRows + 1] = line
        above = line
    end

    panel.OnCommit, panel.OnDefault, panel.OnRefresh = function() end, function() end, function() end      -- the settings window may call them
    local category = Settings.RegisterCanvasLayoutCategory(panel, panel.name)
    Settings.RegisterAddOnCategory(category)
    Live.optionsPanel, Live.optionsCategory = panel, category
end

local frame = CreateFrame("Frame")
frame:RegisterEvent("ADDON_LOADED")
frame:SetScript("OnEvent", function(self, event, name)
    if name ~= ADDON then return end
    self:UnregisterEvent("ADDON_LOADED")
    local ok, err = pcall(Build)
    if not ok then Say(Tr("Optionenseite: Fehler: ", "Options page: error: ") .. tostring(err)) end
end)
