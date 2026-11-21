# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

import shutil

import pytest

from core import paths
from game import wow_install


def test_list_variants_filters_by_enabled(fake_wow):
    assert wow_install.list_variants(fake_wow) == ["_retail_", "_classic_", "_forever_"]
    assert wow_install.list_variants(fake_wow, ["_retail_"]) == ["_retail_"]
    assert wow_install.list_variants(fake_wow, []) == []
    assert wow_install.list_variants(None) == []


def test_resolve_root_accepts_main_or_variant_folder(fake_wow):
    assert wow_install.resolve_root(str(fake_wow)) == (fake_wow, None)
    assert wow_install.resolve_root(str(fake_wow / "_retail_")) == (fake_wow, "_retail_")
    assert wow_install.resolve_root("") == (None, None)
    assert wow_install.resolve_root(str(fake_wow / "missing")) == (None, None)


def test_interface_number_and_build_info(fake_wow):
    assert wow_install.interface_number("12.1.5.70575") == 120105
    assert wow_install.interface_number("nonsense") is None
    assert wow_install.parse_build_info(fake_wow) == {"wow": "12.1.5.70575", "wowf": "1.600.1.1234"}


def test_out_files_live_in_data_dir(instance):
    db, html = wow_install.out_files("_retail_")
    assert (db.name, html.name) == ("wow_stats.db", "stats.html")
    assert db.parent == instance / "data"
    assert wow_install.out_files("_forever_")[0].name == "wow_stats_forever.db"
    assert wow_install.out_files("_forever_")[1].name == "stats_forever.html"


def test_install_sets_interface_number_in_the_copy_only(instance, fake_wow):
    res = wow_install.install_addon(fake_wow, "_retail_")
    toc = (res.dest / "StatTracker.toc").read_text(encoding="utf-8")
    assert "## Interface: 120105" in toc and res.number == 120105
    # bundled source stays pristine
    assert "## Interface: 120105" in (instance / "addon" / "StatTracker" / "StatTracker.toc").read_text(encoding="utf-8")
    assert (res.dest / "StatTracker.lua").is_file()


def test_install_unknown_product_leaves_interface_alone(instance, fake_wow):
    (fake_wow / "_classic_" / "Interface" / "AddOns").mkdir(parents=True)
    res = wow_install.install_addon(fake_wow, "_classic_")
    assert res.number is None and res.product == "wow_classic"


def _set_installed_version(res, version):
    toc = res.dest / "StatTracker.toc"
    toc.write_text(toc.read_text(encoding="utf-8").replace(f"## Version: {wow_install.toc_version(toc)}", f"## Version: {version}"),
                   encoding="utf-8")


def test_install_leaves_an_installed_addon_alone_that_is_newer_than_the_source(instance, fake_wow):
    res = wow_install.install_addon(fake_wow, "_retail_")
    assert res.kept is False
    _set_installed_version(res, "99.0.0")
    (res.dest / "StatTracker.lua").write_text("-- from an addon manager", encoding="utf-8")
    toc_before = (res.dest / "StatTracker.toc").read_bytes()
    again = wow_install.install_addon(fake_wow, "_retail_")
    assert again.kept is True and again.installed_version == "99.0.0" and again.bundled_version == _bundled_version()
    assert again.number is None and again.dest == res.dest
    assert (res.dest / "StatTracker.toc").read_bytes() == toc_before                 # no interface number written either
    assert (res.dest / "StatTracker.lua").read_text(encoding="utf-8") == "-- from an addon manager"


@pytest.mark.parametrize("installed", ["same", "0.0.1", "0.2.3-beta", "beta"])
def test_install_copies_over_the_same_an_older_or_an_unreadable_version(instance, fake_wow, installed):
    installed = _bundled_version() if installed == "same" else installed
    res = wow_install.install_addon(fake_wow, "_retail_")
    _set_installed_version(res, installed)
    (res.dest / "StatTracker.lua").write_text("-- damaged", encoding="utf-8")
    again = wow_install.install_addon(fake_wow, "_retail_")
    assert again.kept is False and again.number == 120105
    assert (res.dest / "StatTracker.lua").read_bytes() == (paths.addon_src() / "StatTracker.lua").read_bytes()
    assert wow_install.toc_version(res.dest / "StatTracker.toc") == _bundled_version()


