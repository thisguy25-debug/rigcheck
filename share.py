"""
Sharing: a rig card image for Discord/Reddit, exporting your rig to a file, and
comparing your PC with a friend's.
"""

import datetime
import json
import os
import subprocess

import app_info
import hw_advisor as hwa

FILE_EXT = ".rigcheck"

# Same palette as the app
BG, CARD, RAISED, LINE = "#1a2029", "#212834", "#2a3240", "#343d4c"
TEXT, MUTED, ACCENT = "#e8ebf1", "#98a2b3", "#43b9cc"
STATUS = {"good": "#56c48b", "warn": "#e9b44c", "bad": "#ef6a64", "unknown": "#98a2b3"}
LEVEL_COLORS = ["#ef6a64", "#e9b44c", "#56c48b"]


# ----------------------------------------------------------------------------
# Snapshot / export / import
# ----------------------------------------------------------------------------
def snapshot(name, profile, specs, ratings, scores, games):
    """specs: {label: text}; ratings: meter items; scores: games_db.system_scores; games: list."""
    return {"app": "RigCheck", "format": 1, "version": app_info.APP_VERSION, "name": name,
            "profile": profile, "created": datetime.date.today().isoformat(), "specs": specs,
            "ratings": [{k: r.get(k) for k in ("label", "value", "ratio", "status", "note")}
                        for r in ratings],
            "scores": scores, "games": games}


def export_rig(snap, path):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(snap, f, indent=2)


def import_rig(path):
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if data.get("app") != "RigCheck" or "ratings" not in data:
        raise ValueError("That file isn't a RigCheck rig file.")
    return data


def compare(mine, theirs):
    """Component-by-component and game-by-game comparison."""
    rows = []
    for key, label, unit in (("cpu", "Processor", ""), ("gpu", "Graphics", ""), ("ram", "Memory", " GB"),
                             ("vram", "Video memory", " GB")):
        a, b = (mine["scores"] or {}).get(key), (theirs["scores"] or {}).get(key)
        spec_a = mine["specs"].get(label, f"{a}{unit}" if a else "?")
        spec_b = theirs["specs"].get(label, f"{b}{unit}" if b else "?")
        if label == "Video memory":
            spec_a, spec_b = (f"{a:g} GB" if a else "?"), (f"{b:g} GB" if b else "?")
        winner = None
        if a and b:
            winner = "tie" if abs(a - b) / max(a, b) < 0.05 else ("mine" if a > b else "theirs")
        pct = f"{max(a, b) / min(a, b) - 1:.0%} faster" if a and b and winner not in ("tie", None) \
            and key in ("cpu", "gpu") else ""
        rows.append({"label": label, "mine": spec_a, "theirs": spec_b, "winner": winner, "detail": pct})
    games = []
    theirs_games = {g["name"]: g for g in theirs.get("games", [])}
    for g in mine.get("games", []):
        t = theirs_games.get(g["name"])
        if t:
            a, b = g.get("rank", g["level"] * 2), t.get("rank", t["level"] * 2)
            games.append({"name": g["name"], "mine": g, "theirs": t,
                          "winner": "tie" if a == b else ("mine" if a > b else "theirs")})
    return {"rows": rows, "games": games,
            "wins": sum(r["winner"] == "mine" for r in rows),
            "losses": sum(r["winner"] == "theirs" for r in rows)}


