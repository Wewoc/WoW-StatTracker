# Changelog

## 0.1.9

- New: *2. Read data* says when scans may be missing. The addon keeps only the latest scan per character, so a scan made between two reads is gone for good; when two or more days lie between the previous scan in the database and the newest one in the file, the log says so. When a read brings nothing new it shows how old the newest scan in the file is. Reading one WoW account now also names the other accounts that have data (every account has its own file)
- New: before a copy of the database is made, it gets a quick integrity check. If it fails, the read stops before anything is changed, no copy is made and no old copy is deleted, so a damaged database can no longer replace your good copies. Restore one as described in the README
- Fixed: an error while downloading an update (an interrupted download, a damaged archive) is now always shown. Before, some errors ended the download silently and every later update check did nothing until the program was restarted
- Fixed: the update helper takes every path literally. An install folder with square brackets in its name (for example `D:\Games\WoW [Retail]\StatTracker`) made the update stop with a wrong message. A rollback that cannot remove the new files now says so instead of reporting a restore, and a leftover lock file of an earlier helper no longer blocks an update when its number now belongs to another program
- Fixed: the updater refuses a redirect to an address that is not https, not only a first address that is not
- Fixed: in the Excel export a name or value from the game file that starts with `=` stays text; it was stored as a formula
- Note: the fixes to the update helper and to the download only apply to updates that start from 0.1.9 or later, because the running version supplies them. Updating from 0.1.8 still uses the old ones
- Changed: the addon itself is unchanged, but its version follows the program version, so after updating from 0.1.8 the window asks once to run *1. Install / update addon*
- Docs: both READMEs say that the addon keeps only the latest scan per character and mention the integrity check
- Developer: the build checks the finished bundle (the data files in `_internal` and every module of `src/`) and stops if something is missing; new tests guard the data version of the addon, the asset names of the release workflow, the imports of the leaf modules and which module may write files

## 0.1.8

- New: a history page for every character with at least two scans. Pick up to ten statistics and see them as lines over your scans, as absolute values or as an index (first value = 100); gold is shown in gold and played time in hours, a scan without a number leaves a gap. The stats page has a new *History* block that links the pages
- Note: *2. Read data* writes the pages into `data/history/` (`data/history_<version>/` for the other game versions), only for characters with a new scan, a missing page, or after a program update. Everything in that folder can be made again from the database. The pages need no internet; the links on the stats page work while the folder lies next to it
- Note: if a history page cannot be written (for example plotly.js is missing), the import still completes and the log shows a warning
- Changed: the addon itself is unchanged, but its version follows the program version, so after updating from 0.1.7 the window asks once to run *1. Install / update addon*
- Docs: both READMEs and the landing page describe the history pages with a picture (invented demo data) and credit plotly.js (MIT)
- Developer tool: `tools/make_demo.py --snapshots N` makes a demo with N scans per character and the history pages, for the screenshots

## 0.1.7

- New: presets for the *Groups* block. A preset remembers the grouping, the figures shown and the added statistics under a name; choose one from the list to apply it, save the current setup under a name (an existing name is overwritten) or delete a preset. The characters and groups ticked are not part of a preset
- Note: presets are kept in the browser (local storage), not in the page and not in `data/`. They apply to all StatTracker pages opened in that browser, and a page you pass on does not carry them. Where the browser blocks local storage the row is hidden and the block works as before
- Changed: the addon itself is unchanged, but its version follows the program version, so after updating from 0.1.6 the window asks once to run *1. Install / update addon*

## 0.1.6

- New: the stats page shows the race next to class and level of each character, in the rates block and in the column header. The scan date moves to a line of its own in the column header
- New: a collapsible *Groups* block groups the characters ticked above by class, race, faction or realm and shows per group the number of characters, the average level, the total played time and the four rates per hour (sum of counters / sum of hours, "n of m characters" where one cannot be used). Any statistic with a number can be added as a column (sum, average or maximum; gold is shown in gold)
- Note: class and race are grouped by the language-independent name the addon records since 0.1.5. A character not scanned again since then is listed under "unknown", nothing is guessed from the stored, gender dependent text. Faction and realm work for every character
- Note: the Excel export is unchanged and has no groups
- Docs: the landing page and both READMEs describe the Groups block, the screenshots are redone

## 0.1.5

- New: with every scan the addon records the class (as a language-independent name) and the race of the character, and the database keeps both per scan (database schema 2). The stats page does not use them yet
- Note: scans taken before have no race and never get one afterwards, because a race can change. After the update run *1. Install / update addon* and scan each character once more (`/statscan`)
- Note: the first read after the update upgrades the database to schema 2 and leaves one copy named `pre-v2` in `data/backups/migration/`
- Changed: a `StatTracker.lua` with a newer data format than the program knows is refused before the database is opened (no copy, no change), with a message to update StatTracker
- Docs: both READMEs mention the recorded class and race

## 0.1.4

- New: before an import writes to an existing database, StatTracker copies it into `data/backups/`. `daily/` keeps one copy per day for the last 7 days; `migration/` keeps one copy before every database upgrade and is never deleted automatically. If a copy cannot be written, the import stops before it changes anything
- Note: a database that has no schema number yet (it was not read since 0.1.3) gets one copy in `migration/` at its first read, named `pre-v1`
- Changed: the addon itself is unchanged, but its version follows the program version, so after updating from 0.1.3 the window asks once to run *1. Install / update addon*
- Docs: both READMEs describe the backup folders and how to restore a copy

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
