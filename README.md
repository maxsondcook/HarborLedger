# HarborLedger

**Case study and résumé bullets:** [docs/CASE_STUDY.md](docs/CASE_STUDY.md)

**Website plan (in progress):** a React site in `site/` that reads static JSON exported from the graph.
It has vessel and shipyard pages, the repair cost ledger, harbor activity, and a close-quarters
**encounter dataset** from AIS. Build it with
`python3 -I run.py export && npm --prefix site run build`.


A public-data ledger of U.S. Navy ship repair and construction contracts, linked to
vessels and firms, with confidence and provenance on every link. It is the identity
spine (weeks 1–2) of a six-week build plan that came out of the project's research phase.
Weeks 3–4 add the availability cost-growth ledger and early-warning model on top of it.

The design follows CROSSR: snapshot every source, assert identities as edges with a method
and confidence, merge only above a threshold, and keep hand overrides in version-controlled
CSVs.

## Local development (website)

```bash
npm --prefix site install          # first time only
npm --prefix site run dev          # http://localhost:5173/HarborLedger/ (hot reload)
```

- **Page edits:** change files in `site/src/` (pages in `site/src/pages/`, charts in `site/src/components/charts.tsx`, colours and layout in `site/src/styles.css`). The browser updates as soon as you save.
- **Data changes:** rebuild the database with `python3 -I run.py build && python3 -I run.py growth`, regenerate the JSON with `python3 -I run.py export`, then refresh the page.
- **Production build:** `npm --prefix site run build`, which writes `site/dist/`.

## Run

All commands use isolated Python (`-I`); `run.py` adds the project to `sys.path` itself.

```bash
python3 -I harborledger/run.py pull-txns harborledger/data/raw/usaspending/awards/navy_336611_US_ge5m_FY15-26.json
python3 -I harborledger/run.py build
python3 -I harborledger/run.py evaluate
python3 -I -m pytest -q harborledger/tests
```

`pull-txns` can be resumed, and a second worker can run with `--reverse`. `build` rebuilds
`data/harborledger.sqlite` from scratch, using the raw snapshots and the curated tables.

## Layout

| Path | What it holds |
|---|---|
| `data/raw/` | Untouched source snapshots: the USAspending award search, per-award transaction histories and the Wikipedia ship lists |
| `data/raw/manifest.jsonl` | One row per snapshot: source, endpoint, query, fetch time, sha256 and licence |
| `curated/firms.csv` | The curated firm table (70 firms) |
| `curated/recipient_firm.csv` | Maps recipient UEIs to firms. SAM parent data is unreliable: for example, Austal USA's parent is listed as Computershare |
| `curated/firm_parent.csv` | Dated ownership edges, such as Continental Maritime: HII → Titan → Vigor, and Vigor: Lone Star → Antin |
| `curated/hull_gazetteer_extra.csv` | Decommissioned and transferred ships missing from the current-ship lists |
| `harborledger/hulls.py` | Hull, ship-name, availability-type and FY extraction, plus the name gazetteer |
| `harborledger/build.py` | Builds the graph |
| `harborledger/evaluate.py` | Week 1–2 success tests |
| `eval/hull_sample_*.csv` | Hand-labelled samples: 2026 is the development sample, 2027 is held out |
| `eval/results.json` | Latest test results |
| `harborledger/ledger.py` | Availability ledger: growth labels, delay keywords, early-window features |
| `harborledger/model.py` | Time-split growth model, baselines, delay proxy, censoring report |
| `eval/growth_model_results.json` | Results for weeks 3–4 |
| `eval/growth_predictions_w90.csv`, `eval/growth_predictions_w180.csv` | Test-set predictions for each availability |

## Graph model (SQLite)

- **Nodes:** `contract`, `contract_action` (each modification), `organization` (`uei:` legal entities and `firm:` curated firms), `vessel` (`hull:DDG-105`), `identifier`.
- **`edge` table:** columns are `src, rel, dst, confidence, method, source_ref, valid_from, valid_to, license, evidence`.
- **Relations:** `AWARDED_TO` (contract → UEI), `PART_OF` (UEI → firm, firm → parent, dated) and `ABOUT_VESSEL` (contract → hull).
- **Threshold:** `ABOUT_VESSEL` edges below 0.5 are kept for audit but are not counted as vessel links. Bare mentions of a lead ship's hull, such as "DDG 51", usually mean the whole class or program.

