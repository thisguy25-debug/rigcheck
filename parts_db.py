"""
Parts knowledge base for RigCheck.

Performance scores are rough relative numbers used only to decide whether an
upgrade is worthwhile. They are NOT benchmarks. Update the lists below as new
parts come out. Prices change constantly, so the app links to live searches
instead of storing prices.
"""

import re
import urllib.parse

DB_DATE = "September 2026"


def price_search_url(name):
    return "https://pcpartpicker.com/search/?q=" + urllib.parse.quote_plus(name)


def web_search_url(query):
    return "https://www.google.com/search?q=" + urllib.parse.quote_plus(query)


# ----------------------------------------------------------------------------
# CPUs: known chips as (gaming score, multi-thread score)
# ----------------------------------------------------------------------------
CPU_SCORES = {
    # Intel LGA1151 (6th-9th gen)
    "6700K": (38, 25), "7700K": (42, 27), "8400": (44, 33), "8700K": (50, 42),
    "9400": (46, 35), "9600K": (50, 38), "9700K": (55, 48), "9900K": (58, 58),
    # Intel LGA1200 (10th-11th gen)
    "10100": (40, 28), "10400": (48, 40), "10600K": (53, 46), "10700": (56, 58),
    "10700K": (58, 60), "10900K": (62, 70), "11400": (55, 45), "11600K": (60, 50),
    "11700K": (63, 60), "11900K": (66, 62),
    # Intel LGA1700 (12th-14th gen)
    "12100": (50, 30), "12400": (58, 40), "12600K": (65, 55), "12700": (70, 68),
    "12700K": (72, 72), "12900K": (74, 80), "13400": (62, 48), "13600K": (76, 78),
    "13700K": (80, 92), "13900K": (85, 110), "14400": (63, 50), "14600K": (78, 80),
    "14700": (80, 95), "14700K": (82, 100), "14900": (84, 105), "14900K": (86, 112),
    # Intel LGA1851 (Core Ultra 200S)
    "245K": (70, 85), "265K": (78, 115), "285K": (82, 135),
    # AMD AM4
    "1600": (35, 28), "1700": (35, 34), "2600": (40, 32), "2700X": (42, 40),
    "3600": (55, 45), "3700X": (57, 55), "3900X": (58, 75), "5500": (62, 48),
    "5600": (68, 52), "5600X": (69, 53), "5600G": (60, 50), "5700X": (71, 64),
    "5800X": (72, 66), "5900X": (73, 85), "5950X": (74, 100),
    "5700X3D": (84, 62), "5800X3D": (86, 64),
    # AMD AM5
    "7600": (78, 65), "7600X": (79, 67), "7700X": (82, 82), "7800X3D": (95, 80),
    "7900X": (83, 110), "7950X": (85, 135), "8600G": (62, 60), "8700G": (66, 70),
    "9600X": (83, 72), "9700X": (86, 88), "9800X3D": (100, 90), "9900X": (88, 120),
    "9950X": (90, 145), "9950X3D": (101, 146),
}

