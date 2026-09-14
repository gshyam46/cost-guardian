# Sillage: OpenTelemetry and OpenInference integration

Recorded on 2026-09-13 before implementation, following the founder's decision to reuse existing open-source instrumentation and preserve agent/workflow context.

## Decision and scope

Use maintained OpenInference instrumentors to observe supported Python SDK/framework operations. Add an in-process `SillageSpanProcessor` that projects ended, explicitly recognised LLM spans into the existing numeric direct-capture exporter. Preserve OpenTelemetry trace, span and parent IDs; reuse supplied technical agent context. An existing OTel application can attach this processor to its own provider, while the launcher can initialise supported instrumentors before loading the original application.

The first implementation is a Python runtime bridge, not a new general OTLP HTTP/gRPC receiver or a second trace database. Existing direct capture and Langfuse reads remain compatible. A deployment still binds one source mode to its database. Langfuse already accepts OTel/OpenInference exports, so teams using it can keep that source path; other backends need an explicit supported export/adapter rather than an invented universal connection.

## Customer behavior

1. Existing Langfuse telemetry: configure the Sillage Langfuse source for that project; do not also instrument the same calls into the same dataset.
2. No existing telemetry: install the Sillage wheel with the tested OpenInference extra in the application's environment, configure the Sillage URL/app key, check the actual SDK/framework compatibility, then start the original script/module through `sillage-run` with OpenInference selected.
3. Existing OpenTelemetry instrumentation: attach the Sillage processor once to the application's existing `TracerProvider`. Preserve its sampler, processors and exporters. Do not replace the global provider or instrument the same library twice.
4. Run a real application action and verify received/processed calls. A local configuration check is not delivery proof. Framework context can identify an agent and group a workflow when the framework supplies it; arbitrary application semantics cannot be inferred from a URL or model name.

Keep the current native Python adapter as an explicit compatibility option. Publish exact tested SDK/instrumentor versions in the install guide; do not silently downgrade application dependencies to satisfy an adapter. The launcher remains single process until separate propagation support is verified.

## Span-to-call contract

Only ended LLM/generation spans with recognised OpenInference or GenAI semantics become call events. HTTP/database/AGENT/CHAIN/TOOL/RETRIEVER/EMBEDDING spans must not inflate LLM-call counts or costs. Non-LLM spans may supply bounded, process-local context; they are not persisted as fake generations.

| OTel evidence | Existing event version 1 field |
| --- | --- |
| Valid nonzero 128-bit trace ID | `trace_id`, canonical 32-character lowercase hex |
| Valid nonzero 64-bit span ID | `observation_id`, canonical 16-character lowercase hex |
| Actual valid parent span ID | `parent_observation_id`; omitted for a root |
| Explicit technical agent attribute or recognised agent context | `agent_name`; configured service-name fallback when unavailable |
| Recognised model attribute | `model`; safe unknown fallback |
| Actual start/end nanoseconds | UTC timestamps, deterministic millisecond precision |
| Strict numeric token attributes | Existing nullable input/output/total token fields |
| Reported span status and supported terminal evidence | Existing success/error/unknown outcome; unset never proves success |
| No independently verified price provenance | `cost_usd: null` |

Use `BackgroundExporter.emit(event)`, not `start_call()`: the latter creates new identifiers/times. Freeze the event when the source span ends. Duplicate delivery retains identical IDs/body; changed evidence follows the existing immutable-conflict behavior. No fingerprint, ledger or event schema migration is needed for this mapping.

Read only explicit supported scalar attribute names. Do not serialize arbitrary span attributes, events, resource metadata, input/output, exception descriptions, baggage or provider headers. Conflicting/invalid token aliases must not become trusted totals. Preserve valid zero and unknown measurements. Status describes the observed operation, not answer quality or overall workflow success; known incomplete/interrupted evidence cannot become success solely because a transport span reports OK.

Agent attribution uses explicit context when supplied and otherwise remains a service label. Bound any active-parent/context map by count, lifetime and scalar size. Do not retain original span objects or payloads for later enrichment. Missing/evicted/remote parent context falls back honestly. Parent IDs may reference uncollected framework spans: show the real reference and explain its absence from captured calls instead of fabricating a tree.

## Runtime, privacy and ownership

The launcher selects one capture mechanism. OpenInference owns SDK wrapping in the standards path; Sillage owns projection and export. Do not run Sillage's native SDK wrappers on the same operation. Avoid nested SDK duplicates by selecting one provider layer and verifying the framework/provider combination, with an explicit diagnostic for unsupported overlap.

Use explicit OpenInference privacy configuration to hide inputs, outputs, prompts, tools, invocation parameters and embedding content. Do not inherit content/blob-upload defaults. The numeric projection is an independent second boundary; externally owned OTel exporters retain the application's own privacy policy and are not silently reconfigured.

