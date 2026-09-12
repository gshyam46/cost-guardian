#!/usr/bin/env python
"""Monitoring rules through real localhost HTTP and marker-owned Mongo cases.

No arguments print help with only the standard library. An explicit localhost
guardian-r102 replica is required for execution. No .env, provider, customer or
pre-existing application database is read. Case databases are removed only after
checking their random name and ownership marker. Reports contain fixed checks
and synthetic counts, never credentials, raw events or database exception text.
"""
from __future__ import annotations

import argparse
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
import json
import logging
from pathlib import Path
import sys
from unittest.mock import AsyncMock, patch
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
POLICY_COLLECTION = "guardian_monitoring_policies"
AUDIT_COLLECTION = "guardian_identity_audit"
RULES = {"max_call_cost_usd": "0.05", "max_call_latency_ms": 1000, "alert_on_errors": True}
RELAXED = {"max_call_cost_usd": "1", "max_call_latency_ms": 10000, "alert_on_errors": False}


def dependencies():
    sys.path.insert(0, str(ROOT / "tools"))
    global mongo, capture, identity, PolicyStore, PolicyError, pin_policy
    import test_mongo_ledger as mongo
    import test_mongo_capture as capture
    import test_mongo_identity as identity
    capture.load_dependencies()
    from policies.store import PolicyStore, pin_policy
    from policies.errors import PolicyError


async def owner(f, configured=None):
    configured = configured or identity.settings()
    store = capture.IdentityStore(f.db, configured)
    token = await store.create_session({"issuer": configured.issuer, "subject": "owner-subject"})
    actor = await store.authenticate(token)
    return configured, store, token, actor


async def denied(awaitable, status, diagnostic):
    try:
        await awaitable
    except Exception as error:
        mongo.check(isinstance(error, (PolicyError, identity.IdentityError))
                    and error.status_code == status, diagnostic + "_wrong_error")
    else:
        raise mongo.CheckFailed(diagnostic)


async def policy_audits(f):
    return await f.db[AUDIT_COLLECTION].find({"action": "update_monitoring_policy"}).to_list(20)


def event(identifier, *, cost=None, latency=50, status="success", trace="synthetic-policy-run"):
    start = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(seconds=10)
    return {"observation_id": identifier, "trace_id": trace, "agent_name": "synthetic-policy-agent",
        "model": "synthetic/model", "started_at": start.isoformat(),
        "ended_at": (start + timedelta(milliseconds=latency)).isoformat(), "status": status,
        "cost_usd": cost, "input_tokens": 2, "output_tokens": 1, "total_tokens": 3}


def envelope(events, *, test=False):
    return {"schema_version": 1, "batch_id": str(uuid4()), "test_mode": test, "events": events}


async def http_owner(f, configured, client):
    _, store, token, actor = await owner(f, configured)
    client.cookies.set(configured.session_cookie, token)
    response = await client.get("/api/guardian/access")
    mongo.check(response.status_code == 200, "named_owner_access_failed")
    headers = {"Origin": configured.ui_origin, "X-Guardian-CSRF": response.json()["csrf_token"]}
    return store, actor, headers


@asynccontextmanager
async def http_api(f):
    async with capture.http_api(f) as values:
        import policies.routes as routes
        with patch.object(routes, "db", f.db):
            yield values


