"""
Processor temperature, power and fan speed through LibreHardwareMonitor (LHM).

Windows doesn't give programs these readings on its own; they need a hardware driver.
LibreHardwareMonitor (free, open source) has one. Current LHM versions share their
readings through a small web server on this PC (http://127.0.0.1:8085/data.json), so
RigCheck sets LHM up to run quietly in the system tray with that feed switched on and
reads it from there. Older LHM versions that publish to WMI are still read too.
"""

import json
import os
import re
import shutil
import subprocess
import tempfile
import urllib.request
import zipfile

import hw_advisor as hwa

WINDOWS = hwa.SYSTEM == "Windows" and os.name == "nt"
PORT = 8085
FEED = f"http://127.0.0.1:{PORT}/data.json"
TASK = "RigCheck Sensors"
LHM_REPO = "LibreHardwareMonitor/LibreHardwareMonitor"
CPU_IDS = ("/intelcpu/", "/amdcpu/")


def install_dir():
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return os.path.join(base, "RigCheck", "LibreHardwareMonitor")


def exe_path():
    return os.path.join(install_dir(), "LibreHardwareMonitor.exe")


def is_installed():
    return os.path.exists(exe_path())


# ---------------------------------------------------------------- reading
_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # never route localhost via a proxy


def _num(node):
    raw = node.get("RawValue")
    if isinstance(raw, (int, float)):
        return float(raw)
    m = re.search(r"-?\d+(?:[.,]\d+)?", str(node.get("Value") or ""))
    return float(m.group(0).replace(",", ".")) if m else None


def _walk(node, out):
    if node.get("SensorId"):
        out.append({"id": node["SensorId"], "type": node.get("Type"), "name": node.get("Text") or "",
                     "value": _num(node)})
    for child in node.get("Children") or []:
        _walk(child, out)


def read(timeout=0.6):
    """Current readings as {'cpu_temp', 'cpu_power', 'cpu_fan', 'gpu_temp'}, only those found.
    Returns None if LibreHardwareMonitor's feed isn't reachable."""
    try:
        with _opener.open(FEED, timeout=timeout) as r:
            data = json.load(r)
    except Exception:
        return None
    sensors = []
    _walk(data, sensors)
    return pick(sensors)


def pick(sensors):
    out = {}
    cpu = [s for s in sensors if s["id"].startswith(CPU_IDS) and s["value"] is not None]
    temps = [s for s in cpu if s["type"] == "Temperature"]
    for pref in ("CPU Package", "Core (Tctl/Tdie)", "Core (Tctl)", "Core Max", "Core Average"):
        t = next((s["value"] for s in temps if s["name"] == pref and s["value"] > 0), None)
        if t:
            out["cpu_temp"] = round(t, 1)
            break
    else:
        if temps:
            out["cpu_temp"] = round(max(s["value"] for s in temps), 1)
    power = [s for s in cpu if s["type"] == "Power"]
    p = next((s["value"] for s in power if "package" in s["name"].lower()), None)
    if p is None and power:
        p = max(s["value"] for s in power)
    if p is not None:
        out["cpu_power"] = round(p, 1)
    fans = [s for s in sensors if s["type"] == "Fan" and s["value"] and not s["id"].startswith("/gpu")]
    if fans:
        named = next((s for s in fans if "cpu" in s["name"].lower()), None)
        out["cpu_fan"] = round((named or fans[0])["value"])
    gpu = [s for s in sensors if s["id"].startswith(("/gpu-amd/", "/gpu-intel/", "/gpu-nvidia/"))
           and s["type"] == "Temperature" and s["value"]]
    if gpu:
        core = next((s for s in gpu if "core" in s["name"].lower()), gpu[0])
        out["gpu_temp"] = round(core["value"], 1)
    return out


# ---------------------------------------------------------------- setup
SETTINGS = {
    # start hidden in the system tray and stay there when closed
    "startMinMenuItem": "true", "minTrayMenuItem": "true", "minCloseMenuItem": "true",
    # share readings with RigCheck through the local web feed, on this PC only
    "runWebServerMenuItem": "true", "listenerIp": "127.0.0.1", "listenerPort": str(PORT),
    "authenticationEnabled": "false",
}


