"""Public ocean and weather data: NOAA NDBC buoy observations (hourly standard meteorology).

Files: https://www.ndbc.noaa.gov/data/historical/stdmet/<station>h<year>.txt.gz (US federal data,
public domain). Columns: #YY MM DD hh mm WDIR WSPD GST WVHT DPD APD MWD PRES ATMP WTMP DEWP VIS TIDE;
missing values are 99, 999, 9999 (or MM). Times are UTC.
"""
import gzip
import io
import os
import re
import time
import urllib.request

import numpy as np
import pandas as pd

from .snapshot import RAW, record

NDBC_DIR = os.path.join(RAW, "ndbc")
URL = "https://www.ndbc.noaa.gov/data/historical/stdmet/{s}h{y}.txt.gz"
STATIONS_URL = "https://www.ndbc.noaa.gov/activestations.xml"

# California buoys with 2024 and 2025 records (checked 2026-11-07); 46012 and 46042 have none.
CA_STATIONS = ["46026", "46013", "46014", "46028", "46011", "46054", "46053", "46025", "46086",
               "46047", "46069", "46219", "46221", "46222", "46232"]
MISSING = {"WDIR": 999, "WSPD": 99, "GST": 99, "WVHT": 99, "DPD": 99, "APD": 99, "MWD": 999,
           "PRES": 9999, "ATMP": 999, "WTMP": 999, "DEWP": 999, "VIS": 99, "TIDE": 99}


def _get(url, path, source_params):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if os.path.exists(path):
        return path
    req = urllib.request.Request(url, headers={"User-Agent": "harborledger/0.1 (research)"})
    with urllib.request.urlopen(req, timeout=120) as r, open(path, "wb") as f:
        f.write(r.read())
    record(path, "ndbc", url, source_params)
    time.sleep(0.5)
    return path


def fetch(stations=CA_STATIONS, years=(2024, 2025)):
    got = []
    for s in stations:
        for y in years:
            p = os.path.join(NDBC_DIR, f"{s}h{y}.txt.gz")
            try:
                got.append(_get(URL.format(s=s, y=y), p, {"station": s, "year": y}))
            except Exception as e:
                print("skip", s, y, e)
    _get(STATIONS_URL, os.path.join(NDBC_DIR, "activestations.xml"), {"what": "station metadata"})
    return got


def stations_meta():
    """Station id -> (lat, lon, name) from NDBC's station list."""
    xml = open(os.path.join(NDBC_DIR, "activestations.xml"), encoding="utf-8").read()
    out = {}
    for m in re.finditer(r'<station id="(\w+)" lat="([-\d.]+)" lon="([-\d.]+)"[^>]*?name="([^"]*)"', xml):
        out[m.group(1).upper()] = (float(m.group(2)), float(m.group(3)), m.group(4))
    return out


def read_stdmet(path):
    with gzip.open(path, "rt") as f:
        lines = f.read().splitlines()
    header = lines[0].lstrip("#").split()
    rows = [l.split() for l in lines[2:] if l.strip()]
    df = pd.DataFrame(rows, columns=header[:len(rows[0])]).apply(pd.to_numeric, errors="coerce")
    df["time"] = pd.to_datetime(dict(year=df.YY, month=df.MM, day=df.DD, hour=df.hh, minute=df.mm), utc=True)
    for c, bad in MISSING.items():
        if c in df:
            df.loc[df[c] >= bad, c] = np.nan
    return df.drop(columns=["YY", "MM", "DD", "hh", "mm"])


def hourly(stations=CA_STATIONS, years=(2024, 2025)):
    """One row per station-hour: wind speed/direction/gust (m/s, deg), significant wave height (m),
    dominant/average period (s), mean wave direction (deg), air and water temperature (C)."""
    meta = stations_meta()
    parts = []
    for s in stations:
        for y in years:
            p = os.path.join(NDBC_DIR, f"{s}h{y}.txt.gz")
            if not os.path.exists(p):
                continue
            d = read_stdmet(p)
            d["hour"] = d.time.dt.floor("h").dt.tz_localize(None).astype("datetime64[ns]")   # naive UTC
            h = d.groupby("hour")[[c for c in ("WDIR", "WSPD", "GST", "WVHT", "DPD", "APD", "MWD",
                                               "ATMP", "WTMP") if c in d]].mean().reset_index()
            h["station"] = s
            lat, lon, name = meta.get(s, (np.nan, np.nan, ""))
            h["lat"], h["lon"], h["name"] = lat, lon, name
            parts.append(h)
    return pd.concat(parts, ignore_index=True)


