#!/usr/bin/env python
"""Offline AsyncOpenAI SDK parsing proof; no provider, intake or database traffic.

No arguments print help using only the standard library. --run uses the explicitly
selected interpreter's pinned SDK, fixed synthetic wire fixtures and MockTransport.
The recording exporter verifies wrapper output; this is not an exporter/Mongo test.
"""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import socket
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
BASE_URL = "https://synthetic-provider.invalid/v1"


class CheckFailed(Exception):
    pass


def check(condition, code):
    if not condition:
        raise CheckFailed(code)


class RecordingExporter:
    """Bounded numeric observation sink, intentionally without a transport."""
    def __init__(self):
        self.started = 0
        self.finish_attempts = 0
        self.finished = []

    def start_call(self, **_metadata):
        self.started += 1
        check(self.started == 1, "unexpected_call_count")
        return self

    def finish(self, status, *, input_tokens=None, output_tokens=None,
               total_tokens=None, cost_usd=None):
        self.finish_attempts += 1
        check(not self.finished, "duplicate_terminal_event")
        self.finished.append({"status": status, "input_tokens": input_tokens,
            "output_tokens": output_tokens, "total_tokens": total_tokens,
            "cost_usd": cost_usd})


def deny_network(*_args, **_kwargs):
    raise CheckFailed("unexpected_network_attempt")


