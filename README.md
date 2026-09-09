# Cost Guardian

Cost, reliability, and security guardrails for LLM applications — built on top of
[Langfuse](https://langfuse.com) rather than reimplementing trace storage and a trace
explorer.

Langfuse captures traces, tokens, and per-call cost for any LLM app. Cost Guardian
reads that data and adds the part Langfuse doesn't:

- **Cost anomaly detection** — flags agents whose spend breaks from their own rolling
  baseline
- **Reliability anomaly detection** — call failures and latency regressions
- **PII leak detection** — scans model output for emails, phone numbers, SSNs, cards, IPs
- **Incidents, not metrics** — threshold breaches become deduplicated incidents with
  severity and evidence, each linking back to the exact Langfuse trace

This is not a Langfuse replacement. Guardian never stores raw traces; it stores
incidents and hourly rollups, and deep-links out for the detail.

## Two separate applications

```
cost-guardian/
├── apps/
│   ├── founder-app/          Product A — a real 5-agent LLM app, used as the
│   │   ├── backend/   :8000  monitored workload. Knows nothing about Guardian.
│   │   └── frontend/  :3000
│   └── guardian/             Cost Guardian — the product
│       ├── backend/   :8001  API + worker, own config/db/auth
│       └── frontend/  :3001  Dashboard, API-key auth
├── tools/                    Cross-app integration harness
└── docs/
```

They share **nothing but Langfuse**. The monitored app emits telemetry to Langfuse;
Guardian polls Langfuse. That's the whole coupling — which is what makes Guardian
point-at-any-project rather than bolt-into-one-app.

## Running it

Each app is independent. You can run Guardian without the founder app at all.

### Guardian (the product)

```bash
cd apps/guardian/backend
pip install -r requirements.txt
cp .env.example .env        # set MONGO_URL, GUARDIAN_API_KEY, LANGFUSE_* keys
uvicorn server:app --reload --port 8001
```

The worker is a separate process — it polls Langfuse and raises incidents:

```bash
cd apps/guardian/backend
python -m guardian.worker
```

Dashboard:

```bash
cd apps/guardian/frontend
npm install
npm start                    # :3001, asks for GUARDIAN_API_KEY on first load
```

### Founder app (the monitored workload)

```bash
cd apps/founder-app/backend
pip install -r requirements.txt
cp .env.example .env         # MONGO_URL + an LLM provider key + LANGFUSE_* keys
uvicorn server:app --reload --port 8000
```

```bash
cd apps/founder-app/frontend
npm install && npm start     # :3000
```

## Verifying the whole flow

```bash
python tools/verify_mvp.py
```

Runs the real pipeline, confirms the Langfuse trace is correctly grouped, runs the
Guardian worker over it, triggers a controlled anomaly, and confirms the resulting
incident is retrievable through the Guardian API — printing a pass/fail line per step.

To build real detector baselines (detectors need ≥5 samples per agent before they
evaluate anything):

```bash
python tools/build_baseline.py 6
```

## Status

MVP flow verified end-to-end against live Langfuse + MongoDB Atlas. Detectors fire
organically on real telemetry, not just planted data. See [docs/EXECUTIVE.md](docs/EXECUTIVE.md)
for a 60-second status read, [docs/PHASES.md](docs/PHASES.md) for the detailed
checklist, and [docs/DECISIONS.md](docs/DECISIONS.md) for why things are built the way
they are.
