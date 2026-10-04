"""
Free speed-ups: Windows settings that quietly cost performance, and fixes for them.

Every check returns a dict:
    id, title, status ("ok", "fix", "tip", "unknown"), detail,
    action: None or {"type": "auto" | "open" | "guide" | "page", "label": str, "arg": ...},
    restart: bool (a restart is needed for the fix to take effect)
"""

import os
import re
import subprocess

import hw_advisor as hwa
from hw_advisor import SYSTEM, run, NO_WINDOW

WINDOWS = SYSTEM == "Windows" and os.name == "nt"
if WINDOWS:
    import ctypes
    import winreg
    from ctypes import wintypes

INTEGRATED_HINTS = ("intel(r) uhd", "intel(r) hd", "intel uhd", "iris", "radeon(tm) graphics",
                    "radeon graphics", "intel(r) graphics", "arc(tm) graphics")


# =============================================================================
# Registry helpers
# =============================================================================
def _reg_get(root, path, name):
    try:
        with winreg.OpenKey(root, path) as k:
            return winreg.QueryValueEx(k, name)[0]
    except OSError:
        return None


def _reg_set_dword(root, path, name, value):
    with winreg.CreateKeyEx(root, path, 0, winreg.KEY_SET_VALUE) as k:
        winreg.SetValueEx(k, name, 0, winreg.REG_DWORD, value)


# =============================================================================
# Displays: refresh rate and which graphics chip drives each monitor
# =============================================================================
if WINDOWS:
    class DEVMODEW(ctypes.Structure):
        _fields_ = [("dmDeviceName", wintypes.WCHAR * 32), ("dmSpecVersion", wintypes.WORD),
                    ("dmDriverVersion", wintypes.WORD), ("dmSize", wintypes.WORD),
                    ("dmDriverExtra", wintypes.WORD), ("dmFields", wintypes.DWORD),
                    ("dmPositionX", wintypes.LONG), ("dmPositionY", wintypes.LONG),
                    ("dmDisplayOrientation", wintypes.DWORD), ("dmDisplayFixedOutput", wintypes.DWORD),
                    ("dmColor", ctypes.c_short), ("dmDuplex", ctypes.c_short),
                    ("dmYResolution", ctypes.c_short), ("dmTTOption", ctypes.c_short),
                    ("dmCollate", ctypes.c_short), ("dmFormName", wintypes.WCHAR * 32),
                    ("dmLogPixels", wintypes.WORD), ("dmBitsPerPel", wintypes.DWORD),
                    ("dmPelsWidth", wintypes.DWORD), ("dmPelsHeight", wintypes.DWORD),
                    ("dmDisplayFlags", wintypes.DWORD), ("dmDisplayFrequency", wintypes.DWORD),
                    ("dmICMMethod", wintypes.DWORD), ("dmICMIntent", wintypes.DWORD),
                    ("dmMediaType", wintypes.DWORD), ("dmDitherType", wintypes.DWORD),
                    ("dmReserved1", wintypes.DWORD), ("dmReserved2", wintypes.DWORD),
                    ("dmPanningWidth", wintypes.DWORD), ("dmPanningHeight", wintypes.DWORD)]

    class DISPLAY_DEVICEW(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("DeviceName", wintypes.WCHAR * 32),
                    ("DeviceString", wintypes.WCHAR * 128), ("StateFlags", wintypes.DWORD),
                    ("DeviceID", wintypes.WCHAR * 128), ("DeviceKey", wintypes.WCHAR * 128)]

ENUM_CURRENT_SETTINGS = -1
DM_DISPLAYFREQUENCY = 0x400000
CDS_UPDATEREGISTRY, CDS_TEST = 0x1, 0x2


def _devmode(device, index):
    dm = DEVMODEW()
    dm.dmSize = ctypes.sizeof(DEVMODEW)
    ok = ctypes.windll.user32.EnumDisplaySettingsW(device, index, ctypes.byref(dm))
    return dm if ok else None


