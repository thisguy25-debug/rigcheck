"""
Farming Simulator 25 mod analyzer.

Finds problems that stop mods loading or slow the game down: bad file names, mods
packed the wrong way, RAR/7z archives, duplicates and older copies, Farming Sim 22
mods in the FS25 folder, mods a savegame needs but that are missing, and savegames
whose mod load is large for your graphics card's memory.
"""

import os
import re
import xml.etree.ElementTree as ET
import zipfile

import hw_advisor as hwa

VALID_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def documents_dir():
    """The real Documents folder (it's often moved into OneDrive on Windows)."""
    if hwa.SYSTEM == "Windows":
        try:
            import ctypes
            import uuid
            from ctypes import wintypes

            class GUID(ctypes.Structure):
                _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
                            ("Data3", wintypes.WORD), ("Data4", wintypes.BYTE * 8)]
            u = uuid.UUID("{FDD39AD0-238F-46AF-ADB4-6C85480369C7}")
            g = GUID(u.fields[0], u.fields[1], u.fields[2],
                     (wintypes.BYTE * 8).from_buffer_copy(u.bytes[8:]))
            p = ctypes.c_wchar_p()
            if ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(g), 0, None, ctypes.byref(p)) == 0:
                path = p.value
                ctypes.windll.ole32.CoTaskMemFree(p)
                return path
        except Exception:
            pass
    return os.path.join(os.path.expanduser("~"), "Documents")


def fs25_dir():
    return os.path.join(documents_dir(), "My Games", "FarmingSimulator2025")


def mods_dir():
    """The mods folder, honoring the game's 'mods folder override' setting."""
    base = fs25_dir()
    try:
        root = ET.parse(os.path.join(base, "game.xml")).getroot()
        o = root.find(".//modsDirectoryOverride")
        if o is not None and o.get("active") == "true" and o.get("directory"):
            return o.get("directory")
    except (OSError, ET.ParseError):
        pass
    return os.path.join(base, "mods")


def _folder_size(path):
    total = 0
    for dp, _dn, fns in os.walk(path):
        for f in fns:
            try:
                total += os.path.getsize(os.path.join(dp, f))
            except OSError:
                pass
    return total


def _version_tuple(v):
    return tuple(int(x) for x in re.findall(r"\d+", v or "0")) or (0,)


def _read_moddesc(data):
    root = ET.fromstring(data)
    title_el = root.find("title")
    title = None
    if title_el is not None:
        en = title_el.find("en")
        title = (en.text if en is not None else title_el.text) or None
        if not title:
            first = next(iter(title_el), None)
            title = first.text if first is not None else None
    maps = root.find("maps")
    return {"title": (title or "").strip() or None,
            "version": (root.findtext("version") or "").strip() or None,
            "author": (root.findtext("author") or "").strip() or None,
            "desc_version": root.get("descVersion"),
            "is_map": maps is not None and maps.find("map") is not None}


def _inspect(path):
    """One mod file or folder -> details and problems."""
    name = os.path.basename(path)
    is_dir = os.path.isdir(path)
    base = name if is_dir else os.path.splitext(name)[0]
    ext = "" if is_dir else os.path.splitext(name)[1].lower()
    mod = {"file": name, "path": path, "name": base, "size": 0, "title": None, "version": None,
           "author": None, "is_map": False, "problems": [], "loads": True}

    if ext in (".rar", ".7z"):
        mod["size"] = os.path.getsize(path)
        mod["problems"].append(f"{ext[1:].upper()} archive. The game only reads .zip files, so "
                               "extract it; inside is usually the real .zip to use.")
        mod["loads"] = False
        return mod
    if not is_dir and ext != ".zip":
        return None  # stray file (readme, image...), ignore

    try:
        if is_dir:
            mod["size"] = _folder_size(path)
            desc_path = os.path.join(path, "modDesc.xml")
            data = open(desc_path, "rb").read() if os.path.exists(desc_path) else None
            nested = None
        else:
            mod["size"] = os.path.getsize(path)
            with zipfile.ZipFile(path) as z:
                names = z.namelist()
                data = z.read("modDesc.xml") if "modDesc.xml" in names else None
                nested = next((n for n in names if n.lower().endswith("/moddesc.xml")), None)
                if data is None and not nested and any(n.lower().endswith(".zip") for n in names):
                    nested = "zip"
        if data is None:
            mod["loads"] = False
            if nested == "zip":
                mod["problems"].append("This .zip contains another .zip. Extract it and use the inner file.")
            elif nested:
                mod["problems"].append("Packed inside an extra folder, so the game can't find modDesc.xml. "
                                       "Re-zip the files from inside that folder.")
            else:
                mod["problems"].append("No modDesc.xml found. This isn't a working mod.")
        else:
            mod.update(_read_moddesc(data))
    except zipfile.BadZipFile:
        mod["loads"] = False
        mod["problems"].append("The .zip file is damaged. Download it again.")
    except ET.ParseError:
        mod["problems"].append("modDesc.xml has errors, so the mod may not load.")
    except OSError as e:
        mod["problems"].append(f"Couldn't read it ({e.strerror}).")

    if not VALID_NAME.match(base):
        mod["loads"] = False
        fixed = re.sub(r"\W+", "_", re.sub(r"\s*\(\d+\)$", "", base)).strip("_") or "FS25_mod"
        mod["problems"].append(f"The name has spaces, brackets or other symbols, which the game "
                               f"rejects. Rename it to something like {fixed}.zip (if it's a "
                               "duplicate download, delete it instead).")
    if re.match(r"FS(19|22)_", base, re.I):
        mod["loads"] = False
        mod["problems"].append("Looks like a mod for an older Farming Simulator. It won't work in FS25.")
    return mod


