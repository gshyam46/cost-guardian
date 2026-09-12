#!/usr/bin/env python
"""Real identity/session transactions in owned temporary localhost databases.

No arguments print help. Uses the guardian-r102 single-member test replica set
and the existing owner-marker cleanup rules. Does not read .env, contact an
identity provider, print session tokens, or alter pre-existing databases.
"""
from __future__ import annotations

import argparse
import asyncio
from dataclasses import replace
from datetime import datetime, timezone
import json

import test_mongo_ledger as mongo_checks


check = mongo_checks.check
ISSUER = "https://identity.example.invalid"


def load_dependencies():
    mongo_checks.load_dependencies()
    global IdentityError, IdentityStore, Member, Settings, Incident, MongoIncidentStore
    from identity.errors import IdentityError
    from identity.store import IdentityStore
    from identity.settings import Member, Settings
    from guardian.incident import Incident
    from guardian.store import MongoIncidentStore

    class IdentityEvents(mongo_checks.CommandEvents):
        def __init__(self):
            super().__init__()
            self.identity_commands = []

        def started(self, event):
            super().started(event)
            collection = event.command.get(event.command_name)
            if isinstance(collection, str) and collection.startswith("guardian_auth_"):
                # Retain option metadata only, never selectors or secret values.
                self.identity_commands.append({"name": event.command_name, "collection": collection,
                    "transaction": event.command.get("autocommit") is False,
                    "read_concern": dict(event.command.get("readConcern", {})),
                    "write_concern": dict(event.command.get("writeConcern", {}))})

    mongo_checks.CommandEvents = IdentityEvents


def settings(**changes):
    configured = Settings(mode="oidc", issuer=ISSUER, client_id="synthetic-client",
        client_secret="synthetic-secret", public_url="https://guardian.example.invalid",
        ui_origin="https://guardian.example.invalid", organization_id="synthetic-organization",
        project_id="synthetic-project", environment="test", project_name="Synthetic Project",
        connection_id="primary", members={
            "operator-subject": Member("operator-subject", "operator", "Synthetic Operator"),
            "owner-subject": Member("owner-subject", "owner", "Synthetic Owner"),
            "viewer-subject": Member("viewer-subject", "viewer", "Synthetic Viewer"),
        })
    return replace(configured, **changes)


async def principal(store, subject="operator-subject", previous_token=None):
    token = await store.create_session({"issuer": ISSUER, "subject": subject}, previous_token=previous_token)
    return token, await store.authenticate(token)


async def incident(db, identifier="synthetic-incident"):
    value = Incident(id=identifier, detector="cost_anomaly", severity="high", title="Synthetic",
        summary="Synthetic private incident content", evidence={"not_for_audit": "synthetic-private-evidence"},
        trace_ids=[], agent_name="synthetic-agent")
    await MongoIncidentStore(db).create_if_absent(value)
    return value


async def expect_denied(awaitable, status, code):
    try:
        await awaitable
    except IdentityError as error:
        check(error.status_code == status, code + "_wrong_status")
    else:
        raise mongo_checks.CheckFailed(code)


async def one_use_browser_state(f):
    store = IdentityStore(f.db, settings())
    flow = await store.create_flow("127.0.0.1")
    wrong = await store.create_flow("127.0.0.2")
    await expect_denied(store.consume_flow(flow["state"], wrong["browser_token"]), 401, "cross_browser_state_accepted")
    results = await asyncio.gather(*(
        store.consume_flow(flow["state"], flow["browser_token"]) for _ in range(16)
    ), return_exceptions=True)
    winners = [value for value in results if isinstance(value, dict)]
    check(len(winners) == 1, "state_consumed_more_or_less_than_once")
    check(all(isinstance(value, dict) or isinstance(value, IdentityError) and value.status_code == 401
              for value in results), "state_consumption_unexpected_failure")
    check(winners[0]["nonce"] == flow["nonce"] and winners[0]["code_verifier"] == flow["code_verifier"],
          "state_cryptographic_binding_changed")
    await store.consume_flow(wrong["state"], wrong["browser_token"])
    check(await f.db.guardian_auth_flows.count_documents({}) == 0, "consumed_flow_persisted")
    indexes = await f.db.guardian_auth_flows.index_information()
    check(any(index.get("expireAfterSeconds") == 0 for index in indexes.values()), "flow_cleanup_ttl_missing")
    consumes = [value for value in f.events.identity_commands
                if value["name"] == "findAndModify" and value["collection"] == "guardian_auth_flows"]
    check(bool(consumes) and all(value["write_concern"].get("w") == "majority"
                                and value["write_concern"].get("wtimeout") == 3000 for value in consumes),
          "state_consumption_not_majority_acknowledged")


