# Run unpack-submissions.py on Windows, setting up everything it needs.
#
# Start it with unpack-submissions.cmd (which runs this file), e.g.
#   unpack-submissions.cmd gradebook_*.zip -o Grading
# All arguments are passed straight through to unpack-submissions.py.
#
# Before starting the program it makes sure of two things:
#   1. Python 3.8 or later. If it is missing, it explains how to install it
#      and offers to do it for you with winget, if this computer has winget.
#   2. A private Python environment (.venv, next to this script) holding
#      Pillow, reportlab and certifi; created on the first run.
# The converters, ffmpeg (audio and video) and LibreOffice (Word, Pages and
# other documents), are fetched by the program only when a submission needs
# them: it asks first, downloads them into the Tools folder next to this
# script (no administrator rights needed), and if you say no it prints
# step-by-step instructions for installing them yourself.
#
# When you have unpacked all your submissions:
#   unpack-submissions.cmd --remove-converters
# deletes the Tools folder and the Python environment (everything these
# scripts downloaded). Programs installed on the computer itself are untouched.
#
# Settings (environment variables):
#   UNPACK_INSTALL=yes   install whatever is missing without asking
#   UNPACK_INSTALL=no    never offer to install anything
#   UNPACK_VENV=DIR      keep the Python environment in DIR instead of .venv
#
# Written with Claude Opus 5.5 (Anthropic).

$ErrorActionPreference = 'Continue'
$ScriptDir = $PSScriptRoot
$Program = Join-Path $ScriptDir 'unpack-submissions.py'
if ($env:UNPACK_VENV) { $Venv = $env:UNPACK_VENV } else { $Venv = Join-Path $ScriptDir '.venv' }
$Tools = Join-Path $ScriptDir 'Tools'
$Packages = @('pillow', 'reportlab', 'certifi')
$Optional = 'pillow-heif'
$Marker = Join-Path $Venv '.installed'
if ($env:UNPACK_INSTALL) { $Mode = $env:UNPACK_INSTALL.ToLower() } else { $Mode = 'ask' }
$env:PYTHONIOENCODING = 'utf-8'

function Say([string]$Message) { [Console]::Error.WriteLine($Message) }

function Ask([string]$Question) {
    if ($Mode -eq 'yes') { return $true }
    if ($Mode -eq 'no') { return $false }
    if ([Console]::IsInputRedirected) { return $false }
    $reply = Read-Host "$Question [Y/n]"
    return -not ($reply -match '^\s*[Nn]')
}

if (-not (Test-Path $Program)) {
    Say "error: $Program not found (keep the scripts together in one folder)"
    exit 1
}

# --------------------------------------------------------------------------
# Removing the downloaded converters and the Python environment
# --------------------------------------------------------------------------
if ($args -contains '--remove-converters') {
    $removed = $false
    foreach ($dir in @($Tools, $Venv)) {
        if (Test-Path $dir) {
            $bytes = (Get-ChildItem $dir -Recurse -File -Force -ErrorAction SilentlyContinue |
                      Measure-Object -Property Length -Sum).Sum
            Remove-Item $dir -Recurse -Force -ErrorAction SilentlyContinue
            if (Test-Path $dir) {
                Say "Could not remove all of $dir (is a file in it open?). Close it and try again."
            } else {
                Say ("Removed {0} ({1:N0} MB)" -f $dir, ($bytes / 1MB))
                $removed = $true
            }
        }
    }
    if (-not $removed) { Say 'Nothing to remove: no converters were downloaded.' }
    Say 'Anything still needed is downloaded again next time.'
    exit 0
}

# --------------------------------------------------------------------------
# 1. Python
# --------------------------------------------------------------------------
function Get-RealPython([string]$Exe, [string[]]$Pre) {
    # Returns the full path of a working Python 3.8+, or $null. The "python"
    # that Windows provides before Python is installed only opens the
    # Microsoft Store; it fails this test and is skipped.
    $test = 'import sys; print(sys.executable) if sys.version_info >= (3, 8) else sys.exit(1)'
    try {
        $out = & $Exe @Pre -c $test 2>$null
    } catch {
        return $null
    }
    if ($LASTEXITCODE -eq 0 -and $out) {
        $path = ($out | Select-Object -Last 1).ToString().Trim()
        if (Test-Path $path) { return $path }
    }
    return $null
}

