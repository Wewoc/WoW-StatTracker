#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)
# char_rules.py
# StatTracker - the rules that keep characters out of the output files. The database keeps everything; these rules are applied only when an output
# is made (stage 0: database -> rules -> stats page, history pages, Excel) and never change the database, so taking a rule away brings the character
# back. A rule is {"type": ..., "value": ..., "for": [targets]}: "type" says how the value names characters, "for" lists the outputs it applies to
# (TARGETS: the stats page with its history pages, the Excel file); a rule without "for" applies to both, a list applies to exactly those targets,
# an empty list to none. The types: "char" (one character by its key), "class", "race", "faction", "realm" (the characters of one group, by the
# class or race file name, the faction, or the realm) and "level_below" (the characters whose newest scan is under that level). The first five name
# their characters through tile_rules.members, the same function that picks the characters of a Top 5 tile, so both agree: the value "" is the group
# "unknown" (a character without that value), and a rule with a real value never names a character that has none. A rule of a type this program does
# not know names nobody; so does a level that is no whole number, and a character without a level is never named by "level_below".
# Pure calculation, no I/O. Needs tile_rules.

from rules import tile_rules

TARGETS = ("page", "excel")
SCOPE_TYPES = ("char", "class", "race", "faction", "realm")      # the scopes of tile_rules.members (without "all": a rule naming everybody is no rule)
LEVEL_BELOW = "level_below"
TYPES = SCOPE_TYPES + (LEVEL_BELOW,)


def applies(rule, target: str) -> bool:
    """Whether the rule is meant for this output: no "for" = every target, a list = the targets in it, anything else = none."""
    targets = rule.get("for")
    if targets is None:
        return True
    return isinstance(targets, (list, tuple)) and target in targets


def _limit(value):
    """The whole number a level rule holds (as text, spaces around it allowed), or None for any other value."""
    text = value.strip() if isinstance(value, str) else ""
    return int(text) if text.isascii() and text.isdigit() else None


def _below(chars: list, value) -> list:
    """The characters whose level is under the value (a whole number as text, spaces around it allowed); none for any other value."""
    limit = _limit(value)
    if limit is None:
        return []
    return [c for c in chars if isinstance(c.get("level"), int) and not isinstance(c.get("level"), bool) and c["level"] < limit]


def named_by(chars: list, rule: dict) -> list:
    """The characters (of `chars`, in their order) that one rule names, whatever its targets; none for an unknown type."""
    kind = rule.get("type")
    if kind == LEVEL_BELOW:
        return _below(chars, rule.get("value"))
    if kind in SCOPE_TYPES:
        return tile_rules.members(chars, kind, rule.get("value"))
    return []


# ------------------------------------------------------------- the list the window shows and changes
# The window shows the rules as a list; a person adds a rule (a type, a value, the targets it is for) or takes marked ones away, and the window applies the
# list when told to. These functions make the new list, so the window decides nothing. They return a new list and never change the one given; a rule they
# do not touch (another type, a value the database does not have, a type this program does not know) stays as it is and in its place.

def targets_of(rule) -> tuple:
    """The targets (of TARGETS, in their order) a rule is meant for; none for anything that is no rule."""
    return tuple(target for target in TARGETS if isinstance(rule, dict) and applies(rule, target))


def _rule(kind: str, value: str, targets) -> dict:
    """A rule for these targets: without "for" when it is for all of them, else with the list."""
    chosen = [target for target in TARGETS if target in targets]
    rule = {"type": kind, "value": value}
    if chosen != list(TARGETS):
        rule["for"] = chosen
    return rule


def add_rule(rules, kind: str, value, targets) -> list:
    """New rules with this rule added at the end. A rule of the same type and value is not added twice: the first one that exists takes the targets as well
    and keeps its place. Nothing is added (the rules come back as they were) for a type this program does not know, a value that is no text, a level
    that is no whole number above 0, or no target that is one of TARGETS."""
    rules = list(rules or ())
    wanted = {target for target in (targets or ()) if target in TARGETS}
    if kind == LEVEL_BELOW:
        limit = _limit(value)
        value = str(limit) if limit else None                      # " 20 " is 20; 0, text and a missing number are no level
    if kind not in TYPES or not isinstance(value, str) or not wanted:
        return rules
    for position, rule in enumerate(rules):
        if isinstance(rule, dict) and rule.get("type") == kind and rule.get("value") == value:
            rules[position] = _rule(kind, value, set(targets_of(rule)) | wanted)
            return rules
    rules.append(_rule(kind, value, wanted))
    return rules


def remove_rules(rules, positions) -> list:
    """New rules without the ones at these positions (a position the list does not have is ignored)."""
    drop = set(positions or ())
    return [rule for position, rule in enumerate(rules or ()) if position not in drop]


def hidden_keys(chars: list, rules, target: str) -> set:
    """The keys of the characters (of `chars`, each with "key" and the fields the types read) that the rules keep out of this output.
    No rules (None, empty) and a target this program does not know hide nobody; an entry that is no rule, or of an unknown type, is skipped."""
    if not rules or target not in TARGETS:
        return set()
    hidden = set()
    for rule in rules:
        if isinstance(rule, dict) and applies(rule, target):
            hidden.update(c["key"] for c in named_by(chars, rule))
    return hidden
