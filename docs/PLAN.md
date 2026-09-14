# Sillage: implementation plan

## Cream and brick product refresh, 2026-09-14

Follow ADR-53 and [DESIGN_REFRESH.md](DESIGN_REFRESH.md): redesign the landing/demo, complete workspace theme, local typography and matching vector brand assets; use normal Sign up/Sign in navigation with confirmed registration leading to a waitlist page. Preserve storage/auth semantics, verify both build modes and desktop/mobile journeys, refresh the owned preview and update documentation with measured results.

Implemented and verified on 2026-09-15: 396 frontend tests, 29 public server/build tests, 53 static-boundary tests (one platform skip), 69 workspace browser scenarios, ten actual public browser/Mongo phases and all eight native onboarding/restart/outage phases pass. Both clean build modes include the matching local fonts and brand assets. Desktop and 320/390px mobile previews were reviewed; the public preview runs on port 3004 and the preserved workspace on 8001. [VALIDATION.md](VALIDATION.md) records the exact artifacts. Next complete the existing hosted-public setup and independent customer activation gates; visual completion does not provision customer accounts.

## Public frontend deployment and registration, 2026-09-14

Follow ADR-52 and [PUBLIC_LAUNCH.md](PUBLIC_LAUNCH.md): independent Vercel public site, bounded workspace availability check, clear unavailable/coming-soon path, durable early-access records, operator export/deletion and actual outage/recovery verification. Preserve existing workspace authentication and runtime. Prepare the code and deployment configuration now; verify the external Vercel project and hosted database before claiming a live signup service.

Implementation and local acceptance are complete: 380 frontend tests, 23 function/storage tests, six build-isolation tests and nine browser/Mongo phases pass. The next step is operator setup: authenticate the intended Vercel account/project, connect and bootstrap a dedicated hosted interest database, configure a real privacy contact and server environment, then verify the deployed public routes and one consented registration. No database or paid hosting plan was provisioned. [VALIDATION.md](VALIDATION.md) records exact scope and artifact evidence; account provisioning and broader product release gates remain open.

## Standards-based capture continuation, 2026-09-13

[OPENTELEMETRY.md](OPENTELEMETRY.md) and ADR-51 defined the implementation before code: maintained OpenInference hooks → bounded numeric OTel processor → existing direct collector/worker → real grouped calls and parent references. This path is now implemented in 0.2.0 and passed independent installed-wheel tests, including existing-provider preservation, OpenAI 1.x/2.x, original Founder agent metadata, LangChain callbacks and native compatibility. The final delivery includes Sillage's landing page, frontend and documentation on `mvp2.0`; [VALIDATION.md](VALIDATION.md) records final build/browser evidence. Existing direct/native and Langfuse paths remain supported.

The next product milestone is an assisted onboarding of an independent application: choose its actual capture layer, confirm a real received and processed call, inspect known/unknown measurements and test a useful alert through resolution. Prioritize gaps observed there. Upstream missing stream/cancellation spans, generic OTLP admission, full workflow/RAG storage, cross-process propagation and self-service provisioning remain explicit release gates; the current numeric bridge does not close them.

## Simpler application integration, 2026-09-13

The next bounded R2-02 slice follows [INSTRUMENTATION.md](INSTRUMENTATION.md) and ADR-50, recorded before code:

1. Package the existing numeric exporter and add version-checked Python startup hooks plus `sillage-run`; retain manual Python/Node compatibility.
2. Serve one authenticated wheel and make install/run the default Connections path. Keep application keys distinct from sign-in and provider keys; show the actual capture source and require a real processed call for verification.
3. Install the wheel outside this checkout and exercise actual SDKs, original Founder Path fallback code and the real collector/worker using explicitly synthetic provider responses. Test identity, error/stream behavior, deduplication and absence of raw content.
4. Run the original Founder Path UI/API and refresh Sillage's preview after tests. Document missing real auth/provider/source credentials separately from local runtime and fixture evidence.

