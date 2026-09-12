# Notifications: R3-03 delivery contract

Recorded before implementation on 2026-09-12. This slice connects a newly detected incident to a Slack channel, then back to its evidence and resolution in Guardian. It applies to direct capture and Langfuse ingestion. It is an isolated-deployment feature, not shared tenancy or a Slack app installation marketplace.

## Customer workflow

1. The deployment operator creates a Slack incoming webhook and sets `GUARDIAN_SLACK_WEBHOOK_URL` in the API, ingestion worker and delivery worker environments. The URL is a secret; it never appears in Mongo, API responses, browser storage, audit records or logs.
2. A named project owner opens Setup → Notifications and selects Send test. This queues a durable, explicitly labelled test message; it does not enable incident delivery. Retesting the same destination preserves existing activation; testing a changed destination clears its prior verification/activation and cancels old queued work.
3. A separate `python -m notifications.worker` process delivers the test. The owner refreshes status and enables notifications after Slack has accepted the test for the current destination. Other project members can inspect status/history.
4. Each newly inserted incident creates one delivery record in the incident transaction. The message contains a fixed category/severity, opaque incident/delivery identifiers and a link to Guardian. It excludes source content, prompts, outputs, evidence, customer labels and arbitrary incident titles/summaries.
5. Setup shows recent delivery results and worker health. Incident detail shows its recent delivery history. Owners can retry eligible exhausted/failed/unconfirmed deliveries, with an explicit warning that an unconfirmed attempt may already have reached Slack.

## Scope and security

- One Slack destination per existing organization/project/environment/connection binding. Named OIDC owner actions require current session, exact Origin and CSRF, rechecked and touched inside the Mongo transaction with an audit record. Local shared-key mode is read-only and cannot activate delivery.
- Production URLs must match HTTPS `hooks.slack.com/services/<segment>/<segment>/<segment>` with no credentials, port, query, fragment, redirects or proxies. GovSlack, generic webhooks, OAuth installation and multiple channels remain separate follow-ups. Tests inject a localhost transport; no environment flag permits arbitrary production webhook hosts.
- The destination identity is an internal SHA-256 of the URL plus the canonical Guardian UI origin. Only that digest is persisted. Changing the webhook or UI origin invalidates verification and activation; old jobs are cancelled rather than silently sent to another destination. Processes must use consistent configuration and restart together.
- Enabling affects new incidents only. Existing/resolved incidents are not backfilled. Disabling prevents new enqueue/claim; queued incident jobs are cancelled. An attempt already admitted before disabling may finish. Test jobs are explicit owner actions and may run while disabled.
- Slack acceptance means HTTP 200 with the expected `ok` body. It does not establish that a person read the alert. Redacted HTTP/network outcome codes are stored, never provider response bodies or exception strings.

## Durable delivery

Incident insertion, the deterministic `incident-created` outbox row and detector completion commit together in the existing ledger transaction. The destination head is touched in that transaction to serialize enable/disable with enqueue. No network operation runs inside a database transaction. Replayed observations and already inserted incidents do not enqueue again.

Collections: `guardian_notification_settings` (one fenced revision head per connection), `guardian_notification_deliveries` (immutable destination/payload identity plus bounded attempt history), and `guardian_notification_commands` (owner request receipts). Owner changes also enter the existing `guardian_identity_audit`. Delivery worker health is stored in `guardian_state` under a notification-specific connection key.

Delivery worker startup creates the due-work and recent-history indexes; its database principal requires index-creation permission on `guardian_notification_deliveries`. Index failure stops startup so supervision must report it. API history reads remain bounded even before the delivery worker starts; they do not create configuration or send requests. External supervision/readiness remains separate from the in-app heartbeat.

One destination lease admits one send at a time and enforces at least one second between admissions. Each admission commits an attempt identifier, epoch and lease deadline before HTTP. Completion checks the same owner/epoch; a late acknowledgement cannot overwrite a replacement worker. A crashed/expired attempt is recorded as unconfirmed before recovery. The HTTP operation has a bounded total deadline shorter than the lease, bounded response reads, no redirects and no automatic HTTP-library retries.

