# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)
# The GitHub workflows (.github/workflows): every action is pinned to a full commit, the tests only read the repository, and in the
# release only the publish job may write (the build job runs the packages and the tests, so it must not be able to publish).
# Text checks only (no YAML library); the real run is only seen on GitHub.

import re
from pathlib import Path

WORKFLOWS = Path(__file__).resolve().parent.parent / ".github" / "workflows"
CI = (WORKFLOWS / "ci.yml").read_text(encoding="utf-8")
RELEASE = (WORKFLOWS / "release.yml").read_text(encoding="utf-8")
ADDON = (WORKFLOWS / "addon-release.yml").read_text(encoding="utf-8")


def uses_lines(text):
    return [line.strip() for line in text.splitlines() if line.strip().startswith(("- uses:", "uses:"))]


def job_text(text, job):
    """The lines of one job of the workflow (from '  <job>:' to the next job or the end)."""
    match = re.search(rf"^  {job}:\n(.*?)(?=^  [A-Za-z_-]+:\n|\Z)", text, re.M | re.S)
    assert match, job
    return match.group(1)


def test_every_action_is_pinned_to_a_commit_with_its_version_in_a_comment():
    for name, text in (("ci.yml", CI), ("release.yml", RELEASE), ("addon-release.yml", ADDON)):
        lines = uses_lines(text)
        assert lines, name
        for line in lines:
            assert re.fullmatch(r"-? ?uses: [\w.-]+/[\w.-]+@[0-9a-f]{40} # v\d+(\.\d+)*", line), (name, line)


def test_the_tests_only_read_the_repository():
    top = CI.split("jobs:")[0]
    assert re.search(r"^permissions:\n  contents: read\n", top, re.M)
    assert "write" not in CI


def test_the_release_has_no_rights_by_default_and_only_the_publish_job_writes():
    top = RELEASE.split("jobs:")[0]
    assert re.search(r"^permissions: \{\}$", top, re.M)
    assert RELEASE.count("contents: write") == 1
    assert "contents: write" in job_text(RELEASE, "publish")
    build = job_text(RELEASE, "build")
    assert "contents: read" in build and "write" not in build
    assert "action-gh-release" in job_text(RELEASE, "publish") and "action-gh-release" not in build


ROOT = WORKFLOWS.parent.parent


def pins(path):
    """{normalised name: version} of a requirements file made of 'name==version' lines (comments and blanks skipped)."""
    found = {}
    for line in (ROOT / path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        match = re.fullmatch(r"([A-Za-z0-9_.-]+)==([0-9][A-Za-z0-9.]*)", line)
        assert match, f"{path}: not an exact pin: {line!r}"
        found[re.sub(r"[-_.]+", "-", match.group(1)).lower()] = match.group(2)
    return found


def test_both_workflows_install_the_lock_file_and_nothing_else():
    for name, text in (("ci.yml", CI), ("release.yml", RELEASE), ("addon-release.yml", ADDON)):
        installs = [line.strip() for line in text.splitlines() if "pip install" in line]
        assert installs == ["- run: pip install -r requirements-lock.txt"], (name, installs)


def test_the_lock_file_pins_every_package_exactly_and_covers_what_the_project_asks_for():
    lock = pins("requirements-lock.txt")
    for path in ("requirements.txt", "requirements-dev.txt"):
        for line in (ROOT / path).read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith(("#", "-r")):
                continue
            name = re.match(r"[A-Za-z0-9_.-]+", line).group(0)
            assert re.sub(r"[-_.]+", "-", name).lower() in lock, f"{name} ({path}) is not in requirements-lock.txt"
    assert "pyinstaller" in lock                                      # the release builds with it
    wanted = re.search(r"PyQt6>=(\d+\.\d+),<(\d+\.\d+)", (ROOT / "requirements.txt").read_text(encoding="utf-8"))
    low, high = (tuple(int(p) for p in wanted.group(i).split(".")) for i in (1, 2))
    version = tuple(int(p) for p in lock["pyqt6"].split(".")[:2])
    assert low <= version < high, "the locked PyQt6 is outside the range of requirements.txt"


def step_text(text, name_part):
    """One step of a workflow (from its '- name:' line to the next step)."""
    match = re.search(rf"^      - name: [^\n]*{re.escape(name_part)}[^\n]*\n(.*?)(?=^      - |\Z)", text, re.M | re.S)
    assert match, name_part
    return match.group(0)


def test_the_addon_workflow_cannot_write_and_runs_on_an_addon_tag_or_by_hand():
    top = ADDON.split("jobs:")[0]
    assert re.search(r"^permissions: \{\}$", top, re.M)
    assert 'tags: ["addon-v*"]' in top and "workflow_dispatch:" in top
    assert "contents: write" not in ADDON and ": write" not in ADDON
    for job in ("test", "package"):
        assert "contents: read" in job_text(ADDON, job)
    assert "needs: test" in job_text(ADDON, "package")


def test_only_the_upload_step_of_the_addon_workflow_has_the_curseforge_token_and_only_on_a_tag():
    assert ADDON.count("secrets.") == 1 and ADDON.count("CF_API_TOKEN: ${{ secrets.CURSEFORGE }}") == 1
    upload = step_text(ADDON, "upload to CurseForge")
    assert "secrets.CURSEFORGE" in upload and "if: github.event_name == 'push'" in upload
    assert " -d" not in upload
    dry = step_text(ADDON, "without uploading")
    assert "if: github.event_name != 'push'" in dry and "args: -d " in dry and "secrets" not in dry
    for name in ("GITHUB_OAUTH", "GH_API_TOKEN", "GITHUB_API_TOKEN", "GITHUB_TOKEN"):
        assert name not in ADDON                                      # the packager gets no GitHub token, so it makes no GitHub release


def test_the_addon_workflow_stages_with_the_tag_check_before_it_packages():
    package = job_text(ADDON, "package")
    assert 'compiler/addon_package.py --out stage --tag "$GITHUB_REF_NAME"' in package
    assert package.index("addon_package.py") < package.index("BigWigsMods/packager")


def test_the_publish_job_checks_the_checksum_before_it_publishes():
    publish = job_text(RELEASE, "publish")
    assert publish.index("checksum must match") < publish.index("action-gh-release")
    assert "needs: build" in publish
