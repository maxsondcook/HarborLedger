"""Entry point. Run with isolated Python from anywhere:

    python3 -I run.py <command> [args]

Rebuild everything from local raw data in dependency order (no network calls):
    python3 -I run.py all                 # build -> growth -> analyses -> export -> check
    python3 -I run.py all --list          # show the steps without running them
    python3 -I run.py all --from export   # resume from a step
Fetch steps (pull-*, match-psix, forecast-fetch) are separate: they are throttled, cached and
partly manual. `pull-wiki-ids` needs a built database, so on a fresh checkout run
`build`, then `pull-wiki-ids`, then `all`.

Commands:
    register-awards FILE   record an existing award-search JSON in the manifest
    pull-awards NAME       re-pull the national Navy 336611 >= $5M universe
    pull-txns FILE         pull transaction histories for every award in FILE (resumable)
    build                  build data/harborledger.sqlite from raw snapshots + curated tables
    eval-sample N SEED     write a fresh hand-labelling sample for hull extraction
    evaluate               run the week 1-2 success tests
    pull-ais START END     download national AIS days, keep California waters
    match-psix             gated AIS -> USCG PSIX matching for CA commercial vessels
    tug-activity [YEAR..]  AIS tug hours by mode, region and DAC proximity, per AIS year (default: all)
    encounters [YEAR..]    close-quarters encounters (CPA/TCPA) + validation, per AIS year (default: all)
    weather-join [YEAR..]  hourly vessel tracks joined to nearest NOAA buoy waves and wind, per AIS year
    weather                speed loss, coastal-leg delay model, small-craft departures, operability
    fishing                fishing activity vs SST, fronts, chlorophyll, upwelling and sea state
    forecast-fetch         download archived NOAA GFS-Wave forecasts for every coastal-leg departure
    forecast-legs          GFS-Wave forecast features along the reference route for each leg's departure
    export                 write static JSON for the website to site/public/data/
    growth                 build the availability ledger and run the weeks 3-4 growth model
    collision              collision-risk model (train 2024, test 2025)
    benchmark              write the open encounter benchmark files to data/benchmark/
    results                headline results table with confidence intervals (eval/headline_results.*)
    check                  integrity checks on the graph and the site JSON (exit 1 on any error)
    all [--list] [--from STEP]   the whole offline pipeline, in order
"""
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)  # -I drops the script dir from sys.path; add the project explicitly


# Offline pipeline, in dependency order. Each step is a run.py command.
PIPELINE = [
    ("tug-activity", "AIS tug hours per year (build reads these for ACTIVE_IN edges)"),
    ("build", "graph from raw snapshots, curated tables, PSIX matches and tug hours"),
    ("growth", "availability ledger and growth model (needs build)"),
    ("evaluate", "hull-extraction success tests (needs build)"),
    ("encounters", "close-quarters encounters and validation per year"),
    ("weather-join", "vessel-hours joined to NOAA buoys per year"),
    ("weather", "speed loss, small craft; writes the coastal legs (needs weather-join)"),
    ("forecast-legs", "GFS-Wave features per coastal leg (needs weather + cached forecasts)"),
    ("weather-final", "re-run weather so the leg model uses the fresh forecast features"),
    ("fishing", "fishing vs ocean conditions"),
    ("collision", "collision-risk model (needs encounters)"),
    ("benchmark", "open encounter benchmark files (needs collision)"),
    ("export", "site JSON (needs build, growth and the analyses)"),
    ("results", "headline results table with CIs (needs the eval outputs)"),
    ("check", "integrity checks on the graph and site JSON"),
]
ALIASES = {"weather-final": "weather"}


def run_all(args):
    names = [n for n, _ in PIPELINE]
    if "--list" in args:
        for i, (n, d) in enumerate(PIPELINE, 1):
            print(f"{i:2}. {n:<14} {d}")
        return 0
    start = 0
    if "--from" in args:
        step = args[args.index("--from") + 1]
        if step not in names:
            print(f"unknown step {step!r}; steps: {', '.join(names)}")
            return 1
        start = names.index(step)
    t_all = time.time()
    for n in names[start:]:
        print(f"\n=== {n}", flush=True)
        t = time.time()
        rc = main([ALIASES.get(n, n)])
        print(f"=== {n} done in {time.time() - t:.0f} s", flush=True)
        if rc:
            print(f"stopped at {n} (exit {rc}); resume with: python3 -I run.py all --from {n}")
            return rc
    print(f"\npipeline finished in {(time.time() - t_all) / 60:.1f} min")
    return 0