def _duplicates(mods):
    groups = {}
    for m in mods:
        if not m["title"]:
            continue
        key = (m["title"].lower(), (m["author"] or "").lower())
        groups.setdefault(key, []).append(m)
    for group in groups.values():
        if len(group) < 2:
            continue
        group.sort(key=lambda m: (_version_tuple(m["version"]), VALID_NAME.match(m["name"]) is not None),
                   reverse=True)
        keep = group[0]
        for m in group[1:]:
            if _version_tuple(m["version"]) < _version_tuple(keep["version"]):
                m["problems"].append(f"Older copy (v{m['version']}) of {keep['file']} (v{keep['version']}). "
                                     "Delete it to avoid conflicts.")
            else:
                m["problems"].append(f"Duplicate of {keep['file']}. Keep one.")


def _savegames(mod_sizes):
    saves = []
    base = fs25_dir()
    try:
        slots = sorted(d for d in os.listdir(base) if re.match(r"savegame\d+$", d))
    except OSError:
        return saves
    for slot in slots:
        path = os.path.join(base, slot, "careerSavegame.xml")
        try:
            root = ET.parse(path).getroot()
        except (OSError, ET.ParseError):
            continue
        name = root.findtext(".//savegameName") or slot
        active = [m.get("modName") for m in root.iter("mod") if m.get("modName")]
        missing = [a for a in active if a not in mod_sizes and not a.startswith("pdlc_")]
        total = sum(mod_sizes.get(a, 0) for a in active)
        saves.append({"slot": slot, "name": name, "mods": len(active), "bytes": total,
                      "missing": missing})
    return saves


def analyze(path=None, vram_gb=None, progress=None):
    path = path or mods_dir()
    result = {"path": path, "found": os.path.isdir(path), "mods": [], "total": 0, "savegames": [],
              "summary": []}
    if not result["found"]:
        return result
    entries = sorted(os.scandir(path), key=lambda e: e.name.lower())
    for i, e in enumerate(entries):
        if progress and i % 10 == 0:
            progress(f"Checking mod {i + 1} of {len(entries)}")
        m = _inspect(e.path)
        if m:
            result["mods"].append(m)
    _duplicates(result["mods"])
    result["total"] = sum(m["size"] for m in result["mods"])
    sizes = {m["name"]: m["size"] for m in result["mods"] if m["loads"]}
    result["savegames"] = _savegames(sizes)

    s = result["summary"]
    broken = [m for m in result["mods"] if not m["loads"]]
    warned = [m for m in result["mods"] if m["loads"] and m["problems"]]
    maps = [m for m in result["mods"] if m["is_map"]]
    if broken:
        s.append(("bad", f"{len(broken)} mod(s) won't load as they are."))
    if warned:
        s.append(("warn", f"{len(warned)} mod(s) have other problems (duplicates, old versions)."))
    if maps:
        s.append(("info", f"{len(maps)} map(s) installed. Maps are the biggest mods; only the one you "
                          "play loads, so unused maps just take up disk space."))
    for sg in result["savegames"]:
        if sg["missing"]:
            s.append(("warn", f"Savegame '{sg['name']}' uses {len(sg['missing'])} mod(s) that aren't in "
                              f"your mods folder: {', '.join(sg['missing'][:5])}"
                              + ("…" if len(sg["missing"]) > 5 else "")))
        if vram_gb and sg["bytes"] / 1024 ** 3 > vram_gb * 0.6:
            s.append(("warn", f"Savegame '{sg['name']}' loads {sg['bytes'] / 1024 ** 3:.1f} GB of mods. "
                              f"With {vram_gb:g} GB of video memory, expect stutter or texture pop-in; "
                              "lower texture quality or trim mods you don't use."))
    if not broken and not warned:
        s.append(("good", "No problems found with your mods."))
    return result
