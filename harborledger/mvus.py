"""USCG Merchant Vessels of the United States (MVUS / "vesdoc") register.

Downloaded manually from dco.uscg.mil (the server blocks automated downloads) into
data/raw/mvus/<edition>/zip/ and extracted to data/raw/mvus/<edition>/extract/.
Despite the "tab" name, the file is comma-separated with quoted fields; 78 fields per row,
in the order of the readme's field table (ReadMeVesdocNov2026.pdf).

Privacy: the Coast Guard already redacts individual owners ("Privacy"). We additionally drop
owner address fields entirely and keep an owner name only when it is an organization.
"""
import csv
import glob
import os

from .snapshot import RAW, record

FIELDS = [
    "vessel_id", "vessel_name", "call_sign", "official_number", "imo_number", "hull_number", "hin",
    "service", "flag", "self_propelled", "gross_ton", "net_ton", "length", "breadth", "depth",
    "itc_gross_ton", "itc_net_ton", "itc_length", "itc_breadth", "itc_depth", "dwt", "dwt_unit",
    "measuring_org", "hailing_port", "hailing_port_state", "hailing_port_country",
    # trade endorsements ("X" / blank)
    "coastwise_unrestricted", "ltd_coastwise_bowaters", "ltd_coastwise_marad_waiver",
    "ltd_coastwise_oil_spill", "ltd_coastwise_charter_citizen", "ltd_coastwise_fish_products",
    "fishery", "ltd_fishery", "recreation", "ltd_recreation_great_lakes", "registry",
    "ltd_registry_cross_border_fin", "ltd_registry_no_foreign_voyage", "ltd_registry_canada_only",
    "great_lakes",
    "builder", "shipyard", "build_year", "complete_build_city", "complete_build_state",
    "complete_build_province", "complete_build_country", "hull_build_city", "hull_build_state",
    "hull_build_province", "hull_build_country",
    # owner block
    "party_id", "org_name", "org_type", "person_first", "person_middle", "person_last",
    "person_suffix", "addr1", "addr2", "addr3", "addr4", "owner_city", "owner_state",
    "owner_province", "owner_country", "owner_postal",
    "main_hp_ahead", "main_hp_astern", "propulsion_type", "hull_material", "hull_configuration",
    "hull_shape", "cod_status", "cod_issue_date", "cod_expire_date", "filler",
]
assert len(FIELDS) == 78
DROP = {"person_first", "person_middle", "person_last", "person_suffix", "addr1", "addr2", "addr3",
        "addr4", "owner_city", "owner_state", "owner_province", "owner_postal", "hin", "party_id",
        "filler"}
TRADE = [f for f in FIELDS[26:41]]
KEEP = [f for f in FIELDS if f not in DROP]
URL = ("https://www.dco.uscg.mil/Portals/9/DCO%20Documents/5p/CG-5PC/INV/"
       "Merchant%20Vessels%20of%20US/vesdoc{e}Rtab.zip")

SCHEMA = """
CREATE TABLE IF NOT EXISTS uscg_vessel (
  edition TEXT, {cols}, coastwise_any INTEGER, PRIMARY KEY (edition, vessel_id)
);
CREATE INDEX IF NOT EXISTS uscg_cs ON uscg_vessel(edition, call_sign);
CREATE INDEX IF NOT EXISTS uscg_on ON uscg_vessel(edition, official_number);
CREATE INDEX IF NOT EXISTS uscg_imo ON uscg_vessel(edition, imo_number);
""".format(cols=", ".join(f"{c} TEXT" for c in KEEP))


def clean(v):
    v = (v or "").strip()
    while len(v) >= 2 and v.startswith('"') and v.endswith('"'):
        v = v[1:-1].strip()
    return v


def editions():
    return sorted(os.path.basename(os.path.dirname(os.path.dirname(p)))
                  for p in glob.glob(os.path.join(RAW, "mvus", "*", "extract", "*.txt")))


def register_snapshots():
    """Record the manually downloaded zips in the manifest (once per edition)."""
    from .snapshot import ROOT, read_manifest
    seen = {m["path"] for m in read_manifest()}
    for z in glob.glob(os.path.join(RAW, "mvus", "*", "zip", "*.zip")):
        if os.path.relpath(z, ROOT) not in seen:
            e = os.path.basename(os.path.dirname(os.path.dirname(z)))
            record(z, "uscg_mvus", URL.format(e=e), {"edition": e, "download": "manual (browser)"})


def rows(path):
    with open(path, newline="", encoding="latin-1") as fh:
        for r in csv.reader(fh):
            if len(r) != 78:
                continue
            d = {k: clean(v) for k, v in zip(FIELDS, r)}
            if d["org_type"] in ("", "N/A") or d["org_name"].lower() == "privacy":
                d["org_name"] = ""
            yield d


def load(con):
    con.executescript(SCHEMA)
    stats = {}
    for e in editions():
        path = glob.glob(os.path.join(RAW, "mvus", e, "extract", "*.txt"))[0]
        n = bad = 0
        batch = []
        for d in rows(path):
            cw = int(any(d[t] == "X" for t in TRADE if "coastwise" in t))
            batch.append((e, *[d[k] for k in KEEP], cw))
            n += 1
            if len(batch) >= 20000:
                con.executemany(f"INSERT OR REPLACE INTO uscg_vessel VALUES ({','.join('?' * (len(KEEP) + 2))})", batch)
                batch = []
        if batch:
            con.executemany(f"INSERT OR REPLACE INTO uscg_vessel VALUES ({','.join('?' * (len(KEEP) + 2))})", batch)
        con.commit()
        stats[e] = n
    return stats
