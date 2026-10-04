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
        self.draw()

    def set(self, value):
        self.value = value
        self.draw()

    def draw(self):
        self.delete("all")
        s, w = self.size, px(9)
        box = (w, w, s - w, s - w)
        seg = self.SWEEP / self.SEGMENTS
        filled = 0 if self.value is None else round(min(max(self.value, 0), 100) / 100 * self.SEGMENTS)
        for i in range(self.SEGMENTS):
            start = self.START - i * seg
            self.create_arc(*box, start=start - seg + 1.2, extent=seg - 2.4, style="arc", width=w,
                            outline=ACCENT if i < filled else RAISED)
        text = "–" if self.value is None else f"{self.value:.0f}%"
        big = 18 if s > px(90) else 15
        self.create_text(s / 2, s / 2 - px(4), text=text, fill=TEXT, font=number_font(big))
        self.create_text(s / 2, s / 2 + px(17), text=self.label, fill=MUTED, font=base_font(8))


class Spark(tk.Canvas):
    """A small history graph. series: list of (values, color)."""

    def __init__(self, parent, height=44, fixed_max=100):
        super().__init__(parent, height=px(height), bg=CARD, highlightthickness=0)
        self.fixed_max, self.series = fixed_max, []
        self.bind("<Configure>", lambda e: self.draw())

    def set(self, series):
        self.series = series
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
        step = w / (HISTORY - 1)
        for values, color in self.series:
            if len(values) < 2:
                continue
            pts = []
            offset = HISTORY - len(values)
            for i, v in enumerate(values):
                pts += [(offset + i) * step, h - 1 - (h - 1 - top) * min((v or 0) / peak, 1)]
            self.create_line(*pts, fill=color, width=px(2))


class CoreBars(tk.Canvas):
    """One thin bar per CPU thread, so a single maxed-out core stands out."""

    def __init__(self, parent):
        super().__init__(parent, height=px(22), bg=CARD, highlightthickness=0)
        self.values = []
        self.bind("<Configure>", lambda e: self.draw())

    def set(self, values):
        self.values = values or []
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

        grid = ttk.Frame(self)
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
        self.cpu_note = tk.Label(self.cpu, text="", bg=CARD, fg=MUTED, font=base_font(8), anchor="w",
                                 justify="left", wraplength=px(420))

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

        app.notebook.bind("<<NotebookTabChanged>>", self._on_tab, add="+")

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
        self.monitor = live.LiveMonitor(self.info, lambda s: self.after(0, self._update, s))
        self.monitor.start()
        self.state.configure(text=self.monitor.note or "Live. Updates every second.")

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
        # CPU
        self.cpu_ring.set(s.get("cpu_load"))
        t = s.get("cpu_temp")
        self.cpu_stats["Temperature"].configure(text=f"{t:.0f}°C" if t is not None else "–",
                                                fg=temp_color(t, 80, 92) if t is not None else MUTED)
        clk = s.get("cpu_clock")
        self.cpu_stats["Clock speed"].configure(text=f"{clk / 1000:.2f} GHz" if clk else "–")
        self.cpu_stats["Power"].configure(text=f"{s['cpu_power']:.0f} W" if s.get("cpu_power") else "–")
        self.cpu_stats["Fan"].configure(text=f"{s['cpu_fan']:,} RPM" if s.get("cpu_fan") else "–")
        self.cores.set(s.get("cpu_cores"))
        self._push("cpu", s.get("cpu_load"))
        self.cpu_spark.set([(self.hist["cpu"], ACCENT)])
        if t is None and hw_tools.WINDOWS and not self.cpu_note.winfo_ismapped():
            self.cpu_note.configure(text="Temperature, power and fan speed appear while LibreHardwareMonitor "
                                         "is running (free; see the Health page).")
            self.cpu_note.pack(fill="x")
        elif t is not None and self.cpu_note.winfo_ismapped():
            self.cpu_note.pack_forget()

        # GPU
        self.gpu_ring.set(s.get("gpu_load"))
        gt = s.get("gpu_temp")
        self.gpu_stats["Temperature"].configure(text=f"{gt:.0f}°C" if gt is not None else "–",
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
        del self.recent[:-30]
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
        if procs:
            t.delete(*t.get_children())
            for n, (name, cpu, mem) in enumerate(procs):
                t.insert("", "end", text=name, values=(f"{cpu:.1f}%", hw_tools.human(mem)),
                         tags=("odd",) if n % 2 else ())
            self.proc_note.configure(text="Updates every 2 seconds")
        elif not live.psutil:
            self.proc_note.configure(text="Install psutil to see programs (the .exe includes it)")
