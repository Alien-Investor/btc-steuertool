#!/usr/bin/env python3
"""make_cards.py — Textkarten für den BTC-Steuertool-Trailer (DE + EN, 16:9). Kanal-Look wie titelkarte-generator.py.
Aufhänger als Band über die Mitte, alle weiteren Karten als linker Textblock neben dem Handy. Endkarte deckend mit QR.
Ausgabe cards/<lang>/<key>.png"""
from PIL import Image, ImageDraw, ImageFont
from pathlib import Path
import qrcode
BG_TOP, BG_BOTTOM = (8, 10, 22), (14, 18, 40)
ACCENT = (0, 185, 255); WHITE = (238, 244, 255); BRAND = (90, 115, 160)
FONT_B = "/usr/share/fonts/truetype/ubuntu/Ubuntu-B.ttf"; FONT_R = "/usr/share/fonts/truetype/ubuntu/Ubuntu-R.ttf"
ROOT = Path(__file__).parent; W, H = 1920, 1080
QR_URL = {"de": "https://alien-investor.org/btc-steuertool.html#app", "en": "https://alien-investor.org/en/btc-steuertool.html#app"}

TEXT = {
 "de": {
  "c01": "Wem gibst du deine Steuerdaten?",
  "c02": "Cloud-Steuertools wollen jede Transaktion auf ihrem Server.",
  "c03": "Das BTC Steuertool rechnet auf deinem Gerät. Kein Upload, kein Konto, keine Telemetrie.",
  "c04": "Die App hat nicht einmal eine Internet-Berechtigung.",
  "l05": "CSV-Exporte rein, die App erkennt jeden Broker am Inhalt",
  "l06": "FiFo mit Jahresfrist nach Kalenderdatum und Freigrenze",
  "l07": "Gebühren in Bitcoin als Veräußerung, Schenkungen als Abgang",
  "l08": "Formaler Steuernachweis fürs Finanzamt",
  "l09": "noKYC strikt getrennt, nie in den Unterlagen fürs Finanzamt",
  "l10": "Alle Reports als ZIP speichern",
  "l11": "Handbuch in der App, Deutsch und Englisch",
  "c12": "Derselbe Rechenkern wie CLI und Web-Version. Open Source. Auch als Flatpak für Linux.",
  "end1": "Deine Steuerdaten bleiben bei dir.",
  "end2": "Kostenlos und Open Source. Zap Store, Obtainium oder direkt als APK.",
  "end3": "alien-investor.org/btc-steuertool.html",
 },
 "en": {
  "c01": "Who gets your tax data?",
  "c02": "Cloud tax tools want every transaction on their server.",
  "c03": "BTC Steuertool calculates on your device. No upload, no account, no telemetry.",
  "c04": "The app does not even have an internet permission.",
  "l05": "Drop in CSV exports, every broker detected by its content",
  "l06": "FiFo with the one-year holding period and the exemption limit",
  "l07": "Fees paid in bitcoin as disposals, gifts as outflows",
  "l08": "Formal tax evidence for the German tax office",
  "l09": "noKYC kept strictly apart, never in the tax office documents",
  "l10": "Save all reports as one ZIP",
  "l11": "In-app guide in German and English",
  "c12": "Same calculation core as the CLI and the web version. Open source. Also a Flatpak for Linux.",
  "end1": "Your tax data stays with you.",
  "end2": "Free and open source. Zap Store, Obtainium or directly as an APK.",
  "end3": "alien-investor.org/en/btc-steuertool.html",
 },
}

def gradient(w, h):
    img = Image.new("RGB", (w, h)); d = ImageDraw.Draw(img)
    for y in range(h):
        t = y / max(h - 1, 1); d.line([(0, y), (w, y)], fill=tuple(int(a + (b - a) * t) for a, b in zip(BG_TOP, BG_BOTTOM)))
    return img

def wrap(draw, text, font, max_w):
    words, lines, cur = text.split(), [], ""
    for wd in words:
        t = (cur + " " + wd).strip()
        if draw.textlength(t, font=font) <= max_w: cur = t
        else: lines.append(cur); cur = wd
    if cur: lines.append(cur)
    return lines

