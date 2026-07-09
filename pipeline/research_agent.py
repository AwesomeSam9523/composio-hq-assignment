"""Research agent: researches each app with live web search and produces one
schema-validated row per app.

Brain + tools are cleanly separated, in the spirit of the role:

  * Reasoning is done by **Google Gemini** (a fallback chain of models, since the
    free tier churns hard — see MODEL_CHAIN).
  * The agent's search/fetch tools are served by **Composio** itself: the
    no-auth COMPOSIO_SEARCH toolkit (web search, Tavily search, news search, URL
    content fetch), fetched via the Composio SDK and executed through
    `provider.handle_response`. The researcher is literally a Composio-powered
    agent. Both GEMINI_API_KEY and COMPOSIO_API_KEY are required.

Usage:
    python pipeline/research_agent.py                # research all 100 apps (resumes)
    python pipeline/research_agent.py --ids 1 2 3    # research specific apps
    python pipeline/research_agent.py --force        # re-research even if cached

Each app's raw result is cached in data/raw/<id>.json, so the run can be
interrupted and resumed without losing progress. Final merged output goes to
data/results.json and data/results.csv. See .env.example for configuration.

The same engine (`research_app`) powers the live single-app Streamlit demo via
`live_research.py`, which just passes an `on_event` callback to stream progress.
"""

import argparse
import copy
import csv
import json
import os
import sys
import time
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

from google import genai
from google.genai import types

from composio import Composio
from composio_gemini import GeminiProvider

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw"
APPS = json.loads((ROOT / "pipeline" / "apps.json").read_text())
SCHEMA = json.loads((ROOT / "pipeline" / "schema.json").read_text())

# The batch pins each row's id to its 1..100 seed index, but the live demo can
# also research an ad-hoc app that isn't in the seed list (id=0). Validate id>=0
# so both paths share one validator; `_pin_identity` overwrites id from the seed
# dict after extraction, so the model's own id is never what gets validated.
_VALIDATOR_SCHEMA = copy.deepcopy(SCHEMA)
_VALIDATOR_SCHEMA["properties"]["id"]["minimum"] = 0
VALIDATOR = Draft202012Validator(_VALIDATOR_SCHEMA)

COMPOSIO_USER_ID = os.environ.get("COMPOSIO_USER_ID", "buildability-research")
MAX_TOOL_TURNS = int(os.environ.get("MAX_TOOL_TURNS", "12"))

# The subset of Composio's no-auth COMPOSIO_SEARCH toolkit this agent needs:
# search the web, search news, and read documentation pages.
COMPOSIO_TOOL_SLUGS = [
    "COMPOSIO_SEARCH_WEB",
    "COMPOSIO_SEARCH_TAVILY",
    "COMPOSIO_SEARCH_NEWS",
    "COMPOSIO_SEARCH_FETCH_URL_CONTENT",
]

# Gemini model churn is real: on 2026-07-10 the 2.x flash models started
# returning 404 "no longer available", and the newest models 503 under load. So
# instead of one fixed model we try a CHAIN — skip models that are gone (404) or
# out of quota (429, a separate bucket per model), and retry transient overloads
# (503). RESEARCH_MODEL, if set, is tried first.
DEFAULT_MODEL_CHAIN = [
    "gemini-3-flash-preview",         # best quality + schema adherence observed
    "gemini-3.1-flash-lite-preview",  # most reliable fallback (weaker; may need repair)
    "gemini-3.5-flash",
    "gemini-2.0-flash-001",
]
_override = os.environ.get("RESEARCH_MODEL")
MODEL_CHAIN = ([_override] if _override else []) + [
    m for m in DEFAULT_MODEL_CHAIN if m != _override
]
MODEL = MODEL_CHAIN[0]  # display / default label

# Short backoff for transient 503s before falling to the next model.
_OVERLOAD_WAITS = [3, 7, 12]
# Long waits (s) once every model is rate-limited (per-minute quota resets).
_RATE_WAITS = [0, 30, 55]

