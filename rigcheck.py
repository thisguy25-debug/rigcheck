#!/usr/bin/env python3
"""
RigCheck - find out what's in your PC, what's holding it back, and which upgrades fit.

Keep all the .py files in the same folder, then run:
    python rigcheck.py
"""

import contextlib
import datetime
import io
import json
import os
import re
import sys
import time
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog

try:
    import hw_advisor as hwa
    import hw_store
    import app_info
    import games_db
    import gui_common as gc
    from gui_common import (RichText, Meter, in_thread, make_tree, px, base_font, display_font,
                            number_font, BG, SIDEBAR, CARD, RAISED, TEXT, MUTED, ACCENT, COLORS,
                            PRIORITY_LABELS)
    import gui_tabs
except ImportError as e:
    root = tk.Tk()
    root.withdraw()
    messagebox.showerror("RigCheck", f"A program file is missing ({e.name}).\n\n"
                                     "Keep all of the RigCheck .py files in the same folder.")
    sys.exit(1)

PROFILE_LABELS = gc.PROFILE_LABELS
PROFILE_WORDS = {"general": "everyday use", "dev": "programming", "gaming": "gaming",
                 "creative": "creative work"}
STATUS_STYLE = {  # icon, label, color
    "ok": ("✓", "Compatible", COLORS["ok"]),
    "bios": ("✓", "Compatible after a BIOS update", COLORS["update"]),
    "check": ("!", "Check before buying", COLORS["update"]),
    "psu": ("!", "Needs a bigger power supply", COLORS["bad"]),
    "new": ("+", "Needs a new motherboard and RAM", COLORS["info"]),
}
PAGES = ["Monitor", "Overview", "Speed-ups", "Budget", "Disk space", "Health", "Performance", "Updates", "Games",
         "Share", "History", "Settings"]
PAGE_TITLES = {"Monitor": "Live monitor", "Speed-ups": "Free speed-ups", "Budget": "Budget planner"}
GUIDE_FOR = {"RAM": ("RAM", "How to install memory"), "Storage": ("Storage", "How to install an SSD"),
             "GPU": ("GPU", "How to install a graphics card"), "CPU": ("CPU", "How to install a processor"),
             "RAM speed": ("XMP", "Show me how to turn on XMP")}


# ----------------------------------------------------------------------------
# Text for the hardware panels
# ----------------------------------------------------------------------------
def short_cpu(name):
    n = re.sub(r"\(R\)|\(TM\)|\d+th Gen|CPU|Processor|@.*|\d+-Core", "", name or "")
    return re.sub(r"\s+", " ", n).strip() or "Unknown processor"


def short_gpu(name):
    return re.sub(r"^(NVIDIA|AMD|Intel\(R\))\s+", "", name or "").strip()


def hardware_lines(hw):
    b, c, r = hw.get("board") or {}, hw["cpu"], hw["ram"]
    board = []
    if b.get("oem") and b.get("system_model"):
        board.append(f"{b.get('system_vendor') or ''} {b['system_model']}".strip())
    if b.get("board_model"):
        board.append(f"{b.get('board_vendor') or ''} {b['board_model']}".strip())
    extra = [f"{b['chipset']} chipset" if b.get("chipset") else "", f"BIOS {b['bios']}" if b.get("bios") else ""]
    if any(extra):
        board.append(", ".join(x for x in extra if x))

    cpu = [short_cpu(c["name"]), f"{c['cores'] or '?'} cores, {c['threads'] or '?'} threads"]
    kind = " ".join(x for x in (r.get("type"), r.get("form")) if x)
    ram = [f"{r['total_gb'] or '?':g} GB {kind}".strip() if r["total_gb"] else "Unknown amount"]
    detail = []
    if r["modules"]:
        sizes = {m for m in r["modules"]}
        sticks = (f"{len(r['modules'])} × {r['modules'][0]:g} GB" if len(sizes) == 1
                  else " + ".join(f"{m:g} GB" for m in r["modules"]))
        detail.append(sticks + (f" in {r['slots_total']} slots" if r["slots_total"] else ""))
    speed = r.get("configured_mhz") or r.get("speed_mhz")
    if speed:
        detail.append(f"running at {speed} MHz")
    if detail:
        ram.append(gc.sentence(", ".join(detail)))

    storage = []
    for d in hw["storage"]["drives"]:
        size = d["size_gb"] or 0
        cap = f"{size / 1024:.1f} TB" if size >= 1000 else f"{size:.0f} GB"
        kind = {"HDD": "hard drive"}.get(d["type"], d["type"])
        storage.append(f"{d['name']} ({cap} {d.get('bus') or ''} {kind})".replace("  ", " "))
    sd = hw["storage"]["system_drive"]
    if sd:
        storage.append(f"{sd['free_gb']:.0f} GB free on the system drive ({sd['free_pct']:.0f}%)")

    gpus = [short_gpu(g["name"]) + (f", {g['vram_gb']:g} GB" if g["vram_gb"] else "")
            + (" (built into the CPU)" if g["integrated"] else "") for g in hw["gpu"]]
    system = [hw["os"]] + ([f"Computer name: {hw['pc_name']}"] if hw.get("pc_name") else [])
    return {"os": system, "board": board or ["Not detected"], "cpu": cpu, "ram": ram,
            "storage": storage or ["No drives detected"], "gpu": gpus or ["No graphics card detected"]}


def storage_summary(hw):
    parts = []
    for d in hw["storage"]["drives"]:
        if d.get("bus") == "USB":
            continue
        size = d["size_gb"] or 0
        cap = f"{size / 1024:.1f} TB" if size >= 1000 else f"{size:.0f} GB"
        kind = "hard drive" if d["type"] == "HDD" else f"{d.get('bus') or ''} SSD".strip()
        parts.append(f"{cap} {kind}")
    return " + ".join(parts) or "Unknown"


