# Scoped credentials and native capture (R2-01/R2-02)

Recorded 2026-09-12 before implementation. This slice gives an operator-configured isolated project a direct path for terminal LLM-call metadata without a Langfuse account. It extends [IDENTITY.md](IDENTITY.md) and reuses the numeric ledger in [INGESTION.md](INGESTION.md). It is Guardian JSON version 1, not OTLP, automatic instrumentation, a provider SDK or full RAG/workflow tracing. The customer must emit one stable event per completed call/attempt. Existing Langfuse reads remain the default. Local implementation and verification are recorded in [VALIDATION.md](VALIDATION.md).

## Deployment and authority

`GUARDIAN_CAPTURE_MODE=langfuse|direct` defaults to `langfuse`; unknown values fail closed. Direct mode requires valid OIDC configuration and its fixed organization/project/environment/connection binding. No dashboard API-key credential may create ingestion credentials or submit events. Direct mode constructs no Langfuse client and uses only its configured database. A capture binding in `guardian_state` pins source mode and identity binding before key issuance/intake/processing. Langfuse workers also claim/touch this same record transactionally before source work and on page writes, so competing initially empty deployments cannot both win. Existing Langfuse observations, rollups, active polling state or incompatible ledger configuration refuse a direct binding. Existing direct binding must refuse a Langfuse worker/read deployment. Changing modes requires an explicit new isolated database or future migration; no automatic reset or reassignment.

Credential management is available only in direct OIDC mode. All named roles can inspect redacted capture state/credential metadata; only a current owner can create/revoke keys. Retain the existing `/access` permission arrays and use its verified actor role for this narrower control; server-side owner checks are independent of `resolve_incidents`. Every mutation requires exact UI Origin and session CSRF, then rechecks/touches session, identity/capture binding and owner role inside the same transaction as credential/audit writes.

Keys are write-only bearer secrets in `X-Guardian-Ingest-Key`, with format `cg_ingest_<32 lowercase hex public id>_<43 URL-safe random characters>`. Persist a SHA-256 digest of the complete secret, never plaintext. Expiry/revocation is explicit on every request; do not rely on TTL or process caches. Keys belong to the fixed project and survive logout or removal of their creator. Revoke project keys explicitly. Successful intake rechecks/touches the credential in its durable transaction; revocation conflicts with that write. Already accepted events may finish processing after revocation.

## APIs

All paths below are prefixed `/api/guardian`; responses are noncacheable. Errors contain fixed safe code/message only, without submitted values, credentials or raw validation bodies.

- `GET /capture`: authenticated settings/status. Response `{mode, enabled, schema_version:1, collector_path:"/api/guardian/ingest/events", can_manage_keys, project, limits, status}`. `enabled` means direct OIDC configuration/binding is usable, not monitoring activation. `project` is the same fixed project object as named access or null in legacy mode. `limits` is `{max_batch_events:100,max_body_bytes:262144,max_active_keys:10,max_keys:100}`. `status` is null in Langfuse mode; in direct mode it is `{last_test_received_at,last_received_at,received_events,pending_events,processed_events,last_processed_at,conflicted_events,worker_status}`. All timestamps are aware UTC strings or null. Counters describe accepted native traffic; unavailable state returns 503, never zero. `worker_status` distinguishes not_started, current and stale from the direct worker heartbeat; no active/healthy customer claim.
- `GET /ingestion-keys`: named direct-mode read; `{credentials:[...]}` includes all retained metadata, capped by the hard 100-key project limit, with no silent pagination loss. Metadata is `{id,label,prefix,status,created_at,expires_at,revoked_at,last_used_at}`; status active/expired/revoked is computed at read time. Prefix is a public identifier label, not a disclosed portion of secret entropy.
- `POST /ingestion-keys`: owner+CSRF. Body `{request_id:<UUID>,label:<1..80 printable nonblank characters>,expires_in_days:<1..90 integer>}`. Response 201 `{credential:<metadata>,token:<one-time secret>}`. At most 10 active and 100 retained credentials per project. A repeated request ID returns 409 with a safe already-created code, never another secret or a second key. An ambiguous/lost response requires list, revoke the orphan and create with a new request ID. No automatic create retry in the UI.
- `POST /ingestion-keys/{id}/revoke`: owner+CSRF; response 200 `{credential:<metadata>}`. Repeated revoke preserves the original time and creates no second audit. Unknown key 404. Expired metadata remains visible. Create/revoke actions insert deterministic redacted actor/project audits in the same transaction.
- `POST /ingest/events`: machine credential only; dashboard cookies, API keys and Authorization headers do not substitute. Body is the strict envelope below. Response 202 `{batch_id,received,duplicate,conflict_candidates,test_mode,replayed,processing:"queued"|"test_only"}` after a majority-committed transaction. This acknowledges durable receipt, not completed detection, export completeness or invoice accuracy. Exact same batch/body can retry with the same receipt; changed content under the same batch ID returns 409. Invalid batch 400, unsupported content type 415, encoding/size 413, expired/revoked/malformed key 401, admission 429, unavailable/mismatched mode/binding 503. Authenticate before reading the body and recheck authority before committing it.

