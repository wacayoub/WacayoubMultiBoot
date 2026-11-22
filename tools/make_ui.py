#!/usr/bin/env python3
"""Draw Wacayoub MultiBoot UI images into src/WMultiBoot/img/{fhd,hd}/.

Glyphs: Lucide icons (ISC License, https://lucide.dev, Lucide Contributors).
Distro "logos" are our own stylised name tiles (brand colour + short name), not the
projects' official artwork.
Needs resvg-py + Pillow (the Wacayoub Panel venv has both):
    "../Wacayoub Panel/build/venv/Scripts/python" tools/make_ui.py
"""
import io
import os

import resvg_py
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "src", "WMultiBoot", "img")
FONT_B = "C:/Windows/Fonts/segoeuib.ttf"
FONT_R = "C:/Windows/Fonts/segoeui.ttf"

G = {
    "drive": '<path d="M22 12H2m3.45-6.89L2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11M6 16h.01M10 16h.01"/>',
    "cpu": '<path d="M12 20v2m0-20v2m5 16v2m0-20v2M2 12h2m-2 5h2M2 7h2m16 5h2m-2 5h2M20 7h2M7 20v2M7 2v2"/><rect width="16" height="16" x="4" y="4" rx="2"/><rect width="8" height="8" x="8" y="8" rx="1"/>',
    "usb": '<circle cx="10" cy="7" r="1"/><circle cx="4" cy="20" r="1"/><path d="M4.7 19.3L19 5m-2 0h4v4M10.75 7.24L7 11h5l-1.5 3"/><circle cx="16" cy="14" r="1"/><path d="M16 15l-3.5 3.5"/>',
    "trash": '<path d="M10 11v6m4-6v6m5-11v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6M3 6h18M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>',
    "power": '<path d="M12 2v10m6.4-5.4a9 9 0 1 1-12.77.04"/>',
    "download": '<path d="M12 15V3m9 12v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4m4-5l5 5l5-5"/>',
    "save": '<path d="M15.2 3a2 2 0 0 1 1.4.6l3.8 3.8a2 2 0 0 1 .6 1.4V19a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2z"/><path d="M17 21v-7a1 1 0 0 0-1-1H8a1 1 0 0 0-1 1v7M7 3v4a1 1 0 0 0 1 1h7"/>',
    "menu": '<path d="M4 6h16M4 12h16M4 18h16"/>',
    "tag": '<path d="M12.586 2.586A2 2 0 0 0 11.172 2H4a2 2 0 0 0-2 2v7.172a2 2 0 0 0 .586 1.414l8.704 8.704a2.426 2.426 0 0 0 3.42 0l6.58-6.58a2.426 2.426 0 0 0 0-3.42z"/><circle cx="7.5" cy="7.5" r=".5" fill="currentColor"/>',
    "calendar": '<path d="M8 2v4m8-4v4"/><rect width="18" height="18" x="3" y="4" rx="2"/><path d="M3 10h18"/>',
    "box": '<path d="M11 21.73a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73z"/><path d="M12 22V12M3.29 7L12 12l8.71-5"/>',
    "layers": '<path d="M12.83 2.18a2 2 0 0 0-1.66 0L2.6 6.08a1 1 0 0 0 0 1.83l8.58 3.91a2 2 0 0 0 1.66 0l8.58-3.9a1 1 0 0 0 0-1.83zM2 12a1 1 0 0 0 .58.91l8.6 3.91a2 2 0 0 0 1.65 0l8.58-3.9A1 1 0 0 0 22 12"/><path d="M2 17a1 1 0 0 0 .58.91l8.6 3.91a2 2 0 0 0 1.65 0l8.58-3.9A1 1 0 0 0 22 17"/>',
    "folder": '<path d="M20 20a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.69-.9L9.6 3.9A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2Z"/>',
    "globe": '<circle cx="12" cy="12" r="10"/><path d="M12 2a14.5 14.5 0 0 0 0 20a14.5 14.5 0 0 0 0-20M2 12h20"/>',
    "link": '<path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/>',
    "archive": '<rect width="20" height="5" x="2" y="3" rx="1"/><path d="M4 8v11a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8m-10 4h4"/>',
    "rotate": '<path d="M3 12a9 9 0 1 0 9-9a9.75 9.75 0 0 0-6.74 2.74L3 8"/><path d="M3 3v5h5"/>',
    "check": '<path d="M20 6L9 17l-5-5"/>',
    "shield": '<path d="M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z"/><path d="m9 12l2 2l4-4"/>',
}

