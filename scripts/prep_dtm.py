#!/usr/bin/env python3
"""Cut the Ministry of the Interior 20 m DTM (2025 edition, Taitung County sheets) to a window
around Torik (都歷) and write data/torik_dtm20.json.

Run by hand: python3 scripts/prep_dtm.py /path/to/分幅_臺東縣20MDEM(2025).zip
The archive is open data but its host (www.tgos.tw) refuses GitHub runners, so this step
is not scheduled. Needs numpy and pyproj.

Each .grd file is plain text, one "E N H" row per 20 m cell, TWD97 TM2 zone 121 (EPSG:3826),
heights on TWVD2001. Cells over the sea are absent from the files.
"""
import json
import os
import sys
import zipfile

import numpy as np
from pyproj import Transformer

TORIK = (121.3340, 23.0236)
WEST, EAST, SOUTH, NORTH = -4000, 2000, -3000, 3000      # window edges in metres from the Torik marker
STEP = 20
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "torik_dtm20.json")


def main(path):
    to_tm = Transformer.from_crs(4326, 3826, always_xy=True)
    to_ll = Transformer.from_crs(3826, 4326, always_xy=True)
    e_mark, n_mark = to_tm.transform(*TORIK)
    snap = lambda v: round(v / STEP) * STEP
    e0, e1, n0, n1 = snap(e_mark + WEST), snap(e_mark + EAST), snap(n_mark + SOUTH), snap(n_mark + NORTH)
    cols, rows = (e1 - e0) // STEP + 1, (n1 - n0) // STEP + 1
    grid = np.full((rows, cols), np.nan)
    sheets, clashes = [], 0
    with zipfile.ZipFile(path) as z:
        names = {i.filename for i in z.infolist()}
        for name in sorted(n for n in names if n.endswith(".hdr")):
            h = z.read(name).decode("big5", "replace").split("\r\n")
            he, hn, hc, hr = float(h[10]), float(h[11]), int(h[8]), int(h[9])
            # the header origin is the sheet's south-west corner
            if he > e1 or he + STEP * hc < e0 or hn > n1 or hn + STEP * hr < n0:
                continue
            a = np.loadtxt(z.open(name[:-4] + ".grd"))
            m = (a[:, 0] >= e0) & (a[:, 0] <= e1) & (a[:, 1] >= n0) & (a[:, 1] <= n1)
            if not m.any():
                continue
            a = a[m]
            j = ((a[:, 0] - e0) / STEP).round().astype(int)
            i = ((a[:, 1] - n0) / STEP).round().astype(int)
            old = grid[i, j]
            both = np.isfinite(old)
            clashes += int((np.abs(old[both] - a[both, 2]) > 0.05).sum())
            grid[i, j] = a[:, 2]
            sheets.append({"sheet": name[:-7], "name": h[0], "method": h[13], "sensor": h[14],
                           "header_date": h[19], "agency": h[20], "datum": h[2], "height_datum": h[3],
                           "cells": int(m.sum())})
    land = np.isfinite(grid)
    z_land = grid[land]
    corners = {k: [round(v, 6) for v in to_ll.transform(e, n)] for k, (e, n) in
               {"sw": (e0, n0), "se": (e1, n0), "nw": (e0, n1), "ne": (e1, n1)}.items()}
    out = {
        "source": "內政部地政司，2025 年版全臺灣 20 公尺網格數值地形模型 DTM 資料，分幅_臺東縣20MDEM(2025)",
        "license": "政府資料開放授權條款－第1版",
        "crs": "TWD97 TM2 zone 121 (EPSG:3826)", "height_datum": "TWVD2001", "step_m": STEP,
        "e0": e0, "n0": n0, "cols": int(cols), "rows": int(rows),
        "marker": {"e": round(e_mark, 1), "n": round(n_mark, 1), "lon": TORIK[0], "lat": TORIK[1]},
        "corners_lonlat": corners, "sheets": sheets,
        "stats": {"land_cells": int(land.sum()), "empty_cells": int((~land).sum()),
                  "min": round(float(z_land.min()), 2), "max": round(float(z_land.max()), 2),
                  "land_at_or_below": {str(k): int((z_land <= k).sum()) for k in (0, 1, 2, 3, 5, 10)},
                  "overlap_disagreements": clashes},
        # rows run south to north, columns west to east; null = no data (sea)
        "z": [[None if not np.isfinite(v) else round(float(v), 1) for v in row] for row in grid],
    }
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    print(json.dumps({k: v for k, v in out.items() if k != "z"}, ensure_ascii=False, indent=1))
    print(os.path.getsize(OUT), "bytes")


if __name__ == "__main__":
    main(sys.argv[1])
