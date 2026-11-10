# HarborLedger: project notes

Public-data graph of California's working waterfront (vessels, Navy repair contracts, shipyards,
Coast Guard records, port activity), with a public static website planned on top.

## Architecture decisions
- **Repo root is the project.** The `harborledger/` package, `run.py` entry point, `curated/` hand
  tables, `eval/` test outputs, `tests/`, and `docs/` (case study). Phase 1-4 research notes live outside
  the repo in ~/Desktop/HarborLedger research (kept private).
- **Run everything with isolated Python:** `python3 -I run.py <cmd>`. `run.py` adds the repo to `sys.path`.
- **Raw data is not committed.** `data/raw/` subfolders are rebuilt by `pull-txns`, `pull-ais` and
  `match-psix`. `data/raw/manifest.jsonl` (committed) records the source, query, fetch time, sha256 and
  licence of every raw file. Wikipedia ship lists (small, CC BY-SA) are committed.
- **SQLite graph** at `data/harborledger.sqlite` (rebuilt by `build`, then `growth` adds the
  `availability` table). Every edge carries confidence, method, source_ref, validity window and licence.
- **Vessel links below confidence 0.5 are kept for audit but not counted** (`hulls.ASSERT_THRESHOLD`).
- **Success tests are set before running and failures are reported, not tuned away.** Held-out samples
  are drawn after fixes (hull sample 2027, PSIX review sample 2026).
- **Licences:** exclude Global Fishing Watch, OpenSanctions and Equasis from anything published.
- **Data collection rules** (from the CROSSR lessons learned; enforced by `tests/test_fetch_policy.py`):
  - Add a source to `docs/data-sources.md` (terms, robots.txt, use, method) **before** writing its fetcher.
  - Never get past a block (no impersonation, stealth flags, cookie reuse, proxies, CAPTCHA
    services or archive copies). A block or CAPTCHA means stop and ask.
  - Never turn off SSL checks.
  - Every request uses `snapshot.USER_AGENT` (project name and repo URL); throttle and cache.
  - Record per-file provenance in `data/raw/manifest.jsonl`. Every graph edge and identifier carries
    its source and licence.
  - Match vessels on stable IDs (MMSI, IMO, call sign, official number), never on name alone.
  - Before making anything public, check every file being published. Owner names are published
    only for organisations, and owner addresses are never kept.
  - One working copy (`~/Desktop/HarborLedger`) and one `main` branch. `archive/pre-public` is a
    local-only record of the pre-publication history and must never be pushed.
- **Hosting target:** static site (GitHub Pages) built from exported JSON; no server.
- **Website stack:** Vite + React + TypeScript in `site/`, HashRouter (works on Pages without
  rewrites), `base: "/HarborLedger/"`. Python `run.py export` writes `site/public/data/*.json`
  (committed so Pages can build without the database). Packages are pinned to releases at least
  two weeks old and checked on npm for real maintainers before adding.
- **Multi-hull contracts:** value is split equally across the hulls they name on vessel pages, and
  labelled as such.
- **Encounter dataset is in scope** (decided 2026-11-07): close-quarters encounters (CPA/TCPA) from
  California AIS, aimed at autonomy-oriented employers such as Saronic.