# ----------------------------------------------------------------------------
# Platforms (CPU socket families) and the CPUs you can drop into them
# ----------------------------------------------------------------------------
PLATFORMS = {
    "LGA1151": {
        "label": "Intel LGA1151 (6th-9th gen Core)",
        "memory": ["DDR4"], "gpu_pcie": 3, "m2_gen": 3, "end_of_line": True,
        "cpu_upgrades": [
            {"name": "Intel Core i7-9700K", "key": "9700K", "tdp": 95},
            {"name": "Intel Core i9-9900K", "key": "9900K", "tdp": 95},
        ],
        "cpu_note": "8th/9th gen chips only work in 300-series boards (Z370/Z390/B360/B365/H370/H310). "
                    "100/200-series boards cannot run them. These chips are only sold used now.",
    },
    "LGA1200": {
        "label": "Intel LGA1200 (10th-11th gen Core)",
        "memory": ["DDR4"], "gpu_pcie": 4, "m2_gen": 4, "end_of_line": True,
        "cpu_upgrades": [
            {"name": "Intel Core i9-10900K", "key": "10900K", "tdp": 125},
            {"name": "Intel Core i7-11700K", "key": "11700K", "tdp": 125, "needs_500": True},
            {"name": "Intel Core i9-11900K", "key": "11900K", "tdp": 125, "needs_500": True},
        ],
        "cpu_note": "11th gen needs a 500-series board (or Z490/H470 with a BIOS update). "
                    "This platform is end-of-line, so a new platform is usually better value.",
    },
    "LGA1700": {
        "label": "Intel LGA1700 (12th-14th gen Core)",
        "memory": ["DDR4", "DDR5"], "gpu_pcie": 4, "m2_gen": 4, "end_of_line": True,
        "cpu_upgrades": [
            {"name": "Intel Core i5-14600K", "key": "14600K", "tdp": 125, "k": True},
            {"name": "Intel Core i7-14700F", "key": "14700", "tdp": 65},
            {"name": "Intel Core i7-14700K", "key": "14700K", "tdp": 125, "k": True},
            {"name": "Intel Core i9-14900F", "key": "14900", "tdp": 65},
            {"name": "Intel Core i9-14900K", "key": "14900K", "tdp": 125, "k": True},
        ],
        "cpu_note": "13th/14th gen chips need a recent BIOS on 600-series boards (flash it BEFORE "
                    "swapping CPUs), and every 13th/14th gen system should run Intel's latest "
                    "stability microcode (0x12B or newer). The 14th gen is the last generation for this socket.",
    },
    "LGA1851": {
        "label": "Intel LGA1851 (Core Ultra 200S)",
        "memory": ["DDR5"], "gpu_pcie": 5, "m2_gen": 5, "end_of_line": False,
        "cpu_upgrades": [
            {"name": "Intel Core Ultra 7 265K", "key": "265K", "tdp": 125, "k": True},
            {"name": "Intel Core Ultra 9 285K", "key": "285K", "tdp": 125, "k": True},
        ],
        "cpu_note": "Keep your BIOS current for the latest performance fixes.",
    },
    "AM4": {
        "label": "AMD AM4 (Ryzen 1000-5000)",
        "memory": ["DDR4"], "gpu_pcie": 4, "m2_gen": 4, "end_of_line": True,
        "cpu_upgrades": [
            {"name": "AMD Ryzen 7 5700X3D", "key": "5700X3D", "tdp": 105},
            {"name": "AMD Ryzen 7 5800X3D", "key": "5800X3D", "tdp": 105,
             "note": "Re-released by AMD in June 2026"},
            {"name": "AMD Ryzen 9 5900X", "key": "5900X", "tdp": 105},
            {"name": "AMD Ryzen 9 5950X", "key": "5950X", "tdp": 105},
        ],
        "cpu_note": "Ryzen 5000 needs a BIOS update on 300/400-series boards, and some A320 boards "
                    "don't support it at all. Check your board's CPU support list first.",
    },
    "AM5": {
        "label": "AMD AM5 (Ryzen 7000-9000)",
        "memory": ["DDR5"], "gpu_pcie": 5, "m2_gen": 5, "end_of_line": False,
        "cpu_upgrades": [
            {"name": "AMD Ryzen 7 9700X", "key": "9700X", "tdp": 65},
            {"name": "AMD Ryzen 7 9800X3D", "key": "9800X3D", "tdp": 120},
            {"name": "AMD Ryzen 9 9900X", "key": "9900X", "tdp": 120},
            {"name": "AMD Ryzen 9 9950X", "key": "9950X", "tdp": 170},
            {"name": "AMD Ryzen 9 9950X3D", "key": "9950X3D", "tdp": 170},
        ],
        "cpu_note": "Ryzen 9000 on a 600-series board needs a BIOS (AGESA) update first.",
    },
}

# When the current platform is old, suggest a whole new platform instead
NEW_PLATFORM_BUNDLES = {
    "gaming": ["AMD Ryzen 7 9800X3D", "B850 motherboard", "32GB (2x16GB) DDR5-6000 CL30"],
    "creative": ["AMD Ryzen 9 9950X", "X870 motherboard", "64GB (2x32GB) DDR5-6000 CL30"],
    "dev": ["AMD Ryzen 7 9700X", "B850 motherboard", "32GB (2x16GB) DDR5-6000 CL30"],
    "general": ["AMD Ryzen 5 9600X", "B850 motherboard", "32GB (2x16GB) DDR5-6000 CL30"],
}

MOBILE_SUFFIX = re.compile(r"^(H|HX|HK|HS|U|P|Y|V|G\d)")