PROMPT_TEMPLATE = """You are a research agent for Composio, which turns SaaS apps into tools AI agents can call. Research this app using the search and URL-fetch tools available to you, then produce ONE JSON object.

APP: {app} (id {id}, category "{category}", hint: {hint})

Research process:
1. Find official developer docs (prefer developer docs over blog posts).
2. Check auth docs specifically - which auth methods does the API actually support? Distinguish exactly: OAuth2, API key, Personal access token, Bearer token, Basic auth, Bot token, JWT, Private app token, App password, Service account, CLI/local auth, HMAC signature. Do NOT assume OAuth just because the app has integrations.
3. Check the API reference - REST/GraphQL/etc. and how broad the surface is.
4. Check how a developer gets credentials: self-serve vs paid plan, admin approval, partner program, or contact-sales.
5. Search for MCP servers: "{app} MCP server" and "{app} Model Context Protocol" (official docs + GitHub).
6. Classify buildability for Composio today.

Honesty rules: every important claim needs an evidence URL you actually saw - NEVER invent URLs. If docs are gated, thin, or contradictory, use "unclear" enums and lower confidence. It is better to say "unclear" than to guess.

When your research is complete, return ONLY a raw JSON object (no markdown fences) with exactly these fields:
{schema_fields}

Enum values must match exactly. Set "verified": false and "verification_notes": "".
"""

SCHEMA_FIELDS = json.dumps(
    {k: v.get("enum", v.get("type", "")) for k, v in SCHEMA["properties"].items()},
    indent=2,
)


def _noop(*_args, **_kwargs):
    pass


# --------------------------------------------------------------------------
# Gemini call (fallback chain) + Composio tool wiring
# --------------------------------------------------------------------------

def _generate_with_retry(client, contents, config, on_event):
    """Call Gemini across the model chain, returning (response, model_used).

    - 404 (model retired) / 429 (that model's quota gone): move to next model.
    - 503 (overloaded): short backoff, retry same model a few times, then move on.
    - If every model is rate-limited, wait for the per-minute window and re-sweep.
    """
    from google.genai import errors as genai_errors

    last_exc = None
    for _rate_pass, rate_wait in enumerate(_RATE_WAITS):
        if rate_wait:
            on_event(
                "rate_limited",
                message=f"All Gemini models busy/limited — waiting {rate_wait}s…",
                wait=rate_wait,
            )
            time.sleep(rate_wait)
        for model in MODEL_CHAIN:
            for attempt in range(len(_OVERLOAD_WAITS) + 1):
                try:
                    resp = client.models.generate_content(
                        model=model, contents=contents, config=config
                    )
                    return resp, model
                except genai_errors.ServerError as exc:  # 503 overloaded
                    last_exc = exc
                    if attempt == len(_OVERLOAD_WAITS):
                        break  # give up on this model, try next
                    time.sleep(_OVERLOAD_WAITS[attempt])
                except genai_errors.ClientError as exc:
                    code = getattr(exc, "code", None)
                    last_exc = exc
                    if code in (404, 429):
                        break  # retired or out of quota — next model
                    raise  # 400/401/403 etc. are real errors
    raise RuntimeError(
        "Every Gemini model in the chain was unavailable or rate-limited. "
        "The free tier is very constrained — wait a minute and retry, or set a "
        "higher-quota key / RESEARCH_MODEL."
    ) from last_exc


def build_agent():
    """Wire Composio's COMPOSIO_SEARCH tools to a Gemini client. Returns
    (client, provider, tools). Raises a clear error if keys are missing."""
    if not os.environ.get("GEMINI_API_KEY"):
        raise RuntimeError("GEMINI_API_KEY is not set")
    if not os.environ.get("COMPOSIO_API_KEY"):
        raise RuntimeError("COMPOSIO_API_KEY is not set")

    provider = GeminiProvider()
    composio = Composio(provider=provider)
    tools = composio.tools.get(user_id=COMPOSIO_USER_ID, tools=COMPOSIO_TOOL_SLUGS)
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    return client, provider, tools


# --------------------------------------------------------------------------
# Row production
# --------------------------------------------------------------------------

def extract_json(text: str):
    """Pull the first JSON object out of a model response."""
    start = text.find("{")
    if start == -1:
        raise ValueError("no JSON object in response")
    depth = 0
    for i, ch in enumerate(text[start:], start):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return json.loads(text[start : i + 1])
    raise ValueError("unbalanced JSON in response")


