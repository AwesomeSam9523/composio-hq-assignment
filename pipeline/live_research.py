"""Live single-app research — the same pass-1 research the batch pipeline runs,
but for ONE app on demand, streamed so a UI can show the agent working.

There is only ONE engine: `research_agent.research_app` (Gemini reasoning over
Composio's no-auth COMPOSIO_SEARCH tools). The batch pipeline calls it with a
no-op callback; the live app passes an `on_event` callback so the Streamlit UI
can render each turn, tool call, and result. This module adds the demo-only
glue: matching a free-text query to the 100-app seed list, synthesising a row
for an ad-hoc off-list app, and the pass-2 evidence check.

Public API:
    research_app_live(app, on_event=...) -> dict     # one schema-valid row
    verify_row_live(row, on_event=...)   -> dict      # pass-2 evidence check
    find_app(query) -> dict | None                    # match the 100-app seed list
    app_dict(query) -> dict                           # seed row or ad-hoc row
"""

from __future__ import annotations

import sys
from pathlib import Path

# Reuse the one research engine (and the shared prompt/schema/model chain) from
# the batch agent, so a live row is identical in shape to a committed row.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from research_agent import (  # noqa: E402
    APPS,
    MODEL,
    research_app,
)

# The live demo drives the exact same engine as the batch pipeline; the only
# difference is that it passes an on_event callback to stream progress.
research_app_live = research_app


# --------------------------------------------------------------------------
# App lookup
# --------------------------------------------------------------------------

def find_app(query: str) -> dict | None:
    """Match a free-text query to one of the 100 seed apps (case-insensitive,
    exact-then-substring). Returns None if it isn't in the seed list — the
    caller can still research an arbitrary app by synthesising a row."""
    q = query.strip().lower()
    if not q:
        return None
    for app in APPS:
        if app["app"].lower() == q:
            return app
    for app in APPS:
        if q in app["app"].lower() or app["app"].lower() in q:
            return app
    return None


def app_dict(query: str) -> dict:
    """Return the seed row for a query, or an ad-hoc row for an app that isn't
    in the seed list (id 0 flags it as off-list; it still researches fine —
    the shared validator accepts id>=0)."""
    found = find_app(query)
    if found:
        return found
    return {
        "id": 0,
        "app": query.strip(),
        "category": "Ad-hoc (not in the 100-app research set)",
        "website_hint": "",
    }


# --------------------------------------------------------------------------
# Pass-2 evidence verification (reused from verify_evidence.py)
# --------------------------------------------------------------------------

def verify_row_live(row: dict, on_event=lambda *a, **k: None) -> dict:
    """Run the same evidence check the batch pass-2 runs: HTTP-check every
    evidence URL and flag weak rows. Imported lazily so the module has no hard
    dependency on `requests` unless verification is used."""
    from verify_evidence import verify_row  # noqa: E402

    on_event("status", message=f"Checking {len(row['evidence_urls'])} evidence URLs…")
    report = verify_row(row)
    on_event("verified", report=report)
    return report


if __name__ == "__main__":
    import json

    query = " ".join(sys.argv[1:]) or "Plain"

    def printer(kind, **data):
        if kind == "tool_call":
            print(f"  → {data['name']}({json.dumps(data['args'])[:120]})")
        elif kind == "tool_result":
            print(f"  ← {data['name']} {'ok' if data['ok'] else 'ERR'}")
        elif kind == "turn":
            print(f"[turn {data['n']}/{data['total']}]")
        elif kind == "model_used":
            print(f"* [model: {data['name']}]")
        elif kind in ("status", "rate_limited"):
            print(f"* {data['message']}")

    app = app_dict(query)
    print(f"Researching: {app['app']} ({app['category']})")
    row = research_app_live(app, printer)
    print(json.dumps(row, indent=2, ensure_ascii=False))
    rep = verify_row_live(row, printer)
    print("evidence flags:", rep["flags"], "dead:", rep["dead_links"])