async def http_customer_path(f):
    async with http_api(f) as (configured, client):
        _, actor, headers = await http_owner(f, configured, client)
        response = await client.get("/api/guardian/monitoring-policy")
        mongo.check(response.status_code == 200 and response.json()["revision"] == 0
                    and response.json()["can_manage"], "initial_policy_not_visible_to_owner")
        response = await client.put("/api/guardian/monitoring-policy", headers=headers,
            json={"expected_revision": 0, "rules": RULES})
        mongo.check(response.status_code == 200 and response.json()["revision"] == 1
                    and response.json()["rules"] == RULES, "owner_http_save_failed")
        response = await client.post("/api/guardian/ingestion-keys", headers=headers,
            json={"label": "Synthetic monitoring proof", "expires_in_days": 7, "request_id": str(uuid4())})
        mongo.check(response.status_code == 201, "owner_ingestion_key_failed")
        token = response.json()["token"]
        machine = {"X-Guardian-Ingest-Key": token}
        trace = "policy-run-" + uuid4().hex
        rows = [event("below", cost="0.02", trace=trace),
                event("equal", cost="0.05", latency=1000, trace=trace),
                event("above", cost="0.050000000001", latency=1001, trace=trace),
                event("unknown", status="unknown", trace=trace),
                event("reported-error", cost="0", status="error", trace=trace)]
        response = await client.post("/api/guardian/ingest/events", headers=machine,
            json=envelope([event("test-only", cost="99", latency=20000)], test=True))
        mongo.check(response.status_code == 202 and response.json()["processing"] == "test_only",
                    "test_rule_handshake_failed")
        mongo.check(await f.db.guardian_capture_inbox.count_documents({}) == 0, "test_traffic_entered_policy_evaluation")
        batch = envelope(rows)
        response = await client.post("/api/guardian/ingest/events", headers=machine, json=batch)
        mongo.check(response.status_code == 202 and response.json()["received"] == 5, "actual_http_events_not_received")
        await f.ledger.release(f.lease)
        await capture.poll_direct_once(f.db, configured)
        response = await client.get("/api/guardian/incidents")
        mongo.check(response.status_code == 200 and len(response.json()) == 3, "coldstart_rules_not_exactly_three_findings")
        incidents = response.json()
        reasons = {row["evidence"].get("reason"): row for row in incidents}
        mongo.check(set(reasons) == {"cost_limit_exceeded", "latency_limit_exceeded", "reported_call_error"},
                    "configured_finding_reasons_incorrect")
        expected = {"cost_limit_exceeded": ("cost_usd", "0.050000000001", "0.05", "gt"),
                    "latency_limit_exceeded": ("latency_ms", 1001, 1000, "gt"),
                    "reported_call_error": ("status", "error", "error", "eq")}
        for reason, (metric, observed, threshold, comparison) in expected.items():
            evidence = reasons[reason]["evidence"]
            mongo.check(evidence["policy_revision"] == 1 and evidence["metric"] == metric
                        and evidence["observed_value"] == observed and evidence["threshold_value"] == threshold
                        and evidence["comparison"] == comparison, "threshold_evidence_not_exact")
        response = await client.get("/api/guardian/live/runs/" + trace)
        mongo.check(response.status_code == 200 and len(response.json()["calls"]) == 5
                    and response.json()["cost_usd"] is None, "run_evidence_or_unknown_cost_missing")
        response = await client.get("/api/guardian/metrics")
        mongo.check(response.status_code == 200 and sum(row["call_count"] for row in response.json()) == 5,
                    "test_or_replayed_calls_inflated_metrics")
        saved_resolutions = {}
        for row in incidents:
            response = await client.post("/api/guardian/incidents/" + row["id"] + "/resolve", headers=headers)
            mongo.check(response.status_code == 200 and response.json()["status"] == "resolved", "owner_resolve_failed")
            saved_resolutions[row["id"]] = response.json()["resolved_at"]
        response = await client.put("/api/guardian/monitoring-policy", headers=headers,
            json={"expected_revision": 1, "rules": RELAXED})
        mongo.check(response.status_code == 200 and response.json()["revision"] == 2, "later_policy_save_failed")
        response = await client.post("/api/guardian/ingest/events", headers=machine, json=batch)
        mongo.check(response.status_code == 202 and response.json()["replayed"], "historical_batch_replay_failed")
        await capture.poll_direct_once(f.db, configured)
        response = await client.get("/api/guardian/incidents")
        replayed = response.json()
        mongo.check(response.status_code == 200 and len(replayed) == 3
                    and all(row["status"] == "resolved" and row["resolved_at"] == saved_resolutions[row["id"]]
                            and row["evidence"]["policy_revision"] == 1 for row in replayed),
                    "policy_edit_or_replay_reopened_historical_incident")
        stored = await f.db.guardian_observations.find({}).to_list(10)
        mongo.check(len(stored) == 5 and all(row["monitoring_policy"]["revision"] == 1 for row in stored),
                    "historical_observation_policy_changed")
        audits = await policy_audits(f)
        mongo.check(len(audits) == 2 and all(row["actor"]["id"] == actor.actor["id"] for row in audits),
                    "owner_policy_audits_missing")
        mongo.check(token not in json.dumps(audits, default=str), "policy_audit_leaked_ingestion_key")
        f.suite.details["actual_http"] = {"transport": "localhost_http", "production_events": 5,
            "test_events": 1, "coldstart_findings": 3, "strict_equality_no_finding": True,
            "unknown_cost_no_finding": True, "exact_decimal_threshold": True,
            "saved_revisions": 2, "historical_policy_revision": 1, "resolved_after_replay": 3}


