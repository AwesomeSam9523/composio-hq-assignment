# Agentic API Buildability Research × 100 Apps

A take-home case study for the AI Product Ops Intern role at Composio.

An AI research agent investigated **100 apps across 10 categories** — what each app does, its auth
methods, whether developer access is self-serve or gated, its API surface, whether an MCP server
already exists, and whether Composio could ship an agent-callable toolkit today — with evidence URLs
behind every claim. A **two-stage verification loop** (automated evidence validation + a 20-app
human-QA sample) then measured whether the results can be trusted, honestly.

**The case study:** open [`index.html`](index.html) — a single self-explanatory static page
(headline findings, pattern dashboard, prioritization matrix, verification results, full filterable
table of all 100 apps). Deployable as-is on Vercel / Netlify / GitHub Pages; no build step, no
external requests.

**The live proof ([`app.py`](app.py)):** a Streamlit app where you search for *any* app and watch
the **entire research flow execute live** — the same pipeline, for one app on demand. **Gemini**
reasons; **Composio's** no-auth search toolkit is its hands. It streams every tool call, emits the
same schema-validated row, HTTP-checks the evidence (pass 2), and — for the 100 seed apps — diffs
the live answer against the committed dataset. Run it locally (`streamlit run app.py`) or deploy it
on Railway (below).

## Headline results

- **85 / 100 apps are buildable today** (66 build-now, 19 build-with-limits); only 15 need a
  partner, paid contract, or sales conversation first.
- **62% of apps hand out credentials fully self-serve**; gating concentrates in ads APIs
  (approval reviews), financial data (contracts), and enterprise suites (sales-led accounts).
- **70 / 100 vendors already ship an official MCP server** — MCP existence is table stakes;
  the toolkit opportunity is breadth, auth brokering, and orchestration.
- **OAuth2 (60 apps) and API keys (55) split the world**: OAuth2 for user-data SaaS,
  keys/PATs for developer & data APIs.
- **Verification: 94.2% first-pass accuracy** on a 120-field-check QA sample → **100% after 7
  corrections** (biggest miss: Otter AI's newly launched public API, first recorded as
  "no public API found").

## What the agent does

`pipeline/research_agent.py` researches one app at a time with **live web search** — **Gemini**
reasons and **Composio's** no-auth `COMPOSIO_SEARCH` toolkit is its hands (no separate search key
or scraping stack):

1. Finds official developer docs (preferring them over blog posts), auth pages, and API references.
2. Checks how a developer actually gets credentials (self-serve vs. trial vs. paid vs. approval vs.
   partner vs. contact-sales).
3. Hunts for MCP servers ("`<app>` MCP server", "`<app>` Model Context Protocol") across vendor
   docs and GitHub, distinguishing official from community.
4. Emits one row per app, validated against a strict JSON Schema (`pipeline/schema.json`) —
   exact enums for auth methods / access model / API surface / MCP status / buildability verdict,
   required evidence URLs, and a confidence grade. The prompt contract requires marking uncertainty
   as `unclear` instead of guessing, and being explicit when an app is gated or undocumented.

Each app's result is cached in `data/raw/<id>.json`, so the run **resumes** after interruption
without losing progress and individual apps can be re-run with `--ids` / `--force`.

> **Built on Composio, in the spirit of the role.** The researcher runs as a **Composio-powered
> agent**: its search/fetch tools are Composio's no-auth `COMPOSIO_SEARCH` toolkit
> (`COMPOSIO_SEARCH_WEB`, `COMPOSIO_SEARCH_TAVILY`, `COMPOSIO_SEARCH_NEWS`,
> `COMPOSIO_SEARCH_FETCH_URL_CONTENT`), fetched via the Composio SDK (`GeminiProvider`) and
> executed through `provider.handle_response` in an agentic loop, while **Gemini** does the
> reasoning. The batch pipeline and the live Streamlit app share this one engine
> (`research_app`) — the demo just streams each step. Honesty note: the **committed dataset**
> was produced by an earlier agentic run (parallel research agents with web search + page
> fetching) on **July 9, 2026**; re-running `research_agent.py` with a `GEMINI_API_KEY` +
> `COMPOSIO_API_KEY` regenerates it live, and the Gemini + Composio path has been exercised
> end-to-end via the live app.

