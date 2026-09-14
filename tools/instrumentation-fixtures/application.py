"""Original SDK operations, launched from an installed Sillage wheel in a temp cwd.

Only local synthetic provider transports are permitted. No Sillage call wrappers
appear here: the parent starts this file through the installed console launcher.
"""
import asyncio
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


sys.addaudithook(local_connections)
logging.disable(logging.CRITICAL)


def sync_calls(origin):
    from openai import OpenAI, BadRequestError
    from openai.types.responses import Response
    from openai.types.chat import ChatCompletion
    client = OpenAI(api_key="synthetic-provider-key", base_url=origin + "/v1", max_retries=0)
    try:
        for api in ("responses", "chat"):
            create = client.responses.create if api == "responses" else client.chat.completions.create
            content = {"input": CANARY} if api == "responses" else {"messages": [{"role": "user", "content": CANARY}]}
            result = create(model="fixture-known", **content)
            assert isinstance(result, Response if api == "responses" else ChatCompletion)
            assert result.usage.total_tokens == 10
            # The observer must have taken a scalar snapshot before the caller mutates usage.
            result.usage.total_tokens = 99999
            kwargs = {} if api == "responses" else {"stream_options": {"include_usage": True}}
            with create(model="fixture-stream", stream=True, **content, **kwargs) as stream:
                assert stream.response.status_code == 200
                chunks = list(stream)
                assert chunks and all(hasattr(chunk, "model_dump") for chunk in chunks)
            with create(model="fixture-early", stream=True, **content, **kwargs) as stream:
                next(stream)
            if api == "responses":
                failed = create(model="fixture-failure", **content)
                assert failed.status == "failed" and CANARY in failed.error.message
            else:
                try:
                    create(model="fixture-failure", **content)
                except BadRequestError as error:
                    assert error.status_code == 400 and CANARY in error.message
                else:
                    raise AssertionError("provider_error_swallowed")
    finally:
        client.close()


async def async_calls(origin):
    from openai import AsyncOpenAI, BadRequestError
    import httpx
    async with AsyncOpenAI(api_key="synthetic-provider-key", base_url=origin + "/v1", max_retries=0) as client:
        for api in ("responses", "chat"):
            create = client.responses.create if api == "responses" else client.chat.completions.create
            content = {"input": CANARY} if api == "responses" else {"messages": [{"role": "user", "content": CANARY}]}
            result = await create(model="fixture-known", **content)
            assert result.usage.total_tokens == 10
            kwargs = {} if api == "responses" else {"stream_options": {"include_usage": True}}
            async with await create(model="fixture-stream", stream=True, **content, **kwargs) as stream:
                assert stream.response.status_code == 200
                chunks = [chunk async for chunk in stream]
                assert chunks and all(hasattr(chunk, "model_dump") for chunk in chunks)
            async with await create(model="fixture-early", stream=True, **content, **kwargs) as stream:
                await anext(stream)
            if api == "responses":
                failed = await create(model="fixture-failure", **content)
                assert failed.status == "failed"
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
        operation = asyncio.create_task(client.responses.create(model="fixture-cancel", input=CANARY))
        await asyncio.wait_for(entered.wait(), 3)
        operation.cancel()
        try:
            await operation
        except asyncio.CancelledError:
            pass
        else:
            raise AssertionError("application_cancellation_swallowed")


async def founder_calls(config):
    # Source files are imported unchanged. Only model/base-URL configuration is
    # replaced by a local provider fixture; this is not a real model analysis.
    sys.path.insert(0, config["founder_source"])
    from services.llm_fallback import LlmChat, UserMessage, configure_langfuse
    import litellm
    from litellm import acompletion
    litellm.suppress_debug_info = True
    assert not configure_langfuse()
    assert getattr(acompletion, "__module__", None) is not None
    litellm.api_base = config["provider"] + "/v1"
    litellm.api_key = "synthetic-provider-key"
    for name in ("profile_analyst", "market_hunter", "fit_evaluator", "roadmap_architect", "tooling_advisor"):
        llm = LlmChat(api_key="synthetic-provider-key", system_message=CANARY)
        llm.fallback_chain = ["openai/fixture-failure", "openai/fixture-known"]
        result = await llm.send_message(UserMessage(CANARY), agent_name=name,
            run_id=config["trace_id"], user_id=CANARY)
        assert result == CANARY


