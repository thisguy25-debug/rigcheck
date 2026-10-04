"""RigCheck look-and-feel: an instrument-panel dark theme and shared widgets."""

import threading
import tkinter as tk
import tkinter.font as tkfont
import webbrowser
from tkinter import ttk

import hw_advisor as hwa

# ---------------------------------------------------------------- palette
BG = "#1a2029"         # window background (graphite blue)
SIDEBAR = "#151a22"    # navigation rail
CARD = "#212834"       # panels
RAISED = "#2a3240"     # buttons, empty meter segments
LINE = "#343d4c"       # hairlines and borders
TEXT = "#e8ebf1"
MUTED = "#98a2b3"
ACCENT = "#43b9cc"     # teal: primary actions, links, selection
ACCENT_HOVER = "#62c9d9"
ACCENT_DIM = "#23434d"
ON_COLOR = "#10161d"   # text on colored backgrounds
GREEN, AMBER, RED, BLUE = "#56c48b", "#e9b44c", "#ef6a64", "#6aa8ff"

COLORS = {
    "FREE": GREEN, "HIGH": RED, "MEDIUM": AMBER, "LOW": BLUE,
    "Good": GREEN, "Caution": AMBER, "Bad": RED, "Unknown": MUTED, "Info": BLUE,
    "ok": GREEN, "update": AMBER, "urgent": RED, "info": BLUE, "unknown": MUTED,
    "good": GREEN, "bad": RED, "warn": AMBER,
}
PRIORITY_LABELS = {"FREE": "Free fix", "HIGH": "Urgent", "MEDIUM": "Recommended", "LOW": "Optional"}

# ---------------------------------------------------------------- type + scaling
_FONTS = {"display": ("DejaVu Sans", "bold"), "number": "DejaVu Sans", "body": "DejaVu Sans"}
_SCALE = 1.0


def _pick(root, *names):
    available = set(tkfont.families(root))
    return next((n for n in names if n in available), names[-1])


def init_theme(root):
    """Pick fonts and measure screen scaling. Call once, right after creating the window."""
    global _SCALE
    available = set(tkfont.families(root))
    _FONTS["display"] = next(
        (c for c in (("Bahnschrift SemiBold", "normal"), ("Barlow SemiBold", "normal"), ("Barlow", "bold"),
                     ("Segoe UI Semibold", "normal"), ("Helvetica Neue", "bold")) if c[0] in available),
        ("DejaVu Sans", "bold"))
    _FONTS["number"] = _pick(root, "Bahnschrift", "Barlow", "Segoe UI", "Helvetica Neue", "DejaVu Sans")
    _FONTS["body"] = _pick(root, "Segoe UI", "Helvetica Neue", "Noto Sans", "DejaVu Sans")
    try:
        _SCALE = max(1.0, root.winfo_fpixels("1i") / 96)
    except tk.TclError:
        _SCALE = 1.0
    setup_styles(root)


def sentence(s):
    """Capitalize the first letter only, keeping units like GB and MHz intact."""
    return s[:1].upper() + s[1:] if s else s


def px(n):
    """Scale a pixel size for high-resolution screens."""
    return int(round(n * _SCALE))


def base_font(size=10, weight="normal"):
    return (_FONTS["body"], size, weight)


def display_font(size=18):
    family, weight = _FONTS["display"]
    return (family, size, weight)


def number_font(size=11):
    return (_FONTS["number"], size)


