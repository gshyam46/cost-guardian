#!/usr/bin/env python
"""Real, isolated MongoDB ledger faults. No arguments print help; no .env reads.

Run with the Guardian interpreter and an explicitly supplied localhost replica
set named guardian-r102. Only random guardian_r102_test_<uuid> databases created
by this process are removed. The instance must enableTestCommands; failpoints
are one-shot, scoped to this run's appName, and cleared before database cleanup.
"""
from __future__ import annotations

import argparse
import asyncio
from collections import Counter
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import sys
from urllib.parse import parse_qsl, urlsplit
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[1]
REPLICA_SET = "guardian-r102"
DB_PREFIX = "guardian_r102_test_"


class CheckFailed(Exception):
    """Contains only a test-authored diagnostic, never database exception text."""


class InjectedAbort(Exception):
    pass


def check(condition, code):
    if not condition:
        raise CheckFailed(code)


def validate_url(value):
    try:
        parsed = urlsplit(value)
        if (parsed.scheme != "mongodb" or parsed.username is not None or parsed.password is not None
                or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
                or parsed.path not in {"", "/"} or parsed.fragment
                or (parsed.port is not None and not 1 <= parsed.port <= 65535)):
            raise ValueError
        options = parse_qsl(parsed.query, keep_blank_values=True, strict_parsing=True)
        seen = set()
        for key, option in options:
            key = key.lower()
            if key in seen or key not in {"replicaset", "directconnection"}:
                raise ValueError
            if key == "replicaset" and option != REPLICA_SET:
                raise ValueError
            if key == "directconnection" and option.lower() != "true":
                raise ValueError
            seen.add(key)
        return value
    except (ValueError, TypeError):
        raise CheckFailed("invalid_local_mongo_url") from None


def load_dependencies():
    # Import only domain/storage modules here. The integration case imports the
    # application under explicit synthetic configuration with dotenv disabled.
    os.environ["PYTHON_DOTENV_DISABLED"] = "1"
    sys.path.insert(0, str(ROOT / "apps" / "guardian" / "backend"))
    global MotorClient, ObservationLedger, LeaseLost, LedgerError, TraceMetric
    global SourcePageResult, SourceRowDisposition, DetectorResult, MongoIncidentStore
    global to_public_dict, CURSOR_DOC_ID, aware, CommandEvents
    from motor.motor_asyncio import AsyncIOMotorClient as MotorClient
    from pymongo.monitoring import CommandListener
    from guardian.ledger import ObservationLedger, LeaseLost, LedgerError, CURSOR_DOC_ID, aware
    from guardian.models import TraceMetric, SourcePageResult, SourceRowDisposition
    from guardian.detectors.base import DetectorResult
    from guardian.store import MongoIncidentStore
    from guardian.metrics import to_public_dict

    class CommandEvents(CommandListener):
        def __init__(self):
            self.started_counts = Counter()
            self.ambiguous_commits = 0

        def started(self, event):
            self.started_counts[event.command_name] += 1

        def succeeded(self, event):
            if event.command_name == "commitTransaction" and "writeConcernError" in event.reply:
                self.ambiguous_commits += 1

        def failed(self, event):
            # PyMongo 4.5 publishes a write-concern reply as commandFailed,
            # although the transaction has already committed on the server.
            if event.command_name == "commitTransaction" and event.failure.get("code") == 64:
                self.ambiguous_commits += 1


def metric(index=0, *, cost=1.25, agent="test-agent", **changes):
    started = datetime(2026, 9, 11, 12, 0, 0, tzinfo=timezone.utc) + timedelta(seconds=index)
    values = dict(trace_id="synthetic-trace", observation_id="synthetic-observation-" + str(index),
                  agent_name=agent, model="synthetic-model", source="langfuse", project_id="test-project",
                  cost_usd=cost, cost_usd_decimal=str(cost) if cost is not None else None,
                  total_tokens=10, input_tokens=6, output_tokens=4, latency_ms=25,
                  status="success", timestamp=started, ended_at=started + timedelta(milliseconds=25),
                  completion_state="complete", output_text="synthetic-content-must-not-persist",
                  status_message="synthetic-status-must-not-persist", user_id="synthetic-user-must-not-persist",
                  session_id="synthetic-session-must-not-persist", trace_tags=("synthetic-tags-must-not-persist",))
    values.update(changes)
    return TraceMetric(**values)


