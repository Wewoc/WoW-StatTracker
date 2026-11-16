-- SPDX-License-Identifier: GPL-3.0-or-later
-- Copyright (C) 2026 Wewoc (github.com/wewoc)
-- StatTrackerOptions.lua (Retail and WoW Forever)
-- The page "StatTracker" in the game's Options -> Addons: the title with the version, a short explanation (with the commands that show and
-- hide the window), the link to the project page in a field to copy from, and below it what the desktop app is and what it is good for.
-- It only shows text; it reads and writes no saved data.
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
