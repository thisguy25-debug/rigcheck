# RigCheck

Shows live CPU, graphics, memory, network and storage readings (click any of them for
detailed graphs), finds out what's in your PC, what's holding it back, and which upgrades
fit. Includes upgrade previews, a monitor resolution and refresh rate check, a game storage
cleaner, drive health, graphics card temperature, a bottleneck monitor, benchmarks, driver and
BIOS checks, shareable rig cards and friend comparisons with one-click posting to Reddit and
Discord, dark and light modes, and in-app updates.

RigCheck uses only what Windows (and, for NVIDIA cards, the NVIDIA driver) already provides. It
doesn't download or install any third-party programs or drivers.

## Files (keep them all in one folder)

| File | What it does |
|---|---|
| `rigcheck.py` | The app window. **Run this one.** |
| `live.py`, `gui_monitor.py` | The Live monitor page |
| `gui_settings.py` | The Settings page |
| `hw_advisor.py` | Hardware detection, recommendations, upgrade preview |
| `parts_db.py` | Parts, compatibility rules, new and used price estimates |
| `perf_checks.py` | Monitor resolution and refresh rate checks and fixes, plus other Windows checks |
| `games_db.py` | Game requirements for "Can I run it?" |
| `mods.py` | Farming Simulator 25 mod analyzer |
| `guides.py` | Install guides and BIOS guides (XMP, Resizable BAR) |
| `share.py` | Rig card images and friend comparisons |
| `hw_tools.py` | Disk, health, monitor, benchmark and update tools |
| `hw_store.py` | Saves your settings and history |
| `app_info.py` | Version number and update checking |
| `prices.json` | Part prices. **Edit it on GitHub to update prices for everyone** |
| `prices.py` | Loads prices.json (built in, then the latest from GitHub) |
| `cleanup.py` | Removes the sensor helper that versions 1.8 to 1.10 could install |
| `game_storage.py`, `gui_games.py` | The Games page: installed games, play time and what to remove |
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

## Administrator mode

Some checks, like detailed drive health, need it. Use the "Restart as administrator" button.

## Where data is saved

Settings and history: `%APPDATA%\RigCheck` on Windows, `~/.rigcheck` elsewhere.
Rig card images: `Pictures\RigCheck` by default.

## Keeping prices current

RigCheck downloads `prices.json` from this repository's `main` branch every time it opens,
so prices update for everyone without a new release:

1. On GitHub, open `prices.json` and click the pencil (Edit) icon.
2. Change the prices, and set `"updated"` to today's date (for example `"2026-11-02"`).
3. Click **Commit changes**.

Keep part names exactly as they are. Typical lowest US prices from Amazon, Newegg and Best
Buy work best.

## Monitor check

The Overview's Monitor card shows each screen's resolution and refresh rate. It reads the
screen's real (native) resolution from the monitor itself, and warns when Windows is running
it below full resolution or below its best refresh rate, or when the cable is plugged into
the motherboard instead of the graphics card. **Switch to …** fixes it in one click; the
change reverts on its own after 15 seconds unless you click Keep it.

## Games page

Lists installed Steam, Epic and Xbox app games with size, play time and when each was last
played, and suggests the ones worth removing to free space. Steam play time is exact; Epic
and Xbox don't keep play time on the PC, so "last played" is estimated from the game's own
settings and save files. RigCheck never deletes game files itself: **Uninstall** opens the
launcher's own uninstall, so cloud saves and the launcher stay in sync.

## Processor temperature, power and fan

Windows doesn't share these with programs. Reading them needs a third-party hardware driver,
and Windows Defender flags those, so RigCheck doesn't show them. Versions 1.8 to 1.10 could
install LibreHardwareMonitor for this. RigCheck now offers to remove it when it starts (also in
Settings > Your data > Remove old sensor helper). If PawnIO is listed in Installed apps
afterwards, uninstall it there too.
