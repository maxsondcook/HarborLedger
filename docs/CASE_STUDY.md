# HarborLedger: case study

**What it is:** a public website and data pipeline that links California's maritime public records into one graph. The records never shared a key: Navy repair and shipbuilding contracts, ship tracking (AIS), Coast Guard inspection and documentation records, shipyard ownership and port activity. Each link carries a confidence score, the method that made it, its source and its licence.

**Stack:** Python (pandas, NumPy, scikit-learn, SciPy, SQLite), React + TypeScript + Vite, custom SVG charts, GitHub Actions and GitHub Pages. Every input is public.

## The problem

Maritime data is plentiful but fragmented. A Navy repair contract names a ship in free text ("USS GREEN BAY (LPD 20) FY25 DSRA"). AIS identifies vessels by MMSI, with unreliable IMO numbers and call signs. The Coast Guard uses its own vessel ID and official number. The government's company data lists the same shipyard under several legal entities, and some of the stated parents are wrong (Austal USA's "parent" is listed as Computershare). Answering a simple question means resolving identity across all of these sources first, and doing it in a way someone else can audit. Examples of simple questions:

- How much do repair jobs grow?
- How often do ships come dangerously close?
- Which vessels may legally trade between U.S. ports?

## What I built

1. **Reproducible ingestion.** Keyless public APIs and bulk files go in as snapshots, each logged with source, query, fetch time, SHA-256 and licence. The sources are 1,965 Navy contracts with 130,636 modifications, a full year of California AIS (366 days, about 290M national rows filtered to California waters), USCG PSIX records and the Coast Guard's 397,587-vessel register.
2. **A confidence-scored graph (SQLite).** Typed nodes, and one edge table in which every link records confidence, method, source record, validity window and licence. Links below 0.5 are kept for audit but not counted.
3. **Entity resolution with measured precision:**
   - **Contract text → Navy hull:** regex plus a name gazetteer. 26/26 correct on a held-out hand sample.
   - **AIS → Coast Guard:** call-sign matching gated on IMO or name agreement. 120/120 correct across two random review samples, with 2,717 of 3,309 vessels matched.
   - **Legal entities → curated firms:** dated ownership, covering 98.7% of award dollars.
4. **Three analyses on top of the graph:**
   - **Navy repair cost-growth ledger** (436 availabilities). It feeds an early-warning model tested on later years, with leakage controls (only actions dated within the first 90 or 180 days are used). It is compared against honest baselines, and unfinished jobs are handled as censored.
   - **Tug activity hours from AIS**, by operating mode, port, month and distance to state-designated disadvantaged communities. These are compared with the Port of LA's emissions inventory.
   - **Close-quarters encounter dataset (CPA/TCPA)** for San Pedro Bay, SF Bay and San Diego. It is vectorized to process a day of AIS in about 2 seconds, it separates predicted alerts from real close passes, and it is validated against report-time recomputation.
5. **A public React site** with vessel, shipyard, ledger, activity, encounter and scenario pages, plus a methods page whose numbers are read from the test results.

## Results

- **Repair cost growth.** Navy surface-ship repair jobs grow a median **+8.3%** beyond their base award and pre-priced options; one in ten grows **+47%** or more.
- **Early warning.** Growth shows up early in public modification records. By day 180, "growth so far" alone cuts forecast error by 49%, and a gradient-boosted model adds no significant improvement.
- **Collision alerts.** Straight-line alerts come true **57%** of the time: 80% when raised under 2 minutes ahead, 44% at 5–10 minutes. This is the false-alarm baseline any collision-avoidance model has to beat.
- **Service boats.** **Most apparent close calls with large ships in San Pedro Bay (59%) involve service boats**: 156 small launches and bunker boats whose AIS type does not say what they are. Without that rule the encounter statistics would be badly inflated.
- **Tug hours.** Busy harbor tugs log about **1,837** active hours a year on AIS against 1,387 in the Port of LA inventory. GPS jitter and seasonality were tested and ruled out as explanations.

## What failed, and what I did about it

- **Hull extraction, development sample: 92.3%, below the 95% target.** Both errors were "DDG 51" used as a programme name rather than a ship. I fixed that, then scored the fix on a *new* sample drawn afterwards, so the reported number isn't tuned to the errors it fixed.
- **Early-warning model at 90 days: +14.7% against a pre-set 15% bar.** I reported it as a miss and did not retune on the test years.
- **Schedule-slip label.** A model scored AUC 0.72, but the contracting office alone scores the same. The label mostly encodes how each office words its modifications, and the site says so.
- **Encounter validation.** It exposed that interpolating across gaps in the thinned AIS feed can manufacture near-zero distances. Scenarios are now ranked by the more conservative of two estimates, and about one alert in ten has an uncertain label. That is stated on the site, not hidden.
- **The first full-year encounter rules counted dredges with their tenders, warships with unmanned vessels, and crew launches as "close calls".** Reviewing the closest cases led to three new rules (service types, a military flag, and a launch heuristic).

## Skills demonstrated

- **Entity resolution and record linkage** across sources with no shared key, with gated merges, confidence and provenance on every link, and precision measured on random samples.
- **Text extraction from messy government records**, evaluated on held-out samples.
- **Modelling discipline:** time-based splits, leakage control, censoring, strong baselines, bootstrap confidence intervals and pre-registered success tests.
- **Geospatial and time-series processing at scale:** AIS resampling, a spatial grid for pair search, closest-point-of-approach maths, COLREGS-style geometry, and raster distance transforms without GIS dependencies.
- **Data engineering:** snapshot manifests, licence tracking, resumable downloads, caching and unit tests (17).
- **Front end:** React and TypeScript, custom accessible SVG charts on a colour-blind-checked palette in light and dark mode, a responsive layout and static deployment.

## What I would do next

- Get **engine-hour or fuel data** from a tug operator, to turn activity hours into emissions.
- Use a **higher-rate AIS source**, to remove the interpolation uncertainty in encounters.
- Add a **partner label** for repair jobs (the Navy's estimate or schedule days), so the model forecasts something public records don't already show.

---

## Résumé bullets

- Built **HarborLedger**, a public-data maritime intelligence site. It links 1,965 Navy contracts (130K modifications), a year of California AIS and Coast Guard records into a confidence-scored graph, with provenance and licence tracking on every link. Stack: Python, SQLite, React/TypeScript, GitHub Pages.
- Designed **entity-resolution rules** across sources with no shared key, and measured their precision on random samples: 120/120 AIS-to-Coast-Guard matches correct (2,717 of 3,309 vessels linked), and 100% hull extraction on a held-out sample.
- Created a **Navy repair cost-growth ledger** (436 availabilities, median +8.3% growth) and tested an early-warning model with time-based splits, leakage controls and pre-registered targets. I reported where it missed and showed that "growth so far" is the baseline to beat.
- Built a **vectorized close-quarters encounter detector** (CPA/TCPA, about 2 s per AIS day). It found that straight-line alerts come true 57% of the time, and that 59% of apparent large-ship close calls in San Pedro Bay involve service boats that AIS types don't identify.
