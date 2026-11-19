"""'One ship, five records': export how separate source records resolve into one vessel.

Files written into the site's data folder:
  traces.json            funnel (raw records -> identifiers -> links -> entities, with accuracy)
                         and the index of showcase vessels for the picker
  trace/<slug>.json      one vessel: each source record as that source names it, the rule and
                         confidence that joined it to the next record, its 2025 AIS track,
                         its Navy contracts and its close calls

Entities are connected components over SAME_AS edges with confidence >= ASSERT (links kept for
audit below that threshold are shown but do not merge records).
"""
import glob
import json
import math
import os

import pandas as pd

from .snapshot import RAW, ROOT

ASSERT = 0.5
DERIVED = os.path.join(ROOT, "data", "derived")
SOURCE = {
    "usaspending": "USAspending (Navy contracts)",
    "wikipedia": "Wikipedia (ship list and article)",
    "ais": "MarineCadastre AIS (ship tracking)",
    "psix": "Coast Guard PSIX (inspections)",
    "mvus": "Coast Guard register (documentation)",
}
RULES = {
    "regex_hull": "Hull number read from the contract text (e.g. 'DDG 105', 'T-AO-194')",
    "gazetteer": "Ship name in the contract text looked up in the Wikipedia name to hull list",
    "gazetteer_short": "Short ship name in the contract text looked up in the name to hull list",
    "regex_hull_classlead": "Class-lead hull mentioned in the text (weak; kept for audit)",
    "wikipedia_imo_mmsi": "Wikipedia infobox IMO and MMSI both equal the AIS record's",
    "wikipedia_imo": "Wikipedia infobox IMO equals the AIS record's IMO",
    "wikipedia_mmsi": "Wikipedia infobox MMSI equals the AIS record's MMSI",
    "callsign_gated": "Same call sign, and the names agree (similarity gate)",
    "name_plus_imo": "Same IMO number, and the names agree",
    "callsign_weak_name": "Same call sign but the names disagree (kept for audit, not merged)",
    "official_number": "PSIX identification equals the register's official number",
    "callsign_gated_mvus": "Same call sign as the register entry, and the names agree",
}


class _UF:
    def __init__(self):
        self.p = {}

    def find(self, x):
        self.p.setdefault(x, x)
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x

    def union(self, a, b):
        self.p[self.find(a)] = self.find(b)


def components(con):
    uf = _UF()
    for (v,) in con.execute("SELECT vessel_id FROM vessel"):
        uf.find(v)
    for s, d in con.execute("SELECT src, dst FROM edge WHERE rel='SAME_AS' AND confidence >= ?", (ASSERT,)):
        uf.union(s, d)
    groups = {}
    for v in list(uf.p):
        groups.setdefault(uf.find(v), []).append(v)
    return groups


def _psix_raw():
    out = {}
    for f in glob.glob(os.path.join(RAW, "psix", "*.json")):
        try:
            for r in json.load(open(f)).get("results") or []:
                out.setdefault(str(r.get("VesselId")), r)
        except (ValueError, AttributeError):
            continue
    return out


def _article(hull):
    p = os.path.join(RAW, "wikipedia", "articles", f"{hull}.json")
    if not os.path.exists(p):
        return None
    b = json.load(open(p)).get("parse")
    return b.get("title") if b else None


def _ids(con, vid):
    return {r[0]: r[1] for r in con.execute("SELECT scheme, value FROM identifier WHERE vessel_id=?", (vid,))}


