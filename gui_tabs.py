"""Tool tabs for the RigCheck window."""

import json
import os
import re
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog, filedialog

import games_db
import hw_advisor as hwa
import hw_store
import hw_tools
import parts_db
from gui_common import (RichText, in_thread, make_tree, base_font, px, CARD, BG, LINE, MUTED,
                        ACCENT, GREEN, AMBER, RED, BLUE, COLORS)
import gui_common as gc


def _toolbar(parent):
    bar = ttk.Frame(parent, padding=(0, 0, 0, px(12)))
    bar.pack(fill="x")
    return bar


def _admin_button(bar, app):
    if hwa.SYSTEM == "Windows" and not hwa.is_admin():
        ttk.Button(bar, text="Restart as administrator",
                   command=lambda: hw_tools.relaunch_as_admin() and app.destroy()).pack(side="right")


# =============================================================================
# Disk space
# =============================================================================
class DiskTab(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, padding=0)
        self.app = app
        self.scan = None
        self.cancel = threading.Event()
        inner = ttk.Notebook(self)
        inner.pack(fill="both", expand=True)
        self._build_cleanup(inner)
        self._build_analyzer(inner)

    # ---------- quick cleanup ----------
    def _build_cleanup(self, nb):
        f = ttk.Frame(nb, padding=(0, px(16), 0, 0))
        nb.add(f, text="Quick cleanup")
        bar = _toolbar(f)
        ttk.Button(bar, text="Find safe cleanups", style="Accent.TButton",
                   command=self.find_targets).pack(side="left")
        self.clean_btn = ttk.Button(bar, text="Clean selected", command=self.clean_selected,
                                    state="disabled")
        self.clean_btn.pack(side="left", padx=px(8))
        if hwa.SYSTEM == "Windows":
            ttk.Button(bar, text="Open Windows Disk Cleanup",
                       command=hw_tools.open_disk_cleanup).pack(side="left")
        _admin_button(bar, self.app)
        self.clean_status = ttk.Label(f, text="Find temporary files, caches and other things "
                                              "that are safe to delete.", style="Sub.TLabel")
        self.clean_status.pack(anchor="w", pady=(0, 8))
        frame, self.targets_tree = make_tree(f, ["Item", "Size", "What to do"], [240, 100, 520], 12)
        frame.pack(fill="both", expand=True)
        self.targets_tree.bind("<<TreeviewSelect>>", self._on_target_select)
        self.targets_tree.bind("<Double-1>", self._open_target)
        self.targets_tree.tag_configure("safe", foreground=GREEN)
        self.targets_tree.tag_configure("other", foreground=MUTED)
        self.targets = []

    def find_targets(self):
        self.clean_status.configure(text="Measuring. Large folders can take a minute.")
        in_thread(self, hw_tools.cleanup_targets, self._targets_done)

    def _targets_done(self, targets, err):
        if err:
            self.clean_status.configure(text=f"Couldn't check: {err}")
            return
        self.targets = targets
        t = self.targets_tree
        t.delete(*t.get_children())
        safe_total = 0
        for i, x in enumerate(targets):
            if x["size"] < 1024 * 1024 and x["kind"] != "info":
                continue
            label = x["name"]
            t.insert("", "end", iid=str(i), text=label,
                     values=(hw_tools.human(x["size"]), x["how"]),
                     tags=("safe" if x["kind"] == "safe" else "other",))
            if x["kind"] == "safe":
                safe_total += x["size"]
        self.clean_status.configure(text=f"About {hw_tools.human(safe_total)} can be safely cleaned "
                                         "(green). Select items, then Clean selected. Double-click "
                                         "an item to open it.")

    def _on_target_select(self, _e=None):
        sel = [self.targets[int(i)] for i in self.targets_tree.selection()]
        self.clean_btn.configure(state="normal" if any(x["kind"] == "safe" for x in sel)
                                 else "disabled")

    def _open_target(self, _e=None):
        for i in self.targets_tree.selection():
            path = self.targets[int(i)]["path"]
            if path != "::recycle":
                hw_tools.open_in_file_manager(path)

    def clean_selected(self):
        sel = [self.targets[int(i)] for i in self.targets_tree.selection()
               if self.targets[int(i)]["kind"] == "safe"]
        if not sel:
            return
        names = "\n".join(f"• {x['name']} ({hw_tools.human(x['size'])})" for x in sel)
        if not messagebox.askyesno("Clean up", f"Permanently delete the contents of:\n\n{names}\n\n"
                                               "Files that are in use will be skipped."):
            return
        self.clean_status.configure(text="Cleaning up.")
        in_thread(self, lambda: sum(hw_tools.clean_target(x) for x in sel), self._clean_done)

    def _clean_done(self, freed, err):
        if err:
            self.clean_status.configure(text=f"Cleanup error: {err}")
            return
        self.app.set_status(f"Cleaned up {hw_tools.human(freed)}.")
        self.find_targets()

    # ---------- folder analyzer ----------
    def _build_analyzer(self, nb):
        f = ttk.Frame(nb, padding=(0, px(16), 0, 0))
        nb.add(f, text="What's using space")
        bar = _toolbar(f)
        ttk.Label(bar, text="Scan:").pack(side="left")
        drives = hw_tools.fixed_drives()
        self.drive_box = ttk.Combobox(bar, values=drives + ["Choose a folder…"], width=24,
                                      state="readonly")
        self.drive_box.set(drives[0] if drives else "Choose a folder…")
        self.drive_box.pack(side="left", padx=6)
        self.drive_box.bind("<<ComboboxSelected>>", self._maybe_pick_folder)
        self.scan_btn = ttk.Button(bar, text="Scan folder", style="Accent.TButton", command=self.start_scan)
        self.scan_btn.pack(side="left")
        self.cancel_btn = ttk.Button(bar, text="Stop", command=self.cancel.set, state="disabled")
        self.cancel_btn.pack(side="left", padx=px(8))
        ttk.Button(bar, text="Open selected", command=self._open_selected).pack(side="right")
        self.scan_status = ttk.Label(f, text="Pick a drive or folder. A whole drive takes a few minutes.",
                                     style="Sub.TLabel")
        self.scan_status.pack(anchor="w", pady=(0, 8))

        panes = ttk.PanedWindow(f, orient="horizontal")
        panes.pack(fill="both", expand=True)
        left, self.tree = make_tree(panes, ["Folder", "Size", "%"], [320, 90, 60], 16)
        right, self.files = make_tree(panes, ["Largest files", "Size"], [320, 90], 16)
        panes.add(left, weight=3)
        panes.add(right, weight=2)
        self.tree.bind("<<TreeviewOpen>>", self._expand)
        self.files.bind("<Double-1>", lambda e: self._open_selected(self.files))
        self.tree.bind("<Double-1>", lambda e: None)

    def _maybe_pick_folder(self, _e=None):
        if self.drive_box.get() == "Choose a folder…":
            path = filedialog.askdirectory()
            if path:
                vals = list(self.drive_box["values"])
                self.drive_box["values"] = [path] + vals
                self.drive_box.set(path)

    def start_scan(self):
        root = self.drive_box.get()
        if not root or root == "Choose a folder…":
            return
        self.cancel.clear()
        self.scan_btn.configure(state="disabled")
        self.cancel_btn.configure(state="normal")
        self.scan = hw_tools.DiskScan(root)

        def progress(files, path):
            self.after(0, lambda: self.scan_status.configure(
                text=f"Scanned {files:,} files. Now in {path[:80]}"))
        in_thread(self, lambda: self.scan.run(progress, self.cancel), self._scan_done)

    def _scan_done(self, _res, err):
        self.scan_btn.configure(state="normal")
        self.cancel_btn.configure(state="disabled")
        s = self.scan
        if err:
            self.scan_status.configure(text=f"Scan failed: {err}")
            return
        total = s.sizes.get(s.root, 0)
        note = " (stopped early)" if self.cancel.is_set() else ""
        skipped = f", {s.errors:,} protected items skipped" if s.errors else ""
        self.scan_status.configure(text=f"{hw_tools.human(total)} in {s.files_seen:,} files{note}"
                                        f"{skipped}. Expand a folder to see what's inside.")
        self.tree.delete(*self.tree.get_children())
        self._insert_folder("", s.root, total, open_=True)
        self.files.delete(*self.files.get_children())
        for size, path in s.top_files:
            self.files.insert("", "end", iid=path, text=path, values=(hw_tools.human(size),))

    def _insert_folder(self, parent_iid, path, parent_size, open_=False):
        s = self.scan
        size = s.sizes.get(path, 0)
        pct = f"{size / parent_size:.0%}" if parent_size else ""
        name = path if parent_iid == "" else os.path.basename(path) or path
        iid = self.tree.insert(parent_iid, "end", iid=path, text=name,
                               values=(hw_tools.human(size), pct), open=open_)
        if s.children.get(path):
            if open_:
                self._fill(path)
            else:
                self.tree.insert(iid, "end", iid=path + "::dummy", text="…")

    def _fill(self, path):
        s = self.scan
        size = s.sizes.get(path, 0)
        for child in s.children.get(path, [])[:200]:
            if s.sizes.get(child, 0) > 0:
                self._insert_folder(path, child, size)
        if s.file_bytes.get(path):
            self.tree.insert(path, "end", iid=path + "::files", text="(files in this folder)",
                             values=(hw_tools.human(s.file_bytes[path]),
                                     f"{s.file_bytes[path] / size:.0%}" if size else ""))

    def _expand(self, _e=None):
        iid = self.tree.focus()
        dummy = iid + "::dummy"
        if self.tree.exists(dummy):
            self.tree.delete(dummy)
            self._fill(iid)

    def _open_selected(self, tree=None):
        tree = tree if isinstance(tree, ttk.Treeview) else None
        for t in ([tree] if tree else [self.tree, self.files]):
            for iid in t.selection():
                hw_tools.open_in_file_manager(iid.split("::")[0])