def identify_cpu(name):
    """Return (platform key or None, model key or None, is_mobile)."""
    n = name or ""
    # Intel Core Ultra (desktop 200S, e.g. "Ultra 7 265K")
    m = re.search(r"Ultra\s*[3579]\s*(\d{3})([A-Z]*)", n)
    if m:
        model, suffix = m.groups()
        mobile = bool(MOBILE_SUFFIX.match(suffix)) or model.startswith("1")
        return (None if mobile else "LGA1851"), model + ("K" if "K" in suffix else ""), mobile

    # Intel Core iX-NNNN(N)
    m = re.search(r"i[3579]-(\d{4,5})([A-Z]*)", n)
    if m:
        digits, suffix = m.groups()
        if MOBILE_SUFFIX.match(suffix):
            return None, None, True
        gen = int(digits[:2]) if len(digits) == 5 else int(digits[0])
        key = digits + ("K" if "K" in suffix else "")
        platform = ("LGA1700" if gen >= 12 else "LGA1200" if gen >= 10
                    else "LGA1151" if gen >= 6 else None)
        return platform, key, False

    # AMD Ryzen N NNNN(suffix)
    m = re.search(r"Ryzen\s+[3579]\s+(\d{4})([A-Z0-9]*)", n)
    if m and "Threadripper" not in n:
        digits, suffix = m.groups()
        if MOBILE_SUFFIX.match(suffix) or "Ryzen AI" in n:
            return None, None, True
        series = int(digits[0])
        key = digits + suffix.replace("XT", "X") if suffix not in ("", "F") else digits
        if suffix == "X3D":
            key = digits + "X3D"
        platform = "AM4" if series <= 5 else "AM5" if series >= 7 else None
        return platform, key, False
    return None, None, False


def cpu_score(model_key):
    return CPU_SCORES.get(model_key)


# ----------------------------------------------------------------------------
# GPUs
# ----------------------------------------------------------------------------
# Relative performance, RTX 3060 = 100 (rough 1440p raster average)
GPU_SCORES = {
    "gtx 1050 ti": 30, "gtx 1060": 45, "gtx 1650": 40, "gtx 1660 super": 60, "gtx 1660": 55,
    "gtx 1070": 60, "gtx 1080 ti": 95, "gtx 1080": 75,
    "rtx 2060 super": 90, "rtx 2060": 80, "rtx 2070 super": 105, "rtx 2070": 95,
    "rtx 2080 super": 120, "rtx 2080 ti": 140, "rtx 2080": 115,
    "rtx 3050": 65, "rtx 3060 ti": 125, "rtx 3060": 100, "rtx 3070 ti": 150, "rtx 3070": 140,
    "rtx 3080 ti": 190, "rtx 3080": 175, "rtx 3090 ti": 210, "rtx 3090": 195,
    "rtx 4060 ti": 135, "rtx 4060": 115, "rtx 4070 ti super": 215, "rtx 4070 ti": 200,
    "rtx 4070 super": 190, "rtx 4070": 170, "rtx 4080 super": 255, "rtx 4080": 250,
    "rtx 4090": 330,
    "rtx 5050": 105, "rtx 5060 ti": 158, "rtx 5060": 135, "rtx 5070 ti": 255,
    "rtx 5070": 195, "rtx 5080": 295, "rtx 5090": 400,
    "rx 580": 50, "rx 590": 55, "rx 5600 xt": 75, "rx 5700 xt": 90, "rx 5700": 82,
    "rx 6600 xt": 105, "rx 6650 xt": 110, "rx 6600": 95, "rx 6700 xt": 130,
    "rx 6750 xt": 135, "rx 6800 xt": 180, "rx 6800": 160, "rx 6900 xt": 190,
    "rx 6950 xt": 200, "rx 7600 xt": 115, "rx 7600": 110, "rx 7700 xt": 155,
    "rx 7800 xt": 185, "rx 7900 gre": 200, "rx 7900 xtx": 265, "rx 7900 xt": 235,
    "rx 9060 xt": 150, "rx 9070 gre": 190, "rx 9070 xt": 245, "rx 9070": 215,
    "arc a750": 95, "arc a770": 105, "arc b570": 100, "arc b580": 115,
    # older and integrated graphics
    "gtx 660": 18, "gtx 770": 25, "gtx 960": 35, "gtx 970": 45, "gtx 980": 55,
    "gtx 1050": 25, "gtx 1630": 22, "gtx 1650 super": 50, "gtx 1660 ti": 62,
    "rx 470": 45, "rx 480": 50, "rx 570": 47, "rx 5500 xt": 55, "rx 6400": 35,
    "rx 6500 xt": 40, "rx vega 56": 70,
    "uhd graphics": 12, "iris xe": 22, "radeon 680m": 35, "radeon 760m": 38,
    "radeon 780m": 45, "radeon 890m": 55, "arc graphics": 40,
}