def component_ratings(hw, profile):
    """How well each part meets the chosen use, for the meters (1.0 = meets needs)."""
    parts_db = hwa.parts_db
    p = hwa.PROFILES[profile]
    items = []

    key = parts_db.identify_cpu(hw["cpu"]["name"])[1]
    sc = parts_db.cpu_score(key)
    target = {"gaming": 68, "creative": 95, "dev": 70, "general": 45}[profile]
    cores = hw["cpu"]["cores"] or hw["cpu"]["threads"]
    ratio = hwa._cpu_perf(sc, profile) / target if sc else (cores / p["cores"][1] if cores else None)
    items.append({"label": "Processor", "value": re.sub(r"^(Intel|AMD)\s+", "", short_cpu(hw["cpu"]["name"])),
                  "ratio": ratio})

    gpus = hw["gpu"]
    scores = [(parts_db.gpu_score(g["name"]), g) for g in gpus]
    rated = [s for s in scores if s[0]]
    target = {"gaming": 150, "creative": 150, "dev": 30, "general": 25}[profile]
    if rated:
        best = max(rated, key=lambda s: s[0])
        items.append({"label": "Graphics", "value": short_gpu(best[1]["name"]), "ratio": best[0] / target})
    else:
        items.append({"label": "Graphics", "value": short_gpu(gpus[0]["name"]) if gpus else "Not detected",
                      "ratio": None})

    r = hw["ram"]
    items.append({"label": "Memory", "value": f"{r['total_gb']:g} GB {r.get('type') or ''}".strip()
                  if r["total_gb"] else "Unknown", "ratio": r["total_gb"] / p["ram"][1] if r["total_gb"] else None})

    drives = [d for d in hw["storage"]["drives"] if d.get("bus") != "USB"]
    sd = hw["storage"]["system_drive"]
    if drives or sd:
        nvme = any(d.get("bus") == "NVMe" for d in drives)
        ssd = any(d["type"] == "SSD" for d in drives)
        ratio = 1.15 if nvme else 1.0 if ssd else 0.45
        note = None
        if sd and sd["free_pct"] < 10:
            ratio, note = min(ratio, 0.4), "Nearly full"
        elif sd and sd["free_pct"] < 20:
            ratio, note = min(ratio, 0.75), "Getting full"
        if drives and not ssd:
            note = "Slow hard drive"
        kind = "NVMe SSD" if nvme else "SATA SSD" if ssd else "Hard drive"
        value = f"{kind}, {sd['free_pct']:.0f}% free" if sd else kind
        items.append({"label": "Storage", "value": value, "ratio": ratio, "fixed_note": note})

    word = PROFILE_WORDS[profile]
    for it in items:
        rt = it["ratio"]
        it["status"] = "unknown" if rt is None else "good" if rt >= 0.98 else "warn" if rt >= 0.7 else "bad"
        it["note"] = it.pop("fixed_note", None) or {
            "unknown": "Couldn't rate", "good": f"Meets {word} needs",
            "warn": "Could be better", "bad": "Holding you back"}[it["status"]]
    weak = [it for it in items if it["ratio"] is not None and it["ratio"] < 0.98]
    if len(weak) > 1:
        weakest = min(weak, key=lambda it: it["ratio"])
        if weakest["note"] in ("Holding you back", "Could be better"):
            weakest["note"] = "Weakest part"
    return items


def scan_summary(hw):
    sd = hw["storage"]["system_drive"] or {}
    return {"CPU": hw["cpu"]["name"], "RAM (GB)": hw["ram"]["total_gb"],
            "RAM speed (MHz)": hw["ram"].get("configured_mhz"),
            "Graphics": ", ".join(g["name"] for g in hw["gpu"]),
            "Drives": ", ".join(f"{d['name']} {d['size_gb']:g} GB" for d in hw["storage"]["drives"]
                                if d["size_gb"]),
            "System drive free (GB)": sd.get("free_gb"), "BIOS": (hw.get("board") or {}).get("bios")}


# ----------------------------------------------------------------------------
# My setup dialog
# ----------------------------------------------------------------------------
class SetupDialog(tk.Toplevel):
    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self.title("My setup")
        self.configure(bg=BG)
        self.transient(app)
        gc.dark_title_bar(self)
        self.grab_set()
        s = app.settings
        f = ttk.Frame(self, padding=px(24))
        f.pack(fill="both", expand=True)
        ttk.Label(f, text="What RigCheck can't detect", style="Section.TLabel").grid(
            row=0, column=0, columnspan=2, sticky="w")
        ttk.Label(f, text="These let RigCheck confirm a graphics card will fit your case and get "
                          "enough power. Leave anything you don't know blank.",
                  style="Sub.TLabel", wraplength=px(480)).grid(row=1, column=0, columnspan=2,
                                                               sticky="w", pady=(px(4), px(14)))
        self.watts = tk.StringVar(value=s.get("psu_watts") or "")
        self.pins = tk.StringVar(value="" if s.get("psu_8pin") is None else str(s["psu_8pin"]))
        self.pin16 = tk.BooleanVar(value=bool(s.get("psu_16pin")))
        self.length = tk.StringVar(value=s.get("gpu_max_length_mm") or "")
        rows = [
            ("Power supply wattage", ttk.Entry(f, textvariable=self.watts, width=10),
             "Printed on the label on the side of the power supply, for example 650 W."),
            ("PCIe 8-pin GPU cables", ttk.Spinbox(f, from_=0, to=6, textvariable=self.pins, width=8),
             "Count the 6+2 pin cables labeled PCIe or VGA coming out of the power supply."),
            ("", ttk.Checkbutton(f, text="Has a 16-pin (12V-2x6 or 12VHPWR) GPU cable",
                                 variable=self.pin16), ""),
            ("Longest graphics card that fits (mm)", ttk.Entry(f, textvariable=self.length, width=10),
             "Measure from the back of the case, where the ports are, to the first thing in the "
             "way at the front, like drive cages or fans."),
        ]
        r = 2
        for label, widget, hint in rows:
            ttk.Label(f, text=label).grid(row=r, column=0, sticky="w", pady=(px(10), 0), padx=(0, px(16)))
            widget.grid(row=r, column=1, sticky="w", pady=(px(10), 0))
            if hint:
                ttk.Label(f, text=hint, style="Sub.TLabel", wraplength=px(480)).grid(
                    row=r + 1, column=0, columnspan=2, sticky="w")
            r += 2
        b = ttk.Frame(f)
        b.grid(row=r, column=0, columnspan=2, sticky="e", pady=(px(22), 0))
        ttk.Button(b, text="Cancel", command=self.destroy).pack(side="right")
        ttk.Button(b, text="Save setup", style="Accent.TButton", command=self.save).pack(
            side="right", padx=px(8))

    def save(self):
        def num(v):
            try:
                return int(float(v)) if str(v).strip() else None
            except ValueError:
                return None
        s = self.app.settings
        s["psu_watts"] = num(self.watts.get())
        s["psu_8pin"] = num(self.pins.get())
        s["psu_16pin"] = self.pin16.get()
        s["gpu_max_length_mm"] = num(self.length.get())
        self.app.save_settings()
        self.app.refresh_recommendations()
        self.app.set_status("Setup saved. Graphics card suggestions now check your power supply and case.")
        self.destroy()


