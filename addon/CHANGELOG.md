# Changelog

Changes of the addon (`addon/StatTracker`), newest first; one chapter per version of the `.toc`.
The lines of a chapter become the changelog of an addon release.

## 0.2.4

- New: a **live window** in game for the current character. `/statlive` shows or hides it (it can be put in a macro on a key), `/statlive text` prints the values in the chat and `/statlive watch` follows every change. It shows five statistics (creatures killed, killing blows, deaths, quests completed, gold received) with the change since login, the session gold, the played time (estimated between the game's own answers, and marked so) and, after a few minutes, rates per hour. A value that comes from the last scan instead of the game is marked "(Scan)" and dimmed; a value the game does not give reads "no value", never 0. The tooltip of a statistic row tells the value of the last scan and how old it is. The window can be moved, its width is changed at the bottom right corner, and it remembers position, width and whether it was open (also after `/reload` and a new login). Nothing runs while it is closed
- New: the page **StatTracker** in the game's *Options -> Addons* with a short explanation (including the command that shows and hides the window), the link to the project page in a field to copy from, and what the program is good for