# =============================================================================
# Health: drives and temperatures
# =============================================================================
class HealthTab(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, padding=0)
        self.app = app
        bar = _toolbar(self)
        self.btn = ttk.Button(bar, text="Check health", style="Accent.TButton", command=self.check)
        self.btn.pack(side="left")
        _admin_button(bar, app)
        self.out = RichText(self)
        self.out.pack(fill="both", expand=True)
        self.out.clear()
        self.out.write("Check your drives for signs of failure and read CPU and GPU temperatures.\n",
                       "muted")
        self.out.done()

    def check(self):
        self.btn.configure(state="disabled")
        self.app.set_status("Checking drive health and temperatures…")
        in_thread(self, lambda: (hw_tools.drive_health(), hw_tools.sensor_report()), self._done)

    def _done(self, res, err):
        self.btn.configure(state="normal")
        self.app.set_status("Health check complete" if not err else "Health check failed")
        o = self.out
        o.clear()
        if err:
            o.write(f"Something went wrong: {err}\n")
            o.done()
            return
        drives, sensors = res
        o.write("Drives\n", "h1")
        if not drives:
            o.write("Couldn't read drive health on this system.\n", "muted")
        for d in drives:
            o.badge(d["verdict"], d["verdict"])
            o.write(f"  {d['name']}  ", "bold")
            o.write(f"{d.get('type', '')}\n", "muted")
            facts = []
            if d.get("wear") is not None:
                facts.append(f"{d['wear']}% of rated life used")
            if d.get("hours"):
                facts.append(f"{d['hours']:,} hours powered on")
            if d.get("temp"):
                facts.append(gc.fmt_temp(d["temp"]))
            if d.get("firmware"):
                facts.append(f"firmware {d['firmware']}")
            if facts:
                o.write(gc.sentence(", ".join(facts)) + "\n", "indent")
            for r in d["reasons"]:
                o.write(f"• {gc.convert_temps(r)}\n", "indent")
            if d["verdict"] == "Bad":
                o.colored("Back up this drive now and plan to replace it.\n", "bad")
            o.write("\n", "gap")
        if hwa.SYSTEM == "Windows" and not hwa.is_admin():
            o.write("Tip: ", "bold")
            o.write("restart as administrator for detailed data like wear level and error counts. ")
            o.write("For the most detail, install ")
            o.link("smartmontools", "https://www.smartmontools.org/wiki/Download")
            o.write(" and the app will use it automatically.\n")

        o.write("\nTemperatures\n", "h1")
        if sensors["cpu_temp"] is not None:
            o.write(f"CPU: {gc.fmt_temp(sensors['cpu_temp'], 1)}", "bold")
            o.write(f"   (source: {sensors['cpu_source']})\n", "muted")
        else:
            o.write("CPU temperature isn't available without a helper. Install and run ", "muted")
            o.link("LibreHardwareMonitor", "https://github.com/LibreHardwareMonitor/LibreHardwareMonitor/releases")
            o.write(" (free); the app reads its sensors automatically while it's open.\n", "muted")
        for g in sensors["gpus"]:
            bits = [gc.fmt_temp(g["temp"]) if g["temp"] is not None else None,
                    f"{g['util']:.0f}% busy" if g["util"] is not None else None,
                    f"{g['power']:.0f} W" if g["power"] is not None else None,
                    f"fan {g['fan']:.0f}%" if g["fan"] is not None else None]
            o.write(f"{g['name']}: ", "bold")
            o.write(", ".join(b for b in bits if b) + "\n")
        for level, text in sensors["findings"]:
            o.badge(level, level)
            o.write(f"  {gc.convert_temps(text)}\n")
        o.write("\nTemperatures at idle don't tell you much. Check again right after gaming, or use "
                "the Performance tab's monitor while you play.\n", "small")
        o.done()