def test_install_copies_when_the_installed_addon_has_no_toc_or_no_version(instance, fake_wow):
    dest = wow_install.addon_dir(fake_wow, "_retail_")
    dest.mkdir(parents=True)
    (dest / "StatTracker.lua").write_text("-- broken", encoding="utf-8")                # no .toc at all
    assert wow_install.install_addon(fake_wow, "_retail_").kept is False
    (dest / "StatTracker.toc").write_text("## Title: x\n", encoding="utf-8")            # a .toc without a version
    assert wow_install.install_addon(fake_wow, "_retail_").kept is False
    assert wow_install.toc_version(dest / "StatTracker.toc") == _bundled_version()


def test_install_from_another_source_follows_the_same_rule(instance, fake_wow, tmp_path):
    src = tmp_path / "newer"
    shutil.copytree(paths.addon_src(), src)
    toc = src / "StatTracker.toc"
    toc.write_text(toc.read_text(encoding="utf-8").replace(f"## Version: {_bundled_version()}", "## Version: 98.0.0"), encoding="utf-8")
    res = wow_install.install_addon(fake_wow, "_retail_")                                # the bundled one is installed
    again = wow_install.install_addon(fake_wow, "_retail_", addon_src=src)              # a newer source is copied
    assert again.kept is False and wow_install.toc_version(res.dest / "StatTracker.toc") == "98.0.0"
    assert wow_install.install_addon(fake_wow, "_retail_").kept is True                 # and the bundled one no longer overwrites it


BOM = b"\xef\xbb\xbf"


def _with_bom(toc):
    toc.write_bytes(BOM + toc.read_bytes().removeprefix(BOM))


def test_a_toc_with_a_byte_order_mark_is_read_and_patched_in_its_first_line(tmp_path):
    toc = tmp_path / "StatTracker.toc"
    toc.write_bytes(BOM + b"## Interface: 120000, 16001\r\n## Version: 1.2.3\r\n")
    assert wow_install.toc_interface(toc) == [120000, 16001]
    assert wow_install.toc_version(toc) == "1.2.3"
    wow_install.patch_toc_interface(toc, 120105)
    assert wow_install.toc_interface(toc) == [120105] and wow_install.toc_version(toc) == "1.2.3"
    assert not toc.read_bytes().startswith(BOM) and toc.read_bytes().startswith(b"## Interface: 120105")


def test_a_version_in_the_first_line_is_read_with_or_without_a_byte_order_mark(tmp_path):
    toc = tmp_path / "StatTracker.toc"
    toc.write_bytes(BOM + b"## Version: 4.5.6\r\n## Interface: 120105\r\n")
    assert wow_install.toc_version(toc) == "4.5.6"
    toc.write_bytes(b"## Version: 4.5.6\r\n## Interface: 120105\r\n")
    assert wow_install.toc_version(toc) == "4.5.6"


def test_install_works_with_a_source_toc_that_has_a_byte_order_mark(instance, fake_wow):
    _with_bom(instance / "addon" / "StatTracker" / "StatTracker.toc")
    res = wow_install.install_addon(fake_wow, "_retail_")
    assert res.number == 120105 and wow_install.toc_interface(res.dest / "StatTracker.toc") == [120105]
    assert wow_install.addon_status(fake_wow, "_retail_")[0] == "ok"


def test_the_status_reads_the_interface_of_an_installed_toc_with_a_byte_order_mark(instance, fake_wow):
    res = wow_install.install_addon(fake_wow, "_retail_")
    toc = res.dest / "StatTracker.toc"
    toc.write_text(toc.read_text(encoding="utf-8").replace("## Interface: 120105", "## Interface: 120000"), encoding="utf-8")
    _with_bom(toc)
    assert wow_install.addon_status(fake_wow, "_retail_") == ("interface", 120000, 120105)


def test_install_requires_addons_folder(instance, fake_wow):
    with pytest.raises(RuntimeError):
        wow_install.install_addon(fake_wow, "_anniversary_")


def _bundled_version():
    """The '## Version:' of the addon the program carries (its own number, not APP_VERSION)."""
    return wow_install.toc_version(paths.addon_src() / "StatTracker.toc")


def test_addon_status(instance, fake_wow):
    assert wow_install.addon_status(fake_wow, "_retail_") == ("missing",)
    res = wow_install.install_addon(fake_wow, "_retail_")
    assert wow_install.addon_status(fake_wow, "_retail_")[0] == "ok"
    toc = res.dest / "StatTracker.toc"
    toc.write_text(toc.read_text(encoding="utf-8").replace(
        f"## Version: {_bundled_version()}", "## Version: 0.0.1"), encoding="utf-8")
    status = wow_install.addon_status(fake_wow, "_retail_")
    assert status[0] == "outdated" and status[1] == "0.0.1"