# Cards currently on sale (September 2026).
# length_mm = shortest common models (bigger versions exist, so always check the exact card).
# eight_pin = PCIe 8-pin cables needed (directly or through the included adapter).
# sixteen = card uses the 12V-2x6 (16-pin) connector.
# price = typical street price estimate, USD (PC Gamer price tracking, Jul-Aug 2026).
GPU_CATALOG = [
    {"name": "Radeon RX 9060 XT 16GB", "score": 150, "vram": 16, "watts": 160, "psu": 550,
     "lanes": 16, "length_mm": 230, "eight_pin": 1, "sixteen": False, "price": 470},
    {"name": "GeForce RTX 5060 Ti 16GB", "score": 158, "vram": 16, "watts": 180, "psu": 550,
     "lanes": 8, "length_mm": 200, "eight_pin": 1, "sixteen": False, "price": 780},
    {"name": "Radeon RX 9070 GRE", "score": 190, "vram": 12, "watts": 220, "psu": 650,
     "lanes": 16, "length_mm": 250, "eight_pin": 2, "sixteen": False, "price": 500},
    {"name": "GeForce RTX 5070", "score": 195, "vram": 12, "watts": 250, "psu": 650,
     "lanes": 16, "length_mm": 230, "eight_pin": 2, "sixteen": False, "price": 763},
    {"name": "Radeon RX 9070", "score": 215, "vram": 16, "watts": 220, "psu": 650,
     "lanes": 16, "length_mm": 270, "eight_pin": 2, "sixteen": False, "price": 650},
    {"name": "Radeon RX 9070 XT", "score": 245, "vram": 16, "watts": 304, "psu": 750,
     "lanes": 16, "length_mm": 290, "eight_pin": 2, "sixteen": False, "price": 720},
    {"name": "GeForce RTX 5070 Ti", "score": 255, "vram": 16, "watts": 300, "psu": 750,
     "lanes": 16, "length_mm": 300, "eight_pin": 3, "sixteen": True, "price": 1088},
    {"name": "GeForce RTX 5080", "score": 295, "vram": 16, "watts": 360, "psu": 850,
     "lanes": 16, "length_mm": 304, "eight_pin": 3, "sixteen": True, "price": 1479},
    {"name": "GeForce RTX 5090", "score": 400, "vram": 32, "watts": 575, "psu": 1000,
     "lanes": 16, "length_mm": 304, "eight_pin": 4, "sixteen": True, "price": 4298},
]

def gpu_score(name):
    n = (name or "").lower()
    for key in sorted(GPU_SCORES, key=len, reverse=True):
        if re.search(r"\b" + re.escape(key) + r"\b", n):
            return GPU_SCORES[key]
    return None


# ----------------------------------------------------------------------------
# Memory kits
# ----------------------------------------------------------------------------
RAM_KITS = {
    ("DDR4", "DIMM", 16): ["Corsair Vengeance LPX 16GB (2x8GB) DDR4-3200 CL16",
                           "G.Skill Ripjaws V 16GB (2x8GB) DDR4-3600 CL16"],
    ("DDR5", "DIMM", 16): ["Crucial Pro 16GB (2x8GB) DDR5-6000 CL36"],
    ("DDR4", "SODIMM", 16): ["Crucial 16GB (2x8GB) DDR4-3200 SODIMM"],
    ("DDR5", "SODIMM", 16): ["Crucial 16GB (2x8GB) DDR5-5600 SODIMM"],
    ("DDR4", "DIMM", 32): ["G.Skill Ripjaws V 32GB (2x16GB) DDR4-3600 CL16",
                           "Corsair Vengeance LPX 32GB (2x16GB) DDR4-3600 CL18"],
    ("DDR4", "DIMM", 64): ["G.Skill Ripjaws V 64GB (2x32GB) DDR4-3600 CL18",
                           "Corsair Vengeance LPX 64GB (2x32GB) DDR4-3200 CL16"],
    ("DDR5", "DIMM", 32): ["G.Skill Flare X5 32GB (2x16GB) DDR5-6000 CL30",
                           "Corsair Vengeance 32GB (2x16GB) DDR5-6000 CL30"],
    ("DDR5", "DIMM", 64): ["G.Skill Trident Z5 64GB (2x32GB) DDR5-6000 CL30",
                           "Kingston Fury Beast 64GB (2x32GB) DDR5-6000 CL30"],
    ("DDR4", "SODIMM", 32): ["Crucial 32GB (2x16GB) DDR4-3200 SODIMM",
                             "Kingston Fury Impact 32GB (2x16GB) DDR4-3200 SODIMM"],
    ("DDR4", "SODIMM", 64): ["Crucial 64GB (2x32GB) DDR4-3200 SODIMM"],
    ("DDR5", "SODIMM", 32): ["Crucial 32GB (2x16GB) DDR5-5600 SODIMM",
                             "Kingston Fury Impact 32GB (2x16GB) DDR5-5600 SODIMM"],
    ("DDR5", "SODIMM", 64): ["Crucial 64GB (2x32GB) DDR5-5600 SODIMM"],
}
RAM_SWEET_SPOT = {"DDR4": "3200-3600 MHz", "DDR5": "6000 MHz"}