class Fixture:
    def __init__(self, suite, name):
        self.suite = suite
        self.owner = uuid4().hex
        self.name = DB_PREFIX + self.owner
        self.app = "guardian-r102-" + name + "-" + self.owner
        self.events = CommandEvents()
        self.client = suite.client(self.app, self.events)
        self.db = self.client[self.name]
        self.ledger = ObservationLedger(self.db)
        self.lease = None
        self.armed = False

    async def arm(self, commands, **data):
        state = await self.suite.admin.admin.command({"getParameter": 1, "failpoint.failCommand": 1})
        check(state["failpoint.failCommand"]["mode"] == 0, "another_failpoint_is_active")
        await self.suite.admin.admin.command({"configureFailPoint": "failCommand", "mode": {"times": 1},
            "data": {"failCommands": commands, "appName": self.app, **data}})
        self.armed = True

    async def disarm(self):
        if not self.armed:
            return
        state = (await self.suite.admin.admin.command({"getParameter": 1, "failpoint.failCommand": 1}))["failpoint.failCommand"]
        check(state.get("data", {}).get("appName") == self.app or state["mode"] == 0,
              "failpoint_ownership_changed")
        if state.get("data", {}).get("appName") == self.app:
            await self.suite.admin.admin.command({"configureFailPoint": "failCommand", "mode": "off"})
        self.armed = False


class Suite:
    def __init__(self, uri):
        self.uri = uri
        self.admin = self.client("guardian-r102-cleanup-" + uuid4().hex)
        self.owned = {}
        self.results = []

    def client(self, app, listener=None):
        return MotorClient(self.uri, appname=app, directConnection=True, replicaSet=REPLICA_SET,
                           serverSelectionTimeoutMS=3000, connectTimeoutMS=2000, socketTimeoutMS=10000,
                           event_listeners=[listener] if listener else [])

    async def preflight(self):
        hello = await self.admin.admin.command("hello")
        check(hello.get("setName") == REPLICA_SET and hello.get("isWritablePrimary"), "isolated_primary_required")
        check(len(hello.get("hosts", [])) == 1, "single_member_test_replica_required")
        member = hello["hosts"][0]
        member_host = member.rsplit(":", 1)[0].strip("[]")
        check(member_host in {"localhost", "127.0.0.1", "::1"}, "nonlocal_replica_member")
        params = await self.admin.admin.command({"getParameter": 1, "enableTestCommands": 1, "failpoint.failCommand": 1})
        check(params["enableTestCommands"], "test_commands_required")
        check(params["failpoint.failCommand"]["mode"] == 0, "another_failpoint_is_active")
        return (await self.admin.server_info())["version"]

    @asynccontextmanager
    async def fixture(self, name):
        f = Fixture(self, name)
        check(f.name not in await self.admin.list_database_names(), "test_database_already_exists")
        await f.db["_suite_owner"].insert_one({"_id": f.owner, "purpose": "guardian_r102_fault_suite"})
        self.owned[f.name] = f.owner
        try:
            await f.ledger.ensure_indexes()
            f.lease = await f.ledger.acquire("owner-" + f.owner)
            check(f.lease is not None, "fresh_database_lease_unavailable")
            yield f
        finally:
            try:
                await f.disarm()
                await self.cleanup_database(f.name)
            finally:
                f.client.close()

    async def cleanup_database(self, name):
        owner = self.owned.get(name)
        check(owner is not None and re.fullmatch(r"guardian_r102_test_[0-9a-f]{32}", name)
              and name == DB_PREFIX + owner, "database_cleanup_scope_invalid")
        marker = await self.admin[name]["_suite_owner"].find_one({"_id": owner})
        check(marker and marker.get("purpose") == "guardian_r102_fault_suite", "database_cleanup_owner_missing")
        await self.admin.drop_database(name)
        check(name not in await self.admin.list_database_names(), "database_cleanup_incomplete")
        del self.owned[name]

    async def run(self, name, test):
        started = asyncio.get_running_loop().time()
        try:
            async with self.fixture(name) as f:
                await asyncio.wait_for(test(f), timeout=45)
            self.results.append({"name": name, "status": "passed"})
        except Exception as error:
            result = {"name": name, "status": "failed", "error_type": type(error).__name__}
            if isinstance(error, CheckFailed):
                result["code"] = str(error)
            self.results.append(result)
        self.results[-1]["duration_seconds"] = round(asyncio.get_running_loop().time() - started, 3)