# distro key -> (short name, colour 1, colour 2)
DISTROS = {
    "openatv": ("ATV", "#1D4ED8", "#38BDF8"),
    "openpli": ("PLi", "#C2410C", "#FB923C"),
    "openvix": ("ViX", "#047857", "#34D399"),
    "openbh": ("BH", "#111827", "#6B7280"),
    "openspa": ("SPA", "#991B1B", "#F87171"),
    "egami": ("EGAMI", "#5B21B6", "#A78BFA"),
    "teamblue": ("TB", "#1E3A8A", "#60A5FA"),
    "openhdf": ("HDF", "#0F766E", "#2DD4BF"),
    "pure2": ("PurE2", "#9D174D", "#F472B6"),
    "openvision": ("OV", "#3730A3", "#818CF8"),
    "opendroid": ("OD", "#3F6212", "#A3E635"),
    "satlodge": ("SL", "#78350F", "#FBBF24"),
    "dreamos": ("DM", "#1F2937", "#9CA3AF"),
    "unknown": (None, "#334155", "#64748B"),
}


def hexrgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def glyph(name, px, color="#FFFFFF", width=2.0):
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" color="%s">'
           '<g fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="%s">%s</g></svg>'
           % (color, width, G[name]))
    png = resvg_py.svg_to_bytes(svg_string=svg, width=px, height=px)
    return Image.open(io.BytesIO(bytes(png))).convert("RGBA")


def gradient(w, h, c1, c2):
    a, b = hexrgb(c1), hexrgb(c2)
    v = Image.linear_gradient("L").resize((w, h))
    hz = Image.linear_gradient("L").rotate(90).transpose(Image.FLIP_LEFT_RIGHT).resize((w, h))
    grad = ImageChops.add(v, hz, scale=2.0)
    im = Image.composite(Image.new("RGBA", (w, h), b + (255,)), Image.new("RGBA", (w, h), a + (255,)), grad)
    return im


def rmask(w, h, r, ss=4):
    m = Image.new("L", (w * ss, h * ss), 0)
    ImageDraw.Draw(m).rounded_rectangle([0, 0, w * ss - 1, h * ss - 1], r * ss, fill=255)
    return m.resize((w, h), Image.LANCZOS)


def fit_font(text, path, max_w, max_h, start):
    size = start
    while size > 6:
        f = ImageFont.truetype(path, size)
        l, t, r, b = f.getbbox(text)
        if r - l <= max_w and b - t <= max_h:
            return f
        size -= 1
    return ImageFont.truetype(path, 6)


