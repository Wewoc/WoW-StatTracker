# Changelog

Changes of the addon (`addon/StatTracker`), newest first; one chapter per version of the `.toc`.
The lines of a chapter become the changelog of an addon release.

## 0.2.5

- New: the live window can be **locked in place**: `/statlive lock` keeps it from being dragged by mistake (the corner at the bottom right still changes the width), `/statlive unlock` releases it. The lock is kept over a `/reload`
- New: the page **StatTracker** in the game's *Options -> Addons* has **check boxes** for the window: lock the position, colour the numbers, and which rows the window shows (the five statistics, session gold, played time, rates per hour and the footer with the age of the last scan). All rows are shown by default; with fewer rows the window gets smaller. `/statlive text` in the chat still shows every value
- New: optional **green and red numbers** (off by default, a check box on the options page): a statistic is green or red when your rate in the session (change per hour) is at least 10 % above or below the average of the character (value of the last scan divided by its played time), with a "^" or "v" behind the value and a line in the tooltip. Deaths are the other way round (fewer is green). Nothing is coloured in the first ten minutes of a session or without an average (no scan, no played time): no number is made up
- Note: the settings are kept in the second saved variable `StatTrackerUI` (`settings.window.locked`, `settings.rows`, `settings.colored`); the scan data (`StatTrackerDB`) and the data contract (5) are unchanged, and the program ignores the new settings

## 0.2.4

- New: a **live window** in game for the current character. `/statlive` shows or hides it (it can be put in a macro on a key), `/statlive text` prints the values in the chat and `/statlive watch` follows every change. It shows five statistics (creatures killed, killing blows, deaths, quests completed, gold received) with the change since login, the session gold, the played time (estimated between the game's own answers, and marked so) and, after a few minutes, rates per hour. A value that comes from the last scan instead of the game is marked "(Scan)" and dimmed; a value the game does not give reads "no value", never 0. The tooltip of a statistic row tells the value of the last scan and how old it is. The window can be moved, its width is changed at the bottom right corner, and it remembers position, width and whether it was open (also after `/reload` and a new login). Nothing runs while it is closed
- New: the page **StatTracker** in the game's *Options -> Addons* with a short explanation (including the command that shows and hides the window), the link to the project page in a field to copy from, and what the program is good for
