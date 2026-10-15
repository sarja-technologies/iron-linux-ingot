#!/usr/bin/env python3
"""Generate the Iron Linux Ingot wallpapers procedurally.

Original artwork: layered translucent "molten metal" waves over a warm-to-cobalt
sky, inspired by (not derived from) the reference desktop wallpaper. Fully
deterministic, so the PNGs can be regenerated from source at any resolution.

usage: gen-wallpaper.py OUTDIR [--width 3840 --height 2160]
"""
import argparse
import os

import numpy as np
from PIL import Image, ImageFilter


def lerp(a, b, t):
    return a + (b - a) * t


def smoothstep(e0, e1, x):
    t = np.clip((x - e0) / (e1 - e0), 0.0, 1.0)
    return t * t * (3 - 2 * t)


def hexrgb(h):
    h = h.lstrip("#")
    return np.array([int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4)], dtype=np.float32)


# (name, sky_top, sky_glow, layer colours dark->light, glow strength)
VARIANTS = {
    "ingot-dawn": dict(top="#4d7fdc", glow="#f6e2bf", mid="#c3d4ee",
                       layers=["#123c9c", "#1f56c4", "#3b7be0", "#8fb2ea", "#c9d8f0"], glow_k=1.0),
    "ingot-forge": dict(top="#0d1014", glow="#e07a2e", mid="#1d232b",
                        layers=["#0b0e12", "#141a21", "#1f2833", "#2c3a4a", "#46596e"], glow_k=0.85),
    "ingot-steel": dict(top="#161b22", glow="#5d86c9", mid="#232b35",
                        layers=["#0c1016", "#121a24", "#1a2a40", "#244a7a", "#3d6eae"], glow_k=0.7),
}


def render(v, w, h):
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    x = xx / w
    y = yy / h

    # Sky: vertical gradient plus warm glow low on the left.
    top, mid, glow = hexrgb(v["top"]), hexrgb(v["mid"]), hexrgb(v["glow"])
    t = smoothstep(0.0, 0.75, 1 - y)[..., None]
    img = lerp(mid, top, t)
    # Diagonal shift towards the top colour on the right.
    img = lerp(img, top, (smoothstep(0.3, 1.0, x) * 0.45)[..., None])
    d = np.sqrt(((x - 0.18) * 1.6) ** 2 + ((y - 0.55) * 2.2) ** 2)
    g = np.exp(-(d ** 2) / 0.12) * v["glow_k"]
    img = lerp(img, glow, g[..., None])

    # Layered waves, back to front. Each layer: crest curve, body colour with
    # vertical shading, a soft specular rim along the crest, partial translucency.
    layers = [hexrgb(c) for c in v["layers"]][::-1]
    params = [  # (base, amp1, freq1, phase1, amp2, freq2, phase2, alpha)
        (0.42, 0.10, 1.1, 0.6, 0.03, 3.1, 1.0, 0.55),
        (0.50, 0.09, 1.4, 2.2, 0.025, 2.7, 0.3, 0.62),
        (0.58, 0.08, 1.2, 4.0, 0.03, 3.6, 2.0, 0.75),
        (0.66, 0.07, 1.7, 1.3, 0.02, 4.2, 0.7, 0.88),
        (0.76, 0.06, 1.3, 5.1, 0.025, 3.3, 1.9, 0.96),
    ]
    for col, (base, a1, f1, p1, a2, f2, p2, alpha) in zip(layers, params):
        crest = base - a1 * np.sin(2 * np.pi * f1 * x + p1) - a2 * np.sin(2 * np.pi * f2 * x + p2)
        depth = y - crest  # >0 inside the layer
        inside = smoothstep(-0.002, 0.004, depth)
        shade = np.clip(depth * 2.2, 0, 1)
        body = lerp(col * 1.12, col * 0.62, shade[..., None])
        # Specular rim: bright thin line just under the crest, stronger where crest slopes up.
        slope = -(2 * np.pi * f1 * a1 * np.cos(2 * np.pi * f1 * x + p1))
        rim = np.exp(-((depth - 0.006) ** 2) / 0.00004) * (0.35 + 0.35 * np.tanh(slope * 3) + 0.3)
        body = body + rim[..., None] * 0.28
        # Inner sheen: broad soft highlight inside each fold.
        sheen = np.exp(-((depth - 0.06) ** 2) / 0.004) * 0.12
        body = body + sheen[..., None]
        a = (inside * alpha)[..., None]
        img = img * (1 - a) + body * a

    img = np.clip(img, 0, 1)
    out = Image.fromarray((img * 255 + 0.5).astype(np.uint8), "RGB")
    # Gentle blur for the glassy look, then tiny dither to avoid banding.
    out = out.filter(ImageFilter.GaussianBlur(radius=max(1, w // 1600)))
    rng = np.random.default_rng(7)
    arr = np.asarray(out).astype(np.int16) + rng.integers(-1, 2, size=(h, w, 3))
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8), "RGB")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("outdir")
    ap.add_argument("--width", type=int, default=3840)
    ap.add_argument("--height", type=int, default=2160)
    ap.add_argument("--only", default=None)
    args = ap.parse_args()
    os.makedirs(args.outdir, exist_ok=True)
    for name, v in VARIANTS.items():
        if args.only and name != args.only:
            continue
        path = os.path.join(args.outdir, f"{name}.png")
        render(v, args.width, args.height).save(path, optimize=True)
        print(path)


if __name__ == "__main__":
    main()