## Week 1–2 success tests (set before testing)

| Test | Target | Result |
|---|---|---|
| Hull precision, fresh hand sample | ≥ 95% | **Held-out sample (seed 2027): 26/26 = 100%** (Wilson 95% CI 87–100%); recall 87% |
| Hull precision, development sample (seed 2026) | — | 92.3% before the program-reference fix, 100% after (25/25) |
| Award dollars mapped to a curated firm | ≥ 90% | **98.7%** ($388B universe; 69 of 207 recipients curated) |

The development sample failed at first, because both of its false positives were "DDG-51" used
as a program name. The fix was then scored on a second sample drawn afterwards, so the
held-out result is not tuned to the errors it fixed.

All the labels are mine, made by reading each description. A second labeller has not
checked them.

## Weeks 3–4: cost-growth ledger and early-warning model

```bash
python3 -I harborledger/run.py growth   # builds the availability table, writes eval/growth_model_results.json
```

### Ledger (`availability` table)

The ledger takes the 1,965 contracts and keeps, in turn:

| Filter | Contracts left |
|---|---|
| Linked to exactly one hull with confidence ≥ 0.5 | 954 |
| Repair availability type | 522 |
| Not a nuclear hull | 514 |
| Not a planning contract | 509 |
| Base obligation ≥ $5M | **436 availabilities** |
| Closed, which here means the period of performance ended by 2026-08-08: the data cut-off minus DoD's 90-day reporting lag | **397** |

The other 39 are still open and are treated as censored. Their mean growth so far is +29%, which is a lower bound.

**Label:** `g_exopt = (total − base − options) / (base + options)`. This is cost growth beyond the base award and the options the Navy priced in advance.

**Results on the 397 closed availabilities:**
- Median **+8.3%**, interquartile range −1.5% to +22.3%, 90th percentile +47%.
- California's 68 availabilities have a median of **+7.2%**. That matches the Phase 3 hand-pull (+7.5%, n=63).
- By type: regular overhauls (ROH, 105) average +18.4%, mid-term availabilities (MTA, 100) +13.1%, SRAs (75) +19.6%, DSRAs (39) +17.9%.

**Robustness label:** `g_exopt_noC` leaves out funding-only actions, because those can be incremental funding of work that was already planned.

### Early-warning model (results fixed in `eval/growth_model_results.json`)

**Setup, fixed before testing:**
- **Training data:** availabilities starting in FY2021 or earlier (237).
- **Test data:** availabilities starting FY2022 or later and already closed (160).
- **Features:** only actions dated within 90 or 180 days of the first action. These cover growth so far, counts and dollars by modification type, keyword counts, availability type, hull class, firm, base size and start year.
- **Model:** a gradient-boosted model of the growth still to come, with absolute-error loss. Nothing was tuned on the test years.

| Window | Label | Global-median MAE | Persistence MAE | Model MAE | Model gain over global median | Pre-registered test (≥ 15%) |
|---|---|---|---|---|---|---|
| 90 d | g_exopt | 0.206 | 0.188 | 0.176 | **+14.7%** (95% CI 4–25%) | **Fail** (just short) |
| 90 d | g_exopt_noC | 0.209 | 0.182 | 0.171 | +18.2% (9–28%) | Pass |
| 180 d | g_exopt | 0.207 | 0.106 | 0.104 | +49.9% (41–60%) | Pass |
| 180 d | g_exopt_noC | 0.211 | 0.103 | 0.100 | +52.5% (42–64%) | Pass |

What the table shows:

- **Day 90 misses the gate.** The headline label falls just short of the 15% bar.
- **Day 180 passes, but the model isn't why.** Most of the gain comes from *persistence*: by day 180 most of an availability's growth is already on the books, and "final = growth so far" captures it.
- **The model barely beats persistence.** Its extra gain over persistence is small at both windows, and the 95% confidence interval includes zero at both.

