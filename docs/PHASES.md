# Cost Guardian: phase status

Updated 2026-09-12. **Canonical IDs: R0-R6.** The older numbered phases are preserved in [archive](archive/2026-09-09/PHASES.md) and are not active implementation tracking.

Status values: planned, in progress, implemented awaiting verification, verified, blocked. A phase is verified only after its exit gate passes. There is no aggregate completion percentage.

| Phase | Intended outcome | Current status | Exit gate |
|---|---|---|---|
| Review baseline | Expert review, decisions, architecture and implementation plan | Verified: documentation review only | Current review, founder requirement and evidence recorded |
| R0 | Reproducible baseline, credential closure and managed-capture decision | In progress: R0-01 implementation | R0-01 through R0-03 evidence recorded; no unresolved credential exposure before external use |
| R1 | Trustworthy ingestion, counts/costs and monitoring health | In progress: bounded ledger, source/live contract and incident summary repairs implemented locally | No silent loss/double count in fault suite; complete/partial/unknown distinguished; migration and operating limits verified |
| R2 | Safe onboarding without observability; BYO alternative | In progress: access/setup and isolated OIDC/session/role foundation implemented locally; scoped keys/native numeric capture implemented locally; managed backing/OTLP still planned | Both journeys with real data; supported Python/JS paths; role/privacy/lifecycle checks |
| R3 | Useful incident-to-action-to-recovery loop | In progress: configurable first-call rules, threshold evidence and durable Slack delivery implemented locally | Grouped evidence, delivery/retry, lifecycle, policies and recovery checks pass |
| R4 | Assisted beta and operating validation | In progress: direct/OIDC packaging and operator runbook implemented; partner beta and operational release proof remain open | Three independent apps, minimum observation window, usefulness/operations evidence |
| R5 | Paid self-service launch | Planned | LAUNCH shared-hosting/lifecycle/economics/rollout gates met |
| R6 | Expansion and research | Deferred | Retained customer demand plus separate evaluation |

## Ticket completion

R3-02 current continuation: owner-managed per-call cost/latency limits and reported-error control, immutable evaluated rule revisions, and readable incident evidence are implemented locally under [POLICIES.md](POLICIES.md). Actual localhost API/Mongo acceptance covers saved rules -> intake -> worker finding -> evidence/run -> resolution, followed by policy edit/replay without reopening history. Slack delivery is implemented under [NOTIFICATIONS.md](NOTIFICATIONS.md); deployed channel acceptance, aggregate budgets, evaluated noise/recall and measured recovery remain open.

R2-02 continuation: background export and explicit call/stream lifecycle helpers under [EXPORTING.md](EXPORTING.md) now include Python/Node OpenAI Responses and Chat Completions usage adapters and Setup recipes under [PROVIDERS.md](PROVIDERS.md). Bounded failure tests and actual SDK/localhost API/Mongo evidence belong in [VALIDATION.md](VALIDATION.md). Pricing provenance, further provider/RAG adapters, image/deployed acceptance, provisioning and real activation remain open; this does not close R2.

**R0-01: implemented, offline verification passed locally; live integration and hosted workflow verification pending.** See [VALIDATION.md](VALIDATION.md). R0 stays in progress: R0-02 credential closure and R0-03 discovery/provisioning are still open. Existing prototype components do not automatically close these tickets.

- R0: R0-01 baseline/harness/CI; R0-02 credential closure; R0-03 discovery/provisioning/schema.
- R1: R1-01, R1-02 and R1-03 in progress. R1-02's bounded ledger follows [INGESTION.md](INGESTION.md). R1-03 summary/calendar/error-state implementation now follows the contract recorded before code in [SUMMARIES.md](SUMMARIES.md). Local evidence is recorded in [VALIDATION.md](VALIDATION.md); recovery and operating gates remain open.
- R2: R2-01 isolated-project OIDC/session/role foundation implemented locally under [IDENTITY.md](IDENTITY.md); scoped credentials and native numeric capture are implemented locally under [CAPTURE.md](CAPTURE.md). Membership/session administration and deployed provider acceptance remain open; R2-02 now includes tested Python/Node background exporters and explicit OpenAI call/stream usage helpers. OTLP, backing provisioning and additional provider/framework adapters remain planned. R2-03 access/setup recovery prerequisite is implemented locally under [ACCESS.md](ACCESS.md), with BYO provisioning/privacy acceptance still open. Local verification does not close the real onboarding gate.
- R3: R3-02 per-call policy setup and pinned threshold evidence, plus R3-03 durable Slack delivery/test/activation/history are implemented locally. Budgets/rates and broader evaluation remain open. R3-01 lifecycle, R3-04 recovery/value and deployed delivery/operating evidence remain unfinished.
- R4: R4-01 partner beta remains open. R4-02 started early to enable R2: direct/OIDC packaging, same-origin UI/API, transactional bootstrap, readiness and operator commands are implemented under [DEPLOYMENT.md](DEPLOYMENT.md). Native/browser evidence, image execution and deployed TLS/IdP acceptance are tracked separately; restore, load, retention/offboarding and operating drills remain open.
- R5: R5-01 isolation/self-service; R5-02 commercial lifecycle; R5-03 rollout.
- R6: R6-01 demand-led expansion.

R1-01's shared normalization and default Observations v2 reader are implemented under [SOURCE_MIGRATION.md](SOURCE_MIGRATION.md); actual server/exporter compatibility remains required before beta. Legacy Cloud interfaces expire on 2026-11-16. R1-03 now adds complete incident-count aggregation, UTC calendar windows including today, explicit historical date coverage and incident-list failure/retry states to its existing live/API/UI work. Local results are in [VALIDATION.md](VALIDATION.md). Legacy conversion cost, query/index deployment, metric-query scaling and production operating validation remain open; R1-03 is not marked verified as a whole.

All seven original regression assertions now pass, including the known-zero-baseline cost transition. Their original expected outcomes were retained; the final expected-failure marker was removed after the policy repair passed. This does not close the broader operating, integration or incident-response gates.

R1-02 now commits source-page dispositions, ledger records and pending work atomically under a connection lease, resumes bounded v2 pages, rebuilds affected buckets and inserts stable incidents without reopening resolved ones. Initial import accounts for the full requested 24 hours. R1-02 remains in progress: automated legacy cutover and backup/rollback, real source delay, high-volume baseline/rebuild behavior, retention and load evidence are unfinished. A local single-node transaction test cannot close production failover or durability requirements.

Change a ticket's status here when work starts; add dated evidence in VALIDATION and link it. Do not create parallel status tables with different phase numbers. [PLAN.md](PLAN.md) contains ticket detail and dependencies.
