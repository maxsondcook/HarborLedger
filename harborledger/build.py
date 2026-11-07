"""Build data/harborledger.sqlite from raw snapshots and curated tables.

The build is deterministic given the manifest and curated CSVs: rerunning it after more
transaction files arrive simply picks them up."""
import collections
import csv
import json
import os

from . import db, hulls
from .snapshot import LICENSES, ROOT, read_manifest

CURATED = os.path.join(ROOT, "curated")
LIC_USA = LICENSES["usaspending"]
LIC_CUR = LICENSES["curated"]
LIC_DER = LICENSES["derived"]


def _csv(name):
    with open(os.path.join(CURATED, name), newline="") as f:
        return list(csv.DictReader(f))


def build_gazetteer(descriptions):
    g = hulls.Gazetteer()
    raw = os.path.join(ROOT, "data", "raw", "wikipedia")
    for fn in ("wp_current.json", "wp_msc.json"):
        p = os.path.join(raw, fn)
        if os.path.exists(p):
            g.load_wikipedia(p)
    extra = os.path.join(CURATED, "hull_gazetteer_extra.csv")
    if os.path.exists(extra):
        for r in _csv("hull_gazetteer_extra.csv"):
            g.add(r["name"], r["hull"], "curated")
    g.mine(descriptions)
    return g