async def concurrent_compare_and_swap(f):
    configured, _, _, actor = await owner(f)
    policies = PolicyStore(f.db, configured)
    outcomes = await asyncio.gather(policies.save(actor, 0, RULES), policies.save(actor, 0, RELAXED), return_exceptions=True)
    winners = [value for value in outcomes if isinstance(value, dict)]
    losers = [value for value in outcomes if isinstance(value, PolicyError)]
    mongo.check(len(winners) == len(losers) == 1 and losers[0].status_code == 409
                and losers[0].code == "policy_revision_conflict", "concurrent_policy_save_not_single_winner")
    # Treat the winner's acknowledgement as lost: read-back is authoritative and
    # repeating the old expected revision must not create another revision/audit.
    current = await policies.get(actor)
    mongo.check(current["revision"] == 1 and current["rules"] == winners[0]["rules"], "lost_receipt_readback_incorrect")
    await denied(policies.save(actor, 0, RULES), 409, "stale_retry_created_new_revision")
    mongo.check(len(await policy_audits(f)) == 1 and (await policies.get(actor))["revision"] == 1,
                "compare_and_swap_duplicate_audit")


async def audit_failure_rolls_back(f):
    configured, _, _, actor = await owner(f)
    policies = PolicyStore(f.db, configured)
    before = await f.db.guardian_auth_sessions.find_one({"_id": actor.session_id})
    await f.db.create_collection(AUDIT_COLLECTION, validator={"synthetic_required_field": {"$exists": True}})
    await denied(policies.save(actor, 0, RULES), 503, "audit_failure_committed_policy")
    mongo.check((await policies.get(actor))["revision"] == 0 and not await policy_audits(f), "audit_failure_left_partial_policy")
    after = await f.db.guardian_auth_sessions.find_one({"_id": actor.session_id})
    mongo.check(after["fence"] == before["fence"] and f.events.started_counts["abortTransaction"] >= 1,
                "audit_abort_left_authority_touch")
    await f.db.command({"collMod": AUDIT_COLLECTION, "validator": {}})
    mongo.check((await policies.save(actor, 0, RULES))["revision"] == 1
                and len(await policy_audits(f)) == 1, "policy_audit_recovery_failed")


class PauseWrite:
    """Pause one real transaction write; selectors/documents are never retained."""
    WRITES = {"find_one_and_update", "update_one", "insert_one", "replace_one"}

    def __init__(self, collection, entered, release, *, after):
        self.collection, self.entered, self.release, self.after = collection, entered, release, after
        self.once = False

    def __getattr__(self, name):
        target = getattr(self.collection, name)
        if name not in self.WRITES:
            return target

        async def execute(*args, **kwargs):
            if self.once or kwargs.get("session") is None:
                return await target(*args, **kwargs)
            self.once = True
            if self.after:
                result = await target(*args, **kwargs)
            self.entered.set()
            await asyncio.wait_for(self.release.wait(), 10)
            return result if self.after else await target(*args, **kwargs)
        return execute


