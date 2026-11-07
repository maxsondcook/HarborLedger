"""Fishing activity versus ocean conditions (Option 2).

Fishing hours: AIS vessel type 30 (fishing) hours that look like fishing rather than transit -
mean speed 1-5 kn and a turning track (course steadiness < 0.9) - outside the port boxes. This
speed-pattern heuristic is standard but imperfect: it misses fishing at other speeds and counts
some slow manoeuvring. Only AIS-equipped boats are seen (mostly larger ones).

Each 0.25-degree cell and ISO week gets: fishing hours, sea-surface temperature (OISST), the
strength of the temperature front (spatial gradient magnitude), chlorophyll (VIIRS 8-day), the
upwelling indices (CUTI, BEUTI at the nearest latitude, previous-week mean) and the week's mean wave
height at the nearest buoy.

Test (pre-set before running): train on 2024, test on 2025. Can ocean conditions predict which
cells see fishing in a week (AUC), and how many hours (MAE), better than each cell's own 2024
average for that month (a seasonal-persistence baseline)?
"""
import json
import os

import numpy as np
import pandas as pd

from . import ocean
from .activity import REGIONS
from .snapshot import ROOT

OUT = os.path.join(ROOT, "data", "derived")
CELL = 0.25


def _cell(lat, lon):
    return (np.floor(lat / CELL) * CELL + CELL / 2).round(3), (np.floor(lon / CELL) * CELL + CELL / 2).round(3)


def fishing_hours(years=(2024, 2025)):
    v = pd.concat([pd.read_parquet(os.path.join(OUT, f"vessel_hours_conditions_{y}.parquet"),
                                   columns=["mmsi", "hour", "lat", "lon", "sog", "course_steadiness",
                                            "vessel_type", "WVHT"]) for y in years])
    f = v[(v.vessel_type == 30)]
    inport = np.zeros(len(f), bool)
    for a, b, c, d in REGIONS.values():
        inport |= (f.lat.between(a, b) & f.lon.between(c, d)).values
    f = f[~inport]
    f = f.assign(fishing=(f.sog.between(1, 5) & (f.course_steadiness < 0.9)).astype(int))
    f["clat"], f["clon"] = _cell(f.lat.values, f.lon.values)
    f["week"] = f.hour.dt.to_period("W-SUN").dt.start_time
    g = f.groupby(["week", "clat", "clon"]).agg(fishing_h=("fishing", "sum"), any_fishing_vessel_h=("fishing", "size"),
                                                 vessels=("mmsi", "nunique")).reset_index()
    return g, f


def ocean_weekly(years=(2024, 2025)):
    s = ocean.sst(years)
    s["clat"], s["clon"] = _cell(s.lat.values, s.lon.values)
    s["week"] = s.time.dt.to_period("W-SUN").dt.start_time
    sw = s.groupby(["week", "clat", "clon"]).sst.mean().reset_index()
    # front strength: gradient magnitude of weekly SST on the 0.25-degree grid (deg C per 100 km)
    fronts = []
    for wk, g in sw.groupby("week"):
        grid = g.pivot(index="clat", columns="clon", values="sst")
        gy, gx = np.gradient(grid.values)
        km_lat = CELL * 111.32
        km_lon = CELL * 111.32 * np.cos(np.radians(grid.index.values))[:, None]
        mag = np.hypot(gy / km_lat, gx / km_lon) * 100
        fr = pd.DataFrame(mag, index=grid.index, columns=grid.columns).stack().rename("sst_front").reset_index()
        fr["week"] = wk
        fronts.append(fr)
    sw = sw.merge(pd.concat(fronts), on=["week", "clat", "clon"], how="left")
    c = ocean.chlorophyll(years)
    c["clat"], c["clon"] = _cell(c.lat.values, c.lon.values)
    c["week"] = c.time.dt.to_period("W-SUN").dt.start_time
    cw = c.groupby(["week", "clat", "clon"]).chla.median().reset_index()
    cw["log_chla"] = np.log10(cw.chla.clip(lower=0.01))
    u = ocean.upwelling(years)
    u["week"] = u.time.dt.to_period("W-SUN").dt.start_time
    uw = u.groupby(["week", "latitude"])[["CUTI", "BEUTI"]].mean().reset_index()
    uw["week"] = uw.week + pd.Timedelta(days=7)            # previous week's upwelling feeds this week
    uw = uw.rename(columns={"CUTI": "cuti_prev_wk", "BEUTI": "beuti_prev_wk"})
    return sw, cw, uw


