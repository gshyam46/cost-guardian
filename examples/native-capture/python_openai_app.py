"""Offline OpenAI-shaped lifecycle examples; --send-test exports synthetic usage."""
import argparse
import asyncio
import json

from guardian_exporter import BackgroundExporter
from guardian_openai import openai_call, async_openai_call, openai_stream, async_openai_stream


def response(identifier="resp_synthetic", status="completed"):
    return {"id": identifier, "object": "response", "status": status,
            "usage": {"input_tokens": 12, "output_tokens": 8, "total_tokens": 20}}


def exercise(exporter):
    # In the application, operation is a zero-argument lambda that calls the
    # application's existing client.responses.create(...) or chat equivalent.
    result = response()
    assert openai_call(exporter, lambda: result, agent_name="example-responses", model="synthetic/model") is result
    chat = {"object": "chat.completion", "choices": [{"index": 0, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}}
    assert openai_call(exporter, lambda: chat, api="chat_completions",
                       agent_name="example-chat", model="synthetic/model") is chat
    chunks = [{"type": "response.completed", "response": response("resp_stream")}]
    assert list(openai_stream(exporter, lambda: iter(chunks), agent_name="example-stream", model="synthetic/model")) == chunks
    failed = response("resp_failed", "failed")
    assert openai_call(exporter, lambda: failed, agent_name="example-failed", model="synthetic/model") is failed


async def async_exercise(exporter):
    result = response("resp_async")

    async def operation():
        return result

    assert await async_openai_call(exporter, operation, agent_name="example-async", model="synthetic/model") is result

    async def stream():
        yield {"type": "response.completed", "response": response("resp_async_stream")}

    async def streaming_operation():
        return stream()

    async for _ in async_openai_stream(exporter, streaming_operation,
                                      agent_name="example-async-stream", model="synthetic/model"):
        pass


def main(argv=None):
    parser = argparse.ArgumentParser(description="Run synthetic OpenAI-shaped usage with optional test-only Guardian export.")
    parser.add_argument("--send-test", action="store_true")
    parser.add_argument("--allow-local-http", action="store_true")
    args = parser.parse_args(argv)
    if not args.send_test:
        parser.print_help()
        return 0
    try:
        exporter = BackgroundExporter(allow_local=args.allow_local_http, test_mode=True)
    except ValueError:
        print(json.dumps({"ok": False, "code": "invalid_configuration"}))
        return 1
    try:
        exercise(exporter)
        asyncio.run(async_exercise(exporter))
    finally:
        result = exporter.close(timeout=5)
    print(json.dumps(result))
    return 0 if result["confirmed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