# =============================================================================
# Performance: bottleneck monitor + benchmark
# =============================================================================
class Graph(tk.Canvas):
    SERIES = [("cpu", "CPU, all cores", BLUE), ("core_max", "Busiest core", "#5b7cae"),
              ("gpu", "GPU", GREEN)]

    def __init__(self, parent):
        super().__init__(parent, height=px(200), bg=CARD, highlightthickness=0)
        self.data = []
        self.bind("<Configure>", lambda e: self.redraw())

    def push(self, sample):
        self.data.append(sample)
        self.data = self.data[-120:]
        self.redraw()

    def reset(self):
        self.data = []
        self.redraw()

    def redraw(self):
        self.delete("all")
        w, h = self.winfo_width(), self.winfo_height()
        left, top, bottom = px(44), px(14), px(30)
        ph = h - top - bottom
        for pct in (0, 50, 100):
            y = top + ph * (1 - pct / 100)
            self.create_line(left, y, w - px(12), y, fill=LINE)
            self.create_text(left - 6, y, text=f"{pct}%", anchor="e", fill=MUTED, font=base_font(8))
        x = left
        for key, label, color in self.SERIES:
            self.create_line(x, h - px(12), x + px(14), h - px(12), fill=color, width=px(3))
            self.create_text(x + px(20), h - px(12), text=label, anchor="w", fill=MUTED, font=base_font(9))
            x += px(40) + len(label) * px(7)
        if len(self.data) < 2:
            return
        step = (w - left - px(12)) / 119
        for key, _, color in self.SERIES:
            pts = []
            for i, s in enumerate(self.data):
                v = s.get(key)
                if v is None:
                    continue
                pts += [left + (120 - len(self.data) + i) * step, top + ph * (1 - min(v, 100) / 100)]
            if len(pts) >= 4:
                self.create_line(*pts, fill=color, width=px(2), smooth=True)