## Event contract and privacy

```json
{
  "schema_version": 1,
  "batch_id": "38aca0cb-e357-4e16-a314-ef031ae4c33d",
  "test_mode": false,
  "events": [{
    "observation_id": "call-unique-attempt-id",
    "trace_id": "workflow-unique-id",
    "agent_name": "answer-generator",
    "model": "provider/model-name",
    "started_at": "2026-09-12T10:00:00Z",
    "ended_at": "2026-09-12T10:00:01Z",
    "status": "success",
    "cost_usd": "0.0025",
    "input_tokens": 100,
    "output_tokens": 20,
    "total_tokens": 120
  }]
}
```

Envelope fields are exact, with `test_mode` required to avoid ambiguous sample traffic. Accept 1..100 events; reject unknown/duplicate JSON keys, malformed JSON, NaN/infinity, nested arbitrary objects and content fields. Only `cost_usd`, token fields and `parent_observation_id` may be omitted/null. Identity/name/model strings are bounded technical identifiers, not free-form payload content. Observation/trace/parent IDs are 1..128 ASCII letters/digits/`_.:-`; agent/model labels are 1..120 ASCII letters/digits/`_.:/-`. Status is success/error/unknown. Both times require explicit timezone, end must follow/equal start, start may be at most 24 hours old and neither time may exceed server receipt by five minutes. Terminal events are immutable; streaming emits after terminal completion, retries get different observation IDs. No raw error message or prompt/output/document/customer/user/session attributes are accepted.

`cost_usd` is null or a nonnegative decimal string with at most 12 fractional digits and less than 1,000,000,000 USD; missing pricing stays unknown. Token counts are null or strict nonnegative integers at most 2^53-1. When input and output are both known their sum must match supplied total; otherwise derive total only when both are known. Latency derives from aware start/end times. Server scope supplies source `guardian_direct`, project and environment; the body cannot select them. Unknown values retain existing ledger semantics. The endpoint accepts JSON identity encoding only, streams at most 256 KiB under a five-second body deadline and never persists rejected raw data.

Test mode validates the same envelope/key/scope and records a separate test receipt/timestamp. It creates no production observations, metrics or incidents and cannot establish first real traffic or processing health. A test receipt is an instrumentation handshake only. The setup UI can send an explicit test with the just-revealed key; it must never reuse the dashboard cookie/key as ingestion authority.

## Durable intake, processing and limits

One transaction fences current credential/binding, applies per-key/project admission, writes a batch receipt and inserts numeric inbox records. Receipt identity is fixed binding + batch UUID; content fingerprint excludes transport/cookie/session values. Exact replay returns the original counts. Inbox identity is observation identity + normalized fingerprint; replay across different batches does not create extra work. Changed copies queue conservative conflict evaluation rather than silently overwrite prior measurements. No plaintext token or raw body enters inbox, receipt, audit or logs.

Allow 120 new batches per key/minute and 300 per project/minute, at most 6,000 submitted events per project/minute and 10,000 pending distinct inbox records. Exact receipt replay bypasses charging new intake quota but still requires a currently valid key. Counters expire for cleanup; enforcement uses explicit minute windows and transactions. There is no advertised production load envelope. Processed inbox/receipt/key/audit history is retained in this slice; an explicit retention/offboarding implementation remains required before hosted use.

