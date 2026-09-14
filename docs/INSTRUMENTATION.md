# Sillage installation and automatic instrumentation

## Current standards path and native compatibility

ADR-51 supersedes the preferred implementation direction below with [OPENTELEMETRY.md](OPENTELEMETRY.md). The 0.2.0 wheel supports maintained OpenInference instrumentors plus `SillageSpanProcessor`. Connections defaults to this standards path and prints explicit `--instrumentation openinference --instrumentors <one-layer>` commands. The CLI's bare invocation retains the original native adapter; use `--instrumentation native` to select it explicitly. Neither mode should wrap the same call alongside the manual helper or another overlapping instrumentor.

The standards bridge preserves actual OTel trace/span/parent IDs, operation times and supported scalar usage. It maps selected technical agent attributes/context and recognised available AGENT ancestry. For existing LiteLLM metadata, the launcher's root ID generator creates a real OTel trace ID from the service name and legacy run ID using the documented SHA256 mapping; an existing parent takes precedence. Projection never rewrites those IDs. Missing ancestry remains a service label or an uncollected parent reference. An existing provider retains its sampling and other processors/exporters. Native compatibility retains its earlier ID/metadata semantics described below.

Install the local `sillage_observe-0.2.0-py3-none-any.whl[openinference]` artifact plus pinned upstream dependencies, or `[otel]` for an existing-provider attachment. No PyPI publication of Sillage is implied. The exact supported stacks and commands are maintained in the [package guide](../packages/sillage-python/README.md) and [onboarding guide](ONBOARDING.md). Current installed-wheel verification is recorded in [VALIDATION.md](VALIDATION.md); the following ADR-50 contract and earlier native acceptance are historical compatibility evidence.

The standards path depends on the upstream instrumentor ending a span. In current acceptance, four early-closed streams and one cancelled operation produced no captured event. This differs from captured OpenAI Responses/LiteLLM returns whose terminal evidence was insufficient and whose status therefore remains unknown. The bridge does not invent a completion, inspect hidden response content or rewrite a transport-OK span into a proven model success. Keep those limitations visible when selecting standards versus a compatible verified native/manual path; full stream/cancellation accounting remains unfinished.

## Original native contract, ADR-50

Recorded 2026-09-13 before implementation, following the founder's request to replace copied helper files and per-call edits with an installable dependency and `sillage-run`.

## What is connected today

The current Sillage preview is an isolated **direct-capture** deployment. Its collector accepts numeric terminal-call events; its worker produces the calls, accounting and incidents shown in the dashboard. It does not consume Langfuse in this mode. The public demo is separate browser-only sample data.

Founder Path currently calls `litellm.acompletion` through `services/llm_fallback.py`. Each agent already supplies a generation name and shared run ID. Its optional LiteLLM Langfuse success/failure callbacks send to Langfuse only when credentials are configured. There is no Sillage helper import in that application. Starting the two applications does not connect them, and a running server or configured library is not proof of received telemetry.

Implemented local continuation: the original Founder backend now runs through the installed `sillage_observe` launcher with a scoped key issued through normal preview-owner OIDC. Its UI/API are on ports 3002/8002; Sillage remains on 8001. No original application source was changed. SDK compatibility is verified and instrumentation is configured, but no real Founder provider request was made. Real analysis still needs the existing app sign-in and provider configuration. The separate synthetic installed-SDK pipeline and current runtime evidence are recorded in [VALIDATION.md](VALIDATION.md).

## Decision: package the client and instrument supported libraries at startup

The existing three Python files are library internals. The explicit call wrapper is an instrumentation hook. Users should not need to copy internals into every application or edit every supported SDK call. Ship an installable Python wheel that owns the transport, bounded background exporter and numeric extraction, then enable compatible runtime instrumentation before the original application imports its SDKs.

The customer journey becomes: **install one wheel → set the collector address and app key → start the original Python app with `sillage-run` → verify a real call in Connections**. The key identifies the destination workspace and authorizes writes; it is not a model-provider key. Installation and local checks are separate from successful export and processing. Keep the existing explicit Python/Node recipes as an advanced fallback and do not silently claim automatic support for other runtimes.

Use the distribution/import name `sillage-observe` / `sillage_observe` to avoid shadowing the existing unrelated `sillage` Python package. The product and executable remain Sillage and `sillage-run`. This is a locally built/downloadable wheel; **no `pip install sillage-observe` registry claim or automatic publication** is made. Use standard Python packaging, a console entry point and a reproducible artifact with recorded hashes. The installed package must work outside this repository and must not import the collector's backend or database.

## Initial supported contract

