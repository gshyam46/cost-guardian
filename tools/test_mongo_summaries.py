#!/usr/bin/env python
"""Real Mongo incident summary checks in owned, temporary localhost databases.

No arguments print help. Uses no application .env or provider credentials. The
explicit guardian-r102 replica set must enableTestCommands for scoped failures.
Only random databases created and marked by this run are removed.
"""
from __future__ import annotations

import argparse
import asyncio
from collections import Counter
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
import json
import logging
import os
import sys
from unittest.mock import patch

import test_mongo_ledger as ledger_checks


check = ledger_checks.check
NOW = datetime.now(timezone.utc).replace(hour=12, minute=0, second=0, microsecond=123000)
TODAY = NOW.replace(hour=0, minute=0, second=0, microsecond=0)
API_KEY = "synthetic-local-summary-api-key"
PRIVATE = "synthetic-private-timestamp-must-not-escape"


def load_dependencies():
    ledger_checks.load_dependencies()
    global IncidentSummaryReader, ensure_summary_indexes
    from guardian.summaries import IncidentSummaryReader, ensure_summary_indexes

    class SummaryEvents(ledger_checks.CommandEvents):
        def __init__(self):
            super().__init__()
            self.aggregate_commands = []

        def started(self, event):
            super().started(event)
            if event.command_name == "aggregate" and event.command.get("aggregate") == "guardian_incidents":
                # Retained in process solely for explain; raw commands are never
                # emitted in the safe JSON report.
                self.aggregate_commands.append(dict(event.command))

    ledger_checks.CommandEvents = SummaryEvents


def native(identifier, when, *, status="resolved", severity="high", detector="cost_anomaly"):
    return {
        "_id": identifier, "id": identifier, "created_at": when.isoformat(),
        "created_at_utc": when, "summary_schema": 1, "status": status,
        "severity": severity, "detector": detector,
        "title": "Synthetic summary fixture", "summary": "Synthetic summary fixture",
        "evidence": {}, "trace_ids": [], "agent_name": "synthetic-agent",
    }


def legacy(identifier, timestamp, *, omit=False):
    row = native(identifier, TODAY + timedelta(hours=2))
    del row["created_at_utc"]
    del row["summary_schema"]
    if omit:
        del row["created_at"]
    else:
        row["created_at"] = timestamp
    return row


async def insert_batches(collection, documents):
    for start in range(0, len(documents), 2000):
        await collection.insert_many(documents[start:start + 2000])