def band_card(text, size=110):
    """Motiv-Szenen: dunkles Band über die ganze Breite im unteren Drittel (Icon sitzt oben), Text zentriert."""
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0)); d = ImageDraw.Draw(img)
    font = ImageFont.truetype(FONT_B, size); lines = wrap(d, text, font, int(W * 0.86))
    lh = sum(font.getbbox(l)[3] - font.getbbox(l)[1] + 14 for l in lines); band_h = lh + 120; y0 = int(H * 0.74) - band_h // 2
    img.alpha_composite(Image.new("RGBA", (W, band_h), (6, 8, 18, 200)), (0, y0)); d = ImageDraw.Draw(img)
    d.rectangle([(0, y0), (10, y0 + band_h)], fill=ACCENT + (255,))
    y = y0 + 60
    for ln in lines:
        bb = font.getbbox(ln); d.text(((W - d.textlength(ln, font=font)) / 2, y), ln, font=font, fill=WHITE); y += bb[3] - bb[1] + 14
    return img

def side_card(text, size=66):
    """Linker Textblock neben dem Handy (x 120 … 1060), vertikal mittig, Cyan-Balken links."""
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0)); d = ImageDraw.Draw(img)
    font = ImageFont.truetype(FONT_B, size); maxw = 900; lines = wrap(d, text, font, maxw)
    gap = int(size * 0.28); lh = size + gap; total = lh * len(lines) - gap
    x0 = 150; y0 = (H - total) // 2
    d.rectangle([(x0 - 40, y0 - 10), (x0 - 28, y0 + total + 10)], fill=ACCENT + (255,))
    y = y0
    for ln in lines: d.text((x0, y - int(size * 0.12)), ln, font=font, fill=WHITE); y += lh
    return img

def end_card(lang):
    t = TEXT[lang]; img = gradient(W, H).convert("RGBA"); d = ImageDraw.Draw(img)
    d.rectangle([(0, 0), (10, H)], fill=ACCENT)
    ic = Image.open(ROOT / "assets/icon.png").convert("RGBA"); s = 520; ic = ic.resize((s, s), Image.LANCZOS)
    mask = Image.new("L", (s, s), 0); ImageDraw.Draw(mask).rounded_rectangle([0, 0, s - 1, s - 1], int(s * 0.22), fill=255); ic.putalpha(mask)
    img.alpha_composite(ic, (150, (H - s) // 2))
    x = 150 + s + 110; maxw = W - x - 120
    f1 = ImageFont.truetype(FONT_B, 92); f2 = ImageFont.truetype(FONT_R, 40); y = 230
    for ln in wrap(d, t["end1"], f1, maxw): d.text((x, y), ln, font=f1, fill=WHITE); y += 112
    d.line([(x, y + 10), (x + maxw, y + 10)], fill=ACCENT, width=3); y += 50
    for ln in wrap(d, t["end2"], f2, maxw): d.text((x, y), ln, font=f2, fill=WHITE); y += 52
    q = qrcode.make(QR_URL[lang], border=2).convert("RGBA"); qs = 260; q = q.resize((qs, qs), Image.NEAREST)
    img.alpha_composite(q, (x, y + 30)); d.text((x + qs + 30, y + 30 + qs // 2 - 22), t["end3"], font=f2, fill=BRAND)
    fb = ImageFont.truetype(FONT_R, 34)
    d.text((W - d.textlength("alien-investor.org", font=fb) - 60, H - 80), "alien-investor.org", font=fb, fill=BRAND)
    return img

if __name__ == "__main__":
    for lang in ("de", "en"):
        out = ROOT / "cards" / lang; out.mkdir(parents=True, exist_ok=True); t = TEXT[lang]
        band_card(t["c01"], 110).save(out / "c01.png"); band_card(t["c02"], 72).save(out / "c02.png")
        band_card(t["c12"], 72).save(out / "c12.png")
        for k in ("c03", "c04"): side_card(t[k], 66).save(out / f"{k}.png")
        for k in ("l05", "l06", "l07", "l08", "l09", "l10", "l11"): side_card(t[k], 84).save(out / f"{k}.png")
        end_card(lang).convert("RGB").save(out / "end.png")
        print(lang, len(list(out.glob("*.png"))), "Karten")