def rated_speed_from_part(part_number):
    """Many kits include their rated speed in the part number (e.g. F4-3600C16)."""
    m = re.search(r"(2400|2666|2800|3000|3200|3466|3600|3733|4000|4400|4800|5200|5600|"
                  r"6000|6200|6400|6800|7200|7600|8000)", part_number or "")
    return int(m.group(1)) if m else None


# ----------------------------------------------------------------------------
# SSDs
# ----------------------------------------------------------------------------
NVME_GEN4 = ["Samsung 990 Pro", "WD_Black SN850X", "Crucial T500"]
NVME_GEN4_VALUE = ["WD Blue SN5000", "Samsung 990 EVO Plus"]
NVME_GEN5 = ["Crucial T705", "Samsung 9100 Pro"]
SATA_SSD = ["Samsung 870 EVO", "Crucial MX500"]

# ----------------------------------------------------------------------------
# Prebuilt / OEM systems
# ----------------------------------------------------------------------------
OEM_VENDORS = ("hp", "hewlett", "dell", "alienware", "lenovo", "acer", "cyberpower",
               "ibuypower", "skytech", "medion", "fujitsu")


def chipset_from_board(product):
    m = re.search(r"\b([ABHXZQ]\d{3})[A-Z]?\b", (product or "").upper())
    return m.group(1) if m else None


# ----------------------------------------------------------------------------
# Price estimates (USD, September 2026). Used only by the budget planner, and
# every price can be edited in the app. RAM and SSD prices are unusually high
# in 2026 because of the memory shortage.
# ----------------------------------------------------------------------------
CPU_PRICES = {
    "Intel Core i7-9700K": 150, "Intel Core i9-9900K": 200,
    "Intel Core i9-10900K": 280, "Intel Core i7-11700K": 200, "Intel Core i9-11900K": 260,
    "Intel Core i5-14600K": 230, "Intel Core i7-14700F": 310, "Intel Core i7-14700K": 340,
    "Intel Core i9-14900F": 400, "Intel Core i9-14900K": 440,
    "Intel Core Ultra 7 265K": 300, "Intel Core Ultra 9 285K": 550,
    "AMD Ryzen 7 5700X3D": 240, "AMD Ryzen 7 5800X3D": 349, "AMD Ryzen 9 5900X": 280,
    "AMD Ryzen 9 5950X": 360, "AMD Ryzen 7 9700X": 300, "AMD Ryzen 7 9800X3D": 470,
    "AMD Ryzen 9 9900X": 380, "AMD Ryzen 9 9950X": 520, "AMD Ryzen 9 9950X3D": 680,
    "AMD Ryzen 5 9600X": 210, "B850 motherboard": 200, "X870 motherboard": 280,
}
RAM_PRICES = {  # (type, size GB) -> price
    ("DDR4", 16): 110, ("DDR4", 32): 200, ("DDR4", 64): 400,
    ("DDR5", 16): 230, ("DDR5", 32): 420, ("DDR5", 64): 850,
}
PSU_PRICES = {650: 90, 750: 110, 850: 130, 1000: 180}
SSD_PRICE_PER_TB = {
    "Samsung 990 Pro": 195, "WD_Black SN850X": 175, "Crucial T500": 165,
    "WD Blue SN5000": 135, "Samsung 990 EVO Plus": 145, "Crucial T705": 260,
    "Samsung 9100 Pro": 280, "Samsung 870 EVO": 170, "Crucial MX500": 155,
    "Samsung T9": 190, "Crucial X10": 180,
}


