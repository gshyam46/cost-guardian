# Cost Guardian — Executive Overview

Status: 🟢
Phase: 5 — Product Validation (MVP end-to-end flow is VERIFIED against live services)
Progress: ~91% of MVP (phases 0–5; see docs/PROGRESS.md for the weighting)

## ✅ MVP success criterion: MET (2026-09-09)

All 10 end-to-end verification steps passed against the real Langfuse project and the
real MongoDB Atlas cluster:

```
Founder Niche Discovery → LiteLLM → Langfuse → Guardian worker
  → detector → incident engine → Mongo → GET /api/guardian/incidents   ✅
```

- Run id: `8993f83a-766f-473c-bd82-f72ee79e59bb`
- Incident id: `672bb007-48a0-4eed-adae-184b76873dc3`
- Reproduce with: `python tools/verify_mvp.py`

**The detectors now catch real problems on their own.** After 6 baseline runs, 11 of
13 incidents are organic — including a 7x cost spike (z=4.48 over a 14-call baseline)
and an 81-second latency regression (z=10.94). Only 2 are the synthetic verify anomaly.

**Guardian is now a standalone application** (`apps/guardian`, :8001/:3001) with its own
auth, database and frontend — fully separate from the app it monitors (`apps/founder-app`,
:8000/:3000). They share nothing but Langfuse.

## What exists (verified, not just written)
- Founder Niche Discovery: working 5-agent app — **runs live**, all 5 agents complete
- Langfuse instrumentation: `run_id` groups one pipeline run into one trace —
  **confirmed against the live project**: 6 generations, all 5 agent names, real
  tokens/cost/latency, failed calls correctly captured as `status=error`
- 3 Guardian detectors, incident engine, hourly metrics rollups, full Guardian API
  (overview/incidents/trends/metrics, with Langfuse trace deep-links) — **all exercised
  against live Langfuse + Atlas**
- **Full React Guardian dashboard** — Overview (stat cards + 4 trend charts),
  Incidents (list + filter), Incident detail (evidence + resolve + trace link).
  Browser-verified end-to-end: ran the real app + real frontend together (only the
  Mongo client swapped for a mock), logged in, clicked through the entire flow,
  confirmed each screen against what actually rendered — not just "it compiled"
- `tools/verify_mvp.py` — a ready-to-run script that performs all 10 of the
  MVP's end-to-end verification steps in one command and writes a pass/fail report
- Found and fixed a real pre-existing bug during browser testing: a CSS variable
  collision between `App.css` and the shadcn design system that was silently making
  some buttons invisible app-wide (see docs/DECISIONS.md)
- Guardian test suite: 83 tests passing, 0 failing (standalone service)
- Live data in Atlas: 13 incidents (11 organic), 10 metric rollups, 58 real LLM calls

## Current blockers
None blocking. Both former blockers are resolved: Langfuse credentials verified live,
MongoDB Atlas connected (v8.0.32, `cost_guardian` database).

Known constraint (not a blocker): Groq's free tier caps at 8,000 tokens/min and a full
5-agent run uses ~10k, so runs intermittently fall back across models. The fallback
chain absorbs this correctly — it's why the reliability detector had real failures to
catch — but repeated Phase 5 validation runs would be smoother on Groq's Dev tier.

## Next milestone (Phase 5)
1. Run the pipeline repeatedly to build real per-agent baselines, then confirm the cost
   detector fires on genuine spend variance (not just a synthetic candidate)
2. Re-verify the React dashboard against the live Atlas data (it's so far only been
   browser-tested against a mocked DB)
3. Add a second, independent AI app to prove Guardian isn't hard-wired to Product A

## Product
AI reliability / incident intelligence layer for early-stage AI startups, built on top
of Langfuse rather than replacing it.

## Research
Not locked yet. See docs/PHASES.md Phase 7 — literature review comes after the MVP is
reliable, not before.