Transient HTTP 429/5xx and network/unconfirmed outcomes retry with bounded backoff; valid `Retry-After` is respected up to the 24-hour cycle deadline. Other HTTP failures stop automatic delivery. After fixing receiver permissions or channel availability, an owner may manually retry a rejected request to the same destination. Invalid internal delivery records cannot be retried through the UI. At most five admitted attempts per cycle, three cycles per delivery, and 15 retained attempt records. A cycle expires after 24 hours. An owner retry is allowed only for a terminal retryable row pinned to the current destination; it starts a new bounded cycle and is audited. Stable request IDs and expected setting revisions prevent duplicate commands after an uncertain acknowledgement.

The queue is capped at 10,000 nonterminal rows per connection. Admission is serialized through the settings head; reaching the cap rolls back incident completion and leaves visible pending monitoring work. This is backpressure, not silent loss. Delivery retention/archival and higher-volume aggregation remain launch work; records are not silently deleted in this slice.

Delivery states: `queued`, `sending`, `retrying`, `accepted`, `failed`, `unconfirmed`, `cancelled`. `last_outcome` is a safe code, and attempt history records start/finish/outcome only. Retries can produce duplicates because Slack incoming webhooks do not provide a receiver deduplication acknowledgement. This is at-least-once delivery, not exactly-once or guaranteed human notification.

## API and interface contract

`GET /api/guardian/notifications` returns the current destination/settings, health and at most 50 recent delivery records; optional `incident_id` filters the history and must identify an existing incident. Reads do not initialize configuration or send messages.

Response fields:

```json
{
  "schema_version": 1, "revision": 0, "project": null, "can_manage": false,
  "updated_at": null,
  "destination": {"channel": "slack", "state": "not_configured", "verified": false, "enabled": false},
  "worker": {"status": "unknown", "last_seen_at": null},
  "deliveries": [], "has_more": false
}
```

Destination states: `not_configured`, `invalid`, `configured`, `changed`. Worker status: `unknown`, `healthy`, `stale`, `blocked` (healthy heartbeat within 30 seconds and matching active binding/destination). Enabled and healthy are separate facts.

Each public delivery has `id`, `incident_id` (null for tests), `kind` (`test`/`incident`), `state`, `created_at`, `updated_at`, `attempt_count`, `cycle`, `next_attempt_at` (nullable), `last_outcome` (nullable), `can_retry`, and `attempts` (at most 15 objects with `number`, `started_at`, `finished_at`, `outcome`). Dates are UTC ISO strings. No payload, lease owner, fingerprint, secret or raw receiver text is returned.

`POST /api/guardian/notifications/actions` accepts strict JSON up to 4 KiB:

```json
{"expected_revision": 0, "request_id": "8fcba456-a0be-440a-9af9-4c57812b260a", "action": "test"}
```

Actions: `test`, `enable`, `disable`, `retry`; only `retry` requires `delivery_id`. Each successful new command increments the settings revision and returns the same complete response as GET (unfiltered). Identical request replay returns current read-back; a changed command under the same ID or stale revision returns 409. A test already pending for the destination is rejected. Enable requires a successful current test; disable works even when destination configuration is missing/invalid. Commands require owner authority at replay time too.

The browser validates project/role/capability and response shape, cancels stale reads on navigation/session changes, and requires fresh read-back after an ambiguous mutation. It labels queued tests and failed reads accurately. History failure does not hide incident evidence. All routes preserve the existing no-store response policy.

## Acceptance and remaining launch evidence

Implemented and verified locally on 2026-09-12: 1,135 backend, 248 frontend and 104 harness tests passed; 33 real Mongo cases (seven delivery plus existing ledger/capture regressions), the production build and 65 browser scenarios passed. [VALIDATION.md](VALIDATION.md) records exact reports, failures found during verification and the limits of this evidence.

Required local evidence: real Mongo incident/outbox atomic rollback and replay; owner/CSRF/CAS/audit rollback; concurrent claims, stale completion and crash recovery; disable/rotation fencing; bounded transient retries and terminal responses; actual localhost HTTP transport with acknowledgement loss and redaction; frontend role/ambiguity/history states; production build and browser desktop/mobile workflow. Tests use synthetic receivers and never send Slack messages.

Deployed Slack acceptance, actual worker supervision/restarts, TLS/OIDC ingress and a customer completing setup remain launch gates. The first channel requires an operator to install a webhook secret; self-service Slack OAuth is deferred explicitly rather than represented as implemented.

Protocol references: [Slack incoming webhooks](https://docs.slack.dev/messaging/sending-messages-using-incoming-webhooks/) defines secret handling and acceptance/errors; [Slack rate limits](https://docs.slack.dev/apis/web-api/rate-limits/) defines pacing and HTTP 429 retry instructions.
