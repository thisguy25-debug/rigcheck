"""
Game storage: find installed games, how big they are, how long you've played them and when
you last played, and suggest the ones worth removing to free up space.

Steam keeps accurate play time and last-played dates on this PC, so Steam games get the most
detail. Epic and Xbox/Game Pass games are listed with their size; those launchers don't keep
play time locally, so RigCheck estimates "last played" from when the game's own files (such
as settings and saves inside its folder) last changed, and says so.

RigCheck never deletes game files itself: removing a game opens the launcher's own uninstall,
so the launcher stays in sync and cloud saves are kept.
"""

import glob
import json
import os
import re
import string
import time

import hw_advisor as hwa

WINDOWS = hwa.SYSTEM == "Windows" and os.name == "nt"
DAY = 86400
NOT_GAMES = re.compile(r"redistributable|steamworks common|proton|steam linux runtime|steamvr|"
                       r"directx|vc\+\+|wallpaper engine|soundtrack|dedicated server|benchmark|sdk",
                       re.I)
TOOL_APPIDS = {"228980", "1070560", "1391110", "1628350", "250820", "1493710"}


# ---------------------------------------------------------------- tiny VDF reader (Steam's file format)
def parse_vdf(text):
    tokens = re.findall(r'"((?:[^"\\]|\\.)*)"|([{}])', text)
    stack = [{}]
    key = None
    for quoted, brace in tokens:
        if brace == "{":
            new = {}
            if key is not None:
                stack[-1][key] = new
            stack.append(new)
            key = None
        elif brace == "}":
            if len(stack) > 1:
                stack.pop()
            key = None
        elif key is None:
            key = quoted.replace("\\\\", "\\")
        else:
            stack[-1][key] = quoted.replace("\\\\", "\\")
            key = None
    return stack[0]


def _ci(d, name):
    """Case-insensitive dictionary lookup (Steam's files mix capitalization)."""
    if not isinstance(d, dict):
        return None
    for k, v in d.items():
        if k.lower() == name.lower():
            return v
    return None


