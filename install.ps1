<#
.SYNOPSIS  Installs the built EXE for the current user (no admin needed).
.DESCRIPTION
  Copies the EXE to %LOCALAPPDATA%\KoustavLaptopBatteryUtil\, runs "--install"
  (protocol, AppUserModelID, Start Menu + Startup shortcuts) and starts the app.
.USAGE     .\install.ps1            (after .\build.ps1)
#>
[CmdletBinding()]
param(
    [string]$ExePath = (Join-Path $PSScriptRoot "dist\koustav-laptopbattery-util.exe"),
    [switch]$NoLaunch
)
$ErrorActionPreference = "Stop"
$name = "koustav-laptopbattery-util"
$dir  = Join-Path $env:LOCALAPPDATA "KoustavLaptopBatteryUtil"
$dest = Join-Path $dir "$name.exe"

if (-not (Test-Path $ExePath)) { throw "EXE not found: $ExePath  (run .\build.ps1 first)" }
New-Item -ItemType Directory -Force -Path $dir | Out-Null

# Stop a running copy so the file isn't locked: ask nicely, then force.
if (Test-Path $dest) { & $dest --quit --quiet | Out-Null }
for ($i = 0; $i -lt 20 -and (Get-Process -Name $name -ErrorAction SilentlyContinue); $i++) { Start-Sleep -Milliseconds 250 }
Get-Process -Name $name -ErrorAction SilentlyContinue | Stop-Process -Force

Copy-Item -LiteralPath $ExePath -Destination $dest -Force
Unblock-File -LiteralPath $dest

$p = Start-Process -FilePath $dest -ArgumentList "--install", "--quiet" -Wait -PassThru
if ($p.ExitCode -ne 0) { throw "--install failed (exit $($p.ExitCode)). See $dir\app.log" }
Write-Host "Installed to $dest" -ForegroundColor Green

if (-not $NoLaunch) {
    Start-Process -FilePath $dest
    Write-Host "Started (look for the battery icon in the tray; it may be under the ^ overflow)."
}