Broader SDK versions, Node startup instrumentation, framework/OTLP bridges, subprocess coverage and full RAG context follow measured customer needs. Completed checks and remaining gaps belong in [PROGRESS.md](PROGRESS.md) and [VALIDATION.md](VALIDATION.md).

This bounded slice is implemented and locally verified: the installed package passed actual SDK/collector checks, the default onboarding passed browser/native acceptance, Sillage was refreshed, and original Founder Path now starts through the package. Next prioritize one real customer workflow and visible exporter failure diagnostics, then broaden the adapter matrix from observed demand. Independent customer activation and deployed operations remain open.

## Query feedback delivery, 2026-09-13

The founder's [query.md](query.md) is addressed through the pre-code [experience contract](EXPERIENCE.md), alongside the selected [Sillage identity](BRAND.md). The public landing/demo, redesigned access/navigation, guided Connections, downloadable integration helpers and independent recent-call Overview are implemented. Current validation is tracked in [VALIDATION.md](VALIDATION.md); original R0-R6 release gates remain in force.

The experience slice passed the full frontend/backend suites, 67 browser scenarios and the actual eight-phase native onboarding/deployment check; the local preview is refreshed with that build. The next product gaps are self-service membership and project provisioning, full workflow/RAG spans and content/privacy controls, independently verified activation by a new customer, and deployed operational acceptance. These require explicit persistent contracts and verification; a demo or visible signup form cannot close them.

Updated 2026-09-12. R0-01, default Observations v2 reads, bounded run views, the R1-02 ledger, R1-03 incident summary/calendar repairs, the R2-03 access/setup prerequisite and the R2-01 isolated OIDC/session/role foundation are implemented locally. R1/R2 remain in progress: real source/exporter compatibility, cutover/recovery, operating limits, account administration, managed provisioning and real application activation are still open. Scoped ingestion credentials and native terminal-event capture are now implemented locally under [CAPTURE.md](CAPTURE.md). [INGESTION.md](INGESTION.md), [SUMMARIES.md](SUMMARIES.md) and [ACCESS.md](ACCESS.md) record the contracts agreed before code. Canonical phase IDs are R0-R6; earlier numeric phases are historical.

This plan implements the founder's requirement: teams without existing observability can onboard, alongside existing Langfuse users. [REVIEW.md](REVIEW.md) explains findings; [ARCHITECTURE.md](ARCHITECTURE.md) defines contracts; [LAUNCH.md](LAUNCH.md) defines gates.

## R0 baseline implementation

**R0-01: restore repeatable verification before changing production behavior.**

- Remove harness reliance on importing both apps' top-level `config/db/server` modules in one process. Start each app in its own environment; exercise Guardian through its actual HTTP authentication contract.
- Keep demo/sample traffic in a dedicated project/database and label synthetic source events. A detector-injected anomaly remains a component check, not source-to-customer verification.
- Create a clean documented Python environment, install requirements, run the existing suite, and record actual output. Resolve runtime compatibility through a narrow change if needed.
- Run each frontend's locked install/build in its own directory; verify frontend environment setup and deep-link routing.
- Add meaningful regressions for the seven confirmed probes and the harness auth/import mismatch. They should initially fail for the affected behavior; do not change expected results to match defects.
- Add a CI job for install/tests/build and a separate explicitly configured live verification job. Ordinary CI must not require paid model calls or production secrets.
- Update VALIDATION/PROGRESS with commands, environment, pass/fail and limitations in the same change.

Done: someone can reproduce baseline results from a clean checkout; reports distinguish unit, adapter, HTTP, browser and live checks.

Implementation record: isolated harness and actual localhost HTTP smoke, independent regression assertions, offline isolation and CI workflows are present. Per-app constraints and lockfiles establish local builds. All seven original product/policy regression assertions now pass after the R3-02 known-zero-baseline repair. [VALIDATION.md](VALIDATION.md) records actual checks; live integration, hosted CI, credential closure and customer activation remain unverified.