# ----------------------------------------------------------------------------
# Sidebar
# ----------------------------------------------------------------------------
class NavItem(tk.Frame):
    SELECTED, HOVER = "#212834", "#1b212b"

    def __init__(self, parent, text, command):
        super().__init__(parent, bg=SIDEBAR, cursor="hand2")
        self.bar = tk.Frame(self, bg=SIDEBAR, width=px(3))
        self.bar.pack(side="left", fill="y")
        self.label = tk.Label(self, text=text, bg=SIDEBAR, fg=MUTED, font=base_font(11), anchor="w",
                              padx=px(18), pady=px(8))
        self.label.pack(side="left", fill="x", expand=True)
        self.selected = False
        for w in (self, self.label):
            w.bind("<Button-1>", lambda _e: command())
            w.bind("<Enter>", lambda _e: self._paint(hover=True))
            w.bind("<Leave>", lambda _e: self._paint())

    def set_selected(self, on):
        self.selected = on
        self._paint()

    def _paint(self, hover=False):
        bg = self.SELECTED if self.selected else self.HOVER if hover else SIDEBAR
        self.configure(bg=bg)
        self.label.configure(bg=bg, fg=TEXT if self.selected or hover else MUTED)
        self.bar.configure(bg=ACCENT if self.selected else bg)


def draw_logo(canvas, color):
    """A small four-bar meter, echoing the Overview meters."""
    for i, h in enumerate((8, 13, 18, 24)):
        x = px(2 + i * 7)
        canvas.create_rectangle(x, px(26 - h), x + px(5), px(26), fill=color, outline="")