def _records(con, nodes, psix_raw):
    """Source records for one entity, in story order, plus the edges that join them."""
    recs = []
    hulls = [n for n in nodes if n.startswith("hull:")]
    mmsis = sorted(n for n in nodes if n.startswith("mmsi:"))
    psixs = sorted(n for n in nodes if n.startswith("psix:"))
    uscgs = sorted(n for n in nodes if n.startswith("uscg:"))
    contracts = []
    for h in hulls:
        for r in con.execute(
                "SELECT c.contract_id, c.piid, c.description, c.recipient_name, c.start_date, c.end_date, "
                "c.award_amount, e.confidence, e.method, e.evidence FROM edge e JOIN contract c "
                "ON e.src = 'contract:' || c.contract_id WHERE e.dst=? AND e.rel='ABOUT_VESSEL' AND e.confidence >= 0.5 "
                "ORDER BY c.start_date", (h,)):
            contracts.append(dict(zip(["contract_id", "piid", "description", "recipient", "start", "end",
                                       "amount", "confidence", "method", "evidence"], r)))
    if contracts:
        top = max(contracts, key=lambda c: c["amount"] or 0)
        recs.append({"source": "usaspending", "id": f"contract:{top['piid']}",
                     "names_it_as": top["evidence"] or top["description"][:60],
                     "fields": {"PIID": top["piid"], "Description (as written)": top["description"],
                                "Recipient": top["recipient"], "Award": top["amount"],
                                "Start": top["start"], "Contracts naming this hull": len(contracts)},
                     "join": {"rule": RULES.get(top["method"], top["method"]), "method": top["method"],
                              "confidence": top["confidence"], "evidence": top["evidence"]}})
    for h in hulls:
        v = con.execute("SELECT name, hull, hull_class, name_source FROM vessel WHERE vessel_id=?", (h,)).fetchone()
        title = _article(v[1])
        link = con.execute("SELECT confidence, method, evidence FROM edge WHERE src=? AND rel='SAME_AS' "
                           "ORDER BY confidence DESC", (h,)).fetchone()
        rec = {"source": "wikipedia", "id": h, "names_it_as": f"{v[0]} ({v[1]})" if v[0] else v[1],
               "fields": {"Hull": v[1], "Class": v[2], "Name": v[0], "Article": title}}
        if link:
            rec["join"] = {"rule": RULES.get(link[1], link[1]), "method": link[1], "confidence": link[0],
                           "evidence": link[2]}
        recs.append(rec)
    for m in mmsis:
        i = _ids(con, m)
        g = con.execute("SELECT hull_class FROM vessel WHERE vessel_id=?", (m,)).fetchone()[0]
        link = con.execute("SELECT confidence, method, evidence, dst FROM edge WHERE src=? AND rel='SAME_AS' "
                           "AND dst NOT LIKE 'hull:%' ORDER BY dst LIKE 'psix:%' DESC, confidence DESC", (m,)).fetchone()
        rec = {"source": "ais", "id": m, "names_it_as": i.get("ais_name"),
               "fields": {"MMSI": i.get("mmsi"), "Name broadcast": i.get("ais_name"), "Call sign": i.get("call_sign"),
                          "IMO": i.get("imo"), "Type group": g}}
        if link:
            rec["join"] = {"rule": RULES.get(link[1], link[1]), "method": link[1], "confidence": link[0],
                           "evidence": link[2]}
        recs.append(rec)
    for p in psixs:
        raw = psix_raw.get(p.split(":")[1], {})
        name = con.execute("SELECT name FROM vessel WHERE vessel_id=?", (p,)).fetchone()[0]
        link = con.execute("SELECT confidence, method, evidence FROM edge WHERE src=? AND rel='SAME_AS'", (p,)).fetchone()
        rec = {"source": "psix", "id": p, "names_it_as": name,
               "fields": {"PSIX vessel ID": p.split(":")[1], "Name": name, "Call sign": raw.get("VesselCallSign"),
                          "Identification": raw.get("Identification"), "Service": raw.get("ServiceType"),
                          "Built": raw.get("ConstructionCompletedYear"), "Status": raw.get("StatusLookupName")}}
        if link:
            rec["join"] = {"rule": RULES.get(link[1], link[1]), "method": link[1], "confidence": link[0],
                           "evidence": link[2]}
        recs.append(rec)
    for u in uscgs:
        r = con.execute("SELECT vessel_name, official_number, call_sign, imo_number, service, builder, build_year, "
                        "length, gross_ton, org_name, coastwise_any FROM uscg_vessel WHERE edition='Jul24' "
                        "AND official_number=?", (u.split(":")[1],)).fetchone()
        if not r:
            continue
        recs.append({"source": "mvus", "id": u, "names_it_as": r[0],
                     "fields": {"Official number": r[1], "Name": r[0], "Call sign": r[2] or None, "IMO": r[3] or None,
                                "Service": r[4], "Builder": r[5] or None, "Built": r[6] or None,
                                "Length (ft)": r[7] or None, "Gross tons": r[8] or None,
                                "Owner (organisations only)": r[9] or None,
                                "Coastwise trade": "yes" if r[10] == 1 else "no"}})
    weak = [dict(zip(["src", "dst", "confidence", "method", "evidence"], r)) for r in con.execute(
        f"SELECT src, dst, confidence, method, evidence FROM edge WHERE rel IN ('SAME_AS','POSSIBLE_SAME_AS') "
        f"AND confidence < ? AND src IN ({','.join('?' * len(nodes))})", (ASSERT, *nodes))]
    return recs, contracts, weak


