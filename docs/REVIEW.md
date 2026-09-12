# Cost Guardian: product and engineering review

2026-09-11; application baseline `a66caf7`. Scope: Guardian backend/frontend, tests, demo instrumentation, verification scripts, configuration, history metadata and documentation. Existing untracked root `frontend/` artifacts were left alone.

**Assessment: the direction is worth pursuing, but the product does not yet serve a customer end to end.** The reviewed baseline demonstrated detection and display; the repairs below now add bounded durable ingestion. Easy activation, effective response and willingness to pay remain unproven. The founder's requirement that teams without observability can onboard is incorporated in the plan.

Seven targeted offline probes reproduced defects. Other findings are identified as source observations or product judgments. Full verification boundaries: [VALIDATION.md](VALIDATION.md).

Implementation note, 2026-09-12: the numbered findings below preserve historical evidence from baseline `a66caf7`; the current repair table supersedes their descriptions of present behavior. R0-01 repaired verification. Bounded R1 adds shared normalization, typed reads, bounded source threads, truthful live coverage, default Observations v2, a transactional ledger and stable findings. R1-03 repairs summary/calendar/read states. R2 adds named OIDC access, fixed scope, roles, transactional action audit and direct numeric capture with scoped write-only keys. [VALIDATION.md](VALIDATION.md) separates local unit/wire, localhost database/HTTP and synthetic browser evidence. Full R1/R2, actual identity/source services, hosted CI and customer activation remain open. Local shared-key compatibility and Langfuse content/privacy work remain distinct unfinished hosted-use concerns.

## Current repair status through R3 monitoring rules

R3-02 now adds owner-managed cost/duration limits, reported-error control, audited revision changes and pinned evaluation. Readable evidence connects the configured threshold to the observed call and existing run/resolve action. Real localhost API/Mongo checks cover the full save/intake/finding/resolve/replay sequence and transaction races. Notification delivery, measured recovery and independent customer activation remain open.

| Finding | Local implementation and evidence | Still open |
|---|---|---|
| F01 | V2 pages, row dispositions and continuation commit atomically; failed envelopes preserve progress; 24-hour overlap captures new late identities; initial import accounts all captured history; out-of-horizon checkpoint blocks | Actual source/exporter delay, history beyond the horizon/retention, legacy revisions, high-volume recovery and production operations |
| F02 | Durable identity deduplicates replay; fenced transactions protect dirty work and bucket replacement; conflicts become unknown coverage; separate processing state remains visible | Automated legacy backup/cutover/reconciliation/rollback, high-volume baseline/rebuild limits, retention/load and production failover evidence |
| F03 | A 250-row window is read across pages; feed size is separate; observations-only live/run views expose partial/stale/unknown state; empty run returns bounded `not_observed`, source failure is distinct | Live reads remain capped at 1,000 observations; run history is at most 168 hours; durable reconciled workflow summaries and settled workflow outcomes are not implemented |
| F04 | Original distinct-agent assertion passes; stable observation/rule/finding hashes preserve separate calls; atomic insert-only persistence retains human resolution; named resolution audit and durable Slack outbox/history are implemented locally | Grouped episodes, ownership, broader lifecycle/timeline, deployed delivery and verified recovery remain R3 |
| F05 | Shared mapping preserves explicit zero/unknown and exact wire decimals; known-free history now has an explicit one-cent materiality transition; saved absolute limits work without a baseline | Comparable baseline cohorts, current pricing and broader materiality/noise evaluation |
| F06 | Separate app processes/environments, authenticated real localhost HTTP smoke, pinned dependency verification and offline CI definition | Actual live services, hosted workflow execution and the full customer journey |
| F07/F08 | Opt-in direct numeric JSON intake removes the Langfuse-account prerequisite; owner key setup and Python/JS recipes feed the ledger/detectors; test receipt, real receipt and processing are distinct | Operator-configured deployment and manual instrumentation remain necessary; managed provisioning, tested framework/streaming integrations and real customer activation |
| F09 | Langfuse generations and direct terminal-call metrics; runs derive from observed calls, leave conflicts unknown and do not invent whole-run duration | Full retrieval/tool/embedding capture and settled application workflow outcomes remain planned |
| F12/F14 access | Named sessions/roles, fixed binding, exact Origin/CSRF, atomic resolution/key audit and logout; owner-managed hashed write-only keys with expiry/revocation; no stored-key fallback in OIDC | Actual IdP/TLS operation, member/session administration, safe Langfuse content defaults, project lifecycle, managed provisioning and retention/deletion |
| F13/F14 | Bounded source/cache/query work; UTC/date-aware incident aggregation; visible failure/retry; direct admission quotas/backpressure, receipt idempotency and separate pending/processed work | Shared upstream-source quotas, retained inbox growth, legacy conversion/index/load validation, scalable metrics/list pagination and complete accessible customer journeys |
| F15 | Per-app constraints, local installs/tests/builds and default direct HTTPX v2 reader; explicit `v1` rollback with no automatic fallback | Founder exporter remains SDK2; supported source/exporter live checks are R1-01/pre-beta critical; driver and frontend-toolchain migrations remain separate work |

