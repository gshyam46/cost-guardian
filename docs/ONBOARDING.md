# Sillage: onboarding and integration design

## Standards-based Python connection, 0.2.0

The default Connections choice uses the installable wheel with the **OpenInference** extra. Choose the layer the application actually calls: OpenAI for direct OpenAI usage, LiteLLM for Founder Path, or the supported LangChain model integration. Select one layer; combining framework/provider instrumentors can double-count one provider request or produce unrelated traces. The native adapter remains an explicit compatibility choice, and bare `sillage-run` preserves its existing native default.

Download `sillage_observe-0.2.0-py3-none-any.whl`, activate the application's environment and install the local artifact. The extra installs pinned open-source dependencies from the configured package index; the package itself is not published on PyPI. Review compatibility without silently downgrading an application's existing dependencies. From the download folder:

```sh
python -m pip install './sillage_observe-0.2.0-py3-none-any.whl[openinference]'
```

Set `SILLAGE_URL`, `SILLAGE_INGEST_KEY` and an optional technical `SILLAGE_SERVICE_NAME` using the displayed server-side template. A loopback HTTP preview additionally requires `SILLAGE_ALLOW_LOCAL=true`. Then return to the application's usual working directory. For Founder Path's LiteLLM stack, check first:

```sh
sillage-run --instrumentation openinference --instrumentors litellm --check
```

Check that the selected SDK/instrumentor is supported before continuing. Valid configuration is separate from `instrumentation_ready`; a local check does not contact the collector or establish receipt. Preserve the application's normal arguments and port when launching, with one process and no reloader:

```sh
sillage-run --instrumentation openinference --instrumentors litellm -- python -m uvicorn server:app
```

Applications already instrumented with OpenTelemetry can install the `[otel]` extra and attach `SillageSpanProcessor` once to their existing provider. Keep the existing provider/sampler/exporters. Teams already sending to Langfuse can retain that source path instead of reinstrumenting the same calls. [Current package APIs and exact versions](../packages/sillage-python/README.md), [projection/ownership contract](OPENTELEMETRY.md).

Run a real application action and verify both receipt and processing. Real OTel IDs group calls; supplied agent context can name them. A model integration cannot automatically infer custom business workflows or every retrieval step. Missing parent spans are displayed as references, not fabricated nodes. Unknown usage/outcomes remain unknown, and the bridge does not infer prices. Full OTLP reception, full RAG span storage and self-service account provisioning remain separate work. Current final artifact/end-to-end verification is pending in [VALIDATION.md](VALIDATION.md); earlier native results do not certify this standards path.

**Choose the capture path with its current stream limits in mind.** The installed OpenInference checks missed four early-closed stream calls and one cancelled call because no ended span reached the processor. These are missing calls, not rows with unknown status. Captured OpenAI Responses and successful LiteLLM returns can have unknown outcomes when upstream omits terminal evidence; exception spans can still report errors. A streaming/cancellation-heavy application should use a separately verified compatible native/manual path or await upstream coverage fixes. Do not infer that every call was observed from a healthy collector or from other calls appearing successfully.

## Implemented entry and connection journey, 2026-09-13

1. Open `/welcome` to understand the product, then `/demo` to select sample runs, inspect timing/tokens/cost, filter calls needing attention and try an incident resolution. These samples never populate a real workspace and work without private APIs.
2. Select **Connect your app**. The `/setup` route first verifies workspace access and restores Connections after organization sign-in. An existing member signs in with the configured identity provider. A new user must ask the owner for membership; self-service signup and workspace creation are still unimplemented. Local shared-key deployments explain the separate workspace access key.
3. In **Connections**, check the actual project, source and server address. Direct capture leads with three steps: **Create an application key → Install and start your app → Verify your first real call**. The default Python path downloads the 0.2.0 wheel and selects OpenInference explicitly as shown above. Install it in the application's existing environment, set the Sillage address/key, check the selected layer, then start the original app. PowerShell/Bash templates keep the one-time key out of copied commands. Native compatibility and **Manual Python / Node** remain alternatives. Keep the key on the application server. Sillage requires no model-provider key.
4. Run the application for a real captured call; check its receipt, pending work and worker state. Open Live activity or Overview to confirm committed numeric evidence. A connection test is optional and excluded from production counts. `sillage-run --check` checks only local settings and SDK compatibility; neither that check nor an accepted receipt establishes completed analysis.
5. Inspect a run, then configure optional monitoring rules and notifications when ready. Key inventory supports rotation/revocation. Advanced JSON and diagnostics remain available without obscuring the initial path. Langfuse deployments explain their configured source and operator-managed connection separately.

