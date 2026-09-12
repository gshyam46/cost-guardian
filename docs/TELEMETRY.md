# R1 telemetry contract and implementation sequence

Agreed 2026-09-11 before the initial R1 implementation. The shared contract supports default Observations v2 and explicit legacy v1 under [SOURCE_MIGRATION.md](SOURCE_MIGRATION.md). The bounded R1-02 ledger implements durable ingestion under [INGESTION.md](INGESTION.md), superseding the earlier whole-window worker stop. R1-03 now adds incident aggregation/calendar/error-state repairs under [SUMMARIES.md](SUMMARIES.md). Managed backing provisioning and shared-tenant hosting remain unimplemented. R1 stays in progress until its cutover, real-source/database and operating gates pass.

## Slice implemented locally

Native Guardian JSON capture was added on 2026-09-12 under [CAPTURE.md](CAPTURE.md). It accepts allowlisted terminal-call metadata from a fixed authenticated project, uses the existing numeric ledger and reads live/run evidence from that ledger. It requires no Langfuse account. The source polling contracts below continue to apply to Langfuse mode. Direct events supply no raw content or workflow outcome; their observed call status is not answer-quality evidence. Named identity is implemented for an isolated project, while managed provisioning and shared-tenant hosting remain open.

1. One normalization module shared by worker and live reads; stable observation identity, UTC timestamps, revision fingerprint and missing measurement semantics.
2. Bounded live source reads returning complete/partial/failed with safe reason codes, plus v2 worker page results with accepted/quarantined row dispositions and durable continuation.
3. Live summaries aggregate every accepted observation in the bounded read, then separately limit the visible feed. Partial, failed, stale and unknown-price states remain visible in API and UI.
4. Detector/rollup consumers handle unknown numeric values. Synchronous source calls run outside the async API/worker event loop. Authenticated monitoring exposes stalled reads and durable processing work.
5. Transactional observation identity, fixed-window continuation, 24-hour overlap, conflict quarantine, rebuilt buckets and atomic insert-only incident identity. Initial import accounts for the full requested window; source and processing watermarks remain separate.

R1-02 is implemented as a bounded local slice, with verification boundaries recorded in [VALIDATION.md](VALIDATION.md). The ledger writer refuses to mix with existing incremental aggregates; automated cutover, backup/rollback and high-volume recovery remain open. R3-02 still owns the zero-baseline materiality policy.

## Normalized observation

`TraceMetric` remains the compatibility type for detectors. Its cost, tokens and latency can now be absent. The normalizer accepts dictionaries and SDK objects and emits a result with a metric or an invalid disposition plus safe issue codes.

| Field | Contract |
|---|---|
| observation_id, trace_id | Nonempty source identifiers required for accepted source rows; no generated fallback identity |
| source, observation_kind | Explicit source and kind; current polling support is Langfuse GENERATION |
| timestamp | Valid timezone-aware source start time normalized to UTC; never substitute current time |
| ended_at, updated_at, completion_state | Source timing/completion evidence when supplied; missing evidence remains unknown |
| status | Observation-level success/error/unknown; never a business workflow outcome |
| cost_usd, total_tokens, latency_ms | Optional finite nonnegative values; tokens must be whole numbers; bool/NaN/infinity/invalid negatives are not measurements |
| cost_usd_decimal | Decimal representation of the input supplied to the normalizer; an SDK-parsed float cannot recover original wire precision. Current float fields are compatibility/presentation values, not invoice precision |
| input_tokens, output_tokens | Optional components; derive a total only from sufficient supplied components; preserve explicit zero |
| revision | Fingerprint of normalized identity, numeric, status and timing fields; raw content excluded; not a provider revision sequence |
| project_id, environment, parent_observation_id | Optional attribution; source metadata is not an authenticated tenant boundary |
| normalization_issues | Safe codes only; no raw payload, prompt, output, provider message or secret in diagnostics |

Empty modern usage fields must not hide populated legacy usage. V2 projection first applies its authoritative detail-map contract. Missing/invalid optional measurements leave a valid observation with unknown values and issue codes, subject to the source's invalid/contradictory measurement checks. Missing identity or invalid start time rejects the observation. Live whole-window reads expose partial coverage; a valid v2 worker envelope can commit a content-free rejected-row disposition and continue. A malformed envelope cannot advance. Existing output previews/PII processing remain a separately documented R2 privacy limitation; the durable ledger excludes those raw fields.

## Bounded source result

