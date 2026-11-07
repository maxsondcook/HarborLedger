"""USAspending pulls (keyless API). Award search results and per-award
transaction histories are written as raw JSON snapshots and logged in the
manifest. Pulls are resumable: existing transaction files are skipped."""
import json
import os
import sys
import time

from .snapshot import RAW, http_json, record

API = "https://api.usaspending.gov/api/v2"
AWARD_DIR = os.path.join(RAW, "usaspending", "awards")
TXN_DIR = os.path.join(RAW, "usaspending", "transactions")

AWARD_FIELDS = [
    "Award ID", "Recipient Name", "Recipient UEI", "Award Amount", "Total Outlays",
    "Description", "Start Date", "End Date", "Awarding Agency", "Awarding Sub Agency",
    "Contract Award Type", "Place of Performance City Code", "Place of Performance State Code",
    "Place of Performance Zip5", "NAICS", "PSC", "generated_internal_id", "Last Modified Date",
    "Base Obligation Date",
]

# The filter used for the national >= $5M Navy NAICS 336611 universe (FY2015-FY2026).
NAVY_336611_GE5M = {
    "time_period": [{"start_date": "2014-10-01", "end_date": "2026-09-30"}],
    "award_type_codes": ["A", "B", "C", "D"],
    "naics_codes": {"require": ["336611"]},
    "agencies": [{"type": "awarding", "tier": "subtier", "name": "Department of the Navy"}],
    "award_amounts": [{"lower_bound": 5000000}],
}


def pull_awards(out_name, filters=NAVY_336611_GE5M, max_pages=200, sleep=0.6):
    rows, page = [], 1
    while page <= max_pages:
        body = {"filters": filters, "fields": AWARD_FIELDS, "limit": 100, "page": page,
                "sort": "Award Amount", "order": "desc", "subawards": False}
        d = http_json(f"{API}/search/spending_by_award/", body)
        rows += d.get("results", [])
        if not d.get("page_metadata", {}).get("hasNext"):
            break
        page += 1
        time.sleep(sleep)
    path = os.path.join(AWARD_DIR, out_name)
    with open(path, "w") as f:
        json.dump(rows, f)
    record(path, "usaspending", "/search/spending_by_award/", {"filters": filters})
    return path, len(rows)


def txn_path(gid):
    return os.path.join(TXN_DIR, gid.replace("/", "_") + ".json")


def pull_transactions(gid, sleep=0.4):
    out, page = [], 1
    while True:
        d = http_json(f"{API}/transactions/", {"award_id": gid, "limit": 5000, "page": page,
                                               "sort": "action_date", "order": "asc"})
        out += d.get("results", [])
        if not d.get("page_metadata", {}).get("hasNext"):
            break
        page += 1
        time.sleep(sleep)
    path = txn_path(gid)
    with open(path, "w") as f:
        json.dump({"award_id": gid, "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                   "results": out}, f)
    record(path, "usaspending", "/transactions/", {"award_id": gid})
    return len(out)


def pull_all_transactions(award_file, sleep=0.4, log=sys.stdout, reverse=False):
    """Resumable. A second worker can run with reverse=True; each skips files that exist."""
    with open(award_file) as f:
        awards = json.load(f)
    gids = [a["generated_internal_id"] for a in awards if a.get("generated_internal_id")]
    if reverse:
        gids.reverse()
    done = skipped = failed = 0
    t0 = time.time()
    for i, gid in enumerate(gids, 1):
        if os.path.exists(txn_path(gid)):
            skipped += 1
            continue
        try:
            pull_transactions(gid)
            done += 1
        except Exception as e:
            failed += 1
            print(f"FAIL {gid}: {e}", file=log, flush=True)
        if i % 50 == 0:
            print(f"{i}/{len(gids)} done={done} skipped={skipped} failed={failed} "
                  f"elapsed={time.time() - t0:.0f}s", file=log, flush=True)
        time.sleep(sleep)
    print(f"FINISHED {len(gids)} done={done} skipped={skipped} failed={failed}", file=log, flush=True)
    return done, skipped, failed
