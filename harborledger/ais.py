"""MarineCadastre AIS: download national daily GeoParquet files, keep only California
waters, and record each California subset in the manifest. The ~300 MB national file is
deleted after filtering, so a month needs ~1 GB rather than ~9 GB."""
import datetime as dt
import os
import sys
import time
import urllib.request

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from .snapshot import RAW, record

URL = "https://ocmgeodatastor1.blob.core.windows.net/marinecadastre/ais{y}/ais-{d}.parquet"
CA_DIR = os.path.join(RAW, "ais_ca")
TMP_DIR = os.path.join(RAW, "ais_tmp")
# California coastal waters incl. SF Bay / Delta, San Pedro Bay, San Diego
BBOX = {"lat_min": 32.4, "lat_max": 38.6, "lon_min": -123.3, "lon_max": -116.9}
KEEP = ["mmsi", "base_date_time", "sog", "cog", "heading", "vessel_name", "imo", "call_sign",
        "vessel_type", "status", "length", "width", "draft", "transceiver"]


def decode_points(wkb_col):
    """WKB Point (little-endian, 21 bytes): 1 byte order + 4 type + 8 x + 8 y."""
    buf = b"".join(bytes(g)[5:21] for g in wkb_col.to_pylist())
    xy = np.frombuffer(buf, dtype="<f8").reshape(-1, 2)
    return xy[:, 0], xy[:, 1]


def ca_path(day):
    return os.path.join(CA_DIR, f"ais-ca-{day.isoformat()}.parquet")


def fetch_day(day, log=sys.stdout):
    out = ca_path(day)
    if os.path.exists(out):
        return "skip"
    os.makedirs(TMP_DIR, exist_ok=True)
    os.makedirs(CA_DIR, exist_ok=True)
    url = URL.format(y=day.year, d=day.isoformat())
    tmp = os.path.join(TMP_DIR, f"ais-{day.isoformat()}.parquet")
    t0 = time.time()
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "harborledger/0.1 (research)"})
            with urllib.request.urlopen(req, timeout=600) as r, open(tmp, "wb") as f:
                while True:
                    chunk = r.read(1 << 22)
                    if not chunk:
                        break
                    f.write(chunk)
            break
        except Exception as e:
            print(f"retry {day} {e}", file=log, flush=True)
            time.sleep(20 * (attempt + 1))
    else:
        return "fail"
    size = os.path.getsize(tmp)
    pf = pq.ParquetFile(tmp)
    parts = []
    for i in range(pf.num_row_groups):
        t = pf.read_row_group(i, columns=KEEP + ["geometry"])
        lon, lat = decode_points(t.column("geometry"))
        m = ((lat >= BBOX["lat_min"]) & (lat <= BBOX["lat_max"]) &
             (lon >= BBOX["lon_min"]) & (lon <= BBOX["lon_max"]))
        if m.any():
            sub = t.drop(["geometry"]).filter(pa.array(m))
            sub = sub.append_column("lon", pa.array(lon[m])).append_column("lat", pa.array(lat[m]))
            parts.append(sub)
    tab = pa.concat_tables(parts) if parts else None
    if tab is not None:
        pq.write_table(tab, out, compression="zstd")
        record(out, "marinecadastre", url, {"bbox": BBOX, "national_file_bytes": size,
                                             "national_rows": pf.metadata.num_rows})
    os.remove(tmp)
    print(f"{day} national={pf.metadata.num_rows} ca={0 if tab is None else tab.num_rows} "
          f"{time.time() - t0:.0f}s", file=log, flush=True)
    return "ok"


def fetch_range(start, end, log=sys.stdout):
    d = start
    while d <= end:
        fetch_day(d, log)
        d += dt.timedelta(days=1)
    print("FINISHED", file=log, flush=True)
