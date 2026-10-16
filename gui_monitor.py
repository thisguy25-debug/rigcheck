"""The Live monitor page: CPU, GPU, memory, network, storage and top programs."""

import math
import re
import tkinter as tk
from tkinter import ttk

import live
import hw_tools
import gui_common as gc
from gui_common import (px, base_font, display_font, number_font, in_thread, make_tree,
                        BG, CARD, RAISED, LINE, TEXT, MUTED, ACCENT, GREEN, AMBER, RED, BLUE)

HISTORY = 60  # seconds of history in the small graphs


def temp_color(t, warm, hot):
    if t is None:
        return MUTED
    return RED if t >= hot else AMBER if t >= warm else GREEN


class Ring(tk.Canvas):
    """A segmented dial, matching the meters on the Overview."""

    SEGMENTS, SWEEP, START = 32, 270, 225

    def __init__(self, parent, size=108, label="Load"):
        super().__init__(parent, width=px(size), height=px(size), bg=CARD, highlightthickness=0)
        self.size, self.label, self.value = px(size), label, None
        self._filled = -1
        s, w = self.size, px(9)
        box = (w, w, s - w, s - w)
        seg = self.SWEEP / self.SEGMENTS
        # draw every segment once; updates only change their colors
        self._segs = [self.create_arc(*box, start=self.START - i * seg - seg + 1.2, extent=seg - 2.4,
                                      style="arc", width=w, outline=RAISED) for i in range(self.SEGMENTS)]
        big = 18 if s > px(90) else 15
        self._text = self.create_text(s / 2, s / 2 - px(4), text="–", fill=TEXT, font=number_font(big))
        self.create_text(s / 2, s / 2 + px(17), text=self.label, fill=MUTED, font=base_font(8))

    def set(self, value):
        self.value = value
        filled = 0 if value is None else round(min(max(value, 0), 100) / 100 * self.SEGMENTS)
        if filled != self._filled:
            lo, hi = sorted((max(self._filled, 0), filled))
            for i in range(lo, hi) if self._filled >= 0 else range(self.SEGMENTS):
                self.itemconfigure(self._segs[i], outline=ACCENT if i < filled else RAISED)
            self._filled = filled
        self.itemconfigure(self._text, text="–" if value is None else f"{value:.0f}%")


class Spark(tk.Canvas):
    """A small history graph. series: list of (values, color)."""

    def __init__(self, parent, height=44, fixed_max=100, capacity=HISTORY):
        super().__init__(parent, height=px(height), bg=CARD, highlightthickness=0)
        self.fixed_max, self.series, self.capacity = fixed_max, [], capacity
        self._pending = False
        self.bind("<Configure>", lambda e: self.request())
        self.bind("<Map>", lambda e: self.request())

    def set(self, series):
        self.series = series
        self.request()

    def request(self):
        """Coalesce redraws: many changes in a row become one redraw."""
        if not self._pending:
            self._pending = True
            self.after_idle(self._redraw)

    def _redraw(self):
        self._pending = False
        if self.winfo_ismapped():
            self.draw()

    def draw(self):
        self.delete("all")
        w, h = self.winfo_width(), self.winfo_height()
        if w < 10:
            return
        top = px(4)
        self.create_line(0, h - 1, w, h - 1, fill=LINE)
        self.create_line(0, top, w, top, fill=LINE, dash=(2, 4))
        peak = self.fixed_max or max([max(v) for v, _ in self.series if v] + [1])
        step = w / (self.capacity - 1)
        for values, color in self.series:
            if len(values) < 2:
                continue
            pts = []
            values = values[-self.capacity:]
            offset = self.capacity - len(values)
            for i, v in enumerate(values):
                pts += [(offset + i) * step, h - 1 - (h - 1 - top) * min((v or 0) / peak, 1)]
            self.create_line(*pts, fill=color, width=px(2))


class CoreBars(tk.Canvas):
    """One thin bar per CPU thread, so a single maxed-out core stands out."""

    def __init__(self, parent):
        super().__init__(parent, height=px(22), bg=CARD, highlightthickness=0)
        self.values = []
        self._pending = False
        self.bind("<Configure>", lambda e: self.request())
        self.bind("<Map>", lambda e: self.request())

    def set(self, values):
        self.values = values or []
        self.request()

    def request(self):
        if not self._pending:
            self._pending = True
            self.after_idle(self._redraw)

    def _redraw(self):
        self._pending = False
        if self.winfo_ismapped():
            self.draw()

    def draw(self):
        self.delete("all")
        w, h = self.winfo_width(), self.winfo_height()
        n = len(self.values)
        if not n or w < 10:
            return
        gap = px(2)
        bw = max(px(2), (w - gap * (n - 1)) / n)
        for i, v in enumerate(self.values):
            x = i * (bw + gap)
            self.create_rectangle(x, 0, x + bw, h, fill=RAISED, outline="")
            fh = h * min(max(v, 0), 100) / 100
            color = AMBER if v >= 95 else ACCENT
            if fh > 0:
                self.create_rectangle(x, h - fh, x + bw, h, fill=color, outline="")


