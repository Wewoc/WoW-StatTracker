# StatTracker

[English](README.md)

StatTracker liest die **Spielstatistiken** deiner World-of-Warcraft-Charaktere über ein kleines Addon aus, speichert jeden Scan in einer lokalen Datenbank (mit Historie) und lässt dich deine **Charaktere vergleichen** - auf einer Seite im Browser oder in einer Excel-Datei. Alles bleibt auf deinem Rechner.

- Windows-Programm mit kleinem Fenster - kein Python nötig (Release-Download)
- Deutsche und englische Oberfläche (Dropdown im Fenster)
- Raten pro Spielstunde (Kills, Tode, Gold) je Charakter und insgesamt; lässt sich eine Zahl nicht berechnen, nennt die Seite den Grund
- Arbeitet pro Spielversion; standardmäßig ist nur **Retail** aktiviert
- Installiert und deinstalliert sein Addon für dich
- Sucht auf GitHub nach neuen Versionen und kann sich selbst aktualisieren (Prüfsumme, mit Rollback)

## Schnellstart (Release-Download)

1. `StatTracker.zip` aus dem neuesten Release laden und in **einen eigenen Ordner** entpacken, zum Beispiel `Dokumente\StatTracker`. Nicht nach `C:\Program Files`: Das Programm legt seine Daten neben sich ab und braucht Schreibrechte.
2. `StatTracker.exe` starten. Windows SmartScreen warnt eventuell, weil die Datei nicht signiert ist: *Weitere Informationen -> Trotzdem ausführen*.
3. **WoW-Ordner** wählen (der Ordner, der `_retail_` enthält), dazu Spielversion und Account.
4. **1. Addon installieren / aktualisieren**.
5. Im Spiel, einmal pro Charakter: `/statscan`. Der Scan dauert etwa 10 Sekunden (gestreckt, damit das Spiel nicht einfriert): Im Chat erscheinen „Stat-Sync gestartet“, dann „Stat-Sync fertig“ und „Spielzeit ... erfasst“. Darauf warten, dann `/reload` (oder ausloggen). Das Addon scannt auch automatisch 10 Sekunden nach dem Einloggen.
6. **2. Daten einlesen**, dann **3. Statistik-Seite öffnen** - oder **Excel exportieren**.

Schritt 5/6 wiederholen, wenn du frische Zahlen willst. Alte Scans bleiben in der Datenbank.

Das Addon speichert bei jedem Scan auch die Klasse (als sprachunabhängigen Namen) und die Rasse des Charakters. Scans eines älteren Addons haben keine Rasse, sie wird nie nachgetragen: *1. Addon installieren / aktualisieren* ausführen und den Charakter erneut scannen. Die Statistik-Seite nutzt sie noch nicht.

## Spielversionen

Im Dropdown erscheinen nur Spielversionen, die du aktiviert hast. Standard ist nur **Retail**. Unter *Einstellungen ...* lassen sich weitere aktivieren. Jede Spielversion hat eigene Datenbank und Seite (`wow_stats.db` / `stats.html` für Retail, `wow_stats_<Version>.db` / `stats_<Version>.html` für die anderen).

| Spielversion | Stand |
|---|---|
| Retail (`_retail_`) | getestet, funktioniert |
| BC Anniversary (`_anniversary_`) | getestet, **funktioniert nicht**: Diese Spielversion stellt keine Statistiken bereit, es gibt also nichts auszulesen |
| alle anderen | ungetestet |

Meldet WoW das Addon als veraltet: im Spiel `/dump (select(4, GetBuildInfo()))` ausführen und die Zahl in `StatTracker.toc` (`## Interface:`) eintragen. Beim Installieren setzt das Programm sie aus `.build.info` selbst.

## Deinstallieren

- **Addon:** *Addon deinstallieren* entfernt `Interface\AddOns\StatTracker` der gewählten Spielversion. Vorher wird gefragt, ob auch die vom Addon in WoW gespeicherten Daten (`StatTracker.lua` in `SavedVariables`) gelöscht werden sollen - Standard ist behalten. Deine lokale Datenbank und die Seiten löscht dieser Button nie.
- **Programm:** schließen und den Ordner löschen.

