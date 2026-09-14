"""Launcher ownership and real optional-runtime checks; synthetic SDK transport."""
from contextlib import redirect_stdout, redirect_stderr
from importlib import metadata
import io
import inspect
import asyncio
import json
import os
from pathlib import Path
import socket
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

PACKAGE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE / "src"))
from sillage_observe import Configuration, ConfigurationError, cli
from sillage_observe import openinference_runtime as runtime

TOKEN = "cg_ingest_" + "0" * 32 + "_" + "a" * 43
CONFIG = Configuration("http://127.0.0.1:8001", TOKEN, "fixture-service", True)
ENV = {"SILLAGE_URL": CONFIG.origin, "SILLAGE_INGEST_KEY": TOKEN, "SILLAGE_ALLOW_LOCAL": "true"}


def versions():
    result = dict(runtime.SHARED_VERSIONS)
    for name, (sdk, tested, instrumentor, _class_name) in runtime.LAYERS.items():
        result[sdk] = tested[0]
        result["openinference-instrumentation-" + name] = instrumentor
    return result


def installed(name):
    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return None


OPTIONAL = all(installed(name) == value for name, value in runtime.SHARED_VERSIONS.items())
OPENAI = OPTIONAL and installed("openai") in runtime.LAYERS["openai"][1]
LITELLM = OPTIONAL and installed("litellm") in runtime.LAYERS["litellm"][1]
LANGCHAIN = OPTIONAL and installed("langchain-core") in runtime.LAYERS["langchain"][1]


class MetadataCheckTests(unittest.TestCase):
    def test_auto_selects_exactly_one_layer_and_explicit_override_is_respected(self):
        with patch.object(runtime, "_version", side_effect=versions().get):
            found = runtime.detected_openinference()
            self.assertEqual(runtime.select_instrumentor("auto", found), "langchain")
            self.assertEqual(runtime.select_instrumentor("openai", found), "openai")
        for value in ("openai,litellm", "all", "", "OPENAI"):
            with self.assertRaises(ConfigurationError):
                runtime.select_instrumentor(value, found)

    def test_unverified_sdk_and_dependency_versions_are_not_admitted(self):
        for package in ("openai", "openinference-instrumentation-openai", "opentelemetry-sdk"):
            matrix = versions()
            matrix[package] = "999.1.0"
            with self.subTest(package=package), patch.object(runtime, "_version", side_effect=matrix.get):
                self.assertIsNone(runtime.select_instrumentor("openai"))

    def test_check_does_not_import_sdk_spawn_threads_or_make_network_calls(self):
        out, err = io.StringIO(), io.StringIO()
        with patch.dict(os.environ, ENV, clear=True), patch.object(runtime, "_version", side_effect=versions().get), \
             patch.object(runtime, "import_module", side_effect=AssertionError("runtime import")), \
             patch.object(socket.socket, "connect", side_effect=AssertionError("network")), \
             patch("threading.Thread.start", side_effect=AssertionError("thread")), \
             redirect_stdout(out), redirect_stderr(err):
            self.assertEqual(cli.main(["--instrumentation", "openinference", "--instrumentors", "litellm", "--check"]), 0)
        value = json.loads(out.getvalue())
        self.assertEqual(value["instrumentors_selected"], ["litellm"])
        self.assertEqual(value["instrumentation"], "openinference")
        self.assertFalse(value["collector_checked"])
        self.assertFalse(value["connected"])
        self.assertNotIn(TOKEN, out.getvalue() + err.getvalue())

    def test_missing_extra_fails_check_and_does_not_launch_target(self):
        for tail in (["--check"], ["--", "python", "app.py"]):
            with patch.dict(os.environ, ENV, clear=True), patch.object(runtime, "_version", return_value=None), \
                 patch.object(cli.runpy, "run_path", side_effect=AssertionError("target")), \
                 redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()) as err:
                self.assertEqual(cli.main(["--instrumentation", "openinference", *tail]), 3)
                self.assertIn("no_supported_openinference_stack", err.getvalue())

    def test_layer_option_is_not_silently_ignored_in_native_mode(self):
        with patch.dict(os.environ, ENV, clear=True), redirect_stderr(io.StringIO()) as err:
            self.assertEqual(cli.main(["--instrumentors", "openai", "--check"]), 2)
            self.assertIn("instrumentors_require_openinference", err.getvalue())

    def test_distribution_metadata_diagnostics_cannot_echo_arbitrary_text(self):
        with patch.object(metadata, "version", return_value="secret with spaces\n" + TOKEN):
            self.assertIsNone(runtime._version("openai"))