async def abort_is_atomic(f):
    original = f.ledger._dirty
    before = await f.db.guardian_leases.find_one({"_id": f.ledger.lease_id})
    async def abort_after_write(bucket, session):
        await original(bucket, session)
        raise InjectedAbort
    f.ledger._dirty = abort_after_write
    try:
        await f.ledger.ingest_metrics([metric()], f.lease)
        raise CheckFailed("injected_abort_was_swallowed")
    except InjectedAbort:
        pass
    finally:
        f.ledger._dirty = original
    for collection in ("guardian_observations", "guardian_dirty_buckets", "guardian_state"):
        check(await f.db[collection].count_documents({}) == 0, "aborted_transaction_left_" + collection)
    after = await f.db.guardian_leases.find_one({"_id": f.ledger.lease_id})
    check(after["fence"] == before["fence"], "aborted_transaction_mutated_fence")
    check(f.events.started_counts["abortTransaction"] >= 1, "real_abort_command_not_observed")


async def restart_and_rebuild(f):
    await f.ledger.ingest_metrics([metric(), metric(1, cost=2.75)], f.lease)
    check(await f.db.guardian_metrics.count_documents({}) == 0, "materialization_not_deferred")
    await f.ledger.release(f.lease)
    restarted_client = f.suite.client(f.app + "-restart")
    try:
        restarted = ObservationLedger(restarted_client[f.name])
        lease = await restarted.acquire("restarted-worker")
        check(lease is not None, "restart_could_not_acquire_lease")
        backlog = await restarted.backlog()
        check(backlog["pending_observations"] == 2 and backlog["dirty_buckets"] == 1, "committed_work_lost_after_restart")
        await restarted.rebuild(lease)
        first = await f.db.guardian_metrics.find_one({})
        check(first["call_count"] == 2 and first["total_cost_usd"] == 4, "restart_rebuild_wrong_totals")
        await restarted.rebuild(lease)
        check(first == await f.db.guardian_metrics.find_one({}), "empty_rebuild_changed_published_bucket")
        rows = await f.db.guardian_observations.find({}).to_list(10)
        encoded = json.dumps(rows, default=str)
        check("must-not-persist" not in encoded, "ledger_persisted_disallowed_content")
    finally:
        restarted_client.close()


async def concurrent_replay(f):
    await f.ledger.release(f.lease)
    other = ObservationLedger(f.db)
    claims = await asyncio.gather(f.ledger.acquire("claim-one"), other.acquire("claim-two"))
    winners = [lease for lease in claims if lease is not None]
    check(len(winners) == 1, "concurrent_lease_acquisition_had_multiple_winners")
    lease = winners[0]
    results = await asyncio.gather(f.ledger.ingest_metrics([metric()], lease), other.ingest_metrics([metric()], lease))
    check(sum(row["accepted"] for row in results) == 1 and sum(row["duplicate"] for row in results) == 1,
          "concurrent_replay_was_not_idempotent")
    await f.ledger.rebuild(lease)
    row = await f.db.guardian_metrics.find_one({})
    check(row["call_count"] == 1 and row["total_cost_usd"] == 1.25, "concurrent_replay_doubled_totals")


async def expired_owner_is_fenced(f):
    old = f.lease
    await f.db.guardian_leases.update_one({"_id": f.ledger.lease_id}, {"$set": {"expires_at": datetime.now(timezone.utc) - timedelta(seconds=1)}})
    replacement = await f.ledger.acquire("replacement-worker")
    check(replacement is not None and replacement.epoch > old.epoch, "takeover_did_not_advance_epoch")
    try:
        await f.ledger.ingest_metrics([metric()], old)
        raise CheckFailed("expired_owner_committed_after_takeover")
    except LeaseLost:
        pass
    check(await f.db.guardian_observations.count_documents({}) == 0, "stale_owner_left_writes")
    await f.ledger.release(old)
    current = await f.db.guardian_leases.find_one({"_id": f.ledger.lease_id})
    check(current["owner"] == replacement.owner, "stale_release_invalidated_current_owner")
    await f.ledger.ingest_metrics([metric()], replacement)


