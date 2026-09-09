# Cost Guardian — Progress

_At-a-glance status. Full checklist detail lives in `docs/PHASES.md`; decisions and
their rationale live in `docs/DECISIONS.md`. The table and test count above are kept
current in place. Dated entries below are a short audit trail of verification
attempts specifically (what was checked, what was blocked) — kept because "record
blockers explicitly" implies keeping the record of when they were re-checked, not just
the current one. Trim old entries if this section gets long._

Status symbols: ✓ Complete · ◐ In progress · ○ Not started · ⚠ Blocked

| Phase | Status | % | Verification |
|---|---|---|---|
| 0. Repository stabilization | ✓ | 100% | `server.py` imports cleanly in a real venv; all routes register; 0 references to `ddtrace`/Datadog in the live path |
| 1. Real telemetry | ✓ | 100% | **VERIFIED LIVE 2026-09-09.** Real pipeline run `8993f83a-766f-473c-bd82-f72ee79e59bb` produced 6 generations in the live Langfuse project, all grouped under the shared `run_id`, all 5 agent names present, real tokens/cost/latency mapped, failed calls captured as `status=error`. Five real bugs found and fixed in the process — see the dated entry below |
| 2. Guardian detection | ✓ | ~90% | 3 detectors, 17 unit tests. **Now validated against real telemetry**: `reliability_anomaly` autonomously caught genuine Groq rate-limit failures from live traces ("Call failure in tooling_advisor/roadmap_architect"). Cost detector confirmed via controlled anomaly; validating it on organic spend variance needs more baseline runs (Phase 5). PII detector still unexercised on real output |
| 3. Guardian API | ✓ | 100% | 6 endpoints verified over real HTTP. **Now confirmed against live Atlas**: `GET /api/guardian/incidents` returned HTTP 200 with the real incident present |
| 4. Guardian dashboard | ✓ | 95% | Overview, Incidents (+filter), Incident detail (+resolve), browser-verified end-to-end. Found/fixed a real pre-existing CSS bug (App.css/index.css variable collision — see DECISIONS.md). Not yet re-verified against live Atlas data — only against a mocked DB |
| 5. Product validation | ◐ | ~60% | **Detectors now fire organically on real telemetry**: 11 of 13 incidents came from genuine pipeline traffic — a 7x cost spike (z=4.48 over a 14-call baseline) and an 81s latency regression (z=10.94 over 8 calls), neither planted. 6/6 baseline runs succeeded; dedup verified (poll cycles 2-3 created 0). Still to do: false-positive rate on sustained normal traffic, PII on real output, second independent app |
| 6. Intelligence layer | ○ | 0% | Not started — explicitly gated on 5 |
| 7. Research | ○ | 0% | Not started — question intentionally not locked |

**Overall MVP progress (phases 0–5, equally weighted): ~91%.**

**Guardian test suite: 83 passing, 0 failing** (now runs standalone in `apps/guardian/backend`). Breakdown: 17 detector tests, 6
incident-engine tests, 6 `MongoIncidentStore` tests, 6 Guardian API HTTP tests, 33
`langfuse_client.py` tests (including 9 new regressions for the live-API bugs), 4
`worker.py` orchestration tests, 9 `metrics.py` rollup tests.
Run: `cd apps/guardian/backend && pytest tests/ -v`.

**Frontend: no automated tests yet** (CRA's default Jest setup exists but nothing
guardian-specific has been added) — verification so far is the manual browser
walkthrough described in Phase 4/5 above. Worth adding component tests once the app is
past pure MVP velocity; not blocking right now.

## Blockers

**None blocking.** Both long-standing blockers were resolved on 2026-09-09:

1. ~~No Langfuse project credentials~~ **Resolved.** Keys in `backend/.env` (mapped
   from the user's `LANGFUSE_BASE_URL` to our actual `LANGFUSE_HOST` var — not a blind
   paste). Verified live against `/api/public/projects` → 200 OK.
2. ~~No reachable MongoDB~~ **Resolved.** MongoDB Atlas connected — ping OK, v8.0.32,
   using the `cost_guardian` database. (Supabase was considered and rejected: it's
   Postgres, our whole data layer is Mongo-shaped, so it'd mean an unnecessary
   rewrite.)

**Known constraint, not a blocker:** Groq's free tier caps at 8,000 tokens/min; a full
5-agent run uses ~10k, so runs intermittently fall back across models mid-pipeline.
The fallback chain handles this correctly — and it's precisely why the reliability
detector had genuine failures to catch — but sustained Phase 5 validation would be
smoother on Groq's Dev tier.