def _track(hours, mmsis, max_pts=700):
    t = hours[hours.mmsi.isin(mmsis)].sort_values("hour")
    if t.empty:
        return None
    step = max(1, math.ceil(len(t) / max_pts))
    s = t.iloc[::step]
    return {"hours": int(len(t)), "days": int(t.hour.dt.date.nunique()),
            "first": str(t.hour.min())[:10], "last": str(t.hour.max())[:10],
            "points": [[round(a, 4), round(b, 4), round(float(c), 1)] for a, b, c in zip(s.lon, s.lat, s.sog)]}


def _encounters(enc, mmsis):
    e = enc[enc.mmsi_a.isin(mmsis) | enc.mmsi_b.isin(mmsis)]
    if e.empty:
        return {"alerts": 0, "realized": 0, "traffic_alerts": 0, "closest": []}
    other = e.apply(lambda r: r.name_b if r.mmsi_a in mmsis else r.name_a, axis=1)
    e = e.assign(other=other)
    top = e[e.realized == 1].nsmallest(5, "min_sep_obs_m")
    return {"alerts": int(len(e)), "realized": int(e.realized.sum()),
            "traffic_alerts": int((e.service == 0).sum()),
            "service_share": round(float((e.service == 1).mean()), 3),
            "regions": e.region.value_counts().to_dict(),
            "closest": [{"day": r.day, "other": r.other if isinstance(r.other, str) else "unnamed vessel",
                         "min_sep_m": round(float(r.min_sep_obs_m)), "pred_cpa_m": round(float(r.cpa_pred_m)),
                         "geometry": r.geometry, "region": r.region} for r in top.itertuples()]}