# ---------------------------------------------------------------- ttk styling
def setup_styles(root):
    root.configure(bg=BG)
    style = ttk.Style(root)
    style.theme_use("clam")
    style.configure(".", background=BG, foreground=TEXT, fieldbackground=CARD, bordercolor=LINE,
                    lightcolor=CARD, darkcolor=CARD, troughcolor=CARD, focuscolor=ACCENT,
                    selectbackground=ACCENT_DIM, selectforeground=TEXT, insertcolor=TEXT,
                    font=base_font())
    style.configure("TFrame", background=BG)
    style.configure("Card.TFrame", background=CARD, borderwidth=0, relief="flat")
    style.configure("TLabel", background=BG, foreground=TEXT)
    style.configure("Title.TLabel", font=display_font(20))
    style.configure("Sub.TLabel", foreground=MUTED)
    style.configure("CardTitle.TLabel", background=CARD, foreground=MUTED, font=base_font(9))
    style.configure("CardBody.TLabel", background=CARD, foreground=TEXT, font=base_font(10))
    style.configure("Section.TLabel", font=display_font(13))

    # Buttons: flat, with a single filled primary
    style.configure("TButton", background=RAISED, foreground=TEXT, borderwidth=0, focusthickness=0,
                    padding=(px(14), px(7)), relief="flat")
    style.map("TButton", background=[("disabled", CARD), ("active", LINE)],
              foreground=[("disabled", MUTED)])
    style.configure("Accent.TButton", background=ACCENT, foreground=ON_COLOR,
                    font=base_font(10, "bold"))
    style.map("Accent.TButton", background=[("disabled", RAISED), ("active", ACCENT_HOVER)],
              foreground=[("disabled", MUTED)])

    # Inputs
    for w in ("TEntry", "TCombobox", "TSpinbox"):
        style.configure(w, fieldbackground=CARD, foreground=TEXT, bordercolor=LINE,
                        lightcolor=CARD, darkcolor=CARD, arrowcolor=MUTED, padding=px(4))
        style.map(w, fieldbackground=[("readonly", CARD)], bordercolor=[("focus", ACCENT)],
                  lightcolor=[("focus", ACCENT)])
    root.option_add("*TCombobox*Listbox.background", CARD)
    root.option_add("*TCombobox*Listbox.foreground", TEXT)
    root.option_add("*TCombobox*Listbox.selectBackground", ACCENT_DIM)
    root.option_add("*TCombobox*Listbox.selectForeground", TEXT)
    root.option_add("*TCombobox*Listbox.font", base_font())
    style.configure("TCheckbutton", background=BG, foreground=TEXT, indicatorbackground=CARD,
                    indicatorforeground=ACCENT, indicatormargin=px(4))
    style.map("TCheckbutton", background=[("active", BG)],
              indicatorbackground=[("selected", CARD)])

    # Lists
    style.configure("Treeview", background=CARD, fieldbackground=CARD, foreground=TEXT,
                    rowheight=px(28), borderwidth=0, font=base_font(10))
    style.map("Treeview", background=[("selected", ACCENT_DIM)], foreground=[("selected", TEXT)])
    style.configure("Treeview.Heading", background=CARD, foreground=MUTED, relief="flat",
                    borderwidth=0, font=base_font(9), padding=(px(6), px(6)))
    style.map("Treeview.Heading", background=[("active", RAISED)])
    style.layout("Treeview", [("Treeview.treearea", {"sticky": "nswe"})])

    # Scrollbars: slim and quiet
    for orient in ("Vertical", "Horizontal"):
        style.configure(f"{orient}.TScrollbar", background=RAISED, troughcolor=CARD, bordercolor=CARD,
                        lightcolor=RAISED, darkcolor=RAISED, arrowcolor=MUTED, gripcount=0,
                        arrowsize=px(12))
        style.map(f"{orient}.TScrollbar", background=[("active", LINE)])

    # Sub-page switcher (used inside Disk space and Performance)
    style.configure("TNotebook", background=BG, borderwidth=0, tabmargins=0, bordercolor=BG,
                    lightcolor=BG, darkcolor=BG)
    style.configure("TNotebook.Tab", background=BG, foreground=MUTED, padding=(px(14), px(7)),
                    borderwidth=0, font=base_font(10))
    style.map("TNotebook.Tab", background=[("selected", CARD)], foreground=[("selected", TEXT)],
              lightcolor=[("selected", CARD)], bordercolor=[("selected", CARD)])
    # The main page switcher has no visible tabs; the sidebar drives it
    style.configure("Pages.TNotebook", background=BG, borderwidth=0, bordercolor=BG,
                    lightcolor=BG, darkcolor=BG)
    style.layout("Pages.TNotebook.Tab", [])

    style.configure("Horizontal.TProgressbar", background=ACCENT, troughcolor=BG, borderwidth=0,
                    lightcolor=ACCENT, darkcolor=ACCENT, thickness=px(3))
    style.configure("TPanedwindow", background=BG)
    style.configure("Sash", sashthickness=px(8), background=BG)