def build_panel(years=(2024, 2025)):
    g, f = fishing_hours(years)
    sw, cw, uw = ocean_weekly(years)
    # every ocean cell-week that had any AIS fishing-vessel presence in the period is in scope
    cells = g.groupby(["clat", "clon"]).size().index
    panel = sw[sw.set_index(["clat", "clon"]).index.isin(cells)].copy()
    panel = panel.merge(g, on=["week", "clat", "clon"], how="left").fillna({"fishing_h": 0, "vessels": 0,
                                                                            "any_fishing_vessel_h": 0})
    # chlorophyll: nearest 8-day composite within the same cell (weeks without a composite stay NaN)
    panel = panel.merge(cw[["week", "clat", "clon", "log_chla"]], on=["week", "clat", "clon"], how="left")
    panel["latitude"] = panel.clat.round().clip(32, 39)
    panel = panel.merge(uw, on=["week", "latitude"], how="left")
    hs = f.groupby(["week", "clat", "clon"]).WVHT.mean().rename("hs_week").reset_index()
    panel = panel.merge(hs, on=["week", "clat", "clon"], how="left")
    panel["month"] = panel.week.dt.month
    panel["year"] = panel.week.dt.year
    return panel


def model(panel, train_year=2024, test_year=2025, seed=7):
    from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor
    from sklearn.metrics import roc_auc_score
    p = panel.copy()
    p["fished"] = (p.fishing_h > 0).astype(int)
    tr, te = p[p.year == train_year], p[p.year == test_year].copy()
    # seasonal-persistence baseline: the cell's 2024 mean for the same month
    clim = tr.groupby(["clat", "clon", "month"]).agg(clim_h=("fishing_h", "mean"), clim_p=("fished", "mean")).reset_index()
    te = te.merge(clim, on=["clat", "clon", "month"], how="left").fillna({"clim_h": 0, "clim_p": 0})
    tr = tr.merge(clim, on=["clat", "clon", "month"], how="left")
    ocean_feats = ["sst", "sst_front", "log_chla", "cuti_prev_wk", "beuti_prev_wk", "hs_week"]
    base_feats = ["clat", "clon", "month", "clim_p", "clim_h"]
    full_feats = base_feats + ocean_feats
    clf = lambda: HistGradientBoostingClassifier(max_depth=4, learning_rate=0.05, max_iter=300,
                                                 min_samples_leaf=30, random_state=seed)
    reg = lambda: HistGradientBoostingRegressor(loss="absolute_error", max_depth=4, learning_rate=0.05,
                                                max_iter=300, min_samples_leaf=30, random_state=seed)
    # in-sample climatology features on the training year would leak; use leave-week-out style by
    # training only on ocean + location + month for the 'ocean only' model, and on everything for 'combined'
    out = {"train_year": train_year, "test_year": test_year, "n_train": int(len(tr)), "n_test": int(len(te)),
           "fished_share_test": round(float(te.fished.mean()), 3)}
    res = {}
    res["seasonal persistence (cell x month, 2024)"] = (te.clim_p.values, te.clim_h.values)
    m1 = clf().fit(tr[["clat", "clon", "month"] + ocean_feats], tr.fished)
    r1 = reg().fit(tr[["clat", "clon", "month"] + ocean_feats], tr.fishing_h)
    res["location + month + ocean conditions"] = (m1.predict_proba(te[["clat", "clon", "month"] + ocean_feats])[:, 1],
                                                  r1.predict(te[["clat", "clon", "month"] + ocean_feats]))
    m0 = clf().fit(tr[["clat", "clon", "month"]], tr.fished)
    r0 = reg().fit(tr[["clat", "clon", "month"]], tr.fishing_h)
    res["location + month only"] = (m0.predict_proba(te[["clat", "clon", "month"]])[:, 1],
                                    r0.predict(te[["clat", "clon", "month"]]))
    out["models"] = {k: {"auc_fished": round(float(roc_auc_score(te.fished, pp)), 3),
                         "mae_hours": round(float(np.mean(np.abs(te.fishing_h - ph))), 3)}
                     for k, (pp, ph) in res.items()}
    # paired bootstrap: AUC gain of ocean conditions over location + month
    rng = np.random.default_rng(seed)
    pa, pb = res["location + month + ocean conditions"][0], res["location + month only"][0]
    y = te.fished.values
    gains = []
    for _ in range(300):
        i = rng.integers(0, len(y), len(y))
        if 0 < y[i].sum() < len(i):
            gains.append(roc_auc_score(y[i], pa[i]) - roc_auc_score(y[i], pb[i]))
    out["auc_gain_from_ocean_ci95"] = [round(float(np.percentile(gains, 2.5)), 3), round(float(np.percentile(gains, 97.5)), 3)]
    # descriptive: share of fished cell-weeks and hours by SST, front strength and wave height bins
    d = p.dropna(subset=["sst"])
    out["by_sst"] = d.groupby(pd.cut(d.sst, [8, 12, 13, 14, 15, 16, 17, 18, 20, 25]), observed=True).agg(
        fished_share=("fished", "mean"), hours_per_cell_week=("fishing_h", "mean"), n=("fished", "size")
    ).round(3).reset_index().assign(sst=lambda x: x.sst.astype(str)).to_dict("records")
    out["by_front"] = d.groupby(pd.qcut(d.sst_front, 5, duplicates="drop"), observed=True).agg(
        fished_share=("fished", "mean"), hours_per_cell_week=("fishing_h", "mean"), n=("fished", "size")
    ).round(3).reset_index().assign(sst_front=lambda x: x.sst_front.astype(str)).to_dict("records")
    w = p.dropna(subset=["hs_week"])
    out["by_wave_height"] = w.groupby(pd.cut(w.hs_week, [0, 1, 1.5, 2, 2.5, 3, 9]), observed=True).agg(
        fishing_share_of_vessel_hours=("fishing_h", "sum"), vessel_hours=("any_fishing_vessel_h", "sum")
    ).assign(fishing_share_of_vessel_hours=lambda x: (x.fishing_share_of_vessel_hours / x.vessel_hours).round(3)
             ).reset_index().assign(hs_week=lambda x: x.hs_week.astype(str)).to_dict("records")
    weekly = p.groupby("week").agg(fishing_h=("fishing_h", "sum"), cuti=("cuti_prev_wk", "mean"),
                                   beuti=("beuti_prev_wk", "mean"), sst=("sst", "mean")).reset_index()
    out["weekly_corr_spearman"] = {k: round(float(weekly.fishing_h.corr(weekly[k], method="spearman")), 3)
                                   for k in ("cuti", "beuti", "sst")}
    return out, te, weekly


def run():
    panel = build_panel()
    panel.to_parquet(os.path.join(OUT, "fishing_panel.parquet"), index=False)
    out, te, weekly = model(panel)
    cells = panel.groupby(["clat", "clon"]).agg(fishing_h=("fishing_h", "sum"), weeks=("week", "nunique"),
                                                sst=("sst", "mean")).reset_index()
    out["cells"] = cells.round(3).to_dict("records")
    out["weekly"] = weekly.assign(week=weekly.week.dt.strftime("%Y-%m-%d")).round(3).to_dict("records")
    out["notes"] = ["Fishing hours are inferred from speed (1-5 kn) and turning; only AIS-equipped boats are seen.",
                    "Global Fishing Watch data is not used (non-commercial licence).",
                    "Ocean data: NOAA OISST v2.1, NOAA VIIRS chlorophyll 8-day, CUTI/BEUTI upwelling indices."]
    with open(os.path.join(ROOT, "eval", "fishing_results.json"), "w") as f:
        from .snapshot import json_safe
        json.dump(json_safe(out), f, indent=2, default=str, allow_nan=False)
    return out