async def conflicting_first_binding(f):
    first = IdentityStore(f.db, settings(project_id="project-a"))
    second = IdentityStore(f.db, settings(project_id="project-b"))
    outcomes = await asyncio.gather(first.ensure_binding(), second.ensure_binding(), return_exceptions=True)
    check(sum(value is None for value in outcomes) == 1, "binding_had_multiple_winners")
    check(sum(isinstance(value, IdentityError) and value.status_code == 503 for value in outcomes) == 1,
          "binding_mismatch_did_not_fail_closed")
    check(await f.db.guardian_state.count_documents({"_id": "identity_binding"}) == 1, "multiple_deployment_bindings")
    row = await f.db.guardian_state.find_one({"_id": "identity_binding"})
    winner = first if row["project_id"] == "project-a" else second
    loser = second if winner is first else first
    token, _ = await principal(winner)
    await expect_denied(loser.authenticate(token), 503, "cross_binding_session_accepted")


async def resolution_audit_rollback(f):
    store = IdentityStore(f.db, settings())
    token, actor = await principal(store)
    await incident(f.db)
    # A real server-side audit validation failure happens after the incident
    # update, proving the transaction rolls both collections back.
    await f.db.create_collection("guardian_identity_audit", validator={"synthetic_required_field": {"$exists": True}})
    await expect_denied(store.resolve(actor, "synthetic-incident"), 503, "audit_failure_accepted")
    check((await MongoIncidentStore(f.db).get("synthetic-incident")).status == "open",
          "incident_committed_without_audit")
    check(await f.db.guardian_identity_audit.count_documents({}) == 0, "failed_audit_left_partial_record")
    session = await f.db.guardian_auth_sessions.find_one({"_id": actor.session_id})
    check(session["fence"] == 0, "aborted_resolution_left_session_write")
    check(f.events.started_counts["abortTransaction"] >= 1, "failed_audit_did_not_abort_transaction")
    await f.db.command({"collMod": "guardian_identity_audit", "validator": {}})
    resolved = await store.resolve(await store.authenticate(token), "synthetic-incident")
    check(resolved.status == "resolved", "audit_recovery_did_not_resolve")
    check(await f.db.guardian_identity_audit.count_documents({}) == 1, "audit_recovery_not_exactly_once")


async def concurrent_resolution_replays(f):
    store = IdentityStore(f.db, settings())
    _, first = await principal(store)
    _, second = await principal(store, "owner-subject")
    await incident(f.db)
    results = await asyncio.gather(*(
        store.resolve(first if index % 2 else second, "synthetic-incident") for index in range(12)
    ))
    check(all(value.status == "resolved" for value in results), "concurrent_resolution_not_successful")
    check(len({value.resolved_at.isoformat() for value in results}) == 1, "replay_changed_first_resolution_time")
    rows = await f.db.guardian_identity_audit.find({}).to_list(length=2)
    check(len(rows) == 1, "concurrent_resolution_duplicated_actor_audit")
    check(rows[0]["actor"]["id"] in {first.actor["id"], second.actor["id"]}, "audit_lost_winning_actor")
    check(rows[0]["project"]["project_id"] == "synthetic-project", "audit_lost_fixed_project")
    serialized = json.dumps(rows, default=str)
    check("synthetic-private-evidence" not in serialized and "Synthetic private incident content" not in serialized,
          "identity_audit_retained_incident_content")


