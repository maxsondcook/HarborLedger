"""Navy hull-number and ship-name extraction from contract descriptions.

Two methods, each reported separately so precision can be measured per method:
  * regex_hull   - an explicit hull designator such as "DDG 105", "LPD-22", "CVN74", "T-AO 187"
  * gazetteer    - a ship name after USS/USNS ("USS ARLEIGH BURKE") resolved to a hull
                   through a name -> hull gazetteer (Wikipedia lists + names mined from
                   descriptions that carry both name and hull)

Boundaries use explicit lookarounds rather than \\b, because "_" is a word
character: "C460A_USS ..." defeated \\bUSS in the earlier prototype.
"""
import collections
import json
import re

# Hull classification prefixes seen in Navy ship repair / construction awards.
CLASSES = [
    "CVN", "CV", "CG", "DDG", "DD", "FFG", "LCS", "LHA", "LHD", "LPD", "LSD", "LCC", "AS",
    "ESB", "ESD", "EPF", "JHSV", "MCM", "PC", "SSN", "SSBN", "SSGN", "AGOS", "AGS", "AGM",
    "AO", "AOE", "AKE", "AH", "ARS", "ATS", "AKR", "AK", "ACS", "AE", "AFSB", "LCU", "YP",
    "ARDM", "AFDM", "AFDL", "APL", "YRBM", "ATF", "AGSE", "AOT", "AVB", "AP", "ARC", "ESB",
    "MLP", "LX", "AFS", "AOR", "AGER", "TAO", "TAKE", "TAKR", "TAGOS", "TAGS", "TAH",
]
# Old designators normalised to current ones.
CLASS_ALIASES = {"JHSV": "EPF", "MLP": "ESD", "AFSB": "ESB", "TAO": "AO", "TAKE": "AKE",
                 "TAKR": "AKR", "TAGOS": "AGOS", "TAGS": "AGS", "TAH": "AH"}

_CLS = "|".join(sorted(set(CLASSES), key=len, reverse=True))
L = r"(?<![A-Z0-9])"   # left boundary: not preceded by letter/digit ("_" and "(" are fine)
R = r"(?![A-Z0-9])"    # right boundary

# "T-AO 187", "DDG 105", "LPD-22", "CVN74", "SSN 802 AND 803", "DDG 1000/1001"
HULL_RE = re.compile(
    L + r"(?P<t>T-)?(?P<cls>" + _CLS + r")\)?\s?[-_\s]?\s?(?P<num>\d{1,4})" + R
    + r"(?P<more>(?:\s*(?:,|/|&|AND)\s*\d{1,4}" + R + r")*)"
)
# a following "CLASS" means a class reference ("DDG 51 CLASS"), not a specific ship
CLASS_REF_RE = re.compile(r"^\s*[-\s]?(?:CLASS|CL\b|FLIGHT|FLT)")
# "USS ARLEIGH BURKE", "USNS RICHARD E. BYRD" - name runs until a stop token.
NAME_RE = re.compile(L + r"(?P<pfx>USS|USNS)[\s_\-:]+(?P<name>[A-Z][A-Z.' \-]{1,40}?)"
                     r"(?=\s*(?:\(|\d|,|;|/|$|\s-\s|\s(?:FY|SRA|DSRA|EDSRA|PIA|DPIA|ROH|MTA|SIA|"
                     r"ISRA|CMAV|PMAV|DMP|RCOH|SSP|SERM|EOH|VOYAGE|MID|EMERGENT|CNO|DRY|DD\b|"
                     r"PSA|PMA|SELRES|AVAIL|REPAIR|CONUS|OCONUS|CODE|POP|IN\b|AT\b|FOR\b|AND\b|"
                     r"PHASE|CLIN|MODERN|MAINT|OVERHAUL|ADVANCE|PLANNING|DOCKING|SHIPYARD|"
                     r"REGULAR|DOCKED|SELECTED|FISCAL|SSRA|DCMAV|LAY\b|EMERGENCY|MARUP|CATEGORY|DEPOT|RFP|DO\b|USS\b|USNS\b|"
                     r"JANUARY|FEBRUARY|MARCH|APRIL|MAY\b|JUNE|JULY|AUGUST|SEPTEMBER|OCTOBER|"
                     r"NOVEMBER|DECEMBER|JAN\b|FEB\b|MAR\b|APR\b|JUN\b|JUL\b|AUG\b|SEP\b|OCT\b|"
                     r"NOV\b|DEC\b)))")

