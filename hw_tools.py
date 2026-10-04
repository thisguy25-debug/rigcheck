"""
RigCheck tools: disk space analysis, cleanup, drive health, temperatures,
bottleneck monitoring, quick benchmarks and update checks.

Most features are Windows-first (that's where they matter most) with Linux/macOS
fallbacks where practical.
"""

import datetime
import hashlib
import heapq
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time

import hw_advisor as hwa
from hw_advisor import SYSTEM, run, powershell_json, psutil, NO_WINDOW

WINDOWS = SYSTEM == "Windows"


def human(n):
    n = float(n or 0)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit in ("B", "KB") else f"{n:.1f} {unit}"
        n /= 1024


def fixed_drives():
    """Mount points / drive letters of local fixed disks."""
    if WINDOWS:
        import ctypes
        drives = []
        mask = ctypes.windll.kernel32.GetLogicalDrives()
        for i in range(26):
            if mask & (1 << i):
                root = f"{chr(65 + i)}:\\"
                if ctypes.windll.kernel32.GetDriveTypeW(root) == 3:  # DRIVE_FIXED
                    drives.append(root)
        return drives
    if psutil:
        return [p.mountpoint for p in psutil.disk_partitions(all=False)
                if not p.mountpoint.startswith(("/boot", "/snap", "/System/Volumes"))
                or p.mountpoint == "/System/Volumes/Data"]
    return ["/"]


# =============================================================================
# 1. Disk space analyzer
# =============================================================================
class DiskScan:
    """Walks a folder tree once and records the size of every folder."""

    def __init__(self, root):
        self.root = os.path.abspath(root)
        self.sizes = {}        # folder -> total bytes (including subfolders)
        self.children = {}     # folder -> [subfolders]
        self.file_bytes = {}   # folder -> bytes of files directly inside
        self.top_files = []    # min-heap of (size, path), largest 100 files
        self.files_seen = 0
        self.dirs_seen = 0
        self.errors = 0

    def run(self, progress=None, cancel=None):
        self._walk(self.root, progress, cancel, depth=0)
        self.top_files.sort(reverse=True)

    def _walk(self, path, progress, cancel, depth):
        if cancel is not None and cancel.is_set():
            return 0
        total, own, subdirs = 0, 0, []
        try:
            with os.scandir(path) as it:
                entries = list(it)
        except OSError:
            self.errors += 1
            self.sizes[path] = 0
            return 0
        for e in entries:
            try:
                st = e.stat(follow_symlinks=False)
                reparse = getattr(st, "st_file_attributes", 0) & 0x400  # junctions etc.
                if e.is_symlink() or reparse:
                    continue
                if e.is_dir(follow_symlinks=False):
                    if depth < 60:
                        subdirs.append(e.path)
                else:
                    own += st.st_size
                    self.files_seen += 1
                    item = (st.st_size, e.path)
                    if len(self.top_files) < 100:
                        heapq.heappush(self.top_files, item)
                    elif item > self.top_files[0]:
                        heapq.heapreplace(self.top_files, item)
            except OSError:
                self.errors += 1
        self.dirs_seen += 1
        if progress and self.dirs_seen % 200 == 0:
            progress(self.files_seen, path)
        total = own
        for d in subdirs:
            total += self._walk(d, progress, cancel, depth + 1)
        self.sizes[path] = total
        self.children[path] = sorted(subdirs, key=lambda d: self.sizes.get(d, 0), reverse=True)
        self.file_bytes[path] = own
        return total


def _dir_size(path, limit_seconds=20):
    total, start = 0, time.time()
    for dirpath, dirnames, filenames in os.walk(path, onerror=lambda e: None):
        for f in filenames:
            try:
                total += os.lstat(os.path.join(dirpath, f)).st_size
            except OSError:
                pass
        if time.time() - start > limit_seconds:
            break
    return total


def _recycle_bin_size():
    if not WINDOWS:
        return 0
    import ctypes
    from ctypes import wintypes

    class SHQUERYRBINFO(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("i64Size", ctypes.c_longlong),
                    ("i64NumItems", ctypes.c_longlong)]
    info = SHQUERYRBINFO()
    info.cbSize = ctypes.sizeof(info)
    if ctypes.windll.shell32.SHQueryRecycleBinW(None, ctypes.byref(info)) == 0:
        return info.i64Size
    return 0


def _documents():
    try:
        import mods
        return mods.documents_dir()
    except Exception:
        return os.path.join(os.path.expanduser("~"), "Documents")