class PerformanceTab(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, padding=0)
        self.app = app
        self.monitor = None
        self.started = None
        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True)
        self._build_monitor(nb)
        self._build_bench(nb)

    # ---------- monitor ----------
    def _build_monitor(self, nb):
        f = ttk.Frame(nb, padding=(0, px(16), 0, 0))
        nb.add(f, text="Bottleneck monitor")
        ttk.Label(f, text="Start the monitor, play for 5 to 10 minutes, then stop it to see whether "
                          "your processor or graphics card is holding you back.",
                  style="Sub.TLabel", wraplength=px(900)).pack(anchor="w", pady=(0, 8))
        bar = _toolbar(f)
        ttk.Label(bar, text="What are you testing?").pack(side="left")
        self.label_var = tk.StringVar(value="")
        ttk.Entry(bar, textvariable=self.label_var, width=28).pack(side="left", padx=6)
        self.start_btn = ttk.Button(bar, text="Start monitor", style="Accent.TButton",
                                    command=self.toggle)
        self.start_btn.pack(side="left")
        self.live = ttk.Label(bar, text="", style="Sub.TLabel")
        self.live.pack(side="left", padx=12)
        self.graph = Graph(f)
        self.graph.pack(fill="x", pady=(0, px(14)))
        self.result = RichText(f, height=8)
        self.result.pack(fill="both", expand=True)

    def toggle(self):
        if self.monitor:
            self.stop()
        else:
            self.start()

    def start(self):
        self.graph.reset()
        self.monitor = hw_tools.Monitor(lambda s: self.after(0, self._on_sample, s))
        self.monitor.start()
        if self.monitor.error:
            messagebox.showinfo("Monitor", self.monitor.error)
            self.monitor = None
            return
        self.started = time.time()
        self.start_btn.configure(text="Stop and analyze")
        self.live.configure(text="Waiting for the first reading")
        self.app.set_status("Monitoring. Leave RigCheck running while you play.")

    def _on_sample(self, s):
        self.graph.push(s)
        parts = [f"CPU {s['cpu']:.0f}%" if s.get("cpu") is not None else "",
                 f"busiest core {s['core_max']:.0f}%" if s.get("core_max") is not None else "",
                 f"GPU {s['gpu']:.0f}%" if s.get("gpu") is not None else "",
                 f"RAM {s['ram']:.0f}%" if s.get("ram") is not None else "",
                 f"GPU {gc.fmt_temp(s['gpu_temp'])}" if s.get("gpu_temp") else ""]
        mins = int((time.time() - self.started) // 60)
        b = hw_tools.breakdown(self.monitor.samples) if self.monitor else None
        so_far = ""
        if b and b["active"] >= 5:
            top = max(("gpu", "cpu", "neither"), key=lambda k: b[k])
            name = {"gpu": "graphics card", "cpu": "processor", "neither": "neither part"}[top]
            so_far = f"   Limit so far: {name} {b[top]:.0f}%"
        self.live.configure(text=",  ".join(p for p in parts if p) + f"   ({mins} min){so_far}")

    def stop(self):
        mon, self.monitor = self.monitor, None
        mon.stop()
        self.start_btn.configure(text="Start monitor")
        self.live.configure(text="")
        res = hw_tools.analyze_session(mon.samples)
        label = self.label_var.get().strip()
        o = self.result
        o.clear()
        o.write((label + ": " if label else "") + "Result\n", "h1")
        if res.get("bottleneck"):
            o.badge({"GPU": "Graphics-limited", "CPU": "Processor-limited", "None": "Not limited"}[res["bottleneck"]],
                    {"GPU": "MEDIUM", "CPU": "MEDIUM", "None": "LOW"}[res["bottleneck"]])
            o.write("  ")
        o.write(res["verdict"] + "\n")
        res["details"] = [gc.convert_temps(d) for d in res["details"]]
        if res.get("breakdown"):
            o.write("\nWhat limited your frame rate\n", "label")
            bar = gc.BottleneckBar(o.text, width=560)
            bar.set(res["breakdown"])
            o.text.window_create("end", window=bar)
            o.write("\n")
            lost = res["breakdown"]["lost_gpu"]
            if lost >= 3:
                o.write(f"Graphics power left unused because of the processor: {lost:.0f}%\n", "muted")
            o.write("\n", "gap")
        for d in res["details"]:
            o.write(f"• {d}\n", "indent")
        if res.get("avg_cpu") is not None:
            o.write("\nAverages while playing: ", "label")
            bits = [f"CPU {res['avg_cpu']:.0f}%",
                    f"busiest core {res['avg_core_max']:.0f}%" if res.get("avg_core_max") else "",
                    f"GPU {res['avg_gpu']:.0f}%" if res.get("avg_gpu") is not None else "",
                    f"RAM {res['avg_ram']:.0f}%" if res.get("avg_ram") else ""]
            o.write(", ".join(b for b in bits if b) + "\n", "muted")
        if res.get("bottleneck") in ("GPU", "CPU"):
            o.write("\n")
            o.link(f"See {res['bottleneck']} upgrades that fit your PC", lambda: self.app.select_page("Overview"))
            o.write("\n")
        o.done()
        if res.get("bottleneck"):
            hw_store.add_history("monitor", {
                "label": label or "Monitor session", "minutes": round((time.time() - self.started) / 60, 1),
                "bottleneck": res["bottleneck"], "verdict": res["verdict"],
                "avg_cpu": res.get("avg_cpu"), "avg_core_max": res.get("avg_core_max"),
                "avg_gpu": res.get("avg_gpu"), "avg_ram": res.get("avg_ram"),
                "pct_gpu": (res.get("breakdown") or {}).get("gpu"),
                "pct_cpu": (res.get("breakdown") or {}).get("cpu"),
                "lost_gpu": (res.get("breakdown") or {}).get("lost_gpu")})
            self.app.refresh_history()
        self.app.set_status("Monitor stopped. Results are below and saved to History.")

    # ---------- benchmark ----------
    def _build_bench(self, nb):
        f = ttk.Frame(nb, padding=(0, px(16), 0, 0))
        nb.add(f, text="Quick benchmark")
        ttk.Label(f, text="Test processor, memory and drive speed in about a minute. Close games "
                          "and large downloads first for accurate results.",
                  style="Sub.TLabel", wraplength=px(900)).pack(anchor="w", pady=(0, 8))
        bar = _toolbar(f)
        self.bench_btn = ttk.Button(bar, text="Run benchmark", style="Accent.TButton",
                                    command=self.run_bench)
        self.bench_btn.pack(side="left")
        self.disk_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(bar, text="Include drives (writes a 1 GB temporary file to each)",
                        variable=self.disk_var).pack(side="left", padx=px(12))
        self.bench_status = ttk.Label(bar, text="", style="Sub.TLabel")
        self.bench_status.pack(side="left")
        self.bench_out = RichText(f)
        self.bench_out.pack(fill="both", expand=True)

    def run_bench(self):
        if not self.app.hw:
            return
        self.bench_btn.configure(state="disabled")

        def progress(msg):
            self.after(0, lambda: self.bench_status.configure(text=msg))
        in_thread(self, lambda: hw_tools.run_benchmark(progress, self.disk_var.get()), self._bench_done)

    def _bench_done(self, res, err):
        self.bench_btn.configure(state="normal")
        self.bench_status.configure(text="")
        o = self.bench_out
        o.clear()
        if err:
            o.write(f"Benchmark failed: {err}\n")
            o.done()
            return
        prev = [h for h in hw_store.load_history() if h["kind"] == "benchmark"]
        prev = prev[-1]["data"] if prev else None

        def delta(new, old):
            if not old or not new:
                return ""
            ch = new / old - 1
            return f"   ({'+' if ch >= 0 else ''}{ch:.0%} vs last run)"

        o.write("Results\n", "h1")
        c = res["cpu"]
        pc = prev["cpu"] if prev else {}
        o.write("CPU single-core: ", "bold")
        o.write(f"{c['single_mbs']:,} MB/s{delta(c['single_mbs'], pc.get('single_mbs'))}\n")
        o.write("CPU all cores: ", "bold")
        o.write(f"{c['multi_mbs']:,} MB/s ({c['scaling']}x one core)"
                f"{delta(c['multi_mbs'], pc.get('multi_mbs'))}\n")
        o.write("Memory copy: ", "bold")
        o.write(f"{res['ram']['copy_gbs']} GB/s"
                f"{delta(res['ram']['copy_gbs'], (prev or {}).get('ram', {}).get('copy_gbs'))}\n")
        for d in res["disks"]:
            o.write(f"Drive {d['drive']}: ", "bold")
            if d.get("skipped"):
                o.write(d["skipped"] + "\n", "muted")
                continue
            name = f"{d.get('name', '')} {d.get('bus') or d.get('type', '')}".strip()
            o.write(f"write {d['write_mbs']:,} MB/s, read {d['read_mbs'] or '?'} MB/s")
            if d.get("expected"):
                o.write(f"   (expected {d['expected']} for {name})", "muted")
            o.write("\n")
        o.write("\nFindings\n", "h1")
        for level, text in hw_tools.assess_benchmark(res, self.app.hw):
            o.badge(level, level)
            o.write(f"  {text}\n")
        o.write("\nScores are for comparing this PC over time (for example before and after "
                "enabling XMP), not against other computers.\n", "small")
        o.done()
        hw_store.add_history("benchmark", res)
        self.app.refresh_history()


# =============================================================================
# Updates
# =============================================================================
def _app_update_item():
    import app_info
    name = f"RigCheck {app_info.APP_VERSION}"
    if not app_info.UPDATE_REPO:
        return {"name": name, "status": "info", "link": None,
                "detail": "Automatic update checks switch on once RigCheck is published on GitHub "
                          "(README.md explains how)."}
    try:
        new = app_info.check_for_update()
    except Exception as e:
        return {"name": name, "status": "unknown", "link": None,
                "detail": f"Couldn't check for a newer version. {e}"}
    if new:
        return {"name": name, "status": "update", "detail": f"Version {new['version']} is available.",
                "link": {"label": f"Download RigCheck {new['version']}", "url": new["url"]}}
    return {"name": name, "status": "ok", "detail": "You have the latest version.", "link": None}


class UpdatesTab(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, padding=0)
        self.app = app
        bar = _toolbar(self)
        self.btn = ttk.Button(bar, text="Check drivers and BIOS", style="Accent.TButton",
                              command=self.check)
        self.btn.pack(side="left")
        if hwa.SYSTEM == "Windows":
            self.wu_btn = ttk.Button(bar, text="Check Windows Update", command=self.check_wu)
            self.wu_btn.pack(side="left", padx=px(8))
        self.out = RichText(self)
        self.out.pack(fill="both", expand=True)
        self.wu_result = None
        self.items = []

    def check(self):
        if not self.app.hw:
            return
        self.btn.configure(state="disabled")
        in_thread(self, lambda: hw_tools.check_updates(self.app.hw) + [_app_update_item()], self._done)

    def _done(self, items, err):
        self.btn.configure(state="normal")
        self.items = items or []
        self._render(err)

    def check_wu(self):
        self.wu_btn.configure(state="disabled")
        self.app.set_status("Asking Windows Update… this can take up to a minute.")
        in_thread(self, hw_tools.windows_update_pending, self._wu_done)

    def _wu_done(self, titles, err):
        self.wu_btn.configure(state="normal")
        self.app.set_status("Windows Update check complete")
        self.wu_result = ("error", str(err)) if err else ("ok", titles)
        self._render(None)

    def _render(self, err):
        o = self.out
        o.clear()
        if err:
            o.write(f"Check failed: {err}\n")
        labels = {"ok": "Up to date", "update": "Update available", "urgent": "Important",
                  "info": "Tip", "unknown": "Unknown"}
        order = {"urgent": 0, "update": 1, "unknown": 2, "info": 3, "ok": 4}
        for it in sorted(self.items, key=lambda x: order.get(x["status"], 5)):
            o.badge(labels[it["status"]], it["status"])
            o.write(f"  {it['name']}\n", "bold")
            o.write(it["detail"] + "\n", "indent")
            if it.get("link"):
                o.write("    ")
                o.link(it["link"]["label"], it["link"]["url"])
                o.write("\n")
            o.write("\n", "gap")
        if self.wu_result:
            kind, data = self.wu_result
            o.write("\nWindows Update\n", "h1")
            if kind == "error" or data is None:
                o.write("Couldn't reach Windows Update.\n", "muted")
            elif not data:
                o.badge("Up to date", "ok")
                o.write("  No pending updates.\n")
            else:
                o.badge(f"{len(data)} pending", "update")
                o.write("  Install them from Settings > Windows Update.\n")
                for t in data[:15]:
                    o.write(f"• {t}\n", "indent")
        if not self.items and not self.wu_result and not err:
            o.write("Check for outdated graphics drivers, BIOS and drive firmware.\n", "muted")
        o.done()


# =============================================================================
# Games: can I run it?
# =============================================================================
class GamesTab(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, padding=0)
        self.app = app
        self.sys_scores = None
        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True)
        page = ttk.Frame(nb, padding=(0, px(16), 0, 0))
        nb.add(page, text="Can I run it?")
        self.mods_panel = ModsPanel(nb, app)
        nb.add(self.mods_panel, text="Farming Simulator 25 mods")
        panes = ttk.PanedWindow(page, orient="horizontal")
        panes.pack(fill="both", expand=True)
        left = ttk.Frame(panes)
        frame, self.tree = make_tree(left, ["Game", "Verdict"], [210, 180], 20)
        frame.pack(fill="both", expand=True)
        btns = ttk.Frame(left, padding=(0, px(10), 0, 0))
        btns.pack(fill="x")
        ttk.Button(btns, text="Add a game…", command=self.add_game).pack(side="left")
        ttk.Button(btns, text="Remove game", command=self.remove_game).pack(side="left", padx=px(8))
        self.out = RichText(panes, width=40)
        panes.add(left, weight=1)
        panes.add(self.out, weight=1)
        for level, color in ((0, RED), (1, AMBER), (2, GREEN)):
            self.tree.tag_configure(f"lvl{level}", foreground=color)
        self.tree.bind("<<TreeviewSelect>>", self.show)

    def games(self):
        custom = [games_db.custom_game(**g) for g in self.app.settings.get("custom_games", [])]
        return custom + games_db.GAMES

    def refresh(self):
        if not self.app.hw:
            return
        self.sys_scores = games_db.system_scores(self.app.hw)
        self.tree.delete(*self.tree.get_children())
        for i, g in enumerate(self.games()):
            r = games_db.check_game(g, self.sys_scores)
            name = g["name"] + ("  (added by you)" if g.get("custom") else "")
            self.tree.insert("", "end", iid=str(i), text=name, values=(r["short"],),
                             tags=(f"lvl{r['level']}",))
        kids = self.tree.get_children()
        if kids:
            self.tree.selection_set(kids[0])

    def show(self, _e=None):
        sel = self.tree.selection()
        if not sel or not self.sys_scores:
            return
        g = self.games()[int(sel[0])]
        r = games_db.check_game(g, self.sys_scores)
        o = self.out
        o.clear()
        o.write(g["name"] + "\n", "h1")
        o.badge(r["verdict"], ["bad", "update", "good"][r["level"]])
        o.write("\n\n")
        names = {"Processor": gc_short_cpu(self.app.hw), "Graphics": gc_short_gpu(self.app.hw)}
        for label, have, text, level in r["rows"]:
            o.write(f"{label}  ", "label")
            o.write(f"{names.get(label) or have}   ")
            o.colored(text + "\n", {"bad": "bad", "ok": "update", "good": "good"}.get(level, "unknown"))
        o.write("\nRequirements\n", "h2")
        for key, title in (("min", "Minimum"), ("rec", "Recommended")):
            req = g.get(key)
            if not req:
                continue
            o.write(f"{title}: ", "label")
            bits = [" / ".join(req["cpus"]), " / ".join(req["gpus"]),
                    f"{req['ram']} GB RAM" if req.get("ram") else "",
                    f"{req['vram']} GB VRAM" if req.get("vram") else "",
                    f"{req['storage']} GB storage" if req.get("storage") else ""]
            o.write(",  ".join(b for b in bits if b) + "\n", "muted")
        if g.get("note"):
            o.write("\nNote: ", "bold")
            o.write(g["note"] + "\n")
        if r["limiting"] and r["level"] < 2:
            o.write("\nHolding you back: ", "bold")
            o.write(", ".join(r["limiting"]) + ".  ")
            o.link("See upgrades that fit your PC", lambda: self.app.select_page("Overview"))
            o.write("\n")
        o.write(f"\n{games_db.REQ_DATE}. Scores are rough estimates; the store page has the "
                "final word.\n", "small")
        o.done()

    def add_game(self):
        dlg = CustomGameDialog(self, self.app)
        self.wait_window(dlg)
        if dlg.result:
            self.app.settings.setdefault("custom_games", []).append(dlg.result)
            self.app.save_settings()
            self.refresh()

    def remove_game(self):
        sel = self.tree.selection()
        if not sel:
            return
        g = self.games()[int(sel[0])]
        if not g.get("custom"):
            messagebox.showinfo("Games", "Only games you added yourself can be removed.")
            return
        customs = self.app.settings.get("custom_games", [])
        self.app.settings["custom_games"] = [c for c in customs if c["name"] != g["name"]]
        self.app.save_settings()
        self.refresh()


