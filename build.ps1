<#
.SYNOPSIS  Builds dist\koustav-laptopbattery-util.exe (single file, windowed).
.USAGE     From the project folder:   .\build.ps1
#>
[CmdletBinding()]
param([switch]$SkipTests)

$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot

function Step([string]$Label, [scriptblock]$Block) {
    Write-Host "==> $Label" -ForegroundColor Cyan
    & $Block
    if ($LASTEXITCODE -ne 0) { throw "$Label failed (exit code $LASTEXITCODE)" }
}

Step "Sync environment"      { uv sync }
if (-not $SkipTests) {
    Step "Run unit tests"    { uv run python -m unittest discover -s tests }
}
Step "Generate icon"         { uv run python -m kbu.icon assets\icon.ico }

$hidden = @(
    "pystray._win32",
    "PIL.ImageTk",
    "win32timezone",
    "win32com.shell.shell", "win32com.propsys.propsys", "win32com.propsys.pscon",
    "win32api", "win32con", "win32gui", "win32pipe", "win32file", "win32security",
    "ntsecuritycon", "pythoncom", "pywintypes",
    "winrt.system",
    "winrt.windows.foundation",
    "winrt.windows.foundation.collections",
    "winrt.windows.data.xml.dom",
    "winrt.windows.ui.notifications"
)
$piArgs = @(
    "--noconfirm", "--clean", "--onefile", "--windowed",
    "--name", "koustav-laptopbattery-util",
    "--icon", (Join-Path $PSScriptRoot "assets\icon.ico"),
    "--distpath", "dist", "--workpath", "build", "--specpath", "build",
    "--collect-submodules", "winrt"
)
foreach ($h in $hidden) { $piArgs += @("--hidden-import", $h) }
$piArgs += (Join-Path $PSScriptRoot "app.py")

Step "Build EXE (PyInstaller)" { uv run pyinstaller @piArgs }

$exe = Join-Path $PSScriptRoot "dist\koustav-laptopbattery-util.exe"
if (-not (Test-Path $exe)) { throw "Build finished but $exe was not created" }

# Prove the frozen EXE can import everything it needs (windowed EXE -> use exit code).
Write-Host "==> Self-check of built EXE" -ForegroundColor Cyan
$p = Start-Process -FilePath $exe -ArgumentList "--self-check" -Wait -PassThru
if ($p.ExitCode -ne 0) {
    throw "Self-check failed (exit $($p.ExitCode)). See $env:LOCALAPPDATA\KoustavLaptopBatteryUtil\app.log"
}

$size = [math]::Round((Get-Item $exe).Length / 1MB, 1)
Write-Host "`nBuilt: $exe ($size MB)" -ForegroundColor Green
