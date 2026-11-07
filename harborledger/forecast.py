"""Archived NOAA GFS-Wave forecasts (West Coast 0.167-degree grid) from the NOAA Open Data
Dissemination bucket on AWS (public, no account):
  https://noaa-gfs-bdp-pds.s3.amazonaws.com/gfs.YYYYMMDD/HH/wave/gridded/gfswave.tHHz.wcoast.0p16.fFFF.grib2

Only the needed GRIB2 messages are downloaded, using the .idx byte offsets and HTTP Range requests:
HTSGW (significant wave height, m) and DIRPW (primary wave direction, degrees, direction waves come
from). The messages use JPEG2000 packing (GRIB2 data template 5.40), which is decoded with Pillow's
OpenJPEG support, so no GRIB library is needed. The decoder handles exactly this case (grid template
3.0 regular lat/lon, data template 5.40, bitmap present) and refuses anything else.
"""
import io
import os
import struct
import time
import urllib.request

import numpy as np

from .snapshot import RAW, record

BASE = "https://noaa-gfs-bdp-pds.s3.amazonaws.com/gfs.{d}/{h:02d}/wave/gridded/gfswave.t{h:02d}z.wcoast.0p16.f{f:03d}.grib2"
CACHE = os.path.join(RAW, "gfswave")
VARS = ("HTSGW", "DIRPW")


def _get(url, rng=None, timeout=60, retries=3):
    last = None
    for i in range(retries):
        try:
            h = {"User-Agent": "harborledger/0.1 (research)"}
            if rng:
                h["Range"] = f"bytes={rng[0]}-{rng[1]}"
            with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=timeout) as r:
                return r.read()
        except Exception as e:
            last = e
            time.sleep(2 * (i + 1))
    raise RuntimeError(f"{url}: {last}")


def fetch_messages(cycle, fhour, variables=VARS, _retry=False):
    """Cached raw GRIB2 messages for one cycle (datetime) and forecast hour. Returns {var: bytes}."""
    d, h = cycle.strftime("%Y%m%d"), cycle.hour
    path = os.path.join(CACHE, f"{d}{h:02d}_f{fhour:03d}.grib2")
    url = BASE.format(d=d, h=h, f=fhour)
    if not os.path.exists(path):
        idx = _get(url + ".idx").decode().splitlines()
        offs = [(int(l.split(":")[1]), l.split(":")[3]) for l in idx]
        parts = []
        for k, (start, var) in enumerate(offs):
            if var in variables:
                end = offs[k + 1][0] - 1 if k + 1 < len(offs) else ""
                parts.append(_get(url, (start, end)))
        os.makedirs(CACHE, exist_ok=True)
        with open(path, "wb") as f:
            f.write(b"".join(parts))
        record(path, "gfswave", url, {"cycle": cycle.isoformat(), "fhour": fhour, "vars": list(variables)})
    try:
        out = _split(open(path, "rb").read())
        if not all(v in out for v in variables):
            raise ValueError("missing variables")
        return out
    except Exception:
        os.remove(path)                       # truncated or corrupt cache file: fetch again once
        if _retry:
            raise
        return fetch_messages(cycle, fhour, variables, _retry=True)


def _split(b):
    out, pos = {}, 0
    while pos < len(b):
        if b[pos:pos + 4] != b"GRIB":
            raise ValueError("bad GRIB message boundary")
        n = struct.unpack(">Q", b[pos + 8:pos + 16])[0]
        msg = b[pos:pos + n]
        if len(msg) != n or msg[-4:] != b"7777":
            raise ValueError("truncated GRIB message")
        out[_param_name(msg)] = msg
        pos += n
    return out


def _sections(msg):
    pos, secs = 16, {}
    while pos < len(msg) - 4 and msg[pos:pos + 4] != b"7777":
        L = struct.unpack(">I", msg[pos:pos + 4])[0]
        secs[msg[pos + 4]] = msg[pos:pos + L]
        pos += L
    return secs


def _param_name(msg):
    s4 = _sections(msg)[4]
    cat, num = s4[9], s4[10]                  # discipline 10 (oceanographic), category 0 (waves)
    return {(0, 3): "HTSGW", (0, 10): "DIRPW", (0, 11): "PERPW"}.get((cat, num), f"{cat}_{num}")