class Card(tk.Frame):
    def __init__(self, parent, title):
        super().__init__(parent, bg=CARD, padx=px(16), pady=px(10))
        head = tk.Frame(self, bg=CARD)
        head.pack(fill="x")
        tk.Label(head, text=title, bg=CARD, fg=TEXT, font=display_font(12)).pack(side="left")
        self.subtitle = tk.Label(head, text="", bg=CARD, fg=MUTED, font=base_font(9))
        self.subtitle.pack(side="right")

    def clickable(self, command):
        """Make the whole card open its details view."""
        hint = tk.Label(self.subtitle.master, text="Details ›", bg=CARD, fg=ACCENT, font=base_font(9))
        hint.pack(side="right", padx=(px(10), 0), before=self.subtitle)

        def bind_all(w):
            if getattr(w, "_no_click", False):
                return  # e.g. the sensor setup row has its own button
            w.bind("<Button-1>", lambda _e: command(), add="+")
            try:
                w.configure(cursor="hand2")
            except tk.TclError:
                pass
            for child in w.winfo_children():
                bind_all(child)
        bind_all(self)

    def stats(self, parent, rows):
        """rows: list of labels. Returns {label: value_label}."""
        grid = tk.Frame(parent, bg=CARD)
        out = {}
        for r, label in enumerate(rows):
            tk.Label(grid, text=label, bg=CARD, fg=MUTED, font=base_font(9), anchor="w").grid(
                row=r, column=0, sticky="w", pady=px(1))
            v = tk.Label(grid, text="–", bg=CARD, fg=TEXT, font=number_font(12), anchor="e")
            v.grid(row=r, column=1, sticky="e", padx=(px(16), 0), pady=px(1))
            out[label] = v
        grid.columnconfigure(1, weight=1)
        return grid, out


