"""Early-warning model for availability cost growth.

Question: knowing only what USAspending shows in the first W days of an availability
(W = 90 or 180), how well can we predict its final growth beyond base + options?

Pre-registered success test (Phase 3 report, weeks 3-4): on held-out later years, beat the
global-median baseline's MAE by >= 15%. The stronger "persistence" baseline (final = growth
already visible at day W) is reported too, because beating only the weakest baseline would
overstate the model.

Design choices fixed before looking at test results:
  * time split: train = availabilities starting FY2021 or earlier; test = FY2022 onward
  * closed availabilities only (open ones are censored)
  * model predicts the *remaining* growth after day W, then adds growth-so-far
  * HistGradientBoostingRegressor, absolute-error loss, depth 3, lr 0.05, 300 iterations,
    min 10 samples per leaf - no tuning on the test set
"""
import datetime as dt
import json
import os
import statistics as st

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor

from . import db, ledger
from .snapshot import ROOT

TRAIN_MAX_FY = 2021
WINDOWS = (90, 180)
CATS = ["avail_type", "hull_class", "firm"]
SEED = 7


def load_frame(con, window):
    rows = []
    for a in con.execute("SELECT * FROM availability").fetchall():
        acts = [dict(x) for x in con.execute(
            "SELECT * FROM contract_action WHERE contract_id=? ORDER BY action_date, seq",
            (a["contract_id"],))]
        first = dt.date.fromisoformat(a["first_action"])
        f = ledger.window_features(acts, first, window)
        f.update({k: a[k] for k in ("contract_id", "piid", "hull", "hull_class", "avail_type", "firm",
                                    "start_fy", "closed", "g_exopt", "g_exopt_noC", "delay_flag",
                                    "first_action", "pop_end")})
        f["firm"] = f["firm"] or "UNMAPPED"
        f["start_fy_num"] = a["start_fy"]
        # Was the window fully observable? (first action + W must precede the data cut-off)
        f["window_complete"] = int(first + dt.timedelta(days=window) <= ledger.DATA_CUTOFF)
        rows.append(f)
    return pd.DataFrame(rows)


def design(train, test):
    num = [c for c in train.columns if c.endswith("_w") or c in ("log_base", "start_fy_num")]
    Xtr = pd.get_dummies(train[num + CATS], columns=CATS, dtype=float)
    Xte = pd.get_dummies(test[num + CATS], columns=CATS, dtype=float)
    Xte = Xte.reindex(columns=Xtr.columns, fill_value=0.0)
    return Xtr, Xte


def mae(y, p):
    return float(np.mean(np.abs(np.asarray(y) - np.asarray(p))))


def medae(y, p):
    return float(np.median(np.abs(np.asarray(y) - np.asarray(p))))


