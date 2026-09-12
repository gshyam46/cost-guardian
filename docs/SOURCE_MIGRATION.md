# R1-01: supported source read migration

Agreed 2026-09-11 before implementation; local verification is recorded in [VALIDATION.md](VALIDATION.md). The default reader uses Langfuse Observations API v2 while preserving the shared measurement/failure contract. Subsequent bounded replay, late-arrival and durable page work is implemented under [INGESTION.md](INGESTION.md). Actual source/exporter compatibility, operating recovery and managed onboarding remain open.

## Decision

Use `GET /api/public/v2/observations` through existing HTTPX; Guardian needs no tracing/export SDK for this read-only path. Keep the existing v1 adapter behind explicit `LANGFUSE_READ_API=v1` for self-hosted v3 and temporary rollback. Default to `v2`; never automatically fall back after an endpoint/authentication/timeout failure. Invalid configuration fails visibly.

| Selection | Intended source | Evidence required |
|---|---|---|
| `v2` default | Langfuse Cloud Observations v2 / self-hosted v4+ | Mock HTTP contract and dedicated live source/server checks |
| `v1` explicit legacy | Self-hosted v3; temporary Cloud compatibility | Existing SDK2 regressions, tested server and cutover plan |

Cloud legacy reads retire on 2026-11-16; self-hosted v4 removes them. Upgrading an exporter SDK alone does not migrate reads. [Migration guide](https://langfuse.com/faq/all/deprecated-api-migration), [Observations API](https://langfuse.com/docs/api-and-data-platform/features/observations-api).

## Contract

- Request `core,basic,time,model,usage,metrics,trace_context,io` explicitly. Existing output previews/PII still process content; default content exclusion remains R2.
- Fix UTC bounds/filters. Keep 100 rows per page. Live reads retain their 1,000-row bound; the v2 worker now persists up to five pages per poll and resumes its fixed query in later polls.
- Follow opaque `meta.cursor` until absent/null. Short pages with cursors are not exhausted. Reject malformed/repeated cursors, missing metadata, oversized pages, non-progressing empty pages and rows outside query scope.
- Keep continuation tokens internal. Do not expose raw cursors in browser responses/logs/diagnostics. A token alone is not durable progress; R1-02 commits it with row dispositions and downstream work.
- Disable automatic retries/redirects and ambient proxy/credential lookup. Bound network/traversal time and response bytes; return safe error codes without provider bodies or URLs.
- Preserve identity, missingness, duplicate/conflict diagnostics and checkpoint protection. Live/legacy incomplete reads remain partial; v2 worker pages separately require a valid envelope and one durable accepted/quarantined disposition per source row.

Present v2 usage/cost detail maps are authoritative, including empty/partial maps. Converter-generated scalar defaults cannot fill missing evidence; explicit detail zero remains known zero. Positive aggregate fallback is allowed only when the corresponding detail map is absent. Exclusive cached-input/reasoning-output buckets are included without falsely declaring a token inconsistency. Custom buckets must reconcile before relaxing ordinary input/output equality. Raw numeric JSON is parsed as Decimal before normalization; exact cost text is retained in the ledger, but the operational numeric API does not claim invoice accuracy.

Contradictory totals are unknown, with an inconsistent-measurement issue and partial read; they cannot become known free usage/spend. Token totals use exact integer consistency. Cost totals are checked against fully known input/output and supplied exclusive buckets with relative tolerance `1e-12`, absolute tolerance zero; zero-versus-positive disagreements are never tolerated. Incomplete/invalid extra buckets cannot disappear through generic input-plus-output fallback. Valid components remain independently available when a total is unknown.

Response bodies request identity encoding and reject non-identity content encoding before decompression. Accepted body size is capped at 8 MiB per page, traversal time at 15 seconds and each network stage at five seconds or the remaining deadline. Actual reads are also capped at `ceil(row_limit / page_size)` pages; short pages with continuation can therefore stop with `page_limit_reached`. Cursor length is capped at 8,192 characters. HTTPX request logs redact the v2 host/query while preserving method/status. Monitoring exposes the selected API; an API/worker version mismatch cannot report healthy ingestion.

## Live and run views

Remove legacy trace-list/get calls in both modes. Group normalized generations by trace ID using observation trace context where available. Do not invent workflow success, root input/output or whole-run duration from child calls.

Run lookup uses a bounded window: default seven days, maximum seven days. Remove the 1970-to-now query. A complete empty result means no generation calls observed in the accessible window, not proof of global trace absence. API/UI must distinguish this from source failure and show the query bounds. Source retention may shorten accessible history; a complete traversal is not a settled/full-history claim.

## Availability and remaining gates

Older exporters without the v4 ingestion contract can take up to 15 minutes to appear in v2. Founder still uses SDK2; its migration and real modern-exporter evidence remain open. Its short live harness timeout cannot certify v2 availability. [Availability requirements](https://langfuse.com/docs/api-and-data-platform/features/observations-api).

The reader migration alone did not repair start-time filtering or replay increments. The subsequent R1-02 implementation now uses stable identities, durable page/quarantine work, fenced transactions and bucket replacement, with 24-hour overlap. Initial import accounts for the full requested window. Source settlement, history beyond that horizon, automated legacy cutover and production load/recovery remain open. The compatibility matrix describes intended targets, not verified live environments.

V4 observations are immutable after ingestion; resending an ID is not an authoritative revision update and can create duplicates. The ledger treats identical fingerprints as replay and quarantines changed copies in both modes until authoritative legacy revision ordering is verified. It never automatically selects the greatest updated timestamp. Identity includes connection/source/project scope, trace ID and observation ID. [Observation update semantics](https://langfuse.com/faq/all/tracing-data-updates).

## Acceptance and rollback

Verify exact path/query/auth; no deprecated default-mode calls; multiple pages; short page with cursor; terminal empty results; exact cap with/without cursor; cursor cycles/duplicate IDs; malformed/oversized responses; auth/rate/unsupported/timeout failures; unchanged checkpoints; trace context; bounded absence UI; no cursor/secret diagnostics. Retain explicit v1 regressions and run backend/frontend/offline HTTP checks.

A source-mode rollback may select v1 only where supported. It must preserve the connection identity; changing an active traversal's query/API/normalization contract blocks for explicit reconciliation. An invalid cursor may restart the same fixed query once, without changing its fingerprint. No data deletion, checkpoint reset or deployment is included. Matching API/worker/frontend changes deploy together. The ledger also requires a verified data cutover/rollback path: restoring an old incremental writer against ledger totals is unsafe.
