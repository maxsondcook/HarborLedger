"""Shape and consistency of the committed site JSON (site/public/data), which CI builds from."""
import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from harborledger import checks, export  # noqa: E402

DATA = os.path.join(ROOT, "site", "public", "data")
needs_data = pytest.mark.skipif(not os.path.exists(os.path.join(DATA, "meta.json")), reason="no exported data")


def test_slug():
    assert export.slug("mmsi:366562000") == "mmsi-366562000"
    assert export.slug("hull:DDG-105") == "hull-DDG-105"
    assert export.slug("uei:AB C/12") == "uei-AB-C-12"


@needs_data
def test_export_file_checks_pass():
    errors = [r for r in checks.check_export_files(DATA) if r[0] == "ERROR"]
    assert not errors, errors


@needs_data
def test_meta_has_counts_and_sources():
    meta = json.load(open(os.path.join(DATA, "meta.json")))
    for k in ("vessels", "edges", "contracts"):
        assert isinstance(meta["counts"][k], int) and meta["counts"][k] > 0
    assert meta["sources"]


@needs_data
def test_vessel_index_fields():
    index = json.load(open(os.path.join(DATA, "vessels.json")))
    assert index
    for v in index[:200]:
        assert {"slug", "kind", "name"} <= set(v)
        assert v["kind"] in {"ais", "navy"}


@needs_data
def test_vessel_pages_parse():
    folder = os.path.join(DATA, "vessels")
    for f in sorted(os.listdir(folder))[:50]:
        json.load(open(os.path.join(folder, f)))
