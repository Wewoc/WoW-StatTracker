<#
updater_helper.ps1
StatTracker - self-update helper (pattern from Garmin Local Archive).

Started detached by the GUI (src/updater.py launch_helper), from a temp copy.
Runs OUTSIDE the app so it can wait for it to exit and then replace its files.

NOTE: this file must stay plain ASCII (a non-ASCII character in a string literal
can break the PowerShell parser on machines with another code page).

Only the program items listed in -Items are replaced. Everything else in
ExeDir - above all the data folder (database, config, generated pages) - is
never moved, deleted or overwritten.

Parameters:
  -ExeDir       Install folder (contains the live files and the data folder).
  -PayloadDir   Folder with the already downloaded, verified, extracted new version.
  -PendingRoot  The _update_pending folder (removed at the end).
  -Items        Comma-separated names to replace (exe, _internal, addon, info, LICENSE).
  -WaitPids     Comma-separated PIDs to wait for before touching any file.
  -GuiExeName   Exe to restart after the swap (relative to ExeDir).
  -RestartGui   Restart the app, wait for the startup handshake flag
                (_update_success.flag, written by the new version once its window
                is up), retry, and roll back if it never appears.
  -SuccessTimeoutSeconds / -MaxLaunchAttempts   handshake tuning (tests use small values).
  -HideGuiWindow   tests only: start the GUI hidden.

Old items are moved to _update_backup/ (replaced by the next update) - the
rollback safety net.
#>

param(
    [Parameter(Mandatory = $true)][string]$ExeDir,
    [Parameter(Mandatory = $true)][string]$PayloadDir,
    [string]$PendingRoot = "",
    [Parameter(Mandatory = $true)][string]$Items,
    [string]$WaitPids = "",
    [string]$GuiExeName = "StatTracker.exe",
    [switch]$RestartGui,
    [int]$SuccessTimeoutSeconds = 60,
    [int]$MaxLaunchAttempts = 3,
    [switch]$HideGuiWindow
)

$ErrorActionPreference = "Stop"
$lockPath = Join-Path $ExeDir "_update_helper.lock"
$backupDir = Join-Path $ExeDir "_update_backup"
$itemList = @($Items -split "," | ForEach-Object { $_.Trim() } | Where-Object { $_ })

$guiStartArgs = @{}
if ($HideGuiWindow) { $guiStartArgs["WindowStyle"] = "Hidden" }

# NOTE: every path below is passed with -LiteralPath. With -Path, square brackets in
# a folder name (D:\Games\WoW [Retail]) are read as a wildcard pattern.

# -- 0. Is another helper already running? ---------------------------------
# The lock holds a PID. A helper that died leaves it behind, and any program can get
# that PID later, so the process must also be a PowerShell.
if (Test-Path -LiteralPath $lockPath) {
    $existingPid = Get-Content -LiteralPath $lockPath -ErrorAction SilentlyContinue
    $holder = $null
    if ($existingPid) { $holder = Get-Process -Id $existingPid -ErrorAction SilentlyContinue }
    if ($holder -and ($holder.ProcessName -match '^(powershell|pwsh)')) {
        Write-Host "UPDATE FAILED: another update is already in progress (PID $existingPid)." -ForegroundColor Red
        Read-Host "Press Enter to close"
        exit 1
    }
}
$PID | Out-File -LiteralPath $lockPath -Encoding ascii

$restored = $false
function Restore-Backup {
    # Remove the (new) items, move the backed-up (old) ones back. An item whose new version
    # cannot be removed (a file held open by another program) is left alone: moving the old
    # folder onto it would bury the old one inside the new one.
    $script:restored = $true
    $notRestored = @()
    foreach ($name in $itemList) {
        $target = Join-Path $ExeDir $name
        if (Test-Path -LiteralPath $target) {
            Remove-Item -LiteralPath $target -Recurse -Force -ErrorAction SilentlyContinue
        }
        if (Test-Path -LiteralPath $target) { $notRestored += $name; continue }
        $saved = Join-Path $backupDir $name
        if (Test-Path -LiteralPath $saved) { Move-Item -LiteralPath $saved -Destination $target -Force }
    }
    if ($notRestored.Count -gt 0) {
        throw "Rollback incomplete - could not replace: $($notRestored -join ', '). The previous version is in $backupDir."
    }
}

