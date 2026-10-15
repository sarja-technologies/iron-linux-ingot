#!/usr/bin/env python3
"""Generate installer artwork (welcome banner, slides, choice illustrations).

The slides are illustrations drawn from the Ingot wallpaper and simple window
shapes - they depict features, they are not screenshots.
usage: gen-images.py BRANDING_BUILD_DIR OUT_BRANDING_DIR OUT_SHARE_DIR
"""
import os
import sys

from PIL import Image, ImageDraw, ImageFilter, ImageFont

GRAPHITE, IRON, STEEL, COBALT, FORGE = "#0e1115", "#20262d", "#c9d1d9", "#3d7be0", "#f29a46"


def font(size, bold=False):
    for name in (f"/usr/share/fonts/opentype/inter/Inter-{'Bold' if bold else 'Regular'}.otf",
                 "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else
                 "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"):
        if os.path.exists(name):
            return ImageFont.truetype(name, size)
    return ImageFont.load_default()


def backdrop(src, size):
    im = Image.open(src).convert("RGB")
    im = im.resize(size, Image.LANCZOS)
    return im


def window(d, box, title=None, accent=False):
    x0, y0, x1, y1 = box
    d.rounded_rectangle(box, radius=10, fill="#1a1f25", outline=COBALT if accent else "#2c3440", width=2)
    d.rounded_rectangle((x0, y0, x1, y0 + 22), radius=10, fill="#232a33")
    d.rectangle((x0, y0 + 12, x1, y0 + 22), fill="#232a33")
    if title:
        d.text((x0 + 10, y0 + 4), title, fill=STEEL, font=font(12))
    for i in range(3):
        d.rounded_rectangle((x0 + 12, y0 + 36 + i * 18, x0 + 12 + (x1 - x0) * (0.7 - i * 0.15), y0 + 46 + i * 18),
                            radius=3, fill="#2c3440")


def desktop_frame(bg, wins, label=None):
    w, h = 900, 520
    im = backdrop(bg, (w, h))
    d = ImageDraw.Draw(im, "RGBA")
    d.rectangle((0, 0, w, 20), fill=(14, 17, 21, 230))
    d.text((w // 2 - 20, 3), "10:24", fill=STEEL, font=font(11, True))
    for box, title, accent in wins:
        window(d, box, title, accent)
    d.rounded_rectangle((w // 2 - 120, h - 46, w // 2 + 120, h - 10), radius=14, fill=(14, 17, 21, 200))
    for i in range(5):
        cx = w // 2 - 92 + i * 46
        d.rounded_rectangle((cx, h - 40, cx + 30, h - 16), radius=7, fill=[COBALT, "#8fb2ea", STEEL, FORGE, "#9aa8b8"][i])
    if label:
        d.rounded_rectangle((16, 32, 16 + 14 + 9 * len(label), 58), radius=8, fill=(61, 123, 224, 220))
        d.text((24, 37), label, fill="white", font=font(13, True))
    return im


def main(bdir, out_brand, out_share):
    os.makedirs(out_brand, exist_ok=True)
    os.makedirs(out_share, exist_ok=True)
    dawn, steel, forge = (os.path.join(bdir, f"ingot-{n}.jpg") for n in ("dawn", "steel", "forge"))

    Image.open(os.path.join(bdir, "iron-logo-256.png")).resize((128, 128), Image.LANCZOS).save(os.path.join(out_brand, "logo.png"))
    wel = backdrop(steel, (900, 300)).filter(ImageFilter.GaussianBlur(6))
    wm = Image.open(os.path.join(bdir, "iron-ingot-wordmark.png")).convert("RGBA")
    wel.paste(wm, ((900 - wm.width) // 2, (300 - wm.height) // 2), wm)
    wel.save(os.path.join(out_brand, "welcome.png"))

    g = 10
    two = [((g, 28, 450 - g // 2, 470), "Editor", True), ((450 + g // 2, 28, 900 - g, 470), "Terminal", False)]
    grid = [((g, 28, 445, 245), "Files", True), ((455, 28, 890, 245), "Browser", False),
            ((g, 255, 445, 470), "Editor", False), ((455, 255, 890, 470), "Terminal", False)]
    desktop_frame(dawn, [((180, 70, 720, 420), "Files", True)]).save(os.path.join(out_brand, "slide-desktop.png"))
    desktop_frame(dawn, grid, "2 × 2 grid").save(os.path.join(out_brand, "slide-tiling.png"))
    agents = desktop_frame(dawn, [((g, 28, 440, 470), "Your work", False)], None)
    d = ImageDraw.Draw(agents, "RGBA")
    ag = backdrop(forge, (430, 300))
    agents.paste(ag, (460, 60))
    d.rounded_rectangle((460, 60, 890, 360), radius=10, outline=FORGE, width=3)
    d.rounded_rectangle((470, 70, 650, 96), radius=8, fill=(242, 154, 70, 230))
    d.text((478, 75), "Agent Desktop 1", fill=GRAPHITE, font=font(13, True))
    window(d, (500, 120, 850, 330), "Agent task", True)
    d.text((470, 372), "Isolated: own disk, limits and identity", fill="white", font=font(13, True))
    agents.save(os.path.join(out_brand, "slide-agents.png"))
    apt = Image.new("RGB", (900, 520), GRAPHITE)
    d = ImageDraw.Draw(apt)
    d.rounded_rectangle((60, 40, 840, 480), radius=12, fill="#14181d", outline="#2c3440", width=2)
    for i, line in enumerate(["$ sudo apt update", "Hit:1 http://security.ubuntu.com/ubuntu resolute-security InRelease",
                              "Reading package lists... Done", "$ sudo apt install ./package.deb",
                              "Setting up package ... done", "$ "]):
        d.text((90, 80 + i * 34), line, fill=STEEL if not line.startswith("$") else "#8fb2ea", font=font(18))
    apt.save(os.path.join(out_brand, "slide-apt.png"))

    # packagechooser illustrations
    desktop_frame(dawn, grid, "Full").resize((450, 260)).save(os.path.join(out_share, "edition-full.png"))
    desktop_frame(dawn, [((180, 70, 720, 420), "Files", True)], "Lite").resize((450, 260)).save(
        os.path.join(out_share, "edition-lite.png"))
    agents.resize((450, 260)).save(os.path.join(out_share, "agents-on.png"))
    desktop_frame(dawn, [((180, 70, 720, 420), "Your work", True)]).resize((450, 260)).save(
        os.path.join(out_share, "agents-off.png"))
    drv = Image.new("RGB", (450, 260), GRAPHITE)
    d = ImageDraw.Draw(drv)
    d.rounded_rectangle((40, 40, 410, 220), radius=12, fill="#14181d", outline=COBALT, width=2)
    d.text((70, 80), "Graphics, Wi-Fi and firmware", fill="white", font=font(18, True))
    d.text((70, 120), "from Ubuntu's signed archive", fill=STEEL, font=font(15))
    drv.save(os.path.join(out_share, "drivers.png"))


if __name__ == "__main__":
    main(*sys.argv[1:4])
