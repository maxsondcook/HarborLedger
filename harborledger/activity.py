"""AIS activity-hours accounting for harbor tugs (week 5, concept C8).

For each California AIS day file, tug positions (AIS types 31, 32, 52) are weighted by the
time to the vessel's next report (capped at 10 minutes, so gaps are not credited), then
classified into operating modes:
  idle      SOG < 0.5 kn
  assist    within 350 m of a moving large ship (types 70-89 or >= 150 m, SOG >= 1 kn)
            in the same minute, SOG < 12 kn
  maneuver  0.5-5 kn, not assist
  transit   >= 5 kn
The 350 m radius allows for AIS antenna offset: a 300 m ship's antenna sits near its bridge,
so a tug working the bow can be 250+ m from the reported position. (Set before the month run.)
Each position also gets its distance to the nearest SB 535 DAC tract, for the CARB E4
"within 2 miles of a disadvantaged community" hour split.

What AIS cannot see: engine state. Hours here are *AIS-observed activity*, not engine
hours. Idle-at-berth with engines off and idle-with-engines-on look the same.
"""
import collections
import glob
import json
import os

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from . import dac
from .ais import CA_DIR
from .snapshot import ROOT

TUG_TYPES = (31, 32, 52)
CAP_S = 600
ASSIST_RADIUS_M = 350
REGIONS = {
    "san_pedro_bay": (33.60, 33.80, -118.35, -118.10),
    "sf_bay": (37.40, 38.20, -122.60, -121.80),
    "san_diego": (32.60, 32.75, -117.27, -117.08),
}
MODES = ("idle", "assist", "maneuver", "transit")


def region_of(lat, lon):
    out = np.full(len(lat), "other", dtype=object)
    for name, (a, b, c, d) in REGIONS.items():
        out[(lat >= a) & (lat <= b) & (lon >= c) & (lon <= d)] = name
    return out


def day_tug_frame(path):
    cols = ["mmsi", "base_date_time", "sog", "vessel_type", "length", "vessel_name", "call_sign",
            "imo", "lon", "lat"]
    df = pq.read_table(path, columns=cols).to_pandas()
    tug = df[df.vessel_type.isin(TUG_TYPES) & df.sog.notna() & (df.sog < 102.2)].copy()
    tug = tug.sort_values(["mmsi", "base_date_time"])
    dt_s = tug.groupby("mmsi").base_date_time.diff(-1).dt.total_seconds().abs()
    tug["h"] = dt_s.clip(upper=CAP_S).fillna(0) / 3600.0
    big = df[(df.vessel_type.between(70, 89) | (df.length >= 150)) & (df.sog >= 1.0)]
    big = big[["base_date_time", "lat", "lon"]].copy()
    big["m"] = big.base_date_time.dt.floor("min")
    tug["m"] = tug.base_date_time.dt.floor("min")
    tug["rid"] = np.arange(len(tug))
    mm = tug[["rid", "m", "lat", "lon"]].merge(big[["m", "lat", "lon"]], on="m", suffixes=("", "_b"))
    d = np.hypot((mm.lat - mm.lat_b) * 111_320,
                 (mm.lon - mm.lon_b) * 111_320 * np.cos(np.radians(mm.lat)))
    near = np.zeros(len(tug), dtype=bool)
    near[mm.rid[d < ASSIST_RADIUS_M].unique()] = True
    sog = tug.sog.values
    tug["mode"] = np.select([sog < 0.5, near & (sog < 12), sog < 5],
                            ["idle", "assist", "maneuver"], "transit")
    tug["region"] = region_of(tug.lat.values, tug.lon.values)
    tug["dac_m"] = dac.distance_m(tug.lon.values, tug.lat.values)
    return tug


def accumulate(files=None):
    files = files or sorted(glob.glob(os.path.join(CA_DIR, "ais-ca-*.parquet")))
    per = collections.defaultdict(lambda: collections.defaultdict(float))
    meta = {}
    days = collections.defaultdict(set)
    monthly = collections.defaultdict(float)   # (mmsi, YYYY-MM, region, mode, near_dac) -> hours
    for f in files:
        day = os.path.basename(f)[7:17]
        t = day_tug_frame(f)
        t["near_dac"] = t.dac_m <= dac.TWO_MILES_M
        t["active"] = t["mode"] != "idle"
        g = t.groupby(["mmsi", "region", "mode", "near_dac"]).h.sum()
        for (m, r, mo, nd), h in g.items():
            per[m][(r, mo, bool(nd))] += h
            monthly[(int(m), day[:7], r, mo, bool(nd))] += h
        for m, sub in t.groupby("mmsi"):
            days[m].add(day)
            if m not in meta:
                r0 = sub.iloc[0]
                meta[m] = {"name": r0.vessel_name, "call_sign": r0.call_sign, "imo": r0.imo,
                           "vessel_type": int(r0.vessel_type)}
    rows = []
    for m, d in per.items():
        row = {"mmsi": int(m), **meta[m], "days_seen": len(days[m])}
        for (r, mo, nd), h in d.items():
            row[f"{r}|{mo}|{'dac' if nd else 'nodac'}"] = h
        rows.append(row)
    mon = pd.DataFrame([(*k, v) for k, v in monthly.items()],
                       columns=["mmsi", "month", "region", "mode", "near_dac", "hours"])
    accumulate.monthly = mon
    accumulate.days_per_month = collections.Counter(os.path.basename(f)[7:14] for f in files)
    return pd.DataFrame(rows).fillna(0.0), len(files)