All seven original assertions now pass, including the known-zero-baseline cost transition. Original expected outcomes were retained and the last expected-failure marker was removed after the repair passed. A repaired assertion does not close every part of its finding. [POLICIES.md](POLICIES.md) defines the latest rule/evaluation contract; [PHASES.md](PHASES.md) keeps broader operating and product gates open.

V2 reads at most five pages per worker poll and resumes the pinned traversal. Detector evaluation waits for its exhaustion so later pages can supply earlier baselines. More than 10,000 observations in an hour/agent rebuild or 5,000 earlier observations in a baseline leaves work pending and health degraded. Mongo replica-set transactions are required; legacy increments require an explicit cutover. No unlimited history or production capacity is established by these local repairs.

R1-03 adds independent acceptance for more than 1,000 open and 10,000 dated incidents, exact category breakdowns, UTC year/month/leap boundaries and safe failure/cancellation. `/summary` reports unknown historical date coverage; legacy endpoints retain their shapes and become unavailable when they cannot express it. Historical conversion occurs without a mass rewrite and still has query/load costs. The original F13/F14 descriptions below remain baseline evidence; [SUMMARIES.md](SUMMARIES.md) defines their current repair boundary.

R2-03 removed the entry flow's dependency on `/overview`; the local key mode remains database-independent. The R2-01 extension now verifies named sessions, configured issuer/subject membership and the fixed project binding in Mongo. It never accepts a shared-key fallback; identity storage failure returns unavailable. Role and scope claims from the browser are not authority. Owner/operator resolution requires exact Origin and CSRF and records its actor atomically. One-use login state, session rotation, logout fencing and resolution audit have independent API/store and actual local Mongo evidence. [ACCESS.md](ACCESS.md) and [IDENTITY.md](IDENTITY.md) record the contracts agreed before code. Actual provider/TLS setup and full managed onboarding remain unfinished.

The default v2 reader uses 100-row cursor requests, a 15-second traversal budget, five-second network timeouts and an 8 MiB per-response cap; opaque cursors stay out of API/log output. Both read modes use observations only. Run lookup is 1–168 hours, default 168: complete absence returns 200 `not_observed`. Without usable cached data, source failure returns run 503 or live snapshot 200 with degraded coverage/null statistics; cached fallback remains labelled stale. These behaviors have local contract evidence, not real-service proof.

