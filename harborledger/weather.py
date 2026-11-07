"""Ship behaviour versus sea state (Option 1).

Step 1, vessel-hours: each AIS day file is collapsed to one row per vessel per hour with mean
position, mean speed over ground, circular-mean course, type and length (moving vessels only,
SOG >= 1 kn).
Step 2, conditions: each vessel-hour gets the nearest NDBC buoy's waves (significant height,
period, mean direction) within MAX_KM, and the nearest buoy's wind, for the same UTC hour. The
sea's direction relative to the vessel's course is classed as head, beam or following.

Buoys are sparse, so conditions are those at the nearest buoy, not at the ship. That smooths
local effects (headlands, shelter) and is stated wherever results are shown.
"""
import glob
import math
import os

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from . import ocean
from .snapshot import ROOT
from .years import files_for

OUT = os.path.join(ROOT, "data", "derived")
MAX_KM = 75.0
COLS = ["mmsi", "base_date_time", "sog", "cog", "vessel_type", "length", "lon", "lat"]


def vessel_hours_day(path):
    t = pq.read_table(path, columns=COLS).to_pandas()
    t = t[(t.sog >= 1.0) & (t.sog < 40) & t.cog.notna() & (t.cog < 360)]
    if t.empty:
        return t
    t["hour"] = t.base_date_time.dt.floor("h").astype("datetime64[ns]")   # naive UTC, same as buoys
    r = np.radians(t.cog.astype(float))
    t["cx"], t["cy"] = np.sin(r), np.cos(r)
    g = t.groupby(["mmsi", "hour"]).agg(lat=("lat", "mean"), lon=("lon", "mean"), sog=("sog", "mean"),
                                        sog_sd=("sog", "std"), cx=("cx", "mean"), cy=("cy", "mean"),
                                        n=("sog", "size"), vessel_type=("vessel_type", "first"),
                                        length=("length", "max")).reset_index()
    g["cog"] = (np.degrees(np.arctan2(g.cx, g.cy)) + 360) % 360
    g["course_steadiness"] = np.hypot(g.cx, g.cy)        # 1 = straight line, low = turning
    return g.drop(columns=["cx", "cy"])


def vessel_hours(year):
    parts = [vessel_hours_day(f) for f in files_for(year)]
    vh = pd.concat([p for p in parts if len(p)], ignore_index=True)
    vh.to_parquet(os.path.join(OUT, f"vessel_hours_{year}.parquet"), index=False)
    return vh


def _haversine_km(lat1, lon1, lat2, lon2):
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dlat, dlon = p2 - p1, np.radians(lon2 - lon1)
    a = np.sin(dlat / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dlon / 2) ** 2
    return 6371.0 * 2 * np.arcsin(np.sqrt(a))


def attach_conditions(vh, buoys=None):
    """Nearest-buoy waves (within MAX_KM) and nearest-buoy wind for each vessel-hour."""
    buoys = buoys if buoys is not None else ocean.hourly()
    st = buoys.groupby("station")[["lat", "lon"]].first()
    d = np.stack([_haversine_km(vh.lat.values, vh.lon.values, la, lo) for la, lo in zip(st.lat, st.lon)], axis=1)
    order = np.argsort(d, axis=1)
    ids = st.index.values
    out = vh.reset_index(drop=True).copy()   # unique row labels for positional assignment
    wave = buoys[["station", "hour", "WVHT", "DPD", "APD", "MWD", "WTMP"]].dropna(subset=["WVHT"])
    wind = buoys[["station", "hour", "WSPD", "WDIR", "GST"]].dropna(subset=["WSPD"])
    wave_k = {k: g.set_index("hour") for k, g in wave.groupby("station")}
    wind_k = {k: g.set_index("hour") for k, g in wind.groupby("station")}
    # try the nearest buoy first, then the next nearest, until one has data for that hour
    for col_set, table, prefix in ((["WVHT", "DPD", "APD", "MWD", "WTMP"], wave_k, "wave"),
                                   (["WSPD", "WDIR", "GST"], wind_k, "wind")):
        for c in col_set:
            out[c] = np.nan
        out[f"{prefix}_station"] = None
        out[f"{prefix}_km"] = np.nan
        for rank in range(min(4, len(ids))):
            need = out[col_set[0]].isna().values
            if not need.any():
                break
            sid = ids[order[need, rank]]
            km = d[need, order[need, rank]]
            ok_km = km <= MAX_KM
            hours = out.loc[need, "hour"].values
            vals = np.full((need.sum(), len(col_set)), np.nan)
            for s in np.unique(sid[ok_km]):
                if s not in table:
                    continue
                sel = np.where((sid == s) & ok_km)[0]
                got = table[s].reindex(pd.DatetimeIndex(hours[sel]))[col_set].values
                vals[sel] = got
            idx = np.where(need)[0]
            have = ~np.isnan(vals[:, 0])
            out.loc[out.index[idx[have]], col_set] = vals[have]
            out.loc[out.index[idx[have]], f"{prefix}_station"] = sid[have]
            out.loc[out.index[idx[have]], f"{prefix}_km"] = km[have]
    # sea direction relative to course: MWD is the direction waves come FROM
    rel = (out.MWD - out.cog + 360) % 360
    rel = np.minimum(rel, 360 - rel)                       # 0 = waves from dead ahead
    out["sea_rel"] = np.select([rel <= 45, rel >= 135], ["head", "following"], "beam")
    out.loc[out.MWD.isna(), "sea_rel"] = None
    return out


