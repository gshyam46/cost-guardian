"""Stdlib-only safety and deterministic transaction-pause harness contracts."""
import asyncio
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock

ROOT = Path(__file__).resolve().parents[2]
PATH = ROOT / "tools" / "test_mongo_policies.py"
spec = importlib.util.spec_from_file_location("policy_mongo_harness", PATH)
policy_harness = importlib.util.module_from_spec(spec)
spec.loader.exec_module(policy_harness)
sys.path.insert(0, str(ROOT / "tools"))
from harness import SYSTEM_KEYS


class Entrypoints(unittest.TestCase):
    def invoke(self, *arguments):
        environment = {key: value for key, value in os.environ.items() if key.upper() in SYSTEM_KEYS}
        environment.update(MONGO_URL="mongodb://private.invalid/customer", GUARDIAN_API_KEY="private-key-canary")
        return subprocess.run([sys.executable, "-I", "-S", str(PATH), *arguments],
            env=environment, capture_output=True, text=True, timeout=15)

    def test_help_and_no_arguments_are_offline_without_packages(self):
        for arguments in ((), ("--help",)):
            with self.subTest(arguments=arguments):
                result = self.invoke(*arguments)
                self.assertEqual(result.returncode, 0)
                self.assertIn("usage:", result.stdout)
                self.assertEqual(result.stderr, "")
                self.assertNotIn("private-key-canary", result.stdout)

    def test_remote_or_credentialed_uri_rejected_before_application_imports(self):
        result = self.invoke("--mongo-url", "mongodb://private-user:private-password@remote.invalid/customer")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(json.loads(result.stdout)["code"], "invalid_local_mongo_url")
        self.assertNotIn("private-password", result.stdout + result.stderr)
        self.assertNotIn("private-user", result.stdout + result.stderr)

    def test_report_outside_owned_artifact_directory_is_rejected(self):
        result = self.invoke("--mongo-url", "mongodb://127.0.0.1:27019/", "--report", "policy-proof-must-not-exist.json")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(json.loads(result.stdout)["code"], "report_path_outside_reports")
        self.assertFalse((ROOT / "policy-proof-must-not-exist.json").exists())


class PauseBoundary(unittest.IsolatedAsyncioTestCase):
    async def test_before_pause_has_not_obtained_transaction_write(self):
        entered, release = asyncio.Event(), asyncio.Event()
        collection = SimpleNamespace(update_one=AsyncMock(return_value="result"))
        wrapped = policy_harness.PauseWrite(collection, entered, release, after=False)
        task = asyncio.create_task(wrapped.update_one({"selector": "private"}, {}, session=object()))
        try:
            await asyncio.wait_for(entered.wait(), 1)
            collection.update_one.assert_not_awaited()
            self.assertNotIn("private", str(wrapped.__dict__))
            release.set()
            self.assertEqual(await task, "result")
            collection.update_one.assert_awaited_once()
        finally:
            await policy_harness.stop_tasks(release, task)

    async def test_after_pause_holds_completed_write_and_only_pauses_once(self):
        entered, release = asyncio.Event(), asyncio.Event()
        collection = SimpleNamespace(update_one=AsyncMock(return_value="result"))
        wrapped = policy_harness.PauseWrite(collection, entered, release, after=True)
        task = asyncio.create_task(wrapped.update_one({}, {}, session=object()))
        try:
            await asyncio.wait_for(entered.wait(), 1)
            collection.update_one.assert_awaited_once()
            self.assertFalse(task.done())
            release.set()
            self.assertEqual(await task, "result")
            release.clear()
            self.assertEqual(await asyncio.wait_for(wrapped.update_one({}, {}, session=object()), 1), "result")
            self.assertEqual(collection.update_one.await_count, 2)
        finally:
            await policy_harness.stop_tasks(release, task)


if __name__ == "__main__":
    unittest.main()
