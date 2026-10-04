"""The Settings page."""

import os
import subprocess
import sys
import tkinter as tk
import webbrowser
from tkinter import ttk, messagebox

import app_info
import hw_advisor as hwa
import hw_store
import hw_tools
import gui_common as gc
from gui_common import (px, base_font, display_font, in_thread, ScrollFrame, BG, CARD, TEXT, MUTED,
                        ACCENT, GREEN, AMBER, PROFILE_LABELS, TEXT_SIZES)

START_PAGES = {"Overview": "Overview", "Live monitor": "Monitor", "Free speed-ups": "Speed-ups"}
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


# ---------------------------------------------------------------- start with Windows
def _launch_command():
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    pyw = sys.executable.replace("python.exe", "pythonw.exe")
    return f'"{pyw if os.path.exists(pyw) else sys.executable}" "{os.path.abspath(sys.argv[0])}"'


def starts_with_windows():
    if hwa.SYSTEM != "Windows":
        return False
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            winreg.QueryValueEx(k, "RigCheck")
            return True
    except OSError:
        return False


def set_start_with_windows(on):
    import winreg
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
        if on:
            winreg.SetValueEx(k, "RigCheck", 0, winreg.REG_SZ, _launch_command())
        else:
            try:
                winreg.DeleteValue(k, "RigCheck")
            except OSError:
                pass