def test_addon_status_accepts_an_installed_addon_that_is_newer_than_the_bundled_one(instance, fake_wow):
    res = wow_install.install_addon(fake_wow, "_retail_")
    toc = res.dest / "StatTracker.toc"
    toc.write_text(toc.read_text(encoding="utf-8").replace(
        f"## Version: {_bundled_version()}", "## Version: 99.0.0"), encoding="utf-8")
    assert wow_install.addon_status(fake_wow, "_retail_") == ("ok", "99.0.0")


def test_addon_status_calls_two_different_versions_outdated_when_one_cannot_be_read(instance, fake_wow):
    res = wow_install.install_addon(fake_wow, "_retail_")
    toc = res.dest / "StatTracker.toc"
    toc.write_text(toc.read_text(encoding="utf-8").replace(
        f"## Version: {_bundled_version()}", "## Version: 0.2.3-beta"), encoding="utf-8")
    assert wow_install.addon_status(fake_wow, "_retail_")[0] == "outdated"


def _set_toc_interface(toc, value):
    text = toc.read_text(encoding="utf-8")
    toc.write_text(text.replace("## Interface: 120105", f"## Interface: {value}"), encoding="utf-8")


def test_toc_interface_reads_one_or_several_numbers(tmp_path):
    toc = tmp_path / "a.toc"
    toc.write_text("## Interface: 120105\n## Title: x\n", encoding="utf-8")
    assert wow_install.toc_interface(toc) == [120105]
    toc.write_text("## Interface: 110207, 120105\n## Title: x\n", encoding="utf-8")
    assert wow_install.toc_interface(toc) == [110207, 120105]
    toc.write_text("## Title: x\n", encoding="utf-8")
    assert wow_install.toc_interface(toc) is None
    assert wow_install.toc_interface(tmp_path / "missing.toc") is None


def test_addon_status_flags_a_wrong_interface_number(instance, fake_wow):
    res = wow_install.install_addon(fake_wow, "_retail_")
    _set_toc_interface(res.dest / "StatTracker.toc", 120000)
    assert wow_install.addon_status(fake_wow, "_retail_") == ("interface", 120000, 120105)
    # reinstalling patches the number again
    wow_install.install_addon(fake_wow, "_retail_")
    assert wow_install.addon_status(fake_wow, "_retail_")[0] == "ok"


def test_addon_status_interface_follows_build_info(instance, fake_wow):
    wow_install.install_addon(fake_wow, "_retail_")
    (fake_wow / ".build.info").write_text(
        "Branch!STRING:0|Active!DEC:1|Product!STRING:0|Version!STRING:0\n"
        "eu|1|wow|12.2.0.70000\n", encoding="utf-8")   # a game patch happened
    assert wow_install.addon_status(fake_wow, "_retail_") == ("interface", 120105, 120200)


def test_addon_status_accepts_a_list_containing_the_expected_number(instance, fake_wow):
    res = wow_install.install_addon(fake_wow, "_retail_")
    _set_toc_interface(res.dest / "StatTracker.toc", "110207, 120105")
    assert wow_install.addon_status(fake_wow, "_retail_")[0] == "ok"
    toc = res.dest / "StatTracker.toc"
    toc.write_text(toc.read_text(encoding="utf-8").replace("110207, 120105", "110207, 120000"), encoding="utf-8")
    assert wow_install.addon_status(fake_wow, "_retail_") == ("interface", 110207, 120105)


def test_addon_status_skips_interface_check_when_build_is_unknown(instance, fake_wow):
    res = wow_install.install_addon(fake_wow, "_retail_")
    _set_toc_interface(res.dest / "StatTracker.toc", 120000)
    (fake_wow / ".build.info").unlink()
    assert wow_install.addon_status(fake_wow, "_retail_")[0] == "ok"
    (fake_wow / ".build.info").write_text(            # file present, but no row for this product
        "Branch!STRING:0|Active!DEC:1|Product!STRING:0|Version!STRING:0\n"
        "eu|1|wowf|1.600.1.1234\n", encoding="utf-8")
    assert wow_install.addon_status(fake_wow, "_retail_")[0] == "ok"


