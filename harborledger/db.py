"""SQLite schema. Nodes are typed tables; relationships live in one `edge` table where
every row carries confidence, method, source reference, validity window and license."""
import os
import sqlite3

from .snapshot import ROOT

DB_PATH = os.path.join(ROOT, "data", "harborledger.sqlite")

SCHEMA = """
CREATE TABLE source_snapshot (
  snapshot_id INTEGER PRIMARY KEY, path TEXT, source TEXT, endpoint TEXT, params TEXT,
  fetched_at TEXT, sha256 TEXT, license TEXT
);
CREATE TABLE contract (
  contract_id TEXT PRIMARY KEY,          -- USAspending generated_internal_id
  piid TEXT, awarding_office TEXT,       -- office = first 6 chars of PIID (e.g. N55236 = SWRMC)
  description TEXT, recipient_uei TEXT, recipient_name TEXT,
  naics TEXT, psc TEXT, pop_state TEXT, start_date TEXT, end_date TEXT,
  award_amount REAL, last_modified TEXT, fy_text INTEGER, avail_type TEXT,
  snapshot_id INTEGER REFERENCES source_snapshot
);
CREATE TABLE contract_action (
  contract_id TEXT REFERENCES contract, seq INTEGER, action_date TEXT, mod_number TEXT,
  action_type TEXT, action_type_desc TEXT, obligation REAL, description TEXT,
  snapshot_id INTEGER REFERENCES source_snapshot, PRIMARY KEY (contract_id, seq)
);
CREATE TABLE organization (
  org_id TEXT PRIMARY KEY,               -- 'uei:XXXX' legal entity or 'firm:ID' curated firm
  kind TEXT, name TEXT, notes TEXT
);
CREATE TABLE org_name_variant (org_id TEXT, name TEXT, n_awards INTEGER);
CREATE TABLE vessel (
  vessel_id TEXT PRIMARY KEY,            -- 'hull:DDG-105' for Navy hulls
  name TEXT, hull TEXT, hull_class TEXT, name_source TEXT
);
CREATE TABLE identifier (
  vessel_id TEXT, scheme TEXT, value TEXT, valid_from TEXT, valid_to TEXT,
  source TEXT, license TEXT
);
CREATE TABLE edge (
  src TEXT, rel TEXT, dst TEXT, confidence REAL, method TEXT, source_ref TEXT,
  valid_from TEXT, valid_to TEXT, license TEXT, evidence TEXT
);
CREATE INDEX edge_src ON edge(src, rel);
CREATE INDEX edge_dst ON edge(dst, rel);
CREATE INDEX action_c ON contract_action(contract_id);
"""


def connect(path=DB_PATH, fresh=False):
    if fresh and os.path.exists(path):
        os.remove(path)
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    if fresh:
        con.executescript(SCHEMA)
    return con