# ----------------------------------------------------------------------------
# Rig card image
# ----------------------------------------------------------------------------
def _fonts():
    from PIL import ImageFont
    win = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")
    home = os.path.expanduser("~")

    def load(size, candidates, variation=None):
        for path in candidates:
            try:
                f = ImageFont.truetype(path, size)
                if variation:
                    try:
                        f.set_variation_by_name(variation)
                    except Exception:
                        pass
                return f
            except OSError:
                continue
        try:
            return ImageFont.load_default(size=size)
        except TypeError:
            return ImageFont.load_default()

    display = [os.path.join(win, "bahnschrift.ttf"), os.path.join(home, ".fonts", "Barlow-SemiBold.ttf"),
               "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "/Library/Fonts/Arial Bold.ttf"]
    number = [os.path.join(win, "bahnschrift.ttf"), os.path.join(home, ".fonts", "Barlow-Regular.ttf"),
              "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/Library/Fonts/Arial.ttf"]
    body = [os.path.join(win, "segoeui.ttf"), "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/Library/Fonts/Arial.ttf"]
    bold = [os.path.join(win, "segoeuib.ttf"), "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/Library/Fonts/Arial Bold.ttf"]
    return {"title": load(56, display, "SemiBold"), "brand": load(26, display, "SemiBold"),
            "value": load(23, number, "Regular"), "label": load(18, body), "body": load(20, body),
            "bold": load(18, bold), "small": load(16, body)}


def _fit(draw, text, font, width):
    if draw.textlength(text, font=font) <= width:
        return text
    while text and draw.textlength(text + "…", font=font) > width:
        text = text[:-1]
    return text + "…"


def make_card(snap, path, profile_label):
    """Draw a 1200×630 PNG (the size Discord, Reddit and X preview best)."""
    from PIL import Image, ImageDraw
    W, H = 1200, 630
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    f = _fonts()
    M = 56

    # Brand mark: the four-bar meter from the app
    for i, h in enumerate((12, 19, 26, 34)):
        x = M + i * 10
        d.rectangle([x, 72 - h, x + 7, 72], fill=ACCENT)
    d.text((M + 50, 40), "RigCheck", font=f["brand"], fill=TEXT)
    when = datetime.date.fromisoformat(snap["created"]).strftime("%B %d, %Y").replace(" 0", " ")
    d.text((W - M, 44), f"Checked {when}", font=f["small"], fill=MUTED, anchor="ra")

    d.text((M, 104), _fit(d, snap["name"], f["title"], W - 2 * M), font=f["title"], fill=TEXT)
    d.text((M, 172), f"{profile_label} PC", font=f["body"], fill=MUTED)

    # Meters
    top, mh, gap = 222, 150, 16
    n = len(snap["ratings"]) or 1
    mw = (W - 2 * M - gap * (n - 1)) / n
    for i, r in enumerate(snap["ratings"]):
        x0 = M + i * (mw + gap)
        d.rectangle([x0, top, x0 + mw, top + mh], fill=CARD)
        p = 20
        d.text((x0 + p, top + 18), r["label"], font=f["label"], fill=MUTED)
        d.text((x0 + p, top + 44), _fit(d, r["value"], f["value"], mw - 2 * p), font=f["value"], fill=TEXT)
        color = STATUS.get(r["status"], MUTED)
        segs, sg = 12, 4
        sw = (mw - 2 * p - sg * (segs - 1)) / segs
        filled = 0 if r["ratio"] is None else max(1, min(segs, round(r["ratio"] / 1.25 * segs)))
        for s in range(segs):
            sx = x0 + p + s * (sw + sg)
            d.rectangle([sx, top + 88, sx + sw, top + 104], fill=color if s < filled else RAISED)
        tx = x0 + p + (mw - 2 * p) / 1.25
        d.line([tx, top + 82, tx, top + 110], fill=MUTED, width=2)
        d.text((x0 + p, top + 118), r["note"], font=f["bold"], fill=color)

    # Specs (left) and games (right)
    y = top + mh + 36
    col2 = W // 2 + 20
    for label in ("Processor", "Graphics", "Memory", "Storage"):
        val = snap["specs"].get(label)
        if not val:
            continue
        d.text((M, y), label, font=f["label"], fill=MUTED)
        d.text((M + 120, y - 1), _fit(d, val, f["body"], col2 - M - 150), font=f["body"], fill=TEXT)
        y += 36
    games = sorted(snap.get("games", []), key=lambda g: -g["level"])[:5]
    y = top + mh + 36
    for g in games:
        color = LEVEL_COLORS[g["level"]]
        d.ellipse([col2, y + 7, col2 + 10, y + 17], fill=color)
        d.text((col2 + 22, y - 1), _fit(d, g["name"], f["body"], 300), font=f["body"], fill=TEXT)
        d.text((W - M, y - 1), g["short"].split(",")[0], font=f["body"], fill=color, anchor="ra")
        y += 36
    img.save(path, "PNG")
    return path


def pillow_available():
    try:
        import PIL  # noqa: F401
        return True
    except ImportError:
        return False


def copy_image_to_clipboard(path):
    """Windows: put the PNG on the clipboard so it can be pasted into Discord."""
    if hwa.SYSTEM != "Windows":
        return False
    script = ("Add-Type -AssemblyName System.Windows.Forms; Add-Type -AssemblyName System.Drawing; "
              f"$img = [System.Drawing.Image]::FromFile('{path}'); "
              "[System.Windows.Forms.Clipboard]::SetImage($img); $img.Dispose()")
    r = subprocess.run(["powershell", "-NoProfile", "-STA", "-Command", script], capture_output=True,
                       creationflags=hwa.NO_WINDOW, stdin=subprocess.DEVNULL, timeout=20)
    return r.returncode == 0


def default_card_folder():
    folder = os.path.join(os.path.expanduser("~"), "Pictures", "RigCheck")
    os.makedirs(folder, exist_ok=True)
    return folder