def build(verbose=True):
    con = db.connect(fresh=True)
    cur = con.cursor()
    manifest = read_manifest()
    snap_ids = {}
    for i, m in enumerate(manifest, 1):
        if m["path"] in snap_ids:   # a re-pull: keep the latest row for that path
            continue
        cur.execute("INSERT INTO source_snapshot VALUES (?,?,?,?,?,?,?,?)",
                    (i, m["path"], m["source"], m["endpoint"], json.dumps(m["params"]),
                     m["fetched_at"], m["sha256"], m["license"]))
        snap_ids[m["path"]] = i

    # ---- contracts -------------------------------------------------------------
    award_snaps = [m for m in manifest if m["endpoint"] == "/search/spending_by_award/"]
    awards = {}
    for m in award_snaps:
        for a in json.load(open(os.path.join(ROOT, m["path"]))):
            gid = a.get("generated_internal_id")
            if gid:
                awards[gid] = (a, snap_ids[m["path"]])
    descs = [a.get("Description") or "" for a, _ in awards.values()]
    gaz = build_gazetteer(descs)

    for gid, (a, sid) in awards.items():
        d = a.get("Description") or ""
        cur.execute("INSERT INTO contract VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
            gid, a.get("Award ID"), (a.get("Award ID") or "")[:6], d,
            a.get("Recipient UEI"), a.get("Recipient Name"),
            (a.get("NAICS") or {}).get("code"), (a.get("PSC") or {}).get("code"),
            a.get("Place of Performance State Code"), a.get("Start Date"), a.get("End Date"),
            a.get("Award Amount"), a.get("Last Modified Date"),
            hulls.extract_fy(d), hulls.extract_avail(d), sid))

    # ---- contract actions (transactions) ----------------------------------------
    n_txn_files = 0
    for m in manifest:
        if m["endpoint"] != "/transactions/":
            continue
        gid = m["params"]["award_id"]
        p = os.path.join(ROOT, m["path"])
        if gid not in awards or not os.path.exists(p):
            continue
        rows = json.load(open(p))["results"]
        cur.execute("DELETE FROM contract_action WHERE contract_id=?", (gid,))
        for seq, t in enumerate(rows):
            cur.execute("INSERT INTO contract_action VALUES (?,?,?,?,?,?,?,?,?)", (
                gid, seq, t.get("action_date"), t.get("modification_number"),
                t.get("action_type"), t.get("action_type_description"),
                t.get("federal_action_obligation"), t.get("description"), snap_ids[m["path"]]))
        n_txn_files += 1

    # ---- organizations ---------------------------------------------------------
    firms = {r["firm_id"]: r for r in _csv("firms.csv")}
    for fid, r in firms.items():
        cur.execute("INSERT INTO organization VALUES (?,?,?,?)",
                    (f"firm:{fid}", r["kind"], r["firm_name"], r["notes"]))
    names = collections.defaultdict(collections.Counter)
    for a, _ in awards.values():
        if a.get("Recipient UEI"):
            names[a["Recipient UEI"]][a.get("Recipient Name") or ""] += 1
    for uei, c in names.items():
        cur.execute("INSERT INTO organization VALUES (?,?,?,?)",
                    (f"uei:{uei}", "legal_entity", c.most_common(1)[0][0], None))
        for n, k in c.items():
            cur.execute("INSERT INTO org_name_variant VALUES (?,?,?)", (f"uei:{uei}", n, k))

    for r in _csv("recipient_firm.csv"):
        if r["firm_id"] not in firms:
            raise ValueError(f"recipient_firm.csv references unknown firm {r['firm_id']}")
        cur.execute("INSERT INTO edge VALUES (?,?,?,?,?,?,?,?,?,?)", (
            f"uei:{r['recipient_uei']}", "PART_OF", f"firm:{r['firm_id']}", 1.0, "curated",
            "curated/recipient_firm.csv", None, None, LIC_CUR, r["note"]))
    for r in _csv("firm_parent.csv"):
        for k in ("child_firm", "parent_firm"):
            if r[k] not in firms:
                raise ValueError(f"firm_parent.csv references unknown firm {r[k]}")
        cur.execute("INSERT INTO edge VALUES (?,?,?,?,?,?,?,?,?,?)", (
            f"firm:{r['child_firm']}", "PART_OF", f"firm:{r['parent_firm']}",
            float(r["confidence"]), "curated", r["source"], r["valid_from"] or None,
            r["valid_to"] or None, LIC_CUR, None))

    # ---- contract -> recipient, contract -> vessel -----------------------------
    vessels = {}
    for gid, (a, sid) in awards.items():
        if a.get("Recipient UEI"):
            cur.execute("INSERT INTO edge VALUES (?,?,?,?,?,?,?,?,?,?)", (
                f"contract:{gid}", "AWARDED_TO", f"uei:{a['Recipient UEI']}", 1.0, "source_field",
                f"snapshot:{sid}", a.get("Start Date"), a.get("End Date"), LIC_USA, None))
        for r in hulls.resolve(a.get("Description") or "", gaz):
            h = r["hull"]
            vessels.setdefault(h, gaz.by_hull.get(h))
            cur.execute("INSERT INTO edge VALUES (?,?,?,?,?,?,?,?,?,?)", (
                f"contract:{gid}", "ABOUT_VESSEL", f"hull:{h}", r["confidence"], r["method"],
                f"snapshot:{sid}", None, None, LIC_DER, r["evidence"]))

    for h, name in vessels.items():
        src = None
        if name:
            hit = gaz.by_name.get(name, {}).get(h)
            src = hit[0] if hit else None
        cur.execute("INSERT INTO vessel VALUES (?,?,?,?,?)",
                    (f"hull:{h}", name, h, h.split("-")[0], src))
        cur.execute("INSERT INTO identifier VALUES (?,?,?,?,?,?,?)",
                    (f"hull:{h}", "navy_hull", h, None, None, "derived", LIC_DER))
        if name:
            cur.execute("INSERT INTO identifier VALUES (?,?,?,?,?,?,?)", (
                f"hull:{h}", "ship_name", name, None, None, src,
                LICENSES["wikipedia"] if src == "wikipedia" else LIC_DER))

    con.commit()
    n_mar = build_maritime(con)
    con.commit()
    n_reg = build_registry(con)
    con.commit()
    if verbose:
        print("maritime layer:", n_mar)
        print("registry layer:", n_reg)
        q = lambda s: con.execute(s).fetchone()[0]
        print(f"contracts={q('SELECT COUNT(*) FROM contract')} "
              f"with_actions={n_txn_files} actions={q('SELECT COUNT(*) FROM contract_action')} "
              f"orgs={q('SELECT COUNT(*) FROM organization')} vessels={q('SELECT COUNT(*) FROM vessel')} "
              f"edges={q('SELECT COUNT(*) FROM edge')} db={db.DB_PATH}")
    con.close()


# ---- week 5: commercial vessel layer (AIS + PSIX + tug activity) -------------------
DERIVED = os.path.join(ROOT, "data", "derived")


def _ais_group(t):
    t = int(t)
    if t in (31, 32, 52):
        return "TUG_TOW"
    if 60 <= t <= 69:
        return "PASSENGER"
    if 70 <= t <= 79:
        return "CARGO"
    if 80 <= t <= 89:
        return "TANKER"
    if t == 30:
        return "FISHING"
    return "OTHER"


