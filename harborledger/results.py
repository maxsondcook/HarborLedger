"""One table of headline numbers, each with a 95% confidence interval and the method behind it.

Writes eval/headline_results.json and docs/RESULTS.md. Run with `python3 -I run.py results`.

Interval methods:
  wilson         Wilson score interval for a proportion of independent items (labelled samples).
  day-block      Bootstrap that resamples whole days. Alerts on the same day share traffic, weather
                 and vessel pairs, so treating them as independent understates the uncertainty.
                 Needs data/derived/ (local only); without it the row falls back to the stored value.
  iid-bootstrap  Taken as stored in eval/: resamples individual rows. Marked because the rows are
                 clustered (legs by ship, cells by area), so these intervals are likely too narrow.
  paired-bootstrap  As stored by model.py: resamples test availabilities (one per contract).

Rows are reported as they come out; a CI that crosses a target is shown, not hidden.
"""
import json
import os

import numpy as np

from .evaluate import wilson
from .snapshot import ROOT

EVAL = os.path.join(ROOT, "eval")
DERIVED = os.path.join(ROOT, "data", "derived")
N_BOOT = 200
SEED = 2026


def _load(name):
    return json.load(open(os.path.join(EVAL, name)))


def _row(area, metric, value, ci, n, method, note=""):
    return {"area": area, "metric": metric, "value": value,
            "ci95": None if ci is None else [round(float(ci[0]), 3), round(float(ci[1]), 3)],
            "n": n, "method": method, "note": note}


def day_block_proportion(day, y, n_boot=N_BOOT, seed=SEED):
    """Proportion of y == 1 with a bootstrap over days. Returns (estimate, (lo, hi), n_days)."""
    import pandas as pd
    g = pd.DataFrame({"day": day, "y": y}).groupby("day").y.agg(["sum", "count"])
    k, n = g["sum"].to_numpy(float), g["count"].to_numpy(float)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(g), (n_boot, len(g)))
    boots = k[idx].sum(1) / n[idx].sum(1)
    return k.sum() / n.sum(), tuple(np.percentile(boots, [2.5, 97.5])), len(g)


def day_block_auc_gain(day, y, p_new, p_base, n_boot=N_BOOT, seed=SEED):
    """AUC(p_new) - AUC(p_base) with a bootstrap over days. Returns (gain, (lo, hi), auc_new, auc_base)."""
    from sklearn.metrics import roc_auc_score
    day = np.asarray(day)
    days, inv = np.unique(day, return_inverse=True)
    order = np.argsort(inv, kind="stable")
    starts = np.searchsorted(inv[order], np.arange(len(days)))
    ends = np.append(starts[1:], len(order))
    rows = [order[s:e] for s, e in zip(starts, ends)]
    rng = np.random.default_rng(seed)
    gains = []
    for _ in range(n_boot):
        i = np.concatenate([rows[d] for d in rng.integers(0, len(days), len(days))])
        gains.append(roc_auc_score(y[i], p_new[i]) - roc_auc_score(y[i], p_base[i]))
    a_new, a_base = roc_auc_score(y, p_new), roc_auc_score(y, p_base)
    return a_new - a_base, tuple(np.percentile(gains, [2.5, 97.5])), a_new, a_base


def entity_resolution_rows():
    rows = []
    r = _load("results.json")
    h = r["hull_sample_2027.csv"]
    rows.append(_row("Entity resolution", "Hull extraction precision (held-out 2027 sample)", h["precision"],
                     wilson(h["tp"], h["tp"] + h["fp"]), h["tp"] + h["fp"], "wilson",
                     "Target was >= 0.95; the CI lower bound (0.87) is below it, so the sample is too small to confirm the target."))
    rows.append(_row("Entity resolution", "Hull extraction recall (held-out 2027 sample)", h["recall"],
                     wilson(h["tp"], h["tp"] + h["fn"]), h["tp"] + h["fn"], "wilson"))
    p = _load("psix_match_results.json")
    rows.append(_row("Entity resolution", "AIS -> Coast Guard match precision (3 review samples)", p["precision"],
                     wilson(p["correct"], p["n"]), p["n"], "wilson",
                     "Reviewer checked the same fields the rule uses (name, IMO, call sign), so this tests the rule's "
                     "implementation more than true identity."))
    rows.append(_row("Entity resolution", "AIS -> Coast Guard match recall (auto-merged / all vessels)",
                     p["recall_same_as"], wilson(p["same_as"], p["vessels"]), p["vessels"], "wilson",
                     f"U.S.-flag recall {p['recall_us']}, foreign {p['recall_foreign']}."))
    b = _load("bridge_results.json")["outcomes"]
    n_art = sum(b.values())
    rows.append(_row("Entity resolution", "Navy hulls linked to AIS (infobox IMO/MMSI)", b["linked"], None, n_art,
                     "count", f"{b['linked']} of {n_art} hull articles; 0 conflicts. {b['not_in_ais']} have IDs not in "
                     "the commercial AIS set."))
    return rows


