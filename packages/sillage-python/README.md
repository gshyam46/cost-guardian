# Sillage for Python

Install one local wheel and start the **original application** with `sillage-run`.
Supported SDK calls are observed at runtime; no copied helper files or per-call
source edits are required. This package has not been published to a registry.

```sh
python -m pip install './sillage_observe-0.2.0-py3-none-any.whl[openinference]'
export SILLAGE_URL=https://your-sillage.example
export SILLAGE_INGEST_KEY='<app key created in Connections>'
export SILLAGE_SERVICE_NAME=my-ai-app
sillage-run --instrumentation openinference --instrumentors openai --check
sillage-run --instrumentation openinference --instrumentors openai -- python app.py
# Or use the same activated Python environment's module entry point:
sillage-run --instrumentation openinference --instrumentors openai -- python -m uvicorn server:app --host 127.0.0.1 --port 8000
```

PowerShell environment assignments use `$env:SILLAGE_URL='...'` and
`$env:SILLAGE_INGEST_KEY='...'`. For a loopback HTTP preview, additionally set
`SILLAGE_ALLOW_LOCAL=true`. Remote collectors require HTTPS. Keys belong in the
environment or your normal secret manager, never command arguments or source
control. The token is an app ingestion key, not your model-provider key.

`python -m sillage_observe` provides the same CLI if the executable is not on PATH.
The selected environment must contain the application's existing SDK dependencies;
Sillage does not install or upgrade them. The base package requires Python 3.10+
and has no dependencies. The `[openinference]` extra installs pinned upstream
instrumentation from the configured package index; `[otel]` installs the OTel SDK
for an already instrumented app. Neither extra installs provider/framework SDKs,
the Sillage server, MongoDB, or an external observability backend.

## Choose one OpenInference layer

| `--instrumentors` | Tested application dependency | Pinned instrumentor |
| --- | --- | --- |
| `openai` | `openai==1.99.9` or `2.54.0` | OpenInference OpenAI 0.1.58 |
| `litellm` | `litellm==1.80.0` | OpenInference LiteLLM 0.1.34 |
| `langchain` | `langchain-core==1.2.5` | OpenInference LangChain 0.1.74 |

The tested shared stack is OpenTelemetry SDK/API 1.37.0, OpenTelemetry
instrumentation 0.58b0, OpenInference core 0.1.60 and semantic conventions 0.1.37.
Upstream declares wider SDK ranges; this launcher currently admits the verified
versions above. Other SDK versions remain untouched. For example, the newer
OpenInference OpenAI 0.1.60 requires OpenAI 2.8.0+, so blindly installing its latest
release would exclude the existing Founder app's OpenAI 1.x dependency.

Choose the layer your app actually uses. With `auto` (or no `--instrumentors`),
selection prefers a supported LangChain installation, then LiteLLM, then OpenAI;
the check prints the selected layer. Installed dependencies alone cannot identify
the app's actual architecture. Explicit selection avoids that ambiguity. Multiple
layers are rejected: observing both LiteLLM and its inner OpenAI client would count
one operation twice. The LangChain layer observes native framework callbacks;
a raw SDK call hidden inside a custom `RunnableLambda` is not automatically a
framework LLM callback and is not covered by that layer.

The launcher passes an owned provider directly to the selected instrumentor. It
does not replace a global provider or its exporters. Already active Sillage native
hooks or recognised upstream instrumentors are rejected; attach the processor to
the existing provider instead. A target that later independently reconfigures the
same instrumentor needs an explicit shared-provider integration. The launcher
owns one process, not reload workers, child processes, notebooks or distributed
context propagation.

Only ended, recognised LLM spans become call events. Their actual OTel trace/span/
parent IDs and strict token measurements are preserved. Non-LLM CHAIN/AGENT/TOOL/
RETRIEVER spans do not inflate generation counts and are not stored as a full trace
tree. A parent reference may therefore point to an uncollected framework span.
Known completion evidence controls success; missing evidence, partial streams and
interruptions remain unknown. Upstream-inferred dollar prices are discarded.

Agent names come from explicit technical span/context fields or available AGENT
parents; otherwise the configured service name is used. LangChain often sets its
span kind only at end, so a useful workflow tree does not guarantee an agent label
on each child. No agent is guessed from a model or arbitrary span name.

LiteLLM's existing `metadata.generation_name` becomes technical agent context.
An existing `metadata.trace_id` creates a real root OTel trace ID using the first
128 bits of SHA-256 over `sillage:litellm:run:v1`, service name and the validated
run ID, separated by NUL bytes. The same workflow/service therefore stays grouped
without changing app code. An existing valid OTel parent always takes precedence.
This does not invent parent spans or rewrite identifiers during export.

Privacy configuration explicitly suppresses inputs, outputs, prompts, invocation
parameters, advertised tools and embedding content, and disables blob uploading.
The numeric processor separately allowlists supported scalar fields; it never
exports arbitrary attributes, resource metadata, events or exception text. This
does not alter privacy settings of independently owned application exporters.

## An application that already uses OpenTelemetry