@unittest.skipUnless(OPTIONAL, "pinned OpenInference extra is not installed")
class ContextTests(unittest.TestCase):
    def test_metadata_enrichment_failure_cannot_replace_app_result_or_exception(self):
        from opentelemetry import context
        result = object()
        async def original_async(**kwargs):
            return result
        def original(**kwargs):
            return result
        sdk = SimpleNamespace(completion=original, acompletion=original_async)
        notes = []
        owner = runtime.OpenInferenceRuntime(CONFIG, "litellm", diagnostic=notes.append)
        with patch.object(runtime, "import_module", return_value=sdk):
            owner._install_litellm_context()
        with patch.object(context, "attach", side_effect=RuntimeError("private context error")):
            self.assertIs(sdk.completion(metadata={"generation_name":"agent"}), result)
            self.assertIs(asyncio.run(sdk.acompletion(metadata={"generation_name":"agent"})), result)
        self.assertEqual(notes, ["context_unavailable"])
        owner.close()

    def test_privacy_config_does_not_load_environment_blob_plugins(self):
        from openinference.instrumentation import config
        with patch.dict(os.environ, {"OPENINFERENCE_BLOB_UPLOADER": "unrelated-upload-plugin"}), \
             patch.object(config, "load_blob_uploader", side_effect=AssertionError("plugin loaded")):
            value = runtime._privacy_config()
        for name in ("hide_inputs", "hide_outputs", "hide_llm_invocation_parameters", "hide_llm_tools", "hide_embeddings_text", "hide_embeddings_vectors"):
            self.assertTrue(getattr(value, name))
        self.assertFalse(value.enable_genai_semconv)

    def test_existing_workflow_context_generates_real_stable_namespaced_trace_ids(self):
        from opentelemetry import context
        generator = runtime._legacy_id_generator("fixture-service")
        token = context.attach(context.set_value("sillage.legacy_run_id", "workflow-123"))
        try:
            first = generator.generate_trace_id()
            self.assertEqual(first, generator.generate_trace_id())
            self.assertNotEqual(first, runtime._legacy_id_generator("other-service").generate_trace_id())
            self.assertGreater(first, 0)
            self.assertLess(first, 2 ** 128)
        finally:
            context.detach(token)
        self.assertNotEqual(generator.generate_trace_id(), generator.generate_trace_id())

    def test_ambient_parent_always_wins_over_legacy_run_identity(self):
        from opentelemetry import context, trace
        from opentelemetry.sdk.trace import TracerProvider
        outer = TracerProvider(shutdown_on_exit=False)
        inner = TracerProvider(shutdown_on_exit=False, id_generator=runtime._legacy_id_generator("fixture-service"))
        try:
            with outer.get_tracer("app").start_as_current_span("existing-workflow") as parent:
                token = context.attach(context.set_value("sillage.legacy_run_id", "legacy-other-run"))
                try:
                    with inner.get_tracer("sdk").start_as_current_span("call") as child:
                        self.assertEqual(child.get_span_context().trace_id, parent.get_span_context().trace_id)
                        self.assertEqual(child.parent.span_id, parent.get_span_context().span_id)
                finally:
                    context.detach(token)
        finally:
            outer.shutdown()
            inner.shutdown()


