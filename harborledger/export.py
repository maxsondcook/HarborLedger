"""Export the SQLite graph to static JSON for the website (site/public/data/).

Files:
  meta.json                 build info, counts, sources and licences
  vessels.json              index of every vessel page (AIS vessels and Navy hulls)
  vessels/<slug>.json       one page per vessel: identifiers, links with evidence, contracts, activity
  yards.json                index of curated firms with Navy repair/construction dollars
  yards/<firm>.json         one page per firm: parents (dated), legal entities, contracts, availabilities
  ledger.json               the availability cost-growth ledger
  growth_model.json         weeks 3-4 model results (copied from eval/)
  years.json                AIS years available; per-year files carry a _YYYY suffix:
  activity_YYYY.json        tug activity summary (+ activity_tugs_YYYY, activity_monthly_YYYY)
  encounters_YYYY.json      encounter summary (+ encounter_daily_YYYY, encounter_scenarios_YYYY,
                            encounter_validation_YYYY; scenario tracks in encounters/<id>.json)

Publication rules: only sources whose licence permits redistribution (see CLAUDE.md); owner
names only for organizations (the USCG register already redacts individuals).
"""
import json
import os
import re
import shutil
import time

from . import db
from .snapshot import ROOT, read_manifest

OUT = os.path.join(ROOT, "site", "public", "data")


def slug(node_id):
    return re.sub(r"[^A-Za-z0-9_-]+", "-", node_id.replace(":", "-")).strip("-")


