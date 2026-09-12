# Customer monitoring rules

Contract recorded 2026-09-12 before implementation; the local feature and actual API/Mongo acceptance are complete, with results in [VALIDATION.md](VALIDATION.md). This R3-02 slice makes existing captured calls useful from the first observation: a project owner can set an absolute cost or duration limit, choose whether reported call errors create incidents, and inspect the measured value against the saved rule. It uses the existing incident/run/resolve workflow. Notifications, aggregate budgets, workflow outcomes and automated remediation remain separate work.

## Use the feature

1. Sign in as the project owner and open **Setup -> Monitoring rules**.
2. Enter the maximum cost per call in USD and/or maximum duration in milliseconds. Leave a limit blank to disable it. Choose whether reported call errors should create incidents, then save.
3. Run your application's normal instrumented calls. The [Python/Node integration](../examples/native-capture/README.md) must provide observed cost for cost limits; the generic wrapper alone does not infer a price. Check real receipts and worker progress separately from test handshakes.
4. Open **Incidents**, select a finding and compare its observed measurement with the saved threshold/revision. Follow its internal run evidence, investigate the application and mark the incident resolved when appropriate.

Resolution records a human action; it does not prove measured recovery. Rules create incidents in Guardian; destination delivery is not implemented by this feature.

## Product behavior

Setup contains Monitoring rules. Owners of a named project can edit; operators and viewers can read. Local shared-key deployments show the existing defaults read-only. Rules are scoped to the deployment's fixed connection/project; request bodies cannot choose a project. Saving does not claim that capture or the worker is healthy.

The initial rules are `max_call_cost_usd: null`, `max_call_latency_ms: null`, `alert_on_errors: true`. Null disables that absolute limit. Cost is an exact nonnegative USD decimal string using the native event cost bounds (up to nine whole digits and twelve fractional digits); duration is a strict integer from 0 through 86,400,000 milliseconds. A known measurement strictly greater than its limit triggers; equality does not. Zero is a valid limit. Unknown cost/duration/status cannot satisfy a rule. Explicit error status triggers only when error alerts are enabled. A failed call still does not establish a failed workflow or exhausted provider retry.

Existing relative cost/latency checks remain active and labelled separately. An absolute finding takes precedence over the relative finding for the same measured condition; cost and latency remain separate findings. Categories stay `cost_anomaly` and `reliability_anomaly` so current filtering and summaries retain their meaning. Every configured finding records policy revision, observed measurement, threshold and a safe reason in evidence; human-readable evidence appears above the raw detail. Historical incidents remain unchanged.

## API and persistence

`GET /api/guardian/monitoring-policy` returns `{schema_version:1, revision, updated_at, updated_by, rules, can_manage, project}`. Revision zero is the initial policy; its update time/actor are null. `updated_by` is the existing redacted actor shape `{id,name,role}`. `project` is the existing authenticated project shape, or null for local shared-key mode. `rules` contains exactly the three fields above.

`PUT /api/guardian/monitoring-policy` requires named owner access, the exact UI Origin and session CSRF. The body is exactly `{expected_revision, rules}`; revision is a nonnegative integer. Unknown fields, duplicate JSON keys, invalid values, oversized bodies and caller-supplied scope are rejected. Configuration, authority and database failures return fixed safe errors rather than request or driver content. Successful saves increment revision and return the same response shape as GET.

A save reauthenticates and touches session/project authority in the same Mongo transaction as policy compare-and-swap and one redacted before/after audit record. A mismatched revision returns 409 `policy_revision_conflict`; no last-writer overwrite occurs. Lost acknowledgements require read-back; retrying a stale revision cannot create another update. Invalid/corrupt saved configuration returns unavailable, never silently resets to defaults.

## Evaluation and changes

Each accepted observation pins a validated `{revision,rules}` snapshot when its first evaluation begins. Pinning checks the observation version/state, touches the worker lease and serializes against policy saves inside a transaction. A policy saved first is used by subsequent pins; observations already pinned retain their rules through retries. A partially evaluated legacy row retains the initial rules so a new edit cannot mix decisions. Finished historical rows are not reopened or rescored by a save or replay.

The snapshot is numeric configuration only, independent of raw source content. Incident insertion, completed-rule bookkeeping and observation state continue to commit atomically through the existing ledger. Stable rule/finding identity prevents replay from duplicating or reopening incidents. Missing policy storage behaves as revision zero; database failure does not. The first default pin and first owner save serialize on one connection policy document. Immediate cost/duration/error decisions can commit when a relative baseline is unavailable or exceeds its bound; unfinished relative work stays pending instead of being treated as a successful empty baseline.

For direct calls with known duration, compare the canonical start/end timestamps using integer time arithmetic. This prevents floating-point conversion noise from crossing an integer-millisecond limit. Preserve the stored ingestion values and fingerprints so existing event replay remains compatible; unknown duration still remains unknown.

Deploy the policy-capable API and worker together, then the matching frontend. The policy head, observation snapshots and human audit are part of backup/restore and retention scope. An older worker ignores these rules and is not a safe rollback after enabling customer limits. Disabling an absolute limit by saving null affects future unpinned work; it does not delete history or cancel already pinned decisions.

Relative cost detection also needs a bounded response to an explicitly free history: after the existing minimum number of known zero-cost baseline calls, a positive candidate of at least $0.01 is a material transition and is reported with finite evidence. Unknown prices never form a free baseline. Preserve the original regression's expected finding and record the rule-version change; this does not introduce a forecast, invoice or project budget.

## Customer recovery and acceptance

Initial read failure shows rules unavailable. Refresh failure may retain labelled saved values. Background reads never overwrite unsaved edits. A revision conflict or ambiguous save requires a fresh read before another save; errors cannot imply success. Owner loss/session expiry removes editing authority. Show that updates affect calls whose evaluation has not started, that missing prices cannot trigger cost limits, and that notifications/spending enforcement are not configured by this screen.

Acceptance covers strict numeric/schema boundaries, role/CSRF checks, concurrent saves, lost receipt read-back, save/audit rollback, policy-pin versus save ordering, retry with pinned rules, unchanged historical resolution, cold-start limits, known zero versus unknown, exact threshold equality, baseline/free transitions, and test traffic separation. The customer path is save rules -> ingest actual HTTP events -> worker processing -> inspect threshold evidence/run -> resolve. Real Mongo tests establish transaction behavior; frontend/browser tests exercise the interactive path and are labelled separately from deployed customer proof. Results go in [VALIDATION.md](VALIDATION.md); status and next product gaps go in [PLAN.md](PLAN.md) and [PROGRESS.md](PROGRESS.md).