## Current R1 slice and next dependency

Implemented: one nullable observation normalizer, typed bounded source traversal, bounded blocking source execution, observed live summaries, ledger-derived rollups, source/processing health and corresponding UI states. The docs contract preceded implementation; source, worker/API, signal identity, live/UI and independent regression streams were integrated and reviewed.

R1-02 reads up to five 100-row v2 pages per poll, persists each page with row dispositions and resumes its fixed query on the next poll. Failed/malformed envelopes preserve progress; valid rejected rows have durable, content-free quarantine. Every new traversal rereads 24 hours and accounts for new observation identities, including all initial import history. Source completion and downstream processing completion are separate. The worker refuses checkpoints outside the supported horizon and legacy aggregate cutover without an explicit decision.

R1-03 now aggregates incident summaries in Mongo instead of loading capped raw lists. A single authenticated response contains totals, bounded category breakdowns, UTC calendar trends including today, query bounds and invalid-date coverage. New writes add indexed BSON creation time while preserving public ISO dates; legacy conversion occurs without a mass migration. Incident lists distinguish failure/retry, stale same-filter rows and successful empty results. Query timeouts become unavailable, not zero. Remaining work validates legacy scan/index costs and production concurrency/load; the 5,000-bucket metrics limit and list pagination still need a scalable follow-up. [SUMMARIES.md](SUMMARIES.md) defines the implemented boundary.

**R1-01's modern read adapter is implemented; live compatibility is still required before beta.** The default uses HTTPX Observations v2 with cursor pagination and explicit field groups; legacy SDK2 reads require `LANGFUSE_READ_API=v1`. Live/run views no longer call deprecated trace endpoints. The legacy Cloud API retires on 2026-11-16 and is absent in self-hosted v4. Founder exporter migration remains open. [Official migration guide](https://langfuse.com/faq/all/deprecated-api-migration), [server compatibility](https://langfuse.com/self-hosting/upgrade/versioning).

R1-02 now uses a fenced Mongo transaction boundary for durable pages, ledger/work changes, rollup replacement and incident insertion. Same-ID replay is a no-op; ambiguous changed copies become unknown conflict coverage in both modes. Detector evaluation waits for source-window exhaustion so later pages can supply the earlier baseline. Rebuilds over 10,000 observations per hour/agent bucket and baselines over 5,000 earlier observations retain pending work and report degraded health. Verify backlog drain at the advertised load; these limits are not a capacity claim.

Remaining R1-02 work is the complete real transaction/failure evidence, automated legacy cutover with backup/rollback, retention and load validation, and recovery for unsupported historical gaps. Local single-node database results are recorded separately from mock/wire tests in [VALIDATION.md](VALIDATION.md). Real delayed availability and exporter compatibility remain R1-01 work under [SOURCE_MIGRATION.md](SOURCE_MIGRATION.md).

## Work packages

Current founder input: [query.md](query.md), 2026-09-13. [EXPERIENCE.md](EXPERIENCE.md) records the product-experience contract before code: visible landing/demo/sign-in and application redesign, guided connection and credential management, clear data provenance, independent recent-call versus processed-accounting views, and trustworthy trace duration. The existing isolated identity/capture model remains authoritative; public demo data cannot enter customer telemetry. Self-service account provisioning and raw/RAG trace capture remain explicit gaps rather than simulated features.

Deployment/onboarding implementation started on 2026-09-12 under [DEPLOYMENT.md](DEPLOYMENT.md), recorded before code. The direct/OIDC package now includes a shared API/static build, independent workers, explicit transactional bootstrap, file-based secrets and separate readiness. [Operator commands](../deploy/guardian/README.md) cover configuration, startup, first traffic and shutdown. Verify the actual entrypoint, login, key/test/real capture, processing, incident resolution and logout through a real local browser/issuer/database; record results in [VALIDATION.md](VALIDATION.md). Native-process, container-build and deployed-TLS evidence remain distinct. This is early R4-02 packaging work that enables the R2 customer journey, not completion of the beta phase.