The honest summary is that public modification histories make cost growth visible early. They do not, yet, make it forecastable beyond extrapolating what is already visible.

### Delay proxy (secondary label)

The label is whether any modification after day W mentions an extension, a period-of-performance change, redelivery or a late-delivery penalty.

- **The hits are mostly real:** hand review of 25 found mostly genuine extensions, such as "EXTEND POP", "SETTLE RCCS AND EXTEND POP", "EXERCISE PENALTIES … INCOMPLETE SCHEDULE".
- **The rates move with how each contracting office writes:** 6% at N40345 against 77% at N00024.

| Window | Rate (test) | Model AUC | Office-rate-only AUC | Growth-so-far AUC |
|---|---|---|---|---|
| 90 d | 41% | 0.716 | **0.720** | 0.43 |
| 180 d | 30% | 0.797 | 0.751 | 0.40 |

- **At 90 days, the model is largely learning office writing style**, not ship condition.
- **Availabilities flagged late do end with more cost growth:** a median of +14.8% against +7.2%.
- **A real delay label in days still needs a partner,** such as SWRMC/NAVSEA schedules or a FOIA request.

## Week 5: commercial vessel graph and AIS tug activity hours

```bash
python3 -I harborledger/run.py pull-ais 2024-07-01 2024-07-31   # ~80 s/day; national file deleted after filtering
python3 -I harborledger/run.py match-psix                       # cached, resumable, ~1 call/s
python3 -I harborledger/run.py tug-activity
python3 -I harborledger/run.py build
```

### Data

| Source | Contents |
|---|---|
| MarineCadastre AIS, July 2024 (31 days) | California waters only (lat 32.4–38.6, lon −123.3 to −116.9): 0.75–0.82M positions/day, 448 MB on disk |
| SB 535 disadvantaged communities, 2022 | 2,255 census tracts from the Caltrans mirror of the OEHHA layer, rasterized at 200 m with a distance transform |

### AIS → USCG PSIX matching (`data/derived/psix_matches.csv`, `eval/psix_match_results.json`)

**Full-year update (2024).** The run covered 3,309 commercial vessels.
- **Matched:** 2,717 `SAME_AS` (82.1%): foreign ships 93.9%, U.S. vessels 54.1%.
- **Held back:** 67 matches, as `POSSIBLE_SAME_AS`.
- **Precision:** a second review sample of 60 vessels first seen outside July was also 60/60 correct, so the combined result is **120/120** (Wilson 95% CI 96.9–100%). One case is a renamed ship (AIS DALLY, PSIX ARIA, same IMO).
- **Graph after the rebuild:** 6,971 vessel nodes and 6,817 edges.

The July-only figures below are kept for the record.


The run covered 1,216 commercial vessels: tugs and tows, passenger, cargo, tanker and fishing.

**Matching rule.** A match is accepted as `SAME_AS` only if the call sign hits and either the IMO number agrees or the name similarity is at least 0.8. Weaker call-sign hits become `POSSIBLE_SAME_AS` and are kept for review.

**What was linked.**
- 895 `SAME_AS` matches, a recall of 73.6%.
- By flag: foreign ships 95.5%, U.S. vessels 56.7%.
- By type: cargo 96.5%, tankers 94.4%, tugs 72.1%, passenger 71.8%, fishing 29.3%.

**What was held back.** 28 matches are `POSSIBLE_SAME_AS`. All 15 inspected are plainly different vessels, such as J M HIDALGO against CAPTAIN TRAVIS: a call sign later reused by another vessel. The gate catches exactly the failure seen in Phase 3.

**Precision test (target ≥ 97%).** The test passes: **60 of 60** randomly sampled `SAME_AS` matches are correct (Wilson 95% CI 94–100%).
- The review could only check name, IMO, call sign and service type.
- Several "type disagreements" are real ships that AIS miscategorises. Sportfishing party boats, for example, broadcast "fishing" but are inspected passenger vessels.

