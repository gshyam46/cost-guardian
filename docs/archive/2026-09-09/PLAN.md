> Historical snapshot preserved during the 2026-09-11 review. Claims below describe prior work and are superseded by the current docs. Internal relative links may refer to the original file locations.

# Cost Guardian — Phased Build Plan

_Supersedes the earlier Datadog-oriented draft of this file. Product framing:
`docs/PRODUCT.md`. Component design: `docs/ARCHITECTURE.md`. Live status:
`docs/PROGRESS.md`._

## Phase 0 — Stabilize the live path
Remove what blocks a clean boot and what's just noise in files we're about to edit
anyway. Does not touch `backend/observability/` (unused, left as reference).
- Strip `ddtrace`/`LLMObs` usage from `llm_fallback.py` and `orchestrator.py`
- Strip ~1000 lines of commented-out alternate orchestrator implementations
- Add `backend/.env.example`

## Phase 1 — Real instrumentation
- Wire `litellm`'s native Langfuse callback (global, set once at startup)
- Add `run_id` to `AgentContext`, thread it + `agent_name` through
  `send_message(..., metadata=...)` so one pipeline execution = one Langfuse trace
- Manually run the Founder Niche pipeline a few times to produce genuine trace/cost
  history (real data, not seeded/mocked)

## Phase 2 — Detectors (pure functions, unit tested, no live services required)
- `cost_anomaly`: rolling per-agent baseline, flag N-sigma spend/token spikes
- `reliability_anomaly`: latency/error-rate baseline, flag regressions
- `pii`: fixed/ported regex detector (email, phone, SSN, card, IP)

## Phase 3 — Incident engine + storage
- `IncidentStore` interface; `InMemoryIncidentStore` (tests) + `MongoIncidentStore` (app)
- Dedup + severity assignment
- `guardian_incidents` Mongo collection

## Phase 4 — Guardian worker
- Polls Langfuse for new traces since last cursor, runs detectors, writes incidents
- Handles missing/invalid telemetry without crashing (a bad trace should not stop the
  loop)

## Phase 5 — Guardian API
- `GET /api/guardian/overview`, `GET /api/guardian/incidents`,
  `GET /api/guardian/incidents/{id}`, `GET /api/guardian/trends`

## Phase 6 — Guardian dashboard (React)
- Overview: spend/reliability trend, spend by agent
- Incidents: list + detail, evidence shown, link out to the Langfuse trace
- Traces: thin summary table, deep-link to Langfuse for the full waterfall

## Phase 7 — Second app proof
- Point one more small, independent script/app at the same Langfuse project +
  Guardian worker, to demonstrate this isn't just self-observing Founder Niche Discovery

## Phase 8 — Local run instructions + deploy notes
- `.env.example` complete, README run steps verified end to end

## Success criterion (MVP definition of done)
Run Founder Niche Discovery → generate real LLM/agent telemetry → Guardian detects a
genuine anomaly → incident appears in the Guardian dashboard with evidence → user opens
the underlying Langfuse trace from there.

## Explicitly not in this plan
Self-hosted Langfuse, correlation engine, agentic SRE investigator, hallucination/
context-loss detectors, prompt-injection detector, billing. See `docs/PRODUCT.md` and
`docs/ARCHITECTURE.md` for why each is deferred, not just that it is.