def displays():
    """Active monitors with their current and best available refresh rate."""
    if not WINDOWS:
        return []
    out = []
    user32 = ctypes.windll.user32
    i = 0
    while True:
        dd = DISPLAY_DEVICEW()
        dd.cb = ctypes.sizeof(dd)
        if not user32.EnumDisplayDevicesW(None, i, ctypes.byref(dd), 0):
            break
        i += 1
        if not dd.StateFlags & 0x1:  # not attached to the desktop
            continue
        cur = _devmode(dd.DeviceName, ENUM_CURRENT_SETTINGS)
        if not cur:
            continue
        best, n = cur.dmDisplayFrequency, 0
        while True:
            m = _devmode(dd.DeviceName, n)
            if not m:
                break
            n += 1
            if (m.dmPelsWidth, m.dmPelsHeight) == (cur.dmPelsWidth, cur.dmPelsHeight) \
                    and m.dmBitsPerPel >= cur.dmBitsPerPel and not m.dmDisplayFlags & 0x2:  # skip interlaced
                best = max(best, m.dmDisplayFrequency)
        mon = DISPLAY_DEVICEW()
        mon.cb = ctypes.sizeof(mon)
        monitor = mon.DeviceString if user32.EnumDisplayDevicesW(dd.DeviceName, 0, ctypes.byref(mon), 0) else ""
        out.append({"device": dd.DeviceName, "adapter": dd.DeviceString, "monitor": monitor,
                    "primary": bool(dd.StateFlags & 0x4), "width": cur.dmPelsWidth,
                    "height": cur.dmPelsHeight, "hz": cur.dmDisplayFrequency, "max_hz": best})
    return out


def set_refresh_rate(device, hz):
    """Returns True on success. The change is saved so it survives a restart."""
    dm = _devmode(device, ENUM_CURRENT_SETTINGS)
    if not dm:
        return False
    dm.dmDisplayFrequency = hz
    dm.dmFields = DM_DISPLAYFREQUENCY
    change = ctypes.windll.user32.ChangeDisplaySettingsExW
    if change(device, ctypes.byref(dm), None, CDS_TEST, None) != 0:
        return False
    return change(device, ctypes.byref(dm), None, CDS_UPDATEREGISTRY, None) == 0


# =============================================================================
# Individual checks
# =============================================================================
def _check_displays(hw):
    checks = []
    ds = displays()
    dedicated = [g for g in hw["gpu"] if not g["integrated"]]
    for d in ds:
        label = "Main monitor" if d["primary"] else f"Monitor {d['device'][-1]}"
        if d["max_hz"] >= 75 and d["hz"] < d["max_hz"] - 1:
            checks.append({
                "id": f"refresh:{d['device']}", "title": f"{label} is running at {d['hz']} Hz",
                "status": "fix",
                "detail": f"It supports {d['max_hz']} Hz at {d['width']}×{d['height']}. Games will look "
                          f"smoother and feel more responsive at the higher rate. This is one of the "
                          f"most common missed settings.",
                "action": {"type": "auto", "label": f"Switch to {d['max_hz']} Hz",
                           "arg": (d["device"], d["max_hz"], d["hz"])}, "restart": False})
        else:
            checks.append({"id": f"refresh:{d['device']}", "title": f"{label} refresh rate",
                           "status": "ok", "detail": f"Running at its best rate, {d['hz']} Hz.",
                           "action": None, "restart": False})
        if dedicated and any(h in d["adapter"].lower() for h in INTEGRATED_HINTS):
            checks.append({
                "id": f"cable:{d['device']}", "title": f"{label} is plugged into the motherboard",
                "status": "fix",
                "detail": f"It's driven by {d['adapter']} instead of your {dedicated[0]['name']}. Move the "
                          "monitor cable from the ports near the USB sockets to the ports on the "
                          "graphics card, lower down on the back of the PC. This can multiply your "
                          "frame rate.",
                "action": None, "restart": False})
    return checks


def _check_xmp(hw, recs):
    rec = next((r for r in recs if r["component"] == "RAM speed"), None)
    if rec:
        return [{"id": "xmp", "title": "Memory is running below its rated speed", "status": "fix",
                 "detail": rec["issue"] + " Turning on XMP in the BIOS is free and takes two minutes.",
                 "action": {"type": "guide", "label": "Show me how", "arg": "XMP"}, "restart": True}]
    speed = hw["ram"].get("configured_mhz")
    return [{"id": "xmp", "title": "Memory speed", "status": "ok",
             "detail": f"Running at {speed} MHz." if speed else "Looks fine.", "action": None,
             "restart": False}]


