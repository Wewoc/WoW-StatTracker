# Changelog

## 0.1.3

- New: the stats page shows rates per hour played (creatures killed, honorable kills, deaths, gold) for every character and as a total over all of them, in a collapsible block. If a number cannot be worked out, for example because of too little played time, the page says why instead of showing a value
- New: the stats page is titled "WoW-StatTracker" and has a footer with the version, a link to the project page, the copyright and the license
- New: the statistics database carries a schema version. The first read with this version stamps your existing database (a number in the file header, no data changes). A database from a newer program is refused untouched, by the import and by the Excel export, with a message to update
- Changed: the addon itself is unchanged, but its version follows the program version, so after updating from 0.1.2 the window asks once to run *1. Install / update addon*
- Docs: the landing page and both READMEs describe the rates; the screenshots are new and made from invented demo data (`tools/make_demo.py`)

## 0.1.2

- Fixed: the update dialog could open twice when the check at start and a manual check overlapped; the second dialog blocked the running update and *Update now* could start a second download. It now opens once
- Changed: the addon itself is unchanged, but its version follows the program version, so after updating from 0.1.1 the window asks once to run *1. Install / update addon*

## 0.1.1

- Fixed: the addon status now also checks the interface number. After a WoW patch the game shows the addon as out of date while the window still said "ok"; it now reports "interface number does not match the game", and *1. Install / update addon* sets the new number
- Changed: the addon itself is unchanged, but its version follows the program version, so after updating from 0.1.0 the window asks once to run *1. Install / update addon*

## 0.1.0

First repository release (continues the earlier 0.0.x packages).

- New: Windows release as `StatTracker.exe` (PyInstaller `--onedir`), no Python needed
- New: German/English interface, stats page and Excel export follow the chosen language
- New: enabled game versions are configurable (*Settings*); default is Retail only
- New: *Uninstall addon* button (optionally also the addon's SavedVariables; local data is never deleted)
- New: About information in the window (version, repository link, copyright, license)
- New: self-updater with SHA256 verification, backup and automatic rollback
- New: addon status in the window (installed / outdated), addon messages in German or English by game language
- Changed: the addon scan is spread over about 10 seconds in small slices instead of one burst (no game freeze); chat shows "Stat sync started" and "Stat sync done"
- Changed: the repository is `Wewoc/WoW-StatTracker`; the update check is active, and a repository without a release counts as "up to date"
- Docs: disclaimer ("as is", use at your own risk) in both READMEs, on the landing page and in the About window
- Docs: game version status is now stated plainly - Retail tested and works, BC Anniversary tested and does not work (the game provides no statistics), all others untested; WoW Forever is no longer mentioned
- Changed: on a game version without statistics the addon says so in chat ("This game version provides no statistics ...") instead of a raw Lua error
- New: the stats page has a *Select all / Deselect all* button for the characters
- Changed: all user data lives in the `data` folder next to the program
- Changed: author and copyright are Wewoc; license GPL-3.0-or-later
- Changed: `parser.py` is now `stat_parser.py`; `check_stats.py` moved to `tools/`