The actual native acceptance journey now passes all eight phases under [VALIDATION.md](VALIDATION.md). Its screenshot review identified a narrow R1-03 display follow-up before beta: render a known zero-duration call as a point rather than a full-width timeline bar, and preserve measured duration when the call reports an error. Accounting is correct; the run UI currently hides that known error-call duration. Record the display decision before the next UI change and retain unknown-versus-zero coverage.

R2-02 provider usage integration is implemented locally under [PROVIDERS.md](PROVIDERS.md), recorded before code on 2026-09-12. Python/Node OpenAI Responses/Chat Completions call and stream adapters reuse the bounded exporters; Setup leads with runnable SDK recipes. The SDK-to-incident verification record is in [VALIDATION.md](VALIDATION.md). Cost remains unknown without an independently supplied amount; automatic pricing requires an explicit provenance/fingerprint contract and is not silently added to recorded spend.

R3-03 is implemented locally under [NOTIFICATIONS.md](NOTIFICATIONS.md), recorded before code on 2026-09-12: one operator-configured Slack destination, owner test/activation, atomic incident outbox, separate delivery worker, bounded retries and visible history. Actual Mongo/local receiver and browser evidence is recorded in [VALIDATION.md](VALIDATION.md). No live Slack message was sent during implementation verification; deployed acceptance remains a launch gate.

Current product continuation (2026-09-12): owner-managed monitoring rules and readable threshold evidence under [POLICIES.md](POLICIES.md) connect to durable Slack delivery under [NOTIFICATIONS.md](NOTIFICATIONS.md). OpenAI usage recipes now connect an application's existing SDK operations to that capture path. These contracts were recorded before code. The API/Mongo/local receiver checks cover test/activation, captured calls, atomic incident/delivery creation, investigation, resolution and replay; actual SDK fixtures add usage extraction evidence. Final slice results belong in [VALIDATION.md](VALIDATION.md). The direct/OIDC deployment package now makes this path runnable; actual image execution, deployed acceptance and operating drills are the next evidence gaps.

The bounded Python/Node exporters under [EXPORTING.md](EXPORTING.md) supply queue/flush/retry behavior for long-running servers while preserving Guardian JSON version 1. OpenAI usage adapters now build on this layer under [PROVIDERS.md](PROVIDERS.md). Deployment/onboarding, further providers, pricing provenance and workflow/RAG event design remain R2 work; durable delivery after process exit remains a separate decision.

Current slice: scoped write-only ingestion keys and a native Guardian JSON intake/worker/setup path are implemented locally under [CAPTURE.md](CAPTURE.md), recorded before code; verification and limits are tracked in [VALIDATION.md](VALIDATION.md). This reuses the numeric ledger for teams without Langfuse and keeps OTLP, automatic instrumentation and managed backing provisioning as separate work. Source modes cannot silently share or reassign an existing database.

Product implementation order now prioritizes proving and operating the packaged onboarding path for the implemented OpenAI usage integration and existing response loop. Saved per-call rules, incident investigation/resolution and durable Slack notification/history are implemented locally. Next close actual Linux image execution, real TLS/IdP/customer activation and restore/retention/offboarding evidence. Define reported-versus-estimated cost provenance without changing old canonical hashes before adding pricing. Extend the event contract for retrieval, embeddings and explicit workflow outcome before implementing a RAG example. Measure setup assistance and actual application traffic through deployed identity/API/ingestion/delivery/UI; finish content defaults and operator lifecycle before release.

R2-01 isolated-project named identity is implemented locally under [IDENTITY.md](IDENTITY.md): maintained OIDC code flow, opaque server sessions, operator-managed membership, a fixed deployment binding, role/CSRF enforcement and transactional resolution audit. Signed-token, route/browser and real Mongo fault checks establish the local foundation. Member invitations/session administration, provider registration and production callback validation remain unfinished R2-01/release work. Scoped ingestion credentials now extend this foundation; automatic provisioning and full application recipes remain open.

