---
name: run-guardian-stack
description: Run the local Cost Guardian stack (Guardian API, Guardian worker, Guardian dashboard, and optionally the monitored founder app) and verify the end-to-end flow. Use when asked to "run the app", "start the dev servers", or "check the MVP works end to end".
---

# Run the Cost Guardian stack locally

Guardian and the monitored app are **separate applications** with separate ports and
separate `.env` files. Guardian can run on its own — it doesn't need the founder app,
only a Langfuse project with data in it.

## Guardian (the product)

1. Confirm `apps/guardian/backend/.env` has `MONGO_URL`, `GUARDIAN_API_KEY`, and
   `LANGFUSE_PUBLIC_KEY`/`LANGFUSE_SECRET_KEY`. Without an API key Guardian returns
   503 on data endpoints by design, rather than serving unauthenticated.
2. API: `cd apps/guardian/backend && uvicorn server:app --reload --port 8001`
3. Worker (separate process): `cd apps/guardian/backend && python -m guardian.worker`
4. Dashboard: `cd apps/guardian/frontend && npm start` (:3001 — it will prompt for the
   API key on first load and store it in localStorage)

## Monitored app (only needed to generate fresh telemetry)

- Backend: `cd apps/founder-app/backend && uvicorn server:app --reload --port 8000`
- Frontend: `cd apps/founder-app/frontend && npm start` (:3000)

## End-to-end check

`python tools/verify_mvp.py` does the whole flow in one command and prints a pass/fail
line per step. Prefer this over clicking through manually — it asserts on real Langfuse
field mappings and a real retrieved incident, and writes a machine-readable report to
`tools/verify_mvp_report.json`.

If the detectors aren't firing, the usual cause is insufficient history rather than a
bug: they require ≥5 baseline samples per agent. `python tools/build_baseline.py 6`
generates real runs to build that history.

When verifying UI changes, actually load the page in a browser and check what rendered —
several real bugs in this project (invisible buttons from a CSS variable collision,
`"z_score": null` in incident evidence) were only visible that way and passed every test.
