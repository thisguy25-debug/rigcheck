"""
Part prices for the Budget planner and upgrade suggestions.

RigCheck ships with a prices.json, and each time it opens it downloads the latest
prices.json from the GitHub repository (the same one used for updates). Editing that one
file on GitHub updates prices for everyone, with no new release needed.
"""

import json
import os

import app_info
import hw_store
import parts_db

CACHE = "prices.json"
source = "built in"   # shown on the Budget page


def _bundled():
    try:
        import gui_common
        path = gui_common.resource("prices.json")
    except Exception:
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prices.json")
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _cached():
    try:
        with open(os.path.join(hw_store.data_dir(), CACHE), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def load():
    """Use the newest of the built-in and last-downloaded price lists (instant, no network)."""
    global source
    lists = [(d, name) for d, name in ((_bundled(), "built in"), (_cached(), "GitHub")) if d]
    if not lists:
        return
    data, source = max(lists, key=lambda x: x[0].get("updated", ""))
    parts_db.apply_prices(data)


def refresh(timeout=8):
    """Download prices.json from GitHub. Returns True if newer prices were applied."""
    global source
    if not app_info.UPDATE_REPO:
        return False
    url = f"https://raw.githubusercontent.com/{app_info.UPDATE_REPO}/main/prices.json"
    with app_info._open(url, timeout, accept="application/json") as r:
        data = json.loads(r.read().decode("utf-8"))
    if not isinstance(data, dict) or "updated" not in data:
        raise ValueError("prices.json on GitHub isn't in the expected format")
    current = max((d.get("updated", "") for d in (_bundled(), _cached()) if d), default="")
    path = os.path.join(hw_store.data_dir(), CACHE)
    with open(path + ".tmp", "w", encoding="utf-8") as f:
        json.dump(data, f)
    os.replace(path + ".tmp", path)
    if data["updated"] >= current:
        parts_db.apply_prices(data)
        source = "GitHub"
        return True
    return False