[CAPTURE.md](CAPTURE.md) records the subsequent no-Langfuse implementation contract. Direct capture accepts only strict terminal-call identities/times/status and optional numeric measurements. Scoped credentials cannot read the dashboard or substitute for human roles; owner changes and redacted audit are transactional. Receipts, quotas and numeric inbox admission commit together, and ledger acceptance commits with inbox acknowledgement. Actual local Mongo tests cover replay, limits, rollback, both revocation orderings and exclusive initial capture-mode claims; actual loopback HTTP reaches worker totals and an incident without a Langfuse client. Test batches stay separate, and a 202 does not claim detection. Production capacity, real integration/activation, managed capture and retained-history deletion remain open.

The subsequent [background exporter contract](EXPORTING.md) closes a practical integration gap: supported Python/Node applications now have a bounded queue, immutable retries, shutdown diagnostics and explicit call/stream helpers. Independent lifecycle tests and actual localhost API/Mongo pipelines cover provider behavior preservation and a hidden committed receipt replay without inflated totals. This advances onboarding for teams without observability, while provider-specific usage extraction, RAG/workflow outcomes, real deployment activation and the customer response loop remain unfinished. In-memory delivery still needs controlled application shutdown.

Explicit `LANGFUSE_READ_API=v1` retains SDK2 for self-hosted v3 or temporary Cloud rollback. Cloud removes legacy reads on **2026-11-16**; self-hosted v4 excludes them. Founder still uses SDK2 ingestion, which can take up to 15 minutes to appear through v2. Exporter migration and actual supported-version evidence remain pre-beta requirements. [Migration contract and primary references](SOURCE_MIGRATION.md).

## Different perspectives at the reviewed baseline

| Perspective | Strength | Missing piece |
|---|---|---|
| Founder | Real problem, vertical slice, small codebase | Reason to buy beyond native alerts; customer evidence |
| New customer | Simple dashboard concept | Setup without Langfuse, project creation, diagnostics |
| Responding engineer | Structured evidence and trace references | Delivery, owner, runbook, recovery and trustworthy grouping |
| Product/finance owner | Costs/models available | Workflow economics, budget policy, measured impact |
| RAG/agent team | Demo groups calls by run | Retrieval, embeddings, tools, terminal outcomes and release context |
| Systems engineer | Separate worker, pure detectors, store interface | Checkpoints, replay, overload handling, indexes and async I/O |
| Security/privacy | Missing key fails closed; PII evidence uses labels | Browser shared key, output previews, key history and data lifecycle |
| Operator/support | Service boundaries and logs | Packaging, readiness, restore, delivery health and runbooks |
| Researcher | Inspectable deterministic rules | Labelled evaluation of usefulness, noise and missed incidents |

## Findings ordered by release impact

P0 prevents trustworthy/safe use or reliable release evidence; P1 blocks a useful private beta; P2 blocks broader self-service or creates material operating debt. These are release priorities, not vulnerability scores.

### F01 — P0: ingestion can permanently miss observations

[langfuse_client.py](../apps/guardian/backend/guardian/langfuse_client.py), `fetch_recent_generations`, returns an empty list for unavailable credentials and a partial/empty list after API failure. [worker.py](../apps/guardian/backend/guardian/worker.py), `poll_once`, advances the cursor to wall-clock `now`, even without candidates. It fetches at most 500 observations from 24 hours and filters candidates by observation start time after the cursor.

Late arrivals, long-running observations completed after their start window, and events on failed/unread pages can be excluded later. An outage over 24 hours cannot fully catch up using this query. First startup records only approximately five minutes as candidates, so the 48-hour overview is not a complete historical view. A detector exception is logged but its work is also passed by the cursor.

**Offline proof:** a failed fetch returned `[]` and advanced the cursor; an older-start event delivered afterward fails the candidate filter. The other loss cases are code-path risks, not live incidents observed this turn.

Fix: typed complete/partial/failed results, stable bounded pagination, durable checkpoints, overlap/reconciliation, retryable detector work and explicit backlog/coverage. R1-01/R1-02.

### F02 — P0: replay inflates cost and calls

