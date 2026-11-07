"""Availability cost-growth ledger.

One row per repair availability: a contract tied with confidence >= 0.5 to exactly one
non-nuclear hull, with a repair availability type, and a base obligation of at least $5M.

Label definitions (as in the Phase 3 report):
  base     = obligation on the original award action (modification number 0)
  options  = obligations on 'G' (exercise an option) actions
  total    = sum of all action obligations
  g_total  = (total - base) / base
  g_exopt  = (total - base - options) / (base + options)   <- headline label:
             growth beyond the base and the options the Navy priced in advance
  g_exopt_noC: same, but ignoring 'C' funding-only actions (robustness check, since
             funding-only actions can be incremental funding of planned scope)

Closed: period-of-performance end at least ~90 days before the data cut-off, because
DoD contract data is published with a ~90-day lag. Open availabilities are censored:
their growth so far is a lower bound and they are excluded from training labels.
"""
import datetime as dt
import math
import re

from . import hulls

REPAIR_TYPES = {"SRA", "DSRA", "EDSRA", "ISRA", "DMP", "SIA", "ROH", "MTA", "PMAV", "CMAV",
                "EOH", "VRA", "PSA"}
NUCLEAR_CLASSES = {"CVN", "SSN", "SSBN", "SSGN"}
MIN_BASE = 5e6
DATA_CUTOFF = dt.date(2026, 11, 6)
CLOSED_BEFORE = DATA_CUTOFF - dt.timedelta(days=90)

KW_GROWTH = re.compile(r"GROWTH|NEW WORK|\bRCCS?\b|REQUEST FOR CONTRACT CHANGE|CHANGE ORDER|ADDITIONAL WORK")
KW_DELAY = re.compile(r"EXTEND|EXTENSION|DELAY|PERIOD OF PERFORMANCE|\bPOP\b|REDELIVERY|SCHEDULE")
KW_PENALTY = re.compile(r"PENALT|LIQUIDATED|LATE DELIVERY|CONSIDERATION FOR LATE")
KW_DESCOPE = re.compile(r"DESCOPE|DE-SCOPE|DELETE WORK|DELETION")

LEDGER_SCHEMA = """
DROP TABLE IF EXISTS availability;
CREATE TABLE availability (
  contract_id TEXT PRIMARY KEY, piid TEXT, hull TEXT, hull_class TEXT, avail_type TEXT,
  firm TEXT, recipient_name TEXT, pop_state TEXT, office TEXT,
  first_action TEXT, last_action TEXT, start_fy INTEGER, pop_end TEXT, closed INTEGER,
  base REAL, options REAL, total REAL, g_total REAL, g_exopt REAL, g_exopt_noC REAL,
  n_mods INTEGER, n_growth_kw INTEGER, n_delay_kw INTEGER, n_penalty_kw INTEGER,
  n_descope_kw INTEGER, delay_flag INTEGER, description TEXT
);
"""


def fy(d):
    return d.year + (1 if d.month >= 10 else 0)


def _date(s):
    return dt.date.fromisoformat(s[:10]) if s else None


def is_base(a):
    return (a["mod_number"] or "0").strip() in ("0", "00", "000", "")


def summarize(actions, base_end=None):
    """Aggregate a list of action rows (dicts) into ledger quantities."""
    base_rows = [a for a in actions if is_base(a)]
    mods = [a for a in actions if not is_base(a)]
    base = sum(a["obligation"] or 0 for a in base_rows)
    opt = sum(a["obligation"] or 0 for a in mods if a["action_type"] == "G")
    funding = sum(a["obligation"] or 0 for a in mods if a["action_type"] == "C")
    total = base + sum(a["obligation"] or 0 for a in mods)
    up = lambda a: (a["description"] or "").upper()
    return {
        "base": base, "options": opt, "total": total,
        "g_total": (total - base) / base if base > 0 else None,
        "g_exopt": (total - base - opt) / (base + opt) if base + opt > 0 else None,
        "g_exopt_noC": (total - base - opt - funding) / (base + opt) if base + opt > 0 else None,
        "n_mods": len(mods),
        "n_growth_kw": sum(bool(KW_GROWTH.search(up(a))) for a in mods),
        "n_delay_kw": sum(bool(KW_DELAY.search(up(a))) for a in mods),
        "n_penalty_kw": sum(bool(KW_PENALTY.search(up(a))) for a in mods),
        "n_descope_kw": sum(bool(KW_DESCOPE.search(up(a))) for a in mods),
    }


