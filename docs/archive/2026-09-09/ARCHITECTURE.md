> Historical snapshot preserved during the 2026-09-11 review. Claims below describe prior work and are superseded by the current docs. Internal relative links may refer to the original file locations.

# Cost Guardian — Architecture

## Two separate applications

Guardian is a standalone service. It shares no process, no database, no auth and no
code with the applications it monitors -- the only thing connecting them is Langfuse.
That separation is the product premise: point Guardian at any Langfuse project and it
works, without that project's app knowing Guardian exists.

```
cost-guardian/
├── apps/
│   ├── founder-app/          Product A -- the monitored demo application
│   │   ├── backend/   :8000  FastAPI, 5 agents, reports (knows nothing about Guardian)
│   │   └── frontend/  :3000  React
│   └── guardian/             Cost Guardian -- the product
│       ├── backend/   :8001  FastAPI + worker, own config/db/auth
│       └── frontend/  :3001  React, API-key auth
├── tools/                    Cross-app integration harness (imports BOTH, on purpose)
└── docs/
```

## Runtime flow

```
   apps/founder-app  (or ANY instrumented app)
            │
            │  litellm.acompletion(..., metadata={agent_name, run_id})
            ▼
        Langfuse                 <-- the only coupling point
            │
            │  fetch_observations()  (Guardian pulls; the app never pushes to Guardian)
            ▼
   apps/guardian/backend
     guardian/worker.py
            │
      ┌─────┼─────┐
      ▼     ▼     ▼
    Cost  Reliab.  PII         pure functions, no I/O
      └─────┼─────┘
            ▼
     incident_engine.py         dedup on (detector, trace_id)
            ▼
   MongoDB: guardian_*          Guardian's own database
            ▼
     api/routes.py :8001        X-Guardian-Key auth
            ▼
   apps/guardian/frontend :3001
            ▼
        Langfuse                deep-link out for the raw trace
```

## Why each boundary exists

- **Detectors are pure functions with no I/O.** They take metric data in, return a
  `DetectorResult` out. This is the single most important design decision in the MVP:
  it means every detector has a fast, deterministic unit test with no live Langfuse
  connection, no Mongo, no network — you can verify "does this detector actually catch
  the anomaly it claims to catch" in milliseconds, which matters a lot for a component
  whose entire job is "don't cry wolf."
- **`IncidentStore` is an interface, not a concrete Mongo class.** `incident_engine.py`
  depends on the interface. Tests use `InMemoryIncidentStore`; the app uses
  `MongoIncidentStore`. This is what makes incident dedup/severity logic testable
  without a running database.
- **Guardian is a separate deployable service, not a module inside the monitored app.**
  It was briefly bundled into the founder app's process during early MVP work, which
  silently let it borrow that app's session auth and database handle. Splitting it out
  forced both to become explicit (its own API key, its own Mongo connection) and
  removed the credibility problem of a monitoring product that only works when it is
  installed *inside* the thing it monitors.
- **The worker polls Langfuse rather than the app pushing to Guardian directly.**
  Keeps Guardian fully decoupled from the instrumented app — Founder Niche Discovery
  (or any future second app) only needs to know about Langfuse, never about Guardian's
  existence. This is what makes the product plug-and-play for a new customer app later:
  point their app at Langfuse (or their existing OTel setup), point Guardian's worker at
  their Langfuse project, done.
- **`run_id` links the 5 agent calls of one pipeline execution into one Langfuse
  trace.** Without it, Langfuse sees 5 unrelated LLM calls per report instead of one
  causal chain — and "the regression is concentrated in workflow Y" (the product's
  actual value proposition) requires being able to group calls by workflow run.

## Data model (MVP)

```python
class Incident(BaseModel):
    id: str
    detector: str            # "cost_anomaly" | "reliability_anomaly" | "pii"
    severity: str             # "low" | "medium" | "high"
    title: str
    summary: str
    evidence: dict             # raw values that triggered it — never just a verdict
    trace_ids: list[str]       # Langfuse trace ids this incident is based on
    agent_name: str | None
    status: str                # "open" | "resolved"
    created_at: datetime
    resolved_at: datetime | None
```

`evidence` is mandatory and structured, not a free-text string — every incident must be
independently checkable against the Langfuse trace it references. This mirrors the
product's later "must provide evidence, must distinguish fact from hypothesis"
requirement for the agentic investigator; the deterministic MVP detectors are held to
the same evidentiary standard from day one, not just the future AI layer.

## Future architecture (Phase 6+, not built yet)

```
Telemetry
   ↓
Signals            (Phase 0-3, done: cost/reliability/PII detectors)
   ↓
Correlation        (not built: multiple signals -> one incident, e.g.
   ↓                "latency ↑ + tokens ↑ + retrieval latency ↑ concentrated
Incident            in workflow Y, starting after deployment X")
   ↓
AI Investigation    (not built: an agent that queries traces/logs/deployments/
   ↓                GitHub diffs to explain an incident that already exists —
Evidence-backed      distinguishing observed facts from hypotheses, never
diagnosis            fabricating a root cause)
```

Explicitly gated on Phase 5 (product validation) being reliable first — see
`docs/PHASES.md`. Building a correlation/investigation layer on top of unvalidated
detectors would mean debugging two unproven things at once.

## What is explicitly deferred (and why)

| Deferred | Why not now |
|---|---|
| Self-hosted Langfuse | Adds Postgres/Clickhouse/Redis infra with zero MVP benefit over the free Cloud tier |
| Correlation engine (multi-signal → one incident) | Needs real incident data from the 3 MVP detectors first to know what's actually worth correlating, rather than guessing |
| Agentic SRE investigator | Its entire job is explaining incidents that don't exist yet without it — deterministic detection has to exist and be trustworthy first |
| Hallucination / context-loss detectors | No evaluation methodology yet — shipping an unvalidated "hallucination score" as a product claim is worse than not having one |
| Prompt injection detector | No labeled benchmark to grade false-positive rate against yet; PII ships first because it's mechanically checkable |