function Find-Python {
    foreach ($candidate in @('py -3', 'python', 'python3')) {
        $parts = $candidate -split ' '
        if (-not (Get-Command $parts[0] -ErrorAction SilentlyContinue)) { continue }
        $found = Get-RealPython $parts[0] @($parts | Select-Object -Skip 1)
        if ($found) { return $found }
    }
    $places = @("$env:LOCALAPPDATA\Programs\Python\Python3*\python.exe",
                "$env:ProgramFiles\Python3*\python.exe")
    foreach ($place in $places) {
        foreach ($f in (Get-ChildItem $place -ErrorAction SilentlyContinue |
                        Sort-Object FullName -Descending)) {
            $found = Get-RealPython $f.FullName @()
            if ($found) { return $found }
        }
    }
    return $null
}

$Python = Find-Python
if (-not $Python) {
    $arm = ($env:PROCESSOR_ARCHITECTURE -match 'ARM') -or ($env:PROCESSOR_ARCHITEW6432 -match 'ARM')
    if ($arm) { $build = 'ARM64' } else { $build = '64-bit' }
    Say ''
    Say 'Python 3 (version 3.8 or later) is needed and was not found on this computer.'
    Say ''
    Say 'To install it:'
    Say '1. Open https://www.python.org/downloads/windows/ in your web browser.'
    Say "2. Under ""Stable Releases"", find the newest Python 3 release and click"
    Say "   ""Download Windows installer ($build)""."
    Say '3. Open your Downloads folder and double-click the file you downloaded.'
    Say '4. On the first screen, tick "Add python.exe to PATH" at the bottom.'
    Say '5. Click "Install Now" and wait for it to finish, then click Close.'
    Say '6. Close this window, open a new one and run unpack-submissions.cmd again.'
    Say ''
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        if (Ask 'Install Python now with winget (no administrator rights needed)?') {
            winget install -e --id Python.Python.3.13 --scope user `
                --accept-package-agreements --accept-source-agreements
            $Python = Find-Python
        }
    }
    if (-not $Python) { exit 1 }
}

# --------------------------------------------------------------------------
# 2. The private Python environment
# --------------------------------------------------------------------------
$VenvPython = Join-Path $Venv 'Scripts\python.exe'
if (-not (Test-Path $VenvPython)) {
    Say "Creating a Python environment in $Venv ..."
    & $Python -m venv $Venv
    if (-not (Test-Path $VenvPython)) {
        Say "error: could not create a Python environment with $Python"
        exit 1
    }
    if (Test-Path $Marker) { Remove-Item $Marker }
}

$wanted = $Packages -join ' '
$have = ''
if (Test-Path $Marker) { $have = (Get-Content $Marker -Raw) }
if ($have -ne $wanted) {
    Say "Installing $wanted ..."
    & $VenvPython -m pip install --quiet --upgrade pip
    & $VenvPython -m pip install --quiet @Packages
    if ($LASTEXITCODE -ne 0) {
        Say 'error: could not install the Python packages (is the internet connection working?)'
        exit 1
    }
    & $VenvPython -m pip install --quiet $Optional 2>$null | Out-Null
    if ($LASTEXITCODE -ne 0) { Say "note: $Optional not installed; HEIC photos will not be converted" }
    Set-Content -Path $Marker -Value $wanted -NoNewline
}

if ($args.Count -eq 0) {
    Say 'Set-up is complete. Now give it your gradebook ZIP files, for example:'
    Say '  unpack-submissions.cmd gradebook_*.zip -o Grading'
    exit 0
}

& $VenvPython $Program @args
exit $LASTEXITCODE
