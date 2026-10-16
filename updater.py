"""
In-app updating for the RigCheck .exe: download the new version from the GitHub release,
check it, swap it in, and restart.

Windows won't let a running program be overwritten, but it does let it be renamed. So the
running RigCheck.exe is renamed to RigCheck.exe.old, the new file takes its place, the new
version starts, and the old file is deleted the next time RigCheck opens.
"""

import hashlib
import os
import shutil
import subprocess
import sys
import tempfile

import app_info
import hw_advisor as hwa


def can_self_update():
    """Only the packaged .exe can replace itself (a script copy is several .py files)."""
    return getattr(sys, "frozen", False) and hwa.SYSTEM == "Windows"


def clean_environment():
    """Environment for launching a fresh copy of a packaged app, without the running copy's
    internal settings (they would make the new copy try to reuse this one's temp files)."""
    env = {k: v for k, v in os.environ.items()
           if not k.startswith("_PYI_") and k not in ("_MEIPASS2", "_MEIPASS")}
    env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    return env


def launch(args=()):
    """Start a new copy of RigCheck, separate from this one."""
    if getattr(sys, "frozen", False):
        cmd = [sys.executable, *args]
    else:
        cmd = [sys.executable, os.path.abspath(sys.argv[0]), *args]
    flags = (0x00000008 | 0x00000200) if hwa.SYSTEM == "Windows" else 0  # detached, new group
    subprocess.Popen(cmd, env=clean_environment(), creationflags=flags, close_fds=True,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def refresh_icon(path=None):
    """Tell Windows the file changed so File Explorer and shortcuts show the new icon
    (otherwise Windows keeps showing the icon it cached for the old RigCheck.exe)."""
    if hwa.SYSTEM != "Windows":
        return
    try:
        import ctypes
        SHCNE_UPDATEITEM, SHCNE_ASSOCCHANGED, SHCNF_PATHW, SHCNF_IDLIST = 0x2000, 0x08000000, 0x0005, 0
        p = ctypes.c_wchar_p(path or sys.executable)
        ctypes.windll.shell32.SHChangeNotify(SHCNE_UPDATEITEM, SHCNF_PATHW, p, None)
        ctypes.windll.shell32.SHChangeNotify(SHCNE_ASSOCCHANGED, SHCNF_IDLIST, None, None)
    except Exception:
        pass


def cleanup_old():
    """Delete the previous version left behind by an update (safe to call on every start)."""
    if not getattr(sys, "frozen", False):
        return
    old = sys.executable + ".old"
    if os.path.exists(old):
        refresh_icon()  # first start after an update
    for path in (old, sys.executable + ".download"):
        try:
            if os.path.exists(path):
                os.remove(path)
        except OSError:
            pass  # the old copy may still be closing; next start will get it


def download(update, progress=None, cancel=None):
    """Download the new .exe next to the current one. Returns its path. Raises on any problem."""
    url = update.get("download_url")
    if not url:
        raise RuntimeError("This release doesn't have RigCheck.exe attached.")
    target_dir = os.path.dirname(sys.executable) if can_self_update() else tempfile.gettempdir()
    path = os.path.join(target_dir, "RigCheck.exe.download")
    if not os.access(target_dir, os.W_OK):
        path = os.path.join(tempfile.gettempdir(), "RigCheck.exe.download")

    sha = hashlib.sha256()
    done = 0
    with app_info._open(url, timeout=30, accept="application/octet-stream") as r, open(path, "wb") as f:
        total = int(r.headers.get("Content-Length") or update.get("size") or 0)
        while True:
            if cancel is not None and cancel.is_set():
                raise RuntimeError("Download cancelled.")
            chunk = r.read(256 * 1024)
            if not chunk:
                break
            f.write(chunk)
            sha.update(chunk)
            done += len(chunk)
            if progress:
                progress(done, total)

    # make sure it's really a complete Windows program before using it
    with open(path, "rb") as f:
        if f.read(2) != b"MZ":
            os.remove(path)
            raise RuntimeError("The downloaded file isn't a Windows program. The release may have "
                               "the wrong file attached.")
    expected = update.get("size") or total
    if expected and done != expected:
        os.remove(path)
        raise RuntimeError("The download was incomplete. Please try again.")
    if update.get("sha256") and sha.hexdigest().lower() != update["sha256"].lower():
        os.remove(path)
        raise RuntimeError("The downloaded file didn't match GitHub's checksum, so it wasn't used. "
                           "Please try again.")
    if done < 1_000_000:
        os.remove(path)
        raise RuntimeError("The downloaded file is too small to be RigCheck.")
    return path


def install_and_restart(new_path, on_close):
    """Swap the new .exe in and start it. Puts everything back if something goes wrong."""
    exe = sys.executable
    old = exe + ".old"
    if os.path.exists(old):
        os.remove(old)
    os.replace(exe, old)                 # renaming a running program is allowed
    try:
        shutil.move(new_path, exe)
    except OSError:
        os.replace(old, exe)             # undo, so the user still has a working copy
        raise
    refresh_icon(exe)
    launch(["--updated-from", app_info.APP_VERSION])
    on_close()