def build_maritime(con):
    """Adds AIS vessels (mmsi:), PSIX vessels (psix:), SAME_AS edges and tug ACTIVE_IN edges.
    Skipped quietly if the derived files have not been produced yet."""
    import pandas as pd
    from . import activity
    cur = con.cursor()
    cur.execute("CREATE TABLE IF NOT EXISTS facility (facility_id TEXT PRIMARY KEY, name TEXT, "
                "kind TEXT, lat_min REAL, lat_max REAL, lon_min REAL, lon_max REAL)")
    for k, (a, b, c, d) in activity.REGIONS.items():
        cur.execute("INSERT OR REPLACE INTO facility VALUES (?,?,?,?,?,?,?)",
                    (f"area:{k}", k.replace("_", " ").title(), "port_area", a, b, c, d))
    stats = {}
    mpath = os.path.join(DERIVED, "psix_matches.csv")
    if os.path.exists(mpath):
        m = pd.read_csv(mpath, dtype={"call_sign": str, "imo": str, "psix_id": str, "psix_ident": str})
        lic_ais, lic_psix = LICENSES["marinecadastre"], LICENSES["psix"]
        for r in m.to_dict("records"):
            vid = f"mmsi:{r['mmsi']}"
            cur.execute("INSERT OR IGNORE INTO vessel VALUES (?,?,?,?,?)",
                        (vid, r.get("ais_name"), None, _ais_group(r["vessel_type"]), "marinecadastre"))
            for scheme, val in (("mmsi", str(r["mmsi"])), ("imo", r.get("imo")),
                                ("call_sign", r.get("call_sign")), ("ais_name", r.get("ais_name"))):
                if isinstance(val, str) and val and val.lower() != "nan":
                    cur.execute("INSERT INTO identifier VALUES (?,?,?,?,?,?,?)",
                                (vid, scheme, val, r["first_day"], r["last_day"], "marinecadastre", lic_ais))
            if isinstance(r.get("rel"), str) and r["rel"]:
                pid = f"psix:{r['psix_id']}"
                cur.execute("INSERT OR IGNORE INTO vessel VALUES (?,?,?,?,?)",
                            (pid, r.get("psix_name"), None, r.get("psix_service"), "psix"))
                cur.execute("INSERT INTO identifier VALUES (?,?,?,?,?,?,?)",
                            (pid, "psix_vessel_id", str(r["psix_id"]), None, None, "psix", lic_psix))
                if isinstance(r.get("psix_ident"), str):
                    cur.execute("INSERT INTO identifier VALUES (?,?,?,?,?,?,?)",
                                (pid, "uscg_identification", r["psix_ident"], None, None, "psix", lic_psix))
                cur.execute("INSERT INTO edge VALUES (?,?,?,?,?,?,?,?,?,?)", (
                    vid, r["rel"], pid, float(r["confidence"]), r["method"], "data/derived/psix_matches.csv",
                    r["first_day"], r["last_day"], LIC_DER,
                    f"ais='{r.get('ais_name')}' psix='{r.get('psix_name')}' ratio={r.get('name_ratio')} "
                    f"imo_agree={r.get('imo_agree')}"))
        stats["ais_vessels"] = int(len(m))
        stats["same_as"] = int((m.rel == "SAME_AS").sum())
        stats["possible_same_as"] = int((m.rel == "POSSIBLE_SAME_AS").sum())
    apath = os.path.join(DERIVED, "tug_activity_full.csv")
    if os.path.exists(apath):
        a = pd.read_csv(apath)
        n = 0
        for r in a.to_dict("records"):
            for reg in activity.REGIONS:
                cols = [c for c in a.columns if c.startswith(reg + "|")]
                h = sum(r[c] for c in cols)
                act = sum(r[c] for c in cols if c.split("|")[1] != "idle")
                if h > 0:
                    cur.execute("INSERT INTO edge VALUES (?,?,?,?,?,?,?,?,?,?)", (
                        f"mmsi:{r['mmsi']}", "ACTIVE_IN", f"area:{reg}", 1.0, "ais_activity_hours",
                        "data/derived/tug_activity_full.csv", None, None, LICENSES["marinecadastre"],
                        f"observed_h={h:.1f} active_h={act:.1f} days={r['days_seen']}"))
                    n += 1
        stats["tug_active_in_edges"] = n
    return stats