def gc_short_cpu(hw):
    import re
    n = re.sub(r"\(R\)|\(TM\)|\d+th Gen|CPU|Processor|@.*|\d+-Core", "", hw["cpu"]["name"] or "")
    return re.sub(r"\s+", " ", n).strip() or None


def gc_short_gpu(hw):
    import re
    rated = [(parts_db.gpu_score(g["name"]) or 0, g["name"]) for g in hw["gpu"]]
    return re.sub(r"^(NVIDIA|AMD|Intel\(R\))\s+", "", max(rated)[1]) if rated else None


class CustomGameDialog(tk.Toplevel):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.title("Add a game")
        self.configure(bg=BG)
        gc.dark_title_bar(self)
        self.result = None
        self.transient(parent)
        self.grab_set()
        cpus = sorted(games_db.REQ_CPU) + sorted(
            {c["name"] for p in parts_db.PLATFORMS.values() for c in p["cpu_upgrades"]})
        gpus = sorted(games_db.REQ_GPU) + [g["name"] for g in parts_db.GPU_CATALOG]
        f = ttk.Frame(self, padding=px(24))
        f.pack(fill="both", expand=True)
        ttk.Label(f, text="Copy the requirements from the game's store page. If a part isn't "
                          "listed, pick the closest match.", style="Sub.TLabel",
                  wraplength=px(440)).grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 10))
        self.vars = {}
        rows = [("name", "Game name", None), ("min_cpu", "Minimum CPU", cpus),
                ("min_gpu", "Minimum GPU", gpus), ("min_ram", "Minimum RAM (GB)", None),
                ("rec_cpu", "Recommended CPU", cpus), ("rec_gpu", "Recommended GPU", gpus),
                ("rec_ram", "Recommended RAM (GB)", None), ("vram", "VRAM needed (GB)", None),
                ("storage", "Storage (GB)", None)]
        for i, (key, label, values) in enumerate(rows, start=1):
            ttk.Label(f, text=label).grid(row=i, column=0, sticky="w", pady=3)
            var = tk.StringVar()
            w = ttk.Combobox(f, textvariable=var, values=values, width=34) if values else \
                ttk.Entry(f, textvariable=var, width=36)
            w.grid(row=i, column=1, sticky="w", pady=3)
            self.vars[key] = var
        b = ttk.Frame(f)
        b.grid(row=len(rows) + 1, column=0, columnspan=2, sticky="e", pady=(12, 0))
        ttk.Button(b, text="Cancel", command=self.destroy).pack(side="right")
        ttk.Button(b, text="Add game", style="Accent.TButton", command=self.ok).pack(side="right", padx=6)

    def ok(self):
        v = {k: var.get().strip() for k, var in self.vars.items()}
        if not v["name"] or not (v["min_cpu"] or v["min_gpu"] or v["min_ram"]):
            messagebox.showwarning("Add a game", "Enter a name and at least one minimum requirement.",
                                   parent=self)
            return

        def num(x):
            try:
                return float(x) if x else None
            except ValueError:
                return None
        self.result = {"name": v["name"], "min_cpu": v["min_cpu"] or None, "min_gpu": v["min_gpu"] or None,
                       "min_ram": num(v["min_ram"]), "rec_cpu": v["rec_cpu"] or None,
                       "rec_gpu": v["rec_gpu"] or None, "rec_ram": num(v["rec_ram"]),
                       "vram": num(v["vram"]), "storage": num(v["storage"])}
        self.destroy()


