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

from .snapshot import RAW, USER_AGENT, record

URL = "https://ocmgeodatastor1.blob.core.windows.net/marinecadastre/ais{y}/ais-{d}.parquet"
# 2025 onward is published as Zstd-compressed daily CSV (filtered to one report per minute)
CSV_URL = "https://noaaocm.blob.core.windows.net/ais/csv2/csv{y}/ais-{d}.csv.zst"
PARQUET_YEARS = {2024}
# Output schema shared by every year, so downstream code never sees a format difference
OUT_SCHEMA = pa.schema([
    ("mmsi", pa.int32()), ("base_date_time", pa.timestamp("ms")), ("sog", pa.float32()), ("cog", pa.float32()),
    ("heading", pa.int32()), ("vessel_name", pa.string()), ("imo", pa.string()), ("call_sign", pa.string()),
    ("vessel_type", pa.int32()), ("status", pa.int32()), ("length", pa.float32()), ("width", pa.int32()),
    ("draft", pa.float32()), ("transceiver", pa.string()), ("lon", pa.float64()), ("lat", pa.float64()),
])
CSV_TYPES = {"mmsi": pa.int64(), "base_date_time": pa.timestamp("s"), "longitude": pa.float64(),
             "latitude": pa.float64(), "sog": pa.float64(), "cog": pa.float64(), "heading": pa.float64(),
             "vessel_name": pa.string(), "imo": pa.string(), "call_sign": pa.string(),
             "vessel_type": pa.float64(), "status": pa.float64(), "length": pa.float64(),
             "width": pa.float64(), "draft": pa.float64(), "cargo": pa.float64(), "transceiver": pa.string()}
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


def _conform(tab):
    """Rename and cast a filtered table to OUT_SCHEMA (unsafe casts tolerate float->int with nulls)."""
    if "longitude" in tab.column_names:
        tab = tab.rename_columns(["lon" if c == "longitude" else "lat" if c == "latitude" else c
                                  for c in tab.column_names])
    cols = []
    for f in OUT_SCHEMA:
        col = tab.column(f.name) if f.name in tab.column_names else pa.nulls(tab.num_rows, f.type)
        cols.append(col.cast(f.type, safe=False))
    return pa.Table.from_arrays(cols, schema=OUT_SCHEMA)


def filter_csv(path):
    """Stream a .csv.zst daily file and keep California waters. Returns (table or None, national rows)."""
    import pyarrow.csv as pcsv
    parts, n = [], 0
    with pa.input_stream(path, compression="zstd") as f:
        reader = pcsv.open_csv(f, convert_options=pcsv.ConvertOptions(column_types=CSV_TYPES),
                               read_options=pcsv.ReadOptions(block_size=1 << 26))
        for batch in reader:
            n += batch.num_rows
            lat = batch.column("latitude").to_numpy(zero_copy_only=False)
            lon = batch.column("longitude").to_numpy(zero_copy_only=False)
            m = ((lat >= BBOX["lat_min"]) & (lat <= BBOX["lat_max"]) &
                 (lon >= BBOX["lon_min"]) & (lon <= BBOX["lon_max"]))
            if m.any():
                parts.append(_conform(pa.Table.from_batches([batch]).filter(pa.array(m))))
    return (pa.concat_tables(parts) if parts else None), n


def ca_path(day):
    return os.path.join(CA_DIR, f"ais-ca-{day.isoformat()}.parquet")


def fetch_day(day, log=sys.stdout):
    out = ca_path(day)
    if os.path.exists(out):
        return "skip"
    os.makedirs(TMP_DIR, exist_ok=True)
    os.makedirs(CA_DIR, exist_ok=True)
    is_parquet = day.year in PARQUET_YEARS
    url = (URL if is_parquet else CSV_URL).format(y=day.year, d=day.isoformat())
    tmp = os.path.join(TMP_DIR, f"ais-{day.isoformat()}." + ("parquet" if is_parquet else "csv.zst"))
    t0 = time.time()
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
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
    if is_parquet:
        pf = pq.ParquetFile(tmp)
        national = pf.metadata.num_rows
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
    else:
        tab, national = filter_csv(tmp)
    if tab is not None:
        pq.write_table(tab, out, compression="zstd")
        record(out, "marinecadastre", url, {"bbox": BBOX, "national_file_bytes": size,
                                             "national_rows": national})
    os.remove(tmp)
    print(f"{day} national={national} ca={0 if tab is None else tab.num_rows} "
          f"{time.time() - t0:.0f}s", file=log, flush=True)
    return "ok"


def fetch_range(start, end, log=sys.stdout):
    d = start
    while d <= end:
        fetch_day(d, log)
        d += dt.timedelta(days=1)
    print("FINISHED", file=log, flush=True)
