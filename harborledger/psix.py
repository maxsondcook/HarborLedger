"""USCG PSIX (CGMIX) vessel lookup and gated AIS -> PSIX matching.

PSIX is a keyless SOAP service. Each query response is cached as a raw snapshot, so
re-running the match never repeats a call. Calls are throttled to ~1 per 1.1 s.

Gating, learned from the Phase 3 test (n=443, where all six false positives were call
signs reused by a different vessel):
  SAME_AS (auto-merge)      call-sign hit AND (IMO agrees OR name similarity >= 0.8)
  POSSIBLE_SAME_AS          call-sign hit with weaker name agreement (kept for review)
  SAME_AS via name+IMO      no call-sign hit, name search returns a record whose IMO agrees
"""
import difflib
import glob
import hashlib
import html
import json
import os
import re
import time
import urllib.request

import pandas as pd

from .snapshot import RAW, USER_AGENT, record

URL = "https://cgmix.uscg.mil/xml/PSIXData.asmx"
CACHE = os.path.join(RAW, "psix")
NAME_GATE = 0.8
COMMERCIAL_TYPES = set(range(60, 90)) | {31, 32, 52, 30}   # passenger, cargo, tanker, tug/tow, fishing
JUNK_CALLSIGNS = {"", "NAN", "NONE", "NOCOMMS", "CH16", "APPLY", "UNKNOWN", "0", "NA"}


def _key(kw):
    return hashlib.sha1(json.dumps(kw, sort_keys=True).encode()).hexdigest()[:16]