$exitCode = 0
$swapStarted = $false
try {
    # -- 1. Wait for the given PIDs (max. 60 s each) ------------------------
    if ($WaitPids) {
        foreach ($p in ($WaitPids -split ",")) {
            $p = $p.Trim()
            if (-not $p) { continue }
            $deadline = (Get-Date).AddSeconds(60)
            while ((Get-Process -Id $p -ErrorAction SilentlyContinue) -and (Get-Date) -lt $deadline) {
                Start-Sleep -Milliseconds 500
            }
            if (Get-Process -Id $p -ErrorAction SilentlyContinue) {
                throw "Process $p did not exit within 60 seconds - update aborted, nothing changed."
            }
        }
    }

    # -- 2. Check the payload BEFORE touching anything ----------------------
    foreach ($name in $itemList) {
        if (-not (Test-Path -LiteralPath (Join-Path $PayloadDir $name))) {
            throw "Update package is incomplete (missing: $name) - nothing changed."
        }
    }

    # -- 3. Back up the old items, move the new ones into place -------------
    if (Test-Path -LiteralPath $backupDir) { Remove-Item -LiteralPath $backupDir -Recurse -Force }
    New-Item -ItemType Directory -Path $backupDir | Out-Null
    $swapStarted = $true
    foreach ($name in $itemList) {
        $live = Join-Path $ExeDir $name
        if (Test-Path -LiteralPath $live) { Move-Item -LiteralPath $live -Destination (Join-Path $backupDir $name) -Force }
    }
    foreach ($name in $itemList) {
        Move-Item -LiteralPath (Join-Path $PayloadDir $name) -Destination (Join-Path $ExeDir $name) -Force
    }
    if ($PendingRoot -and (Test-Path -LiteralPath $PendingRoot)) {
        Remove-Item -LiteralPath $PendingRoot -Recurse -Force -ErrorAction SilentlyContinue
    }

    # -- 4. Strip Mark-of-the-Web from the new files (SmartScreen friction) -
    foreach ($name in $itemList) {
        $target = Join-Path $ExeDir $name
        if (Test-Path -LiteralPath $target) {
            Get-ChildItem -LiteralPath $target -Recurse -File -ErrorAction SilentlyContinue |
                Unblock-File -ErrorAction SilentlyContinue
            if (-not (Get-Item -LiteralPath $target).PSIsContainer) { Unblock-File -LiteralPath $target -ErrorAction SilentlyContinue }
        }
    }

    # -- 5. Restart the GUI with the startup handshake ----------------------
    if ($RestartGui) {
        $successFlag = Join-Path $ExeDir "_update_success.flag"
        $launchSucceeded = $false

        for ($attempt = 1; $attempt -le $MaxLaunchAttempts; $attempt++) {
            Remove-Item -LiteralPath $successFlag -Force -ErrorAction SilentlyContinue
            $newGui = Start-Process (Join-Path $ExeDir $GuiExeName) -PassThru @guiStartArgs

            $deadline = (Get-Date).AddSeconds($SuccessTimeoutSeconds)
            while ((-not (Test-Path -LiteralPath $successFlag)) -and ((Get-Date) -lt $deadline) -and (-not $newGui.HasExited)) {
                Start-Sleep -Milliseconds 500
            }
            if (Test-Path -LiteralPath $successFlag) {
                Remove-Item -LiteralPath $successFlag -Force -ErrorAction SilentlyContinue
                $launchSucceeded = $true
                break
            }

            # No success signal: make sure the process is really gone before the next
            # attempt or the rollback touches its files.
            if (-not $newGui.HasExited) {
                Stop-Process -Id $newGui.Id -Force -ErrorAction SilentlyContinue
                $killDeadline = (Get-Date).AddSeconds(10)
                while ((Get-Process -Id $newGui.Id -ErrorAction SilentlyContinue) -and (Get-Date) -lt $killDeadline) {
                    Start-Sleep -Milliseconds 250
                }
            }
            if ($attempt -lt $MaxLaunchAttempts) {
                Write-Host "Launch attempt $attempt of $MaxLaunchAttempts did not signal success - retrying ..."
            }
        }

        if (-not $launchSucceeded) {
            Restore-Backup
            Start-Process (Join-Path $ExeDir $GuiExeName) @guiStartArgs
            throw "New version did not signal a successful start after $MaxLaunchAttempts attempt(s) ($SuccessTimeoutSeconds seconds each) - rolled back to the previous version."
        }
    }

    Write-Host "Update applied successfully."
}
catch {
    Write-Host "UPDATE FAILED: $($_.Exception.Message)" -ForegroundColor Red
    $exitCode = 1
    if ($swapStarted -and -not $restored) {
        # failed in the middle of the swap: put the old version back
        try { Restore-Backup; Write-Host "Previous version restored." } catch { Write-Host "ROLLBACK FAILED: $($_.Exception.Message)" -ForegroundColor Red }
    }
}
finally {
    Remove-Item -LiteralPath $lockPath -Force -ErrorAction SilentlyContinue
}

if ($exitCode -ne 0) {
    Read-Host "Press Enter to close"
}
exit $exitCode
