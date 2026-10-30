# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)
# Builds the real main window in a temporary instance (skipped without a working Tk).
# One window is shared by all tests of this module: creating several Tk roots in one
# process is unreliable on some Windows Python installs.

import shutil
import tkinter as tk
import urllib.error
from types import SimpleNamespace

import pytest

import app_info
import config
import gui_app
import i18n
import paths
import wow_install
from conftest import ROOT, make_fake_wow


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    mp = pytest.MonkeyPatch()
    base = tmp_path_factory.mktemp("instance")
    wow = make_fake_wow(tmp_path_factory.mktemp("wowroot") / "World of Warcraft")
    mp.setattr(paths, "base_dir", lambda: base)
    mp.setattr(wow_install, "WOW_CANDIDATES", ())
    (base / "addon").mkdir()
    shutil.copytree(ROOT / "addon" / "StatTracker", base / "addon" / "StatTracker")
    cfg, _ = config.load()
    cfg.update(wow_dir=str(wow), language="en", check_updates=False)
    config.save(cfg)
    try:
        window = gui_app.App()
    except tk.TclError as exc:
        mp.undo()
        pytest.skip(f"no usable Tk: {exc}")
    window.update()
    yield SimpleNamespace(app=window, wow=wow, base=base)
    window.destroy()
    mp.undo()


@pytest.fixture
def app(env):
    """The shared window, reset to a known state before each test."""
    a = env.app
    i18n.set_language("en")
    a.cfg["language"] = "en"
    a.var_lang.set("English")
    a.cfg["enabled_variants"] = ["_retail_"]
    a.var_wow.set(str(env.wow))
    a._rebuild()
    wow_install.uninstall_addon(env.wow, "_retail_")
    a.refresh_variants(keep="_retail_")
    a.update()
    return a


def test_default_shows_retail_only(app):
    assert list(app.cmb_var["values"]) == ["_retail_"]
    assert app.var_variant.get() == "_retail_"
    assert app.var_acc.get() == "ACC1"
    assert "Addon: not installed" in app.var_status.get()


def test_enabling_another_version_adds_it_to_the_dropdown(app):
    app.cfg["enabled_variants"] = ["_retail_", "_forever_"]
    app.refresh_variants()
    assert list(app.cmb_var["values"]) == ["_retail_", "_forever_"]


def test_typed_in_disabled_version_is_reported(app, env):
    app.var_wow.set(str(env.wow / "_forever_"))
    app.update()
    assert app.root_and_variant() == (env.wow, None)
    assert "not enabled" in app.var_status.get()


def test_install_then_uninstall_through_the_window(app, env, monkeypatch):
    monkeypatch.setattr(gui_app.messagebox, "askyesno", lambda *a, **k: True)
    app.on_install()
    assert wow_install.addon_dir(env.wow, "_retail_").is_dir()
    assert f"Addon: version {app_info.APP_VERSION}" in app.var_status.get()
    app.on_uninstall()
    assert not wow_install.addon_dir(env.wow, "_retail_").exists()
    assert "Addon: not installed" in app.var_status.get()


def test_status_shows_a_wrong_interface_number_until_reinstalled(app, env):
    app.on_install()
    toc = wow_install.addon_dir(env.wow, "_retail_") / "StatTracker.toc"
    toc.write_text(toc.read_text(encoding="utf-8").replace("## Interface: 120105", "## Interface: 120000"),
                   encoding="utf-8")
    app.update_status()
    assert "interface number does not match the game (installed 120000, game 120105)" in app.var_status.get()
    app.on_install()
    assert "Addon: version" in app.var_status.get()


def _newer_release_with_dialog(app, monkeypatch, choice):
    """Stubs the update dialog and the download; returns the lists of dialogs shown and updates started."""
    shown, started = [], []
    monkeypatch.setattr(gui_app.gui_dialogs, "ask_update", lambda *a, **k: shown.append(a) or choice)
    monkeypatch.setattr(app, "_start_update", lambda data, tag: started.append(tag))
    return {"tag_name": "v9.9.9", "name": "StatTracker 9.9.9"}, shown, started


def test_overlapping_update_checks_open_only_one_dialog(app, monkeypatch):
    """Start check + manual check both queue a release; the second must not open a second dialog or download."""
    data, shown, started = _newer_release_with_dialog(app, monkeypatch, "update")
    app._update_open = False
    try:
        app._on_release(data, False)
        app._on_release(data, True)
        assert len(shown) == 1 and started == ["v9.9.9"]
    finally:
        app._update_open = False


def test_update_dialog_can_be_reopened_after_later(app, monkeypatch):
    data, shown, started = _newer_release_with_dialog(app, monkeypatch, None)
    app._update_open = False
    app._on_release(data, True)
    app._on_release(data, True)
    assert len(shown) == 2 and not started


def test_update_check_is_passive_while_repo_is_unconfirmed(app, monkeypatch):
    monkeypatch.setattr(app_info, "REPO_CONFIRMED", False)
    monkeypatch.setattr(gui_app.updater, "fetch_latest_release",
                        lambda *a, **k: pytest.fail("no request may be sent"))
    shown = []
    monkeypatch.setattr(gui_app.messagebox, "showinfo", lambda *a, **k: shown.append(a))
    app.check_updates(manual=True)
    assert shown and "placeholder" in shown[0][1]


def _checked(app, monkeypatch, error):
    """Runs the update check with fetch_latest_release failing with `error`; returns the queued result."""
    def fail(*_a, **_k):
        raise error
    monkeypatch.setattr(app_info, "REPO_CONFIRMED", True)
    monkeypatch.setattr(gui_app.updater, "fetch_latest_release", fail)
    app.check_updates(manual=True)
    return app._queue.get(timeout=5)          # no event loop runs here, so _poll_queue does not steal it


def test_repository_without_a_release_counts_as_up_to_date(app, monkeypatch):
    err = urllib.error.HTTPError("https://api.github.com/x", 404, "Not Found", None, None)
    assert _checked(app, monkeypatch, err) == ("release", {}, True)


def test_other_http_errors_are_reported(app, monkeypatch):
    err = urllib.error.HTTPError("https://api.github.com/x", 403, "rate limit", None, None)
    kind, message, manual = _checked(app, monkeypatch, err)
    assert kind == "update_error" and "403" in message and manual is True


def test_network_errors_are_reported(app, monkeypatch):
    kind, message, _manual = _checked(app, monkeypatch, OSError("offline"))
    assert kind == "update_error" and "offline" in message


def test_language_switch_rebuilds_the_window_and_keeps_the_log(app):
    app.write("hello log")
    app.var_lang.set("Deutsch")
    app.on_language()
    app.update()
    assert i18n.get_language() == "de"
    assert "hello log" in app.log.get("1.0", "end")
    assert "Addon: nicht installiert" in app.var_status.get()
    assert config.load()[0]["language"] == "de"
