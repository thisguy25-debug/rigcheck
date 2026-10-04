"""RigCheck version and update checking.

To turn on update notifications, publish RigCheck on GitHub (see README.md) and put
your repository name below, for example UPDATE_REPO = "yourname/rigcheck".
Each new version is a GitHub Release with a tag like v1.4.0 and RigCheck.exe attached.
"""

import json
import re
import urllib.request

APP_VERSION = "1.5.0"
UPDATE_REPO = "thisguy25-debug/rigcheck"


def _vt(v):
    return tuple(int(x) for x in re.findall(r"\d+", v or "0")) or (0,)


def check_for_update(timeout=6):
    """Returns {'version', 'url', 'notes'} if a newer release exists, None if up to date or not set up.
    Raises on network errors so the caller can say so."""
    if not UPDATE_REPO:
        return None
    req = urllib.request.Request(f"https://api.github.com/repos/{UPDATE_REPO}/releases/latest",
                                 headers={"User-Agent": f"RigCheck/{APP_VERSION}",
                                          "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = json.load(r)
    latest = data.get("tag_name", "")
    if _vt(latest) > _vt(APP_VERSION):
        return {"version": latest.lstrip("vV"), "url": data.get("html_url"),
                "notes": (data.get("body") or "").strip()[:600]}
    return None