def cleanup_targets():
    """Known space users. 'safe' ones can be emptied by the app."""
    t = []
    home = os.path.expanduser("~")
    if WINDOWS:
        local = os.environ.get("LOCALAPPDATA", "")
        windir = os.environ.get("WINDIR", r"C:\Windows")
        sysdrive = os.environ.get("SystemDrive", "C:") + "\\"
        t += [
            ("Your temporary files", os.environ.get("TEMP", ""), "safe",
             "Leftovers from installers and apps. Files in use are skipped."),
            ("Windows temporary files", os.path.join(windir, "Temp"), "safe",
             "Needs administrator rights to clear fully."),
            ("NVIDIA shader cache", os.path.join(local, "NVIDIA", "DXCache"), "safe",
             "Games rebuild it automatically. The first launch after clearing may stutter briefly."),
            ("NVIDIA OpenGL cache", os.path.join(local, "NVIDIA", "GLCache"), "safe",
             "Rebuilt automatically."),
            ("AMD shader cache", os.path.join(local, "AMD", "DxCache"), "safe",
             "Rebuilt automatically."),
            ("DirectX shader cache", os.path.join(local, "D3DSCache"), "safe",
             "Rebuilt automatically."),
            ("Crash dumps", os.path.join(local, "CrashDumps"), "safe",
             "Only useful to developers debugging crashes."),
            ("Windows Update downloads", os.path.join(windir, "SoftwareDistribution", "Download"), "safe",
             "Already-installed update files. Needs administrator rights."),
            ("Windows error reports", r"C:\ProgramData\Microsoft\Windows\WER\ReportArchive", "safe",
             "Old crash reports. Needs administrator rights."),
            ("Recycle Bin", "::recycle", "safe", "Permanently deletes what's in the Recycle Bin."),
            ("FiveM cache", os.path.join(local, "FiveM", "FiveM.app", "data", "cache"), "safe",
             "Clearing it fixes many FiveM crashes and slow loading. Close FiveM first."),
            ("FiveM server cache", os.path.join(local, "FiveM", "FiveM.app", "data", "server-cache"), "safe",
             "Downloaded server files (cars, maps). They download again when you join a server."),
            ("FiveM private server cache", os.path.join(local, "FiveM", "FiveM.app", "data",
                                                        "server-cache-priv"), "safe",
             "More downloaded server files. Your GTA game files (game-storage) are left alone."),
            ("FiveM crash dumps", os.path.join(local, "FiveM", "FiveM.app", "crashes"), "safe",
             "Old crash reports."),
            ("Farming Simulator 25 shader cache", os.path.join(_documents(), "My Games",
                                                               "FarmingSimulator2025", "shader_cache"), "safe",
             "Rebuilt the next time you play. Clearing it can fix graphics glitches after driver updates."),
            ("Downloads folder", os.path.join(home, "Downloads"), "review",
             "Often full of old installers. Review it yourself; the app won't delete it."),
            ("Previous Windows installation", os.path.join(sysdrive, "Windows.old"), "tool",
             "Remove with Windows Disk Cleanup > Clean up system files."),
            ("Hibernation file", os.path.join(sysdrive, "hiberfil.sys"), "tool",
             "If you never hibernate, run 'powercfg /h off' as administrator to remove it."),
            ("Virtual memory file", os.path.join(sysdrive, "pagefile.sys"), "info",
             "Managed by Windows; don't delete."),
        ]
    else:
        t += [
            ("App caches", os.path.join(home, ".cache"), "safe", "Rebuilt automatically by apps."),
            ("Downloads folder", os.path.join(home, "Downloads"), "review", "Review it yourself."),
            ("Trash", os.path.join(home, ".local", "share", "Trash"), "safe",
             "Permanently deletes what's in the Trash."),
        ]
    out = []
    for name, path, kind, how in t:
        if path == "::recycle":
            size = _recycle_bin_size()
        elif path and os.path.isfile(path):
            try:
                size = os.path.getsize(path)
            except OSError:
                size = 0
        elif path and os.path.isdir(path):
            size = _dir_size(path)
        else:
            continue
        out.append({"name": name, "path": path, "kind": kind, "how": how, "size": size})
    return sorted(out, key=lambda x: x["size"], reverse=True)


def clean_target(target):
    """Empty a 'safe' target. Returns bytes freed (approximate)."""
    if target["kind"] != "safe":
        return 0
    if target["path"] == "::recycle":
        if WINDOWS:
            import ctypes
            before = _recycle_bin_size()
            ctypes.windll.shell32.SHEmptyRecycleBinW(None, None, 0x7)  # no confirm/progress/sound
            return before - _recycle_bin_size()
        return 0
    before = _dir_size(target["path"])
    for entry in os.scandir(target["path"]):
        try:
            if entry.is_dir(follow_symlinks=False):
                shutil.rmtree(entry.path, ignore_errors=True)
            else:
                os.remove(entry.path)
        except OSError:
            pass  # in use or protected, skip
    return max(0, before - _dir_size(target["path"]))


def open_in_file_manager(path):
    try:
        if WINDOWS:
            if os.path.isfile(path):
                subprocess.Popen(["explorer", "/select,", path], stdin=subprocess.DEVNULL)
            else:
                os.startfile(path)
        elif SYSTEM == "Darwin":
            subprocess.Popen(["open", "-R" if os.path.isfile(path) else "", path])
        else:
            subprocess.Popen(["xdg-open", os.path.dirname(path) if os.path.isfile(path) else path])
    except Exception:
        pass


def open_disk_cleanup():
    if WINDOWS:
        subprocess.Popen(["cleanmgr.exe"], stdin=subprocess.DEVNULL)


# =============================================================================
# 2. Drive health
# =============================================================================
def _smartctl_health():
    if not shutil.which("smartctl"):
        return None
    scan = run(["smartctl", "--scan-open", "-j"], timeout=20)
    try:
        devices = json.loads(scan).get("devices", [])
    except (json.JSONDecodeError, AttributeError):
        return None
    drives = []
    for dev in devices:
        cmd = ["smartctl", "-a", "-j", dev["name"]]
        if dev.get("type"):
            cmd[3:3] = ["-d", dev["type"]]
        try:
            d = json.loads(run(cmd, timeout=30) or "{}")
        except json.JSONDecodeError:
            continue
        if not d.get("model_name"):
            continue
        attrs = {a["id"]: a.get("raw", {}).get("value") for a in
                 d.get("ata_smart_attributes", {}).get("table", [])}
        nv = d.get("nvme_smart_health_information_log", {})
        drives.append({
            "name": d.get("model_name"),
            "type": "SSD" if d.get("rotation_rate", 1) == 0 or nv else "HDD",
            "passed": d.get("smart_status", {}).get("passed"),
            "temp": d.get("temperature", {}).get("current"),
            "hours": d.get("power_on_time", {}).get("hours"),
            "wear": nv.get("percentage_used"),
            "reallocated": attrs.get(5), "pending": attrs.get(197),
            "uncorrectable": attrs.get(198) or nv.get("media_errors"),
            "firmware": d.get("firmware_version"), "source": "smartctl",
        })
    return drives