def encounter_rows():
    import pandas as pd
    rows = []
    for year in (2024, 2025):
        res = _load(f"encounter_results_{year}.json")
        path = os.path.join(DERIVED, f"encounters_{year}.csv")
        if os.path.exists(path):
            df = pd.read_csv(path, usecols=["day", "service", "realized"])
            df = df[df.service == 0]
            est, ci, n_days = day_block_proportion(df.day.values, df.realized.values)
            rows.append(_row("Encounters", f"Straight-line alert precision, all traffic alerts ({year})",
                             round(float(est), 3), ci, int(len(df)), "day-block",
                             f"Includes pairs already within 0.25 nm at the first alert; {n_days} days resampled."))
        else:
            rows.append(_row("Encounters", f"Straight-line alert precision, all traffic alerts ({year})",
                             res["alert_precision_traffic"], None, res["n_traffic_alerts"], "point only",
                             "data/derived/ not present; run locally for the day-block CI."))
        v = _load(f"encounter_validation_{year}.json")
        agree = round(v["label_agreement"] * v["n_comparable"])
        rows.append(_row("Encounters", f"Label agreement with report-time recomputation ({year})", v["label_agreement"],
                         wilson(agree, v["n_comparable"]), v["n_comparable"], "wilson",
                         "Measures sensitivity to the 1-minute grid, not independent ground truth."))
    return rows


def collision_rows():
    import pandas as pd
    rows = []
    c = _load("collision_model_results.json")
    path = os.path.join(DERIVED, "collision_predictions_2025.parquet")
    if os.path.exists(path):
        d = pd.read_parquet(path, columns=["day", "realized", "p_kin", "p_gbm"])
        y = d.realized.to_numpy()
        est, ci, n_days = day_block_proportion(d.day.values, y)
        rows.append(_row("Collision risk", "Straight-line alert precision, open alerts (> 0.25 nm at first alert, 2025)",
                         round(float(est), 3), ci, int(len(d)), "day-block",
                         "This is the 51% in the collision write-up; the 57% elsewhere includes already-close pairs."))
        gain, gci, a_new, a_base = day_block_auc_gain(d.day.values, y, d.p_gbm.to_numpy(), d.p_kin.to_numpy())
        rows.append(_row("Collision risk", "Model AUC, trained 2024, tested 2025", round(float(a_new), 3), None, int(len(d)),
                         "point only", "See the gain row for the interval."))
        rows.append(_row("Collision risk", "Kinematic baseline AUC (logistic on CPA, TCPA)", round(float(a_base), 3), None,
                         int(len(d)), "point only",
                         "Baseline omits current separation, the model's top feature; a stronger baseline would shrink the gain."))
        iid = c["gain_over_kinematic"]["auc"]
        rows.append(_row("Collision risk", "AUC gain over kinematic baseline", round(float(gain), 3), gci, int(len(d)),
                         "day-block", f"The stored iid bootstrap gave [{iid[0]}, {iid[2]}]; resampling days widens it."))
    else:
        m = {r["model"]: r for r in c["models"]}
        rows.append(_row("Collision risk", "Model AUC, trained 2024, tested 2025", m["full model"]["auc"], None, c["n_test"],
                         "point only", "data/derived/ not present; run locally for the day-block CI."))
        g = c["gain_over_kinematic"]["auc"]
        rows.append(_row("Collision risk", "AUC gain over kinematic baseline", g[1], (g[0], g[2]), c["n_test"],
                         "iid-bootstrap", "Resamples alerts as independent; likely too narrow."))
    return rows


