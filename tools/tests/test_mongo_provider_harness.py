"""Stdlib entrypoint, fixture privacy and localhost lifecycle contracts."""
import asyncio
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
PATH = ROOT / "tools" / "test_mongo_providers.py"
spec = importlib.util.spec_from_file_location("provider_mongo_harness", PATH)
harness = importlib.util.module_from_spec(spec)
spec.loader.exec_module(harness)
sys.path.insert(0, str(ROOT / "tools"))
from harness import SYSTEM_KEYS


class Entrypoints(unittest.TestCase):
    def invoke(self, *arguments, script=PATH):
        environment = {key: value for key, value in os.environ.items() if key.upper() in SYSTEM_KEYS}
        environment.update(OPENAI_API_KEY="private-provider-key", MONGO_URL="mongodb://private.invalid/customer")
        return subprocess.run([sys.executable, "-I", "-S", str(script), *arguments],
            env=environment, capture_output=True, text=True, timeout=15)

    def test_help_and_no_arguments_require_no_packages(self):
        for arguments in ((), ("--help",)):
            result = self.invoke(*arguments)
            self.assertEqual(result.returncode, 0)
            self.assertIn("usage:", result.stdout)
            self.assertEqual(result.stderr, "")
            self.assertNotIn("private-provider-key", result.stdout)

    def test_python_child_is_inert_without_explicit_execution(self):
        result = self.invoke(script=harness.FIXTURES / "python_child.py")
        self.assertEqual(result.returncode, 0)
        self.assertIn("Usage:", result.stdout)
        self.assertEqual(result.stderr, "")

    def test_node_child_is_inert_without_sdk_import(self):
        environment = {key: value for key, value in os.environ.items() if key.upper() in SYSTEM_KEYS}
        result = subprocess.run([shutil.which("node"), str(harness.FIXTURES / "node_child.mjs")], env=environment,
            capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0)
        self.assertIn("Usage:", result.stdout)
        self.assertEqual(result.stderr, "")

    def test_remote_uri_rejected_without_exposing_input(self):
        result = self.invoke("--mongo-url", "mongodb://private-user:private-password@remote.invalid/customer")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(json.loads(result.stdout)["code"], "invalid_local_mongo_url")
        self.assertNotIn("private-password", result.stdout + result.stderr)

    def test_sdk_interpreter_must_be_explicit_before_imports(self):
        result = self.invoke("--mongo-url", "mongodb://127.0.0.1:27019/")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(json.loads(result.stdout)["code"], "sdk_python_required")

    def test_report_outside_artifacts_rejected(self):
        result = self.invoke("--mongo-url", "mongodb://127.0.0.1:27019/", "--report", "provider-must-not-exist.json")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(json.loads(result.stdout)["code"], "report_path_outside_reports")
        self.assertFalse((ROOT / "provider-must-not-exist.json").exists())

    def test_children_reject_external_guardian_before_sdk_import(self):
        config = {"origin": "https://private.invalid", "provider_origin": "http://127.0.0.1:12345"}
        environment = {key: value for key, value in os.environ.items() if key.upper() in SYSTEM_KEYS}
        commands = ([sys.executable, "-I", "-S", str(harness.FIXTURES / "python_child.py"), "--run-fixture"],
                    [shutil.which("node"), str(harness.FIXTURES / "node_child.mjs"), "--run-fixture"])
        for command in commands:
            with self.subTest(command=Path(command[0]).name):
                result = subprocess.run(command, input=json.dumps(config), env=environment,
                    capture_output=True, text=True, timeout=15)
                self.assertEqual(result.returncode, 1)
                self.assertEqual(json.loads(result.stdout), {"status": "failed", "phase": "configuration"})
                self.assertEqual(result.stderr, "")