class Recorder:
    def __init__(self):
        self.events, self.closes = [], 0
    def emit(self, event):
        self.events.append(event)
        return True
    def close(self, timeout=3):
        self.closes += 1
        return {"confirmed": True}


@unittest.skipUnless(OPENAI, "a verified OpenAI SDK and pinned OpenInference extra are not installed")
class RealRuntimeTests(unittest.TestCase):
    def test_sync_async_chat_responses_and_streams_keep_usage_and_hide_content(self):
        import httpx
        import openai
        output = Recorder()
        owner = runtime.OpenInferenceRuntime(CONFIG, "openai", output).install()

        def transport(request):
            body = json.loads(request.content)
            if request.url.path.endswith("/responses"):
                response = {"id":"resp_fixture", "object":"response", "created_at":1,
                    "status":"completed", "model":"gpt-4o-mini", "output":[],
                    "usage":{"input_tokens":7,"output_tokens":3,"total_tokens":10}}
                if body.get("stream"):
                    data = {"type":"response.completed","sequence_number":1,"response":response}
                    return httpx.Response(200, text="data: " + json.dumps(data) + "\n\n", headers={"content-type":"text/event-stream"})
                return httpx.Response(200, json=response)
            response = {"id":"fixture", "object":"chat.completion", "created":1, "model":"gpt-4o-mini",
                "choices":[{"index":0,"message":{"role":"assistant","content":"PRIVATE_OUTPUT"},"finish_reason":"stop"}],
                "usage":{"prompt_tokens":7,"completion_tokens":3,"total_tokens":10}}
            if body.get("stream"):
                response["object"] = "chat.completion.chunk"
                response["choices"] = [{"index":0,"delta":{"content":"PRIVATE_OUTPUT"},"finish_reason":"stop"}]
                return httpx.Response(200, text="data: " + json.dumps(response) + "\n\ndata: [DONE]\n\n", headers={"content-type":"text/event-stream"})
            return httpx.Response(200, json=response)

        async def asynchronous():
            async with openai.AsyncOpenAI(api_key="synthetic", http_client=httpx.AsyncClient(transport=httpx.MockTransport(transport)), max_retries=0) as client:
                for streamed in (False, True):
                    result = await client.chat.completions.create(model="gpt-4o-mini", messages=[{"role":"user","content":"PRIVATE_INPUT"}], stream=streamed)
                    if streamed:
                        async with result:
                            self.assertTrue([chunk async for chunk in result])
                    result = await client.responses.create(model="gpt-4o-mini", input="PRIVATE_INPUT", stream=streamed)
                    if streamed:
                        async with result:
                            self.assertTrue([chunk async for chunk in result])
        try:
            with openai.OpenAI(api_key="synthetic", http_client=httpx.Client(transport=httpx.MockTransport(transport)), max_retries=0) as client:
                for streamed in (False, True):
                    result = client.chat.completions.create(model="gpt-4o-mini", messages=[{"role":"user","content":"PRIVATE_INPUT"}], stream=streamed)
                    if streamed:
                        with result:
                            self.assertTrue(list(result))
                    result = client.responses.create(model="gpt-4o-mini", input="PRIVATE_INPUT", stream=streamed)
                    if streamed:
                        with result:
                            self.assertTrue(list(result))
            asyncio.run(asynchronous())
            self.assertEqual(len(output.events), 8)
            for event in output.events:
                self.assertNotIn("PRIVATE", json.dumps(event))
                self.assertIsNone(event.get("cost_usd"))
                self.assertEqual(event["total_tokens"], 10)
        finally:
            owner.close()

    def test_existing_unsampled_parent_is_respected(self):
        import httpx
        import openai
        from opentelemetry import trace
        global_before = trace.get_tracer_provider()
        output = Recorder()
        owner = runtime.OpenInferenceRuntime(CONFIG, "openai", output).install()
        parent = trace.NonRecordingSpan(trace.SpanContext(123, 456, True, trace.TraceFlags(0)))
        try:
            with trace.use_span(parent), openai.OpenAI(api_key="synthetic", http_client=httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, json={
                "id":"fixture", "object":"chat.completion", "created":1, "model":"gpt-4o-mini",
                "choices":[{"index":0,"message":{"role":"assistant","content":"answer"},"finish_reason":"stop"}]}))), max_retries=0) as client:
                client.chat.completions.create(model="gpt-4o-mini", messages=[{"role":"user","content":"input"}])
            self.assertEqual(output.events, [])
            self.assertIs(trace.get_tracer_provider(), global_before)
        finally:
            owner.close()

    def test_one_real_sdk_call_preserves_parent_and_restores_owned_hooks(self):
        import httpx
        import openai
        from opentelemetry import trace
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import SimpleSpanProcessor
        from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
        original = inspect.getattr_static(openai.OpenAI, "request")
        global_before = trace.get_tracer_provider()
        existing = TracerProvider(shutdown_on_exit=False)
        existing_export = InMemorySpanExporter()
        existing.add_span_processor(SimpleSpanProcessor(existing_export))
        output, notes = Recorder(), []
        owner = runtime.OpenInferenceRuntime(CONFIG, "openai", output, notes.append)
        with patch.object(trace, "set_tracer_provider", side_effect=AssertionError("global replacement")):
            owner.install()
            self.assertIs(owner.install(), owner)
            with self.assertRaises(ConfigurationError):
                runtime.OpenInferenceRuntime(CONFIG, "openai", Recorder()).install()
            def response(request):
                return httpx.Response(200, json={"id":"fixture","object":"chat.completion","created":1,"model":"gpt-4o-mini",
                    "choices":[{"index":0,"message":{"role":"assistant","content":"PRIVATE_OUTPUT"},"finish_reason":"stop"}],
                    "usage":{"prompt_tokens":7,"completion_tokens":3,"total_tokens":10}})
            try:
                with existing.get_tracer("app").start_as_current_span("original-agent", attributes={"openinference.span.kind":"AGENT"}) as parent:
                    with openai.OpenAI(api_key="synthetic", http_client=httpx.Client(transport=httpx.MockTransport(response)), max_retries=0) as client:
                        result = client.chat.completions.create(model="gpt-4o-mini", messages=[{"role":"user","content":"PRIVATE_INPUT"}])
                        self.assertEqual(result.choices[0].message.content, "PRIVATE_OUTPUT")
                self.assertEqual(len(output.events), 1)
                event = output.events[0]
                self.assertEqual(event["trace_id"], format(parent.context.trace_id, "032x"))
                self.assertEqual(event["parent_observation_id"], format(parent.context.span_id, "016x"))
                self.assertNotIn("PRIVATE", json.dumps(event))
            finally:
                first = owner.close()
                self.assertEqual(owner.close(), first)
                existing.shutdown()
        self.assertEqual(output.closes, 1)
        self.assertEqual(len(existing_export.get_finished_spans()), 1)
        self.assertIs(trace.get_tracer_provider(), global_before)
        self.assertIs(inspect.getattr_static(openai.OpenAI, "request"), original)
        self.assertIn("openinference_layer_openai", notes)

    def test_existing_upstream_instrumentor_is_not_replaced(self):
        from openinference.instrumentation.openai import OpenAIInstrumentor
        from opentelemetry.sdk.trace import TracerProvider
        import openai
        provider = TracerProvider(shutdown_on_exit=False)
        upstream = OpenAIInstrumentor()
        upstream.instrument(tracer_provider=provider, config=runtime._privacy_config())
        original = inspect.getattr_static(openai.OpenAI, "request")
        try:
            with self.assertRaisesRegex(ConfigurationError, "existing_instrumentor_use_span_processor"):
                runtime.OpenInferenceRuntime(CONFIG, "openai", Recorder()).install()
            self.assertIs(inspect.getattr_static(openai.OpenAI, "request"), original)
        finally:
            upstream.uninstrument()
            provider.shutdown()