def _windows_health():
    rows = powershell_json(
        "Get-PhysicalDisk | ForEach-Object { $r = $_ | Get-StorageReliabilityCounter "
        "-ErrorAction SilentlyContinue; [pscustomobject]@{Name=$_.FriendlyName; "
        "Media=[int]$_.MediaType; Health=[string]$_.HealthStatus; Firmware=$_.FirmwareVersion; "
        "Wear=$r.Wear; Temp=$r.Temperature; Hours=$r.PowerOnHours; "
        "ReadErr=$r.ReadErrorsUncorrected; WriteErr=$r.WriteErrorsUncorrected} }")
    predict = powershell_json(
        "Get-CimInstance -Namespace root\\wmi -ClassName MSStorageDriver_FailurePredictStatus "
        "-ErrorAction SilentlyContinue | Select PredictFailure")
    failing = any(p.get("PredictFailure") for p in predict)
    drives = []
    for r in rows:
        health = str(r.get("Health") or "")
        health = {"0": "Healthy", "1": "Warning", "2": "Unhealthy"}.get(health, health)
        errs = (r.get("ReadErr") or 0) + (r.get("WriteErr") or 0)
        drives.append({
            "name": r.get("Name"), "type": {3: "HDD", 4: "SSD"}.get(r.get("Media"), "Drive"),
            "passed": None if health in ("", "Unknown") else health == "Healthy",
            "windows_health": health, "temp": r.get("Temp") or None, "hours": r.get("Hours"),
            "wear": r.get("Wear"), "reallocated": None, "pending": None,
            "uncorrectable": errs if (r.get("ReadErr") is not None) else None,
            "firmware": r.get("Firmware"), "source": "windows",
        })
    return drives, failing


def assess_drive(d):
    """Returns (verdict, reasons). verdict: Good / Caution / Bad / Unknown."""
    bad, caution = [], []
    if d.get("passed") is False:
        bad.append("The drive reports it is failing its own health check")
    wear = d.get("wear")
    if wear is not None:
        if wear >= 90:
            bad.append(f"SSD wear is at {wear}% of its rated life")
        elif wear >= 70:
            caution.append(f"SSD wear is at {wear}% of its rated life")
    if d.get("pending"):
        bad.append(f"{d['pending']} sectors are waiting to be remapped (unstable)")
    if d.get("reallocated"):
        (bad if d["reallocated"] > 100 else caution).append(
            f"{d['reallocated']} bad sectors have been replaced")
    if d.get("uncorrectable"):
        caution.append(f"{d['uncorrectable']} uncorrectable read/write errors logged")
    temp = d.get("temp")
    if temp:
        limit = 50 if d.get("type") == "HDD" else 65
        if temp >= limit:
            caution.append(f"Running hot at {temp}°C")
    hours = d.get("hours")
    if hours and d.get("type") == "HDD" and hours > 35000:
        caution.append(f"{hours:,} powered-on hours (about {hours / 8760:.1f} years); hard drives "
                       "this old fail more often")
    if bad:
        return "Bad", bad
    if caution:
        return "Caution", caution
    if d.get("passed") is None and wear is None and d.get("hours") is None:
        return "Unknown", ["Detailed health data needs administrator rights (or smartmontools)"]
    return "Good", ["No problems reported"]


def drive_health():
    """List of drives with health verdicts."""
    drives = _smartctl_health()
    failing = False
    if not drives:
        if WINDOWS:
            drives, failing = _windows_health()
        elif SYSTEM == "Darwin":
            drives = []
            for disk in re.findall(r"^/dev/(disk\d+)", run(["diskutil", "list"]), re.M):
                info = run(["diskutil", "info", disk])
                status = re.search(r"SMART Status:\s*(.+)", info)
                name = re.search(r"Device / Media Name:\s*(.+)", info)
                if status and "Not Supported" not in status.group(1):
                    drives.append({"name": name.group(1) if name else disk, "type": "SSD",
                                   "passed": "Verified" in status.group(1), "source": "diskutil"})
        else:
            drives = []
    for d in drives:
        d["verdict"], d["reasons"] = assess_drive(d)
        if failing and d["verdict"] != "Bad":
            d["reasons"].append("Windows is predicting a drive failure on this system")
            d["verdict"] = "Caution"
    return drives


# =============================================================================
# 3. Temperatures and live sensors
# =============================================================================
NV_QUERY = ("name,temperature.gpu,utilization.gpu,power.draw,clocks.sm,clocks.max.sm,"
            "fan.speed,memory.used,memory.total")


def nvidia_status():
    out = run(["nvidia-smi", f"--query-gpu={NV_QUERY},clocks_event_reasons.active",
               "--format=csv,noheader,nounits"])
    if not out:  # older drivers use the old field name
        out = run(["nvidia-smi", f"--query-gpu={NV_QUERY},clocks_throttle_reasons.active",
                   "--format=csv,noheader,nounits"])
    gpus = []
    for line in out.splitlines():
        f = [x.strip() for x in line.split(",")]
        if len(f) < 10:
            continue

        def num(x):
            try:
                return float(x)
            except ValueError:
                return None
        try:
            reasons = int(f[9], 16)
        except ValueError:
            reasons = 0
        gpus.append({"name": f[0], "temp": num(f[1]), "util": num(f[2]), "power": num(f[3]),
                     "clock": num(f[4]), "max_clock": num(f[5]), "fan": num(f[6]),
                     "vram_used": num(f[7]), "vram_total": num(f[8]),
                     "thermal_throttle": bool(reasons & 0x60), "power_limited": bool(reasons & 0x4)})
    return gpus


