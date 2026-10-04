#!/usr/bin/env python3
"""
RigCheck - detects your computer's hardware and recommends upgrades.

Works on Windows, macOS and Linux. Uses only the standard library, but will
use `psutil` for better accuracy if installed (pip install psutil).

Usage:
    python hw_advisor.py                    # general-use recommendations
    python hw_advisor.py --profile gaming   # gaming | creative | dev | general
    python hw_advisor.py --json             # machine-readable output
"""

import argparse
import json
import os
import platform
import re
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import parts_db  # noqa: E402  (lives next to this file)

try:
    import psutil  # optional
except ImportError:
    psutil = None

SYSTEM = platform.system()  # 'Windows', 'Darwin', 'Linux'


# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------
NO_WINDOW = 0x08000000 if SYSTEM == "Windows" else 0  # CREATE_NO_WINDOW


def run(cmd, timeout=15):
    """Run a command and return stdout, or '' on any failure."""
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, creationflags=NO_WINDOW,
                             stdin=subprocess.DEVNULL,
                             timeout=timeout, shell=isinstance(cmd, str),
                             encoding="utf-8", errors="replace")
        return out.stdout.strip()
    except Exception:
        return ""


def powershell_json(query):
    """Run a PowerShell CIM query and return parsed JSON as a list of dicts."""
    raw = run(["powershell", "-NoProfile", "-Command",
               f"{query} | ConvertTo-Json -Compress"])
    if not raw:
        return []
    try:
        data = json.loads(raw)
        return data if isinstance(data, list) else [data]
    except json.JSONDecodeError:
        return []


def is_admin():
    try:
        if SYSTEM == "Windows":
            import ctypes
            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        return os.geteuid() == 0
    except Exception:
        return False


def gb(n_bytes):
    return round(n_bytes / (1024 ** 3), 1)


# ----------------------------------------------------------------------------
# Detection
# ----------------------------------------------------------------------------
def detect_cpu():
    info = {"name": platform.processor() or "Unknown",
            "cores": None, "threads": os.cpu_count(), "max_ghz": None}

    if SYSTEM == "Windows":
        rows = powershell_json("Get-CimInstance Win32_Processor | "
                               "Select Name,NumberOfCores,NumberOfLogicalProcessors,MaxClockSpeed")
        if rows:
            r = rows[0]
            info["name"] = (r.get("Name") or info["name"]).strip()
            info["cores"] = sum(x.get("NumberOfCores") or 0 for x in rows) or None
            info["threads"] = sum(x.get("NumberOfLogicalProcessors") or 0 for x in rows) or info["threads"]
            if r.get("MaxClockSpeed"):
                info["max_ghz"] = round(r["MaxClockSpeed"] / 1000, 2)
    elif SYSTEM == "Darwin":
        info["name"] = run(["sysctl", "-n", "machdep.cpu.brand_string"]) or info["name"]
        cores = run(["sysctl", "-n", "hw.physicalcpu"])
        info["cores"] = int(cores) if cores.isdigit() else None
    elif SYSTEM == "Linux":
        try:
            with open("/proc/cpuinfo") as f:
                text = f.read()
            m = re.search(r"model name\s*:\s*(.+)", text)
            if m:
                info["name"] = m.group(1).strip()
            ids = set(re.findall(r"physical id\s*:\s*(\d+)\n(?:.*\n)*?core id\s*:\s*(\d+)", text))
            if ids:
                info["cores"] = len(ids)
        except OSError:
            pass

    if psutil:
        info["cores"] = info["cores"] or psutil.cpu_count(logical=False)
        try:
            f = psutil.cpu_freq()
            if f and f.max and not info["max_ghz"]:
                info["max_ghz"] = round(f.max / 1000, 2)
        except Exception:
            pass
    return info


MEMORY_TYPES = {20: "DDR", 21: "DDR2", 24: "DDR3", 26: "DDR4", 34: "DDR5", 35: "LPDDR5"}
FORM_FACTORS = {8: "DIMM", 12: "SODIMM"}


def detect_ram():
    info = {"total_gb": None, "speed_mhz": None, "configured_mhz": None,
            "rated_mhz": None, "type": None, "form": None, "modules": [],
            "part_numbers": [], "slots_total": None}

    if psutil:
        info["total_gb"] = gb(psutil.virtual_memory().total)

    if SYSTEM == "Windows":
        mods = powershell_json("Get-CimInstance Win32_PhysicalMemory | Select Capacity,Speed,"
                               "ConfiguredClockSpeed,SMBIOSMemoryType,FormFactor,PartNumber,Manufacturer")
        info["modules"] = [gb(int(m.get("Capacity") or 0)) for m in mods]
        info["part_numbers"] = [str(m.get("PartNumber") or "").strip() for m in mods]
        speeds = [m.get("Speed") for m in mods if m.get("Speed")]
        conf = [m.get("ConfiguredClockSpeed") for m in mods if m.get("ConfiguredClockSpeed")]
        info["speed_mhz"] = min(speeds) if speeds else None
        info["configured_mhz"] = min(conf) if conf else info["speed_mhz"]
        if mods:
            info["type"] = MEMORY_TYPES.get(mods[0].get("SMBIOSMemoryType"))
            info["form"] = FORM_FACTORS.get(mods[0].get("FormFactor"))
        arr = powershell_json("Get-CimInstance Win32_PhysicalMemoryArray | Select MemoryDevices")
        if arr:
            info["slots_total"] = sum(a.get("MemoryDevices") or 0 for a in arr) or None
        if not info["total_gb"] and info["modules"]:
            info["total_gb"] = round(sum(info["modules"]), 1)
    elif SYSTEM == "Darwin":
        mem = run(["sysctl", "-n", "hw.memsize"])
        if mem.isdigit() and not info["total_gb"]:
            info["total_gb"] = gb(int(mem))
    elif SYSTEM == "Linux":
        if not info["total_gb"]:
            try:
                with open("/proc/meminfo") as f:
                    m = re.search(r"MemTotal:\s+(\d+)", f.read())
                    if m:
                        info["total_gb"] = gb(int(m.group(1)) * 1024)
            except OSError:
                pass
        # dmidecode only works as root; skip quietly otherwise
        dmi = run(["dmidecode", "-t", "memory"]) if os.geteuid() == 0 else ""
        for block in dmi.split("Memory Device")[1:]:
            size = re.search(r"Size:\s*(\d+)\s*(GB|MB)", block)
            if not size:
                continue
            val = int(size.group(1)) / (1024 if size.group(2) == "MB" else 1)
            info["modules"].append(round(val, 1))
            t = re.search(r"Type:\s*(DDR\d)", block)
            f = re.search(r"Form Factor:\s*(\w+)", block)
            c = re.search(r"Configured (?:Memory|Clock) Speed:\s*(\d+)", block)
            pn = re.search(r"Part Number:\s*(\S+)", block)
            info["type"] = info["type"] or (t.group(1) if t else None)
            info["form"] = info["form"] or (f.group(1) if f else None)
            if c:
                info["configured_mhz"] = int(c.group(1))
            if pn:
                info["part_numbers"].append(pn.group(1))
        if dmi:
            info["slots_total"] = dmi.count("Memory Device") or None

    rated = [parts_db.rated_speed_from_part(p) for p in info["part_numbers"]]
    rated = [r for r in rated if r]
    info["rated_mhz"] = min(rated) if rated else info["speed_mhz"]
    return info


