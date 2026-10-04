"""
Saves RigCheck settings and scan history as JSON files.

Windows: %APPDATA%\\RigCheck\\
Others:  ~/.rigcheck/
Settings from the old "Hardware Advisor" folder are copied over automatically.
"""

import json
import os
import shutil
import time

MAX_HISTORY = 50


def data_dir():
    base = os.environ.get("APPDATA")
    path = os.path.join(base, "RigCheck") if base else os.path.expanduser("~/.rigcheck")
    old = os.path.join(base, "HardwareAdvisor") if base else os.path.expanduser("~/.hw_advisor")
    if not os.path.isdir(path):
        os.makedirs(path, exist_ok=True)
        if os.path.isdir(old):  # one-time move from the app's old name
            for name in ("settings.json", "history.json"):
                src = os.path.join(old, name)
                if os.path.exists(src):
                    shutil.copy2(src, os.path.join(path, name))
    return path


def _load(name, default):
    try:
        with open(os.path.join(data_dir(), name), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return default


def _save(name, data):
    path = os.path.join(data_dir(), name)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)  # atomic, so a crash never leaves a half-written file


# ---------------------------------------------------------------- settings
DEFAULT_SETTINGS = {
    "profile": "gaming",
    "psu_watts": None,          # your power supply's wattage
    "psu_8pin": None,           # number of PCIe 8-pin (6+2) GPU power cables
    "psu_16pin": False,         # has a native 12V-2x6 / 12VHPWR cable
    "gpu_max_length_mm": None,  # free space in the case for a graphics card
    "budget": 800,
    "price_overrides": {},      # {"part name": price}
    "monitor_interval": 1.0,
}


def load_settings():
    s = dict(DEFAULT_SETTINGS)
    s.update(_load("settings.json", {}))
    return s


def save_settings(settings):
    _save("settings.json", settings)


# ---------------------------------------------------------------- history
def load_history():
    return _load("history.json", [])


def add_history(kind, data):
    """kind: 'scan', 'benchmark' or 'monitor'."""
    history = load_history()
    history.append({"time": time.time(), "kind": kind, "data": data})
    _save("history.json", history[-MAX_HISTORY:])


def delete_history(indices):
    history = load_history()
    keep = [h for i, h in enumerate(history) if i not in set(indices)]
    _save("history.json", keep)
