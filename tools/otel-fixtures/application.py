"""Synthetic original SDK work in an installed-wheel environment, outside checkout."""
import asyncio
from contextlib import contextmanager
import hashlib
import importlib.metadata
import json
import logging
from pathlib import Path
import socket
import sys

CANARY = "synthetic-provider-private-\u03c0-content"


def local_connections(event, arguments):
    if event == "socket.connect":
        address = arguments[1]
        if not isinstance(address, tuple) or address[0] not in ("127.0.0.1", "::1"):
            raise RuntimeError("fixture_nonlocal_connection_refused")
    if event == "socket.getaddrinfo" and arguments[0] not in ("127.0.0.1", "::1", "localhost", None):
        raise RuntimeError("fixture_nonlocal_dns_refused")


sys.addaudithook(local_connections)
logging.disable(logging.CRITICAL)


@contextmanager
def agent_label(name):
    from opentelemetry import context
    token = context.attach(context.set_value("sillage.agent.name", name))
    try:
        yield
    finally:
        context.detach(token)


def programmatic(config, replay=False):
    from opentelemetry import trace
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider, SpanProcessor, ReadableSpan
    from opentelemetry.sdk.trace.sampling import ALWAYS_ON
    from opentelemetry.trace import SpanContext, TraceFlags, Status, StatusCode
    from sillage_observe import Configuration
    from sillage_observe.otel import SillageSpanProcessor
    from sillage_observe._vendor.guardian_exporter import BackgroundExporter

    class NumericSink:
        def __init__(self):
            self.events = []
            self.transport = BackgroundExporter(origin=config["collector"], token=config["token"], allow_local=True)
        def emit(self, event):
            assert CANARY not in json.dumps(event, ensure_ascii=False)
            self.events.append(dict(event))
            return self.transport.emit(event)
        def flush(self, timeout=3):
            return self.transport.flush(timeout)
        def close(self, timeout=3):
            return self.transport.close(timeout)

    class ExistingProcessor(SpanProcessor):
        def __init__(self):
            self.spans, self.closed = [], False
        def on_end(self, span):
            self.spans.append(span)
        def shutdown(self):
            self.closed = True
        def force_flush(self, timeout_millis=30000):
            return True

    settings = Configuration(origin=config["collector"], token=config["token"], allow_local=True,
                             service_name="otel-programmatic")
    sink = NumericSink()
    processor = SillageSpanProcessor(settings, exporter=sink)
    global_before = trace.get_tracer_provider()
    provider = TracerProvider(sampler=ALWAYS_ON, resource=Resource({"private.resource": CANARY}), shutdown_on_exit=False)
    existing = ExistingProcessor()
    provider.add_span_processor(existing)
    provider.add_span_processor(processor)
    tracer = provider.get_tracer("independent-fixture")
    expected = []
    def record(span, agent, status, tokens):
        context = span.get_span_context()
        expected.append({"id": f"{context.span_id:016x}", "trace_id": f"{context.trace_id:032x}",
            "parent_observation_id": f"{span.parent.span_id:016x}" if span.parent else None,
            "agent_name": agent, "status": status, "total_tokens": tokens})
    try:
        if replay:
            saved = json.loads((Path(config["work"]) / "replay.json").read_text(encoding="utf8"))
            context = SpanContext(trace_id=saved["trace_id"], span_id=saved["span_id"], is_remote=False, trace_flags=TraceFlags(1))
            parent = SpanContext(trace_id=saved["trace_id"], span_id=saved["parent_id"], is_remote=False, trace_flags=TraceFlags(1))
            attributes = {"openinference.span.kind": "LLM", "llm.model_name": "programmatic-known",
                "sillage.agent.name": "planning-agent", "llm.token_count.prompt": 8, "llm.token_count.completion": 2,
                "llm.token_count.total": 10, "gen_ai.response.finish_reason": "stop"}
            def copy_span(attrs):
                return ReadableSpan("known", context=context, parent=parent, attributes=attrs,
                    start_time=saved["start_time"], end_time=saved["end_time"], status=Status(StatusCode.OK))
            processor.on_end(copy_span(attributes))
            processor.on_end(copy_span({**attributes, "llm.token_count.prompt": 9, "llm.token_count.total": 11}))
            assert processor.force_flush(5000)
            return {"status": "passed", "replayed_id": f"{saved['span_id']:016x}",
                "replayed_trace": f"{saved['trace_id']:032x}", "submitted_events": 2}

        with tracer.start_as_current_span("planning-agent", attributes={"openinference.span.kind": "AGENT", "input.value": CANARY}):
            with tracer.start_as_current_span("retrieval-chain", attributes={"openinference.span.kind": "CHAIN",
                    "llm.model_name": "must-not-count", "llm.token_count.total": 999999}):
                with tracer.start_as_current_span("known", attributes={"openinference.span.kind": "LLM",
                        "llm.model_name": "programmatic-known", "llm.token_count.prompt": 8,
                        "llm.token_count.completion": 2, "llm.token_count.total": 10,
                        "gen_ai.response.finish_reason": "stop", "input.value": CANARY, "output.value": CANARY}) as span:
                    span.set_status(Status(StatusCode.OK))
                    record(span, "planning-agent", "success", 10)
                known = existing.spans[-1]
                (Path(config["work"]) / "replay.json").write_text(json.dumps({
                    "trace_id": known.context.trace_id, "span_id": known.context.span_id,
                    "parent_id": known.parent.span_id, "start_time": known.start_time, "end_time": known.end_time}), encoding="utf8")
                with tracer.start_as_current_span("zero-unset", attributes={"openinference.span.kind": "LLM",
                        "llm.model_name": "programmatic-zero", "llm.token_count.prompt": 0,
                        "llm.token_count.completion": 0}) as span:
                    record(span, "planning-agent", "unknown", 0)
                async def concurrent():
                    entered = asyncio.Event()
                    async def task(name, tokens):
                        with tracer.start_as_current_span(name, attributes={"openinference.span.kind": "AGENT"}):
                            if name == "alpha-agent":
                                entered.set()
                                await asyncio.sleep(.01)
                            else:
                                await entered.wait()
                            attrs = {"openinference.span.kind": "LLM", "llm.model_name": "programmatic-concurrent"}
                            if tokens is not None:
                                attrs.update({"llm.token_count.prompt": 4, "llm.token_count.completion": 1,
                                              "gen_ai.response.finish_reason": "stop"})
                            with tracer.start_as_current_span("concurrent-call", attributes=attrs) as item:
                                if tokens is not None:
                                    item.set_status(Status(StatusCode.OK))
                                record(item, name, "success" if tokens is not None else "unknown", tokens)
                                await asyncio.sleep(0)
                    await asyncio.gather(task("alpha-agent", 5), task("beta-agent", None))
                asyncio.run(concurrent())
        for kind in ("AGENT", "CHAIN", "TOOL", "RETRIEVER", "EMBEDDING"):
            with tracer.start_as_current_span("ignored-" + kind, attributes={"openinference.span.kind": kind,
                    "llm.model_name": "not-a-call", "llm.token_count.total": 999999, "input.value": CANARY}):
                pass
        with tracer.start_as_current_span("http-request", attributes={"http.request.method": "POST", "url.full": CANARY}):
            pass
        assert len(sink.events) == 4
        by_id = {row["observation_id"]: row for row in sink.events}
        for row in expected:
            actual = by_id[row["id"]]
            assert all(actual[key] == value for key, value in row.items() if key != "id")
            assert actual["cost_usd"] is None
        assert len({row["trace_id"] for row in expected}) == 1
        assert len(existing.spans) == 14
        assert provider.sampler is ALWAYS_ON and trace.get_tracer_provider() is global_before
        assert processor.force_flush(5000)
        processor.close(timeout=3)
        assert not existing.closed
        with tracer.start_as_current_span("existing-processor-still-owned"):
            pass
        assert len(existing.spans) == 15 and len(sink.events) == 4
        return {"status": "passed", "expected": expected, "events": 4,
            "other_processor_preserved": True, "sampler_preserved": True, "global_provider_preserved": True,
            "concurrent_agent_context_preserved": True, "non_llm_spans_not_counted": True}
    finally:
        processor.close(timeout=3)
        provider.shutdown()


