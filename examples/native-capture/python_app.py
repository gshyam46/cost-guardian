"""Provider-neutral lifecycle examples; no arguments perform any work."""
import argparse
import asyncio
import json

from guardian_exporter import BackgroundExporter


def run_call(exporter, provider, *, agent_name, model, trace_id=None, parent_observation_id=None):
    handle = exporter.start_call(agent_name=agent_name, model=model, trace_id=trace_id,
                                 parent_observation_id=parent_observation_id)
    try:
        result = provider()
    except Exception:
        handle.finish("error")
        raise
    else:
        handle.finish("success")
        return result
    finally:
        # KeyboardInterrupt/SystemExit/cancellation have no observed completion.
        handle.finish("unknown")


def stream_call(exporter, provider, *, agent_name, model, trace_id=None, parent_observation_id=None):
    handle = exporter.start_call(agent_name=agent_name, model=model, trace_id=trace_id,
                                 parent_observation_id=parent_observation_id)
    try:
        result = yield from provider()
    except Exception:
        handle.finish("error")
        raise
    else:
        handle.finish("success")
        return result
    finally:
        # Call close() explicitly on early exit; GC timing is not a flush policy.
        handle.finish("unknown")


async def async_run_call(exporter, provider, *, agent_name, model, trace_id=None, parent_observation_id=None):
    handle = exporter.start_call(agent_name=agent_name, model=model, trace_id=trace_id,
                                 parent_observation_id=parent_observation_id)
    try:
        result = await provider()
    except Exception:
        handle.finish("error")
        raise
    else:
        handle.finish("success")
        return result
    finally:
        handle.finish("unknown")


async def async_stream_call(exporter, provider, *, agent_name, model, trace_id=None, parent_observation_id=None):
    handle = exporter.start_call(agent_name=agent_name, model=model, trace_id=trace_id,
                                 parent_observation_id=parent_observation_id)
    iterator, completed = None, False
    try:
        iterator = provider()
        async for item in iterator:
            yield item
    except Exception:
        handle.finish("error")
        raise
    else:
        completed = True
        handle.finish("success")
    finally:
        handle.finish("unknown")
        if iterator is not None and not completed:
            # async-for does not forward generator close as yield-from does.
            # Cleanup must not replace the original provider/cancellation error.
            try:
                closer = getattr(iterator, "aclose", None)
                if closer is not None:
                    await closer()
            except BaseException:
                pass


def exercise(exporter):
    """Only local synthetic values. Nothing inspects or exports these objects."""
    result = object()
    assert run_call(exporter, lambda: result, agent_name="example-call", model="synthetic/model") is result
    list(stream_call(exporter, lambda: iter([object(), object()]), agent_name="example-stream", model="synthetic/model"))
    stream = stream_call(exporter, lambda: iter([object(), object()]), agent_name="example-early", model="synthetic/model")
    next(stream)
    stream.close()
    failure = RuntimeError("synthetic local provider failure")

    def failing():
        raise failure

    try:
        run_call(exporter, failing, agent_name="example-error", model="synthetic/model")
    except RuntimeError as error:
        assert error is failure


async def async_exercise(exporter):
    result = object()

    async def normal():
        return result

    async def stream():
        yield object()
        yield object()

    assert await async_run_call(exporter, normal, agent_name="example-async-call", model="synthetic/model") is result
    async for _ in async_stream_call(exporter, stream, agent_name="example-async-stream", model="synthetic/model"):
        pass
    early = async_stream_call(exporter, stream, agent_name="example-async-early", model="synthetic/model")
    await anext(early)
    await early.aclose()
    failure = RuntimeError("synthetic local async provider failure")

    async def failing():
        raise failure

    try:
        await async_run_call(exporter, failing, agent_name="example-async-error", model="synthetic/model")
    except RuntimeError as error:
        assert error is failure


def main(argv=None):
    parser = argparse.ArgumentParser(description="Exercise local synthetic lifecycle helpers; optional explicit test-only export.")
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
