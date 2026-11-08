# HarborLedger close-quarters encounter benchmark (v1)

[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.24047861.svg)](https://doi.org/10.5281/zenodo.24047861)

Real-traffic close-quarters alerts and outcomes for three California port areas (San Pedro Bay,
San Francisco Bay, San Diego Bay) for 2024 and 2025, built from public AIS. Each row is one alert
event: a pair of moving vessels whose straight-line projection (constant speed and course) put them
within 0.25 nm (463 m) of each other within 10 minutes, with the features known at that moment and
whether they actually came that close.

It is meant for evaluating collision-risk and alert-filtering methods against a real-traffic
baseline, and for studying the gap between straight-line predictions and what vessels actually do.

**Download:** [Zenodo, DOI 10.5281/zenodo.24047861](https://doi.org/10.5281/zenodo.24047861) or the [GitHub release `encounters-v1`](https://github.com/maxsondcook/HarborLedger/releases/tag/encounters-v1) (27 files, about 100 MB in total; check them with `shasum -a 256 -c SHA256SUMS`).

## Contents

| File | Description |
|---|---|
| `alerts_YYYY-MM.parquet` (24 files) | one row per alert event (schema below), one file per month |
| `scenarios_tracks.parquet` | AIS reports (local metres around vessel A) for the closest large-vessel encounters |
| `SHA256SUMS` | checksums |

| Year | Alert events | Traffic alerts (no service vessel) | Traffic alerts that came true |
|---|---|---|---|
| 2024 | 1,601,939 | 895,503 | 56.8% |
| 2025 | 1,533,461 | 865,576 | 57.1% |

Suggested split: train on 2024, test on 2025 (time-based, no shuffling across years).

Load a year with pandas: `pd.concat(pd.read_parquet(f) for f in sorted(glob.glob("alerts_2024-*.parquet")))`.

## Baselines (train 2024, test 2025)

Task: traffic alerts whose vessels are still more than 0.25 nm apart at the first alert
(n = 752,017 in 2025). Predict `realized`.

| Method | AUC | Precision at 90% recall |
|---|---|---|
| Straight-line rule (every alert is a warning) | 0.500 | 0.507 |
| Kinematic: logistic regression on CPA and TCPA | 0.610 | 0.531 |
| Gradient boosting on all alert-time features | 0.732 | 0.576 |

Code: `harborledger/collision.py` in https://github.com/maxsondcook/HarborLedger.

## Schema

| Column | Description |
|---|---|
| `day` | UTC date of the first alert |
| `region` | port area: san_pedro_bay, sf_bay or san_diego |
| `mmsi_a` | MMSI of vessel A (the lower MMSI of the pair) |
| `mmsi_b` | MMSI of vessel B |
| `type_a` | AIS vessel type of A |
| `type_b` | AIS vessel type of B |
| `len_a` | AIS length of A (m) |
| `len_b` | AIS length of B (m) |
| `t_first` | first alert time (epoch seconds, UTC) |
| `dist_first_m` | separation at the first alert (m) |
| `cpa_pred_m` | straight-line predicted closest point of approach at the first alert (m) |
| `tcpa_pred_s` | straight-line predicted time to CPA at the first alert (s) |
| `sog_a` | speed over ground of A at the first alert (kn) |
| `sog_b` | speed over ground of B (kn) |
| `cog_a` | course over ground of A (deg) |
| `cog_b` | course over ground of B (deg) |
| `rel_x_m` | east offset of B from A at the first alert (m) |
| `rel_y_m` | north offset of B from A (m) |
| `rel_speed_kn` | relative speed of the pair (kn) |
| `area_moving_vessels` | moving vessels in the port area in that minute |
| `neighbours_a` | vessels within 2 nm of A in that minute |
| `neighbours_b` | vessels within 2 nm of B |
| `geometry` | COLREGS-style geometry at the first alert: head-on, crossing, overtaking |
| `service` | 1 if either vessel is a tug/tow, dredge, diver, pilot, SAR, port tender or law-enforcement vessel |
| `pleasure_involved` | 1 if either vessel is AIS type 36/37 |
| `military_involved` | 1 if either vessel is AIS type 35 |
| `large_involved` | 1 if either vessel is cargo/tanker or at least 50 m |
| `launch_involved` | 1 if either vessel is a 'likely launch' (small non-pleasure vessel alongside >= 10 distinct large ships in the year). Computed from outcomes: do NOT use as a model feature |
| `realized` | LABEL: 1 if the pair actually came within 0.25 nm (463 m) after the alert |
| `min_sep_obs_m` | LABEL: observed minimum separation after the alert on 1-minute tracks (m) |
| `t_min_sep` | time of the observed minimum separation (epoch seconds) |
| `minutes` | number of alert minutes merged into the event (known only afterwards: do NOT use as a feature) |

## How the alerts were built

- Source: NOAA/BOEM MarineCadastre AIS broadcast points (CC0), filtered by MarineCadastre to
  about one report per vessel per minute.
- Moving vessels (SOG >= 1 kn) are resampled to a 1-minute grid (gaps up to 5 minutes bridged).
  Each minute, pairs within 2 nm get straight-line CPA/TCPA. Consecutive alert minutes for a pair
  (gaps up to 3 minutes) merge into one event.
- `realized` uses the observed minimum separation over the alert window plus 10 minutes.

## Known limitations

- AIS positions are antenna positions, not hull outlines.
- Thinning to about one report per minute means interpolated separations can be wrong. On a
  random sample of 400 alerts per year, recomputing at the actual report times changes the label
  for about 9% of alerts.
- Vessels without AIS (most small craft, warships that switch it off) are absent.
- `launch_involved` and `minutes` are derived from outcomes; they are for analysis, not features.

## Licence and citation

Derived from public-domain U.S. federal data (MarineCadastre AIS, CC0). Released under CC BY 4.0.
Cite as: HarborLedger close-quarters encounter benchmark v1 (2026). Zenodo. https://doi.org/10.5281/zenodo.24047861
