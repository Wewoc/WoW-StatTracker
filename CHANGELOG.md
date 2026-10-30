# Changelog

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
