# QAClan Agent uninstaller for Windows (PowerShell 5.1+)
# Usage:
#   irm https://raw.githubusercontent.com/qaclan/agent/master/uninstall.ps1 | iex
# Or:
#   Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
#   .\uninstall.ps1

$ErrorActionPreference = 'Stop'

$BinaryName = 'qaclan.exe'
$InstallDir = Join-Path $env:USERPROFILE '.qaclan\bin'
$DataDir    = Join-Path $env:USERPROFILE '.qaclan'
$TargetPath = Join-Path $InstallDir $BinaryName

function Info { param($m) Write-Host ">>> $m" -ForegroundColor Green }
function Warn { param($m) Write-Host ">>> $m" -ForegroundColor Yellow }
function Fail { param($m) Write-Host ">>> $m" -ForegroundColor Red; exit 1 }

function Confirm-YesNo {
    param(
        [string]$Prompt,
        [string]$Default = 'no'   # 'yes' or 'no'
    )
    $hint = "[y/n/yes/no] (default: $Default)"
    while ($true) {
        $ans = Read-Host "$Prompt $hint"
        if ([string]::IsNullOrWhiteSpace($ans)) { $ans = $Default }
        switch ($ans.Trim().ToLower()) {
            'y'   { return $true }
            'yes' { return $true }
            'n'   { return $false }
            'no'  { return $false }
            default { Write-Host "Please answer: y, n, yes, or no." }
        }
    }
}

if (-not (Test-Path $TargetPath) -and -not (Test-Path $DataDir)) {
    Warn "Nothing to remove — qaclan is not installed."
    exit 0
}

Write-Host ""
Write-Host "This will remove:"
if (Test-Path $TargetPath) { Write-Host "  - qaclan binary: $TargetPath" }
Write-Host "  - qaclan data directory: $DataDir (database, scripts, runtime, config, auth credentials)"
Write-Host "  - $InstallDir from your user PATH"
Write-Host ""
if (-not (Confirm-YesNo "Continue?" 'no')) {
    Write-Host "Aborted."
    exit 0
}

# ── Remove install dir from user PATH ────────────────────────────────
$userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
if ($userPath) {
    $entries  = $userPath.Split(';') | Where-Object { $_ }
    $filtered = $entries | Where-Object {
        (Get-Item -LiteralPath $_ -ErrorAction SilentlyContinue).FullName -ne (Get-Item -LiteralPath $InstallDir -ErrorAction SilentlyContinue).FullName `
            -and $_.TrimEnd('\') -ne $InstallDir.TrimEnd('\')
    }
    if ($filtered.Count -ne $entries.Count) {
        [Environment]::SetEnvironmentVariable('Path', ($filtered -join ';'), 'User')
        Info "Removed $InstallDir from user PATH."
    } else {
        Warn "PATH already clean (nothing to remove)."
    }
} else {
    Warn "No user PATH entries found."
}

# ── Remove qaclan binary ─────────────────────────────────────────────
if (Test-Path $TargetPath) {
    try {
        Remove-Item -LiteralPath $TargetPath -Force -ErrorAction Stop
        Info "Removed binary: $TargetPath"
    } catch {
        Warn "Could not remove $TargetPath (is qaclan still running?). Close it and delete manually:"
        Warn "  Remove-Item '$TargetPath' -Force"
    }
} else {
    Warn "Binary not found at $TargetPath, skipping."
}

# ── Remove qaclan data directory ─────────────────────────────────────
if (Test-Path $DataDir) {
    try {
        Remove-Item -LiteralPath $DataDir -Recurse -Force -ErrorAction Stop
        Info "Removed data directory: $DataDir"
    } catch {
        Warn "Could not fully remove $DataDir (files may be in use). Remaining items:"
        Warn "  Remove-Item '$DataDir' -Recurse -Force"
    }
} else {
    Warn "Data directory $DataDir not found, skipping."
}

Write-Host ""
Info "qaclan has been fully uninstalled."
Warn "Open a new terminal for PATH changes to take effect."
