# RigCheck

Shows live CPU, graphics, memory, network and storage readings (click any of them for
detailed graphs), finds out what's in your PC, what's holding it back, and which upgrades
fit. Includes upgrade previews, a budget planner, drive health and temperatures, a
bottleneck monitor, benchmarks, driver and BIOS checks, shareable rig cards and friend
comparisons, dark and light modes, and in-app updates.

## Files (keep them all in one folder)

| File | What it does |
|---|---|
| `rigcheck.py` | The app window. **Run this one.** |
| `live.py`, `gui_monitor.py` | The Live monitor page |
| `gui_settings.py` | The Settings page |
| `hw_advisor.py` | Hardware detection, recommendations, budget planner, upgrade preview |
| `parts_db.py` | Parts, compatibility rules, new and used price estimates |
| `perf_checks.py` | Free speed-ups: refresh rate, XMP, Game Mode, power plan and more |
| `games_db.py` | Game requirements for "Can I run it?" |
| `mods.py` | Farming Simulator 25 mod analyzer |
| `guides.py` | Install guides and BIOS guides (XMP, Resizable BAR) |
| `share.py` | Rig card images and friend comparisons |
| `hw_tools.py` | Disk, health, monitor, benchmark and update tools |
| `hw_store.py` | Saves your settings and history |
| `app_info.py` | Version number and update checking |
| `updater.py` | Downloads and installs new versions from inside the app |
| `gui_common.py`, `gui_tabs.py` | Parts of the app window |
| `rigcheck.ico`, `rigcheck*.png` | The app icon, logo images and startup splash |
| `build_exe.bat` | Builds a double-clickable `RigCheck.exe` |

## Running it

    pip install psutil pillow
    python rigcheck.py

`pillow` is needed for rig card images; `psutil` improves detection. The .exe includes both.

## Making an .exe

Double-click `build_exe.bat`. The finished app appears in the `dist` folder. Keep the project
folder outside OneDrive (for example `C:\RigCheck`) for the most reliable builds. Windows may
show a "Windows protected your PC" warning the first time it runs: click More info, then
Run anyway.

## Turning on update notifications (optional)

RigCheck can tell you and your friends when a new version is out, using GitHub Releases.

1. Create a free account at github.com and a new repository, for example `rigcheck`.
2. Upload all the files above to it.
3. In `app_info.py`, set `UPDATE_REPO = "yourname/rigcheck"`.
4. Rebuild the .exe with `build_exe.bat`.
5. On GitHub, open Releases > Draft a new release, set the tag to `v` plus `APP_VERSION`
   (for example `v1.7.0`), attach `dist\RigCheck.exe`, and publish.

For each later version: raise `APP_VERSION` (for example to `1.7.1`), rebuild, and publish a
release tagged `v1.7.1`. RigCheck checks every time it opens and every 4 hours while it's
running; anyone on an older version sees a banner with an **Update now** button that downloads
and installs the new version from inside the app. The release must have the new `RigCheck.exe`
attached, named exactly `RigCheck.exe`.

Don't upload the `dist` or `build` folders or `RigCheck.spec`; they're created by the build.

## Optional helpers

- **CPU temperature (Windows):** run
  [LibreHardwareMonitor](https://github.com/LibreHardwareMonitor/LibreHardwareMonitor/releases)
  in the background. RigCheck reads its sensors.
- **Detailed drive health:** install [smartmontools](https://www.smartmontools.org/wiki/Download).
- **Administrator mode:** some checks need it. Use the "Restart as administrator" button.

## Where data is saved

Settings and history: `%APPDATA%\RigCheck` on Windows, `~/.rigcheck` elsewhere.
Rig card images: `Pictures\RigCheck` by default.

## Keeping it current

Part lists and prices are from September 2026. Edit `parts_db.py` to add new parts, or
double-click a price in the Budget planner to enter what you see in stores.