A separate direct worker consumes at most 500 inbox records per cycle. It persists the current receipt-sequence cutoff and drains that fixed prefix across cycles before evaluating detectors; newer arrivals cannot move that cutoff or make a partial prefix appear complete. The connection lease fences each transaction combining ledger acceptance/conflict and inbox completion. Interrupted/uncommitted work remains pending. Rebuild existing dirty buckets and run existing deterministic cost/reliability detectors under the same ledger rules; content-free capture does not establish PII coverage, and late earlier events do not retroactively re-evaluate already completed statistical decisions in this slice. Accounting captures accepted events once; delivery order and baseline completeness remain explicit limitations. Test traffic is excluded. A direct worker never opens an upstream source window or fabricates a polled-source watermark.

Direct live/run views read a bounded 1,000-record ledger window and reuse the existing unknown/partial numeric presentation. They provide internal run/incident evidence without vendor deep links or content previews. Scope comes from authenticated deployment configuration before database reads. Limits/conflicts show partial coverage; absence in the bounded window is not a missing run or healthy application. Metrics and incident APIs use the existing derived stores; inbox receipt can precede their appearance.

## UI, recipes and acceptance

[EXPORTING.md](EXPORTING.md) adds bounded Python/Node background exporters and explicit call/stream lifecycle helpers using this unchanged event contract. The manual sender API remains available for applications with an existing queue. Client admission is in memory; API receipt is durable; analysis happens later. These three stages must not be conflated.

For an operator-configured direct deployment:

1. Follow [IDENTITY.md](IDENTITY.md) for the isolated transaction-capable database, OIDC membership and public HTTPS origin. Select a fresh database with no Langfuse ledger/history. Keep organization/project/environment/connection identifiers stable. This version provides no self-service project creation.
2. Set `GUARDIAN_CAPTURE_MODE=direct` consistently for the API and worker. Langfuse and model-provider credentials are unnecessary for this mode. Give Guardian access to its capture/credential/receipt/inbox/admission collections and required indexes as well as its existing identity/ledger stores.
3. Start the API and the separate worker using the existing [README commands](../README.md). From the backend directory these are `python -m uvicorn server:app --port 8001` and, in another process with the same configuration, `python -m guardian.worker`. API availability alone does not start ingestion processing.
4. Sign in as an owner, open Setup and create an expiring ingestion key. Copy the one-time secret to the application's server-side secret configuration, then dismiss it. Other roles can inspect redacted key metadata. If creation times out, refresh the list, revoke the uncertain key and create a replacement; the secret cannot be recovered.
5. Send an explicit labelled test from Setup or the [Python/Node examples](../examples/native-capture/README.md). Then integrate actual completed call metadata through the application's background queue. The JSON example above is illustrative: use real event IDs and current observed timestamps, not the literal example values.
6. Confirm real receipt, pending/processed counts, worker heartbeat and internal call/run evidence. Test receipt alone proves neither processing nor a useful customer workflow. Rotate a key by creating/installing its replacement, verifying receipt, then revoking the old one. Already accepted work may still complete.

Retain the database and bindings through upgrades. Removing configuration or changing source mode is not a migration/offboarding procedure. Hosted rollout still needs retention/deletion, recovery, capacity and actual provider/browser/TLS acceptance; this local implementation does not close those gates.

Setup separates direct capture from existing Langfuse diagnostics. An owner may create/revoke; others see redacted metadata and their access limitation. The secret appears only once in component memory, with explicit copy and dismiss. Clear on unmount/focus session revalidation; never place it in local/session storage, URL, toast, polling data or a cached generated snippet. Explain lost-response recovery. Examples use environment placeholders and the exact versioned JSON endpoint. Include standard-library Python and built-in Node fetch senders for terminal metadata, explicit timeout and retries with unchanged IDs/body; telemetry failure is reported without failing a customer workflow. These recipes do not claim automatic SDK/framework instrumentation.

Acceptance covers role/CSRF/key scope, one-time reveal/lost response, expiry/revocation, duplicate/malformed credentials, content/size/encoding/time/numeric rejection with canaries absent, exact/changed batch replay, cross-batch observation replay/conflicts, test separation, stopped-worker backlog, actual inbox-to-ledger-to-metrics/incident behavior, and no Langfuse dependency in direct mode. Real local Mongo must prove audit/intake rollback, concurrent quota/replay and revoke versus intake ordering. Browser evidence remains separate from actual API/database integration and deployed TLS/provider checks. Record results and remaining gates in [VALIDATION.md](VALIDATION.md).
