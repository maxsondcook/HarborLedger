"""Bridge the two halves of the graph: Navy hulls named in contracts  <->  ships seen on AIS.

Contracts name hulls ("T-AO-194"); AIS knows MMSI, IMO and call sign. Neither carries the other's ID,
and project rules forbid matching on names alone. Each ship's Wikipedia article infobox lists its
IMO and MMSI numbers, so a hull is linked to an AIS vessel only when those stable IDs equal the AIS
record's:

  both IMO and MMSI agree with one AIS vessel  -> SAME_AS, confidence 0.98 (wikipedia_imo_mmsi)
  only one of them is listed and agrees        -> SAME_AS, confidence 0.95 (wikipedia_imo / _mmsi)
  the two IDs point at different AIS vessels   -> no link, counted as a conflict
  a call sign alone is never enough            -> it is reported as evidence, not used to link

Articles are fetched once (1 request/s, project user-agent) and cached under
data/raw/wikipedia/articles/, with each file recorded in the manifest.
"""
import json
import os
import re
import time
import urllib.parse
import urllib.request

from .snapshot import LICENSES, RAW, ROOT, USER_AGENT, record

ART_DIR = os.path.join(RAW, "wikipedia", "articles")
LIST_DIR = os.path.join(RAW, "wikipedia")
API = "https://en.wikipedia.org/w/api.php"
RESULTS = os.path.join(ROOT, "eval", "bridge_results.json")

TEMPLATE = re.compile(r"\{\{\s*(USS|USNS)\s*\|\s*([^|}]+?)\s*\|\s*((?:T-)?([A-Z]+)-(\d+))")


def list_titles(wikitext):
    """(normalized hull, article title) for every {{USS|Name|HULL}} / {{USNS|...}} template."""
    out = []
    for m in TEMPLATE.finditer(wikitext):
        prefix, name, raw, cls, num = m.groups()
        out.append((f"{cls}-{int(num)}", f"{prefix} {name.strip()} ({raw})"))
    return out


def _identification(wikitext):
    m = re.search(r"\|\s*identification\s*=(.*?)(?=\n\s*\|\s*[a-z_]+\s*=|\n\}\})", wikitext, re.S | re.I)
    return m.group(1) if m else ""


def parse_ids(wikitext):
    """IMO, MMSI and call sign from the infobox identification field only."""
    f = _identification(wikitext)
    ids = {}
    if m := re.search(r"IMO\s*Number\s*\|\s*(\d{7})", f, re.I) or re.search(r"\bIMO[:\s]+(\d{7})\b", f):
        ids["imo"] = m.group(1)
    if m := re.search(r"MMSI\s*Number\s*\|\s*(\d{9})", f, re.I) or re.search(r"\bMMSI[:\s]+(\d{9})\b", f):
        ids["mmsi"] = m.group(1)
    if m := re.search(r"call\s*sign[^:\n]*:\s*([A-Z0-9]{3,7})\b", f, re.I):
        ids["call_sign"] = m.group(1).upper()
    return ids


def decide(ids, ais_rows):
    """ais_rows: iterable of (vessel_id, mmsi, imo, call_sign). Returns the link decision."""
    by_mmsi = {r[0] for r in ais_rows if ids.get("mmsi") and r[1] == ids["mmsi"]}
    by_imo = {r[0] for r in ais_rows if ids.get("imo") and r[2] == ids["imo"]}
    if not (ids.get("imo") or ids.get("mmsi")):
        return {"status": "no_ids", "dst": []}
    if ids.get("imo") and ids.get("mmsi") and by_mmsi and by_imo:
        if by_mmsi & by_imo:
            return {"status": "linked", "dst": sorted(by_mmsi & by_imo), "method": "wikipedia_imo_mmsi", "confidence": 0.98}
        return {"status": "conflict", "dst": []}
    if by_imo and not (ids.get("mmsi") and by_mmsi):
        return {"status": "linked", "dst": sorted(by_imo), "method": "wikipedia_imo", "confidence": 0.95}
    if by_mmsi:
        return {"status": "linked", "dst": sorted(by_mmsi), "method": "wikipedia_mmsi", "confidence": 0.95}
    return {"status": "not_in_ais", "dst": []}


