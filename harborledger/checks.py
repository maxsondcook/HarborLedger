"""Post-build integrity checks for the SQLite graph and the exported site JSON.

Run with `python3 -I run.py check`. Each check returns (level, name, detail):
  ERROR  breaks a stated project rule (e.g. an edge without a licence); `check` exits non-zero
  WARN   worth a look but not a broken rule (e.g. a curated edge with no source reference)
  OK     passed

The rules come from CLAUDE.md: every edge carries confidence, method, source and licence; vessel
links rest on stable IDs; links below hulls.ASSERT_THRESHOLD are kept but not counted.
"""
import json
import os

from . import db
from .snapshot import ROOT

SITE_DATA = os.path.join(ROOT, "site", "public", "data")
VESSEL_PREFIXES = ("hull:", "mmsi:", "psix:", "uscg:")
STABLE_ID_METHODS = {
    "callsign_gated", "callsign_gated_mvus", "callsign_weak_name", "name_plus_imo",
    "official_number", "wikipedia_imo_mmsi",
}
REQUIRED_TABLES = ("source_snapshot", "contract", "contract_action", "organization", "vessel",
                   "identifier", "edge")


def _one(con, sql, *args):
    return con.execute(sql, args).fetchone()[0]


def check_db(con):
    out = []

    def add(ok, name, detail, level="ERROR"):
        out.append(("OK" if ok else level, name, detail))

    tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type IN ('table','view')")}
    missing = [t for t in REQUIRED_TABLES if t not in tables]
    add(not missing, "required tables present", f"missing: {missing}" if missing else f"{len(REQUIRED_TABLES)} tables")
    if missing:
        return out

    n_edges = _one(con, "SELECT COUNT(*) FROM edge")
    add(n_edges > 0, "graph has edges", f"{n_edges} edges")

    bad = _one(con, "SELECT COUNT(*) FROM edge WHERE confidence IS NULL OR confidence < 0 OR confidence > 1")
    add(bad == 0, "edge confidence in [0, 1]", f"{bad} out of range")

    bad = _one(con, "SELECT COUNT(*) FROM edge WHERE license IS NULL OR TRIM(license) = ''")
    add(bad == 0, "every edge has a licence", f"{bad} without")

    bad = _one(con, "SELECT COUNT(*) FROM edge WHERE method IS NULL OR TRIM(method) = ''")
    add(bad == 0, "every edge has a method", f"{bad} without")

    rows = con.execute("SELECT src, rel, dst, method FROM edge WHERE source_ref IS NULL OR TRIM(source_ref) = ''").fetchall()
    curated_only = all(r[3] == "curated" for r in rows)
    detail = f"{len(rows)} without" + (": " + ", ".join(f"{r[0]}->{r[2]}" for r in rows[:5]) if rows else "")
    add(not rows, "every edge has a source reference", detail, level="WARN" if curated_only else "ERROR")

    bad = _one(con, "SELECT COUNT(*) FROM identifier WHERE source IS NULL OR TRIM(source) = '' "
                    "OR license IS NULL OR TRIM(license) = ''")
    add(bad == 0, "every identifier has a source and licence", f"{bad} without")

    bad = _one(con, "SELECT COUNT(*) FROM source_snapshot WHERE sha256 IS NULL OR TRIM(sha256) = '' "
                    "OR license IS NULL OR TRIM(license) = ''")
    add(bad == 0, "every snapshot has sha256 and licence", f"{bad} without")

    like = " OR ".join(f"{{col}} LIKE '{p}%'" for p in VESSEL_PREFIXES)
    orphans = 0
    for col in ("src", "dst"):
        orphans += _one(con, f"SELECT COUNT(*) FROM edge WHERE ({like.format(col=col)}) "
                             f"AND {col} NOT IN (SELECT vessel_id FROM vessel)")
    orphans += _one(con, "SELECT COUNT(*) FROM edge WHERE src LIKE 'contract:%' "
                         "AND SUBSTR(src, 10) NOT IN (SELECT contract_id FROM contract)")  # strip 'contract:'
    for col in ("src", "dst"):
        orphans += _one(con, f"SELECT COUNT(*) FROM edge WHERE ({col} LIKE 'uei:%' OR {col} LIKE 'firm:%') "
                             f"AND {col} NOT IN (SELECT org_id FROM organization)")
    add(orphans == 0, "no orphan edges", f"{orphans} edges point at a missing node")

    bad = _one(con, "SELECT COUNT(*) FROM edge WHERE rel IN ('SAME_AS','POSSIBLE_SAME_AS') AND src = dst")
    add(bad == 0, "no self-links", f"{bad} self-links")

    multi = _one(con, "SELECT COUNT(*) FROM (SELECT src FROM edge WHERE rel = 'SAME_AS' AND src LIKE 'mmsi:%' "
                      "AND dst LIKE 'psix:%' GROUP BY src HAVING COUNT(DISTINCT dst) > 1)")
    add(multi == 0, "each AIS vessel links to at most one PSIX record", f"{multi} conflicts")

    methods = {r[0] for r in con.execute("SELECT DISTINCT method FROM edge WHERE rel IN ('SAME_AS','POSSIBLE_SAME_AS')")}
    unknown = sorted(methods - STABLE_ID_METHODS)
    add(not unknown, "vessel links use stable-ID methods only", f"unrecognised methods: {unknown}" if unknown
        else f"{len(methods)} methods")

    weak = _one(con, "SELECT COUNT(*) FROM edge WHERE rel = 'SAME_AS' AND confidence < 0.5")
    add(weak == 0, "no SAME_AS link below confidence 0.5", f"{weak} weak SAME_AS links (should be POSSIBLE_SAME_AS)")
    return out


