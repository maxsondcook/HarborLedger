"""Collision-risk model: which close-quarters alerts become real close passes?

Question: when the straight-line (constant speed and course) projection raises an alert, a predicted
pass under 0.25 nm within 10 minutes, can information available at that moment say which alerts
will actually come true?

Data: traffic alerts (no tug/pilot/dredge/law-enforcement vessel) whose vessels are still more than
0.25 nm apart at the first alert, so the outcome is still open. Label: the vessels later came within
0.25 nm (observed on 1-minute tracks).

Features are known at the first alert only. Excluded on purpose: how long the alert lasted, any
observed separation, and the 'likely launch' flag (it is computed from realized encounters).

Pre-set test: train on 2024, test on 2025. Compare with (a) the straight-line rule (every alert is a
warning), and (b) a kinematic baseline using only predicted CPA and TCPA (logistic regression).
Also scored on vessel pairs never seen in training, so the model cannot just memorise regular
pairs such as ferries passing each other on schedule.
"""
import json
import os

import numpy as np
import pandas as pd

from . import ocean
from .encounters import CPA_NM, NM
from .snapshot import ROOT, json_safe
from .weather import OFFSHORE_BUOY

OUT = os.path.join(ROOT, "data", "derived")
THRESH = CPA_NM * NM


def vclass(t):
    t = pd.Series(t)
    return np.select([t.between(70, 79), t.between(80, 89), t.between(60, 69), t.isin([31, 32, 52]),
                      t == 30, t.isin([36, 37]), t == 35], ["cargo", "tanker", "passenger", "tug", "fishing",
                                                             "pleasure", "military"], "other")


def features(df, buoys):
    d = df[(df.service == 0) & (df.dist_first_m > THRESH)].copy()
    d["t"] = pd.to_datetime(d.t_first, unit="s")
    d["hour_utc"] = d.t.dt.hour
    d["weekday"] = d.t.dt.dayofweek
    d["month"] = d.t.dt.month
    d["course_diff"] = np.abs(((d.cog_a - d.cog_b) + 180) % 360 - 180)
    brg = np.degrees(np.arctan2(d.rel_x_m, d.rel_y_m)) % 360          # bearing A -> B
    d["rel_bearing_a"] = np.abs(((brg - d.cog_a) + 180) % 360 - 180)  # 0 = B dead ahead of A
    d["rel_bearing_b"] = np.abs((((brg + 180) % 360 - d.cog_b) + 180) % 360 - 180)
    d["speed_ratio"] = np.minimum(d.sog_a, d.sog_b) / np.maximum(d.sog_a, d.sog_b).clip(lower=0.1)
    d["closing_fraction"] = (d.dist_first_m - d.cpa_pred_m) / d.dist_first_m.clip(lower=1)
    d["class_a"], d["class_b"] = vclass(d.type_a), vclass(d.type_b)
    pair = np.sort(np.stack([d.class_a.values, d.class_b.values], 1), axis=1)
    d["class_pair"] = pd.Series(pair[:, 0] + "|" + pair[:, 1], index=d.index)
    d["len_max"] = d[["len_a", "len_b"]].max(axis=1)
    d["len_min"] = d[["len_a", "len_b"]].min(axis=1)
    # sea state at the area's offshore buoy that hour
    b = buoys[["station", "hour", "WVHT", "WSPD"]]
    d["station"] = d.region.map(OFFSHORE_BUOY)
    d["hour"] = d.t.dt.floor("h")
    d = d.merge(b, on=["station", "hour"], how="left")
    for c in ("geometry", "region", "class_pair"):
        d[c] = d[c].astype("category")
    d["pair_key"] = np.minimum(d.mmsi_a, d.mmsi_b).astype(str) + "_" + np.maximum(d.mmsi_a, d.mmsi_b).astype(str)
    return d


FEATS = ["cpa_pred_m", "tcpa_pred_s", "dist_first_m", "sog_a", "sog_b", "rel_speed_kn", "course_diff",
         "rel_bearing_a", "rel_bearing_b", "speed_ratio", "closing_fraction", "len_max", "len_min",
         "area_moving_vessels", "neighbours_a", "neighbours_b", "hour_utc", "weekday", "month",
         "WVHT", "WSPD", "geometry", "region", "class_pair"]
KIN = ["cpa_pred_m", "tcpa_pred_s"]


def _prec_at_recall(y, p, recall):
    """Precision when the threshold is set to catch `recall` of true encounters."""
    order = np.argsort(-p)
    ys = y[order]
    tp = np.cumsum(ys)
    k = np.searchsorted(tp, recall * ys.sum())
    return float(tp[k] / (k + 1))


