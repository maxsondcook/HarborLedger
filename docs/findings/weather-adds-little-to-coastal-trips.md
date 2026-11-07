# Weather adds about an hour to a big ship's coastal trip. Schedules add far more.

**Finding.** On the roughly 375-nautical-mile coastal leg between the Los Angeles/Long Beach and
San Francisco approaches, large ships lose **3–7% of their speed in head seas of 3.5 m or more**
and almost nothing in beam or following seas. Predicting leg duration, a NOAA wave forecast
available at departure cuts the error by **0.22 hours** (95% CI 0.08–0.38). Perfect knowledge of
the actual conditions would cut it by **0.52 hours** (CI 0.38–0.66). The remaining error is about
**7 hours** on a 36-hour leg. Most variation in trip time is not weather: ships routinely slow down
to arrive when their berth is ready.

## Why it matters

Arrival-time prediction products often lead with weather. For coastal legs in California, the
evidence says weather is a minor, though real and forecastable, part of the delay. Berth scheduling
and speed choices dominate. Weather-routing value is concentrated in the few legs with heavy head
seas.

## Data

- **Ships:** 3.75 million vessel-hours of 2024–2025 California AIS, each joined to the nearest of
  15 NOAA buoys for waves and wind (within 75 km). From these, 380,278 steady open-water hours of
  3,622 cargo ships and tankers.
- **Legs:** 2,373 coastal legs (1,611 northbound, 762 southbound) from 842 ships, with no tracking
  gap over 3 hours. Median 35 hours and 375 nm.
- **Forecasts:** archived NOAA GFS-Wave forecasts (West Coast 0.167° grid, 11,470 files) from
  NOAA's open data on AWS. For each leg, the last 00Z or 12Z run before departure is sampled every
  6 hours, out to 48 hours, along a reference route of 17 waypoints. Only the wave-height and
  wave-direction GRIB2 messages are downloaded, and a small JPEG2000 decoder reads them, so no GRIB
  library is needed.

## Speed loss (median speed ÷ the same ship's usual speed in the same area and season)

| Head-sea wave height | Ratio | 95% CI | Hours |
|---|---|---|---|
| under 1 m | 1.007 | 1.006–1.008 | 10,894 |
| 2.5–3 m | 0.989 | 0.986–0.991 | 4,473 |
| 3–3.5 m | 0.979 | 0.974–0.984 | 2,489 |
| 3.5–4 m | 0.968 | 0.962–0.974 | 1,347 |
| 4–5 m | 0.963 | 0.956–0.972 | 811 |
| over 5 m | 0.928 | 0.910–0.950 | 158 |

Comparing each ship with itself in the same 0.5° cell and season absorbs the voluntary 10-knot
whale-protection zones that apply from May to December.

## Leg duration (train 2024, test 2025; mean absolute error)

| Predictor | Error |
|---|---|
| Distance ÷ ship's calm-weather speed | 7.6 h |
| Typical time for that direction | 7.5 h |
| Ship's own typical leg | 6.99 h |
| Model without sea conditions | 7.11 h |
| **Model + NOAA forecast at departure** | **6.89 h** |
| Model + conditions that actually occurred (ceiling) | 6.59 h |

## Limits

- **Buoys, not ships:** conditions come from the nearest buoy, not the ship, so shelter behind
  islands and headlands is smoothed over.
- **Wave direction differs:** the forecast's primary wave direction follows the dominant swell,
  while the buoys report mean direction.
- **California coast only:** this covers legs along the California coast, not ocean crossings,
  which AIS from U.S. coastal receivers does not see.

## Reproduce

```bash
python3 -I run.py weather-join 2024 2025
python3 -I run.py forecast-fetch
python3 -I run.py forecast-legs
python3 -I run.py weather
```