def test_addon_status_outdated_wins_over_interface(instance, fake_wow):
    res = wow_install.install_addon(fake_wow, "_retail_")
    toc = res.dest / "StatTracker.toc"
    text = toc.read_text(encoding="utf-8").replace(f"## Version: {_bundled_version()}", "## Version: 0.0.1")
    toc.write_text(text.replace("## Interface: 120105", "## Interface: 120000"), encoding="utf-8")
    assert wow_install.addon_status(fake_wow, "_retail_")[0] == "outdated"


def test_uninstall_removes_addon_but_keeps_everything_else(instance, fake_wow):
    wow_install.install_addon(fake_wow, "_retail_")
    sv = wow_install.saved_vars_path(fake_wow / "_retail_", "ACC1")
    sv.write_text("StatTrackerDB = {}", encoding="utf-8")
    (instance / "data").mkdir()
    db = instance / "data" / "wow_stats.db"
    db.write_text("history", encoding="utf-8")

    res = wow_install.uninstall_addon(fake_wow, "_retail_")
    assert res.removed_addon and not res.removed_files
    assert not wow_install.addon_dir(fake_wow, "_retail_").exists()
    assert sv.is_file() and db.read_text(encoding="utf-8") == "history"


def test_uninstall_can_remove_saved_variables(instance, fake_wow):
    wow_install.install_addon(fake_wow, "_retail_")
    sv_dir = fake_wow / "_retail_" / "WTF" / "Account" / "ACC1" / "SavedVariables"
    (sv_dir / "StatTracker.lua").write_text("x", encoding="utf-8")
    (sv_dir / "StatTracker.lua.bak").write_text("x", encoding="utf-8")
    (sv_dir / "OtherAddon.lua").write_text("keep", encoding="utf-8")

    res = wow_install.uninstall_addon(fake_wow, "_retail_", remove_saved_vars=True)
    assert len(res.removed_files) == 2
    assert (sv_dir / "OtherAddon.lua").is_file()
    assert not (sv_dir / "StatTracker.lua").exists()


def test_uninstall_when_not_installed_is_a_noop(instance, fake_wow):
    res = wow_install.uninstall_addon(fake_wow, "_retail_")
    assert not res.removed_addon


def test_uninstall_refuses_a_folder_that_is_not_our_addon(instance, fake_wow):
    foreign = fake_wow / "_retail_" / "Interface" / "AddOns" / "StatTracker"
    foreign.mkdir()
    (foreign / "precious.txt").write_text("not ours: no StatTracker.toc", encoding="utf-8")
    with pytest.raises(RuntimeError):
        wow_install.uninstall_addon(fake_wow, "_retail_")
    assert (foreign / "precious.txt").is_file()


def test_list_accounts_puts_accounts_with_data_first(fake_wow):
    game = fake_wow / "_retail_"
    (game / "WTF" / "Account" / "AAA").mkdir()
    (game / "WTF" / "Account" / "SavedVariables").mkdir()   # global folder, not an account
    wow_install.saved_vars_path(game, "ACC1").write_text("x", encoding="utf-8")
    assert wow_install.list_accounts(game) == ["ACC1", "AAA"]


def test_only_retail_and_forever_count_as_tested_and_each_has_a_product():
    assert wow_install.TESTED_VARIANTS == ("_retail_", "_forever_")
    assert wow_install.is_tested("_retail_") and wow_install.is_tested("_forever_")
    for name in ("_classic_", "_classic_era_", "_classic_beta_", "_anniversary_", "_unknown_", ""):
        assert not wow_install.is_tested(name)
    assert all(name in wow_install.VARIANT_PRODUCT for name in wow_install.TESTED_VARIANTS)


def test_list_accounts_of_joins_the_game_versions(fake_wow):
    retail, forever = fake_wow / "_retail_", fake_wow / "_forever_"
    (retail / "WTF" / "Account" / "AAA").mkdir()
    (forever / "WTF" / "Account" / "ZZZ" / "SavedVariables").mkdir(parents=True)
    wow_install.saved_vars_path(forever, "ZZZ").write_text("x", encoding="utf-8")         # data in one version is enough to come first
    assert wow_install.list_accounts_of(fake_wow, ["_retail_", "_forever_"]) == ["ZZZ", "AAA", "ACC1"]      # each name once, ACC1 is in both
    assert wow_install.list_accounts_of(fake_wow, ["_retail_"]) == ["AAA", "ACC1"]
    assert wow_install.list_accounts_of(fake_wow, []) == [] and wow_install.list_accounts_of(fake_wow, ["_missing_"]) == []
