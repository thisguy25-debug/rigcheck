"""
Live PC monitoring: CPU, GPU, memory, network, storage and top programs, once a second.

Windows: one long-running PowerShell process reads Windows performance counters (and
LibreHardwareMonitor's sensors when it's running, for CPU temperature, power and fans).
nvidia-smi streams NVIDIA graphics card details. psutil, when installed, lists the
programs using the most CPU and memory. Other systems use psutil for everything.
"""

import json
import os
import shutil
import socket
import subprocess
import threading
import time

import hw_advisor as hwa
import hw_tools
from hw_advisor import SYSTEM, NO_WINDOW, psutil, powershell_json

WINDOWS = SYSTEM == "Windows" and os.name == "nt"

_PS_LOOP = r"""
$ErrorActionPreference = 'SilentlyContinue'
$counters = @('\Processor(*)\% Processor Time',
              '\Processor Information(_Total)\% Processor Performance',
              '\GPU Engine(*engtype_3D)\Utilization Percentage',
              '\GPU Adapter Memory(*)\Dedicated Usage',
              '\Network Interface(*)\Bytes Received/sec',
              '\Network Interface(*)\Bytes Sent/sec',
              '\PhysicalDisk(_Total)\Disk Read Bytes/sec',
              '\PhysicalDisk(_Total)\Disk Write Bytes/sec',
              '\PhysicalDisk(_Total)\% Idle Time')
$i = 0; $sensors = @()
while ($true) {
  $r = Get-Counter -Counter $counters -SampleInterval __IV__ -MaxSamples 1
  $o = @{cores=@(); total=0; perf=0; gpu=0; vram=0; rx=0; tx=0; dr=0; dw=0; idle=100}
  foreach ($s in $r.CounterSamples) {
    $p = $s.Path; $v = $s.CookedValue
    if ($p -like '*\processor(_total)\% processor time') { $o.total = $v }
    elseif ($p -like '*\processor(*)\% processor time') { $o.cores += [math]::Round($v, 1) }
    elseif ($p -like '*% processor performance') { $o.perf = $v }
    elseif ($p -like '*\gpu engine(*') { $o.gpu += $v }
    elseif ($p -like '*\gpu adapter memory(*') { if ($v -gt $o.vram) { $o.vram = $v } }
    elseif ($p -like '*bytes received/sec') { if ($p -notmatch 'loopback|isatap|teredo|vethernet') { $o.rx += $v } }
    elseif ($p -like '*bytes sent/sec') { if ($p -notmatch 'loopback|isatap|teredo|vethernet') { $o.tx += $v } }
    elseif ($p -like '*disk read bytes/sec') { $o.dr = $v }
    elseif ($p -like '*disk write bytes/sec') { $o.dw = $v }
    elseif ($p -like '*% idle time') { $o.idle = $v }
  }
  if ($i % 3 -eq 0) {
    $sensors = @(Get-CimInstance -Namespace root/LibreHardwareMonitor -ClassName Sensor |
      Where-Object { $_.SensorType -in @('Temperature','Fan','Power') } |
      ForEach-Object { @{n=$_.Name; t=$_.SensorType; v=$_.Value; p=$_.Parent} })
  }
  $o.sensors = $sensors; $i++
  [Console]::Out.WriteLine(($o | ConvertTo-Json -Compress -Depth 4))
  [Console]::Out.Flush()
}
"""


def static_info(hw):
    """Details that don't change while monitoring."""
    info = {"cpu_name": hw["cpu"]["name"], "base_mhz": None, "cores": hw["cpu"].get("threads"),
            "ram_total": hw["ram"].get("total_gb"), "ram_type": hw["ram"].get("type"),
            "ram_mhz": hw["ram"].get("configured_mhz"), "adapter": None, "ip": None, "link": None}
    dedicated = [g for g in hw["gpu"] if not g["integrated"]] or hw["gpu"]
    info["gpu_name"] = dedicated[0]["name"] if dedicated else None
    info["gpu_vram_total"] = dedicated[0].get("vram_gb") if dedicated else None
    if WINDOWS:
        p = powershell_json("Get-CimInstance Win32_Processor | Select MaxClockSpeed")
        if p:
            info["base_mhz"] = p[0].get("MaxClockSpeed")
        n = powershell_json(
            "Get-NetIPConfiguration | Where-Object {$_.IPv4DefaultGateway} | Select-Object -First 1 "
            "@{n='Alias';e={$_.InterfaceAlias}}, @{n='IP';e={$_.IPv4Address.IPAddress}}, "
            "@{n='Speed';e={$_.NetAdapter.LinkSpeed}}")
        if n:
            info["adapter"], info["ip"], info["link"] = n[0].get("Alias"), n[0].get("IP"), n[0].get("Speed")
            if isinstance(info["ip"], list):
                info["ip"] = info["ip"][0]
    if not info["ip"]:
        try:  # finds the address used for internet traffic without sending anything
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("1.1.1.1", 80))
            info["ip"] = s.getsockname()[0]
            s.close()
        except OSError:
            pass
    info["drives"] = hw_tools.fixed_drives()
    return info


