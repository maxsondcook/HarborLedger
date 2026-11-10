# Data-source register

Every source HarborLedger uses: its terms, what it is used for, how it is collected, and what was
checked. Add a row **before** writing code for a new source; `tests/test_fetch_policy.py` fails if the
code fetches from a host not listed here. Each raw file's source, URL, fetch time, sha256 and licence
are also recorded per file in `data/raw/manifest.jsonl`.

Last reviewed 2026-11-10 (against the CROSSR lessons-learned checklist).

## Collection rules

- **Read the terms and robots.txt first.** If they forbid automated access or reuse, look for an
  official API, a licence, or written permission. If none exists, don't use the source.
- **Never get past a block:**
  - no browser impersonation, stealth flags, reused cookies, proxies or CAPTCHA services;
  - no archive copies used as a way around a block.

  A block page means no. A person may still download a file the site offers in an ordinary browser,
  as with the Coast Guard register below.
- **Identify honestly.** Every request sends `snapshot.USER_AGENT`, which gives the project name and
  the repo URL as the contact. Requests are throttled and cached, so nothing is fetched twice.
- **SSL checks stay on.**
- **Publish only what the licence allows.** Global Fishing Watch, OpenSanctions and Equasis are
  excluded (non-commercial only, or no reproduction). Owner names are published only for
  organisations, and owner addresses are never kept.

## Sources

| Source | Host(s) | Terms / licence | robots.txt (checked 2026-11-10) | How collected | Used for | Published? |
|---|---|---|---|---|---|---|
| USAspending awards and transactions | `api.usaspending.gov` | Federal data, public domain. Official keyless API | none served | API, 0.4–0.6 s sleep between calls | contract ledger, yards | derived values on site |
| MarineCadastre AIS 2024 (GeoParquet) | `ocmgeodatastor1.blob.core.windows.net` | NOAA/BOEM, public domain (CC0). Official bulk download | none (blob storage) | daily files, filtered to California; retries back off | activity, encounters, weather, fishing | derived values; benchmark (CC BY 4.0) |
| MarineCadastre AIS 2025 (`csv.zst`) | `noaaocm.blob.core.windows.net` | same | none (blob storage) | same | same | same |
| USCG PSIX vessel records | `cgmix.uscg.mil` | No terms page. The Coast Guard's own help page offers the XML web service for bulk access; the data is a weekly FOIA snapshot. Treated as a federal work | robots.txt redirects to an error page | official SOAP service, about 1 request/s, cached | vessel identity matching | match results and vessel names |
| USCG Merchant Vessels of the U.S. register | `www.dco.uscg.mil` | Federal work. The Coast Guard redacts individual owners | the server blocks scripts (Akamai) | **downloaded by hand in a browser**; not fetched by code | vessel register fields | organisation owners only; no addresses |
| NOAA NDBC buoys | `www.ndbc.noaa.gov` | Federal data, public domain | disallows only named bots (not `*`) | yearly history files, 0.5 s sleep, cached | sea state | derived values |
| NOAA CoastWatch ERDDAP (OISST, VIIRS chlorophyll) | `coastwatch.pfeg.noaa.gov` | Federal data, public domain. ERDDAP is NOAA's data API and documents use by scripts | `Disallow: /*?` and data file types for `*` (see note) | 2 griddap requests in total, cached | fishing model | derived values |
| NOAA SWFSC ERDDAP (CUTI, BEUTI upwelling) | `oceanview.pfeg.noaa.gov` | Federal data, public domain | `Disallow: /` for `*` (see note) | 2 griddap requests in total, cached | fishing model | derived values |
| NOAA GFS-Wave forecast archive | `noaa-gfs-bdp-pds.s3.amazonaws.com` | NOAA Open Data Dissemination on AWS, public domain | none (S3) | byte-range requests from `.idx` files, 8 workers, cached | trip-time forecast | derived values |
| SB 535 disadvantaged communities (2022) | `geodata.dot.ca.gov` (Caltrans ArcGIS service; credits OEHHA/CalEPA) | California's site policy treats state information as generally public domain. **OEHHA's own conditions-of-use page sits behind a CAPTCHA and was not read** (see note) | none served | one ArcGIS REST query, cached | "near a disadvantaged community" share of tug hours | derived shares only; polygons not published |
| Wikipedia ship lists | `en.wikipedia.org` | CC BY-SA 4.0: attribution, and share-alike for adaptations | API allowed | MediaWiki API, 2 pages | Navy and MSC hull names | committed raw copy, credited on the site |
| Excluded: Global Fishing Watch, OpenSanctions, Equasis | n/a | non-commercial only / no reproduction or bulk download | n/a | not used | n/a | no |

## Open items and judgement calls

1. **ERDDAP robots.txt.** Both NOAA ERDDAP servers tell crawlers not to fetch query URLs. ERDDAP
   itself is NOAA's data API, and its documentation says every form has a matching service "designed
   to be easy for computer programs and scripts to use". HarborLedger made four targeted, cached
   requests, not a crawl. This is recorded as a judgement call, not a settled permission. If it
   matters (for example before any commercial use), email the ERDDAP administrators
   (erd.data@noaa.gov) and record the answer here.
2. **OEHHA / CalEPA terms.** The SB 535 layer's own terms could not be read because the OEHHA site
   requires a CAPTCHA, which this project will not get past. Read
   https://oehha.ca.gov/public-information/conditions-use in a browser, or email OEHHA, and record
   the result here. Only derived hour shares are published, not the polygons.
3. **PSIX.** No explicit licence exists. The Coast Guard offers the bulk web service publicly and
   the data is a FOIA snapshot, so it is treated as a federal work.