def cpu_temperature():
    """Returns (temp °C or None, source description)."""
    if WINDOWS:
        for ns in ("root/LibreHardwareMonitor", "root/OpenHardwareMonitor"):
            rows = powershell_json(
                f"Get-CimInstance -Namespace {ns} -ClassName Sensor -ErrorAction SilentlyContinue "
                "| Where-Object {$_.SensorType -eq 'Temperature'} | Select Name,Value,Parent")
            cpu = [r for r in rows if "cpu" in str(r.get("Parent", "")).lower()
                   or "amdcpu" in str(r.get("Parent", "")).lower()
                   or "intelcpu" in str(r.get("Parent", "")).lower()]
            for pref in ("CPU Package", "Core (Tctl/Tdie)", "Core Max", "Core Average"):
                for r in cpu:
                    if r.get("Name") == pref and r.get("Value"):
                        return round(r["Value"], 1), ns.split("/")[1]
            if cpu:
                vals = [r["Value"] for r in cpu if r.get("Value")]
                if vals:
                    return round(max(vals), 1), ns.split("/")[1]
        zones = powershell_json("Get-CimInstance -Namespace root/wmi -ClassName "
                                "MSAcpi_ThermalZoneTemperature -ErrorAction SilentlyContinue "
                                "| Select CurrentTemperature")
        vals = [z["CurrentTemperature"] / 10 - 273.15 for z in zones if z.get("CurrentTemperature")]
        if vals:
            return round(max(vals), 1), "ACPI thermal zone (approximate)"
        return None, None
    if psutil and hasattr(psutil, "sensors_temperatures"):
        temps = psutil.sensors_temperatures() or {}
        for key in ("coretemp", "k10temp", "zenpower", "cpu_thermal"):
            if temps.get(key):
                return round(max(t.current for t in temps[key]), 1), key
    return None, None


def sensor_report():
    cpu_t, src = cpu_temperature()
    gpus = nvidia_status()
    findings = []
    if cpu_t is not None:
        if cpu_t >= 95:
            findings.append(("Bad", f"CPU is at {cpu_t}°C, hot enough to throttle. Check the cooler, "
                                    "clean dust out, and consider fresh thermal paste."))
        elif cpu_t >= 85:
            findings.append(("Caution", f"CPU is warm at {cpu_t}°C. Fine under heavy load, "
                                        "but high if the PC is idle."))
        else:
            findings.append(("Good", f"CPU temperature is fine ({cpu_t}°C)."))
    for g in gpus:
        if g["thermal_throttle"]:
            findings.append(("Bad", f"{g['name']} is slowing down because of heat. Clean the fans "
                                    "and check case airflow."))
        elif g["temp"] and g["temp"] >= 85:
            findings.append(("Caution", f"{g['name']} is hot at {g['temp']:.0f}°C."))
        elif g["temp"]:
            findings.append(("Good", f"{g['name']} temperature is fine ({g['temp']:.0f}°C)."))
    return {"cpu_temp": cpu_t, "cpu_source": src, "gpus": gpus, "findings": findings}


# =============================================================================
# 4. Bottleneck monitor
# =============================================================================
_PS_SAMPLER = r"""
$ErrorActionPreference = 'SilentlyContinue'
$inv = [cultureinfo]::InvariantCulture
while ($true) {
  $r = Get-Counter -Counter @('\Processor(*)\% Processor Time',
       '\Processor Information(_Total)\% Processor Performance',
       '\GPU Engine(*engtype_3D)\Utilization Percentage') -MaxSamples 1
  $cores = @(); $total = 0; $perf = 0; $gpu = 0
  foreach ($s in $r.CounterSamples) {
    $p = $s.Path
    if ($p -like '*\processor(_total)\% processor time') { $total = $s.CookedValue }
    elseif ($p -like '*\processor(*)\% processor time') { $cores += $s.CookedValue }
    elseif ($p -like '*% processor performance') { $perf = $s.CookedValue }
    elseif ($p -like '*gpu engine*') { $gpu += $s.CookedValue }
  }
  $max = ($cores | Measure-Object -Maximum).Maximum
  [Console]::Out.WriteLine([string]::Format($inv, '{0:F1},{1:F1},{2:F1},{3:F1}', $total, $max, $perf, $gpu))
  [Console]::Out.Flush()
}
"""


def _ram_percent():
    if psutil:
        return psutil.virtual_memory().percent
    if WINDOWS:
        import ctypes

        class MEMSTAT(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                        ("rest", ctypes.c_ulonglong * 7)]
        m = MEMSTAT()
        m.dwLength = ctypes.sizeof(m)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
        return float(m.dwMemoryLoad)
    return None


