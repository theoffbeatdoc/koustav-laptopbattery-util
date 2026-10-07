<#
.SYNOPSIS  Removes the app for the current user.
.USAGE     .\uninstall.ps1               keeps config + logs
           .\uninstall.ps1 -RemoveData   deletes config + logs too
#>
[CmdletBinding()]
param([switch]$RemoveData)
$ErrorActionPreference = "Stop"
$name = "koustav-laptopbattery-util"
$dir  = Join-Path $env:LOCALAPPDATA "KoustavLaptopBatteryUtil"
$exe  = Join-Path $dir "$name.exe"

if (Test-Path $exe) {
    $a = @("--uninstall", "--quiet"); if ($RemoveData) { $a += "--purge-data" }
    Start-Process -FilePath $exe -ArgumentList $a -Wait | Out-Null
}
for ($i = 0; $i -lt 20 -and (Get-Process -Name $name -ErrorAction SilentlyContinue); $i++) { Start-Sleep -Milliseconds 250 }
Get-Process -Name $name -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep -Milliseconds 300
Remove-Item -LiteralPath $exe -Force -ErrorAction SilentlyContinue
if ($RemoveData) {
    Remove-Item -LiteralPath $dir -Recurse -Force -ErrorAction SilentlyContinue
} elseif (-not (Get-ChildItem -LiteralPath $dir -ErrorAction SilentlyContinue)) {
    Remove-Item -LiteralPath $dir -Force -ErrorAction SilentlyContinue
}
Write-Host "Uninstalled." -ForegroundColor Green
if (-not $RemoveData) { Write-Host "Config and logs kept in $dir" }