def _pick_sensors(sensors):
    """CPU temperature, power and fan speed (plus a non-NVIDIA GPU temp) from LibreHardwareMonitor."""
    out = {}
    if not sensors:
        return out
    if isinstance(sensors, dict):
        sensors = [sensors]
    cpu = [s for s in sensors if "cpu" in str(s.get("p", "")).lower()]
    for pref in ("CPU Package", "Core (Tctl/Tdie)", "Core Max", "Core Average"):
        t = next((s["v"] for s in cpu if s.get("t") == "Temperature" and s.get("n") == pref and s.get("v")), None)
        if t:
            out["cpu_temp"] = round(t, 1)
            break
    p = next((s["v"] for s in cpu if s.get("t") == "Power" and "package" in str(s.get("n", "")).lower()), None)
    if p:
        out["cpu_power"] = round(p, 1)
    fans = [s for s in sensors if s.get("t") == "Fan" and s.get("v")]
    if fans:
        named = next((s for s in fans if "cpu" in str(s.get("n", "")).lower()), fans[0])
        out["cpu_fan"] = round(named["v"])
    gpu = [s for s in sensors if "gpu" in str(s.get("p", "")).lower() and s.get("t") == "Temperature"]
    if gpu:
        core = next((s for s in gpu if "core" in str(s.get("n", "")).lower()), gpu[0])
        out["gpu_temp"] = round(core["v"], 1)
    return out