## Repo layout

```
app.py                 the live Streamlit app (search an app → run the flow)
railway.json           Railway deploy config (build + start command)
Procfile               Railway/Nixpacks web start command
.python-version        pins Python 3.12 for the deploy
.streamlit/config.toml Streamlit server settings (headless, CORS/XSRF off)
pipeline/
  apps.json            seed list — 100 apps × 10 categories
  schema.json          JSON Schema every row must pass
  research_agent.py    pass 1 (batch): research all 100 (resumable, schema-validated)
  live_research.py     pass 1 for ONE app on demand — Gemini + Composio, streamed
  verify_evidence.py   pass 2: HTTP-check every evidence URL, flag weak rows
  qa_sample.py         pass 3: stratified 20-app QA worksheet + apply corrections
  analyze.py           pattern analysis → data/insights.json
  build_page.py        inject data + live-demo link into template.html → index.html
  template.html        the case-study page template
data/
  links.json           live-demo + repo URLs injected into the case-study page
  results.json         canonical dataset (post-verification) — 100 rows
  results.csv          same, flat CSV
  raw/                 per-app first-pass cache (pre-correction, kept for transparency)
  evidence_report.json pass-2 output: URL checks, dead links, flags
  qa/sample.json       the 20-app QA worksheet (what was checked)
  qa/corrections.json  all 120 field checks with verdicts and evidence
  verification.json    accuracy metrics + the full QA table
  insights.json        computed distributions, category matrix, blocker themes
index.html             the case study (self-contained, static)
```

## How to run

```bash
pip install -r requirements.txt
cp .env.example .env                  # add GEMINI_API_KEY + COMPOSIO_API_KEY (both free tiers work)

python pipeline/research_agent.py     # pass 1 — research all 100 apps (resumes; ~1-2h, API costs apply)
python pipeline/verify_evidence.py    # pass 2 — validate all evidence URLs (network only, no key needed)
python pipeline/qa_sample.py          # pass 3 — emit data/qa/sample.json for human review
#   ...fill data/qa/corrections.json (one entry per field checked; see qa_sample.py docstring)...
python pipeline/qa_sample.py --apply  # apply corrections, mark rows verified, compute accuracy
python pipeline/analyze.py            # recompute insights
python pipeline/build_page.py         # regenerate index.html
```

Only `research_agent.py` needs API keys (`GEMINI_API_KEY` + `COMPOSIO_API_KEY`). No paid accounts
were created for any of the 100 apps —
where credentials sit behind payment, partnership, approval, or contact-sales, **that is recorded
as the finding**.

## Run the live app (Streamlit)

Search an app and watch the **entire flow execute live** for that one app — the same research +
verification pipeline, streamed. Here the agent is driven by **Google Gemini** over **Composio's**
COMPOSIO_SEARCH tools (Gemini reasons, Composio searches/fetches).

```bash
pip install -r requirements.txt
cp .env.example .env      # set GEMINI_API_KEY + COMPOSIO_API_KEY (both free tiers work)

streamlit run app.py                          # → http://localhost:8501
python pipeline/live_research.py "Notion"     # same flow, headless CLI
```

