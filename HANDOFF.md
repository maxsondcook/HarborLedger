# Handoff (2026-11-07)

## State
- **Live:** https://maxsondcook.github.io/HarborLedger/ (GitHub Pages, deployed by `.github/workflows/deploy.yml` on pushes that touch `site/**`).
- **Repo:** https://github.com/maxsondcook/HarborLedger is public. It was recreated with a fresh single-commit history so the research notes never became public. The old history is kept locally on branch `archive/pre-public` (never pushed).
- **Research notes** live outside the repo at `~/Desktop/HarborLedger research`.
- **Data:** all of 2024 and 2025 California AIS is processed (2024 from MarineCadastre GeoParquet, 2025 from the daily `csv.zst` files; `ais.py` handles both). Per-year outputs use `harborledger/years.py`, and the site has a year selector on Harbor activity and Encounters. Large raw files and the `data/derived/` outputs are local and gitignored; rebuild them with the run commands in the README.
- **Analyses done:**
  - Graph: 10,070 vessels, 8,689 edges; Coast Guard matching 4,117 of 4,922 (180/180 held-out precision).
  - Tug hours vs the POLA inventory, both years.
  - Encounters: alert precision 56.8% (2024) / 57.1% (2025); validation 90.2% / 91.2%.
  - Collision-risk model (`collision.py`): train 2024, test 2025. AUC 0.732 against 0.610 for the kinematic baseline.
  - Weather (`weather.py`, `forecast.py`): speed loss in head seas; coastal-leg trip time; archived GFS-Wave forecasts cut MAE by 0.22 h (observed conditions: 0.52 h). A Pillow-based JPEG2000 GRIB2 decoder is used because eccodes wheels need macOS 15.
  - Fishing vs ocean data (`fishing.py`): AUC 0.922 → 0.944.
- **Write-ups:** four findings in `docs/findings/`; `docs/CASE_STUDY.md` has the results and résumé bullets.
- **Benchmark release:** https://github.com/maxsondcook/HarborLedger/releases/tag/encounters-v1 holds the 27 benchmark files (24 monthly alert Parquets, scenario tracks, data card, SHA256SUMS). They were uploaded on 2026-11-07 with the GitHub CLI and checked by downloading them again (all checksums match).
  - The released data card must stay byte-identical to its `SHA256SUMS` entry. So the release link is added only to the docs copy (`docs/benchmark/README.md`), not to `benchmark.py`'s generator.
  - `gh` is not installed; it was run from the session scratchpad and has since been logged out.
- **Zenodo:** the same 27 files are published as a dataset, DOI 10.5281/zenodo.24047861 (all-versions DOI 10.5281/zenodo.24047860), record https://zenodo.org/records/24047861, CC BY 4.0. Uploaded by the user through the web form; sizes and MD5s were checked against the local files before publishing. A new version should go through "New version" on that record.
- **Lessons-learned audit (2026-11-10):** checked against `~/Desktop/Crossr/lessons-learned.md`. No block bypass, no SSL changes, no secrets or research in pushed history, no third-party data the terms forbid. Added `docs/data-sources.md` (register), a shared honest `USER_AGENT`, `tests/test_fetch_policy.py`, and collection rules in `CLAUDE.md`. Open items: ERDDAP robots.txt judgement call (email erd.data@noaa.gov if it matters); OEHHA conditions of use not read (CAPTCHA).
- **Deploy Actions** are pinned by SHA to their Node 24 majors (checkout v6, setup-node v6, configure-pages v6, upload-pages-artifact v5, deploy-pages v5).

## Decided
- Portfolio piece for employers, public data only, public website (React). The encounter dataset is in scope.
- Commits keep the NYU email (user's choice).
- Success tests are set before running; failures are reported, not tuned away.

## Possible next steps
1. Outreach: send the collision write-up and benchmark to autonomy and port practitioners; post the findings.
2. Optional: the MARAD U.S.-flag fleet sheet (manual download); a second hand-labeller for the hull samples; a higher-rate AIS source for encounters.