class DatabaseProxy:
    def __init__(self, database, name, collection):
        self.database, self.name, self.collection = database, name, collection

    def __getattr__(self, name):
        return self.collection if name == self.name else getattr(self.database, name)

    def __getitem__(self, name):
        return self.collection if name == self.name else self.database[name]

    def get_collection(self, name, **kwargs):
        target = self.database.get_collection(name, **kwargs)
        if name == self.name:
            self.collection.collection = target
            return self.collection
        return target

    def with_options(self, **kwargs):
        return DatabaseProxy(self.database.with_options(**kwargs), self.name, self.collection)


async def stop_tasks(release, *tasks):
    release.set()
    for task in tasks:
        if task is not None and not task.done():
            task.cancel()
    await asyncio.gather(*(task for task in tasks if task is not None), return_exceptions=True)


async def logout_save_ordering(f):
    configured, identities, token, actor = await owner(f)
    entered, release = asyncio.Event(), asyncio.Event()
    proxy = DatabaseProxy(f.db, "guardian_auth_sessions", PauseWrite(f.db.guardian_auth_sessions, entered, release, after=False))
    policies = PolicyStore(proxy, configured)
    saving = asyncio.create_task(policies.save(actor, 0, RULES))
    try:
        await asyncio.wait_for(entered.wait(), 5)
        await identities.logout(actor)
        release.set()
        await denied(saving, 401, "logged_out_owner_committed_policy")
        mongo.check(await f.db[POLICY_COLLECTION].count_documents({"revision": {"$gt": 0}}) == 0,
                    "logout_winner_left_policy_mutation")
        mongo.check(not await policy_audits(f), "logout_winner_created_policy_audit")
    finally:
        await stop_tasks(release, saving)

    _, identities, token, actor = await owner(f, configured)
    entered, release = asyncio.Event(), asyncio.Event()
    proxy = DatabaseProxy(f.db, "guardian_auth_sessions", PauseWrite(f.db.guardian_auth_sessions, entered, release, after=True))
    saving = asyncio.create_task(PolicyStore(proxy, configured).save(actor, 0, RULES))
    logging_out = None
    try:
        await asyncio.wait_for(entered.wait(), 5)
        logging_out = asyncio.create_task(identities.logout(actor))
        done, _ = await asyncio.wait({logging_out}, timeout=0.15)
        mongo.check(not done, "logout_finished_while_save_owned_authority_write")
        release.set()
        mongo.check((await saving)["revision"] == 1, "authorized_first_save_failed")
        await logging_out
        await denied(PolicyStore(f.db, configured).save(actor, 1, RELAXED), 401, "revoked_owner_saved_again")
        mongo.check(len(await policy_audits(f)) == 1, "logout_save_ordering_audit_incorrect")
    finally:
        await stop_tasks(release, saving, logging_out)


async def unevaluated_rows(f, count=2):
    configured, actor, _, created, service = await capture.setup(f)
    rows = [event("pin-" + str(index), cost="0.1") for index in range(count)]
    await service.ingest(created["token"], capture.decode_batch(envelope(rows), configured))
    await f.ledger.release(f.lease)
    with patch.object(mongo.ObservationLedger, "process_pending", AsyncMock(return_value=(0, 0))):
        await capture.poll_direct_once(f.db, configured)
    f.lease = await f.ledger.acquire("policy-proof-" + f.owner)
    mongo.check(f.lease is not None, "policy_pin_test_lease_unavailable")
    stored = await f.db.guardian_observations.find({}).sort("metric.observation_id", 1).to_list(count)
    mongo.check(len(stored) == count and all(row["pending"] and not row.get("monitoring_policy") for row in stored),
                "pin_test_rows_not_unevaluated")
    return configured, actor, stored