def detect_board():
    info = {"system_vendor": None, "system_model": None, "board_vendor": None,
            "board_model": None, "chipset": None, "bios": None, "laptop": False, "oem": False}
    laptop_types = {8, 9, 10, 14, 30, 31, 32}

    if SYSTEM == "Windows":
        bb = powershell_json("Get-CimInstance Win32_BaseBoard | Select Manufacturer,Product")
        cs = powershell_json("Get-CimInstance Win32_ComputerSystem | Select Manufacturer,Model")
        bios = powershell_json("Get-CimInstance Win32_BIOS | Select SMBIOSBIOSVersion,ReleaseDate")
        enc = powershell_json("Get-CimInstance Win32_SystemEnclosure | Select ChassisTypes")
        if bb:
            info["board_vendor"] = bb[0].get("Manufacturer")
            info["board_model"] = bb[0].get("Product")
        if cs:
            info["system_vendor"] = cs[0].get("Manufacturer")
            info["system_model"] = cs[0].get("Model")
        if bios:
            info["bios"] = bios[0].get("SMBIOSBIOSVersion")
        if enc:
            types = enc[0].get("ChassisTypes") or []
            types = types if isinstance(types, list) else [types]
            info["laptop"] = any(t in laptop_types for t in types)
    elif SYSTEM == "Linux":
        def dmi(name):
            try:
                with open(f"/sys/class/dmi/id/{name}") as f:
                    return f.read().strip() or None
            except OSError:
                return None
        info.update(board_vendor=dmi("board_vendor"), board_model=dmi("board_name"),
                    system_vendor=dmi("sys_vendor"), system_model=dmi("product_name"),
                    bios=dmi("bios_version"))
        ct = dmi("chassis_type")
        info["laptop"] = bool(ct and ct.isdigit() and int(ct) in laptop_types)
    elif SYSTEM == "Darwin":
        info["system_vendor"] = "Apple"
        info["system_model"] = run(["sysctl", "-n", "hw.model"]) or None
        info["laptop"] = "book" in (info["system_model"] or "").lower()

    info["chipset"] = parts_db.chipset_from_board(info["board_model"])
    vendors = f"{info['system_vendor'] or ''} {info['board_vendor'] or ''}".lower()
    info["oem"] = any(v in vendors for v in parts_db.OEM_VENDORS)
    return info


def detect_storage():
    drives = []

    if SYSTEM == "Windows":
        for d in powershell_json("Get-PhysicalDisk | Select FriendlyName,MediaType,Size,BusType"):
            media = str(d.get("MediaType") or "Unknown")
            media = {"3": "HDD", "4": "SSD", "0": "Unknown"}.get(media, media)
            bus = str(d.get("BusType") or "")
            bus = {"7": "USB", "11": "SATA", "17": "NVMe", "3": "ATA", "8": "RAID",
                   "10": "SAS", "12": "SD"}.get(bus, bus)
            drives.append({"name": d.get("FriendlyName"), "type": media, "bus": bus,
                           "size_gb": gb(int(d.get("Size") or 0))})
    elif SYSTEM == "Linux":
        base = "/sys/block"
        if os.path.isdir(base):
            for dev in sorted(os.listdir(base)):
                if dev.startswith(("loop", "ram", "zram", "sr", "dm-", "md")):
                    continue
                try:
                    with open(f"{base}/{dev}/queue/rotational") as f:
                        rot = f.read().strip() == "1"
                    with open(f"{base}/{dev}/size") as f:
                        size = int(f.read().strip()) * 512
                except OSError:
                    continue
                if size < 1024 ** 3:  # skip tiny/virtual devices under 1 GB
                    continue
                nvme = dev.startswith("nvme")
                kind = "HDD" if rot else "SSD"
                drives.append({"name": dev, "type": kind, "bus": "NVMe" if nvme else "SATA",
                               "size_gb": gb(size)})
    elif SYSTEM == "Darwin":
        out = run(["system_profiler", "SPStorageDataType"])
        is_ssd = "Solid State: Yes" in out
        drives.append({"name": "Internal disk", "type": "SSD" if is_ssd else "Unknown",
                       "bus": "", "size_gb": None})

    # Free space on the system drive
    root = os.environ.get("SystemDrive", "C:") + "\\" if SYSTEM == "Windows" else "/"
    try:
        usage = shutil.disk_usage(root)
        system_drive = {"path": root, "total_gb": gb(usage.total),
                        "free_gb": gb(usage.free),
                        "free_pct": round(usage.free / usage.total * 100, 1)}
    except OSError:
        system_drive = None

    if SYSTEM == "Darwin" and system_drive and drives:
        drives[0]["size_gb"] = system_drive["total_gb"]
    return {"drives": drives, "system_drive": system_drive}