## Sprache

Die Fenstersprache stellst du oben rechts im Dropdown ein (Deutsch / English); sie wird gemerkt. Beim ersten Start gilt deine Windows-Sprache. Die erzeugte Statistik-Seite und die Excel-Datei nutzen dieselbe Sprache.

Die **Namen der Statistiken** kommen vom WoW-Client und erscheinen in dessen Sprache - StatTracker übersetzt sie nicht.

## Updates

Beim Start (abschaltbar unter *Einstellungen ...*) fragt StatTracker bei GitHub nach einem neueren Release. Gibt es eins, lädt *Jetzt aktualisieren* die `StatTracker.zip`, prüft sie gegen `StatTracker.zip.sha256` (ohne Prüfsumme kein Update), ersetzt **nur die Programmdateien** und startet neu. Dein Ordner `data` wird nie angefasst. Die vorherige Version bleibt in `_update_backup` und wird automatisch zurückgespielt, wenn die neue nicht startet. Die einzige Netzwerkanfrage ist diese Prüfung; sie sendet keine persönlichen Daten.

## Wo liegen meine Daten?

Neben dem Programm im Ordner `data`: `config.json`, `wow_stats*.db`, `stats*.html`, `stattracker.xlsx` und der Ordner `backups`. Sichere diesen Ordner, wenn dir die Historie wichtig ist.

Bevor ein Einlesen in eine vorhandene Datenbank schreibt, kopiert StatTracker sie nach `data/backups/`:

- `daily/` enthält eine Kopie pro Tag für die letzten 7 Tage; ältere werden automatisch gelöscht.
- `migration/` enthält eine Kopie vor jedem Datenbank-Upgrade (der Dateiname nennt die Version, zu der es führt). Diese werden nie automatisch gelöscht; lösche sie von Hand, wenn du sie nicht mehr brauchst.

So stellst du eine Kopie wieder her: StatTracker schließen, eine `.bak`-Datei aus dem Ordner kopieren, in `wow_stats.db` umbenennen (`wow_stats_<Version>.db` bei den anderen Spielversionen) und in `data` legen. Die Kopien liegen auf derselben Platte wie die Datenbank: sie schützen vor einem fehlerhaften Einlesen oder Upgrade, nicht vor einer defekten Platte - sichere `data` zusätzlich an anderer Stelle. Lässt sich eine Kopie nicht schreiben, bricht das Einlesen ab und ändert nichts.

## Aus dem Quellcode starten

Python 3.10+ mit tkinter (im normalen Windows-Installer enthalten):

```bash
pip install -r requirements.txt
python src/start.py
```

Mehr in [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md).

## Haftungsausschluss

Diese Software wird **„wie besehen“ (as is)** bereitgestellt, ohne Gewährleistung jeglicher Art, weder ausdrücklich noch stillschweigend. **Die Nutzung erfolgt auf eigenes Risiko.** Der Autor haftet nicht für Schäden oder Verluste, die aus der Nutzung entstehen, darunter verlorene oder beschädigte Daten, Probleme mit deiner Spielinstallation oder deinem Account oder Folgen nach den Nutzungsbedingungen des Spiels, deren Einhaltung in deiner Verantwortung liegt.

StatTracker installiert und entfernt Dateien in deinem WoW-Ordner, ersetzt beim Selbst-Update seine eigenen Programmdateien und legt neben sich eine Datenbank an - sichere, was dir wichtig ist (zum Beispiel den Ordner `data`). Siehe Abschnitte 15 bis 17 der [LICENSE](LICENSE) (Gewährleistungsausschluss, Haftungsbeschränkung).

## Lizenz

Copyright (C) 2026 Wewoc. GNU General Public License v3.0 oder neuer - siehe [LICENSE](LICENSE). Dies ist ein Fan-Werkzeug; World of Warcraft ist eine Marke von Blizzard Entertainment, die mit diesem Projekt nicht verbunden ist.
