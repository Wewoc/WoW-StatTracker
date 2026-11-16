# Development

Notes for running, testing and building StatTracker from source. For using the
program see the [README](../README.md) ([Deutsch](../README.de.md)).

Python 3.10+ (developed on 3.13). The window uses PyQt6 with the embedded browser (PyQt6-WebEngine, Chromium); the tests
need no screen (pytest-qt, `QT_QPA_PLATFORM=offscreen` is set in `tests/conftest.py`). Windows is the target of the
packaged release; the logic modules are platform-neutral, the self-updater is
Windows-only (PowerShell helper).

## Run from source

```bash
pip install -r requirements.txt
python src/start.py
```

On Windows you can also double-click `src/bat/start.bat`.

All data goes to `data/` in the repository root (git-ignored): `config.json`,
`wow_stats*.db`, `stats*.html`, `history/` (history pages per character, `history_<version>/` for other
game versions, made by the import with `--history-dir`), `stattracker.xlsx`, `crash.log`, `backups/` (copies of the
database: `daily/` rotates, `migration/` and `delete/` stay).

plotly.js (for the history pages) is not part of the repository. `python compiler/plotly_fetch.py`
downloads the pinned version from `cdn.plot.ly` into `src/plotly.min.js` (git-ignored) and checks
its SHA-256 (`src/pages/plotly_asset.py` holds version and hash; change them together). Run it once
before using the history pages from source. The program itself never downloads it.

`CascLib.dll` (reads the item icons from a local WoW installation) is not part of the repository either.
`python compiler/casclib_build.py` fetches CascLib at the pinned commit with git, builds it with CMake and the
Visual Studio Build Tools (C++ workload) and puts the checked x64 DLL into `src/CascLib.dll` (git-ignored).
`src/game/casclib_asset.py` holds version and commit (change them together). CI and the release build run the script
before the tests; `compiler/build.py` runs it too, and on a machine that cannot build the DLL it goes on without it
(the program then reads no item icons) unless `--require-casclib` is given, which CI and the release build do.
Without the build tools, copy a CascLib.dll of the pinned version to `src/CascLib.dll`. The program neither builds
nor downloads it.

## Tests

```bash
pip install -r requirements-dev.txt
python compiler/plotly_fetch.py       # optional: lets the test for the real Plotly file run
python compiler/casclib_build.py      # optional: lets the test with the real CascLib DLL run (needs the build tools)
python -m pytest -q
```

The tests never touch a real instance: they point `paths.base_dir` at a temporary
folder. `tests/test_updater_helper.py` runs the real PowerShell helper against
temporary folders (skipped without PowerShell).

## Build the release

```bash
python compiler/build.py              # exe + release ZIP + .sha256
python compiler/build.py --no-zip
python compiler/build.py --no-venv    # current Python instead of .venv-build/ (CI)
```

The build first runs `compiler/plotly_fetch.py` itself (a missing `src/plotly.min.js` is downloaded
and hash-checked, a mismatch aborts), so it needs network access once.

Output: `dist/StatTracker/` (disposable), `dist/StatTracker.zip` and
`dist/StatTracker.zip.sha256`. Upload **both** files to the GitHub release - the
updater refuses a release without the checksum file. `compiler/build_manifest.py`
and `src/core/app_info.py` are the single sources for names and release contents.

Release checklist:

