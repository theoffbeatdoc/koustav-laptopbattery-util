# Koustav Laptop Battery Util

A lightweight Windows 11 system-tray utility that watches your laptop battery and shows native Windows notifications when it drops too low or charges too high. It exists to stop the laptop from being drained to nothing, or left charging at 100% all day.

- Runs quietly in the tray; no window on startup
- Native, persistent Windows toast notifications with action buttons
- Configurable thresholds (defaults: warn at **20%** discharging, **80%** charging)
- One notification per event, never one per poll
- No network, no account, no telemetry, no admin rights
- Ships as a single `.exe`, plus an optional per-user installer

## Features

| Alert | Fires when | Buttons |
|---|---|---|
| Charge limit reached | Charging and battery >= high threshold (default 80%) | Renotify in 5 mins / Allow charge to 99% / Ignore |
| Battery at 99% | After "Allow charge to 99%", at 99% | Renotify in 5 mins / Ignore |
| Battery is getting low | On battery and battery <= low threshold (default 20%) | Renotify in 5 mins / Ignore |

- **Allow charge to 99%** is a temporary override. Your configured threshold is not changed, and the override resets when the charger is unplugged.
- **Ignore** silences that alert for the current charge or discharge cycle only. Monitoring stays on.
- **Renotify in 5 mins** schedules a single reminder. Before it is shown, the battery state is checked again; if you have unplugged in the meantime, it is dropped.
- A **master toggle** (tray menu or Settings) pauses all monitoring, handy during presentations or gaming.
- Handles sleep/resume, charger plug/unplug, starting above the threshold, readings that wobble around the threshold, and desktops with no battery.

### Settings

| Setting | Default | Range |
|---|---|---|
| Enable battery monitoring | On | |
| Low battery threshold | 20% | 1-98 |
| High battery threshold | 80% | 2-99 (must be above the low threshold) |
| Polling interval | 30 s | 5-300 s |
| Start automatically with Windows | On | |

Settings are stored in `%LOCALAPPDATA%\KoustavLaptopBatteryUtil\config.json`. A corrupt file is logged, set aside as `config.json.corrupt`, and replaced with safe defaults.

## Requirements

