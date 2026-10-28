#!/usr/bin/env python3
"""Preview a captured frame's class masks: colour, colour with the fine classes over it, the fine classes
and the coarse classes, each class named at its largest region.

    python segmentation_preview.py <camera dir>/frame_0000012 [out.png]

The class table is read from segmentation_classes.json, two folders up (the capture's output directory).
Needs numpy and opencv-python; colour is read from frame_N.png (separate layout) or frame_N.exr (combined
layout, via OpenEXR).
"""
import colorsys
import json
import os
import sys

import cv2
import numpy as np


def load_colour(base):
    if os.path.exists(base + ".png"):
        return cv2.cvtColor(cv2.imread(base + ".png", cv2.IMREAD_COLOR), cv2.COLOR_BGR2RGB)
    import OpenEXR  # combined layout: linear RGB in the EXR, depth in alpha
    channels = OpenEXR.File(base + ".exr").channels()
    px = channels["RGBA"].pixels if "RGBA" in channels else np.dstack([channels[c].pixels for c in "RGB"])
    rgb = np.clip(px[..., :3].astype(np.float32), 0, None)
    srgb = np.where(rgb <= 0.0031308, rgb * 12.92, 1.055 * np.power(rgb, 1 / 2.4) - 0.055)
    return (np.clip(srgb, 0, 1) * 255).astype(np.uint8)


def palette(seed):
    rng = np.random.RandomState(seed)
    p = np.zeros((256, 3), np.uint8)
    for i in range(1, 256):
        r, g, b = colorsys.hsv_to_rgb((i * 0.61803398875) % 1.0, 0.55 + 0.4 * rng.rand(), 0.75 + 0.25 * rng.rand())
        p[i] = (int(r * 255), int(g * 255), int(b * 255))
    return p


def put_text(img, text, x, y, scale=0.4):
    for colour, thick in (((0, 0, 0), 3), ((255, 255, 255), 1)):
        cv2.putText(img, text, (int(x), int(y)), cv2.FONT_HERSHEY_SIMPLEX, scale, colour, thick, cv2.LINE_AA)


def name_regions(img, mask, names, min_pixels=400):
    for v in np.unique(mask):
        if v == 0 or (mask == v).sum() < min_pixels:
            continue
        n, _, stats, cent = cv2.connectedComponentsWithStats((mask == v).astype(np.uint8))
        k = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
        text = names.get(int(v), str(int(v)))
        put_text(img, text, cent[k][0] - 4 * len(text), cent[k][1])
    return img


def main():
    base = sys.argv[1]
    out = sys.argv[2] if len(sys.argv) > 2 else base + "_preview.png"
    table = json.load(open(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(base)))), "segmentation_classes.json")))
    fine_names = {c["value"]: c["name"] for c in table["classes"]}
    coarse_names = {c["id"]: c["name"] for c in table["coarse"]}

    colour = load_colour(base)
    fine = cv2.imread(base + "_class.png", cv2.IMREAD_UNCHANGED)
    if fine is None:
        sys.exit("no class mask at %s_class.png" % base)
    coarse_path = base + "_class_coarse.png"
    coarse = cv2.imread(coarse_path, cv2.IMREAD_UNCHANGED) if os.path.exists(coarse_path) else None
    if coarse is None:  # rebuild it from the table
        lut = np.zeros(256, np.uint8)
        for c in table["classes"]:
            lut[c["value"]] = c["coarse_id"]
        coarse = lut[fine]
    fine_rgb, coarse_rgb = palette(1)[fine], palette(7)[coarse]

    h, w = fine.shape
    panels = [
        (colour, "colour"),
        ((0.5 * colour + 0.5 * fine_rgb).astype(np.uint8), "colour + fine classes"),
        (name_regions(fine_rgb.copy(), fine, fine_names), "fine classes"),
        (name_regions(coarse_rgb.copy(), coarse, coarse_names), "coarse classes"),
    ]
    for img, title in panels:
        put_text(img, title, 8, 18, 0.55)
    grid = np.vstack([np.hstack([panels[0][0], panels[1][0]]), np.hstack([panels[2][0], panels[3][0]])])
    cv2.imwrite(out, cv2.cvtColor(grid, cv2.COLOR_RGB2BGR))
    print(out)


if __name__ == "__main__":
    main()
