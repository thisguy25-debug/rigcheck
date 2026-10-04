"""
"Can I run it?" game requirements.

Requirements are the publishers' official minimum / recommended specs.
Each listed CPU/GPU is converted to the same rough performance scale used in
parts_db (GPU: RTX 3060 = 100, CPU gaming score: i7-12700 = 70).
"""

import parts_db

# Gaming scores for older CPUs that appear in requirement lists
REQ_CPU = {
    "Core 2 Quad Q6600": 6, "Phenom 9850": 6, "Core 2 Duo E8400": 5, "Core i5-750": 12,
    "Core i3-3210": 15, "Core i3-3225": 15, "A8-7600": 12, "Core i5-2500K": 22,
    "Core i5-3470": 22, "FX-6300": 14, "FX-8350": 18, "FX-9590": 20, "Core i5-4690": 28,
    "Core i7-4770": 30, "Core i7-4770K": 30, "Core i3-6300": 22, "Core i5-6400": 26,
    "Core i5-6600": 28, "Core i7-6700": 34, "Core i7-6700K": 34, "Core i7-6800K": 35,
    "Core i5-7300U": 18, "Ryzen 3 3300U": 18, "Core i5-8400": 44, "Core i7-8700": 50,
    "Core i7-8700K": 50, "Core i5-9600K": 52, "Core i7-9700": 55, "Core i7-10700": 57,
    "Core i7-10700K": 58, "Core i7-12700": 70, "Ryzen 5 1400": 26, "Ryzen 5 1500X": 28,
    "Ryzen 5 1600": 35, "Ryzen 5 1600X": 36, "Ryzen 5 2600X": 42, "Ryzen 7 2700X": 42,
    "Ryzen 3 3300X": 48, "Ryzen 5 3600": 55, "Ryzen 5 3600X": 56, "Ryzen 5 5500": 62,
    "Ryzen 7 7800X3D": 95,
}

# Scores for older GPUs that appear in requirement lists
REQ_GPU = {
    "GeForce 9800 GT": 4, "Radeon HD 4870": 5, "Intel HD 4000": 3, "Radeon Vega 8": 10,
    "GeForce GT 740": 8, "Radeon R7 250": 8, "GeForce GTX 660": 18, "Radeon HD 7870": 20,
    "GeForce GTX 770": 25, "Radeon R9 280": 28, "GeForce GTX 960": 35, "GeForce GTX 970": 45,
    "GeForce GTX 1050 Ti": 30, "GeForce GTX 1060 3GB": 42, "GeForce GTX 1060 6GB": 45,
    "GeForce GTX 1070": 60, "GeForce GTX 1080 Ti": 95, "GeForce GTX 1630": 22,
    "GeForce RTX 2060": 80, "GeForce RTX 2060 Super": 90, "GeForce RTX 2070": 95,
    "GeForce RTX 2080": 115, "GeForce RTX 3060": 100, "Radeon RX 470": 45, "Radeon RX 480": 50,
    "Radeon RX 580": 50, "Radeon RX 5500 XT": 55, "Radeon RX 5700 XT": 90, "Radeon RX Vega 56": 70,
    "Radeon RX 6400": 35, "Radeon RX 6600 XT": 105, "Arc A380": 30, "Arc A750": 95, "Arc A770": 105,
}


def _req(cpus, gpus, ram, vram=None, storage=None, note=""):
    return {"cpus": cpus, "gpus": gpus, "ram": ram, "vram": vram, "storage": storage,
            "cpu_score": min(REQ_CPU[c] for c in cpus) if cpus else None,
            "gpu_score": min(REQ_GPU[g] for g in gpus) if gpus else None, "note": note}