R2-03 access/setup prerequisite is implemented under [ACCESS.md](ACCESS.md). Access verification is independent of dashboard/telemetry health; candidate keys are verified before storage and stored keys before protected rendering. Browser recovery, credential-change guards, read-only setup diagnostics and distinct incident-detail errors are implemented. This fixes rejected-key persistence and summary-dependent sign-in without closing managed provisioning or real onboarding acceptance. Local evidence is recorded in [VALIDATION.md](VALIDATION.md).

| ID | Outcome / scope | Dependencies | Evidence required |
|---|---|---|---|
| R0-01 | Independent harness, clean installs, baseline tests and CI | None | Repeatable offline suite and build; correct header-auth HTTP check |
| R0-02 | Close historical credential exposure, secret scan and release data boundary | None | Revocation confirmations without values; history/current scan reviewed |
| R0-03 | Partner problem discovery and managed-ingestion/provider spike; agree telemetry schema | None | 8-10 interviews planned/conducted status; three candidate stacks; provisioning/quotas/cost/retention decision; contract examples |
| R1-01 | Shared observation contract; default v2 REST reader and explicit v1 compatibility; bounded observation-based views | R0-01; schema from R0-03 | Local cursor/field/measurement/consumer fixtures implemented; real server/exporter matrix and cutover evidence still required |
| R1-02 | Bounded ledger, lease, work queue, stable incident identity and rebuilt rollups implemented; finish cutover and operating gate | R1-01 | Real transaction/restart/takeover evidence; source/ledger/rollup reconciliation; legacy backup/cutover/rollback; conflict and high-volume bounds verified |
| R1-03 | Summary aggregation/calendar/coverage and incident error states implemented; finish query/index and operating validation | R1-01/R1-02 for final integration | >1,000 open/>10,000 dated counts; UTC/legacy date and failed-read evidence; index plans and legacy scan/load costs; supported metric/list scale |
| R2-01 | Named users, roles, project lifecycle and credential management | R0-02; scope contract R1-01 | Role-denial and project-bound key tests, session expiry, rotation, tenant boundary checks |
| R2-02 | Native scoped JSON intake, bounded Python/Node exporters and OpenAI call/stream usage recipes implemented locally; finish deployment, pricing provenance, further providers and RAG outcomes | R0-03/R1/R2-01 | Developer with no Langfuse account gets real attributed traffic; streaming/retry/retrieval/embedding tests |
| R2-03 | Bring-your-own setup, diagnostics, content-safe defaults, internal evidence, accessibility/auth recovery | R1/R2-01 | BYO and managed journeys; wrong host/region/key; disconnect/reconnect; content canaries absent; keyboard flow |
| R3-01 | Grouped incidents and lifecycle: preserve signals, owner, acknowledge, snooze, dismiss, resolve/reopen and audit | R1-02/R2-01 | Distinct failures survive; duplicate replay does not notify twice; actor/reason history |
| R3-02 | Per-call cost/duration/error policies and pinned evidence implemented locally; finish budgets/burn/error rates, outcomes, cohorts and RAG indicators | R1/R2 telemetry contract | Actual save/capture/finding/resolve/replay covered; broader normal/spike/volume/retry/low-data evaluation remains open |
| R3-03 | Durable Slack delivery implemented locally: owner test/activation, atomic outbox, retries/history | Identity; existing stable incident creation (broader R3-01 remains separate) | Real Mongo/local receiver and browser evidence; deployed Slack, supervisor/image acceptance, retention/load and external dead-man monitoring remain open |
| R3-04 | Investigation guide, feedback and post-change recovery/weekly outcome report | R3-01/R3-02 | Partner follows evidence, records action and sees recovery pending/confirmed correctly |
| R4-01 | Assisted beta on three independent partner apps, both onboarding paths | R0-R3 gates | SaaS/RAG/agent journeys; observed setup and incident handling; minimum beta observation window |
| R4-02 | Direct/OIDC packaging, bootstrap/readiness and operator runbook implemented; finish image/deployed acceptance, load/failure/restore/offboarding drills and dependency lifecycle | R1-R3; packaging started early to unblock R2 | Distinct native/browser, image-build and TLS/IdP evidence; real replica-set recovery, operator alert, backing deletion and dependency lifecycle |
| R5-01 | Shared self-service only if justified; full tenant isolation and account lifecycle | R4 evidence | Two-tenant adversarial tests across API/jobs/cache/exports/deletion/delivery |
| R5-02 | Paid launch: pricing/allowances/metering/billing lifecycle, support/privacy/access/retention pages | R4 customer/economic evidence | Auditable usage; trial/cancel/export/delete; payment failure/webhook idempotence if billing integrated |
| R5-03 | Staged rollout, rollback, support ownership and published supported limits | R5-01/R5-02 and LAUNCH gates | Canary and rollback drill, monitored launch and first renewal/value review |
| R6-01 | Additional integrations, evaluated quality, change correlation or AI investigation | Retained customers and measured demand | Separate evaluation and economic justification for each addition |

