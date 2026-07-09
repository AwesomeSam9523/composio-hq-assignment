"""Composio Buildability Researcher — live demo.

Search for any app and watch the *same* research pipeline the 100-app case study
used run end to end for that one app:

  Pass 1  Gemini drives Composio's no-auth COMPOSIO_SEARCH tools (web / Tavily /
          news / URL-fetch) in an agentic loop, then emits ONE schema-validated
          row: auth, self-serve-vs-gated, API surface, MCP status, buildability
          verdict, evidence URLs, confidence.
  Pass 2  Every evidence URL is HTTP-checked and the row is flagged if evidence
          is dead or non-official — the same verification loop from the study.

Run:  streamlit run app.py
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "pipeline"))

# The full 100-app case study (index.html), hosted on GitHub Pages. Override
# with CASE_STUDY_URL if you host it elsewhere.
CASE_STUDY_URL = os.environ.get(
    "CASE_STUDY_URL",
    "https://awesomesam9523.github.io/composio-hq-assignment/",
)

from live_research import (  # noqa: E402
    MODEL,
    app_dict,
    find_app,
    research_app_live,
    verify_row_live,
)
from research_agent import APPS  # noqa: E402

st.set_page_config(
    page_title="Composio Buildability Researcher",
    page_icon="🧩",
    layout="wide",
)

# --------------------------------------------------------------------------
# Data + label helpers
# --------------------------------------------------------------------------

@st.cache_data
def load_json(rel: str):
    path = ROOT / rel
    return json.loads(path.read_text()) if path.exists() else None


INSIGHTS = load_json("data/insights.json")
RESULTS = load_json("data/results.json") or []
RESULTS_BY_ID = {r["id"]: r for r in RESULTS}

VERDICT_LABEL = {
    "build_now": "Build now",
    "build_with_limits": "Build with limits",
    "needs_partner_or_paid_access": "Needs partner / paid access",
    "not_buildable_today": "Not buildable today",
    "unclear": "Unclear",
}
VERDICT_COLOR = {
    "build_now": "#16a34a",
    "build_with_limits": "#0d9488",
    "needs_partner_or_paid_access": "#d97706",
    "not_buildable_today": "#dc2626",
    "unclear": "#6b7280",
}
ACCESS_LABEL = {
    "self_serve": "Self-serve",
    "trial_or_free_but_limited": "Trial / free but limited",
    "paid_plan_required": "Paid plan required",
    "admin_approval_required": "Admin approval required",
    "partner_gated": "Partner-gated",
    "contact_sales": "Contact sales",
    "unclear": "Unclear",
}
ACCESS_COLOR = {
    "self_serve": "#16a34a",
    "trial_or_free_but_limited": "#0d9488",
    "paid_plan_required": "#d97706",
    "admin_approval_required": "#d97706",
    "partner_gated": "#dc2626",
    "contact_sales": "#dc2626",
    "unclear": "#6b7280",
}
MCP_LABEL = {
    "official_mcp": "Official MCP",
    "community_mcp": "Community MCP",
    "no_mcp_found": "No MCP found",
    "unclear": "Unclear",
}
SURFACE_LABEL = {
    "REST": "REST",
    "GraphQL": "GraphQL",
    "REST_and_GraphQL": "REST + GraphQL",
    "SDK_only": "SDK only",
    "CLI": "CLI",
    "Webhook_only": "Webhook only",
    "No_public_API_found": "No public API found",
    "unclear": "Unclear",
}
CONFIDENCE_COLOR = {"high": "#16a34a", "medium": "#d97706", "low": "#dc2626"}

TOOL_LABEL = {
    "COMPOSIO_SEARCH_WEB": "Web search",
    "COMPOSIO_SEARCH_TAVILY": "Tavily search",
    "COMPOSIO_SEARCH_NEWS": "News search",
    "COMPOSIO_SEARCH_FETCH_URL_CONTENT": "Fetch page",
}

st.markdown(
    """
    <style>
      .chip {display:inline-block;padding:3px 10px;margin:2px 4px 2px 0;border-radius:999px;
             font-size:0.8rem;font-weight:600;color:#fff;}
      .chip-outline {display:inline-block;padding:3px 10px;margin:2px 4px 2px 0;border-radius:999px;
             font-size:0.8rem;font-weight:600;border:1px solid #94a3b8;color:#334155;}
      .big-verdict {display:inline-block;padding:8px 18px;border-radius:10px;color:#fff;
             font-size:1.05rem;font-weight:700;}
      .kv {font-size:0.78rem;color:#64748b;text-transform:uppercase;letter-spacing:0.04em;
             margin-bottom:2px;}
      .muted {color:#64748b;}
    </style>
    """,
    unsafe_allow_html=True,
)


def chip(text, color):
    return f'<span class="chip" style="background:{color}">{text}</span>'


def outline_chip(text):
    return f'<span class="chip-outline">{text}</span>'


# --------------------------------------------------------------------------
# Header
# --------------------------------------------------------------------------

st.title("🧩 Composio Buildability Researcher")
st.markdown(
    "Search an app and watch the research agent run the **entire flow live** — "
    "the same pipeline behind the 100-app case study, for one app on demand. "
    f"**Gemini** reasons (chain led by `{MODEL}`, with automatic fallback); "
    "**Composio's** no-auth search toolkit is its hands."
)
st.markdown(
    f"📄 **[Read the full 100-app case study →]({CASE_STUDY_URL})**"
    "  ·  findings, patterns, prioritization, and the verification results."
)

if INSIGHTS:
    t = INSIGHTS["totals"]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Apps studied", t["apps"])
    c2.metric("Buildable today", f'{t["buildable_pct"]}%')
    c3.metric("Self-serve", f'{t["self_serve_pct"]}%')
    c4.metric("Official MCP", t["official_mcp"])

st.divider()

# --------------------------------------------------------------------------
# Search
# --------------------------------------------------------------------------

app_names = sorted(a["app"] for a in APPS)

custom = st.toggle("Research an app **not** in the 100-app set", value=False)
left, right = st.columns([3, 1], vertical_alignment="bottom")
with left:
    if custom:
        query = st.text_input(
            "App name", placeholder="e.g. Calendly", label_visibility="collapsed"
        )
    else:
        query = st.selectbox(
            "Pick one of the 100 apps",
            app_names,
            index=None,
            placeholder="Search the 100 research-set apps…",
            label_visibility="collapsed",
        )
with right:
    run = st.button("▶ Run research", type="primary", width="stretch")


# --------------------------------------------------------------------------
# Rendering
# --------------------------------------------------------------------------

def render_row(row, report):
    v = row["buildability_verdict"]
    st.markdown(
        f'<span class="big-verdict" style="background:{VERDICT_COLOR[v]}">'
        f'{VERDICT_LABEL.get(v, v)}</span>',
        unsafe_allow_html=True,
    )
    st.markdown(f"### {row['app']}")
    st.markdown(f"*{row['one_line_description']}*")
    st.caption(row["category"])

    col1, col2 = st.columns(2)
    with col1:
        st.markdown('<div class="kv">Auth methods</div>', unsafe_allow_html=True)
        st.markdown(
            "".join(outline_chip(a) for a in row["auth_methods"]),
            unsafe_allow_html=True,
        )
        st.write(f'<span class="muted">{row["auth_summary"]}</span>', unsafe_allow_html=True)

        st.markdown('<div class="kv">Access model</div>', unsafe_allow_html=True)
        am = row["access_model"]
        st.markdown(
            chip(ACCESS_LABEL.get(am, am), ACCESS_COLOR.get(am, "#6b7280")),
            unsafe_allow_html=True,
        )
        if row.get("access_notes"):
            st.write(f'<span class="muted">{row["access_notes"]}</span>', unsafe_allow_html=True)
    with col2:
        st.markdown('<div class="kv">API surface</div>', unsafe_allow_html=True)
        st.markdown(
            outline_chip(SURFACE_LABEL.get(row["api_surface_type"], row["api_surface_type"]))
            + outline_chip(row["api_surface_breadth"]),
            unsafe_allow_html=True,
        )
        st.write(f'<span class="muted">{row["api_surface_summary"]}</span>', unsafe_allow_html=True)

        st.markdown('<div class="kv">MCP status</div>', unsafe_allow_html=True)
        st.markdown(outline_chip(MCP_LABEL.get(row["mcp_status"], row["mcp_status"])),
                    unsafe_allow_html=True)
        if row.get("existing_mcp_url"):
            st.markdown(f'[{row["existing_mcp_url"]}]({row["existing_mcp_url"]})')

    if row.get("main_blocker") and row["main_blocker"].strip().lower() not in ("none", ""):
        st.markdown('<div class="kv">Main blocker</div>', unsafe_allow_html=True)
        st.warning(row["main_blocker"])

    conf = row["confidence"]
    st.markdown(
        '<div class="kv">Confidence</div>'
        + chip(conf.upper(), CONFIDENCE_COLOR.get(conf, "#6b7280")),
        unsafe_allow_html=True,
    )
    if row.get("agent_notes"):
        with st.expander("Agent notes"):
            st.write(row["agent_notes"])

    # Evidence with pass-2 live/dead status
    st.markdown('<div class="kv">Evidence (pass-2 URL check)</div>', unsafe_allow_html=True)
    checks = {c["url"]: c for c in report.get("url_checks", [])}
    for url in row["evidence_urls"]:
        c = checks.get(url, {})
        if c.get("ok") and not c.get("note"):
            mark = "🟢"
        elif c.get("ok"):
            mark = "🟡"  # reachable but bot-blocked
        else:
            mark = "🔴"
        st.markdown(f"{mark} [{url}]({url})")
    if report.get("flags"):
        st.caption("Flags: " + ", ".join(report["flags"]))
    else:
        st.caption("No evidence flags — links resolve and at least one is on an official domain.")

    with st.expander("Raw schema-validated JSON row"):
        st.json(row)


def render_patterns(row):
    if not INSIGHTS:
        return
    st.markdown("#### How this app fits the 100-app patterns")
    d = INSIGHTS["distributions"]
    total = INSIGHTS["totals"]["apps"]
    bits = []
    for a in row["auth_methods"]:
        n = d["auth_methods"].get(a, 0)
        if n:
            bits.append(f"**{a}** auth appears in **{n}/{total}** apps.")
    verdict_n = d["buildability_verdict"].get(row["buildability_verdict"], 0)
    bits.append(
        f"**{VERDICT_LABEL.get(row['buildability_verdict'])}** describes "
        f"**{verdict_n}/{total}** apps."
    )
    mcp_n = d["mcp_status"].get(row["mcp_status"], 0)
    bits.append(f"**{MCP_LABEL.get(row['mcp_status'])}** applies to **{mcp_n}/{total}** apps.")
    for b in bits:
        st.markdown("- " + b)


def render_committed_comparison(row):
    """If this app is one of the 100, show the study's verified answer alongside."""
    seed = find_app(row["app"])
    if not seed or seed["id"] not in RESULTS_BY_ID:
        return
    committed = RESULTS_BY_ID[seed["id"]]
    fields = [
        ("Auth", lambda r: ", ".join(r["auth_methods"])),
        ("Access", lambda r: ACCESS_LABEL.get(r["access_model"], r["access_model"])),
        ("API surface", lambda r: SURFACE_LABEL.get(r["api_surface_type"], r["api_surface_type"])),
        ("MCP", lambda r: MCP_LABEL.get(r["mcp_status"], r["mcp_status"])),
        ("Verdict", lambda r: VERDICT_LABEL.get(r["buildability_verdict"], r["buildability_verdict"])),
        ("Confidence", lambda r: r["confidence"]),
    ]
    with st.expander(
        f"Compare to the study's committed answer for {committed['app']} "
        f"({'verified by human QA' if committed.get('verified') else 'first-pass'})"
    ):
        rows = []
        for name, fn in fields:
            live_val, comm_val = fn(row), fn(committed)
            match = "✅" if live_val == comm_val else "⚠️"
            rows.append({"Field": name, "This live run": live_val,
                         "Committed study": comm_val, "": match})
        st.dataframe(rows, hide_index=True, width="stretch")
        st.caption(
            "⚠️ marks where the live run diverged from the committed dataset — "
            "expected occasionally: different model (Gemini vs. the study's run), "
            "point-in-time web results, and MCP status churn."
        )


# --------------------------------------------------------------------------
# Run
# --------------------------------------------------------------------------

if run:
    if not query or not query.strip():
        st.warning("Pick an app or type a name first.")
        st.stop()

    app = app_dict(query)
    if app["id"] == 0:
        st.info(f"“{app['app']}” isn't in the 100-app set — researching it ad-hoc.")

    status = st.status(f"Researching **{app['app']}** …", expanded=True)

    used_models = []

    def on_event(kind, **d):
        if kind == "status":
            status.write(f"⚙️ {d['message']}")
        elif kind == "model_used":
            used_models.append(d["name"])
            status.write(f"🤖 Model: `{d['name']}`")
        elif kind == "rate_limited":
            status.write(f"⏳ {d['message']}")
        elif kind == "turn":
            status.write(f"**Turn {d['n']}/{d['total']}** — Gemini deciding next step…")
        elif kind == "tool_call":
            label = TOOL_LABEL.get(d["name"], d["name"])
            arg = d["args"].get("query") or (
                ", ".join(d["args"].get("urls", [])) if d["args"].get("urls") else ""
            )
            arg = (arg[:90] + "…") if len(str(arg)) > 90 else arg
            status.write(f"&nbsp;&nbsp;🔧 **{label}** — `{arg}`")
        elif kind == "tool_result":
            status.write(
                f"&nbsp;&nbsp;{'✅' if d['ok'] else '❌'} {TOOL_LABEL.get(d['name'], d['name'])} returned"
            )
        elif kind == "thinking" and d["text"]:
            snippet = d["text"][:200] + ("…" if len(d["text"]) > 200 else "")
            status.write(f"&nbsp;&nbsp;💭 _{snippet}_")

    fell_back = False
    try:
        row = research_app_live(app, on_event)
        report = verify_row_live(row, on_event)
        status.update(label=f"✅ Done — researched {app['app']}", state="complete",
                      expanded=False)
    except Exception as exc:  # surface honestly, and salvage seed apps
        err_name = type(exc).__name__
        seed = find_app(app["app"])
        cached = RESULTS_BY_ID.get(seed["id"]) if seed else None
        if cached:
            fell_back = True
            row = cached
            report = verify_row_live(row, on_event)
            status.update(
                label="⚠️ Live tier exhausted — showing the study's verified result",
                state="error", expanded=False,
            )
        else:
            status.update(label="❌ Research failed", state="error")
            st.error(f"{type(exc).__name__}: {exc}")
            st.info(
                "The free Gemini tier is very constrained (models churn / rate-limit). "
                "Try again in a minute, pick one of the 100 seed apps (those have a "
                "committed result to fall back on), or set a higher-quota "
                "`RESEARCH_MODEL`/key."
            )
            st.stop()

    st.divider()
    if fell_back:
        st.warning(
            f"⚠️ Live research couldn't complete on the free tier just now "
            f"(`{err_name}`). Showing **{app['app']}**'s committed result "
            "from the 100-app study — verified by human QA — so the flow still "
            "produces the answer. Retry in a minute for a fresh live run.",
            icon="⚠️",
        )
    elif used_models:
        st.caption(
            "Researched live via "
            + ", ".join(f"`{m}`" for m in dict.fromkeys(used_models))
            + " driving Composio's COMPOSIO_SEARCH tools."
        )
    render_row(row, report)
    st.divider()
    render_patterns(row)
    if not fell_back:
        render_committed_comparison(row)

else:
    st.caption(
        "Pick an app and hit **Run research**. On the free Gemini tier a run takes "
        "roughly 30–90s and may pause for rate limits — that's expected."
    )