@unittest.skipUnless(LITELLM, "verified LiteLLM SDK and OpenInference extra are not installed")
class LiteLLMRuntimeTests(unittest.TestCase):
    def test_existing_founder_agent_and_workflow_metadata_survive_without_source_changes(self):
        import litellm
        callbacks = litellm.success_callback
        original = litellm.completion
        output, notes = Recorder(), []
        owner = runtime.OpenInferenceRuntime(CONFIG, "litellm", output, notes.append).install()
        # The original application's imported alias is taken after startup.
        from litellm import completion, acompletion
        def arguments(agent, run):
            return {"model":"openai/gpt-4o-mini", "messages":[{"role":"user","content":"PRIVATE_INPUT"}],
                "metadata":{"generation_name":agent,"trace_id":run,"private":"PRIVATE_METADATA"},
                "mock_response":"PRIVATE_OUTPUT"}
        try:
            for name in ("profile-agent", "market-agent"):
                response = completion(**arguments(name, "founder-workflow-123"))
                self.assertEqual(response.choices[0].message.content, "PRIVATE_OUTPUT")
            asyncio.run(acompletion(**arguments("roadmap-agent", "different-workflow-456")))
            self.assertEqual(len(output.events), 3)
            first, second, third = output.events
            self.assertEqual(first["trace_id"], second["trace_id"])
            self.assertNotEqual(first["trace_id"], third["trace_id"])
            self.assertEqual([event["agent_name"] for event in output.events], ["profile-agent", "market-agent", "roadmap-agent"])
            self.assertNotEqual(first["observation_id"], second["observation_id"])
            for event in output.events:
                self.assertIsNone(event.get("cost_usd"))
                self.assertNotIn("PRIVATE", json.dumps(event))
                self.assertEqual(event["status"], "unknown")
            self.assertIs(litellm.success_callback, callbacks)
        finally:
            owner.close()
        self.assertIs(litellm.completion, original)
        self.assertIn("legacy_workflow_id_mapped_to_otel_trace", notes)