async def conflicts_remove_trusted_cost(f):
    await f.ledger.ingest_metrics([metric()], f.lease)
    await f.ledger.rebuild(f.lease)
    result = await f.ledger.ingest_metrics([metric(cost=9)], f.lease)
    check(result["conflict"] == 1, "revision_conflict_not_detected")
    await f.ledger.rebuild(f.lease)
    row = await f.db.guardian_metrics.find_one({})
    public = to_public_dict(row)
    check(row["conflict_count"] == 1 and row["cost_known_count"] == 0 and row["cost_unknown_count"] == 1,
          "conflicted_identity_retained_trusted_cost")
    check(public["total_cost_usd"] is None, "conflict_published_free_total")
    await f.ledger.ingest_metrics([metric()], f.lease)
    check((await f.db.guardian_observations.find_one({}))["state"] == "conflicted", "old_copy_restored_conflicted_trust")


async def ambiguous_commit_is_once(f):
    calls = 0
    original = f.ledger._accept
    async def counted(*args):
        nonlocal calls
        calls += 1
        return await original(*args)
    f.ledger._accept = counted
    before = f.events.started_counts["commitTransaction"]
    await f.arm(["commitTransaction"], writeConcernError={"code": 64, "errmsg": "synthetic acknowledgement failure"},
                errorLabels=["UnknownTransactionCommitResult"])
    try:
        await f.ledger.ingest_metrics([metric()], f.lease)
    finally:
        await f.disarm()
        f.ledger._accept = original
    check(f.events.ambiguous_commits == 1, "ambiguous_commit_reply_not_observed")
    check(f.events.started_counts["commitTransaction"] - before >= 2 and calls == 1, "commit_retry_reexecuted_transaction_body")
    check(await f.db.guardian_observations.count_documents({}) == 1, "ambiguous_commit_duplicated_ledger")
    await f.ledger.rebuild(f.lease)
    check((await f.db.guardian_metrics.find_one({}))["total_cost_usd"] == 1.25, "ambiguous_commit_doubled_cost")


async def transient_write_retries_whole_transaction(f):
    calls = 0
    original = f.ledger._accept
    async def counted(*args):
        nonlocal calls
        calls += 1
        return await original(*args)
    f.ledger._accept = counted
    await f.arm(["insert"], errorCode=112, errorLabels=["TransientTransactionError"])
    try:
        result = await f.ledger.ingest_metrics([metric()], f.lease)
    finally:
        await f.disarm()
        f.ledger._accept = original
    check(calls >= 2 and result["accepted"] == 1, "transient_write_did_not_retry_transaction_body")
    check(await f.db.guardian_observations.count_documents({}) == 1, "retried_body_duplicated_identity")
    check(await f.db.guardian_dirty_buckets.count_documents({}) == 1, "retried_body_duplicated_work")


def source_page(window, rows, *, next_cursor=None, exhausted=True):
    return SourcePageResult(rows, "ok", window_start=aware(window["start"]), window_end=aware(window["end"]),
                            query_fingerprint="synthetic-fixed-query", request_cursor=window["cursor"],
                            next_cursor=next_cursor, exhausted=exhausted, records_read=len(rows))


def accepted_row(value, ordinal=0):
    return SourceRowDisposition(ordinal, "accepted", "synthetic-row-fingerprint", metric=value,
                                observation_id=value.observation_id, trace_id=value.trace_id,
                                source_project_id=value.project_id)