`fetch_generations(since, until=None, limit=500, trace_id=None)` returns `SourceReadResult` with `metrics`, `status`, `fetched_at`, query bounds, page/record/invalid/duplicate counts, safe issues/reason and `api_version`. Legacy `next_page` and opaque v2 `next_cursor` are internal traversal hints; browser coverage exposes only continuation availability for v2.

- Use one fixed page size throughout a traversal, at most 100; shrinking the last request changes offset pagination and can repeat/skip observations.
- Keep the same UTC lower and upper bounds on every page. Bound total rows/pages and SDK request time/retries. No unbounded source scan from an API request.
- Successful exhaustion means complete traversal of that bounded source query. Missing credentials or a failed first read means failed; a later failure, reached cap, invalid row or repeated/conflicting identity means partial unless exhaustion can be established safely.
- Deduplicate source observation IDs within a read and expose repeated/conflicting data. Do not imply the legacy offset API is a stable snapshot while observations are being inserted or revised.
- Legacy `next_page` is an offset traversal hint, not a durable ingestion checkpoint. The v2 worker uses the page contract below to persist opaque continuation and row dispositions atomically.
- V2 follows `meta.cursor` until absent/null in valid metadata; a short page with a cursor is not exhausted. Repeated/malformed cursors, missing metadata and empty non-progressing pages cannot complete successfully. Current v2 identities combine trace and observation IDs within the configured source project.
- Keep the older list-returning helper only for explicit compatibility callers. Worker/live use typed results so they cannot confuse errors with an empty successful read.

The v2 worker pins query bounds, API/normalization version and page size, reads at most five 100-row pages per poll and resumes its stored cursor on the next poll. Each page transaction commits accepted/quarantined dispositions, ledger changes, processing work and continuation together. The source checkpoint advances only after terminal-page persistence; failures cannot skip an uncommitted page. Query-fingerprint mismatch blocks for explicit reconciliation. An upstream-invalid cursor can restart the same fixed window once, relying on identity deduplication. Explicit v1 retains a 500-row whole-window limit and writes nothing on incomplete reads.

Every new traversal rereads the preceding 24 hours and accounts for new identities, including baseline history on initial import. Late observations inside that horizon are captured once; unlimited lateness, mutable legacy revision ordering and history beyond upstream retention are not established. All detector work waits until source-window exhaustion so descending pagination cannot hide an earlier baseline on a later page. Rebuilds over 10,000 observations per hour/agent bucket and baselines over 5,000 earlier observations remain pending with degraded health. [INGESTION.md](INGESTION.md) owns transaction, privacy, conflict and recovery details.

If the saved checkpoint has fallen outside the 24-hour query horizon, the worker stops with `checkpoint_outside_window` and preserves that checkpoint. It cannot call a newer bounded window successful recovery for the missing history. Operators must wait for or use a separately verified backfill/reconciliation path; this slice provides no automatic reset that would discard the gap.

## Compatibility deadline

Guardian now defaults to Observations v2 through HTTPX and reconstructs observed runs without trace-list/get calls. `LANGFUSE_READ_API=v1` explicitly selects the legacy SDK2 reader for self-hosted v3/temporary compatibility; it is never an automatic fallback. Cloud legacy reads retire on **2026-11-16** and self-hosted v4 removes them. Local wire tests pass; real server/exporter compatibility still gates beta. Founder remains on the old exporter. The ledger's overlap handles bounded delayed fixtures, but actual exporter availability and retention need live evidence. [Migration guide](https://langfuse.com/faq/all/deprecated-api-migration), [server version compatibility](https://langfuse.com/self-hosting/upgrade/versioning).

## API and UI behavior

Live reads initially allow at most 1,000 observations per window; the feed remains separately limited. Responses include query bounds, read status, observed/invalid/duplicate counts, safe reason, cap and fetched time. A complete traversal does not mean all delayed telemetry has arrived. Partial observations are labelled observed results, never a full-window total.

Run queries default to the last 168 hours and accept 1-168 hours. A complete empty query returns `observation_state=not_observed`; a partial empty query is `undetermined`. Neither proves global trace absence or known zero spend. Source failure remains unavailable. Trace names/user/session/tags come only from consistent observation context; workflow duration/outcome remain unknown. Source retention can shorten accessible history even when traversal is complete.

Unknown per-call cost/tokens/latency serialize as null. Where any constituent cost or token value is unknown, its total is null and a separately labelled known subtotal/count remains available. Latency summaries use known measurements with a denominator. Run summaries describe observed child calls; workflow outcome stays unknown without explicit application evidence.