INTEGRATED_HINTS = ("intel(r) uhd", "intel(r) hd", "intel hd", "intel uhd", "iris",
                    "radeon(tm) graphics", "radeon graphics", "vega", "microsoft basic",
                    "llvmpipe", "virtualbox", "vmware", "apple m", "apple gpu")


def detect_gpu():
    gpus = []

    # NVIDIA cards report accurate VRAM through nvidia-smi on any OS
    nv = run(["nvidia-smi", "--query-gpu=name,memory.total",
              "--format=csv,noheader,nounits"])
    for line in nv.splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) == 2 and parts[1].isdigit():
            gpus.append({"name": parts[0], "vram_gb": round(int(parts[1]) / 1024, 1)})

    if SYSTEM == "Windows":
        for v in powershell_json("Get-CimInstance Win32_VideoController | Select Name,AdapterRAM"):
            name = v.get("Name") or "Unknown"
            if any(g["name"] in name or name in g["name"] for g in gpus):
                continue
            ram = v.get("AdapterRAM") or 0
            # AdapterRAM is a 32-bit field and caps at 4 GB, so it's a lower bound
            gpus.append({"name": name, "vram_gb": gb(ram) if ram > 0 else None})
    elif SYSTEM == "Linux" and not gpus:
        for line in run("lspci 2>/dev/null").splitlines():
            if re.search(r"VGA|3D controller|Display controller", line):
                gpus.append({"name": line.split(": ", 1)[-1], "vram_gb": None})
    elif SYSTEM == "Darwin":
        out = run(["system_profiler", "SPDisplaysDataType"])
        for m in re.finditer(r"Chipset Model:\s*(.+)", out):
            gpus.append({"name": m.group(1).strip(), "vram_gb": None})

    # Drop virtual display adapters (VR software, remote desktop, streaming tools)
    virtual = ("virtual", "remote", "basic display", "basic render", "parsec", "spacedesk", "idd")
    gpus = [g for g in gpus if not any(v in g["name"].lower() for v in virtual)]
    for g in gpus:
        g["integrated"] = any(h in g["name"].lower() for h in INTEGRATED_HINTS)
    return gpus


def detect_all():
    return {
        "os": f"{platform.system()} {platform.release()} ({platform.machine()})",
        "cpu": detect_cpu(),
        "ram": detect_ram(),
        "storage": detect_storage(),
        "gpu": detect_gpu(),
        "board": detect_board(),
    }


# ----------------------------------------------------------------------------
# Recommendations
# ----------------------------------------------------------------------------
# Minimum / recommended targets per use profile
PROFILES = {
    "general":  {"ram": (8, 16),  "cores": (4, 6),  "vram": (0, 0)},
    "dev":      {"ram": (16, 32), "cores": (6, 8),  "vram": (0, 0)},
    "gaming":   {"ram": (16, 32), "cores": (6, 8),  "vram": (8, 12)},
    "creative": {"ram": (32, 64), "cores": (8, 12), "vram": (8, 12)},
}

FREE, HIGH, MED, LOW = "FREE", "HIGH", "MEDIUM", "LOW"
PRIORITY_ORDER = {FREE: 0, HIGH: 1, MED: 2, LOW: 3}


_SETTINGS = {}


def _part(name, note="", status="ok", gain=1.0, extra_cost=0, extra_note=""):
    """status: ok (fits as-is), bios (fits after a BIOS update), check (verify first),
    psu (needs a bigger power supply), new (needs a new platform)."""
    overrides = _SETTINGS.get("price_overrides") or {}
    price = overrides.get(name, parts_db.estimate_price(name))
    return {"name": name, "note": note, "status": status, "gain": round(gain, 3),
            "price": price, "extra_cost": extra_cost, "extra_note": extra_note,
            "url": parts_db.price_search_url(name)}


def _context(hw):
    board = hw.get("board") or {}
    platform_key, cpu_key, mobile = parts_db.identify_cpu(hw["cpu"]["name"])
    laptop = bool(board.get("laptop") or mobile)
    mac = SYSTEM == "Darwin"
    return {"platform": None if (laptop or mac) else platform_key, "cpu_key": cpu_key,
            "laptop": laptop, "mac": mac, "board": board,
            "chipset": board.get("chipset"), "oem": board.get("oem"),
            "vendor": board.get("system_vendor") or board.get("board_vendor") or "your PC maker"}


def _cpu_perf(scores, profile):
    g, m = scores
    return {"gaming": g, "creative": m, "dev": 0.4 * g + 0.6 * m}.get(profile, (g + m) / 2)


def _gpu_pcie_gen(ctx):
    plat, chip = ctx["platform"], ctx["chipset"] or ""
    if plat == "AM4" and chip in ("A320", "B350", "X370", "B450", "X470", "A520"):
        return 3
    if plat == "LGA1200" and (ctx["cpu_key"] or "").startswith("10"):
        return 3
    return parts_db.PLATFORMS[plat]["gpu_pcie"] if plat else None