def dark_title_bar(window):
    """Ask Windows 10/11 to draw this window's title bar in dark mode."""
    if hwa.SYSTEM != "Windows":
        return
    try:
        import ctypes
        window.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(window.winfo_id())
        value = ctypes.c_int(1)
        for attr in (20, 19):  # DWMWA_USE_IMMERSIVE_DARK_MODE (newer, older builds)
            if ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(value),
                                                          ctypes.sizeof(value)) == 0:
                break
    except Exception:
        pass


def enable_sharp_text():
    """Make Windows render the app at full resolution instead of blurry-scaled. Call before Tk()."""
    if hwa.SYSTEM != "Windows":
        return
    try:
        import ctypes
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


# ---------------------------------------------------------------- rich text
class RichText(ttk.Frame):
    """A read-only scrolling text area with simple formatting helpers."""

    def __init__(self, parent, **kw):
        super().__init__(parent, style="Card.TFrame")
        self.text = tk.Text(self, wrap="word", bg=CARD, fg=TEXT, relief="flat", padx=px(20),
                            pady=px(16), font=base_font(10), highlightthickness=0, cursor="arrow",
                            selectbackground=ACCENT_DIM, insertbackground=TEXT, spacing1=px(1),
                            spacing3=px(1), **kw)
        sb = ttk.Scrollbar(self, command=self.text.yview)
        self.text.configure(yscrollcommand=sb.set, state="disabled")
        sb.pack(side="right", fill="y")
        self.text.pack(side="left", fill="both", expand=True)
        t = self.text
        t.tag_configure("h1", font=display_font(15), spacing1=px(4), spacing3=px(6))
        t.tag_configure("h2", font=display_font(12), spacing1=px(2), spacing3=px(2))
        t.tag_configure("label", foreground=MUTED, font=base_font(9))
        t.tag_configure("muted", foreground=MUTED)
        t.tag_configure("small", foreground=MUTED, font=base_font(9))
        t.tag_configure("indent", lmargin1=px(26), lmargin2=px(26), foreground=MUTED,
                        font=base_font(9), spacing3=px(4))
        t.tag_configure("bold", font=base_font(10, "bold"))
        t.tag_configure("num", font=number_font(11))
        t.tag_configure("link", foreground=ACCENT, underline=False)
        t.tag_configure("boldlink", foreground=ACCENT, font=base_font(10, "bold"))
        t.tag_configure("smalllink", foreground=ACCENT, font=base_font(9))
        t.tag_configure("gap", font=base_font(4))
        t.tag_configure("biggap", font=base_font(12))
        self._links = 0
        self._colors = set()

    def clear(self):
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        for tag in self.text.tag_names():
            if tag.startswith("url"):
                self.text.tag_delete(tag)
        self._links = 0

    def done(self):
        self.text.configure(state="disabled")

    def write(self, s, *tags):
        self.text.insert("end", s, tags)

    def _color_tag(self, color, badge):
        tag = f"{'badge' if badge else 'fg'}_{color}"
        if tag not in self._colors:
            if badge:
                self.text.tag_configure(tag, foreground=ON_COLOR, background=color,
                                        font=base_font(9, "bold"))
            else:
                self.text.tag_configure(tag, foreground=color, font=base_font(10, "bold"))
            self._colors.add(tag)
        return tag

    def badge(self, label, color_key):
        self.write(f" {label} ", self._color_tag(COLORS.get(color_key, color_key), True))

    def colored(self, s, color_key):
        self.write(s, self._color_tag(COLORS.get(color_key, color_key), False))

    def link(self, s, target, tags=("link",)):
        """target: a URL string or a callable."""
        self._links += 1
        tag = f"url{self._links}"
        self.text.insert("end", s, tags + (tag,))
        action = (lambda _e: webbrowser.open(target)) if isinstance(target, str) else \
                 (lambda _e: target())
        self.text.tag_bind(tag, "<Button-1>", action)
        self.text.tag_bind(tag, "<Enter>", lambda _e: (self.text.configure(cursor="hand2"),
                                                      self.text.tag_configure(tag, underline=True)))
        self.text.tag_bind(tag, "<Leave>", lambda _e: (self.text.configure(cursor="arrow"),
                                                      self.text.tag_configure(tag, underline=False)))

    def rule(self):
        self.write("\n", "biggap")