def write_config():
    """LHM keeps its settings in LibreHardwareMonitor.config next to the program."""
    path = os.path.join(install_dir(), "LibreHardwareMonitor.config")
    existing = {}
    try:
        import xml.etree.ElementTree as ET
        for add in ET.parse(path).getroot().iter("add"):
            existing[add.get("key")] = add.get("value")
    except Exception:
        pass
    existing.update(SETTINGS)
    from xml.sax.saxutils import quoteattr
    lines = ['<?xml version="1.0" encoding="utf-8"?>', "<configuration>", "  <appSettings>"]
    lines += [f"    <add key={quoteattr(k)} value={quoteattr(str(v))} />" for k, v in existing.items()]
    lines += ["  </appSettings>", "</configuration>", ""]
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def _latest_zip(timeout=10):
    import app_info
    with app_info._open(f"https://api.github.com/repos/{LHM_REPO}/releases/latest", timeout) as r:
        data = json.load(r)
    zips = [a for a in data.get("assets", []) if a.get("name", "").lower().endswith(".zip")]
    # .NET Framework 4.7.2 is built into Windows 10 and 11, so that build needs nothing extra
    zips.sort(key=lambda a: (0 if "net472" in a["name"].lower() else 1, a["name"]))
    if not zips:
        raise RuntimeError("LibreHardwareMonitor's latest release has no download attached.")
    return data.get("tag_name", ""), zips[0]["browser_download_url"]


def download(progress=None):
    """Download and unpack LibreHardwareMonitor into RigCheck's own folder."""
    import app_info
    tag, url = _latest_zip()
    tmp = os.path.join(tempfile.gettempdir(), "rigcheck_lhm.zip")
    with app_info._open(url, timeout=30, accept="application/octet-stream") as r, open(tmp, "wb") as f:
        total, done = int(r.headers.get("Content-Length") or 0), 0
        while True:
            chunk = r.read(256 * 1024)
            if not chunk:
                break
            f.write(chunk)
            done += len(chunk)
            if progress and total:
                progress(f"Downloading LibreHardwareMonitor {tag}… {done / total:.0%}")
    if progress:
        progress("Unpacking…")
    target = install_dir()
    stop()
    os.makedirs(target, exist_ok=True)
    with zipfile.ZipFile(tmp) as z:
        names = z.namelist()
        # some releases put everything inside one folder; flatten it
        prefix = os.path.commonprefix(names) if len(names) > 1 else ""
        prefix = prefix[:prefix.rfind("/") + 1] if "/" in prefix else ""
        for n in names:
            rel = n[len(prefix):]
            if not rel or rel.endswith("/") or ".." in rel.replace("\\", "/").split("/"):
                continue
            dest = os.path.join(target, rel)
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with z.open(n) as src, open(dest, "wb") as out:
                shutil.copyfileobj(src, out)
    os.remove(tmp)
    if not is_installed():
        raise RuntimeError("The download didn't contain LibreHardwareMonitor.exe.")
    write_config()
    return tag


def register_and_start():
    """One Windows permission prompt: add a startup task (so LHM runs with Windows without
    asking again) and start it now. Returns False if the prompt was declined."""
    import ctypes
    exe = exe_path().replace("'", "''")
    script = (f"$a = New-ScheduledTaskAction -Execute '{exe}'; "
              "$t = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME; "
              "$p = New-ScheduledTaskPrincipal -UserId $env:USERNAME -RunLevel Highest -LogonType Interactive; "
              "$s = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries "
              "-ExecutionTimeLimit 0; "
              f"Register-ScheduledTask -TaskName '{TASK}' -Action $a -Trigger $t -Principal $p "
              "-Settings $s -Force | Out-Null; "
              f"Start-ScheduledTask -TaskName '{TASK}'")
    rc = ctypes.windll.shell32.ShellExecuteW(None, "runas", "powershell.exe",
                                             f'-NoProfile -WindowStyle Hidden -Command "{script}"', None, 0)
    return rc > 32


def ensure_running():
    """Start LHM through its startup task if it's installed but not running (no prompt needed)."""
    if not WINDOWS or not is_installed() or read(timeout=0.3) is not None:
        return
    subprocess.run(["schtasks", "/Run", "/TN", TASK], capture_output=True, stdin=subprocess.DEVNULL,
                   creationflags=hwa.NO_WINDOW, timeout=10)


def stop():
    if WINDOWS:
        subprocess.run(["taskkill", "/im", "LibreHardwareMonitor.exe", "/f"], capture_output=True,
                       stdin=subprocess.DEVNULL, creationflags=hwa.NO_WINDOW, timeout=10)


def remove():
    """Turn the sensors off: remove the startup task, close LHM, and delete its files."""
    import ctypes
    ctypes.windll.shell32.ShellExecuteW(None, "runas", "schtasks.exe", f'/Delete /TN "{TASK}" /F', None, 0)
    stop()
    shutil.rmtree(install_dir(), ignore_errors=True)
