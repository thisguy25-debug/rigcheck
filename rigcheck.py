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
PAGES = ["Monitor", "Overview", "Games", "Health", "Performance", "Updates", "Share", "History", "Settings"]
PAGE_TITLES = {"Monitor": "Live monitor", "Games": "Game storage"}
PROFILE = "gaming"  # RigCheck judges hardware for gaming
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
    SELECTED, HOVER = gc.NAV_SELECTED, gc.NAV_HOVER

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
        self.started_theme = self.settings.get("theme") or "dark"
        gc.init_theme(self, self.started_text_size, self.settings.get("temp_unit") or "C")
        self.title("RigCheck")
        gc.apply_window_icon(self)
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
        import gui_games
        self.games_tab = gui_games.GamesTab(self.notebook, self)
        self.notebook.add(self.games_tab)
        self.health_tab = gui_tabs.HealthTab(self.notebook, self)
        self.perf_tab = gui_tabs.PerformanceTab(self.notebook, self)
        self.updates_tab = gui_tabs.UpdatesTab(self.notebook, self)
        self.share_tab = gui_tabs.ShareTab(self.notebook, self)
        for tab in (self.health_tab, self.perf_tab, self.updates_tab,
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
        try:
            import prices
            prices.load()           # newest saved price list, no waiting on the internet
        except Exception:
            pass
        self.after(2000, self.refresh_prices)
        self._show_last_scan()      # instant: show the previous scan right away
        self.after(50, self.start_scan)  # then check the PC again in the background
        self.after(1500, self.check_app_update)
        self.after(2500, self._offer_helper_removal)

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
        import updater
        try:
            updater.launch()
        except OSError as e:
            messagebox.showerror("RigCheck", f"RigCheck couldn't restart itself. Please reopen it.\n\n{e}")
        self.on_close()

    def cleanup_after_update(self):
        """The previous version may still have been closing at startup; try removing it again."""
        try:
            import updater
            updater.cleanup_old()
        except Exception:
            pass

    def refresh_prices(self, manual=False):
        """Fetch the latest prices.json from GitHub in the background."""
        import prices

        def done(changed, err):
            if manual:
                if err:
                    self.set_status("Couldn't download new prices. Showing prices from "
                                    f"{hwa.parts_db.DB_DATE}.")
                else:
                    self.set_status(f"Prices are up to date ({hwa.parts_db.DB_DATE}).")
            if changed and self.hw:
                self.refresh_recommendations()
            self._update_price_label()
        in_thread(self, prices.refresh, done)

    def _update_price_label(self):
        import prices
        if getattr(self, "price_label", None):
            self.price_label.configure(text=f"Prices from {hwa.parts_db.DB_DATE}"
                                            + (" (downloaded from GitHub)" if prices.source == "GitHub" else ""))

    def select_page(self, name):
        self.select_tab(PAGES.index(name))

    def set_speedup_count(self, n):
        pass  # the Speed-ups page was removed

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
        import threading
        import webbrowser
        import updater
        bar = tk.Frame(self.main, bg=gc.ACCENT_DIM)
        bar.pack(fill="x", before=self.notebook, pady=(px(12), 0))
        self._update_banner = bar
        msg = tk.Label(bar, text=f"RigCheck {new['version']} is available.", bg=gc.ACCENT_DIM, fg=TEXT,
                       font=base_font(10, "bold"), padx=px(14), pady=px(8))
        msg.pack(side="left")
        btn = ttk.Button(bar, style="Accent.TButton")
        btn.pack(side="left")
        if new.get("notes"):
            notes = tk.Label(bar, text="What's new", bg=gc.ACCENT_DIM, fg=gc.ACCENT, cursor="hand2",
                             font=base_font(9), padx=px(12))
            notes.pack(side="left")
            notes.bind("<Button-1>", lambda _e: messagebox.showinfo(
                f"What's new in RigCheck {new['version']}", new["notes"]))
        close = tk.Label(bar, text="Not now", bg=gc.ACCENT_DIM, fg=MUTED, cursor="hand2", padx=px(14))
        close.pack(side="right")
        close.bind("<Button-1>", lambda _e: (bar.destroy(), setattr(self, "_update_banner", None)))

        def browser():
            webbrowser.open(new["url"])

        def failed(reason):
            msg.configure(text=f"The update didn't finish: {reason}", font=base_font(10))
            btn.configure(text="Download in browser", command=browser)
            btn.state(["!disabled"])
            close.pack(side="right")

        def progress(done, total):
            pct = f" {done / total:.0%}" if total else f" {done / 1024 ** 2:.0f} MB"
            self.after(0, lambda: msg.configure(text=f"Downloading RigCheck {new['version']}…{pct}"))

        def install(path):
            msg.configure(text=f"Installing RigCheck {new['version']} and restarting…")
            self.update_idletasks()
            try:
                updater.install_and_restart(path, self.on_close)
            except OSError as e:
                failed(f"RigCheck couldn't replace its own file ({e.strerror or e}). If it's in a "
                       "protected folder, move it to Documents or Desktop.")

        def start_update():
            btn.state(["disabled"])
            close.pack_forget()

            def work():
                try:
                    path = updater.download(new, progress)
                    self.after(0, install, path)
                except Exception as e:
                    reason = str(e) if isinstance(e, RuntimeError) else app_info._reason(e)
                    self.after(0, failed, reason)
            threading.Thread(target=work, daemon=True).start()

        if updater.can_self_update() and new.get("download_url"):
            btn.configure(text="Update now", command=start_update)
        else:
            btn.configure(text="Download", command=browser)

    def current_profile(self):
        return PROFILE

    # ---------- removing the old sensor helper (1.8 to 1.10) ----------
    def _offer_helper_removal(self):
        """Earlier versions could install LibreHardwareMonitor, which Windows Defender flags.
        Offer to remove it once per RigCheck version until it's gone."""
        import cleanup
        if self.settings.get("helper_offer_seen") == app_info.APP_VERSION:
            return

        def done(present, err):
            if not present:
                return
            self.settings["helper_offer_seen"] = app_info.APP_VERSION
            self.save_settings()
            if messagebox.askyesno(
                    "Remove the old sensor helper",
                    "RigCheck no longer uses LibreHardwareMonitor, the sensor helper an earlier version set "
                    "up. It's what causes the Windows Defender warnings.\n\nRemove it now? Windows will ask "
                    "for permission once."):
                self.remove_old_helper()
        in_thread(self, cleanup.old_helper_present, done)

    def remove_old_helper(self):
        import cleanup
        self.set_status("Removing the old sensor helper…")

        def done(ok, err):
            if not ok:
                self.set_status("The old sensor helper wasn't removed. You can try again in Settings > Your data.")
                return
            btn = getattr(self.settings_tab, "helper_btn", None)
            if btn is not None:
                btn.destroy()
            msg = "The old sensor helper is removed."
            if cleanup.pawnio_installed():
                msg += (" One more: PawnIO, a driver it installed, is still in your apps. To remove it, "
                        "open Settings > Apps > Installed apps, find PawnIO and choose Uninstall.")
            self.set_status(msg)
            messagebox.showinfo("Sensor helper removed", msg)
        in_thread(self, cleanup.remove_old_helper, done)

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
        logo_file = next((gc.resource(f"rigcheck_{s}.png") for s in (32, 48, 64)
                          if s >= px(30) and os.path.exists(gc.resource(f"rigcheck_{s}.png"))), None)
        if logo_file:
            self._logo_img = tk.PhotoImage(file=logo_file)
            tk.Label(brand, image=self._logo_img, bg=SIDEBAR).pack(side="left")
        else:
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
        for key, title in [("cpu", "Processor"), ("gpu", "Graphics"), ("display", "Monitor"), ("ram", "Memory"),
                           ("storage", "Storage"), ("board", "Motherboard"), ("os", "System")]:
            ttk.Label(left, text=title, style="CardTitle.TLabel").pack(anchor="w", pady=(px(8), 0))
            lbl = ttk.Label(left, text="…", style="CardBody.TLabel", justify="left", wraplength=px(320))
            lbl.pack(anchor="w", fill="x", pady=(px(2), px(4)))
            self.cards[key] = lbl
            if key == "display":
                self.display_box = ttk.Frame(left, style="Card.TFrame")
                self.display_box.pack(anchor="w", fill="x")
        self._card_wrap = px(320)

        def wrap(e):
            self._card_wrap = max(px(200), e.width - px(40))
            for l in list(self.cards.values()) + list(self.display_box.winfo_children()):
                if isinstance(l, ttk.Label):
                    l.configure(wraplength=self._card_wrap)
        left.bind("<Configure>", wrap)
        head = ttk.Frame(body)
        head.grid(row=0, column=1, sticky="ew", pady=(0, px(10)))
        ttk.Label(head, text="Upgrades", style="Section.TLabel").pack(side="left")
        self.summary = ttk.Label(head, text="", style="Sub.TLabel")
        self.summary.pack(side="right")
        self.rec_out = RichText(body)
        self.rec_out.grid(row=1, column=1, sticky="nsew")

    # ---------- scanning ----------
    def _show_last_scan(self):
        """Fill the window from the last saved scan of this same PC, so nothing waits on Windows."""
        import platform
        try:
            with open(os.path.join(hw_store.data_dir(), "last_scan.json"), encoding="utf-8") as f:
                saved = json.load(f)
            hw = saved["hw"]
            if hw.get("pc_name") != (platform.node() or None) or saved.get("version") != app_info.APP_VERSION:
                return  # another computer or another RigCheck version: wait for a fresh scan
        except (OSError, ValueError, KeyError, TypeError):
            return
        try:
            self._scan_done(hw, None, cached=True)
        except Exception:
            self.hw = None  # a bad saved file never stops RigCheck opening

    def _save_last_scan(self, hw):
        try:
            path = os.path.join(hw_store.data_dir(), "last_scan.json")
            with open(path + ".tmp", "w", encoding="utf-8") as f:
                json.dump({"version": app_info.APP_VERSION, "time": time.time(), "hw": hw}, f)
            os.replace(path + ".tmp", path)
        except (OSError, TypeError, ValueError):
            pass

    def start_scan(self):
        self.scan_btn.configure(state="disabled")
        self.export_btn.configure(state="disabled")
        if not self.hw:
            self.set_status("Scanning your hardware. This takes a few seconds.")
        self.progress.pack(fill="both", expand=True)
        self.progress.start(12)
        in_thread(self, hwa.detect_all, self._scan_done)

    def _scan_done(self, hw, err, cached=False):
        if not cached:
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
        if cached:
            self.set_status(f"Showing your last scan{pc.rstrip(',')}. Checking for changes…", base=True)
        if "--updated-from" in sys.argv and not getattr(self, "_told_updated", False):
            self._told_updated = True
            self.set_status(f"Updated to RigCheck {app_info.APP_VERSION}. Scanned this PC{pc} at {when}.")
            self.after(20000, lambda: self.cleanup_after_update())
        for key, lines in hardware_lines(hw).items():
            self.cards[key].configure(text="\n".join(lines))
        self.check_displays()
        self.refresh_recommendations()

        self.share_tab.refresh()
        self.monitor_tab.hw_ready()
        if not cached:
            self._record_scan()
            self._save_last_scan(hw)

    # ---------- monitor (display) check ----------
    def check_displays(self):
        import perf_checks
        if hwa.SYSTEM != "Windows":
            self.cards["display"].configure(text="Checked on Windows only")
            return
        in_thread(self, perf_checks.displays, self._show_displays)

    def _show_displays(self, ds, err):
        import perf_checks
        for w in self.display_box.winfo_children():
            w.destroy()
        if err or not ds:
            self.cards["display"].configure(text="Couldn't read the monitor settings")
            return
        ds = sorted(ds, key=lambda d: not d["primary"])
        lines = []
        for d in ds:
            name = d["monitor"] if d["monitor"] and "generic" not in d["monitor"].lower() else \
                ("Main monitor" if d["primary"] else "Second monitor")
            lines.append(f"{name}: {d['width']}×{d['height']} at {d['hz']} Hz")
        self.cards["display"].configure(text="\n".join(lines))
        for d in ds:
            issues, fix = perf_checks.display_issues(d, self.hw)
            if not issues:
                continue
            prefix = "" if len(ds) == 1 else ("Main monitor: " if d["primary"] else "Second monitor: ")
            for text in issues:
                ttk.Label(self.display_box, text=prefix + text, style="CardWarn.TLabel", justify="left",
                          wraplength=self._card_wrap).pack(anchor="w", fill="x", pady=(0, px(3)))
            if fix:
                w, h, hz = fix
                link = ttk.Label(self.display_box, style="CardLink.TLabel", cursor="hand2",
                                 text=f"Switch to {w}×{h} at {hz} Hz  ›")
                link.pack(anchor="w", pady=(0, px(6)))
                link.bind("<Button-1>", lambda _e, d=d, fix=fix: self.fix_display(d, fix))

    def fix_display(self, d, fix):
        import perf_checks
        from gui_tabs import RefreshConfirm
        w, h, hz = fix
        old = (d["width"], d["height"], d["hz"])
        if not messagebox.askyesno("Change monitor settings",
                                   f"Switch this monitor to {w}×{h} at {hz} Hz?\n\nThe screen may go black "
                                   "for a second. You'll be asked to keep it, and it switches back on its "
                                   "own after 15 seconds if you don't answer."):
            return
        if not perf_checks.set_mode(d["device"], w, h, hz):
            messagebox.showinfo("Monitor", "Windows didn't accept that setting. You can change it in "
                                           "Settings > System > Display.")
            return

        def done(kept):
            self.set_status(f"Monitor set to {w}×{h} at {hz} Hz." if kept else "Monitor settings put back.")
            self.check_displays()
        RefreshConfirm(self, d["device"], f"{w}×{h} at {hz} Hz", old, done)

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


    # ---------- recommendations ----------
    def refresh_recommendations(self):
        if not self.hw:
            return
        profile = self.current_profile()
        self.recs = hwa.recommend(self.hw, profile, self.settings)
        self.stop_preview()
        self._render_recs()

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
        o.write(f"\nTypical lowest US prices from {hwa.parts_db.DB_DATE}. They change daily, so "
                "compare before buying.\n", "small")
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
    gc.set_app_id()
    try:
        import updater
        updater.cleanup_old()
    except Exception:
        pass
    try:
        import pyi_splash  # only exists inside the .exe, which shows a splash while it unpacks
    except ImportError:
        pyi_splash = None
    app = AdvisorApp()
    if pyi_splash:
        app.after(100, pyi_splash.close)  # hide the splash once the window is on screen
    app.mainloop()
