#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)
# updater.py
# StatTracker - self-update, client side (pattern from Garmin Local Archive).
# stdlib + app_info/paths/i18n only, no GUI.
#
# Flow:
#   fetch_latest_release()   GitHub "latest release" JSON
#   resolve_release_asset()  exact asset name -> download URL (no guessing)
#   prepare_update()         download ZIP, verify SHA256 (fail closed), extract to
#                            <base>/_update_pending/. Nothing outside that folder is
#                            touched; on any error it is removed again.
#   launch_helper()          starts updater_helper.ps1 detached (copied to a temp
#                            folder first). The helper waits for this process, swaps
#                            ONLY app_info.PROGRAM_ITEMS (never data/), restarts the
#                            app and rolls back if the new version does not start.
#   write_success_flag()     startup handshake: the new version signals "window is up".

import hashlib
import json
import shutil
import subprocess
import tempfile
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

import app_info
import paths
from i18n import t

UPDATE_PENDING_DIRNAME = "_update_pending"
UPDATE_SUCCESS_FLAG_NAME = "_update_success.flag"
USER_AGENT = app_info.APP_NAME

# Only https is accepted for downloads; tests widen this to reach local files.
ALLOWED_SCHEMES = ("https",)


def _check_scheme(url: str) -> None:
    if urllib.parse.urlparse(url).scheme.lower() not in ALLOWED_SCHEMES:
        raise RuntimeError(t("err_bad_url", url=url))


class _SchemeCheckedRedirects(urllib.request.HTTPRedirectHandler):
    """urlopen follows a redirect to any scheme it knows (http, ftp), so the check of the first address
    would not hold for the rest of the way: every hop gets the same check."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _check_scheme(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_OPENER = urllib.request.build_opener(_SchemeCheckedRedirects)


def _open(url: str, timeout: int):
    _check_scheme(url)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    return _OPENER.open(req, timeout=timeout)


def fetch_latest_release(url: str = None, timeout: int = 5) -> dict:
    """The GitHub 'latest release' JSON. Raises OSError/ValueError/RuntimeError."""
    with _open(url or app_info.LATEST_API_URL, timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    if not isinstance(data, dict):
        raise ValueError("unexpected response")
    return data


def resolve_release_asset(release_json: dict, asset_name: str):
    """browser_download_url of the asset with exactly this name, or None. No substring matching."""
    for asset in release_json.get("assets", []):
        if asset.get("name") == asset_name:
            return asset.get("browser_download_url")
    return None


def write_success_flag(base_dir: Path) -> None:
    """Best-effort marker for the helper; a write error must never block app start."""
    try:
        (base_dir / UPDATE_SUCCESS_FLAG_NAME).touch()
    except OSError:
        pass


def _download(url: str, dest: Path) -> None:
    with _open(url, 30) as resp, open(dest, "wb") as f:
        shutil.copyfileobj(resp, f)


def _sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _payload_root(pending_dir: Path) -> Path:
    """The release ZIP has one top folder (StatTracker/); the payload is inside it.
    A flat ZIP works too."""
    children = [p for p in pending_dir.iterdir()]
    if len(children) == 1 and children[0].is_dir() and children[0].name not in app_info.PROGRAM_ITEMS:
        return children[0]
    return pending_dir


def prepare_update(base_dir: Path, zip_url: str, checksum_url) -> Path:
    """Downloads and verifies the release ZIP and extracts it to <base>/_update_pending/.
    Returns the payload folder (the one containing StatTracker.exe).
    Raises RuntimeError (translated) on any problem; the running install is never touched."""
    pending_dir = Path(base_dir) / UPDATE_PENDING_DIRNAME
    if pending_dir.exists():
        shutil.rmtree(pending_dir)  # leftover of an aborted attempt
    pending_dir.mkdir()

    def fail(message):
        shutil.rmtree(pending_dir, ignore_errors=True)
        raise RuntimeError(message)

    if not checksum_url:
        fail(t("err_no_checksum"))

    zip_path = pending_dir / "update.zip"
    try:
        _download(zip_url, zip_path)
        with _open(checksum_url, 10) as resp:
            expected = resp.read().decode("utf-8", "replace").split()[0].lower()
    except (OSError, IndexError) as exc:
        fail(t("err_download", error=exc))
    except RuntimeError as exc:
        fail(str(exc))

    actual = _sha256_of(zip_path).lower()
    if actual != expected:
        fail(t("err_checksum", expected=expected, actual=actual))

    try:
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(pending_dir)
    except zipfile.BadZipFile as exc:
        fail(t("err_bad_zip", error=exc))
    zip_path.unlink()

    payload = _payload_root(pending_dir)
    missing = [name for name in app_info.PROGRAM_ITEMS if not (payload / name).exists()]
    if missing:
        fail(t("err_payload_incomplete", missing=", ".join(missing)))
    return payload


def launch_helper(base_dir: Path, payload_dir: Path, wait_pids, restart: bool = True) -> subprocess.Popen:
    """Starts the PowerShell helper detached. It is copied to a temp folder first, because
    it replaces files in base_dir while it runs. The caller must exit afterwards."""
    src = paths.resource_dir() / "updater_helper.ps1"
    if not src.is_file():
        raise RuntimeError(t("err_download", error=f"{src} missing"))
    helper = Path(tempfile.mkdtemp(prefix="stattracker_update_")) / src.name
    shutil.copy2(src, helper)
    args = [
        "powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
        "-File", str(helper),
        "-ExeDir", str(base_dir),
        "-PayloadDir", str(payload_dir),
        "-PendingRoot", str(Path(base_dir) / UPDATE_PENDING_DIRNAME),
        "-Items", ",".join(app_info.PROGRAM_ITEMS),
        "-WaitPids", ",".join(str(p) for p in wait_pids),
        "-GuiExeName", app_info.EXE_NAME,
    ]
    if restart:
        args.append("-RestartGui")
    return subprocess.Popen(
        args, creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
        | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
