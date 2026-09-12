# Cost Guardian: launch gates and evaluation

2026-09-12. All gates below are **open**. Thresholds are proposed acceptance targets to validate during R0/R4, not current service guarantees. [PHASES.md](PHASES.md) tracks implementation; [VALIDATION.md](VALIDATION.md) records proof.

R0 verification, default direct HTTPX Observations v2 reads and the bounded R1-02 ledger have local evidence. All seven original regression assertions now pass. R3 adds [Monitoring rules](POLICIES.md): saved cost/duration limits, reported-error control, pinned revisions and readable threshold evidence through investigation/resolution. Actual localhost API/Mongo checks cover that path, policy edits and replay. These repairs do not establish production failover, real provider/source compatibility, migration, tested capacity, notifications or independent customer activation. [VALIDATION.md](VALIDATION.md) records evidence and limits; the full launch gates remain open.

R1-03 now removes incident summary truncation, uses UTC calendar days including today, reports invalid-date coverage and separates failed incident-list reads from empty results. [SUMMARIES.md](SUMMARIES.md) records the contract agreed before code; query/index deployment and legacy-conversion load still require validation at the advertised capacity.

The R2 access foundation adds named OIDC sessions, configured owner/operator/viewer roles, fixed binding, CSRF/Origin and transactional action audit under [IDENTITY.md](IDENTITY.md). Direct numeric capture now adds owner-managed scoped write-only keys, strict application JSON intake, atomic receipts/inbox work and the existing ledger/detectors without Langfuse. [CAPTURE.md](CAPTURE.md) records the bounded contract. Local shared-key compatibility remains for Langfuse development under [ACCESS.md](ACCESS.md). Protocol/API, actual local Mongo race/rollback and loopback HTTP checks provide bounded evidence. Actual provider/TLS operation, membership administration, managed instrumentation and privacy lifecycle remain open. Successful access, a test handshake or a receipt does not establish completed monitoring or customer activation; no complete launch gate is closed by this slice.

## Gate A: before any external customer data

The [direct/OIDC package](../deploy/guardian/README.md) now supplies the application image definition, role supervision, secret-file configuration, transactional initialization, same-origin static serving and separate readiness. Local native/browser acceptance is distinct from actual Linux image execution and public TLS/IdP verification. Require those deployed checks and production restore/retention/offboarding evidence; packaging alone does not close this gate.

- [ ] R0-02 historical credential revocation/replacement confirmed without exposing values; secret scans reviewed.
- [ ] Selected capture/deployment model, region, costs and data-handling responsibilities approved by the responsible product/operator owners; backing-service provisioning and terms verified where that mode uses one.
- [ ] Named-user access, scoped ingestion credentials, safe content defaults and customer-isolated deployment verified.
- [ ] Data categories, retention, subprocessors/backing service, disconnect/delete behavior and support contact documented; required agreement/policy review completed by the owner.
- [ ] Production/demo data are separated; test traffic is labelled and cannot pollute customer baselines or invoices.

## Gate B: assisted private beta, after R0-R3

R2-02 now includes Python/Node OpenAI Responses/Chat Completions usage helpers and Setup recipes under [PROVIDERS.md](PROVIDERS.md). Actual SDK objects and JSON/SSE localhost fixtures establish bounded integration behavior, not live-provider or customer activation. Validate the advertised SDK/application deployment, real usage/processing, cancellation and useful incident handling. These adapters do not calculate USD cost; any estimated pricing needs its own provenance and compatibility contract before launch claims rely on it. RAG outcomes, further providers and deployed/image acceptance remain open.

R3-03 now implements one Slack incoming-webhook destination under [NOTIFICATIONS.md](NOTIFICATIONS.md): operator secret configuration, owner test/activation, atomic incident outbox, separate delivery process and recent history. Local Mongo/receiver/browser proof is recorded in [VALIDATION.md](VALIDATION.md). The delivery gate still requires a real configured Slack channel, supervised restarts, external dead-man monitoring, load/retention limits and a customer following setup. Receiver acceptance does not establish human acknowledgement or measured recovery.

Background exporters in [EXPORTING.md](EXPORTING.md) add local queue/flush/retry diagnostics for long-running Python/Node servers. Verify these with the advertised application runtime and shutdown behavior. In-memory admission is not durable across process loss, and an unconfirmed event may already have committed at Guardian. Generic call/stream helpers do not close the provider integration, RAG semantics or activation gates below.

