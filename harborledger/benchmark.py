"""Package the close-quarters encounter benchmark as an open, versioned dataset.

Output: data/benchmark/harborledger-encounters-v1/
  alerts_YYYY-MM.parquet (one per month)    every traffic alert (one row per alert event) with
                                              alert-time features, context and outcome labels
  scenarios_tracks.parquet                    1-minute-resolution AIS reports around the closest
                                              large-vessel encounters (the site's scenario pages)
  README.md                                   data card: sources, licence, schema, labels, split,
                                              baselines, limitations, citation
  SHA256SUMS                                  checksums
A 2,000-row sample of each year goes to docs/benchmark_sample/ so the format is visible in the repo.
The full files are too large for git and are published as GitHub release assets (one file per
month, each under 10 MB).
"""
import hashlib
import json
import os

import pandas as pd

from .snapshot import ROOT

VERSION = "v1"
NAME = f"harborledger-encounters-{VERSION}"
OUTDIR = os.path.join(ROOT, "data", "benchmark", NAME)
SAMPLE_DIR = os.path.join(ROOT, "docs", "benchmark_sample")
DERIVED = os.path.join(ROOT, "data", "derived")

COLUMNS = {
    "day": "UTC date of the first alert",
    "region": "port area: san_pedro_bay, sf_bay or san_diego",
    "mmsi_a": "MMSI of vessel A (the lower MMSI of the pair)",
    "mmsi_b": "MMSI of vessel B",
    "type_a": "AIS vessel type of A", "type_b": "AIS vessel type of B",
    "len_a": "AIS length of A (m)", "len_b": "AIS length of B (m)",
    "t_first": "first alert time (epoch seconds, UTC)",
    "dist_first_m": "separation at the first alert (m)",
    "cpa_pred_m": "straight-line predicted closest point of approach at the first alert (m)",
    "tcpa_pred_s": "straight-line predicted time to CPA at the first alert (s)",
    "sog_a": "speed over ground of A at the first alert (kn)", "sog_b": "speed over ground of B (kn)",
    "cog_a": "course over ground of A (deg)", "cog_b": "course over ground of B (deg)",
    "rel_x_m": "east offset of B from A at the first alert (m)", "rel_y_m": "north offset of B from A (m)",
    "rel_speed_kn": "relative speed of the pair (kn)",
    "area_moving_vessels": "moving vessels in the port area in that minute",
    "neighbours_a": "vessels within 2 nm of A in that minute", "neighbours_b": "vessels within 2 nm of B",
    "geometry": "COLREGS-style geometry at the first alert: head-on, crossing, overtaking",
    "service": "1 if either vessel is a tug/tow, dredge, diver, pilot, SAR, port tender or law-enforcement vessel",
    "pleasure_involved": "1 if either vessel is AIS type 36/37",
    "military_involved": "1 if either vessel is AIS type 35",
    "large_involved": "1 if either vessel is cargo/tanker or at least 50 m",
    "launch_involved": "1 if either vessel is a 'likely launch' (small non-pleasure vessel alongside >= 10 distinct large ships in the year). Computed from outcomes: do NOT use as a model feature",
    "realized": "LABEL: 1 if the pair actually came within 0.25 nm (463 m) after the alert",
    "min_sep_obs_m": "LABEL: observed minimum separation after the alert on 1-minute tracks (m)",
    "t_min_sep": "time of the observed minimum separation (epoch seconds)",
    "minutes": "number of alert minutes merged into the event (known only afterwards: do NOT use as a feature)",
}


def _sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def build(years=(2024, 2025)):
    os.makedirs(OUTDIR, exist_ok=True)
    os.makedirs(SAMPLE_DIR, exist_ok=True)
    counts = {}
    for y in years:
        df = pd.read_csv(os.path.join(DERIVED, f"encounters_{y}.csv"))
        keep = [c for c in COLUMNS if c in df.columns]
        df = df[keep]
        # one file per month (each well under 10 MB) so files can be downloaded selectively
        for old in [f for f in os.listdir(OUTDIR) if f.startswith(f"alerts_{y}")]:
            os.remove(os.path.join(OUTDIR, old))
        month = df.day.str[:7]
        for mth, part in df.groupby(month):
            part.to_parquet(os.path.join(OUTDIR, f"alerts_{mth}.parquet"), index=False, compression="zstd")
        df.sample(min(2000, len(df)), random_state=7).to_csv(os.path.join(SAMPLE_DIR, f"alerts_{y}_sample.csv"), index=False)
        counts[y] = {"alerts": int(len(df)), "traffic_alerts": int((df.service == 0).sum()),
                     "realized_share_traffic": round(float(df[df.service == 0].realized.mean()), 3)}
    # scenario tracks from the site export
    sc_dir = os.path.join(ROOT, "site", "public", "data", "encounters")
    rows = []
    for f in sorted(os.listdir(sc_dir)) if os.path.isdir(sc_dir) else []:
        d = json.load(open(os.path.join(sc_dir, f)))
        for m, pts in d["tracks"].items():
            for ts, x, yy, sog, cog in pts:
                rows.append({"scenario_id": d["id"], "mmsi": int(m), "ts": int(ts), "x_m": x, "y_m": yy, "sog": sog, "cog": cog})
    if rows:
        tr = pd.DataFrame(rows)
        for c in ("x_m", "y_m", "sog", "cog"):             # missing values arrive as '<NA>' text
            tr[c] = pd.to_numeric(tr[c], errors="coerce")
        tr.to_parquet(os.path.join(OUTDIR, "scenarios_tracks.parquet"), index=False, compression="zstd")
    res = json.load(open(os.path.join(ROOT, "eval", "collision_model_results.json"))) \
        if os.path.exists(os.path.join(ROOT, "eval", "collision_model_results.json")) else None
    _readme(counts, res)
    files = sorted(f for f in os.listdir(OUTDIR) if f != "SHA256SUMS")
    with open(os.path.join(OUTDIR, "SHA256SUMS"), "w") as fh:
        for f in files:
            fh.write(f"{_sha(os.path.join(OUTDIR, f))}  {f}\n")
    sizes = {f: round(os.path.getsize(os.path.join(OUTDIR, f)) / 1e6, 1) for f in files}
    return counts, sizes