def _article_path(hull):
    return os.path.join(ART_DIR, f"{hull}.json")


def titles_for_contract_hulls(con):
    hulls = {r[0][5:] for r in con.execute(
        "SELECT DISTINCT dst FROM edge WHERE rel='ABOUT_VESSEL' AND confidence >= 0.5")}
    out = {}
    for f in sorted(os.listdir(LIST_DIR)):
        if f.endswith(".json"):
            p = json.load(open(os.path.join(LIST_DIR, f)))["parse"]
            w = p["wikitext"] if isinstance(p["wikitext"], str) else p["wikitext"]["*"]
            for hull, title in list_titles(w):
                if hull in hulls:
                    out.setdefault(hull, title)
    return out


def fetch(con, log=print, delay=1.0):
    os.makedirs(ART_DIR, exist_ok=True)
    todo = titles_for_contract_hulls(con)
    got = 0
    for hull, title in sorted(todo.items()):
        path = _article_path(hull)
        if os.path.exists(path):
            continue
        q = {"action": "parse", "prop": "wikitext", "format": "json", "formatversion": "2",
             "redirects": "1", "page": title}
        url = API + "?" + urllib.parse.urlencode(q)
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                body = json.load(r)
        except Exception as e:  # noqa: BLE001 - logged and skipped; rerun picks it up
            log(f"  {hull}: {e}")
            time.sleep(delay)
            continue
        if "parse" not in body:
            body = {"missing": title}
        with open(path, "w") as f:
            json.dump(body, f)
        record(path, "wikipedia", API, {"page": title, "hull": hull})
        got += 1
        time.sleep(delay)
    log(f"articles: {len(todo)} hulls with list entries, {got} fetched now")
    return todo


def link(con, log=print):
    """Add hull -> mmsi SAME_AS edges from cached articles. Called by build()."""
    if not os.path.isdir(ART_DIR):
        return {}
    ais = {}
    for vid, scheme, value in con.execute(
            "SELECT vessel_id, scheme, value FROM identifier WHERE vessel_id LIKE 'mmsi:%' "
            "AND scheme IN ('mmsi','imo','call_sign')"):
        ais.setdefault(vid, {})[scheme] = value
    rows = [(v, d.get("mmsi"), d.get("imo"), d.get("call_sign")) for v, d in ais.items()]
    hull_ids = {r[0] for r in con.execute("SELECT vessel_id FROM vessel WHERE vessel_id LIKE 'hull:%'")}
    counts = {}
    cur = con.cursor()
    for f in sorted(os.listdir(ART_DIR)):
        hull = f[:-5]
        vid = f"hull:{hull}"
        body = json.load(open(os.path.join(ART_DIR, f)))
        if vid not in hull_ids or "parse" not in body:
            counts["no_article"] = counts.get("no_article", 0) + 1
            continue
        p = body["parse"]
        w = p["wikitext"] if isinstance(p["wikitext"], str) else p["wikitext"]["*"]
        ids = parse_ids(w)
        d = decide(ids, rows)
        counts[d["status"]] = counts.get(d["status"], 0) + 1
        for dst in d["dst"]:
            a = ais[dst]
            cs = "agrees" if ids.get("call_sign") and ids["call_sign"] == (a.get("call_sign") or "").upper() else "n/a"
            ev = (f"article='{p.get('title')}' infobox imo={ids.get('imo', '-')} mmsi={ids.get('mmsi', '-')}; "
                  f"ais imo={a.get('imo', '-')} mmsi={a.get('mmsi', '-')}; call_sign {cs}")
            cur.execute("INSERT INTO edge VALUES (?,?,?,?,?,?,?,?,?,?)", (
                vid, "SAME_AS", dst, d["confidence"], d["method"],
                os.path.relpath(os.path.join(ART_DIR, f), ROOT),
                None, None, LICENSES["wikipedia"], ev))
    con.commit()
    with open(RESULTS, "w") as fh:
        json.dump({"articles": len(os.listdir(ART_DIR)), "outcomes": counts}, fh, indent=1)
    log(f"navy-ais bridge: {counts}")
    return counts