async def verify():
    # These imports are deliberately behind --run. The source fixture module is
    # stdlib-only at import; its dependency loader and Mongo suite are never run.
    sys.path.insert(0, str(ROOT / "tools"))
    sys.path.insert(0, str(ROOT / "examples" / "native-capture"))
    import httpx
    import openai
    import pydantic
    from guardian_openai import async_openai_call, async_openai_stream
    from test_mongo_providers import CANARY, fixture_reply

    check(openai.__version__ == "1.99.9", "unexpected_sdk_version")
    cases = []
    extra_checks = []
    phase = "configuration"

    async def verify_extra_storage(api):
        for count in (-1, 9, 2):
            _, body = fixture_reply(api, "known", False)
            field = "input_tokens_details" if api == "responses" else "prompt_tokens_details"
            body["usage"][field]["cache_write_tokens"] = count
            exporter = RecordingExporter()
            async with httpx.AsyncClient(transport=httpx.MockTransport(
                    lambda request: httpx.Response(200, json=body)), trust_env=False,
                    follow_redirects=False, timeout=2) as http:
                async with openai.AsyncOpenAI(api_key="synthetic-provider-key", organization="synthetic",
                        project="synthetic", webhook_secret="synthetic", base_url=BASE_URL,
                        max_retries=0, http_client=http) as client:
                    async def operation():
                        if api == "responses":
                            return await client.responses.create(model="fixture-known", input=CANARY)
                        return await client.chat.completions.create(model="fixture-known",
                            messages=[{"role": "user", "content": CANARY}])
                    result = await async_openai_call(exporter, operation, api=api,
                        agent_name="synthetic-extra", model="synthetic/model")
                    details = object.__getattribute__(result.usage, field)
                    check("cache_write_tokens" not in object.__getattribute__(details, "__dict__")
                        and object.__getattribute__(details, "__pydantic_extra__")["cache_write_tokens"] == count,
                        "unexpected_sdk_extra_storage")
            expected = {"status": "success", "input_tokens": 8 if count == 2 else None,
                "output_tokens": 2 if count == 2 else None, "total_tokens": 10 if count == 2 else None,
                "cost_usd": None}
            check(exporter.started == exporter.finish_attempts == 1
                and exporter.finished == [expected], "invalid_extra_usage_accepted")
            extra_checks.append({"api": api, "cache_write_tokens": count,
                "usage": "known" if count == 2 else "unknown", "status": "passed"})

    class FragmentedBody(httpx.AsyncByteStream):
        def __init__(self, content):
            self.content = content
            self.closed = False

        async def __aiter__(self):
            # Small fragments exercise the actual SDK's incremental UTF-8/SSE
            # decoder. Fixture size is fixed; no network or producer is involved.
            for index in range(0, len(self.content), 13):
                await asyncio.sleep(0)
                yield self.content[index:index + 13]

        async def aclose(self):
            self.closed = True

    class ObservedStream:
        def __init__(self, stream):
            self.stream = stream
            self.iterator = aiter(stream)
            self.originals = []

        def __aiter__(self):
            return self

        async def __anext__(self):
            item = await anext(self.iterator)
            check(len(self.originals) < 3, "unexpected_chunk_count")
            self.originals.append(item)
            return item

        async def aclose(self):
            await self.stream.close()

    try:
        async with asyncio.timeout(10):
            # MockTransport is the only HTTP transport. These guards also reject
            # accidental DNS/socket calls added by a future dependency change.
            with patch.object(socket, "getaddrinfo", deny_network), \
                    patch.object(socket, "create_connection", deny_network), \
                    patch.object(socket.socket, "connect", deny_network), \
                    patch.object(socket.socket, "connect_ex", deny_network):
                for api in ("responses", "chat_completions"):
                    for streaming in (False, True):
                        phase = api + ("_stream" if streaming else "_call")
                        exporter = RecordingExporter()
                        requests, seen, bodies = [], {}, []

                        async def respond(request):
                            expected_path = "/v1/responses" if api == "responses" else "/v1/chat/completions"
                            check(request.method == "POST" and request.url.scheme == "https"
                                and request.url.host == "synthetic-provider.invalid"
                                and request.url.path == expected_path, "unexpected_request_target")
                            check(request.headers.get("authorization") == "Bearer synthetic-provider-key",
                                "unexpected_provider_authentication")
                            check(not requests, "unexpected_provider_retry")
                            request_body = json.loads(request.content)
                            check(bool(request_body.get("stream", False)) is streaming, "unexpected_stream_mode")
                            if api == "chat_completions" and streaming:
                                check(request_body.get("stream_options") == {"include_usage": True},
                                    "missing_chat_usage_request")
                            requests.append(expected_path)
                            status, body = fixture_reply(api, "stream" if streaming else "known", streaming)
                            if streaming:
                                wire = FragmentedBody(body.encode("utf-8"))
                                bodies.append(wire)
                                return httpx.Response(status, headers={"content-type": "text/event-stream"}, stream=wire)
                            return httpx.Response(status, json=body)

                        async with httpx.AsyncClient(transport=httpx.MockTransport(respond),
                                trust_env=False, follow_redirects=False, timeout=2) as http:
                            async with openai.AsyncOpenAI(api_key="synthetic-provider-key",
                                    organization="synthetic", project="synthetic", webhook_secret="synthetic",
                                    base_url=BASE_URL, max_retries=0, http_client=http) as client:
                                async def operation():
                                    if api == "responses":
                                        result = await client.responses.create(model="fixture-known", input=CANARY,
                                            stream=streaming)
                                    else:
                                        options = {"stream": True, "stream_options": {"include_usage": True}} if streaming else {}
                                        result = await client.chat.completions.create(model="fixture-known",
                                            messages=[{"role": "user", "content": CANARY}], **options)
                                    seen["sdk_result"] = result
                                    if streaming:
                                        seen["observed"] = ObservedStream(result)
                                        return seen["observed"]
                                    return result

                                metadata = {"api": api, "agent_name": "synthetic-async", "model": "synthetic/model"}
                                if streaming:
                                    returned = [item async for item in async_openai_stream(exporter, operation, **metadata)]
                                    expected_count = 2 if api == "responses" else 3
                                    originals = seen["observed"].originals
                                    check(len(returned) == len(originals) == expected_count
                                        and all(first is second for first, second in zip(returned, originals)),
                                        "chunk_identity_changed")
                                    check(all(isinstance(item, pydantic.BaseModel) for item in returned), "non_sdk_chunk")
                                    check(bodies and all(body.closed for body in bodies)
                                        and seen["sdk_result"].response.is_closed, "stream_not_closed")
                                else:
                                    returned = await async_openai_call(exporter, operation, **metadata)
                                    check(returned is seen["sdk_result"] and isinstance(returned, pydantic.BaseModel),
                                        "result_identity_changed")

                        # Fixed expectations are independent of extraction code.
                        # Cached input (3) and reasoning output (1) are subsets.
                        expected = {"status": "success", "input_tokens": 8, "output_tokens": 2,
                                    "total_tokens": 10, "cost_usd": None}
                        check(exporter.started == exporter.finish_attempts == 1
                            and exporter.finished == [expected], "unexpected_terminal_measurement")
                        check(len(requests) == 1, "unexpected_request_count")
                        cases.append({"name": phase, "status": "passed", "tokens": {"input": 8, "output": 2, "total": 10},
                            "completion": "success", "cost_usd": None, "identity_preserved": True})
                    phase = api + "_extra_storage"
                    await verify_extra_storage(api)
    except BaseException as error:
        return {"status": "failed", "phase": phase,
            "code": str(error) if isinstance(error, CheckFailed) else "verification_failed"}

    return {"status": "passed", "finished_at": datetime.now(timezone.utc).isoformat(),
        "passed": len(cases), "failed": 0, "runtime_version": ".".join(map(str, sys.version_info[:3])),
        "sdk_version": openai.__version__, "httpx_version": httpx.__version__, "pydantic_version": pydantic.__version__,
        "transport": "httpx.MockTransport", "scope": "AsyncOpenAI parsing and async wrapper output; recording exporter only",
        "network_calls": 0, "paid_provider_calls": 0,
        "adapter_sha256": hashlib.sha256((ROOT / "examples" / "native-capture" / "guardian_openai.py").read_bytes()).hexdigest(),
        "tests": cases, "extra_field_validation": extra_checks}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true", help="Run the fixed offline fixtures using the installed SDK")
    arguments = parser.parse_args(argv)
    if not arguments.run:
        parser.print_help()
        return 0
    try:
        result = asyncio.run(verify())
    except BaseException:
        result = {"status": "failed", "phase": "configuration", "code": "verification_failed"}
    print(json.dumps(result, indent=2))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