def funnel(con, groups, bridge_counts):
    q = lambda s, *a: con.execute(s, a).fetchone()[0]
    import pyarrow.parquet as pq
    from . import ais
    ais_rows = sum(pq.ParquetFile(f).metadata.num_rows for f in glob.glob(os.path.join(ais.CA_DIR, "ais-ca-*.parquet")))
    px = json.load(open(os.path.join(ROOT, "eval", "psix_match_results.json")))
    ev = json.load(open(os.path.join(ROOT, "eval", "results.json")))
    hs = ev.get("hull_sample_2027.csv", {})
    multi = [g for g in groups.values() if len(g) > 1]
    return {
        "raw": [
            {"source": "ais", "label": "AIS position reports, California 2024-2025", "n": ais_rows},
            {"source": "usaspending", "label": "Navy contract records and modifications",
             "n": q("SELECT COUNT(*) FROM contract") + q("SELECT COUNT(*) FROM contract_action")},
            {"source": "mvus", "label": "Coast Guard register rows (2 editions)", "n": q("SELECT COUNT(*) FROM uscg_vessel")},
            {"source": "psix", "label": "Coast Guard PSIX lookups", "n": q("SELECT COUNT(*) FROM source_snapshot WHERE source='psix'")},
            {"source": "wikipedia", "label": "Wikipedia lists and ship articles", "n": q("SELECT COUNT(*) FROM source_snapshot WHERE source='wikipedia'")},
        ],
        "identifiers": q("SELECT COUNT(*) FROM identifier"),
        "records": q("SELECT COUNT(*) FROM vessel"),
        "links": q("SELECT COUNT(*) FROM edge WHERE rel IN ('SAME_AS','ABOUT_VESSEL')"),
        "links_asserted": q("SELECT COUNT(*) FROM edge WHERE rel IN ('SAME_AS','ABOUT_VESSEL') AND confidence >= ?", ASSERT),
        "links_held_back": q("SELECT COUNT(*) FROM edge WHERE rel IN ('SAME_AS','POSSIBLE_SAME_AS','ABOUT_VESSEL') AND confidence < ?", ASSERT),
        "entities": len(groups),
        "entities_multi_source": len(multi),
        "by_method": [dict(zip(["method", "rel", "n", "min_conf", "max_conf"], r)) | {"rule": RULES.get(r[0], r[0])}
                      for r in con.execute("SELECT method, rel, COUNT(*), MIN(confidence), MAX(confidence) FROM edge "
                                           "WHERE rel IN ('SAME_AS','POSSIBLE_SAME_AS','ABOUT_VESSEL') GROUP BY method, rel "
                                           "ORDER BY COUNT(*) DESC")],
        "accuracy": [
            {"test": "AIS to Coast Guard matches, 3 held-out review samples", "correct": px["correct"], "n": px["n"],
             "ci95": px["precision_ci95"], "recall": px.get("recall_same_as")},
            {"test": "Hull numbers read from contract text, held-out sample", "correct": hs.get("tp"),
             "n": (hs.get("tp") or 0) + (hs.get("fp") or 0), "ci95": hs.get("precision_ci95"), "recall": hs.get("recall")},
        ],
        "bridge": bridge_counts,
    }