def openai_calls(config):
    import httpx
    from openai import OpenAI, AsyncOpenAI, BadRequestError
    operations = []
    checked_requests = []
    def validate_request(request):
        payload = json.loads(request.content)
        assert request.headers["authorization"] == "Bearer synthetic-provider-key"
        assert payload.get("input") == CANARY or payload.get("messages") == [{"role": "user", "content": CANARY}]
        checked_requests.append(True)
    async def validate_async_request(request):
        validate_request(request)
    def label(api, mode, asynchronous=False):
        name = ("async-" if asynchronous else "sync-") + api + "-" + mode
        operations.append({"agent": name, "mode": mode, "api": api})
        return agent_label(name)
    with OpenAI(api_key="synthetic-provider-key", base_url=config["provider"] + "/v1", max_retries=0,
                http_client=httpx.Client(event_hooks={"request": [validate_request]})) as client:
        for api in ("chat", "responses"):
            create = client.responses.create if api == "responses" else client.chat.completions.create
            content = {"input": CANARY} if api == "responses" else {"messages": [{"role": "user", "content": CANARY}]}
            with label(api, "known"):
                result = create(model="fixture-known", **content)
                assert result.usage.total_tokens == 10
                assert CANARY in (result.output_text if api == "responses" else result.choices[0].message.content)
            kwargs = {} if api == "responses" else {"stream_options": {"include_usage": True}}
            with label(api, "stream"):
                with create(model="fixture-stream", stream=True, **content, **kwargs) as stream:
                    assert list(stream)
            with label(api, "early"):
                with create(model="fixture-early", stream=True, **content, **kwargs) as stream:
                    next(stream)
            with label(api, "failure"):
                if api == "responses":
                    assert create(model="fixture-failure", **content).status == "failed"
                else:
                    try:
                        create(model="fixture-failure", **content)
                    except BadRequestError as error:
                        assert error.status_code == 400
                    else:
                        raise AssertionError("provider_error_swallowed")
    async def asynchronous():
        async with AsyncOpenAI(api_key="synthetic-provider-key", base_url=config["provider"] + "/v1", max_retries=0,
                http_client=httpx.AsyncClient(event_hooks={"request": [validate_async_request]})) as client:
            for api in ("chat", "responses"):
                create = client.responses.create if api == "responses" else client.chat.completions.create
                content = {"input": CANARY} if api == "responses" else {"messages": [{"role": "user", "content": CANARY}]}
                with label(api, "known", True):
                    assert (await create(model="fixture-known", **content)).usage.total_tokens == 10
                kwargs = {} if api == "responses" else {"stream_options": {"include_usage": True}}
                with label(api, "stream", True):
                    async with await create(model="fixture-stream", stream=True, **content, **kwargs) as stream:
                        assert [chunk async for chunk in stream]
                with label(api, "early", True):
                    async with await create(model="fixture-early", stream=True, **content, **kwargs) as stream:
                        await anext(stream)
                with label(api, "failure", True):
                    if api == "responses":
                        assert (await create(model="fixture-failure", **content)).status == "failed"
                    else:
                        try:
                            await create(model="fixture-failure", **content)
                        except BadRequestError as error:
                            assert error.status_code == 400
                        else:
                            raise AssertionError("async_provider_error_swallowed")
        entered = asyncio.Event()
        async def waiting(_request):
            entered.set()
            await asyncio.Event().wait()
        async with AsyncOpenAI(api_key="synthetic-provider-key", max_retries=0,
                http_client=httpx.AsyncClient(transport=httpx.MockTransport(waiting))) as client:
            with label("chat", "cancel", True):
                operation = asyncio.create_task(client.chat.completions.create(model="fixture-cancel",
                    messages=[{"role": "user", "content": CANARY}]))
                await asyncio.wait_for(entered.wait(), 3)
                operation.cancel()
                try:
                    await operation
                except asyncio.CancelledError:
                    pass
                else:
                    raise AssertionError("application_cancellation_swallowed")
    asyncio.run(asynchronous())
    assert len(checked_requests) == 16
    return {"status": "passed", "operations": operations, "provider_results_preserved": True,
            "provider_arguments_preserved": True, "application_cancellation_preserved": True}


