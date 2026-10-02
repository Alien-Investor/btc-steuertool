#!/usr/bin/env python3
"""make_thumbs.py — Thumbnail-Varianten für den BTC-Steuertool-Trailer (1280x720, DE + EN).
Hintergründe hier (Motiv gedimmt + Handy rechts), Textebene über ~/Skripte/thumbnail-text.py. V3 = Endkarte."""
from PIL import Image, ImageDraw, ImageFilter
from pathlib import Path
import subprocess, sys
ROOT = Path(__file__).parent; OUT = ROOT/"thumbs"; OUT.mkdir(exist_ok=True)
W, H = 1280, 720
TXT = {"de": {"v1": ("BTC STEUERTOOL", "App-Trailer · Bitcoin-Steuerreport offline für GrapheneOS und Linux"),
              "v2": ("KEIN UPLOAD.", "BTC Steuertool · Deine Steuerdaten bleiben bei dir")},
       "en": {"v1": ("BTC STEUERTOOL", "App trailer · Bitcoin tax report offline for GrapheneOS and Linux"),
              "v2": ("NO UPLOAD.", "BTC Steuertool · Your tax data stays with you")}}
def bg_motiv(dim):
    im = Image.open(ROOT/"frames/de/motiv.jpg").convert("RGB").resize((W, H), Image.LANCZOS)
    return Image.eval(im, lambda v: int(v*dim)).convert("RGBA")
def phone(lang, h):
    sc = Image.open(ROOT/"shots"/f"files-{lang}.png").convert("RGBA"); w = int(sc.width*h/sc.height); sc = sc.resize((w, h), Image.LANCZOS)
    m = Image.new("L", sc.size, 0); ImageDraw.Draw(m).rounded_rectangle([0, 0, w-1, h-1], 30, fill=255); sc.putalpha(m); return sc
def with_phone(bg, lang, h, x, y):
    c = phone(lang, h); sh = Image.new("RGBA", (c.width+40, c.height+40), (0,0,0,0))
    sh.paste((0,0,0,200), (20,20,c.width+20,c.height+20)); sh = sh.filter(ImageFilter.GaussianBlur(18))
    bg.alpha_composite(sh, (x-20, y-20+12)); bg.alpha_composite(c, (x, y)); return bg.convert("RGB")
for lang in ("de","en"):
    with_phone(bg_motiv(0.5), lang, 470, W-330, 25).save(OUT/f"bg-v1-{lang}.png")
    with_phone(bg_motiv(0.7), lang, 470, W-330, 25).save(OUT/f"bg-v2-{lang}.png")
    for v in ("v1","v2"):
        t, s = TXT[lang][v]
        subprocess.run([sys.executable, str(Path.home()/"Skripte/thumbnail-text.py"), "--input", str(OUT/f"bg-{v}-{lang}.png"),
                        "--title", t, "--sub", s, "--output", str(OUT/f"thumb-{v}-{lang}.png")], check=True)
    Image.open(ROOT/"cards"/lang/"end.png").convert("RGB").resize((W,H), Image.LANCZOS).save(OUT/f"thumb-v3-{lang}.png")
for f in sorted(OUT.glob("thumb-*.png")):
    Image.open(f).convert("RGB").save(f.with_suffix(".jpg"), quality=90); print(f.with_suffix(".jpg").name)