# =============================================================================
# Install and BIOS guides
# =============================================================================
class GuideDialog(tk.Toplevel):
    def __init__(self, app, key):
        import guides
        super().__init__(app)
        g = guides.get_guide(key, app.hw)
        self.title(g["title"])
        self.configure(bg=BG)
        self.geometry(f"{px(640)}x{px(680)}")
        self.transient(app)
        gc.dark_title_bar(self)
        out = RichText(self)
        out.pack(fill="both", expand=True, padx=px(16), pady=(px(16), 0))
        o = out
        o.clear()
        o.write(g["title"] + "\n", "h1")
        o.write(g["intro"] + "\n", "muted")
        if g["needs"]:
            o.write("\nYou'll need\n", "h2")
            for n in g["needs"]:
                o.write(f"•  {n}\n")
        o.write("\nSteps\n", "h2")
        for i, step in enumerate(g["steps"], 1):
            o.write(f"{i}.  ", "num")
            o.write(step + "\n")
            o.write("\n", "gap")
        if g["tips"]:
            o.write("Tips\n", "h2")
            for t in g["tips"]:
                o.write(f"•  {t}\n", "muted")
        o.done()
        b = ttk.Frame(self, padding=px(16))
        b.pack(fill="x")
        ttk.Button(b, text="Close", command=self.destroy).pack(side="right")


# =============================================================================
# Free speed-ups
# =============================================================================
class RefreshConfirm(tk.Toplevel):
    """After switching refresh rate: keep it, or it reverts on its own in 15 seconds."""

    def __init__(self, app, device, new_hz, old_hz, on_done):
        super().__init__(app)
        self.device, self.old_hz, self.on_done, self.left = device, old_hz, on_done, 15
        self.title("Keep this refresh rate?")
        self.configure(bg=BG)
        self.transient(app)
        gc.dark_title_bar(self)
        self.attributes("-topmost", True)
        f = ttk.Frame(self, padding=px(24))
        f.pack(fill="both", expand=True)
        ttk.Label(f, text=f"Your monitor is now at {new_hz} Hz", style="Section.TLabel").pack(anchor="w")
        self.msg = ttk.Label(f, style="Sub.TLabel", wraplength=px(380))
        self.msg.pack(anchor="w", pady=(px(6), px(18)))
        b = ttk.Frame(f)
        b.pack(fill="x")
        ttk.Button(b, text="Go back", command=self.revert).pack(side="right")
        ttk.Button(b, text="Keep it", style="Accent.TButton", command=self.keep).pack(side="right", padx=px(8))
        self.protocol("WM_DELETE_WINDOW", self.revert)
        self.tick()

    def tick(self):
        if not self.winfo_exists():
            return
        self.msg.configure(text=f"If everything looks right, keep it. Otherwise it goes back to "
                                f"{self.old_hz} Hz in {self.left} seconds.")
        if self.left <= 0:
            self.revert()
            return
        self.left -= 1
        self.after(1000, self.tick)

    def keep(self):
        self.destroy()
        self.on_done(True)

    def revert(self):
        import perf_checks
        perf_checks.set_refresh_rate(self.device, self.old_hz)
        self.destroy()
        self.on_done(False)


class SpeedupsTab(ttk.Frame):
    STATUS = {"fix": ("Worth fixing", "warn"), "tip": ("Tip", "info"), "ok": ("Good", "good"),
              "unknown": ("Couldn't check", "unknown")}

    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.checks = []
        bar = _toolbar(self)
        self.btn = ttk.Button(bar, text="Check again", style="Accent.TButton", command=self.check)
        self.btn.pack(side="left")
        ttk.Label(bar, text="Settings that quietly cost performance, with fixes that don't cost anything.",
                  style="Sub.TLabel").pack(side="left", padx=px(12))
        self.out = RichText(self)
        self.out.pack(fill="both", expand=True)

    def check(self):
        if not self.app.hw:
            return
        import perf_checks
        self.btn.configure(state="disabled")
        in_thread(self, lambda: perf_checks.run_checks(self.app.hw, self.app.recs), self._done)

    def _done(self, checks, err):
        self.btn.configure(state="normal")
        self.checks = checks or []
        o = self.out
        o.clear()
        if err:
            o.write(f"The checks stopped with an error: {err}\n")
            o.done()
            return
        todo = [c for c in self.checks if c["status"] in ("fix", "tip")]
        good = [c for c in self.checks if c["status"] == "ok"]
        fixes = sum(c["status"] == "fix" for c in todo)
        if todo:
            o.write(f"{len(todo)} free speed-up{'s' if len(todo) != 1 else ''} found\n", "h1")
            if fixes:
                o.write(f"{fixes} {'are' if fixes != 1 else 'is'} worth fixing now.\n", "muted")
        else:
            o.write("Everything is set up well\n", "h1")
        self.app.set_speedup_count(fixes)
        for c in todo + [c for c in self.checks if c["status"] == "unknown"]:
            o.write("\n", "gap")
            label, color = self.STATUS[c["status"]]
            o.badge(label, color)
            o.write(f"  {c['title']}\n", "h2")
            o.write(c["detail"] + "\n", "muted")
            if c.get("restart"):
                o.write("Takes effect after a restart.\n", "small")
            if c.get("action"):
                o.link(c["action"]["label"], lambda c=c: self.act(c), ("boldlink",))
                o.write("\n")
            o.rule()
        if good:
            o.write("Already set up well\n", "h2")
            for c in good:
                o.colored("✓  ", "good")
                o.write(f"{c['title']}. ", "bold")
                o.write(c["detail"] + "\n", "muted")
        o.done()

    def act(self, c):
        import perf_checks
        a = c["action"]
        if a["type"] == "guide":
            self.app.open_guide(a["arg"])
            return
        if a["type"] == "page":
            self.app.select_page(a["arg"])
            return
        if c["id"].startswith("refresh:"):
            device, new_hz, old_hz = a["arg"]
            if not messagebox.askyesno("Change refresh rate",
                                       f"Switch this monitor to {new_hz} Hz? The screen may go black "
                                       "for a second. You'll be asked to keep it, and it switches back "
                                       "on its own if you don't answer."):
                return
            msg = perf_checks.apply_fix(c)
            if "Switched" in msg:
                RefreshConfirm(self.app, device, new_hz, old_hz,
                               lambda kept: (self.app.set_status(
                                   f"Monitor set to {new_hz} Hz." if kept else f"Went back to {old_hz} Hz."),
                                   self.check()))
            else:
                messagebox.showinfo("Refresh rate", msg)
            return
        try:
            msg = perf_checks.apply_fix(c)
        except OSError as e:
            msg = f"Windows didn't allow the change ({e}). Try running RigCheck as administrator."
        self.app.set_status(msg)
        self.check()