class OwnedChildLifecycle(unittest.IsolatedAsyncioTestCase):
    async def tree_case(self, cancel):
        # The SDK's Windows venv launcher also introduces a child process. A
        # synchronized real grandchild listener proves tree cleanup, beyond
        # merely checking that the directly owned parent returned an exit code.
        environment = {key: value for key, value in os.environ.items() if key.upper() in SYSTEM_KEYS}
        grandchild = """const fs=require('fs'),net=require('net');
const server=net.createServer(s=>s.end());
server.listen(0,'127.0.0.1',()=>fs.writeFileSync(process.argv[1],JSON.stringify({port:server.address().port,pid:process.pid})));"""
        parent = """require('child_process').spawn(process.execPath,['-e',process.argv[1],process.argv[2]],{stdio:'inherit',windowsHide:true});
setInterval(()=>{},1000);"""
        with tempfile.TemporaryDirectory(prefix="guardian-provider-child-") as directory:
            marker = Path(directory) / "ready.json"
            task = asyncio.create_task(harness.run_owned_child(
                [shutil.which("node"), "-e", parent, grandchild, str(marker)], b"", environment, timeout=5))
            try:
                deadline = asyncio.get_running_loop().time() + 4
                while not marker.exists() and asyncio.get_running_loop().time() < deadline:
                    await asyncio.sleep(.025)
                self.assertTrue(marker.exists(), "owned grandchild did not reach readiness")
                record = json.loads(marker.read_text())
                _, writer = await asyncio.open_connection("127.0.0.1", record["port"])
                writer.close()
                await writer.wait_closed()
                if cancel:
                    task.cancel()
                    with self.assertRaises(asyncio.CancelledError): await task
                else:
                    with self.assertRaises(TimeoutError): await task
                with self.assertRaises(OSError): await asyncio.open_connection("127.0.0.1", record["port"])
            finally:
                if not task.done():
                    task.cancel()
                    try: await task
                    except (asyncio.CancelledError, TimeoutError): pass

    async def test_timeout_reaps_owned_process_tree(self):
        await self.tree_case(False)

    async def test_cancellation_reaps_owned_process_tree(self):
        await self.tree_case(True)


class LocalFixture(unittest.IsolatedAsyncioTestCase):
    async def test_actual_chunked_sse_and_listener_cleanup_keep_metadata_only(self):
        async with harness.ProviderFixture() as provider:
            host, port = provider.server.sockets[0].getsockname()
            self.assertEqual(host, "127.0.0.1")
            reader, writer = await asyncio.open_connection(host, port)
            body = json.dumps({"model": "fixture-stream", "stream": True, "input": harness.CANARY}).encode()
            writer.write(b"POST /v1/responses HTTP/1.1\r\nAuthorization: Bearer synthetic-provider-key\r\nContent-Length: "
                         + str(len(body)).encode() + b"\r\n\r\n" + body)
            await writer.drain()
            raw = await asyncio.wait_for(reader.read(), 2)
            self.assertIn(b"Transfer-Encoding: chunked", raw)
            self.assertIn(b"response.completed", raw)
            self.assertEqual(provider.requests, [{"api": "responses", "mode": "stream", "stream": True}])
            self.assertNotIn(harness.CANARY, str(provider.requests))
            writer.close()
            await writer.wait_closed()
        with self.assertRaises(OSError): await asyncio.open_connection(host, port)
        self.assertFalse(provider.tasks)

    async def test_fixture_does_not_answer_unknown_routes(self):
        async with harness.ProviderFixture() as provider:
            reader, writer = await asyncio.open_connection(*provider.server.sockets[0].getsockname())
            writer.write(b"GET /customer HTTP/1.1\r\n\r\n")
            await writer.drain()
            self.assertEqual(await asyncio.wait_for(reader.read(), 2), b"")
            self.assertFalse(provider.requests)
            writer.close()
            await writer.wait_closed()

    def test_chat_usage_chunk_is_distinct_from_finish_and_cached_not_added(self):
        _, stream = harness.fixture_reply("chat_completions", "stream", True)
        rows = [json.loads(line[6:]) for line in stream.splitlines() if line.startswith("data: {")]
        self.assertEqual(rows[1]["choices"][0]["finish_reason"], "stop")
        self.assertIsNone(rows[1]["usage"])
        self.assertEqual(rows[2]["choices"], [])
        self.assertEqual(rows[2]["usage"]["total_tokens"], 10)
        self.assertEqual(rows[2]["usage"]["prompt_tokens_details"]["cached_tokens"], 3)


if __name__ == "__main__":
    unittest.main()
