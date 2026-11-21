# StatTracker-Addon

Release channel for the ZIP of the **StatTracker** World of Warcraft addon. There is no source code here: the program
[StatTracker](https://github.com/Wewoc/WoW-StatTracker) loads the addon from the releases of this repository.

**Players:** get the addon from [CurseForge](https://www.curseforge.com/wow/addons/stattracker) (updates arrive there), or let the
StatTracker program install it. Nothing needs to be done in this repository.

**What a release is:** `StatTracker-addon.zip` (one folder `StatTracker/` with the files of the addon, exactly as in the main repository),
`StatTracker-addon.zip.sha256` (its SHA-256) and the notes of the version. The release `vX.Y.Z` is built from the tag `addon-vX.Y.Z` of
the main repository; its text names that tag and the commit. The build is reproducible: the same files give the same ZIP, so the checksum
can be checked again by anyone (`compiler/addon_zip.py` in the main repository). A release is never changed after it is made; a fix is a new version.

**Issues, questions, source:** in the [main repository](https://github.com/Wewoc/WoW-StatTracker). Issues are switched off here.

License: GPL-3.0-or-later (see `LICENSE`).

---

**Deutsch:** Dieses Repository ist nur der Veröffentlichungsweg für die ZIP-Datei des WoW-Addons StatTracker, Quelltext liegt hier nicht.
Spieler holen das Addon bei [CurseForge](https://www.curseforge.com/wow/addons/stattracker) oder über das Programm StatTracker; hier ist nichts zu tun.
Fragen und Fehlermeldungen bitte im [Haupt-Repository](https://github.com/Wewoc/WoW-StatTracker).
