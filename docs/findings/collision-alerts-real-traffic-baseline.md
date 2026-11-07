# Straight-line collision alerts are right about half the time. Context makes them better.

**Finding.** In real California port traffic, the standard straight-line close-quarters alert (a
predicted pass under 0.25 nm within 10 minutes, assuming constant speed and course) comes true for
**51% of alerts** raised while the vessels are still more than a quarter mile apart. A model using
only information available when the alert fires ranks alerts much better (AUC **0.73** against
**0.61** for predicted CPA and TCPA alone). At the same 90% catch rate it raises **about 17% fewer
false alarms**, and at 75% about 29% fewer. The result holds on vessel pairs never seen in
training, and for alerts involving large ships.

## Why it matters

Collision-avoidance systems, on crewed bridges and in autonomous vessels, start from a
closest-point-of-approach projection. Too many false alarms and operators tune them out; too few
and real risks are missed. Public, real-traffic evidence of how often the projection is right, and
how much context helps, is rare. This study supplies both, and the data is released as an open
benchmark ([data card](../benchmark/README.md)).

## Data

- **Source:** all of 2024 and 2025 California AIS (NOAA/BOEM MarineCadastre) for San Pedro Bay,
  San Francisco Bay and San Diego Bay. About 1.6 million alert events a year.
- **Traffic only:** tugs, tows, dredges, divers, pilots, search and rescue, port tenders and law
  enforcement are excluded, because they work close to ships by design.
- **Open alerts only:** pairs already within 0.25 nm at the first alert are excluded, since the
  outcome is already decided. That leaves 789,429 alerts in 2024 (training) and 752,017 in 2025
  (test).
- **Label:** the vessels then came within 0.25 nm, measured on 1-minute tracks.
- **Features (all known at the first alert):**
  - predicted CPA and TCPA, and current separation;
  - both speeds and courses, relative bearing, relative speed;
  - vessel-type pair and lengths;
  - port area, hour, weekday and month;
  - moving vessels in the area and each vessel's neighbours within 2 nm;
  - wave height and wind at the area's offshore NOAA buoy.
- **Leakage controls:** alert duration and the "likely launch" flag are excluded because they
  depend on what happened next.

## Results (train 2024, test 2025)

| Method | AUC | Precision at 90% recall | Precision at 75% recall |
|---|---|---|---|
| Straight-line rule (every alert) | 0.50 | 0.507 | — |
| Kinematic: logistic regression on CPA, TCPA | 0.610 | 0.531 | 0.560 |
| **Gradient boosting, all alert-time features** | **0.732** | **0.576** | **0.641** |

The gain over the kinematic baseline is +0.122 AUC (bootstrap 95% CI +0.121 to +0.123) and +4.4
points of precision at 90% recall (CI +4.3 to +4.5).

| Look-ahead | Alerts | Straight-line precision | Kinematic AUC | Model AUC |
|---|---|---|---|---|
| 0–2 min | 81,600 | 61.8% | 0.49 | **0.78** |
| 2–5 min | 276,550 | 58.5% | 0.57 | 0.74 |
| 5–10 min | 393,789 | 42.8% | 0.56 | 0.68 |

**Robustness checks:**
- **Vessel pairs never seen in training** (47% of the 2025 test set): AUC 0.72 against 0.62 for the
  kinematic baseline. The model is not just memorising regular pairs such as scheduled ferries.
- **Alerts involving large ships** (cargo, tanker or 50 m and longer; 71,525 alerts): AUC 0.74
  against 0.58.
- **Calibration:** in each tenth of predicted risk, the observed rate is within about 2 points of
  the prediction.

**What the model relies on** (drop in AUC when a feature is shuffled): current separation, TCPA,
predicted CPA, port area, course difference and the vessel-type pair. Sea state and traffic density
add little on their own.

## Limits

- **AIS thinning:** MarineCadastre filters AIS to about one report per vessel per minute.
  Recomputing separations at the actual report times flips the label for about 9% of alerts (random
  sample of 400 per year), so some label noise is built in.
- **Positions, not hulls:** AIS gives antenna positions, not hull outlines. A "pass within 463 m"
  is a proxy for close quarters, not a near-collision.
- **Ports only:** three California port areas. Open-ocean encounters behave differently.
- **Missing vessels:** non-AIS vessels (most small craft, warships with AIS off) are absent.

## Reproduce

```bash
python3 -I run.py encounters 2024 2025
python3 -I -c "import sys; sys.path.insert(0, '.'); from harborledger import collision; collision.run()"
```

Results: `eval/collision_model_results.json`; data: `harborledger-encounters-v1` (see the data card).