[metrics.py](../apps/guardian/backend/guardian/metrics.py), `record`, increments every candidate with `$inc`. [models.py](../apps/guardian/backend/guardian/models.py) drops observation ID and retains only trace ID. Crashes between rollups and checkpoint persistence, replays or concurrent workers repeat increments.

**Offline proof:** recording one $2 observation twice produced two calls and $4. Previously accepting this as “only trend lines” undermines a cost product's core promise.

Fix: durable project/observation identity, revision-aware processing, rebuildable/transactional rollups and reconciliation. Keep bounded derived numeric records, not prompts or outputs. R1-02; ADR-04.

### F03 — P0: window totals may describe only 100 calls

[traces.py](../apps/guardian/backend/guardian/traces.py), `_fetch_calls`, reads one page of 100 and ignores pagination metadata. `_stats_from` labels that sample with the selected 24-hour/7-day window. The visible feed defaults to 60 rows. `_runs_from` joins traces to the limited sample and treats no observed errors as success, even when children are absent. Trace fetches do not apply the selected time window. `run_detail` maps upstream errors to not-found and discards stale-cache status.

**Offline proof:** an upstream fixture reporting 250 observations produced a 100-call snapshot without a partial flag.

Fix: complete reconciled summary data, explicit sample/partial/unknown states, paginated rows, matching time ranges and explicit workflow outcomes. R1-03.

### F04 — P0: dedup loses distinct evidence and races

[incident_engine.py](../apps/guardian/backend/guardian/incident_engine.py) checks `(detector, first_trace_id)`. [store.py](../apps/guardian/backend/guardian/store.py) separately checks existence then saves by random incident ID. Multiple agents/conditions in one trace can be suppressed without evidence merging; concurrent workers can both pass the check.

**Offline proof:** reliability findings for two agents in one trace persisted only the first agent's incident. This is evidence loss, not useful correlation.

Fix: atomic unique signal identity including observation/rule/version; explicit bounded grouping retains all signals and updates severity/timeline. R1-02/R3-01.

### F05 — P0: unknown cost/usage becomes zero

[langfuse_client.py](../apps/guardian/backend/guardian/langfuse_client.py) and [traces.py](../apps/guardian/backend/guardian/traces.py) maintain different mappings. Missing costs become zero; invalid timestamps can become current time. Live `_tokens` accepts empty `usageDetails` before populated `usage`. Baselines mix failures, models and environments sharing an agent name.

**Offline proof:** empty `usageDetails` hid 20 valid tokens. A $2 candidate against six zero-cost baseline samples caused no cost alert. Zero-baseline suppression is the current policy, made problematic by representing unknown prices as zero.

Fix: one normalized mapper, cost provenance/currency, finite/nonnegative validation, explicit missingness, observation kind/outcome and comparable cohorts. Unknown is not free. R1-01/R3-02.

### F06 — P0: the verification harness is incompatible with the split

[verify_mvp.py](../tools/verify_mvp.py) prioritizes Guardian directories on `sys.path`, importing Guardian `config`, `db` and `server`. Founder [base_agent.py](../apps/founder-app/backend/services/agents/base_agent.py) imports `get_llm_api_key`, absent from Guardian config. Both `.env` files load into one environment without isolation. Step 9 creates Founder sessions and sends a cookie; Guardian [auth.py](../apps/guardian/backend/auth.py) requires a header/Bearer key. [build_baseline.py](../tools/build_baseline.py) shares import/environment mixing.

The harness uses in-process ASGI transport, not a deployed network boundary. Its synthetic anomaly bypasses source ingestion and does not refer to a real source trace. These can be useful component checks when accurately labelled, but cannot prove the complete customer journey.

**Evidence:** source contract mismatches; live harness not executed. Fix independent subprocess/HTTP orchestration, scoped credentials, fixture isolation and truthful reports. R0-01.

### F07 — P0 before external data: historical credentials need closure

