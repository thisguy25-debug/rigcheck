"""The Games page: installed games, how much you play them, and which to remove to free space."""

import datetime
import time
import tkinter as tk
from tkinter import ttk, messagebox

import game_storage
import hw_tools
import gui_common as gc
from gui_common import (RichText, in_thread, make_tree, px, base_font, AMBER, RED, MUTED, GREEN)

LABELS = {"remove": "Remove", "maybe": "Maybe", "keep": "Keep"}


def _when(ts, exact):
    if not ts:
        return "Never" if exact else "Unknown"
    days = (time.time() - ts) / 86400
    text = ("Today" if days < 1 else "Yesterday" if days < 2 else f"{days:.0f} days ago" if days < 45
            else f"{days / 30:.0f} months ago" if days < 540 else f"{days / 365:.1f} years ago")
    return text if exact else f"About {text.lower()}"


def _played(mins):
    if mins is None:
        return "Not tracked"
    if mins == 0:
        return "Never"
    return f"{mins} min" if mins < 60 else f"{mins / 60:,.1f} h" if mins < 6000 else f"{mins / 60:,.0f} h"


class GamesTab(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.result = None
        bar = ttk.Frame(self)
        bar.pack(fill="x", pady=(0, px(10)))
        self.scan_btn = ttk.Button(bar, text="Scan games", style="Accent.TButton", command=self.scan)
        self.scan_btn.pack(side="left")
        self.status = ttk.Label(bar, text="Finds your Steam, Epic and Xbox games and the ones you rarely play.",
                                style="Sub.TLabel")
        self.status.pack(side="left", padx=px(12))
        self.summary = RichText(self, height=3)
        self.summary.pack(fill="x", pady=(0, px(10)))
        body = ttk.Frame(self)
        body.pack(fill="both", expand=True)
        body.columnconfigure(0, weight=3)
        body.columnconfigure(1, weight=2, minsize=px(300))
        body.rowconfigure(0, weight=1)
        frame, self.tree = make_tree(body, ["Game", "Size", "Played", "Last played", "Suggestion"],
                                     [190, 75, 70, 115, 95], 16)
        for col in ("Size", "Played"):
            self.tree.column(col, anchor="e")
            self.tree.heading(col, anchor="e")
        self.tree.tag_configure("remove", foreground=RED)
        self.tree.tag_configure("maybe", foreground=AMBER)
        self.tree.tag_configure("keep", foreground=MUTED)
        self.tree.bind("<<TreeviewSelect>>", self.show)
        frame.grid(row=0, column=0, sticky="nsew", padx=(0, px(12)))
        self.detail = RichText(body, width=36)
        self.detail.grid(row=0, column=1, sticky="nsew")
        self._scanned = False
        app.notebook.bind("<<NotebookTabChanged>>", self._on_tab, add="+")

    def _on_tab(self, _e=None):
        try:
            visible = self.app.notebook.select() == str(self)
        except tk.TclError:
            return
        if visible and not self._scanned:
            self.scan()

    def scan(self):
        self._scanned = True
        self.scan_btn.state(["disabled"])

        def progress(msg):
            self.after(0, lambda: self.status.configure(text=msg))
        in_thread(self, lambda: game_storage.scan(progress), self._done)

    def _done(self, res, err):
        self.scan_btn.state(["!disabled"])
        if err or res is None:
            self.status.configure(text=f"The scan didn't finish: {err}")
            return
        self.result = res
        games = res["games"]
        self.status.configure(text=f"Scanned at {datetime.datetime.now().strftime('%I:%M %p').lstrip('0')}. "
                                   "Steam has exact play time; other launchers are estimated.")
        o = self.summary
        o.clear()
        if not games:
            o.write("No installed games found\n", "h2")
            o.write("RigCheck looks for Steam, Epic Games and Xbox app games.\n", "muted")
        else:
            gb = res["suggested"] / 1024 ** 3
            n = sum(g["level"] == "remove" for g in games)
            if n:
                o.write(f"You could free about {gb:,.0f} GB", "h1")
                o.write(f" by removing {n} game{'s' if n != 1 else ''} you rarely or never play.\n", "muted")
            else:
                o.write("Nothing obvious to remove", "h1")
                o.write("  You play the games you have installed.\n", "muted")
            o.write(f"{len(games)} games use {res['total'] / 1024 ** 3:,.0f} GB in total. "
                    "Select a game for details.\n", "small")
        o.done()
        t = self.tree
        t.delete(*t.get_children())
        for i, g in enumerate(games):
            t.insert("", "end", iid=str(i), text=f"{g['name']}  ·  {g['launcher']}",
                     values=(hw_tools.human(g["size"]), _played(g["minutes"]), _when(g["last_played"], g["exact"]),
                             LABELS[g["level"]]), tags=(g["level"],))
        if games:
            t.selection_set("0")

    def show(self, _e=None):
        sel = self.tree.selection()
        if not sel or not self.result:
            return
        g = self.result["games"][int(sel[0])]
        o = self.detail
        o.clear()
        o.write(g["name"] + "\n", "h1")
        o.write(f"{g['launcher']}  ·  {hw_tools.human(g['size'])}\n", "muted")
        o.write("\n", "gap")
        o.badge(LABELS[g["level"]], {"remove": "bad", "maybe": "update", "keep": "good"}[g["level"]])
        o.write("  " + g["reason"] + "\n")
        o.write("\n", "gap")
        o.write("Time played  ", "label")
        o.write(_played(g["minutes"]) + "\n")
        o.write("Last played  ", "label")
        o.write(_when(g["last_played"], g["exact"]) + "\n")
        if not g["exact"]:
            o.write(f"{g['launcher']} doesn't record play time on this PC, so the last-played date is "
                    "estimated from when the game last saved its settings.\n", "small")
        o.write("\n")
        if g["level"] != "keep":
            o.link(f"Uninstall with {g['launcher'] if g['launcher'] != 'Xbox' else 'Windows'}",
                   lambda: self.uninstall(g), ("boldlink",))
            o.write("\n")
        o.link("Show in folder", lambda: hw_tools.open_in_file_manager(g["folder"]))
        o.write("\n\n")
        o.write("RigCheck never deletes game files itself. Uninstalling goes through the game's launcher, "
                "which keeps your cloud saves, and you can reinstall any time.\n", "small")
        o.done()

    def uninstall(self, g):
        if not messagebox.askyesno("Uninstall", f"Uninstall {g['name']} to free about "
                                                f"{hw_tools.human(g['size'])}?\n\n{g['launcher'] if g['launcher'] != 'Xbox' else 'Windows'} "
                                                "will ask you to confirm."):
            return
        msg = game_storage.uninstall(g)
        self.app.set_status(msg + " Click Scan games afterwards to update this list.")