The authenticated Python package route is `/api/guardian/integrations/python.whl`; its fixed attachment is `sillage_observe-0.2.0-py3-none-any.whl`. It is a local installable artifact, not a published PyPI package. The [package guide](../packages/sillage-python/README.md) owns the exact SDK/instrumentor compatibility matrix and stream limits for each selected layer; native compatibility retains its earlier OpenAI 1.99.9/LiteLLM 1.80.0 matrix. Existing manual archives at `/api/guardian/integrations/python.zip` and `/api/guardian/integrations/node.zip` contain three modules plus instructions. No artifact contains credentials. Raw prompts, responses, retrieved documents, full RAG hierarchy and general OTLP reception remain outside this capture contract. [OPENTELEMETRY.md](OPENTELEMETRY.md), [PROVIDERS.md](PROVIDERS.md), [EXPERIENCE.md](EXPERIENCE.md) and [VALIDATION.md](VALIDATION.md).

## Earlier journey design and remaining target behavior

Updated 2026-09-13. The full journeys below remain target behavior. An operator-configured isolated project supports OIDC sign-in, scoped ingestion keys, native capture, separate test/real receipt state, processing backlog, saved monitoring rules, internal incident/run evidence and Slack destination test/activation. The Python launcher now adds bounded automatic SDK capture; manual Python/Node integration remains available. Use [CAPTURE.md](CAPTURE.md), [POLICIES.md](POLICIES.md), [NOTIFICATIONS.md](NOTIFICATIONS.md) and the [Python/Node senders](../examples/native-capture/README.md). This does not provision accounts or establish independent customer activation. Existing access recovery and Langfuse diagnostics remain available under [ACCESS.md](ACCESS.md); named access is defined in [IDENTITY.md](IDENTITY.md).

## Entry experience

R3-03 adds a bounded Slack route under [NOTIFICATIONS.md](NOTIFICATIONS.md): the operator configures one webhook secret and starts the separate delivery worker; a named owner tests and enables it from Setup. This works with native capture or Langfuse. A queued test, receiver acceptance, enabled notifications and a healthy worker are separate states. A new incident links from Slack back to Guardian evidence and resolution; owner retry and recent delivery history expose failures. Self-service Slack installation and customer/deployed activation still need follow-up.

Explain the outcome and supported integrations before asking for credentials. Show a labelled sample incident with workflow impact and an investigation path. Describe collected fields, defaults, retention and limits. Ask the customer to choose:

1. **Start monitoring my app** — no existing telemetry required.
2. **Connect my Langfuse project** — preserve existing instrumentation.

Do not expose infrastructure/module paths in customer-facing errors. Keep operator troubleshooting in a separate guide. A provider key is neither necessary for Guardian to receive exported telemetry nor sufficient to reconstruct historical workflows.

## Journey A: no existing telemetry

Operators can now prepare this journey with the [direct/OIDC deployment package](../deploy/guardian/README.md): configure one isolated database/project and registered identity client, run bootstrap, then expose the same-origin UI/API through HTTPS. Bootstrap removes the previous first-login initialization dependency. Readiness checks database/configuration state, while Setup separately reports test receipt, real receipt and worker processing. The package does not create a customer account or provision the backing services; actual customer activation still requires the deployed checks below.

