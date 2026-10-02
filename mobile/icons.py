#!/usr/bin/env python3
"""App-Icon und Startbild der APK aus desktop/icon.png (dasselbe Motiv wie die Desktop-App).

Ersetzt die Capacitor-Platzhalter in android/app/src/main/res: Launcher-Icons (klassisch, rund, adaptiv mit schwarzem
Hintergrund) und alle splash.png (schwarz, Icon mittig) — sonst blitzt beim Start das Capacitor-Logo auf weißem Grund auf.
"""
from pathlib import Path
from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent
SRC = Image.open(HERE.parent / "desktop" / "icon.png").convert("RGBA")
RES = HERE / "android" / "app" / "src" / "main" / "res"
DENS = {"mdpi": 48, "hdpi": 72, "xhdpi": 96, "xxhdpi": 144, "xxxhdpi": 192}


def scaled(size):
    return SRC.resize((size, size), Image.LANCZOS)


for dens, px in DENS.items():
    d = RES / f"mipmap-{dens}"
    scaled(px).save(d / "ic_launcher.png")
    # rund: Kreis-Maske über dem Motiv
    mask = Image.new("L", (px, px), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, px - 1, px - 1), fill=255)
    rnd = Image.new("RGBA", (px, px), (0, 0, 0, 0))
    rnd.paste(scaled(px), (0, 0), mask)
    rnd.save(d / "ic_launcher_round.png")
    # adaptiv: 108-dp-Leinwand, Motiv in der sicheren Zone (≈ 66 %), Hintergrund schwarz (values/ic_launcher_background.xml)
    fg_px = px * 108 // 48
    inner = int(fg_px * 0.66)
    fg = Image.new("RGBA", (fg_px, fg_px), (0, 0, 0, 0))
    fg.paste(scaled(inner), ((fg_px - inner) // 2, (fg_px - inner) // 2), scaled(inner))
    fg.save(d / "ic_launcher_foreground.png")

(RES / "values" / "ic_launcher_background.xml").write_text(
    '<?xml version="1.0" encoding="utf-8"?>\n<resources>\n    <color name="ic_launcher_background">#000000</color>\n</resources>\n',
    encoding="utf-8")

n = 0
for sp in RES.glob("drawable*/splash.png"):
    w, h = Image.open(sp).size
    canvas = Image.new("RGB", (w, h), (0, 0, 0))
    s = min(w, h) // 3
    canvas.paste(scaled(s), ((w - s) // 2, (h - s) // 2), scaled(s))
    canvas.save(sp)
    n += 1
print(f"Icons: {len(DENS)} Dichten, Startbilder: {n}")