def run(train_year=2024, test_year=2025, seed=7):
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.inspection import permutation_importance
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score
    buoys = ocean.hourly()
    tr = features(pd.read_csv(os.path.join(OUT, f"encounters_{train_year}.csv")), buoys)
    te = features(pd.read_csv(os.path.join(OUT, f"encounters_{test_year}.csv")), buoys)
    ytr, yte = tr.realized.values, te.realized.values

    kin = LogisticRegression(max_iter=1000).fit(np.log1p(tr[KIN]), ytr)
    p_kin = kin.predict_proba(np.log1p(te[KIN]))[:, 1]
    gbm = HistGradientBoostingClassifier(max_depth=6, learning_rate=0.05, max_iter=400, min_samples_leaf=50,
                                         categorical_features="from_dtype", random_state=seed)
    gbm.fit(tr[FEATS], ytr)
    p_gbm = gbm.predict_proba(te[FEATS])[:, 1]

    def scores(y, p, name):
        return {"model": name, "auc": round(float(roc_auc_score(y, p)), 3),
                "avg_precision": round(float(average_precision_score(y, p)), 3),
                "brier": round(float(brier_score_loss(y, p)), 4),
                "precision_at_90pct_recall": round(_prec_at_recall(y, p, 0.90), 3),
                "precision_at_75pct_recall": round(_prec_at_recall(y, p, 0.75), 3)}

    base = float(yte.mean())
    out = {"train_year": train_year, "test_year": test_year, "n_train": int(len(tr)), "n_test": int(len(te)),
           "definition": "traffic alerts still > 0.25 nm apart at first alert; label = came within 0.25 nm",
           "straight_line_precision": round(base, 3),
           "models": [scores(yte, p_kin, "kinematic (CPA + TCPA only)"), scores(yte, p_gbm, "full model")]}
    # bootstrap the AUC and precision gains of the full model over the kinematic baseline
    rng = np.random.default_rng(seed)
    g_auc, g_p90 = [], []
    for _ in range(200):
        i = rng.integers(0, len(yte), len(yte))
        g_auc.append(roc_auc_score(yte[i], p_gbm[i]) - roc_auc_score(yte[i], p_kin[i]))
        g_p90.append(_prec_at_recall(yte[i], p_gbm[i], 0.9) - _prec_at_recall(yte[i], p_kin[i], 0.9))
    out["gain_over_kinematic"] = {
        "auc": [round(float(np.percentile(g_auc, q)), 3) for q in (2.5, 50, 97.5)],
        "precision_at_90pct_recall": [round(float(np.percentile(g_p90, q)), 3) for q in (2.5, 50, 97.5)]}
    # by look-ahead
    te = te.assign(p_gbm=p_gbm, p_kin=p_kin)
    out["by_lookahead"] = []
    for lo, hi in ((0, 2), (2, 5), (5, 10)):
        s = te[(te.tcpa_pred_s >= lo * 60) & (te.tcpa_pred_s < hi * 60)]
        if s.realized.nunique() < 2:
            continue
        out["by_lookahead"].append({
            "minutes": f"{lo}-{hi}", "n": int(len(s)), "straight_line_precision": round(float(s.realized.mean()), 3),
            "kinematic_p90": round(_prec_at_recall(s.realized.values, s.p_kin.values, 0.9), 3),
            "model_p90": round(_prec_at_recall(s.realized.values, s.p_gbm.values, 0.9), 3),
            "kinematic_auc": round(float(roc_auc_score(s.realized, s.p_kin)), 3),
            "model_auc": round(float(roc_auc_score(s.realized, s.p_gbm)), 3)})
    # vessel pairs never seen in training
    new = ~te.pair_key.isin(set(tr.pair_key))
    out["unseen_pairs"] = {"share_of_test": round(float(new.mean()), 3),
                           **{k: v for k, v in scores(te.realized.values[new], p_gbm[new], "full model").items() if k != "model"},
                           "kinematic_auc": round(float(roc_auc_score(te.realized.values[new], p_kin[new])), 3)}
    # large-vessel subset (cargo/tanker or >= 50 m), the case autonomy and pilots care most about
    lg = (te.class_a.isin(["cargo", "tanker"]) | te.class_b.isin(["cargo", "tanker"]) | (te.len_max >= 50)).values
    if lg.any() and te.realized.values[lg].std() > 0:
        out["large_vessel_alerts"] = {"n": int(lg.sum()), "straight_line_precision": round(float(yte[lg].mean()), 3),
                                      "kinematic_auc": round(float(roc_auc_score(yte[lg], p_kin[lg])), 3),
                                      "model_auc": round(float(roc_auc_score(yte[lg], p_gbm[lg])), 3),
                                      "kinematic_p90": round(_prec_at_recall(yte[lg], p_kin[lg], 0.9), 3),
                                      "model_p90": round(_prec_at_recall(yte[lg], p_gbm[lg], 0.9), 3)}
    # what the model relies on (permutation importance on a test sample)
    samp = te.sample(min(40000, len(te)), random_state=seed)
    pi = permutation_importance(gbm, samp[FEATS], samp.realized, scoring="roc_auc", n_repeats=3, random_state=seed)
    out["importance_auc_drop"] = sorted([{"feature": f, "drop": round(float(m), 4)} for f, m in zip(FEATS, pi.importances_mean)],
                                        key=lambda r: -r["drop"])[:12]
    # calibration in deciles
    te["dec"] = pd.qcut(te.p_gbm, 10, labels=False, duplicates="drop")
    out["calibration"] = te.groupby("dec").agg(pred=("p_gbm", "mean"), obs=("realized", "mean"), n=("realized", "size")
                                               ).round(3).reset_index().to_dict("records")
    with open(os.path.join(ROOT, "eval", "collision_model_results.json"), "w") as f:
        json.dump(json_safe(out), f, indent=2, default=str, allow_nan=False)
    te[["day", "region", "mmsi_a", "mmsi_b", "t_first", "cpa_pred_m", "tcpa_pred_s", "realized", "p_kin", "p_gbm"]].to_parquet(
        os.path.join(OUT, f"collision_predictions_{test_year}.parquet"), index=False)
    return out