def _board_links(ctx):
    b = ctx["board"]
    name = " ".join(x for x in (b.get("system_model") if ctx["oem"] else None,
                                b.get("board_vendor"), b.get("board_model")) if x)
    if not name:
        return []
    return [{"label": "Look up your motherboard's CPU/RAM support list",
             "url": parts_db.web_search_url(f"{name} CPU support list memory QVL")}]


# ---------------- RAM ----------------
def _ram_recs(hw, p, profile, ctx, add):
    r = hw["ram"]
    total, rtype = r["total_gb"], r.get("type")
    board_model = (ctx["board"].get("board_model") or "").upper()
    if not rtype and ctx["platform"] in ("LGA1700",):
        rtype = "DDR4" if re.search(r"DDR4|\bD4\b", board_model) else None
    if not rtype and ctx["platform"]:
        mem = parts_db.PLATFORMS[ctx["platform"]]["memory"]
        rtype = mem[0] if len(mem) == 1 else None
    form = r.get("form") or ("SODIMM" if ctx["laptop"] else "DIMM")
    conf, rated = r.get("configured_mhz"), r.get("rated_mhz")
    oem_note = (f" Note: many prebuilt systems ({ctx['vendor']}) lock memory speed and have no "
                "XMP option. If yours doesn't show it, there's nothing to fix.") if ctx["oem"] else ""

    # Free speed fix
    if not ctx["laptop"] and not ctx["mac"] and conf:
        if rated and rated > conf + 100:
            add(FREE, "RAM speed", f"Your memory is rated for {rated} MHz but is running at {conf} MHz.",
                "Restart, enter the BIOS (usually Del or F2), and enable XMP (Intel) or EXPO/DOCP (AMD). "
                "It's a free speed boost." + oem_note)
        elif (rtype == "DDR4" and conf <= 2400) or (rtype == "DDR5" and conf <= 4800):
            add(FREE, "RAM speed", f"Your {rtype} is running at {conf} MHz, the slow fallback speed.",
                f"Most {rtype} kits are rated faster ({parts_db.RAM_SWEET_SPOT[rtype]}) but run at the "
                "fallback speed until XMP (Intel) or EXPO/DOCP (AMD) is enabled in the BIOS. "
                "Check your BIOS for that setting." + oem_note)

    if not total:
        return
    mods, slots = r["modules"], r["slots_total"]
    lo, hi = p["ram"]

    if total < hi:
        if rtype == "LPDDR5" or (ctx["mac"]):
            add(MED if total >= lo else HIGH, "RAM", f"{total:g} GB is under the recommended {hi} GB.",
                "This memory is soldered to the motherboard and can't be upgraded.")
            return
        target = hi
        free_slots = (slots - len(mods)) if (slots and mods) else None
        needed = target - total
        if free_slots and free_slots >= 2 and needed in (16, 32):
            kit_size, how = int(needed), (f"You have {free_slots} empty slots, so you can add a "
                                         f"{int(needed)} GB kit alongside your current memory. For best "
                                         "stability, match the speed of your existing sticks.")
        else:
            kit_size = target
            how = (f"Your {slots or len(mods) or '?'} slot(s) are full, so replace your current sticks "
                   f"with a {target} GB kit." if mods else f"Get a {target} GB kit.")
        kits = parts_db.RAM_KITS.get((rtype, form, kit_size), []) if rtype else []
        status = "ok" if rtype else "check"
        note = (f"{rtype} {form}, matches your system" if rtype
                else "Confirm whether your board takes DDR4 or DDR5 first")
        if ctx["laptop"]:
            status, note = "check", "Check that your laptop's RAM isn't soldered before buying"
        parts = [_part(k, note, status) for k in kits[:1]]  # one kit is enough for pricing
        parts += [_part(k, note, status) for k in kits[1:]]
        if not parts and rtype == "DDR3":
            how += " DDR3 is obsolete; a new platform is a better use of money."
        prio = HIGH if total < lo else MED if profile in ("creative", "dev", "gaming") else LOW
        add(prio, "RAM", f"{total:g} GB is {'below the minimum' if total < lo else 'under the recommended'} "
                         f"{lo if total < lo else hi} GB for {profile} use.", how, parts, _board_links(ctx))
    elif len(mods) == 1 and (slots or 2) >= 2:
        add(MED, "RAM", "Only one memory stick is installed (single-channel).",
            "Add an identical second stick to enable dual-channel mode, which noticeably boosts performance.")


# ---------------- Storage ----------------
def _ssd_parts(ctx, size_label, has_nvme):
    plat = ctx["platform"]
    if ctx["mac"]:
        return [_part(f"Samsung T9 {size_label}", "External USB SSD", "ok"),
                _part(f"Crucial X10 {size_label}", "External USB SSD", "ok")]
    gen = parts_db.PLATFORMS[plat]["m2_gen"] if plat else None
    if plat == "LGA1151":
        gen = 3
    if ctx["laptop"]:
        status, note = "check", "Check your laptop has a free M.2 2280 slot (or replace the current drive)"
    elif gen:
        status = "check" if has_nvme else "ok"
        note = ("Needs a free M.2 slot (one is already in use; most boards have 2+)" if has_nvme
                else "Fits your motherboard's M.2 slot")
        if gen == 3:
            note += "; runs at PCIe 3.0 speed on your board, still far faster than SATA"
    else:
        status, note = "check", "Check your motherboard has an M.2 slot"

    parts = [_part(f"{n} {size_label}", note, status, gain=1.05 if n in parts_db.NVME_GEN4 else 1.0)
             for n in parts_db.NVME_GEN4[:2] + parts_db.NVME_GEN4_VALUE[:1]]
    if size_label == "4TB":
        parts.append(_part(f"{parts_db.NVME_GEN4_VALUE[0]} 2TB",
                           note + " (budget option, less space)", status, gain=0.75))
    if gen and gen >= 5:
        parts.append(_part(f"{parts_db.NVME_GEN5[0]} {size_label}",
                           "PCIe 5.0, fastest option; your platform supports it", status))
    if plat == "LGA1151" or not gen:
        parts += [_part(f"{n} {size_label}", "2.5\" SATA, fits any system with a SATA port and a drive bay", "ok")
                  for n in parts_db.SATA_SSD[:1]]
    return parts


