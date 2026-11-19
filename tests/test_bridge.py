import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harborledger import bridge  # noqa: E402

INFOBOX = """{{Infobox ship career
 |in_service=18 March 1991
 |identification=*{{IMO Number|8511512}}
                 *{{MMSI Number|367221000}}
                 *[[Maritime call sign|Callsign]]: NNJE
 |status=Inactive
}}
Later text mentions IMO 1234567 and MMSI 999999999 outside the infobox."""


def test_parse_ids_reads_only_the_identification_field():
    assert bridge.parse_ids(INFOBOX) == {"imo": "8511512", "mmsi": "367221000", "call_sign": "NNJE"}


def test_parse_ids_handles_missing_ids():
    assert bridge.parse_ids("{{Infobox ship career |identification= |status=Active}}") == {}
    assert bridge.parse_ids("no infobox at all") == {}


def test_list_titles_keep_the_hull_suffix():
    w = "|{{USNS|John Ericsson|T-AO-194|6}}\n|{{USS|Pinckney|DDG-91|6}}"
    got = bridge.list_titles(w)
    assert ("AO-194", "USNS John Ericsson (T-AO-194)") in got
    assert ("DDG-91", "USS Pinckney (DDG-91)") in got


AIS = [  # (vessel_id, mmsi, imo, call_sign)
    ("mmsi:367221000", "367221000", "8511512", "NNJE"),
    ("mmsi:111111111", "111111111", "7777777", "XXXX"),
]


def test_both_ids_agree_gives_strong_link():
    d = bridge.decide({"imo": "8511512", "mmsi": "367221000", "call_sign": "NNJE"}, AIS)
    assert d["status"] == "linked" and d["dst"] == ["mmsi:367221000"]
    assert d["method"] == "wikipedia_imo_mmsi" and d["confidence"] == 0.98


def test_one_id_gives_weaker_link():
    d = bridge.decide({"imo": "8511512"}, AIS)
    assert d["status"] == "linked" and d["method"] == "wikipedia_imo" and d["confidence"] == 0.95
    d = bridge.decide({"mmsi": "367221000"}, AIS)
    assert d["status"] == "linked" and d["method"] == "wikipedia_mmsi"


def test_conflicting_ids_are_not_linked():
    d = bridge.decide({"imo": "8511512", "mmsi": "111111111"}, AIS)
    assert d["status"] == "conflict" and d["dst"] == []


def test_no_match_and_no_ids():
    assert bridge.decide({"imo": "1234567"}, AIS)["status"] == "not_in_ais"
    assert bridge.decide({}, AIS)["status"] == "no_ids"


def test_names_are_never_used():
    # same name, no shared stable ID -> no link
    d = bridge.decide({"call_sign": "NNJE"}, AIS)
    assert d["status"] == "no_ids"