Install the wheel with `[otel]` and attach the processor once when that application
constructs its existing provider. Keep its instrumentors, sampler and exporters.

```python
from sillage_observe import Configuration
from sillage_observe.otel import SillageSpanProcessor

# provider is the application's already configured OTel SDK TracerProvider.
provider.add_span_processor(SillageSpanProcessor(Configuration.from_env()))
```

Sampling applies: dropped/non-recording spans cannot be recovered by the processor.
Do not also run native Sillage wrappers or a second OpenInference launcher around
the same calls. An app already exporting to Langfuse can keep that source path
instead of sending a second copy directly to Sillage.

## Native compatibility mode

Installing the wheel without extras and using `sillage-run --check` / `sillage-run
-- python app.py` retains the previous native implementation. Explicit
`--instrumentation native` is equivalent. It does not initialise OpenTelemetry.

The initial verified adapter versions are **OpenAI Python 1.99.9** and **LiteLLM
1.80.0**. Other installed versions are reported as unsupported and are left alone.
Compatibility is deliberately explicit; this package does not promise all future
SDK versions work without verification.

- OpenAI sync/async Responses and Chat Completions `create` and `parse`, including
  their normal `stream=True` objects and higher-level managers that call `create`.
  The original stream/response/chunk objects and context-manager APIs are retained.
- LiteLLM sync/async `completion`/`acompletion` without streaming, including existing
  `from litellm import acompletion` imports made after startup. Existing technical
  `metadata.generation_name` and `metadata.trace_id` are retained when valid.
- One process, Python script or `-m` module. Uvicorn reload and multiple-worker
  arguments and inherited `UVICORN_RELOAD`, `UVICORN_WORKERS` or
  `WEB_CONCURRENCY` settings that enable children are rejected. Arbitrary
  subprocesses, process managers, fork workers,
  notebooks, LiteLLM streams and OpenAI raw-response interfaces are **not covered**.
  Use the explicit helper fallback where an application needs unsupported behavior.
- Suppression of nested captures when LiteLLM owns a call. Each application-level
  fallback remains a separate attempt; internal SDK retries remain part of that
  SDK operation. Do not also wrap the same operation with manual Sillage helpers.

Hooks are installed before the target imports its SDK. They observe standard
installed wheel modules without installing a global `sitecustomize` or modifying
the app's source. The launcher preserves target arguments, working directory,
exceptions and exit status and uses the **same interpreter** that runs it.

## What gets sent

Only technical model/agent/trace IDs, call start/end, outcome and validated numeric
token usage. Raw prompts, generated content, documents, tool arguments, user IDs,
request headers, exception text and provider credentials are never exported.
Interrupted/missing usage remains unknown. USD cost is unknown; this package does
not infer provider prices. Standard calls use the configured service name, and
unannotated calls have separate generated trace IDs. SDK hooks cannot infer custom
business workflows, retrieval steps or overall workflow success.

The existing bounded exporter sends version-1 JSON events to Sillage's direct
collector in the background. It does **not** export OTLP. Slow/unavailable telemetry
must not change the provider operation's result or exception. Delivery is not
durable across crashes; shutdown waits at most three seconds. The launcher reports
capture failures and unconfirmed shutdown with fixed diagnostic codes. Exporter
capacity, retry and credential-rejection counters remain internal; this release
does not continuously report them to the console. Verify actual receipt and
processing in Connections. Continuous delivery diagnostics remain follow-up work. Inherited
forked instrumentation is deliberately inactive rather than sharing unsafe queues.

`--check` validates local configuration and reads installed package metadata.
`instrumentation_ready` is true when at least one verified adapter is installed;
also check that the SDK your application actually calls has `supported: true`.
In OpenInference mode, only the selected verified layer makes the check ready;
the JSON includes `instrumentors_selected` and each pinned dependency version.
Valid settings with no supported SDK/stack return exit code **3**, with
`no_supported_sdk_installed` or `no_supported_openinference_stack`. Invalid settings
or an ownership conflict return **2**. A successful local
check returns **0** and does not prove that a collector accepted the app key.
It does not read `.env` files, contact a model/collector, send a test event, or prove
connection. Next run a real application action, then verify receipt and processing
in Sillage Connections. Public browser demo data is unrelated to app ingestion.

The compatible legacy configuration aliases are `GUARDIAN_URL`,
`GUARDIAN_INGEST_KEY`, `GUARDIAN_SERVICE_NAME`, and `GUARDIAN_ALLOW_LOCAL`.
Providing different values for both old and new names fails before target startup.
Boolean values must be the literal `true` or `false`. The application's own normal
environment configuration still belongs to the application.

## Build and test locally

Use a separate build environment containing the versions pinned in
`pyproject.toml`; avoid installing build tools into the application environment.

```sh
python build_wheel.py --output dist
python -m unittest discover -s tests
```

The build uses standard setuptools/PEP 517, no package index lookup, a fixed source
epoch, and reports the wheel's SHA-256. Vendored numeric capture files must match
the repository's tested examples exactly except the exporter's relative import.
Do not edit one copy without the other and the parity check.
