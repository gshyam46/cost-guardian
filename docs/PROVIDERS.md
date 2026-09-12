# OpenAI usage integration: R2-02 provider adapter contract

Recorded before implementation on 2026-09-12. This slice lets a Python or Node application export actual OpenAI call usage to Guardian without Langfuse, manually constructing events or extracting counters. It uses the existing process-scoped background exporter and Guardian JSON version 1. No ingestion, fingerprint, pricing or detector schema migration is part of this slice.

## Supported customer path

1. Configure an isolated direct-capture Guardian deployment and create an ingestion key in Setup.
2. Copy the matching `guardian_capture`, `guardian_exporter` and `guardian_openai` source modules into the server application. These are repository modules, not published packages. Keep using the application's own OpenAI SDK client and model configuration.
3. Create one background exporter per process. Wrap the existing SDK operation with the OpenAI helper. The operation owns prompts, model parameters, authentication and provider retries; the helper never changes those arguments or creates a provider client.
4. The helper returns the original result, forwards each original stream object and rethrows the original exception. It emits only technical caller-supplied identity, timestamps, status and validated token totals through the existing bounded queue.
5. Inspect **Live activity -> Call feed** for captured token totals and **Recent traces -> Tokens (in / out)** for call detail. Check processing status separately. Configure duration/error rules and a notification destination to reach an actionable incident. Test-only recipes remain separate from production metrics and incidents.

The supported API surfaces are Responses `create` and Chat Completions `create`, including `stream=True`/`stream:true`. Python supports synchronous and asynchronous clients; Node supports awaited calls and asynchronous streams. Chat usage integration initially supports a single choice (`n=1`). SDK stream context managers/event-emitter helpers, background Responses polling, realtime sessions, Batch API, automatic retry-attempt accounting, other providers and complete RAG/workflow outcomes remain separate integrations. A returned queued/in-progress response is unknown completion, never successful model completion.

## Public helper contract

Python `guardian_openai.py`:

```python
openai_call(exporter, operation, *, api="responses", agent_name, model,
            trace_id=None, parent_observation_id=None)
async_openai_call(exporter, operation, *, api="responses", agent_name, model,
                  trace_id=None, parent_observation_id=None)
openai_stream(exporter, operation, *, api="responses", agent_name, model,
              trace_id=None, parent_observation_id=None)
async_openai_stream(exporter, operation, *, api="responses", agent_name, model,
                    trace_id=None, parent_observation_id=None)
extract_openai_usage(response, api="responses")
```

Node `guardian_openai.mjs`:

```javascript
openaiCall(exporter, metadata, operation, { api = 'responses', signal } = {})
openaiStream(exporter, metadata, operation, { api = 'responses', signal } = {})
extractOpenAIUsage(response, api = 'responses')
```

`api` is `responses` or `chat_completions`. `metadata` uses existing `agent_name`, `model`, optional trace/parent IDs. The caller supplies a safe technical model label; provider model strings and request IDs are not copied into event metadata. Python async operations may return an awaitable stream. Node operations may return a Promise of the SDK stream. Generator construction is inert: a never-consumed stream creates no call/event. Runtime instrumentation failures must not suppress the operation, change results/errors, or stop stream iteration. No automatic provider retries, logging, SDK monkey-patching, prompt inspection or whole-object serialization occur.

The pure usage functions return a fresh mapping with `input_tokens`, `output_tokens` and `total_tokens`, each an integer or null. They read only known scalar fields from plain dictionaries/objects or stored Python SDK model fields; getters, custom serialization hooks, content, output, messages, tool arguments and error bodies are not inspected. Missing/null counters remain unknown. Present invalid counters (boolean, string, fractional number, negative, above 2^53-1), inconsistent totals, impossible subset/total relationships or unsafe container access make that usage snapshot entirely unknown. Python requires actual integers; JavaScript validates safe integer Numbers, whose parsed representation cannot distinguish `1` from `1.0`. When valid input and output counters exist without a supplied total, their checked sum supplies total. A valid total-only snapshot remains total-only.

Responses maps `usage.input_tokens`, `output_tokens`, `total_tokens`; Chat maps `usage.prompt_tokens`, `completion_tokens`, `total_tokens`. Known cached/reasoning details are validated as subsets when present and are never added again to the parent totals. Unsupported detail fields are ignored, not serialized. This slice does not persist per-category cache, reasoning, audio or tool billing.