| Area | Required proof |
|---|---|
| No-telemetry activation | A developer without a Langfuse account completes the supported integration and reaches real attributed traffic, an enabled policy and verified destination; record manual assistance and distinguish native JSON from future managed instrumentation |
| BYO activation | Existing project imports safely and shows capabilities/missing fields and source health |
| Source compatibility | Native export recipes tested in actual advertised customer runtimes; for Langfuse mode, default v2 reader/modern exporter verified against the source/version matrix and explicit legacy mode has a tested cutover/rollback path |
| Coverage | Python, JS/TS and one RAG path exercised on tested versions; concurrent runs, streaming/retries and export failure covered |
| Correctness | No loss/double count in replay, duplicate pages, page failure, delayed observations, supported revisions and restart/concurrent-owner scenarios; v4 immutable-ID conflicts quarantined without inventing revision order |
| Accounting | Source/ledger/rollups reconcile within declared currency rounding; unknown prices/default scalar zeros and excluded costs visible; cached/reasoning/custom usage buckets do not double-count |
| Completeness | >100 live/>500 ingestion and >1,000 open/>10,000 dated incident cases; UTC today and boundaries correct; invalid-date coverage visible; capped/partial data never represented as complete; outages beyond replay horizon show a gap |
| Detection | Absolute/relative budget and reliability policies tested on normal, spike, volume-growth, recovered-retry, low-data and expected-change cases |
| Incident loop | Distinct evidence retained; grouping, owner, acknowledge/snooze/dismiss/resolve/reopen and audit tested |
| Delivery | Failure, rate limits, retry/exhaustion and ambiguous responses exercised; delivery history and dead-man monitoring available |
| Recovery | Explicit post-change comparison and insufficient-traffic state; manual resolve does not claim measured recovery |
| Privacy/access | Actual OIDC provider/TLS deployment, fixed binding and configured role lifecycle verified; content canaries absent by default; viewer cannot mutate; revoked sessions/ingestion credentials fail; caches/logs/exports preserve scope |
| UX | Verified named/local entry, safe deep-link return, transient retry, expiry and replacement races, confirmed logout and logout-failure recovery; setup distinguishes configuration from observed progress; incident error states, UTC summaries, bounded run history, keyboard and small-screen journey |
| Operations | Transaction-capable Mongo deployment, Guardian packaging/startup, database indexes, legacy ledger cutover, readiness, backup/restore, rollback and offboarding drill |

**Langfuse-mode compatibility deadline:** the default reader now uses HTTPX Observations v2. Explicit `LANGFUSE_READ_API=v1` retains SDK2 for self-hosted v3 or temporary Cloud rollback, with no automatic fallback. Cloud removes legacy reads on **2026-11-16**; self-hosted v4 excludes them. Founder still uses SDK2 ingestion, and older ingestion can take up to 15 minutes to become visible in v2. Modern exporter migration and actual server/availability evidence remain pre-beta R1-01 work for that advertised path. Direct numeric capture constructs no Langfuse client and has its own integration evidence gate. [Contract and primary references](SOURCE_MIGRATION.md).

The v2 worker now reads up to five 100-row pages per poll and resumes its durable fixed query. It accounts for new identities in a 24-hour overlap, including the full initial import window; accepted/quarantined dispositions and continuation commit together. Failed envelopes and out-of-horizon checkpoints cannot silently skip data. V1 retains its complete-read-only 500-row compatibility limit. Beta still requires real source delay/retention and recovery evidence at the advertised load.

All detector work waits for source-window exhaustion. More than 10,000 observations in an hour/agent rebuild or 5,000 earlier baseline observations leaves work pending with degraded health; backlog growth/drain must be measured. Existing incremental aggregates require a verified backup/cutover/reconciliation/rollback path; running the old writer against new ledger totals is unsafe. The live 1,000-observation cap is labelled, and >5,000 hourly buckets returns 422. These bounds do not prove the target capacity below.

Incident summary aggregation has no silent raw-input count cap, but matching/legacy records still cost database work. A two-second aggregation execution budget and bounded application wait return 503 on failure; they are not throughput guarantees. Validate index setup privileges/time, historical conversion cost, concurrent dashboard load and operational retry behavior. Invalid timestamps make `/summary` coverage partial and compatibility summary routes unavailable. New writes add BSON dates; no historical mass migration is performed.

V2 requests use 100-row pages, a 15-second traversal budget, five-second network timeouts and an 8 MiB page response cap. Run lookup uses observations only over 1–168 hours, default 168; complete empty results return 200 `not_observed`. Without usable cached data, source failures return run 503 or live 200 with degraded coverage/null statistics; cached fallback stays visibly stale. Context conflicts and whole-workflow outcome/duration stay unknown. Local checks of these boundaries do not establish upstream retention, complete history or production freshness.

An assisted isolated beta may use manual provisioning and invoicing. It may not waive data correctness, privacy, incident delivery or usable investigation. No public signups into an untested shared database.

Setup offers Langfuse diagnostics or direct owner key creation/revocation with separate test/real receipt and worker states. It does not instrument or provision an application. Local Guardian access keys are not provider credentials or scoped ingestion tokens; local disconnection does not revoke that key. OIDC logout revokes its application session and reports failure honestly, but does not revoke project ingestion keys, stop collection or perform provider-wide logout. Named roles and scoped expiring/revocable keys are implemented for an operator-configured isolated project. Actual provider/TLS deployment, member/session administration and the supported no-telemetry activation journey still require customer-path evidence before hosting.

Direct admission is bounded to 100 events/256 KiB, 120 new batches/key/minute, 300 new batches/project/minute, 6,000 submitted events/project/minute and 10,000 pending inbox records. Credential history is bounded to 100 keys with at most 10 active. These rejection thresholds do not establish sustainable capacity. The worker drains at most 500 records/cycle in transactions of 100 and may retain processing backlog. Exact batch replay is idempotent while the key remains authorized; test batches never affect production metrics/incidents. A 202 means receipt only. Validate export failure/retry and timing in actual customer applications, and measure receipt-to-analysis lag separately from application-to-receipt time. Retained inbox, receipt, key and audit history still needs explicit retention/deletion and recovery policy.

