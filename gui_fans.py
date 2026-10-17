"""Fan control window: a slider per fan, presets, and the safety rules spelled out."""

import tkinter as tk
from tkinter import ttk, messagebox

import gui_common as gc
from gui_common import in_thread, px, base_font, BG, TEXT, MUTED
import fan_control
import sensors

KIND_LABEL = {"pump": "Pump", "gpu": "Graphics card", "fan": "Fan"}
PRESETS = (("Quiet", 40), ("Balanced", 60), ("Full speed", 100))


class FanDialog(tk.Toplevel):
    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self.fans = app.fans
        self.rows = {}
        self._pending = {}
        self.title("Fan control")
        self.configure(bg=BG)
        self.transient(app)
        gc.dark_title_bar(self)
        self.geometry(f"{px(640)}x{px(620)}")
        self.minsize(px(520), px(420))

        top = ttk.Frame(self, padding=(px(22), px(18), px(22), 0))
        top.pack(fill="x")
        ttk.Label(top, text="Fan control", style="Title.TLabel").pack(anchor="w")
        ttk.Label(top, style="Sub.TLabel", wraplength=px(580), justify="left",
                  text=f"Fans you don't change stay on automatic. If the processor reaches "
                       f"{fan_control.CPU_LIMIT} °C or the graphics card {fan_control.GPU_LIMIT} °C, every fan "
                       "goes back to automatic straight away. Closing RigCheck does the same, and your "
                       "speeds come back the next time you open it.").pack(anchor="w", pady=(px(4), 0))
        self.temps = ttk.Label(top, text="", style="Sub.TLabel")
        self.temps.pack(anchor="w", pady=(px(8), 0))
        self.warn = ttk.Label(top, text="", foreground=gc.AMBER, wraplength=px(580), justify="left")

        bar = ttk.Frame(self, padding=(px(22), px(12), px(22), px(6)))
        bar.pack(fill="x")
        ttk.Button(bar, text="All automatic", style="Accent.TButton", command=self.all_auto).pack(side="left")
        for label, pct in PRESETS:
            ttk.Button(bar, text=label, command=lambda p=pct: self.preset(p)).pack(side="left", padx=(px(8), 0))
        self.preset_note = ttk.Label(self, text="Presets set every fan except pumps, which stay on automatic.",
                                     style="Sub.TLabel", padding=(px(22), 0))
        self.preset_note.pack(anchor="w")

        outer = ttk.Frame(self, padding=(px(22), px(10), px(22), px(10)))
        outer.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(outer, bg=BG, highlightthickness=0)
        sb = ttk.Scrollbar(outer, command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.list = ttk.Frame(self.canvas)
        win = self.canvas.create_window(0, 0, window=self.list, anchor="nw")
        self.list.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(win, width=e.width))
        self.message = ttk.Label(self.list, text="Reading your fans…", style="Sub.TLabel", wraplength=px(560),
                                 justify="left")
        self.message.pack(anchor="w")

        b = ttk.Frame(self, padding=px(16))
        b.pack(fill="x")
        ttk.Button(b, text="Close", command=self.destroy).pack(side="right")
        self.refresh(first=True)

    # ------------------------------------------------------------ reading
    def refresh(self, first=False):
        if not self.winfo_exists():
            return
        in_thread(self, lambda: sensors.read_sensors(timeout=1), lambda s, e: self._got(s, first))

    def _got(self, all_sensors, first):
        if not self.winfo_exists():
            return
        self.after(1500, self.refresh)
        if all_sensors is None:
            self._show_message("Fan control works through the sensor helper (LibreHardwareMonitor). Turn it on "
                               "with Turn on sensors on the Live monitor's Processor card, then open this "
                               "window again.")
            return
        controls = sensors.fan_controls(all_sensors)
        info = sensors.pick(all_sensors, sensors.PREFERRED_FAN)
        t = [f"Processor {info['cpu_temp']:.0f} °C" if info.get("cpu_temp") else None,
             f"Graphics card {info['gpu_temp']:.0f} °C" if info.get("gpu_temp") else None]
        self.temps.configure(text="   ·   ".join(x for x in t if x))
        tripped = self.fans.status()
        if tripped:
            self.warn.configure(text=tripped)
            self.warn.pack(anchor="w", pady=(px(6), 0))
        else:
            self.warn.pack_forget()
        if not controls:
            self._show_message("Your motherboard doesn't let programs change its fan speeds (common on laptops "
                               "and some boards). You can still set a fan curve in the BIOS or in your "
                               "motherboard maker's own app.")
            return
        if first or set(self.rows) != {c["id"] for c in controls}:
            self._build(controls)
        for c in controls:
            self._update_row(c)

    def _show_message(self, text):
        for w in self.list.winfo_children():
            if w is not self.message:
                w.destroy()
        self.rows = {}
        self.message.configure(text=text)
        self.message.pack(anchor="w")

    # ------------------------------------------------------------ rows
    def _build(self, controls):
        for w in self.list.winfo_children():
            if w is not self.message:
                w.destroy()
        self.message.pack_forget()
        self.rows = {}
        saved = self.app.settings.get("fan_profile") or {}
        order = {"fan": 0, "pump": 1, "gpu": 2}
        for c in sorted(controls, key=lambda c: (order[c["kind"]], c["name"])):
            card = ttk.Frame(self.list, style="Card.TFrame", padding=(px(16), px(12)))
            card.pack(fill="x", pady=(0, px(10)))
            head = ttk.Frame(card, style="Card.TFrame")
            head.pack(fill="x")
            ttk.Label(head, text=c["name"], style="CardBody.TLabel", font=base_font(11, "bold")).pack(side="left")
            reading = ttk.Label(head, text="", style="CardTitle.TLabel")
            reading.pack(side="right")
            row = ttk.Frame(card, style="Card.TFrame")
            row.pack(fill="x", pady=(px(8), 0))
            auto = tk.BooleanVar(value=c["id"] not in saved)
            low = sensors.MIN_PERCENT[c["kind"]]
            value = tk.DoubleVar(value=saved.get(c["id"], max(low, round(c["percent"] or 50))))
            pct = ttk.Label(row, text="", style="CardBody.TLabel", width=6, anchor="e")
            scale = ttk.Scale(row, from_=low, to=100, variable=value,
                              command=lambda _v, sid=c["id"]: self._slid(sid))
            chk = ttk.Checkbutton(row, text="Automatic", variable=auto,
                                  command=lambda sid=c["id"]: self._toggled(sid))
            chk.pack(side="left")
            pct.pack(side="right")
            scale.pack(side="left", fill="x", expand=True, padx=(px(14), px(8)))
            note = None
            if c["kind"] == "pump":
                note = f"Liquid cooler pump: it can't go below {low}% so coolant keeps flowing."
            elif c["kind"] == "gpu":
                note = f"Graphics card fan, from {low}%. Under load the guard watches the card's temperature."
            if note:
                ttk.Label(card, text=note, style="CardTitle.TLabel").pack(anchor="w", pady=(px(6), 0))
            self.rows[c["id"]] = {"auto": auto, "value": value, "scale": scale, "pct": pct,
                                  "reading": reading, "kind": c["kind"], "name": c["name"]}
            self._sync_row(c["id"])

    def _sync_row(self, sid):
        r = self.rows[sid]
        r["scale"].state(["disabled"] if r["auto"].get() else ["!disabled"])
        r["pct"].configure(text="Auto" if r["auto"].get() else f"{round(r['value'].get())}%",
                           foreground=MUTED if r["auto"].get() else TEXT)

    def _update_row(self, c):
        r = self.rows.get(c["id"])
        if not r:
            return
        bits = []
        if c["rpm"] is not None:
            bits.append(f"{c['rpm']:,} RPM" if c["rpm"] else "Stopped")
        if c["percent"] is not None:
            bits.append(f"{c['percent']:.0f}% now")
        r["reading"].configure(text="   ".join(bits))

    # ------------------------------------------------------------ changes
    def _slid(self, sid):
        r = self.rows[sid]
        r["value"].set(round(r["value"].get()))
        self._sync_row(sid)
        # Apply once the slider rests for a moment, not on every pixel of a drag
        if sid in self._pending:
            self.after_cancel(self._pending[sid])
        self._pending[sid] = self.after(250, lambda: self._apply(sid))

    def _toggled(self, sid):
        self._sync_row(sid)
        self._apply(sid)

    def _apply(self, sid):
        self._pending.pop(sid, None)
        r = self.rows.get(sid)
        if not r:
            return
        if not r["auto"].get() and not self._ready_for_manual():
            r["auto"].set(True)
            self._sync_row(sid)
            return
        percent = None if r["auto"].get() else round(r["value"].get())
        self._save(sid, percent)
        in_thread(self, lambda: self.fans.set(sid, percent, r["kind"]),
                  lambda ok, e: ok or self.app.set_status(
                      f"{r['name']} didn't accept the change. Make sure the sensor helper is running."))

    def _save(self, sid, percent):
        profile = dict(self.app.settings.get("fan_profile") or {})
        kinds = dict(self.app.settings.get("fan_kinds") or {})
        if percent is None:
            profile.pop(sid, None)
        else:
            profile[sid] = percent
            kinds[sid] = self.rows[sid]["kind"]
        self.app.settings["fan_profile"] = profile
        self.app.settings["fan_kinds"] = kinds
        self.app.save_settings()

    def preset(self, percent):
        if not self.rows or not self._ready_for_manual():
            return
        for sid, r in self.rows.items():
            if r["kind"] == "pump":
                continue
            r["auto"].set(False)
            r["value"].set(max(sensors.MIN_PERCENT[r["kind"]], percent))
            self._sync_row(sid)
            self._apply(sid)

    def all_auto(self):
        for sid, r in self.rows.items():
            r["auto"].set(True)
            self._sync_row(sid)
        self.app.settings["fan_profile"] = {}
        self.app.save_settings()
        in_thread(self, self.fans.all_auto, lambda *_: self.app.set_status("Every fan is back on automatic."))

    def _ready_for_manual(self):
        """Older RigCheck versions set the sensor helper to start without clearing saved fan speeds.
        Update its startup task once, before the first manual speed."""
        if self.app.settings.get("sensor_task", 1) >= sensors.TASK_VERSION or not sensors.WINDOWS:
            return True
        if not messagebox.askyesno(
                "Fan control",
                "One-time setup: RigCheck needs to update how the sensor helper starts with Windows, so fan "
                "speeds set here never stay on after RigCheck closes. Windows will ask for permission.\n\n"
                "Continue?", parent=self):
            return False
        if not sensors.register_and_start():
            messagebox.showinfo("Fan control", "Windows permission was declined, so fan speeds can't be "
                                               "changed yet.", parent=self)
            return False
        self.app.settings["sensor_task"] = sensors.TASK_VERSION
        self.app.save_settings()
        return True