def _storage_recs(hw, ctx, add):
    drives = [d for d in hw["storage"]["drives"] if d.get("bus") != "USB"]
    sd = hw["storage"]["system_drive"]
    has_nvme = any(d.get("bus") == "NVMe" for d in drives)
    size_label = "4TB" if sd and sd["total_gb"] >= 1500 else "2TB"
    issues, prio = [], None

    def bump(new):
        nonlocal prio
        if prio is None or PRIORITY_ORDER[new] < PRIORITY_ORDER[prio]:
            prio = new

    if drives and all(d["type"] == "HDD" for d in drives):
        issues.append("No SSD detected: your system runs from a slow hard drive.")
        bump(HIGH)
    if sd:
        if sd["free_pct"] < 10:
            issues.append(f"Your system drive is nearly full ({sd['free_gb']:g} GB, {sd['free_pct']}% free).")
            bump(HIGH)
        elif sd["free_pct"] < 20:
            issues.append(f"Your system drive is getting full ({sd['free_pct']}% free).")
            bump(MED)
        if sd["total_gb"] < 250:
            issues.append(f"Your system drive is small ({sd['total_gb']:g} GB).")
            bump(MED)
    if not issues:
        return

    sata_ssd_only = drives and not has_nvme and any(d["type"] == "SSD" for d in drives)
    advice = (f"Add a {size_label} NVMe SSD and move your games and large folders onto it, or clone "
              "Windows onto it with the drive maker's free migration tool.")
    if sata_ssd_only and not ctx["laptop"]:
        advice += " Your current SSD uses SATA; an NVMe drive is also several times faster."
    add(prio, "Storage", " ".join(issues), advice, _ssd_parts(ctx, size_label, has_nvme))


# ---------------- CPU ----------------
def _cpu_recs(hw, p, profile, ctx, add):
    cores = hw["cpu"]["cores"] or hw["cpu"]["threads"]
    lo, hi = p["cores"]
    too_few = bool(cores and cores < lo)
    plat = ctx["platform"]

    if ctx["laptop"] or ctx["mac"]:
        if too_few:
            add(HIGH, "CPU", f"{cores} cores is below the {lo}-core minimum for {profile} use.",
                "Laptop and Mac processors are soldered to the motherboard, so the only upgrade "
                "path is a new computer.")
        return
    if not plat:
        if too_few:
            add(HIGH, "CPU", f"{cores} cores is below the {lo}-core minimum for {profile} use.",
                "Couldn't identify your CPU socket, so check your motherboard's CPU support list before buying.",
                links=_board_links(ctx))
        return

    info = parts_db.PLATFORMS[plat]
    chip = ctx["chipset"] or ""
    cur = parts_db.cpu_score(ctx["cpu_key"])
    cur_perf = _cpu_perf(cur, profile) if cur else 0
    parts = []
    for c in info["cpu_upgrades"]:
        perf = _cpu_perf(parts_db.CPU_SCORES[c["key"]], profile)
        if cur and perf < cur_perf * 1.12:
            continue
        status, notes = "ok", []
        if plat == "LGA1700":
            if chip.startswith(("Z6", "H6", "B6")):
                status = "bios"
                notes.append(f"Needs a BIOS update first ({chip} board)")
            elif not chip:
                status = "check"
                notes.append("May need a BIOS update; check your board's support list")
            if c.get("k") and chip and not chip.startswith("Z"):
                notes.append(f"Your {chip} board can't overclock, so the F version is better value")
        elif plat == "AM4":
            if chip == "A320":
                status = "check"
                notes.append("Many A320 boards don't support Ryzen 5000")
            elif chip[1:2] in ("3", "4"):
                status = "bios"
                notes.append(f"Needs a BIOS update first ({chip} board)")
        elif plat == "AM5" and chip[1:2] == "6":
            status = "bios"
            notes.append(f"Needs a BIOS update first ({chip} board)")
        elif plat == "LGA1200" and c.get("needs_500"):
            if chip in ("B460", "H410"):
                continue
            if chip in ("Z490", "H470"):
                status = "bios"
                notes.append("Needs a BIOS update first")
            elif not chip.startswith(("Z5", "B5", "H5")):
                status = "check"
                notes.append("Needs a 500-series board")
        elif plat == "LGA1151" and chip[1:2] in ("1", "2"):
            continue  # 100/200-series boards can't run 8th/9th gen
        if ctx["oem"]:
            status = "check"
            notes.append(f"Prebuilt board: confirm on {ctx['vendor']}'s support site that it supports this CPU")
        if c["tdp"] >= 120:
            notes.append("Runs hot: needs a large tower or 240mm+ liquid cooler")
        if c.get("note"):
            notes.append(c["note"])
        gain = (perf / cur_perf - 1) if cur_perf else 0.5
        parts.append(_part(c["name"], "; ".join(notes) or f"Drops into your {plat} motherboard",
                           status, gain=max(gain, 0.05)))

    weak_old_platform = info["end_of_line"] and cur and cur_perf < 60
    if weak_old_platform:
        bundle = parts_db.NEW_PLATFORM_BUNDLES[profile]
        parts += [_part(n, "New platform: CPU, motherboard and RAM are bought together", "new", gain=0.8)
                  for n in bundle]

    if not parts and not too_few:
        return
    cpu_short = re.sub(r"\(R\)|\(TM\)|CPU|Processor|\d+th Gen|@.*", "", hw["cpu"]["name"]).strip()
    cpu_short = re.sub(r"\s+", " ", cpu_short)
    if too_few:
        prio, issue = HIGH, f"{cores} cores is below the {lo}-core minimum for {profile} use."
    elif weak_old_platform:
        prio, issue = MED, f"Your {cpu_short} is on an older platform that's reaching its limits."
    else:
        prio, issue = LOW, f"Your {cpu_short} is fine for {profile} use. This is an optional upgrade."
    advice = f"These fit your {info['label']} motherboard. {info['cpu_note']}"
    if weak_old_platform:
        advice += " A new platform (last three items) gives a much bigger jump."
    add(prio, "CPU", issue, advice, parts, _board_links(ctx))


