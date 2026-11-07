#!/usr/bin/env python3
"""Draw a planned route (list of [lat, lon]) on OpenStreetMap tiles and save a PNG.

    route_map.py ROUTE_POINTS.json OUT.png [--mark NAME LAT LON ...] [--zoom 19]

Tiles come from tile.openstreetmap.org (a handful per map, cached in ./tiles/, with a User-Agent, per the
OSM tile usage policy). Map data (c) OpenStreetMap contributors.
"""
import argparse
import io
import json
import math
import os
import urllib.request

import matplotlib
matplotlib.use("Agg")
import matplotlib.image as mpimg      # noqa: E402
import matplotlib.pyplot as plt       # noqa: E402
import numpy as np                    # noqa: E402

UA = "sdteam22-robot/1.0 (Purdue ECE49022 student project)"


def tile_xy(lat, lon, z):
    n = 2 ** z
    x = (lon + 180) / 360 * n
    y = (1 - math.log(math.tan(math.radians(lat)) + 1 / math.cos(math.radians(lat))) / math.pi) / 2 * n
    return x, y


def tile(z, x, y, cache="tiles"):
    os.makedirs(cache, exist_ok=True)
    path = os.path.join(cache, f"{z}_{x}_{y}.png")
    if not os.path.exists(path):
        req = urllib.request.Request(f"https://tile.openstreetmap.org/{z}/{x}/{y}.png", headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=20) as r, open(path, "wb") as f:
            f.write(r.read())
    return mpimg.imread(path, format="png")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("points")
    ap.add_argument("out")
    ap.add_argument("--mark", nargs=3, action="append", default=[], metavar=("NAME", "LAT", "LON"))
    ap.add_argument("--zoom", type=int, default=19)
    ap.add_argument("--title", default="")
    a = ap.parse_args()
    pts = json.load(open(a.points))
    marks = [(n, float(la), float(lo)) for n, la, lo in a.mark]
    lats = [p[0] for p in pts] + [m[1] for m in marks]
    lons = [p[1] for p in pts] + [m[2] for m in marks]
    pad = 0.00030
    x0, y0 = tile_xy(max(lats) + pad, min(lons) - pad, a.zoom)
    x1, y1 = tile_xy(min(lats) - pad, max(lons) + pad, a.zoom)
    tx = range(int(x0), int(x1) + 1)
    ty = range(int(y0), int(y1) + 1)
    rows = [np.concatenate([tile(a.zoom, x, y)[..., :3] for x in tx], axis=1) for y in ty]
    img = np.concatenate(rows, axis=0)

    def px(lat, lon):                                  # pixel position within the stitched image
        x, y = tile_xy(lat, lon, a.zoom)
        return (x - tx[0]) * 256, (y - ty[0]) * 256

    fig, ax = plt.subplots(figsize=(7, 7 * img.shape[0] / img.shape[1]))
    ax.imshow(img)
    P = np.array([px(*p) for p in pts])
    ax.plot(P[:, 0], P[:, 1], "-", color="#2a78d6", lw=4, alpha=0.9, label="planned route")
    ax.plot(P[:, 0], P[:, 1], "o", color="#2a78d6", ms=4)
    for i, (name, la, lo) in enumerate(marks):
        x, y = px(la, lo)
        ax.plot(x, y, "o", ms=11, mec="black", mfc=("#1baf7a", "#d03b3b", "#fab219")[i % 3], label=name)
    # 20 m scale bar
    m_per_px = 156543.03392 * math.cos(math.radians(lats[0])) / 2 ** a.zoom
    L = 20 / m_per_px
    cx0, cy0 = px(max(lats) + pad, min(lons) - pad)
    cx1, cy1 = px(min(lats) - pad, max(lons) + pad)
    sx, sy = cx0 + 0.05 * (cx1 - cx0), cy1 - 0.04 * (cy1 - cy0)          # scale bar, bottom left of the view
    ax.plot([sx, sx + L], [sy, sy], "k-", lw=3)
    ax.text(sx, sy - 0.015 * (cy1 - cy0), "20 m", fontsize=9)
    ax.set_xlim(cx0, cx1); ax.set_ylim(cy1, cy0)
    ax.set_xticks([]); ax.set_yticks([])
    ax.legend(loc="upper right", fontsize=8)
    ax.set_title(a.title, fontsize=10)
    ax.text(0.99, 0.005, "© OpenStreetMap contributors", transform=ax.transAxes, ha="right", va="bottom", fontsize=7)
    fig.savefig(a.out, dpi=120, bbox_inches="tight")
    print(f"map: {a.out}")


if __name__ == "__main__":
    main()