class MonitorTab(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.monitor = None
        self.info = None
        self.hist = {k: [] for k in ("cpu", "gpu", "ram", "down", "up", "disk")}
        self._building_info = False

        bar = ttk.Frame(self)
        bar.pack(fill="x", pady=(0, px(8)))
        self.state = ttk.Label(bar, text="Starts when you open this page.", style="Sub.TLabel")
        self.state.pack(side="left")
        self.pause_btn = ttk.Button(bar, text="Pause", command=self.toggle_pause)
        self.pause_btn.pack(side="right")
        self.bn_bar = gc.BottleneckBar(bar, width=160, bg=BG, legend=False)
        self.bn_bar.pack(side="right", padx=(px(10), px(16)))
        self.bn_text = ttk.Label(bar, text="", style="Sub.TLabel")
        self.bn_text.pack(side="right")
        self.recent = []
        self.paused = False

        self.long = {}            # 5-minute history for the details views
        self.detail_kind = None
        self.last = {}
        self.detail = ttk.Frame(self)
        grid = self.overview = ttk.Frame(self)
        grid.pack(fill="both", expand=True)
        for c in range(6):
            grid.columnconfigure(c, weight=1, uniform="m")
        grid.rowconfigure(2, weight=1, minsize=px(200))
        gap = px(12)

        # ----- CPU
        self.cpu = Card(grid, "Processor")
        self.cpu.grid(row=0, column=0, columnspan=3, sticky="nsew", padx=(0, gap // 2), pady=(0, gap))
        body = tk.Frame(self.cpu, bg=CARD)
        body.pack(fill="x", pady=(px(8), 0))
        self.cpu_ring = Ring(body)
        self.cpu_ring.pack(side="left")
        g, self.cpu_stats = self.cpu.stats(body, ["Temperature", "Clock speed", "Power", "Fan"])
        g.pack(side="left", fill="x", expand=True, padx=(px(18), 0))
        tk.Label(self.cpu, text="Each core", bg=CARD, fg=MUTED, font=base_font(8)).pack(anchor="w", pady=(px(6), 0))
        self.cores = CoreBars(self.cpu)
        self.cores.pack(fill="x")
        self.cpu_spark = Spark(self.cpu, height=30)
        self.cpu_spark.pack(fill="x", pady=(px(6), 0))
        self.cpu_note = tk.Frame(self.cpu, bg=CARD)
        self.cpu_note._no_click = True
        self.cpu_note_text = tk.Label(self.cpu_note, text="", bg=CARD, fg=MUTED, font=base_font(8), anchor="w",
                                      justify="left", wraplength=px(300))
        self.cpu_note_text.pack(side="left", fill="x", expand=True)
        self.sensor_btn = ttk.Button(self.cpu_note, text="Turn on sensors", command=self.setup_sensors)
        self.sensor_btn.pack(side="right", padx=(px(8), 0))
        self._sensor_busy = False
        self._no_feed = 0

        # ----- GPU
        self.gpu = Card(grid, "Graphics")
        self.gpu.grid(row=0, column=3, columnspan=3, sticky="nsew", padx=(gap // 2, 0), pady=(0, gap))
        body = tk.Frame(self.gpu, bg=CARD)
        body.pack(fill="x", pady=(px(8), 0))
        self.gpu_ring = Ring(body)
        self.gpu_ring.pack(side="left")
        g, self.gpu_stats = self.gpu.stats(body, ["Temperature", "Clock speed", "Power", "Fan"])
        g.pack(side="left", fill="x", expand=True, padx=(px(18), 0))
        vr = tk.Frame(self.gpu, bg=CARD)
        vr.pack(fill="x", pady=(px(6), 0))
        tk.Label(vr, text="Video memory", bg=CARD, fg=MUTED, font=base_font(8)).pack(side="left")
        self.vram_text = tk.Label(vr, text="", bg=CARD, fg=MUTED, font=base_font(8))
        self.vram_text.pack(side="right")
        self.vram_bar = tk.Canvas(self.gpu, height=px(10), bg=CARD, highlightthickness=0)
        self.vram_bar.pack(fill="x", pady=(px(4), 0))
        self.gpu_spark = Spark(self.gpu, height=30)
        self.gpu_spark.pack(fill="x", pady=(px(12), 0))

        # ----- Memory
        self.ram = Card(grid, "Memory")
        self.ram.grid(row=1, column=0, columnspan=2, sticky="nsew", padx=(0, gap // 2), pady=(0, gap))
        body = tk.Frame(self.ram, bg=CARD)
        body.pack(fill="x", pady=(px(8), 0))
        self.ram_ring = Ring(body, size=86, label="In use")
        self.ram_ring.pack(side="left")
        info = tk.Frame(body, bg=CARD)
        info.pack(side="left", fill="x", expand=True, padx=(px(14), 0))
        self.ram_used = tk.Label(info, text="–", bg=CARD, fg=TEXT, font=number_font(14), anchor="w")
        self.ram_used.pack(anchor="w")
        self.ram_kind = tk.Label(info, text="", bg=CARD, fg=MUTED, font=base_font(9), anchor="w",
                                 justify="left")
        self.ram_kind.pack(anchor="w")
        self.ram_spark = Spark(self.ram, height=28)
        self.ram_spark.pack(fill="x", pady=(px(8), 0))

        # ----- Network
        self.net = Card(grid, "Network")
        self.net.grid(row=1, column=2, columnspan=2, sticky="nsew", padx=(gap // 2, gap // 2), pady=(0, gap))
        speeds = tk.Frame(self.net, bg=CARD)
        speeds.pack(fill="x", pady=(px(8), 0))
        self.down = self._speed(speeds, "↓ Download", ACCENT)
        self.up = self._speed(speeds, "↑ Upload", BLUE)
        g, self.net_stats = self.net.stats(self.net, ["Latency", "Connection", "IP address"])
        g.pack(fill="x", pady=(px(6), 0))
        self.net_spark = Spark(self.net, height=28, fixed_max=None)
        self.net_spark.pack(fill="x", pady=(px(8), 0))

        # ----- Storage
        self.disk = Card(grid, "Storage")
        self.disk.grid(row=1, column=4, columnspan=2, sticky="nsew", padx=(gap // 2, 0), pady=(0, gap))
        g, self.disk_stats = self.disk.stats(self.disk, ["Reading", "Writing", "Busy"])
        g.pack(fill="x", pady=(px(8), 0))
        self.drive_box = tk.Frame(self.disk, bg=CARD)
        self.drive_box.pack(fill="x", pady=(px(8), 0))
        self.drive_rows = {}
        self.disk_spark = Spark(self.disk, height=28)
        self.disk_spark.pack(fill="x", pady=(px(8), 0))

        # ----- Top programs
        progs = Card(grid, "Programs using the most")
        progs.grid(row=2, column=0, columnspan=6, sticky="nsew")
        frame, self.proc_tree = make_tree(progs, ["Program", "CPU", "Memory"], [360, 100, 120], 6)
        self.proc_tree.column("CPU", anchor="e")
        self.proc_tree.heading("CPU", anchor="e")
        self.proc_tree.column("Memory", anchor="e")
        self.proc_tree.heading("Memory", anchor="e")
        frame.pack(fill="both", expand=True, pady=(px(8), 0))
        self.proc_note = progs.subtitle

        for card, kind in ((self.cpu, "cpu"), (self.gpu, "gpu"), (self.ram, "ram"), (self.net, "net"),
                           (self.disk, "disk")):
            card.clickable(lambda k=kind: self.show_detail(k))
        app.notebook.bind("<<NotebookTabChanged>>", self._on_tab, add="+")
        app.bind("<Unmap>", self._on_minimize, add="+")
        app.bind("<Map>", self._on_restore, add="+")

    def _speed(self, parent, label, color):
        f = tk.Frame(parent, bg=CARD)
        f.pack(side="left", fill="x", expand=True)
        tk.Label(f, text=label, bg=CARD, fg=color, font=base_font(9, "bold")).pack(anchor="w")
        v = tk.Label(f, text="–", bg=CARD, fg=TEXT, font=number_font(17))
        v.pack(anchor="w")
        return v

    # ---------- start / stop with page visibility ----------
    def _visible(self):
        try:
            return self.app.notebook.select() == str(self)
        except tk.TclError:
            return False

    def _on_tab(self, _e=None):
        if self._visible() and not self.paused:
            self.start()
        else:
            self.stop()

    def _on_minimize(self, e):
        """Stop reading sensors while RigCheck is minimized, so it doesn't compete with games."""
        if e.widget is self.app and self.monitor:
            self.stop()
            self._minimized = True
            self.state.configure(text="Paused while RigCheck is minimized.")

    def _on_restore(self, e):
        if e.widget is self.app and getattr(self, "_minimized", False):
            self._minimized = False
            self._on_tab()

    # ---------- processor sensors (LibreHardwareMonitor) ----------
    def _show_sensor_offer(self):
        import sensors
        if sensors.is_installed():
            self.cpu_note_text.configure(text="The sensor helper is installed but not running.")
            self.sensor_btn.configure(text="Start sensors")
        else:
            self.cpu_note_text.configure(text="Temperature, power and fan need a free sensor helper "
                                              "(LibreHardwareMonitor). Setup takes about a minute.")
            self.sensor_btn.configure(text="Turn on sensors")
        self.sensor_btn.state(["!disabled"])
        self.cpu_note.pack(fill="x", pady=(px(4), 0))

    def setup_sensors(self):
        import sensors
        self._sensor_busy = True
        self.sensor_btn.state(["disabled"])

        def say(msg):
            self.after(0, lambda: self.cpu_note_text.configure(text=msg))

        def work():
            if not sensors.is_installed():
                sensors.download(say)
            else:
                sensors.write_config()
            say("Click Yes on the Windows permission prompt…")
            return sensors.register_and_start()

        def done(ok, err):
            self._sensor_busy = False
            self.sensor_btn.state(["!disabled"])
            if err:
                reason = str(err) if isinstance(err, RuntimeError) else "couldn't reach GitHub to download it"
                self.cpu_note_text.configure(text=f"Setup didn't finish: {reason}. Try again in a minute.")
            elif not ok:
                self.cpu_note_text.configure(text="Windows permission was declined, so the sensors can't "
                                                  "start. Click to try again.")
                self.sensor_btn.configure(text="Try again")
            else:
                self.cpu_note_text.configure(text="Starting. If LibreHardwareMonitor asks to install "
                                                  "PawnIO, click OK. Readings appear here in a few seconds, "
                                                  "and from now on it starts with Windows.")
                self.sensor_btn.pack_forget()
                self.after(60000, lambda: self.sensor_btn.pack(side="right", padx=(px(8), 0)))
        in_thread(self, work, done)

    def hw_ready(self):
        if self._visible() and not self.paused:
            self.start()

    def start(self):
        if self.monitor or not self.app.hw:
            if not self.app.hw:
                self.state.configure(text="Waiting for the hardware scan to finish.")
            return
        if self.info is None:
            if self._building_info:
                return
            self._building_info = True
            self.state.configure(text="Starting up.")

            def done(info, err):
                self._building_info = False
                self.info = info or live.static_info(self.app.hw)
                self._apply_static()
                if self._visible() and not self.paused:
                    self.start()
            in_thread(self, lambda: live.static_info(self.app.hw), done)
            return
        iv = int(self.app.settings.get("monitor_interval") or 1)
        self.monitor = live.LiveMonitor(self.info, lambda s: self.after(0, self._update, s), interval=iv)
        self.monitor.start()
        self.state.configure(text=self.monitor.note or
                             ("Live. Updates every second." if iv == 1 else f"Live. Updates every {iv} seconds."))

    def restart_monitor(self):
        """Apply a new update speed right away."""
        if self.monitor:
            self.stop()
            self.start()

    def stop(self):
        if self.monitor:
            self.monitor.stop()
            self.monitor = None
            if not self.paused:
                self.state.configure(text="Paused while you're on another page.")

    def toggle_pause(self):
        self.paused = not self.paused
        self.pause_btn.configure(text="Resume" if self.paused else "Pause")
        if self.paused:
            self.stop()
            self.state.configure(text="Paused.")
        else:
            self.start()

    # ---------- drawing ----------
    def _apply_static(self):
        i = self.info
        cpu = re.sub(r"\(R\)|\(TM\)|\d+th Gen|CPU|Processor|@.*|\d+-Core", "", i["cpu_name"] or "")
        self.cpu.subtitle.configure(text=re.sub(r"\s+", " ", cpu).strip())
        self.gpu.subtitle.configure(text=re.sub(r"^(NVIDIA|AMD)\s+", "", i.get("gpu_name") or ""))
        kind = " ".join(str(x) for x in (i.get("ram_type"), f"{i['ram_mhz']} MHz" if i.get("ram_mhz") else None) if x)
        self.ram_kind.configure(text=kind)
        link = ", ".join(x for x in (i.get("adapter"), i.get("link")) if x) or "–"
        self.net_stats["Connection"].configure(text=link)
        self.net_stats["IP address"].configure(text=i.get("ip") or "–")
        for w in self.drive_box.winfo_children():
            w.destroy()
        self.drive_rows = {}
        for d in i.get("drives") or []:
            row = tk.Frame(self.drive_box, bg=CARD)
            row.pack(fill="x", pady=px(2))
            top = tk.Frame(row, bg=CARD)
            top.pack(fill="x")
            tk.Label(top, text=d, bg=CARD, fg=TEXT, font=base_font(9)).pack(side="left")
            txt = tk.Label(top, text="", bg=CARD, fg=MUTED, font=base_font(8))
            txt.pack(side="right")
            bar = tk.Canvas(row, height=px(6), bg=CARD, highlightthickness=0)
            bar.pack(fill="x", pady=(px(2), 0))
            self.drive_rows[d] = (txt, bar)

    @staticmethod
    def _bar(canvas, pct, color):
        key = (round(pct or 0, 1), color, canvas.winfo_width())
        if getattr(canvas, "_last", None) == key:
            return
        canvas._last = key
        canvas.delete("all")
        w, h = canvas.winfo_width(), canvas.winfo_height()
        canvas.create_rectangle(0, 0, w, h, fill=RAISED, outline="")
        if pct:
            canvas.create_rectangle(0, 0, w * min(pct, 100) / 100, h, fill=color, outline="")

    def _push(self, key, value):
        h = self.hist[key]
        h.append(value or 0)
        del h[:-HISTORY]

    def _update(self, s):
        if not self.monitor:
            return
        self.last = s
        self._push_long(s)
        if self.detail_kind:
            self._update_detail(s)
        # CPU
        self.cpu_ring.set(s.get("cpu_load"))
        t = s.get("cpu_temp")
        self.cpu_stats["Temperature"].configure(text=gc.fmt_temp(t),
                                                fg=temp_color(t, 80, 92) if t is not None else MUTED)
        clk = s.get("cpu_clock")
        self.cpu_stats["Clock speed"].configure(text=f"{clk / 1000:.2f} GHz" if clk else "–")
        self.cpu_stats["Power"].configure(text=f"{s['cpu_power']:.0f} W" if s.get("cpu_power") else "–")
        self.cpu_stats["Fan"].configure(text=f"{s['cpu_fan']:,} RPM" if s.get("cpu_fan") else "–")
        self.cores.set(s.get("cpu_cores"))
        self._push("cpu", s.get("cpu_load"))
        self.cpu_spark.set([(self.hist["cpu"], ACCENT)])
        self._no_feed = 0 if t is not None else self._no_feed + 1
        if t is None and hw_tools.WINDOWS and self._no_feed >= 6 and not self.cpu_note.winfo_ismapped():
            self._show_sensor_offer()
        elif t is not None and self.cpu_note.winfo_ismapped() and not self._sensor_busy:
            self.cpu_note.pack_forget()

        # GPU
        self.gpu_ring.set(s.get("gpu_load"))
        gt = s.get("gpu_temp")
        self.gpu_stats["Temperature"].configure(text=gc.fmt_temp(gt),
                                                fg=temp_color(gt, 78, 87) if gt is not None else MUTED)
        self.gpu_stats["Clock speed"].configure(text=f"{s['gpu_clock']:,.0f} MHz" if s.get("gpu_clock") else "–")
        self.gpu_stats["Power"].configure(text=f"{s['gpu_power']:.0f} W" if s.get("gpu_power") else "–")
        fan = s.get("gpu_fan")
        self.gpu_stats["Fan"].configure(text=(f"{fan:.0f}%" if fan else "Stopped (quiet mode)") if fan is not None else "–")
        used = s.get("vram_used")
        total = (s.get("vram_total") or ((self.info.get("gpu_vram_total") or 0) * 1024)) or None
        if used and total:
            self.vram_text.configure(text=f"{used / 1024:.1f} of {total / 1024:.0f} GB")
            self._bar(self.vram_bar, used / total * 100, ACCENT)
        self._push("gpu", s.get("gpu_load"))
        self.gpu_spark.set([(self.hist["gpu"], ACCENT)])

        # Memory
        self.ram_ring.set(s.get("ram_load"))
        if s.get("ram_used") is not None and self.info.get("ram_total"):
            self.ram_used.configure(text=f"{s['ram_used']:.1f} of {self.info['ram_total']:g} GB")
        self._push("ram", s.get("ram_load"))
        self.ram_spark.set([(self.hist["ram"], ACCENT)])

        # Network
        self.down.configure(text=live.rate(s.get("net_down")))
        self.up.configure(text=live.rate(s.get("net_up")))
        ping = s.get("ping")
        self.net_stats["Latency"].configure(text=f"{ping} ms" if ping else "–",
                                            fg=(GREEN if ping < 40 else AMBER if ping < 100 else RED) if ping else TEXT)
        self._push("down", s.get("net_down"))
        self._push("up", s.get("net_up"))
        self.net_spark.set([(self.hist["down"], ACCENT), (self.hist["up"], BLUE)])

        # Storage
        self.disk_stats["Reading"].configure(text=live.bytes_rate(s.get("disk_read")))
        self.disk_stats["Writing"].configure(text=live.bytes_rate(s.get("disk_write")))
        busy = s.get("disk_active")
        self.disk_stats["Busy"].configure(text=f"{busy:.0f}%" if busy is not None else "–")
        for d in s.get("drives") or []:
            row = self.drive_rows.get(d["drive"])
            if row:
                txt, bar = row
                txt.configure(text=f"{hw_tools.human(d['used'])} of {hw_tools.human(d['total'])}")
                self._bar(bar, d["pct"], RED if d["pct"] >= 90 else AMBER if d["pct"] >= 80 else ACCENT)
        self._push("disk", busy)
        self.disk_spark.set([(self.hist["disk"], ACCENT)])

        # Bottleneck over the last 30 seconds
        cores = s.get("cpu_cores") or []
        self.recent.append({"gpu": s.get("gpu_load"), "cpu": s.get("cpu_load"),
                            "core_max": max(cores) if cores else s.get("cpu_load")})
        del self.recent[:-max(5, 30 // int(self.app.settings.get("monitor_interval") or 1))]
        b = hw_tools.breakdown(self.recent)
        if s.get("gpu_load") is None and not any(r["gpu"] for r in self.recent):
            self.bn_text.configure(text="Bottleneck: graphics usage isn't available on this PC")
        elif b and b["active"] >= 5:
            top = max(("gpu", "cpu", "neither"), key=lambda k: b[k])
            name = {"gpu": "graphics card", "cpu": "processor", "neither": "neither part"}[top]
            self.bn_text.configure(text=f"Bottleneck, last 30 s: {name} {b[top]:.0f}%")
            self.bn_bar.set(b)
        else:
            self.bn_text.configure(text="Bottleneck: shows up once a game or heavy task is running")
            self.bn_bar.set(None)

        # Programs
        procs = s.get("procs") or []
        t = self.proc_tree
        if procs and procs is not getattr(self, "_shown_procs", None):
            self._shown_procs = procs
            rows = t.get_children()
            for n, (name, cpu, mem) in enumerate(procs):
                values = (f"{cpu:.1f}%", hw_tools.human(mem))
                if n < len(rows):
                    t.item(rows[n], text=name, values=values)
                else:
                    t.insert("", "end", text=name, values=values, tags=("odd",) if n % 2 else ())
            for extra in rows[len(procs):]:
                t.delete(extra)
            self.proc_note.configure(text="Updates every 3 seconds")
        elif not live.psutil:
            self.proc_note.configure(text="Install psutil to see programs (the .exe includes it)")


# =============================================================================
# Details views (click a card on the Live monitor)
# =============================================================================
LONG = 300  # samples kept for the details graphs


class Chart(tk.Frame):
    """A larger history graph with the current value and low / average / high."""

    def __init__(self, parent, title, fmt, fixed_max=None, color=None):
        super().__init__(parent, bg=CARD, padx=px(16), pady=px(12))
        self.fmt = fmt
        head = tk.Frame(self, bg=CARD)
        head.pack(fill="x")
        tk.Label(head, text=title, bg=CARD, fg=MUTED, font=base_font(9)).pack(side="left")
        self.value = tk.Label(self, text="–", bg=CARD, fg=TEXT, font=number_font(20), anchor="w")
        self.value.pack(anchor="w")
        self.stats = tk.Label(self, text="", bg=CARD, fg=MUTED, font=base_font(8), anchor="w")
        self.stats.pack(anchor="w")
        self.spark = Spark(self, height=96, fixed_max=fixed_max, capacity=LONG)
        self.spark.pack(fill="x", pady=(px(6), 0))
        self.caption = tk.Label(self, text="", bg=CARD, fg=MUTED, font=base_font(8))
        self.caption.pack(anchor="w")
        self.color = color or ACCENT

    def set(self, values, empty_note="No readings yet"):
        vals = [v for v in values if v is not None]
        if not vals:
            self.value.configure(text="–")
            self.stats.configure(text="")
            self.caption.configure(text=empty_note)
            self.spark.set([])
            return
        self.value.configure(text=self.fmt(vals[-1]))
        self.stats.configure(text=f"Low {self.fmt(min(vals))}   Avg {self.fmt(sum(vals) / len(vals))}   "
                                  f"High {self.fmt(max(vals))}")
        self.spark.set([([v or 0 for v in values], self.color)])


def _ghz(mhz):
    return f"{mhz / 1000:.2f} GHz"


DETAILS = {
    # kind: (title, [(chart title, history key, formatter, fixed max, note when empty)])
    "cpu": ("Processor", [
        ("Load", "cpu_load", lambda v: f"{v:.0f}%", 100, ""),
        ("Temperature", "cpu_temp", lambda v: gc.fmt_temp(v), 100,
         "Needs LibreHardwareMonitor running (free; see the Health page)"),
        ("Clock speed", "cpu_clock", _ghz, None, ""),
        ("Power", "cpu_power", lambda v: f"{v:.0f} W", None,
         "Needs LibreHardwareMonitor running (free; see the Health page)")]),
    "gpu": ("Graphics", [
        ("Load", "gpu_load", lambda v: f"{v:.0f}%", 100, ""),
        ("Temperature", "gpu_temp", lambda v: gc.fmt_temp(v), 100, "Not reported by this graphics card"),
        ("Clock speed", "gpu_clock", lambda v: f"{v:,.0f} MHz", None, "Not reported by this graphics card"),
        ("Video memory in use", "vram_gb", lambda v: f"{v:.1f} GB", None, "")]),
    "ram": ("Memory", [
        ("In use", "ram_load", lambda v: f"{v:.0f}%", 100, ""),
        ("Used", "ram_gb", lambda v: f"{v:.1f} GB", None, "")]),
    "net": ("Network", [
        ("Download", "down_mbps", lambda v: f"{v:.1f} Mbps", None, ""),
        ("Upload", "up_mbps", lambda v: f"{v:.1f} Mbps", None, ""),
        ("Latency", "ping", lambda v: f"{v:.0f} ms", None, "Checked every 6 seconds")]),
    "disk": ("Storage", [
        ("Reading", "read_mbs", lambda v: f"{v:.1f} MB/s", None, ""),
        ("Writing", "write_mbs", lambda v: f"{v:.1f} MB/s", None, ""),
        ("Busy", "disk_active", lambda v: f"{v:.0f}%", 100, "")]),
}


def _mt_push(self, s):
    vram = s.get("vram_used")
    values = {
        "cpu_load": s.get("cpu_load"), "cpu_temp": s.get("cpu_temp"), "cpu_clock": s.get("cpu_clock"),
        "cpu_power": s.get("cpu_power"), "gpu_load": s.get("gpu_load"), "gpu_temp": s.get("gpu_temp"),
        "gpu_clock": s.get("gpu_clock"), "vram_gb": vram / 1024 if vram else None,
        "ram_load": s.get("ram_load"), "ram_gb": s.get("ram_used"),
        "down_mbps": s["net_down"] * 8 / 1e6 if s.get("net_down") is not None else None,
        "up_mbps": s["net_up"] * 8 / 1e6 if s.get("net_up") is not None else None,
        "ping": s.get("ping"),
        "read_mbs": s["disk_read"] / 1024 ** 2 if s.get("disk_read") is not None else None,
        "write_mbs": s["disk_write"] / 1024 ** 2 if s.get("disk_write") is not None else None,
        "disk_active": s.get("disk_active")}
    for k, v in values.items():
        h = self.long.setdefault(k, [])
        h.append(v)
        del h[:-LONG]


def _mt_specs(self, kind):
    """(label, value) rows for the details view's specs panel."""
    hw, i, s = self.app.hw or {}, self.info or {}, self.last or {}
    import hw_advisor as hwa
    if kind == "cpu":
        c = hw.get("cpu", {})
        platform = hwa.parts_db.identify_cpu(c.get("name"))[0]
        label = hwa.parts_db.PLATFORMS.get(platform, {}).get("label") if platform else None
        model = re.sub(r"\s+", " ", re.sub(r"\(R\)|\(TM\)|\d+th Gen|CPU|Processor|@.*|\d+-Core", "",
                                          c.get("name") or "")).strip()
        rows = [("Model", model or c.get("name")), ("Cores", c.get("cores")), ("Threads", c.get("threads")),
                ("Base clock", _ghz(i["base_mhz"]) if i.get("base_mhz") else None),
                ("Current clock", _ghz(s["cpu_clock"]) if s.get("cpu_clock") else None),
                ("Socket", label)]
    elif kind == "gpu":
        g = next((g for g in hw.get("gpu", []) if not g["integrated"]), (hw.get("gpu") or [{}])[0])
        total = s.get("vram_total")
        rows = [("Model", g.get("name")),
                ("Video memory", f"{total / 1024:.0f} GB" if total else
                 (f"{g['vram_gb']:g} GB" if g.get("vram_gb") else None)),
                ("Current clock", f"{s['gpu_clock']:,.0f} MHz" if s.get("gpu_clock") else None),
                ("Power", f"{s['gpu_power']:.0f} W" if s.get("gpu_power") else None),
                ("Fan", (f"{s['gpu_fan']:.0f}%" if s.get("gpu_fan") else "Stopped (quiet mode)")
                 if s.get("gpu_fan") is not None else None)]
    elif kind == "ram":
        r = hw.get("ram", {})
        mods = r.get("modules") or []
        rows = [("Capacity", f"{r['total_gb']:g} GB" if r.get("total_gb") else None),
                ("Type", " ".join(x for x in (r.get("type"), r.get("form")) if x) or None),
                ("Running at", f"{r['configured_mhz']} MHz" if r.get("configured_mhz") else None),
                ("Rated for", f"{r['rated_mhz']} MHz" if r.get("rated_mhz") and r.get("rated_mhz") != r.get(
                    "configured_mhz") else None),
                ("Sticks", (" + ".join(f"{m:g} GB" for m in mods) +
                            (f" in {r['slots_total']} slots" if r.get("slots_total") else "")) if mods else None)]
    elif kind == "net":
        rows = [("Connection", i.get("adapter")), ("Link speed", i.get("link")), ("IP address", i.get("ip")),
                ("Latency", f"{s['ping']} ms" if s.get("ping") else None)]
    else:
        rows = []
        for d in hw.get("storage", {}).get("drives", []):
            size = d.get("size_gb") or 0
            cap = f"{size / 1024:.1f} TB" if size >= 1000 else f"{size:.0f} GB"
            rows.append((d.get("name") or "Drive", f"{cap} {d.get('bus') or ''} {d.get('type') or ''}".strip()))
        for d in s.get("drives") or []:
            rows.append((f"{d['drive']} space", f"{hw_tools.human(d['used'])} used of "
                                                  f"{hw_tools.human(d['total'])} ({d['pct']:.0f}%)"))
    return [(k, v) for k, v in rows if v not in (None, "")]


def _mt_show_detail(self, kind):
    self.detail_kind = kind
    for w in self.detail.winfo_children():
        w.destroy()
    title, charts = DETAILS[kind]
    head = tk.Frame(self.detail, bg=BG)
    head.pack(fill="x", pady=(0, px(10)))
    back = tk.Label(head, text="‹ Back to all", bg=BG, fg=ACCENT, cursor="hand2", font=base_font(10))
    back.pack(side="left")
    back.bind("<Button-1>", lambda _e: self.hide_detail())
    tk.Label(head, text=f"{title} details", bg=BG, fg=TEXT, font=display_font(14)).pack(side="left",
                                                                                     padx=px(16))
    body = tk.Frame(self.detail, bg=BG)
    body.pack(fill="both", expand=True)
    body.columnconfigure(0, weight=1, minsize=px(260))
    body.columnconfigure(1, weight=2)
    body.columnconfigure(2, weight=2)

    specs = tk.Frame(body, bg=CARD, padx=px(16), pady=px(12))
    specs.grid(row=0, column=0, rowspan=2, sticky="nsew", padx=(0, px(12)))
    tk.Label(specs, text="Specs", bg=CARD, fg=TEXT, font=display_font(12)).pack(anchor="w", pady=(0, px(6)))
    self.spec_box = tk.Frame(specs, bg=CARD)
    self.spec_box.pack(fill="x")
    if kind == "cpu":
        tk.Label(specs, text="Each core", bg=CARD, fg=MUTED, font=base_font(9)).pack(anchor="w", pady=(px(14), px(4)))
        self.detail_cores = CoreBars(specs)
        self.detail_cores.configure(height=px(70))
        self.detail_cores.pack(fill="x")
    else:
        self.detail_cores = None

    self.detail_charts = []
    for n, (ctitle, key, fmt, fmax, note) in enumerate(charts):
        ch = Chart(body, ctitle, fmt, fixed_max=fmax, color=BLUE if key == "up_mbps" else ACCENT)
        ch.grid(row=n // 2, column=1 + n % 2, sticky="nsew", padx=(0, px(12) if n % 2 == 0 else 0),
                pady=(0, px(12)))
        self.detail_charts.append((ch, key, note))
    minutes = LONG * int(self.app.settings.get("monitor_interval") or 1) / 60
    for ch, _k, _n in self.detail_charts:
        ch.caption.configure(text=f"Last {minutes:g} minutes")
    self.overview.pack_forget()
    self.detail.pack(fill="both", expand=True)
    if self.last:
        self._update_detail(self.last)


def _mt_hide_detail(self):
    self.detail_kind = None
    self.detail.pack_forget()
    self.overview.pack(fill="both", expand=True)


def _mt_update_detail(self, s):
    rows = self._specs(self.detail_kind)
    box = self.spec_box
    existing = getattr(self, "_spec_labels", {})
    if [r[0] for r in rows] != list(existing) or not box.winfo_children():
        for w in box.winfo_children():
            w.destroy()
        existing = {}
        for r, (label, value) in enumerate(rows):
            tk.Label(box, text=label, bg=CARD, fg=MUTED, font=base_font(9), anchor="w").grid(
                row=r * 2, column=0, sticky="w", pady=(px(4), 0))
            v = tk.Label(box, text=str(value), bg=CARD, fg=TEXT, font=base_font(10), anchor="w",
                         justify="left", wraplength=px(240))
            v.grid(row=r * 2 + 1, column=0, sticky="w")
            existing[label] = v
        self._spec_labels = existing
    else:
        for label, value in rows:
            existing[label].configure(text=str(value))
    if self.detail_cores is not None:
        self.detail_cores.set(s.get("cpu_cores"))
    minutes = LONG * int(self.app.settings.get("monitor_interval") or 1) / 60
    for ch, key, note in self.detail_charts:
        values = self.long.get(key, [])
        ch.set(values, empty_note=note or "No readings yet")
        if any(v is not None for v in values):
            ch.caption.configure(text=f"Last {minutes:g} minutes")


MonitorTab._push_long = _mt_push
MonitorTab._specs = _mt_specs
MonitorTab.show_detail = _mt_show_detail
MonitorTab.hide_detail = _mt_hide_detail
MonitorTab._update_detail = _mt_update_detail
