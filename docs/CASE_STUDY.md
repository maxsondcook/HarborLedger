# HarborLedger: case study

**Live site:** https://maxsondcook.github.io/HarborLedger/ · **Code:** https://github.com/maxsondcook/HarborLedger ·
**Open benchmark:** [Zenodo, DOI 10.5281/zenodo.24047861](https://doi.org/10.5281/zenodo.24047861)

**What it is:** a data pipeline and public website that resolves five public maritime sources into
one graph of vessels:
- Navy repair contracts;
- Wikipedia ship lists and articles;
- AIS ship tracking;
- Coast Guard inspection records;
- the federal vessel register.

No two of these sources share a key. Every link records its confidence, the rule that made it, its
source and its licence. The site leads with that engineering: pick a vessel and follow each source's
own record through every join. The analyses (repair cost growth, tug hours, close calls, weather,
fishing) are built on the graph.

**Stack:** Python (pandas, NumPy, scikit-learn, SciPy, SQLite), React + TypeScript + Vite, custom SVG
charts, GitHub Actions and GitHub Pages. Every input is public.

## The problem

Maritime data is plentiful but fragmented, and each source names the same ship differently:

| Source | How it identifies a ship |
|---|---|
| Navy repair contract | in free text, e.g. "USS GREEN BAY (LPD 20) FY25 DSRA" or "USNS HENRY J. KAISER MID-TERM AVAILABILITY" |
| AIS | MMSI; IMO numbers and call signs are unreliable |
| Coast Guard inspections (PSIX) | their own vessel ID |
| Federal vessel register | an official number |

Companies are just as messy. The government's data lists the same shipyard under several legal
entities, and some of the stated parents are wrong (Austal USA's "parent" is listed as
Computershare). Before you can answer even a simple question, you have to resolve identity across
every source, in a way someone else can audit. Questions like:

- How much do repair jobs grow?
- How often do ships come dangerously close?
- Where did the ship that got that repair contract actually sail?

## What I built

1. **Vetted, reproducible ingestion.** Every source is in a
   [data-source register](data-sources.md) before any code fetches it: its terms, robots.txt, how
   it's collected and what may be published. A test fails if the code calls a host that isn't
   listed, or tries to get past a block. Raw files are logged in a manifest with source, query,
   fetch time, SHA-256 and licence. In total, **514.8 million raw records**:
   - 513.9M California AIS reports (731 days, 2024–2025);
   - 132,601 Navy contract records and modifications;
   - 780,493 Coast Guard register rows (two editions);
   - 5,194 PSIX lookups;
   - 256 Wikipedia pages.
2. **A confidence-scored graph (SQLite).**
   - 27,643 identifiers extracted from those records, across 10,070 source records.
   - 5,901 links tested. Each records its confidence, method, source file, validity window and licence.
   - Links below 0.5 are kept for audit but never merge records.
   - The result is **5,242 real-world vessels**, of which 4,124 were joined across two or more sources.
3. **Entity resolution on stable IDs, never on names alone, with precision measured on held-out samples:**
   - **Contract text → Navy hull:** regex plus a name gazetteer. 26/26 correct on a hand sample
     drawn after the rules were fixed.
   - **AIS → Coast Guard:** call-sign matching, gated on IMO or name agreement. 180/180 correct
     across three random review samples. 4,117 of 4,922 vessels matched.
   - **Coast Guard inspection record → register:** exact official number.
   - **Navy hull → AIS:** contracts and AIS share no ID, so each hull's Wikipedia infobox IMO and
     MMSI must equal the AIS record's.
     - 7 links, 0 conflicts. The call sign, which the rule doesn't use, agrees on all 7.
     - The other 147 hulls are reported as a miss: their IDs aren't in commercial AIS.
   - **Legal entities → curated firms:** dated ownership, covering 98.7% of award dollars.
4. **Analyses on top of the graph:**
   - **Navy repair cost-growth ledger** (436 availabilities), with an early-warning model. Tested
     on later years, with leakage controls and unfinished jobs handled as censored.
   - **Tug activity hours from AIS**, compared with the Port of LA's emissions inventory.
   - **Close-quarters encounters (CPA/TCPA).** About 2 seconds per AIS day. Separates predicted
     alerts from real close passes. Feeds a **collision-risk model**.
   - **Weather and fishing**, using NOAA buoys and archived forecasts. The forecasts are read with
     a custom GRIB2/JPEG2000 decoder.
5. **A public site built around the data engineering:**
   - **Home ("One ship, many records"):** a scrolling picker of 25 vessels. Each shows its source
     records with the join rule, confidence and evidence, then the resolved vessel: its 2025 track,
     its contracts and its close calls.
   - **A funnel** from raw records to vessels.
   - **Findings** labelled with the joins they needed.
   - **A Data engineering page** covering sources and terms, join rules, held-out tests, misses and
     provenance.

## Results

- **Identity at scale.** 514.8M raw records resolve into 5,242 vessels. Every merge goes through a
  tested rule on a stable ID, and the precision is published (180/180, 26/26, 7/7 call-sign agreement).
- **Repair contracts meet ship tracks.** Linking Navy hulls to AIS puts a supply ship's repairs next
  to where it sailed. For example, USNS Henry J. Kaiser had 12 contracts worth $183M and 189
  close-quarters alerts in 2025.
- **Collision alerts.** Straight-line alerts come true **57%** of the time (80% when raised under 2
  minutes ahead, 44% at 5–10 minutes). A model using only information available when the alert fires
  ranks alerts much better: AUC **0.73 against 0.61**, trained on 2024 and tested on 752,017 alerts
  from 2025. At the same 90% catch rate it raises about 17% fewer false alarms. It holds on vessel
  pairs never seen in training and is well calibrated. The alerts are released as an open benchmark.
- **Service boats.** **59% of apparent large-ship close calls in San Pedro Bay involve service
  boats:** 156 small launches and bunker boats whose AIS type doesn't say what they are.
- **Repair cost growth.** Navy surface-ship repair jobs grow a median **8.3%** beyond their base award
  and pre-priced options, and one in ten grows **47%** or more. By day 180, "growth so far" alone cuts
  forecast error by 49%.
- **Tug hours.** Busy harbor tugs log about **1,600–1,850** active hours a year on AIS, against 1,387
  in the Port of LA inventory. GPS jitter and seasonality were tested and ruled out.
- **Weather and trip time.** On 2,373 coastal legs, an archived NOAA wave forecast cuts trip-time
  error by 0.22 hours (95% CI 0.08–0.38), against about 7 hours of scheduling-driven variation.
- **Fishing and ocean conditions.** Temperature fronts, chlorophyll and upwelling add a small,
  significant gain in predicting where fishing vessels work (AUC 0.922 → 0.944).

## What failed, and what I did about it

- **Hull extraction, development sample: 92.3%, below the 95% target.** Both errors were "DDG 51"
  used as a programme name rather than a ship. I fixed that, then scored the fix on a *new* sample
  drawn afterwards.
- **Early-warning model at 90 days: +14.7% against a pre-set 15% bar.** I reported it as a miss and
  didn't retune on the test years.
- **Schedule-slip label.** A model scored AUC 0.72, but the contracting office alone scores the same.
  The label mostly encodes how each office words its modifications, and the site says so.
- **Encounter validation.** Interpolating across gaps in thinned AIS can manufacture near-zero
  distances. Scenarios are ranked by the more conservative of two estimates, and about one alert in
  ten has an uncertain label. This is stated on the site.
- **The first encounter rules counted dredges with their tenders, and crew launches, as close
  calls.** Reviewing the closest cases led to three new rules.
- **Recall is reported next to precision.** Only 50% of U.S. AIS vessels match a Coast Guard record,
  because many small boats broadcast no call sign or IMO and the rules won't fall back to names. Only
  7 of 254 Navy hulls could be linked to AIS.
- **Data-source terms.** Two questions are recorded as open rather than assumed away: ERDDAP's
  robots.txt, and OEHHA's terms page, which is behind a CAPTCHA.

## Skills demonstrated

- **Entity resolution and record linkage** across five sources with no shared key. Merges are gated
  on stable IDs, every link carries confidence and provenance, and precision and recall are measured
  on held-out samples.
- **Data engineering:** a data-source register enforced by tests, snapshot manifests with hashes and
  licences, resumable throttled downloads, caching, a rebuild-from-scratch pipeline and 29 unit tests.
- **Text extraction from messy government records**, evaluated on held-out samples.
- **Geospatial and time-series processing at scale:** 514M AIS reports, resampling, a spatial grid for
  pair search, closest-point-of-approach maths, and GRIB2 decoding without GIS dependencies.
- **Modelling discipline:** time-based splits, leakage control, censoring, strong baselines, bootstrap
  confidence intervals and pre-registered success tests.
- **Front end:** React and TypeScript. An interactive record-by-record trace with a track map,
  accessible SVG charts on a colour-blind-checked palette in light and dark mode, a responsive layout
  and static deployment.

## What I would do next

- Extend the Navy-to-AIS bridge to military-type AIS broadcasts, which would link more of the 147
  unmatched hulls.
- Get feedback from autonomy and port practitioners on the encounter benchmark, and add higher-rate
  AIS to remove its interpolation label noise.
- Get **engine-hour or fuel data** from a tug operator, to turn activity hours into emissions.
- Add a **partner label** for repair jobs (the Navy's estimate or schedule days), so the model forecasts
  something public records don't already show.

---

## Résumé bullets

- Built **HarborLedger**, a public data pipeline and website that resolves five maritime sources with
  no shared key into one graph. Sources: Navy contracts, Wikipedia, AIS, and Coast Guard inspections
  and register. It takes 514.8M raw records down to 5,242 vessels, with confidence, method and
  provenance on every link. Stack: Python, SQLite, React/TypeScript, GitHub Pages.
- Designed **entity-resolution rules on stable IDs** (MMSI, IMO, call sign, official number, hull
  number) and measured them on held-out samples. 180/180 AIS-to-Coast-Guard matches correct; 26/26
  hull numbers extracted from contract free text correct. Linked Navy hulls to their AIS tracks
  through Wikipedia infobox IDs (7 links, 0 conflicts).
- Built a **data-source register enforced by tests** (terms, robots.txt, honest user-agent, no
  getting past blocks), plus snapshot manifests with SHA-256 hashes and licences, so every number
  traces back to its source files.
- Built a **collision-risk model** on 1.5M real-traffic close-quarters alerts. It beat the standard
  CPA/TCPA projection (AUC 0.73 vs 0.61; about 17% fewer false alarms at 90% recall), was validated
  on the following year and on unseen vessel pairs, and is published as an open benchmark (DOI).
- Built a **Navy repair cost-growth ledger** (436 jobs, median 8.3% growth) with an early-warning
  model tested under time-based splits and pre-registered targets, and reported where it missed.
  Joined 3.75M vessel-hours to NOAA buoys and archived wave forecasts, using a custom GRIB2 decoder.