def seasonal(mon, days_per_month, assist_mmsi):
    """Per-month active hours for the selected assist tugs, scaled to a 30-day month so months
    with missing AIS days stay comparable."""
    a = mon[mon.mmsi.isin(assist_mmsi) & (mon["mode"] != "idle")]
    by = a.groupby(["month", "mmsi"]).hours.sum().unstack(fill_value=0.0)
    by = by.reindex(columns=sorted(assist_mmsi), fill_value=0.0)
    scale = pd.Series({m: 30.0 / d for m, d in days_per_month.items()})
    per_tug_30d = by.mul(scale.reindex(by.index), axis=0)
    return {m: {"days_of_ais": int(days_per_month[m]),
                "mean_active_hours_per_tug_per_30d": round(float(per_tug_30d.loc[m].mean()), 1),
                "median": round(float(per_tug_30d.loc[m].median()), 1)}
            for m in per_tug_30d.index}


def summarize(df, n_days):
    hcols = [c for c in df.columns if c.count("|") == 2]
    pick = lambda **kw: [c for c in hcols if all(c.split("|")[["region", "mode", "dac"].index(k)] == v
                                                 for k, v in kw.items())]
    df = df.copy()
    df["hours_total"] = df[hcols].sum(axis=1)
    df["hours_active"] = df[[c for c in hcols if c.split("|")[1] != "idle"]].sum(axis=1)
    df["hours_assist"] = df[pick(mode="assist")].sum(axis=1)
    df["hours_active_dac"] = df[[c for c in hcols if c.split("|")[1] != "idle" and c.endswith("|dac")]].sum(axis=1)
    df["spb_share"] = df[pick(region="san_pedro_bay")].sum(axis=1) / df.hours_total.clip(lower=1e-9)
    ann = 365.0 / n_days
    df["active_hours_annualized"] = df.hours_active * ann
    df["active_dac_hours_annualized"] = df.hours_active_dac * ann
    # San Pedro Bay ship-assist tugs: at least half of observed time in SPB and >= 1 assist-proxy
    # hour per 3 observed days (>= ~10 h in a month)
    spb_assist = df[(df.spb_share >= 0.5) & (df.hours_assist >= df.days_seen / 3.0)]
    out = {
        "days": n_days, "tugs_seen": int(len(df)),
        "mode_hours_all_tugs": {mo: round(float(df[pick(mode=mo)].sum().sum()), 1) for mo in MODES},
        "region_active_hours": {r: round(float(df[[c for c in pick(region=r) if c.split('|')[1] != 'idle']].sum().sum()), 1)
                                for r in list(REGIONS) + ["other"]},
        "share_active_hours_within_2mi_dac": round(float(df.hours_active_dac.sum() / df.hours_active.sum()), 3),
        "spb_assist_tugs": {
            "n": int(len(spb_assist)),
            "active_hours_annualized_mean": round(float(spb_assist.active_hours_annualized.mean()), 0),
            "active_hours_annualized_median": round(float(spb_assist.active_hours_annualized.median()), 0),
            "active_hours_annualized_iqr": [round(float(x), 0) for x in spb_assist.active_hours_annualized.quantile([.25, .75])],
            "dac_share_of_active": round(float(spb_assist.hours_active_dac.sum() / spb_assist.hours_active.sum()), 3),
            "days_seen_median": float(spb_assist.days_seen.median()),
            "e4_cap_1300_dac_hours_exceeded_annualized": int((spb_assist.active_dac_hours_annualized > 1300).sum()),
            "e4_cap_2600_total_hours_exceeded_annualized": int((spb_assist.active_hours_annualized > 2600).sum()),
        },
        "assist_tug_mmsi": sorted(int(x) for x in spb_assist.mmsi),
        "benchmarks": {
            "POLA_2023_inventory_assist_tug_avg_hours": 1387,
            "POLA_note": "operator-reported engine hours, 11 assist tugs, Port of LA 2023 inventory (Starcrest)",
            "CARB_2021_ship_assist_main_engine_hours": 2676,
        },
    }
    keep = ["mmsi", "name", "call_sign", "vessel_type", "days_seen", "hours_total", "hours_active",
            "hours_assist", "hours_active_dac", "spb_share", "active_hours_annualized",
            "active_dac_hours_annualized"]
    return out, df[keep].sort_values("hours_active", ascending=False)


def run():
    df, n = accumulate()
    out, per = summarize(df, n)
    mon = accumulate.monthly
    out["coverage_days"] = n
    out["by_month_spb_assist"] = seasonal(mon, accumulate.days_per_month, out["assist_tug_mmsi"])
    if out["by_month_spb_assist"]:
        vals = [v["mean_active_hours_per_tug_per_30d"] for v in out["by_month_spb_assist"].values()]
        out["seasonality_peak_to_trough"] = round(max(vals) / max(min(vals), 1e-9), 2)
    os.makedirs(os.path.join(ROOT, "eval"), exist_ok=True)
    per.round(2).to_csv(os.path.join(ROOT, "eval", "tug_activity_by_vessel.csv"), index=False)
    os.makedirs(os.path.join(ROOT, "data", "derived"), exist_ok=True)
    df.to_csv(os.path.join(ROOT, "data", "derived", "tug_activity_full.csv"), index=False)
    mon.round(3).to_csv(os.path.join(ROOT, "data", "derived", "tug_activity_monthly.csv"), index=False)
    with open(os.path.join(ROOT, "eval", "tug_activity_results.json"), "w") as f:
        json.dump(out, f, indent=2)
    print(json.dumps(out, indent=2))
    return out