**Graph.** It now holds 2,462 vessel nodes and 4,223 edges, including `SAME_AS`, `POSSIBLE_SAME_AS` and `ACTIVE_IN` (tug → port area, with hours).

### Tug activity hours (`eval/tug_activity_results.json`, `eval/tug_activity_by_vessel.csv`)

AIS saw 172 tugs in California in July 2024.

| Mode | Hours |
|---|---|
| Idle (< 0.5 kn) | 56,568 |
| Assist proxy | 2,324 |
| Maneuver | 3,958 |
| Transit | 7,969 |

How the categories are defined:
- **Assist proxy:** within 350 m of a moving large ship. The radius was set before the run, to allow for antenna offset on long ships.
- **Disadvantaged-community share:** 57.7% of all active tug hours fall within 2 miles of an SB 535 tract.

**San Pedro Bay ship-assist tugs (14).** These are tugs that spend at least half their time in the bay and log at least one assist-proxy hour per three days observed.
- Annualized AIS-active hours (SOG ≥ 0.5 kn): **mean 2,071, median 2,101**, interquartile range 1,564–2,722.
- **89%** of those hours fall within 2 miles of a disadvantaged community.

**Full-year update (2024, 366 days).** The 14 bay assist tugs selected over the whole year averaged **1,837 active hours (median 1,653, IQR 1,494–2,130)**. These are actual annual totals, not one month scaled up.
- **Season is ruled out:** monthly activity per tug varies only 1.26× between the busiest and quietest month, and July is about average.
- **What remains:** the gap with POLA (+32% on the mean, +19% on the median) comes from tug selection, the 2023 vs 2024 year, and movement vs engine hours.
- **Near-DAC share:** 92.6% of these tugs' active hours fall within 2 miles of a DAC, and 12 of the 14 exceed 1,300 near-DAC hours.
- **Coverage:** 248 tugs were seen across the year.

**Benchmark test (July only): compare with POLA and explain the gap.** The Port of LA's 2023 inventory reports **1,387 h/yr** average for 11 assist tugs. AIS is about 49% higher. The gap is partly explained:
- **Not jitter.** Raising the speed threshold to 1 kn gives a mean of 1,899 h. At 2 kn it is 1,678 h, still above POLA. Only 8% of active hours sit at 0.5–1 kn, and about 12% of the 0.5–2 kn hours show near-zero actual movement.
- **Season.** July is peak season, so annualizing one month overstates the year. Testing this needs other months.
- **Selection.** The 14 tugs are chosen *because* they assist ships, and they include Long Beach tugs. POLA's 11 tugs are the ones working its own terminals. Seven of the 14 exceed 2,300 h; the three lowest are below 1,400.
- **Definitions.** POLA's figure is operator-reported *engine* hours for 2023. This is AIS *movement* time in 2024. If engines run during every movement, engine hours should be at least AIS hours. A tug fleet's engine hour-meter data would settle it.

**CARB E4 implication (an inference, not a compliance finding).** Port waters fall *inside* DAC tracts. The Wilmington and POLA main channel cells are at distance 0, and so is West Oakland. So almost all harbor work counts toward the 1,300 h "near a DAC" cap.
- 11 of the 14 assist tugs would exceed 1,300 near-DAC hours on an AIS-annualized basis.
- The cap only applies to Tier 4 vessels holding an E4 extension, and these are movement hours, not engine hours.

## Site week 3: close-quarters encounters (full year 2024)

```bash
python3 -I run.py encounters 2024-07     # ~40 s for a month (vectorized; ~2 s/day)
python3 -I run.py export && npm --prefix site run build
```

The detector looks at moving vessels (at least 1 kn) in San Pedro Bay, SF Bay and San Diego Bay.
- **Resampling:** each track is resampled to 1 minute, bridging gaps of up to 5 minutes.
- **Pair search:** nearby pairs (within 2 nm) are found with a spatial grid.
- **Prediction:** closest point of approach (CPA) and time to it (TCPA) come from extrapolating speed and course in a straight line.

**Definitions.**

