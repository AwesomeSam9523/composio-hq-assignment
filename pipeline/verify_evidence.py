"""Pass 2 - evidence validator.

Re-checks every evidence URL in data/results.json:
  * Does the URL still resolve (HTTP status)?
  * Is at least one evidence URL on an official/vendor domain (vs third-party)?
  * Does the row have enough evidence for its confidence level?

Writes data/evidence_report.json with per-row flags. Rows with dead links or
no official-domain evidence are flagged `weak_evidence` so the human QA pass
can prioritise them. This pass never edits research fields - it only flags.

Usage: python pipeline/verify_evidence.py
"""

import json
import re
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "data" / "results.json"
REPORT = ROOT / "data" / "evidence_report.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
}

# Vendor domains that block bots but are known-good documentation hosts.
BOT_BLOCKED_OK = {403, 405, 429, 503, 999}


def domain(url: str) -> str:
    return urllib.parse.urlparse(url).netloc.lower().removeprefix("www.")


def official_domains(row: dict) -> set[str]:
    """Domains we consider 'official' for this app: the website hint domain
    and any subdomain of it, plus known doc hosts referenced in the hint."""
    hints = set()
    for token in re.findall(r"[a-z0-9.-]+\.[a-z]{2,}", row["website_hint"].lower()):
        parts = token.split(".")
        hints.add(".".join(parts[-2:]))
    return hints


def check_url(url: str) -> dict:
    try:
        resp = requests.head(url, headers=HEADERS, timeout=15, allow_redirects=True)
        if resp.status_code in (405, 403, 404):
            resp = requests.get(url, headers=HEADERS, timeout=20, allow_redirects=True, stream=True)
        status = resp.status_code
    except requests.RequestException as exc:
        return {"url": url, "status": None, "ok": False, "note": type(exc).__name__}
    ok = status < 400 or status in BOT_BLOCKED_OK
    note = "bot_blocked_but_reachable" if status in BOT_BLOCKED_OK else ""
    return {"url": url, "status": status, "ok": ok, "note": note}


def verify_row(row: dict) -> dict:
    checks = list(ThreadPoolExecutor(4).map(check_url, row["evidence_urls"]))
    officials = official_domains(row)
    has_official = any(
        any(domain(c["url"]).endswith(o) for o in officials) for c in checks
    ) or not officials
    dead = [c["url"] for c in checks if not c["ok"]]
    flags = []
    if dead:
        flags.append("dead_links")
    if not has_official:
        flags.append("no_official_domain_evidence")
    if len(row["evidence_urls"]) < 2 and row["confidence"] == "high":
        flags.append("high_confidence_thin_evidence")
    return {
        "id": row["id"],
        "app": row["app"],
        "confidence": row["confidence"],
        "url_checks": checks,
        "dead_links": dead,
        "has_official_domain_evidence": has_official,
        "flags": flags,
        "weak_evidence": bool(flags),
    }


def main() -> None:
    rows = json.loads(RESULTS.read_text())
    report = [verify_row(r) for r in rows]
    weak = [r for r in report if r["weak_evidence"]]
    summary = {
        "total_rows": len(report),
        "rows_flagged": len(weak),
        "total_urls_checked": sum(len(r["url_checks"]) for r in report),
        "dead_urls": sum(len(r["dead_links"]) for r in report),
        "flagged_apps": [r["app"] for r in weak],
    }
    REPORT.write_text(json.dumps({"summary": summary, "rows": report}, indent=2))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
