"""Tek seferlik görsel üretici: app.ico + Inno Setup wizard BMP'leri."""
from PIL import Image, ImageDraw

OUT = "installer/assets"


def lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def gradient_bg(size, top=(37, 99, 235), bottom=(30, 27, 75)):
    img = Image.new("RGB", (size, size))
    px = img.load()
    for y in range(size):
        color = lerp(top, bottom, y / max(1, size - 1))
        for x in range(size):
            px[x, y] = color
    return img


def draw_icon(size):
    img = gradient_bg(size).convert("RGBA")
    d = ImageDraw.Draw(img)
    u = size / 256.0

    # Arka plan yuvarlatılmış maske (köşeleri saydam yap)
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        [0, 0, size - 1, size - 1], radius=int(56 * u), fill=255
    )
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    canvas.paste(img, (0, 0), mask)
    d = ImageDraw.Draw(canvas)

    # İndirme oku: gövde
    shaft_w = 44 * u
    cx = size / 2
    d.rounded_rectangle(
        [cx - shaft_w / 2, 42 * u, cx + shaft_w / 2, 138 * u],
        radius=shaft_w / 2,
        fill=(255, 255, 255, 255),
    )
    # Ok başı (aşağı bakan üçgen)
    d.polygon(
        [
            (cx - 74 * u, 118 * u),
            (cx + 74 * u, 118 * u),
            (cx, 192 * u),
        ],
        fill=(255, 255, 255, 255),
    )
    # Tepsi çizgisi
    d.rounded_rectangle(
        [52 * u, 206 * u, 204 * u, 226 * u],
        radius=10 * u,
        fill=(255, 255, 255, 235),
    )
    return canvas


def icon_to_rgb_on_white(img):
    bg = Image.new("RGB", img.size, (255, 255, 255))
    bg.paste(img, (0, 0), img)
    return bg


# 1) app.ico (çok boyutlu; PIL her boyutu kaynaktan yeniden örnekler)
sizes = [16, 20, 24, 32, 40, 48, 64, 128, 256]
draw_icon(256).save(f"{OUT}/app.ico", format="ICO", sizes=[(s, s) for s in sizes])

# 2) Wizard sol görseli (164x314) — koyu gradyan + büyük ok motifi
w = Image.new("RGB", (164, 314))
px = w.load()
for y in range(314):
    color = lerp((30, 64, 175), (17, 24, 39), y / 313)
    for x in range(164):
        px[x, y] = color
big = draw_icon(256).resize((132, 132), Image.LANCZOS)
w.paste(icon_to_rgb_on_white(big), (16, 60), big)
d = ImageDraw.Draw(w)
d.rectangle([16, 236, 148, 240], fill=(96, 165, 250))
d.rectangle([16, 252, 116, 256], fill=(148, 163, 184))
d.rectangle([16, 266, 132, 270], fill=(148, 163, 184))
w.save(f"{OUT}/wizard-left.bmp")

# 3) Wizard küçük görseli (55x58)
small = draw_icon(232).resize((55, 55), Image.LANCZOS)
s = Image.new("RGB", (55, 58), (255, 255, 255))
s.paste(small, (0, 1), small)
s.save(f"{OUT}/wizard-small.bmp")

print("OK")
