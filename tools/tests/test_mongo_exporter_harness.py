"""Independent safety checks for the optional real-Mongo exporter proof CLI."""
import asyncio
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parents[2]
PATH = ROOT / "tools" / "test_mongo_exporters.py"
spec = importlib.util.spec_from_file_location("exporter_mongo_harness", PATH)
harness = importlib.util.module_from_spec(spec)
spec.loader.exec_module(harness)
sys.path.insert(0, str(ROOT / "tools"))
from harness import SYSTEM_KEYS


class CheckFailed(Exception):
    pass


def check(condition, code):
    if not condition:
        raise CheckFailed(code)


class Entrypoints(unittest.TestCase):
    def invoke(self, *arguments):
        environment = {key: value for key, value in os.environ.items() if key.upper() in SYSTEM_KEYS}
        environment.update(MONGO_URL="mongodb://unreachable.invalid/private",
            GUARDIAN_INGEST_KEY="private-env-canary", PYTHON_DOTENV_DISABLED="1")
        return subprocess.run([sys.executable, "-I", "-S", str(PATH), *arguments],
            env=environment, capture_output=True, text=True, timeout=10)

    def test_no_arguments_and_help_do_not_need_packages_or_configuration(self):
        for arguments in ((), ("--help",)):
            with self.subTest(arguments=arguments):
                result = self.invoke(*arguments)
                self.assertEqual(result.returncode, 0)
                self.assertIn("usage:", result.stdout)
                self.assertEqual(result.stderr, "")
                self.assertNotIn("private-env-canary", result.stdout)

    def test_remote_database_is_rejected_before_dependencies_with_safe_error(self):
        result = self.invoke("--mongo-url", "mongodb://private-user:private-password@remote.invalid/private")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(json.loads(result.stdout)["code"], "invalid_local_mongo_url")
        self.assertNotIn("private-user", result.stdout + result.stderr)
        self.assertNotIn("private-password", result.stdout + result.stderr)

    def test_report_cannot_escape_tools_reports(self):
        result = self.invoke("--mongo-url", "mongodb://127.0.0.1:27019/", "--report", "exporter-proof-must-not-exist.json")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(json.loads(result.stdout)["code"], "report_path_outside_reports")
        self.assertFalse((ROOT / "exporter-proof-must-not-exist.json").exists())


class ChildBoundary(unittest.IsolatedAsyncioTestCase):
    async def test_only_stdin_carries_synthetic_credential_and_app_env_is_scrubbed(self):
        captured = {}
        result = {"status": "passed", "runtime_version": "3.13.14", "stats": {"enqueued_events": 1, "confirmed_events": 1, "rejected_events": 1,
            "pending_events": 0, "unconfirmed_events": 0, "pending_bytes": 0, "closed": True,
            "transport_active": False}}
        process = SimpleNamespace(returncode=0)

        async def communicate(data):
            captured["stdin"] = json.loads(data)
            return json.dumps(result).encode(), b""

        process.communicate = communicate

        async def spawn(*args, **kwargs):
            captured["argv"], captured["options"] = args, kwargs
            return process

        with patch.dict(harness.__dict__, {"mongo": SimpleNamespace(check=check, CheckFailed=CheckFailed), "SYSTEM_KEYS": SYSTEM_KEYS}), \
                patch.dict(os.environ, {"GUARDIAN_API_KEY": "ambient-dashboard", "OPENAI_API_KEY": "ambient-provider",
                    "MONGO_URL": "ambient-database", "PYTHONPATH": "ambient-python", "NODE_OPTIONS": "ambient-node"}), \
                patch.object(asyncio, "create_subprocess_exec", spawn):
            await harness.child("python", "http://127.0.0.1:1", "private-synthetic-key", True, "node")
        self.assertEqual(captured["stdin"]["token"], "private-synthetic-key")
        self.assertNotIn("private-synthetic-key", str(captured["argv"]))
        environment = captured["options"]["env"]
        for name in ("GUARDIAN_API_KEY", "OPENAI_API_KEY", "MONGO_URL", "PYTHONPATH", "NODE_OPTIONS"):
            self.assertNotIn(name, environment)
        self.assertIn("-S", captured["argv"])
        for name in ("SYSTEMDRIVE", "COMSPEC"):
            if name in os.environ:
                self.assertEqual(environment[name], os.environ[name])

    async def test_timeout_kills_and_reaps_only_the_owned_child(self):
        process = SimpleNamespace(returncode=None, communicate=AsyncMock(side_effect=TimeoutError),
            kill=lambda: setattr(process, "killed", True), wait=AsyncMock(), killed=False)
        with patch.dict(harness.__dict__, {"mongo": SimpleNamespace(check=check, CheckFailed=CheckFailed), "SYSTEM_KEYS": SYSTEM_KEYS}), \
                patch.object(asyncio, "create_subprocess_exec", AsyncMock(return_value=process)):
            with self.assertRaises(TimeoutError):
                await harness.child("node", "http://127.0.0.1:1", "private-synthetic-key", True, "node")
        self.assertTrue(process.killed)
        process.wait.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
