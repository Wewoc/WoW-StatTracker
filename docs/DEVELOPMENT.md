# Development

Notes for running, testing and building StatTracker from source. For using the
program see the [README](../README.md) ([Deutsch](../README.de.md)).

Python 3.10+ (developed on 3.13) with tkinter. Windows is the target of the
packaged release; the logic modules are platform-neutral, the self-updater is
Windows-only (PowerShell helper).

## Run from source

```bash
pip install -r requirements.txt
python src/start.py
```

On Windows you can also double-click `src/bat/start.bat`.

All data goes to `data/` in the repository root (git-ignored): `config.json`,
`wow_stats*.db`, `stats*.html`, `stattracker.xlsx`, `crash.log`, `backups/` (copies of the
database: `daily/` rotates, `migration/` stays).

## Tests

```bash
pip install -r requirements-dev.txt
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

Output: `dist/StatTracker/` (disposable), `dist/StatTracker.zip` and
`dist/StatTracker.zip.sha256`. Upload **both** files to the GitHub release - the
updater refuses a release without the checksum file. `compiler/build_manifest.py`
and `src/app_info.py` are the single sources for names and release contents.

Release checklist:

1. Set `APP_VERSION` in `src/app_info.py` and `## Version:` in `addon/StatTracker/StatTracker.toc` (a test checks they match); update `CHANGELOG.md`.
2. Create an annotated tag `vX.Y.Z` (`git tag -a vX.Y.Z -F <message file>`: first line = release title, the rest = release notes) and push it - `.github/workflows/release.yml` builds, attaches the files and takes title and notes from the tag message. A lightweight tag still releases, but without title and notes.
3. The repository is `Wewoc/WoW-StatTracker` (`REPO_OWNER`/`REPO_NAME` in `src/app_info.py`, `REPO_CONFIRMED = True`). If it is ever renamed or forked, change those, the GitHub links in `docs/index.html`, the READMEs and `X-Website` in the `.toc`; `SITE_URL` (the landing page shown in the footer of the stats page) follows from the same two values. While `REPO_CONFIRMED` is False the update check sends no request. A repository without a release counts as "up to date" (the GitHub API answers 404).

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
`app-*.png` (the program window) is taken by hand.

## Layout

```
src/            application code (flat modules), template.html, updater_helper.ps1
addon/          the WoW addon (copied into AddOns by the program)
compiler/       PyInstaller build
tests/          pytest
tools/          developer helpers (check_stats.py, make_demo.py) - not part of the release
docs/           this file
```

Instance folder of a release:

```
StatTracker.exe, _internal/, addon/, info/, LICENSE     (replaced by an update)
data/                                                    (yours - never touched)
```

## Conventions

- Files carry the SPDX header (`GPL-3.0-or-later`) and the copyright line.
- Interface text lives in `src/i18n.py` (`de`/`en`); `tests/test_i18n.py` checks that every key used in code exists and both languages carry the same placeholders.
- `updater_helper.ps1` must stay plain ASCII (a test checks it).
- A statistics database is opened for writing only through `stat_parser.init_db`, which takes the copy (`src/db_backup.py`) before the first change; a schema migration gets its own permanent copy.
- Never put user data (databases, generated pages, config) into the repository - `tests/test_public_ready.py` guards this and private references.
