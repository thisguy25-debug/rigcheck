"""
Removes the sensor helper (LibreHardwareMonitor) that RigCheck 1.8 to 1.10 could set up.

RigCheck no longer uses any third-party programs or drivers. LibreHardwareMonitor reads
temperatures through a low-level hardware driver, which Windows Defender flags, so this
removes everything RigCheck added for it: the program, its startup task and its driver service.
"""

import base64
import ctypes
import os
import subprocess
import time

import hw_advisor as hwa

WINDOWS = hwa.SYSTEM == "Windows" and os.name == "nt"
TASK = "RigCheck Sensors"
DRIVER_SERVICES = ("R0LibreHardwareMonitor", "WinRing0_1_2_0", "LibreHardwareMonitor")


def helper_dir():
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return os.path.join(base, "RigCheck", "LibreHardwareMonitor")


def _task_exists():
    try:
        r = subprocess.run(["schtasks", "/Query", "/TN", TASK], capture_output=True,
                           stdin=subprocess.DEVNULL, creationflags=hwa.NO_WINDOW, timeout=10)
        return r.returncode == 0
    except Exception:
        return False


def old_helper_present():
    return WINDOWS and (os.path.isdir(helper_dir()) or _task_exists())


def pawnio_installed():
    """PawnIO is a separate driver LibreHardwareMonitor offers to install. It has its own
    uninstaller, listed in Windows' Installed apps."""
    if not WINDOWS:
        return False
    import winreg
    for root, path in ((winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
                       (winreg.HKEY_LOCAL_MACHINE,
                        r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall")):
        try:
            with winreg.OpenKey(root, path) as k:
                for i in range(winreg.QueryInfoKey(k)[0]):
                    try:
                        with winreg.OpenKey(k, winreg.EnumKey(k, i)) as sub:
                            if "pawnio" in str(winreg.QueryValueEx(sub, "DisplayName")[0]).lower():
                                return True
                    except OSError:
                        continue
        except OSError:
            continue
    return False


def remove_old_helper(wait=25):
    """One Windows permission prompt: stop the helper, delete its startup task and driver
    service, and delete its files. Returns True once it's gone, False if declined or stuck."""
    folder = helper_dir().replace("'", "''")
    services = ",".join(f"'{s}'" for s in DRIVER_SERVICES)
    script = (
        "Stop-Process -Name LibreHardwareMonitor -Force -ErrorAction SilentlyContinue; "
        f"Unregister-ScheduledTask -TaskName '{TASK}' -Confirm:$false -ErrorAction SilentlyContinue; "
        f"foreach ($s in @({services})) {{ sc.exe stop $s | Out-Null; sc.exe delete $s | Out-Null }}; "
        "Start-Sleep -Seconds 1; "
        f"Remove-Item -LiteralPath '{folder}' -Recurse -Force -ErrorAction SilentlyContinue"
    )
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    rc = ctypes.windll.shell32.ShellExecuteW(None, "runas", "powershell.exe",
                                             f"-NoProfile -WindowStyle Hidden -EncodedCommand {encoded}",
                                             None, 0)
    if rc <= 32:
        return False
    end = time.time() + wait
    while time.time() < end:
        if not os.path.isdir(helper_dir()) and not _task_exists():
            return True
        time.sleep(1)
    return False