async def pin_before_first_save(f):
    configured, actor, rows = await unevaluated_rows(f)
    # An existing empty namespace isolates unique-document locking from Mongo's
    # separate transactional catalog-creation conflict/retry mechanism.
    await f.db.create_collection(POLICY_COLLECTION)
    entered, release = asyncio.Event(), asyncio.Event()
    proxy = DatabaseProxy(f.db, POLICY_COLLECTION, PauseWrite(f.db[POLICY_COLLECTION], entered, release, after=True))
    ledger = mongo.ObservationLedger(proxy, configured.connection_id)
    pinning = asyncio.create_task(pin_policy(ledger, f.lease, rows[0]))
    saving = None
    try:
        await asyncio.wait_for(entered.wait(), 5)
        saving = asyncio.create_task(PolicyStore(f.db, configured).save(actor, 0, RULES))
        done, _ = await asyncio.wait({saving}, timeout=0.15)
        mongo.check(not done, "first_save_bypassed_default_pin_write")
        release.set()
        pinned = await pinning
        mongo.check(pinned["revision"] == 0 and (await saving)["revision"] == 1, "default_pin_first_order_incorrect")
        current = await f.db.guardian_observations.find_one({"_id": rows[0]["_id"]})
        mongo.check((await pin_policy(f.ledger, f.lease, current)) == pinned, "retry_replaced_pinned_default_rules")
        mongo.check((await pin_policy(f.ledger, f.lease, rows[1]))["revision"] == 1, "later_pin_missed_saved_policy")
    finally:
        await stop_tasks(release, pinning, saving)


async def save_before_first_pin(f):
    configured, actor, rows = await unevaluated_rows(f)
    await f.db.create_collection(POLICY_COLLECTION)
    entered, release = asyncio.Event(), asyncio.Event()
    proxy = DatabaseProxy(f.db, POLICY_COLLECTION, PauseWrite(f.db[POLICY_COLLECTION], entered, release, after=True))
    saving = asyncio.create_task(PolicyStore(proxy, configured).save(actor, 0, RULES))
    pinning = None
    try:
        await asyncio.wait_for(entered.wait(), 5)
        pinning = asyncio.create_task(pin_policy(f.ledger, f.lease, rows[0]))
        done, _ = await asyncio.wait({pinning}, timeout=0.15)
        mongo.check(not done, "first_pin_bypassed_policy_save_write")
        release.set()
        mongo.check((await saving)["revision"] == 1 and (await pinning)["revision"] == 1,
                    "save_first_pin_used_old_rules")
        await f.db.guardian_observations.update_one({"_id": rows[1]["_id"]}, {"$set": {"completed_rules": ["cost_anomaly:1"]}})
        legacy = await f.db.guardian_observations.find_one({"_id": rows[1]["_id"]})
        mongo.check((await pin_policy(f.ledger, f.lease, legacy))["revision"] == 0,
                    "partially_evaluated_legacy_row_adopted_new_rules")
    finally:
        await stop_tasks(release, saving, pinning)


