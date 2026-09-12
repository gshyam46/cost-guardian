"""Notification proof entrypoint and owned receiver safety, without packages."""
import asyncio
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
PATH = ROOT / "tools" / "test_mongo_notifications.py"
spec = importlib.util.spec_from_file_location("notification_mongo_harness", PATH)
harness = importlib.util.module_from_spec(spec)
spec.loader.exec_module(harness)
sys.path.insert(0, str(ROOT / "tools"))
from harness import SYSTEM_KEYS


class Entrypoints(unittest.TestCase):
    def invoke(self, *arguments):
        environment = {key: value for key, value in os.environ.items() if key.upper() in SYSTEM_KEYS}
        environment.update(MONGO_URL="mongodb://private.invalid/customer", GUARDIAN_SLACK_WEBHOOK_URL="private-webhook-canary")
        return subprocess.run([sys.executable, "-I", "-S", str(PATH), *arguments],
            env=environment, capture_output=True, text=True, timeout=15)

    def test_help_and_no_arguments_are_offline_without_packages(self):
        for arguments in ((), ("--help",)):
            result = self.invoke(*arguments)
            self.assertEqual(result.returncode, 0)
            self.assertIn("usage:", result.stdout)
            self.assertEqual(result.stderr, "")
            self.assertNotIn("private-webhook-canary", result.stdout)

    def test_remote_or_credentialed_uri_is_rejected_before_imports(self):
        result = self.invoke("--mongo-url", "mongodb://private-user:private-password@remote.invalid/customer")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(json.loads(result.stdout)["code"], "invalid_local_mongo_url")
        self.assertNotIn("private-password", result.stdout + result.stderr)
        self.assertNotIn("private-user", result.stdout + result.stderr)

    def test_report_outside_owned_artifact_directory_is_rejected(self):
        result = self.invoke("--mongo-url", "mongodb://127.0.0.1:27019/", "--report", "notification-proof-must-not-exist.json")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(json.loads(result.stdout)["code"], "report_path_outside_reports")
        self.assertFalse((ROOT / "notification-proof-must-not-exist.json").exists())


class OwnedReceiver(unittest.IsolatedAsyncioTestCase):
    async def test_receiver_binds_loopback_and_closes_listener(self):
        async with harness.LocalReceiver() as receiver:
            host, port = receiver.server.sockets[0].getsockname()
            self.assertEqual(host, "127.0.0.1")
            reader, writer = await asyncio.open_connection(host, port)
            body = b'{"text":"synthetic-test"}'
            writer.write(b"POST /synthetic-slack HTTP/1.1\r\nContent-Length: " + str(len(body)).encode() + b"\r\n\r\n" + body)
            await writer.drain()
            response = await reader.read()
            self.assertTrue(response.endswith(b"\r\n\r\nok"))
            self.assertEqual(receiver.requests, [{"text": "synthetic-test"}])
            writer.close()
            await writer.wait_closed()
        with self.assertRaises(OSError):
            await asyncio.open_connection(host, port)
        self.assertFalse(receiver.tasks)

    async def test_shutdown_cancels_owned_held_connection(self):
        async with harness.LocalReceiver() as receiver:
            receiver.mode = "hold"
            reader, writer = await asyncio.open_connection(*receiver.server.sockets[0].getsockname())
            writer.write(b"POST / HTTP/1.1\r\nContent-Length: 2\r\n\r\n{}")
            await writer.drain()
            await asyncio.wait_for(receiver.entered.wait(), 1)
            self.assertTrue(receiver.tasks)
        self.assertFalse(receiver.tasks)
        await asyncio.wait_for(reader.read(), 1)
        writer.close()
        await writer.wait_closed()


if __name__ == "__main__":
    unittest.main()
