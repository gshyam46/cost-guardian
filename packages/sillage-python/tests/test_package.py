"""Fast, dependency-free launcher/adapter boundary tests; no provider traffic."""
import asyncio
from contextlib import redirect_stderr, redirect_stdout
import importlib
import io
import json
import os
from pathlib import Path
import socket
import sys
import tempfile
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch

PACKAGE = Path(__file__).resolve().parents[1]
ROOT = PACKAGE.parents[1]
sys.path.insert(0, str(PACKAGE / "src"))

from sillage_observe import Configuration, ConfigurationError, Instrumentation
from sillage_observe import cli
from sillage_observe.instrumentation import _Terminal, _observe_stream

TOKEN = "cg_ingest_" + "0" * 32 + "_" + "a" * 43
CONFIG = Configuration("http://127.0.0.1:8001", TOKEN, "fixture-service", True)
ENV = {"SILLAGE_URL": CONFIG.origin, "SILLAGE_INGEST_KEY": TOKEN, "SILLAGE_ALLOW_LOCAL": "true"}
RESPONSE = {"object": "chat.completion", "choices": [{"index": 0, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5}}


class Recorder:
    def __init__(self):
        self.events, self.started, self.closed = [], [], False

    def start_call(self, **fields):
        self.started.append(fields)
        def finish(status, **usage):
            self.events.append({**fields, "status": status, **usage})
        return SimpleNamespace(finish=finish)

    def close(self, timeout=3):
        self.closed = True
        return {"confirmed": True}


class ConfigurationTests(unittest.TestCase):
    def test_modern_and_identical_legacy(self):
        mixed = {**ENV, "GUARDIAN_URL": CONFIG.origin, "GUARDIAN_INGEST_KEY": TOKEN}
        config = Configuration.from_env(mixed)
        self.assertEqual(config.origin, CONFIG.origin)
        self.assertNotIn(TOKEN, repr(config))

    def test_all_alias_conflicts_fail_without_values(self):
        for name in ("URL", "INGEST_KEY", "SERVICE_NAME", "ALLOW_LOCAL"):
            with self.subTest(name=name), self.assertRaises(ConfigurationError) as caught:
                Configuration.from_env({**ENV, "SILLAGE_" + name: "secret-a", "GUARDIAN_" + name: "secret-b"})
            self.assertNotIn("secret", str(caught.exception))

    def test_origin_restrictions(self):
        for origin in ("http://collector.example", "https://user:secret@collector.example", "https://collector.example/path", "https://collector.example?secret=1"):
            with self.subTest(origin=origin), self.assertRaises(ConfigurationError):
                Configuration(origin, TOKEN, allow_local=True)

    def test_local_requires_opt_in_and_boolean_is_literal(self):
        with self.assertRaises(ConfigurationError):
            Configuration(CONFIG.origin, TOKEN)
        for value in ("1", "TRUE", "yes", ""):
            with self.assertRaises(ConfigurationError):
                Configuration.from_env({**ENV, "SILLAGE_ALLOW_LOCAL": value})

    def test_missing_invalid_key_and_service(self):
        for values in ({}, {**ENV, "SILLAGE_INGEST_KEY": "secret"}, {**ENV, "SILLAGE_SERVICE_NAME": "customer content with spaces"}):
            with self.assertRaises(ConfigurationError):
                Configuration.from_env(values)


class PackagingTests(unittest.TestCase):
    def test_vendored_sources_match_reviewed_examples(self):
        for module in ("guardian_capture", "guardian_exporter", "guardian_openai"):
            source = (ROOT / "examples/native-capture" / (module + ".py")).read_text()
            if module == "guardian_exporter":
                source = source.replace("from guardian_capture import send_batch, target", "from .guardian_capture import send_batch, target")
            vendored = (PACKAGE / "src/sillage_observe/_vendor" / (module + ".py")).read_text()
            self.assertEqual(source.strip(), vendored.strip(), module)

    def test_import_and_check_are_inert(self):
        out, err = io.StringIO(), io.StringIO()
        with patch.dict(os.environ, ENV, clear=True), patch.object(socket.socket, "connect", side_effect=AssertionError("network")), patch("threading.Thread.start", side_effect=AssertionError("thread")), patch.object(cli, "detected_adapters", return_value={"openai": {"supported": True}}), redirect_stdout(out), redirect_stderr(err):
            self.assertEqual(cli.main(["--check"]), 0)
        result = json.loads(out.getvalue())
        self.assertFalse(result["connected"])
        self.assertFalse(result["collector_checked"])
        self.assertNotIn(TOKEN, out.getvalue() + err.getvalue())

    def test_check_distinguishes_local_settings_from_missing_adapter(self):
        for adapters in ({"openai": {"installed": False, "supported": False}},
                         {"openai": {"installed": True, "version": "99.0.0", "supported": False}}):
            out, err = io.StringIO(), io.StringIO()
            with self.subTest(adapters=adapters), patch.dict(os.environ, ENV, clear=True), patch.object(cli, "detected_adapters", return_value=adapters), redirect_stdout(out), redirect_stderr(err):
                self.assertEqual(cli.main(["--check"]), 3)
            value = json.loads(out.getvalue())
            self.assertEqual(value["configuration"], "valid")
            self.assertFalse(value["instrumentation_ready"])
            self.assertFalse(value["connected"])
            self.assertIn("no_supported_sdk_installed", err.getvalue())

    def test_check_reports_supported_adapter_without_claiming_collector_connection(self):
        adapters = {"litellm": {"installed": True, "supported": True}, "openai": {"installed": True, "supported": False}}
        out, err = io.StringIO(), io.StringIO()
        with patch.dict(os.environ, ENV, clear=True), patch.object(cli, "detected_adapters", return_value=adapters), redirect_stdout(out), redirect_stderr(err):
            self.assertEqual(cli.main(["--check"]), 0)
        value = json.loads(out.getvalue())
        self.assertTrue(value["instrumentation_ready"])
        self.assertFalse(value["collector_checked"])
        self.assertEqual(value["adapters"], adapters)
        self.assertEqual(err.getvalue(), "")


class LauncherTests(unittest.TestCase):
    def test_invalid_launch_fails_before_target_without_key_echo(self):
        with patch.dict(os.environ, {}, clear=True), redirect_stderr(io.StringIO()) as err:
            self.assertEqual(cli.main(["--", "python", "not-found.py"]), 2)
        self.assertIn("invalid_collector_origin", err.getvalue())

    def test_unsupported_process_modes(self):
        for command in (["python", "-c", "print(1)"], ["another-python", "app.py"],
                        ["python", "-m", "uvicorn", "app:app", "--reload"],
                        ["python", "-m", "uvicorn", "app:app", "--workers", "2"],
                        ["python", "-m", "uvicorn", "app:app", "--workers=2"]):
            with self.subTest(command=command), self.assertRaises(ConfigurationError):
                cli._command(command)

    def test_same_process_arguments_working_directory_and_exit_status(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "original.py"
            target.write_text("import os,sys,json\nprint(json.dumps({'args':sys.argv[1:], 'pid':os.getpid(), 'cwd':os.getcwd()}))\nraise SystemExit(7)\n")
            out, err = io.StringIO(), io.StringIO()
            original_argv, original_path = sys.argv, sys.path[:]
            with patch.dict(os.environ, ENV, clear=True), redirect_stdout(out), redirect_stderr(err), self.assertRaises(SystemExit) as exit_status:
                cli.main(["--", "python", str(target), "--arbitrary", "space argument"])
            self.assertEqual(exit_status.exception.code, 7)
            result = json.loads(out.getvalue())
            self.assertEqual(result, {"args": ["--arbitrary", "space argument"], "pid": os.getpid(), "cwd": os.getcwd()})
            self.assertIs(sys.argv, original_argv)
            self.assertEqual(sys.path, original_path)

    def test_uvicorn_environment_cannot_silently_spawn_workers(self):
        for env in ({"WEB_CONCURRENCY": "2"}, {"UVICORN_WORKERS": "2"}, {"UVICORN_RELOAD": "true"}):
            with self.subTest(env=env), patch.dict(os.environ, env, clear=True), self.assertRaises(ConfigurationError):
                cli._command(["python", "-m", "uvicorn", "app:app"])
        with patch.dict(os.environ, {"WEB_CONCURRENCY": "2"}, clear=True):
            mode, target, _args = cli._command(["python", "-m", "uvicorn", "app:app", "--workers", "1"])
        self.assertEqual((mode, target), ("module", "uvicorn"))

    def test_module_mode_restores_process_state(self):
        calls = []
        def run(name, **kwargs):
            calls.append((name, list(sys.argv), kwargs))
        with patch.dict(os.environ, ENV, clear=True), patch.object(cli.runpy, "run_module", side_effect=run), redirect_stderr(io.StringIO()):
            self.assertEqual(cli.main(["--", "python", "-m", "original_module", "a"]), 0)
        self.assertEqual(calls[0], ("original_module", ["original_module", "a"], {"run_name": "__main__", "alter_sys": True}))


class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.recorder = Recorder()
        self.diagnostics = []
        self.instrument = Instrumentation(CONFIG, exporter=self.recorder, diagnostic=self.diagnostics.append)

    def tearDown(self):
        self.instrument.close()

    def test_result_identity_metadata_allowlist_and_unknown_price(self):
        def operation(**kwargs):
            return RESPONSE
        wrapped = self.instrument._wrap(operation, "litellm", "chat_completions", False)
        self.assertIs(wrapped(model="fixture/model", messages=["PRIVATE_PROMPT"],
            metadata={"generation_name": "agent", "trace_id": "shared-run", "trace_user_id": "PRIVATE_USER", "arbitrary": "PRIVATE"}), RESPONSE)
        event = self.recorder.events[0]
        self.assertEqual((event["agent_name"], event["trace_id"], event["total_tokens"]), ("agent", "shared-run", 5))
        self.assertNotIn("PRIVATE", json.dumps(self.recorder.events))
        self.assertNotIn("cost_usd", event)

    def test_original_exception_identity_and_content_omitted(self):
        error = RuntimeError("PRIVATE_ERROR")
        def operation(**kwargs):
            raise error
        wrapped = self.instrument._wrap(operation, "litellm", "chat_completions", False)
        with self.assertRaises(RuntimeError) as caught:
            wrapped(model="fixture")
        self.assertIs(caught.exception, error)
        self.assertEqual(self.recorder.events[0]["status"], "error")
        self.assertNotIn("PRIVATE", json.dumps(self.recorder.events))

    def test_nested_sdk_capture_has_one_owner(self):
        inner = self.instrument._wrap(lambda **kwargs: RESPONSE, "openai", "chat_completions", False)
        outer = self.instrument._wrap(lambda **kwargs: inner(model="nested"), "litellm", "chat_completions", False)
        self.assertIs(outer(model="outer"), RESPONSE)
        self.assertEqual(len(self.recorder.events), 1)
        self.assertEqual(self.recorder.events[0]["model"], "outer")

    def test_export_failure_leaves_operation_unchanged(self):
        self.recorder.start_call = lambda **kwargs: (_ for _ in ()).throw(RuntimeError("secret"))
        wrapped = self.instrument._wrap(lambda **kwargs: RESPONSE, "litellm", "chat_completions", False)
        self.assertIs(wrapped(model="fixture"), RESPONSE)
        self.assertEqual(self.diagnostics, ["capture_unavailable"])

    def test_unsupported_stream_is_passed_through_with_diagnostic(self):
        stream = object()
        wrapped = self.instrument._wrap(lambda **kwargs: stream, "litellm", "chat_completions", False)
        self.assertIs(wrapped(model="fixture", stream=True), stream)
        self.assertEqual(self.recorder.events, [])
        self.assertEqual(self.diagnostics, ["litellm_streaming_not_supported"])

    def test_positional_litellm_stream_also_skips_capture(self):
        stream_result = object()
        def operation(model, messages, stream=False):
            return stream_result
        wrapped = self.instrument._wrap(operation, "litellm", "chat_completions", False)
        self.assertIs(wrapped("fixture", [], True), stream_result)
        self.assertEqual(self.recorder.events, [])
        self.assertEqual(self.diagnostics, ["litellm_streaming_not_supported"])

    def test_invalid_metadata_falls_back_without_inspecting_arbitrary_objects(self):
        class Hostile:
            def __getattribute__(self, name):
                raise AssertionError("content inspected")
        wrapped = self.instrument._wrap(lambda **kwargs: RESPONSE, "litellm", "chat_completions", False)
        self.assertIs(wrapped(model=Hostile(), metadata=Hostile()), RESPONSE)
        self.assertEqual(self.recorder.events[0]["model"], "unknown-model")

    def test_forked_exporter_is_not_reused(self):
        self.instrument._pid = -1
        wrapped = self.instrument._wrap(lambda **kwargs: RESPONSE, "litellm", "chat_completions", False)
        self.assertIs(wrapped(model="fixture"), RESPONSE)
        self.assertEqual(self.recorder.events, [])
        self.assertEqual(self.diagnostics, ["unsupported_child_process"])

    def test_double_install_and_restore_do_not_clobber_later_wrapper(self):
        value = SimpleNamespace(create=lambda **kwargs: RESPONSE)
        original = value.create
        self.instrument._patch(value, "create", "openai", "chat_completions", False)
        first = value.create
        self.instrument._patch(value, "create", "openai", "chat_completions", False)
        self.assertIs(value.create, first)
        external = lambda **kwargs: None
        value.create = external
        self.instrument.close()
        self.assertIs(value.create, external)
        self.assertIsNot(first, original)

    def test_lazy_hook_preserves_direct_import_binding(self):
        module = ModuleType("litellm")
        module.completion = lambda **kwargs: RESPONSE
        async def async_call(**kwargs):
            return RESPONSE
        module.acompletion = async_call
        self.instrument._loaded(module)
        imported_alias = module.completion
        self.assertIs(imported_alias(model="fixture"), RESPONSE)
        self.assertEqual(len(self.recorder.events), 1)

    def test_known_stream_same_object_and_chunks_finish_once(self):
        chunks = [{"id": "chunk-1", "object": "chat.completion.chunk", "choices": [{"index": 0, "finish_reason": "stop"}]},
                  {"id": "chunk-1", "object": "chat.completion.chunk", "choices": [], "usage": RESPONSE["usage"]}]
        class Stream:
            def __init__(self):
                self._iterator, self.closed = iter(chunks), False
            def __iter__(self):
                yield from self._iterator
            def close(self):
                self.closed = True
        Stream.__module__ = "openai"
        stream = Stream()
        terminal = _Terminal(self.recorder.start_call(model="fixture"))
        self.assertIs(_observe_stream(stream, terminal, "chat_completions", False), stream)
        received = list(stream)
        self.assertTrue(all(a is b for a, b in zip(chunks, received)))
        stream.close()
        self.assertEqual(len(self.recorder.events), 1)
        self.assertEqual(self.recorder.events[0]["total_tokens"], 5)

    def test_unstarted_stream_close_reports_unknown(self):
        class Stream:
            _iterator = iter(())
            def close(self):
                return "closed"
        Stream.__module__ = "openai"
        stream = Stream()
        _observe_stream(stream, _Terminal(self.recorder.start_call(model="fixture")), "responses", False)
        self.assertEqual(stream.close(), "closed")
        self.assertEqual(self.recorder.events[0]["status"], "unknown")
        self.assertIsNone(self.recorder.events[0]["total_tokens"])


class AsyncAdapterTests(unittest.IsolatedAsyncioTestCase):
    async def test_concurrent_calls_context_isolation_and_nested_suppression(self):
        recorder = Recorder()
        instrument = Instrumentation(CONFIG, exporter=recorder)
        async def sdk(**kwargs):
            await asyncio.sleep(0)
            return RESPONSE
        inner = instrument._wrap(sdk, "openai", "chat_completions", True)
        async def outer(**kwargs):
            return await inner(model="nested")
        wrapped = instrument._wrap(outer, "litellm", "chat_completions", True)
        results = await asyncio.gather(wrapped(model="a"), wrapped(model="b"))
        self.assertTrue(all(value is RESPONSE for value in results))
        self.assertEqual(len(recorder.events), 2)
        self.assertEqual({value["model"] for value in recorder.events}, {"a", "b"})
        instrument.close()

    async def test_cancellation_remains_original_and_unknown(self):
        recorder = Recorder()
        instrument = Instrumentation(CONFIG, exporter=recorder)
        error = asyncio.CancelledError("PRIVATE_CANCELLATION")
        async def operation(**kwargs):
            raise error
        wrapped = instrument._wrap(operation, "litellm", "chat_completions", True)
        with self.assertRaises(asyncio.CancelledError) as caught:
            await wrapped(model="fixture")
        self.assertIs(caught.exception, error)
        self.assertEqual(recorder.events[0]["status"], "unknown")
        self.assertNotIn("PRIVATE", json.dumps(recorder.events))
        instrument.close()


if __name__ == "__main__":
    unittest.main()
