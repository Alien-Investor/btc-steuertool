#!/usr/bin/env python3
"""make_frames.py — Vollbild-Stills 1920×1080 für den BTC-Steuertool-Trailer: Motiv (Icon + Glow),
Handy-Szenen (Screenshot rechts, links Platz für die Karte) und Titelbild. Ausgabe frames/<lang>/<name>.jpg"""
from PIL import Image, ImageDraw, ImageFilter, ImageFont
from pathlib import Path
ROOT = Path(__file__).parent
W, H = 1920, 1080
BG_TOP, BG_BOTTOM = (8, 10, 22), (14, 18, 40)
GLOW = (0, 190, 150)
WHITE = (238, 244, 255); BRAND = (90, 115, 160)
FONT_B = "/usr/share/fonts/truetype/ubuntu/Ubuntu-B.ttf"; FONT_R = "/usr/share/fonts/truetype/ubuntu/Ubuntu-R.ttf"
ICON = ROOT / "assets/icon.png"
SHOTS = ["start", "dropzone", "files", "report", "fees", "proof", "nokyc", "save", "help"]
SUB = {"de": "Bitcoin-Steuerreport, offline auf GrapheneOS und Linux", "en": "Bitcoin tax report, offline on GrapheneOS and Linux"}

def gradient():
    img = Image.new("RGB", (W, H)); d = ImageDraw.Draw(img)
    for y in range(H):
        t = y / (H - 1); d.line([(0, y), (W, y)], fill=tuple(int(a + (b - a) * t) for a, b in zip(BG_TOP, BG_BOTTOM)))
    return img.convert("RGBA")

def glow(img, cx, cy, rx, ry, color, alpha=120, blur=90):
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0)); d = ImageDraw.Draw(layer)
    d.ellipse([cx - rx, cy - ry, cx + rx, cy + ry], fill=color + (alpha,))
    img.alpha_composite(layer.filter(ImageFilter.GaussianBlur(blur)))

def rounded(im, r):
    mask = Image.new("L", im.size, 0); ImageDraw.Draw(mask).rounded_rectangle([0, 0, im.width - 1, im.height - 1], r, fill=255)
    out = im.copy(); out.putalpha(mask); return out

def motiv():
    img = gradient(); glow(img, W // 2, 330, 480, 340, GLOW, 110, 120)   # Icon oben, Textband unten (Karten „lower“)
    ic = Image.open(ICON).convert("RGBA"); s = 440; ic = ic.resize((s, s), Image.LANCZOS)
    ic = rounded(ic, int(s * 0.22))
    img.alpha_composite(ic, ((W - s) // 2, 110))
    return img

def phone(shot):
    img = gradient()
    sc = Image.open(shot).convert("RGBA"); ph = 940; pwid = int(sc.width * ph / sc.height)
    sc = sc.resize((pwid, ph), Image.LANCZOS)
    x0, y0 = 1180, (H - ph) // 2
    glow(img, x0 + pwid // 2, y0 + ph // 2, pwid // 2 + 160, ph // 2 + 60, GLOW, 70, 110)
    r = 46
    frame = Image.new("RGBA", (pwid + 6, ph + 6), (0, 0, 0, 0))
    ImageDraw.Draw(frame).rounded_rectangle([0, 0, pwid + 5, ph + 5], r + 3, fill=(0, 255, 204, 70))
    img.alpha_composite(frame, (x0 - 3, y0 - 3))
    img.alpha_composite(rounded(sc, r), (x0, y0))
    return img

def title(lang):
    img = gradient(); glow(img, W // 2, 380, 420, 300, GLOW, 90, 110)
    ic = Image.open(ICON).convert("RGBA"); s = 380; ic = rounded(ic.resize((s, s), Image.LANCZOS), int(s * 0.22))
    img.alpha_composite(ic, ((W - s) // 2, 150))
    d = ImageDraw.Draw(img)
    f1 = ImageFont.truetype(FONT_B, 132); f2 = ImageFont.truetype(FONT_R, 50)
    t = "BTC Steuertool"; d.text(((W - d.textlength(t, font=f1)) / 2, 580), t, font=f1, fill=WHITE)
    d.line([(W // 2 - 180, 760), (W // 2 + 180, 760)], fill=(0, 185, 255), width=3)
    t = SUB[lang]; d.text(((W - d.textlength(t, font=f2)) / 2, 800), t, font=f2, fill=WHITE)
    fb = ImageFont.truetype(FONT_R, 34)
    d.text((W - d.textlength("alien-investor.org", font=fb) - 60, H - 80), "alien-investor.org", font=fb, fill=BRAND)
    return img

if __name__ == "__main__":
    for lang in ("de", "en"):
        out = ROOT / "frames" / lang; out.mkdir(parents=True, exist_ok=True)
        motiv().convert("RGB").save(out / "motiv.jpg", quality=95)
        title(lang).convert("RGB").save(out / "title.jpg", quality=95)
        for s in SHOTS:
            phone(ROOT / "shots" / f"{s}-{lang}.png").convert("RGB").save(out / f"{s}.jpg", quality=95)
        print(lang, len(list(out.glob("*.jpg"))), "Frames")