The first provider recipe is implemented: **Setup -> Capture -> Python/Node -> Responses/Chat Completions**, with a streaming option. Copy the three repository modules into the application, create one process exporter with server-side Guardian configuration and wrap the existing OpenAI SDK operation. Python async and shutdown/early-close guidance are in the [examples](../examples/native-capture/README.md). Chat streams must request final usage; absent/invalid measurements stay unknown and the adapter does not estimate spend. The advanced raw JSON path remains available for unsupported providers. Follow [PROVIDERS.md](PROVIDERS.md) for supported surfaces and exact limitations.

After a labelled synthetic test receipt, run the application's real operation, inspect **Live activity -> Call feed** token totals and **Recent traces -> Tokens (in / out)**, and wait for processing to finish. Configure a duration limit or reported-error rule, investigate its incident and verify notification delivery. An accepted export alone does not establish analysis or activation. A full RAG outcome, real billed cost and deployed customer success require additional evidence.

Implemented now: after configuring direct capture, a named owner opens **Setup -> Monitoring rules**, saves a cost/duration limit and error preference, then checks an actual captured call in Incidents. Details show its measured value, saved threshold/revision and internal run link; resolution preserves the original evidence. Missing prices cannot trigger cost rules. The configured-incident step follows [POLICIES.md](POLICIES.md); Slack test/activation and delivery history follow [NOTIFICATIONS.md](NOTIFICATIONS.md). Deployed customer activation remains open.

| Step | Experience | Completion evidence |
|---|---|---|
| Account/project | Named login, project name, environment, region/data policy | Authorized project created with server-assigned scope |
| Integration | Choose supported language/provider/framework recipe | Exact supported versions and server deployment assumptions shown |
| Provision | Guardian configures an isolated project and ingestion; allocate backing telemetry only when required by the selected capture mode | Provisioning succeeded; retryable error on failure; direct numeric capture requires no Langfuse signup or backing telemetry service |
| Instrument | Copy project-specific setup and add root workflow/outcome plus supported child instrumentation | No provider secret sent to Guardian; ingestion key scoped/revocable; content default off |
| Test | Send a labelled synthetic test event | UI confirms project/environment, timestamp, parsed fields and processing state |
| Real traffic | Run one real customer workflow | Real traffic shown separately from synthetic demo; costs/unknowns, spans and outcome coverage visible |
| Warm up | See baseline sample/history coverage and rules available now | Absolute policies can operate; unavailable statistical rules explicitly warming up |
| Route | Configure an owner and supported destination; send test notification | Destination verified and delivery recorded |
| Activate | Show “Monitoring active” with covered workflows and limitations | Real ingestion healthy, policy enabled, destination verified |

No instrumentation means no real monitoring. Explain the small application change honestly. Do not put Guardian in the synchronous provider request path. Export outages should not break the customer's app; dropped telemetry is counted and shown.

Customers without a Langfuse account investigate in Guardian: workflow summary, signal evidence, affected component, comparison window and runbook. Raw trace exploration may remain in the backing system, but cannot be the only way to understand an incident. Any optional backing-UI access requires project-scoped authorization, never public trace links.

## Journey B: existing Langfuse

1. Choose region/host and submit credentials over authenticated TLS to the server. Store only a secret reference; never return credentials to the UI.
2. Validate connection, project identity, read capabilities, endpoint version and rate-limit behavior. Do not advertise supplied vendor keys as read-only unless their actual permissions establish that.
3. Preview allowlisted metadata and completeness: supported span kinds, cost/usage coverage, workflow names, environment and terminal outcome.
4. Select a bounded backfill window, source usage/cost limits and policies. Explain delayed/updating observations and the distinction between history imported and live monitoring active.
5. Identify missing workflow/RAG instrumentation and provide a precise recipe; basic call metrics remain usable with limits stated.
6. Confirm baseline readiness and delivery using the same final steps as Journey A.