Validation applies to the values exposed by the application's SDK, not its raw HTTP response. Python reads requested keys from both builtin model dictionary and Pydantic extra storage so a newer usage field cannot escape validation solely because the installed SDK predates it. The tested SDK/runtime versions and actual async versus localhost pipeline coverage are recorded in [VALIDATION.md](VALIDATION.md).

## Completion and streaming

Responses `status=completed` means successful model-call completion; `failed` means error; incomplete, cancelled, queued/in-progress, missing or unrecognized status means unknown. Only terminal completed/failed/incomplete responses can supply final usage; queued/in-progress/cancelled statuses leave usage unknown. A successful model call does not establish workflow or answer quality.

For Chat Completions, one choice finishing with `stop`, `tool_calls` or legacy `function_call` is completed successfully. `length`, `content_filter`, missing/unrecognized finish reason, empty/multiple choices or malformed choice metadata are unknown. Completion usage can still be known for a terminal length/content-filter result. The helper never reads message/delta content or refusal text.

Streaming retains a bounded scalar state, never a growing list of chunks. Snapshot supported numeric fields before yielding a terminal chunk so caller mutation cannot alter telemetry. Responses reads usage from a terminal `response.completed`, `response.failed` or `response.incomplete` event's `response`. Generic `error` signals error without retaining its message. Chat records the single choice's finish reason and the final usage-only chunk (`choices=[]`); the application must request `stream_options={"include_usage": true}` to receive usage. Do not add repeated cumulative snapshots together. Missing final usage stays unknown, including interrupted streams.

Bind stream lifecycle/usage to one bounded provider response ID and reject conflicting IDs, terminal states or differing repeated usage snapshots as unknown. Identical repeated terminal/usage snapshots are idempotent. Ignore unrelated content event types. At most one terminal Guardian event is emitted after normal exhaustion, exception or explicit close. Stream exhaustion alone does not prove success: the corresponding terminal marker/finish reason is required. Early consumer exit or cancellation emits unknown status and unknown usage; exceptions emit error unless explicitly cancelled. Python generator callers must close on early exit (use `contextlib.closing`/`aclosing`); Node callers should pass the same AbortSignal used by their provider. Cleanup should close the owned SDK stream/iterator without masking the original provider/consumer error.

## Cost and compatibility decision

OpenAI token usage does not provide a billed USD amount. These adapters leave `cost_usd` unknown; they do not infer prices or billable retries from tokens. The existing explicit call handle remains available when an application independently knows a cost amount.

Declared pricing is deferred until a separate provenance contract carries the distinction between reported amounts and estimates through intake, immutable fingerprints, aggregates, incident evidence and UI labels. Adding a default field to existing canonical events would change historical receipt/ledger hashes; absent new metadata must preserve the old bytes. Current numeric costs must not silently gain an invented billing interpretation. This boundary keeps usage integration useful for duration/error monitoring without misrepresenting spend.

## Acceptance and documentation

Required proof: parity fixtures for both APIs and languages; zero/missing/inconsistent/overflow counters; cached/reasoning subset handling; terminal/duplicate/conflicting streaming metadata; result/chunk/error identity; cancellation/early close/cleanup; hostile getters/serialization canaries; exporter failure isolation; independent real SDK parsing where available; actual localhost provider-shaped responses through exporter, Guardian intake, worker, run usage and an error incident; replay and test/real separation. No actual provider key, paid model call, real prompt or customer traffic is needed for local verification.

Setup must present Python and Node provider recipes before the advanced raw JSON payload, explain copying the modules, keep secrets server-side and direct the customer to captured usage and processed work. No-argument example entrypoints print help offline; explicit synthetic tests emit only test-mode events. Record exact SDK/runtime versions and distinguish schema/wire fixtures from live provider compatibility in [VALIDATION.md](VALIDATION.md). The next product priority remains runnable deployment/onboarding, with pricing provenance, further providers and workflow outcomes still explicit launch work.

Official references: [Responses create and usage](https://developers.openai.com/api/reference/python/resources/responses/methods/create), [Chat Completions create](https://developers.openai.com/api/reference/python/resources/chat/subresources/completions/methods/create), and [stream lifecycle](https://developers.openai.com/api/docs/guides/streaming-responses). Local integration must follow the observed API fields rather than assume every OpenAI-compatible endpoint has identical semantics.
