# Native capture for Python and Node

**Python default:** [install `sillage-observe` and start your existing app with `sillage-run`](../../packages/sillage-python/README.md). The downloadable wheel bundles the transport and version-checked SDK instrumentation; supported calls need no copied files or per-call wrapper. The manual Python/Node integrations below remain available for explicit instrumentation and unsupported startup environments. [Architecture and limits](../../docs/INSTRUMENTATION.md).

Use these files with a configured direct-mode Guardian project and an owner-issued ingestion key. No Langfuse account is required. Local synthetic commands need no provider key; a real integration keeps using the application's own authenticated provider client. The background exporters support long-running application processes; manual senders remain available for applications that already own a telemetry queue. See [PROVIDERS.md](../../docs/PROVIDERS.md) for OpenAI usage, [EXPORTING.md](../../docs/EXPORTING.md) for exporter lifecycle and [CAPTURE.md](../../docs/CAPTURE.md) for the accepted event schema.

## Connect an existing OpenAI application

Copy the three matching source modules into your server application and keep them together:

| Language | Files |
| --- | --- |
| Python | [guardian_capture.py](guardian_capture.py), [guardian_exporter.py](guardian_exporter.py), [guardian_openai.py](guardian_openai.py) |
| Node | [guardian_capture.mjs](guardian_capture.mjs), [guardian_exporter.mjs](guardian_exporter.mjs), [guardian_openai.mjs](guardian_openai.mjs) |

These are repository modules, not published pip/npm packages. Keep the application's existing OpenAI SDK, client, credentials and request arguments. The adapters do not construct a client or change request arguments; your zero-argument operation calls the SDK. They return the original result, forward original stream objects and rethrow the original exception. Only validated usage counters, technical caller-supplied labels, timestamps and status enter Guardian; prompts, outputs, tool arguments, provider IDs and raw errors are not copied. Supported SDK/runtime evidence is recorded in [VALIDATION.md](../../docs/VALIDATION.md).

Set `GUARDIAN_URL` to the HTTPS Guardian origin, `GUARDIAN_INGEST_KEY` to an owner-issued write-only key, and `OPENAI_MODEL` to your application's model setting. Keep these in server-side configuration; no module loads an application `.env` automatically. Use one exporter per process, created at startup and reused across requests. For an explicitly local HTTP development deployment only, add `allow_local=True` to the Python constructor or `allowLocal: true` in Node. Configuration errors are explicit at startup. These exporters require a long-running server process; browser/serverless execution and durable delivery across process crashes are not established by these examples.

### Python: Responses, synchronous and asynchronous

This template uses your existing synchronous `client` and `request_args` dictionary. Adapt it at the existing call site; the dictionary still owns the application's input and other provider parameters. The recipe makes its model and nonstreaming choice explicit:

```python
import os
from guardian_exporter import BackgroundExporter
from guardian_openai import openai_call

# Once at application startup.
exporter = BackgroundExporter(
    origin=os.environ["GUARDIAN_URL"],
    token=os.environ["GUARDIAN_INGEST_KEY"],
    test_mode=False,
)
model = os.environ["OPENAI_MODEL"]

# At the existing request handler; reuse client and request_args.
observed_args = {**request_args, "model": model, "stream": False}
result = openai_call(
    exporter,
    lambda: client.responses.create(**observed_args),
    api="responses", agent_name="answer-generator", model=model,
)
# result is the original SDK result; consume it as before.
```

For an asynchronous client, reuse the same process exporter and call the async helper inside your existing async function:

```python
from guardian_openai import async_openai_call

result = await async_openai_call(
    exporter,
    lambda: async_client.responses.create(**observed_args),
    api="responses", agent_name="answer-generator", model=model,
)
```

For synchronous streaming, close the wrapper on early exit. Replace `consume_chunk` with your existing consumer; the helper does not buffer chunks:

```python
from contextlib import closing
from guardian_openai import openai_stream

stream_args = {**request_args, "model": model, "stream": True}
with closing(openai_stream(
    exporter,
    lambda: client.responses.create(**stream_args),
    api="responses", agent_name="answer-generator", model=model,
)) as events:
    for chunk in events:
        consume_chunk(chunk)
```

Use `aclosing` for asynchronous streaming, including when the SDK operation returns an awaitable stream:

```python
from contextlib import aclosing
from guardian_openai import async_openai_stream

async with aclosing(async_openai_stream(
    exporter,
    lambda: async_client.responses.create(**stream_args),
    api="responses", agent_name="answer-generator", model=model,
)) as events:
    async for chunk in events:
        await consume_chunk_async(chunk)
```

At controlled application shutdown, use `exporter.close(timeout=5)`. For async shutdown, use `await asyncio.to_thread(exporter.close, timeout=5)` after importing `asyncio`, so the exporter's synchronous wait does not block the event loop. Do not flush or close after every model call.