Untrusted custom hosts create an outbound-request boundary: validate schemes, redirects, DNS/IP destinations and egress policy. Public managed onboarding must not turn connector configuration into access to internal services. Private self-hosted endpoints need an explicit deployment/network mode.

## Initial support matrix

The process integration layer in [EXPORTING.md](EXPORTING.md) supplies a bounded Python/Node queue, explicit call/stream handles, prefix flush and visible unconfirmed work. It removes basic queue implementation work for long-running servers. Provider SDK adapters, production runtime acceptance, serverless teardown and RAG semantic coverage remain separate from these generic helpers.

This is the **planned beta** matrix. The manual Python/Node JSON senders are locally tested transport examples, not provider/framework integrations. Choose exact integration versions in R0-03 and publish their separate application results in R2.

| Integration | Required initial evidence | Scope limit |
|---|---|---|
| Python server-side LLM app | Context propagation, model/cost/usage, success/error, streaming, export failure and flush | Tested provider integration versions only |
| JS/TS server-side LLM app | Same, including concurrent requests and serverless shutdown where supported | Browser-direct and untested serverless runtimes excluded initially |
| Python RAG example | Root workflow, retrieval duration/result count, embedding usage, generation and outcome | No document/body capture; no answer-quality guarantee |
| Existing Langfuse Cloud | Versions/fields/pagination, source outage, unknown-price behavior | Supported API/version matrix required |
| Custom OTel/export path | Validated semantic mapping and scoped ingress | OTel connectivity alone does not guarantee workflow/cost semantics |
| Other vendors/no-code stacks | Demand assessment and documented export path | Deferred until tested; don't display as supported |

A single user operation is the root workflow. Child attempts use distinct IDs. Preserve parent/trace linkage through retries and async calls. Embedding costs must not be omitted or double-counted; retrieval timing differs from embedding/model timing. Application outcome and optional pseudonymous customer/feature dimensions need an explicit field contract.

## States and failure messages

| State | Meaning | Customer action |
|---|---|---|
| Setup incomplete | Project exists but ingestion/source not ready | Continue the missing step |
| Awaiting first event | Connection configured; no confirmed event | Run the supplied test and check export diagnostics |
| Test received | Synthetic event works; real traffic not confirmed | Run the real app |
| Warming up | Real telemetry present; baseline insufficient | Review sample/coverage progress; configure absolute policy |
| Active | Real data current, enabled policy and destination verified | Inspect covered workflows |
| Partial | Some spans/pages/fields missing or backlog pending | See exact coverage/reason; avoid conclusions from incomplete totals |
| Delayed | Source ingestion or processing behind target | Inspect lag/queue; retry policy handles recovery |
| Disconnected | Credentials invalid/revoked or source unreachable | Repair connection; show last complete time |
| Paused | Customer intentionally stopped monitoring | Resume when ready |

A successful browser refresh cannot establish “Active.” Failed reads never render as zero spend or “all clear.” Missing prices, outcomes and trace children remain unknown. A retried connection must not create duplicate projects or repeatedly provision backing services.

## Lifecycle and privacy

- Show scopes when creating keys; support rotation and immediate revocation. Never ask a customer to share a server administrator's Guardian key with the whole team.
- Content capture, output previews and PII scanning are disabled by default in the target product. Explain any opt-in before data leaves the app; validate SDK-side redaction.
- Allow disconnect without deleting history, and deletion with a clear scope/retention/backup-expiry explanation. Cancel running work so it cannot recreate deleted data.
- Managed backing data is part of deletion/export policy. BYO disconnection does not delete the customer's original Langfuse project.
- Support failed setup, expired sessions, keyboard navigation, screen readers and narrow displays. Preserve setup progress without keeping secrets in localStorage.

## Activation test

Observe developers who have not worked on Guardian complete setup on their own apps. Record time per step, assistance, failure reason, first synthetic event, first real event, baseline readiness and notification verification. Target a median at most 15 minutes to real attributed traffic for supported stacks; report sample size and slower cases. Measure both paths separately. A fixture/demo-only setup cannot close activation.
