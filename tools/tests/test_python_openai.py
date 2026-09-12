"""OpenAI usage/lifecycle acceptance without a provider SDK or external service."""
import asyncio
import copy
import gc
import importlib
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch
import weakref

ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = ROOT / "examples" / "native-capture"
sys.path.insert(0, str(EXAMPLES))
adapter = importlib.import_module("guardian_openai")
app = importlib.import_module("python_openai_app")
META = {"agent_name": "answer", "model": "configured/model"}
UNKNOWN = {"input_tokens": None, "output_tokens": None, "total_tokens": None}


def response(**changes):
    return {"id": "resp_one", "object": "response", "status": "completed",
            "usage": {"input_tokens": 12, "output_tokens": 8, "total_tokens": 20}, **changes}


def terminal(status="completed", **changes):
    return {"type": "response." + status, "response": response(status=status, **changes)}


def chat(reason="stop", **changes):
    return {"object": "chat.completion", "choices": [{"index": 0, "finish_reason": reason}],
            "usage": {"prompt_tokens": 12, "completion_tokens": 8, "total_tokens": 20}, **changes}


def chat_chunk(reason=None, **changes):
    return {"id": "chatcmpl_one", "object": "chat.completion.chunk",
            "choices": [{"index": 0, "finish_reason": reason}], **changes}


class Recorder:
    def __init__(self, fail_start=False, fail_finish=False):
        self.started, self.finished = [], []
        self.fail_start, self.fail_finish = fail_start, fail_finish

    def start_call(self, **metadata):
        if self.fail_start:
            raise RuntimeError("instrumentation failure")
        self.started.append(metadata)
        return self

    def finish(self, status, **usage):
        if self.fail_finish:
            raise RuntimeError("instrumentation failure")
        self.finished.append({"status": status, **usage})