# =============================================================================
# Share: rig card and comparing with a friend
# =============================================================================
class ShareTab(ttk.Frame):
    def __init__(self, parent, app):
        import share
        super().__init__(parent)
        self.app = app
        self.card_path = None
        self.photo = None
        self.friend = None
        self.body = ttk.Frame(self)
        self.body.pack(fill="both", expand=True)
        self.body.columnconfigure(0, weight=3)
        self.body.columnconfigure(1, weight=2)
        self.body.rowconfigure(1, weight=1)

        # rig card
        left = ttk.Frame(self.body)
        left.grid(row=0, column=0, rowspan=2, sticky="nsew", padx=(0, px(20)))
        ttk.Label(left, text="Rig card", style="Section.TLabel").pack(anchor="w")
        ttk.Label(left, text="An image of your PC to post on Discord or Reddit, or send to a friend.",
                  style="Sub.TLabel").pack(anchor="w", pady=(px(2), px(10)))
        row = ttk.Frame(left)
        row.pack(fill="x", pady=(0, px(10)))
        ttk.Label(row, text="Name").pack(side="left")
        default = self.app.settings.get("rig_name") or f"{_user_name()}'s rig"
        self.name_var = tk.StringVar(value=default)
        e = ttk.Entry(row, textvariable=self.name_var, width=28)
        e.pack(side="left", padx=px(8))
        e.bind("<Return>", lambda _e: self.render_card())
        ttk.Button(row, text="Update card", command=self.render_card).pack(side="left")
        self.card_label = tk.Label(left, bg=CARD, fg=MUTED, text="The card appears after the scan.",
                                   font=base_font(10), justify="left", wraplength=px(500))
        self.card_label.pack(fill="both", expand=True)
        self.card_label.bind("<Configure>", lambda e: self.after_idle(self._show_preview))
        btns = ttk.Frame(left)
        btns.pack(fill="x", pady=(px(10), 0))
        if hwa.SYSTEM == "Windows":
            ttk.Button(btns, text="Copy image", style="Accent.TButton", command=self.copy).pack(side="left")
        ttk.Button(btns, text="Save image…", command=self.save).pack(side="left", padx=px(8))
        self.pillow_ok = share.pillow_available()

        # compare
        right = ttk.Frame(self.body)
        right.grid(row=0, column=1, rowspan=2, sticky="nsew")
        ttk.Label(right, text="Compare with a friend", style="Section.TLabel").pack(anchor="w")
        ttk.Label(right, text="Export your rig and send the file to a friend who has RigCheck. "
                              "Load theirs to see whose PC wins where.", style="Sub.TLabel",
                  wraplength=px(380)).pack(anchor="w", pady=(px(2), px(10)))
        b2 = ttk.Frame(right)
        b2.pack(fill="x", pady=(0, px(10)))
        ttk.Button(b2, text="Export my rig…", command=self.export).pack(side="left")
        ttk.Button(b2, text="Load a friend's rig…", style="Accent.TButton",
                   command=self.load_friend).pack(side="left", padx=px(8))
        self.cmp = RichText(right, width=40)
        self.cmp.pack(fill="both", expand=True)

    def snapshot(self):
        self.app.settings["rig_name"] = self.name_var.get().strip() or "My rig"
        self.app.save_settings()
        return self.app.make_snapshot(self.app.settings["rig_name"])

    def render_card(self):
        import share
        if not self.app.hw:
            return
        if not self.pillow_ok:
            self.card_label.configure(text="Rig cards need the Pillow library. Run  pip install pillow  "
                                           "and restart RigCheck. (The .exe version includes it.)")
            return
        path = os.path.join(hw_store.data_dir(), "rig_card.png")
        share.make_card(self.snapshot(), path, self.app.profile_label())
        self.card_path = path
        self._show_preview()

    def _show_preview(self, _e=None):
        """Scale the saved card to fit the space available."""
        if not self.card_path:
            return
        from PIL import Image
        width = self.card_label.winfo_width() - px(8)
        width = min(1200, width if width > px(200) else px(560))
        if getattr(self, "_shown_width", None) == width and self.photo:
            return
        img = Image.open(self.card_path).resize((width, round(width * 630 / 1200)), Image.LANCZOS)
        preview = os.path.join(hw_store.data_dir(), "rig_card_preview.png")
        img.save(preview)
        self.photo = tk.PhotoImage(file=preview)
        self._shown_width = width
        self.card_label.configure(image=self.photo, text="")

    def copy(self):
        import share
        if not self.card_path:
            self.render_card()
        if self.card_path and share.copy_image_to_clipboard(self.card_path):
            self.app.set_status("Card copied. Paste it into Discord or anywhere with Ctrl+V.")
        else:
            self.app.set_status("The card couldn't be copied. Use Save image instead.")

    def save(self):
        import share
        import shutil as sh
        if not self.card_path:
            self.render_card()
        if not self.card_path:
            return
        name = re.sub(r"[^\w\- ]", "", self.name_var.get()).strip().replace(" ", "_") or "rig"
        path = filedialog.asksaveasfilename(title="Save rig card", defaultextension=".png",
                                            initialdir=share.default_card_folder(),
                                            initialfile=f"{name}.png", filetypes=[("PNG image", "*.png")])
        if path:
            sh.copyfile(self.card_path, path)
            self.app.set_status(f"Card saved to {path}")

    def export(self):
        import share
        if not self.app.hw:
            return
        name = re.sub(r"[^\w\- ]", "", self.name_var.get()).strip().replace(" ", "_") or "rig"
        path = filedialog.asksaveasfilename(title="Export my rig", defaultextension=share.FILE_EXT,
                                            initialfile=f"{name}{share.FILE_EXT}",
                                            filetypes=[("RigCheck rig", f"*{share.FILE_EXT}")])
        if path:
            share.export_rig(self.snapshot(), path)
            self.app.set_status(f"Rig exported. Send {os.path.basename(path)} to your friend.")

    def load_friend(self):
        import share
        if not self.app.hw:
            return
        path = filedialog.askopenfilename(title="Load a friend's rig",
                                          filetypes=[("RigCheck rig", f"*{share.FILE_EXT}"),
                                                     ("All files", "*.*")])
        if not path:
            return
        try:
            self.friend = share.import_rig(path)
        except (OSError, ValueError, json.JSONDecodeError) as e:
            messagebox.showerror("Compare", f"That file couldn't be loaded.\n\n{e}")
            return
        self.show_compare()

    def show_compare(self):
        import share
        if not self.friend:
            return
        mine = self.snapshot()
        c = share.compare(mine, self.friend)
        them = self.friend["name"]
        o = self.cmp
        o.clear()
        o.write(f"You vs {them}\n", "h1")
        if c["wins"] > c["losses"]:
            o.colored(f"Your rig comes out ahead on {c['wins']} of {len(c['rows'])} parts.\n", "good")
        elif c["losses"] > c["wins"]:
            o.colored(f"{them} comes out ahead on {c['losses']} of {len(c['rows'])} parts.\n", "warn")
        else:
            o.write("An even match.\n", "muted")
        for r in c["rows"]:
            o.write("\n", "gap")
            o.write(r["label"] + "\n", "label")
            for who, key in (("You", "mine"), (them, "theirs")):
                win = r["winner"] == key
                o.write(f"{who}:  ", "muted")
                o.write(r[key], "bold" if win else ())
                if win and r["detail"]:
                    o.colored(f"   {r['detail']}", "good")
                o.write("\n")
        if c["games"]:
            better = [g for g in c["games"] if g["winner"] == "mine"]
            worse = [g for g in c["games"] if g["winner"] == "theirs"]
            o.write("\nGames\n", "h2")
            o.write(f"You run {len(better)} better, {them} runs {len(worse)} better, and "
                    f"{len(c['games']) - len(better) - len(worse)} run the same.\n", "muted")
            for g in (better + worse)[:10]:
                o.write(f"{g['name']}\n", "bold")
                o.write(f"{g['mine']['short'].split(',')[0]} for you, "
                        f"{g['theirs']['short'].split(',')[0].lower()} for {them}\n", "muted")
        o.done()

    def refresh(self):
        self.after(100, self.render_card)
        if self.friend:
            self.show_compare()