def decode(msg):
    """Decode one GRIB2 message (grid 3.0 + data 5.40 + bitmap) -> (lats, lons, 2-D array)."""
    from PIL import Image
    s = _sections(msg)
    s3, s5, s6, s7 = s[3], s[5], s[6], s[7]
    if struct.unpack(">H", s3[12:14])[0] != 0 or struct.unpack(">H", s5[9:11])[0] != 40:
        raise ValueError("unsupported GRIB2 template")
    ni, nj = struct.unpack(">II", s3[30:38])
    la1, lo1 = struct.unpack(">iI", s3[46:54])
    la2, lo2 = struct.unpack(">iI", s3[55:63])
    di, dj = struct.unpack(">II", s3[63:71])
    scan = s3[71]
    R = struct.unpack(">f", s5[11:15])[0]
    E = struct.unpack(">h", bytes([s5[15] & 0x7F, s5[16]]))[0] * (-1 if s5[15] & 0x80 else 1)
    D = struct.unpack(">h", bytes([s5[17] & 0x7F, s5[18]]))[0] * (-1 if s5[17] & 0x80 else 1)
    nbits = s5[19]
    npts = ni * nj
    if s6[5] == 0:
        bits = np.unpackbits(np.frombuffer(s6[6:], dtype=np.uint8))[:npts].astype(bool)
    else:
        bits = np.ones(npts, bool)
    if nbits == 0:
        vals = np.full(bits.sum(), R)
    else:
        img = Image.open(io.BytesIO(s7[5:]))
        x = np.asarray(img, dtype=np.float64).ravel()
        vals = (R + x * 2.0 ** E) / 10.0 ** D
    grid = np.full(npts, np.nan)
    grid[bits] = vals[:bits.sum()]
    grid = grid.reshape(nj, ni)
    lats = la1 / 1e6 + np.arange(nj) * (dj / 1e6) * (1 if scan & 0x40 else -1)
    lons = lo1 / 1e6 + np.arange(ni) * (di / 1e6)
    lons = np.where(lons > 180, lons - 360, lons)
    return lats, lons, grid


def sample(lats, lons, grid, plat, plon):
    """Nearest grid value at each point (NaN over land / missing)."""
    i = np.abs(lats[:, None] - np.asarray(plat)[None, :]).argmin(axis=0)
    j = np.abs(lons[:, None] - np.asarray(plon)[None, :]).argmin(axis=0)
    return grid[i, j]


# ---------- forecast features for coastal legs ----------
FHOURS = tuple(range(6, 61, 6))      # forecast hours fetched per cycle (covers departure +0..48 h)


def cycle_for(ts):
    """Latest 00Z/12Z GFS cycle at or before ts (what a planner could have used at departure)."""
    import pandas as pd
    t = pd.Timestamp(ts).floor("12h")
    return t.to_pydatetime()


def reference_route(big, step=0.25):
    """Median open-water track of large ships between the LA and SF approaches, as waypoints."""
    import pandas as pd
    b = big[big.lat.between(33.6, 37.8) & (big.lon > -124.5)]
    bands = np.arange(33.75, 37.8, step)
    lons = [b[(b.lat >= x - step / 2) & (b.lat < x + step / 2)].lon.median() for x in bands]
    return pd.DataFrame({"lat": bands, "lon": lons}).dropna()


def fetch_cycles(cycles, log=print, workers=8):
    """Download every (cycle, forecast hour) pair with a small thread pool; cached files are skipped."""
    import threading
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from . import snapshot
    lock = threading.Lock()
    orig = snapshot.record

    def safe_record(*a, **k):                     # manifest appends from several threads
        with lock:
            return orig(*a, **k)
    globals()["record"] = safe_record
    jobs = [(c, f) for c in sorted(set(cycles)) for f in FHOURS]
    done = fail = 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(fetch_messages, c, f): (c, f) for c, f in jobs}
        for fut in as_completed(futs):
            try:
                fut.result()
                done += 1
            except Exception as e:
                fail += 1
                log(f"skip {futs[fut]}: {e}")
            if (done + fail) % 500 == 0:
                log(f"{done + fail}/{len(jobs)} files (failed {fail})")
    globals()["record"] = orig
    log(f"FINISHED {done} ok, {fail} failed")


def leg_features(legs, route):
    """Forecast wave height along the route for the 48 h after departure, from the last cycle
    issued before departure. Head seas: waves coming from within 45 degrees of the bow, using the
    route's bearing (north-west for northbound, south-east for southbound)."""
    import pandas as pd
    rows = []
    for L in legs.itertuples():
        c = cycle_for(L.depart)
        offset = (pd.Timestamp(L.depart) - pd.Timestamp(c)).total_seconds() / 3600
        hs_all, head_all = [], []
        bearing = 315.0 if L.to == "SF" else 135.0
        for f in FHOURS:
            if f < offset or f > offset + 48:
                continue
            try:
                m = fetch_messages(c, f)
            except Exception:
                continue
            la, lo, hs = decode(m["HTSGW"])
            _, _, dr = decode(m["DIRPW"])
            h = sample(la, lo, hs, route.lat.values, route.lon.values)
            d = sample(la, lo, dr, route.lat.values, route.lon.values)
            rel = np.abs(((d - bearing) + 180) % 360 - 180)
            hs_all.append(h)
            head_all.append(np.where(rel <= 45, h, np.nan))
        if not hs_all:
            rows.append({"fc_cycle": c, "fc_hs_mean": np.nan, "fc_hs_max": np.nan, "fc_head_share": np.nan,
                         "fc_head_hs_mean": np.nan, "fc_steps": 0})
            continue
        H, Hh = np.concatenate(hs_all), np.concatenate(head_all)
        rows.append({"fc_cycle": c, "fc_hs_mean": float(np.nanmean(H)), "fc_hs_max": float(np.nanmax(H)),
                     "fc_head_share": float(np.mean(~np.isnan(Hh))),
                     "fc_head_hs_mean": float(np.nanmean(Hh)) if (~np.isnan(Hh)).any() else 0.0,
                     "fc_steps": len(hs_all)})
    return pd.concat([legs.reset_index(drop=True), pd.DataFrame(rows)], axis=1)
