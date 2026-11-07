# Handoff (2026-11-07)

## State
- **Live:** https://maxsondcook.github.io/HarborLedger/ (GitHub Pages, deployed by `.github/workflows/deploy.yml` on pushes that touch `site/**`).
- **Repo:** https://github.com/maxsondcook/HarborLedger is public. It was recreated with a fresh single-commit history so the research notes never became public. The old history is kept locally on branch `archive/pre-public` (never pushed).
- **Research notes** live outside the repo at `~/Desktop/HarborLedger research`.
- **Data:** all of 2024 California AIS is processed. Large raw files and `data/derived/encounters.csv` (262 MB) are local and gitignored; rebuild them with the run commands in the README.
- **Week 4 is done:** mobile and light-mode check, readable charts on phones, page titles, favicon, home-page findings, methods page, Pages deploy, and `docs/CASE_STUDY.md` with résumé bullets.

## Decided
- Portfolio piece for employers, public data only, public website (React). The encounter dataset is in scope.
- Commits keep the NYU email (user's choice).

## Possible next steps
1. Upgrade the pinned Actions to their Node 24 majors (checkout v6, setup-node v6, configure-pages v6, upload-pages-artifact v5, deploy-pages v5) and check that a deploy still succeeds. Today GitHub only warns about this.
2. Optional: the MARAD U.S.-flag fleet sheet (manual download).
3. Optional: a second hand-labeller for the hull samples; a higher-rate AIS source for encounters.
