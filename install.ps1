# QAClan Agent installer for Windows (PowerShell 5.1+)
# Usage:
#   irm https://raw.githubusercontent.com/qaclan/agent/master/install.ps1 | iex
# Or:
#   Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
#   .\install.ps1

$ErrorActionPreference = 'Stop'

$Repo        = 'qaclan/agent'
$BinaryName  = 'qaclan.exe'
$InstallDir  = Join-Path $env:USERPROFILE '.qaclan\bin'

function Info  { param($m) Write-Host ">>> $m" -ForegroundColor Green }
function Warn  { param($m) Write-Host ">>> $m" -ForegroundColor Yellow }
function Fail  { param($m) Write-Host ">>> $m" -ForegroundColor Red; exit 1 }

function Confirm-YesNo {
    param(
        [string]$Prompt,
        [string]$Default = 'yes'   # 'yes' or 'no'
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

# ── Detect architecture ──────────────────────────────────────────────
$arch = switch ($env:PROCESSOR_ARCHITECTURE) {
    'AMD64' { 'amd64' }
    'ARM64' { 'arm64' }
    default { Fail "Unsupported architecture: $($env:PROCESSOR_ARCHITECTURE)" }
}
Info "Detected platform: windows-$arch"

# ── Fetch latest release ─────────────────────────────────────────────
Info "Fetching latest release..."
try {
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    $release = Invoke-RestMethod -Uri "https://api.github.com/repos/$Repo/releases/latest" -UseBasicParsing
} catch {
    Fail "Could not fetch release info: $($_.Exception.Message)"
}

$tag         = $release.tag_name
$assetName   = "qaclan-windows-$arch.exe"
$downloadUrl = "https://github.com/$Repo/releases/download/$tag/$assetName"

if (-not $tag) { Fail "Could not determine latest release. Check https://github.com/$Repo/releases" }

Info "Installing qaclan $tag (windows-$arch)..."

# ── Create install dir ───────────────────────────────────────────────
if (-not (Test-Path $InstallDir)) {
    New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null
}
$targetPath = Join-Path $InstallDir $BinaryName

# ── Download binary ──────────────────────────────────────────────────
$tmpFile = [IO.Path]::GetTempFileName()
try {
    Invoke-WebRequest -Uri $downloadUrl -OutFile $tmpFile -UseBasicParsing
    Move-Item -Path $tmpFile -Destination $targetPath -Force
} catch {
    Remove-Item $tmpFile -ErrorAction SilentlyContinue
    Fail "Download failed: $($_.Exception.Message)"
}

# ── Add install dir to user PATH ─────────────────────────────────────
$userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
if (-not $userPath) { $userPath = '' }
if ($userPath -notlike "*$InstallDir*") {
    Info "Adding $InstallDir to user PATH..."
    $newPath = if ($userPath) { "$userPath;$InstallDir" } else { $InstallDir }
    [Environment]::SetEnvironmentVariable('Path', $newPath, 'User')
    $env:Path = "$env:Path;$InstallDir"
    Warn "Restart your terminal for PATH changes to take effect."
}

# ── Install Node.js ──────────────────────────────────────────────────
function Test-Cmd { param($name) [bool](Get-Command $name -ErrorAction SilentlyContinue) }

$skipPlaywright = $false

if (-not (Test-Cmd 'npm')) {
    Warn "Node.js not found. Required for Playwright JS/TS script support."
    if (Confirm-YesNo "Install Node.js now?" 'yes') {
        if (Test-Cmd 'winget') {
            Info "Installing Node.js via winget..."
            winget install --silent --accept-source-agreements --accept-package-agreements -e --id OpenJS.NodeJS.LTS
        } elseif (Test-Cmd 'choco') {
            Info "Installing Node.js via Chocolatey..."
            choco install nodejs-lts -y
        } else {
            Fail "Neither winget nor choco found. Install Node.js manually from https://nodejs.org and re-run this script."
        }
        # Refresh PATH so npm visible in current session
        $env:Path = [Environment]::GetEnvironmentVariable('Path','Machine') + ';' + [Environment]::GetEnvironmentVariable('Path','User')
        if (-not (Test-Cmd 'npm')) {
            Warn "Node.js installed but npm not on PATH yet. Open a new terminal and re-run to install Playwright."
            $skipPlaywright = $true
        }
    } else {
        Warn "Skipping Node.js. Playwright JS/TS scripts will not run until Node.js is installed."
        $skipPlaywright = $true
    }
}

# ── Install Playwright + tsx ─────────────────────────────────────────
if (-not $skipPlaywright) {
    if (Confirm-YesNo "Install Playwright 1.58.0 + tsx globally via npm?" 'yes') {
        Info "Installing Playwright and tsx..."
        npm install -g playwright@1.58.0 '@playwright/test@1.58.0' tsx
        if ($LASTEXITCODE -ne 0) {
            Fail "Failed to install Playwright/tsx. Run manually: npm install -g playwright@1.58.0 @playwright/test@1.58.0 tsx"
        }

        if (-not (Test-Cmd 'playwright')) {
            Warn "Playwright installed but not found on PATH. Check npm global bin: npm bin -g"
        } else {
            Info "Playwright and tsx installed."

            # ── Install Chromium ─────────────────────────────────────
            if (Confirm-YesNo "Install Chromium browser for Playwright?" 'yes') {
                Info "Installing Chromium..."
                playwright install chromium
                if ($LASTEXITCODE -ne 0) {
                    Warn "Failed to install Chromium. Run manually: playwright install chromium"
                } else {
                    Info "Chromium installed."
                }
            } else {
                Warn "Skipped Chromium. Run later: playwright install chromium"
            }
        }
    } else {
        Warn "Skipped Playwright. Run later: npm install -g playwright@1.58.0 @playwright/test@1.58.0 tsx"
    }
}

# ── Verify ───────────────────────────────────────────────────────────
if (Test-Path $targetPath) {
    Info "qaclan installed successfully!"
    Write-Host ""
    Write-Host "  Location: $targetPath"
    Write-Host ""
    Write-Host "  Get started (open a NEW terminal first):"
    Write-Host "    qaclan login          # Authenticate with your API key"
    Write-Host "    qaclan serve          # Launch the web UI"
    Write-Host "    qaclan --help         # See all commands"
    Write-Host ""
} else {
    Fail "Install verification failed: $targetPath not found."
}
