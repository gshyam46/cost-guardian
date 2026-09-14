# Sillage

**Public frontend prepared for Vercel:** public-site mode, an independent workspace availability check, coming-soon/unavailable pages and durable early-access registration are implemented under [PUBLIC_LAUNCH.md](docs/PUBLIC_LAUNCH.md). The built browser journey passed against real local MongoDB, including registration while the monitoring backend is unavailable. This records contact interest, not workspace accounts. Vercel login, a hosted registration database and real privacy contact still need configuration; no hosted signup service is claimed. [Deployment setup](apps/guardian/frontend/README.md#public-vercel-deployment) and [simple end-to-end workflow](docs/WORKFLOW.md).

**Python onboarding with OpenTelemetry:** Connections offers the 0.2.0 `sillage-observe` wheel with maintained OpenInference instrumentors. Install the local wheel with its `[openinference]` extra, configure your Sillage address/application key, select one SDK/framework layer and run the original application through `sillage-run`. Existing OTel applications can attach the numeric span processor to their own provider; existing Langfuse projects can keep that source path. [Install guide and exact compatibility](packages/sillage-python/README.md) · [OpenTelemetry architecture](docs/OPENTELEMETRY.md) · [Verification evidence](docs/VALIDATION.md).

The standards command is explicit, for example `sillage-run --instrumentation openinference --instrumentors litellm -- python app.py`. Bare `sillage-run` retains the native adapter for compatibility. Real OTel trace/span/parent IDs and supplied agent context survive numeric projection; absent workflow spans and terminal evidence remain unknown. This bridge is not a general OTLP receiver or a full RAG trace store. The exact 0.2.0 wheel passed the installed OpenAI 1.x/2.x, LiteLLM/Founder, LangChain and native collector/worker checks. Final product/build evidence is recorded in [VALIDATION.md](docs/VALIDATION.md).

**Current upstream gap:** installed-instrumentor checks missed early-closed streams and a cancelled call when no ended span was emitted. Those calls are absent, not recorded as unknown. Some captured OpenAI Responses and LiteLLM returns also lack enough terminal evidence to report success. Verify the [capture limits](docs/ONBOARDING.md) before relying on this path for complete streaming or failure accounting; compatible native/manual integrations remain alternatives.

**Understand the evidence your AI leaves behind.** The product name is now Sillage, selected for the idea of a wake: understanding what passed through by what it leaves behind. [Meaning and compatibility](docs/BRAND.md). Existing repository paths, `GUARDIAN_*` settings and `/api/guardian` integrations continue to work.

The public experience starts at `/welcome`; `/demo` is an interactive sample workspace that needs no account or private API connection. Sign in at `/signin`, then use **Connections** (`/setup`) to create an app key, install the Python package or select the manual Python/Node alternative, and verify a real captured call. Overview separates recent captured calls from worker-produced accounting, with source and processing state explained. [Experience decisions and acceptance](docs/EXPERIENCE.md), [onboarding](docs/ONBOARDING.md) and [current verification](docs/VALIDATION.md).

Sillage is an early product for understanding cost and reliability problems in AI workflows. It can read an existing Langfuse project or accept numeric terminal-call events directly from an application, apply deterministic detectors and display incidents, metrics and live activity.

**Status: engineering prototype, not production-ready.** The 2026-09-11 review found data-correctness and customer-journey gaps. The next objective is an assisted private beta after the documented gates pass. Historical demo success is not a current release guarantee.

R0 verification infrastructure, the R1 source migration, a bounded durable ledger and incident summary repairs are implemented locally. Guardian defaults to direct HTTPX Langfuse Observations v2 reads. The worker resumes durable pages, deduplicates replay, captures late arrivals within a 24-hour horizon and rebuilds affected rollups. Incident summaries now aggregate all matching records and include today in UTC; live views expose partial, stale and unknown measurements. R1 remains in progress: cutover/recovery, real source compatibility and operating limits still need evidence. The full customer journey is unfinished. See [INGESTION.md](docs/INGESTION.md), [SUMMARIES.md](docs/SUMMARIES.md) and current checks in [VALIDATION.md](docs/VALIDATION.md).

AI SaaS, RAG and agent teams **without existing telemetry or a Langfuse account** have a bounded direct JSON intake path. In an operator-configured OIDC deployment, an owner creates a scoped write-only key and selects the Python launcher, existing-OTel processor or [manual Python/JavaScript recipe](examples/native-capture/README.md). This captures supported call metrics without prompts or responses. Managed provisioning, arbitrary SDK coverage and the complete RAG/workflow journey remain unfinished. [CAPTURE.md](docs/CAPTURE.md) defines the unchanged intake contract.

Bounded per-process Python/Node background exporters and explicit call/stream lifecycle helpers are implemented under [EXPORTING.md](docs/EXPORTING.md). Local admission keeps telemetry HTTP waits outside the model response path, and queue limits, retries, unconfirmed work and shutdown are visible. These source modules require no provider SDK dependency; they do not supply a durable spool, serverless delivery guarantee or automatic RAG instrumentation. Follow the [integration examples](examples/native-capture/README.md) and current [validation record](docs/VALIDATION.md).

Connections retains manual Python/Node OpenAI recipes for Responses and Chat Completions as an alternative to automatic instrumentation. The [provider helper](docs/PROVIDERS.md) surrounds the existing SDK call and extracts validated usage, duration and status; do not apply it to the same call as a launcher/upstream instrumentor. Python supports sync and async clients. Missing usage stays unknown; no price is inferred from tokens. Local SDK checks use synthetic transports, not paid provider calls.

The direct/OIDC path now has an [isolated deployment package and operator guide](deploy/guardian/README.md): one image contains the UI/API, separate processes run ingestion and optional delivery, and explicit bootstrap initializes a compatible database before login. The API serves same-origin static assets and a bounded `/api/ready` endpoint. Operators still supply a TLS Mongo replica set, registered OIDC client and HTTPS ingress. [Deployment evidence](docs/VALIDATION.md) separates native local acceptance from image-build and deployed customer proof; managed provisioning and the release gates remain open.

The R2 named-access foundation supports opt-in OIDC login, opaque server-side sessions and owner/operator/viewer roles for one isolated project. Membership comes from operator configuration; incident resolution and ingestion-key changes record the named actor atomically. Owners can create and revoke direct-ingestion keys; operators/viewers see redacted status. The existing shared-key mode remains available for local Langfuse development. Access, test receipt, real receipt and completed analysis are separate states. This does not create projects or provision managed observability infrastructure. [IDENTITY.md](docs/IDENTITY.md) and [ACCESS.md](docs/ACCESS.md) define access; current verification is recorded in [VALIDATION.md](docs/VALIDATION.md).

## Start with the review

- [Executive assessment](docs/EXECUTIVE.md): verdict and priorities.
- [Product and engineering review](docs/REVIEW.md): concrete findings and customer impact.
- [Product direction](docs/PRODUCT.md) and [onboarding](docs/ONBOARDING.md): who it serves and the complete journey.
- [Architecture](docs/ARCHITECTURE.md) and [decisions](docs/DECISIONS.md): current vs target design.
- [Implementation plan](docs/PLAN.md) and [phase status](docs/PHASES.md): dependency-ordered work.
- [Launch gates](docs/LAUNCH.md), [progress](docs/PROGRESS.md) and [validation](docs/VALIDATION.md): evidence required and available.

## Repository

```text
apps/
  founder-app/             Independent monitored demo, not required by Guardian
    backend/               FastAPI :8000
    frontend/              React :3000
  guardian/                The product
    backend/               FastAPI :8001; separate polling worker
    frontend/              React :3001
packages/sillage-python/   Installable Python client and sillage-run launcher
tools/                     Isolated offline/live verification harness and tests
deploy/guardian/           Direct/OIDC image, Compose roles and operator guide
docs/                      Active review, architecture, plan and evidence
docs/archive/2026-09-09/    Historical planning/status snapshots
```

Services are independent and communicate through telemetry. Guardian pins one capture mode/database/project per deployment: `langfuse` by default, or explicit `direct` with OIDC. It stores numeric observation records, safe PII category findings, work/ingestion state, incidents and derived rollups. OIDC adds hashed sessions, short-lived login state, fixed binding and redacted audit; direct capture adds hashed write-only credentials, receipts and a numeric inbox. Direct views contain no raw content or vendor links. Langfuse live views still process output and serve previews through an in-memory cache, so privacy work remains for that mode. Shared multi-tenant hosting is not implemented.

## Current local developer setup

Use Python 3.13 and Node 24/npm 11 for the locally verified baseline. Each backend has its own virtual environment and resolved-version constraints; each frontend uses its tracked npm lockfile. Real ingestion requires a MongoDB replica set supporting transactions. Langfuse mode also requires an instrumented Langfuse project; direct mode requires OIDC and application instrumentation sending supported numeric events, either through the Python launcher or explicit helpers. The worker has no production nontransactional fallback. Offline tests and the synthetic HTTP smoke need neither service nor provider credentials; dedicated real-database tests have separate setup in [tools/README.md](tools/README.md).

The Guardian database user also needs index-creation permission on `guardian_incidents`: the first summary request after process startup initializes its indexes, then caches successful setup. Failure is reported as unavailable data. See the index contract and operating limits in [SUMMARIES.md](docs/SUMMARIES.md).

OIDC mode also requires transaction-capable Mongo for session rotation and incident resolution, plus TTL-index creation on the authentication collections. Configure a maintained identity provider, a fixed HTTPS frontend/API origin and the named-member allowlist before enabling `GUARDIAN_AUTH_MODE=oidc`. Register the exact `/api/guardian/auth/callback` URL. The database pins organization/project/environment/connection/issuer/client identity and rejects a mismatched deployment; caller project fields cannot reassign it. Full configuration and the explicit loopback-only development exception are in [IDENTITY.md](docs/IDENTITY.md) and the backend environment template. Actual provider registration and deployed TLS callback operation remain unverified.

The default `LANGFUSE_READ_API=v2` uses `GET /api/public/v2/observations` through HTTPX and does not construct an exporter SDK. Set `LANGFUSE_READ_API=v1` explicitly only for a supported self-hosted v3 source or temporary Cloud rollback; that path retains SDK 2.53.9. There is no automatic fallback. Cloud removes legacy reads on **2026-11-16**, and self-hosted v4 omits them. Actual server/exporter compatibility remains a pre-beta verification requirement; the local mock contract does not establish it. [Migration contract and primary sources](docs/SOURCE_MIGRATION.md).

PowerShell, starting at the repository root:

```powershell
Set-Location apps/guardian/backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt -c requirements.constraints.txt
Copy-Item .env.example .env
```

For the default `GUARDIAN_AUTH_MODE=api_key` local path, fill `MONGO_URL`, `GUARDIAN_DB_NAME`, `GUARDIAN_API_KEY`, `LANGFUSE_HOST`, `LANGFUSE_PUBLIC_KEY` and `LANGFUSE_SECRET_KEY` locally. OIDC mode uses its separate settings and never accepts the shared key as a fallback. Keep `LANGFUSE_READ_API=v2` unless deliberately selecting the legacy source path. Keep `GUARDIAN_CONNECTION_ID` (default `primary`) stable when rotating source keys; changing upstream projects requires a new connection. Use the same source mode/connection in API and worker processes, a development source/database, and keep real credentials out of version control. Existing incremental rollups require an explicit cutover; the new writer refuses to silently mix or overwrite them. See [ingestion deployment boundaries](docs/INGESTION.md).

Start the API:

For optional Slack incident delivery in OIDC mode, set `GUARDIAN_SLACK_WEBHOOK_URL` identically in the API and both workers. The URL is a deployment secret. Follow [notification setup and delivery semantics](docs/NOTIFICATIONS.md); the owner must test and enable the destination before new incidents are queued.

```powershell
.\.venv\Scripts\python.exe -m uvicorn server:app --reload --port 8001
```

In another terminal, from `apps/guardian/backend`, start the worker:

```powershell
.\.venv\Scripts\python.exe -m guardian.worker
```

If using Slack delivery, start its separate process from `apps/guardian/backend`:

```powershell
.\.venv\Scripts\python.exe -m notifications.worker
```

In **Setup → Notifications**, select **Send test**, refresh until Slack acceptance appears, then enable incident delivery. Setup shows worker health and recent delivery results; each incident has its own history. Queueing a test does not prove acceptance, and an unconfirmed retry can send another copy. The [direct/OIDC package](deploy/guardian/README.md) supplies a notification-worker override; actual image execution and deployed Slack acceptance remain launch checks.

In another terminal, from the repository root:

```powershell
Set-Location apps/guardian/frontend
Copy-Item .env.example .env
npm.cmd ci
npm.cmd start
```

Copying the frontend environment template sets `PORT=3001` and `REACT_APP_GUARDIAN_URL=http://localhost:8001`. In local shared-key mode, open the dashboard and supply the development Guardian API key. The browser verifies it before saving and restores the requested page after access succeeds. A rejected key requires reconnection; temporary access-service failure offers retry without silently discarding a stored key. In OIDC mode the browser uses the sign-in flow and server cookie, keeps actor/project/CSRF in memory, and does not read or send a saved legacy key. This remains operator setup; managed onboarding is unfinished.

Open **Setup** to inspect source configuration and processing work. Direct setup lets owners create/revoke ingestion keys and separates test handshakes, real received events and worker progress; the full key is displayed only after creation and must be copied before dismissal. In **Monitoring rules**, named owners can save per-call USD and duration limits and choose whether reported errors create incidents. Known values above a configured limit can trigger from the first call; missing prices remain unknown. Open an incident to compare its measurement with the saved rule, inspect its captured run and mark it resolved. [Monitoring rules and change behavior](docs/POLICIES.md).

Configuration or a test receipt does not establish real monitoring. Langfuse source setup remains diagnostic. In local key mode, monitoring rules are read-only and Disconnect clears browser access while the server key remains active. OIDC logout revokes the application session and reports failure with retry; it does not revoke project ingestion keys, stop collection or sign out of the identity provider globally.

For the no-Langfuse path, configure `GUARDIAN_AUTH_MODE=oidc` and `GUARDIAN_CAPTURE_MODE=direct` consistently in API and worker processes, using a fresh isolated database and the fixed identity settings above. See [direct capture setup](docs/CAPTURE.md) and [export recipes](examples/native-capture/README.md). Existing Langfuse data or an incompatible capture binding blocks mode switching; there is no automatic migration or reset. Run the same worker command in either mode.

`GET /api/health` is liveness only. Packaged direct/OIDC deployments use `GET /api/ready` for initialized configuration/database readiness; it remains unavailable in other modes and does not certify worker activity. `GET /api/guardian/auth/config` identifies the configured auth mode without secrets. `GET /api/guardian/access` is independent of summaries and source reads. In local key mode it validates the header/Bearer credential without database/index work; in OIDC mode it checks the Mongo session, fixed scope and current configured membership. A database outage makes named access unavailable, with no key fallback. Guardian API responses are noncacheable; packaged hashed UI assets have immutable caching. Successful access does not establish monitoring readiness.

Authenticated `GET /api/guardian/monitoring` reports the worker's last attempt, successful checkpoint, read status and reason. A stale or blocked worker needs attention even when the API responds. Keep the polling default at 60 seconds for development unless intentionally testing source limits; source quotas depend on endpoint/plan/organization. The existing template's faster-demo suggestion is not a production capacity recommendation.

## Optional Founder workload

From `apps/founder-app/backend`, create its own virtual environment, install with `-r requirements.txt -c requirements.constraints.txt`, copy `.env.example` and configure a development Mongo database, provider credentials and Langfuse. Run:

```powershell
.\.venv\Scripts\python.exe -m uvicorn server:app --reload --port 8000
```

Keep its environment/imports separate from Guardian. Configure a distinct Founder `DB_NAME`; Guardian reads `GUARDIAN_DB_NAME`. Founder still exports through SDK2 and has not migrated to modern ingestion. Older ingestion can take up to 15 minutes to appear in v2, so a short verification timeout cannot establish source availability. The Founder browser flow also depends on its external Emergent authentication integration and has not been validated here. See [source availability](docs/SOURCE_MIGRATION.md) and its [frontend README](apps/founder-app/frontend/README.md).

## Verification

Backend suite, from `apps/guardian/backend` with dependencies installed:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/ -q -rx
```

Harness isolation tests and actual localhost HTTP smoke, from the repository root:

```powershell
.\apps\guardian\backend\.venv\Scripts\python.exe -m unittest discover -s tools/tests -v
.\apps\guardian\backend\.venv\Scripts\python.exe tools/verify_mvp.py offline --guardian-python .\apps\guardian\backend\.venv\Scripts\python.exe --report tools/reports/offline.json
```

Frontend tests and production build, from each app's `frontend` directory:

```powershell
$env:CI = "true"
npm.cmd test -- --watchAll=false --runInBand
npm.cmd run build
```

The repaired harness isolates applications in subprocesses and checks the real `X-Guardian-Key` HTTP contract. No arguments print help. `offline` uses synthetic source events and mocked Mongo; `live --allow-live` requires explicit, dedicated test configuration and can incur provider charges. Setup, boundaries and error codes are in [tools/README.md](tools/README.md).

[Ordinary CI](.github/workflows/ci.yml) runs backend/harness tests, the offline HTTP smoke and both frontend tests/builds without application secrets. The separate [manual live workflow](.github/workflows/live-verification.yml) needs environment setup described in [the CI guide](.github/README.md). Local results and remaining verification are in [VALIDATION.md](docs/VALIDATION.md); a hosted workflow run has not yet been observed.

## Current limitations

Direct intake accepts at most 100 events/256 KiB per batch, with explicit terminal timestamps, stable IDs and optional numeric measurements. A 202 response confirms a durable receipt; processing may still be pending. Test-mode batches never enter production totals or detectors. The worker handles at most 500 inbox records per cycle in transactions of 100; direct live/run views remain bounded to 1,000 records. Per-key/project admission quotas and a 10,000-record pending limit reject excess work explicitly. These are safety limits, not measured production capacity. Receipts, inbox history, credentials and audits currently remain retained; retention/offboarding is unfinished.

The v2 worker reads up to five 100-row pages per poll and resumes the same fixed query on the next poll. Each page persists accepted/quarantined dispositions atomically; only an exhausted traversal advances the source watermark. Every new traversal rereads 24 hours, and initial import accounts for all captured history in that window. A checkpoint older than the supported horizon blocks for an explicit backfill decision. Legacy v1 retains a complete-read-only 500-row limit.

Detector processing waits for source-window exhaustion; bounded work can accumulate. More than 10,000 observations in one hour/agent rebuild or 5,000 earlier observations in a detector baseline leaves work pending with degraded health. Live reads remain capped at 1,000 observations. V2 source calls use fixed 100-row pages, a 15-second read budget, five-second network timeouts and an 8 MiB response limit per page. The hourly metrics endpoint returns HTTP 422 when more than 5,000 buckets match. These are visible limits, not tested production capacity.

Incident summaries use one authenticated `/api/guardian/summary` response with UTC calendar days including today, explicit query bounds and invalid-timestamp coverage. The former 1,000-open/10,000-trend caps are removed. Legacy timestamps are interpreted in Mongo without rewriting history; invalid or timezone-naive dates make coverage partial. Query failures/timeouts return 503, and incident lists show failed reads and retry separately from successful empty results. Exact aggregates still inspect matching data, with a two-second server execution budget; legacy conversion, query/index deployment and production load remain operating limits. [Summary contract](docs/SUMMARIES.md).

Live/run views use observations only. Run lookup accepts 1–168 hours, defaulting to 168; an empty successful lookup returns HTTP 200 with `not_observed` in that window, not a claim that the trace does not exist. Without usable cached data, source failure returns 503 for run lookup or a 200 live snapshot with degraded coverage and null statistics. Cached fallback is labelled stale. Child calls do not establish workflow success or duration; conflicting trace context stays unknown.

All seven original regression assertions now pass: source failure preserves the checkpoint, legacy usage fallback works, a 250-row live window includes later pages, late arrivals inside the tested horizon count once, replay preserves totals, distinct-agent evidence survives, and material spend after a known free baseline is detected. Unknown prices never become a free baseline. Saved policies are pinned at first evaluation; changes do not rescore finished history or reopen resolved incidents. Conflicting observation copies remain quarantined with unknown measurements. Ledger-derived totals describe captured observations, not invoice reconciliation or unlimited history.

Managed provisioning, membership administration, shared-tenant hosting and retention/offboarding remain unfinished. Bounded Slack delivery is implemented; deployed channel acceptance and the broader recovery loop remain open. Named sessions and scoped direct-ingestion keys have local protocol/API/database evidence, including audit rollback, replay, quota and revocation races. Actual loopback HTTP intake reaches worker totals and incidents without constructing a Langfuse client. Real identity-provider registration, deployed TLS and the full account lifecycle remain release gates. Cost alerts are advisory and do not enforce a budget. Regex PII matches are experimental, not proof of a leak. Synthetic browser checks, real local database checks and native browser/worker journeys have distinct evidence boundaries in [VALIDATION.md](docs/VALIDATION.md). Real source services, hosted CI, production recovery and independent customer activation remain open.

Next work completes R1-02 cutover/recovery and load/retention validation, R1-03 query/index and operating validation, and R1-01 modern exporter migration with real source compatibility evidence. R0 credential closure and provisioning/discovery remain open. Each implementation change updates its docs and verification evidence.