def estimate_price(name):
    """Best-effort price estimate for a part name, or None if unknown."""
    if name in CPU_PRICES:
        return CPU_PRICES[name]
    for g in GPU_CATALOG:
        if g["name"] == name:
            return g["price"]
    m = re.search(r"(\d+)GB \(\dx\d+GB\) (DDR\d)", name)
    if m:
        return RAM_PRICES.get((m.group(2), int(m.group(1))))
    m = re.search(r"(\d+)TB$", name)
    if m:
        base = name[:m.start()].strip()
        per_tb = SSD_PRICE_PER_TB.get(base)
        return per_tb * int(m.group(1)) if per_tb else None
    return None


# ----------------------------------------------------------------------------
# Used (resale) value estimates, USD, September 2026. Rough: local listings vary a
# lot, and the app lets you enter what you think you'll actually get.
# ----------------------------------------------------------------------------
USED_GPU = {
    "gtx 1060": 60, "gtx 1070": 80, "gtx 1080": 100, "gtx 1080 ti": 150, "gtx 1650": 70,
    "gtx 1660": 90, "gtx 1660 super": 100, "gtx 1660 ti": 100, "rtx 2060": 130, "rtx 2060 super": 150,
    "rtx 2070": 160, "rtx 2070 super": 190, "rtx 2080": 210, "rtx 2080 super": 230, "rtx 2080 ti": 280,
    "rtx 3050": 130, "rtx 3060": 200, "rtx 3060 ti": 230, "rtx 3070": 270, "rtx 3070 ti": 290,
    "rtx 3080": 360, "rtx 3080 ti": 420, "rtx 3090": 550, "rtx 4060": 240, "rtx 4060 ti": 300,
    "rtx 4070": 420, "rtx 4070 super": 480, "rtx 4070 ti": 520, "rtx 4070 ti super": 600,
    "rtx 4080": 800, "rtx 4080 super": 850, "rtx 4090": 1500,
    "rx 580": 60, "rx 5600 xt": 100, "rx 5700 xt": 140, "rx 6600": 150, "rx 6600 xt": 170,
    "rx 6650 xt": 180, "rx 6700 xt": 230, "rx 6750 xt": 250, "rx 6800": 300, "rx 6800 xt": 340,
    "rx 6900 xt": 380, "rx 7600": 200, "rx 7700 xt": 300, "rx 7800 xt": 380, "rx 7900 xt": 520,
    "rx 7900 xtx": 650, "arc a750": 130, "arc a770": 160, "arc b580": 220,
}
USED_CPU = {
    "8700K": 70, "9600K": 60, "9700K": 90, "9900K": 130, "10400": 60, "10600K": 80, "10700K": 120,
    "10900K": 170, "11400": 70, "11700K": 130, "12100": 60, "12400": 90, "12600K": 130, "12700": 170,
    "12700K": 180, "12900K": 220, "13400": 120, "13600K": 180, "13700K": 240, "13900K": 320,
    "14600K": 180, "14700K": 260, "1600": 30, "2600": 40, "3600": 60, "3700X": 80, "5600": 80,
    "5600X": 90, "5700X": 110, "5800X": 130, "5800X3D": 250, "5900X": 170, "5950X": 230,
    "7600": 140, "7600X": 150, "7700X": 200, "7800X3D": 330, "9600X": 170, "9700X": 230, "9800X3D": 400,
}
USED_RAM_FACTOR = 0.55  # used memory sells for roughly this share of the new price


def estimate_resale(hw, component):
    """(description, value) for the part a recommendation would replace, or None."""
    if component == "GPU":
        dedicated = [g for g in hw["gpu"] if not g["integrated"]]
        if not dedicated:
            return None
        g = max(dedicated, key=lambda g: gpu_score(g["name"]) or 0)
        n = g["name"].lower()
        for key in sorted(USED_GPU, key=len, reverse=True):
            if re.search(r"\b" + re.escape(key) + r"\b", n):
                return (g["name"], USED_GPU[key])
        return (g["name"], None)
    if component == "CPU":
        key = identify_cpu(hw["cpu"]["name"])[1]
        return (hw["cpu"]["name"], USED_CPU.get(key)) if key else None
    if component == "RAM":
        r = hw["ram"]
        full = r.get("slots_total") and len(r.get("modules") or []) >= r["slots_total"]
        if not full or not r.get("type") or not r.get("total_gb"):
            return None
        size = int(round(r["total_gb"]))
        new = RAM_PRICES.get((r["type"], size))
        return (f"{size} GB {r['type']} memory", round(new * USED_RAM_FACTOR) if new else None)
    return None