OIDC requires same-origin HTTPS frontend/API deployment, the registered fixed callback and secure host cookies; the explicit insecure development exception is loopback-only. Database access must support transactions and authentication TTL indexes. Membership/config changes require consistent process restarts across replicas. Local Mongo proof covers atomic state consumption, deployment binding, audit rollback, concurrent resolution and logout, session rotation and uncertain commit retry. Majority concerns are configured, but these single-node checks do not establish failover or the full account lifecycle. Verify proxy callback-log redaction and production cache/CORS behaviour as part of the deployed gate.

## Gate C: beta usefulness and economics

Run at least three independent applications across SaaS, RAG and agent workflows, for at least 14 days after the loop is usable. Include at least two teams starting without telemetry and one BYO user where feasible; disclose any gap rather than substituting demo traffic.

| Metric | Proposed target / interpretation |
|---|---|
| Setup | Median <=15 minutes to a real attributed workflow on supported stacks; record every participant and amount of assistance |
| Data freshness | p95 <=3 minutes from availability at the selected upstream read API to incident evaluation, within tested load; separately measure app-event-to-upstream latency |
| Notification | p95 <=60 seconds from committed incident event to initial delivery attempt; actual delivery has its own measurement |
| Detector usefulness | >=80% of at least 20 reviewed incident episodes judged actionable; show breakdown, reviewer and labels; extend trial if sample too small |
| Noise | <=2 non-actionable delivered notifications/project/week as an initial target; include repeated/incorrectly grouped messages |
| Regression recall | All explicitly critical injected acceptance scenarios detected; this is scenario coverage, not a general-world recall claim |
| Customer outcome | At least two partners independently investigate and record a useful action; before/after evidence where measurable |
| Retention | Partners continue production traffic and can describe recurring value at the end of the observation window |
| Commercial evidence | At least two explicit paid-pilot/continuation commitments or actual payments; a positive demo reaction is insufficient |
| Unit economics | Measured telemetry/compute/delivery/support cost per project at expected traffic; price/allowance decision includes support time and quota headroom |

Do not manufacture production incidents to meet a sample target. Review labelled replays separately from organic traffic; report the denominator for each. Compare Guardian's usefulness/setup effort with the partner's current process and native alerting.

If noise is high, tune policies and impact grouping before adding detectors. If activation is difficult, improve integration before buying traffic. If outcomes/willingness to pay are weak, revisit the offer before shared-platform expansion.

## Gate D: paid self-service launch

- [ ] R5 isolation tests cover cross-organization/project API IDs, query filters, background jobs, cache keys, telemetry keys, notification destinations, exports and deletion.
- [ ] Tested signup/invite/remove-member/role-change/session-revoke/key-rotate lifecycle; support access is limited and audited.
- [ ] Versioned integrations, quotas, retention, supported regions and service expectations are published accurately.
- [ ] Metering is auditable and idempotent; trial/allowance/overage behavior is visible. If automated billing exists, test webhook signatures/replay, cancellation, failed payment and invoice changes.
- [ ] Pricing, terms/data-handling materials, support ownership and escalation process are ready; no unsupported security or prevention claims.
- [ ] Clean install, backend tests, frontend production build, browser journeys, real database fault tests and relevant dependency/security checks run in release CI.
- [ ] Current adapter, database driver and frontend toolchain support risks are resolved or bounded with an owner/date and a justified release decision.
- [ ] Staged rollout/canary and rollback exercised; backup restore and data deletion tested against managed backing data as well as Guardian.
- [ ] All unresolved P0/P1 findings closed for the advertised scope; remaining P2 items have owner, impact and due date.

## Capacity and operating envelope

Initial load-test candidates: 10,000 observations/day/project, a burst of 1,000 observations/minute, and 10 concurrent dashboard sessions. These are test inputs, not promised capacity. Use a controllable local adapter to stress correctness, then validate representative real-source quota/latency separately. Never load-test a customer's service unexpectedly.

Measure backlog growth/drain, source requests per organization/bucket, ingestion/drop counts, database size, memory, API latency and delivery delay. Publish only the envelope that meets the agreed limits. Source rate limits can dominate throughput; dashboard usage must not starve ingestion.

Proposed beta restore objectives: RPO <=24 hours for non-replayable configuration/incident actions and RTO <=4 hours. Establish actual backup/restore behavior and source retention before adopting these targets. Replayable telemetry is not a substitute for backups of human actions or policies. Runbooks must cover source 429/outage, stalled worker, DB failure, delivery failure, key revocation and deletion racing with queued work.

## Evidence template

For every gate, record: ticket, commit, date, environment/versions, fixture or approved project, command/workflow, expected and observed result, safe artifact link, limitations and owner. Keep live secrets, prompts and personal data out of reports. “Implemented” without evidence leaves the gate open.