async def first_collection_creation_race(f):
    configured, actor, rows = await unevaluated_rows(f)
    mongo.check(POLICY_COLLECTION not in await f.db.list_collection_names(), "policy_namespace_not_fresh")
    entered, release = asyncio.Event(), asyncio.Event()
    proxy = DatabaseProxy(f.db, POLICY_COLLECTION, PauseWrite(f.db[POLICY_COLLECTION], entered, release, after=True))
    pinning = asyncio.create_task(pin_policy(mongo.ObservationLedger(proxy, configured.connection_id), f.lease, rows[0]))
    saving = None
    try:
        await asyncio.wait_for(entered.wait(), 5)
        saving = asyncio.create_task(PolicyStore(f.db, configured).save(actor, 0, RULES))
        done, _ = await asyncio.wait({saving}, timeout=0.15)
        # Mongo may let the competing transaction create/commit the namespace,
        # then abort and retry the earlier catalog writer. A write returning is
        # not a committed snapshot; verify the eventual policy, not sleep order.
        committed_while_pin_paused = bool(done)
        if committed_while_pin_paused:
            mongo.check((await saving)["revision"] == 1, "first_namespace_save_failed")
        release.set()
        pinned, saved = await asyncio.gather(pinning, saving)
        mongo.check(saved["revision"] == 1 and pinned["revision"] in (0, 1), "first_namespace_race_did_not_complete")
        if committed_while_pin_paused:
            mongo.check(pinned["revision"] == 1, "namespace_retry_pinned_stale_policy_after_save_commit")
        persisted = await f.db.guardian_observations.find_one({"_id": rows[0]["_id"]})
        mongo.check(persisted["monitoring_policy"] == pinned, "namespace_race_snapshot_not_durable")
        mongo.check((await pin_policy(f.ledger, f.lease, persisted)) == pinned, "namespace_race_retry_changed_pin")
        mongo.check((await pin_policy(f.ledger, f.lease, rows[1]))["revision"] == 1,
                    "namespace_race_later_pin_missed_committed_rules")
        mongo.check(await f.db[POLICY_COLLECTION].count_documents({}) == 1 and len(await policy_audits(f)) == 1,
                    "namespace_race_duplicated_policy_or_audit")
        f.suite.details["initial_collection_race"] = {"both_transactions_completed": True,
            "eventual_pinned_revision": pinned["revision"], "saved_revision": 1,
            "save_committed_while_pin_paused": committed_while_pin_paused, "snapshot_stable_on_retry": True}
    finally:
        await stop_tasks(release, pinning, saving)


async def run_suite(uri):
    suite = mongo.Suite(uri)
    suite.details = {}
    started = asyncio.get_running_loop().time()
    try:
        version = await suite.preflight()
        for name, function in (("actual_http_customer_policy_path", http_customer_path),
                ("concurrent_revision_cas_and_lost_receipt_readback", concurrent_compare_and_swap),
                ("policy_audit_failure_rollback", audit_failure_rolls_back),
                ("logout_and_save_transaction_ordering", logout_save_ordering),
                ("default_pin_before_first_save_and_retry", pin_before_first_save),
                ("first_save_before_pin_and_legacy_partial", save_before_first_pin),
                ("first_policy_collection_creation_race", first_collection_creation_race)):
            await suite.run(name, function)
        failed = sum(result["status"] != "passed" for result in suite.results)
        return {"status": "failed" if failed or suite.owned else "passed", "mongo_version": version,
            "finished_at": datetime.now(timezone.utc).isoformat(), "passed": len(suite.results) - failed,
            "failed": failed, "cleanup_complete": not suite.owned,
            "duration_seconds": round(asyncio.get_running_loop().time() - started, 3),
            "tests": suite.results, "evidence": suite.details}
    finally:
        suite.admin.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mongo-url", help="Explicit localhost-only guardian-r102 replica-set URI")
    parser.add_argument("--report", help="Optional safe JSON artifact under tools/reports")
    args = parser.parse_args(argv)
    if not args.mongo_url:
        parser.print_help()
        return 0
    report = None
    try:
        sys.path.insert(0, str(ROOT / "tools"))
        import test_mongo_ledger as safe_mongo
        uri = safe_mongo.validate_url(args.mongo_url)
        if args.report:
            candidate = Path(args.report).resolve()
            safe_mongo.check(candidate.is_relative_to((ROOT / "tools" / "reports").resolve()), "report_path_outside_reports")
            report = candidate
        dependencies()
        logging.getLogger("httpx").setLevel(logging.WARNING)
        result = asyncio.run(run_suite(uri))
    except Exception as error:
        result = {"status": "failed", "error_type": type(error).__name__}
        if "safe_mongo" in locals() and isinstance(error, safe_mongo.CheckFailed):
            result["code"] = str(error)
    rendered = json.dumps(result, indent=2)
    if report:
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
