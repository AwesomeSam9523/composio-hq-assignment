"""Generates the static case-study page (index.html) from pipeline/template.html
by injecting data/results.json, data/insights.json, data/verification.json and
the evidence report summary. Also buckets free-text blockers into themes.

Usage: python pipeline/build_page.py
"""

import json
import os
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def bucket_blocker(row: dict) -> str | None:
    if row["buildability_verdict"] == "build_now":
        return None
    text = row["main_blocker"].lower()
    rules = [
        (r"partner|contract|sales-led|sales-onboard|merchant|licen|customer account|account manager|enterprise", "Partner / enterprise contract required"),
        (r"paid plan|paid subscription|paid, consumption|paid usage|paid ahrefs|professional\+|plan required|paid.*(plan|tier)|acu billing|consumption", "Paid plan or paid usage required"),
        (r"app review|approval|verification|access tier|developer token|review process|certification|vetting|restricted", "App review / access-tier approval"),
        (r"no public|no general-purpose|no hosted api|webhook-in|no usable", "No general-purpose public API"),
        (r"narrow|thin|small|partial|evolving|docs", "Narrow API surface or thin docs"),
        (r"oauth|token lifetime|credential|api key|self-serve", "Credential / OAuth registration friction"),
    ]
    for pattern, label in rules:
        if re.search(pattern, text):
            return label
    return "Other"


def main() -> None:
    rows = json.loads((ROOT / "data" / "results.json").read_text())
    insights = json.loads((ROOT / "data" / "insights.json").read_text())
    verification = json.loads((ROOT / "data" / "verification.json").read_text())
    evidence = json.loads((ROOT / "data" / "evidence_report.json").read_text())["summary"]

    themes = Counter(t for r in rows if (t := bucket_blocker(r)))
    insights["blocker_themes"] = dict(themes.most_common())

    payload = json.dumps(
        {
            "rows": rows,
            "insights": insights,
            "verification": verification,
            "evidence_summary": evidence,
        },
        ensure_ascii=False,
    ).replace("</", "<\\/")  # keep </script> sequences inert inside the data block

    # Live-demo + repo links. Precedence: env var > data/links.json > default.
    # After deploying app.py on Railway, run:
    #   LIVE_DEMO_URL="https://<app>.up.railway.app" python pipeline/build_page.py
    # (or edit data/links.json once). Env values are persisted back to links.json.
    links_file = ROOT / "data" / "links.json"
    links = json.loads(links_file.read_text()) if links_file.exists() else {}
    live_url = os.environ.get("LIVE_DEMO_URL") or links.get("live_demo_url") or "#"
    repo_url = (
        os.environ.get("REPO_URL")
        or links.get("repo_url")
        or "https://github.com/AwesomeSam9523/composio-hq-assignment"
    )
    if os.environ.get("LIVE_DEMO_URL") or os.environ.get("REPO_URL"):
        links_file.write_text(
            json.dumps({"live_demo_url": live_url, "repo_url": repo_url}, indent=2)
        )

    template = (ROOT / "pipeline" / "template.html").read_text()
    html = (
        template.replace("__DATA_JSON__", payload)
        .replace("__LIVE_DEMO_URL__", live_url)
        .replace("__REPO_URL__", repo_url)
    )
    (ROOT / "index.html").write_text(html)
    print(f"wrote index.html ({len(html) // 1024} KB); live_demo_url={live_url}")
    if live_url == "#":
        print("  note: LIVE_DEMO_URL not set — 'Try the live agent' links are inert.")


if __name__ == "__main__":
    main()