An owned launcher provider must not replace a pre-existing global provider. Pass it explicitly to the instrumentors. An existing-provider integration must preserve other processors/exporters, sampling and context. Shut down only resources owned by Sillage; application failures/results/stream behavior must remain intact. Rejected/unsupported spans and delivery failures need bounded, redacted diagnostics. Bounded asynchronous export stays outside the customer response path; forced process exit can lose queued events.

## Phases and acceptance

1. **Contract and upstream compatibility:** verify maintained instrumentor APIs, dependency ranges and privacy settings in an isolated environment; record actual supported versions.
2. **Runtime bridge:** implement strict projection, context/parent preservation, failure isolation, existing-provider API and launcher selection; retain native compatibility.
3. **Product integration:** ship a new versioned wheel/extras; update authenticated downloads, onboarding commands, source explanations and real parent references in run views.
4. **Independent verification:** install outside the checkout; exercise real OTel providers and installed instrumentors using synthetic provider transport; verify agent/workflow grouping, preserved IDs, no non-LLM accounting, no duplicate nested capture, unknown measurements, replay/conflict semantics, privacy canaries, cancellation and bounded shutdown through the actual collector/worker/browser.
5. **Review and delivery:** update docs with exact artifact/evidence, refresh the isolated preview if the new path is verified, then commit and push the authorised work including the landing page to `mvp2.0`.

Full non-LLM span storage, OTLP receiver/protocol admission, cross-process propagation, arbitrary SDK compatibility, live provider/customer activation and self-service backend provisioning remain separate gates. Do not describe a local synthetic provider test as a real model run.

## Implemented behavior and compatibility

Version **0.2.0** implements this contract. Connections recommends the OpenInference extra and explicit standards-mode launcher flags; an existing bare `sillage-run` command continues to select the native compatibility adapter. Auto selection chooses one installed compatible layer in the order LangChain, LiteLLM, OpenAI. Select the layer your application actually uses: finding an installed distribution does not prove that a workflow calls it.

| OpenInference instrumentor | Verified application SDK |
| --- | --- |
| OpenAI 0.1.58 | OpenAI 1.99.9 and 2.54.0 |
| LiteLLM 0.1.34 | LiteLLM 1.80.0 |
| LangChain 0.1.74 | LangChain Core 1.2.5 |

Shared versions: OpenTelemetry SDK/API 1.37.0, instrumentation 0.58b0, OpenInference instrumentation 0.1.60 and semantic conventions 0.1.37. The launcher checks exact verified versions and refuses an unsupported stack. The extra installs tracing dependencies; it does not declare application SDK upgrades. `--check` performs local metadata/configuration checks without imports, network calls or receipt claims.

The private provider uses `ParentBased(ALWAYS_ON)` and is passed directly to the selected instrumentor. It leaves the global provider unchanged and respects an existing unsampled parent. The processor remembers at most 2,048 scalar context entries for 300 seconds. Labels available only after a child ends cannot enrich an already immutable event. Missing context falls back to the configured service name.

For the original Founder's existing LiteLLM metadata, a small context shim reads only technical `generation_name` and `trace_id` values. With no actual OTel parent, the root ID generator uses the first 16 bytes of `SHA256("sillage:litellm:run:v1\0" + service_name + "\0" + legacy_run_id)` as the real OTel trace ID. Existing OTel parents take precedence. It creates no synthetic parent span and does not parse provider responses. This groups existing Founder attempts without modifying application source; it cannot invent agent names in an arbitrary unlabelled app.

The installed-provider acceptance records missing capture separately from unknown measurements. In the verified OpenAI 1.99.9 matrix, some early-closed streams and cancellation produced no upstream ended span. Responses operations and normal LiteLLM returns lacked terminal attributes, so their captured outcomes remain unknown. A provider-reported failure embedded only in hidden response content can also remain unknown. Completed Chat Completions and thrown provider errors have distinct evidence where supplied. These limits make the standards path unsuitable for claiming complete cancellation/error coverage. The native compatibility path retains its separately tested terminal handling.

See [VALIDATION.md](VALIDATION.md) for final artifact hashes, repeatable checks and current evidence. Full span storage and a general OTLP receiver remain unimplemented.

## Primary sources

- [OpenInference LiteLLM instrumentation](https://arize-ai.github.io/openinference/python/instrumentation/openinference-instrumentation-litellm/).
- [OpenInference privacy configuration](https://arize-ai.github.io/openinference/spec/configuration.html).
- [OpenTelemetry Python SpanProcessor and TracerProvider](https://opentelemetry-python.readthedocs.io/en/latest/sdk/trace.html).
- [Langfuse OpenTelemetry integration](https://langfuse.com/integrations/native/opentelemetry).
- [OpenLLMetry](https://docs.traceloop.com/docs/openllmetry/introduction) is an alternative instrumentor family to evaluate after the initial OpenInference matrix; do not install overlapping families indiscriminately.