class PauseSessionTouch:
    def __init__(self, collection, entered, release, *, after=False):
        self.collection, self.entered, self.release = collection, entered, release
        self.after, self.once = after, False

    def __getattr__(self, name):
        return getattr(self.collection, name)

    async def find_one_and_update(self, *args, **kwargs):
        if self.once or kwargs.get("session") is None:
            return await self.collection.find_one_and_update(*args, **kwargs)
        self.once = True
        if self.after:
            value = await self.collection.find_one_and_update(*args, **kwargs)
        self.entered.set()
        await asyncio.wait_for(self.release.wait(), timeout=10)
        if self.after:
            return value
        return await self.collection.find_one_and_update(*args, **kwargs)


class DatabaseProxy:
    def __init__(self, database, sessions):
        self.database, self.guardian_auth_sessions = database, sessions

    def __getattr__(self, name):
        return getattr(self.database, name)

    def __getitem__(self, name):
        return self.guardian_auth_sessions if name == "guardian_auth_sessions" else self.database[name]

    def with_options(self, **kwargs):
        self.database = self.database.with_options(**kwargs)
        self.guardian_auth_sessions.collection = self.database.guardian_auth_sessions
        return self

    def get_collection(self, name, **kwargs):
        collection = self.database.get_collection(name, **kwargs)
        if name == "guardian_auth_sessions":
            self.guardian_auth_sessions.collection = collection
            return self.guardian_auth_sessions
        return collection


async def logout_wins_before_authorization_write(f):
    store = IdentityStore(f.db, settings())
    token, actor = await principal(store)
    await incident(f.db)
    entered, release = asyncio.Event(), asyncio.Event()
    paused = IdentityStore(DatabaseProxy(f.db, PauseSessionTouch(f.db.guardian_auth_sessions, entered, release)), settings())
    resolving = asyncio.create_task(paused.resolve(actor, "synthetic-incident"))
    try:
        await asyncio.wait_for(entered.wait(), timeout=5)
        # The transaction has read its binding snapshot, but has not written the
        # session. Logout must win and force retry to observe revoked authority.
        await store.logout(actor)
        deletes = [value for value in f.events.identity_commands
                   if value["name"] == "delete" and value["collection"] == "guardian_auth_sessions"
                   and not value["transaction"]]
        check(bool(deletes) and deletes[-1]["write_concern"].get("w") == "majority",
              "logout_not_majority_acknowledged")
        await expect_denied(store.authenticate(token), 401, "logout_did_not_revoke")
        release.set()
        await expect_denied(resolving, 401, "revoked_session_committed_resolution")
        check((await MongoIncidentStore(f.db).get("synthetic-incident")).status == "open",
              "revoked_session_changed_incident")
        check(await f.db.guardian_identity_audit.count_documents({}) == 0, "revoked_session_created_audit")
    finally:
        release.set()
        if not resolving.done():
            resolving.cancel()
        await asyncio.gather(resolving, return_exceptions=True)


async def resolution_serializes_before_concurrent_logout(f):
    store = IdentityStore(f.db, settings())
    token, actor = await principal(store)
    await incident(f.db)
    entered, release = asyncio.Event(), asyncio.Event()
    paused = IdentityStore(DatabaseProxy(f.db, PauseSessionTouch(f.db.guardian_auth_sessions, entered, release, after=True)), settings())
    resolving = asyncio.create_task(paused.resolve(actor, "synthetic-incident"))
    logging_out = None
    try:
        await asyncio.wait_for(entered.wait(), timeout=5)
        # This transaction owns the session write. A completed logout cannot
        # precede its commit; afterwards the same principal cannot write again.
        logging_out = asyncio.create_task(store.logout(actor))
        done, _ = await asyncio.wait({logging_out}, timeout=0.15)
        check(not done, "logout_completed_while_older_resolution_still_held_session_write")
        release.set()
        resolved = await resolving
        await logging_out
        check(resolved.status == "resolved", "authorized_first_resolution_failed")
        await expect_denied(store.authenticate(token), 401, "serialized_logout_did_not_revoke")
        await incident(f.db, "later-incident")
        await expect_denied(store.resolve(actor, "later-incident"), 401, "revoked_principal_resolved_later_incident")
        check(await f.db.guardian_identity_audit.count_documents({}) == 1, "serialized_logout_audit_incorrect")
    finally:
        release.set()
        pending = [task for task in (resolving, logging_out) if task is not None]
        for task in pending:
            if not task.done():
                task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)