# ---- week 6 (site week 1): USCG register (MVUS) -> coastwise flags ----------------------
def build_registry(con, edition="Jul24"):
    """Load MVUS editions and link vessels to them.
    psix:ID -> uscg:<official_number>  when PSIX's identification equals the official number
    mmsi:X  -> uscg:<official_number>  for AIS vessels with no PSIX link, by call sign with a
                                       name-similarity gate (same rule as the PSIX match)."""
    import difflib
    from . import mvus, psix as px
    if not mvus.editions():
        return {}
    mvus.register_snapshots()
    loaded = mvus.load(con)
    cur = con.cursor()
    lic = LICENSES["uscg_mvus"]
    by_on = {r["official_number"]: dict(r) for r in con.execute(
        "SELECT * FROM uscg_vessel WHERE edition=? AND official_number<>''", (edition,))}
    by_cs = {}
    for r in con.execute("SELECT * FROM uscg_vessel WHERE edition=? AND call_sign<>''", (edition,)):
        by_cs.setdefault(r["call_sign"].upper(), []).append(dict(r))

    def add_node(r):
        vid = f"uscg:{r['official_number']}"
        cur.execute("INSERT OR IGNORE INTO vessel VALUES (?,?,?,?,?)",
                    (vid, r["vessel_name"], None, r["service"], f"uscg_mvus_{edition}"))
        return vid

    n_psix = n_cs = 0
    for r in con.execute("SELECT v.vessel_id, i.value FROM vessel v JOIN identifier i "
                         "ON i.vessel_id=v.vessel_id AND i.scheme='uscg_identification' "
                         "WHERE v.vessel_id LIKE 'psix:%'").fetchall():
        rec = by_on.get(r["value"])
        if rec:
            cur.execute("INSERT INTO edge VALUES (?,?,?,?,?,?,?,?,?,?)", (
                r["vessel_id"], "SAME_AS", add_node(rec), 0.99, "official_number",
                f"mvus:{edition}", None, None, LIC_DER, f"official_number={r['value']}"))
            n_psix += 1
    linked = {r[0] for r in con.execute("SELECT src FROM edge WHERE rel='SAME_AS' AND src LIKE 'mmsi:%'")}
    for r in con.execute("SELECT v.vessel_id, v.name, i.value AS cs FROM vessel v JOIN identifier i "
                         "ON i.vessel_id=v.vessel_id AND i.scheme='call_sign' "
                         "WHERE v.vessel_id LIKE 'mmsi:%'").fetchall():
        if r["vessel_id"] in linked:
            continue
        cands = by_cs.get((r["cs"] or "").upper(), [])
        best, ratio = None, 0.0
        for c in cands:
            q = difflib.SequenceMatcher(None, px.norm_name(r["name"]), px.norm_name(c["vessel_name"])).ratio()
            if q > ratio:
                best, ratio = c, q
        if best and ratio >= px.NAME_GATE:
            cur.execute("INSERT INTO edge VALUES (?,?,?,?,?,?,?,?,?,?)", (
                r["vessel_id"], "SAME_AS", add_node(best), round(0.85 + 0.12 * ratio, 3),
                "callsign_gated_mvus", f"mvus:{edition}", None, None, LIC_DER,
                f"ais='{r['name']}' mvus='{best['vessel_name']}' ratio={ratio:.2f}"))
            n_cs += 1
    cur.executescript(f"""
    DROP VIEW IF EXISTS v_vessel_profile;
    CREATE VIEW v_vessel_profile AS
    WITH m AS (SELECT vessel_id AS mmsi_node, name AS ais_name, hull_class AS ais_group
               FROM vessel WHERE vessel_id LIKE 'mmsi:%'),
         p AS (SELECT src, dst AS psix_node FROM edge WHERE rel='SAME_AS' AND dst LIKE 'psix:%'),
         u1 AS (SELECT src, dst AS uscg_node FROM edge WHERE rel='SAME_AS' AND dst LIKE 'uscg:%')
    SELECT m.mmsi_node, m.ais_name, m.ais_group, p.psix_node,
           COALESCE(ua.uscg_node, ub.uscg_node) AS uscg_node,
           r.service, r.flag, r.coastwise_unrestricted, r.coastwise_any, r.registry, r.fishery,
           r.builder, r.build_year, r.complete_build_country, r.org_name AS owner_org,
           r.gross_ton, r.length, r.cod_status
    FROM m LEFT JOIN p ON p.src = m.mmsi_node
           LEFT JOIN u1 ua ON ua.src = p.psix_node
           LEFT JOIN u1 ub ON ub.src = m.mmsi_node
           LEFT JOIN uscg_vessel r ON r.edition = '{edition}'
                AND 'uscg:' || r.official_number = COALESCE(ua.uscg_node, ub.uscg_node);
    """)
    return {"loaded": loaded, "psix_to_uscg": n_psix, "ais_to_uscg_by_callsign": n_cs}