**One-command verification:** `python tools/verify_mvp.py` runs all 10 of the MVP's end-to-end verification steps
(instrument → trace → group → field-map → worker → detector → incident → Mongo → API
retrieval) automatically and writes a pass/fail report to
`tools/verify_mvp_report.json`. Nothing else needs to be built first — the
whole stack (detectors, incident engine, API, dashboard) is code-complete and
verified against every layer except the two live services themselves.

## 2026-09-09 — end-to-end verification attempt: blocked before it could start

Asked to run the real end-to-end flow (Founder Niche Discovery → Langfuse → Guardian
worker → detector → incident → Mongo → `GET /api/guardian/incidents`) against a real
Langfuse Cloud project. Checked prerequisites before running anything (per the "do not
claim success without actually running the flow" rule):

- `backend/.env`: `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` — **absent** (checked
  the file directly; also checked OS-level environment variables in case they were set
  outside `.env` — also absent)
- `backend/.env`: `MONGO_URL` — present but still the original placeholder
  (`mongodb://localhost:27017`); confirmed **not reachable** (TCP connect to
  `localhost:27017` times out)
- Network path to Langfuse itself is fine (`cloud.langfuse.com` responds 200) — this is
  specifically a missing-credentials/missing-database problem, not a connectivity
  problem

**Result: 0 of the 10 requested verification tasks were performed.** Creating a
Langfuse account or an Atlas cluster on your behalf is out of scope for me (account
creation with personal/payment details isn't something I do unprompted) — this needs
you to create the project/cluster and drop the resulting credentials into
`backend/.env`. Nothing else changed this session; no code, no tests, no architecture.

## 2026-09-09 (continued) — closed two known gaps while still blocked, no new features

Asked to keep building while waiting on credentials. Scoped to closing gaps already
flagged as "candidate for next session" in `docs/PHASES.md`, not new product surface:

- **Trace deep-links**: `api/guardian.py` now returns `trace_urls` on every incident
  response (`IncidentOut`), built from the Langfuse SDK's own `get_trace_url()` — see
  the decision entry in `docs/DECISIONS.md` for why that's used instead of a
  hand-tracked project id. _Verified: with no credentials configured it returns `[]`
  cleanly (covered by a test); the URL **shape** matches Langfuse's documented format,
  but whether a real trace id actually resolves is still unverified — needs live
  Langfuse._
- **Test coverage for the two files that had none**: `guardian/langfuse_client.py`
  (field-extraction logic — 24 tests, both dict- and attribute-object-shaped fake
  observations, camelCase/snake_case fallbacks, malformed-input handling) and
  `guardian/worker.py` (`poll_once()`'s cursor/baseline/candidate wiring and
  detector-failure isolation — 4 tests, fake Langfuse source + mongomock). _Verified:
  `pytest tests/` → 62 passed, 0 failed, run twice to confirm stability after a venv
  hiccup (two concurrent pip installs into the same scratch venv briefly left it
  inconsistent — not a repo issue, just my own tooling mistake; a clean single install
  resolved it)._
- Added `mongomock-motor==0.0.36` to `requirements.txt` (already relied on informally
  last session; now pinned like everything else in that file).

No architecture change, no new detector, no dashboard work, per this session's
constraints. Still blocked on the same two things — see the entry above.

## 2026-09-09 (continued further) — built the whole Guardian dashboard + verify script ahead of credentials

User asked to keep building everything possible so it's "all ready" the moment
Langfuse/Mongo credentials arrive. Scope this time deliberately included the dashboard
(previously held back) since the API contract had proven stable:

- **`guardian/metrics.py`**: hourly cost/latency/error rollups per agent (aggregates
  only — no prompts/outputs stored, see the module docstring), feeding the dashboard's
  trend charts. Wired into `worker.py`'s `poll_once()` and a new
  `GET /api/guardian/metrics` endpoint. 9 tests.
- **Full React Guardian dashboard**: Overview (stat cards, 4 trend charts via a small
  dependency-free inline-SVG chart component — no charting library added), Incidents
  (list + status filter), Incident detail (evidence, resolve action, Langfuse
  deep-link with a graceful fallback). Wired into `App.js` routing and linked from the
  existing `Dashboard.jsx` header.
- **`tools/verify_mvp.py`**: a ready-to-run script that performs all 10 of
  the MVP's end-to-end verification steps in one command the moment credentials exist,
  writing a pass/fail report. Uses one clearly-labeled synthetic data point
  (prefixed `guardian-verify-`) to trigger a controlled, deterministic anomaly rather
  than hoping for a real cost spike — everything else in the script (the pipeline run,
  the Langfuse fetch, the worker) is 100% real.
- **Verification performed this session** (strongest available without live
  Langfuse/Mongo): ran the actual FastAPI app and the actual React dev server
  together, with only the Mongo client swapped for `mongomock-motor`, seeded
  realistic data, logged in through a real browser session, and clicked through the
  entire Overview → Incidents → filter → detail → resolve flow, confirming each step
  against what the screen actually showed (not just "it compiled"). `pytest tests/` →
  **71 passed, 0 failed** afterward.
- **Found and fixed a real, pre-existing bug** during that browser walkthrough: a CSS
  custom-property name collision between `App.css` and shadcn's `index.css` was
  silently breaking every `variant="default"` Button app-wide (invisible
  white-on-white text). Not something Guardian's code caused — it just hadn't been
  exercised before. See `docs/DECISIONS.md`.
- Added `.claude/launch.json` (frontend dev server config, for the `preview_start`
  tool) and a throwaway (not committed) mock-DB dev server script used only for this
  session's browser verification — deleted, not part of the repo.

**Still genuinely blocked, same two things as every prior session**: no Langfuse
credentials, no reachable MongoDB. Everything that can be built and verified without
them now has been. See `docs/EXECUTIVE.md` for the one-command unlock path.

## 2026-09-09 — ✅ MVP END-TO-END FLOW VERIFIED AGAINST LIVE SERVICES

Credentials arrived (Langfuse Cloud + MongoDB Atlas + a working Groq key) and the full
flow was run for real. **All 10 verification steps passed.**

```
Founder Niche Discovery → LiteLLM → Langfuse → Guardian worker
  → detector → incident engine → Mongo → GET /api/guardian/incidents
```

### What was verified

| # | Step | Result |
|---|---|---|
| 1 | Prerequisites | Langfuse `/api/public/projects` → 200; Atlas ping OK (v8.0.32) |
| 2 | Real pipeline run | Completed, all 5 agents, `run_id=8993f83a-766f-473c-bd82-f72ee79e59bb` |
| 3 | Trace grouping by `run_id` | 6 generations, all under one trace, all 5 agent names present |
| 4 | Real field mapping | 4 successful generations carried model/tokens/latency/cost; 2 failed ones correctly captured with `status=error` and zero tokens |
| 5 | `poll_once()` on real data | Ran clean, created 1 incident from live traces |
| 6 | Worker → TraceMetric transform | Correct (same path as step 4) |
| 7 | Controlled anomaly | Synthetic candidate `$0.05` vs baseline mean `$0.001` → `cost_anomaly` fired |
| 8 | Persisted in Mongo | Incident `672bb007-48a0-4eed-adae-184b76873dc3`, read back OK |
| 9 | Retrieved via API | `GET /api/guardian/incidents` → HTTP 200, incident present |
| 10 | Regression tests for bugs found | 9 added; 80 tests passing |

Reproduce: `python tools/verify_mvp.py`

### Real Langfuse field mappings discovered

Field names on a langfuse 2.53.9 GENERATION observation (mixed snake_case and
camelCase in the same object — the defensive `_get()` fallbacks earned their keep):

- `trace_id`, `name` (→ our `agent_name`), `model`, `latency` (**seconds**, ×1000 for ms)
- `start_time` / `end_time` (datetimes), `level` (`ObservationLevel.ERROR` → our `status`)
- `calculated_total_cost` (the one that actually populates), `total_price` (None),
  `costDetails` (`{}`), `usage` (object with `input`/`output`/`total`)
- `promptTokens` / `completionTokens` / `totalTokens` (camelCase), `usageDetails` (`{}`)
- `projectId`, `id`, `type`, `status_message` (carries the provider error text)

### Anomaly used

A single clearly-labelled synthetic `TraceMetric`
(`guardian-verify-anomaly-bc78e107-…`) at `$0.05` against a synthetic baseline of six
`$0.001` calls — deliberately synthetic because there's no reliable way to force a real
LLM call to cost 50× on demand. Everything else in the run was real. Separately, and
more interestingly, **the reliability detector caught genuine failures unprompted**:
real Groq rate-limit errors became "Call failure in tooling_advisor" and "Call failure
in roadmap_architect" incidents straight from live telemetry.

### Five real bugs found — none of which mocked testing could have caught

1. **Entire LLM fallback chain was dead.** `groq/llama-3.3-70b-versatile` +
   `llama-3.1-8b-instant` not available on the account; `openrouter/allenai/olmo-3-32b-think`
   404s; `openrouter/arcee/trinity-mini` withdrawn. Rebuilt the chain from models
   probed live.
2. **30s timeout too short.** Real agent prompts generate large JSON; every OpenRouter
   model timed out mid-generation. Raised to 120s and put Groq (~1–2s) first.
3. **No retry on malformed JSON.** `send_message()` retried transport errors, but a
   model returning *syntactically broken* JSON killed the whole 5-agent run.
   Added a 3-attempt re-ask in `base_agent.run()`.
4. **Wrong Langfuse SDK API.** Code called `client.api.observations.get_many()` (the v3
   path); 2.x uses `client.fetch_observations()`. Pure `AttributeError` — no amount of
   defensive field mapping helps when the method doesn't exist.
5. **Langfuse caps `limit` at 100.** We requested 200/500 → HTTP 400 on every fetch.
   Replaced with proper pagination (and the new test immediately caught a follow-on
   overshoot bug on the final partial page).

Plus one fix that wasn't a code bug at all: **step 4's own assertion was wrong**,
demanding every generation have `tokens > 0`. Failed calls legitimately have zero
tokens — that's the exact signal the reliability detector consumes. Reading the real
data rather than trusting the assertion prevented "fixing" correct code.

### Configuration changes made

- `LANGFUSE_HOST` (not the user-supplied `LANGFUSE_BASE_URL` — our config reads the
  former; pasting verbatim would have silently done nothing)
- `DB_NAME` → `cost_guardian`, matching the database already present in the cluster
  rather than creating a stray second one
- Groq key replaced with a working one; JSON mode
  (`response_format={"type": "json_object"}`) enabled on all agent calls

### What was NOT verified

- Cost detector on **organic** spend variance (only via the controlled synthetic
  anomaly) — needs many baseline runs
- **PII detector** against real model output — never triggered on live data
- **False-positive rate** on sustained normal workload
- The **React dashboard against live Atlas data** — so far only browser-tested against
  a mocked DB
- A **second independent application** (Phase 5's "not hard-coded to Product A" proof)


## 2026-09-09 — split into two independent applications + organic detection proven

Two things landed after the end-to-end verification.

### 1. Guardian is now a standalone application

Guardian was running inside the founder app's process on the same port, which quietly
undermined the product premise — a monitoring tool that only works when installed
*inside* the thing it monitors isn't the product. Now:

```
apps/founder-app/{backend :8000, frontend :3000}   # monitored app, zero Guardian refs
apps/guardian/{backend :8001, frontend :3001}      # the product, fully standalone
tools/                                              # cross-app harness (imports both)
```

The split forced three things that the shared process had been hiding:

- **Guardian needed its own auth.** It had been borrowing the founder app's session
  cookie. It now has its own API key (`X-Guardian-Key`, constant-time compared) and
  returns **503 rather than serving data unauthenticated** when no key is configured.
- **`verify_mvp.py`/`build_baseline.py` belong to neither app.** They drive the
  monitored app *and* assert on Guardian, so they moved to `tools/`. Neither service
  imports the other; only the harness imports both — by design.
- **Guardian's frontend got a clean CSS slate.** `App.css` was deliberately not copied
  over: it was the source of the shadcn variable collision fixed earlier.

_Verified: Guardian's 83 tests pass standalone; `:8001` returns 401 without a key and
live Atlas data with one; the `:3001` dashboard rejects a bad key with a clear message
and renders 13 real incidents with a working trend line; the founder app boots with
`guardian routes present? False`._

### 2. The detectors fire organically — not just on planted data

After 6 real pipeline runs built genuine per-agent baselines:

| Incident | Evidence |
|---|---|
| Cost spike in `tooling_advisor` | $0.0014 vs baseline mean $0.0002 over **14 calls**, z=4.48 |
| Latency regression in `roadmap_architect` | 81022ms vs baseline mean 6463ms over **8 calls**, z=10.94 |
| 9 × call failures | real Groq rate-limit errors captured as `status=error` |

**11 of 13 incidents are organic** (real trace ids); only 2 are the synthetic verify
anomaly. This closes the central Phase 5 question: the product detects real problems in
real telemetry without being told where to look.

### Two more bugs fixed

- **`float("inf")` in evidence serialised to `null`.** A zero-variance baseline reported
  an infinite z-score, which isn't representable in JSON — so the dashboard showed
  `"z_score": null`, destroying the very evidence the UI tells users to verify. Both
  detectors now report a finite `cost_multiple`/`latency_multiple` instead. Found by
  reading rendered UI data, not by a test.
- **Output token ceiling.** With JSON mode on, `roadmap_architect`'s ~6k-token response
  hit the provider default and Groq rejected it outright
  (`json_validate_failed: max completion tokens reached`). Now `max_tokens=8000`.
  Note this was JSON mode doing its job — the same truncation used to pass silently as
  malformed JSON.
