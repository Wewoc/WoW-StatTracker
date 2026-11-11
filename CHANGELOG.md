# Changelog

## 0.2.3

- New: the **Page** tab has one page for every enabled game version, made automatically when the program starts (from the database, without a read; a version without a database waits for its first read). A game version chooser (*Game version*) sits at the top of the *Page*, *Top 5* and *Characters* tabs; it is **one** choice for the three tabs, so changing it in one tab changes the others. The pages keep their state while another tab is in front
- Changed: **Read data + open** and **Export Excel** now work on **all enabled game versions** at once: one page (and one sheet in the Excel file) per version. There is **one account for all game versions** (the choice in *Game*; a version without that account or without a data file is skipped with a log line, a dialog appears only when nothing could be read). The buttons *2. Read data* and *3. Open stats page* and the row *Game version* in the *Game* group are gone
- Changed: the game version list of the *Settings* tab is now the group **Addon**: a *Game version* box with *Install / update addon* and *Uninstall addon*. It controls the addon only. The status bar shows the data of every game version read and the addon state of the version in the box
- Changed: the **Top 5 are set per game version** (`top5` in `data/config.json` is now `{game version: [tiles]}`). The tiles saved before belong to Retail (their statistic ids come from Retail data) and are moved there when the settings are loaded; WoW Forever starts with none. Unsaved changes in the rows are dropped when you change the game version in the tab (the tab says so)
- Changed: check boxes of **untested game versions** are greyed out in the options (only Retail and WoW Forever can be enabled; one that is enabled already stays clickable, so it can be switched off, and is never removed silently)
- Changed: characters are shown as **First name Surname / Realm** everywhere (character selection, table head, rates, reputation, history links and pages, tiles, the lists of the *Characters* tab, the Excel sheets): `Catless Everbeen / CAMWOW EU4 Realm 3 PvE` instead of the whole key `Catless-CAMWOW EU4 Realm 3 PvE`. The key itself (`Name-Realm`) is unchanged in the database, the blacklist, the rules and the file names of the history pages, so nothing breaks and no history is split. Without a surname (older scans, Retail) it reads `Name / Realm`
- Changed: **data contract 5 and database schema 4**: the addon writes the optional field `surname` into every scan (the second return value of `UnitName("player")`; on WoW Forever it carries the surname) and the database has the new column `scans.surname` (schema 4, a copy of the database is made first, as for every migration). The newest scan decides what is shown; older scans keep it empty and are never filled in afterwards. A file of contract 4 stays readable
- Note: **update the addon** (*Install / update addon*, then scan again in game and `/reload` or log out) to get the surname; until then the name is shown without it. The surname is seen in game on WoW Forever (a character of low level); on Retail characters have no surname, so the field stays empty and the name reads `Name / Realm`
- Note: tried by hand (test build and built program, Retail and WoW Forever): the pages per game version, the version choosers, reading, the surname in the character selection and in the *Characters* tab, the status bar with two versions at 920 px width, memory and load time with two pages, the start with many history pages, the Excel file opened in Excel (one sheet per version), the Top 5 tab and tiles (also with many characters), the stats pages and the snapshot in Edge, the colour schemes and the *Characters* tab at 920 x 640. Not tried: the Excel file with rules for *Excel*, deleting characters from a real database, the smallest window size, the *Save* button of the diagrams, the rollback after a failed update
- Docs: both READMEs and the landing page describe the pages per game version, the *Addon* group and the Top 5 per game version; the pictures of the window, the stats page and the Top 5 tab are made again (the *Character* picture is unchanged)
- Developer: `src/rules/char_names.py` (the one place that knows how a character is shown: `split_key`, `display(key, surname)`); `main_window.PageTab`, `VersionPicker` and the shared choice `MainWindow._version`; `actions.import_all`, `actions.rebuild_pages`, `actions.status_parts(root, variants, account, variant)`; `wow_install.list_accounts_of`, `TESTED_VARIANTS` and `is_tested`; `config.clean_top5_by_variant`; `importer.DATA_VERSION` 5 and `db_schema.SCHEMA_VERSION` 4 (`SCAN_COLUMNS_V4`, `_migrate_3_to_4`); the field `label` in the page payload; `tests/test_docs_consistency.py` keeps the layout list of `docs/DEVELOPMENT.md`, the CHANGELOG head and the READMEs in step

## 0.2.2

