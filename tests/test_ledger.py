import datetime as dt
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harborledger import ledger  # noqa: E402


def act(date, mod, typ, amt, desc=""):
    return {"action_date": date, "mod_number": mod, "action_type": typ, "obligation": amt,
            "description": desc}


ACTS = [
    act("2024-11-22", "0", None, 100.0, "USS GREEN BAY (LPD 20) FY25 DSRA"),
    act("2025-01-21", "A00002", "G", 20.0, "EXERCISE OPTIONS"),
    act("2025-02-10", "A00003", "B", 6.0, "SETTLE GROWTH WORK VIA RCCS"),
    act("2025-03-01", "A00004", "C", 4.0, "FUNDING ONLY"),
    act("2025-09-01", "A00005", "D", 12.0, "NEW WORK RCC; EXTEND POP"),
    act("2025-12-01", "A00006", "B", -2.0, "DESCOPE ITEM 123"),
]


def test_label_definitions():
    s = ledger.summarize(ACTS)
    assert s["base"] == 100 and s["options"] == 20 and s["total"] == 140
    assert abs(s["g_total"] - 0.40) < 1e-9
    assert abs(s["g_exopt"] - (140 - 100 - 20) / 120) < 1e-9          # 0.1667
    assert abs(s["g_exopt_noC"] - (140 - 100 - 20 - 4) / 120) < 1e-9  # 0.1333
    assert s["n_mods"] == 5 and s["n_growth_kw"] == 2 and s["n_delay_kw"] == 1
    assert s["n_descope_kw"] == 1


def test_window_features_ignore_later_actions():
    first = dt.date(2024, 11, 22)
    f90 = ledger.window_features(ACTS, first, 90)     # through 2025-02-20
    assert f90["n_mods_w"] == 2                       # the option and the 2025-02-10 growth mod
    assert abs(f90["g_w"] - 6 / 120) < 1e-9
    assert f90["n_delay_kw_w"] == 0                   # the Sept extension is not visible yet
    f180 = ledger.window_features(ACTS, first, 180)
    assert f180["n_mods_w"] == 3


def test_fiscal_year():
    assert ledger.fy(dt.date(2024, 11, 22)) == 2025
    assert ledger.fy(dt.date(2025, 9, 30)) == 2025


def test_psix_helpers():
    from harborledger import psix
    assert psix.imo_valid("IMO9686754") == "9686754"
    assert psix.imo_valid("IMO0000001") == ""          # placeholder
    assert psix.imo_valid("1234568") == ""             # bad check digit (1234567 is valid)
    assert psix.norm_name("M/V  Sea-Change") == "SEA CHANGE"


def test_seasonal_scales_partial_months():
    import pandas as pd
    from harborledger import activity
    mon = pd.DataFrame([
        (1, "2024-01", "san_pedro_bay", "assist", True, 10.0),
        (1, "2024-01", "san_pedro_bay", "idle", True, 99.0),     # idle is excluded
        (2, "2024-01", "san_pedro_bay", "transit", False, 20.0),
        (1, "2024-02", "san_pedro_bay", "assist", True, 3.0),
    ], columns=["mmsi", "month", "region", "mode", "near_dac", "hours"])
    out = activity.seasonal(mon, {"2024-01": 30, "2024-02": 3}, [1, 2])
    assert out["2024-01"]["mean_active_hours_per_tug_per_30d"] == 15.0   # (10 + 20) / 2
    assert out["2024-02"]["mean_active_hours_per_tug_per_30d"] == 15.0   # (3*10 + 0) / 2


def test_mvus_row_parsing_and_privacy(tmp_path):
    from harborledger import mvus
    row = ["494962", '"""COMPROMISE"""', "WDX1234", "1080967", "", "HULL1", "HIN1", "Towing Vessel", "US", "1",
           "19.0", "15", "36.4", "13.1", "6.1", "", "", "", "", "", "", "", "UNSPECIFIED", "ST CHARLES", "MO",
           "UNITED STATES"] + ["X"] + [""] * 14 + ["BUILDER INC", "", "1998", "", "", "", "UNITED STATES", "", "",
           "", ""] + ["332732", "Privacy", "Individual", "Privacy", "Privacy", "Privacy", "Privacy", "Privacy",
           "Privacy", "Privacy", "Privacy", "Green Cove Springs", "FL", "", "UNITED STATES", "32043", "", "",
           "Diesel", "Steel", "Monohull", "Ship", "Valid", "", "", ""]
    assert len(row) == 78
    p = tmp_path / "v.txt"
    import csv
    with open(p, "w", newline="", encoding="latin-1") as fh:
        csv.writer(fh).writerow(row)
    d = next(mvus.rows(str(p)))
    assert d["vessel_name"] == "COMPROMISE"
    assert d["coastwise_unrestricted"] == "X" and d["service"] == "Towing Vessel"
    assert d["org_name"] == ""                      # individual owner: no name kept
    assert "owner_city" not in mvus.KEEP and "person_last" not in mvus.KEEP


def test_cpa_tcpa_and_geometry():
    import numpy as np
    from harborledger import encounters as en
    # B 1000 m due north of A, closing head-on at 5 m/s relative: CPA 0 in 200 s
    cpa, t = en.cpa_tcpa(np.array([0.0]), np.array([1000.0]), np.array([0.0]), np.array([-5.0]))
    assert abs(cpa[0]) < 1e-6 and abs(t[0] - 200) < 1e-6
    # parallel offset 300 m, same speed: no closure, CPA = current distance
    cpa, t = en.cpa_tcpa(np.array([300.0]), np.array([0.0]), np.array([0.0]), np.array([0.0]))
    assert abs(cpa[0] - 300) < 1e-6 and t[0] == 0
    assert en.geometry(0, 180, 0, 180) == "head-on"
    assert en.geometry(0, 90, 45, 225) == "crossing"
    assert en.geometry(0, 10, 180, 0) == "overtaking"      # B dead astern of A, similar course


def test_raw_min_separation_interpolates_between_reports():
    import pandas as pd
    from harborledger import encounters as en
    # A sits still at the origin; B moves east along y=50 from x=-300 to x=300 over 120 s,
    # reporting only at the ends (60 s apart) -> closest pass 50 m at t=60 (A reports then).
    tr = pd.DataFrame([
        (1, 0, 0.0, 0.0), (1, 60, 0.0, 0.0), (1, 120, 0.0, 0.0),
        (2, 0, -300.0, 50.0), (2, 120, 300.0, 50.0),
    ], columns=["mmsi", "ts", "x", "y"])
    d = en.raw_min_separation(tr, 1, 2, 0, 0)
    assert abs(d - 50.0) < 1e-6