Cache storage is bounded. Freshness and retention use a monotonic clock; public timestamps retain source UTC time. A failed refresh may serve a previously valid result marked stale with its original fetched time and coverage; after the stale retention limit it becomes unavailable. A cold failure does not synthesize a zero-valued successful summary. Source failure when fetching a run returns unavailable, distinct from a confirmed missing run.

Ledger-derived hourly rollups expose known/unknown measurements and conflict counts with `accounting_status=ledger-1`. A rebuild replaces the affected bucket atomically with dirty-work completion. This describes captured observations, not settled upstream history or invoice accuracy. Existing incremental rows remain legacy/provisional and block unsafe writer cutover. They cannot establish observation identity or historical coverage retroactively; no automatic reset, deletion or migration is supplied.

Bound API parameters: live/metric windows 1-168 hours, visible runs 1-100, visible calls 1-100, incident page size 1-500, incident trend days 1-90. The legacy metrics endpoint refuses windows containing over 5,000 hourly agent buckets instead of silently truncating them. Its later scalable aggregate/pagination design remains R1-03.

Incident counts are separate from source telemetry completeness. `/api/guardian/summary` aggregates all matching incidents into bounded category/day groups; the prior 1,000-open/10,000-trend caps are removed. UTC calendar days include today and use one half-open request cutoff at BSON millisecond precision. New incident writes carry an indexed BSON date alongside public ISO time; legacy aware dates convert server-side without rewriting history. Missing/invalid/naive dates remain partial coverage. Old summary routes return 503 when their shapes cannot represent that incompleteness, and all query failures/timeouts remain unavailable. An empty incident chart is not evidence of healthy monitored traffic. Query/index deployment and legacy scan/load limits are detailed in [SUMMARIES.md](SUMMARIES.md).

Incident lists expose retry and distinguish failed initial reads from successful empty results. Failed refresh may retain labelled rows only for the same filter; request cancellation prevents previous filters from overwriting current results. These UI repairs do not establish the full incident-to-action customer journey.

Finite individual numbers can still overflow aggregate storage/display ranges. Such public totals are null with an explicit `aggregate_issues` code rather than infinity or a rounded integer disguised as exact. The ledger retains exact source cost text and out-of-range integer totals for later reconciliation; the current numeric API remains an operational view. Browser counts outside the safe integer range are labelled out of display range. Old increment storage cannot retroactively reconstruct missing identity or exact measurements.

`GET /api/guardian/monitoring` uses Guardian authentication and reports source configuration, last attempt, source progress, processing state, pending work and safe reasons. It is monitoring evidence, separate from unauthenticated API liveness. A completed source query does not imply completed bucket or detector work; a timestamp must make a stopped worker visible rather than treating its last status as current health. Worker health writes use the connection fence so a stale owner cannot overwrite replacement-worker state.

The API and worker each bound blocking source work to four executor slots. Caller cancellation or a 20-second wait timeout does not release a slot until the physical SDK work ends. SDK requests have explicit timeouts and no automatic retries; threads cannot be forcibly terminated. This protects the event loop and bounds queued work, but does not coordinate capacity across processes or replace source quota management. Live browser requests abort on query changes, have a 25-second timeout, and do not stack interval requests for the same query.

## Acceptance and remaining gates

Required local cases: >100 live and >500 ingested observations, fixed page size, exact-cap exhaustion vs unknown remainder, page failure/restart, accepted/quarantined row coverage, zero vs unknown measurements, malformed numeric values, duplicate/conflicting IDs, unchanged progress on failed envelopes, API responsiveness during blocked source work, stale cache and unknown-safe frontend rendering. Ledger checks additionally cover late arrivals, atomic materialization, lease takeover, pending-work recovery, safe PII persistence, cross-page baselines and resolution-preserving replay.

All seven original assertions now pass, including the known-zero-baseline policy repair. [POLICIES.md](POLICIES.md) adds configurable absolute limits and a pinned first-evaluation revision without changing telemetry wire identity. Mock HTTP transports exercise v1 SDK/v2 REST wiring; mock persistence does not establish transactions. Real localhost replica-set evidence is recorded separately in [VALIDATION.md](VALIDATION.md), alongside browser results and remaining limitations. Live compatibility, quotas, production recovery and customer activation remain open.

Deploy the matching API, worker and frontend together only after validation. Mongo replica-set transactions are mandatory for the ledger writer. Existing aggregates require an explicit clean database/cutover decision and retained backup evidence; automated migration and rollback remain unfinished. Running the old incremental writer against new ledger-derived totals would break accounting, so code rollback alone is not a safe data rollback. Deployment is not part of this local slice.