def query(**kw):
    os.makedirs(CACHE, exist_ok=True)
    path = os.path.join(CACHE, f"{_key(kw)}.json")
    if os.path.exists(path):
        return json.load(open(path))["results"]
    f = dict(VesselID="", VesselName="", CallSign="", VIN="", HIN="", Flag="", Service="", BuildYear="")
    f.update(kw)
    body = "".join(f"<{k}>{html.escape(str(x))}</{k}>" for k, x in f.items())
    env = ('<?xml version="1.0" encoding="utf-8"?><soap:Envelope '
           'xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/"><soap:Body>'
           f'<getVesselSummaryXMLString xmlns="https://cgmix.uscg.mil">{body}'
           '</getVesselSummaryXMLString></soap:Body></soap:Envelope>')
    last = None
    for attempt in range(3):
        try:
            req = urllib.request.Request(URL, data=env.encode(), headers={
                "Content-Type": "text/xml; charset=utf-8",
                "SOAPAction": '"https://cgmix.uscg.mil/getVesselSummaryXMLString"',
                "User-Agent": USER_AGENT})
            t = html.unescape(urllib.request.urlopen(req, timeout=60).read().decode("utf-8", "replace"))
            res = [dict(re.findall(r"<(\w+)>([^<]*)</\1>", r))
                   for r in re.findall(r"<VesselSummary>(.*?)</VesselSummary>", t, re.S)]
            with open(path, "w") as fh:
                json.dump({"query": kw, "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                           "results": res}, fh)
            record(path, "psix", URL + "#getVesselSummaryXMLString", kw)
            time.sleep(1.1)
            return res
        except Exception as e:
            last = e
            time.sleep(5 * (attempt + 1))
    raise RuntimeError(f"PSIX failed {kw}: {last}")


def norm_name(n):
    n = re.sub(r"[^A-Z0-9 ]", " ", str(n or "").upper())
    n = re.sub(r"^(M ?V|F ?V|S ?S|T ?V|MV|FV|RV|TUG|USNS|USS)\s+", "", n.strip())
    return re.sub(r"\s+", " ", n).strip()


def imo_valid(x):
    x = str(x or "").upper().replace("IMO", "").strip()
    if not re.fullmatch(r"\d{7}", x) or int(x) < 1000000:
        return ""
    d = [int(c) for c in x]
    return x if sum(d[i] * (7 - i) for i in range(6)) % 10 == d[6] else ""


def match_vessel(v):
    """v: dict with mmsi, name, call_sign, imo. Returns a match record."""
    cs = str(v.get("call_sign") or "").strip().upper()
    cs = "" if cs in JUNK_CALLSIGNS else cs
    imo = imo_valid(v.get("imo"))
    an = norm_name(v.get("name"))
    rec = {"mmsi": int(v["mmsi"]), "ais_name": v.get("name"), "call_sign": cs, "imo": imo,
           "rel": None, "method": None, "confidence": None}
    def scored(c):
        pn = norm_name(c.get("VesselName"))
        ratio = difflib.SequenceMatcher(None, an, pn).ratio() if an and pn else 0.0
        imo_ok = bool(imo) and c.get("Identification", "").strip() == imo
        return ratio, imo_ok
    if cs:
        cands = query(CallSign=cs)
        rec["cs_hits"] = len(cands)
        if cands:
            best = max(cands, key=lambda c: (scored(c)[1], scored(c)[0],
                                             c.get("StatusLookupName", "").lower().startswith("active")))
            ratio, imo_ok = scored(best)
            rec.update(psix_id=best.get("VesselId"), psix_name=best.get("VesselName"),
                       psix_ident=best.get("Identification"), psix_status=best.get("StatusLookupName"),
                       psix_service=best.get("ServiceType"), name_ratio=round(ratio, 3), imo_agree=imo_ok)
            if imo_ok or ratio >= NAME_GATE:
                rec.update(rel="SAME_AS", method="callsign_gated",
                           confidence=0.98 if imo_ok else round(0.85 + 0.12 * ratio, 3))
            else:
                rec.update(rel="POSSIBLE_SAME_AS", method="callsign_weak_name",
                           confidence=round(0.3 + 0.4 * ratio, 3))
            return rec
    if imo and an and len(an) >= 3:
        nc = query(VesselName=str(v.get("name")).strip())
        m = [c for c in nc if c.get("Identification", "").strip() == imo]
        if m:
            rec.update(psix_id=m[0].get("VesselId"), psix_name=m[0].get("VesselName"),
                       psix_ident=m[0].get("Identification"), psix_status=m[0].get("StatusLookupName"),
                       psix_service=m[0].get("ServiceType"), imo_agree=True,
                       name_ratio=round(scored(m[0])[0], 3),
                       rel="SAME_AS", method="name_plus_imo", confidence=0.97)
    return rec


def ca_commercial_vessels(files):
    seen = {}
    for f in files:
        import pyarrow.parquet as pq
        t = pq.read_table(f, columns=["mmsi", "vessel_name", "call_sign", "imo", "vessel_type",
                                      "base_date_time"]).to_pandas()
        t = t[t.vessel_type.isin(COMMERCIAL_TYPES)]
        day = os.path.basename(f)[7:17]
        g = t.groupby("mmsi").agg(name=("vessel_name", "first"), call_sign=("call_sign", "first"),
                                  imo=("imo", "first"), vessel_type=("vessel_type", "first"))
        for m, r in g.iterrows():
            if m not in seen:
                seen[m] = {"mmsi": int(m), **r.to_dict(), "first_day": day, "last_day": day}
            else:
                seen[m]["last_day"] = day
    return pd.DataFrame(seen.values())


def run_matching(files, out_csv, log=print):
    vs = ca_commercial_vessels(files)
    log(f"commercial vessels: {len(vs)}")
    rows = []
    for i, v in enumerate(vs.to_dict("records"), 1):
        r = match_vessel(v)
        r.update(vessel_type=int(v["vessel_type"]), first_day=v["first_day"], last_day=v["last_day"])
        rows.append(r)
        if i % 100 == 0:
            log(f"{i}/{len(vs)}")
            pd.DataFrame(rows).to_csv(out_csv, index=False)
    pd.DataFrame(rows).to_csv(out_csv, index=False)
    log("FINISHED")
    return pd.DataFrame(rows)