GAMES = [
    {"name": "Farming Simulator 25",
     "min": _req(["Core i5-6400", "Ryzen 5 1400"], ["GeForce GTX 1050 Ti", "Radeon RX 470"], 8, 3, 45),
     "rec": _req(["Core i7-10700", "Ryzen 5 1500X"], ["GeForce RTX 2070", "Radeon RX 5700 XT", "Arc A750"],
                 12, 8, 45),
     "note": "Big modded maps and lots of mods lean hard on VRAM and single-core CPU speed."},
    {"name": "GTA V Enhanced",
     "min": _req(["Core i7-4770", "FX-9590"], ["GeForce GTX 1630", "Radeon RX 6400"], 8, 4, 105),
     "rec": _req(["Core i5-9600K", "Ryzen 5 3600"], ["GeForce RTX 3060", "Radeon RX 6600 XT"], 16, 8, 105),
     "note": "Requires an SSD. Rockstar recommends dual-channel RAM."},
    {"name": "GTA V Legacy / FiveM",
     "min": _req(["Core 2 Quad Q6600", "Phenom 9850"], ["GeForce 9800 GT", "Radeon HD 4870"], 4, 1, 120),
     "rec": _req(["Core i5-3470", "FX-8350"], ["GeForce GTX 660", "Radeon HD 7870"], 8, 2, 120),
     "note": "Busy FiveM roleplay servers with custom cars and maps need far more than this: "
             "plan on 16 GB+ RAM and 6 GB+ VRAM."},
    {"name": "Cyberpunk 2077",
     "min": _req(["Core i7-6700", "Ryzen 5 1600"], ["GeForce GTX 1060 6GB", "Radeon RX 580", "Arc A380"],
                 12, 6, 70),
     "rec": _req(["Core i7-12700", "Ryzen 7 7800X3D"], ["GeForce RTX 2060 Super", "Radeon RX 5700 XT",
                                                        "Arc A770"], 16, 8, 70),
     "note": "Requires an SSD."},
    {"name": "Black Myth: Wukong",
     "min": _req(["Core i5-8400", "Ryzen 5 1600"], ["GeForce GTX 1060 6GB", "Radeon RX 580"], 16, 6, 130),
     "rec": _req(["Core i7-9700", "Ryzen 5 5500"], ["GeForce RTX 2060", "Radeon RX 5700 XT", "Arc A750"],
                 16, 6, 130),
     "note": "Requires an SSD."},
    {"name": "Elden Ring",
     "min": _req(["Core i5-8400", "Ryzen 3 3300X"], ["GeForce GTX 1060 3GB", "Radeon RX 580"], 12, 3, 60),
     "rec": _req(["Core i7-8700K", "Ryzen 5 3600X"], ["GeForce GTX 1070", "Radeon RX Vega 56"], 16, 8, 60)},
    {"name": "Baldur's Gate 3",
     "min": _req(["Core i5-4690", "FX-8350"], ["GeForce GTX 970", "Radeon RX 480"], 8, 4, 150),
     "rec": _req(["Core i7-8700K", "Ryzen 5 3600"], ["GeForce RTX 2060 Super", "Radeon RX 5700 XT"],
                 16, 8, 150),
     "note": "Requires an SSD."},
    {"name": "Hogwarts Legacy",
     "min": _req(["Core i5-6600", "Ryzen 5 1400"], ["GeForce GTX 960", "Radeon RX 470"], 16, 4, 85),
     "rec": _req(["Core i7-8700", "Ryzen 5 3600"], ["GeForce GTX 1080 Ti", "Radeon RX 5700 XT"], 16, 8, 85)},
    {"name": "Red Dead Redemption 2",
     "min": _req(["Core i5-2500K", "FX-6300"], ["GeForce GTX 770", "Radeon R9 280"], 8, 2, 150),
     "rec": _req(["Core i7-4770K", "Ryzen 5 1500X"], ["GeForce GTX 1060 6GB", "Radeon RX 480"], 12, 4, 150)},
    {"name": "Call of Duty: Black Ops 6",
     "min": _req(["Core i5-6600", "Ryzen 5 1400"], ["GeForce GTX 960", "Radeon RX 470"], 8, 2, 149),
     "rec": _req(["Core i7-6700K", "Ryzen 5 1600X"], ["GeForce RTX 3060", "Radeon RX 6600 XT"], 12, 8, 149)},
    {"name": "Microsoft Flight Simulator 2024",
     "min": _req(["Core i7-6800K", "Ryzen 5 2600X"], ["GeForce GTX 970", "Radeon RX 5500 XT"], 16, 4, 50),
     "rec": _req(["Core i7-10700K", "Ryzen 7 2700X"], ["GeForce RTX 2080", "Radeon RX 5700 XT"], 32, 8, 50),
     "note": "Streams scenery from the internet; a fast connection matters too."},
    {"name": "Fortnite",
     "min": _req(["Core i3-3225"], ["Intel HD 4000", "Radeon Vega 8"], 8, None, 50),
     "rec": _req(["Core i5-7300U", "Ryzen 3 3300U"], ["GeForce GTX 960", "Radeon R9 280"], 16, 2, 50)},
    {"name": "Counter-Strike 2",
     "min": _req(["Core i5-750"], ["GeForce GTX 660", "Radeon HD 7870"], 8, 1, 85),
     "rec": None},
    {"name": "Minecraft (Java)",
     "min": _req(["Core i3-3210", "A8-7600"], ["Intel HD 4000", "Radeon R7 250"], 4, None, 4),
     "rec": _req(["Core i5-4690", "A8-7600"], ["GeForce GT 740", "Radeon R7 250"], 8, None, 4),
     "note": "Big modpacks and shaders need much more: 16 GB RAM and a mid-range GPU."},
]

