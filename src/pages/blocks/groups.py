#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)
# groups.py
# StatTracker - the block "Groups" of the stats page: the ticked characters grouped by class, race, faction or realm, with the figures
# of group_rules (characters, average level, played time, rates, statistics added by hand), the pick of the groups shown, the
# presets, and the table with its total. It replaces the script of the page (renderGroups and its helpers) with the same elements,
# ids and classes. render() gives the whole block; handle() answers an action of the page (a click, a change) with the parts of
# the block that changed ("updates": element id, new inner HTML, hidden, disabled), so the page only puts them in.
# The state (grouping, groups and figures unticked, statistics added) lives in View.states, the ticked characters in the View.
# Texts are the html_* texts of the payload ("ui"), numbers are written in the language of the page (numfmt).
# Needs markup, view, group_rules, numfmt.

from pages.blocks.cells import DASH, agg_labels, by_labels, cell_text, factions, number
from pages.blocks.markup import esc, fmt, plain, ui
from pages.blocks.view import View
from rules import group_rules as rules
from rules import numfmt

USES_SELECTION = True               # layout.select calls handle(..., "selection", ...) when the ticked characters change
NAME_MAX = 40                       # longest name of a preset when the program gives no store


class State:
    def __init__(self):
        self.by = "class"
        self.hidden = {}            # grouping -> keys of the groups unticked (None = the unknown group)
        self.figures_off = set()    # ids of the standard figures unticked
        self.extras = []            # statistics added by hand: (stat id, aggregate)


# ----------------------------------------------------------------------------------------------------------------- texts
def _figure_label(payload, figure) -> str:
    if figure.agg:
        return f"{figure.label} ({agg_labels(payload)[figure.agg]})"
    return figure.label or {"groups_fig_chars": ui(payload, "groups_fig_chars"), "groups_fig_level": ui(payload, "groups_fig_level"),
                            "groups_fig_played": ui(payload, "groups_fig_played")}[figure.label_key]


def _cell_html(payload, cell) -> str:
    text, small = cell_text(payload, cell)
    return f'<td class="num">{esc(text)}' + (f'<span class="small">{esc(small)}</span>' if small else "") + "</td>"


# -------------------------------------------------------------------------------------------------------------------- data
class Data:
    """What one answer needs, worked out once: the ticked characters, the groups of the chosen grouping, the figures shown."""

    def __init__(self, payload, view, state):
        stats = payload.get("stats") or []
        self.stats_by_id = {s["id"]: s for s in stats}
        self.chars = view.chars()
        self.groups = rules.build_groups(self.chars, state.by, payload.get("names") or {}, factions(payload), ui(payload, "groups_unknown"))
        self.hidden = state.hidden.setdefault(state.by, set())
        self.standard = rules.standard_figures(stats, payload.get("derived"))
        self.extra = [rules.extra_figure(self.stats_by_id.get(i), i, agg) for i, agg in state.extras]
        self.figures = [f for f in self.standard if f.id not in state.figures_off] + self.extra
        self.stats = stats


# ----------------------------------------------------------------------------------------------------------------- regions
def _options(items, selected) -> str:
    return "".join(f'<option value="{esc(value)}"{" selected" if value == selected else ""}>{esc(text)}</option>' for value, text in items)


def _region_by(payload, view, state, data, **_):
    return {"id": "groupBy", "html": _options(by_labels(payload).items(), state.by)}


def _region_pick(payload, view, state, data, **_):
    parts = [f'<span class="lbl">{esc(ui(payload, "groups_pick"))}</span>']
    for group in data.groups:
        checked = "" if group.key in data.hidden else " checked"
        key = "" if group.key is None else group.key
        parts.append(f'<label><input type="checkbox" data-action="group" data-key="{esc(key)}"{checked}> {esc(group.label)} ({len(group.members)})</label>')
    return {"id": "groupPick", "html": "".join(parts)}