The prior [decision log](archive/2026-09-09/DECISIONS.md) records credentials committed in `6b20601`/`bbb6820`. History metadata confirms `backend/.env` existed there and was later removed. This review did not retrieve values, test credentials or verify revocation. Ignore rules do not revoke history or guarantee future secrets cannot be committed.

Fix: owner verifies revocation/replacement for the affected providers; record completion without secret values; scan history and new changes. Do not assume keys are currently live or already rotated. R0-02.

### F08 — P1: customers without telemetry cannot activate

[ConnectScreen.jsx](../apps/guardian/frontend/src/pages/ConnectScreen.jsx) expects a key from an operator's `.env`; [config.py](../apps/guardian/backend/config.py) configures one global Langfuse project. Signup/project creation, instrumentation, source provisioning, diagnostics and baseline readiness are absent.

Fix: managed capture and bring-your-own Langfuse as equally deliberate journeys. Instrumentation remains necessary; an LLM provider key alone is not workflow history. [ONBOARDING.md](ONBOARDING.md), R2.

### F09 — P1: RAG/workflow health is outside ingestion coverage

Only `GENERATION` observations are fetched. The model lacks kind, parent, project, environment, workflow, deployment and terminal outcome. Embedding spend, retrieval timing/results, tool errors and application outcomes are not represented. Recovered provider failures are high-severity candidates; semantically failed workflows with successful model calls may be missed.

Fix: root workflows, attempt relationships, retrieval/embedding/tool span metadata and application-declared outcome. Do not equate operational health with answer quality. R1-01/R2-02/R3-02.

### F10 — P1: response ends at “mark resolved”

At the review baseline, [routes.py](../apps/guardian/backend/api/routes.py), [incident.py](../apps/guardian/backend/guardian/incident.py) and [GuardianIncidentDetail.jsx](../apps/guardian/frontend/src/pages/GuardianIncidentDetail.jsx) provided open/resolved status and JSON evidence. The current implementation adds named resolution audit, readable policy evidence and [durable Slack notification delivery](NOTIFICATIONS.md) with owner test/activation, bounded retries and history. Assignment, acknowledge/snooze, dismissal reasons, deterministic guidance and measured recovery remain open.

Fix: one durable notification channel, auditable lifecycle, deterministic runbooks and post-mitigation measurement. R3.

### F11 — P1: rules lack economic and operational calibration

[cost_anomaly.py](../apps/guardian/backend/guardian/detectors/cost_anomaly.py) checks per-call cost, not token or aggregate-spend anomalies. Five samples and z-scores do not establish performance on skewed traffic. No absolute impact floor, volume floor, budget, expected-change suppression or cohort policy exists. Ten times the volume at unchanged per-call cost can yield ten times the spend with no cost anomaly.

[reliability_anomaly.py](../apps/guardian/backend/guardian/detectors/reliability_anomaly.py) flags every failed generation, not an error-rate change. A few recovered free-tier errors prove detection wiring, not incident usefulness.

Fix: budgets/burn policy, meaningful baseline cohorts, cold-start status, error-rate/outcome policy, business impact, labelled evaluation against simple threshold alternatives. R3-02.

### F12 — P1: access/privacy promises exceed implementation

[guardianApi.js](../apps/guardian/frontend/src/services/guardianApi.js) keeps the shared all-access key in localStorage; there are no individual permissions or resolve actors. [traces.py](../apps/guardian/backend/guardian/traces.py) serves output previews, provider error text, user/session IDs and tags, and caches read results in memory. “Not persisted in Mongo” is narrower than “no sensitive data processed/exposed.”

[pii.py](../apps/guardian/backend/guardian/detectors/pii.py) identifies patterns, not policy violations. Public emails may be legitimate; phone formats are US-oriented; card matches lack checksum validation. No locale/allowlist/content-consent policy exists.

Fix: named users, scoped credentials, short-lived browser sessions, default-off content capture/previews, sanitized errors, retention/export/delete/disconnect, experimental scanning disclosure. R2-01/R2-03.