async def session_rotation_rolls_back_on_revocation_failure(f):
    store = IdentityStore(f.db, settings())
    token, _ = await principal(store)
    await f.arm(["delete"], errorCode=2)
    try:
        await expect_denied(store.create_session({"issuer": ISSUER, "subject": "owner-subject"}, previous_token=token),
                            503, "failed_rotation_returned_success")
    finally:
        await f.disarm()
    await store.authenticate(token)
    check(await f.db.guardian_auth_sessions.count_documents({}) == 1, "failed_rotation_left_replacement_session")
    replacement, _ = await principal(store, "owner-subject", previous_token=token)
    await expect_denied(store.authenticate(token), 401, "successful_rotation_kept_previous_session")
    await store.authenticate(replacement)


async def ambiguous_resolution_commit_is_not_duplicated(f):
    store = IdentityStore(f.db, settings())
    _, actor = await principal(store)
    await incident(f.db)
    before_commits = f.events.started_counts["commitTransaction"]
    await f.arm(["commitTransaction"], writeConcernError={"code": 64, "errmsg": "synthetic acknowledgement failure"},
                errorLabels=["UnknownTransactionCommitResult"])
    try:
        resolved = await store.resolve(actor, "synthetic-incident")
    finally:
        await f.disarm()
    check(resolved.status == "resolved", "ambiguous_resolution_did_not_recover")
    check(f.events.ambiguous_commits == 1, "ambiguous_commit_not_observed")
    check(f.events.started_counts["commitTransaction"] >= before_commits + 2, "ambiguous_commit_not_retried")
    check(await f.db.guardian_identity_audit.count_documents({}) == 1, "ambiguous_commit_duplicated_audit")
    session = await f.db.guardian_auth_sessions.find_one({"_id": actor.session_id})
    check(session["fence"] == 1, "ambiguous_commit_reexecuted_resolution_callback")


async def run_suite(uri):
    suite = mongo_checks.Suite(uri)
    try:
        version = await suite.preflight()
        for name, test in (
            ("browser_state_single_consumer", one_use_browser_state),
            ("fixed_binding_race", conflicting_first_binding),
            ("resolution_audit_rollback", resolution_audit_rollback),
            ("concurrent_resolution_replay", concurrent_resolution_replays),
            ("logout_wins_before_session_touch", logout_wins_before_authorization_write),
            ("resolution_serializes_before_logout", resolution_serializes_before_concurrent_logout),
            ("session_rotation_rollback", session_rotation_rolls_back_on_revocation_failure),
            ("ambiguous_resolution_commit", ambiguous_resolution_commit_is_not_duplicated),
        ):
            await suite.run(name, test)
        failed = sum(result["status"] != "passed" for result in suite.results)
        return {"status": "failed" if failed or suite.owned else "passed", "mongo_version": version,
                "finished_at": datetime.now(timezone.utc).isoformat(), "passed": len(suite.results) - failed,
                "failed": failed, "cleanup_complete": not suite.owned, "tests": suite.results}
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
        uri = mongo_checks.validate_url(args.mongo_url)
        load_dependencies()
        result = asyncio.run(run_suite(uri))
    except Exception as error:
        result = {"status": "failed", "error_type": type(error).__name__}
        if isinstance(error, mongo_checks.CheckFailed):
            result["code"] = str(error)
    print(json.dumps(result, indent=2))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