def _region_figures(payload, view, state, data, **_):
    parts = [f'<span class="lbl">{esc(ui(payload, "groups_figures"))}</span>']
    for figure in data.standard:
        checked = "" if figure.id in state.figures_off else " checked"
        parts.append(f'<label><input type="checkbox" id="fig_{esc(figure.id)}" data-action="figure" data-id="{esc(figure.id)}"{checked}>'
                     f' {esc(_figure_label(payload, figure))}</label>')
    return {"id": "figures", "html": "".join(parts)}


def _region_xstat(payload, view, state, data, controls=None, **_):
    query = (controls or {}).get("query") or ""
    keep = (controls or {}).get("xstat") or ""
    items = [(str(s["id"]), f'{s["name"]} ({s["cat"]})') for s in rules.offered_stats(data.stats, data.chars, query)]
    return {"id": "xstat", "html": _options(items, keep)}


def _region_chips(payload, view, state, data, **_):
    parts = []
    for index, figure in enumerate(data.extra):
        parts.append(f'<span class="chip">{esc(_figure_label(payload, figure))}'
                     f'<button type="button" title="{esc(ui(payload, "groups_remove"))}" data-action="remove" data-index="{index}">×</button></span>')
    return {"id": "extraChips", "html": "".join(parts), "hidden": not data.extra}


def _table_html(payload, data) -> str:
    head = [f'<th>{esc(ui(payload, "groups_col_group"))}</th>']
    for figure in data.figures:
        small = f'<span class="small">{esc(figure.cat)}</span>' if figure.cat else ""
        head.append(f'<th class="num">{esc(_figure_label(payload, figure))}{small}</th>')
    table = rules.build_table(data.groups, data.hidden, data.figures)
    rows = [f'<tr><td>{esc(row.group.label)}</td>' + "".join(_cell_html(payload, c) for c in row.cells) + "</tr>" for row in table.rows]
    if table.total is not None:
        rows.append(f'<tr class="total"><td>{esc(ui(payload, "rates_total"))}</td>' + "".join(_cell_html(payload, c) for c in table.total) + "</tr>")
    return f'<table id="gt"><thead><tr>{"".join(head)}</tr></thead><tbody>{"".join(rows)}</tbody></table>'


def _region_table(payload, view, state, data, **_):
    """The table (or, with no character ticked, the notice): two elements, so two updates."""
    if data.chars:
        return [{"id": "groupsNone", "html": "", "hidden": True}, {"id": "groupsWrap", "html": _table_html(payload, data), "hidden": False}]
    return [{"id": "groupsNone", "html": esc(ui(payload, "groups_none_selected")), "hidden": False},
            {"id": "groupsWrap", "html": '<table id="gt"><thead></thead><tbody></tbody></table>', "hidden": True}]


def _region_presets(payload, view, state, data, keep="", message="", **_):
    names = [p["name"] for p in view.presets.load()] if view.presets else []
    items = [("", ui(payload, "groups_preset_none"))] + [(n, n) for n in names]
    chosen = keep if keep in names else ""
    return [{"id": "presetBox", "hidden": view.presets is None}, {"id": "presetSel", "html": _options(items, chosen)},
            {"id": "presetDel", "disabled": chosen == ""}, {"id": "presetMsg", "html": esc(message)}]


REGIONS = {"groupBy": _region_by, "groupPick": _region_pick, "figures": _region_figures, "xstat": _region_xstat,
           "extraChips": _region_chips, "table": _region_table, "presets": _region_presets}


def _updates(payload, view, state, names, **options):
    data = Data(payload, view, state)
    found = []
    for name in names:
        result = REGIONS[name](payload, view, state, data, **options)
        found.extend(result if isinstance(result, list) else [result])
    return found


# ----------------------------------------------------------------------------------------------------------------- the block
def new_state() -> State:
    return State()


