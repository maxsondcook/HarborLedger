"""Close-quarters vessel encounters from AIS (CPA / TCPA).

For each California AIS day and port area:
  1. keep moving vessels (SOG >= 1 kn) with a valid course, and resample each vessel's track to a
     1-minute grid (linear interpolation; gaps over 5 minutes are not bridged);
  2. each minute, find vessel pairs within SEARCH_NM of each other (spatial grid, so it is not
     O(n^2) over all vessels);
  3. compute the closest point of approach (CPA) and time to it (TCPA) from relative position and
     velocity (straight-line extrapolation of SOG/COG);
  4. a pair is "in encounter" in a minute when the predicted CPA < CPA_NM and 0 <= TCPA <= TCPA_MIN;
     consecutive minutes for the same pair (allowing a GAP_MIN break) merge into one encounter;
  5. each encounter records the observed minimum separation, the predicted CPA/TCPA at first
     detection, the geometry (head-on / crossing / overtaking, by COLREGS-style sectors) and whether
     it is a *service interaction* (tug, pilot or law-enforcement vessel working another ship),
     which is close by design and kept separate from traffic encounters.

Limits (stated on the site): AIS positions are antenna positions, not hull extents; SOG/COG noise
makes TCPA unreliable at very low speed; vessels without AIS (most small craft, all warships that
switch it off) are invisible.
"""
import collections
import glob
import json
import math
import os

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from .activity import REGIONS
from .ais import CA_DIR
from .snapshot import ROOT

NM = 1852.0
SEARCH_NM = 2.0
CPA_NM = 0.25          # 463 m: predicted pass closer than a quarter mile
TCPA_MIN = 10.0        # within the next 10 minutes
MIN_SOG = 1.0
TIERS = {"0.25nm": 463.0, "0.10nm": 185.2, "0.05nm": 92.6}
GAP_MIN = 3            # minutes allowed between detections of the same encounter
MAX_INTERP_GAP_S = 300
SERVICE_TYPES = {31, 32, 33, 34, 50, 51, 52, 53, 55}   # tug/tow, dredging/underwater ops, diving, pilot, SAR, port tender, law enforcement
MILITARY_TYPES = {35}
LAUNCH_MAX_LEN = 35.0      # 'likely launch / service boat': small, not pleasure, alongside many large ships
LAUNCH_MIN_PARTNERS = 10
OUT_DIR = os.path.join(ROOT, "data", "derived")


def _xy(lat, lon, lat0):
    return lon * 111_320.0 * math.cos(math.radians(lat0)), lat * 111_320.0


def cpa_tcpa(dx, dy, dvx, dvy):
    """Relative position (m) and velocity (m/s) of B with respect to A -> (cpa_m, tcpa_s)."""
    v2 = dvx * dvx + dvy * dvy
    t = np.where(v2 > 1e-6, -(dx * dvx + dy * dvy) / np.maximum(v2, 1e-6), 0.0)
    cx, cy = dx + dvx * t, dy + dvy * t
    return np.hypot(cx, cy), t


def geometry(cog_a, cog_b, bearing_a_to_b, bearing_b_to_a):
    """COLREGS-style classification from courses and relative bearings (degrees)."""
    dcourse = abs((cog_a - cog_b + 180) % 360 - 180)
    rel_b_from_a = (bearing_a_to_b - cog_a) % 360          # where B appears from A's bow
    rel_a_from_b = (bearing_b_to_a - cog_b) % 360
    if dcourse >= 165:
        return "head-on"
    if dcourse <= 67.5 and (112.5 <= rel_b_from_a <= 247.5 or 112.5 <= rel_a_from_b <= 247.5):
        return "overtaking"
    return "crossing"