_STRING_FIELDS = {
    k for k, v in SCHEMA["properties"].items()
    if v.get("type") == "string" or ("enum" in v and v.get("type") != "array")
}
_ARRAY_FIELDS = {
    k for k, v in SCHEMA["properties"].items() if v.get("type") == "array"
}


def _coerce_row(row: dict) -> dict:
    """Fix the type slips weaker models make: scalar-enum fields wrapped in a
    one-element list (['self_serve'] -> 'self_serve'), and array fields given a
    bare string (a single evidence URL string -> [url]). Cheaper and more
    reliable than a model round-trip."""
    if not isinstance(row, dict):
        return row
    for key in list(row):
        val = row[key]
        if key in _STRING_FIELDS and isinstance(val, list) and len(val) == 1:
            row[key] = val[0]
        elif key in _ARRAY_FIELDS and isinstance(val, str):
            row[key] = [val]
    return row


def _repair_row(client, app, bad_row, errors, on_event):
    """One-shot repair: hand the model its invalid row + the exact validator
    errors and ask for a corrected JSON object. Uses the first working model."""
    on_event("status", message="Row failed schema — asking the model to repair it…")
    msg = (
        "The JSON row you produced for this research task failed schema "
        "validation. Fix ONLY the structure/enum values so it validates; keep "
        "the researched facts and evidence URLs unchanged. Return ONLY the "
        "corrected raw JSON object.\n\n"
        f"Allowed field values:\n{SCHEMA_FIELDS}\n\n"
        f"Validation errors:\n- " + "\n- ".join(errors[:8]) + "\n\n"
        f"Your row:\n{json.dumps(bad_row, ensure_ascii=False)}"
    )
    config = types.GenerateContentConfig(temperature=0)
    contents = [types.Content(role="user", parts=[types.Part(text=msg)])]
    response, _model = _generate_with_retry(client, contents, config, on_event)
    text = "".join(
        p.text for p in (response.candidates[0].content.parts or [])
        if getattr(p, "text", None)
    )
    return _coerce_row(extract_json(text))


def _pin_identity(row: dict, app: dict) -> dict:
    """Pin identity fields so a confused model can't mislabel a row."""
    row.update(
        id=app["id"],
        app=app["app"],
        category=app["category"],
        website_hint=app["website_hint"],
        verified=False,
    )
    row.setdefault("verification_notes", "")
    return row


