# Cost Guardian — Phases

Status symbols: ✓ Complete · ◐ In progress · ○ Not started · ⚠ Blocked

This file is the source of truth for phase tracking (supersedes the older phase
numbering in `docs/PLAN.md`, which remains as build-plan detail/history). Every
completed item below carries a one-line verification statement — "implemented" alone
is not a valid status per the project's tracking rules.

---

## ✓ Phase 0 — Repository stabilization

- ✓ Remove dead Datadog/ddtrace runtime dependency
  _Verified: `ddtrace`/`datadog_api_client` no longer imported anywhere in the live
  path (`orchestrator.py`, `llm_fallback.py`); `grep` confirms zero matches outside the
  untouched, unimported `backend/observability/` legacy folder._
- ✓ Remove obsolete commented orchestrator implementations
  _Verified: `orchestrator.py` reduced from ~1000 lines (LangGraph/CrewAI/plain-async
  dead variants) to ~140 lines of live code._
- ✓ Fix existing detector structural bugs
  _Verified: rebuilt cleanly in `backend/guardian/detectors/` rather than patched in
  place (per the decision to not blindly repair `backend/observability/`); the old
  `PIIDetector` class/function bug is moot because that module is unused._
- ✓ Clean configuration/environment handling
  _Verified: `backend/.env.example` created with every var the live path reads;
  `backend/config.py` has explicit `LANGFUSE_*` entries._
- ✓ Verify backend boots
  _Verified: built a real venv, installed pinned deps (fixed a `pymongo`/`motor`
  version-compatibility bug in the process — `pymongo==4.5.0` is required, a bare
  `pip install motor` pulls a newer incompatible `pymongo`), imported `server.py`,
  confirmed all routes register including the 5 new Guardian routes._

## ✓ Phase 1 — Real telemetry

- ✓ Identify single LLM instrumentation point
  _Verified: `base_agent.py:118` → `llm_fallback.LlmChat.send_message()` →
  `litellm.acompletion()` is the only call site; confirmed by reading every agent
  subclass, none override it._
- ✓ Thread `agent_name`
  _Verified: `base_agent.py` now passes `agent_name=self.name` into `send_message()`
  (previously unused despite the parameter existing) → litellm `metadata.generation_name`._
- ✓ Thread shared `run_id`
  _Verified: `AgentContext.run_id` generated once per pipeline run in
  `orchestrator.py`, flows through all 5 agents → litellm `metadata.trace_id`/`session_id`._