def _check_game_mode():
    v = _reg_get(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\GameBar", "AutoGameModeEnabled")
    if v == 0:
        return [{"id": "gamemode", "title": "Game Mode is off", "status": "fix",
                 "detail": "Game Mode stops Windows Update and background tasks from interrupting "
                           "games. It's on by default and usually best left on.",
                 "action": {"type": "auto", "label": "Turn on Game Mode"}, "restart": False}]
    return [{"id": "gamemode", "title": "Game Mode", "status": "ok", "detail": "Game Mode is on.",
             "action": None, "restart": False}]


def _check_background_recording():
    v = _reg_get(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\GameDVR",
                 "AppCaptureEnabled")
    if v == 1:
        return [{"id": "dvr", "title": "Background game recording is on", "status": "tip",
                 "detail": "Xbox Game Bar is constantly recording your games in the background so you "
                           "can save the last few minutes. That costs a little performance. Turn it "
                           "off if you don't use it (NVIDIA's own Instant Replay is unaffected).",
                 "action": {"type": "auto", "label": "Turn off background recording"}, "restart": False}]
    return [{"id": "dvr", "title": "Background game recording", "status": "ok",
             "detail": "Not recording in the background.", "action": None, "restart": False}]


POWER_PLANS = {"a1841308-3541-4fab-bc81-f71556f20b4a": "Power saver",
               "381b4222-f694-41f0-9685-ff5bb260df2e": "Balanced",
               "8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c": "High performance",
               "e9a42b02-d5df-448d-aa00-03f14749eb61": "Ultimate Performance"}


def _check_power_plan():
    out = run(["powercfg", "/getactivescheme"])
    m = re.search(r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})", out, re.I)
    if not m:
        return []
    guid = m.group(1).lower()
    name = POWER_PLANS.get(guid) or (re.search(r"\((.+)\)", out) or [None, "Custom"])[1]
    if guid == "a1841308-3541-4fab-bc81-f71556f20b4a":
        return [{"id": "power", "title": "Power saver plan is active", "status": "fix",
                 "detail": "Power saver holds your processor back to save energy. Balanced lets it "
                           "run at full speed when needed and still idles efficiently.",
                 "action": {"type": "auto", "label": "Switch to Balanced"}, "restart": False}]
    return [{"id": "power", "title": "Power plan", "status": "ok",
             "detail": f"{name}. That's fine for gaming.", "action": None, "restart": False}]


def _check_gpu_scheduling(hw):
    v = _reg_get(winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\GraphicsDrivers",
                 "HwSchMode")
    names = " ".join(g["name"].lower() for g in hw["gpu"])
    newer = re.search(r"rtx (40|50)\d0|rx (7|9)\d00|arc b", names)
    if v == 1 and newer:
        return [{"id": "hags", "title": "Hardware-accelerated GPU scheduling is off", "status": "tip",
                 "detail": "Your graphics card needs this setting for frame generation (DLSS 3/4 or "
                           "FSR 3), which can raise frame rates a lot in supported games.",
                 "action": {"type": "open", "label": "Open graphics settings",
                            "arg": "ms-settings:display-advancedgraphics"}, "restart": True}]
    if v == 2:
        return [{"id": "hags", "title": "Hardware-accelerated GPU scheduling", "status": "ok",
                 "detail": "On.", "action": None, "restart": False}]
    return []


def _check_resizable_bar():
    out = run(["nvidia-smi", "-q", "-d", "MEMORY"])
    m = re.search(r"BAR1 Memory Usage\s*\n\s*Total\s*:\s*(\d+)\s*MiB", out)
    if not m:
        return []
    if int(m.group(1)) <= 256:
        return [{"id": "rebar", "title": "Resizable BAR is off", "status": "tip",
                 "detail": "Resizable BAR lets the processor reach all of your graphics card's memory "
                           "at once, which adds a few percent in many newer games. It's switched on "
                           "in the BIOS.",
                 "action": {"type": "guide", "label": "Show me how", "arg": "REBAR"}, "restart": True}]
    return [{"id": "rebar", "title": "Resizable BAR", "status": "ok", "detail": "On.",
             "action": None, "restart": False}]