def research_app(app: dict, on_event=_noop) -> dict:
    """Research one app with Gemini driving Composio search tools in a manual
    function-calling loop, emitting progress through on_event(kind, **data):

        ("status", message=...)                       coarse phase updates
        ("model_used", name=...)                       which model answered
        ("turn", n=..., total=...)                    each model turn
        ("tool_call", name=..., args=...)             a Composio tool Gemini chose
        ("tool_result", name=..., ok=...)             that tool returned
        ("thinking", text=...)                        interim model text, if any
        ("final", row=...)                            the validated row

    Returns the schema-validated row (also emitted as the final event). The
    batch pipeline uses the default no-op callback; the live app passes one that
    renders each step.
    """
    on_event("status", message="Connecting Gemini to Composio search tools…")
    client, provider, tools = build_agent()

    prompt = PROMPT_TEMPLATE.format(
        app=app["app"],
        id=app["id"],
        category=app["category"],
        hint=app["website_hint"] or "(no hint — search for the official site)",
        schema_fields=SCHEMA_FIELDS,
    ) + (
        "\n\nIMPORTANT: Actually USE the search/fetch tools before answering — at "
        "minimum search the developer docs, the auth docs, and for an MCP server. "
        "Do not answer from prior knowledge alone. For every field whose allowed "
        "values are a single enum (access_model, api_surface_type, "
        "api_surface_breadth, mcp_status, buildability_verdict, confidence), return "
        "a plain STRING, not a list. auth_methods and evidence_urls are the only "
        "arrays."
    )
    config = types.GenerateContentConfig(
        tools=tools,
        temperature=0,
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    )
    contents = [types.Content(role="user", parts=[types.Part(text=prompt)])]

    final_text = ""
    current_model = None
    for turn in range(1, MAX_TOOL_TURNS + 1):
        on_event("turn", n=turn, total=MAX_TOOL_TURNS)
        response, used_model = _generate_with_retry(client, contents, config, on_event)
        if used_model != current_model:
            current_model = used_model
            on_event("model_used", name=used_model)
        candidate = response.candidates[0]
        parts = candidate.content.parts or []
        contents.append(candidate.content)

        interim = "".join(p.text for p in parts if getattr(p, "text", None))
        if interim.strip():
            on_event("thinking", text=interim.strip())

        for p in parts:
            fc = getattr(p, "function_call", None)
            if fc:
                on_event("tool_call", name=fc.name, args=dict(fc.args or {}))

        function_responses, executed = provider.handle_response(response)
        if not executed:
            final_text = interim
            break

        for fr in function_responses:
            resp = fr.function_response.response or {}
            on_event("tool_result", name=fr.function_response.name,
                     ok="error" not in resp)
        contents.append(types.Content(role="user", parts=function_responses))
    else:
        raise RuntimeError(f"no final answer after {MAX_TOOL_TURNS} tool turns")

    if not final_text.strip():
        raise RuntimeError("agent stopped without producing a result")

    on_event("status", message="Validating the row against the schema…")
    row = _pin_identity(_coerce_row(extract_json(final_text)), app)
    errors = sorted(VALIDATOR.iter_errors(row), key=lambda e: list(e.path))

    if errors:  # one-shot repair before giving up
        try:
            repaired = _repair_row(
                client, app, row, [e.message for e in errors], on_event
            )
            repaired = _pin_identity(repaired, app)
            repaired_errors = sorted(
                VALIDATOR.iter_errors(repaired), key=lambda e: list(e.path)
            )
            if not repaired_errors:
                row, errors = repaired, []
            else:
                errors = repaired_errors
        except Exception:  # repair failed; fall through to the original errors
            pass

    if errors:
        raise ValueError(
            f"schema validation failed for {app['app']}: "
            + "; ".join(e.message for e in errors[:5])
        )
    on_event("final", row=row)
    return row


def merge_results() -> list[dict]:
    return [
        json.loads(f.read_text())
        for f in sorted(RAW_DIR.glob("*.json"), key=lambda p: int(p.stem))
    ]


def write_outputs(rows: list[dict]) -> None:
    out = ROOT / "data" / "results.json"
    out.write_text(json.dumps(rows, indent=2, ensure_ascii=False))
    csv_path = ROOT / "data" / "results.csv"
    if rows:
        with csv_path.open("w", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(SCHEMA["properties"].keys()))
            writer.writeheader()
            for row in rows:
                flat = dict(row)
                flat["auth_methods"] = "; ".join(row["auth_methods"])
                flat["evidence_urls"] = "; ".join(row["evidence_urls"])
                writer.writerow(flat)
    print(f"wrote {out} and {csv_path} ({len(rows)} rows)")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ids", nargs="*", type=int, help="only these app ids")
    parser.add_argument("--force", action="store_true", help="ignore cache")
    args = parser.parse_args()

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    print(f"tool layer: Gemini ({MODEL}) driving Composio's COMPOSIO_SEARCH toolkit")

    targets = [a for a in APPS if not args.ids or a["id"] in args.ids]
    failures = []
    for app in targets:
        cache = RAW_DIR / f"{app['id']:03d}.json"
        if cache.exists() and not args.force:
            print(f"[{app['id']:3d}] {app['app']}: cached, skipping")
            continue
        print(f"[{app['id']:3d}] {app['app']}: researching...")
        try:
            row = research_app(app)
            cache.write_text(json.dumps(row, indent=2, ensure_ascii=False))
            print(f"[{app['id']:3d}] {app['app']}: done ({row['buildability_verdict']})")
        except Exception as exc:  # keep going; resume handles retries
            failures.append((app["app"], str(exc)))
            print(f"[{app['id']:3d}] {app['app']}: FAILED - {exc}", file=sys.stderr)
        time.sleep(1)  # be polite to rate limits

    write_outputs(merge_results())
    if failures:
        print(f"\n{len(failures)} apps failed; re-run to retry:", file=sys.stderr)
        for name, err in failures:
            print(f"  - {name}: {err}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