class LiveMonitor:
    """Calls on_sample(dict) about once a second until stopped."""

    def __init__(self, info, on_sample, interval=1):
        self.interval = max(1, int(interval))
        self.info = info
        self.on_sample = on_sample
        self._stop = threading.Event()
        self._procs = []
        self._nv = {}
        self._extra = {"procs": [], "ping": None, "drives": []}
        self.note = None

    # ---------- lifecycle ----------
    def start(self):
        self._stop.clear()
        if shutil.which("nvidia-smi"):
            nv = subprocess.Popen(
                ["nvidia-smi", "--query-gpu=utilization.gpu,temperature.gpu,clocks.gr,fan.speed,power.draw,"
                 "memory.used,memory.total", "--format=csv,noheader,nounits", "-l", str(self.interval)],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL, text=True,
                creationflags=NO_WINDOW)
            self._procs.append(nv)
            threading.Thread(target=self._read_nvidia, args=(nv,), daemon=True).start()
        threading.Thread(target=self._slow_loop, daemon=True).start()
        if WINDOWS:
            script = _PS_LOOP.replace("__IV__", str(self.interval))
            ps = subprocess.Popen(["powershell", "-NoProfile", "-Command", script], stdout=subprocess.PIPE,
                                  stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL, text=True,
                                  creationflags=NO_WINDOW)
            self._procs.append(ps)
            threading.Thread(target=self._read_windows, args=(ps,), daemon=True).start()
        elif psutil:
            threading.Thread(target=self._read_psutil, daemon=True).start()
        else:
            self.note = "Install psutil (pip install psutil) to see live readings on this system."

    def stop(self):
        self._stop.set()
        for p in self._procs:
            try:
                p.terminate()
            except Exception:
                pass
        self._procs = []

    # ---------- sources ----------
    def _read_nvidia(self, proc):
        for line in proc.stdout:
            if self._stop.is_set():
                break
            f = [x.strip() for x in line.split(",")]
            if len(f) < 7:
                continue

            def num(x):
                try:
                    return float(x)
                except ValueError:
                    return None
            self._nv = {"gpu_load": num(f[0]), "gpu_temp": num(f[1]), "gpu_clock": num(f[2]),
                        "gpu_fan": num(f[3]), "gpu_power": num(f[4]), "vram_used": num(f[5]),
                        "vram_total": num(f[6])}

    def _slow_loop(self):
        """Top programs every 2 s, latency and drive space every 5 s."""
        tick = 0
        if psutil:
            for p in psutil.process_iter():
                try:
                    p.cpu_percent(None)
                except Exception:
                    pass
        while not self._stop.wait(2):
            if psutil:
                self._extra["procs"] = self._top_programs()
            if tick % 3 == 0:
                self._extra["ping"] = self._latency()
                drives = []
                for d in self.info.get("drives") or []:
                    try:
                        u = shutil.disk_usage(d)
                        drives.append({"drive": d, "used": u.used, "total": u.total,
                                       "pct": u.used / u.total * 100 if u.total else 0})
                    except OSError:
                        pass
                self._extra["drives"] = drives
            tick += 1

    @staticmethod
    def _top_programs(limit=8):
        ncpu = psutil.cpu_count() or 1
        groups = {}
        for p in psutil.process_iter(["name", "memory_info"]):
            try:
                name = (p.info["name"] or "?").replace(".exe", "")
                if name in ("System Idle Process", "Idle"):
                    continue
                cpu = p.cpu_percent(None) / ncpu
                mem = p.info["memory_info"].rss if p.info["memory_info"] else 0
            except Exception:
                continue
            g = groups.setdefault(name, [0.0, 0])
            g[0] += cpu
            g[1] += mem
        rows = sorted(groups.items(), key=lambda kv: (kv[1][0], kv[1][1]), reverse=True)
        return [(n, round(c, 1), m) for n, (c, m) in rows[:limit]]

    @staticmethod
    def _latency():
        """Round trip to a nearby Cloudflare server, in ms (a TCP connect; no admin rights needed)."""
        try:
            t = time.perf_counter()
            with socket.create_connection(("1.1.1.1", 443), timeout=2):
                pass
            return round((time.perf_counter() - t) * 1000)
        except OSError:
            return None

    def _emit(self, s):
        s.update(self._nv)
        s.update({k: v for k, v in self._extra.items()})
        s["t"] = time.time()
        self.on_sample(s)

    def _read_windows(self, proc):
        base = self.info.get("base_mhz")
        for line in proc.stdout:
            if self._stop.is_set():
                break
            try:
                o = json.loads(line)
            except json.JSONDecodeError:
                continue
            cores = o.get("cores") or []
            if not isinstance(cores, list):
                cores = [cores]
            s = {"cpu_load": o.get("total"), "cpu_cores": cores,
                 "cpu_clock": base * o["perf"] / 100 if base and o.get("perf") else None,
                 "gpu_load": min(o.get("gpu") or 0, 100),
                 "vram_used": (o.get("vram") or 0) / 1024 ** 2 or None,
                 "net_down": o.get("rx"), "net_up": o.get("tx"),
                 "disk_read": o.get("dr"), "disk_write": o.get("dw"),
                 "disk_active": max(0, 100 - (o.get("idle") or 100)),
                 "ram_load": hw_tools._ram_percent()}
            s.update(_pick_sensors(o.get("sensors")))
            total = self.info.get("ram_total")
            if total and s["ram_load"] is not None:
                s["ram_used"] = total * s["ram_load"] / 100
            self._emit(s)

    def _read_psutil(self):
        psutil.cpu_percent(percpu=True)
        net0, disk0, t0 = psutil.net_io_counters(), psutil.disk_io_counters(), time.time()
        while not self._stop.wait(self.interval):
            t = time.time()
            dt = max(t - t0, 0.001)
            cores = psutil.cpu_percent(percpu=True)
            net, disk = psutil.net_io_counters(), psutil.disk_io_counters()
            vm = psutil.virtual_memory()
            s = {"cpu_load": sum(cores) / len(cores), "cpu_cores": cores,
                 "cpu_clock": (psutil.cpu_freq().current if psutil.cpu_freq() else None),
                 "ram_load": vm.percent, "ram_used": vm.used / 1024 ** 3,
                 "net_down": (net.bytes_recv - net0.bytes_recv) / dt, "net_up": (net.bytes_sent - net0.bytes_sent) / dt}
            if disk and disk0:
                s["disk_read"] = (disk.read_bytes - disk0.read_bytes) / dt
                s["disk_write"] = (disk.write_bytes - disk0.write_bytes) / dt
                busy = getattr(disk, "busy_time", None)
                if busy is not None and getattr(disk0, "busy_time", None) is not None:
                    s["disk_active"] = min(100, (busy - disk0.busy_time) / (dt * 10))
            temp, _src = hw_tools.cpu_temperature()
            if temp is not None:
                s["cpu_temp"] = temp
            net0, disk0, t0 = net, disk, t
            self._emit(s)


def rate(bps):
    """Bytes per second -> short readable rate."""
    if bps is None:
        return "–"
    bits = bps * 8
    for unit, size in (("Gbps", 1e9), ("Mbps", 1e6), ("Kbps", 1e3)):
        if bits >= size:
            return f"{bits / size:.1f} {unit}" if bits / size < 100 else f"{bits / size:.0f} {unit}"
    return f"{bits:.0f} bps"


def bytes_rate(bps):
    if bps is None:
        return "–"
    for unit, size in (("GB/s", 1024 ** 3), ("MB/s", 1024 ** 2), ("KB/s", 1024)):
        if bps >= size:
            return f"{bps / size:.1f} {unit}"
    return f"{bps:.0f} B/s"