- `sillage-run -- python app.py` and `sillage-run -- python -m uvicorn server:app --host ... --port ...` run the target in the same selected Python interpreter. Preserve target arguments, working directory, results, exceptions and exit status. Do not launch shell strings or change provider request arguments.
- `sillage-run --check` reports local configuration and detected adapter versions without reading an application's `.env`, sending telemetry or making provider calls. It must not print the ingestion token or claim that an app is connected. Valid configuration is separate from `instrumentation_ready`; no compatible installed SDK returns exit 3 and false readiness. Inspect the adapter used by the application, since another supported dependency alone does not cover it.
- Configuration uses `SILLAGE_URL`, `SILLAGE_INGEST_KEY`, optional `SILLAGE_SERVICE_NAME`, and explicit `SILLAGE_ALLOW_LOCAL=true` for the supported loopback preview. Keep prior `GUARDIAN_*` transport settings compatible through a documented mapping; reject conflicting configuration rather than choosing credentials silently.
- Install hooks before importing the original target. Founder Path uses `from litellm import acompletion`, so patching after application import misses that bound name. Avoid modifying customer files or installing a global `sitecustomize` hook.
- Instrument LiteLLM `completion`/`acompletion` for the actual Founder Path stack, and the verified synchronous/asynchronous OpenAI create/parse surfaces. Retain existing technical `generation_name` and `trace_id` metadata where valid. Ignore user IDs, tags, prompts, messages, headers, tool arguments and raw error text. Record actual SDK/version compatibility with tests; unsupported APIs must not masquerade as covered.
- One model call has one capture owner. Suppress nested OpenAI observations while LiteLLM owns the logical call, including context propagated through async work, so an internal provider implementation does not inflate counts. App-level fallback calls remain distinct attempts.
- Preserve original response objects and streamed chunks. OpenAI streaming instrumentation must preserve the original stream/context-manager interface, snapshot only numeric/lifecycle fields, finish once on exhaustion/error/close, and keep interrupted usage/outcome unknown. Initial LiteLLM streaming, arbitrary reloader/subprocess/multiworker execution and automatic Node instrumentation remain separate work unless explicitly implemented and verified.
- Reuse existing event version 1, strict numeric extraction and bounded exporter semantics. USD cost stays unknown without independently supplied cost. No price inference, ingestion fingerprint migration, prompt capture or automatic workflow-success assertion is introduced.
- The launcher owns exporter startup and bounded shutdown. Configuration errors fail clearly before starting the target; runtime instrumentation/export failures must not break the application's provider operation. In-process delivery is not durable across process crash. Existing fork and capacity safeguards remain effective.

## Why OpenTelemetry is relevant

OpenTelemetry Python's zero-code launcher installs supported instrumentation before the application starts. Instrumentation commonly wraps library functions at runtime; it still requires a dependency, destination configuration and a compatible adapter. OTel supplies context/structure/export; AI adapters understand model/usage/framework events. [Official Python zero-code guide](https://opentelemetry.io/docs/zero-code/python/).

Current Langfuse uses OTel SDK/integration paths and can accept OTLP HTTP. Framework callbacks expose framework events; provider wrappers expose model calls; optional application annotations supply business meaning. An endpoint alone cannot discover an application's internal activity. [Langfuse OpenTelemetry](https://langfuse.com/integrations/native/opentelemetry), [LiteLLM integration](https://langfuse.com/integrations/frameworks/litellm-sdk), [OpenInference LiteLLM adapter](https://arize-ai.github.io/openinference/python/instrumentation/openinference-instrumentation-litellm/).

Going down to generic HTTP or the operating system mainly reveals network requests, timings and failures. It does not reliably recover tokens, retrieval meaning or business workflow from encrypted traffic. A model gateway sees routed provider calls but requires routing changes and misses local tools/retrieval. Supported SDK/framework instrumentation is the useful default layer; richer custom workflow attribution still needs optional context.

The original native package exports through the existing Sillage JSON collector, **not OTLP**. ADR-51 now implements the in-process standards projection described above while retaining the same numeric event contract. General OTLP reception and persistence of framework/tool/retrieval spans still need their own schema and privacy controls. Upstream content-capture defaults must not silently become Sillage storage defaults.

## Implementation and verification sequence

1. Build the independent Python package/CLI, preserving existing helper behavior and backward-compatible manual downloads.
2. Test installation into an isolated environment outside the source tree, command help/check/argument/exit semantics, imported aliases, supported real SDKs against local provider-shaped responses, success/failure/stream cancellation, privacy canaries, duplicate suppression and exporter failure isolation.
3. Supply the wheel through an authenticated download and make install/configure/run the first Python onboarding option, with accurate compatibility and receipt/processing states. Update the deployment image's explicit artifact inputs.
4. Verify the installed launcher against an owned local collector/worker and the original Founder Path call service using synthetic provider transport. Do not describe fixture responses as real model work or add them invisibly to the user's production metrics. Keep the running original Founder UI separate from test fixtures.
5. Record artifact/version/test evidence and refresh Sillage's preview. Keep source mode, actual receipt and processed observations independently visible. Preserve the user's existing database and unrelated running applications.

## Remaining product work

Live exporter failure/capacity diagnostics, registry publication/signing, tested Node installation and automatic loading, additional providers/frameworks, subprocess/reloader propagation, OTLP ingestion, full RAG/workflow schema and content/privacy controls remain tracked follow-ups. Founder Path still requires its actual sign-in/provider configuration to perform a real end-user analysis. Its legacy Langfuse Python 2.53.9 callback path also needs a separately tested upgrade: current Langfuse compatibility documentation schedules legacy Cloud ingestion/read removal for **2026-11-16**. The newer Sillage read adapter does not upgrade the monitored application's legacy exporter. [Compatibility guidance](https://langfuse.com/docs/compatibility).