- New: the **Characters** tab, with a block for every enabled game version (choose the version at the top; a version without data shows a note). It has two blocks: *Ignore* and *Delete*
- New: **Ignore** leaves characters out of the stats page, the history pages and the Excel file, and loses nothing: the database and the addon keep every scan, and the rules are applied again each time an output is made. In a form you pick a type (class, race, faction, realm, one character, or *level under* a number), the value from the data ("unknown" is a value too) and the targets (*Page*, which includes the history pages, and/or *Excel*), then add the rule to the list. The list shows every rule with its targets and how many characters it hits; a rule for something the data no longer has shows with 0. Several rules work together: a character is left out as soon as one of them hits it. For a level the newest scan counts, so a character that reaches the level appears with its whole history. A counter says how many characters are left out of the page and of the Excel file. Changes are a draft ("Changed, not applied yet") until *Apply*, which saves the list in the settings (`char_rules` in `data/config.json`, one list per game version) and writes the page and the history pages of that game version again; the pages of the other game versions follow at the next read, the Excel file at the next export. The history page of a character that is left out is deleted and made again when the rule goes
- New: **Delete** removes a character from the database of a game version for good: pick it, add it to the delete list, *Apply*. A question names the characters ("No" is preselected). With *Yes* the program first copies the database into `data/backups/delete/` (never deleted automatically), then deletes all scans, equipment and reputation of those characters in one transaction (all or nothing), removes their history pages and writes the page again. If the copy cannot be written, or the database is damaged or newer than the program, nothing is deleted
- New: the **blacklist** (`char_blacklist` in `data/config.json`, one list per game version) lists the deleted characters, and *Read data* leaves them out (the log names them). The addon keeps a character in its file even after you delete it in game, so without the blacklist the next read would bring it back. The keys go on the blacklist before the deleting starts and come off again if nothing was deleted; if the settings cannot be saved, nothing is deleted. An entry can be taken off the blacklist in the tab (it is saved at once; the next read takes the character in again as far as the file still holds it); an entry of a character you deleted in game may simply stay
- Changed: the Excel export leaves out the characters the rules name for *Excel* (a sheet whose characters are all left out is skipped, the log says how many were left out); the choice lists of the *Top 5* tab no longer offer a character that is left out of the page. The command line `python export_xlsx.py` knows no settings and exports everything
- Note: *Ignore* never changes the database. *Delete* does, and only a copy from `backups/delete/` brings a character back; restore it as described in the README. The copies are about the size of the database and are never deleted automatically: delete them by hand when you no longer need them
- Note: the addon itself is unchanged, but its version follows the program version, so after updating the window asks once to run *1. Install / update addon*
- Note: the automated tests cover the rules, the pages, the Excel file, the deleting and the window without a screen (more than 1,300 tests, with the addon tests); the look of the new tab was checked by hand in a test build. Deleting characters from a real database, the Excel file opened in Excel and the history pages written with the real plotly.js were only tested with test data
- Docs: both READMEs and the landing page describe the new tab
- Developer: `src/rules/char_rules.py` (the rules, pure calculation: who a rule names, for which target, the list changes); `importer.delete_chars` and `importer.import_data(skip=...)`; `db_backup.delete_backup`; `stat_history.remove_page` and `write_pages(hidden=...)`; `page_payload.build_payload(rules=...)` and `hidden_keys`; `export_xlsx.export(hidden=...)`; `actions.delete_chars`; the arguments `--hide` and `--skip` of the import (the parser reads no settings); the config keys `char_rules` and `char_blacklist`

## 0.2.1

- Changed: the note about game versions in the *Settings* tab now stands above the check boxes, in the accent colour instead of the dimmed hint colour, and names what is tested: Retail and WoW Forever. It says that on Forever not all statistics are unlocked yet (that depends on the character level), that all other game versions are untested, and that BC Anniversary provides no statistics. The old wording "Default: Retail only" is gone; the default is unchanged
- Docs: both READMEs and the landing page now list WoW Forever as tested and working, next to Retail
- Note: the addon itself is unchanged, but its version follows the program version, so after updating the window asks once to run *1. Install / update addon*. Tried with Retail and with WoW Forever (a character of low level; some statistics did not appear yet). The look of the note in the window was not checked by hand

## 0.2.0