1. Set `APP_VERSION` in `src/core/app_info.py` for a new app version. The addon has its own number: `## Version:` in `addon/StatTracker/StatTracker.toc`, raised whenever the addon changes (the two are independent; compatibility is carried by `StatTrackerDB.version`, not by the numbers, and the program offers a newer bundled addon through *Install / update addon*). Update `CHANGELOG.md`: addon changes appear in the chapter of the app release that ships them, as a line "Addon x.y.z: ...".
2. Create an annotated tag `vX.Y.Z` (`git tag -a vX.Y.Z -F <message file>`: first line = release title, the rest = release notes) and push it - `.github/workflows/release.yml` builds, attaches the files and takes title and notes from the tag message. A lightweight tag still releases, but without title and notes.
3. The pipeline (`.github/workflows/`): `ci.yml` runs the tests on every push to `main` and can only read the repository. `release.yml` has no rights by default and two jobs: **build** (read-only: tests, the tag must equal `APP_VERSION`, the build, the checksum) and **publish** (the only job with write access: it checks the checksum of the downloaded ZIP again and makes the release). Every action is pinned to a full commit (the version stands in a comment), and both workflows install exactly `requirements-lock.txt` (every package pinned with `==`, including what the packages pull in). To update an action: take the commit of a release that is at least two weeks old from the action's repository (`git ls-remote --tags <repo>`; an annotated tag needs the `^{}` line), check that it runs on a current Node, and change commit and comment together. To update the packages: upgrade them in `.venv-build`, run the tests and a build, then `pip freeze > requirements-lock.txt` and put the header comment back. `tests/test_workflows.py` keeps the pins, the rights and the lock file. The real run is only seen on GitHub (a test run in a private test repository comes before a release that changes the workflows).
4. The addon on CurseForge (project id 1810842, in the `.toc` as `X-Curse-Project-ID`) is released on its own, independent of the app: raise `## Version:` in the `.toc`, add the lines "- Addon x.y.z: ..." to the chapter of `CHANGELOG.md` that carries them (they become the changelog of the file page), then push an annotated tag `addon-vX.Y.Z` (the version of the `.toc`). `.github/workflows/addon-release.yml` runs the addon tests, stages the addon (`compiler/addon_package.py`: the interface line of the staged `.toc` also lists `16001`, the number of WoW Forever; the `.toc` in the repository stays as it is) and lets the BigWigs packager upload it; only that step has the token (the secret `CURSEFORGE`). Started by hand from the Actions tab, the workflow only makes the package (a dry run, nothing is uploaded) and keeps it as an artifact. The interface number of the `.toc` needs a look with every game patch.
5. The repository is `Wewoc/WoW-StatTracker` (`REPO_OWNER`/`REPO_NAME` in `src/core/app_info.py`, `REPO_CONFIRMED = True`). If it is ever renamed or forked, change those, the GitHub links in `docs/index.html`, the READMEs and `X-Website` in the `.toc`; `SITE_URL` (the landing page shown in the footer of the stats page) follows from the same two values. While `REPO_CONFIRMED` is False the update check sends no request. A repository without a release counts as "up to date" (the GitHub API answers 404).

## Landing page (GitHub Pages)

`docs/index.html` (German/English, screenshots in `docs/images/`) is a static page. After the
repository exists: *Settings -> Pages -> Deploy from a branch -> `main` and `/docs`*. The
screenshots show invented demo data only; `tests/test_docs_site.py` checks that every image
exists in both languages and that nothing is loaded from a third party. If you change the
repository owner/name, update the GitHub links in `docs/index.html` as well.

To redo the screenshots after the stats page changed: `python tools/make_demo.py --out <folder outside the repository>`
writes invented demo data per language and four variants of the page (`shot-stats.html`,
`shot-rates.html`, `shot-compare.html`, `shot-groups.html`). Take one picture of each with Edge or
Chrome in headless mode, 1280 x 760 at scale 1.5 (= 1920 x 1140; the groups picture 1280 x 800 =
1920 x 1200), for example
`msedge --headless=new --hide-scrollbars --force-device-scale-factor=1.5 --window-size=1280,760 --screenshot=stats-en.png file:///<folder>/en/shot-stats.html`,
and copy them to `docs/images/` as `stats-`, `rates-`, `compare-` and `groups-` plus `en`/`de`.
The four pages carry the five invented Top 5 tiles of the demo (`make_demo.DEMO_TOP5`); the variants are made by giving the actions of the blocks to a `View` and writing the page from it,
not by a script in the page. Run the demo with `--snapshots 12` for these four pictures as well, so the *History* block shows (the numbers do not change: the last scan is the single scan).

The pictures of the program window, `app-*.png` (Settings tab) and `top5-*.png` (Top 5 tab, cut below the button), are made from the same demo output by
`python tools/make_window_shots.py --demo <demo folder> --out <folder>`: it starts the real window without a screen in a temporary instance folder (the Qt
`offscreen` platform, system fonts, 1.5 times the size) and replaces the game folder, the log and the status line by invented texts, so nothing of the machine shows.
Copy them to `docs/images/`; `tests/test_docs_site.py` checks that the sizes written into `docs/index.html` are the real ones.

The picture of the in-game live window, `live-en.png` / `live-de.png`, is an **illustration**, not a screenshot (the window lives in the game, which cannot run here):
`.venv-build/Scripts/python.exe tools/make_live_shot.py --out <folder>` runs the real addon files (`StatTrackerLive.lua`, `StatTrackerWindow.lua`) in an embedded Lua against
the faked game API of `tests/test_live_lua.py` with invented values of the demo character (a login, a played-time answer, 47 minutes of play), takes the rows from `Live.WindowLines`
and paints them with Qt on a plain background (it needs `lupa` and PyQt6, so use the build venv). The words and numbers are the addon's, the look (frame, font, corner) is not the game's.
The captions and alt texts must say "illustration". Copy the pictures to `docs/images/`.

