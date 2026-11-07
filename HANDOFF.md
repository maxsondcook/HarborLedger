# Handoff (2026-11-07, early morning)

## State
- **All 2024 California AIS is processed** (366 days, 4.6 GB, gitignored). It drove the full-year reruns of:
  - tug hours by month (season ruled out as the reason for the POLA gap);
  - encounters (dredging and diving now count as service, a military flag, a likely-launch rule, validation on 400 alerts);
  - Coast Guard matching (3,309 vessels, 120/120 precision across two review samples).
- **Graph rebuilt, model rerun, site data exported** (3,915 files, 6.4 MB).
- **Methods page** is built and reads every figure from the exported test results.
- **Pushed:** the full-year work is on GitHub as one commit (07b2629). `data/derived/encounters.csv` (262 MB) stays local and gitignored; rebuild it with `run.py encounters`.
- **Site:** runs locally with `npm --prefix site run dev` (Terminal tab "HarborLedger site").

## Decided
- Portfolio piece for employers, about a month at 15-20 h/week, public data only, public website.
- React front end, and the encounter dataset is part of the plan.

## Next steps
1. Week 4: polish (mobile check, light-mode check, page titles), make the repo public, deploy to GitHub Pages with Actions, and write a short case study / résumé bullets.
2. Optional: the MARAD U.S.-flag fleet sheet (manual download).