# ---------------------------------------------------------------- page
class SettingsTab(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self._refresh_job = None
        self._loading = False
        scroll = ScrollFrame(self)
        scroll.pack(fill="both", expand=True)
        body = scroll.inner
        body.columnconfigure(0, weight=1, uniform="s")
        body.columnconfigure(1, weight=1, uniform="s")
        gap = px(12)

        # ---------- General
        c = self._card(body, "General", 0, 0, gap)
        self.profile = self._combo(c, "I use this PC for", list(PROFILE_LABELS.values()), self._on_profile)
        self.start_page = self._combo(c, "Open RigCheck on", list(START_PAGES), self._on_start_page)
        self.startup = tk.BooleanVar()
        cb = ttk.Checkbutton(c, text="Start RigCheck when Windows starts", style="Card.TCheckbutton",
                             variable=self.startup, command=self._on_startup)
        cb.pack(anchor="w", pady=(px(10), 0))
        if hwa.SYSTEM != "Windows":
            cb.state(["disabled"])
        self._label(c, "Temperatures", top=px(12))
        row = tk.Frame(c, bg=CARD)
        row.pack(anchor="w")
        self.temp = tk.StringVar()
        for text, val in (("Celsius (°C)", "C"), ("Fahrenheit (°F)", "F")):
            ttk.Radiobutton(row, text=text, value=val, variable=self.temp, style="Card.TRadiobutton",
                            command=self._on_temp).pack(side="left", padx=(0, px(14)))
        self.text_size = self._combo(c, "Text size", list(TEXT_SIZES), self._on_text_size)
        self.restart_row = tk.Frame(c, bg=CARD)
        tk.Label(self.restart_row, text="Applies after RigCheck restarts.", bg=CARD, fg=AMBER,
                 font=base_font(9)).pack(side="left")
        ttk.Button(self.restart_row, text="Restart now", command=self.app.restart).pack(side="left", padx=px(10))

        # ---------- Your PC
        c = self._card(body, "Your PC", 0, 1, gap,
                       "What RigCheck can't detect. Used to check that graphics cards fit and get "
                       "enough power.")
        self.watts = self._entry(c, "Power supply wattage", "W", "Printed on the power supply's label.")
        self.pins = self._entry(c, "PCIe 8-pin GPU cables", "", "The 6+2 pin cables labeled PCIe or VGA.")
        self.pin16 = tk.BooleanVar()
        ttk.Checkbutton(c, text="Has a 16-pin (12V-2x6) GPU cable", style="Card.TCheckbutton",
                        variable=self.pin16, command=self._on_pc).pack(anchor="w", pady=(px(8), 0))
        self.length = self._entry(c, "Longest graphics card that fits", "mm",
                                  "From the back of the case to the first obstacle at the front.")

        # ---------- Live monitor
        c = self._card(body, "Live monitor", 1, 0, gap, "Slower updates use a little less processor time.")
        self.interval = tk.IntVar()
        for text, val in (("Every second", 1), ("Every 2 seconds", 2), ("Every 5 seconds", 5)):
            ttk.Radiobutton(c, text=text, value=val, variable=self.interval, style="Card.TRadiobutton",
                            command=self._on_interval).pack(anchor="w", pady=px(2))

        # ---------- Updates
        c = self._card(body, "Updates", 1, 1, gap)
        tk.Label(c, text=f"RigCheck {app_info.APP_VERSION}", bg=CARD, fg=TEXT,
                 font=display_font(13)).pack(anchor="w")
        self.auto = tk.BooleanVar()
        ttk.Checkbutton(c, text="Check for new versions automatically", style="Card.TCheckbutton",
                        variable=self.auto, command=self._on_auto).pack(anchor="w", pady=(px(8), 0))
        row = tk.Frame(c, bg=CARD)
        row.pack(anchor="w", fill="x", pady=(px(10), 0))
        self.check_btn = ttk.Button(row, text="Check now", command=self._check_now)
        self.check_btn.pack(side="left")
        self.update_msg = tk.Label(row, text="", bg=CARD, fg=MUTED, font=base_font(9), justify="left",
                                   wraplength=px(280))
        self.update_msg.pack(side="left", padx=px(10))
        if app_info.UPDATE_REPO:
            link = tk.Label(c, text="See all versions on GitHub", bg=CARD, fg=ACCENT, cursor="hand2",
                            font=base_font(9))
            link.pack(anchor="w", pady=(px(10), 0))
            link.bind("<Button-1>", lambda e: webbrowser.open(
                f"https://github.com/{app_info.UPDATE_REPO}/releases"))
        else:
            for w in (self.check_btn,):
                w.state(["disabled"])
            self.update_msg.configure(text="Update checks aren't set up in this copy.")

        # ---------- Your data
        c = self._card(body, "Your data", 2, 0, gap,
                       "Settings, history and edited prices are stored on this PC only.", span=2)
        row = tk.Frame(c, bg=CARD)
        row.pack(anchor="w", pady=(px(4), 0))
        ttk.Button(row, text="Open data folder",
                   command=lambda: hw_tools.open_in_file_manager(hw_store.data_dir())).pack(side="left")
        ttk.Button(row, text="Reset edited prices", command=self._reset_prices).pack(side="left", padx=px(8))
        ttk.Button(row, text="Clear history", command=self._clear_history).pack(side="left")
        ttk.Button(row, text="Reset all settings", command=self._reset_all).pack(side="left", padx=px(8))

        app.notebook.bind("<<NotebookTabChanged>>", lambda e: self.refresh() if self._visible() else None,
                          add="+")
        self.refresh()

    # ---------- small builders
    def _card(self, parent, title, row, col, gap, desc=None, span=1):
        f = tk.Frame(parent, bg=CARD, padx=px(18), pady=px(14))
        f.grid(row=row, column=col, columnspan=span, sticky="nsew",
               padx=(0 if col == 0 else gap // 2, 0 if col + span == 2 else gap // 2), pady=(0, gap))
        tk.Label(f, text=title, bg=CARD, fg=TEXT, font=display_font(13)).pack(anchor="w")
        if desc:
            tk.Label(f, text=desc, bg=CARD, fg=MUTED, font=base_font(9), justify="left",
                     wraplength=px(420)).pack(anchor="w", pady=(px(2), px(6)))
        return f

    def _label(self, parent, text, top=px(10)):
        tk.Label(parent, text=text, bg=CARD, fg=MUTED, font=base_font(9)).pack(anchor="w", pady=(top, px(3)))

    def _combo(self, parent, label, values, command):
        self._label(parent, label)
        box = ttk.Combobox(parent, state="readonly", values=values, width=26)
        box.pack(anchor="w")
        box.bind("<<ComboboxSelected>>", lambda e: command())
        return box

    def _entry(self, parent, label, unit, hint):
        self._label(parent, label)
        row = tk.Frame(parent, bg=CARD)
        row.pack(anchor="w")
        var = tk.StringVar()
        ttk.Entry(row, textvariable=var, width=8).pack(side="left")
        if unit:
            tk.Label(row, text=unit, bg=CARD, fg=MUTED, font=base_font(9)).pack(side="left", padx=px(6))
        tk.Label(parent, text=hint, bg=CARD, fg=MUTED, font=base_font(8)).pack(anchor="w")
        var.trace_add("write", lambda *_: self._on_pc())
        return var

    # ---------- load current values
    def _visible(self):
        try:
            return self.app.notebook.select() == str(self)
        except tk.TclError:
            return False

    def refresh(self):
        s = self.app.settings
        self._loading = True
        self.profile.set(PROFILE_LABELS.get(s.get("profile"), "Gaming"))
        page = next((k for k, v in START_PAGES.items() if v == s.get("start_page")), "Overview")
        self.start_page.set(page)
        self.startup.set(starts_with_windows())
        self.temp.set(s.get("temp_unit") or "C")
        self.text_size.set(s.get("text_size") or "Normal")
        self.watts.set(s.get("psu_watts") or "")
        self.pins.set("" if s.get("psu_8pin") is None else str(s["psu_8pin"]))
        self.pin16.set(bool(s.get("psu_16pin")))
        self.length.set(s.get("gpu_max_length_mm") or "")
        self.interval.set(int(s.get("monitor_interval") or 1))
        self.auto.set(bool(s.get("auto_update_check", True)))
        self._loading = False

    # ---------- saving
    def _save(self, key, value, status="Settings saved."):
        self.app.settings[key] = value
        self.app.save_settings()
        self.app.set_status(status)

    def _on_profile(self):
        self.app.profile_box.set(self.profile.get())
        self.app.on_profile_change()
        self.app.set_status("Settings saved. Recommendations updated.")

    def _on_start_page(self):
        self._save("start_page", START_PAGES[self.start_page.get()])

    def _on_startup(self):
        try:
            set_start_with_windows(self.startup.get())
            self.app.set_status("RigCheck will start with Windows." if self.startup.get()
                                else "RigCheck won't start with Windows.")
        except OSError as e:
            self.startup.set(not self.startup.get())
            messagebox.showerror("Settings", f"Windows didn't allow that change.\n\n{e}")

    def _on_temp(self):
        gc.set_temp_unit(self.temp.get())
        self._save("temp_unit", self.temp.get(), "Temperatures will show in " +
                   ("Fahrenheit." if self.temp.get() == "F" else "Celsius."))

    def _on_text_size(self):
        changed = self.text_size.get() != (self.app.started_text_size or "Normal")
        self._save("text_size", self.text_size.get())
        if changed:
            self.restart_row.pack(anchor="w", pady=(px(8), 0))
        else:
            self.restart_row.pack_forget()

    def _on_pc(self):
        if self._loading:
            return

        def num(v):
            try:
                return int(float(v)) if str(v).strip() else None
            except ValueError:
                return None
        s = self.app.settings
        s["psu_watts"], s["psu_8pin"] = num(self.watts.get()), num(self.pins.get())
        s["psu_16pin"], s["gpu_max_length_mm"] = self.pin16.get(), num(self.length.get())
        self.app.save_settings()
        # wait until typing pauses before redoing recommendations
        if self._refresh_job:
            self.after_cancel(self._refresh_job)
        self._refresh_job = self.after(700, lambda: (self.app.refresh_recommendations(),
                                                     self.app.set_status("Settings saved. Graphics card "
                                                                         "suggestions updated.")))

    def _on_interval(self):
        self._save("monitor_interval", self.interval.get())
        self.app.monitor_tab.restart_monitor()

    def _on_auto(self):
        self._save("auto_update_check", self.auto.get())

    def _check_now(self):
        self.check_btn.state(["disabled"])
        self.update_msg.configure(text="Checking…", fg=MUTED)

        def done(new, err):
            self.check_btn.state(["!disabled"])
            if err:
                self.update_msg.configure(text="Couldn't reach GitHub. Try again in a little while.", fg=AMBER)
            elif new:
                self.update_msg.configure(text=f"Version {new['version']} is available.", fg=GREEN)
                if not getattr(self.app, "_update_banner", None):
                    self.app.show_update_banner(new)
            else:
                self.update_msg.configure(text="You have the latest version.", fg=GREEN)
        in_thread(self, app_info.check_for_update, done)

    def _reset_prices(self):
        self.app.settings["price_overrides"] = {}
        self.app.settings["resale_overrides"] = {}
        self.app.save_settings()
        self.app.refresh_recommendations()
        self.app.set_status("Prices reset to RigCheck's estimates.")

    def _clear_history(self):
        if messagebox.askyesno("Clear history", "Delete all saved scans, benchmarks and monitor sessions?"):
            hw_store.clear_history()
            self.app.refresh_history()
            self.app.set_status("History cleared.")

    def _reset_all(self):
        if messagebox.askyesno("Reset all settings", "Put every setting back to how RigCheck came, "
                                                     "including your PC details and edited prices? "
                                                     "History is kept. RigCheck will restart."):
            hw_store.reset_settings()
            self.app.settings = hw_store.load_settings()
            self.app.restart()