def _readme(counts, res):
    schema = "\n".join(f"| `{k}` | {v} |" for k, v in COLUMNS.items())
    cnt = "\n".join(f"| {y} | {c['alerts']:,} | {c['traffic_alerts']:,} | {c['realized_share_traffic']:.1%} |" for y, c in counts.items())
    base = ""
    if res:
        m = {r["model"]: r for r in res["models"]}
        k, g = m.get("kinematic (CPA + TCPA only)"), m.get("full model")
        base = f"""
## Baselines (train 2024, test 2025)

Task: traffic alerts whose vessels are still more than 0.25 nm apart at the first alert
(n = {res['n_test']:,} in 2025). Predict `realized`.

| Method | AUC | Precision at 90% recall |
|---|---|---|
| Straight-line rule (every alert is a warning) | 0.500 | {res['straight_line_precision']:.3f} |
| Kinematic: logistic regression on CPA and TCPA | {k['auc']:.3f} | {k['precision_at_90pct_recall']:.3f} |
| Gradient boosting on all alert-time features | {g['auc']:.3f} | {g['precision_at_90pct_recall']:.3f} |

Code: `harborledger/collision.py` in https://github.com/maxsondcook/HarborLedger.
"""
    text = f"""# HarborLedger close-quarters encounter benchmark ({VERSION})

Real-traffic close-quarters alerts and outcomes for three California port areas (San Pedro Bay,
San Francisco Bay, San Diego Bay) for 2024 and 2025, built from public AIS. Each row is one alert
event: a pair of moving vessels whose straight-line projection (constant speed and course) put them
within 0.25 nm (463 m) of each other within 10 minutes, with the features known at that moment and
whether they actually came that close.

It is meant for evaluating collision-risk and alert-filtering methods against a real-traffic
baseline, and for studying the gap between straight-line predictions and what vessels actually do.

## Contents

| File | Description |
|---|---|
| `alerts_YYYY-MM.parquet` (24 files) | one row per alert event (schema below), one file per month |
| `scenarios_tracks.parquet` | AIS reports (local metres around vessel A) for the closest large-vessel encounters |
| `SHA256SUMS` | checksums |

| Year | Alert events | Traffic alerts (no service vessel) | Traffic alerts that came true |
|---|---|---|---|
{cnt}

Suggested split: train on 2024, test on 2025 (time-based, no shuffling across years).

Load a year with pandas: `pd.concat(pd.read_parquet(f) for f in sorted(glob.glob("alerts_2024-*.parquet")))`.
{base}
## Schema

| Column | Description |
|---|---|
{schema}

## How the alerts were built

- Source: NOAA/BOEM MarineCadastre AIS broadcast points (CC0), filtered by MarineCadastre to
  about one report per vessel per minute.
- Moving vessels (SOG >= 1 kn) are resampled to a 1-minute grid (gaps up to 5 minutes bridged).
  Each minute, pairs within 2 nm get straight-line CPA/TCPA. Consecutive alert minutes for a pair
  (gaps up to 3 minutes) merge into one event.
- `realized` uses the observed minimum separation over the alert window plus 10 minutes.

## Known limitations

- AIS positions are antenna positions, not hull outlines.
- Thinning to about one report per minute means interpolated separations can be wrong. On a
  random sample of 400 alerts per year, recomputing at the actual report times changes the label
  for about 9% of alerts.
- Vessels without AIS (most small craft, warships that switch it off) are absent.
- `launch_involved` and `minutes` are derived from outcomes; they are for analysis, not features.

## Licence and citation

Derived from public-domain U.S. federal data (MarineCadastre AIS, CC0). Released under CC BY 4.0.
Cite as: HarborLedger close-quarters encounter benchmark {VERSION} (2026),
https://github.com/maxsondcook/HarborLedger.
"""
    with open(os.path.join(OUTDIR, "README.md"), "w") as f:
        f.write(text)
