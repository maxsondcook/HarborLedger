"""Distance to SB 535 disadvantaged communities (DACs), as a raster lookup.

CARB's CHC E4 extension caps Tier 4 vessels at 1,300 hours a year near DACs.
- NOTE: the CHC fact sheet says "within 2 miles of a disadvantaged community"; we use
  2 statute miles (3,218.7 m) and expose the distance so other definitions can be tested.

Method (no GIS dependencies): project to a local equirectangular grid (200 m cells) over the
California AIS box, rasterize each DAC tract polygon (matplotlib Path, per-polygon bbox),
then compute the Euclidean distance transform from DAC cells. Boundary error is at most
~0.7 cell (~140 m), small next to the 3.2 km buffer.
"""
import json
import math
import os

import numpy as np
from matplotlib.path import Path
from scipy.ndimage import distance_transform_edt

from .ais import BBOX
from .snapshot import RAW, ROOT

CELL_M = 200.0
LAT0 = (BBOX["lat_min"] + BBOX["lat_max"]) / 2
M_PER_DEG_LAT = 111_320.0
M_PER_DEG_LON = 111_320.0 * math.cos(math.radians(LAT0))
TWO_MILES_M = 3218.69
GEOJSON = os.path.join(RAW, "calepa", "sb535_dac_2022_tracts.geojson")
CACHE = os.path.join(ROOT, "data", "dac_distance_200m.npz")


def to_xy(lon, lat):
    x = (np.asarray(lon) - BBOX["lon_min"]) * M_PER_DEG_LON
    y = (np.asarray(lat) - BBOX["lat_min"]) * M_PER_DEG_LAT
    return x, y


def grid_shape():
    nx = int(math.ceil((BBOX["lon_max"] - BBOX["lon_min"]) * M_PER_DEG_LON / CELL_M))
    ny = int(math.ceil((BBOX["lat_max"] - BBOX["lat_min"]) * M_PER_DEG_LAT / CELL_M))
    return ny, nx


def _rings(geom):
    if geom["type"] == "Polygon":
        return [geom["coordinates"]]
    if geom["type"] == "MultiPolygon":
        return geom["coordinates"]
    return []


def build_distance_raster():
    ny, nx = grid_shape()
    dac = np.zeros((ny, nx), dtype=bool)
    feats = json.load(open(GEOJSON))["features"]
    for f in feats:
        for poly in _rings(f["geometry"]):
            outer = np.asarray(poly[0])
            x, y = to_xy(outer[:, 0], outer[:, 1])
            i0, i1 = max(int(y.min() // CELL_M), 0), min(int(y.max() // CELL_M) + 1, ny)
            j0, j1 = max(int(x.min() // CELL_M), 0), min(int(x.max() // CELL_M) + 1, nx)
            if i0 >= i1 or j0 >= j1:
                continue
            jj, ii = np.meshgrid(np.arange(j0, j1), np.arange(i0, i1))
            pts = np.column_stack([(jj.ravel() + 0.5) * CELL_M, (ii.ravel() + 0.5) * CELL_M])
            inside = Path(np.column_stack([x, y])).contains_points(pts)
            for hole in poly[1:]:
                h = np.asarray(hole)
                hx, hy = to_xy(h[:, 0], h[:, 1])
                inside &= ~Path(np.column_stack([hx, hy])).contains_points(pts)
            sub = dac[i0:i1, j0:j1]
            sub |= inside.reshape(sub.shape)
    dist = distance_transform_edt(~dac) * CELL_M
    np.savez_compressed(CACHE, dist=dist.astype(np.float32), n_tracts=len(feats))
    return dist


_DIST = None


def distance_m(lon, lat):
    """Distance in metres from each point to the nearest DAC tract (0 inside a DAC)."""
    global _DIST
    if _DIST is None:
        _DIST = np.load(CACHE)["dist"] if os.path.exists(CACHE) else build_distance_raster()
    x, y = to_xy(lon, lat)
    i = np.clip((y // CELL_M).astype(int), 0, _DIST.shape[0] - 1)
    j = np.clip((x // CELL_M).astype(int), 0, _DIST.shape[1] - 1)
    return _DIST[i, j]