def render(payload, view=None, slot=None, **_):
    """The whole block, as the page shows it at the start (every character ticked, the first grouping, nothing added); for a snapshot as the View says,
    with the search, the statistic and the function chosen for a statistic to add (the controls the page last sent)."""
    view = view or View(payload)
    state = view.state(slot, new_state)
    controls = view.controls.get(slot) or {}
    parts = {u["id"]: u for u in _updates(payload, view, state, REGIONS, controls=controls)}
    query = f' value="{esc(controls.get("query") or "")}"' if controls.get("query") else ""
    agg = controls.get("xagg") if controls.get("xagg") in agg_labels(payload) else "sum"
    name_max = view.presets.name_max if view.presets is not None else NAME_MAX
    hours = plain((payload.get("derived") or {}).get("min_played_seconds", 3600) / 3600)

    def inner(element):
        return parts[element].get("html", "")

    def flag(element, key="hidden"):
        return f" {key}" if parts[element].get(key) else ""

    return (
        '<details class="rates groups" id="groups">\n'
        f'  <summary id="groupsTitle">{esc(ui(payload, "groups_title"))}</summary>\n'
        f'  <div id="presetBox"{flag("presetBox")}>\n'
        '    <div class="gbar">\n'
        f'      <span class="lbl" id="lblPreset">{esc(ui(payload, "groups_preset"))}</span>\n'
        f'      <select id="presetSel" data-name="preset" data-action="preset_apply">{inner("presetSel")}</select>\n'
        f'      <input type="search" id="presetName" data-name="name" maxlength="{name_max}" placeholder="{esc(ui(payload, "groups_preset_name"))}">\n'
        f'      <button type="button" id="presetSave" data-action="preset_save">{esc(ui(payload, "groups_preset_save"))}</button>\n'
        f'      <button type="button" id="presetDel" data-action="preset_delete"{flag("presetDel", "disabled")}>{esc(ui(payload, "groups_preset_delete"))}</button>\n'
        f'      <span class="lbl" id="presetMsg">{inner("presetMsg")}</span>\n'
        '    </div>\n'
        f'    <div class="note" id="presetNote">{esc(ui(payload, "groups_preset_note"))}</div>\n'
        '  </div>\n'
        f'  <div class="gbar"><span class="lbl" id="lblGroupBy">{esc(ui(payload, "groups_by"))}</span>'
        f'<select id="groupBy" data-name="by" data-action="by">{inner("groupBy")}</select></div>\n'
        f'  <div class="gbar" id="groupPick">{inner("groupPick")}</div>\n'
        f'  <div class="gbar" id="figures">{inner("figures")}</div>\n'
        '  <div class="gbar">\n'
        f'    <span class="lbl" id="lblExtra">{esc(ui(payload, "groups_extra"))}</span>\n'
        f'    <input type="search" id="xq" data-name="query" data-action="query" placeholder="{esc(ui(payload, "search"))}"{query}>\n'
        f'    <select id="xstat" data-name="xstat">{inner("xstat")}</select>\n'
        f'    <select id="xagg" data-name="xagg">{_options(agg_labels(payload).items(), agg)}</select>\n'
        f'    <button type="button" id="xadd" data-action="add">{esc(ui(payload, "groups_add"))}</button>\n'
        '  </div>\n'
        f'  <div class="gbar" id="extraChips"{flag("extraChips")}>{inner("extraChips")}</div>\n'
        f'  <div class="note" id="extraNote">{esc(ui(payload, "groups_extra_note"))}</div>\n'
        f'  <div class="gnone" id="groupsNone"{flag("groupsNone")}>{inner("groupsNone")}</div>\n'
        f'  <div class="rwrap" id="groupsWrap"{flag("groupsWrap")}>{inner("groupsWrap")}</div>\n'
        f'  <div class="note" id="groupsNote">{esc(fmt(ui(payload, "groups_note"), hours=hours))}</div>\n'
        '</details>')


# --------------------------------------------------------------------------------------------------------------- the answers
def _toggle(items, key, on):
    if on:
        items.discard(key)
    else:
        items.add(key)


def _preset_entry(state, standard) -> dict:
    return {"name": "", "by": state.by, "off": [f.id for f in standard if f.id in state.figures_off],
            "extras": [{"id": i, "agg": agg} for i, agg in state.extras]}