def _w(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(obj, f, separators=(",", ":"), default=str)


def _r(x, n=4):
    return None if x is None else round(float(x), n)


def export(out=OUT):
    if os.path.exists(out):
        shutil.rmtree(out)
    con = db.connect()
    q = lambda s, *a: [dict(r) for r in con.execute(s, a).fetchall()]
    has = lambda t: bool(q("SELECT name FROM sqlite_master WHERE name=?", t))

    # ---------- vessels: AIS (mmsi) ----------
    index = []
    prof = {r["mmsi_node"]: r for r in q("SELECT * FROM v_vessel_profile")} if has("v_vessel_profile") else {}
    for v in q("SELECT * FROM vessel WHERE vessel_id LIKE 'mmsi:%'"):
        vid = v["vessel_id"]
        p = prof.get(vid, {})
        ids = q("SELECT scheme, value, valid_from, valid_to, source, license FROM identifier WHERE vessel_id=?", vid)
        links = q("SELECT rel, dst, confidence, method, evidence, license FROM edge WHERE src=? "
                  "AND rel IN ('SAME_AS','POSSIBLE_SAME_AS')", vid)
        for l in links:   # second hop: psix -> uscg
            if l["dst"].startswith("psix:"):
                links += [dict(x, via=l["dst"]) for x in q(
                    "SELECT rel, dst, confidence, method, evidence, license FROM edge WHERE src=? AND rel='SAME_AS'",
                    l["dst"])]
        act = q("SELECT dst, evidence FROM edge WHERE src=? AND rel='ACTIVE_IN'", vid)
        mmsi = vid.split(":")[1]
        page = {
            "id": vid, "slug": slug(vid), "kind": "ais", "name": v["name"], "group": v["hull_class"],
            "flag": "US" if mmsi[:3] in ("338", "366", "367", "368", "369") else "foreign",
            "identifiers": ids, "links": links, "active_in": act,
            "register": {k: p.get(k) for k in ("service", "coastwise_unrestricted", "coastwise_any",
                                                "registry", "fishery", "builder", "build_year",
                                                "complete_build_country", "owner_org", "gross_ton",
                                                "length", "cod_status")} if p.get("uscg_node") else None,
        }
        _w(os.path.join(out, "vessels", page["slug"] + ".json"), page)
        best = max((l["confidence"] for l in links if l["rel"] == "SAME_AS"), default=None)
        index.append({"slug": page["slug"], "kind": "ais", "name": v["name"], "group": v["hull_class"],
                      "flag": page["flag"], "coastwise": (p.get("coastwise_any") == 1) if p else None,
                      "linked": best is not None, "conf": best})

    # ---------- vessels: Navy hulls ----------
    for v in q("SELECT * FROM vessel WHERE vessel_id LIKE 'hull:%'"):
        vid = v["vessel_id"]
        cons = q("""SELECT c.contract_id, c.piid, c.description, c.recipient_name, c.start_date, c.end_date,
                           c.award_amount, c.avail_type, c.fy_text, e.confidence, e.method, e.evidence,
                           (SELECT dst FROM edge f WHERE f.src='uei:'||c.recipient_uei AND f.rel='PART_OF' LIMIT 1) AS firm,
                           (SELECT COUNT(*) FROM edge g WHERE g.src=e.src AND g.rel='ABOUT_VESSEL'
                                   AND g.confidence >= 0.5) AS n_hulls
                    FROM edge e JOIN contract c ON 'contract:'||c.contract_id = e.src
                    WHERE e.rel='ABOUT_VESSEL' AND e.dst=? ORDER BY c.start_date""", vid)
        avails = q("SELECT piid, avail_type, firm, first_action, pop_end, closed, base, options, total, "
                   "g_exopt, n_mods, delay_flag FROM availability WHERE hull=? ORDER BY first_action",
                   v["hull"]) if has("availability") else []
        page = {"id": vid, "slug": slug(vid), "kind": "navy", "name": v["name"], "hull": v["hull"],
                "hull_class": v["hull_class"], "name_source": v["name_source"],
                "contracts": [dict(c, firm=(c["firm"] or "")[5:] or None,
                                   award_amount=_r(c["award_amount"], 0)) for c in cons],
                "availabilities": [dict(a, g_exopt=_r(a["g_exopt"])) for a in avails]}
        _w(os.path.join(out, "vessels", page["slug"] + ".json"), page)
        asserted = [c for c in cons if c["confidence"] >= 0.5]
        index.append({"slug": page["slug"], "kind": "navy", "name": v["name"], "hull": v["hull"],
                      "group": v["hull_class"], "n_contracts": len(asserted),
                      # multi-ship awards are split equally across the hulls they name (labelled on the site)
                      "dollars_allocated": _r(sum((c["award_amount"] or 0) / max(c["n_hulls"], 1)
                                                  for c in asserted), 0)})
    _w(os.path.join(out, "vessels.json"), index)

    # ---------- yards / firms ----------
    firms = q("SELECT org_id, kind, name, notes FROM organization WHERE org_id LIKE 'firm:%'")
    yidx = []
    for f in firms:
        fid = f["org_id"][5:]
        ueis = q("SELECT src FROM edge WHERE rel='PART_OF' AND dst=? AND src LIKE 'uei:%'", f["org_id"])
        uei_list = [u["src"][4:] for u in ueis]
        parents = q("SELECT dst, valid_from, valid_to, confidence, method, source_ref FROM edge "
                    "WHERE rel='PART_OF' AND src=? AND dst LIKE 'firm:%'", f["org_id"])
        children = q("SELECT src FROM edge WHERE rel='PART_OF' AND dst=? AND src LIKE 'firm:%'", f["org_id"])
        cons = []
        if uei_list:
            ph = ",".join("?" * len(uei_list))
            cons = q(f"SELECT contract_id, piid, description, recipient_name, recipient_uei, start_date, "
                     f"end_date, award_amount, psc, pop_state, avail_type FROM contract "
                     f"WHERE recipient_uei IN ({ph}) ORDER BY award_amount DESC", *uei_list)
        av = q("SELECT piid, hull, avail_type, first_action, closed, g_exopt FROM availability WHERE firm=? "
               "ORDER BY first_action", fid) if has("availability") else []
        closed = sorted(a["g_exopt"] for a in av if a["closed"] and a["g_exopt"] is not None)
        med = closed[len(closed) // 2] if closed else None
        dollars = sum(c["award_amount"] or 0 for c in cons)
        repair = sum(c["award_amount"] or 0 for c in cons if (c["psc"] or "").startswith("J"))
        page = {"id": f["org_id"], "slug": fid, "name": f["name"], "kind": f["kind"], "notes": f["notes"],
                "legal_entities": [{"uei": u, "names": [n["name"] for n in q(
                    "SELECT name FROM org_name_variant WHERE org_id=?", "uei:" + u)]} for u in uei_list],
                "parents": [dict(p, dst=p["dst"][5:]) for p in parents],
                "children": [c["src"][5:] for c in children],
                "contracts": [dict(c, award_amount=_r(c["award_amount"], 0)) for c in cons[:300]],
                "n_contracts": len(cons), "dollars": _r(dollars, 0), "repair_dollars": _r(repair, 0),
                "availabilities": [dict(a, g_exopt=_r(a["g_exopt"])) for a in av],
                "median_growth_closed": _r(med)}
        _w(os.path.join(out, "yards", fid + ".json"), page)
        yidx.append({"slug": fid, "name": f["name"], "kind": f["kind"], "n_contracts": len(cons),
                     "dollars": _r(dollars, 0), "repair_dollars": _r(repair, 0), "n_avail": len(av),
                     "median_growth_closed": _r(med)})
    _w(os.path.join(out, "yards.json"), sorted(yidx, key=lambda y: -(y["dollars"] or 0)))

    # ---------- ledger, model, activity ----------
    if has("availability"):
        led = q("SELECT contract_id, piid, hull, hull_class, avail_type, firm, recipient_name, pop_state, "
                "office, first_action, last_action, start_fy, pop_end, closed, base, options, total, g_total, "
                "g_exopt, g_exopt_noC, n_mods, n_growth_kw, n_delay_kw, n_penalty_kw, delay_flag FROM availability")
        for r in led:
            for k in ("base", "options", "total"):
                r[k] = _r(r[k], 0)
            for k in ("g_total", "g_exopt", "g_exopt_noC"):
                r[k] = _r(r[k])
            r["hull_slug"] = slug("hull:" + r["hull"])
        _w(os.path.join(out, "ledger.json"), led)
    for src, dst in (("growth_model_results.json", "growth_model.json"),
                     ("psix_match_results.json", "psix_match.json"),
                     ("results.json", "identity_tests.json")):
        p = os.path.join(ROOT, "eval", src)
        if os.path.exists(p):
            shutil.copy(p, os.path.join(out, dst))

    # ---------- per-year AIS products (activity, encounters) ----------
    import glob as _glob
    import pandas as pd
    from .years import by_year
    years = sorted({int(os.path.splitext(f)[0].rsplit("_", 1)[1])
                    for f in _glob.glob(os.path.join(ROOT, "eval", "tug_activity_results_*.json"))
                    + _glob.glob(os.path.join(ROOT, "eval", "encounter_results_*.json"))})
    for y in years:
        for src, dst in (("tug_activity_results.json", "activity.json"),
                         ("encounter_validation.json", "encounter_validation.json")):
            p = by_year(os.path.join(ROOT, "eval", src), y)
            if os.path.exists(p):
                shutil.copy(p, by_year(os.path.join(out, dst), y))
        tug = by_year(os.path.join(ROOT, "eval", "tug_activity_by_vessel.csv"), y)
        act = by_year(os.path.join(ROOT, "eval", "tug_activity_results.json"), y)
        if os.path.exists(tug):
            t = pd.read_csv(tug)
            assist = set(json.load(open(act)).get("assist_tug_mmsi", [])) if os.path.exists(act) else set()
            t["assist_tug"] = t.mmsi.isin(assist)
            t["name"] = t["name"].fillna("")
            _w(by_year(os.path.join(out, "activity_tugs.json"), y),
               t[["mmsi", "name", "days_seen", "hours_active", "hours_assist", "hours_active_dac", "spb_share",
                  "active_hours_annualized", "assist_tug"]].round(1).to_dict("records"))
        mon = by_year(os.path.join(ROOT, "data", "derived", "tug_activity_monthly.csv"), y)
        if os.path.exists(mon):
            m = pd.read_csv(mon).groupby(["month", "region", "mode", "near_dac"]).hours.sum().reset_index()
            _w(by_year(os.path.join(out, "activity_monthly.json"), y), m.round(2).to_dict("records"))
        enc_csv = by_year(os.path.join(ROOT, "data", "derived", "encounters.csv"), y)
        if os.path.exists(enc_csv):
            export_encounters(out, enc_csv, y)
    _w(os.path.join(out, "years.json"), {"years": years, "latest": years[-1] if years else None})

    # ---------- meta ----------
    man = read_manifest()
    srcs = {}
    for m in man:
        s = srcs.setdefault(m["source"], {"license": m["license"], "files": 0, "latest_fetch": ""})
        s["files"] += 1
        s["latest_fetch"] = max(s["latest_fetch"], m["fetched_at"])
    count = lambda s: con.execute(s).fetchone()[0]
    meta = {"built_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "counts": {"contracts": count("SELECT COUNT(*) FROM contract"),
                       "contract_actions": count("SELECT COUNT(*) FROM contract_action"),
                       "vessels": count("SELECT COUNT(*) FROM vessel"),
                       "edges": count("SELECT COUNT(*) FROM edge"),
                       "firms": len(firms),
                       "availabilities": count("SELECT COUNT(*) FROM availability") if has("availability") else 0},
            "sources": srcs}
    _w(os.path.join(out, "meta.json"), meta)
    n_files = sum(len(fs) for _, _, fs in os.walk(out))
    size = sum(os.path.getsize(os.path.join(d, f)) for d, _, fs in os.walk(out) for f in fs)
    print(f"exported {n_files} files, {size / 1e6:.1f} MB -> {out}")
    return meta


def export_encounters(out, enc_csv, year, n_scenarios=200):
    """Summary, daily counts, and the closest large-vessel traffic encounters with raw tracks (one year)."""
    import pandas as pd
    from . import encounters as en
    from .years import by_year
    df = pd.read_csv(enc_csv)
    p = by_year(os.path.join(ROOT, "eval", "encounter_results.json"), year)
    if os.path.exists(p):
        shutil.copy(p, by_year(os.path.join(out, "encounters.json"), year))
    tr = df[(df.service == 0) & (df.realized == 1)].copy()
    lg = (tr.large_involved == 1) & (tr.pleasure_involved == 0)
    if "launch_involved" in tr:
        lg &= (tr.launch_involved == 0) & (tr.military_involved == 0)
    daily = (tr.assign(t185=tr.min_sep_obs_m <= 185.2, t93=tr.min_sep_obs_m <= 92.6, lg=lg)
               .groupby(["day", "region"])
               .agg(encounters=("realized", "size"), within_185m=("t185", "sum"), within_93m=("t93", "sum"),
                    large_no_pleasure=("lg", "sum")).reset_index())
    _w(by_year(os.path.join(out, "encounter_daily.json"), year), daily.to_dict("records"))
    # candidates: closest 3x by the 1-minute grid; then rank by the more conservative of the grid value
    # and the report-time check, because interpolating across long reporting gaps can make
    # near-zero distances that never happened
    keep = (tr.large_involved == 1) & (tr.pleasure_involved == 0)
    if "launch_involved" in tr:
        keep &= tr.launch_involved == 0
    if "military_involved" in tr:
        keep &= tr.military_involved == 0
    cand = tr[keep].sort_values("min_sep_obs_m").head(n_scenarios * 4)
    checked = []
    for e in cand.to_dict("records"):
        t = en.snippet(e["day"], e["region"], e["mmsi_a"], e["mmsi_b"], e["t_first"], e["t_last"])
        raw = None if t.empty else en.raw_min_separation(t, e["mmsi_a"], e["mmsi_b"], e["t_first"], e["t_last"])
        checked.append((max(e["min_sep_obs_m"], raw if raw is not None else 1e9), e, t, raw))
    checked.sort(key=lambda c: c[0])
    rows, seen = [], set()
    for _, e, t, raw in checked:
        if len(rows) >= n_scenarios:
            break
        # the same pass can be reached from several alert runs: one scenario per pair per 15 minutes
        key = (e["day"], e["mmsi_a"], e["mmsi_b"], int((e["t_min_sep"] or e["t_first"]) // 900))
        if key in seen:
            continue
        seen.add(key)
        sid = f"{e['day']}-{e['region']}-{e['mmsi_a']}-{e['mmsi_b']}-{e['t_first']}"
        if t.empty:
            continue
        ox = t[t.mmsi == e["mmsi_a"]].x.iloc[0] if (t.mmsi == e["mmsi_a"]).any() else t.x.iloc[0]
        oy = t[t.mmsi == e["mmsi_a"]].y.iloc[0] if (t.mmsi == e["mmsi_a"]).any() else t.y.iloc[0]
        tracks = {str(m): g.assign(x=(g.x - ox).round(1), y=(g.y - oy).round(1))[["ts", "x", "y", "sog", "cog"]]
                  .round({"sog": 1, "cog": 0}).values.tolist() for m, g in t.groupby("mmsi")}
        clean = {k: (None if isinstance(v, float) and v != v else v) for k, v in e.items()}
        meta = dict(clean, id=sid, raw_min_sep_m=None if raw is None else round(raw, 1),
                    conservative_min_sep_m=round(max(e["min_sep_obs_m"], raw if raw is not None else 0), 1))
        _w(os.path.join(out, "encounters", sid + ".json"), dict(meta, tracks=tracks))
        rows.append(meta)
    _w(by_year(os.path.join(out, "encounter_scenarios.json"), year), rows)