def resample(df):
    """Per-vessel 1-minute positions and velocity components."""
    out = []
    for mmsi, g in df.groupby("mmsi", sort=False):
        g = g.sort_values("t")
        if len(g) < 3:
            continue
        t = g.t.values.astype("datetime64[s]").astype("int64")   # epoch seconds, whatever the unit
        grid = np.arange((t[0] // 60 + 1) * 60, t[-1], 60)
        if len(grid) == 0:
            continue
        idx = np.searchsorted(t, grid)
        ok = (idx > 0) & (idx < len(t))
        idx = idx[ok]
        grid = grid[ok]
        gap = t[idx] - t[idx - 1]
        keep = gap <= MAX_INTERP_GAP_S
        grid, idx = grid[keep], idx[keep]
        if len(grid) == 0:
            continue
        w = (grid - t[idx - 1]) / np.maximum(t[idx] - t[idx - 1], 1)
        def lerp(col):
            v = g[col].values
            return v[idx - 1] + (v[idx] - v[idx - 1]) * w
        x, y, sog = lerp("x"), lerp("y"), lerp("sog")
        cog = g.cog.values[idx]   # nearest-previous course avoids 359->0 interpolation errors
        r = np.radians(cog)
        sp = sog * NM / 3600.0
        out.append(pd.DataFrame({"mmsi": mmsi, "t": grid, "x": x, "y": y, "sog": sog, "cog": cog,
                                 "vx": sp * np.sin(r), "vy": sp * np.cos(r)}))
    return pd.concat(out, ignore_index=True) if out else pd.DataFrame()


def _large(vtype, length):
    """Large commercial traffic: cargo or tanker of any size, or any vessel >= 50 m. (Passenger
    type alone is not enough: it includes small excursion and sportfishing boats.)"""
    return (vtype is not None and (70 <= vtype <= 89)) or (length is not None and not pd.isna(length)
                                                            and length >= 50)


def day_encounters(path, region):
    lat_min, lat_max, lon_min, lon_max = REGIONS[region]
    lat0 = (lat_min + lat_max) / 2
    cols = ["mmsi", "base_date_time", "sog", "cog", "vessel_type", "length", "vessel_name", "lat", "lon"]
    df = pq.read_table(path, columns=cols).to_pandas()
    df = df[df.lat.between(lat_min, lat_max) & df.lon.between(lon_min, lon_max)]
    meta = df.groupby("mmsi").agg(name=("vessel_name", "first"), vtype=("vessel_type", "first"),
                                  length=("length", "max"))
    df = df[(df.sog >= MIN_SOG) & (df.sog < 102.2) & df.cog.notna() & (df.cog < 360)].copy()
    if df.empty:
        return [], {}
    df["t"] = df.base_date_time
    df["x"], df["y"] = _xy(df.lat.values, df.lon.values, lat0)
    r = resample(df)
    if r.empty:
        return [], {}
    vessel_minutes = len(r)
    cell = SEARCH_NM * NM
    r = r.reset_index(drop=True)
    r["cx"] = (r.x // cell).astype(int)
    r["cy"] = (r.y // cell).astype(int)
    r["rid"] = np.arange(len(r))
    base = r[["rid", "t", "cx", "cy"]]
    parts = []
    # each unordered pair once: same cell (i < j) plus four "forward" neighbour cells
    for ox, oy in ((0, 0), (1, -1), (1, 0), (1, 1), (0, 1)):
        sh = base.assign(cx=base.cx - ox, cy=base.cy - oy)
        m = base.merge(sh, on=["t", "cx", "cy"], suffixes=("_i", "_j"))
        if (ox, oy) == (0, 0):
            m = m[m.rid_i < m.rid_j]
        parts.append(m[["rid_i", "rid_j"]])
    P = pd.concat(parts, ignore_index=True)
    if P.empty:
        return [], {"vessel_minutes_moving": int(vessel_minutes), "moving_vessels": int(r.mmsi.nunique())}
    M, T = r.mmsi.values, r.t.values
    i0, j0 = P.rid_i.values, P.rid_j.values
    swap = M[i0] > M[j0]                       # order each pair by MMSI so events merge consistently
    i, j = np.where(swap, j0, i0), np.where(swap, i0, j0)
    X, Y = r.x.values, r.y.values
    dx, dy = X[j] - X[i], Y[j] - Y[i]
    dist = np.hypot(dx, dy)
    k = dist <= cell
    i, j, dx, dy, dist = i[k], j[k], dx[k], dy[k], dist[k]
    cpa, tcpa = cpa_tcpa(dx, dy, r.vx.values[j] - r.vx.values[i], r.vy.values[j] - r.vy.values[i])
    dvx, dvy = r.vx.values[j] - r.vx.values[i], r.vy.values[j] - r.vy.values[i]
    pm = pd.DataFrame({"m1": M[i], "m2": M[j], "t": T[i], "dist": dist, "cpa": cpa, "tcpa": tcpa,
                       "cog1": r.cog.values[i], "cog2": r.cog.values[j], "dx": dx, "dy": dy,
                       "sog1": r.sog.values[i], "sog2": r.sog.values[j], "dvx": dvx, "dvy": dvy})
    # alert-time context: moving vessels in the area that minute, and each vessel's neighbours within 2 nm
    area_n = r.groupby("t").size()
    nb = pd.concat([pm[["m1", "t"]].rename(columns={"m1": "m"}), pm[["m2", "t"]].rename(columns={"m2": "m"})])
    nb_n = nb.groupby(["m", "t"]).size()
    flag = (pm.cpa < CPA_NM * NM) & (pm.tcpa >= 0) & (pm.tcpa <= TCPA_MIN * 60)
    hits = pm[flag].sort_values(["m1", "m2", "t"])
    if hits.empty:
        return [], {"vessel_minutes_moving": int(vessel_minutes), "moving_vessels": int(r.mmsi.nunique())}
    newev = (hits.m1.ne(hits.m1.shift()) | hits.m2.ne(hits.m2.shift())
             | (hits.t - hits.t.shift() > GAP_MIN * 60))
    hits = hits.assign(ev=newev.cumsum())
    g = hits.groupby("ev")
    first = g.first()
    ev = first[["m1", "m2"]].assign(t0=g.t.min(), t1=g.t.max(), minutes=g.size())
    # observed minimum separation over [first alert, last alert + TCPA window], from pair-minutes
    J = pm[["m1", "m2", "t", "dist"]].merge(ev.reset_index()[["ev", "m1", "m2", "t0", "t1"]], on=["m1", "m2"])
    J = J[(J.t >= J.t0) & (J.t <= J.t1 + int(TCPA_MIN * 60))]
    mins = J.loc[J.groupby("ev").dist.idxmin(), ["ev", "dist", "t"]].set_index("ev")
    md = meta.to_dict("index")
    out = []
    for e, row in ev.iterrows():
        f = first.loc[e]
        m1, m2 = int(row.m1), int(row.m2)
        min_sep = float(mins.dist[e]) if e in mins.index else None
        t_min = int(mins.t[e]) if e in mins.index else None
        brg12 = math.degrees(math.atan2(f.dx, f.dy)) % 360
        geo = geometry(f.cog1, f.cog2, brg12, (brg12 + 180) % 360)
        v1, v2 = md[m1], md[m2]
        ta = None if pd.isna(v1["vtype"]) else int(v1["vtype"])
        tb = None if pd.isna(v2["vtype"]) else int(v2["vtype"])
        la = None if pd.isna(v1["length"]) else float(v1["length"])
        lb = None if pd.isna(v2["length"]) else float(v2["length"])
        out.append({
            "region": region, "mmsi_a": m1, "mmsi_b": m2,
            "name_a": v1["name"], "name_b": v2["name"], "type_a": ta, "type_b": tb, "len_a": la, "len_b": lb,
            "t_first": int(row.t0), "t_last": int(row.t1), "minutes": int(row.minutes),
            "dist_first_m": round(float(f.dist), 1), "cpa_pred_m": round(float(f.cpa), 1),
            "tcpa_pred_s": round(float(f.tcpa), 1), "min_sep_obs_m": None if min_sep is None else round(min_sep, 1),
            "t_min_sep": t_min, "geometry": geo, "service": int(ta in SERVICE_TYPES or tb in SERVICE_TYPES),
            "sog_a": round(float(f.sog1), 1), "sog_b": round(float(f.sog2), 1),
            # features known at the first alert (for the collision-risk model; nothing from later minutes)
            "cog_a": round(float(f.cog1), 1), "cog_b": round(float(f.cog2), 1),
            "rel_x_m": round(float(f.dx), 1), "rel_y_m": round(float(f.dy), 1),
            "rel_speed_kn": round(float(np.hypot(f.dvx, f.dvy) * 3600 / NM), 2),
            "area_moving_vessels": int(area_n.get(int(row.t0), 0)),
            "neighbours_a": int(nb_n.get((m1, int(row.t0)), 0)), "neighbours_b": int(nb_n.get((m2, int(row.t0)), 0)),
            # an alert is "realized" when the vessels actually came within the CPA threshold
            "realized": int(min_sep is not None and min_sep <= CPA_NM * NM),
            "large_involved": int(_large(ta, la) or _large(tb, lb)),
            "pleasure_involved": int(ta in (36, 37) or tb in (36, 37)),
            "military_involved": int(ta in MILITARY_TYPES or tb in MILITARY_TYPES),
        })
    return out, {"vessel_minutes_moving": int(vessel_minutes), "moving_vessels": int(r.mmsi.nunique())}


def run(year, files=None, regions=tuple(REGIONS), log=print):
    from .years import by_year, files_for
    files = files or files_for(year)
    allev, exposure = [], collections.defaultdict(lambda: collections.Counter())
    for f in files:
        day = os.path.basename(f)[7:17]
        for reg in regions:
            ev, exp = day_encounters(f, reg)
            for e in ev:
                e["day"] = day
            allev += ev
            exposure[reg].update(exp)
            exposure[reg]["days"] += 1
        log(f"{day}: {len(allev)} encounters so far")
    df = pd.DataFrame(allev)
    os.makedirs(OUT_DIR, exist_ok=True)
    summ = summarize(df, exposure)
    launches = set(summ.get("likely_launch_vessels", []))
    if not df.empty:
        df["launch_involved"] = (df.mmsi_a.isin(launches) | df.mmsi_b.isin(launches)).astype(int)
    summ["year"] = year
    df.to_csv(by_year(os.path.join(OUT_DIR, "encounters.csv"), year), index=False)
    with open(by_year(os.path.join(ROOT, "eval", "encounter_results.json"), year), "w") as fh:
        json.dump(summ, fh, indent=2)
    return df, summ


def _lg(e, m):
    """Large-vessel traffic encounters within m metres, excluding pleasure craft and likely launches."""
    return ((e.min_sep_obs_m <= m) & (e.large_involved == 1) & (e.pleasure_involved == 0)
            & (e.launch_involved == 0) & (e.military_involved == 0))


def likely_launches(df):
    """MMSIs of small non-pleasure vessels that had realized encounters with at least
    LAUNCH_MIN_PARTNERS distinct large vessels: crew launches, bunker and service boats whose AIS type
    (often 'passenger' or 'other') does not say so."""
    e = df[(df.realized == 1) & (df.service == 0)]
    rows = []
    for a, b in (("a", "b"), ("b", "a")):
        side = e[[f"mmsi_{a}", f"len_{a}", f"type_{a}", f"mmsi_{b}", f"len_{b}", f"type_{b}"]].copy()
        side.columns = ["m", "len", "typ", "pm", "plen", "ptyp"]
        rows.append(side)
    s_ = pd.concat(rows)
    small = (s_.len.isna() | (s_.len <= LAUNCH_MAX_LEN)) & ~s_.typ.isin([36, 37])
    big = s_.ptyp.between(70, 89) | (s_.plen >= 50)
    cnt = s_[small & big].groupby("m").pm.nunique()
    return set(int(m) for m in cnt[cnt >= LAUNCH_MIN_PARTNERS].index)


def summarize(df, exposure):
    s = {"definition": {"cpa_nm": CPA_NM, "tcpa_min": TCPA_MIN, "min_sog_kn": MIN_SOG,
                        "search_nm": SEARCH_NM, "merge_gap_min": GAP_MIN,
                        "alert": "predicted CPA < cpa_nm within tcpa_min (straight-line SOG/COG)",
                        "encounter": "alert whose observed minimum separation <= cpa_nm",
                        "service": "one vessel is a tug/tow, pilot, SAR, port tender or law enforcement"},
         "exposure": {r: dict(v) for r, v in exposure.items()}, "n_alerts": int(len(df))}
    if df.empty:
        return s
    launches = likely_launches(df)
    df = df.assign(launch_involved=(df.mmsi_a.isin(launches) | df.mmsi_b.isin(launches)).astype(int))
    s["likely_launch_vessels"] = sorted(launches)
    s["definition"]["likely_launch"] = (f"small (<= {LAUNCH_MAX_LEN:.0f} m or unknown length), non-pleasure vessel with "
                                        f"encounters against >= {LAUNCH_MIN_PARTNERS} distinct large vessels")
    tr = df[df.service == 0]
    enc = tr[tr.realized == 1]
    s["n_traffic_alerts"] = int(len(tr))
    s["n_service_alerts"] = int((df.service == 1).sum())
    s["n_traffic_encounters"] = int(len(enc))
    s["alert_precision_traffic"] = round(float(tr.realized.mean()), 3)
    s["by_region"] = {}
    for reg, g in df.groupby("region"):
        t = g[g.service == 0]
        e = t[t.realized == 1]
        hrs = (exposure[reg]["vessel_minutes_moving"] or 1) / 60.0
        el = e[(e.large_involved == 1) & (e.launch_involved == 0)]
        s["by_region"][reg] = {
            "moving_vessel_hours": round(hrs, 0),
            "traffic_alerts": int(len(t)), "traffic_encounters": int(len(e)),
            "alert_precision": round(float(t.realized.mean()), 3) if len(t) else None,
            "encounters_per_1000_moving_vessel_hours": round(len(e) / hrs * 1000, 1),
            "encounters_with_large_vessel": int(len(el)),
            "large_vessel_encounters_per_1000_h": round(len(el) / hrs * 1000, 1),
            "pleasure_share_of_encounters": round(float(e.pleasure_involved.mean()), 3) if len(e) else None,
            "geometry": e.geometry.value_counts().to_dict(),
            "median_min_sep_m": None if e.empty else round(float(e.min_sep_obs_m.median()), 0),
            "launch_share_of_large_encounters": round(float(e[e.large_involved == 1].launch_involved.mean()), 3)
                                                 if (e.large_involved == 1).any() else None,
            "military_encounters": int(e.military_involved.sum()),
            "tiers": {name: {
                "all": int((e.min_sep_obs_m <= m).sum()),
                "large_no_pleasure": int(_lg(e, m).sum()),
                "large_no_pleasure_per_1000_h": round(float(_lg(e, m).sum()) / hrs * 1000, 1)}
                for name, m in TIERS.items()},
        }
    s["alert_precision_by_tcpa_min"] = {
        f"{lo}-{hi}": round(float(tr[(tr.tcpa_pred_s >= lo * 60) & (tr.tcpa_pred_s < hi * 60)].realized.mean()), 3)
        for lo, hi in ((0, 2), (2, 5), (5, 10))}
    return s


def snippet(day, region, mmsi_a, mmsi_b, t0, t1, pad_s=600):
    """Raw AIS reports for two vessels from t0 - pad to t1 + pad (epoch seconds), in local metres
    relative to vessel A's position at t0. Used for scenario pages and for validation."""
    lat_min, lat_max, lon_min, lon_max = REGIONS[region]
    lat0 = (lat_min + lat_max) / 2
    path = os.path.join(CA_DIR, f"ais-ca-{day}.parquet")
    t = pq.read_table(path, columns=["mmsi", "base_date_time", "sog", "cog", "lat", "lon"],
                      filters=[("mmsi", "in", [int(mmsi_a), int(mmsi_b)])]).to_pandas()
    t["ts"] = t.base_date_time.values.astype("datetime64[s]").astype("int64")
    t = t[(t.ts >= t0 - pad_s) & (t.ts <= t1 + pad_s)].sort_values("ts")
    t["x"], t["y"] = _xy(t.lat.values, t.lon.values, lat0)
    return t


def raw_min_separation(tr, mmsi_a, mmsi_b, t0, t1, max_gap=MAX_INTERP_GAP_S):
    """Closest distance with B's position interpolated to the exact time of each A report (and vice
    versa), using only B reports that bracket it within max_gap seconds. MarineCadastre thins AIS to
    roughly one report per 1-3 minutes, so a truly interpolation-free check is not possible; this measures
    sensitivity to the time grid (report times vs whole minutes). Interpolation spans at most
    one reporting interval, unlike the detector's 1-minute grid; window [t0, t1 + TCPA]."""
    lo, hi = t0, t1 + TCPA_MIN * 60
    best = None
    for p_, q_ in ((mmsi_a, mmsi_b), (mmsi_b, mmsi_a)):
        a = tr[tr.mmsi == p_][["ts", "x", "y"]].values
        b = tr[tr.mmsi == q_][["ts", "x", "y"]].values
        if len(a) == 0 or len(b) < 2:
            continue
        a = a[(a[:, 0] >= lo) & (a[:, 0] <= hi)]
        if len(a) == 0:
            continue
        k = np.searchsorted(b[:, 0], a[:, 0])
        ok = (k > 0) & (k < len(b))
        a, k = a[ok], k[ok]
        if len(a) == 0:
            continue
        b0, b1 = b[k - 1], b[k]
        span = b1[:, 0] - b0[:, 0]
        ok = (span > 0) & (span <= max_gap)
        if not ok.any():
            continue
        a, b0, b1, span = a[ok], b0[ok], b1[ok], span[ok]
        w = (a[:, 0] - b0[:, 0]) / span
        bx = b0[:, 1] + (b1[:, 1] - b0[:, 1]) * w
        by = b0[:, 2] + (b1[:, 2] - b0[:, 2]) * w
        d = np.hypot(bx - a[:, 1], by - a[:, 2]).min()
        best = d if best is None else min(best, d)
    return None if best is None else float(best)


def validate(year, n=400, seed=2026):
    """Independent check on a random sample of traffic alerts: recompute the closest pass from raw
    AIS reports (other vessel interpolated to each report time) and compare with the detector's
    1-minute value, and check whether the 'realized' label would change."""
    from .years import by_year
    df = pd.read_csv(by_year(os.path.join(OUT_DIR, "encounters.csv"), year))
    tr = df[df.service == 0].sample(n=min(n, (df.service == 0).sum()), random_state=seed)
    rows = []
    for e in tr.to_dict("records"):
        t = snippet(e["day"], e["region"], e["mmsi_a"], e["mmsi_b"], e["t_first"], e["t_last"])
        raw = raw_min_separation(t, e["mmsi_a"], e["mmsi_b"], e["t_first"], e["t_last"])
        rows.append({"day": e["day"], "region": e["region"], "mmsi_a": e["mmsi_a"], "mmsi_b": e["mmsi_b"],
                     "min_sep_obs_m": e["min_sep_obs_m"], "raw_min_sep_m": raw, "realized": e["realized"],
                     "realized_raw": None if raw is None else int(raw <= CPA_NM * NM)})
    v = pd.DataFrame(rows)
    ok = v.dropna(subset=["raw_min_sep_m", "min_sep_obs_m"])
    diff = (ok.raw_min_sep_m - ok.min_sep_obs_m)
    res = {"n_sampled": int(len(v)), "n_comparable": int(len(ok)),
           "median_abs_diff_m": round(float(diff.abs().median()), 1),
           "p90_abs_diff_m": round(float(diff.abs().quantile(0.9)), 1),
           "median_signed_diff_m": round(float(diff.median()), 1),
           "label_agreement": round(float((ok.realized == ok.realized_raw).mean()), 3),
           "label_disagreements": int((ok.realized != ok.realized_raw).sum()),
           "disagreements_within_100m_of_threshold": int((((ok.realized != ok.realized_raw)
                                                          & ((ok.min_sep_obs_m - CPA_NM * NM).abs() <= 100)
                                                          & ((ok.raw_min_sep_m - CPA_NM * NM).abs() <= 100))).sum()),
           "note": "check = other vessel interpolated to each report time (bracketing reports <= 300 s apart, same limit as the detector); MarineCadastre thins AIS to ~1 report per 1-3 min, so this measures time-grid sensitivity, not independence from interpolation; signed diff = check - 1-minute grid"}
    res["year"] = year
    v.to_csv(by_year(os.path.join(ROOT, "eval", "encounter_validation_sample.csv"), year), index=False)
    with open(by_year(os.path.join(ROOT, "eval", "encounter_validation.json"), year), "w") as fh:
        json.dump(res, fh, indent=2)
    return res