For the history page add `--snapshots 12`: every character then gets 12 scans three days apart (the
last one is exactly the single scan of the default run, so the pictures above stay the same), the
import writes `<folder>/<lang>/history/` and the stats page gets its *History* block. The picture of
the history page is `history/shot-history.html` (one character, four statistics as an index), 1280 x 840
at scale 1.5, saved as `history-en.png` / `history-de.png`. The same page with the *Character* block
opened is `history/shot-character.html`, saved as `character-en.png` / `character-de.png` (1280 x 1100 at
scale 1.5 = 1920 x 1650). It needs plotly.js: run `python compiler/plotly_fetch.py` once before.

By default the demo history pages show invented placeholder tiles instead of item pictures (`make_demo` writes them to `<folder>/<lang>/icons/` and
passes `--icons-dir`). The Character picture of the landing page and the READMEs (`character-en.png` / `character-de.png`) is made with
`--icons-from-game <WoW folder>` instead (and `--product`, default `wow`): the demo then reads sixteen fixed pictures of the game (`GAME_ICON_IDS`, only
ids are in the source) from that installation into the output folder, which has to lie outside the repository. Only the finished screenshot goes into
`docs/images/` (decision of the maintainer, 2026-11-05: one picture with a few game icons, credited to Blizzard Entertainment under the block and on the
page). In PowerShell, Edge returns before it has written the file unless its output is piped, for example `| Select-Object -Last 1`.

## Layout

```
src/            start.py (entry script), the files the program bundles (template.html, history.html, updater_helper.ps1,
                plotly.min.js, CascLib.dll) and the application code in folders (Python packages):
  src/core/     names and version (app_info), folders (paths), settings (config), texts (i18n), colour schemes (theme), updater
  src/game/     the WoW installation and its files: wow_install, wow_icons, blp_decode, casclib_asset
  src/store/    the statistics database: lua_reader, stat_values, db_schema, importer, db_backup
  src/rules/    stat_derive, group_rules, rep_rules, table_rules, tile_rules, char_rules, char_names, collation, numfmt (figures, rows, sort order, which characters the outputs leave out, how a character is shown, and number format, pure calculation)
  src/pages/    page_payload, outputs, stat_history, plotly_asset (what is shown and the files written);
                blocks/ (the blocks of the stats page, one module each, and layout.py: which block fills which numbered place of the page)
  src/export/   export_xlsx
  src/app/      main_window, dialogs, qt_style, qwebengine_hardening, actions, page_bridge, suggest_list, stat_parser (the window, the bridge to the page, the order of the steps)
addon/          the WoW addon (copied into AddOns by the program)
compiler/       PyInstaller build and the addon package for CurseForge (addon_package.py)
tests/          pytest
tools/          developer helpers (check_stats.py, make_demo.py, make_window_shots.py, make_live_shot.py) - not part of the release
docs/           this file
```

Instance folder of a release:

```
StatTracker.exe, _internal/, addon/, info/, LICENSE     (replaced by an update)
data/                                                    (yours - never touched)
```

## Conventions

- Imports go one way: `core` and `rules` stand alone, `store` and `game` use `core`, `pages` uses those, `export` uses `core` and `store`, `app` may use all. `tests/test_architecture.py` checks it (folders, no cycle, no import inside a function). A new module goes into the folder where its job is.
- The colours of the generated pages are CSS variables (`:root` in `src/template.html` and `src/history.html`); the program window sets them to the chosen colour scheme (`src/core/theme.py`), a page opened without the window keeps its original colours (`theme.PAGE_ORIGINAL`). `tests/test_theme.py` checks that no colour is written into the CSS or the script.
- Files carry the SPDX header (`GPL-3.0-or-later`) and the copyright line.
- Interface text lives in `src/core/i18n.py` (`de`/`en`); `tests/test_i18n.py` checks that every key used in code exists and both languages carry the same placeholders.
- `updater_helper.ps1` must stay plain ASCII (a test checks it).
- A statistics database is opened for writing only through `db_schema.init_db`, which takes the copy (`src/store/db_backup.py`) before the first change; a schema migration gets its own permanent copy.
- Never put user data (databases, generated pages, config) into the repository - `tests/test_public_ready.py` guards this and private references.
