# Most "close calls" with large ships are service boats doing their job

**Finding.** When you count close passes between large ships and other vessels from public AIS
data in California ports, a large share are small service boats deliberately coming alongside:
crew launches, bunker and supply boats. In San Pedro Bay (Los Angeles/Long Beach) they account for
**59% of large-vessel encounters in 2024 and 54% in 2025**. Their AIS vessel type usually says
"passenger" or "other", not "service", so a naive near-miss analysis counts them as traffic risk.

## Why it matters

Near-miss counts from AIS are used, or proposed, for port risk assessments, waterway management
and training data for collision avoidance. If service work is mixed in, risk looks higher than it
is, and the "dangerous" cases a model learns from are mostly routine operations.

## How it was measured

1. **Encounters.** A close-quarters detector runs on every minute of 2024 and 2025 AIS for San
   Pedro Bay, San Francisco Bay and San Diego Bay. An encounter is a pair of moving vessels whose
   straight-line projection put them within 0.25 nm within 10 minutes, and which then came that
   close. There were 508,425 traffic encounters in 2024 and 494,462 in 2025.
2. **Known service types are removed first.** Tugs, tows, dredges, divers, pilots, search and
   rescue, port tenders and law enforcement are excluded using their AIS types.
3. **Likely launches.** Small vessels (35 m or less, or unknown length) that are not pleasure craft
   and came within a quarter mile of **10 or more different large ships** in the year are flagged as
   likely launches or service boats. That flagged 156 vessels in 2024 and 159 in 2025.
4. **What reviewing the closest cases showed.** The rule came from looking at the closest
   large-vessel passes. The same few small boats appeared alongside dozens of different tankers;
   dredges worked with their tenders; a Navy warship ran in close formation with an unmanned
   minesweeping vessel.

| Port area | Large-vessel encounters 2024 | Share involving a likely launch, 2024 | 2025 |
|---|---|---|---|
| San Pedro Bay | 4,016 | **58.8%** | 53.7% |
| San Francisco Bay | 22,629 | 27.6% | 28.2% |
| San Diego Bay | 7,013 | 24.9% | 27.3% |

Once pleasure craft, military vessels and likely launches are removed, large-vessel passes under
185 m per 1,000 moving-vessel hours were 13.2 (SF Bay), 4.1 (San Diego) and 3.7 (San Pedro Bay) in
2024. Before the launch rule the San Pedro figure was 20.0.

## Limits

- The launch rule is a heuristic. A busy ferry or excursion boat that meets many ships could be
  flagged, and a launch serving fewer than 10 ships a year is missed.
- AIS shows broadcasting vessels only. Many small boats do not broadcast.
- The rule uses outcomes over a whole year, so it suits analysis and benchmark cleaning, not
  real-time alert filtering.

## Reproduce

```bash
python3 -I run.py encounters 2024 2025
```

Results: `eval/encounter_results_YYYY.json`; site: Encounters page.