### Node: Responses, awaited calls and streaming

This template uses your existing `client`, `requestArgs` and `requestOptions` objects. Use an empty options object if your application has none. Keep the same AbortSignal on the provider request and helper so cancellation remains distinguishable from a provider error:

```javascript
import { BackgroundExporter } from './guardian_exporter.mjs';
import { openaiCall } from './guardian_openai.mjs';

// Once at application startup.
const exporter = new BackgroundExporter({
  origin: process.env.GUARDIAN_URL,
  token: process.env.GUARDIAN_INGEST_KEY,
  testMode: false,
});
const model = process.env.OPENAI_MODEL;

// At the existing request handler; reuse client and requestArgs.
const requestOptions = {}; // Reuse your existing request options here, including signal if used.
const signal = requestOptions.signal;
const result = await openaiCall(
  exporter,
  { agent_name: 'answer-generator', model },
  () => client.responses.create(
    { ...requestArgs, model, stream: false },
    { ...requestOptions, signal },
  ),
  { api: 'responses', signal },
);
// result is the original SDK result; consume it as before.
```

For streaming, reuse the exporter, model and request options. A `break`, consumer error or cancellation closes the wrapper without claiming successful completion:

```javascript
import { openaiStream } from './guardian_openai.mjs';

for await (const chunk of openaiStream(
  exporter,
  { agent_name: 'answer-generator', model },
  () => client.responses.create(
    { ...requestArgs, model, stream: true },
    { ...requestOptions, signal },
  ),
  { api: 'responses', signal },
)) {
  await consumeChunk(chunk); // Your existing consumer receives the original chunk.
}
```

At controlled application shutdown, use `await exporter.close(5000)`. Reuse the exporter during normal traffic; do not flush/close inside every request. Both languages expose `snapshot()` for your application's diagnostics, including rejected, pending and unconfirmed events. A timed-out close may leave an already admitted request unconfirmed; Python also reports whether its transport remains active.

### Chat Completions and completion boundaries

For Chat Completions, call `client.chat.completions.create(...)` and pass `api="chat_completions"` in Python or `{ api: 'chat_completions', signal }` in Node. The helper supports one choice: explicitly set `n=1` / `n: 1`. For streaming, request the final usage-only chunk as well:

```python
chat_args = {**request_args, "model": model, "n": 1, "stream": True}
chat_args["stream_options"] = {
    **(request_args.get("stream_options") or {}), "include_usage": True
}
# Use client.chat.completions.create(**chat_args) inside openai_stream
# or async_openai_stream, with api="chat_completions".
```

```javascript
const chatArgs = {
  ...requestArgs, model, n: 1, stream: true,
  stream_options: { ...requestArgs.stream_options, include_usage: true },
};
// Use client.chat.completions.create(chatArgs, { ...requestOptions, signal })
// inside openaiStream, with { api: 'chat_completions', signal }.
```

The OpenAI helpers require the corresponding terminal response status or Chat finish reason; stream exhaustion alone is not success. Missing or invalid usage remains unknown. Early exit/cancellation leaves status and usage unknown, even when a terminal chunk was seen before the consumer exited. Python `closing`/`aclosing` and Node's shared AbortSignal preserve those boundaries. Queued/in-progress Responses, incomplete output, multi-choice Chat and SDK-internal retry attempts do not establish a complete customer workflow. Supported states and excluded surfaces are detailed in [PROVIDERS.md](../../docs/PROVIDERS.md).

**Token usage does not establish billed USD cost.** These adapters leave `cost_usd` unknown and never infer a price or zero amount. Cost alerts require an independently known cost supplied through the existing explicit call-handle API. Estimated pricing awaits a separate provenance contract; duration and reported-error monitoring can already use the captured metadata.

### Test the connection, then verify a real call

The standalone [python_openai_app.py](python_openai_app.py) and [node_openai_app.mjs](node_openai_app.mjs) use synthetic OpenAI-shaped objects. Run either without arguments to print help offline. With the Guardian environment values configured, explicitly send test-only events from the repository root:

```powershell
python examples/native-capture/python_openai_app.py --send-test
node examples/native-capture/node_openai_app.mjs --send-test
```

Add `--allow-local-http` only for an explicit loopback development deployment. These commands make no provider calls and need no provider key. They update the test receipt only, creating no production observations, metrics or incidents. They are connection checks, not proof of real OpenAI traffic or deployed SDK compatibility.

To verify the actual application integration:

1. Run one real application call through the helper using `test_mode=False` / `testMode: false`. Keep the exporter alive to submit its queued metadata; inspect `snapshot()` if it reports a rejection or unconfirmed delivery.
2. In Setup, check **Latest real event receipt**, accepted/pending/processed counts and worker diagnostics. A receipt confirms intake, not completed monitoring work. Resolve a stalled worker or processing backlog before claiming coverage.
3. Open **Live activity** (also linked as captured activity in Setup). Compare the matching **Call feed** row's total tokens with the provider's final usage. Under **Recent traces**, open the corresponding run and expand its call to inspect **Tokens (in / out)**. USD cost should remain **Unknown** for this integration. Use technical trace IDs to group intentional application attempts; never use customer identifiers.
4. In **Setup -> Monitoring rules**, configure useful duration limits and reported-error checks. Review a resulting incident's observed value, rule revision and linked run. In **Setup -> Notifications**, test and enable Slack as the owner; inspect delivery history separately from incident resolution. See [POLICIES.md](../../docs/POLICIES.md) and [NOTIFICATIONS.md](../../docs/NOTIFICATIONS.md).

An incident-free screen, a successful test receipt, or a completed model call does not establish end-to-end workflow quality or complete traffic coverage.

## Background exporter and generic lifecycle wrappers

Copy the matching pair into your server application: `guardian_exporter.py` plus `guardian_capture.py`, or `guardian_exporter.mjs` plus `guardian_capture.mjs`. Keep the two files together. Also copy `python_app.py` or `node_app.mjs` when using the lifecycle wrapper snippets below; these helper files are optional when using handles directly. These are repository source modules, not published pip/npm packages. Use the runtime versions actually recorded in [VALIDATION.md](../../docs/VALIDATION.md); other versions, browser use, worker teardown and serverless runtimes require separate validation.

Set `GUARDIAN_URL` to the HTTPS Guardian origin and keep `GUARDIAN_INGEST_KEY` in server-side secret configuration. Construct one instance during application startup. Constructor configuration errors are explicit; runtime event validation, queue overflow and transport failure do not replace provider results or exceptions. Importing a module does no network/configuration work. Neither exporter reads an application `.env` automatically.

Python startup and an ordinary synchronous call:

```python
from guardian_exporter import BackgroundExporter
from python_app import run_call

exporter = BackgroundExporter()  # Reads the two environment values at construction.

# Your existing callable retains its provider credentials and request content.
result = run_call(exporter, existing_provider_call,
                  agent_name="answer-generator", model="provider/model")

# During controlled application shutdown, outside request handling:
outcome = exporter.close(timeout=5)
```

For async Python, use `await async_run_call(...)`. For streaming use `stream_call(...)` or `async_stream_call(...)`; the provider factory must return the corresponding iterator. These generic wrappers treat natural exhaustion as success, provider exceptions as error, and early close/cancellation as unknown; use the OpenAI helpers above when provider terminal markers and token usage are required. Always close/aclose the wrapper when a consumer exits early. The generic wrappers do not buffer chunks, prefetch or read provider result/error content. Synchronous and asynchronous helpers are separate: choose the one matching your provider operation. Python flush/close waits synchronously; during async application shutdown use `await asyncio.to_thread(exporter.close, timeout=5)` to keep the event loop available.

Node startup and an awaited call:

```javascript
import { BackgroundExporter } from './guardian_exporter.mjs';
import { runCall } from './node_app.mjs';

const exporter = new BackgroundExporter({
  origin: process.env.GUARDIAN_URL,
  token: process.env.GUARDIAN_INGEST_KEY,
});

const result = await runCall(exporter,
  { agent_name: 'answer-generator', model: 'provider/model' },
  existingProviderCall);

// During controlled application shutdown, outside request handling:
const outcome = await exporter.close(5000);
```

Use `streamCall` with a sync/async iterable provider for Node streaming. Pass the provider's same AbortSignal as the fifth helper argument, `{ signal }`, when cancellation is possible. Cancellation is then recorded as unknown without inspecting error names/messages or changing the original thrown value. Breaking a `for await` loop closes the wrapper. No stream event is fabricated for an iterator that was never consumed.

The generic `python_app.py` / `node_app.mjs` helpers supply IDs/timestamps/status and leave prices/usage unknown. To supply actual measurements, create a handle with `start_call(...)` / `startCall({...})`, then call `finish("success", cost_usd="...", input_tokens=..., output_tokens=...)` or `finish({status:'success', cost_usd:'...', input_tokens:..., output_tokens:...})` after actual completion. Supply only observed integers and an exact known decimal USD string. The first finish seals the handle, including when queue admission fails; a final unknown finish cannot overwrite it. Application retries use new handles under the same supplied trace ID. SDK-internal retries remain opaque. These generic wrappers do not inspect SDK usage or establish a RAG workflow outcome.

`emit(event)` and handle completion validate/copy/admit locally, without waiting for HTTP. Defaults bound all pending work, including in-flight batches, to 1,000 events/4 MiB, with at most 100 events/256 KiB per batch. Queue-full admission rejects the newest event visibly. One sender retains the same batch ID/body across at most five attempts and a five-minute retry/start budget, respects Retry-After and never refreshes old event timestamps. An already running Python urllib/DNS operation can outlast that budget. An invalid/revoked credential stops that instance; recreate it with a replacement key after fixing configuration.