async def page_checkpoint_is_atomic(f):
    start = datetime(2026, 9, 11, 11, 0, 0, 123456, tzinfo=timezone.utc)
    end = start + timedelta(hours=2)
    window = await f.ledger.begin_window(f.lease, start, end, "v2")
    persisted = await f.db.guardian_state.find_one({"_id": CURSOR_DOC_ID})
    check(aware(window["start"]) == aware(persisted["active_window"]["start"]) == start,
          "durable_window_changed_query_precision")
    first = source_page(window, [accepted_row(metric()), SourceRowDisposition(1, "quarantined", "safe-invalid-row",
                         issues=("missing_observation_id",))], next_cursor="private-test-cursor", exhausted=False)
    original = f.ledger.transaction
    async def abort_before_commit(callback):
        async def wrapped(session):
            await callback(session)
            raise InjectedAbort
        return await original(wrapped)
    f.ledger.transaction = abort_before_commit
    try:
        await f.ledger.commit_page(f.lease, window, first)
        raise CheckFailed("page_abort_was_swallowed")
    except InjectedAbort:
        pass
    finally:
        f.ledger.transaction = original
    for collection in ("guardian_observations", "guardian_page_receipts", "guardian_dirty_buckets", "guardian_quarantine"):
        check(await f.db[collection].count_documents({}) == 0, "aborted_page_left_" + collection)
    check((await f.db.guardian_state.find_one({"_id": CURSOR_DOC_ID}))["active_window"] == persisted["active_window"],
          "aborted_page_advanced_continuation")
    await f.ledger.commit_page(f.lease, window, first)
    resumed = ObservationLedger(f.db)
    active = await resumed.begin_window(f.lease, start, end, "v2")
    check(active["cursor"] == "private-test-cursor" and active["page"] == 1, "durable_continuation_not_resumed")
    state = await f.db.guardian_state.find_one({"_id": CURSOR_DOC_ID})
    check(not state.get("source_watermark"), "nonterminal_page_advanced_watermark")
    final = source_page(active, [accepted_row(metric(1, cost=2.75))])
    await resumed.commit_page(f.lease, active, final)
    try:
        await resumed.commit_page(f.lease, active, final)
        raise CheckFailed("already_committed_page_accepted_again")
    except LedgerError:
        pass
    state = await f.db.guardian_state.find_one({"_id": CURSOR_DOC_ID})
    check(state["active_window"] is None and aware(state["source_watermark"]) == end, "terminal_page_did_not_publish_watermark")
    check(await f.db.guardian_observations.count_documents({}) == 2 and await f.db.guardian_page_receipts.count_documents({}) == 2,
          "page_replay_duplicated_observations_or_receipts")
    check(await f.db.guardian_quarantine.count_documents({}) == 1, "row_disposition_not_durable")
    await resumed.rebuild(f.lease)
    check((await f.db.guardian_metrics.find_one({}))["total_cost_usd"] == 4, "page_recovery_materialized_wrong_total")


class SyntheticDetector:
    NAME = "synthetic-rule"
    def evaluate(self, baseline, candidates):
        candidate = candidates[0]
        check(all(row.timestamp < candidate.timestamp for row in baseline), "candidate_trained_own_baseline")
        return [DetectorResult(True, self.NAME, [candidate.trace_id], "low", "Synthetic test finding",
                               "Synthetic evidence", {"measured_cost": candidate.cost_usd}, candidate.agent_name,
                               observation_ids=[candidate.observation_id], source=candidate.source,
                               project_id=candidate.project_id)]


async def incidents_and_completion_are_atomic(f):
    await f.ledger.ingest_metrics([metric(), metric(1, agent="second-agent")], f.lease)
    original = f.ledger.transaction
    async def abort_before_commit(callback):
        async def wrapped(session):
            await callback(session)
            raise InjectedAbort
        return await original(wrapped)
    f.ledger.transaction = abort_before_commit
    try:
        await f.ledger.process_pending(f.lease, [SyntheticDetector()])
        raise CheckFailed("incident_abort_was_swallowed")
    except InjectedAbort:
        pass
    finally:
        f.ledger.transaction = original
    check(await f.db.guardian_incidents.count_documents({}) == 0, "aborted_work_left_incident")
    check(await f.db.guardian_observations.count_documents({"pending": True}) == 2, "aborted_work_marked_processing_complete")
    created, failures = await f.ledger.process_pending(f.lease, [SyntheticDetector()])
    check(created == 2 and failures == 0, "distinct_observations_collapsed_into_one_incident")
    incident = await f.db.guardian_incidents.find_one({})
    await MongoIncidentStore(f.db).resolve(incident["id"])
    resolved = await f.db.guardian_incidents.find_one({"_id": incident["_id"]})
    await f.db.guardian_observations.update_many({}, {"$set": {"pending": True, "completed_rules": []}})
    created, failures = await f.ledger.process_pending(f.lease, [SyntheticDetector()])
    check(created == 0 and failures == 0, "incident_replay_created_new_finding")
    check(await f.db.guardian_incidents.find_one({"_id": incident["_id"]}) == resolved and resolved["status"] == "resolved",
          "replay_reopened_or_rewrote_resolved_incident")


