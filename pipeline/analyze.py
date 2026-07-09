"""Pattern analysis: computes the distributions and insights that feed the
case-study page. Writes data/insights.json.

Usage: python pipeline/analyze.py
"""

import json
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "data" / "results.json"


def pct(n: int, total: int) -> float:
    return round(100 * n / total, 1) if total else 0.0


def main() -> None:
    rows = json.loads(RESULTS.read_text())
    total = len(rows)

    auth = Counter(m for r in rows for m in r["auth_methods"])
    access = Counter(r["access_model"] for r in rows)
    surface = Counter(r["api_surface_type"] for r in rows)
    breadth = Counter(r["api_surface_breadth"] for r in rows)
    mcp = Counter(r["mcp_status"] for r in rows)
    verdict = Counter(r["buildability_verdict"] for r in rows)
    confidence = Counter(r["confidence"] for r in rows)

    by_cat = defaultdict(list)
    for r in rows:
        by_cat[r["category"]].append(r)

    cat_matrix = {}
    for cat, cat_rows in by_cat.items():
        cat_matrix[cat] = {
            "total": len(cat_rows),
            "buildability": dict(Counter(r["buildability_verdict"] for r in cat_rows)),
            "access": dict(Counter(r["access_model"] for r in cat_rows)),
            "self_serve_pct": pct(
                sum(r["access_model"] == "self_serve" for r in cat_rows), len(cat_rows)
            ),
            "build_now_pct": pct(
                sum(r["buildability_verdict"] == "build_now" for r in cat_rows),
                len(cat_rows),
            ),
            "broad_api_pct": pct(
                sum(r["api_surface_breadth"] == "broad" for r in cat_rows),
                len(cat_rows),
            ),
            "official_mcp_pct": pct(
                sum(r["mcp_status"] == "official_mcp" for r in cat_rows), len(cat_rows)
            ),
        }

    blockers = Counter(
        r["main_blocker"].strip() for r in rows
        if r["main_blocker"].strip().lower() not in ("none", "")
        and not r["main_blocker"].strip().lower().startswith("none (")
    )

    gated = {"paid_plan_required", "admin_approval_required", "partner_gated", "contact_sales"}
    easy_wins = [
        r["app"] for r in rows
        if r["buildability_verdict"] == "build_now" and r["access_model"] == "self_serve"
        and r["confidence"] == "high"
    ]
    outreach = [
        r["app"] for r in rows
        if r["buildability_verdict"] == "needs_partner_or_paid_access"
        or r["access_model"] in ("partner_gated", "contact_sales")
    ]

    insights = {
        "totals": {
            "apps": total,
            "categories": len(by_cat),
            "build_now": verdict.get("build_now", 0),
            "build_with_limits": verdict.get("build_with_limits", 0),
            "buildable_pct": pct(
                verdict.get("build_now", 0) + verdict.get("build_with_limits", 0), total
            ),
            "self_serve_pct": pct(access.get("self_serve", 0), total),
            "gated_pct": pct(sum(access.get(g, 0) for g in gated), total),
            "official_mcp": mcp.get("official_mcp", 0),
            "no_public_api": surface.get("No_public_API_found", 0),
        },
        "distributions": {
            "auth_methods": dict(auth.most_common()),
            "access_model": dict(access.most_common()),
            "api_surface_type": dict(surface.most_common()),
            "api_surface_breadth": dict(breadth.most_common()),
            "mcp_status": dict(mcp.most_common()),
            "buildability_verdict": dict(verdict.most_common()),
            "confidence": dict(confidence.most_common()),
        },
        "category_matrix": cat_matrix,
        "blockers": dict(blockers.most_common()),
        "easy_wins": easy_wins,
        "outreach_needed": sorted(set(outreach)),
    }
    (ROOT / "data" / "insights.json").write_text(json.dumps(insights, indent=2))
    print(json.dumps(insights["totals"], indent=2))
    print("\nTop auth methods:", auth.most_common(5))
    print("Verdicts:", verdict.most_common())
    print("MCP:", mcp.most_common())


if __name__ == "__main__":
    main()