REQ_DATE = "Official publisher requirements, checked September 2026"


def custom_game(name, min_cpu, min_gpu, min_ram, rec_cpu=None, rec_gpu=None, rec_ram=None,
                vram=None, storage=None):
    """Build a game entry from names chosen in the app's dropdowns."""
    def cpu_s(n):
        key = parts_db.identify_cpu(n)[1] if n else None
        return REQ_CPU.get(n) or (parts_db.CPU_SCORES.get(key, (None,))[0] if key else None)

    def gpu_s(n):
        return REQ_GPU.get(n) or parts_db.gpu_score(n)

    def req(cpu, gpu, ram):
        return {"cpus": [cpu] if cpu else [], "gpus": [gpu] if gpu else [], "ram": ram, "vram": vram,
                "storage": storage, "cpu_score": cpu_s(cpu), "gpu_score": gpu_s(gpu), "note": ""}
    rec = req(rec_cpu, rec_gpu, rec_ram) if (rec_cpu or rec_gpu or rec_ram) else None
    return {"name": name, "min": req(min_cpu, min_gpu, min_ram), "rec": rec, "custom": True}


def system_scores(hw):
    """The current PC on the same scales."""
    key = parts_db.identify_cpu(hw["cpu"]["name"])[1]
    cpu = parts_db.CPU_SCORES.get(key, (None, None))[0] if key else None
    gpu_scores = [parts_db.gpu_score(g["name"]) for g in hw["gpu"]]
    gpu_scores = [s for s in gpu_scores if s]
    vram = max((g["vram_gb"] or 0) for g in hw["gpu"]) if hw["gpu"] else 0
    free = 0
    if hw.get("_preview_free_gb"):
        free = hw["_preview_free_gb"]
    else:
        try:
            import shutil
            import hw_tools
            free = max(shutil.disk_usage(d).free for d in hw_tools.fixed_drives()) / 1024 ** 3
        except Exception:
            sd = hw["storage"].get("system_drive")
            free = sd["free_gb"] if sd else 0
    return {"cpu": cpu, "gpu": max(gpu_scores) if gpu_scores else None,
            "ram": hw["ram"]["total_gb"], "vram": vram or None, "free_gb": free}


def check_game(game, sys_scores):
    """Compare one game against the PC. Returns overall verdict and per-part rows."""
    rows = []
    worst = 2  # 0 below min, 1 meets min, 2 meets rec

    def compare(label, have, need_min, need_rec, unit="", fmt="{:g}"):
        nonlocal worst
        if need_min is None and need_rec is None:
            return
        if have is None:
            rows.append((label, "?", "Couldn't measure", "unknown"))
            return
        if need_min is not None and have < need_min:
            level, text = 0, "Below minimum"
        elif need_rec is not None and have < need_rec:
            level, text = 1, "Meets minimum"
        else:
            level, text = 2, "Meets recommended" if need_rec is not None else "Meets requirement"
        worst = min(worst, level)
        rows.append((label, fmt.format(have) + unit, text, ["bad", "ok", "good"][level]))

    mn, rc = game["min"], game.get("rec") or {}
    compare("Processor", sys_scores["cpu"], mn.get("cpu_score"), rc.get("cpu_score"), fmt="score {:.0f}")
    compare("Graphics", sys_scores["gpu"], mn.get("gpu_score"), rc.get("gpu_score"), fmt="score {:.0f}")
    compare("Video memory", sys_scores["vram"], mn.get("vram"), rc.get("vram"), " GB")
    compare("RAM", sys_scores["ram"], mn.get("ram"), rc.get("ram"), " GB")
    space_short = False
    if mn.get("storage"):
        have = round(sys_scores["free_gb"] or 0)
        space_short = have < mn["storage"]
        rows.append(("Free space", f"{have} GB",
                     f"Need {mn['storage']} GB, free up space first" if space_short else "Enough space",
                     "ok" if space_short else "good"))

    verdict = ["Below minimum", "Runs at low-medium settings", "Runs well (meets recommended)"][worst]
    if worst == 2 and rc and sys_scores["gpu"] and rc.get("gpu_score"):
        ratio = sys_scores["gpu"] / rc["gpu_score"]
        if ratio >= 1.8:
            verdict = "Runs great (well above recommended)"
    short = ["Below minimum", "Low-medium settings", "Runs well"][worst]
    if verdict.startswith("Runs great"):
        short = "Runs great"
    if space_short:
        verdict += ", needs free space"
        short += ", low space"
    failing = [r[0] for r in rows if r[3] == "bad"] or \
              [r[0] for r in rows if r[3] == "ok" and r[0] != "Free space"]
    return {"verdict": verdict, "short": short, "level": worst, "rows": rows, "limiting": failing}