### F13 — P1/P2: quiet availability and scale failures

[server.py](../apps/guardian/backend/server.py) returns healthy without Mongo/source/worker/delivery checks. Synchronous upstream reads inside async routes can block the event loop. The live cache is process-local with no capacity eviction or shared quota coordination. Multiple windows/tabs/processes can multiply upstream demand.

[routes.py](../apps/guardian/backend/api/routes.py) lacks bounds on `days`, `hours` and list limits. Overview/trends/metrics silently cap loaded data at 1,000/10,000/5,000 documents; the trends day loop omits today. Lists lack pagination. No index setup/migration, Guardian deployment package, CI pipeline, restore procedure or retention job was found in tracked files.

Fix: bounded async work, source-budget coordination, indexes/aggregation, explicit liveness/readiness/freshness, capacity and restore drills. R1-03/R4-02/R5.

### F14 — P1/P2: UI failures can appear healthy

[GuardianIncidents.jsx](../apps/guardian/frontend/src/pages/GuardianIncidents.jsx) may show “No incidents” after a failed initial read; overview similarly defaults to zero. [GuardianLayout.jsx](../apps/guardian/frontend/src/pages/GuardianLayout.jsx) paints “Live” from browser response time, not worker coverage. [useLiveData.js](../apps/guardian/frontend/src/hooks/useLiveData.js) lacks request cancellation/sequence guards, permitting an older filter response to overwrite the current selection. API requests lack timeout and global expired-key recovery. ConnectScreen stores the key before validation; reload treats key presence as connection.

Clickable incident cards lack semantic links, creating keyboard-access issues. No frontend or live-reader automated tests were found; mobile/screen-reader behavior was not exercised here.

Fix: honest empty/error/stale states, source heartbeat, guarded refreshes, auth recovery, accessible controls and journey browser tests. R1-03/R2-03.

### F15 — P2: dependency lifecycle and reproducibility

Guardian pins Langfuse 2.53.9 and Motor 3.3.1; frontend uses CRA/CRACO. Current Langfuse docs describe changed read/availability contracts, MongoDB recommends PyMongo Async migration, and React has deprecated CRA. Migrate through adapters with regression and rollback checks. [Langfuse observations](https://langfuse.com/docs/api-and-data-platform/features/observations-api), [PyMongo migration](https://www.mongodb.com/docs/languages/python/pymongo-driver/current/reference/migration/), [CRA deprecation](https://react.dev/blog/2025/02/14/sunsetting-create-react-app).

Both frontends have tracked lockfiles. The gap is clean-install/build proof and maintenance, not a missing Guardian lockfile. No vulnerability scan ran; version age alone is not asserted to be an exploit.

### F16 — P1: positioning and status drift

Old docs contained conflicting phases, “no blockers,” ~87%/~91% progress, superseded auth decisions and inconsistent browser/live results. Native Langfuse alerts now overlap the original pitch. This update replaces active planning/status and preserves the earlier records in [archive](archive/2026-09-09/PROGRESS.md).

## Keep, change, postpone

**Keep:** separate Guardian service, pure detectors, structured evidence, initial Langfuse adapter, storage interface and independent demo workload.

**Change:** onboarding, observation identity/checkpoint design, workflow economics, grouping/delivery/recovery, privacy/access defaults and release evidence.

**Postpone:** autonomous remediation, broad AI investigator, every-provider connectors, unvalidated security/quality claims and a custom raw-trace database. A small deterministic grouping/runbook layer is sufficient for the first useful release.

## Founder guidance

The next important demonstration is a new team connecting its own app, receiving one useful incident, taking action and seeing a measured improvement. Repeat with SaaS, RAG and agent workflows. Account for support effort if you must operate every step. Compare the experience against native alerts for already-instrumented users. If partners cannot show repeated value, narrow or change the offer before expanding the platform.