def evaluate_window(df, window, label="g_exopt"):
    d = df[(df.closed == 1) & (df.window_complete == 1)].copy()
    train, test = d[d.start_fy <= TRAIN_MAX_FY], d[d.start_fy > TRAIN_MAX_FY]
    ytr, yte = train[label].values, test[label].values
    gw_col = "g_w" if label == "g_exopt" else "g_w_noC"
    preds = {}
    gm = float(np.median(ytr))
    preds["global_median"] = np.full(len(test), gm)
    by_type = train.groupby("avail_type")[label].median()
    preds["median_by_type"] = test.avail_type.map(by_type).fillna(gm).values
    preds["persistence"] = test[gw_col].values
    rem_med = float(np.median(ytr - train[gw_col].values))
    preds["persistence_plus_median_remaining"] = test[gw_col].values + rem_med
    Xtr, Xte = design(train, test)
    m = HistGradientBoostingRegressor(loss="absolute_error", max_depth=3, learning_rate=0.05,
                                      max_iter=300, min_samples_leaf=10, random_state=SEED)
    m.fit(Xtr.values, ytr - train[gw_col].values)
    preds["gbm"] = test[gw_col].values + m.predict(Xte.values)

    base = mae(yte, preds["global_median"])
    out = {"window_days": window, "label": label, "n_train": int(len(train)), "n_test": int(len(test)),
           "train_fy": f"<= {TRAIN_MAX_FY}", "test_fy": f">= {TRAIN_MAX_FY + 1}",
           "test_label_median": float(np.median(yte)), "models": {}}
    for k, p in preds.items():
        out["models"][k] = {"mae": round(mae(yte, p), 4), "medae": round(medae(yte, p), 4),
                            "mae_vs_global_median": round(1 - mae(yte, p) / base, 3)}
    out["pass_preregistered"] = out["models"]["gbm"]["mae_vs_global_median"] >= 0.15
    out["beats_persistence"] = out["models"]["gbm"]["mae"] < out["models"]["persistence"]["mae"]
    # bootstrap CI on the MAE improvement of gbm over persistence (paired)
    rng = np.random.default_rng(SEED)
    e_g = np.abs(yte - preds["gbm"])
    e_p = np.abs(yte - preds["persistence"])
    e_b = np.abs(yte - preds["global_median"])
    diffs_p, diffs_b = [], []
    for _ in range(2000):
        i = rng.integers(0, len(yte), len(yte))
        diffs_p.append(e_p[i].mean() - e_g[i].mean())
        diffs_b.append(1 - e_g[i].mean() / e_b[i].mean())
    out["gbm_minus_persistence_mae_gain_ci95"] = [round(float(np.percentile(diffs_p, 2.5)), 4),
                                                  round(float(np.percentile(diffs_p, 97.5)), 4)]
    out["gbm_vs_global_median_gain_ci95"] = [round(float(np.percentile(diffs_b, 2.5)), 3),
                                             round(float(np.percentile(diffs_b, 97.5)), 3)]
    return out, test.assign(pred_gbm=preds["gbm"], pred_persist=preds["persistence"])


def delay_label(con, window):
    """Secondary label: does a modification *after* day W mention a schedule extension,
    delay, period-of-performance change or late-delivery penalty? Keyword-based, so it is a
    proxy for schedule slip, not a measured delay in days."""
    lab = {}
    for a in con.execute("SELECT contract_id, first_action FROM availability").fetchall():
        cut = dt.date.fromisoformat(a["first_action"]) + dt.timedelta(days=window)
        hit = 0
        for x in con.execute("SELECT action_date, mod_number, description FROM contract_action "
                             "WHERE contract_id=?", (a["contract_id"],)):
            if dt.date.fromisoformat(x["action_date"][:10]) > cut and not ledger.is_base(x):
                t = (x["description"] or "").upper()
                if ledger.KW_DELAY.search(t) or ledger.KW_PENALTY.search(t):
                    hit = 1
                    break
        lab[a["contract_id"]] = hit
    return lab


def evaluate_delay(con, df, window):
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.metrics import roc_auc_score, brier_score_loss
    lab = delay_label(con, window)
    d = df[(df.closed == 1) & (df.window_complete == 1)].copy()
    d["late_flag"] = d.contract_id.map(lab)
    train, test = d[d.start_fy <= TRAIN_MAX_FY], d[d.start_fy > TRAIN_MAX_FY]
    Xtr, Xte = design(train, test)
    clf = HistGradientBoostingClassifier(max_depth=3, learning_rate=0.05, max_iter=200,
                                         min_samples_leaf=10, random_state=SEED)
    clf.fit(Xtr.values, train.late_flag.values)
    p = clf.predict_proba(Xte.values)[:, 1]
    yte = test.late_flag.values
    base_rate = float(train.late_flag.mean())
    # simple heuristic: growth already visible at day W
    out = {"window_days": window, "label": "delay/penalty keyword in a mod after day W",
           "n_train": int(len(train)), "n_test": int(len(test)),
           "rate_train": round(base_rate, 3), "rate_test": round(float(yte.mean()), 3)}
    if 0 < yte.sum() < len(yte):
        out["auc_gbm"] = round(float(roc_auc_score(yte, p)), 3)
        out["auc_growth_so_far"] = round(float(roc_auc_score(yte, test.g_w.values)), 3)
        out["auc_n_mods_so_far"] = round(float(roc_auc_score(yte, test.n_mods_w.values)), 3)
        # Writing-style check: offices word modifications differently, so a label built from
        # keywords can partly encode which office wrote it. Score an office-rate baseline.
        offices = {r["contract_id"]: r["office"] for r in con.execute(
            "SELECT contract_id, office FROM availability")}
        tr_off = train.contract_id.map(offices)
        rate = train.groupby(tr_off).late_flag.mean()
        p_off = test.contract_id.map(offices).map(rate).fillna(base_rate).values
        out["auc_office_rate_only"] = round(float(roc_auc_score(yte, p_off)), 3)
        out["brier_gbm"] = round(float(brier_score_loss(yte, p)), 4)
        out["brier_base_rate"] = round(float(brier_score_loss(yte, np.full(len(yte), base_rate))), 4)
    # does the delay proxy line up with cost growth?
    out["median_final_growth_if_late"] = round(float(d[d.late_flag == 1].g_exopt.median()), 3)
    out["median_final_growth_if_not"] = round(float(d[d.late_flag == 0].g_exopt.median()), 3)
    return out