- Windows 11 (Windows 10 should work but is untested)
- [uv](https://docs.astral.sh/uv/) (it manages Python 3.12+ for you)
- [Git](https://git-scm.com/)
- [Inno Setup 6](https://jrsoftware.org/isinfo.php), only if you want to build the installer

End users of the built `.exe` or installer need nothing installed.

## Quick start (from source)

```powershell
git clone https://github.com/<your-username>/koustav-laptopbattery-util.git
cd koustav-laptopbattery-util

uv sync
uv run python app.py --install   # register toast buttons / notification identity (once)
uv run python app.py             # starts in the tray
```

Look for the battery icon in the system tray (it may be under the `^` overflow). Launching the app a second time just opens Settings; it never starts a second instance.

> `--install` run from source registers `pythonw.exe` + `app.py`. If you later install the built EXE, run `uv run python app.py --uninstall` first (or just run the EXE's own `--install`, which overwrites it).

## Testing without waiting for the battery

```powershell
uv run python app.py --battery-status        # prints percentage, power state, AC state
uv run python app.py --test-notification     # sample toast (also: final | lower)
uv run python app.py --settings              # open the Settings window
uv run python -m unittest discover -s tests -v
```

To simulate a battery end to end, point the app at a JSON file and edit it while it runs:

```powershell
'{"percent": 79, "ac": true, "charging": true}' | Set-Content fake_battery.json
$env:KBU_FAKE_BATTERY_FILE = "$PWD\fake_battery.json"
uv run python app.py
```

Then change `percent` to `80` to trigger the charge-limit toast, click **Allow charge to 99%**, set `99` for the second toast, or set `"ac": false, "charging": false, "percent": 20` for the low-battery toast.

## Build the EXE

PowerShell blocks unsigned scripts by default, so run the build script with a one-off bypass (no admin needed):

```powershell
powershell -ExecutionPolicy Bypass -File .\build.ps1
```

This syncs dependencies, runs the unit tests, generates the icon, builds a single windowed executable with PyInstaller, and runs a self-check of the built EXE. Output:

```
dist\koustav-laptopbattery-util.exe
```

Quick test of the built EXE (result appears in a message box, since it has no console):

```powershell
.\dist\koustav-laptopbattery-util.exe --battery-status
```

Alternatively, allow local scripts for your user permanently:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
Unblock-File .\build.ps1, .\install.ps1, .\uninstall.ps1
```

## Create the installer

The installer is built with [Inno Setup](https://jrsoftware.org/isinfo.php). It installs per user (no admin prompt), registers the Windows integration, adds an entry to **Settings > Apps**, and supports in-place upgrades.

```powershell
winget install JRSoftware.InnoSetup
```

Build the EXE first (previous section), then compile `installer.iss`:

```powershell
$iscc = @(
  "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
  "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
  "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
) | Where-Object { Test-Path $_ } | Select-Object -First 1

if (-not $iscc) { throw "ISCC.exe not found" }
& $iscc installer.iss
```

> The leading `&` is required in PowerShell when running a quoted path.

Output:

```
dist\KoustavLaptopBatteryUtil-Setup.exe
```

Run it once. It copies the app to `%LOCALAPPDATA%\KoustavLaptopBatteryUtil\`, registers the protocol handler, notification identity and shortcuts, and offers to launch the app. Uninstall via **Settings > Apps**; your `config.json` and `app.log` are kept.

### Installing without the installer

```powershell
powershell -ExecutionPolicy Bypass -File .\install.ps1       # copy EXE, register, start
powershell -ExecutionPolicy Bypass -File .\uninstall.ps1     # add -RemoveData to delete config and logs
```

### Command-line reference

| Command | Purpose |
|---|---|
| *(none)* | Start the tray app (or open Settings if already running) |
| `--settings` | Open Settings in the running instance (starts the app if needed) |
| `--install` | Register protocol, AppUserModelID, Start Menu and Startup shortcuts, then exit |
| `--uninstall [--purge-data]` | Remove the above; optionally delete config and logs |
| `--quit` | Ask the running instance to exit |
| `--battery-status` | Print battery %, power state and AC state |
| `--test-notification [upper\|final\|lower]` | Show a sample toast |
| `--self-check` | Verify all runtime imports (used by the build) |
| `--quiet` | Suppress informational message boxes (for scripts) |
| `--debug` | Verbose logging |

## How it works

**State machine.** Notification logic lives in `kbu/engine.py` as an explicit, unit-tested state machine. There are two cycle types: an *AC cycle* (charger connected) that owns the high-threshold alert and the temporary 99% override, and a *battery cycle* that owns the low-threshold alert. Changing between them, or starting the app, begins a new cycle and resets alert state. Alerts are level-based and one-shot, so starting at 85% notifies once, and 79 -> 80 -> 79 -> 80 does not repeat.

**Toasts and buttons.** Notifications are real WinRT toasts using `scenario="reminder"`, so they stay on screen until dismissed. Each alert uses a fixed tag and group, so a new one replaces the old one instead of stacking. Buttons use protocol activation, e.g. `koustav-laptopbattery://action/charge99`. Windows launches the EXE with that URI; the new process cannot take the single-instance mutex, validates the action against a whitelist, forwards it through a per-user named pipe to the running instance, and exits. The running instance applies it and immediately re-checks the battery.

**Single instance.** A named mutex (`Local\KoustavLaptopBatteryUtil.SingleInstance`) guarantees one tray icon and one monitoring loop. A second launch forwards a request to open Settings.

**Windows identity.** A stable AppUserModelID (`Koustav.KoustavLaptopBatteryUtil`) is attached to a Start Menu shortcut and registered under HKCU, which Windows needs to reliably deliver toasts from an unpackaged app.

**Startup.** Enabling "Start automatically with Windows" creates a `.lnk` in the user's Startup folder. No registry run keys, no admin rights.

**Battery reading.** `GetSystemPowerStatus` from `kernel32.dll`, polled on a background thread that sleeps on an event (no busy loop). A hidden window listens for sleep/resume and AC-change messages to re-poll immediately; polling alone also recovers if an event is missed.

**Resilience.** A failed battery read or toast is logged and retried on the next cycle; the monitor, notifier, IPC and tray each run on their own thread so one failure does not take the app down.

### Project layout

```
koustav-laptopbattery-util/
├── app.py              entry point, main(), CLI
├── installer.iss       Inno Setup script
├── build.ps1  install.ps1  uninstall.ps1
├── pyproject.toml  uv.lock  .python-version
├── assets/icon.ico     generated by build.ps1
├── kbu/
│   ├── engine.py       notification state machine
│   ├── battery.py      power status + classification
│   ├── monitor.py      polling thread
│   ├── notifier.py     toast XML + WinRT backend
│   ├── ipc.py          mutex + named pipe
│   ├── power_events.py sleep/resume + AC change
│   ├── winintegration.py  protocol, AUMID, shortcuts, startup
│   ├── tray.py  settings_ui.py  icon.py  config.py  application.py ...
└── tests/test_engine.py
```

## Files and data

| What | Where |
|---|---|
| Config | `%LOCALAPPDATA%\KoustavLaptopBatteryUtil\config.json` |
| Log (rotating, 512 KB x 3) | `%LOCALAPPDATA%\KoustavLaptopBatteryUtil\app.log` |
| Installed EXE | `%LOCALAPPDATA%\KoustavLaptopBatteryUtil\koustav-laptopbattery-util.exe` |
| Protocol handler | `HKCU\Software\Classes\koustav-laptopbattery` |
| Notification identity | `HKCU\Software\Classes\AppUserModelId\Koustav.KoustavLaptopBatteryUtil` |
| Shortcuts | Start Menu `Programs\` and `Programs\Startup\` |

Everything is per-user. Nothing leaves your machine.

## Known limitations

- **Windows controls notification policy.** Focus / Do Not Disturb and per-app notification settings can suppress or defer toasts. The app cannot override that.
- **Charging detection depends on firmware.** The high alert fires only while the battery is actually *charging*. A laptop that is plugged in but holding at its own charge limit (AC connected, not charging) will not alert. Some firmware stops charging below 99% and clears the charging flag, so the 99% alert may not fire on those machines.
- **Toast button latency.** The one-file EXE unpacks itself on every launch, so a button click takes about 1-2 seconds to register.
- **Unsigned binaries.** Windows SmartScreen or antivirus may flag unsigned PyInstaller executables. Build it yourself from source if in doubt.
- Tested logic (state machine, config, power classification) runs on any OS; the tray, toast, registry and installer layers are Windows-only.

## Troubleshooting

| Problem | Fix |
|---|---|
| `running scripts is disabled` | Use `powershell -ExecutionPolicy Bypass -File .\build.ps1` |
| `Unexpected token 'installer.iss'` | Put `&` before the quoted `ISCC.exe` path |
| `Required [Setup] section directive "AppName" not specified` | `installer.iss` lost its line breaks (often from copy/paste). Re-save it with proper newlines |
| `Icon input file ... not found` during build | Use an absolute `--icon` path in `build.ps1` (PyInstaller resolves it relative to the spec folder) |
| No tray icon | Check the `^` overflow and `app.log`; a second launch only opens Settings |
| No toast appears | Run `--install`, check Settings > System > Notifications and Focus assist; try `--test-notification` |
| Toast buttons do nothing | The app must be running, and the protocol must point at the current EXE; re-run `--install` after moving it |
| Settings says "integration not installed" | Run `--install` from the EXE's final location |
| Build self-check fails | The error lists the missing module; add it to the hidden-import list in `build.ps1` |
| Startup toggle fails | See the warning dialog and `app.log`; verify the Startup folder is writable |

## Uninstall

- **Installer:** Settings > Apps > Koustav Laptop Battery Util > Uninstall.
- **Scripts:** `powershell -ExecutionPolicy Bypass -File .\uninstall.ps1` (add `-RemoveData` to also delete config and logs).
- **Manual:** `koustav-laptopbattery-util.exe --uninstall [--purge-data]`.

Uninstalling removes the shortcuts, protocol and notification registrations, and the EXE. Config and logs are kept unless you purge them.

## Privacy and security

No network access, accounts, analytics or crash reporting. Everything is stored locally under your user profile and HKCU. The single-instance control pipe is restricted to the current user and rejects remote clients, and only whitelisted action names are accepted.

## License

[Mit License](LICENSE)