def langchain_calls(config):
    from langchain_core.runnables import RunnableLambda, RunnableParallel
    from langchain_core.language_models.fake_chat_models import FakeListChatModel
    import httpx
    from openai import OpenAI
    chain = RunnableLambda(lambda value: value).with_config(run_name="retrieve-fixture") | RunnableParallel(
        first=FakeListChatModel(responses=[CANARY]), second=FakeListChatModel(responses=[CANARY]))
    with agent_label("langchain-workflow"):
        result = chain.invoke(CANARY, config={"run_name": "fixture-workflow"})
    assert result["first"].content == result["second"].content == CANARY
    def reply(request):
        assert json.loads(request.content)["messages"][0]["content"] == CANARY
        return httpx.Response(200, json={"id": "opaque-call", "object": "chat.completion", "created": 1,
            "model": "opaque-provider", "choices": [{"index": 0, "message": {"role": "assistant", "content": CANARY},
            "finish_reason": "stop"}], "usage": {"prompt_tokens": 8, "completion_tokens": 2, "total_tokens": 10}})
    with OpenAI(api_key="synthetic-provider-key", max_retries=0,
            http_client=httpx.Client(transport=httpx.MockTransport(reply))) as client:
        opaque = RunnableLambda(lambda value: client.chat.completions.create(model="opaque-provider",
            messages=[{"role": "user", "content": value}]))
        with agent_label("opaque-sdk-in-runnable"):
            assert opaque.invoke(CANARY).choices[0].message.content == CANARY
    return {"status": "passed", "framework_llm_operations": 2, "opaque_sdk_operations": 1,
            "provider_results_preserved": True}