def check_export(con, site_data=SITE_DATA):
    out = []

    def add(ok, name, detail, level="ERROR"):
        out.append(("OK" if ok else level, name, detail))

    meta_path = os.path.join(site_data, "meta.json")
    if not os.path.exists(meta_path):
        return [("WARN", "site export present", f"{meta_path} not found; run `run.py export`")]
    meta = json.load(open(meta_path))
    counts = meta.get("counts", {})
    for key, sql in (("vessels", "SELECT COUNT(*) FROM vessel"), ("edges", "SELECT COUNT(*) FROM edge"),
                     ("contracts", "SELECT COUNT(*) FROM contract")):
        if key in counts:
            n = _one(con, sql)
            add(counts[key] == n, f"meta.json {key} matches the database", f"meta {counts[key]} vs db {n}",
                level="WARN")
    out.extend(check_export_files(site_data))
    return out


def check_export_files(site_data=SITE_DATA):
    """Checks that need only the exported JSON (these also run in CI, which has no database)."""
    out = []
    idx_path = os.path.join(site_data, "vessels.json")
    if not os.path.exists(idx_path):
        return [("WARN", "vessel index present", "vessels.json not found")]
    index = json.load(open(idx_path))
    slugs = [v["slug"] for v in index]
    files = {f[:-5] for f in os.listdir(os.path.join(site_data, "vessels")) if f.endswith(".json")}
    out.append(("OK" if len(slugs) == len(set(slugs)) else "ERROR", "vessel slugs unique",
                f"{len(slugs) - len(set(slugs))} duplicates"))
    missing, extra = set(slugs) - files, files - set(slugs)
    out.append(("OK" if not missing and not extra else "ERROR", "every indexed vessel has a page file",
                f"{len(missing)} missing, {len(extra)} unindexed"))
    bad_conf = [v["slug"] for v in index if v.get("conf") is not None and not 0 <= v["conf"] <= 1]
    out.append(("OK" if not bad_conf else "ERROR", "vessel index confidence in [0, 1]", f"{len(bad_conf)} out of range"))
    return out


def run(con=None, site_data=SITE_DATA):
    con = con or db.connect()
    results = check_db(con) + check_export(con, site_data)
    width = max(len(r[1]) for r in results)
    for level, name, detail in results:
        print(f"{level:<5}  {name:<{width}}  {detail}")
    n_err = sum(r[0] == "ERROR" for r in results)
    n_warn = sum(r[0] == "WARN" for r in results)
    print(f"\n{len(results)} checks: {n_err} errors, {n_warn} warnings")
    return n_err
