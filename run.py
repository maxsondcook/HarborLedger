"""Entry point. Run with isolated Python from anywhere:

    python3 -I harborledger/run.py <command> [args]

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
    export                 write static JSON for the website to site/public/data/
    growth                 build the availability ledger and run the weeks 3-4 growth model
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)  # -I drops the script dir from sys.path; add the project explicitly


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
    elif cmd == "export":
        from harborledger import export
        export.export()
    elif cmd == "growth":
        from harborledger import model
        model.run()
    elif cmd == "evaluate":
        from harborledger import evaluate
        evaluate.run()
    else:
        print(__doc__)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