# ---------------- GPU ----------------
def _gpu_recs(hw, p, profile, ctx, add):
    lo_v, hi_v = p["vram"]
    gpus = hw["gpu"]
    dedicated = [g for g in gpus if not g["integrated"]]
    needs_gpu = lo_v > 0

    if ctx["laptop"] or ctx["mac"]:
        if needs_gpu and not dedicated:
            add(HIGH, "GPU", f"Only integrated graphics; {profile} benefits from a dedicated GPU.",
                "Laptop graphics can't be upgraded. For a big jump you'd need a new computer.")
        return
    if not needs_gpu:
        return

    scores = [parts_db.gpu_score(g["name"]) for g in dedicated]
    scores = [s for s in scores if s]
    cur = max(scores) if scores else (0 if not dedicated else None)
    vram = max((g["vram_gb"] or 0) for g in dedicated) if dedicated else 0
    base = cur if cur is not None else 100
    candidates = [c for c in parts_db.GPU_CATALOG
                  if c["score"] >= base * 1.4 and c["vram"] >= lo_v
                  and (profile == "creative" or c["score"] < 400)]

    pcie = _gpu_pcie_gen(ctx)
    cpu = parts_db.cpu_score(ctx["cpu_key"])
    st = _SETTINGS
    psu_w, pins8, pins16, max_len = (st.get("psu_watts"), st.get("psu_8pin"),
                                     st.get("psu_16pin"), st.get("gpu_max_length_mm"))
    parts, too_long = [], 0
    for c in candidates:
        if max_len and c["length_mm"] > max_len:
            too_long += 1
            continue
        notes, status, extra_cost, extra_note = [], "ok", 0, ""
        if cur:
            notes.append(f"About {c['score'] / cur:.1f}x your current card")
        notes.append(f"{c['vram']} GB VRAM, {c['watts']} W")
        if c["lanes"] == 8 and pcie and pcie <= 3:
            status = "check"
            notes.append("Uses 8 PCIe lanes, so it loses some speed on your PCIe 3.0 board")
        if cpu and cpu[0] < 60 and c["score"] >= 200:
            notes.append("Your CPU may hold this card back")

        # Power supply
        psu_short = False
        if psu_w:
            if psu_w < c["psu"] - 50:
                psu_short = True
                notes.append(f"Your {psu_w} W PSU is too small; needs about {c['psu']} W")
            elif psu_w < c["psu"]:
                notes.append(f"Your {psu_w} W PSU is borderline (recommended {c['psu']} W)")
        else:
            notes.append(f"Needs a {c['psu']} W+ power supply")
        if pins8 is not None:
            if not ((c["sixteen"] and pins16) or pins8 >= c["eight_pin"]):
                psu_short = True
                notes.append(f"Needs {c['eight_pin']} PCIe 8-pin cables (you have {pins8})"
                             + (" or a 16-pin cable" if c["sixteen"] else ""))
        if psu_short:
            status = "psu"
            watts = max(c["psu"], 750)
            extra_cost = parts_db.PSU_PRICES.get(watts, 180)
            extra_note = f"+ {watts} W power supply"
        elif ctx["oem"] and c["watts"] >= 250 and not psu_w:
            status = "check"
            notes.append("Prebuilt PSU: enter its wattage in My Setup to check")

        # Case space
        if max_len:
            room = max_len - c["length_mm"]
            notes.append(f"Choose a model under {max_len} mm" + (" (tight fit)" if room < 20 else ""))
        else:
            notes.append(f"Shortest models are about {c['length_mm']} mm")

        gain = (c["score"] / cur - 1) if cur else c["score"] / 100
        parts.append(_part(c["name"], "; ".join(notes), status, gain=gain,
                           extra_cost=extra_cost, extra_note=extra_note))

    if not gpus:
        prio, issue = MED, "Couldn't detect a graphics card. If you have one, compare it with these."
    elif not dedicated:
        prio, issue = HIGH, f"Only integrated graphics; {profile} benefits from a dedicated card."
    elif 0 < vram < lo_v:
        prio, issue = HIGH, f"Your GPU has about {vram:g} GB VRAM (minimum {lo_v} GB for {profile})."
    elif cur and cur < 150:
        best = max(dedicated, key=lambda g: parts_db.gpu_score(g["name"]) or 0)
        prio, issue = MED, f"Your {best['name']} is the weakest link for {profile}."
    elif cur is None:
        prio, issue = LOW, "Couldn't rate your current card, but these are strong current options."
    else:
        prio, issue = LOW, "Your GPU is capable. This is an optional upgrade."
    if not parts and not too_long:
        return
    advice = ("All of these fit a standard PCIe x16 slot. They're listed from slowest to fastest, "
              "so pick based on budget.")
    if too_long:
        advice += f" {too_long} card(s) were hidden because they're too long for your case."
    if not st.get("psu_watts"):
        advice += " Enter your power supply and case size under My Setup for exact fit checks."
    add(prio, "GPU", issue, advice, parts)