# ---------------------------------------------------------------- misc helpers
def in_thread(root, work, done):
    """Run work() in the background, then done(result, error) on the UI thread."""
    def runner():
        try:
            res, err = work(), None
        except Exception as e:  # never crash the window
            res, err = None, e
        root.after(0, done, res, err)
    threading.Thread(target=runner, daemon=True).start()


def make_tree(parent, columns, widths, height=10, stretch_first=True):
    frame = ttk.Frame(parent, style="Card.TFrame")
    tree = ttk.Treeview(frame, columns=columns[1:], height=height)
    tree.heading("#0", text=columns[0], anchor="w")
    tree.column("#0", width=px(widths[0]), stretch=stretch_first)
    for c, w in zip(columns[1:], widths[1:]):
        right = c in ("Size", "Price", "%")
        tree.heading(c, text=c, anchor="e" if right else "w")
        tree.column(c, width=px(w), anchor="e" if right else "w", stretch=False)
    tree.tag_configure("odd", background="#1e2530")
    sb = ttk.Scrollbar(frame, command=tree.yview)
    tree.configure(yscrollcommand=sb.set)
    sb.pack(side="right", fill="y")
    tree.pack(side="left", fill="both", expand=True, padx=(px(4), 0), pady=px(4))
    return frame, tree


class Meter(tk.Canvas):
    """RigCheck's signature element: segmented meters, one per component."""

    SEGMENTS = 12

    def __init__(self, parent):
        super().__init__(parent, height=px(112), bg=BG, highlightthickness=0)
        self.items = []
        self.before = None
        self.bind("<Configure>", lambda e: self.redraw())

    def set(self, items, before=None):
        """items: list of dicts with label, value, ratio (None = unknown), status, note.
        before: the same list for the current PC, to show what an upgrade would change."""
        self.items = items
        self.before = before
        self.redraw()

    def redraw(self):
        self.delete("all")
        if not self.items:
            return
        w = self.winfo_width()
        gap = px(12)
        cw = (w - gap * (len(self.items) - 1)) / len(self.items)
        h = int(self["height"])
        for i, it in enumerate(self.items):
            x0 = i * (cw + gap)
            self.create_rectangle(x0, 0, x0 + cw, h, fill=CARD, outline="")
            pad = px(14)
            self.create_text(x0 + pad, px(16), text=it["label"], anchor="w", fill=MUTED,
                             font=base_font(9))
            value = it["value"]
            max_chars = max(8, int((cw - 2 * pad) / px(8)))
            if len(value) > max_chars:
                value = value[:max_chars - 1] + "…"
            self.create_text(x0 + pad, px(40), text=value, anchor="w", fill=TEXT, font=number_font(13))
            color = COLORS.get(it["status"], MUTED)
            ratio = it["ratio"]
            filled = 0 if ratio is None else max(1, min(self.SEGMENTS, round(ratio / 1.25 * self.SEGMENTS)))
            old = self.before[i] if self.before and i < len(self.before) else None
            was = filled if not old or old["ratio"] is None else \
                max(1, min(self.SEGMENTS, round(old["ratio"] / 1.25 * self.SEGMENTS)))
            seg_gap = px(3)
            seg_w = (cw - 2 * pad - seg_gap * (self.SEGMENTS - 1)) / self.SEGMENTS
            y0, y1 = px(60), px(74)
            for s in range(self.SEGMENTS):
                sx = x0 + pad + s * (seg_w + seg_gap)
                gained = was <= s < filled
                self.create_rectangle(sx, y0, sx + seg_w, y1, outline="",
                                      fill=ACCENT if gained else color if s < filled else RAISED)
            # target marker: where "meets your needs" sits on the scale
            tx = x0 + pad + (cw - 2 * pad) * (1 / 1.25)
            self.create_line(tx, y0 - px(4), tx, y1 + px(4), fill=MUTED, width=1)
            self.create_text(x0 + pad, px(94), text=it["note"], anchor="w", fill=color,
                             font=base_font(9, "bold"))
            if old and old["note"] != it["note"]:
                self.create_text(x0 + cw - pad, px(16), text=f"was: {old['note'].lower()}", anchor="e",
                                 fill=MUTED, font=base_font(8))