def growth_rows():
    rows = []
    g = _load("growth_model_results.json")
    for w in g["windows"]:
        if w["label"] != "g_exopt":
            continue
        m = w["models"]
        gain_med = m["gbm"]["mae_vs_global_median"]
        rows.append(_row("Repair cost ledger", f"Error cut vs global median, day {w['window_days']}", gain_med,
                         w["gbm_vs_global_median_gain_ci95"], w["n_test"], "paired-bootstrap",
                         f"Pre-set target 0.15: {'met' if w['pass_preregistered'] else 'missed'} on the point estimate."))
        lo, hi = w["gbm_minus_persistence_mae_gain_ci95"]
        rows.append(_row("Repair cost ledger", f"MAE gain over persistence (growth so far), day {w['window_days']}",
                         round(m["persistence"]["mae"] - m["gbm"]["mae"], 4), (lo, hi), w["n_test"], "paired-bootstrap",
                         "CI includes 0: not significantly better than carrying forward the growth seen so far."
                         if lo <= 0 <= hi else ""))
    return rows


def other_rows():
    rows = []
    w = _load("weather_results.json")
    for key, label in (("leg_model", "observed sea conditions (upper bound)"), ("leg_model_forecast", "archived forecasts")):
        lm = w[key]
        best_base = min(v for k, v in lm["mae_hours"].items() if k not in ("model with sea conditions",))
        rows.append(_row("Weather", f"Trip-time MAE gain from {label}, hours", lm["gain_from_conditions_hours"],
                         lm["gain_ci95"], lm["n_test"], "iid-bootstrap",
                         f"Measured against the model without conditions ({lm['mae_hours']['model without sea conditions']} h). "
                         f"Against the best simple baseline ({best_base} h) the gain is "
                         f"{round(best_base - lm['mae_hours']['model with sea conditions'], 2)} h. Legs cluster by ship."))
    f = _load("fishing_results.json")
    lo, hi = f["auc_gain_from_ocean_ci95"]
    m = f["models"]
    gain = round(m["location + month + ocean conditions"]["auc_fished"] - m["location + month only"]["auc_fished"], 3)
    rows.append(_row("Fishing", "AUC gain from ocean conditions", gain, (lo, hi), f["n_test"], "iid-bootstrap",
                     "Cell-weeks cluster in space; the fishing label (1-5 kn plus turning) is not hand-validated."))
    return rows


def build_table():
    return entity_resolution_rows() + encounter_rows() + collision_rows() + growth_rows() + other_rows()


def _fmt(x):
    if x is None:
        return "–"
    if isinstance(x, float):
        return f"{x:.3f}".rstrip("0").rstrip(".") if abs(x) < 10 else f"{x:,.1f}"
    return f"{x:,}" if isinstance(x, int) else str(x)


def to_markdown(rows):
    lines = ["# Headline results", "",
             "Generated by `python3 -I run.py results` from the files in `eval/` (and `data/derived/` for the "
             "day-block intervals). Do not edit by hand.", "",
             "| Area | Metric | Value | 95% CI | n | CI method | Note |", "|---|---|---|---|---|---|---|"]
    for r in rows:
        ci = "–" if r["ci95"] is None else f"{_fmt(r['ci95'][0])} – {_fmt(r['ci95'][1])}"
        lines.append(f"| {r['area']} | {r['metric']} | {_fmt(r['value'])} | {ci} | {_fmt(r['n'])} | {r['method']} | {r['note']} |")
    lines += ["", "**CI methods.** *wilson*: Wilson score interval on a labelled sample. *day-block*: bootstrap "
              f"({N_BOOT} resamples) over whole days, because alerts on the same day are not independent. "
              "*paired-bootstrap*: as stored by the growth model, resampling test availabilities. "
              "*iid-bootstrap*: as stored, resampling rows that are in fact clustered, so these intervals are "
              "likely too narrow. *point only*: no interval computed.", ""]
    return "\n".join(lines)


def run():
    rows = build_table()
    with open(os.path.join(EVAL, "headline_results.json"), "w") as f:
        json.dump(rows, f, indent=2)
    with open(os.path.join(ROOT, "docs", "RESULTS.md"), "w") as f:
        f.write(to_markdown(rows))
    for r in rows:
        ci = "" if r["ci95"] is None else f"  [{r['ci95'][0]}, {r['ci95'][1]}]"
        print(f"{r['area']:<20} {r['metric'][:70]:<70} {r['value']}{ci}  ({r['method']})")
    return rows
