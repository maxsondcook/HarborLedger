# Busy harbor tugs move more than the port's emissions inventory assumes

**Finding.** AIS shows the busiest ship-assist tugs in San Pedro Bay moving about **1,600–1,850
hours a year** (mean 1,837 in 2024, 1,626 in 2025; medians 1,653 and 1,720). The Port of Los
Angeles's 2023 emissions inventory uses **1,387 hours** for its 11 assist tugs. That figure is
operator-reported engine hours. The gap is not GPS noise and not seasonality.

## Why it matters

Harbor-craft emissions inventories multiply engine hours by load factors and emission factors.
They feed port clean-air plans and California's harbor-craft rule, which caps some vessels at 1,300
hours a year within 2 miles of a disadvantaged community. If activity is understated, so are
emissions. An independent, public activity estimate is a useful cross-check.

## How it was measured

- **Tugs:** every AIS report from tug types (31, 32, 52) in California waters, all 366 days of
  2024 and 365 days of 2025: 248 and 246 tugs.
- **Time weighting:** each report is weighted by the time to the vessel's next report, capped at
  10 minutes.
- **Modes:** idle (< 0.5 kn), ship assist (within 350 m of a moving large ship), maneuvering
  (0.5–5 kn) and transit (5 kn or more).
- **"Active" hours:** everything but idle.
- **Bay assist tugs:** tugs spending at least half their time in San Pedro Bay with regular
  ship-assist hours. That gives 14 in 2024 and 17 in 2025.

| | 2024 | 2025 |
|---|---|---|
| Assist tugs | 14 | 17 |
| Active hours / year, mean | 1,837 | 1,626 |
| Active hours / year, median | 1,653 | 1,720 |
| Share of active hours within 2 miles of an SB 535 community | 92.6% | 89.7% |
| Busiest month ÷ quietest month (per tug) | 1.26 | 1.28 |

## What was ruled out

- **GPS jitter.** Raising the "moving" threshold from 0.5 to 2 knots lowers the July 2024 estimate
  from 2,071 to 1,678 hours, still above 1,387. Only about 8% of active hours sit at 0.5–1 kn.
- **Seasonality.** A July-only estimate first suggested a summer peak. With full years, the busiest
  month is only about 1.3 times the quietest, and July is about average.

## What it cannot settle

- **Movement versus engines.** AIS shows movement, not engine running time. Engines idling at
  a berth add engine hours that AIS never sees, which would make engine hours *higher*, not lower.
  An operator's engine hour-meter data would settle it.
- **Selection.** These 14–17 tugs are chosen because they assist ships, and they include Long
  Beach boats. The inventory's 11 tugs are those working Port of LA terminals in 2023.
- **Near-community hours.** Census tracts around the harbor extend over the water, so almost all
  port work counts as "near" in the 2-mile rule. This is an AIS movement measure, not a compliance
  finding.

## Reproduce

```bash
python3 -I run.py tug-activity 2024 2025
```

Results: `eval/tug_activity_results_YYYY.json`; site: Harbor activity page.