class PythonOpenAI(unittest.TestCase):
    def test_shared_usage_fixtures_match_node_contract(self):
        fixtures = json.loads((ROOT / "tools" / "fixtures" / "openai-usage.json").read_text(encoding="utf-8"))
        self.assertGreaterEqual(len(fixtures), 20)
        for fixture in fixtures:
            with self.subTest(fixture=fixture["name"]):
                self.assertEqual(adapter.extract_openai_usage(fixture["response"], fixture["api"]), fixture["expected"])

    def stream(self, chunks, **options):
        recorder = Recorder()
        result = list(adapter.openai_stream(recorder, lambda: iter(chunks), **META, **options))
        self.assertEqual(len(result), len(chunks))
        self.assertTrue(all(first is second for first, second in zip(result, chunks)))
        self.assertEqual(len(recorder.finished), 1)
        return recorder.finished[0]

    def test_extracts_both_apis_without_mutation(self):
        for api, value in [("responses", response()), ("chat_completions", chat())]:
            before = copy.deepcopy(value)
            result = adapter.extract_openai_usage(value, api)
            self.assertEqual(result, {"input_tokens": 12, "output_tokens": 8, "total_tokens": 20})
            result["input_tokens"] = 99
            self.assertEqual(value, before)

    def test_usage_validation_unknown_zero_total_only_and_checked_sum(self):
        fixtures = [({}, UNKNOWN), ({"input_tokens": 0, "output_tokens": 0}, dict.fromkeys(UNKNOWN, 0)),
            ({"total_tokens": 7}, {**UNKNOWN, "total_tokens": 7}),
            ({"input_tokens": 12, "output_tokens": 8}, {"input_tokens": 12, "output_tokens": 8, "total_tokens": 20})]
        for usage, expected in fixtures:
            with self.subTest(usage=usage):
                self.assertEqual(adapter.extract_openai_usage({"usage": usage}), expected)
        for value in (True, "12", 12.0, -1, 2**53, float("nan"), object()):
            with self.subTest(value=type(value)):
                self.assertEqual(adapter.extract_openai_usage(response(usage={"input_tokens": value, "output_tokens": 2})), UNKNOWN)
        for usage in [{"input_tokens": 9, "total_tokens": 8},
            {"input_tokens": 2**53 - 1, "output_tokens": 1}, {"input_tokens": 12, "output_tokens": 8, "total_tokens": 21}]:
            self.assertEqual(adapter.extract_openai_usage(response(usage=usage)), UNKNOWN)

    def test_cache_reasoning_subsets_are_not_added_to_parent_counts(self):
        value = response()
        value["usage"].update(input_tokens_details={"cached_tokens": 4, "cache_write_tokens": 2, "unsupported": object()},
                              output_tokens_details={"reasoning_tokens": 6})
        self.assertEqual(adapter.extract_openai_usage(value)["total_tokens"], 20)
        for name, details in [("input_tokens_details", {"cached_tokens": 13}),
            ("input_tokens_details", {"cache_write_tokens": True}), ("output_tokens_details", {"reasoning_tokens": 9})]:
            invalid = response()
            invalid["usage"][name] = details
            self.assertEqual(adapter.extract_openai_usage(invalid), UNKNOWN)
        self.assertEqual(adapter.extract_openai_usage({"usage": {"total_tokens": 3,
            "input_tokens_details": {"cached_tokens": 4}}}), UNKNOWN)

    def test_getters_and_serialization_hooks_are_never_called(self):
        touched = []

        class Hostile:
            @property
            def usage(self):
                touched.append("getter")
                raise AssertionError()

            def model_dump(self):
                touched.append("serializer")
                raise AssertionError()

        self.assertEqual(adapter.extract_openai_usage(Hostile()), UNKNOWN)
        value = response(output=Hostile(), error=Hostile(), model=Hostile())
        recorder = Recorder()
        self.assertIs(adapter.openai_call(recorder, lambda: value, **META), value)
        self.assertEqual(touched, [])
        self.assertEqual(recorder.finished[0]["total_tokens"], 20)
        self.assertEqual(recorder.started[0]["model"], META["model"])

    def test_nonstream_completion_status_and_usage_gate(self):
        for status, expected, known in [("completed", "success", True), ("failed", "error", True),
            ("incomplete", "unknown", True), ("cancelled", "unknown", False), ("queued", "unknown", False),
            ("in_progress", "unknown", False), (None, "unknown", False)]:
            recorder, value = Recorder(), response(status=status)
            self.assertIs(adapter.openai_call(recorder, lambda: value, **META), value)
            self.assertEqual(recorder.finished[0], {"status": expected,
                **({"input_tokens": 12, "output_tokens": 8, "total_tokens": 20} if known else UNKNOWN)})
        recorder = Recorder()
        adapter.openai_call(recorder, lambda: response(object="not-a-response"), **META)
        self.assertEqual(recorder.finished, [{"status": "unknown", **UNKNOWN}])

    def test_allowlisted_extra_storage_bypasses_pydantic_getters(self):
        # The stdlib suite models Pydantic v2's builtin storage slots. Actual SDK
        # parsing of these fields is checked by python_async_check.py separately.
        base = type("BaseModel", (), {"__module__": "pydantic.main",
            "__slots__": ("__dict__", "__pydantic_extra__")})
        touched = []

        class StoredModel(base):
            def __getattribute__(self, name):
                touched.append(name)
                raise AssertionError("instance getter must not run")

        details = StoredModel()
        object.__setattr__(details, "cached_tokens", 3)
        value = response(usage={"input_tokens": 8, "output_tokens": 2, "total_tokens": 10,
            "input_tokens_details": details})
        for count in (-1, 9, True, "2"):
            object.__setattr__(details, "__pydantic_extra__", {"cache_write_tokens": count})
            self.assertEqual(adapter.extract_openai_usage(value), UNKNOWN)
        for extra in (None, {}, {"cache_write_tokens": 2, "unrelated_content": object()}):
            object.__setattr__(details, "__pydantic_extra__", extra)
            self.assertEqual(adapter.extract_openai_usage(value),
                {"input_tokens": 8, "output_tokens": 2, "total_tokens": 10})
        self.assertEqual(touched, [])

    def test_single_choice_chat_terminal_reasons(self):
        for reason, status, known in [("stop", "success", True), ("tool_calls", "success", True),
            ("function_call", "success", True), ("length", "unknown", True),
            ("content_filter", "unknown", True), (None, "unknown", False), ("other", "unknown", False)]:
            recorder = Recorder()
            adapter.openai_call(recorder, lambda: chat(reason), api="chat_completions", **META)
            self.assertEqual(recorder.finished[0]["status"], status)
            self.assertEqual(recorder.finished[0]["total_tokens"], 20 if known else None)
        for choices in ([], [{"index": True, "finish_reason": "stop"}],
                        [{"index": 0, "finish_reason": "stop"}, {"index": 1, "finish_reason": "stop"}]):
            recorder = Recorder()
            adapter.openai_call(recorder, lambda: chat(choices=choices), api="chat_completions", **META)
            self.assertEqual(recorder.finished, [{"status": "unknown", **UNKNOWN}])

    def test_exporter_failures_preserve_provider_result_and_exception(self):
        error, value = RuntimeError("original provider exception"), response()

        def fails():
            raise error

        for recorder in (Recorder(fail_start=True), Recorder(fail_finish=True)):
            self.assertIs(adapter.openai_call(recorder, lambda: value, **META), value)
            with self.assertRaises(RuntimeError) as caught:
                adapter.openai_call(recorder, fails, **META)
            self.assertIs(caught.exception, error)
            self.assertEqual(list(adapter.openai_stream(recorder, lambda: iter([terminal()]), **META))[0]["type"], "response.completed")

    def test_stream_constructor_is_inert_and_response_terminal_is_required(self):
        recorder = Recorder()
        value = adapter.openai_stream(recorder, lambda: self.fail("operation called"), **META)
        self.assertEqual(recorder.started, [])
        value.close()
        self.assertEqual(recorder.finished, [])
        self.assertEqual(self.stream([]), {"status": "unknown", **UNKNOWN})
        self.assertEqual(self.stream([{"type": "response.output_text.delta", "delta": "private"}]), {"status": "unknown", **UNKNOWN})
        self.assertEqual(self.stream([terminal()])["status"], "success")

    def test_response_stream_repeated_metadata_and_conflicts(self):
        result = self.stream([terminal(), terminal()])
        self.assertEqual(result, {"status": "success", "input_tokens": 12, "output_tokens": 8, "total_tokens": 20})
        for chunks in ([terminal(), terminal(id="resp_other")], [terminal(), terminal("failed")],
            [terminal(), terminal(usage={"input_tokens": 1, "output_tokens": 1})],
            [terminal(id="invalid ID")], [{"type": "response.created", "response": {"id": "other"}}, terminal()]):
            self.assertEqual(self.stream(chunks), {"status": "unknown", **UNKNOWN})

    def test_invalid_usage_preserves_valid_stream_completion_and_latches_unknown(self):
        bad = terminal(usage={"input_tokens": True})
        self.assertEqual(self.stream([bad, terminal()]), {"status": "success", **UNKNOWN})
        self.assertEqual(self.stream([terminal(), bad]), {"status": "success", **UNKNOWN})

    def test_invalid_usage_does_not_hide_conflicting_valid_snapshots(self):
        bad = terminal(usage={"input_tokens": True})
        changed = terminal(usage={"input_tokens": 1, "output_tokens": 1})
        self.assertEqual(self.stream([terminal(), bad, changed]), {"status": "unknown", **UNKNOWN})
        self.assertEqual(self.stream([terminal(), bad, terminal()]), {"status": "success", **UNKNOWN})
        chunks = [chat_chunk("stop"), chat_chunk(choices=[], usage=chat()["usage"]),
            chat_chunk(choices=[], usage={"prompt_tokens": True}),
            chat_chunk(choices=[], usage={"prompt_tokens": 1, "completion_tokens": 1})]
        self.assertEqual(self.stream(chunks, api="chat_completions"), {"status": "unknown", **UNKNOWN})

    def test_generic_response_error_is_error_without_reading_message(self):
        class Private:
            def __str__(self):
                raise AssertionError("private text inspected")
        error = {"type": "error", "message": Private()}
        self.assertEqual(self.stream([error]), {"status": "error", **UNKNOWN})
        self.assertEqual(self.stream([error, terminal()]), {"status": "unknown", **UNKNOWN})
        self.assertEqual(self.stream([error, terminal("failed")])["status"], "error")

    def test_chat_stream_only_final_usage_after_finish_is_trusted(self):
        usage = chat_chunk(choices=[], usage=chat()["usage"])
        result = self.stream([chat_chunk(usage={"prompt_tokens": 999}), chat_chunk("stop"), usage, copy.deepcopy(usage)], api="chat_completions")
        self.assertEqual(result, {"status": "success", "input_tokens": 12, "output_tokens": 8, "total_tokens": 20})
        self.assertEqual(self.stream([usage, chat_chunk("stop")], api="chat_completions"), {"status": "unknown", **UNKNOWN})
        self.assertEqual(self.stream([chat_chunk("stop")], api="chat_completions"), {"status": "success", **UNKNOWN})

    def test_terminal_usage_is_snapshotted_before_yield_without_retaining_chunks(self):
        recorder, chunk = Recorder(), terminal()
        iterator = adapter.openai_stream(recorder, lambda: iter([chunk]), **META)
        self.assertIs(next(iterator), chunk)
        chunk["response"]["usage"]["input_tokens"] = 2000
        with self.assertRaises(StopIteration):
            next(iterator)
        self.assertEqual(recorder.finished[0]["input_tokens"], 12)
        class Canary: pass
        canary = Canary()
        reference = weakref.ref(canary)
        state = adapter._StreamState("responses")
        state.observe({"type": "response.output_text.delta", "delta": canary})
        del canary
        gc.collect()
        self.assertIsNone(reference())

    def test_early_close_consumer_throw_and_provider_error_are_distinct(self):
        for consumer in ("close", "throw"):
            recorder, failure = Recorder(), RuntimeError("consumer failure")
            iterator = adapter.openai_stream(recorder, lambda: iter([terminal()]), **META)
            next(iterator)
            if consumer == "close":
                iterator.close()
            else:
                with self.assertRaises(RuntimeError) as caught:
                    iterator.throw(failure)
                self.assertIs(caught.exception, failure)
            self.assertEqual(recorder.finished, [{"status": "unknown", **UNKNOWN}])
        error, recorder = RuntimeError("provider failure"), Recorder()
        def provider():
            yield terminal()
            raise error
        with self.assertRaises(RuntimeError) as caught:
            list(adapter.openai_stream(recorder, provider, **META))
        self.assertIs(caught.exception, error)
        self.assertEqual(recorder.finished, [{"status": "error", **UNKNOWN}])

    def test_stream_generator_return_and_cleanup_errors_preserve_result(self):
        returned, recorder = object(), Recorder()
        def provider():
            yield terminal()
            return returned
        value = adapter.openai_stream(recorder, provider, **META)
        next(value)
        with self.assertRaises(StopIteration) as completed:
            next(value)
        self.assertIs(completed.exception.value, returned)
        class Iterator:
            def __iter__(self): return self
            def __next__(self): raise StopIteration
            def close(self): raise RuntimeError("cleanup failure")
        self.assertEqual(list(adapter.openai_stream(Recorder(), Iterator, **META)), [])

    def test_no_arguments_and_import_are_offline(self):
        with patch.object(app, "BackgroundExporter", side_effect=AssertionError("exporter created")):
            with patch("sys.stdout"):
                self.assertEqual(app.main([]), 0)
        script = ("import sys,socket,os,threading; from unittest.mock import patch; "
            f"sys.path.insert(0,{str(EXAMPLES)!r}); "
            "fail=lambda *a,**k: (_ for _ in ()).throw(AssertionError('side effect')); "
            "exec('with patch.object(socket.socket,\"connect\",fail), patch.object(os,\"getenv\",fail), patch.object(threading.Thread,\"start\",fail):\\n import guardian_openai,python_openai_app')")
        interpreter = getattr(sys, "_base_executable", sys.executable)
        result = subprocess.run([interpreter, "-I", "-S", "-c", script], capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)