def nodes(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from nodes(child)
    elif isinstance(value, list):
        for child in value:
            yield from nodes(child)


async def explain_actual_aggregate(f, expected_candidates):
    check(bool(f.events.aggregate_commands), "summary_did_not_execute_server_aggregation")
    command = f.events.aggregate_commands[-1]
    check(isinstance(command.get("maxTimeMS"), int) and 0 < command["maxTimeMS"] <= 10000,
          "summary_server_execution_budget_missing")
    explain_command = {key: command[key] for key in (
        "aggregate", "pipeline", "cursor", "maxTimeMS", "allowDiskUse", "hint", "collation",
    ) if key in command}
    explanation = await f.db.command({"explain": explain_command, "verbosity": "executionStats"})
    statistics = [value for value in nodes(explanation)
                  if "totalDocsExamined" in value and "totalKeysExamined" in value]
    check(bool(statistics), "execution_statistics_missing")
    examined = max(value["totalDocsExamined"] for value in statistics)
    keys = max(value["totalKeysExamined"] for value in statistics)
    winning = [part["winningPlan"] for part in nodes(explanation) if "winningPlan" in part]
    stages = {part.get("stage") for plan in winning for part in nodes(plan) if "stage" in part}
    indexes = sorted({part["indexName"] for plan in winning for part in nodes(plan) if "indexName" in part})
    evidence = {"documents_examined": examined, "keys_examined": keys, "index_names": indexes,
                "candidate_count": expected_candidates}
    f.suite.details["indexed_volume"] = evidence
    check(bool(indexes) and "COLLSCAN" not in stages, "summary_candidate_match_did_not_use_indexes")
    check(examined <= expected_candidates, "summary_scanned_unrelated_native_history")
    return evidence


@asynccontextmanager
async def api_client(f):
    import httpx

    synthetic_env = {
        "PYTHON_DOTENV_DISABLED": "1", "MONGO_URL": "mongodb://127.0.0.1:1",
        "GUARDIAN_DB_NAME": "synthetic_unused_summary_default", "GUARDIAN_API_KEY": API_KEY,
        "GUARDIAN_CONNECTION_ID": "primary", "GUARDIAN_PORT": "8001",
        "GUARDIAN_CORS_ORIGINS": "http://localhost:3001", "GUARDIAN_POLL_INTERVAL_SECONDS": "60",
        "LANGFUSE_PUBLIC_KEY": "", "LANGFUSE_SECRET_KEY": "",
        "LANGFUSE_HOST": "https://source.invalid", "LANGFUSE_READ_API": "v2",
    }
    original_handlers = list(logging.getLogger().handlers)
    original_level = logging.getLogger().level
    new_default_db = "db" not in sys.modules
    new_default_routes = "api.routes" not in sys.modules
    default_db = default_source = None

    class FixedClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW.astimezone(tz) if tz is not None else NOW.replace(tzinfo=None)

    try:
        with patch.dict(os.environ, synthetic_env):
            import auth
            import db as database_module
            import api.routes as routes
            from server import app

            default_db, default_source = database_module.client, routes._trace_source
            with (patch.object(routes, "db", f.db), patch.object(routes, "datetime", FixedClock),
                  patch.object(auth, "GUARDIAN_API_KEY", API_KEY)):
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                    yield client
    finally:
        if new_default_db and default_db is not None:
            default_db.close()
        if new_default_routes and default_source is not None:
            default_source.close()
        for handler in list(logging.getLogger().handlers):
            if handler not in original_handlers:
                logging.getLogger().removeHandler(handler)
                handler.close()
        logging.getLogger().setLevel(original_level)


async def complete_native_volume_and_index_plan(f):
    severities = ("high", "medium", "low")
    detectors = ("cost_anomaly", "reliability_anomaly", "pii")
    open_docs = [native("open-" + str(index), TODAY + timedelta(hours=1), status="open",
                        severity=severities[index % 3], detector=detectors[index % 3]) for index in range(1500)]
    open_docs += [native("old-open-" + str(index), TODAY - timedelta(days=90), status="open") for index in range(4)]
    open_docs += [native("future-open", NOW + timedelta(days=1), status="open")]
    documents = list(open_docs)
    documents += [native("today-" + str(index), TODAY + timedelta(hours=2)) for index in range(10500)]
    for days_ago, count in ((1, 33), (6, 17), (7, 11), (13, 9)):
        documents += [native("day-" + str(days_ago) + "-" + str(index), TODAY - timedelta(days=days_ago))
                      for index in range(count)]
    documents += [native("at-upper-bound", NOW), native("future-resolved", NOW + timedelta(seconds=1))]
    # Much larger unrelated history ensures explain proves candidate selection,
    # rather than merely succeeding on an all-matching collection.
    documents += [native("history-" + str(index), TODAY - timedelta(days=90)) for index in range(30000)]
    await insert_batches(f.db.guardian_incidents, documents)
    await ensure_summary_indexes(f.db)
    snapshot = await IncidentSummaryReader(f.db).snapshot(days=14, now=NOW)
    overview = snapshot["overview"]
    check(overview["open_incidents"] == 1505, "open_count_truncated_or_date_filtered")
    check(overview["open_by_severity"] == dict(Counter(row["severity"] for row in open_docs)), "severity_totals_incomplete")
    check(overview["open_by_detector"] == dict(Counter(row["detector"] for row in open_docs)), "detector_totals_incomplete")
    check(overview["incidents_last_7_days"] == 12050, "recent_calendar_window_incorrect")
    expected = {(TODAY - timedelta(days=days)).date().isoformat(): 0 for days in range(14)}
    expected[TODAY.date().isoformat()] = 12000
    for days_ago, count in ((1, 33), (6, 17), (7, 11), (13, 9)):
        expected[(TODAY - timedelta(days=days_ago)).date().isoformat()] = count
    check(snapshot["trends"] == [{"date": day, "count": count} for day, count in sorted(expected.items())],
          "trend_count_truncated_or_utc_bounds_wrong")
    check(snapshot["coverage"] == {"status": "complete", "invalid_timestamp_count": 0}, "native_coverage_incorrect")
    check(snapshot["timezone"] == "UTC", "summary_timezone_missing")
    check(datetime.fromisoformat(snapshot["as_of"]) == NOW and datetime.fromisoformat(snapshot["window_end"]) == NOW,
          "summary_as_of_boundary_changed")
    check(datetime.fromisoformat(snapshot["window_start"]) == TODAY - timedelta(days=13), "summary_start_boundary_changed")
    candidate_count = 12075  # in-window 12070 plus 4 old and 1 future open.
    f.suite.details["indexed_volume"] = await explain_actual_aggregate(f, candidate_count)
    f.suite.details["indexed_volume"].update(total_fixture_rows=len(documents), open_count=1505, trend_count=12070)
    async with api_client(f) as client:
        response = await client.get("/api/guardian/summary", params={"days": 14}, headers={"X-Guardian-Key": API_KEY})
        check(response.status_code == 200, "native_summary_api_failed")
        check(response.json() == snapshot, "native_api_summary_disagrees_with_reader")
        legacy_overview = await client.get("/api/guardian/overview", headers={"X-Guardian-Key": API_KEY})
        legacy_trends = await client.get("/api/guardian/trends", params={"days": 14}, headers={"X-Guardian-Key": API_KEY})
        check(legacy_overview.status_code == legacy_trends.status_code == 200, "compatible_summary_endpoints_failed")
        check(legacy_overview.json() == overview and legacy_trends.json() == snapshot["trends"], "compatible_endpoints_changed_results")


async def legacy_utc_conversion_and_visible_partial(f):
    next_local_date = (TODAY + timedelta(days=1, minutes=30)).replace(tzinfo=timezone(timedelta(hours=14)))
    previous_local_date = (TODAY - timedelta(minutes=30)).replace(tzinfo=timezone(-timedelta(hours=2)))
    documents = [
        legacy("plus-fourteen", next_local_date.isoformat()),
        legacy("minus-two", previous_local_date.isoformat()),
        legacy("zulu", (TODAY + timedelta(hours=3)).isoformat().replace("+00:00", "Z")),
        legacy("bson-fallback", TODAY + timedelta(hours=4)),
        legacy("explicit-utc", (TODAY + timedelta(hours=5)).isoformat()),
        legacy("naive", (TODAY + timedelta(hours=6)).replace(tzinfo=None).isoformat()),
        legacy("malformed", PRIVATE), legacy("null", None), legacy("missing", None, omit=True),
        legacy("number", 1770000000), legacy("upper-bound", NOW.isoformat()),
        legacy("future", (NOW + timedelta(seconds=1)).isoformat()),
        legacy("before-window", (TODAY - timedelta(days=14)).isoformat()),
        legacy("valid-historical-leap-day", "2024-02-29T12:00:00+00:00"),
        legacy("invalid-nonleap-day", "2026-02-29T12:00:00+00:00"),
    ]
    for kind in ("missing", "null", "string", "number"):
        # Declaring the native schema cannot make a missing/corrupt BSON date
        # complete, or silently trust the otherwise parseable legacy field.
        row = native("corrupt-native-" + kind, TODAY + timedelta(hours=2))
        if kind == "missing":
            del row["created_at_utc"]
        else:
            row["created_at_utc"] = {"null": None, "string": TODAY.isoformat(), "number": 1770000000}[kind]
        documents.append(row)
    await f.db.guardian_incidents.insert_many(documents)
    await ensure_summary_indexes(f.db)
    result = await IncidentSummaryReader(f.db).snapshot(days=14, now=NOW)
    check(result["coverage"] == {"status": "partial", "invalid_timestamp_count": 10}, "legacy_or_native_invalid_dates_not_visible")
    check(result["overview"]["incidents_last_7_days"] == 5, "legacy_aware_dates_not_converted_to_utc")
    check(result["trends"][-1] == {"date": TODAY.date().isoformat(), "count": 5}, "legacy_today_bucket_incorrect")
    check(sum(point["count"] for point in result["trends"]) == 5, "legacy_future_or_outside_date_counted")
    check(PRIVATE not in json.dumps(result), "summary_returned_raw_timestamp")
    async with api_client(f) as client:
        headers = {"X-Guardian-Key": API_KEY}
        response = await client.get("/api/guardian/summary", params={"days": 14}, headers=headers)
        check(response.status_code == 200 and response.json()["coverage"] == result["coverage"], "partial_api_summary_hidden")
        for path in ("/api/guardian/overview", "/api/guardian/trends"):
            response = await client.get(path, headers=headers)
            check(response.status_code == 503, "compatible_endpoint_fabricated_complete_date_coverage")
            check(PRIVATE not in response.text, "compatible_error_leaked_timestamp")


async def native_containers_and_unsupported_dates_are_invalid(f):
    from bson.datetime_ms import DatetimeMS

    values = [
        [TODAY - timedelta(days=90)], [TODAY], [TODAY, "invalid"], [],
        DatetimeMS(253402300800000), DatetimeMS(-62167219200000),
    ]
    for index, value in enumerate(values):
        row = native("malformed-native-" + str(index), TODAY)
        row["created_at_utc"] = value
        await f.db.guardian_incidents.insert_one(row)
    await ensure_summary_indexes(f.db)
    result = await IncidentSummaryReader(f.db).snapshot(days=14, now=NOW)
    check(result["coverage"] == {"status": "partial", "invalid_timestamp_count": 6},
          "native_container_or_unsupported_date_falsely_complete")
    check(sum(row["count"] for row in result["trends"]) == 0,
          "native_container_or_unsupported_date_counted_as_valid")
    f.suite.details["native_corruption"] = {"invalid_timestamp_count": 6, "dated_count": 0}


async def actual_writer_emits_canonical_native_timestamp(f):
    from guardian.incident import Incident
    from guardian.store import MongoIncidentStore

    local_time = (TODAY + timedelta(hours=10)).replace(
        tzinfo=timezone(timedelta(hours=5, minutes=30)), microsecond=123456,
    )
    expected = local_time.astimezone(timezone.utc)
    incident = Incident(id="native-writer", detector="cost_anomaly", severity="high",
                        title="Synthetic", summary="Synthetic", created_at=local_time)
    store = MongoIncidentStore(f.db)
    check(await store.create_if_absent(incident), "native_writer_did_not_insert")
    document = await f.db.guardian_incidents.find_one({"_id": incident.id})
    check(document["summary_schema"] == 1 and isinstance(document["created_at_utc"], datetime),
          "writer_did_not_emit_native_bson_date")
    bson_time = document["created_at_utc"].replace(tzinfo=timezone.utc)
    check(bson_time == expected.replace(microsecond=123000), "writer_bson_date_wrong_utc_or_precision")
    check(document["created_at"] == expected.isoformat(), "writer_public_timestamp_not_canonical_utc")
    check((await store.get(incident.id)).created_at == expected, "public_incident_roundtrip_changed_timestamp")
    naive = incident.model_copy(update={"id": "naive-writer", "created_at": local_time.replace(tzinfo=None)})
    try:
        await store.create_if_absent(naive)
    except ValueError:
        pass
    else:
        raise ledger_checks.CheckFailed("writer_accepted_ambiguous_naive_timestamp")
    check(await f.db.guardian_incidents.count_documents({}) == 1, "rejected_writer_left_incident")
    result = await IncidentSummaryReader(f.db).snapshot(days=1, now=NOW)
    check(result["overview"]["open_incidents"] == result["overview"]["incidents_last_7_days"] == 1,
          "summary_omitted_actual_native_writer")
    check(result["trends"] == [{"date": TODAY.date().isoformat(), "count": 1}],
          "native_writer_bucket_not_today_utc")


async def real_query_failure_and_auth_boundaries(f):
    await ensure_summary_indexes(f.db)
    async with api_client(f) as client:
        paths = ("/api/guardian/summary", "/api/guardian/overview", "/api/guardian/trends")
        before = len(f.events.aggregate_commands)
        before_commands = dict(f.events.started_counts)
        for path in paths:
            for headers in ({}, {"X-Guardian-Key": "wrong"}, {"Cookie": "guardian_key=" + API_KEY}):
                response = await client.get(path, headers=headers)
                check(response.status_code == 401, "summary_auth_denial_failed")
        check(len(f.events.aggregate_commands) == before, "unauthorized_summary_queried_database")
        check(dict(f.events.started_counts) == before_commands, "unauthorized_summary_executed_database_command")
        for path in paths:
            await f.arm(["aggregate"], errorCode=50)
            try:
                response = await client.get(path, headers={"X-Guardian-Key": API_KEY})
            finally:
                await f.disarm()
            check(response.status_code == 503, "real_aggregate_failure_became_success_or_internal_error")
            check("failCommand" not in response.text and f.name not in response.text,
                  "summary_error_exposed_database_details")
        response = await client.get("/api/guardian/summary", headers={"X-Guardian-Key": API_KEY})
        check(response.status_code == 200 and response.json()["overview"]["open_incidents"] == 0,
              "summary_did_not_recover_after_query_failure")
        before = len(f.events.aggregate_commands)
        for days in ("0", "91", "invalid"):
            response = await client.get("/api/guardian/summary", params={"days": days}, headers={"X-Guardian-Key": API_KEY})
            check(response.status_code == 422, "summary_unbounded_days_accepted")
        check(len(f.events.aggregate_commands) == before, "invalid_days_queried_database")


async def run_suite(uri):
    suite = ledger_checks.Suite(uri)
    suite.details = {}
    try:
        version = await suite.preflight()
        for name, test in (
            ("complete_volume_index_plan", complete_native_volume_and_index_plan),
            ("legacy_utc_partial_coverage", legacy_utc_conversion_and_visible_partial),
            ("native_container_date_corruption", native_containers_and_unsupported_dates_are_invalid),
            ("native_writer_timestamp", actual_writer_emits_canonical_native_timestamp),
            ("aggregate_failures_and_auth", real_query_failure_and_auth_boundaries),
        ):
            await suite.run(name, test)
        failed = sum(result["status"] != "passed" for result in suite.results)
        return {"status": "failed" if failed or suite.owned else "passed", "mongo_version": version,
                "finished_at": datetime.now(timezone.utc).isoformat(), "fixture_as_of": NOW.isoformat(),
                "passed": len(suite.results) - failed, "failed": failed, "cleanup_complete": not suite.owned,
                "tests": suite.results, "evidence": suite.details}
    finally:
        suite.admin.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mongo-url", help="Explicit localhost-only guardian-r102 replica-set URI")
    args = parser.parse_args(argv)
    if not args.mongo_url:
        parser.print_help()
        return 0
    try:
        uri = ledger_checks.validate_url(args.mongo_url)
        load_dependencies()
        result = asyncio.run(run_suite(uri))
    except Exception as error:
        result = {"status": "failed", "error_type": type(error).__name__}
        if isinstance(error, ledger_checks.CheckFailed):
            result["code"] = str(error)
    print(json.dumps(result, indent=2))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