- ✓ Wire Langfuse through LiteLLM
  _Verified: `configure_langfuse()` sets `litellm.success_callback`/`failure_callback`,
  called at app startup; confirmed importing without crashing when credentials are
  absent (logs a warning, doesn't raise)._
- ✓ Add environment configuration
  _Verified: `LANGFUSE_PUBLIC_KEY`/`LANGFUSE_SECRET_KEY`/`LANGFUSE_HOST` in
  `config.py` and `.env.example`._
- ✓ Connect to a real Langfuse project
  _Verified: keys in `backend/.env`, `/api/public/projects` → 200 OK._
- ✓ Run real Founder Niche Discovery requests
  _Verified: run `8993f83a-766f-473c-bd82-f72ee79e59bb` completed all 5 agents against
  live Groq. Required fixing an entirely dead model chain, a too-short 30s timeout,
  and adding JSON mode + a JSON re-ask — see docs/PROGRESS.md's dated entry._
- ✓ Verify one pipeline execution produces correctly grouped traces
  _Verified: 6 generations, all under the one `run_id`, all 5 agent names present._
- ✓ Verify tokens/cost/latency/errors map correctly
  _Verified against live data: 4 successful generations carried model, tokens, cost and
  latency; 2 failed ones were correctly captured as `status=error` with zero tokens.
  The real field names are recorded in docs/PROGRESS.md — the observation object mixes
  snake_case and camelCase, so the defensive `_get()` fallbacks were load-bearing._
- ✓ Verify Guardian worker reads real Langfuse data
  _Verified: `poll_once()` ran against live Langfuse without raising and created a real
  incident. Required fixing two live-API bugs first: the v3-vs-2.x SDK method
  (`client.api.observations.get_many` doesn't exist) and Langfuse's 100-item page cap._

2026-09-09: this phase is **complete**. All live-verification items above passed. Five
real bugs were found and fixed in the process; full account in `docs/PROGRESS.md`.

## ✓ Phase 2 — Guardian detection

- ✓ Cost anomaly detector — _17 passing tests across the 3 detectors, see below._
- ✓ Reliability anomaly detector — _included in the 17._
- ✓ PII detector — _included in the 17; picked ahead of prompt-injection because it has
  a mechanically checkable ground truth (regex vs. known formats)._
- ✓ Unit tests — _`pytest tests/` → 80 passed, 0 failed (last run: 2026-09-09)._
- ✓ Incident deduplication — _`test_dedupes_same_detector_and_trace` /
  `test_does_not_dedupe_different_traces` passing against `InMemoryIncidentStore`._
- ✓ Severity model — _`low`/`medium`/`high`, z-score-based thresholds in each detector._
- ✓ Validate detectors against real telemetry
  _Verified: `reliability_anomaly` autonomously caught genuine Groq rate-limit failures
  from live traces, producing "Call failure in tooling_advisor" and "Call failure in
  roadmap_architect" incidents now stored in Atlas. These were not planted — they're
  real failures the detector found on its own._
- ✓ Generate controlled anomaly test cases
  _Verified: `tools/verify_mvp.py` step 7 injects one clearly-labelled synthetic
  `TraceMetric` (`guardian-verify-anomaly-*`, `$0.05` vs a `$0.001` baseline) and
  confirms `cost_anomaly` fires. Deliberately synthetic — there's no reliable way to
  force a real LLM call to cost 50× on demand._
- ◐ Validate false positives with normal workload — needs sustained runs to build real
  per-agent baselines; the cost detector has so far only fired on the controlled
  anomaly, never organically. Phase 5 work.
- ○ PII detector on real output — never triggered on live data (the agents don't emit
  PII), so its real-world false-positive rate is still unmeasured.

## ✓ Phase 3 — Guardian API

- ✓ Overview endpoint — `GET /api/guardian/overview`
- ✓ Incidents endpoint — `GET /api/guardian/incidents`, `GET .../{id}`,
  `POST .../{id}/resolve`
- ✓ Trends endpoint — `GET /api/guardian/trends`
- ✓ Metrics endpoint — `GET /api/guardian/metrics` (hourly cost/latency/error rollups
  per agent, backing the dashboard's trend charts — see Phase 4)
- ✓ Guardian router registration — wired into `server.py`
  _Verified: imported `server.app.routes`, confirmed all 6 paths present._
- ✓ Verify endpoints using real data (real code paths, mocked DB)
  _Verified: ran the actual FastAPI app (uvicorn, not TestClient) with only the Mongo
  client swapped for `mongomock-motor` (no real MongoDB reachable in this
  environment), hit `/dev/login` in a real browser to get a real session cookie, then
  exercised every Guardian page end-to-end through the browser: overview loaded real
  aggregated stats, incidents list + filter + detail all worked, and resolving an
  incident through the UI correctly updated Mongo and the overview counts. This is the
  strongest verification possible without a live MongoDB/Langfuse; only the database
  underneath is fake, everything above it (routing, auth, serialization, the React
  app) is real._
- ✓ Add trace/deep-link data
  _Verified: `IncidentOut` (api/guardian.py) adds a computed `trace_urls` field.
  Originally delegated to the SDK's `get_trace_url()` — that turned out to be broken:
  langfuse 2.x's version takes no arguments and only describes the SDK's *current*
  trace, so every link silently came back `None`. Now built directly as
  `{LANGFUSE_HOST}/trace/{trace_id}`; both that and the project-scoped form were
  confirmed to return HTTP 200 against the live project. 4 regression tests added._
- ✓ Verify endpoints against live Atlas
  _Verified: step 9 of the end-to-end run hit `GET /api/guardian/incidents` against the
  real cluster → HTTP 200 with the real incident present._
- ○ Add any missing API fields required by dashboard — none identified; the dashboard
  is built and consuming the existing contract.

## ✓ Phase 4 — Guardian Dashboard

- ✓ Overview page — `frontend/src/pages/guardian/GuardianOverview.jsx`: stat cards
  (open incidents, spend, avg latency, errors), severity/detector badges, 4 charts
  (cost/hour, latency/hour, errors/hour, incidents/day), an empty-state banner when
  there's no telemetry yet.
- ✓ Cost trend, Latency/reliability trend — dependency-free inline-SVG line/bar charts
  (`MiniChart.jsx`) rather than pulling in a charting library the app didn't already
  have, per "don't add unnecessary frameworks."
- ✓ Active Incidents — `GuardianIncidents.jsx`, list + open/resolved/all filter.
- ✓ Incident detail — `GuardianIncidentDetail.jsx`: evidence JSON, agent, timestamps,
  resolve action, Langfuse trace link (or a clear "not connected yet" fallback with
  the raw trace id).
- ✓ Trace summary / Langfuse deep-link — via `IncidentOut.trace_urls` (Phase 3).
- ○ Project/settings/API configuration page — not built; nothing to configure yet
  (single-tenant MVP, no API keys to manage until Phase 7's multi-tenant work).
- ✓ Nav wiring — `App.js` routes (`/guardian`, `/guardian/incidents`,
  `/guardian/incidents/:id`), a "Cost Guardian" button added to the existing
  `Dashboard.jsx` header.

  _Verified end-to-end in a real browser (not just "it compiles"): ran the actual
  FastAPI app + React dev server together, Mongo client swapped for
  `mongomock-motor`, seeded realistic incidents/metrics, logged in for real, and
  clicked through Overview → Incidents → filter → detail → resolve → back to Overview
  (counts updated correctly). Screenshotted at each step._

  **Real bug found and fixed during this verification** (not introduced by Guardian
  code, but surfaced by it): `frontend/src/App.css` defined `:root` custom properties
  named `--primary`, `--secondary`, `--accent`, and `--border` — the exact same names
  shadcn's `index.css` uses for its design tokens, but in a different value format
  (hex vs. space-separated HSL triplet). App.css loads after index.css, so its hex
  values won by cascade order, silently breaking `hsl(var(--primary))`-style
  utilities app-wide (invalid CSS value → declaration dropped) — most visibly, a
  `variant="default"` Button rendered with fully invisible white-on-white text. Fixed
  by namespacing App.css's custom properties to `--brand-*`. This was a pre-existing
  latent bug in the app, not something the Guardian work introduced — it just hadn't
  been hit because nothing had used a plain `variant="default"` Button before. See
  `docs/DECISIONS.md`.

## ◐ Phase 5 — Product validation

- ✓ Demonstrate the full incident lifecycle against a running app (create → list →
  filter → view evidence → resolve → confirm counts update) — done against mocked
  Mongo, see Phase 4.
- ✓ Demonstrate a **real reliability anomaly** from actual Founder Niche Discovery
  traffic
  _Verified: genuine Groq rate-limit failures during a live run were picked up by the
  reliability detector unprompted and are now real incidents in Atlas ("Call failure
  in tooling_advisor", "Call failure in roadmap_architect")._
- ✓ Demonstrate a controlled cost anomaly end-to-end (incident
  `672bb007-48a0-4eed-adae-184b76873dc3`, retrievable via the API).
- ◐ Demonstrate **normal workload** and an **organic** cost anomaly — the cost detector
  needs ≥5 real baseline samples per agent before it evaluates anything, so this wants
  a batch of repeated runs. Groq's 8k TPM free-tier cap makes that slow but not
  impossible.
- ○ Real PII signal — the agents don't emit PII, so the detector has never fired on
  live data. Needs a deliberately seeded case to be meaningful.
- ○ Verify false-positive behaviour over sustained normal traffic.
- ○ Re-verify the React dashboard against **live Atlas data** (so far browser-tested
  only against a mocked DB — the data is now real, so this is straightforward).
- ○ Second independent AI application — the "not hard-coded to Product A" proof. Now
  correctly unblocked and the natural next milestone.

## ○ Phase 6 — Intelligence layer

Not started. Explicitly gated on Phase 5 being reliable first, per the project's own
instructions — do not start early.

## ○ Phase 7 — Research

Not started. Research question intentionally not locked — see docs/PRODUCT.md.