@unittest.skipUnless(LANGCHAIN, "verified LangChain Core and OpenInference extra are not installed")
class LangChainRuntimeTests(unittest.TestCase):
    def test_framework_callbacks_preserve_workflow_parent_without_extra_llm_counts(self):
        from langchain_core.callbacks import BaseCallbackManager
        from langchain_core.runnables import RunnableLambda
        from langchain_core.language_models.fake_chat_models import FakeListChatModel
        from opentelemetry.sdk.trace.export import SimpleSpanProcessor
        from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
        original = inspect.getattr_static(BaseCallbackManager, "__init__")
        output = Recorder()
        owner = runtime.OpenInferenceRuntime(CONFIG, "langchain", output).install()
        recorded = InMemorySpanExporter()
        owner._provider.add_span_processor(SimpleSpanProcessor(recorded))
        try:
            chain = RunnableLambda(lambda value: value).with_config(run_name="retrieve-documents") | FakeListChatModel(responses=["PRIVATE_OUTPUT"])
            result = chain.invoke("PRIVATE_INPUT", config={"run_name":"original-workflow", "metadata":{"private":"PRIVATE_METADATA"}})
            self.assertEqual(result.content, "PRIVATE_OUTPUT")
            self.assertEqual(len(output.events), 1)
            span = next(span for span in recorded.get_finished_spans() if span.name == "FakeListChatModel")
            event = output.events[0]
            self.assertEqual(event["trace_id"], format(span.context.trace_id, "032x"))
            self.assertEqual(event["parent_observation_id"], format(span.parent.span_id, "016x"))
            self.assertEqual(event["agent_name"], CONFIG.service_name)
            self.assertIsNone(event["total_tokens"])
            self.assertNotIn("PRIVATE", json.dumps(event))
        finally:
            owner.close()
        self.assertIs(inspect.getattr_static(BaseCallbackManager, "__init__"), original)


if __name__ == "__main__":
    unittest.main()
