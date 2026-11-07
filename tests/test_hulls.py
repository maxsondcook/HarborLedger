import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harborledger import hulls  # noqa: E402


def H(desc):
    return [h for h, _ in hulls.extract_hulls(desc)]


def test_basic_forms():
    assert H("USS GREEN BAY (LPD 20) FY25 DSRA") == ["LPD-20"]
    assert H("USS SAN DIEGO(LPD-22)FY18 SRA") == ["LPD-22"]
    assert H("CVN 75 EXECUTION") == ["CVN-75"]
    assert H("SUPPORT THE CVN74 REFUEL") == ["CVN-74"]


def test_underscore_prefix_bug_fixed():
    assert H("C460A_USS SAMPSON (DDG_102) SRA") == ["DDG-102"]
    names = hulls.extract_names("C460A_USS SAMPSON (DDG 102) SRA")
    assert names == [("USS", "SAMPSON")]


def test_multi_hull_and_t_prefix():
    assert H("SSN 802 AND 803 LONG LEAD TIME MATERIAL") == ["SSN-802", "SSN-803"]
    assert H("USNS JOHN LEWIS (T-AO 205) PSA") == ["AO-205"]
    assert H("JOINT HIGH SPEED VESSEL 11") == []  # spelled out: not a designator
    assert H("JHSV 11 LONG LEAD") == ["EPF-11"]


def test_class_reference_is_not_a_ship():
    assert H("CONSTRUCTION OF DDG 51 CLASS DESTROYER") == []
    assert H("DDG 51 FLIGHT III") == []


def test_no_false_hits_inside_tokens():
    assert H("N0002417C2100") == []
    assert H("PSC 1905 PROCUREMENT") == []
    assert H("ADDG123") == []


def test_avail_and_fy():
    assert hulls.extract_avail("USS GREEN BAY (LPD 20) FY25 DSRA") == "DSRA"
    assert hulls.extract_avail("USS DONALD COOK (DDG 75) CNO EDSRA") == "EDSRA"
    assert hulls.extract_avail("USNS RICHARD BYRD FEBRUARY 2025 MID-TERM AVAILABLITY") == "MTA"
    assert hulls.extract_fy("USS GREEN BAY (LPD 20) FY25 DSRA") == 2025
    assert hulls.extract_fy("FY2019 SRA") == 2019


def test_gazetteer_resolution():
    g = hulls.Gazetteer()
    g.add("Arleigh Burke", "DDG-51", "wikipedia")
    r = hulls.resolve("USS ARLEIGH BURKE FY23 SIA", g)
    assert [(x["hull"], x["method"]) for x in r] == [("DDG-51", "gazetteer")]
    # explicit hull suppresses a duplicate gazetteer hit
    r = hulls.resolve("USS ARLEIGH BURKE (DDG 51) SRA", g)
    assert [(x["hull"], x["method"]) for x in r] == [("DDG-51", "regex_hull")]


def test_class_lead_program_reference_downweighted():
    r = hulls.resolve("DDG 51, PROP SHAFT", None)
    assert r[0]["method"] == "regex_hull_classlead" and r[0]["confidence"] < hulls.ASSERT_THRESHOLD
    r = hulls.resolve("USS ARLEIGH BURKE (DDG 51) FY23 SIA", None)
    assert r[0]["method"] == "regex_hull" and r[0]["confidence"] >= hulls.ASSERT_THRESHOLD


def test_parenthesised_designator():
    assert H("EXPEDITIONARY FAST TRANSPORT (EPF) 13") == ["EPF-13"]