def censoring_report(con):
    q = lambda s: [dict(r) for r in con.execute(s).fetchall()]
    return {
        "by_start_fy": q("SELECT start_fy, COUNT(*) n, SUM(closed) closed FROM availability GROUP BY start_fy"),
        "open_availabilities": q("SELECT COUNT(*) n, ROUND(AVG(g_exopt),3) mean_growth_so_far "
                                 "FROM availability WHERE closed=0")[0],
        "closed_definition": f"PoP end <= {ledger.CLOSED_BEFORE} (data cut-off {ledger.DATA_CUTOFF} minus 90-day DoD lag)",
        "latest_action_in_data": con.execute("SELECT MAX(action_date) FROM contract_action").fetchone()[0],
        "note": "Recent closed availabilities are biased toward short, quick ones; long FY24-26 "
                "availabilities are still open, so later-year test labels under-represent long jobs.",
    }


def run():
    con = db.connect()
    stats = ledger.build_ledger(con)
    results = {"ledger_funnel": stats, "censoring": censoring_report(con), "windows": [], "delay": []}
    for w in WINDOWS:
        df = load_frame(con, w)
        results["delay"].append(evaluate_delay(con, df, w))
        for label in ("g_exopt", "g_exopt_noC"):
            r, pred = evaluate_window(df, w, label)
            results["windows"].append(r)
            if label == "g_exopt":
                pred[["piid", "hull", "avail_type", "firm", "start_fy", "g_w", "g_exopt",
                      "pred_persist", "pred_gbm"]].to_csv(
                    os.path.join(ROOT, "eval", f"growth_predictions_w{w}.csv"), index=False)
    out = os.path.join(ROOT, "eval", "growth_model_results.json")
    with open(out, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(json.dumps(results["ledger_funnel"]))
    for r in results["windows"]:
        print(f"\nW={r['window_days']}d label={r['label']} train={r['n_train']} test={r['n_test']} "
              f"test median={r['test_label_median']:.3f}")
        for k, v in r["models"].items():
            print(f"   {k:36s} MAE={v['mae']:.4f} MedAE={v['medae']:.4f} gain_vs_global={v['mae_vs_global_median']:+.3f}")
        print(f"   pass_preregistered={r['pass_preregistered']} beats_persistence={r['beats_persistence']} "
              f"gain_vs_global CI95={r['gbm_vs_global_median_gain_ci95']} "
              f"gbm-vs-persistence MAE gain CI95={r['gbm_minus_persistence_mae_gain_ci95']}")
    for r in results["delay"]:
        print("\nDELAY", json.dumps(r))
    print("\nCENSORING", json.dumps(results["censoring"]["open_availabilities"]),
          results["censoring"]["latest_action_in_data"])
    print("wrote", out)
    return results