def shaped_response(request):
    """Wire responses for the SDK's structured parser and stream managers."""
    import httpx
    payload = json.loads(request.content)
    text = json.dumps({"answer": CANARY})
    if request.url.path.endswith("/responses"):
        response = {"id": "resp_manager", "object": "response", "created_at": 1700000000,
            "status": "completed", "model": "fixture-structured", "parallel_tool_calls": False,
            "tool_choice": "auto", "tools": [], "error": None,
            "output": [{"id": "msg_fixture", "type": "message", "status": "completed", "role": "assistant",
                "content": [{"type": "output_text", "text": text, "annotations": []}]}],
            "usage": {"input_tokens": 8, "output_tokens": 2, "total_tokens": 10}}
        if payload.get("stream"):
            start = {**response, "status": "in_progress", "output": [], "usage": None}
            events = [{"type": "response.created", "sequence_number": 0, "response": start},
                {"type": "response.completed", "sequence_number": 1, "response": response}]
            wire = "".join("event: " + row["type"] + "\ndata: " + json.dumps(row) + "\n\n" for row in events)
            return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=wire)
    else:
        response = {"id": "chatcmpl_manager", "object": "chat.completion", "created": 1700000000,
            "model": "fixture-structured", "choices": [{"index": 0, "finish_reason": "stop",
                "message": {"role": "assistant", "content": text, "refusal": None}}],
            "usage": {"prompt_tokens": 8, "completion_tokens": 2, "total_tokens": 10}}
        if payload.get("stream"):
            base = {key: value for key, value in response.items() if key not in ("choices", "usage")}
            base["object"] = "chat.completion.chunk"
            events = [{**base, "choices": [{"index": 0, "delta": {"role": "assistant", "content": text},
                       "finish_reason": None}], "usage": None},
                {**base, "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}], "usage": None},
                {**base, "choices": [], "usage": response["usage"]}]
            wire = "".join("data: " + json.dumps(row) + "\n\n" for row in events) + "data: [DONE]\n\n"
            return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=wire)
    return httpx.Response(200, json=response)


def structured_calls():
    import httpx
    from openai import OpenAI
    from pydantic import BaseModel

    class Answer(BaseModel):
        answer: str

    with OpenAI(api_key="synthetic-provider-key", max_retries=0,
            http_client=httpx.Client(transport=httpx.MockTransport(shaped_response))) as client:
        response = client.responses.parse(model="fixture-structured", input=CANARY, text_format=Answer)
        assert response.output_parsed.answer == CANARY
        response = client.chat.completions.parse(model="fixture-structured",
            messages=[{"role": "user", "content": CANARY}], response_format=Answer)
        assert response.choices[0].message.parsed.answer == CANARY
        with client.responses.stream(model="fixture-manager", input=CANARY) as stream:
            list(stream)
            assert json.loads(stream.get_final_response().output_text)["answer"] == CANARY
        with client.chat.completions.stream(model="fixture-manager", messages=[{"role": "user", "content": CANARY}],
                stream_options={"include_usage": True}) as stream:
            list(stream)
            assert json.loads(stream.get_final_completion().choices[0].message.content)["answer"] == CANARY


async def async_structured_calls():
    import httpx
    from openai import AsyncOpenAI
    from pydantic import BaseModel

    class Answer(BaseModel):
        answer: str

    async with AsyncOpenAI(api_key="synthetic-provider-key", max_retries=0,
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(shaped_response))) as client:
        response = await client.responses.parse(model="fixture-structured", input=CANARY, text_format=Answer)
        assert response.output_parsed.answer == CANARY
        response = await client.chat.completions.parse(model="fixture-structured",
            messages=[{"role": "user", "content": CANARY}], response_format=Answer)
        assert response.choices[0].message.parsed.answer == CANARY
        async with client.responses.stream(model="fixture-manager", input=CANARY) as stream:
            [event async for event in stream]
            assert json.loads((await stream.get_final_response()).output_text)["answer"] == CANARY
        async with client.chat.completions.stream(model="fixture-manager", messages=[{"role": "user", "content": CANARY}],
                stream_options={"include_usage": True}) as stream:
            [event async for event in stream]
            assert json.loads((await stream.get_final_completion()).choices[0].message.content)["answer"] == CANARY


def main():
    phase = sys.argv[1] if len(sys.argv) == 2 else "invalid"
    try:
        config = json.loads(sys.stdin.buffer.read(16385))
        import sillage_observe
        package = Path(sillage_observe.__file__).resolve()
        assert package.is_relative_to(Path(sys.prefix).resolve())
        assert not package.is_relative_to(Path(config["repository"]).resolve())
        assert Path.cwd() == Path(config["work"]).resolve()
        if phase == "openai":
            sync_calls(config["provider"])
            asyncio.run(async_calls(config["provider"]))
            structured_calls()
            asyncio.run(async_structured_calls())
        elif phase == "founder":
            asyncio.run(founder_calls(config))
        else:
            raise AssertionError("fixture_phase_invalid")
        print(json.dumps({"status": "passed", "phase": phase, "wheel_import_outside_checkout": True,
            "openai": importlib.metadata.version("openai"), "litellm": importlib.metadata.version("litellm"),
            "python": sys.version.split()[0]}))
        return 0
    except BaseException as error:
        import traceback
        frames = [str(frame.lineno) for frame in traceback.extract_tb(error.__traceback__)
                  if Path(frame.filename).name == Path(__file__).name]
        print(json.dumps({"status": "failed", "phase": phase, "error_type": type(error).__name__, "fixture_lines": frames}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