async def legacy_totals_require_explicit_cutover(f):
    await f.db.guardian_metrics.insert_one({"_id": "legacy", "call_count": 3, "total_cost_usd": 9})
    try:
        await f.ledger.ingest_metrics([metric()], f.lease)
        raise CheckFailed("legacy_totals_mixed_with_ledger")
    except LedgerError:
        pass
    check(await f.db.guardian_observations.count_documents({}) == 0, "cutover_refusal_left_ledger_writes")
    check((await f.db.guardian_metrics.find_one({"_id": "legacy"}))["total_cost_usd"] == 9, "cutover_refusal_overwrote_legacy_total")


async def bson_aggregate_overflow_stays_explicit(f):
    maximum = (1 << 63) - 1
    rows = [metric(index, cost=1e308, total_tokens=maximum, input_tokens=maximum,
                   output_tokens=0, latency_ms=1e308) for index in range(2)]
    await f.ledger.ingest_metrics(rows, f.lease)
    await f.ledger.rebuild(f.lease)
    stored = await f.db.guardian_metrics.find_one({})
    check(stored["total_tokens"] is None and stored["total_tokens_exact"] == str(maximum * 2),
          "bson_token_overflow_lost_exact_total")
    public = to_public_dict(stored)
    check(public["total_tokens"] is None and public["known_total_tokens"] is None,
          "overflowed_token_total_appears_known")
    check(public["total_cost_usd"] is None and public["avg_latency_ms"] is None,
          "nonfinite_aggregate_was_published")
    check(set(public["aggregate_issues"]) >= {"tokens_total_out_of_range", "cost_total_out_of_range", "latency_total_out_of_range"},
          "aggregate_overflow_reason_missing")
    json.dumps(public, allow_nan=False)
    persisted = await f.db.guardian_observations.find({}).to_list(2)
    check(all(row["metric"]["cost_usd_decimal"] == "1e+308" for row in persisted), "source_cost_text_not_preserved")


async def known_invalid_identity_is_order_independent(f):
    first, second = metric(agent="valid-first"), metric(1, agent="invalid-first")
    def invalid(value, ordinal):
        return SourceRowDisposition(ordinal, "quarantined", "safe-invalid-" + value.observation_id,
            observation_id=value.observation_id, trace_id=value.trace_id,
            source_project_id=value.project_id, issues=("invalid_start_time",))
    window = await f.ledger.begin_window(f.lease, first.timestamp - timedelta(hours=1),
                                         second.timestamp + timedelta(hours=1), "v2")
    rows = [accepted_row(first, 0), invalid(first, 1), invalid(second, 2), accepted_row(second, 3)]
    await f.ledger.commit_page(f.lease, window, source_page(window, rows))
    await f.ledger.rebuild(f.lease)
    observations = await f.db.guardian_observations.find({}).to_list(3)
    check(len(observations) == 2 and all(row["state"] == "conflicted" and not row["pending"] for row in observations),
          "invalid_identity_order_changed_trust")
    buckets = await f.db.guardian_metrics.find({}).to_list(3)
    check(len(buckets) == 2 and all(row["conflict_count"] == 1 and row["cost_known_count"] == 0
                                  and row["cost_unknown_count"] == 1 for row in buckets),
          "known_invalid_identity_retained_trusted_contribution")
    check(all(to_public_dict(row)["total_cost_usd"] is None for row in buckets), "known_invalid_identity_became_free")