Inspect `snapshot()` through your application's operational metrics. `enqueued_events` reconciles with `confirmed_events + unconfirmed_events + pending_events`; `rejected_events` counts events never admitted. These are local submission counters, not unique calls or invoices. `flush` waits for the admission prefix present when it was called; later traffic cannot hold it open forever. A deadline leaves pending work in place. `close` stops admission and, on timeout, marks remaining work unconfirmed. An unconfirmed request may already have committed remotely. Python cannot forcibly cancel an in-progress urllib/DNS operation; `transport_active` discloses that limitation after close. Node aborts its request. Neither module survives process crashes with guaranteed delivery; a durable spool remains future work. Do not call flush/close after every model call.

No-argument synthetic examples print help without creating telemetry. With environment configuration, explicitly test lifecycle capture:

```powershell
python examples/native-capture/python_app.py --send-test
node examples/native-capture/node_app.mjs --send-test
```

Add `--allow-local-http` only for an explicit loopback development deployment. These examples run local synthetic providers and send test-only events; they make no paid model calls and create no production metrics or incidents. Real application activation still requires actual completed calls, worker processing and useful incident handling.

## Manual sender for an existing queue

To use captured calls for customer monitoring, open Guardian **Setup -> Monitoring rules** as the project owner and save per-call limits. Supply observed cost using call handles if you need cost alerts; the generic wrapper does not infer prices. After the worker checks a call, its incident shows the observed value, threshold and evaluated revision, with an internal run link and resolution action. Test-only examples never trigger production incidents. See [POLICIES.md](../../docs/POLICIES.md).

The dependency-free manual sender examples send Guardian JSON version 1. The senders require no Langfuse account or provider key. They do not instrument an SDK, stream partial tokens, infer prices, provision a project or guarantee telemetry delivery. Use a configured direct-mode Guardian deployment and an owner-issued ingestion key from Setup. See the exact [capture contract](../../docs/CAPTURE.md).

Keep `GUARDIAN_URL` and `GUARDIAN_INGEST_KEY` in the application's server-side secret/environment configuration. `GUARDIAN_URL` is the HTTPS Guardian origin. Do not put secrets in command arguments, tracked files, browser code or event metadata. Both commands below are safe without arguments: they print help without network activity. With the environment configured, explicitly send a labelled test:

```powershell
python examples/native-capture/guardian_capture.py --send-test
node examples/native-capture/guardian_capture.mjs --send-test
```

For an explicitly local HTTP development deployment add `--allow-local-http`. Test traffic updates the test receipt only; it creates no production metrics, incidents or first-real-traffic claim.

For real integration, construct the envelope in CAPTURE.md from actual completed calls/attempts, set `test_mode:false`, and invoke Python `send_batch(batch)` or Node `sendBatch(batch)` from your application's existing background telemetry queue/job. The sender returns a fixed `{ok,code}` result (with optional numeric `retry_after_seconds`) instead of raising a provider/network exception into the application. It is synchronous in Python and awaited in Node; neither creates a background queue for you. Do not put this network wait in the model-serving critical path.

Assign stable observation/trace IDs when the call begins. Each retry attempt gets its own observation ID. Record aware start/end times, observed status and exact known token counts. Convert a supplied USD cost to a decimal string; absent pricing stays null. Never estimate missing cost as zero or put prompts, completions, documents, raw errors or customer IDs into labels. Populate every retry from the same saved batch body and UUID. The manual senders make at most three attempts, use five-second socket/abort timeouts, reject redirects, cap receipt bodies at 16 KiB and reuse the same bytes. Rate-limit responses and HTTP 500/502/503/504 with a valid Retry-After return a bounded retry delay to your queue instead of retrying immediately; both integer seconds and aware HTTP dates are supported, capped at one hour. Node aborts the request/body after five seconds; Python uses a five-second socket timeout and checks elapsed time between bounded body reads, so DNS and an in-progress read can extend total time. An exhausted or unconfirmed response needs your queue's durable retry/drop accounting; a new invocation must reuse the saved IDs/body. Long outages and observations older than 24 hours require explicit recovery rather than silent resubmission with a new timestamp.

Check `last_received_at`, pending/processed counts and the worker status in Setup. A 202 confirms receipt; derived metrics and incidents appear after worker processing. An incident-free dashboard does not prove healthy customer traffic. The current rules cover cost/reliability metadata; content-free events cannot establish PII or answer-quality checks. Locally tested versions/results are recorded in [VALIDATION.md](../../docs/VALIDATION.md); deployment and real application instrumentation remain separate acceptance gates.
