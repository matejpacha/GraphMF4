# build.ps1 — Build GraphMF4 as a Windows standalone application
#
# Usage (from repo root):
#   .\build.ps1
#
# Requires Python 3.10+ in PATH.  PyInstaller is installed automatically
# if not already present.

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

Set-Location $PSScriptRoot

# --- 1. Ensure PyInstaller is available -------------------------------------
$pyiTest = python -c "import PyInstaller" 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "PyInstaller not found -- installing..." -ForegroundColor Yellow
    python -m pip install "pyinstaller>=6.0"
}

# --- 2. Build ---------------------------------------------------------------
Write-Host "`nBuilding GraphMF4 (this may take 1-3 minutes)..." -ForegroundColor Cyan
pyinstaller GraphMF4.spec --clean --noconfirm

if ($LASTEXITCODE -ne 0) {
    Write-Host "`nBuild FAILED (exit code $LASTEXITCODE)" -ForegroundColor Red
    exit $LASTEXITCODE
}

# --- 3. Report --------------------------------------------------------------
$exePath = Join-Path $PSScriptRoot "dist\GraphMF4\GraphMF4.exe"
$sizeMB  = [math]::Round((Get-ChildItem "dist\GraphMF4" -Recurse |
             Measure-Object -Property Length -Sum).Sum / 1MB, 1)

Write-Host "`nBuild successful!" -ForegroundColor Green
Write-Host "  EXE  : $exePath"
Write-Host "  Size : $sizeMB MB (full folder)"