def _apply_preset(payload, state, preset) -> None:
    """Figures and statistics this page does not have are skipped; the groups unticked stay as they are."""
    if preset.get("by") in rules.GROUP_BY:
        state.by = preset["by"]
    known = {f.id for f in rules.standard_figures(payload.get("stats") or [], payload.get("derived"))}
    state.figures_off = {i for i in preset.get("off") or [] if i in known}
    stat_ids = {s["id"] for s in payload.get("stats") or []}
    state.extras = []
    for item in preset.get("extras") or []:
        if not isinstance(item, dict):
            continue
        number, agg = item.get("id"), item.get("agg")
        if rules.is_number(number) and number >= 0 and number in stat_ids and agg in rules.AGGREGATES and (number, agg) not in state.extras:
            state.extras.append((int(number), agg))


def handle(payload, view, slot, action, args):
    """The parts of the block that change after `action` (see the header). args: {"value", "checked", "controls", plus the data-* of the
    element}; controls = the values of the elements of the block that carry data-name (by, query, xstat, xagg, preset, name)."""
    state = view.state(slot, new_state)
    controls = args.get("controls") or {}
    keep = {"controls": controls}
    if action == "by":
        if args.get("value") in rules.GROUP_BY:
            state.by = args["value"]
        return _updates(payload, view, state, ("groupPick", "table"), **keep)
    if action == "group":
        key = args.get("key") or None
        _toggle(state.hidden.setdefault(state.by, set()), key, bool(args.get("checked")))
        return _updates(payload, view, state, ("table",), **keep)
    if action == "figure":
        _toggle(state.figures_off, args.get("id"), bool(args.get("checked")))
        return _updates(payload, view, state, ("table",), **keep)
    if action == "query":
        return _updates(payload, view, state, ("xstat",), **keep)
    if action == "add":
        agg, raw = controls.get("xagg"), controls.get("xstat")
        if raw in (None, "") or agg not in rules.AGGREGATES or not str(raw).isdigit() or (int(raw), agg) in state.extras:
            return []
        state.extras.append((int(raw), agg))
        return _updates(payload, view, state, ("extraChips", "table"), **keep)
    if action == "remove":
        index = str(args.get("index"))
        if index.isdigit() and int(index) < len(state.extras):
            del state.extras[int(index)]
        return _updates(payload, view, state, ("extraChips", "table"), **keep)
    if action == "selection":
        return _updates(payload, view, state, ("groupPick", "xstat", "table"), **keep)
    if action == "attach":                    # the page is shown in a window: the presets of the program replace the first state
        return _updates(payload, view, state, ("presets",), **keep)
    if action.startswith("preset_") and view.presets is not None:
        return _preset_action(payload, view, state, action, controls)
    return []


def _preset_action(payload, view, state, action, controls):
    store = view.presets
    standard = rules.standard_figures(payload.get("stats") or [], payload.get("derived"))
    if action == "preset_apply":
        name = controls.get("preset") or ""
        found = next((p for p in store.load() if p["name"] == name), None)
        if found:
            _apply_preset(payload, state, found)
        return _updates(payload, view, state, ("groupBy", "figures", "groupPick", "extraChips", "table", "presets"),
                        controls=controls, keep=name if found else "", message="")
    if action == "preset_save":
        name = (controls.get("name") or "").strip()[:store.name_max]
        if not name:
            return []
        entry = _preset_entry(state, standard)
        entry["name"] = name
        presets = store.load()
        index = next((i for i, p in enumerate(presets) if p["name"] == name), -1)
        if index >= 0:
            presets[index] = entry
        else:
            presets.append(entry)
        saved = store.save(presets)
        return _updates(payload, view, state, ("presets",), controls=controls, keep=name,
                        message="" if saved else ui(payload, "groups_preset_failed"))
    if action == "preset_delete":
        name = controls.get("preset") or ""
        if name == "":
            return []
        saved = store.save([p for p in store.load() if p["name"] != name])
        return _updates(payload, view, state, ("presets",), controls=controls, keep="",
                        message="" if saved else ui(payload, "groups_preset_failed"))
    return []