def build_ledger(con):
    con.executescript(LEDGER_SCHEMA)
    links = {}
    for r in con.execute("SELECT src, dst FROM edge WHERE rel='ABOUT_VESSEL' AND confidence >= ?",
                         (hulls.ASSERT_THRESHOLD,)):
        links.setdefault(r["src"][len("contract:"):], set()).add(r["dst"][len("hull:"):])
    firm_of = {r["src"][4:]: r["dst"][5:] for r in con.execute(
        "SELECT src, dst FROM edge WHERE rel='PART_OF' AND src LIKE 'uei:%'")}
    stats = {"contracts": 0, "single_vessel": 0, "repair_type": 0, "non_nuclear": 0,
             "not_planning": 0, "base_ge_5m": 0, "closed": 0}
    for c in con.execute("SELECT * FROM contract").fetchall():
        stats["contracts"] += 1
        hs = links.get(c["contract_id"], set())
        if len(hs) != 1:
            continue
        stats["single_vessel"] += 1
        if c["avail_type"] not in REPAIR_TYPES:
            continue
        stats["repair_type"] += 1
        hull = next(iter(hs))
        hcls = hull.split("-")[0]
        if hcls in NUCLEAR_CLASSES:
            continue
        stats["non_nuclear"] += 1
        if "PLANNING" in (c["description"] or "").upper():
            continue
        stats["not_planning"] += 1
        acts = [dict(a) for a in con.execute(
            "SELECT * FROM contract_action WHERE contract_id=? ORDER BY action_date, seq",
            (c["contract_id"],))]
        if not acts:
            continue
        s = summarize(acts)
        if s["base"] < MIN_BASE:
            continue
        stats["base_ge_5m"] += 1
        first, last = _date(acts[0]["action_date"]), _date(acts[-1]["action_date"])
        pop_end = _date(c["end_date"])
        closed = int(pop_end is not None and pop_end <= CLOSED_BEFORE)
        stats["closed"] += closed
        con.execute("INSERT INTO availability VALUES (" + ",".join("?" * 27) + ")", (
            c["contract_id"], c["piid"], hull, hcls, c["avail_type"],
            firm_of.get(c["recipient_uei"]), c["recipient_name"], c["pop_state"], c["awarding_office"],
            first.isoformat(), last.isoformat(), fy(first), c["end_date"], closed,
            s["base"], s["options"], s["total"], s["g_total"], s["g_exopt"], s["g_exopt_noC"],
            s["n_mods"], s["n_growth_kw"], s["n_delay_kw"], s["n_penalty_kw"], s["n_descope_kw"],
            int(s["n_delay_kw"] + s["n_penalty_kw"] > 0), c["description"]))
    con.commit()
    return stats


# ---- early-window features ------------------------------------------------------

def window_features(actions, first, days):
    """Features using only actions dated within `days` of the first action (no leakage)."""
    cut = first + dt.timedelta(days=days)
    w = [a for a in actions if _date(a["action_date"]) <= cut]
    s = summarize(w)
    mods = [a for a in w if not is_base(a)]
    typ = lambda t: sum(1 for a in mods if a["action_type"] == t)
    dollars = lambda t: sum(a["obligation"] or 0 for a in mods if a["action_type"] == t)
    denom = (s["base"] + s["options"]) or 1.0
    return {
        "g_w": s["g_exopt"] or 0.0,
        "g_w_noC": s["g_exopt_noC"] or 0.0,
        "opt_share_w": s["options"] / (s["base"] or 1.0),
        "n_mods_w": s["n_mods"],
        "n_growth_kw_w": s["n_growth_kw"],
        "n_delay_kw_w": s["n_delay_kw"],
        "n_penalty_kw_w": s["n_penalty_kw"],
        "n_descope_kw_w": s["n_descope_kw"],
        "n_D_w": typ("D"), "n_B_w": typ("B"), "n_A_w": typ("A"), "n_L_w": typ("L"), "n_C_w": typ("C"),
        "d_D_w": dollars("D") / denom, "d_B_w": dollars("B") / denom, "d_A_w": dollars("A") / denom,
        "d_C_w": dollars("C") / denom,
        "log_base": math.log10(max(s["base"], 1.0)),
    }
