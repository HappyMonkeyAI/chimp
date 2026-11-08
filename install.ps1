#Requires -Version 5.1
<#
.SYNOPSIS
  Install chimp (local OpenAI-compatible VRAM-sticky router).

.DESCRIPTION
  One-liner:
    irm https://raw.githubusercontent.com/HappyMonkeyAI/chimp/main/install.ps1 | iex

  From a clone:
    .\install.ps1

  Options:
    -Dir <path>   Install directory (default: CHIMP_HOME or %USERPROFILE%\chimp,
                  or the current directory when it is already a chimp checkout)
    -Dev          Also install pytest extras (or set CHIMP_DEV=1)

  Env:
    CHIMP_HOME, CHIMP_REPO, CHIMP_REF, CHIMP_DEV
#>
[CmdletBinding()]
param(
    [string]$Dir = "",
    [switch]$Dev
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

$RepoUrl = if ($env:CHIMP_REPO) { $env:CHIMP_REPO } else { "https://github.com/HappyMonkeyAI/chimp.git" }
$Ref = if ($env:CHIMP_REF) { $env:CHIMP_REF } else { "main" }
$WantDev = $Dev -or ($env:CHIMP_DEV -eq "1")

function Write-Step([string]$Message) { Write-Host "==> $Message" -ForegroundColor Cyan }
function Write-Ok([string]$Message) { Write-Host "OK  $Message" -ForegroundColor Green }
function Write-Fail([string]$Message) { Write-Host "ERR $Message" -ForegroundColor Red }

function Test-IsChimpRoot([string]$Path) {
    $pyproject = Join-Path $Path "pyproject.toml"
    if (-not (Test-Path -LiteralPath $pyproject)) { return $false }
    $text = Get-Content -LiteralPath $pyproject -Raw -ErrorAction SilentlyContinue
    return ($text -match '(?m)^name\s*=\s*"chimp"')
}

function Find-Python {
    $candidates = @(
        @{ Cmd = "py"; Args = @("-3.12") },
        @{ Cmd = "py"; Args = @("-3.11") },
        @{ Cmd = "python"; Args = @() },
        @{ Cmd = "python3"; Args = @() }
    )
    foreach ($c in $candidates) {
        if (-not (Get-Command $c.Cmd -ErrorAction SilentlyContinue)) { continue }
        try {
            $versionText = & $c.Cmd @($c.Args + @("-c", "import sys; print('%d.%d' % sys.version_info[:2])")) 2>$null
            if (-not $versionText) { continue }
            $parts = $versionText.Trim().Split(".")
            $major = [int]$parts[0]
            $minor = [int]$parts[1]
            if ($major -gt 3 -or ($major -eq 3 -and $minor -ge 11)) {
                return @{ Exe = $c.Cmd; Args = $c.Args; Version = "$major.$minor" }
            }
        } catch { }
    }
    return $null
}

function Get-InstallRoot {
    if ($Dir) { return [System.IO.Path]::GetFullPath($Dir) }
    if ($env:CHIMP_HOME) { return [System.IO.Path]::GetFullPath($env:CHIMP_HOME) }
    if (Test-IsChimpRoot (Get-Location).Path) { return (Get-Location).Path }
    return Join-Path $env:USERPROFILE "chimp"
}

function Sync-Repo([string]$Root) {
    if (Test-IsChimpRoot $Root) {
        Write-Step "Using existing checkout at $Root"
        if (Get-Command git -ErrorAction SilentlyContinue) {
            Push-Location $Root
            try {
                git fetch --depth 1 origin $Ref 2>$null | Out-Null
                git checkout $Ref 2>$null | Out-Null
                git pull --ff-only origin $Ref 2>$null | Out-Null
            } catch {
                Write-Host "    (skip update: $($_.Exception.Message))"
            } finally {
                Pop-Location
            }
        }
        return
    }

    if (Test-Path -LiteralPath $Root) {
        $empty = -not (Get-ChildItem -LiteralPath $Root -Force -ErrorAction SilentlyContinue | Select-Object -First 1)
        if (-not $empty) {
            throw "Directory exists and is not a chimp checkout: $Root (set -Dir / CHIMP_HOME)"
        }
    } else {
        New-Item -ItemType Directory -Path $Root -Force | Out-Null
    }

    if (Get-Command git -ErrorAction SilentlyContinue) {
        Write-Step "Cloning $RepoUrl ($Ref) -> $Root"
        # Clone into a temp name if root was pre-created empty
        $tmp = Join-Path ([System.IO.Path]::GetTempPath()) ("chimp-clone-" + [guid]::NewGuid().ToString("n"))
        git clone --branch $Ref --depth 1 $RepoUrl $tmp
        Get-ChildItem -LiteralPath $tmp -Force | ForEach-Object {
            Move-Item -LiteralPath $_.FullName -Destination (Join-Path $Root $_.Name) -Force
        }
        Remove-Item -LiteralPath $tmp -Recurse -Force -ErrorAction SilentlyContinue
        return
    }

    Write-Step "git not found; downloading zipball"
    $owner = "HappyMonkeyAI"
    $name = "chimp"
    if ($RepoUrl -match 'github\.com[:/]([^/]+)/([^/.]+)') {
        $owner = $Matches[1]
        $name = $Matches[2]
    }
    $zip = Join-Path $env:TEMP "chimp-$Ref.zip"
    $url = "https://github.com/$owner/$name/archive/refs/heads/$Ref.zip"
    Invoke-WebRequest -Uri $url -OutFile $zip
    $extract = Join-Path $env:TEMP "chimp-extract-$Ref"
    if (Test-Path $extract) { Remove-Item $extract -Recurse -Force }
    Expand-Archive -LiteralPath $zip -DestinationPath $extract -Force
    $inner = Get-ChildItem $extract -Directory | Select-Object -First 1
    if (-not $inner) { throw "Zipball extract failed" }
    Get-ChildItem -LiteralPath $inner.FullName -Force | ForEach-Object {
        Move-Item -LiteralPath $_.FullName -Destination (Join-Path $Root $_.Name) -Force
    }
    Remove-Item $zip -Force -ErrorAction SilentlyContinue
    Remove-Item $extract -Recurse -Force -ErrorAction SilentlyContinue
}

function Install-Chimp {
    $root = Get-InstallRoot
    Write-Step "Install root: $root"

    Write-Step "Checking Python >= 3.11"
    $py = Find-Python
    if (-not $py) {
        Write-Fail "Python 3.11+ not found. Install from https://www.python.org/downloads/ (enable py launcher) and re-run."
        exit 1
    }
    Write-Ok "Python $($py.Version) via $($py.Exe) $($py.Args -join ' ')"

    Sync-Repo $root
    if (-not (Test-IsChimpRoot $root)) {
        Write-Fail "Not a chimp project after sync: $root"
        exit 1
    }

    $venv = Join-Path $root ".venv"
    $venvPython = Join-Path $venv "Scripts\python.exe"
    if (-not (Test-Path -LiteralPath $venvPython)) {
        Write-Step "Creating venv"
        & $py.Exe @($py.Args + @("-m", "venv", $venv))
        if ($LASTEXITCODE -ne 0) { throw "venv creation failed" }
    } else {
        Write-Step "Reusing venv at $venv"
    }

    Write-Step "Upgrading pip"
    & $venvPython -m pip install --upgrade pip
    if ($LASTEXITCODE -ne 0) { throw "pip upgrade failed" }

    $spec = if ($WantDev) { ".[dev]" } else { "." }
    Write-Step "Installing chimp ($spec)"
    Push-Location $root
    try {
        & $venvPython -m pip install -e $spec
        if ($LASTEXITCODE -ne 0) { throw "pip install failed" }
    } finally {
        Pop-Location
    }

    $config = Join-Path $root "config.yaml"
    $example = Join-Path $root "config.example.yaml"
    if (-not (Test-Path -LiteralPath $config)) {
        Write-Step "Creating config.yaml from example"
        Copy-Item -LiteralPath $example -Destination $config
        Write-Ok "Edit $config with your endpoint URLs"
    } else {
        Write-Ok "Keeping existing config.yaml"
    }

    Write-Step "Verifying dependencies and config load"
    $examplePosix = $example -replace '\\', '/'
    $code = @"
import importlib.util, sys
from pathlib import Path
missing = [m for m in ('chimp', 'httpx', 'yaml', 'starlette', 'uvicorn') if importlib.util.find_spec(m) is None]
if missing:
    print('missing modules:', ', '.join(missing))
    sys.exit(1)
from chimp.config import load_settings
load_settings(Path(r'$examplePosix'))
print('ok')
"@
    & $venvPython -c $code
    if ($LASTEXITCODE -ne 0) {
        Write-Fail "Verification failed"
        exit 1
    }

    $chimpExe = Join-Path $venv "Scripts\chimp.exe"
    if (-not (Test-Path -LiteralPath $chimpExe)) {
        Write-Fail "Console script missing: $chimpExe"
        exit 1
    }
    Write-Ok "chimp entrypoint ready"

    Write-Host ""
    Write-Host "chimp installed." -ForegroundColor Green
    Write-Host "  1. Edit endpoints:  $config"
    Write-Host "  2. Start router:    $chimpExe"
    Write-Host "  3. Point clients at http://127.0.0.1:8787/v1"
    Write-Host "  Status:             http://127.0.0.1:8787/status"
}

try {
    Install-Chimp
} catch {
    Write-Fail $_.Exception.Message
    exit 1
}