- New: a new program window. It is made with PyQt6 instead of Tk and has three tabs: *Settings* (game folder, game version, account, options, the buttons and the log), *Page* (the stats page, shown inside the window: no browser has to be set up) and *Top 5*. The window and the stats page follow one of six colour schemes (*Design* in the *Settings* tab; the change applies after a restart)
- New: **Top 5**. Up to five tiles stand at the top of the stats page; each shows one value from the newest scan of your characters: a statistic you pick, combined as a sum, an average or a maximum over all characters, over one class, race, faction or realm, or for one character. A tile says whom it is about and how many characters it is made of when some had no number; where there is none it says so, nothing is made up (gold is shown in gold, played time in hours). They are set in the *Top 5* tab: type a part of the name of the statistic and pick it from the list, then *Save and write the page again*; the page of the chosen game version is written again at once
- New: *Open in browser* opens a **snapshot** of what the window shows now (the ticked characters, filters, sorting, grouping, added statistics) as the file `data/stats_snapshot.html`, written again at every click. In the browser its controls are locked, because the page there has no connection to the program
- New: the search box of the main table suggests statistics while you type (name and category, at most twelve, with the number of matches) instead of building the table again at every key, which made the window freeze for a moment. The table follows when you pick a suggestion or press Enter
- Changed: the blocks of the stats page (rates, groups, history links, character selection, reputation, filter row, counter, table, footer, and the new tiles) are now written by the program instead of by a script in the page; the page script only sends what you do and puts the answer in. The page looks and works as before; the numbers, the sort order of the names and the number format were compared with the old page on real data, cell by cell
- Changed: the presets of the *Groups* block are kept in the settings of the program (`data/config.json`) instead of in the browser. **The presets saved earlier in Edge or in the browser of the old window are not carried over**; save them again
- Changed: the download is larger: the release ZIP is about 160 MB instead of about 16 MB, because the program now carries Qt and its own browser engine (Chromium, through Qt WebEngine) to show the page. Updates download the whole ZIP; the `data` folder is still never touched. A new folder `data/webview` appears (what the engine keeps; nothing you need)
- Changed: the *Settings ...* dialog is now the *Settings* tab; the database and the Excel export are unchanged
- Changed: the addon itself is unchanged, but its version follows the program version, so after updating the window asks once to run *1. Install / update addon*
- Note: the licenses of the Qt stack (PyQt6 under the GPL v3, Qt 6 under the LGPL v3, Qt WebEngine on Chromium) and where the source code of Qt can be found are in `THIRD_PARTY_LICENSES.md` and `LICENSE-LGPL-3.0.txt` in the `info` folder of the release; the notice also names Python, PyInstaller and openpyxl
- Note: with the update check switched off, the program and its browser engine opened no network connection in a test run of 75 seconds (watched in the process table every 0.4 s, and no new name appeared in the DNS cache of Windows); this shows no connection, it does not prove there can never be one
- Note: tried with Retail on Windows, and the update from 0.1.12 to this version with the release download (it works; the rollback after a failed update is only tested by the automated tests). Not tried: the snapshot in Edge or Chrome
- Docs: both READMEs and the landing page describe the window, the Top 5 and the snapshot; the pictures of the landing page show the new window and the tiles
- Developer: the source is organized in folders (`core`, `game`, `store`, `rules`, `pages` with `pages/blocks`, `export`, `app`) with the direction of imports checked by a test; the parser is split into `lua_reader`, `stat_values`, `db_schema`, `importer`, `page_payload` and `outputs`; the stats page is a template with numbered places and one table (`pages/blocks/layout.py`) that says which block fills which place; the rules of the blocks are in `rules/` (pure calculation, tested); the window talks to the page through `app/page_bridge.py` (QWebChannel). The window tests run without a screen (`QT_QPA_PLATFORM=offscreen`); the suite has more than 1,100 tests

## 0.1.12

- New: the *Character* block of a history page shows the pictures of the items instead of the symbols of the slots, framed in the colour of the item quality. *2. Read data* reads them by itself from the game files of your WoW installation (read-only, the game may be running): the pictures of the items your characters wore, only those that are still missing. They are kept as small PNG files in `data/icons`, and the pages whose characters wore them are made again, even without a new scan. Where a picture is missing the symbol of the slot stays. The first read after the update takes a few seconds longer (in a test, about 130 pictures and opening the game files took 4 seconds), later ones hardly any
- New: the setting *Read item icons from the game files when importing* (on by default). With it off nothing is read from the game, and the pictures read earlier stay visible
- Note: the pictures belong to Blizzard Entertainment. They are made on your computer from your own installation, they are not part of StatTracker, and a history page that you pass on contains the pictures it shows; a credit stands under the block. The program calls only the functions of the game-file library for a local installation and makes no network request for the pictures
- Note: tried with Retail and the current game build, with the game running and with it closed. Reading after a patch and for other game versions is untested. A picture that the game files do not have, or of a kind the program does not decode, is not tried again before the next game build and shows the symbol of the slot
- Changed: the release now carries `CascLib.dll` (CascLib by Ladislav Zezula, MIT license) and the file `THIRD_PARTY_LICENSES.md` with its license text in the `info` folder; the ZIP is a few hundred KB larger
- Changed: the addon itself is unchanged, but its version follows the program version, so after updating the window asks once to run *1. Install / update addon*
- Docs: both READMEs and the landing page describe the item pictures and where they come from (a new entry in the FAQ); the READMEs name CascLib next to plotly.js
- Developer: the build makes `CascLib.dll` from a fixed commit of CascLib (`compiler/casclib_build.py`, `src/casclib_asset.py`; CI and the release build run it before the tests, `--require-casclib` makes a missing DLL an error, a machine without the build tools builds without it and reads no pictures); `blp_decode.py` turns the BLP pictures of the game into PNG with the standard library only; `wow_icons.py` reads and stores them; `stat_parser` takes `--icons-dir`, `--game-dir` and `--product`; the demo (`tools/make_demo.py`) makes invented placeholder pictures