class Monitor:
    """Samples CPU/GPU/RAM once a second in the background."""

    def __init__(self, on_sample):
        self.on_sample = on_sample
        self.samples = []
        self._procs = []
        self._stop = threading.Event()
        self._nv = {}
        self.error = None

    def start(self):
        self._stop.clear()
        if shutil.which("nvidia-smi"):
            nv = subprocess.Popen(["nvidia-smi", "--query-gpu=utilization.gpu,memory.used,"
                                   "memory.total,temperature.gpu", "--format=csv,noheader,nounits",
                                   "-l", "1"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                  stdin=subprocess.DEVNULL,
                                  text=True, creationflags=NO_WINDOW)
            self._procs.append(nv)
            threading.Thread(target=self._read_nvidia, args=(nv,), daemon=True).start()
        if WINDOWS:
            ps = subprocess.Popen(["powershell", "-NoProfile", "-Command", _PS_SAMPLER],
                                  stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
                                  stdin=subprocess.DEVNULL,
                                  creationflags=NO_WINDOW)
            self._procs.append(ps)
            threading.Thread(target=self._read_windows, args=(ps,), daemon=True).start()
        elif psutil:
            threading.Thread(target=self._read_psutil, daemon=True).start()
        else:
            self.error = "Install psutil (pip install psutil) to use the monitor on this system."

    def stop(self):
        self._stop.set()
        for p in self._procs:
            try:
                p.terminate()
            except Exception:
                pass
        self._procs = []

    def _read_nvidia(self, proc):
        for line in proc.stdout:
            if self._stop.is_set():
                break
            f = [x.strip() for x in line.split(",")]
            if len(f) >= 4:
                try:
                    self._nv = {"gpu": float(f[0]), "vram_used": float(f[1]),
                                "vram_total": float(f[2]), "gpu_temp": float(f[3])}
                except ValueError:
                    pass

    def _emit(self, cpu, core_max, perf, gpu):
        s = {"t": time.time(), "cpu": cpu, "core_max": core_max, "cpu_perf": perf,
             "gpu": min(gpu, 100) if gpu is not None else None, "ram": _ram_percent()}
        if self._nv:
            s.update(self._nv)  # NVIDIA's own numbers are more accurate
        self.samples.append(s)
        self.on_sample(s)

    def _read_windows(self, proc):
        for line in proc.stdout:
            if self._stop.is_set():
                break
            try:
                total, core_max, perf, gpu = (float(x) for x in line.strip().split(","))
            except ValueError:
                continue
            self._emit(total, core_max, perf, gpu)

    def _read_psutil(self):
        psutil.cpu_percent(percpu=True)
        while not self._stop.wait(1.0):
            cores = psutil.cpu_percent(percpu=True)
            self._emit(sum(cores) / len(cores), max(cores), None, None)


def classify(gpu, cpu, core_max):
    """What limited performance in one reading: 'gpu', 'cpu', 'neither', or None when idle."""
    gpu, cpu, core_max = gpu or 0, cpu or 0, core_max or 0
    if gpu <= 25 and cpu <= 25:
        return None
    if gpu >= 90:
        return "gpu"
    if gpu < 80 and (core_max >= 90 or cpu >= 85):
        return "cpu"
    return "neither"


def breakdown(samples, gpu_key="gpu", cpu_key="cpu", core_key="core_max"):
    """Share of active time each part was the limit, plus graphics power lost to the CPU (0-100)."""
    kinds, lost = [], []
    for s in samples:
        k = classify(s.get(gpu_key), s.get(cpu_key), s.get(core_key))
        if k:
            kinds.append(k)
            lost.append(100 - (s.get(gpu_key) or 0) if k == "cpu" else 0)
    n = len(kinds)
    if not n:
        return None
    return {"gpu": 100 * kinds.count("gpu") / n, "cpu": 100 * kinds.count("cpu") / n,
            "neither": 100 * kinds.count("neither") / n, "lost_gpu": sum(lost) / n, "active": n}


def analyze_session(samples):
    """Decide what limited performance during a recorded session."""
    active = [s for s in samples if (s.get("gpu") or 0) > 25 or (s.get("cpu") or 0) > 25]
    result = {"samples": len(samples), "active": len(active), "verdict": None, "details": [],
              "bottleneck": None}
    if len(active) < 15:
        result["verdict"] = ("Not enough activity recorded. Start the monitor, then play a game "
                             "for at least a few minutes before stopping it.")
        return result

    def avg(key):
        vals = [s[key] for s in active if s.get(key) is not None]
        return sum(vals) / len(vals) if vals else None

    n = len(active)
    has_gpu = any(s.get("gpu") is not None for s in active)
    b = breakdown(active)
    gpu_bound, cpu_bound = b["gpu"] / 100, b["cpu"] / 100
    result["breakdown"] = b
    result.update(avg_cpu=avg("cpu"), avg_core_max=avg("core_max"), avg_gpu=avg("gpu"),
                  avg_ram=avg("ram"), gpu_bound=gpu_bound, cpu_bound=cpu_bound,
                  max_gpu_temp=max((s.get("gpu_temp") or 0) for s in active) or None)

    if not has_gpu:
        result["verdict"] = "GPU usage couldn't be read on this system, so only CPU/RAM are shown."
    elif gpu_bound >= 0.6:
        result["bottleneck"] = "GPU"
        result["verdict"] = (f"Your graphics card was the limit {gpu_bound:.0%} of the time. A faster "
                             "graphics card will raise your frame rate the most.")
    elif cpu_bound >= 0.4:
        result["bottleneck"] = "CPU"
        result["verdict"] = (f"Your processor was the limit {cpu_bound:.0%} of the time, leaving about "
                             f"{b['lost_gpu']:.0f}% of your graphics card's power unused. A faster processor "
                             "helps more than a new graphics card. Lowering CPU-heavy settings (view "
                             "distance, traffic, crowds) also helps.")
    else:
        result["bottleneck"] = "None"
        result["verdict"] = ("Neither the CPU nor the GPU was maxed out. The game is probably held by "
                             "a frame-rate cap, V-Sync, or the game engine itself, so an upgrade "
                             "may not raise your frame rate.")

    if (result["avg_core_max"] or 0) >= 85 and (result["avg_cpu"] or 100) < 60:
        result["details"].append("One CPU core was near 100% while overall CPU use stayed low. "
                                 "This game depends on single-core speed.")
    ram = result["avg_ram"]
    if ram and ram >= 90:
        result["details"].append(f"Memory use averaged {ram:.0f}%. More RAM would help.")
    vram_full = [s for s in active if s.get("vram_total") and s["vram_used"] / s["vram_total"] >= 0.95]
    if len(vram_full) / n >= 0.2:
        result["details"].append("Graphics memory (VRAM) was full much of the time. Lower texture "
                                 "quality, or look for a card with more VRAM.")
    perf = [s["cpu_perf"] for s in active if s.get("cpu_perf") and (s.get("cpu") or 0) > 50]
    if perf and sum(perf) / len(perf) < 80:
        result["details"].append("The CPU ran below its base speed under load, which points to "
                                 "overheating or power limits.")
    if result["max_gpu_temp"] and result["max_gpu_temp"] >= 85:
        result["details"].append(f"GPU reached {result['max_gpu_temp']:.0f}°C. Check fans and airflow.")
    return result


# =============================================================================
# 5. Quick benchmark
# =============================================================================
def _hash_rate(seconds, stop_at=None):
    """SHA-256 throughput in MB/s on one thread (hashlib releases the GIL)."""
    buf = os.urandom(8 * 1024 * 1024)
    done, start = 0, time.perf_counter()
    while time.perf_counter() - start < seconds:
        hashlib.sha256(buf).digest()
        done += len(buf)
    return done / (time.perf_counter() - start) / 1e6


def bench_cpu(progress=None):
    if progress:
        progress("CPU: single-core test…")
    single = _hash_rate(3)
    threads = os.cpu_count() or 1
    results = [0.0] * threads
    if progress:
        progress(f"CPU: all-core test on {threads} threads…")

    def worker(i):
        results[i] = _hash_rate(8)
    ts = [threading.Thread(target=worker, args=(i,)) for i in range(threads)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    multi = sum(results)
    if progress:
        progress("CPU: checking for heat slowdown…")
    single_after = _hash_rate(3)
    return {"single_mbs": round(single), "multi_mbs": round(multi),
            "scaling": round(multi / single, 1) if single else None,
            "single_after_mbs": round(single_after),
            "throttle_drop": round(1 - single_after / single, 3) if single else 0}


def bench_ram(progress=None):
    if progress:
        progress("Memory: copy speed test…")
    size = 256 * 1024 * 1024
    src = bytearray(os.urandom(1024 * 1024)) * 256
    dst = bytearray(size)
    best = 0
    for _ in range(5):
        t = time.perf_counter()
        dst[:] = src
        dt = time.perf_counter() - t
        best = max(best, 2 * size / dt / 1e9)  # read + write
    del src, dst
    return {"copy_gbs": round(best, 1)}


def _uncached_read_windows(path, chunk=8 * 1024 * 1024):
    import ctypes
    from ctypes import wintypes
    k32 = ctypes.windll.kernel32
    k32.CreateFileW.restype = wintypes.HANDLE
    k32.VirtualAlloc.restype = ctypes.c_void_p
    GENERIC_READ, OPEN_EXISTING = 0x80000000, 3
    NO_BUFFERING, SEQUENTIAL = 0x20000000, 0x08000000
    h = k32.CreateFileW(path, GENERIC_READ, 1, None, OPEN_EXISTING, NO_BUFFERING | SEQUENTIAL, None)
    if h in (None, wintypes.HANDLE(-1).value):
        return None
    buf = k32.VirtualAlloc(None, chunk, 0x3000, 0x04)  # aligned buffer, required for no-buffering
    read = wintypes.DWORD()
    total, start = 0, time.perf_counter()
    try:
        while k32.ReadFile(h, ctypes.c_void_p(buf), chunk, ctypes.byref(read), None) and read.value:
            total += read.value
    finally:
        k32.CloseHandle(h)
        k32.VirtualFree(ctypes.c_void_p(buf), 0, 0x8000)
    dt = time.perf_counter() - start
    return total / dt / 1e6 if dt else None


def _uncached_read_posix(path, chunk=8 * 1024 * 1024):
    fd = os.open(path, os.O_RDONLY)
    try:
        if SYSTEM == "Darwin":
            import fcntl
            fcntl.fcntl(fd, 48, 1)  # F_NOCACHE
        elif hasattr(os, "posix_fadvise"):
            os.posix_fadvise(fd, 0, 0, os.POSIX_FADV_DONTNEED)
        total, start = 0, time.perf_counter()
        while True:
            data = os.read(fd, chunk)
            if not data:
                break
            total += len(data)
        dt = time.perf_counter() - start
        return total / dt / 1e6 if dt else None
    finally:
        os.close(fd)


def drive_letter_map():
    """Windows: 'C' -> {'name', 'type', 'bus'} of the physical disk behind it."""
    if not WINDOWS:
        return {}
    parts = powershell_json("Get-Partition | Where-Object DriveLetter | Select DriveLetter,DiskNumber")
    disks = powershell_json("Get-PhysicalDisk | Select DeviceId,FriendlyName,MediaType,BusType")
    by_id = {str(d.get("DeviceId")): d for d in disks}
    out = {}
    for p in parts:
        d = by_id.get(str(p.get("DiskNumber")))
        if d:
            out[str(p.get("DriveLetter"))] = {
                "name": d.get("FriendlyName"),
                "type": {3: "HDD", 4: "SSD"}.get(d.get("MediaType"), "Drive"),
                "bus": {7: "USB", 11: "SATA", 17: "NVMe"}.get(d.get("BusType"), "")}
    return out


EXPECTED_MBS = {"HDD": (80, 280), "SATA": (300, 560), "NVMe": (1500, 7500), "USB": (30, 1000)}


def bench_disk(root, size_mb=1024, progress=None, info=None):
    """Sequential write + uncached read test on the drive holding `root`."""
    free = shutil.disk_usage(root).free
    if free < (size_mb * 3) * 1024 * 1024:
        return {"drive": root, "skipped": "Not enough free space to test safely"}
    folder = tempfile.gettempdir() if os.path.splitdrive(tempfile.gettempdir())[0].upper() == \
        os.path.splitdrive(root)[0].upper() else root
    path = os.path.join(folder, "rigcheck_speedtest.tmp")
    chunk = os.urandom(16 * 1024 * 1024)
    try:
        if progress:
            progress(f"Disk {root}: write test…")
        start = time.perf_counter()
        with open(path, "wb", buffering=0) as f:
            for _ in range(size_mb // 16):
                f.write(chunk)
            os.fsync(f.fileno())
        write = size_mb * 1.048576 / (time.perf_counter() - start)
        if progress:
            progress(f"Disk {root}: read test…")
        read = _uncached_read_windows(path) if WINDOWS else _uncached_read_posix(path)
    except OSError as e:
        return {"drive": root, "skipped": f"Couldn't write a test file ({e.strerror})"}
    finally:
        try:
            os.remove(path)
        except OSError:
            pass
    res = {"drive": root, "write_mbs": round(write), "read_mbs": round(read) if read else None}
    if info:
        res.update(info)
        kind = info["bus"] if info.get("bus") in ("NVMe", "USB") else (
            "HDD" if info.get("type") == "HDD" else "SATA")
        lo, hi = EXPECTED_MBS[kind]
        res["expected"] = f"{lo}-{hi} MB/s"
        best = max(write, read or 0)
        if best < lo * 0.7:
            res["note"] = ("Slower than expected for this kind of drive. A nearly full drive, an old "
                           "SATA cable/port, or a failing drive can cause this.")
    return res


def run_benchmark(progress=None, disks=True):
    results = {"time": time.time(), "cpu": bench_cpu(progress), "ram": bench_ram(progress), "disks": []}
    if disks:
        letters = drive_letter_map()
        for root in fixed_drives():
            info = letters.get(root[0]) if WINDOWS else None
            results["disks"].append(bench_disk(root, progress=progress, info=info))
    return results


def assess_benchmark(res, hw):
    notes = []
    cpu = res["cpu"]
    threads = hw["cpu"].get("threads") or os.cpu_count() or 1
    cores = hw["cpu"].get("cores") or threads
    if cpu.get("throttle_drop", 0) > 0.12:
        notes.append(("Caution", f"Single-core speed dropped {cpu['throttle_drop']:.0%} after the "
                                 "all-core test, a sign the CPU slows down when hot. Check the cooler."))
    if cpu.get("scaling") and cpu["scaling"] < cores * 0.5:
        notes.append(("Caution", f"All-core speed was only {cpu['scaling']}x one core with {cores} "
                                 "cores. Background programs or power limits may be holding it back."))
    ram_mhz = hw["ram"].get("configured_mhz")
    notes.append(("Info", f"Memory copy speed {res['ram']['copy_gbs']} GB/s"
                          + (f" at {ram_mhz} MHz" if ram_mhz else "")
                          + ". Run the benchmark again after changing RAM settings to compare."))
    for d in res["disks"]:
        if d.get("note"):
            notes.append(("Caution", f"{d['drive']} {d['note']}"))
    if not any(n[0] == "Caution" for n in notes):
        notes.insert(0, ("Good", "No performance problems found."))
    return notes


# =============================================================================
# 6. Driver, BIOS and Windows update checks
# =============================================================================
DRIVER_LINKS = {
    "nvidia": ("NVIDIA App", "https://www.nvidia.com/en-us/software/nvidia-app/"),
    "amd": ("AMD Software: Adrenalin", "https://www.amd.com/en/support/download/drivers.html"),
    "intel": ("Intel Driver & Support Assistant",
              "https://www.intel.com/content/www/us/en/support/detect.html"),
}
SSD_TOOLS = {
    "samsung": ("Samsung Magician", "https://semiconductor.samsung.com/consumer-storage/magician/"),
    "wd": ("WD Dashboard", "https://support-en.wd.com/app/products/downloads/softwaredownloads"),
    "sandisk": ("WD/SanDisk Dashboard", "https://support-en.wd.com/app/products/downloads/softwaredownloads"),
    "crucial": ("Crucial Storage Executive", "https://www.crucial.com/support/storage-executive"),
    "kingston": ("Kingston SSD Manager", "https://www.kingston.com/en/support/technical/ssdmanager"),
    "seagate": ("Seagate SeaTools", "https://www.seagate.com/support/downloads/seatools/"),
}


def _age_days(date_str):
    try:
        d = datetime.date.fromisoformat(date_str[:10])
        return (datetime.date.today() - d).days
    except (TypeError, ValueError):
        return None


def check_updates(hw):
    items = []
    board = hw.get("board") or {}

    # Graphics drivers
    if WINDOWS:
        vids = powershell_json("Get-CimInstance Win32_VideoController | Select Name,DriverVersion,"
                               "@{n='Date';e={if($_.DriverDate){$_.DriverDate.ToString('yyyy-MM-dd')}}}")
    else:
        vids = []
    nv_ver = run(["nvidia-smi", "--query-gpu=driver_version", "--format=csv,noheader"]).splitlines()
    for v in vids:
        name = v.get("Name") or ""
        if any(x in name.lower() for x in ("virtual", "remote", "basic")):
            continue
        vendor = next((k for k in DRIVER_LINKS if k in name.lower() or
                       (k == "amd" and "radeon" in name.lower())), None)
        version = nv_ver[0].strip() if vendor == "nvidia" and nv_ver else v.get("DriverVersion")
        age = _age_days(v.get("Date"))
        status = "ok" if age is not None and age < 180 else "update" if age is not None else "unknown"
        detail = (f"Driver {version}, released {v.get('Date')} ({age} days ago)." if age is not None
                  else f"Driver {version}.")
        if status == "update":
            detail += " Graphics drivers older than 6 months often miss game fixes and speedups."
        link = DRIVER_LINKS.get(vendor)
        items.append({"name": f"Graphics driver: {name}", "status": status, "detail": detail,
                      "link": {"label": f"Get the latest from {link[0]}", "url": link[1]} if link else None})
    if not vids and nv_ver:
        items.append({"name": "NVIDIA driver", "status": "unknown", "detail": f"Version {nv_ver[0]}",
                      "link": {"label": "NVIDIA drivers", "url": DRIVER_LINKS["nvidia"][1]}})

    # BIOS
    bios_date = None
    if WINDOWS:
        b = powershell_json("Get-CimInstance Win32_BIOS | Select SMBIOSBIOSVersion,"
                            "@{n='Date';e={$_.ReleaseDate.ToString('yyyy-MM-dd')}}")
        bios_date = b[0].get("Date") if b else None
    elif SYSTEM == "Linux":
        try:
            with open("/sys/class/dmi/id/bios_date") as f:
                m, d, y = f.read().strip().split("/")
                bios_date = f"{y}-{m}-{d}"
        except (OSError, ValueError):
            pass
    if board.get("bios") or bios_date:
        age = _age_days(bios_date)
        status, detail = "ok", f"Version {board.get('bios') or '?'}"
        if bios_date:
            detail += f", released {bios_date}"
        platform, key, _ = hwa.parts_db.identify_cpu(hw["cpu"]["name"])
        gen13 = platform == "LGA1700" and key and key[:2] in ("13", "14")
        if gen13 and bios_date and bios_date < "2024-10-01":
            status = "urgent"
            detail += (". Your 13th/14th gen Intel CPU needs a BIOS from late 2024 or newer with "
                       "Intel's stability fix (microcode 0x12B+) to prevent permanent damage.")
        elif age and age > 365:
            status = "update"
            detail += (f" ({age // 365} year(s) old). Newer BIOS versions add CPU support and "
                       "stability fixes. Only update if a newer one exists for your exact board.")
        name = " ".join(x for x in (board.get("system_model") if board.get("oem") else None,
                                    board.get("board_vendor"), board.get("board_model")) if x)
        items.append({"name": "Motherboard BIOS", "status": status, "detail": detail,
                      "link": {"label": "Find BIOS downloads for your board",
                               "url": hwa.parts_db.web_search_url(f"{name} BIOS download")} if name else None})

    # Windows version
    if WINDOWS:
        build = sys.getwindowsversion().build
        if build < 22000:
            items.append({"name": "Windows 10", "status": "urgent",
                          "detail": "Windows 10 stopped getting regular security updates in October 2025. "
                                    "Upgrade to Windows 11 if your PC supports it, or enroll in Extended "
                                    "Security Updates.",
                          "link": {"label": "Windows 11 upgrade info",
                                   "url": "https://www.microsoft.com/en-us/windows/get-windows-11"}})
        else:
            items.append({"name": f"Windows 11 (build {build})", "status": "ok",
                          "detail": "Use 'Check Windows Update' below to look for pending updates.",
                          "link": None})

    # SSD firmware
    for d in hw["storage"]["drives"]:
        if d["type"] != "SSD":
            continue
        name = (d.get("name") or "").lower()
        tool = next((v for k, v in SSD_TOOLS.items() if k in name), None)
        if tool:
            items.append({"name": f"SSD firmware: {d['name']}", "status": "info",
                          "detail": "Drive makers release firmware fixes. Their tool checks and installs them.",
                          "link": {"label": f"Download {tool[0]}", "url": tool[1]}})
    return items


def windows_update_pending():
    """Slow (up to a minute). Returns list of pending update titles, or None if unavailable."""
    if not WINDOWS:
        return None
    out = run(["powershell", "-NoProfile", "-Command",
               "$s = New-Object -ComObject Microsoft.Update.Session; "
               "$r = $s.CreateUpdateSearcher().Search('IsInstalled=0 and IsHidden=0'); "
               "$r.Updates | ForEach-Object { $_.Title }"], timeout=180)
    return [line.strip() for line in out.splitlines() if line.strip()]


def relaunch_as_admin():
    """Restart the app with administrator rights (Windows). Returns True if started."""
    if not WINDOWS:
        return False
    import ctypes
    if getattr(sys, "frozen", False):
        exe, params = sys.executable, ""
    else:
        exe = sys.executable.replace("python.exe", "pythonw.exe")
        if not os.path.exists(exe):
            exe = sys.executable
        params = f'"{os.path.abspath(sys.argv[0])}"'
    return ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, params, None, 1) > 32