async def worker_to_authenticated_api_recovers_late_observation(f):
    """Real transactions and ASGI routes; only provider HTTP is simulated."""
    import logging
    from unittest.mock import patch
    import httpx

    api_key = "synthetic-local-ledger-integration-key"
    private_cursor = "synthetic-private-cursor:+/reserved?=&"
    started = datetime.now(timezone.utc) - timedelta(minutes=1)
    row = {
        "id": "wire-observation", "traceId": "wire-trace", "projectId": "synthetic-project",
        "type": "GENERATION", "name": "answer-generator", "model": "synthetic-model",
        "startTime": started.isoformat(), "endTime": (started + timedelta(seconds=0.5)).isoformat(),
        "usageDetails": {"input": 12, "output": 8, "total": 20},
        "inputUsage": 12, "outputUsage": 8, "totalUsage": 20,
        "costDetails": {"total": 0.75}, "totalCost": 0.75, "latency": 0.5,
        "level": "ERROR", "output": "Safe synthetic provider response",
    }
    phase = 0
    requests = []

    def handler(request):
        check(request.url.path == "/api/public/v2/observations", "unexpected_provider_endpoint")
        check(request.url.params.get("type") == "GENERATION", "source_generation_filter_missing")
        requests.append((phase, dict(request.url.params)))
        cursor = request.url.params.get("cursor")
        if phase == 0:
            check(cursor is None, "empty_window_requested_cursor")
            return httpx.Response(200, json={"data": [], "meta": {}})
        if cursor is None:
            return httpx.Response(200, json={"data": [row], "meta": {"cursor": private_cursor}})
        check(cursor == private_cursor, "provider_continuation_changed")
        return httpx.Response(200, json={"data": [], "meta": {}})

    # Override every config input before importing the real application. The
    # module's default database client is lazy and points to an unused port.
    synthetic_env = {
        "PYTHON_DOTENV_DISABLED": "1", "MONGO_URL": "mongodb://127.0.0.1:1",
        "GUARDIAN_DB_NAME": "synthetic_unused_default", "GUARDIAN_API_KEY": api_key,
        "GUARDIAN_CONNECTION_ID": "primary", "GUARDIAN_PORT": "8001",
        "GUARDIAN_CORS_ORIGINS": "http://localhost:3001", "GUARDIAN_POLL_INTERVAL_SECONDS": "60",
        "LANGFUSE_PUBLIC_KEY": "", "LANGFUSE_SECRET_KEY": "",
        "LANGFUSE_HOST": "https://source.invalid", "LANGFUSE_READ_API": "v2",
    }
    source = None
    new_default_db = "db" not in sys.modules
    new_default_routes = "api.routes" not in sys.modules
    root_logger = logging.getLogger()
    original_handlers, original_level = list(root_logger.handlers), root_logger.level
    default_db = default_source = None
    try:
        with patch.dict(os.environ, synthetic_env):
            import auth
            import config
            import db as database_module
            import guardian.worker as worker
            import api.routes as routes
            from guardian.langfuse_client import LangfuseTraceSource
            from server import app

            default_db = database_module.client
            default_source = routes._trace_source
            source = LangfuseTraceSource(api_version="v2", host="https://source.invalid",
                public_key="synthetic-public", secret_key="synthetic-secret",
                transport=httpx.MockTransport(handler))
            await f.ledger.release(f.lease)
            with (patch.object(worker, "db", f.db), patch.object(routes, "db", f.db),
                  patch.object(routes, "_trace_source", source), patch.object(auth, "GUARDIAN_API_KEY", api_key),
                  patch.object(config, "GUARDIAN_CONNECTION_ID", "primary")):
                created = []
                first_watermark = None
                for phase in range(3):
                    created.append(await worker.poll_once(source))
                    state = await f.db.guardian_state.find_one({"_id": CURSOR_DOC_ID})
                    check(state.get("read_status") == "complete" and state.get("processing_status") == "complete",
                          "worker_did_not_complete_source_and_processing")
                    check(state.get("active_window") is None, "worker_left_completed_window_active")
                    if phase == 0:
                        first_watermark = aware(state["source_watermark"])
                        check(await f.db.guardian_observations.count_documents({}) == 0, "empty_poll_created_observation")
                    else:
                        check(await f.db.guardian_observations.count_documents({}) == 1, "late_replay_changed_observation_count")
                check(started < first_watermark, "late_fixture_not_before_initial_watermark")
                check(created == [0, 1, 0], "worker_replay_duplicated_or_lost_incident")
                check(await f.db.guardian_incidents.count_documents({}) == 1, "worker_did_not_keep_single_incident")
                check(state.get("ledger_version") == "ledger-1", "worker_did_not_publish_ledger_version")
                check(aware(state["source_watermark"]) == aware(state["processing_watermark"]),
                      "worker_watermarks_disagree")
                check(state.get("pending_observations") == 0 and state.get("dirty_buckets") == 0
                      and state.get("quarantined_records") == 0, "worker_left_durable_backlog")
                check(len(requests) == 5, "unexpected_worker_page_count")
                for request_phase in (1, 2):
                    pair = [params for value, params in requests if value == request_phase]
                    check(len(pair) == 2 and pair[0]["fromStartTime"] == pair[1]["fromStartTime"]
                          and pair[0]["toStartTime"] == pair[1]["toStartTime"], "worker_changed_bounds_during_cursor_read")
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                    for path in ("/api/guardian/metrics", "/api/guardian/monitoring"):
                        unauthorized = await client.get(path)
                        check(unauthorized.status_code == 401, "api_allowed_unauthenticated_ledger_read")
                    headers = {"X-Guardian-Key": api_key}
                    metrics_response = await client.get("/api/guardian/metrics", headers=headers)
                    monitoring_response = await client.get("/api/guardian/monitoring", headers=headers)
                    check(metrics_response.status_code == 200 and monitoring_response.status_code == 200,
                          "authenticated_api_read_failed")
                    metrics = metrics_response.json()
                    check(len(metrics) == 1 and metrics[0]["call_count"] == 1 and metrics[0]["error_count"] == 1
                          and metrics[0]["total_cost_usd"] == 0.75 and metrics[0]["total_tokens"] == 20,
                          "api_totals_disagree_with_accepted_observation")
                    check(metrics[0]["accounting_status"] == "ledger-1", "api_metrics_lost_accounting_version")
                    monitoring = monitoring_response.json()
                    check(monitoring["healthy"] and monitoring["status"] == "complete"
                          and monitoring["read_status"] == "complete", "api_monitoring_did_not_report_completed_worker")
                    check(monitoring["accounting_status"] == "ledger-1"
                          and monitoring["pending_observations"] == 0 and monitoring["dirty_buckets"] == 0,
                          "api_monitoring_disagrees_with_ledger")
                    check(aware(monitoring["source_watermark"]) == aware(monitoring["processing_watermark"])
                          == aware(state["source_watermark"]), "api_watermarks_disagree_with_storage")
                    for response in (metrics_response, monitoring_response):
                        check(private_cursor not in response.text and "next_cursor" not in response.text
                              and "active_window" not in response.text, "api_exposed_private_source_continuation")
    finally:
        if source is not None:
            source.close()
        if new_default_routes and default_source is not None:
            default_source.close()
        if new_default_db and default_db is not None:
            default_db.close()
        # server imports configure logging; restore the harness caller's state.
        for handler in list(root_logger.handlers):
            if handler not in original_handlers:
                root_logger.removeHandler(handler)
                handler.close()
        root_logger.setLevel(original_level)