def main(argv):
    if not argv:
        print(__doc__)
        return 1
    cmd, args = argv[0], argv[1:]
    if cmd == "register-awards":
        from harborledger import snapshot, usaspending
        import time
        path = os.path.abspath(args[0])
        ts = time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(os.path.getmtime(path)))
        print(snapshot.record(path, "usaspending", "/search/spending_by_award/",
                              {"filters": usaspending.NAVY_336611_GE5M}, fetched_at=ts))
    elif cmd == "pull-awards":
        from harborledger import usaspending
        print(usaspending.pull_awards(args[0]))
    elif cmd == "pull-txns":
        from harborledger import usaspending
        usaspending.pull_all_transactions(os.path.abspath(args[0]), reverse="--reverse" in args)
    elif cmd == "build":
        from harborledger import build
        build.build()
    elif cmd == "eval-sample":
        from harborledger import evaluate
        evaluate.write_sample(int(args[0]), int(args[1]))
    elif cmd == "pull-ais":
        import datetime as dt
        from harborledger import ais
        ais.fetch_range(dt.date.fromisoformat(args[0]), dt.date.fromisoformat(args[1]))
    elif cmd == "tug-activity":
        from harborledger import activity, years
        for y in ([int(a) for a in args] or years.years_available()):
            print(f"== tug activity {y}", flush=True)
            activity.run(y)
    elif cmd == "match-psix":
        import glob
        from harborledger import psix, ais
        files = sorted(glob.glob(os.path.join(ais.CA_DIR, "ais-ca-*.parquet")))
        os.makedirs(os.path.join(HERE, "data", "derived"), exist_ok=True)
        psix.run_matching(files, os.path.join(HERE, "data", "derived", "psix_matches.csv"),
                          log=lambda s: print(s, flush=True))
    elif cmd == "encounters":
        from harborledger import encounters, years
        for y in ([int(a) for a in args] or years.years_available()):
            print(f"== encounters {y}", flush=True)
            encounters.run(y, log=lambda s: print(s, flush=True))
            print(encounters.validate(y), flush=True)
    elif cmd == "weather-join":
        from harborledger import weather, years
        for y in ([int(a) for a in args] or years.years_available()):
            print(f"== vessel-hours + sea conditions {y}", flush=True)
            weather.run(y)
    elif cmd == "weather":
        from harborledger import weather
        r = weather.analyze()
        print({k: r[k] for k in ("coverage", "legs")}, r["leg_model"]["mae_hours"], flush=True)
    elif cmd == "fishing":
        from harborledger import fishing
        r = fishing.run()
        print(r["models"], r["auc_gain_from_ocean_ci95"], flush=True)
    elif cmd == "forecast-fetch":
        import pandas as pd
        from harborledger import forecast as fc
        legs = pd.read_parquet(os.path.join(HERE, "data", "derived", "coastal_legs.parquet"))
        fc.fetch_cycles([fc.cycle_for(t) for t in legs.depart], log=lambda s: print(s, flush=True))
    elif cmd == "forecast-legs":
        import pandas as pd
        from harborledger import forecast as fc, weather
        legs = pd.read_parquet(os.path.join(HERE, "data", "derived", "coastal_legs.parquet"))
        v = pd.concat([pd.read_parquet(os.path.join(HERE, "data", "derived", f"vessel_hours_conditions_{y}.parquet"))
                       for y in (2024, 2025)])
        route = fc.reference_route(weather.open_water_big(v))
        route.to_csv(os.path.join(HERE, "eval", "reference_route.csv"), index=False)
        out = fc.leg_features(legs, route)
        out.to_parquet(os.path.join(HERE, "data", "derived", "coastal_legs_forecast.parquet"), index=False)
        print(len(out), "legs;", int((out.fc_steps > 0).sum()), "with forecasts", flush=True)
    elif cmd == "pull-wiki-ids":
        from harborledger import bridge, db
        con = db.connect()
        bridge.fetch(con, log=lambda s: print(s, flush=True))
    elif cmd == "export":
        from harborledger import export
        export.export()
    elif cmd == "growth":
        from harborledger import model
        model.run()
    elif cmd == "collision":
        from harborledger import collision
        r = collision.run()
        print({m["model"]: m["auc"] for m in r["models"]}, flush=True)
    elif cmd == "benchmark":
        from harborledger import benchmark
        benchmark.build()
    elif cmd == "results":
        from harborledger import results
        results.run()
    elif cmd == "check":
        from harborledger import checks
        return 1 if checks.run() else 0
    elif cmd == "all":
        return run_all(args)
    elif cmd == "evaluate":
        from harborledger import evaluate
        evaluate.run()
    else:
        print(__doc__)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
