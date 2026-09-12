# Incident summary contract (R1-03)

Agreed 2026-09-11 before implementation. This slice closes incident overview/trend truncation and calendar boundary defects, and the incident list's false empty state. It extends [ARCHITECTURE.md](ARCHITECTURE.md) and [PLAN.md](PLAN.md); source compatibility, cutover, operating and onboarding gates remain open.

## Customer-visible behavior

The dashboard requests one `/api/guardian/summary?days=14` response for open totals, severity/detector breakdowns and daily incident counts. Open totals describe all currently open incidents. Recent-seven-day counts and trends use UTC calendar days including today, from midnight on the first day up to one captured request time. Today is partial. This replaces the previous rolling-seven-day count so the seven-day trend and recent total reconcile. Query dates/hours are labelled UTC; incident detail timestamps may still use the viewer's local timezone.

The response contains `overview` (the existing four count fields), `trends` (ordered `{date,count}` points), `as_of`, `timezone`, `window_start`, `window_end` and `coverage: {status, invalid_timestamp_count}`. The interval is half-open: `[window_start, as_of)`. Request time is rounded down to BSON millisecond precision. Future incidents are excluded from time-window counts; an open incident remains in open totals even when its timestamp is unusable. Zero-filled days mean no dated incidents in that day, not proof of healthy monitored traffic.

Malformed, missing or timezone-naive historical dates cannot be assigned to a day. The new endpoint reports partial coverage and their count; the dashboard displays the limitation. Existing `/overview` and `/trends` retain their response shapes but return a safe 503 when timestamp coverage is incomplete. Database errors and query deadlines also return a safe 503, never empty successful totals. Authentication precedes database work.

Incident lists distinguish loading, successful empty, failed initial load and failed refresh. A retry is visible. Failed refresh may retain labelled last-successful rows for the same filter; old Open results cannot appear under Resolved. Requests propagate cancellation and a bounded timeout. A zero-count chart reports a peak of zero while retaining a nonzero internal scale denominator.

## Storage and query design

New incident writes retain the public ISO timestamp and add `created_at_utc` as a BSON UTC date with `summary_schema=1`. New writes reject timezone-naive creation times. Existing records are not rewritten by serving a summary. Legacy aware ISO strings, including numeric offsets and `Z`, and BSON dates are converted within Mongo with invalid values handled explicitly. Dates without an explicit timezone remain unknown. A future dedicated backfill may populate canonical fields after review; this slice does not perform a mass migration.

The database aggregates matching incidents instead of returning capped raw lists to Python. One aggregation produces the open and dated facets from the same request stream. Current severity and detector categories have bounded known values plus `unknown`; unexpected legacy categories cannot create an unbounded response. Daily groups are bounded by the requested 1–90 days plus the seven-day overview window and fixed coverage groups. Exact counts may examine every matching record: there is no silent input count cap.

Candidate predicates and indexes cover open status, canonical creation time and the schema marker used to find legacy records. Historical legacy rows must still be examined until canonicalized, because their original strings are not a safe UTC range index. The aggregation has a 2-second server execution budget, bounded application wait, and bounded grouped output. Exceeding a budget produces unavailable data. Indexes are created lazily by the summary service and verified against a real local Mongo instance; no new unique constraint or historical rewrite is introduced.

Canonical date validation uses scalar BSON expression comparisons, including explicit missing-field handling. It rejects arrays, other date-field types and years outside the supported 1-9999 range. A query-selector `$type` test alone can match an array element, while its complement can force unrelated historical rows to be read. Real Mongo evidence checks both correctness and the winning index plan. Legacy conversion and invalid-date counting can still increase read work; the local fixture is not a production capacity promise.

Index initialization is serialized and cached per database handle after all indexes succeed. Each index command has the same server time budget; the total application wait is five seconds. The first summary request after process startup needs index-creation permission, even if definitions already exist. Normal subsequent reads do not recreate indexes. An interrupted or failed setup remains retryable. Index maintenance and permissions belong in the deployment runbook.

`as_of` is the dated-event cutoff, not a historical reconstruction of open/resolved lifecycle. The facets share one aggregation stream, without claiming a multi-document snapshot or a status history that the current incident schema does not retain.

## Verification

Acceptance includes more than 1,000 open incidents, more than 10,000 dated incidents, exact breakdown reconciliation, today/month/year/leap-day boundaries, future exclusion, offset dates, invalid-date coverage, authorization and safe database failure. Mock tests must not pretend unsupported Mongo date operators are implemented; real Mongo tests verify legacy conversion and query plans. Inspect safe explain counters and index usage without exposing documents. Browser checks cover partial summaries, true empty state, failed reads, filter changes and retry. Record actual results in [VALIDATION.md](VALIDATION.md).

Reference semantics: MongoDB's [$facet](https://www.mongodb.com/docs/manual/reference/operator/aggregation/facet/), [$convert](https://www.mongodb.com/docs/manual/reference/operator/aggregation/convert/) and [$dateToString](https://www.mongodb.com/docs/manual/reference/operator/aggregation/dateToString/) documentation. The preceding candidate match, bounded categories and bounded date groups are intentional; this service does not rely on facet spill-to-disk to handle unlimited output.
