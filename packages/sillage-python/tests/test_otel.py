"""Real OTel providers plus hostile boundary fixtures; no network or raw export."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

try:
    from opentelemetry import context as otel_context, trace
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
    from opentelemetry.trace import Status, StatusCode
except ImportError:
    raise unittest.SkipTest("Install the isolated OpenTelemetry test dependencies")

PACKAGE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE / "src"))
from sillage_observe import Configuration
from sillage_observe import otel
from sillage_observe.otel import SillageSpanProcessor

CONFIG = Configuration("http://127.0.0.1:8001", "cg_ingest_" + "0" * 32 + "_" + "a" * 43,
                       "fixture-service", True)
LLM = {"openinference.span.kind": "LLM", "llm.model_name": "fixture/model"}
START = 1_700_000_000_123_456_789
END = START + 345_999_999


class Recorder:
    def __init__(self):
        self.events, self.flushes, self.closes = [], [], []
        self.confirmed = True

    def emit(self, event):
        self.events.append(dict(event))
        return {"accepted": True, "code": "queued"}

    def flush(self, timeout):
        self.flushes.append(timeout)
        return {"drained": True, "confirmed": self.confirmed}

    def close(self, timeout):
        self.closes.append(timeout)
        return {"drained": True, "confirmed": self.confirmed}


def readable(attributes=None, *, trace_id=1, span_id=2, parent_id=None, status=StatusCode.OK,
             start=START, end=END, name="fixture-call", scope="user.own.instrumentation"):
    context = SimpleNamespace(trace_id=trace_id, span_id=span_id)
    parent = SimpleNamespace(trace_id=trace_id, span_id=parent_id) if parent_id is not None else None
    return SimpleNamespace(get_span_context=lambda: context, parent=parent, attributes=attributes or {},
        name=name, start_time=start, end_time=end, status=SimpleNamespace(status_code=status),
        instrumentation_scope=SimpleNamespace(name=scope))


class ProjectionTests(unittest.TestCase):
    def setUp(self):
        self.sink = Recorder()
        self.diagnostics = []
        self.processor = SillageSpanProcessor(CONFIG, exporter=self.sink, diagnostic=self.diagnostics.append)

    def tearDown(self):
        self.processor.shutdown()

    def test_canonical_ids_actual_parent_times_zero_tokens_and_unknown_cost(self):
        self.processor.on_end(readable({**LLM, "llm.token_count.prompt": 0,
            "llm.token_count.completion": 0, "llm.cost.total": 999.99}, trace_id=15, span_id=16, parent_id=14))
        self.assertEqual(self.sink.events, [{"trace_id": "0000000000000000000000000000000f",
            "observation_id": "0000000000000010", "parent_observation_id": "000000000000000e",
            "agent_name": "fixture-service", "model": "fixture/model",
            "started_at": "2023-11-14T22:13:20.123Z", "ended_at": "2023-11-14T22:13:20.469Z",
            "status": "success", "input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "cost_usd": None}])

    def test_only_llm_semantics_generate_events(self):
        for index, kind in enumerate(("AGENT", "CHAIN", "TOOL", "RETRIEVER", "EMBEDDING", "HTTP"), 3):
            self.processor.on_end(readable({"openinference.span.kind": kind, "llm.model_name": "fixture"}, span_id=index))
        self.processor.on_end(readable({"http.request.method": "POST", "llm.model_name": "fixture"}))
        self.processor.on_end(readable({"gen_ai.operation.name": "embeddings", "gen_ai.request.model": "fixture"}))
        self.processor.on_end(readable({**LLM, "gen_ai.operation.name": "embeddings"}))
        self.assertEqual(self.sink.events, [])
        self.assertEqual(self.processor.snapshot()["ignored_spans"], 9)
        self.assertEqual(self.diagnostics, ["unsupported_span"])

    def test_conflicting_semantics_and_provider_non_chat_apis_are_ignored(self):
        for operation in ("embeddings", "tool", "image_generation", "unknown_operation"):
            self.processor.on_end(readable({**LLM, "gen_ai.operation.name": operation}))
        for scope, names in (("openinference.instrumentation.litellm", ("image_generation", "aimage_generation", "embedding", "new_api")),
                             ("openinference.instrumentation.openai", ("ImagesResponse", "CreateEmbeddingResponse", "Transcription", "Page[Model]"))):
            for name in names:
                self.processor.on_end(readable(LLM, scope=scope, name=name))
        self.processor.on_end(readable({"gen_ai.operation.name": "chat", "gen_ai.request.model": "fixture"},
            scope="openinference.instrumentation.litellm", name="image_generation"))
        self.assertEqual(self.sink.events, [])
        self.assertEqual(self.processor.snapshot()["ignored_spans"], 13)

    def test_genai_requires_supported_operation_and_model(self):
        self.processor.on_end(readable({"gen_ai.operation.name": "chat"}))
        self.processor.on_end(readable({"gen_ai.operation.name": "chat", "gen_ai.request.model": "fixture-model",
            "gen_ai.usage.input_tokens": 3, "gen_ai.usage.output_tokens": 4}))
        self.assertEqual(len(self.sink.events), 1)
        self.assertEqual(self.sink.events[0]["total_tokens"], 7)

    def test_malformed_conflicting_or_impossible_usage_becomes_all_unknown(self):
        cases = [
            {"llm.token_count.prompt": 3, "gen_ai.usage.input_tokens": 4, "llm.token_count.completion": 2},
            {"llm.token_count.prompt": True}, {"llm.token_count.prompt": 1.0},
            {"llm.token_count.prompt": "1"}, {"llm.token_count.prompt": -1},
            {"llm.token_count.prompt": 2**53}, {"llm.token_count.total": float("nan")},
            {"llm.token_count.prompt": 3, "llm.token_count.completion": 2, "llm.token_count.total": 9},
            {"llm.token_count.prompt": 3, "llm.token_count.total": 2},
        ]
        for attrs in cases:
            self.processor.on_end(readable({**LLM, **attrs}))
        for event in self.sink.events:
            self.assertTrue(all(event[key] is None for key in ("input_tokens", "output_tokens", "total_tokens")))
        self.assertEqual(self.diagnostics, ["invalid_token_measurements"])

    def test_aliases_agree_and_missing_bucket_remains_unknown(self):
        self.processor.on_end(readable({**LLM, "llm.token_count.prompt": 7,
            "gen_ai.usage.input_tokens": 7, "gen_ai.usage.total_tokens": 10}))
        event = self.sink.events[0]
        self.assertEqual(event["input_tokens"], 7)
        self.assertIsNone(event["output_tokens"])
        self.assertEqual(event["total_tokens"], 10)

    def test_status_is_not_quality_and_interruption_overrides_ok(self):
        for code in (StatusCode.UNSET, StatusCode.ERROR, StatusCode.OK):
            self.processor.on_end(readable(LLM, status=code))
        self.processor.on_end(readable({**LLM, "sillage.call.status": "cancelled"}, status=StatusCode.ERROR))
        self.processor.on_end(readable({**LLM, "gen_ai.response.finish_reasons": ("stop", "length")}))
        self.assertEqual([event["status"] for event in self.sink.events], ["unknown", "error", "success", "unknown", "unknown"])

    def test_known_provider_ok_needs_terminal_evidence(self):
        for scope in ("openinference.instrumentation.openai", "openinference.instrumentation.litellm"):
            name = "ChatCompletion" if scope.endswith("openai") else "completion"
            self.processor.on_end(readable(LLM, scope=scope, name=name))
            self.processor.on_end(readable({**LLM, "llm.finish_reason": "stop"}, scope=scope, name=name))
            self.processor.on_end(readable({**LLM, "gen_ai.response.finish_reasons": ("stop",)}, scope=scope, name=name))
        self.assertEqual([event["status"] for event in self.sink.events], ["unknown", "success", "success"] * 2)
        self.assertEqual(self.processor.snapshot()["missing_terminal_evidence_spans"], 2)
        self.assertEqual(self.diagnostics, ["missing_terminal_evidence"])

    def test_finish_reason_sequence_is_bounded_and_scalar(self):
        for reasons in ("stop", ["stop"] * 9, [{"PRIVATE": "PAYLOAD"}], ["x" * 100]):
            self.processor.on_end(readable({**LLM, "gen_ai.response.finish_reasons": reasons}))
        self.assertTrue(all(event["status"] == "unknown" for event in self.sink.events))

    def test_invalid_ids_and_times_never_reach_exporter(self):
        for overrides in ({"trace_id": 0}, {"trace_id": 2**128}, {"trace_id": True}, {"span_id": 0},
                          {"span_id": 2**64}, {"parent_id": 2}, {"end": START - 1}, {"start": 0}, {"end": 2**63}):
            self.processor.on_end(readable(LLM, **overrides))
        self.assertEqual(self.sink.events, [])

    def test_replay_preserves_identity_and_changed_evidence_is_not_hidden(self):
        span = readable({**LLM, "llm.token_count.prompt": 1})
        self.processor.on_end(span)
        self.processor.on_end(span)
        self.assertEqual(self.sink.events[0], self.sink.events[1])
        span.attributes["llm.token_count.prompt"] = 2
        self.processor.on_end(span)
        self.assertEqual(self.sink.events[0]["observation_id"], self.sink.events[2]["observation_id"])
        self.assertNotEqual(self.sink.events[0], self.sink.events[2])

    def test_no_events_resources_serializers_or_unallowlisted_attributes_are_read(self):
        allowed = {"openinference.span.kind", "gen_ai.operation.name", *otel._MODEL, *otel._AGENT,
                   *otel._INPUT, *otel._OUTPUT, *otel._TOTAL, "sillage.call.status", "gen_ai.response.status",
                   "gen_ai.response.finish_reason", "llm.finish_reason", "gen_ai.response.finish_reasons"}
        class GuardedAttributes:
            def get(self, key, default):
                if key not in allowed:
                    raise AssertionError("unexpected attribute")
                return LLM.get(key, default)
            def __iter__(self):
                raise AssertionError("attributes iterated")
        class GuardedSpan:
            def __getattribute__(self, name):
                if name in {"events", "resource", "to_json"}:
                    raise AssertionError("private data inspected")
                return object.__getattribute__(self, name)
        source = readable()
        span = GuardedSpan()
        span.__dict__.update(source.__dict__, attributes=GuardedAttributes())
        self.processor.on_end(span)
        self.assertEqual(len(self.sink.events), 1)
        self.assertNotIn("PRIVATE", json.dumps(self.sink.events))


class ProviderContextTests(unittest.TestCase):
    def setUp(self):
        self.sink, self.external = Recorder(), InMemorySpanExporter()
        self.processor = SillageSpanProcessor(CONFIG, exporter=self.sink)
        self.provider = TracerProvider(shutdown_on_exit=False)
        self.provider.add_span_processor(SimpleSpanProcessor(self.external))
        self.provider.add_span_processor(self.processor)
        self.tracer = self.provider.get_tracer("user.instrumentation")

    def tearDown(self):
        self.provider.shutdown()

    def test_actual_agent_chain_parent_and_external_exporter_preserved(self):
        with self.tracer.start_as_current_span("research-agent", attributes={"openinference.span.kind": "AGENT"}) as agent:
            with self.tracer.start_as_current_span("retrieval-step", attributes={"openinference.span.kind": "CHAIN"}) as chain:
                with self.tracer.start_as_current_span("model-call", attributes=LLM) as call:
                    call.set_status(Status(StatusCode.OK))
        event = self.sink.events[0]
        self.assertEqual(event["agent_name"], "research-agent")
        self.assertEqual(event["trace_id"], f"{agent.get_span_context().trace_id:032x}")
        self.assertEqual(event["observation_id"], f"{call.get_span_context().span_id:016x}")
        self.assertEqual(event["parent_observation_id"], f"{chain.get_span_context().span_id:016x}")
        self.assertEqual(len(self.sink.events), 1)
        self.assertEqual(len(self.external.get_finished_spans()), 3)

    def test_explicit_agent_and_otel_context_take_precedence(self):
        token = otel_context.attach(otel_context.set_value("sillage.agent.name", "context-agent"))
        try:
            with self.tracer.start_as_current_span("call", attributes=LLM):
                pass
            with self.tracer.start_as_current_span("call", attributes={**LLM, "sillage.agent.name": "explicit-agent"}):
                pass
        finally:
            otel_context.detach(token)
        self.assertEqual([event["agent_name"] for event in self.sink.events], ["context-agent", "explicit-agent"])

    def test_late_agent_kind_does_not_rewrite_finished_child(self):
        with self.tracer.start_as_current_span("late-agent") as agent:
            with self.tracer.start_as_current_span("call", attributes=LLM):
                pass
            agent.set_attribute("openinference.span.kind", "AGENT")
        self.assertEqual(self.sink.events[0]["agent_name"], CONFIG.service_name)

    def test_nested_llm_spans_are_distinct_not_guessed_duplicates(self):
        with self.tracer.start_as_current_span("outer", attributes=LLM):
            with self.tracer.start_as_current_span("inner", attributes=LLM):
                pass
        self.assertEqual(len(self.sink.events), 2)
        self.assertNotEqual(self.sink.events[0]["observation_id"], self.sink.events[1]["observation_id"])
        self.assertEqual(self.processor.snapshot()["nested_llm_spans"], 1)

    def test_concurrent_traces_do_not_share_agents(self):
        def run(index):
            with self.tracer.start_as_current_span("agent-" + str(index), attributes={"openinference.span.kind": "AGENT"}):
                with self.tracer.start_as_current_span("call", attributes=LLM):
                    pass
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(run, range(20)))
        self.assertEqual({event["agent_name"] for event in self.sink.events}, {"agent-" + str(i) for i in range(20)})
        self.assertEqual(len({event["trace_id"] for event in self.sink.events}), 20)

    def test_scalar_context_cache_is_bounded_and_expires(self):
        with patch.object(otel, "_CONTEXT_LIMIT", 3), patch.object(otel, "_CONTEXT_TTL", 1), patch.object(otel.time, "monotonic", return_value=1):
            for i in range(8):
                with self.tracer.start_as_current_span("agent-" + str(i), attributes={"openinference.span.kind": "AGENT"}):
                    pass
            self.assertEqual(self.processor.snapshot()["context_entries"], 3)
            for key, record in self.processor._contexts.items():
                self.assertEqual(len(key), 2)
                self.assertTrue(all(value is None or type(value) in (str, int, bool, float) for value in record))
        with patch.object(otel.time, "monotonic", return_value=3):
            self.assertEqual(self.processor.snapshot()["context_entries"], 0)


class LifecycleTests(unittest.TestCase):
    def test_non_llm_does_not_create_exporter_or_thread(self):
        processor = SillageSpanProcessor(CONFIG)
        with patch.object(otel, "BackgroundExporter", side_effect=AssertionError("exporter created")):
            processor.on_end(readable({"openinference.span.kind": "TOOL"}))
            self.assertTrue(processor.force_flush())
            self.assertTrue(processor.close()["confirmed"])

    def test_flush_and_shutdown_are_bounded_owned_and_idempotent(self):
        sink = Recorder()
        processor = SillageSpanProcessor(CONFIG, exporter=sink)
        self.assertTrue(processor.force_flush(25))
        self.assertEqual(sink.flushes, [0.025])
        first = processor.close(timeout=0.2)
        processor.shutdown()
        self.assertEqual(sink.closes, [0.2])
        self.assertEqual(first, processor.close())
        processor.on_end(readable(LLM))
        self.assertEqual(sink.events, [])
        self.assertFalse(processor.force_flush())

    def test_export_failure_is_redacted_and_does_not_break_provider(self):
        sink, diagnostics = Recorder(), []
        def failing(event):
            raise RuntimeError("PRIVATE_EXPORT_FAILURE")
        sink.emit = failing
        processor = SillageSpanProcessor(CONFIG, exporter=sink, diagnostic=diagnostics.append)
        processor.on_end(readable(LLM))
        self.assertEqual(diagnostics, ["capture_unavailable"])
        self.assertNotIn("PRIVATE", json.dumps(processor.snapshot()))
        processor.shutdown()

    def test_rejected_delivery_and_flush_are_visible(self):
        sink, diagnostics = Recorder(), []
        sink.emit = lambda event: {"accepted": False, "code": "queue_full"}
        sink.confirmed = False
        processor = SillageSpanProcessor(CONFIG, exporter=sink, diagnostic=diagnostics.append)
        processor.on_end(readable(LLM))
        self.assertFalse(processor.force_flush())
        self.assertFalse(processor.close()["confirmed"])
        self.assertEqual(diagnostics, ["queue_full", "flush_unconfirmed", "shutdown_unconfirmed"])

    def test_forked_processor_does_not_touch_inherited_exporter(self):
        sink = Recorder()
        processor = SillageSpanProcessor(CONFIG, exporter=sink)
        processor._pid = -1
        processor.on_end(readable(LLM))
        self.assertFalse(processor.close()["confirmed"])
        self.assertEqual(sink.closes, [])
        self.assertEqual(processor.snapshot()["context_entries"], 0)


if __name__ == "__main__":
    unittest.main()