AVAIL_TYPES = [
    ("EDSRA", r"EDSRA"), ("DSRA", r"DSRA"), ("ISRA", r"ISRA"), ("SRA", r"SRA"),
    ("DPIA", r"DPIA"), ("PIA", r"PIA"), ("RCOH", r"RCOH"), ("EOH", r"EOH"),
    ("DMP", r"DMP"), ("ROH", r"ROH(?:/?DD)?"), ("MTA", r"MTA|MID[\s-]?TERM"),
    ("SIA", r"SIA"), ("PMAV", r"PMAV"), ("CMAV", r"CMAV"), ("PSA", r"PSA"),
    ("VRA", r"VOYAGE REPAIR|VRA"), ("SSP", r"SSP"),
]
AVAIL_RE = [(k, re.compile(L + "(?:" + p + ")" + R)) for k, p in AVAIL_TYPES]
FY_RE = re.compile(L + r"FY\s?-?(?P<fy>\d{2}|20\d{2})" + R)


def norm_class(cls, t_prefix=False):
    cls = CLASS_ALIASES.get(cls, cls)
    return cls


def norm_hull(cls, num):
    return f"{norm_class(cls)}-{int(num)}"


def norm_name(s):
    s = s.upper().replace(".", " ").replace("'", "")
    s = re.sub(r"[^A-Z ]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def extract_hulls(desc):
    """Return [(hull, span_text)] for explicit hull designators, skipping class references."""
    if not desc:
        return []
    text = desc.upper()
    out = []
    for m in HULL_RE.finditer(text):
        if CLASS_REF_RE.match(text[m.end():]):
            continue
        cls = m.group("cls")
        nums = [m.group("num")] + re.findall(r"\d{1,4}", m.group("more") or "")
        for n in nums:
            if int(n) == 0:
                continue
            out.append((norm_hull(cls, n), m.group(0)))
    seen, uniq = set(), []
    for h, s in out:
        if h not in seen:
            seen.add(h)
            uniq.append((h, s))
    return uniq


def extract_names(desc):
    if not desc:
        return []
    text = desc.upper().replace("_", " ")
    out = []
    for m in NAME_RE.finditer(text):
        n = norm_name(m.group("name"))
        n = re.sub(r"\s+(?:T|LPD|DDG|CG|LSD|LHD|LHA|LCS|CVN|SSN)$", "", n).strip()
        if len(n) >= 3:
            out.append((m.group("pfx"), n))
    return out


def extract_avail(desc):
    if not desc:
        return None
    text = desc.upper()
    for k, rx in AVAIL_RE:
        if rx.search(text):
            return k
    return None


def extract_fy(desc):
    if not desc:
        return None
    m = FY_RE.search(desc.upper())
    if not m:
        return None
    fy = int(m.group("fy"))
    return fy + 2000 if fy < 100 else fy


class Gazetteer:
    """name -> hull and hull -> name. Built from Wikipedia ship lists, then extended with
    (name, hull) pairs mined from descriptions that state both (support >= min_support)."""

    def __init__(self):
        self.by_name = {}   # norm name -> {hull: (source, support)}
        self.by_hull = {}   # hull -> norm name

    def add(self, name, hull, source, support=1):
        n = norm_name(name)
        self.by_name.setdefault(n, {})
        prev = self.by_name[n].get(hull)
        if prev is None or prev[1] < support:
            self.by_name[n][hull] = (source, support)
        self.by_hull.setdefault(hull, n)

    def load_wikipedia(self, path):
        w = json.load(open(path))["parse"]["wikitext"]
        n = 0
        for m in re.finditer(r"\{\{\s*(USS|USNS)\s*\|\s*([^|}]+?)\s*\|\s*(?:T-)?([A-Z]+)-(\d+)", w):
            self.add(m.group(2), norm_hull(m.group(3), m.group(4)), "wikipedia")
            n += 1
        return n

    def mine(self, descriptions, min_support=2):
        pairs = collections.Counter()
        for d in descriptions:
            names, hulls = extract_names(d), extract_hulls(d)
            if len(names) == 1 and len(hulls) == 1:
                pairs[(names[0][1], hulls[0][0])] += 1
        added = 0
        for (n, h), c in pairs.items():
            if c >= min_support and n not in self.by_name:
                self.add(n, h, "mined", c)
                added += 1
        return added

    def lookup(self, name, fuzzy=True):
        return self.lookup_with_method(name, fuzzy)[0]

    def lookup_with_method(self, name, fuzzy=True):
        """Exact normalised match first; otherwise a unique 'short form' match where the
        query's tokens are a subset of one gazetteer name and the last tokens agree
        ("KAISER" -> HENRY J KAISER, "WINSTON CHURCHILL" -> WINSTON S CHURCHILL)."""
        q = norm_name(name)
        hit = self._exact(q)
        if hit:
            return hit, "exact"
        if not fuzzy:
            return None, None
        qt = q.split()
        cands = set()
        for n, hulls_ in self.by_name.items():
            nt = n.split()
            if qt and nt and qt[-1] == nt[-1] and set(qt) <= set(nt):
                cands.update(hulls_)
        if len(cands) == 1:
            return cands.pop(), "short_form"
        return None, None

    def _exact(self, q):
        hits = self.by_name.get(q)
        if not hits:
            return None
        if len(hits) == 1:
            return next(iter(hits))
        # several hulls share a name (e.g. reused names) - prefer the best-supported
        return max(hits.items(), key=lambda kv: (kv[1][0] == "wikipedia", kv[1][1]))[0]


# Lead ships whose hull number doubles as the name of the whole program ("DDG-51" = the
# Arleigh Burke class). A bare mention with no ship name and no availability type is
# treated as a program reference.
CLASS_LEAD = {"DDG-51", "DDG-1000", "CG-47", "LCS-1", "LCS-2", "FFG-62", "LPD-17", "LSD-41",
              "LSD-49", "LHA-6", "LHD-1", "CVN-78", "SSN-774", "SSN-21", "SSBN-826", "AO-205",
              "AKE-1", "EPF-1", "ESB-3", "ESD-1"}
ASSERT_THRESHOLD = 0.5   # edges below this are kept for audit but not counted as vessel links


def resolve(desc, gaz):
    """Return list of dicts: hull, method, confidence, evidence. Explicit hulls win;
    names are used only for ships with no explicit hull in the same description."""
    hulls = extract_hulls(desc)
    names = extract_names(desc)
    res = []
    hull_set = {h for h, _ in hulls}
    multi = len(hulls) > 1
    has_avail = extract_avail(desc) is not None
    for h, span in hulls:
        if h in CLASS_LEAD and not names and not has_avail:
            res.append({"hull": h, "method": "regex_hull_classlead", "evidence": span,
                        "confidence": 0.4})
            continue
        res.append({"hull": h, "method": "regex_hull", "evidence": span,
                    "confidence": 0.75 if multi else 0.95})
    for pfx, n in names:
        h, how = gaz.lookup_with_method(n) if gaz else (None, None)
        if h and h not in hull_set:
            res.append({"hull": h, "method": "gazetteer" if how == "exact" else "gazetteer_short",
                        "evidence": f"{pfx} {n}",
                        "confidence": 0.85 if how == "exact" else 0.7})
            hull_set.add(h)
    return res