class AsyncPythonOpenAI(unittest.IsolatedAsyncioTestCase):
    async def test_async_call_cancel_preserves_original_exception(self):
        error, recorder = asyncio.CancelledError("explicit cancellation"), Recorder()
        async def operation(): raise error
        with self.assertRaises(asyncio.CancelledError) as caught:
            await adapter.async_openai_call(recorder, operation, **META)
        self.assertIs(caught.exception, error)
        self.assertEqual(recorder.finished, [{"status": "unknown", **UNKNOWN}])

    async def test_synthetic_app_uses_only_numeric_usage_and_no_cost(self):
        recorder = Recorder()
        app.exercise(recorder)
        await app.async_exercise(recorder)
        self.assertEqual(len(recorder.finished), 6)
        self.assertEqual({key for item in recorder.finished for key in item}, {"status", *UNKNOWN})
        self.assertTrue(all(item["total_tokens"] in (15, 20) for item in recorder.finished))

    async def test_awaited_call_and_stream_preserve_objects(self):
        value, chunk, recorder = response(), terminal(), Recorder()
        async def call(): return value
        self.assertIs(await adapter.async_openai_call(recorder, call, **META), value)
        async def chunks(): yield chunk
        async def operation(): return chunks()
        result = [item async for item in adapter.async_openai_stream(recorder, operation, **META)]
        self.assertIs(result[0], chunk)
        self.assertEqual([item["total_tokens"] for item in recorder.finished], [20, 20])

    async def test_async_exporter_failures_do_not_change_operation_or_exception(self):
        value, error = response(), RuntimeError("original")
        async def normal(): return value
        async def failing(): raise error
        async def chunks(): yield terminal()
        for recorder in (Recorder(fail_start=True), Recorder(fail_finish=True)):
            self.assertIs(await adapter.async_openai_call(recorder, normal, **META), value)
            with self.assertRaises(RuntimeError) as caught:
                await adapter.async_openai_call(recorder, failing, **META)
            self.assertIs(caught.exception, error)
            self.assertEqual(len([item async for item in adapter.async_openai_stream(recorder, chunks, **META)]), 1)

    async def test_async_cancel_and_athrow_remain_unknown_and_close_provider(self):
        for abort in ("cancel", "athrow", "aclose"):
            recorder, closed, waiting = Recorder(), asyncio.Event(), asyncio.Event()
            async def provider():
                try:
                    yield terminal()
                    waiting.set()
                    await asyncio.Event().wait()
                finally:
                    closed.set()
            stream = adapter.async_openai_stream(recorder, provider, **META)
            await anext(stream)
            if abort == "cancel":
                task = asyncio.create_task(anext(stream))
                await asyncio.wait_for(waiting.wait(), 2)
                task.cancel()
                with self.assertRaises(asyncio.CancelledError): await task
            elif abort == "athrow":
                error = RuntimeError("consumer")
                with self.assertRaises(RuntimeError) as caught: await stream.athrow(error)
                self.assertIs(caught.exception, error)
            else:
                await stream.aclose()
            self.assertTrue(closed.is_set())
            self.assertEqual(recorder.finished, [{"status": "unknown", **UNKNOWN}])

    async def test_async_provider_exception_and_cleanup_preserve_original(self):
        error, recorder = RuntimeError("provider"), Recorder()
        class Stream:
            def __aiter__(self): return self
            async def __anext__(self): raise error
            async def close(self): raise RuntimeError("cleanup")
        with self.assertRaises(RuntimeError) as caught:
            async for _ in adapter.async_openai_stream(recorder, Stream, **META): pass
        self.assertIs(caught.exception, error)
        self.assertEqual(recorder.finished, [{"status": "error", **UNKNOWN}])


if __name__ == "__main__":
    unittest.main()
