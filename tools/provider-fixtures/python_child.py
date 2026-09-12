"""Explicit synthetic SDK child; no arguments print help without third parties."""
import json
from pathlib import Path
import sys
from urllib.parse import urlsplit


def main():
    if sys.argv[1:] != ["--run-fixture"]:
        print("Usage: python python_child.py --run-fixture < synthetic-config.json")
        return 0
    phase = "configuration"
    exporter = None
    try:
        config = json.loads(sys.stdin.read(16384))
        for field in ("origin", "provider_origin"):
            value = config[field]
            address = urlsplit(value)
            assert address.scheme == "http" and address.hostname == "127.0.0.1" and address.port
            assert value == "http://127.0.0.1:" + str(address.port)
        sys.path.insert(0, config["module_dir"])
        import httpx
        import openai
        from guardian_exporter import BackgroundExporter
        from guardian_openai import openai_call, openai_stream
        from uuid import uuid4

        base = httpx.URL(config["provider_origin"])
        assert base.scheme == "http" and base.host == "127.0.0.1" and base.port

        class LoopbackOnly(httpx.BaseTransport):
            def __init__(self):
                self.inner = httpx.HTTPTransport(retries=0, trust_env=False)

            def handle_request(self, request):
                assert (request.url.scheme, request.url.host, request.url.port) == (base.scheme, base.host, base.port)
                return self.inner.handle_request(request)

            def close(self):
                self.inner.close()

        exporter = BackgroundExporter(origin=config["origin"], token=config["token"], allow_local=True,
                                      test_mode=config["test_mode"])
        trace = "sdk-python-" + uuid4().hex
        api = config["api"]
        modes = ["known"] if config["test_mode"] else ["known", "stream", "missing", "early", "failure", "inconsistent"]
        shapes = []
        with httpx.Client(transport=LoopbackOnly(), trust_env=False, follow_redirects=False, timeout=3) as http:
            with openai.OpenAI(api_key="synthetic-provider-key", organization="synthetic", project="synthetic",
                    webhook_secret="synthetic", base_url=config["provider_origin"] + "/v1", max_retries=0, http_client=http) as client:
                for mode in modes:
                    phase = mode
                    metadata = {"api": api, "agent_name": "sdk-" + mode, "model": "synthetic/model", "trace_id": trace}
                    seen = {}

                    def operation():
                        try:
                            if api == "responses":
                                result = client.responses.create(model="fixture-" + mode, input=config["canary"],
                                    stream=mode in ("stream", "early"))
                            else:
                                options = {"stream": True, "stream_options": {"include_usage": True}} if mode in ("stream", "early") else {}
                                result = client.chat.completions.create(model="fixture-" + mode,
                                    messages=[{"role": "user", "content": config["canary"]}], **options)
                            seen["result"] = result
                            return result
                        except Exception as error:
                            seen["error"] = error
                            raise

                    if mode in ("stream", "early"):
                        stream = openai_stream(exporter, operation, **metadata)
                        try:
                            for item in stream:
                                shapes.append(type(item).__name__)
                                if mode == "early":
                                    break
                                # Consumer mutation after yield cannot replace the
                                # usage snapshot already admitted by the helper.
                                terminal = getattr(item, "response", None)
                                usage = getattr(terminal, "usage", None) if terminal is not None else getattr(item, "usage", None)
                                if usage is not None:
                                    if api == "responses": usage.input_tokens = 9999
                                    else: usage.prompt_tokens = 9999
                        finally:
                            stream.close()
                    else:
                        try:
                            result = openai_call(exporter, operation, **metadata)
                            assert result is seen["result"]
                            shapes.append(type(result).__name__)
                        except Exception as error:
                            assert mode == "failure" and api == "chat_completions" and error is seen.get("error")
                phase = "flush"
                assert exporter.flush(10)["drained"]
        phase = "close"
        result = exporter.close(10)
        assert result["drained"]
        print(json.dumps({"status": "passed", "trace_id": trace, "sdk_version": openai.__version__,
            "runtime_version": ".".join(map(str, sys.version_info[:3])), "stats": exporter.snapshot(),
            "sdk_shapes": sorted(set(shapes))}))
        return 0
    except BaseException:
        if exporter is not None:
            try: exporter.close(1)
            except BaseException: pass
        print(json.dumps({"status": "failed", "phase": phase}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