# ---------- ERDDAP (NOAA SWFSC / CoastWatch): upwelling indices, SST, chlorophyll ----------
ERDDAP_DIR = os.path.join(RAW, "erddap")
OCEANVIEW = "https://oceanview.pfeg.noaa.gov/erddap/griddap/"
COASTWATCH = "https://coastwatch.pfeg.noaa.gov/erddap/griddap/"


def erddap_csv(server, dataset, query, name, retries=4):
    """Download an ERDDAP griddap CSV subset once (cached) and record it in the manifest."""
    os.makedirs(ERDDAP_DIR, exist_ok=True)
    path = os.path.join(ERDDAP_DIR, name)
    if os.path.exists(path):
        return path
    url = f"{server}{dataset}.csv?{query}"
    last = None
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "harborledger/0.1 (research)"})
            with urllib.request.urlopen(req, timeout=300) as r, open(path, "wb") as f:
                f.write(r.read())
            record(path, "erddap", url, {"dataset": dataset})
            return path
        except Exception as e:
            last = e
            time.sleep(30 * (i + 1))
    raise RuntimeError(f"ERDDAP failed {dataset}: {last}")


def read_erddap_csv(path):
    """ERDDAP CSV: header row, units row, then data."""
    df = pd.read_csv(path, skiprows=[1])
    if "time" in df:
        df["time"] = pd.to_datetime(df.time, utc=True).dt.tz_localize(None)
    return df


def upwelling(years=(2024, 2025)):
    """Daily CUTI (vertical transport) and BEUTI (nitrate flux) for 32N-39N (California coast)."""
    q = lambda v: f"{v}%5B({years[0]}-01-01T00:00:00Z):1:({years[-1]}-12-31T00:00:00Z)%5D%5B(32.0):1:(39.0)%5D"
    a = read_erddap_csv(erddap_csv(OCEANVIEW, "erdCUTIdaily", q("CUTI"), f"cuti_{years[0]}_{years[-1]}.csv"))
    b = read_erddap_csv(erddap_csv(OCEANVIEW, "erdBEUTIdaily", q("BEUTI"), f"beuti_{years[0]}_{years[-1]}.csv"))
    return a.merge(b, on=["time", "latitude"], how="outer")


def sst(years=(2024, 2025)):
    """NOAA OISST v2.1 daily sea-surface temperature, 0.25 deg, over the California AIS box."""
    q = (f"sst%5B({years[0]}-01-01T12:00:00Z):1:({years[-1]}-12-31T12:00:00Z)%5D%5B(0.0)%5D"
         f"%5B(32.375):1:(38.625)%5D%5B(236.625):1:(243.125)%5D")
    d = read_erddap_csv(erddap_csv(COASTWATCH, "ncdcOisst21Agg", q, f"oisst_{years[0]}_{years[-1]}.csv"))
    d["lon"] = d.longitude - 360.0
    return d.rename(columns={"latitude": "lat"})[["time", "lat", "lon", "sst"]].dropna()


def chlorophyll(years=(2024, 2025), stride=20):
    """NOAA VIIRS chlorophyll-a, 8-day composites (750 m grid sampled every `stride` cells, ~0.15 deg)."""
    q = (f"chla%5B({years[0]}-01-01T00:00:00Z):1:({years[-1]}-12-31T00:00:00Z)%5D%5B(0.0)%5D"
         f"%5B(38.6):{stride}:(32.4)%5D%5B(-123.3):{stride}:(-116.9)%5D")
    d = read_erddap_csv(erddap_csv(COASTWATCH, "erdVHNchla8day", q, f"chla8day_{years[0]}_{years[-1]}_s{stride}.csv"))
    return d.rename(columns={"latitude": "lat", "longitude": "lon"})[["time", "lat", "lon", "chla"]].dropna()