def _user_name():
    try:
        import getpass
        return getpass.getuser().split("\\")[-1].split(".")[0].title() or "My"
    except Exception:
        return "My"


# =============================================================================
# Farming Simulator 25 mods
# =============================================================================
class ModsPanel(ttk.Frame):
    STATUS = {"bad": "Won't load", "warn": "Problem", "map": "Map", "ok": "OK"}

    def __init__(self, parent, app):
        import mods
        super().__init__(parent, padding=(0, px(16), 0, 0))
        self.app = app
        self.result = None
        self.path = mods.mods_dir()
        bar = _toolbar(self)
        self.btn = ttk.Button(bar, text="Check my mods", style="Accent.TButton", command=self.check)
        self.btn.pack(side="left")
        ttk.Button(bar, text="Choose folder…", command=self.choose).pack(side="left", padx=px(8))
        ttk.Button(bar, text="Open mods folder",
                   command=lambda: hw_tools.open_in_file_manager(self.path)).pack(side="left")
        self.path_label = ttk.Label(self, text=self.path, style="Sub.TLabel")
        self.path_label.pack(anchor="w", pady=(0, px(10)))
        panes = ttk.PanedWindow(self, orient="horizontal")
        panes.pack(fill="both", expand=True)
        frame, self.tree = make_tree(panes, ["Mod", "Size", "Status"], [260, 90, 100], 16)
        self.tree.tag_configure("bad", foreground=RED)
        self.tree.tag_configure("warn", foreground=AMBER)
        self.tree.tag_configure("map", foreground=BLUE)
        self.tree.bind("<<TreeviewSelect>>", self.show_mod)
        self.tree.bind("<Double-1>", lambda _e: self._open_selected())
        self.out = RichText(panes, width=40)
        panes.add(frame, weight=1)
        panes.add(self.out, weight=1)

    def choose(self):
        path = filedialog.askdirectory(initialdir=self.path if os.path.isdir(self.path) else None)
        if path:
            self.path = path
            self.path_label.configure(text=path)
            self.check()

    def check(self):
        import mods
        vram = max((g.get("vram_gb") or 0) for g in self.app.hw["gpu"]) if self.app.hw and self.app.hw["gpu"] else None
        self.btn.configure(state="disabled")

        def progress(msg):
            self.after(0, lambda: self.path_label.configure(text=msg))
        in_thread(self, lambda: mods.analyze(self.path, vram, progress), self._done)

    def _status(self, m):
        if not m["loads"]:
            return "bad"
        if m["problems"]:
            return "warn"
        return "map" if m["is_map"] else "ok"

    def _done(self, res, err):
        self.btn.configure(state="normal")
        self.path_label.configure(text=self.path)
        self.result = res
        t = self.tree
        t.delete(*t.get_children())
        o = self.out
        o.clear()
        if err or not res:
            o.write(f"The check stopped with an error: {err}\n")
            o.done()
            return
        if not res["found"]:
            o.write("No Farming Simulator 25 mods folder here\n", "h1")
            o.write(f"RigCheck looked in {res['path']}. If you keep mods somewhere else, use Choose folder.\n",
                    "muted")
            o.done()
            return
        order = {"bad": 0, "warn": 1, "map": 2, "ok": 3}
        for i, m in sorted(enumerate(res["mods"]), key=lambda x: (order[self._status(x[1])], -x[1]["size"])):
            st = self._status(m)
            t.insert("", "end", iid=str(i), text=m["file"], values=(hw_tools.human(m["size"]), self.STATUS[st]),
                     tags=(st,) if st != "ok" else ())
        self._summary()

    def _summary(self):
        res, o = self.result, self.out
        o.clear()
        o.write(f"{len(res['mods'])} mods, {hw_tools.human(res['total'])}\n", "h1")
        for level, text in res["summary"]:
            o.badge({"bad": "Won't load", "warn": "Check", "info": "Note", "good": "Good"}[level],
                    {"info": "info"}.get(level, level))
            o.write(f"  {text}\n")
            o.write("\n", "gap")
        if res["savegames"]:
            o.write("Savegames\n", "h2")
            for sg in res["savegames"]:
                o.write(f"{sg['name']}  ", "bold")
                o.write(f"{sg['mods']} mods, {hw_tools.human(sg['bytes'])}"
                        + (f", {len(sg['missing'])} missing" if sg["missing"] else "") + "\n", "muted")
        o.write("\nSelect a mod for details. Sizes are file sizes; in-game memory use is higher.\n", "small")
        o.done()

    def show_mod(self, _e=None):
        sel = self.tree.selection()
        if not sel or not self.result:
            return
        m = self.result["mods"][int(sel[0])]
        o = self.out
        o.clear()
        o.write((m["title"] or m["file"]) + "\n", "h1")
        facts = [f"version {m['version']}" if m["version"] else "", f"by {m['author']}" if m["author"] else "",
                 hw_tools.human(m["size"]), "map" if m["is_map"] else ""]
        o.write(gc.sentence(", ".join(f for f in facts if f)) + "\n", "muted")
        o.write(m["file"] + "\n", "small")
        o.write("\n", "gap")
        if m["problems"]:
            for p in m["problems"]:
                o.colored("•  ", "bad" if not m["loads"] else "warn")
                o.write(p + "\n")
        else:
            o.colored("No problems found.\n", "good")
        o.write("\n")
        o.link("Show in folder", lambda: hw_tools.open_in_file_manager(m["path"]))
        o.write("      ")
        o.link("Back to summary", self._summary)
        o.write("\n")
        o.done()

    def _open_selected(self):
        sel = self.tree.selection()
        if sel and self.result:
            hw_tools.open_in_file_manager(self.result["mods"][int(sel[0])]["path"])
