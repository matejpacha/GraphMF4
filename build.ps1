# build.ps1 — Build GraphMF4 as a Windows standalone application
#
# Usage (from repo root):
#   .\build.ps1
#
# Requires Python 3.10+ in PATH.  PyInstaller is installed automatically
# if not already present.
#
# Each invocation auto-increments the patch segment of the version number
# (MAJOR.MINOR.PATCH) and propagates it to:
#   src\version.py  — runtime version used by the application
#   pyproject.toml  — project metadata
#   GraphMF4.iss    — InnoSetup installer definition

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

Set-Location $PSScriptRoot

# --- 1. Ensure PyInstaller is available -------------------------------------
$pyiTest = python -c "import PyInstaller" 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "PyInstaller not found -- installing..." -ForegroundColor Yellow
    python -m pip install "pyinstaller>=6.0"
}

# --- 2. Bump version --------------------------------------------------------
$versionFile   = Join-Path $PSScriptRoot "src\version.py"
$pyprojectFile = Join-Path $PSScriptRoot "pyproject.toml"
$issFile       = Join-Path $PSScriptRoot "GraphMF4.iss"

# Read current version from src/version.py
$versionContent = Get-Content $versionFile -Raw -Encoding UTF8
if ($versionContent -notmatch '__version__\s*=\s*"(\d+)\.(\d+)\.(\d+)"') {
    Write-Host "ERROR: Cannot parse version from $versionFile" -ForegroundColor Red
    exit 1
}
$major = [int]$Matches[1]
$minor = [int]$Matches[2]
$patch = [int]$Matches[3]

$oldVersion = "$major.$minor.$patch"
$patch++
$newVersion = "$major.$minor.$patch"

Write-Host "Version: $oldVersion  ->  $newVersion" -ForegroundColor Cyan

# src\version.py
$versionContent = $versionContent -replace `
    '__version__\s*=\s*"[\d.]+"', `
    "__version__ = `"$newVersion`""
Set-Content $versionFile $versionContent -Encoding UTF8 -NoNewline

# pyproject.toml  (the "version = ..." line inside [project])
$pyprojectContent = Get-Content $pyprojectFile -Raw -Encoding UTF8
$pyprojectContent = $pyprojectContent -replace `
    '(?m)^version\s*=\s*"[\d.]+"', `
    "version = `"$newVersion`""
Set-Content $pyprojectFile $pyprojectContent -Encoding UTF8 -NoNewline

# GraphMF4.iss
$issContent = Get-Content $issFile -Raw -Encoding UTF8
$issContent = $issContent -replace `
    '#define AppVersion\s+"[\d.]+"', `
    "#define AppVersion   `"$newVersion`""
Set-Content $issFile $issContent -Encoding UTF8 -NoNewline

Write-Host "Updated: version.py, pyproject.toml, GraphMF4.iss" -ForegroundColor Green

# --- 3. Build ---------------------------------------------------------------
Write-Host "`nBuilding GraphMF4 v$newVersion (this may take 1-3 minutes)..." -ForegroundColor Cyan
pyinstaller GraphMF4.spec --clean --noconfirm

if ($LASTEXITCODE -ne 0) {
    Write-Host "`nBuild FAILED (exit code $LASTEXITCODE)" -ForegroundColor Red
    exit $LASTEXITCODE
}

# --- 4. Report --------------------------------------------------------------
$exePath = Join-Path $PSScriptRoot "dist\GraphMF4\GraphMF4.exe"
$sizeMB  = [math]::Round((Get-ChildItem "dist\GraphMF4" -Recurse |
             Measure-Object -Property Length -Sum).Sum / 1MB, 1)

Write-Host "`nBuild successful!" -ForegroundColor Green
Write-Host "  Version: $newVersion"
Write-Host "  EXE    : $exePath"
Write-Host "  Size   : $sizeMB MB (full folder)"

# --- 5. Git commit dialog ---------------------------------------------------
$buildDate   = Get-Date -Format "yyyy-MM-dd"
$commitTitle = "build: v$newVersion ($buildDate)"

# WPF input dialog – multiline text area for extra notes
Add-Type -AssemblyName PresentationFramework

[xml]$xaml = @"
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        Title="Git Commit" Width="520" Height="340"
        WindowStartupLocation="CenterScreen" ResizeMode="CanResize"
        Topmost="True">
  <Window.Resources>
    <Style TargetType="Button">
      <Setter Property="Padding"  Value="18,4"/>
      <Setter Property="MinWidth" Value="80"/>
    </Style>
  </Window.Resources>
  <Grid Margin="12">
    <Grid.RowDefinitions>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="*"/>
      <RowDefinition Height="Auto"/>
    </Grid.RowDefinitions>

    <TextBlock Grid.Row="0" Text="Commit message (first line is fixed):"
               FontWeight="SemiBold" Margin="0,0,0,4"/>

    <TextBox Grid.Row="1" Name="TitleBox" IsReadOnly="True"
             Background="#F0F0F0" Padding="4,3"
             FontFamily="Consolas" Margin="0,0,0,8"/>

    <TextBox Grid.Row="2" Name="NotesBox" AcceptsReturn="True"
             TextWrapping="Wrap" VerticalScrollBarVisibility="Auto"
             Padding="4,3" FontFamily="Consolas"
             ToolTip="Optional extra lines appended to the commit message"/>

    <StackPanel Grid.Row="3" Orientation="Horizontal" HorizontalAlignment="Right"
                Margin="0,10,0,0">
      <Button Name="BtnCommit" Content="Commit" IsDefault="True" Margin="0,0,8,0"/>
      <Button Name="BtnSkip"   Content="Skip"   IsCancel="True"/>
    </StackPanel>
  </Grid>
</Window>
"@

$reader = [System.Xml.XmlNodeReader]::new($xaml)
$window = [Windows.Markup.XamlReader]::Load($reader)

$window.FindName("TitleBox").Text = $commitTitle

$doCommit = $false
$window.FindName("BtnCommit").Add_Click({ $script:doCommit = $true; $window.Close() })
$window.FindName("BtnSkip").Add_Click({  $script:doCommit = $false; $window.Close() })

$null = $window.ShowDialog()

if ($doCommit) {
    $notes      = $window.FindName("NotesBox").Text.Trim()
    $fullMessage = if ($notes) { "$commitTitle`n`n$notes" } else { $commitTitle }

    Write-Host "`nCommitting..." -ForegroundColor Cyan
    git add src\version.py pyproject.toml GraphMF4.iss
    git commit -m $fullMessage

    if ($LASTEXITCODE -eq 0) {
        Write-Host "Git commit OK." -ForegroundColor Green
    } else {
        Write-Host "Git commit failed (exit $LASTEXITCODE)." -ForegroundColor Yellow
    }
} else {
    Write-Host "`nGit commit skipped." -ForegroundColor Yellow
}