def export(con, out, write):
    groups = components(con)
    psix_raw = _psix_raw()
    node_group = {n: r for r, ns in groups.items() for n in ns}
    # candidate entities: Navy hulls bridged to AIS, plus richly linked commercial vessels
    bridged = {node_group[s] for (s,) in con.execute(
        "SELECT src FROM edge WHERE rel='SAME_AS' AND src LIKE 'hull:%' AND confidence >= ?", (ASSERT,))}
    year = 2025
    hours = pd.read_parquet(os.path.join(DERIVED, f"vessel_hours_{year}.parquet"), columns=["mmsi", "hour", "lat", "lon", "sog"])
    hours["hour"] = pd.to_datetime(hours["hour"])
    hours_by = hours.groupby("mmsi").size()
    enc = pd.read_csv(os.path.join(DERIVED, f"encounters_{year}.csv"),
                      usecols=["region", "mmsi_a", "mmsi_b", "name_a", "name_b", "min_sep_obs_m", "cpa_pred_m",
                               "geometry", "service", "realized", "day"])
    enc_by = pd.concat([enc.mmsi_a, enc.mmsi_b]).value_counts()

    def score(root):
        ns = groups[root]
        kinds = {n.split(":")[0] for n in ns}
        mm = [int(n[5:]) for n in ns if n.startswith("mmsi:")]
        h = sum(int(hours_by.get(m, 0)) for m in mm)
        e = sum(int(enc_by.get(m, 0)) for m in mm)
        return len(kinds), h, e, mm

    picks = []
    for r in bridged:
        k, h, e, mm = score(r)
        if h:
            picks.append((r, "navy", k, h, e))
    by_group = {}
    for r, ns in groups.items():
        if r in bridged or not any(n.startswith("uscg:") for n in ns) or not any(n.startswith("psix:") for n in ns):
            continue
        k, h, e, mm = score(r)
        if h < 200 or e < 5:
            continue
        g = con.execute("SELECT hull_class FROM vessel WHERE vessel_id=?", (f"mmsi:{mm[0]}",)).fetchone()[0] if mm else "OTHER"
        by_group.setdefault(g, []).append((r, "commercial", k, h, e))
    quota = {"TUG_TOW": 6, "PASSENGER": 4, "CARGO": 3, "TANKER": 3, "FISHING": 3}
    for g, rows in by_group.items():
        rows.sort(key=lambda x: (x[2], math.log1p(x[4]) + math.log1p(x[3])), reverse=True)
        picks += rows[:quota.get(g, 2)]

    index = []
    from .export import slug
    for r, kind, k, h, e in picks:
        ns = groups[r]
        recs, contracts, weak = _records(con, ns, psix_raw)
        mm = [int(n[5:]) for n in ns if n.startswith("mmsi:")]
        wiki = next((x["fields"]["Name"] for x in recs if x["source"] == "wikipedia" and x["fields"].get("Name")), None)
        name = wiki or next((x["names_it_as"] for x in recs if x["source"] in ("ais", "mvus", "psix") and x["names_it_as"]), None)
        hull = next((x["fields"]["Hull"] for x in recs if x["source"] == "wikipedia"), None)
        group = con.execute("SELECT hull_class FROM vessel WHERE vessel_id=?", (f"mmsi:{mm[0]}",)).fetchone()[0] if mm else None
        s = slug(sorted(ns)[0] if kind == "commercial" else next(n for n in ns if n.startswith("hull:")))
        sources = [x for x in SOURCE if any(rec["source"] == x for rec in recs)]
        page = {"slug": s, "kind": kind, "name": name, "hull": hull, "group": group, "sources": sources,
                "nodes": sorted(ns), "records": recs, "held_back": weak,
                "contracts": {"n": len(contracts), "total": round(sum(c["amount"] or 0 for c in contracts)),
                              "list": contracts[:12]},
                "track": _track(hours, mm), "track_year": year,
                "encounters": _encounters(enc, mm), "vessel_page": slug(next((n for n in ns if n.startswith("mmsi:")), ns[0]))}
        write(os.path.join(out, "trace", s + ".json"), page)
        index.append({"slug": s, "kind": kind, "name": name, "hull": hull, "group": group, "sources": sources,
                      "n_sources": len(sources), "hours": h, "alerts": e, "contracts": len(contracts)})
    index.sort(key=lambda x: (x["n_sources"], x["contracts"] > 0, x["alerts"]), reverse=True)
    from . import bridge
    bc = {}
    if os.path.exists(bridge.RESULTS):
        bc = json.load(open(bridge.RESULTS))
        bc["linked_hulls"] = len(bridged)
        rows = con.execute("SELECT method, COUNT(*), SUM(evidence LIKE '%call_sign agrees%') FROM edge "
                           "WHERE src LIKE 'hull:%' AND rel='SAME_AS' GROUP BY method").fetchall()
        bc["by_method"] = {m: n for m, n, _ in rows}
        bc["call_sign_agrees"] = int(sum(a or 0 for _, _, a in rows))
        bc["links"] = int(sum(n for _, n, _ in rows))
    write(os.path.join(out, "traces.json"), {"funnel": funnel(con, groups, bc), "vessels": index,
                                             "sources": SOURCE})
    return {"showcase": len(index), "entities": len(groups)}


def register(path=os.path.join(ROOT, "docs", "data-sources.md")):
    """The data-source register (docs/data-sources.md) as JSON, so the site never drifts from it."""
    import re
    text = open(path, encoding="utf-8").read()
    rows, head = [], None
    for line in text.splitlines():
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if head is None:
            head = cells
            continue
        if set(line) <= set("|-: "):
            continue
        rows.append(dict(zip(head, [re.sub(r"\*\*|`", "", c) for c in cells])))
    opens = re.search(r"## Open items and judgement calls\n(.*)", text, re.S)
    items = re.findall(r"^\d+\. (.+?)(?=^\d+\. |\Z)", opens.group(1), re.S | re.M) if opens else []
    return {"sources": rows, "open_items": [re.sub(r"\s+", " ", re.sub(r"\*\*|`", "", i)).strip() for i in items],
            "reviewed": (re.search(r"Last reviewed ([0-9-]+)", text) or [None, None])[1]}