def run(year):
    vh = vessel_hours(year)
    vc = attach_conditions(vh)
    vc.to_parquet(os.path.join(OUT, f"vessel_hours_conditions_{year}.parquet"), index=False)
    cov = {"year": year, "vessel_hours": int(len(vc)), "vessels": int(vc.mmsi.nunique()),
           "with_waves": round(float(vc.WVHT.notna().mean()), 3),
           "with_wind": round(float(vc.WSPD.notna().mean()), 3)}
    print(cov, flush=True)
    return cov


# ---------- big-ship speed loss ----------
from .activity import REGIONS  # noqa: E402

BIG_TYPES = (70, 89)


def open_water_big(vc):
    """Steady open-water transit hours of large cargo ships and tankers."""
    inport = np.zeros(len(vc), bool)
    for a, b, c, d in REGIONS.values():
        inport |= (vc.lat.between(a, b) & vc.lon.between(c, d)).values
    m = (vc.vessel_type.between(*BIG_TYPES) & ((vc.length >= 100) | vc.length.isna()) & (vc.sog >= 6)
         & (vc.course_steadiness >= 0.98) & (vc.n >= 10) & ~inport)
    big = vc[m].copy()
    big["cell"] = (big.lat // 0.5).astype(int).astype(str) + "_" + (big.lon // 0.5).astype(int).astype(str)
    big["vsr_season"] = big.hour.dt.month.between(5, 12)     # voluntary 10-kn whale zones May-Dec
    g = big.groupby(["mmsi", "cell", "vsr_season"]).sog
    big["ref_sog"], big["n_ref"] = g.transform("median"), g.transform("size")
    big["speed_ratio"] = big.sog / big.ref_sog
    return big


HS_BINS = [0, 1, 1.5, 2, 2.5, 3, 3.5, 4, 5, 9]


def speed_loss_table(big, n_boot=200, seed=7):
    """Median speed ratio by wave-height bin and sea direction, with bootstrap 95% intervals."""
    b = big[(big.n_ref >= 6) & big.WVHT.notna() & big.sea_rel.notna()].copy()
    b["hs_bin"] = pd.cut(b.WVHT, HS_BINS)
    rng = np.random.default_rng(seed)
    rows = []
    for (hb, rel), g in b.groupby(["hs_bin", "sea_rel"], observed=True):
        r = g.speed_ratio.values
        boots = [np.median(rng.choice(r, len(r))) for _ in range(n_boot)] if len(r) >= 30 else [np.nan]
        rows.append({"hs_lo": hb.left, "hs_hi": hb.right, "sea_rel": rel, "n": int(len(r)),
                     "median_ratio": round(float(np.median(r)), 4),
                     "ci95": [round(float(np.nanpercentile(boots, 2.5)), 4), round(float(np.nanpercentile(boots, 97.5)), 4)]})
    return rows


# ---------- coastal legs between the LA/Long Beach and San Francisco approaches ----------
GATES = {"SF": (37.55, 37.95, -122.95, -122.45), "LA": (33.50, 33.78, -118.40, -117.95)}
MAX_GAP_H = 3


def _in(lat, lon, box):
    a, b, c, d = box
    return (lat >= a) & (lat <= b) & (lon >= c) & (lon <= d)


def coastal_legs(vc):
    """A leg: a large ship's last hour in one approach gate followed, with no tracking gap over
    MAX_GAP_H hours, by its first hour in the other gate, 12-72 h later."""
    v = vc[vc.vessel_type.between(*BIG_TYPES)].sort_values(["mmsi", "hour"])
    v = v.assign(gate=np.select([_in(v.lat, v.lon, GATES["SF"]), _in(v.lat, v.lon, GATES["LA"])], ["SF", "LA"], ""))
    legs = []
    for m, g in v.groupby("mmsi", sort=False):
        g = g.reset_index(drop=True)
        gates = g.gate.values
        hrs = g.hour.values
        last_gate, last_i = None, None
        for i in range(len(g)):
            if gates[i]:
                if last_gate and gates[i] != last_gate and i > last_i:
                    seg = g.iloc[last_i:i + 1]
                    gaps = np.diff(seg.hour.values).astype("timedelta64[h]").astype(int)
                    dur = (hrs[i] - hrs[last_i]).astype("timedelta64[m]").astype(int) / 60
                    if 12 <= dur <= 72 and (gaps.max() if len(gaps) else 0) <= MAX_GAP_H:
                        dist_nm = float(_haversine_km(seg.lat.values[:-1], seg.lon.values[:-1],
                                                      seg.lat.values[1:], seg.lon.values[1:]).sum() / 1.852)
                        hs = seg.WVHT
                        head = (seg.sea_rel == "head")
                        legs.append({
                            "mmsi": int(m), "from": last_gate, "to": gates[i],
                            "depart": pd.Timestamp(hrs[last_i]), "arrive": pd.Timestamp(hrs[i]),
                            "hours": dur, "track_nm": dist_nm, "mean_sog": float(seg.sog.mean()),
                            "hs_mean": float(hs.mean()) if hs.notna().any() else np.nan,
                            "hs_max": float(hs.max()) if hs.notna().any() else np.nan,
                            "head_share": float(head.mean()),
                            "head_hs_mean": float((hs.where(head)).mean()) if (head & hs.notna()).any() else 0.0,
                            "wind_mean": float(seg.WSPD.mean()) if seg.WSPD.notna().any() else np.nan,
                            "wave_coverage": float(hs.notna().mean()), "n_hours": int(len(seg)),
                            "length": float(seg.length.max()) if seg.length.notna().any() else np.nan,
                            "vessel_type": int(seg.vessel_type.iloc[0]),
                        })
                last_gate, last_i = gates[i], i
    return pd.DataFrame(legs)


def leg_model(legs, big, train_year=2024, test_year=2025, seed=7):
    """Predict coastal-leg duration from sea conditions along the leg. Calm-weather speed comes from
    the training year only (hours with waves < 1.5 m), so no test information leaks in. Conditions
    are the observed buoy values along the route, i.e. a perfect-forecast upper bound."""
    from sklearn.ensemble import HistGradientBoostingRegressor
    L = legs.copy()
    L["year"] = L.depart.dt.year
    tr_hours = big[(big.hour.dt.year == train_year) & (big.WVHT < 1.5)]
    calm = tr_hours.groupby("mmsi").sog.median()
    type_calm = tr_hours.groupby("vessel_type").sog.median()
    L["calm_sog"] = L.mmsi.map(calm)
    L["calm_from"] = np.where(L.calm_sog.notna(), "own", "type")
    L["calm_sog"] = L.calm_sog.fillna(L.vessel_type.map(type_calm)).fillna(tr_hours.sog.median())
    L["calm_hours"] = L.track_nm / L.calm_sog
    L["added_h"] = L.hours - L.calm_hours
    L["northbound"] = (L["to"] == "SF").astype(int)
    L["month"] = L.depart.dt.month
    tr, te = L[L.year == train_year], L[L.year == test_year]
    feats = ["calm_hours", "track_nm", "northbound", "hs_mean", "hs_max", "head_share", "head_hs_mean",
             "wind_mean", "month", "length"]
    base_feats = ["calm_hours", "track_nm", "northbound", "month", "length"]
    mk = lambda: HistGradientBoostingRegressor(loss="absolute_error", max_depth=3, learning_rate=0.05,
                                                max_iter=300, min_samples_leaf=20, random_state=seed)
    m_full, m_base = mk().fit(tr[feats], tr.hours), mk().fit(tr[base_feats], tr.hours)
    own = tr.groupby("mmsi").hours.median()
    dir_med = tr.groupby("northbound").hours.median()
    preds = {
        "distance / calm speed": te.calm_hours.values,
        "median for direction": te.northbound.map(dir_med).values,
        "ship's own median leg": te.mmsi.map(own).fillna(te.northbound.map(dir_med)).values,
        "model without sea conditions": m_base.predict(te[base_feats]),
        "model with sea conditions": m_full.predict(te[feats]),
    }
    mae = {k: round(float(np.mean(np.abs(te.hours.values - p))), 2) for k, p in preds.items()}
    # bootstrap the gain from adding conditions (paired)
    rng = np.random.default_rng(seed)
    e_b = np.abs(te.hours.values - preds["model without sea conditions"])
    e_f = np.abs(te.hours.values - preds["model with sea conditions"])
    gains = [e_b[i].mean() - e_f[i].mean() for i in (rng.integers(0, len(te), len(te)) for _ in range(2000))]
    # weather effect: predicted hours for each test leg under its real conditions vs calm conditions
    calm_te = te[feats].copy()
    calm_te[["hs_mean", "hs_max", "head_hs_mean"]] = [1.0, 1.5, 0.0]
    calm_te["head_share"] = 0.0
    calm_te["wind_mean"] = np.nanpercentile(tr.wind_mean, 25)
    te = te.assign(pred=preds["model with sea conditions"], pred_calm=m_full.predict(calm_te))
    te["weather_added_h"] = te.pred - te.pred_calm
    by_hs = te.assign(hs_bin=pd.cut(te.head_hs_mean, [-0.01, 0.5, 1.5, 2, 2.5, 3, 9])).groupby(
        ["northbound", "hs_bin"], observed=True).weather_added_h.agg(["median", "size"]).reset_index()
    return {
        "train_year": train_year, "test_year": test_year, "n_train": int(len(tr)), "n_test": int(len(te)),
        "calm_speed_from_own_history_share": round(float((te.calm_from == "own").mean()), 3),
        "mae_hours": mae,
        "gain_from_conditions_hours": round(float(np.mean(gains)), 2),
        "gain_ci95": [round(float(np.percentile(gains, 2.5)), 2), round(float(np.percentile(gains, 97.5)), 2)],
        "median_leg_hours_test": round(float(te.hours.median()), 1),
        "weather_added_hours_by_head_sea": [
            {"northbound": bool(r.northbound), "head_hs_lo": float(r.hs_bin.left), "head_hs_hi": float(r.hs_bin.right),
             "median_added_h": round(float(r.median), 2), "n": int(r.size)} for r in by_hs.itertuples()],
    }, te


# ---------- small craft: do they stay in port on rough days? ----------
SMALL = {"tug/tow": lambda v: v.vessel_type.isin([31, 32, 52]),
         "fishing": lambda v: v.vessel_type == 30,
         "passenger < 50 m": lambda v: v.vessel_type.between(60, 69) & (v.length < 50),
         "pleasure/sailing": lambda v: v.vessel_type.isin([36, 37])}
OFFSHORE_BUOY = {"san_pedro_bay": "46025", "sf_bay": "46026", "san_diego": "46232"}


def small_craft_days(vc):
    """Per port area and day: number of distinct small vessels moving OUTSIDE the port box
    (i.e. at sea), against that day's maximum wave height and wind at the area's offshore buoy."""
    from . import ocean
    b = ocean.hourly()
    b["day"] = b.hour.dt.floor("D")
    daily = b.groupby(["station", "day"]).agg(hs_max=("WVHT", "max"), hs_mean=("WVHT", "mean"),
                                              wind_max=("WSPD", "max")).reset_index()
    rows = []
    for area, (a, bb, c, d) in REGIONS.items():
        # 'at sea' = within ~40 km of the port box but outside it
        near = vc.lat.between(a - 0.35, bb + 0.35) & vc.lon.between(c - 0.45, d + 0.45)
        inside = vc.lat.between(a, bb) & vc.lon.between(c, d)
        sea = vc[near & ~inside].assign(day=lambda x: x.hour.dt.floor("D"))
        for cls, f in SMALL.items():
            cnt = sea[f(sea)].groupby("day").mmsi.nunique().rename("vessels_at_sea").reset_index()
            cnt["area"], cnt["class"] = area, cls
            rows.append(cnt)
    out = pd.concat(rows, ignore_index=True)
    out["station"] = out.area.map(OFFSHORE_BUOY)
    return out.merge(daily, on=["station", "day"], how="left")


def departures_vs_seastate(days):
    """Vessels at sea on a day relative to that area/class/month/weekday norm, by wave-height bin."""
    d = days.dropna(subset=["hs_max"]).copy()
    d["month"], d["weekend"] = d.day.dt.month, d.day.dt.dayofweek >= 5
    norm = d.groupby(["area", "class", "month", "weekend"]).vessels_at_sea.transform("median")
    d["rel"] = d.vessels_at_sea / norm.clip(lower=1)
    d["hs_bin"] = pd.cut(d.hs_max, [0, 1.5, 2, 2.5, 3, 3.5, 4, 5, 12])
    t = d.groupby(["class", "hs_bin"], observed=True).rel.agg(["median", "size"]).reset_index()
    return [{"class": r["class"], "hs_lo": float(r.hs_bin.left), "hs_hi": float(r.hs_bin.right),
             "median_rel": round(float(r["median"]), 3), "days": int(r["size"])} for _, r in t.iterrows()]


# ---------- operability: how often is the sea calm enough? ----------
def operability(thresholds=(1.0, 1.5, 2.0, 2.5, 3.0)):
    """Share of hours with significant wave height at or below each threshold, by buoy and month."""
    from . import ocean
    b = ocean.hourly().dropna(subset=["WVHT"])
    b["month"] = b.hour.dt.month
    rows = []
    for (s, mth), g in b.groupby(["station", "month"]):
        r = {"station": s, "name": g.name.iloc[0], "lat": float(g.lat.iloc[0]), "lon": float(g.lon.iloc[0]),
             "month": int(mth), "hours": int(len(g))}
        for t in thresholds:
            r[f"le_{t:g}m"] = round(float((g.WVHT <= t).mean()), 3)
        rows.append(r)
    return rows


def analyze(years=(2024, 2025)):
    """Run every Option 1 analysis and write eval/weather_results.json (+ legs for the site)."""
    import json
    v = pd.concat([pd.read_parquet(os.path.join(OUT, f"vessel_hours_conditions_{y}.parquet")) for y in years])
    big = open_water_big(v)
    legs = coastal_legs(v)
    legs.to_parquet(os.path.join(OUT, "coastal_legs.parquet"), index=False)
    leg_res, te = leg_model(legs, big)
    days = small_craft_days(v)
    res = {
        "years": list(years),
        "coverage": {"vessel_hours": int(len(v)), "with_waves": round(float(v.WVHT.notna().mean()), 3),
                     "with_wind": round(float(v.WSPD.notna().mean()), 3),
                     "big_ship_open_water_hours": int(len(big)), "big_ships": int(big.mmsi.nunique())},
        "speed_loss": speed_loss_table(big),
        "legs": {"n": int(len(legs)), "ships": int(legs.mmsi.nunique()),
                 "northbound": int((legs["to"] == "SF").sum()), "southbound": int((legs["to"] == "LA").sum()),
                 "median_hours": round(float(legs.hours.median()), 1),
                 "median_track_nm": round(float(legs.track_nm.median()), 0)},
        "leg_model": leg_res,
        "small_craft": departures_vs_seastate(days),
        "operability": operability(),
        "notes": ["Conditions are from the nearest NOAA buoy, not at the ship.",
                  "Leg-model conditions are observed values along the route: a perfect-forecast upper bound.",
                  "Speed ratios compare each ship with its own median speed in the same 0.5-degree cell and season,"
                  " which absorbs the voluntary 10-knot whale-protection zones (May-December)."],
    }
    with open(os.path.join(ROOT, "eval", "weather_results.json"), "w") as f:
        from .snapshot import json_safe
        json.dump(json_safe(res), f, indent=2, default=str, allow_nan=False)
    te[["mmsi", "from", "to", "depart", "hours", "calm_hours", "hs_mean", "head_hs_mean", "head_share",
        "pred", "pred_calm", "weather_added_h"]].round(2).to_csv(
        os.path.join(ROOT, "eval", "coastal_leg_predictions_2025.csv"), index=False)
    return res