async def run_suite(uri):
    suite = Suite(uri)
    try:
        version = await suite.preflight()
        for name, test in (
            ("transaction_abort", abort_is_atomic), ("restart_rebuild", restart_and_rebuild),
            ("concurrent_replay", concurrent_replay), ("lease_takeover", expired_owner_is_fenced),
            ("identity_conflict", conflicts_remove_trusted_cost), ("ambiguous_commit", ambiguous_commit_is_once),
            ("transient_transaction_retry", transient_write_retries_whole_transaction),
            ("atomic_page_checkpoint", page_checkpoint_is_atomic),
            ("atomic_incident_resolution", incidents_and_completion_are_atomic),
            ("legacy_cutover_guard", legacy_totals_require_explicit_cutover),
            ("bson_aggregate_overflow", bson_aggregate_overflow_stays_explicit),
            ("known_invalid_identity_order", known_invalid_identity_is_order_independent),
            ("worker_authenticated_api_late_replay", worker_to_authenticated_api_recovers_late_observation),
        ):
            await suite.run(name, test)
        failed = sum(result["status"] != "passed" for result in suite.results)
        from importlib.metadata import version as package_version
        return {"status": "failed" if failed or suite.owned else "passed", "mongo_version": version,
                "python_version": sys.version.split()[0], "pymongo_version": package_version("pymongo"),
                "motor_version": package_version("motor"), "finished_at": datetime.now(timezone.utc).isoformat(),
                "replica_members": 1, "passed": len(suite.results) - failed, "failed": failed,
                "cleanup_complete": not suite.owned, "tests": suite.results}
    finally:
        suite.admin.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mongo-url", help="Explicit localhost-only URI for the isolated guardian-r102 replica set")
    args = parser.parse_args(argv)
    if not args.mongo_url:
        parser.print_help()
        return 0
    try:
        uri = validate_url(args.mongo_url)
        load_dependencies()
        result = asyncio.run(run_suite(uri))
    except Exception as error:
        result = {"status": "failed", "error_type": type(error).__name__}
        if isinstance(error, CheckFailed):
            result["code"] = str(error)
    print(json.dumps(result, indent=2))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
