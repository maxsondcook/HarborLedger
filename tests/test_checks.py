"""Post-build integrity checks against a small in-memory graph."""
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harborledger import checks, db  # noqa: E402


def graph():
    con = sqlite3.connect(":memory:")
    con.executescript(db.SCHEMA)
    con.execute("INSERT INTO source_snapshot VALUES (1,'p','s','e','{}','t','abc','CC0')")
    con.executemany("INSERT INTO vessel (vessel_id, name) VALUES (?, ?)",
                    [("mmsi:1", "A"), ("psix:1", "A"), ("hull:T-AO-1", "B")])
    con.execute("INSERT INTO contract (contract_id) VALUES ('C1')")
    con.execute("INSERT INTO organization (org_id) VALUES ('uei:X')")
    con.execute("INSERT INTO identifier VALUES ('mmsi:1','mmsi','1',NULL,NULL,'ais','CC0')")
    edges = [("mmsi:1", "SAME_AS", "psix:1", 0.98, "callsign_gated", "psix.json", "CC0"),
             ("contract:C1", "ABOUT_VESSEL", "hull:T-AO-1", 0.9, "regex_hull", "txn.json", "CC0"),
             ("contract:C1", "AWARDED_TO", "uei:X", 1.0, "source_field", "award.json", "CC0")]
    con.executemany("INSERT INTO edge (src, rel, dst, confidence, method, source_ref, license) "
                    "VALUES (?,?,?,?,?,?,?)", edges)
    return con


def levels(con):
    return {name: level for level, name, _ in checks.check_db(con)}


def test_clean_graph_passes():
    assert all(lv == "OK" for lv in levels(graph()).values())


def test_missing_licence_is_an_error():
    con = graph()
    con.execute("UPDATE edge SET license = '' WHERE rel = 'SAME_AS'")
    assert levels(con)["every edge has a licence"] == "ERROR"


def test_confidence_out_of_range_is_an_error():
    con = graph()
    con.execute("UPDATE edge SET confidence = 1.2 WHERE rel = 'SAME_AS'")
    assert levels(con)["edge confidence in [0, 1]"] == "ERROR"


def test_orphan_edge_is_an_error():
    con = graph()
    con.execute("INSERT INTO edge (src, rel, dst, confidence, method, source_ref, license) "
                "VALUES ('mmsi:1','SAME_AS','psix:999',0.98,'callsign_gated','x','CC0')")
    lv = levels(con)
    assert lv["no orphan edges"] == "ERROR"
    assert lv["each AIS vessel links to at most one PSIX record"] == "ERROR"


def test_name_only_link_method_is_an_error():
    con = graph()
    con.execute("UPDATE edge SET method = 'name_match' WHERE rel = 'SAME_AS'")
    assert levels(con)["vessel links use stable-ID methods only"] == "ERROR"


def test_weak_same_as_is_an_error():
    con = graph()
    con.execute("UPDATE edge SET confidence = 0.4 WHERE rel = 'SAME_AS'")
    assert levels(con)["no SAME_AS link below confidence 0.5"] == "ERROR"


def test_curated_edge_without_source_is_only_a_warning():
    con = graph()
    con.execute("INSERT INTO organization (org_id) VALUES ('firm:A'), ('firm:B')")
    con.execute("INSERT INTO edge (src, rel, dst, confidence, method, source_ref, license) "
                "VALUES ('firm:A','PART_OF','firm:B',0.95,'curated','','curated')")
    assert levels(con)["every edge has a source reference"] == "WARN"