R1 now supplies stable finding identity; R3 must preserve it when adding incident grouping and delivery. R2 may build against reviewed contracts while R1 gates are completed, but cannot pass acceptance on mocks alone.

## Parallel work and integration order

Parallel work means independent implementation streams with shared contracts. R0-01 used separate harness, backend regression and frontend streams, followed by an independent review of the harness and workflow boundaries.

| Stream | Can proceed alongside | Contract / merge boundary |
|---|---|---|
| Customer discovery and pricing research | R0-R3 engineering | PRODUCT/DECISIONS own claims and open assumptions |
| Ingestion, normalized records and rollups | Setup UI prototypes after schema agreement | Merge schema/adapter first, then consumers |
| Identity and project lifecycle | Ingestion fixes | Server-derived scope required before external data |
| Setup UX/integration recipes | Backend pipeline and identity | Use versioned examples/mocks; integrate against real API before gate |
| Incident UX and runbooks | R3 policy/delivery implementation | One incident/event contract; no independent competing statuses |
| Operations/security and documentation | Every phase | Deployment, migration and evidence accompany the feature |

Assign one owner per shared contract/file area. Keep implementation slices small enough to review and roll back. Avoid simultaneous migrations of telemetry SDK, database driver and frontend toolchain in the same change.

## Documentation accompanies every implementation slice

Before code: agree affected behavior, scope, contract, failure cases and acceptance test. Update the relevant decision if the design changes.

With code: update setup examples/OpenAPI, data handling, migration/rollback and operational instructions. Record actual checks in VALIDATION and status in PROGRESS/PHASES.

After verification: mark the ticket complete only when the customer-facing acceptance condition passes. A mock, a compilation or a happy-path demo cannot close a live recovery/onboarding/value gate.

Document ownership:

- PRODUCT: customer promise, supported scope, value metrics.
- ONBOARDING: setup steps, diagnostics and supported integrations.
- ARCHITECTURE/DECISIONS: boundaries, contracts, tradeoffs and migrations.
- PLAN: dependency-ordered work packages.
- PHASES: one phase/ticket status source.
- LAUNCH: release thresholds and evidence checklist.
- PROGRESS/VALIDATION: current summary and actual verification.
- README: current setup and navigation, with limitations.

## Sequencing and effort

Do not promise a launch date from file count or the old completion percentage. R0 establishes environment and provisioning complexity; estimate R1-R3 after that spike with named engineers and actual capacity. Reserve at least two weeks of beta observation after the response loop works; low incident volume can require longer. Managed onboarding, privacy and operations materially increase scope beyond the old dashboard MVP.

The first go-live milestone is an **assisted private beta meeting its gates**, not public self-service. Paid shared hosting has additional gates. Research is not on the critical path.
