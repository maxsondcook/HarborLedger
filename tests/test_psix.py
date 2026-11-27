"""Gated AIS -> USCG PSIX matching. The network call (psix.query) is replaced by a fake."""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harborledger import psix  # noqa: E402

VALID_IMO = "9686754"


def rec(name, ident="", vid="P1", status="Active"):
    return {"VesselName": name, "Identification": ident, "VesselId": vid,
            "StatusLookupName": status, "ServiceType": "Tug"}


@pytest.fixture
def fake_query(monkeypatch):
    db = {}

    def q(**kw):
        key = ("cs", kw["CallSign"]) if "CallSign" in kw else ("name", kw["VesselName"])
        return db.get(key, [])
    monkeypatch.setattr(psix, "query", q)
    return db


def test_callsign_plus_imo_is_auto_merge(fake_query):
    fake_query[("cs", "WDA1234")] = [rec("SEA CHANGE", VALID_IMO)]
    r = psix.match_vessel({"mmsi": 1, "name": "M/V SEA CHANGE", "call_sign": "wda1234", "imo": VALID_IMO})
    assert r["rel"] == "SAME_AS" and r["method"] == "callsign_gated" and r["confidence"] == 0.98


def test_callsign_plus_similar_name_is_auto_merge(fake_query):
    fake_query[("cs", "WDA1234")] = [rec("SEA CHANGE")]
    r = psix.match_vessel({"mmsi": 1, "name": "SEA CHANGE", "call_sign": "WDA1234", "imo": ""})
    assert r["rel"] == "SAME_AS" and 0.85 <= r["confidence"] <= 0.97


def test_callsign_with_different_name_is_only_possible(fake_query):
    # the Phase 3 failure mode: a call sign reused by a different vessel
    fake_query[("cs", "WDA1234")] = [rec("PACIFIC STAR")]
    r = psix.match_vessel({"mmsi": 1, "name": "SEA CHANGE", "call_sign": "WDA1234", "imo": ""})
    assert r["rel"] == "POSSIBLE_SAME_AS" and r["confidence"] < 0.5


def test_imo_agreement_beats_name_among_candidates(fake_query):
    fake_query[("cs", "WDA1234")] = [rec("SEA CHANGE", "", vid="A"), rec("OTHER", VALID_IMO, vid="B")]
    r = psix.match_vessel({"mmsi": 1, "name": "SEA CHANGE", "call_sign": "WDA1234", "imo": VALID_IMO})
    assert r["psix_id"] == "B" and r["imo_agree"] is True


def test_junk_callsign_falls_back_to_name_plus_imo(fake_query):
    fake_query[("name", "SEA CHANGE")] = [rec("SEA CHANGE", VALID_IMO)]
    r = psix.match_vessel({"mmsi": 1, "name": "SEA CHANGE", "call_sign": "NOCOMMS", "imo": VALID_IMO})
    assert r["call_sign"] == "" and r["method"] == "name_plus_imo" and r["confidence"] == 0.97


def test_name_alone_never_links(fake_query):
    # same name, no call sign and no valid IMO: must not link (names are never enough)
    fake_query[("name", "SEA CHANGE")] = [rec("SEA CHANGE", VALID_IMO)]
    r = psix.match_vessel({"mmsi": 1, "name": "SEA CHANGE", "call_sign": "", "imo": ""})
    assert r["rel"] is None


def test_name_search_with_wrong_imo_does_not_link(fake_query):
    fake_query[("name", "SEA CHANGE")] = [rec("SEA CHANGE", "9074729")]
    r = psix.match_vessel({"mmsi": 1, "name": "SEA CHANGE", "call_sign": "", "imo": VALID_IMO})
    assert r["rel"] is None


def test_callsign_with_no_hits_and_no_imo_is_unmatched(fake_query):
    r = psix.match_vessel({"mmsi": 1, "name": "SEA CHANGE", "call_sign": "WZZ9999", "imo": ""})
    assert r["rel"] is None and r["cs_hits"] == 0