| Term | Meaning |
|---|---|
| Alert | Predicted CPA under 0.25 nm within 10 minutes |
| Encounter | An alert where the vessels actually came within 0.25 nm |
| Service interactions | Tug, pilot, search and rescue, port tender or law enforcement involved. Kept separate, because these vessels work close to ships by design |

| 2024 (366 days) | Value |
|---|---|
| Traffic alerts | 895,503 (+706,436 service alerts: tug, pilot, dredging, diving, law enforcement) |
| Traffic encounters (< 0.25 nm) | 508,425 |
| Alerts that came true | **57%**: 80% if raised < 2 min ahead, 62% at 2–5 min, 44% at 5–10 min (July alone: 56%, same pattern) |
| Encounters per 1,000 moving-vessel hours | San Diego 2,813 · SF Bay 1,424 · San Pedro Bay 547 |
| Share involving a pleasure craft | 87% · 68% · 59% |
| Likely launch or service boats | 156 vessels. They are behind 59% of large-vessel encounters in San Pedro Bay, 28% in SF Bay and 25% in San Diego |
| Large-vessel encounters < 185 m per 1,000 h (no pleasure, military or launches) | SF Bay 13.2 · San Diego 4.1 · San Pedro Bay 3.7 |

A **likely launch** is a small (≤ 35 m or unknown length), non-pleasure vessel that came within a quarter mile of 10 or more different large ships during the year. Crew launches and bunker boats usually broadcast "passenger" or "other" as their AIS type. Without this rule they made up most of the apparent close calls with tankers.

**What the numbers mean.** A straight-line projection has a high false-alarm rate, and it rises with how far ahead the alert is raised. That is the baseline any collision-avoidance model has to beat.

**Validation.** I took a random sample of 400 traffic alerts from the full year (`eval/encounter_validation.json`). For each, the other vessel's position was recomputed at every actual report time and compared with the detector's 1-minute grid.
- Median difference in closest pass: 28 m; 90th percentile: 335 m.
- The encounter/not-encounter label agrees in **90.2%** of cases (39 disagreements; 13 within 100 m of the threshold, the rest from interpolating across reporting gaps). A July-only sample of 120 gave 96.7%.
- So roughly one alert in ten has an uncertain label with this thinned data.
- MarineCadastre thins AIS to about one report every 1–3 minutes, so this check measures sensitivity to the time grid. It is not independent of interpolation.

**Scenario pages.** These list the 200 closest large-vessel passes, ranked by the more conservative of the two estimates. Interpolating across reporting gaps can manufacture near-zero distances, which is why the ranking takes the larger value.

**Notable cases.**
- Several of the closest passes involve small passenger-typed boats coming alongside tankers. These are probably crew launches, and AIS vessel types cannot separate them from traffic.
- One San Diego case is a Navy unmanned minesweeping surface vessel (MCMUSV-05) in close formation with a warship.

## Known gaps

- **Recall misses:** hull ranges ("SSN 807-809"), LCAC craft numbers, bare follow-on numbers ("72 AND 74 PIAS"), and "LCS 2&4", which the class-lead rule now suppresses.
- **Firm long tail:** 138 small recipients are not mapped. They hold 1.3% of dollars.
- **Ownership dates:** some are approximate and rest on single trade-press sources (see the `source` column).
- **Wikipedia:** ship names from Wikipedia are CC BY-SA. That only matters if this graph is redistributed commercially, and the licence column flags it.
- **USAspending lag:** DoD data runs about 90 days behind, so recent quarters are incomplete.
- **Test-year bias:** the test years are biased toward short availabilities, because long FY24–26 jobs are still open (censored).
- **Unmeasured costs:** growth is measured against obligations, not costs. Modifications record when money was committed, not when the work happened.
- **One month of AIS:** July only, and annualized hours assume July is typical. They also run 2024 data against a 2023 benchmark.
- **Hours that aren't engine hours:** AIS can't see engine state, so "active hours" are movement time.
- **Uncertain disadvantaged-community boundaries:** the boundaries use tract polygons, which extend over water. CARB may measure "within 2 miles" differently, and that hasn't been checked with CARB.
- **What would improve the model:** a partner label (the Navy's independent government estimate, schedule days or the causes of growth) would help more than more features.
