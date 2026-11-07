"""Which AIS years are on disk, and per-year output file names."""
import glob
import os

from .ais import CA_DIR


def years_available():
    return sorted({int(os.path.basename(f)[7:11]) for f in glob.glob(os.path.join(CA_DIR, "ais-ca-*.parquet"))})


def files_for(year):
    return sorted(glob.glob(os.path.join(CA_DIR, f"ais-ca-{year}-*.parquet")))


def by_year(path, year):
    """'eval/tug_activity_results.json' -> 'eval/tug_activity_results_2025.json'."""
    root, ext = os.path.splitext(path)
    return f"{root}_{year}{ext}"