## 0.1.11

- New: every history page has a collapsible *Character* block above the statistics: the equipment of one scan, arranged like the character screen of the game. Each slot shows the item in its quality colour, its item level, upgrade track, enchantment, its stats and a note on an empty gem socket; the head line names the specialization and the average item level, and below the slots stands the sum of the secondary stats of the equipped items. Pick any scan that has equipment data and compare it with the previous one: slots whose item, item level, enchantment, upgrade or gems changed get a gold edge. The shirt and the tabard are left out, and the symbols are drawn by the page: the item pictures of the game are not shown
- New: two more lines on the history page, the equipped and the overall item level of every scan. The overall one takes the best piece for each slot among everything the character carries, so it is higher when a better piece waits in the bags; a note under the chart says so
- Note: only scans taken with the addon of 0.1.10 or later have equipment and item level. Older scans leave a gap in the lines and have no Character block; nothing is filled in afterwards
- Note: the names of the slots, stats and upgrade tracks are the game's own words in German and English, compared with the client texts of the game, not with a running client. An empty gem socket is recognized from the gem ids only; the stats of inserted gems are not in the stored data and are not part of the sum
- Note: the first read after the update makes every history page again, so the new block appears without a new scan
- Changed: the addon itself is unchanged, but its version follows the program version, so after updating the window asks once to run *1. Install / update addon*
- Docs: both READMEs and the landing page describe the Character block; all pictures of the landing page are made again and a new one shows the block
- Developer: the page data of a history page carries the equipment of every scan (`gear`) and the names of slots, stats and tracks (`names`); the demo data (`tools/make_demo.py`) has invented equipment that changes over the scans and writes `history/shot-character.html` for the new picture; tests for the equipment in the page data, the names, the slots shown and the demo equipment

## 0.1.10

- New: a collapsible *Reputation* block on the stats page shows the reputation of the ticked characters: every faction in the order of the game, grouped by category, with the level and a bar to the next one. Friendships and renown are shown with their own levels, paragon progress and a waiting reward are marked. Account-wide reputation appears once per faction. A character whose last scan does not contain reputation yet (scanned with an older addon) is listed under the block as without reputation data; it needs one new scan
- New: the addon now keeps the last five scans of each character instead of only the latest one. *2. Read data* reads all of them, so a scan made between two reads is no longer lost as long as no more than five scans lie between them. The note about missing scans now compares with the oldest scan in the file
- New: each scan also records the character's specialization, its average item level, the equipped items (name, item level, stats, enchantment, upgrade level, sockets, gem ids) and the reputation list. They are stored in the database; only the reputation is shown so far
- Changed: on the stats page the character selection now sits directly above the parts it controls (Reputation and the statistics table); Rates, Groups and History stay above it
- Note: the database is updated to a new layout (schema 3) on the first read; a permanent copy of it is made first (`data/backups/migration/`). Older scans have no gear or reputation, nothing is filled in afterwards
- Note: the data file of the addon grows with the new parts: 1.2 MB with three characters scanned (before: 1.0 MB for 19 characters); about 6 MB with 19 characters is calculated, not measured in the game
- Note: gem sockets are recorded as gem ids (0 = empty), without name or values
- Changed: the addon changed, so its version follows the program version: after updating the window asks once to run *1. Install / update addon*
- Docs: both READMEs describe the last five scans and the Reputation block; the pictures of the landing page show the new order of the stats page
- Developer: tests for the ring of scans, the gear and reputation reading (with a faked game interface), the reading of `history`, schema 3, the gap note, the reputation in the page data, the order of the blocks and the version `0.1.10` in the update check; the demo data (`tools/make_demo.py`) carries an invented reputation

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