# ----------------------------------------------------------------------------
# Main window
# ----------------------------------------------------------------------------
class AdvisorApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.settings = hw_store.load_settings()
        self.started_text_size = self.settings.get("text_size") or "Normal"
        gc.init_theme(self, self.started_text_size, self.settings.get("temp_unit") or "C")
        self.title("RigCheck")
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        self.geometry(f"{min(px(1200), sw - 40)}x{min(px(820), sh - 80)}")
        self.minsize(min(px(980), sw - 40), min(px(640), sh - 80))
        self.hw = None
        self.recs = []

        self._build_sidebar()
        self.main = ttk.Frame(self, padding=(px(28), px(20), px(28), px(20)))
        self.main.pack(side="left", fill="both", expand=True)
        self._build_topbar()
        self.notebook = ttk.Notebook(self.main, style="Pages.TNotebook")
        self.notebook.pack(fill="both", expand=True, pady=(px(14), 0))

        self.preview = None
        import gui_monitor
        self.monitor_tab = gui_monitor.MonitorTab(self.notebook, self)
        self.notebook.add(self.monitor_tab)
        self._build_overview()
        self.speedups_tab = gui_tabs.SpeedupsTab(self.notebook, self)
        self.notebook.add(self.speedups_tab)
        self._build_budget()
        self.disk_tab = gui_tabs.DiskTab(self.notebook, self)
        self.health_tab = gui_tabs.HealthTab(self.notebook, self)
        self.perf_tab = gui_tabs.PerformanceTab(self.notebook, self)
        self.updates_tab = gui_tabs.UpdatesTab(self.notebook, self)
        self.games_tab = gui_tabs.GamesTab(self.notebook, self)
        self.share_tab = gui_tabs.ShareTab(self.notebook, self)
        for tab in (self.disk_tab, self.health_tab, self.perf_tab, self.updates_tab, self.games_tab,
                    self.share_tab):
            self.notebook.add(tab)
        self._build_history()
        import gui_settings
        self.settings_tab = gui_settings.SettingsTab(self.notebook, self)
        self.notebook.add(self.settings_tab)
        start = self.settings.get("start_page") or "Overview"
        self.select_page(start if start in PAGES else "Overview")
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        gc.dark_title_bar(self)
        self.after(200, self.start_scan)
        self.after(1500, self.check_app_update)

    # ---------- shared helpers used by tabs ----------
    def set_status(self, text, base=False):
        if base:
            self.base_status = text
        self.status.configure(text=text)

    def save_settings(self):
        try:
            hw_store.save_settings(self.settings)
        except OSError as e:
            self.set_status(f"Settings weren't saved: {e}")

    def select_tab(self, index):
        self.notebook.select(index)
        for i, item in enumerate(self.nav):
            item.set_selected(i == index)
        name = PAGES[index]
        self.page_title.configure(text=PAGE_TITLES.get(name, name))
        if getattr(self, "base_status", None):
            self.status.configure(text=self.base_status)

    def restart(self):
        """Close and reopen RigCheck (used after changing text size or resetting settings)."""
        import subprocess
        if getattr(sys, "frozen", False):
            cmd = [sys.executable]
        else:
            cmd = [sys.executable, os.path.abspath(sys.argv[0])]
        try:
            subprocess.Popen(cmd, creationflags=hwa.NO_WINDOW, stdin=subprocess.DEVNULL,
                             close_fds=True)
        except OSError as e:
            messagebox.showerror("RigCheck", f"RigCheck couldn't restart itself. Please reopen it.\n\n{e}")
        self.on_close()

    def select_page(self, name):
        self.select_tab(PAGES.index(name))

    def set_speedup_count(self, n):
        self.nav[PAGES.index("Speed-ups")].label.configure(text=f"Speed-ups   {n}" if n else "Speed-ups")

    def open_guide(self, key):
        gui_tabs.GuideDialog(self, key)

    def profile_label(self):
        return PROFILE_LABELS[self.current_profile()]

    def make_snapshot(self, name):
        import share
        profile = self.current_profile()
        lines = hardware_lines(self.hw)
        specs = {"Processor": lines["cpu"][0], "Graphics": lines["gpu"][0], "Memory": lines["ram"][0],
                 "Storage": storage_summary(self.hw), "System": self.hw["os"]}
        scores = games_db.system_scores(self.hw)
        games = []
        for g in games_db.GAMES:
            r = games_db.check_game(g, scores)
            games.append({"name": g["name"], "short": r["short"], "level": r["level"],
                          "rank": r["level"] * 2 + r["short"].startswith("Runs great")})
        return share.snapshot(name, profile, specs, component_ratings(self.hw, profile), scores, games)

    # ---------- app updates ----------
    def check_app_update(self):
        """Look for a newer release on GitHub at startup and every 4 hours while open."""
        if not app_info.UPDATE_REPO:
            return
        self.after(4 * 3600 * 1000, self.check_app_update)
        if not self.settings.get("auto_update_check", True):
            return
        if getattr(self, "_update_banner", None):
            return  # already showing one

        def done(new, err):
            if err:
                return  # offline or GitHub busy: try again next time
            self.settings["last_update_check"] = time.time()
            self.save_settings()
            if new:
                self.show_update_banner(new)
        in_thread(self, app_info.check_for_update, done)

    def show_update_banner(self, new):
        import webbrowser
        bar = tk.Frame(self.main, bg=gc.ACCENT_DIM)
        bar.pack(fill="x", before=self.notebook, pady=(px(12), 0))
        self._update_banner = bar
        tk.Label(bar, text=f"RigCheck {new['version']} is available.", bg=gc.ACCENT_DIM, fg=TEXT,
                 font=base_font(10, "bold"), padx=px(14), pady=px(8)).pack(side="left")
        ttk.Button(bar, text="Download", style="Accent.TButton",
                   command=lambda: webbrowser.open(new["url"])).pack(side="left")
        close = tk.Label(bar, text="Not now", bg=gc.ACCENT_DIM, fg=MUTED, cursor="hand2", padx=px(14))
        close.pack(side="right")
        close.bind("<Button-1>", lambda _e: (bar.destroy(), setattr(self, "_update_banner", None)))

    def current_profile(self):
        label = self.profile_box.get()
        return next(k for k, v in PROFILE_LABELS.items() if v == label)

    def on_close(self):
        if self.perf_tab.monitor:
            self.perf_tab.monitor.stop()
        self.monitor_tab.stop()
        self.destroy()

    # ---------- sidebar and top bar ----------
    def _build_sidebar(self):
        side = tk.Frame(self, bg=SIDEBAR, width=px(220))
        side.pack(side="left", fill="y")
        side.pack_propagate(False)
        brand = tk.Frame(side, bg=SIDEBAR)
        brand.pack(fill="x", padx=px(22), pady=(px(26), px(28)))
        logo = tk.Canvas(brand, width=px(30), height=px(28), bg=SIDEBAR, highlightthickness=0)
        logo.pack(side="left")
        draw_logo(logo, ACCENT)
        tk.Label(brand, text="RigCheck", bg=SIDEBAR, fg=TEXT, font=display_font(19)).pack(
            side="left", padx=(px(8), 0))

        self.nav = [NavItem(side, name, lambda i=i: self.select_tab(i)) for i, name in enumerate(PAGES)]
        for item in self.nav:
            item.pack(fill="x")

        foot = tk.Frame(side, bg=SIDEBAR)
        foot.pack(side="bottom", fill="x", padx=px(22), pady=px(22))
        tk.Label(foot, text=f"Version {app_info.APP_VERSION}", bg=SIDEBAR, fg=MUTED,
                 font=base_font(8)).pack(side="bottom", anchor="w", pady=(px(14), 0))
        tk.Label(foot, text="I use this PC for", bg=SIDEBAR, fg=MUTED, font=base_font(9)).pack(anchor="w")
        self.profile_box = ttk.Combobox(foot, state="readonly", values=list(PROFILE_LABELS.values()))
        self.profile_box.set(PROFILE_LABELS.get(self.settings.get("profile"), "Gaming"))
        self.profile_box.pack(fill="x", pady=(px(6), 0))
        self.profile_box.bind("<<ComboboxSelected>>", self.on_profile_change)

    def _build_topbar(self):
        top = ttk.Frame(self.main)
        top.pack(fill="x")
        actions = ttk.Frame(top)
        actions.pack(side="right", anchor="n")  # packed first so long status text never squeezes it
        titles = ttk.Frame(top)
        titles.pack(side="left", fill="x", expand=True)
        self.page_title = ttk.Label(titles, text="Overview", style="Title.TLabel")
        self.page_title.pack(anchor="w")
        self.status = ttk.Label(titles, text="Getting ready…", style="Sub.TLabel", wraplength=px(560))
        self.status.pack(anchor="w", pady=(px(2), 0))
        self.export_btn = ttk.Button(actions, text="Save report", command=self.export_report,
                                     state="disabled")
        self.export_btn.pack(side="right")
        ttk.Button(actions, text="My setup", command=lambda: SetupDialog(self)).pack(side="right", padx=px(8))
        self.scan_btn = ttk.Button(actions, text="Scan again", style="Accent.TButton", width=12,
                                   command=self.start_scan)
        self.scan_btn.pack(side="right")
        slot = ttk.Frame(self.main, height=px(3))
        slot.pack(fill="x", pady=(px(12), 0))
        slot.pack_propagate(False)
        self.progress = ttk.Progressbar(slot, mode="indeterminate")

    # ---------- overview ----------
    def _build_overview(self):
        tab = ttk.Frame(self.notebook)
        self.notebook.add(tab)
        self.meter = Meter(tab)
        self.meter.pack(fill="x")
        self.preview_bar = tk.Frame(tab, bg=gc.ACCENT_DIM)
        self.preview_text = tk.Label(self.preview_bar, bg=gc.ACCENT_DIM, fg=TEXT, font=base_font(10),
                                     justify="left", anchor="w", padx=px(14), pady=px(10),
                                     wraplength=px(760))
        self.preview_text.pack(side="left", fill="x", expand=True)
        ttk.Button(self.preview_bar, text="Stop preview", command=self.stop_preview).pack(
            side="right", padx=px(10))
        body = ttk.Frame(tab)
        body.pack(fill="both", expand=True, pady=(px(22), 0))
        body.columnconfigure(0, weight=2, uniform="c")
        body.columnconfigure(1, weight=3, uniform="c")
        body.rowconfigure(1, weight=1)
        ttk.Label(body, text="Your hardware", style="Section.TLabel").grid(row=0, column=0, sticky="w",
                                                                           pady=(0, px(10)))
        left = ttk.Frame(body, style="Card.TFrame", padding=(px(18), px(12)))
        left.grid(row=1, column=0, sticky="nsew", padx=(0, px(16)))
        self.cards = {}
        for key, title in [("cpu", "Processor"), ("gpu", "Graphics"), ("ram", "Memory"),
                           ("storage", "Storage"), ("board", "Motherboard"), ("os", "System")]:
            ttk.Label(left, text=title, style="CardTitle.TLabel").pack(anchor="w", pady=(px(8), 0))
            lbl = ttk.Label(left, text="…", style="CardBody.TLabel", justify="left", wraplength=px(320))
            lbl.pack(anchor="w", fill="x", pady=(px(2), px(4)))
            self.cards[key] = lbl
        left.bind("<Configure>", lambda e: [l.configure(wraplength=max(px(200), e.width - px(40)))
                                            for l in self.cards.values()])
        head = ttk.Frame(body)
        head.grid(row=0, column=1, sticky="ew", pady=(0, px(10)))
        ttk.Label(head, text="Upgrades", style="Section.TLabel").pack(side="left")
        self.summary = ttk.Label(head, text="", style="Sub.TLabel")
        self.summary.pack(side="right")
        self.rec_out = RichText(body)
        self.rec_out.grid(row=1, column=1, sticky="nsew")

    # ---------- scanning ----------
    def start_scan(self):
        self.scan_btn.configure(state="disabled")
        self.export_btn.configure(state="disabled")
        self.set_status("Scanning your hardware. This takes a few seconds.")
        self.progress.pack(fill="both", expand=True)
        self.progress.start(12)
        in_thread(self, hwa.detect_all, self._scan_done)

    def _scan_done(self, hw, err):
        self.progress.stop()
        self.progress.pack_forget()
        self.scan_btn.configure(state="normal")
        if err:
            self.set_status("The scan didn't finish.")
            messagebox.showerror("RigCheck", f"The hardware scan stopped with an error:\n\n{err}")
            return
        self.hw = hw
        self.export_btn.configure(state="normal")
        when = datetime.datetime.now().strftime("%I:%M %p").lstrip("0")
        admin = "" if hwa.SYSTEM != "Windows" or hwa.is_admin() else \
            " Some checks show more detail when RigCheck runs as administrator."
        pc = f", {hw['pc_name']}," if hw.get("pc_name") else ""
        self.set_status(f"Scanned this PC{pc} at {when}.{admin}", base=True)
        for key, lines in hardware_lines(hw).items():
            self.cards[key].configure(text="\n".join(lines))
        self.refresh_recommendations()
        self.games_tab.refresh()
        self.speedups_tab.check()
        self.share_tab.refresh()
        self.monitor_tab.hw_ready()
        self._record_scan()

    def _record_scan(self):
        summary = scan_summary(self.hw)
        scans = [h for h in hw_store.load_history() if h["kind"] == "scan"]
        if not scans or scans[-1]["data"] != summary or time.time() - scans[-1]["time"] > 7 * 86400:
            hw_store.add_history("scan", summary)
        self.refresh_history()

    def on_profile_change(self, _e=None):
        self.settings["profile"] = self.current_profile()
        self.save_settings()
        self.refresh_recommendations()
        self.games_tab.refresh()

    # ---------- recommendations ----------
    def refresh_recommendations(self):
        if not self.hw:
            return
        profile = self.current_profile()
        self.recs = hwa.recommend(self.hw, profile, self.settings)
        self.stop_preview()
        self._render_recs()
        self._render_budget()

    def _render_recs(self):
        profile = self.current_profile()
        counts = [(PRIORITY_LABELS[p].lower(), sum(r["priority"] == p for r in self.recs))
                  for p in ("FREE", "HIGH", "MEDIUM", "LOW")]
        self.summary.configure(text=", ".join(f"{n} {label}" for label, n in counts if n).capitalize())
        o = self.rec_out
        o.clear()
        if not self.recs:
            o.colored("Nothing to upgrade.\n", "good")
            o.write(f"This PC is well matched for {PROFILE_WORDS[profile]}.\n", "muted")
        elif any(r["parts"] for r in self.recs):
            o.write("Click a part to compare prices, or Preview to see what it would change.\n", "small")
            o.write("\n", "gap")
        for rec in self.recs:
            o.badge(PRIORITY_LABELS[rec["priority"]], rec["priority"])
            o.write(f"  {rec['component']}\n", "h2")
            o.write(rec["issue"] + "\n", "bold")
            o.write(rec["advice"] + "\n", "muted")
            if rec["parts"]:
                o.write("\n", "gap")
                for part in rec["parts"]:
                    icon, label, color = STATUS_STYLE[part["status"]]
                    o.colored(f"{icon}  ", color)
                    o.link(part["name"], part["url"], ("boldlink",))
                    if part.get("price"):
                        o.write(f"   ${part['price']:,}", "muted")
                    if part["status"] != "new" and rec["component"] in ("GPU", "CPU", "RAM", "Storage"):
                        o.write("   ")
                        o.link("Preview", lambda c=rec["component"], n=part["name"]: self.start_preview(c, n),
                               ("smalllink",))
                    o.write("\n")
                    self._part_note(o, label, color, part)
            if rec["component"] in GUIDE_FOR:
                key, label = GUIDE_FOR[rec["component"]]
                o.write("\n", "gap")
                o.link(label, lambda k=key: self.open_guide(k))
                o.write("\n")
            for link in rec["links"]:
                o.write("\n", "gap")
                o.link(link["label"], link["url"])
                o.write("\n")
            o.rule()
        checks = hwa.buying_checks(self.hw, self.recs)
        if checks:
            o.write("Before you buy\n", "h2")
            for c in checks:
                o.write(f"•  {c}\n", "muted")
        o.write(f"\nPrices are estimates from {hwa.parts_db.DB_DATE} and change daily. "
                "Plan a budget on the Budget page.\n", "small")
        o.done()

    @staticmethod
    def _part_note(o, label, color, part):
        tag = o._color_tag(color, False)
        o.text.tag_configure(tag + "_small", foreground=color, font=base_font(9, "bold"),
                             lmargin1=px(26), lmargin2=px(26))
        note = part["note"] + (f"; {part['extra_note']}" if part.get("extra_note") else "")
        o.write(label + (". " if note else ""), tag + "_small")
        o.write((note + "\n") if note else "\n", "indent")

    # ---------- upgrade preview ----------
    def start_preview(self, component, part_name):
        profile = self.current_profile()
        new_hw = hwa.simulate_upgrade(self.hw, component, part_name)
        before = component_ratings(self.hw, profile)
        self.meter.set(component_ratings(new_hw, profile), before=before)
        s0, s1 = games_db.system_scores(self.hw), games_db.system_scores(new_hw)
        changes = []
        for g in games_db.GAMES:
            a, b = games_db.check_game(g, s0), games_db.check_game(g, s1)
            if (b["level"], b["short"]) != (a["level"], a["short"]) and b["level"] >= a["level"]:
                changes.append(f"{g['name']} ({a['short'].split(',')[0].lower()} to "
                               f"{b['short'].split(',')[0].lower()})")
        text = f"Previewing {part_name}. "
        if changes:
            text += f"{len(changes)} game{'s' if len(changes) != 1 else ''} would improve: " + \
                    ", ".join(changes[:4]) + (", and more." if len(changes) > 4 else ".")
        else:
            text += "None of the listed games would change level, though frame rates would still rise " \
                    "where this part was the limit." if component in ("GPU", "CPU") else ""
        if component == "Storage":
            text += " This assumes you move your games onto the new drive."
        if component == "GPU":
            cpu = hwa.parts_db.cpu_score(hwa.parts_db.identify_cpu(self.hw["cpu"]["name"])[1])
            est = hwa.estimated_cpu_bottleneck(cpu[0] if cpu else None, s1["gpu"])
            if est is not None:
                text += (f" Estimated processor bottleneck with this card: {est:.0%} at 1440p."
                         if est >= 0.05 else " Your processor can keep this card fully fed.")
        self.preview_text.configure(text=text)
        self.preview_bar.pack(fill="x", pady=(px(12), 0), after=self.meter)
        self.preview = (component, part_name)

    def stop_preview(self):
        self.preview = None
        self.preview_bar.pack_forget()
        if self.hw:
            self.meter.set(component_ratings(self.hw, self.current_profile()))

    # ---------- budget ----------
    def _build_budget(self):
        tab = ttk.Frame(self.notebook)
        self.notebook.add(tab)
        bar = ttk.Frame(tab)
        bar.pack(fill="x", pady=(0, px(6)))
        ttk.Label(bar, text="Budget  $").pack(side="left")
        self.budget_var = tk.StringVar(value=str(self.settings.get("budget", 800)))
        e = ttk.Entry(bar, textvariable=self.budget_var, width=8, font=number_font(12))
        e.pack(side="left")
        e.bind("<Return>", lambda _e: self._render_budget(save=True))
        ttk.Button(bar, text="Plan upgrades", style="Accent.TButton",
                   command=lambda: self._render_budget(save=True)).pack(side="left", padx=px(10))
        ttk.Button(bar, text="Reset prices", command=self._reset_prices).pack(side="right")
        self.sell_var = tk.BooleanVar(value=bool(self.settings.get("sell_old_parts", False)))
        ttk.Checkbutton(bar, text="Count money from selling the parts I replace", variable=self.sell_var,
                        command=lambda: self._render_budget(save=True)).pack(side="left", padx=px(14))
        ttk.Label(tab, text="Prices are estimates. Memory and SSD prices are unusually high in 2026 "
                            "because of a memory shortage, so double-click a price to enter what you "
                            "see in stores.", style="Sub.TLabel", wraplength=px(900)).pack(
            anchor="w", pady=(px(4), px(14)))
        body = ttk.Frame(tab)
        body.pack(fill="both", expand=True)
        body.columnconfigure(0, weight=1, minsize=px(480))
        body.columnconfigure(1, weight=1)
        body.rowconfigure(0, weight=1)
        frame, self.price_tree = make_tree(body, ["Part", "Component", "Price"], [220, 100, 100], 18)
        frame.grid(row=0, column=0, sticky="nsew", padx=(0, px(16)))
        self.price_tree.bind("<Double-1>", self._edit_price)
        self.plan_out = RichText(body)
        self.plan_out.grid(row=0, column=1, sticky="nsew")

    def _render_budget(self, save=False):
        try:
            budget = int(float(self.budget_var.get()))
        except ValueError:
            budget = self.settings.get("budget", 800)
        if save:
            self.settings["budget"] = budget
            self.settings["sell_old_parts"] = self.sell_var.get()
            self.save_settings()
        resale = self._resale() if self.sell_var.get() else {}
        t = self.price_tree
        t.delete(*t.get_children())
        seen = set()
        for rec in self.recs:
            for p in rec["parts"]:
                if p["name"] in seen:
                    continue
                seen.add(p["name"])
                edited = p["name"] in (self.settings.get("price_overrides") or {})
                price = (f"${p['price']:,}" + (" (yours)" if edited else "")) if p.get("price") else "?"
                t.insert("", "end", iid=p["name"], text=p["name"], values=(rec["component"], price),
                         tags=("odd",) if len(seen) % 2 == 0 else ())
        if self.hw:
            for comp, (desc, value) in self._resale(include_unknown=True).items():
                t.insert("", "end", iid=f"sell:{comp}", text=f"Sell your {desc}",
                         values=("Resale", f"+${value:,}" if value else "enter value"))
        o = self.plan_out
        o.clear()
        if not self.hw:
            o.done()
            return
        plans = hwa.plan_budget(self.recs, budget, {c: v[1] for c, v in resale.items()})
        o.write(f"${budget:,}", "h1")
        o.write("  best use of your budget\n", "muted")
        if not plans:
            cheapest = min((p["price"] for r in self.recs for p in r["parts"] if p.get("price")), default=None)
            o.write("Nothing on the list fits this budget." +
                    (f" The cheapest suggested part is about ${cheapest:,}." if cheapest else "") + "\n",
                    "muted")
        for i, plan in enumerate(plans):
            o.write("\n", "gap")
            o.write(("Best plan" if i == 0 else f"Alternative {i}") + "\n", "h2")
            for pick in plan["picks"]:
                for p in pick["parts"]:
                    o.write(f"{pick['component']}  ", "muted")
                    o.link(p["name"], p["url"], ("boldlink",))
                    o.write(f"   ${p['price']:,}\n", "muted")
                    if pick.get("resale"):
                        o.write(f"After selling your old part for about ${pick['resale']:,}, this costs "
                                f"about ${pick['cost']:,}.\n", "indent")
                    if p.get("extra_cost"):
                        o.write(f"Plus a {p['extra_note'][2:]} (about ${p['extra_cost']:,}), because "
                                "your current power supply isn't enough for this card.\n", "indent")
            sold = sum(p.get("resale") or 0 for p in plan["picks"])
            o.write(f"Total about ${plan['total']:,}" + (" after selling old parts" if sold else "")
                    + f", leaving ${plan['leftover']:,}\n", "muted")
        free = [r for r in self.recs if r["priority"] == "FREE"]
        if free:
            o.write("\nDo the free fixes first: ", "bold")
            o.write(", ".join(r["component"] for r in free) + " (see Overview).\n")
        o.write("\nPlans fix urgent problems first, then add the most performance per dollar.\n", "small")
        o.done()

    def _resale(self, include_unknown=False):
        """{component: (description, value)} for parts the current plan could replace."""
        out = {}
        overrides = self.settings.get("resale_overrides") or {}
        comps = {r["component"] for r in self.recs if r["parts"]}
        for comp in ("GPU", "CPU", "RAM"):
            if comp not in comps:
                continue
            est = hwa.parts_db.estimate_resale(self.hw, comp)
            if not est:
                continue
            desc = short_gpu(est[0]) if comp == "GPU" else short_cpu(est[0]) if comp == "CPU" else est[0]
            value = overrides.get(comp, est[1])
            if value or include_unknown:
                out[comp] = (desc, value)
        return out

    def _edit_price(self, _e=None):
        sel = self.price_tree.selection()
        if not sel:
            return
        name = sel[0]
        if name.startswith("sell:"):
            comp = name[5:]
            current = self._resale(include_unknown=True).get(comp, (None, 0))[1]
            val = simpledialog.askinteger("Resale value", "What do you expect to get for it?",
                                          initialvalue=current or 0, minvalue=0, parent=self)
            if val is not None:
                self.settings.setdefault("resale_overrides", {})[comp] = val
                self.save_settings()
                self._render_budget()
            return
        current = next((p["price"] for r in self.recs for p in r["parts"] if p["name"] == name), None)
        val = simpledialog.askinteger("Edit price", f"Price you see for\n{name}",
                                      initialvalue=current or 0, minvalue=0, parent=self)
        if val is None:
            return
        self.settings.setdefault("price_overrides", {})[name] = val
        self.save_settings()
        self.refresh_recommendations()

    def _reset_prices(self):
        self.settings["price_overrides"] = {}
        self.settings["resale_overrides"] = {}
        self.save_settings()
        self.refresh_recommendations()

    # ---------- history ----------
    def _build_history(self):
        tab = ttk.Frame(self.notebook)
        self.notebook.add(tab)
        bar = ttk.Frame(tab)
        bar.pack(fill="x", pady=(0, px(12)))
        ttk.Button(bar, text="Compare", style="Accent.TButton", command=self.compare_history).pack(side="left")
        ttk.Button(bar, text="Delete", command=self.delete_history).pack(side="left", padx=px(8))
        ttk.Label(bar, text="Hold Ctrl and select two entries of the same type to compare them.",
                  style="Sub.TLabel").pack(side="left", padx=px(10))
        panes = ttk.PanedWindow(tab, orient="vertical")
        panes.pack(fill="both", expand=True)
        frame, self.hist_tree = make_tree(panes, ["When", "Type", "Summary"], [170, 110, 700], 10)
        self.hist_out = RichText(panes, height=10)
        panes.add(frame, weight=1)
        panes.add(self.hist_out, weight=1)

    def refresh_history(self):
        t = self.hist_tree
        t.delete(*t.get_children())
        for n, (i, h) in enumerate(reversed(list(enumerate(hw_store.load_history())))):
            when = datetime.datetime.fromtimestamp(h["time"]).strftime("%b %d, %Y  %I:%M %p")
            d = h["data"]
            if h["kind"] == "scan":
                summ = (f"{d.get('RAM (GB)')} GB RAM at {d.get('RAM speed (MHz)')} MHz, "
                        f"{d.get('Graphics')}, {d.get('System drive free (GB)')} GB free")
            elif h["kind"] == "benchmark":
                summ = (f"CPU {d['cpu']['single_mbs']:,} / {d['cpu']['multi_mbs']:,} MB/s, "
                        f"memory {d['ram']['copy_gbs']} GB/s")
            else:
                pct = d.get("pct_gpu") if d.get("bottleneck") == "GPU" else d.get("pct_cpu") \
                    if d.get("bottleneck") == "CPU" else None
                who = {"GPU": "graphics card", "CPU": "processor"}.get(d.get("bottleneck"), "neither part")
                summ = f"{d.get('label')}: limit was the {who}" + (f" {pct:.0f}% of the time" if pct else "") \
                    + f" ({d.get('minutes')} min)"
            t.insert("", "end", iid=str(i), text=when, values=(h["kind"].title(), summ),
                     tags=("odd",) if n % 2 else ())

    @staticmethod
    def _flatten(kind, d):
        if kind == "benchmark":
            out = {"CPU single-core (MB/s)": d["cpu"]["single_mbs"],
                   "CPU all cores (MB/s)": d["cpu"]["multi_mbs"],
                   "Memory copy (GB/s)": d["ram"]["copy_gbs"]}
            for disk in d.get("disks", []):
                if not disk.get("skipped"):
                    out[f"Drive {disk['drive']} write (MB/s)"] = disk.get("write_mbs")
                    out[f"Drive {disk['drive']} read (MB/s)"] = disk.get("read_mbs")
            return out
        if kind == "monitor":
            return {"Test": d.get("label"), "Limited by": d.get("bottleneck"),
                    "Graphics card was the limit %": round(d["pct_gpu"]) if d.get("pct_gpu") is not None else None,
                    "Processor was the limit %": round(d["pct_cpu"]) if d.get("pct_cpu") is not None else None,
                    "Graphics power unused %": round(d["lost_gpu"]) if d.get("lost_gpu") is not None else None,
                    "Average CPU %": round(d["avg_cpu"]) if d.get("avg_cpu") else None,
                    "Average busiest core %": round(d["avg_core_max"]) if d.get("avg_core_max") else None,
                    "Average GPU %": round(d["avg_gpu"]) if d.get("avg_gpu") else None,
                    "Average RAM %": round(d["avg_ram"]) if d.get("avg_ram") else None}
        return d

    def compare_history(self):
        sel = sorted(int(i) for i in self.hist_tree.selection())
        hist = hw_store.load_history()
        o = self.hist_out
        o.clear()
        if len(sel) != 2 or hist[sel[0]]["kind"] != hist[sel[1]]["kind"]:
            o.write("Select exactly two entries of the same type.\n", "muted")
            o.done()
            return
        a, b = hist[sel[0]], hist[sel[1]]
        fa, fb = self._flatten(a["kind"], a["data"]), self._flatten(b["kind"], b["data"])
        ta = datetime.datetime.fromtimestamp(a["time"]).strftime("%b %d")
        tb = datetime.datetime.fromtimestamp(b["time"]).strftime("%b %d")
        o.write(f"{a['kind'].title()}s from {ta} and {tb}\n", "h1")
        for key in list(dict.fromkeys(list(fa) + list(fb))):
            va, vb = fa.get(key), fb.get(key)
            o.write(f"{key}\n", "label")
            o.write(f"{va}", "muted")
            o.write("  to  ", "small")
            o.write(f"{vb}")
            if isinstance(va, (int, float)) and isinstance(vb, (int, float)) and va:
                ch = vb / va - 1
                if abs(ch) >= 0.005:
                    o.colored(f"   {'+' if ch > 0 else ''}{ch:.0%}", "good" if ch > 0 else "bad")
            elif va != vb:
                o.colored("   changed", "info")
            o.write("\n")
            o.write("\n", "gap")
        o.done()

    def delete_history(self):
        sel = [int(i) for i in self.hist_tree.selection()]
        if sel and messagebox.askyesno("History", f"Delete {len(sel)} entr{'y' if len(sel) == 1 else 'ies'}?"):
            hw_store.delete_history(sel)
            self.refresh_history()

    # ---------- export ----------
    def export_report(self):
        if not self.hw:
            return
        path = filedialog.asksaveasfilename(title="Save report", defaultextension=".txt",
                                            initialfile="rigcheck_report.txt",
                                            filetypes=[("Text report", "*.txt"), ("JSON data", "*.json")])
        if not path:
            return
        profile = self.current_profile()
        try:
            if path.lower().endswith(".json"):
                data = json.dumps({"profile": profile, "hardware": self.hw, "recommendations": self.recs,
                                   "before_you_buy": hwa.buying_checks(self.hw, self.recs)}, indent=2)
            else:
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf):
                    hwa.print_report(self.hw, self.recs, profile)
                data = buf.getvalue()
            with open(path, "w", encoding="utf-8") as f:
                f.write(data)
            self.set_status(f"Report saved to {path}")
        except OSError as e:
            messagebox.showerror("RigCheck", f"The report wasn't saved:\n\n{e}")


if __name__ == "__main__":
    gc.enable_sharp_text()
    AdvisorApp().mainloop()