- **Keys:** `GEMINI_API_KEY` ([AI Studio](https://aistudio.google.com/apikey), free) reasons;
  `COMPOSIO_API_KEY` ([app.composio.dev](https://app.composio.dev), free) serves the search tools.
- **Model resilience:** Gemini free-tier models churn (deprecations, 429/503). `live_research.py`
  walks a **fallback chain** (`gemini-3-flash-preview` → `-flash-lite` → …), skipping retired/
  quota'd models and retrying transient overloads. Override with `RESEARCH_MODEL` on a paid key.
- **Weak-model guard:** the row is normalized and, if it still fails the JSON Schema, a **one-shot
  repair** re-prompts with the validator errors before giving up.
- **Graceful fallback:** if the free tier is exhausted mid-run, for any of the 100 seed apps the app
  shows the study's committed (human-QA'd) row instead of erroring — labeled honestly.

## Deploy on Railway

The repo is Railway-ready (`railway.json` + `Procfile` set the Streamlit start command; `.python-version`
pins 3.12). Deploy from GitHub:

1. Push this repo to GitHub (`.env` is gitignored — set keys in Railway instead).
2. Railway → **New Project → Deploy from GitHub repo** → pick this repo. Nixpacks auto-installs
   `requirements.txt` and runs the `Procfile` web command.
3. Add **Variables**: `GEMINI_API_KEY` and `COMPOSIO_API_KEY` (optionally `RESEARCH_MODEL`,
   `COMPOSIO_USER_ID`). Railway injects `$PORT` automatically.
4. Under **Settings → Networking**, generate a public domain. That URL is your live app.
5. Point the case study at it and rebuild the page:
   ```bash
   LIVE_DEMO_URL="https://<your-app>.up.railway.app" python pipeline/build_page.py
   ```
   (the URL is saved to `data/links.json`, so later rebuilds keep it). Commit `index.html` and push.

The start command is `streamlit run app.py --server.port $PORT --server.address 0.0.0.0 --server.headless true`.

## Verification, honestly

- **Pass 2 (automated):** all **381 evidence URLs** were HTTP-checked; 13 dead links (3.4%) and
  14 rows flagged (dead links or no official-domain evidence). Flags fed the QA sample.
- **Pass 3 (human QA):** 20 apps (2 per category, biased toward low-confidence and flagged rows),
  6 fields each = **120 checks**, re-verified against official docs and adjudicated by hand.
  - First-pass accuracy: **94.2%** (113/120)
  - Corrections: **7**, across 4 rows (Otter AI ×4, Consensus, Coda, systeme.io)
  - Final accuracy on sampled fields: **100%**
  - Error profile: stale "no API" claims on fast-moving AI vendors, MCP-status churn
    (community → official), and over/under-stated free-text blockers.
- `data/raw/` intentionally preserves the *uncorrected* first-pass rows so the before/after diff
  is auditable.

## Known limitations

- **Point-in-time snapshot (July 2026).** MCP status is the fastest-moving field; expect churn.
- **QA covered 20 of 100 apps.** Unsampled rows carry first-pass accuracy (~94% by extrapolation);
  the per-row `confidence` field flags where evidence was weakest.
- Some rows rest on official-doc snippets surfaced in search rather than full page fetches — those
  are graded `medium` confidence with the gap named in `agent_notes`.
- URL checking can misread bot-blocked sites (Meta/Facebook, some help centers); flags are QA
  inputs, not verdicts.
- Pricing/access gates come from vendor pages, not purchase attempts.

## Where human judgment was needed

- **Ambiguous identities** — "Paygent Connect" (Japanese gateway vs. the hinted NMI product),
  iPayX vs. unrelated "iPay" brands, Consensus vs. goConsensus, Clay vs. clay.earth. The agent
  flagged these; a human decided what the row should mean (and kept confidence low).
- **Enum boundary calls** — self-serve vs. trial-gated vs. paid-plan; what counts as an
  "official" MCP when vendors ship betas and EAPs.
- **QA adjudication** — deciding when a first-pass answer was substantively wrong vs. loosely
  worded (only substantive errors counted against accuracy).
- **Prioritization** — the build-first / outreach lists apply judgment (ecosystem pull, credential
  friction) on top of the data.
