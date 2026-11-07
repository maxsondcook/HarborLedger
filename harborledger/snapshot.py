"""Source snapshots: every raw file that enters the graph is recorded with its
origin, query, fetch time, hash and license, so any edge can be traced back."""
import hashlib
import json
import os
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(ROOT, "data", "raw")
MANIFEST = os.path.join(RAW, "manifest.jsonl")

LICENSES = {
    "usaspending": "CC0-1.0 (USAspending; federal data, public domain)",
    "wikipedia": "CC BY-SA 4.0 (Wikipedia; attribution + share-alike)",
    "curated": "Project-curated (cite research notes)",
    "marinecadastre": "CC0-1.0 (NOAA/BOEM MarineCadastre AIS)",
    "psix": "U.S. federal work, presumed public domain (USCG CGMIX PSIX; no terms page found)",
    "uscg_mvus": "U.S. federal work, presumed public domain (USCG Merchant Vessels of the U.S.; owner PII pre-redacted by USCG)",
    "calepa":"CalEPA/OEHHA public data (SB 535 disadvantaged communities; verify terms)",
    "derived": "Derived from sources listed on edge",
}


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def record(path, source, endpoint, params=None, fetched_at=None):
    rel = os.path.relpath(path, ROOT)
    row = {
        "path": rel,
        "source": source,
        "endpoint": endpoint,
        "params": params or {},
        "fetched_at": fetched_at or time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "sha256": sha256(path),
        "license": LICENSES[source],
    }
    with open(MANIFEST, "a") as f:
        f.write(json.dumps(row) + "\n")
    return row


def read_manifest():
    if not os.path.exists(MANIFEST):
        return []
    with open(MANIFEST) as f:
        return [json.loads(line) for line in f if line.strip()]


def http_json(url, body=None, timeout=90, retries=3, backoff=5.0):
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json", "User-Agent": "harborledger/0.1 (research)"}
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, data=data, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.load(r)
        except Exception as e:  # network errors, 5xx, bad JSON
            last = e
            time.sleep(backoff * (attempt + 1))
    raise RuntimeError(f"request failed after {retries} tries: {url}: {last}")