def distro_tile(key, size):
    short, c1, c2 = DISTROS[key]
    im = gradient(size, size, c1, c2)
    hl = Image.new("RGBA", (size, size), (255, 255, 255, 0))
    ImageDraw.Draw(hl).ellipse([-size * 0.3, -size * 0.9, size * 1.3, size * 0.45], fill=(255, 255, 255, 46))
    im = Image.alpha_composite(im, hl.filter(ImageFilter.GaussianBlur(size / 10)))
    if short:
        f = fit_font(short, FONT_B, size * 0.78, size * 0.42, int(size * 0.42))
        d = ImageDraw.Draw(im)
        l, t, r, b = f.getbbox(short)
        x, y = (size - (r - l)) / 2 - l, (size - (b - t)) / 2 - t
        d.text((x + 1, y + 2), short, font=f, fill=(0, 0, 0, 70))
        d.text((x, y), short, font=f, fill=(255, 255, 255, 255))
    else:
        g = glyph("layers", int(size * 0.55))
        im.alpha_composite(g, ((size - g.width) // 2, (size - g.height) // 2))
    im.putalpha(rmask(size, size, int(size * 0.24)))
    return im


def key_icon(name, col, size):
    im = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    r, g, b = hexrgb(col)
    sq = Image.new("RGBA", (size, size), (r, g, b, 255))
    sq.putalpha(rmask(size, size, int(size * 0.28)))
    im.alpha_composite(sq)
    gl = glyph(name, int(size * 0.6), "#FFFFFF", 2.2)
    im.alpha_composite(gl, ((size - gl.width) // 2, (size - gl.height) // 2))
    return im


def pill(text, col, h):
    f = ImageFont.truetype(FONT_B, int(h * 0.52))
    l, t, r, b = f.getbbox(text)
    w = (r - l) + int(h * 1.1)
    rr, gg, bb = hexrgb(col)
    im = Image.new("RGBA", (w, h), (rr, gg, bb, 52))
    im.putalpha(Image.eval(rmask(w, h, h // 2), lambda v: v * 60 // 255))
    border = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ImageDraw.Draw(border).rounded_rectangle([0, 0, w - 1, h - 1], h // 2, outline=(rr, gg, bb, 200), width=max(1, h // 18))
    im = Image.alpha_composite(im, border)
    d = ImageDraw.Draw(im)
    d.ellipse([h * 0.32, h * 0.38, h * 0.32 + h * 0.24, h * 0.38 + h * 0.24], fill=(rr, gg, bb, 255))
    d.text((int(h * 0.7) - l, (h - (b - t)) / 2 - t), text, font=f, fill=(rr, gg, bb, 255))
    return im


def selection(w, h):
    im = gradient(w, h, "#1D4ED8", "#0E7490")
    im.putalpha(rmask(w, h, int(h * 0.2)))
    edge = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ImageDraw.Draw(edge).rounded_rectangle([0, 0, w - 1, h - 1], int(h * 0.2), outline=(103, 232, 249, 170), width=2)
    return Image.alpha_composite(im, edge)


def background(w, h, s):
    im = gradient(w, h, "#060A13", "#0B1426").convert("RGBA")
    glow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(glow)
    d.ellipse([-300 * s, -420 * s, 900 * s, 420 * s], fill=(34, 211, 238, 50))
    d.ellipse([1300 * s, 650 * s, 2300 * s, 1450 * s], fill=(124, 92, 255, 42))
    im = Image.alpha_composite(im, glow.filter(ImageFilter.GaussianBlur(160 * s)))
    card = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(card)
    R = int(22 * s)
    for box, fill, out in (((48, 150, 1172, 940), (255, 255, 255, 10), (255, 255, 255, 24)),
                           ((1200, 150, 1872, 650), (255, 255, 255, 14), (255, 255, 255, 26)),
                           ((1200, 670, 1872, 940), (255, 255, 255, 10), (255, 255, 255, 22)),
                           ((0, 1000, 1920, 1080), (255, 255, 255, 8), (255, 255, 255, 0))):
        d.rounded_rectangle([int(v * s) for v in box], R if box[0] else 0, fill=fill, outline=out, width=1)
    d.line([0, int(122 * s), w, int(122 * s)], fill=(34, 211, 238, 90), width=max(1, int(2 * s)))
    im = Image.alpha_composite(im, card)
    return im.convert("RGB")


def picker_bg(w, h, s):
    im = gradient(w, h, "#060A13", "#0B1426").convert("RGBA")
    glow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(glow)
    d.ellipse([-300 * s, -420 * s, 900 * s, 420 * s], fill=(34, 211, 238, 50))
    d.ellipse([1300 * s, 650 * s, 2300 * s, 1450 * s], fill=(124, 92, 255, 42))
    im = Image.alpha_composite(im, glow.filter(ImageFilter.GaussianBlur(160 * s)))
    card = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(card)
    d.rounded_rectangle([int(v * s) for v in (260, 120, 1660, 960)], int(26 * s),
                        fill=(255, 255, 255, 12), outline=(255, 255, 255, 28), width=1)
    d.line([int(300 * s), int(222 * s), int(1620 * s), int(222 * s)], fill=(34, 211, 238, 110), width=max(1, int(2 * s)))
    im = Image.alpha_composite(im, card)
    return im.convert("RGB")


def app_logo(size):
    im = gradient(size, size, "#0EA5E9", "#7C3AED")
    im.putalpha(rmask(size, size, int(size * 0.26)))
    d = ImageDraw.Draw(im)
    pad, gap = size * 0.2, size * 0.07
    hh = (size - 2 * pad - 2 * gap) / 3
    for i in range(3):
        y = pad + i * (hh + gap)
        a = 255 if i == 1 else 120
        d.rounded_rectangle([pad, y, size - pad, y + hh], hh / 3, fill=(255, 255, 255, a))
    return im


def build(scale, sub):
    out = os.path.join(OUT, sub)
    os.makedirs(out, exist_ok=True)
    S = lambda v: max(1, int(round(v * scale)))
    background(S(1920), S(1080), scale).save(os.path.join(out, "bg.jpg"), quality=90)
    picker_bg(S(1920), S(1080), scale).save(os.path.join(out, "bg_picker.jpg"), quality=90)
    selection(S(1092), S(92)).save(os.path.join(out, "sel.png"))
    selection(S(1300), S(92)).save(os.path.join(out, "sel_picker.png"))
    app_logo(S(64)).save(os.path.join(out, "logo.png"))
    for k in DISTROS:
        distro_tile(k, S(68)).save(os.path.join(out, "d_%s.png" % k))
        distro_tile(k, S(120)).save(os.path.join(out, "dl_%s.png" % k))
    for name, col, file in (("trash", "#EF4444", "k_red"), ("power", "#22C55E", "k_green"),
                            ("download", "#EAB308", "k_yellow"), ("save", "#3B82F6", "k_blue"),
                            ("menu", "#475569", "k_menu")):
        key_icon(name, col, S(40)).save(os.path.join(out, file + ".png"))
    for name in ("tag", "calendar", "box", "cpu", "drive", "usb", "folder", "layers", "shield"):
        glyph(name, S(26), "#8B98B0", 2.0).save(os.path.join(out, "i_%s.png" % name))
    for name, col in (("drive", "#22D3EE"), ("cpu", "#22D3EE"), ("usb", "#22D3EE")):
        glyph(name, S(22), col, 2.0).save(os.path.join(out, "t_%s.png" % name))
    for name, col, file in (("power", "#22C55E", "a_boot"), ("rotate", "#F59E0B", "a_once"),
                            ("download", "#EAB308", "a_install"), ("save", "#3B82F6", "a_backup"),
                            ("tag", "#8B5CF6", "a_settings"), ("layers", "#14B8A6", "a_copy"),
                            ("drive", "#64748B", "a_size"), ("trash", "#EF4444", "a_delete"),
                            ("drive", "#0EA5E9", "a_disk"), ("shield", "#475569", "a_help"),
                            ("archive", "#F59E0B", "a_backups"), ("globe", "#22D3EE", "a_online"),
                            ("link", "#A78BFA", "a_url"), ("folder", "#FBBF24", "a_file")):
        key_icon(name, col, S(64)).save(os.path.join(out, file + ".png"))
    cb = Image.new("RGBA", (S(44), S(44)), (0, 0, 0, 0))
    ImageDraw.Draw(cb).rounded_rectangle([1, 1, S(44) - 2, S(44) - 2], S(10), outline=(139, 152, 176, 255), width=max(2, S(3)))
    cb.save(os.path.join(out, "cb_off.png"))
    on = key_icon("check", "#22C55E", S(44))
    on.save(os.path.join(out, "cb_on.png"))
    for key, text, col in (("running", "EN COURS", "#22C55E"), ("next", "PROCHAIN DÉMARRAGE", "#22D3EE"),
                           ("once", "UNE FOIS", "#F59E0B"), ("empty", "VIDE", "#94A3B8"),
                           ("recovery", "RECOVERY", "#A78BFA"), ("beta", "BÊTA", "#F59E0B"),
                           ("eol", "FIN DE SUPPORT", "#94A3B8"), ("release", "STABLE", "#22C55E")):
        pill(text, col, S(38)).save(os.path.join(out, "p_%s.png" % key))


if __name__ == "__main__":
    build(1.0, "fhd")
    build(2 / 3.0, "hd")
    total = sum(os.path.getsize(os.path.join(dp, f)) for dp, _, fs in os.walk(OUT) for f in fs)
    print("ok", OUT, total // 1024, "KB")