def founder_calls(config):
    sys.path.insert(0, config["founder_source"])
    from services.llm_fallback import LlmChat, UserMessage, configure_langfuse
    import litellm
    litellm.suppress_debug_info = True
    assert not configure_langfuse()
    litellm.api_base = config["provider"] + "/v1"
    litellm.api_key = "synthetic-provider-key"
    names = ("profile_analyst", "market_hunter", "fit_evaluator", "roadmap_architect", "tooling_advisor")
    async def invoke():
        for name in names:
            llm = LlmChat(api_key="synthetic-provider-key", system_message=CANARY)
            llm.fallback_chain = ["openai/fixture-failure", "openai/fixture-known"]
            result = await llm.send_message(UserMessage(CANARY), agent_name=name,
                run_id=config["legacy_run"], user_id=CANARY)
            assert result == CANARY
    asyncio.run(invoke())
    source = "sillage:litellm:run:v1\0otel-founder\0" + config["legacy_run"]
    return {"status": "passed", "agents": list(names), "attempts": 10,
        "trace_id": hashlib.sha256(source.encode()).digest()[:16].hex(), "provider_results_preserved": True}


def main():
    phase = sys.argv[1] if len(sys.argv) == 2 else "invalid"
    try:
        config = json.loads(sys.stdin.buffer.read(16385))
        import sillage_observe
        package = Path(sillage_observe.__file__).resolve()
        assert package.is_relative_to(Path(sys.prefix).resolve())
        assert not package.is_relative_to(Path(config["repository"]).resolve())
        assert Path.cwd() == Path(config["work"]).resolve()
        if phase in ("programmatic", "replay"):
            result = programmatic(config, phase == "replay")
        elif phase == "openai":
            result = openai_calls(config)
        elif phase == "langchain":
            result = langchain_calls(config)
        elif phase == "founder":
            result = founder_calls(config)
        else:
            raise AssertionError("fixture_phase_invalid")
        result.update(phase=phase, wheel_import_outside_checkout=True,
            versions={name: importlib.metadata.version(name) for name in ("sillage-observe", "opentelemetry-sdk",
                "openinference-instrumentation", "openai", "litellm", "langchain-core")})
        print(json.dumps(result))
        return 0
    except BaseException as error:
        import traceback
        frames = [str(frame.lineno) for frame in traceback.extract_tb(error.__traceback__)
                  if Path(frame.filename).name == Path(__file__).name]
        print(json.dumps({"status": "failed", "phase": phase, "error_type": type(error).__name__, "fixture_lines": frames}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