def startup_apps():
    """Programs that start with Windows and aren't disabled in Task Manager."""
    if not WINDOWS:
        return []
    approved_base = r"Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved"
    names = []
    for root in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        for path, approved in ((r"Software\Microsoft\Windows\CurrentVersion\Run", "Run"),
                               (r"Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Run", "Run32")):
            try:
                with winreg.OpenKey(root, path) as k:
                    for i in range(winreg.QueryInfoKey(k)[1]):
                        name = winreg.EnumValue(k, i)[0]
                        flag = _reg_get(root, rf"{approved_base}\{approved}", name)
                        if not (isinstance(flag, bytes) and flag[:1] in (b"\x03", b"\x01")):
                            names.append(name)
            except OSError:
                pass
    for folder in (os.path.join(os.environ.get("APPDATA", ""), r"Microsoft\Windows\Start Menu\Programs\Startup"),
                   os.path.join(os.environ.get("PROGRAMDATA", ""), r"Microsoft\Windows\Start Menu\Programs\Startup")):
        try:
            for f in os.listdir(folder):
                if f.lower().endswith(".lnk"):
                    flag = _reg_get(winreg.HKEY_CURRENT_USER, rf"{approved_base}\StartupFolder", f)
                    if not (isinstance(flag, bytes) and flag[:1] in (b"\x03", b"\x01")):
                        names.append(f[:-4])
        except OSError:
            pass
    return sorted(set(names), key=str.lower)


def _check_startup():
    apps = startup_apps()
    if len(apps) >= 12:
        return [{"id": "startup", "title": f"{len(apps)} programs start with Windows", "status": "tip",
                 "detail": "Each one slows startup and uses memory in the background. Disable the ones "
                           "you don't need right away: " + ", ".join(apps[:8]) +
                           (", and more." if len(apps) > 8 else "."),
                 "action": {"type": "open", "label": "Open startup apps", "arg": "taskmgr-startup"},
                 "restart": False}]
    return [{"id": "startup", "title": "Startup programs", "status": "ok",
             "detail": f"{len(apps)} programs start with Windows. That's reasonable.", "action": None,
             "restart": False}]


def _check_disk(hw):
    sd = hw["storage"].get("system_drive")
    if sd and sd["free_pct"] < 15:
        return [{"id": "disk", "title": "System drive is nearly full", "status": "fix",
                 "detail": f"Only {sd['free_gb']:.0f} GB ({sd['free_pct']:.0f}%) is free. Windows and SSDs "
                           "both slow down when a drive is this full.",
                 "action": {"type": "page", "label": "Free up space", "arg": "Disk space"},
                 "restart": False}]
    return []


def run_checks(hw, recs):
    if not WINDOWS:
        return [{"id": "os", "title": "Free speed-ups need Windows", "status": "unknown",
                 "detail": "These checks look at Windows settings.", "action": None, "restart": False}]
    checks = []
    for fn in (lambda: _check_displays(hw), lambda: _check_xmp(hw, recs), _check_game_mode,
               _check_background_recording, _check_power_plan, lambda: _check_gpu_scheduling(hw),
               _check_resizable_bar, _check_startup, lambda: _check_disk(hw)):
        try:
            checks += fn()
        except Exception as e:  # one broken check shouldn't hide the rest
            checks.append({"id": "error", "title": "A check couldn't run", "status": "unknown",
                           "detail": str(e), "action": None, "restart": False})
    order = {"fix": 0, "tip": 1, "unknown": 2, "ok": 3}
    return sorted(checks, key=lambda c: order[c["status"]])


# =============================================================================
# Applying fixes
# =============================================================================
def apply_fix(check):
    """Run an 'auto' or 'open' action. Returns a short message describing what happened."""
    action = check["action"]
    if action["type"] == "open":
        if action["arg"] == "taskmgr-startup":
            subprocess.Popen(["taskmgr", "/0", "/startup"], stdin=subprocess.DEVNULL)
        else:
            os.startfile(action["arg"])
        return "Opened. Make the change there."
    cid = check["id"]
    if cid.startswith("refresh:"):
        device, hz, _old = action["arg"]
        return f"Switched to {hz} Hz." if set_refresh_rate(device, hz) else \
            "Windows didn't accept that refresh rate. Try it in Settings > Display > Advanced display."
    if cid == "gamemode":
        _reg_set_dword(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\GameBar", "AutoGameModeEnabled", 1)
        return "Game Mode is on."
    if cid == "dvr":
        _reg_set_dword(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\GameDVR",
                       "AppCaptureEnabled", 0)
        _reg_set_dword(winreg.HKEY_CURRENT_USER, r"System\GameConfigStore", "GameDVR_Enabled", 0)
        return "Background recording is off."
    if cid == "power":
        run(["powercfg", "/setactive", "381b4222-f694-41f0-9685-ff5bb260df2e"])
        return "Switched to the Balanced power plan."
    return "Nothing to do."
