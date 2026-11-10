"""Guards for the data-collection rules in CLAUDE.md and docs/data-sources.md.

- Never get past a block: no browser impersonation, stealth flags, cookie reuse, proxies or archives
  used as a way around a site that said no.
- Never turn off SSL certificate checks.
- Identify honestly: every automated request sends the shared project user-agent, which names the
  project and a contact URL.
- Every source the code fetches from is listed in the data-source register.
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from harborledger import snapshot  # noqa: E402

PKG = os.path.join(ROOT, "harborledger")


def _sources():
    out = {}
    for f in sorted(os.listdir(PKG)):
        if f.endswith(".py"):
            out[f] = open(os.path.join(PKG, f), encoding="utf-8").read()
    out["run.py"] = open(os.path.join(ROOT, "run.py"), encoding="utf-8").read()
    return out


FORBIDDEN = [
    r"verify\s*=\s*False", r"_create_unverified_context", r"CERT_NONE", r"check_hostname\s*=\s*False",
    r"curl_cffi", r"impersonate", r"AutomationControlled", r"undetected", r"cloudscraper",
    r"cf_clearance", r"web\.archive\.org", r"Mozilla/5\.0", r"\bproxies\s*=", r"captcha",
]


def test_no_block_bypass_or_ssl_off():
    hits = [(f, p) for f, src in _sources().items() for p in FORBIDDEN if re.search(p, src, re.I)]
    assert hits == [], hits


def test_user_agent_names_project_and_contact():
    ua = snapshot.USER_AGENT
    assert ua.startswith("harborledger/")
    assert "https://github.com/maxsondcook/HarborLedger" in ua


def test_requests_use_shared_user_agent():
    # no module may write its own User-Agent string; all go through snapshot.USER_AGENT
    for f, src in _sources().items():
        for m in re.finditer(r"[\"']User-Agent[\"']\s*:\s*([^,}\n]+)", src):
            assert "USER_AGENT" in m.group(1), (f, m.group(0))


def test_every_fetched_host_is_in_the_register():
    register = open(os.path.join(ROOT, "docs", "data-sources.md"), encoding="utf-8").read()
    hosts = set()
    for src in _sources().values():
        hosts.update(re.findall(r"https://([a-z0-9.-]+\.[a-z]{2,})", src))
    hosts -= {"github.com", "schemas.xmlsoap.org", "doi.org", "zenodo.org"}
    missing = sorted(h for h in hosts if h not in register)
    assert missing == [], missing
