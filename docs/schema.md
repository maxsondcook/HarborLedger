# Graph schema

The graph lives in `data/harborledger.sqlite`. `run.py build` rebuilds it from scratch; `run.py growth`
adds the `availability` table. The DDL for the core tables is in `harborledger/db.py`.
`run.py check` checks the rules below after each build (see `harborledger/checks.py`).

## Node IDs

Every node ID has a prefix that says which source it comes from. Edges use these IDs.

| Prefix | Node | Table | Example |
|---|---|---|---|
| `contract:` | A Navy contract (USAspending award) | `contract` (stored without the prefix) | `contract:CONT_AWD_0001_9700_N0002405D2300_9700` |
| `uei:` | A legal entity that received an award | `organization` | `uei:C1F2V6232KT5` |
| `firm:` | A curated firm that groups UEIs | `organization` | `firm:ALABAMA_SHIPYARD` |
| `hull:` | A Navy hull | `vessel` | `hull:AO-187` |
| `mmsi:` | A vessel seen in AIS | `vessel` | `mmsi:366562000` |
| `psix:` | A Coast Guard PSIX record | `vessel` | `psix:1000104` |
| `uscg:` | A federal vessel register (MVUS) entry | `vessel` | `uscg:1000315` |
| `area:` | A port area used for activity hours | `facility` | `area:san_pedro_bay` |

## Tables

| Table | One row per | Key columns |
|---|---|---|
| `source_snapshot` | Raw file fetched from a source | `path, source, endpoint, params, fetched_at, sha256, license` |
| `contract` | Award | `contract_id, piid, awarding_office, description, recipient_uei, award_amount, start_date, end_date, avail_type` |
| `contract_action` | Contract modification | `contract_id, seq, action_date, mod_number, action_type, obligation, description` |
| `organization` | UEI or curated firm | `org_id, kind, name` |
| `org_name_variant` | Name a UEI used on an award | `org_id, name, n_awards` |
| `vessel` | Source record for a vessel (not a resolved vessel) | `vessel_id, name, hull, hull_class, name_source` |
| `identifier` | ID asserted for a vessel record | `vessel_id, scheme, value, valid_from, valid_to, source, license` |
| `edge` | Relationship | see below |
| `facility` | Port area bounding box | `facility_id, name, kind, lat_min, lat_max, lon_min, lon_max` |
| `uscg_vessel` | Row of the federal vessel register, per edition | `edition, vessel_id, vessel_name, call_sign, official_number, imo_number, ...` (owner addresses are not kept) |
| `availability` | Repair availability (added by `growth`) | `contract_id, hull, avail_type, firm, first_action, closed, base, options, total, g_total, g_exopt, g_exopt_noC, n_mods, delay_flag` |
| `v_vessel_profile` (view) | AIS vessel with its PSIX and register links | `mmsi_node, ais_name, psix_node, uscg_node, ...` |

`vessel` holds **source records**, so its 10,070 rows are not 10,070 ships. Connected components of
`SAME_AS` edges are resolved vessels (5,242 in the current build; see `trace.funnel`).

Identifier schemes: `mmsi`, `imo`, `call_sign`, `ais_name`, `navy_hull`, `ship_name`,
`psix_vessel_id`, `uscg_identification`.

## Edges

`edge(src, rel, dst, confidence, method, source_ref, valid_from, valid_to, license, evidence)`

| `rel` | From → to | `method` values | Meaning |
|---|---|---|---|
| `AWARDED_TO` | `contract:` → `uei:` | `source_field` | Recipient named on the award |
| `PART_OF` | `uei:` → `firm:`, `firm:` → `firm:` | `curated` | UEI belongs to a firm; firm owned by a parent (dated with `valid_from`/`valid_to`) |
| `ABOUT_VESSEL` | `contract:` → `hull:` | `regex_hull`, `regex_hull_classlead`, `gazetteer`, `gazetteer_short` | Contract text names the hull |
| `SAME_AS` | `mmsi:` → `psix:` | `callsign_gated`, `name_plus_imo` | AIS vessel is this Coast Guard record |
| `SAME_AS` | `mmsi:` → `uscg:`, `psix:` → `uscg:` | `callsign_gated_mvus`, `official_number` | Same vessel in the federal register |
| `SAME_AS` | `hull:` → `mmsi:` | `wikipedia_imo_mmsi` | Navy hull's infobox IMO/MMSI equals the AIS record's |
| `POSSIBLE_SAME_AS` | `mmsi:` → `psix:` | `callsign_weak_name` | Call sign matched but the name did not; kept for review, not counted |
| `ACTIVE_IN` | `mmsi:` → `area:` | `ais_activity_hours` | Tug activity hours in a port area |

## Rules

These hold for every build. `run.py check` reports each one, and exits with status 1 on any error.

- `confidence` is in [0, 1]. A `SAME_AS` link always has confidence ≥ 0.5. Weaker matches are
  `POSSIBLE_SAME_AS`, and `ABOUT_VESSEL` links below 0.5 (`hulls.ASSERT_THRESHOLD`) are kept but
  not counted.
- Vessel links use stable IDs only: call sign, IMO, MMSI or official number. A name can confirm a call-sign
  hit but never links on its own. Conflicting IDs are never linked.
- Every edge has a `method`, a `license` and, except for some curated ownership edges, a
  `source_ref`. The `license` column is authoritative for any record.
- Every identifier has a `source` and `license`. Every snapshot has a `sha256` and `license`.
- No edge points at a missing node, and each AIS vessel links to at most one PSIX record.
- The site export (`site/public/data/meta.json`) reports the same counts as the database.

Known exception (reported as a warning): four curated `PART_OF` ownership edges have no `source_ref`.
Their sources are in the private research notes.