def _read(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return None


# ---------------------------------------------------------------- Steam
def steam_dir():
    if WINDOWS:
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as k:
                p = winreg.QueryValueEx(k, "SteamPath")[0]
                if p and os.path.isdir(p):
                    return os.path.normpath(p)
        except OSError:
            pass
        for p in (r"C:\Program Files (x86)\Steam", r"C:\Program Files\Steam"):
            if os.path.isdir(p):
                return p
    for p in ("~/.steam/steam", "~/.local/share/Steam", "~/Library/Application Support/Steam"):
        p = os.path.expanduser(p)
        if os.path.isdir(p):
            return p
    return None


def _steam_playtime(steam):
    """{appid: (minutes played, last played unix time)} from every Steam account on this PC."""
    out = {}
    for cfg in glob.glob(os.path.join(steam, "userdata", "*", "config", "localconfig.vdf")):
        text = _read(cfg)
        if not text:
            continue
        data = parse_vdf(text)
        apps = data
        for key in ("UserLocalConfigStore", "Software", "Valve", "Steam", "apps"):
            apps = _ci(apps, key) or {}
        for appid, info in apps.items():
            if not isinstance(info, dict):
                continue
            mins = int(_ci(info, "Playtime") or 0)
            last = int(_ci(info, "LastPlayed") or 0)
            old_m, old_l = out.get(appid, (0, 0))
            out[appid] = (max(mins, old_m), max(last, old_l))
    return out


def steam_games():
    steam = steam_dir()
    if not steam:
        return []
    libraries = {os.path.join(steam, "steamapps")}
    lf = _read(os.path.join(steam, "steamapps", "libraryfolders.vdf"))
    if lf:
        folders = _ci(parse_vdf(lf), "libraryfolders") or {}
        for v in folders.values():
            path = _ci(v, "path") if isinstance(v, dict) else v
            if path:
                libraries.add(os.path.join(os.path.normpath(path), "steamapps"))
    playtime = _steam_playtime(steam)
    games = []
    for lib in libraries:
        for acf in glob.glob(os.path.join(lib, "appmanifest_*.acf")):
            state = _ci(parse_vdf(_read(acf) or ""), "AppState") or {}
            appid, name = str(_ci(state, "appid") or ""), _ci(state, "name") or ""
            if not appid or appid in TOOL_APPIDS or NOT_GAMES.search(name):
                continue
            size = int(_ci(state, "SizeOnDisk") or 0)
            folder = os.path.join(lib, "common", _ci(state, "installdir") or "")
            mins, last = playtime.get(appid, (0, 0))
            last = max(last, int(_ci(state, "LastPlayed") or 0))
            games.append({"launcher": "Steam", "id": appid, "name": name, "size": size, "folder": folder,
                          "minutes": mins, "last_played": last or None, "exact": True,
                          "installed": _installed_time(acf)})
    return games


# ---------------------------------------------------------------- Epic Games
def epic_games():
    base = os.path.join(os.environ.get("PROGRAMDATA", r"C:\ProgramData"), "Epic", "EpicGamesLauncher",
                        "Data", "Manifests")
    games = []
    for item in glob.glob(os.path.join(base, "*.item")):
        try:
            d = json.loads(_read(item) or "{}")
        except ValueError:
            continue
        name = d.get("DisplayName") or d.get("AppName")
        cats = [c.lower() for c in d.get("AppCategories") or []]
        if not name or (cats and "games" not in cats) or NOT_GAMES.search(name):
            continue
        folder = d.get("InstallLocation") or ""
        games.append({"launcher": "Epic", "id": d.get("AppName"), "name": name,
                      "size": int(d.get("InstallSize") or 0), "folder": folder, "minutes": None,
                      "last_played": _last_used(folder), "exact": False, "installed": _installed_time(item)})
    return games


# ---------------------------------------------------------------- Xbox / Game Pass (PC)
def xbox_games():
    if not WINDOWS:
        return []
    games = []
    for letter in string.ascii_uppercase:
        root = f"{letter}:\\XboxGames"
        if not os.path.isdir(root):
            continue
        for entry in os.scandir(root):
            if not entry.is_dir() or entry.name.lower() in ("gamesave", "gamingservices"):
                continue
            size = _folder_size(entry.path)
            if size < 200 * 1024 ** 2:
                continue
            games.append({"launcher": "Xbox", "id": entry.name, "name": entry.name, "size": size,
                          "folder": entry.path, "minutes": None, "last_played": _last_used(entry.path),
                          "exact": False, "installed": _installed_time(entry.path)})
    return games


# ---------------------------------------------------------------- helpers
def _installed_time(path):
    try:
        return os.path.getctime(path)
    except OSError:
        return None


def _folder_size(path, limit=60):
    total, start = 0, time.time()
    for dp, _dn, fns in os.walk(path):
        for f in fns:
            try:
                total += os.path.getsize(os.path.join(dp, f))
            except OSError:
                pass
        if time.time() - start > limit:
            break
    return total


def _last_used(folder, max_files=4000):
    """Best guess at when a game was last played, for launchers that don't record it: the newest
    change to small files a game writes while running (settings, saves, logs, caches). Big game
    data files are skipped because updates rewrite those."""
    if not folder or not os.path.isdir(folder):
        return None
    newest, seen = 0.0, 0
    for dp, dn, fns in os.walk(folder):
        dn[:] = [d for d in dn if d.lower() not in ("__installer", "redist", "_commonredist", "directx")]
        for f in fns:
            seen += 1
            if seen > max_files:
                return newest or None
            if not f.lower().endswith((".ini", ".cfg", ".json", ".log", ".sav", ".save", ".dat", ".xml",
                                       ".txt", ".config")):
                continue
            try:
                st = os.stat(os.path.join(dp, f))
            except OSError:
                continue
            if st.st_size < 5 * 1024 ** 2:
                newest = max(newest, st.st_mtime)
    return newest or None


# ---------------------------------------------------------------- recommendations
def _days(ts, now):
    return None if not ts else max(0, (now - ts) / DAY)


def assess(game, now=None):
    """Adds 'reason', 'level' (remove / maybe / keep) and 'score' (higher = better to remove)."""
    now = now or time.time()
    days = _days(game["last_played"], now)
    installed_days = _days(game.get("installed"), now)
    gb = game["size"] / 1024 ** 3
    hours = None if game["minutes"] is None else game["minutes"] / 60
    reasons = []
    score = gb  # bigger games free more space
    if days is None:
        if game["exact"] and hours == 0:
            reasons.append("never played")
            if installed_days and installed_days > 30:
                score *= 4
                reasons[-1] = f"never played since it was installed {installed_days / 30:.0f} months ago" \
                    if installed_days > 60 else "never played since it was installed over a month ago"
            else:
                score *= 1.5
        else:
            score *= 1.2
            reasons.append("no record of when it was last played")
    elif days >= 180:
        score *= 4
        reasons.append(f"last played {days / 30:.0f} months ago")
    elif days >= 60:
        score *= 2.5
        reasons.append(f"last played {days / 30:.0f} months ago")
    elif days >= 21:
        score *= 1.2
        reasons.append(f"last played {days:.0f} days ago")
    else:
        score *= 0.1
        reasons.append("played recently" if days >= 1 else "played today")
    if hours is not None and hours > 0:
        if hours < 2:
            score *= 1.5
            reasons.append(f"only {hours * 60:.0f} minutes played in total" if hours < 1
                           else f"only {hours:.1f} hours played in total")
        elif hours > 100 and (days or 0) < 120:
            score *= 0.5
            reasons.append(f"{hours:,.0f} hours played, a favorite")
        elif hours >= 10:
            reasons.append(f"{hours:,.0f} hours played")
    if not game["exact"] and game["last_played"]:
        reasons[0] = reasons[0].replace("last played", "probably last played")
    level = "keep"
    if gb >= 1 and (days is None or days >= 60) and score >= 20:
        level = "remove"
    elif gb >= 1 and (days is None or days >= 21) and score >= 8:
        level = "maybe"
    if level == "remove" and hours and hours >= 20 and (days or 0) < 180:
        level = "maybe"  # a game you've put real time into gets a softer suggestion
    game.update(score=round(score, 1), level=level, reason=", ".join(reasons).capitalize())
    return game


def scan(progress=None):
    games = []
    for label, fn in (("Steam", steam_games), ("Epic Games", epic_games), ("Xbox app", xbox_games)):
        if progress:
            progress(f"Checking {label} games…")
        try:
            games += fn()
        except Exception:
            continue
    now = time.time()
    games = [assess(g, now) for g in games if g["size"] > 0]
    games.sort(key=lambda g: (-{"remove": 2, "maybe": 1, "keep": 0}[g["level"]], -g["score"]))
    return {"games": games, "total": sum(g["size"] for g in games),
            "suggested": sum(g["size"] for g in games if g["level"] == "remove"),
            "steam_found": steam_dir() is not None}


# ---------------------------------------------------------------- actions
def uninstall(game):
    """Open the launcher's own uninstall for this game. Returns a message for the user."""
    import webbrowser
    if game["launcher"] == "Steam":
        webbrowser.open(f"steam://uninstall/{game['id']}")
        return f"Steam is asking to confirm uninstalling {game['name']}."
    if game["launcher"] == "Epic":
        webbrowser.open("com.epicgames.launcher://store/library")
        return (f"The Epic Games Launcher is open. In your Library, click the three dots on "
                f"{game['name']} and choose Uninstall.")
    if WINDOWS:
        os.startfile("ms-settings:appsfeatures")
    return f"Windows' Installed apps list is open. Find {game['name']} and choose Uninstall."
