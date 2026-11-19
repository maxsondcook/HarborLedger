"""California coastline for the vessel-track maps (Natural Earth 1:10m, public domain).

Downloads the coastline GeoJSON once, records it in the manifest, then clips it to California
waters and thins it to roughly 100 m so the site ships a small file (site/public/data/coast.json).
"""
import json
import os
import urllib.request

from .snapshot import RAW, ROOT, USER_AGENT, record

URL = ("https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/"
       "geojson/ne_10m_coastline.geojson")
PATH = os.path.join(RAW, "naturalearth", "ne_10m_coastline.geojson")
BBOX = (-125.5, 31.8, -114.0, 42.2)          # lon_min, lat_min, lon_max, lat_max
OUT = os.path.join(ROOT, "site", "public", "data", "coast.json")


def fetch():
    if os.path.exists(PATH):
        return PATH
    os.makedirs(os.path.dirname(PATH), exist_ok=True)
    req = urllib.request.Request(URL, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=300) as r, open(PATH + ".part", "wb") as f:
        f.write(r.read())
    os.replace(PATH + ".part", PATH)
    record(PATH, "naturalearth", URL)
    return PATH


def _inside(lon, lat):
    return BBOX[0] <= lon <= BBOX[2] and BBOX[1] <= lat <= BBOX[3]


def clip(step=0.001):
    """Lines as [[lon, lat], ...] rounded to 3 decimals, consecutive duplicates dropped."""
    g = json.load(open(fetch()))
    lines = []
    for feat in g["features"]:
        geom = feat["geometry"]
        parts = geom["coordinates"] if geom["type"] == "MultiLineString" else [geom["coordinates"]]
        for part in parts:
            run = []
            for lon, lat in part:
                if _inside(lon, lat):
                    pt = [round(lon / step) * step, round(lat / step) * step]
                    pt = [round(pt[0], 3), round(pt[1], 3)]
                    if not run or pt != run[-1]:
                        run.append(pt)
                elif run:
                    if len(run) > 1:
                        lines.append(run)
                    run = []
            if len(run) > 1:
                lines.append(run)
    return lines


def export():
    lines = clip()
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as f:
        json.dump({"source": "Natural Earth 1:10m coastline (public domain)", "bbox": BBOX, "lines": lines},
                  f, separators=(",", ":"))
    return {"lines": len(lines), "points": sum(map(len, lines)), "kb": round(os.path.getsize(OUT) / 1024)}