def recommend(hw, profile, settings=None):
    global _SETTINGS
    _SETTINGS = settings or {}
    p = PROFILES[profile]
    ctx = _context(hw)
    recs = []

    def add(priority, component, issue, advice, parts=None, links=None):
        recs.append({"priority": priority, "component": component, "issue": issue,
                     "advice": advice, "parts": parts or [], "links": links or []})

    _ram_recs(hw, p, profile, ctx, add)
    _storage_recs(hw, ctx, add)
    _cpu_recs(hw, p, profile, ctx, add)
    _gpu_recs(hw, p, profile, ctx, add)
    if ctx["mac"]:
        add(LOW, "Platform", "Modern Macs have soldered RAM and storage.",
            "Internal upgrades usually aren't possible. External SSDs are the practical option.")
    return sorted(recs, key=lambda r: PRIORITY_ORDER[r["priority"]])


PRIORITY_WEIGHT = {HIGH: 3, MED: 2, LOW: 1, FREE: 0}


def plan_budget(recs, budget, resale=None):
    """Pick at most one part per recommendation to get the most benefit for the money.

    Benefit = priority weight x expected gain. resale: {component: value} of old parts
    you'll sell when replacing them; it's subtracted from the cost. Returns the best
    plan plus runner-ups.
    """
    resale = resale or {}
    import itertools

    groups = []
    for r in recs:
        opts, bundle = [], [p for p in r["parts"] if p["status"] == "new"]
        for part in r["parts"]:
            if part["status"] == "new" or part["price"] is None:
                continue
            gross = part["price"] + (part.get("extra_cost") or 0)
            sold = resale.get(r["component"]) or 0
            opts.append({"component": r["component"], "parts": [part], "cost": max(0, gross - sold),
                         "gross": gross, "resale": sold,
                         "value": PRIORITY_WEIGHT[r["priority"]] * part["gain"]})
        if bundle and all(p["price"] is not None for p in bundle):
            opts.append({"component": r["component"] + " (new platform)", "parts": bundle,
                         "cost": sum(p["price"] for p in bundle), "gross": sum(p["price"] for p in bundle),
                         "resale": 0,
                         "value": PRIORITY_WEIGHT[r["priority"]] * bundle[0]["gain"] * 1.5})
        if opts:
            groups.append(opts)

    plans = []
    for combo in itertools.product(*[[None] + g for g in groups]):
        picks = [c for c in combo if c]
        cost = sum(c["cost"] for c in picks)
        if cost <= budget and picks:
            plans.append({"picks": picks, "total": cost, "value": sum(c["value"] for c in picks)})
    plans.sort(key=lambda p: (-round(p["value"], 3), p["total"]))

    # Keep a few distinct alternatives
    seen, best = set(), []
    for plan in plans:
        key = tuple(sorted(pp["name"] for c in plan["picks"] for pp in c["parts"]))
        if key not in seen:
            seen.add(key)
            best.append(dict(plan, leftover=budget - plan["total"]))
        if len(best) == 3:
            break
    return best


def simulate_upgrade(hw, component, part_name):
    """A copy of the scan with one part swapped in, for previewing an upgrade."""
    import copy
    new = copy.deepcopy(hw)
    if component == "GPU":
        cat = next((g for g in parts_db.GPU_CATALOG if g["name"] == part_name), None)
        new["gpu"] = [{"name": part_name, "vram_gb": cat["vram"] if cat else None, "integrated": False}]
    elif component == "CPU":
        new["cpu"]["name"] = part_name
        m = re.search(r"(\d+)C/(\d+)T", part_name)
        if m:
            new["cpu"]["cores"], new["cpu"]["threads"] = int(m.group(1)), int(m.group(2))
    elif component == "RAM":
        m = re.search(r"(\d+)GB \((\d)x(\d+)GB\) (DDR\d)-(\d+)", part_name)
        if m:
            total, count, each, kind, mhz = m.groups()
            add = (new["ram"].get("slots_total") or 0) - len(new["ram"]["modules"]) >= int(count) and \
                int(total) < (new["ram"]["total_gb"] or 0) * 2
            new["ram"]["modules"] = (new["ram"]["modules"] if add else []) + [float(each)] * int(count)
            new["ram"]["total_gb"] = float(sum(new["ram"]["modules"]))
            new["ram"]["type"], new["ram"]["configured_mhz"] = kind, int(mhz)
    elif component == "Storage":
        m = re.search(r"(\d+)TB", part_name)
        tb = int(m.group(1)) if m else 2
        new["storage"]["drives"].append({"name": part_name, "type": "SSD", "bus": "NVMe",
                                         "size_gb": tb * 931.0})
        sd = new["storage"].get("system_drive")
        if sd:  # assumes games and big folders move to the new drive
            used = sd["total_gb"] - sd["free_gb"]
            moved = min(used * 0.6, tb * 931 * 0.8)
            sd["free_gb"] = round(sd["free_gb"] + moved, 1)
            sd["free_pct"] = round(sd["free_gb"] / sd["total_gb"] * 100, 1)
        new["_preview_free_gb"] = tb * 931 * 0.95  # space for games on the new drive
    return new


