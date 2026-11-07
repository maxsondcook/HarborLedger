"""Week 1-2 success tests (pre-registered in the Phase 3 report):
  1. Hull precision >= 95% on a fresh 50-award hand-labelled sample.
  2. >= 90% of award dollars mapped to a curated firm.
Labels live in eval/hull_sample_<seed>.csv; `label_hulls` is filled by hand
(semicolon-separated normalised hulls such as DDG-105; empty = no specific ship named)."""
import csv
import json
import math
import os
import random

from . import db, hulls
from .snapshot import ROOT

EVAL = os.path.join(ROOT, "eval")


def wilson(k, n, z=1.96):
    if n == 0:
        return (float("nan"), float("nan"))
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (round(c - h, 3), round(c + h, 3))


def write_sample(n, seed):
    con = db.connect()
    rows = con.execute("SELECT contract_id, piid, description FROM contract "
                       "WHERE description IS NOT NULL AND description <> '' ORDER BY contract_id").fetchall()
    random.Random(seed).shuffle(rows)
    pred = {}
    for r in con.execute("SELECT src, dst, method FROM edge WHERE rel='ABOUT_VESSEL' AND confidence >= ?",
                         (hulls.ASSERT_THRESHOLD,)):
        pred.setdefault(r["src"][len("contract:"):], []).append(f"{r['dst'][5:]}|{r['method']}")
    path = os.path.join(EVAL, f"hull_sample_{seed}.csv")
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["contract_id", "piid", "description", "predicted", "label_hulls", "label_note"])
        for r in rows[:n]:
            w.writerow([r["contract_id"], r["piid"], r["description"],
                        ";".join(pred.get(r["contract_id"], [])), "", ""])
    print("wrote", path)


def hull_test(path):
    tp = fp = fn = 0
    by_method = {}
    errors = []
    with open(path, newline="") as f:
        for r in csv.DictReader(f):
            gold = {h.strip() for h in r["label_hulls"].split(";") if h.strip()}
            preds = [p.split("|") for p in r["predicted"].split(";") if p.strip()]
            got = {h for h, _ in preds}
            for h, m in preds:
                ok = h in gold
                s = by_method.setdefault(m, [0, 0])
                s[0] += ok
                s[1] += 1
                if not ok:
                    errors.append(("FP", r["piid"], h, m, r["description"][:90]))
            tp += len(got & gold)
            fp += len(got - gold)
            fn += len(gold - got)
            for h in gold - got:
                errors.append(("FN", r["piid"], h, "", r["description"][:90]))
    prec = tp / (tp + fp) if tp + fp else float("nan")
    rec = tp / (tp + fn) if tp + fn else float("nan")
    return {
        "sample_file": os.path.relpath(path, ROOT),
        "precision": round(prec, 3), "precision_ci95": wilson(tp, tp + fp),
        "recall": round(rec, 3), "recall_ci95": wilson(tp, tp + fn),
        "tp": tp, "fp": fp, "fn": fn,
        "by_method": {m: {"correct": c, "n": n, "precision": round(c / n, 3)} for m, (c, n) in by_method.items()},
        "errors": errors,
        "pass": prec >= 0.95,
    }


def firm_coverage():
    con = db.connect()
    rows = con.execute("""
        SELECT c.recipient_uei, c.award_amount,
               (SELECT dst FROM edge e WHERE e.src = 'uei:' || c.recipient_uei
                 AND e.rel='PART_OF' LIMIT 1) AS firm
        FROM contract c""").fetchall()
    tot = sum(r["award_amount"] or 0 for r in rows)
    mapped = sum(r["award_amount"] or 0 for r in rows if r["firm"])
    n_map = sum(1 for r in rows if r["firm"])
    ueis = {r["recipient_uei"] for r in rows}
    ueis_mapped = {r["recipient_uei"] for r in rows if r["firm"]}
    multi = con.execute("""SELECT dst, COUNT(*) n FROM edge WHERE rel='PART_OF' AND src LIKE 'uei:%'
                           GROUP BY dst HAVING n > 1""").fetchall()
    return {
        "dollar_share_mapped": round(mapped / tot, 4), "awards_mapped": n_map, "awards": len(rows),
        "recipients_mapped": len(ueis_mapped), "recipients": len(ueis),
        "firms_with_multiple_ueis": {r["dst"]: r["n"] for r in multi},
        "pass": mapped / tot >= 0.90,
    }


def repredict(path):
    """Refresh the `predicted` column of a labelled sample from the current build,
    keeping the hand labels. Used to re-score the development sample after a fix."""
    con = db.connect()
    with open(path, newline="") as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        r["predicted"] = ";".join(
            f"{e['dst'][5:]}|{e['method']}" for e in con.execute(
                "SELECT dst, method FROM edge WHERE rel='ABOUT_VESSEL' AND src=? AND confidence >= ?",
                ("contract:" + r["contract_id"], hulls.ASSERT_THRESHOLD)))
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


def run():
    results = {"firm_coverage": firm_coverage()}
    samples = sorted(f for f in os.listdir(EVAL) if f.startswith("hull_sample_") and f.endswith(".csv"))
    for s in samples:
        results[s] = hull_test(os.path.join(EVAL, s))
    out = os.path.join(EVAL, "results.json")
    with open(out, "w") as f:
        json.dump(results, f, indent=2)
    for k, v in results.items():
        print(k, json.dumps({kk: vv for kk, vv in v.items() if kk != "errors"}))
        for e in v.get("errors", []):
            print("   ", e)
    print("wrote", out)
