# Data licences

The **code** in this repository is under the MIT License (`LICENSE`). Data is licensed separately:

| Data | Licence | Notes |
|---|---|---|
| Derived data written by this project (`eval/`, `site/public/data/`, `docs/benchmark*`, the `encounters-v1` benchmark) | [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) | Cite the Zenodo record (see `CITATION.cff`). |
| Wikipedia ship lists (`data/raw/wikipedia/`) and rows whose `license` column says `CC BY-SA 4.0` | [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/) | Adaptations must stay share-alike, with attribution to Wikipedia contributors. |
| Hand-curated tables (`curated/`) | CC BY 4.0 | Each row cites its own source. |
| Upstream U.S. federal data (MarineCadastre AIS, USAspending, USCG PSIX, NOAA) | Public domain / CC0 | Not redistributed in raw form; rebuilt by `run.py`. |

Every graph edge and identifier carries its own `license` value; that column is authoritative for
any individual record. Global Fishing Watch, OpenSanctions and Equasis data are not used in
anything published.