def buying_checks(hw, recs):
    """Things the program can't detect that the person should verify before buying."""
    ctx = _context(hw)
    comps = {r["component"] for r in recs if r["parts"]}
    checks = []
    if ctx["oem"]:
        checks.append(f"Prebuilt system ({ctx['vendor']}): these often use proprietary power supplies, "
                      "cases and BIOS limits. Look up your exact model's spec sheet first.")
    if "GPU" in comps:
        if not _SETTINGS.get("psu_watts"):
            checks.append("Power supply: open the side panel and read the PSU label for its wattage, "
                          "then enter it under My Setup so the app can check each card.")
        if not _SETTINGS.get("gpu_max_length_mm"):
            checks.append("Case space: measure from the rear slot to the front of the case "
                          "(or the front fans) and enter it under My Setup.")
        checks.append("Graphics card thickness: many current cards are 2.5-3 slots thick, "
                      "so check nothing blocks the slots below your current card.")
    if "CPU" in comps:
        checks.append("CPU swap: update your BIOS to the newest version while your current CPU is "
                      "still installed, and make sure your cooler can handle the new chip.")
    if "RAM" in comps:
        checks.append("RAM: buy one matched kit rather than mixing with old sticks, and check it's "
                      "on your motherboard's memory support list (QVL) if you can.")
    if "Storage" in comps:
        checks.append("Moving Windows to a new drive: back up first, then use the SSD maker's free "
                      "cloning tool or do a clean install.")
    return checks


# ----------------------------------------------------------------------------
# Output
# ----------------------------------------------------------------------------
STATUS_LABELS = {"ok": "Compatible", "bios": "Compatible after BIOS update",
                 "check": "Check before buying", "new": "Needs new platform",
                 "psu": "Needs a bigger power supply"}


def print_report(hw, recs, profile):
    line = "=" * 64
    print(f"\n{line}\n  RIGCHECK  -  profile: {profile}\n{line}")
    print(f"OS:      {hw['os']}")

    b = hw.get("board") or {}
    if b.get("system_model") and b.get("oem"):
        print(f"System:  {b.get('system_vendor') or ''} {b['system_model']}".rstrip())
    if b.get("board_model"):
        chip = f"  (chipset {b['chipset']})" if b.get("chipset") else ""
        print(f"Board:   {b.get('board_vendor') or ''} {b['board_model']}{chip}")
    if b.get("bios"):
        print(f"BIOS:    {b['bios']}")

    c = hw["cpu"]
    print(f"CPU:     {c['name']}")
    print(f"         {c['cores'] or '?'} cores / {c['threads'] or '?'} threads"
          + (f" @ up to {c['max_ghz']} GHz" if c['max_ghz'] else ""))

    r = hw["ram"]
    extra = [x for x in (r.get("type"), r.get("form")) if x]
    if r["modules"]:
        extra.append(f"{len(r['modules'])} stick(s): " + " + ".join(f"{m:g} GB" for m in r["modules"]))
    if r["slots_total"]:
        extra.append(f"{r['slots_total']} slots total")
    if r.get("configured_mhz"):
        extra.append(f"running at {r['configured_mhz']} MHz")
    print(f"RAM:     {r['total_gb'] or '?'} GB" + (f"  ({', '.join(extra)})" if extra else ""))

    print("Storage:")
    for d in hw["storage"]["drives"] or [{"name": "(not detected)", "type": "", "size_gb": None, "bus": ""}]:
        size = f"{d['size_gb']:g} GB" if d["size_gb"] else ""
        print(f"         - {d['name']}  {d['type']} {d['bus']} {size}".rstrip())
    sd = hw["storage"]["system_drive"]
    if sd:
        print(f"         System drive: {sd['free_gb']} GB free of {sd['total_gb']} GB ({sd['free_pct']}%)")

    print("GPU:")
    for g in hw["gpu"] or [{"name": "(not detected)", "vram_gb": None, "integrated": False}]:
        tag = " [integrated]" if g["integrated"] else ""
        vram = f"  {g['vram_gb']} GB VRAM" if g["vram_gb"] else ""
        print(f"         - {g['name']}{vram}{tag}")

    print(f"\n{line}\n  RECOMMENDATIONS\n{line}")
    if not recs:
        print("Your system looks well-matched to this profile. No upgrades needed!")
    for i, rec in enumerate(recs, 1):
        print(f"\n{i}. [{rec['priority']}] {rec['component']}")
        print(f"   Issue:  {rec['issue']}")
        print(f"   Advice: {rec['advice']}")
        if rec["parts"]:
            print("   Compatible parts:")
            for part in rec["parts"]:
                price = f"  ~${part['price']}" if part.get("price") else ""
                print(f"     * {part['name']}{price}  [{STATUS_LABELS[part['status']]}]")
                if part["note"]:
                    print(f"       {part['note']}")
                print(f"       Prices: {part['url']}")
        for link in rec["links"]:
            print(f"   {link['label']}: {link['url']}")

    checks = buying_checks(hw, recs)
    if checks:
        print(f"\n{line}\n  BEFORE YOU BUY\n{line}")
        for chk in checks:
            print(f" - {chk}")
    print(f"\nParts list current as of {parts_db.DB_DATE}. Prices change daily, so compare before buying.")
    if not psutil:
        print("Tip: `pip install psutil` for more accurate detection.")
    print()


def main():
    ap = argparse.ArgumentParser(description="Detect hardware and recommend compatible upgrades.")
    ap.add_argument("--profile", choices=PROFILES.keys(), default="general",
                    help="what you mainly use the computer for")
    ap.add_argument("--json", action="store_true", help="output JSON instead of a report")
    args = ap.parse_args()

    try:
        import hw_store
        settings = hw_store.load_settings()  # PSU / case info entered in the app
    except Exception:
        settings = {}
    hw = detect_all()
    recs = recommend(hw, args.profile, settings)

    if args.json:
        print(json.dumps({"profile": args.profile, "hardware": hw, "recommendations": recs,
                          "before_you_buy": buying_checks(hw, recs)}, indent=2))
    else:
        print_report(hw, recs, args.profile)


if __name__ == "__main__":
    main()
