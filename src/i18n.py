#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)
# i18n.py
# StatTracker - the app's own interface text (DE/EN). Not the WoW statistic
# names: those come from the game client in the client's language and are
# stored and shown as they are.
# Leaf-Node: no project imports.
#
#   t(key, **fields)   text in the current language, str.format()-ed
#   raw(key)           text without formatting (html_* strings, formatted in JS)
#   html_strings(lang) all html_* strings of one language (embedded in stats pages)
#   names(prefix, lang) class_* / race_* names of one language (the group labels of the stats page)

LANGUAGES = {"de": "Deutsch", "en": "English"}
DEFAULT_LANGUAGE = "en"

_lang = DEFAULT_LANGUAGE

_STRINGS = {
    # ------------------------------------------------------------ main window
    "window_title": {"de": "StatTracker", "en": "StatTracker"},
    "lbl_language": {"de": "Sprache:", "en": "Language:"},
    "lbl_wow_folder": {"de": "WoW-Ordner:", "en": "WoW folder:"},
    "btn_browse": {"de": "Durchsuchen ...", "en": "Browse ..."},
    "lbl_variant": {"de": "Spielversion:", "en": "Game version:"},
    "btn_settings": {"de": "Einstellungen ...", "en": "Settings ..."},
    "lbl_account": {"de": "Account:", "en": "Account:"},
    "btn_reload": {"de": "Neu laden", "en": "Reload"},
    "btn_install": {"de": "1. Addon installieren / aktualisieren", "en": "1. Install / update addon"},
    "btn_parse": {"de": "2. Daten einlesen", "en": "2. Read data"},
    "btn_open": {"de": "3. Statistik-Seite öffnen", "en": "3. Open stats page"},
    "btn_parse_open": {"de": "Einlesen + öffnen", "en": "Read + open"},
    "btn_export": {"de": "Excel exportieren", "en": "Export to Excel"},
    "btn_uninstall": {"de": "Addon deinstallieren", "en": "Uninstall addon"},
    "browse_title": {
        "de": "WoW-Ordner wählen (der Ordner mit _retail_ ...)",
        "en": "Choose the WoW folder (the folder containing _retail_ ...)",
    },
    "footer_version": {"de": "Version {version}", "en": "Version {version}"},
    "btn_about": {"de": "Über ...", "en": "About ..."},
    "btn_check_updates": {"de": "Nach Updates suchen", "en": "Check for updates"},

    # ----------------------------------------------------------------- status
    "status_invalid_root": {
        "de": "WoW-Ordner ungültig: es wird ein Ordner mit Unterordnern wie _retail_ erwartet.",
        "en": "Invalid WoW folder: a folder containing subfolders such as _retail_ is expected.",
    },
    "status_variant_disabled": {
        "de": "Die Spielversion {variant} ist nicht aktiviert (Einstellungen ...).",
        "en": "The game version {variant} is not enabled (Settings ...).",
    },
    "status_game": {"de": "Spiel: {path}", "en": "Game: {path}"},
    "status_data_present": {
        "de": "Datendatei vorhanden (zuletzt geschrieben {ts})",
        "en": "Data file present (last written {ts})",
    },
    "status_data_missing": {
        "de": "Datendatei fehlt noch: im Spiel Addon laden, /statscan, dann /reload",
        "en": "Data file missing: in game load the addon, /statscan, then /reload",
    },
    "status_no_account": {"de": "Kein Account gefunden", "en": "No account found"},
    "status_html_present": {"de": "{name}: vorhanden", "en": "{name}: present"},
    "status_html_missing": {"de": "{name}: noch nicht erzeugt", "en": "{name}: not created yet"},
    "status_addon_missing": {"de": "Addon: nicht installiert", "en": "Addon: not installed"},
    "status_addon_ok": {"de": "Addon: Version {version}", "en": "Addon: version {version}"},
    "status_addon_outdated": {
        "de": "Addon: veraltet (installiert {installed}, mitgeliefert {bundled}) - Schritt 1 ausführen",
        "en": "Addon: outdated (installed {installed}, bundled {bundled}) - run step 1",
    },
    "status_addon_interface": {
        "de": "Addon: Interface-Nummer passt nicht zum Spiel (installiert {installed}, Spiel {expected}) - Schritt 1 ausführen",
        "en": "Addon: interface number does not match the game (installed {installed}, game {expected}) - run step 1",
    },
    "status_addon_unknown": {"de": "Addon: installiert", "en": "Addon: installed"},

    # ------------------------------------------------------- messages / dialogs
    "dlg_title": {"de": "StatTracker", "en": "StatTracker"},
    "err_invalid_root": {
        "de": "WoW-Ordner ungültig.\nGewählt werden muss der Ordner, in dem _retail_ liegt.",
        "en": "Invalid WoW folder.\nChoose the folder that contains _retail_.",
    },
    "err_no_account": {"de": "Kein Account ausgewählt.", "en": "No account selected."},
    "err_no_variant": {"de": "Keine Spielversion gewählt.", "en": "No game version selected."},
    "err_no_data_file": {
        "de": "Datendatei nicht gefunden:\n{path}\n\nIm Spiel /statscan ausführen, auf die Spielzeit-Meldung warten, dann /reload.",
        "en": "Data file not found:\n{path}\n\nIn game run /statscan, wait for the played-time message, then /reload.",
    },
    "info_no_html": {
        "de": "{name} existiert noch nicht. Zuerst Daten einlesen.",
        "en": "{name} does not exist yet. Read the data first.",
    },
    "err_config_save": {
        "de": "Konfiguration konnte nicht gespeichert werden: {error}",
        "en": "Configuration could not be saved: {error}",
    },
    "warn_config_broken": {
        "de": "Die Konfigurationsdatei war unlesbar und wurde zurückgesetzt ({detail}).",
        "en": "The configuration file was unreadable and has been reset ({detail}).",
    },

    # ---------------------------------------------------------------- log lines
    "log_install_ok": {"de": "Addon kopiert nach {dest}", "en": "Addon copied to {dest}"},
    "log_interface_set": {
        "de": "Interface-Nummer {number} gesetzt (Version {version}, Produkt {product}).",
        "en": "Interface number {number} set (version {version}, product {product}).",
    },
    "log_interface_unset": {
        "de": "Interface-Nummer nicht gesetzt (Produkt {product!r} nicht in .build.info gefunden). "
              "Im Spiel '/dump (select(4, GetBuildInfo()))' ausführen und in die .toc eintragen.",
        "en": "Interface number not set (product {product!r} not found in .build.info). "
              "In game run '/dump (select(4, GetBuildInfo()))' and enter the number in the .toc.",
    },
    "log_install_reload": {
        "de": "Im Spiel: WoW neu starten (neue .toc) oder /reload (nur .lua geändert).",
        "en": "In game: restart WoW (new .toc) or /reload (only .lua changed).",
    },
    "err_install_failed": {"de": "Installation fehlgeschlagen: {error}", "en": "Installation failed: {error}"},
    "err_addon_source": {"de": "Addon-Quelle unvollständig: {path}", "en": "Addon source incomplete: {path}"},
    "err_addons_dir": {"de": "AddOns-Ordner nicht gefunden: {path}", "en": "AddOns folder not found: {path}"},
    "err_copy_failed": {"de": "Kopie fehlerhaft: {path}", "en": "Copy is faulty: {path}"},
    "err_toc_interface": {"de": "Keine '## Interface:'-Zeile in {path}", "en": "No '## Interface:' line in {path}"},
    "log_parse_ok": {"de": "Einlesen erfolgreich.", "en": "Read successfully."},
    "log_parse_fail": {"de": "Einlesen fehlgeschlagen.", "en": "Reading failed."},
    "log_parse_unexpected": {"de": "Unerwarteter Fehler: {error}", "en": "Unexpected error: {error}"},
    "log_opened": {"de": "Geöffnet: {path}", "en": "Opened: {path}"},
    "log_browser_fail": {
        "de": "Browser konnte nicht gestartet werden. Datei: {path}",
        "en": "Could not start the browser. File: {path}",
    },
    "log_export_ok": {"de": "Excel-Export erfolgreich.", "en": "Excel export successful."},
    "log_export_fail": {"de": "Excel-Export fehlgeschlagen.", "en": "Excel export failed."},
    "log_file_open_fail": {"de": "Datei konnte nicht geöffnet werden: {path}", "en": "Could not open file: {path}"},

    # --------------------------------------------------------------- uninstall
    "confirm_uninstall": {
        "de": "Das Addon wird aus diesem Ordner entfernt:\n{dest}\n\nFortfahren?",
        "en": "The addon will be removed from this folder:\n{dest}\n\nContinue?",
    },
    "confirm_uninstall_vars": {
        "de": "Auch die vom Addon gespeicherten Daten in WoW löschen (StatTracker.lua in SavedVariables)?\n\n"
              "Nein = behalten. Die lokale Datenbank und die erzeugten Seiten in diesem Programm bleiben in beiden Fällen erhalten.",
        "en": "Also delete the data the addon saved inside WoW (StatTracker.lua in SavedVariables)?\n\n"
              "No = keep it. The local database and generated pages of this program are kept in both cases.",
    },
    "log_uninstall_ok": {"de": "Addon entfernt: {dest}", "en": "Addon removed: {dest}"},
    "log_uninstall_none": {"de": "Addon war nicht installiert: {dest}", "en": "Addon was not installed: {dest}"},
    "log_uninstall_vars": {
        "de": "{count} Datendatei(en) in WoW gelöscht.",
        "en": "{count} data file(s) deleted inside WoW.",
    },
    "log_uninstall_kept": {
        "de": "Lokale Datenbank und Seiten in {path} bleiben erhalten.",
        "en": "Local database and pages in {path} are kept.",
    },
    "err_uninstall_failed": {"de": "Deinstallation fehlgeschlagen: {error}", "en": "Uninstall failed: {error}"},
    "err_uninstall_unsafe": {
        "de": "Verweigert: {path} sieht nicht wie die StatTracker-Addon-Installation aus.",
        "en": "Refused: {path} does not look like the StatTracker addon installation.",
    },

    # ---------------------------------------------------------------- settings
    "settings_title": {"de": "Einstellungen", "en": "Settings"},
    "settings_variants": {"de": "Aktivierte Spielversionen:", "en": "Enabled game versions:"},
    "settings_variants_hint": {
        "de": "Nur aktivierte Spielversionen erscheinen in der Auswahl. Standard: nur Retail (getestet). "
              "BC Anniversary stellt keine Statistiken bereit und funktioniert nicht.",
        "en": "Only enabled game versions appear in the selection. Default: Retail only (tested). "
              "BC Anniversary provides no statistics and does not work.",
    },
    "settings_check_updates": {"de": "Beim Start nach Updates suchen", "en": "Check for updates at start"},
    "settings_none_selected": {
        "de": "Mindestens eine Spielversion muss aktiviert sein.",
        "en": "At least one game version must be enabled.",
    },
    "btn_ok": {"de": "OK", "en": "OK"},
    "btn_cancel": {"de": "Abbrechen", "en": "Cancel"},
    "btn_close": {"de": "Schließen", "en": "Close"},

    # ------------------------------------------------------------------- about
    "about_title": {"de": "Über StatTracker", "en": "About StatTracker"},
    "about_desc": {
        "de": "Liest die Spielstatistiken deiner WoW-Charaktere über ein kleines Addon aus, "
              "sammelt sie in einer lokalen Datenbank und vergleicht sie in einer Seite oder in Excel. "
              "Alle Daten bleiben auf deinem Rechner.",
        "en": "Reads the game statistics of your WoW characters through a small addon, "
              "collects them in a local database and compares them in a page or in Excel. "
              "All data stays on your computer.",
    },
    "about_repo": {"de": "Repository:", "en": "Repository:"},
    "about_repo_placeholder": {
        "de": "Hinweis: Der Repository-Link ist noch ein Platzhalter. Die Update-Prüfung ist deaktiviert.",
        "en": "Note: the repository link is still a placeholder. The update check is disabled.",
    },
    "about_license": {
        "de": "Lizenz: {license}. Freie Software, bereitgestellt „wie besehen“ ohne Gewährleistung - Nutzung auf eigenes Risiko.",
        "en": "License: {license}. Free software, provided \"as is\" without any warranty - use at your own risk.",
    },

    # ----------------------------------------------------------------- updater
    "update_title": {"de": "Update verfügbar", "en": "Update available"},
    "update_text": {
        "de": "Eine neue Version ist verfügbar: {title}\nInstalliert: {current}",
        "en": "A new version is available: {title}\nInstalled: {current}",
    },
    "btn_update_now": {"de": "Jetzt aktualisieren", "en": "Update now"},
    "btn_open_github": {"de": "GitHub öffnen", "en": "Open GitHub"},
    "btn_later": {"de": "Später", "en": "Later"},
    "update_none": {"de": "Du nutzt die aktuelle Version ({version}).", "en": "You are running the latest version ({version})."},
    "update_check_failed": {"de": "Update-Prüfung fehlgeschlagen: {error}", "en": "Update check failed: {error}"},
    "update_repo_placeholder": {
        "de": "Das Repository ist noch ein Platzhalter - die Update-Prüfung ist deaktiviert.",
        "en": "The repository is still a placeholder - the update check is disabled.",
    },
    "update_downloading": {
        "de": "Update auf {version}: lade herunter und prüfe ...",
        "en": "Update to {version}: downloading and verifying ...",
    },
    "update_failed": {"de": "Update fehlgeschlagen: {error}", "en": "Update failed: {error}"},
    "update_no_asset": {
        "de": "Das Release enthält kein Asset {asset}.",
        "en": "The release has no asset {asset}.",
    },
    "update_applying": {
        "de": "Update wird angewendet, StatTracker startet gleich neu ...",
        "en": "Applying the update, StatTracker restarts in a moment ...",
    },
    "update_not_frozen": {
        "de": "Selbst-Update gibt es nur in der installierten Exe-Version. Neue Version: {url}",
        "en": "Self-update is only available in the installed exe version. New version: {url}",
    },
    "err_no_checksum": {
        "de": "Dieses Release veröffentlicht keine Prüfsummen-Datei - ein ungeprüftes Update wird nicht angewendet.",
        "en": "This release does not publish a checksum file - refusing to apply an unverified update.",
    },
    "err_download": {"de": "Download fehlgeschlagen: {error}", "en": "Download failed: {error}"},
    "err_checksum": {
        "de": "Prüfsumme stimmt nicht (erwartet {expected}, erhalten {actual}). Download verworfen, nichts angewendet.",
        "en": "Checksum mismatch (expected {expected}, got {actual}). Download discarded, nothing applied.",
    },
    "err_bad_zip": {"de": "Die heruntergeladene Datei ist kein gültiges ZIP: {error}", "en": "The downloaded file is not a valid ZIP: {error}"},
    "err_payload_incomplete": {
        "de": "Das Update-Paket ist unvollständig (fehlt: {missing}) - nichts angewendet.",
        "en": "The update package is incomplete (missing: {missing}) - nothing applied.",
    },
    "err_bad_url": {"de": "Unzulässige Download-Adresse: {url}", "en": "Refused download address: {url}"},

    # ------------------------------------------------------------------ parser
    "played_total": {"de": "Gesamte Spielzeit", "en": "Total time played"},
    "played_level": {"de": "Zeit auf dieser Stufe", "en": "Time played this level"},
    "played_category": {"de": "Charakter > Spielzeit", "en": "Character > Time played"},
    "duration_fmt": {
        "de": "{d} Tage, {h} Std., {m} Min., {s} Sek.",
        "en": "{d} days, {h} h, {m} min, {s} s",
    },
    "parse_err_no_chars": {
        "de": "FEHLER: StatTrackerDB enthält keine Charaktere. Im Spiel /statscan ausführen und danach /reload.",
        "en": "ERROR: StatTrackerDB contains no characters. In game run /statscan and then /reload.",
    },
    "parse_err_incomplete_char": {
        "de": "FEHLER: Charakter {key!r} hat ein unvollständiges Format.",
        "en": "ERROR: character {key!r} has an incomplete format.",
    },
    "parse_warn_no_played": {
        "de": "WARNUNG: {key}: keine Spielzeit im Scan vom {at} (im Spiel /statscan wiederholen und auf die Spielzeit-Meldung warten).",
        "en": "WARNING: {key}: no played time in the scan from {at} (repeat /statscan in game and wait for the played-time message).",
    },
    "parse_err_played_invalid": {
        "de": "FEHLER: {key!r}: {field} ist keine gültige Sekundenzahl: {value!r}",
        "en": "ERROR: {key!r}: {field} is not a valid number of seconds: {value!r}",
    },
    "parse_err_template_missing": {"de": "FEHLER: {path} fehlt.", "en": "ERROR: {path} is missing."},
    "parse_err_marker_missing": {
        "de": "FEHLER: Platzhalter fehlt in template.html.",
        "en": "ERROR: placeholder missing in template.html.",
    },
    "parse_err_file_missing": {"de": "FEHLER: Datei nicht gefunden: {path}", "en": "ERROR: file not found: {path}"},
    "parse_err_default_path": {
        "de": "FEHLER: StatTracker.lua nicht im Standardpfad gefunden. --input PFAD angeben.",
        "en": "ERROR: StatTracker.lua not found in the default path. Pass --input PATH.",
    },
    "parse_err_multi_accounts": {
        "de": "FEHLER: mehrere Accounts gefunden, --input angeben:\n  {paths}",
        "en": "ERROR: several accounts found, pass --input:\n  {paths}",
    },
    "parse_err_db_too_new": {
        "de": "FEHLER: Die Datenbank {path} hat das Schema {found}, dieses StatTracker kennt nur bis Schema {known}. "
              "StatTracker aktualisieren; die Datenbank wurde nicht verändert.",
        "en": "ERROR: the database {path} has schema {found}, this StatTracker only knows up to schema {known}. "
              "Update StatTracker; the database was not changed.",
    },
    "parse_err_data_too_new": {
        "de": "FEHLER: Die Datei {path} hat das Datenformat {found!r}, dieses StatTracker versteht nur Datenformate "
              "bis {known}. StatTracker aktualisieren; es wurde nichts gelesen und nichts geändert.",
        "en": "ERROR: the file {path} has data format {found!r}, this StatTracker only understands data formats "
              "up to {known}. Update StatTracker; nothing was read and nothing was changed.",
    },
    "parse_err_backup_failed": {
        "de": "FEHLER: Das Backup der Datenbank ist fehlgeschlagen, es wurde nichts geändert. "
              "Freien Platz und Schreibrechte im Ordner der Datenbank prüfen. {error}",
        "en": "ERROR: the backup of the database failed, nothing was changed. "
              "Check the free space and write permission in the database folder. {error}",
    },
    "parse_warn_backup_rotate": {
        "de": "WARNUNG: Alte Backups konnten nicht gelöscht werden: {paths}",
        "en": "WARNING: old backups could not be deleted: {paths}",
    },
    "parse_err_read": {"de": "FEHLER beim Lesen von {path}: {error}", "en": "ERROR reading {path}: {error}"},
    "parse_err_no_db_var": {"de": "FEHLER: StatTrackerDB nicht in der Datei.", "en": "ERROR: StatTrackerDB not in the file."},
    "parse_out_source": {"de": "Quelle:   {path}", "en": "Source:   {path}"},
    "parse_out_scans": {"de": "Scans:    {new} neu, {skipped} bereits in der DB", "en": "Scans:    {new} new, {skipped} already in the DB"},
    "parse_out_numbers": {
        "de": "Zahlen:   {count} gespeicherte Werte nach neuer Regel korrigiert",
        "en": "Numbers:  {count} stored values corrected by the current rules",
    },
    "parse_out_backup": {"de": "Backup:   {path}", "en": "Backup:   {path}"},
    "parse_out_db": {"de": "DB:       {path}", "en": "DB:       {path}"},
    "parse_out_html": {
        "de": "HTML:     {path}  ({chars} Charaktere, {stats} Statistiken)",
        "en": "HTML:     {path}  ({chars} characters, {stats} statistics)",
    },

    # ------------------------------------------------------------------- excel
    "xl_err_openpyxl": {
        "de": "FEHLER: openpyxl fehlt. Installieren mit:  pip install openpyxl",
        "en": "ERROR: openpyxl is missing. Install with:  pip install openpyxl",
    },
    "xl_err_no_db": {
        "de": "FEHLER: keine wow_stats*.db in {folder}. Zuerst Daten einlesen.",
        "en": "ERROR: no wow_stats*.db in {folder}. Read the data first.",
    },
    "xl_skip_no_scans": {"de": "{name}: keine Scans, übersprungen", "en": "{name}: no scans, skipped"},
    "xl_err_no_scans": {"de": "FEHLER: in keiner Datenbank sind Scans vorhanden.", "en": "ERROR: no database contains scans."},
    "xl_err_permission": {
        "de": "FEHLER: {path} kann nicht geschrieben werden. Ist die Datei in Excel geöffnet?",
        "en": "ERROR: {path} cannot be written. Is the file open in Excel?",
    },
    "xl_sheet_info": {
        "de": "Blatt '{sheet}': {chars} Charaktere, {stats} Statistiken (aus {db})",
        "en": "Sheet '{sheet}': {chars} characters, {stats} statistics (from {db})",
    },
    "xl_file": {"de": "Datei: {path}", "en": "File: {path}"},
    "xl_col_category": {"de": "Kategorie", "en": "Category"},
    "xl_col_stat": {"de": "Statistik", "en": "Statistic"},
    "xl_col_unit": {"de": "Einheit", "en": "Unit"},
    "xl_col_diff": {"de": "Unterschied", "en": "Differs"},
    "xl_yes": {"de": "ja", "en": "yes"},
    "xl_no": {"de": "nein", "en": "no"},
    "unit_num": {"de": "Zahl", "en": "Number"},
    "unit_gold": {"de": "Gold", "en": "Gold"},
    "unit_hours": {"de": "Std.", "en": "Hours"},
    "unit_text": {"de": "Text", "en": "Text"},
    "unit_mix": {"de": "Mix", "en": "Mixed"},

    # ------------------------------------------- derived statistics (stat_derive.py)
    "derive_kills_pve": {"de": "Kreaturen getötet pro Std.", "en": "Creatures killed per hour"},
    "derive_kills_pvp": {"de": "Ehrenhafte Siege pro Std.", "en": "Honorable kills per hour"},
    "derive_deaths": {"de": "Tode pro Std.", "en": "Deaths per hour"},
    "derive_gold": {"de": "Erhaltenes Gold pro Std. (in Gold)", "en": "Gold acquired per hour (in gold)"},
    "derive_reason_no_played": {"de": "keine Spielzeit", "en": "no played time"},
    "derive_reason_too_little_played": {"de": "zu wenig Spielzeit", "en": "too little played time"},
    "derive_reason_no_stat": {"de": "Statistik fehlt", "en": "statistic missing"},
    "derive_reason_no_chars": {"de": "kein Charakter verwertbar", "en": "no usable character"},

    # --------------------------------------------------- stats page (template.html)
    "html_title": {"de": "WoW-StatTracker", "en": "WoW-StatTracker"},
    "html_footer_version": {"de": "Version {version}", "en": "Version {version}"},
    "html_generated": {
        "de": "Erzeugt: {generated} · {chars} Charaktere · {stats} Statistiken",
        "en": "Generated: {generated} · {chars} characters · {stats} statistics",
    },
    "html_no_data": {"de": "Keine Daten.", "en": "No data."},
    "html_search": {"de": "Statistik suchen ...", "en": "Search statistics ..."},
    "html_all_cats": {"de": "Alle Kategorien", "en": "All categories"},
    "html_only_diff": {"de": "nur Unterschiede", "en": "differences only"},
    "html_hide_empty": {"de": "leere ausblenden", "en": "hide empty"},
    "html_select_all": {"de": "Alle auswählen", "en": "Select all"},
    "html_deselect_all": {"de": "Alle abwählen", "en": "Deselect all"},
    "html_col_cat": {"de": "Kategorie", "en": "Category"},
    "html_col_stat": {"de": "Statistik", "en": "Statistic"},
    "html_count": {"de": "{shown} von {total} Statistiken", "en": "{shown} of {total} statistics"},
    "html_rates_title": {"de": "Raten pro Spielstunde", "en": "Rates per hour played"},
    "html_rates_col_char": {"de": "Charakter", "en": "Character"},
    "html_rates_total": {"de": "Gesamt", "en": "Total"},
    "html_rates_total_of": {"de": "{used} von {of} Charakteren", "en": "{used} of {of} characters"},
    "html_rates_note": {
        "de": "Zähler geteilt durch die gesamte Spielzeit des Charakters (aktueller Scan). "
              "Gesamt = Summe der Zähler / Summe der Stunden, ohne Charaktere mit weniger als {hours} Std. Spielzeit. "
              "„--“ bei Toden und Ehrenhaften Siegen zählt als 0.",
        "en": "Counter divided by the character's total played time (latest scan). "
              "Total = sum of counters / sum of hours, leaving out characters with less than {hours} h played. "
              "“--” for deaths and honorable kills counts as 0.",
    },
    "html_groups_title": {"de": "Gruppen", "en": "Groups"},
    "html_groups_by": {"de": "Gruppieren nach", "en": "Group by"},
    "html_groups_by_class": {"de": "Klasse", "en": "Class"},
    "html_groups_by_race": {"de": "Rasse", "en": "Race"},
    "html_groups_by_faction": {"de": "Fraktion", "en": "Faction"},
    "html_groups_by_realm": {"de": "Realm", "en": "Realm"},
    "html_groups_pick": {"de": "Angezeigte Gruppen", "en": "Groups shown"},
    "html_groups_figures": {"de": "Kennzahlen", "en": "Figures"},
    "html_groups_col_group": {"de": "Gruppe", "en": "Group"},
    "html_groups_fig_chars": {"de": "Charaktere", "en": "Characters"},
    "html_groups_fig_level": {"de": "Ø Level", "en": "Avg. level"},
    "html_groups_fig_played": {"de": "Spielzeit gesamt", "en": "Total played time"},
    "html_groups_unknown": {"de": "unbekannt", "en": "unknown"},
    "html_groups_none_selected": {"de": "Keine Charaktere ausgewählt.", "en": "No characters selected."},
    "html_groups_no_value": {"de": "kein Wert", "en": "no value"},
    "html_groups_hours": {"de": "{n} Std.", "en": "{n} h"},
    "html_groups_note": {
        "de": "Klasse und Rasse stammen aus dem Scan: Charaktere, die seit dem Addon-Update nicht neu gescannt wurden, "
              "stehen unter „unbekannt“. Raten = Summe der Zähler / Summe der Stunden der Gruppe, ohne Charaktere mit "
              "weniger als {hours} Std. Spielzeit. Gesamt gilt für die angezeigten Gruppen; es zählen die oben "
              "angehakten Charaktere.",
        "en": "Class and race come from the scan: characters not scanned again since the addon update are listed "
              "under “unknown”. Rates = sum of counters / sum of hours of the group, leaving out characters with "
              "less than {hours} h played. Total covers the groups shown; the characters ticked above are counted.",
    },
    "html_faction_Alliance": {"de": "Allianz", "en": "Alliance"},
    "html_faction_Horde": {"de": "Horde", "en": "Horde"},
    "html_faction_Neutral": {"de": "Neutral", "en": "Neutral"},

    # ------------------------------------------- class and race names for the groups on the stats page
    # Keyed by the language independent file name the game gives (UnitClass/UnitRace, second value):
    # one neutral name per class or race, whatever the gender of the character. Unknown file names
    # are shown with the text stored in the scan. New races are added here by hand.
    "class_WARRIOR": {"de": "Krieger", "en": "Warrior"},
    "class_PALADIN": {"de": "Paladin", "en": "Paladin"},
    "class_HUNTER": {"de": "Jäger", "en": "Hunter"},
    "class_ROGUE": {"de": "Schurke", "en": "Rogue"},
    "class_PRIEST": {"de": "Priester", "en": "Priest"},
    "class_DEATHKNIGHT": {"de": "Todesritter", "en": "Death Knight"},
    "class_SHAMAN": {"de": "Schamane", "en": "Shaman"},
    "class_MAGE": {"de": "Magier", "en": "Mage"},
    "class_WARLOCK": {"de": "Hexenmeister", "en": "Warlock"},
    "class_MONK": {"de": "Mönch", "en": "Monk"},
    "class_DRUID": {"de": "Druide", "en": "Druid"},
    "class_DEMONHUNTER": {"de": "Dämonenjäger", "en": "Demon Hunter"},
    "class_EVOKER": {"de": "Rufer", "en": "Evoker"},
    "race_Human": {"de": "Mensch", "en": "Human"},
    "race_Orc": {"de": "Orc", "en": "Orc"},
    "race_Dwarf": {"de": "Zwerg", "en": "Dwarf"},
    "race_NightElf": {"de": "Nachtelf", "en": "Night Elf"},
    "race_Scourge": {"de": "Untoter", "en": "Undead"},
    "race_Tauren": {"de": "Tauren", "en": "Tauren"},
    "race_Gnome": {"de": "Gnom", "en": "Gnome"},
    "race_Troll": {"de": "Troll", "en": "Troll"},
    "race_Goblin": {"de": "Goblin", "en": "Goblin"},
    "race_BloodElf": {"de": "Blutelf", "en": "Blood Elf"},
    "race_Draenei": {"de": "Draenei", "en": "Draenei"},
    "race_Worgen": {"de": "Worgen", "en": "Worgen"},
    "race_Pandaren": {"de": "Pandaren", "en": "Pandaren"},
    "race_Nightborne": {"de": "Nachtgeborener", "en": "Nightborne"},
    "race_HighmountainTauren": {"de": "Hochbergtauren", "en": "Highmountain Tauren"},
    "race_VoidElf": {"de": "Leerenelf", "en": "Void Elf"},
    "race_LightforgedDraenei": {"de": "Lichtgeschmiedeter Draenei", "en": "Lightforged Draenei"},
    "race_ZandalariTroll": {"de": "Zandalaritroll", "en": "Zandalari Troll"},
    "race_KulTiran": {"de": "Kul Tiraner", "en": "Kul Tiran"},
    "race_DarkIronDwarf": {"de": "Dunkeleisenzwerg", "en": "Dark Iron Dwarf"},
    "race_Vulpera": {"de": "Vulpera", "en": "Vulpera"},
    "race_MagharOrc": {"de": "Mag'har", "en": "Mag'har Orc"},
    "race_Mechagnome": {"de": "Mechagnom", "en": "Mechagnome"},
    "race_Dracthyr": {"de": "Dracthyr", "en": "Dracthyr"},
}


def set_language(lang: str) -> None:
    global _lang
    _lang = lang if lang in LANGUAGES else DEFAULT_LANGUAGE


def get_language() -> str:
    return _lang


def raw(key: str, /, lang: str = None) -> str:
    entry = _STRINGS.get(key)
    if entry is None:
        return f"[{key}]"  # visible, never silently empty
    return entry.get(lang or _lang) or entry[DEFAULT_LANGUAGE]


def t(key: str, /, **fields) -> str:  # positional-only: some messages have a {key} field of their own
    text = raw(key)
    if not fields:
        return text
    try:
        return text.format(**fields)
    except (KeyError, IndexError, ValueError):
        return text  # a bad placeholder must not crash the GUI; tests check consistency


def html_strings(lang: str) -> dict:
    return {k[len("html_"):]: raw(k, lang) for k in _STRINGS if k.startswith("html_")}


def names(prefix: str, lang: str) -> dict:
    """{file name: text} of all keys with this prefix ("class_", "race_"), in one language."""
    return {k[len(prefix):]: raw(k, lang) for k in _STRINGS if k.startswith(prefix)}
