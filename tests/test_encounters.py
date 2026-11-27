"""CPA/TCPA maths and encounter geometry: the foundation of the encounter benchmark."""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harborledger import encounters as enc  # noqa: E402


def test_head_on_collision_course_has_zero_cpa():
    # B is 1,000 m north of A, closing at 5 m/s: they meet in 200 s with zero separation
    cpa, tcpa = enc.cpa_tcpa(np.array([0.0]), np.array([1000.0]), np.array([0.0]), np.array([-5.0]))
    assert abs(cpa[0]) < 1e-9 and abs(tcpa[0] - 200.0) < 1e-9


def test_parallel_offset_pass():
    # B 300 m east and 1,000 m north, heading south at 5 m/s relative: closest pass 300 m at t = 200 s
    cpa, tcpa = enc.cpa_tcpa(np.array([300.0]), np.array([1000.0]), np.array([0.0]), np.array([-5.0]))
    assert abs(cpa[0] - 300.0) < 1e-9 and abs(tcpa[0] - 200.0) < 1e-9


def test_diverging_vessels_have_negative_tcpa():
    # B is ahead and moving away: the closest point was in the past
    cpa, tcpa = enc.cpa_tcpa(np.array([0.0]), np.array([500.0]), np.array([0.0]), np.array([3.0]))
    assert tcpa[0] < 0 and abs(cpa[0]) < 1e-9


def test_no_relative_motion_keeps_current_separation():
    cpa, tcpa = enc.cpa_tcpa(np.array([400.0]), np.array([300.0]), np.array([0.0]), np.array([0.0]))
    assert abs(cpa[0] - 500.0) < 1e-9 and tcpa[0] == 0.0


def test_cpa_is_vectorised():
    dx = np.array([0.0, 300.0]); dy = np.array([1000.0, 1000.0])
    cpa, tcpa = enc.cpa_tcpa(dx, dy, np.zeros(2), np.array([-5.0, -5.0]))
    assert cpa.shape == (2,) and np.allclose(cpa, [0.0, 300.0]) and np.allclose(tcpa, [200.0, 200.0])


def test_alert_threshold_constants():
    assert enc.CPA_NM == 0.25 and enc.TCPA_MIN == 10.0
    assert abs(enc.TIERS["0.25nm"] - 0.25 * enc.NM) < 0.1


def test_geometry_head_on():
    # A heading north, B heading south, each dead ahead of the other
    assert enc.geometry(0, 180, 0, 180) == "head-on"


def test_geometry_overtaking():
    # same course; B is astern of A (A sees B at 180 deg relative)
    assert enc.geometry(90, 95, 270, 90) == "overtaking"


def test_geometry_crossing():
    # A north, B west, B on A's starboard bow
    assert enc.geometry(0, 270, 45, 225) == "crossing"


def test_geometry_wraps_across_north():
    # 355 and 175 are reciprocal courses (180 apart across 0/360)
    assert enc.geometry(355, 175, 355, 175) == "head-on"


def test_resample_interpolates_to_minute_grid_and_skips_gaps():
    t0 = pd.Timestamp("2025-01-01T00:00:00")
    # 4 reports 2 minutes apart, then a 20-minute gap (not bridged), then one more
    times = [t0 + pd.Timedelta(minutes=m) for m in (0, 2, 4, 6, 26)]
    df = pd.DataFrame({"mmsi": 1, "t": times, "x": [0.0, 120.0, 240.0, 360.0, 1560.0],
                       "y": 0.0, "sog": 10.0, "cog": 90.0})
    r = enc.resample(df)
    secs = (r.t - r.t.iloc[0]).tolist()
    assert all(s % 60 == 0 for s in r.t)                     # on whole minutes
    assert r.t.max() < (t0 + pd.Timedelta(minutes=7)).value // 10**9   # nothing inside the 20-min gap
    assert np.allclose(np.diff(r.x), 60.0)                   # 60 m per minute, linear
    assert np.allclose(r.vx, 10 * enc.NM / 3600, atol=1e-6) and np.allclose(r.vy, 0, atol=1e-6)
    assert secs == sorted(secs)


def test_resample_drops_vessels_with_too_few_reports():
    df = pd.DataFrame({"mmsi": [1, 1], "t": pd.to_datetime(["2025-01-01T00:00", "2025-01-01T00:02"]),
                       "x": [0.0, 1.0], "y": [0.0, 0.0], "sog": [5.0, 5.0], "cog": [0.0, 0.0]})
    assert enc.resample(df).empty
