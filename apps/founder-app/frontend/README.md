# Founder demo frontend

This frontend belongs to the independent Founder Niche Discovery demo workload, shown as FounderPath in the browser. Sillage does not require this app, its authentication or its database to run.

For the product review and implementation plan, start at the [repository README](../../../README.md). The demo is maintained to exercise realistic multi-step LLM telemetry, not as a second launch product.

## Local setup

Use Node 24/npm 11. From this directory, in PowerShell:

```powershell
npm.cmd ci
Copy-Item .env.example .env
npm.cmd start
```

The backend runs separately on port 8000 with its own Python environment and configuration. The browser authentication flow currently depends on an external Emergent authentication service. Its credentials/availability and a complete browser run were not verified in the 2026-09-11 review.

The template sets port 3000 and the public backend URL at port 8000. Keep real secrets on the backend; never put provider credentials into React build variables.

## Original-app preview and telemetry

The original app was started locally on **2026-09-13 IST** at <http://127.0.0.1:3002>, with its FastAPI backend at <http://127.0.0.1:8002/api/health>. Ports 3000 and 8000 were already owned by another project and were preserved. This preview uses a fresh production build of this frontend, the existing Founder backend, and a separate `founder_preview_mvp2` Mongo database. Runtime details are in ignored `.cache/preview/founder-preview.json` at the repository root. These URLs are local processes, not hosted deployments.

The backend now runs through the installed **Sillage Python launcher**, with an application key issued through the preview's actual owner OIDC flow. No Founder application source was changed for this connection. The existing database and frontend were preserved. The local check confirms compatible OpenAI `1.99.9` and LiteLLM `1.80.0` adapters; backend health is successful.

**Instrumentation is configured, but no real Founder model-call receipt has been verified.** No private environment files, model-provider credentials or Langfuse credentials were loaded. Starting the server or viewing its landing page does not make an LLM call. Capture counts were unchanged by the restart. Sign-in still redirects to the original external Emergent authentication service; no local sign-in bypass or generated reports were introduced.

The installed runtime observes this path when a supported model call occurs:

```text
sillage-run starts the original Founder backend
  -> instrumentation hooks load before application imports
  -> existing five-agent pipeline calls LiteLLM acompletion
  -> numeric call metadata enters the background exporter
  -> Sillage direct collector -> worker -> captured calls and runs
```

The application key is held only in the running backend environment, not in source, command arguments, logs or saved runtime reports. Its label is `FounderPath local preview` and it expires after seven days. A future manual restart must supply a securely stored valid key; existing secrets cannot be recovered from the dashboard. The safe restart evidence is in ignored `.cache/preview/founder-instrumentation.json`. The installed wheel is `sillage_observe-0.1.0-py3-none-any.whl`, SHA-256 `a75974be424406aa30d8cc637cc84257162f7118e6583d050efed873f8fb540f`.

The original source also retains this optional Langfuse path:

```text
POST /api/analyze
  -> orchestrator creates one run_id
  -> five agents pass that run_id and their agent name
  -> llm_fallback.py calls LiteLLM acompletion
  -> configured success/failure callbacks export to Langfuse
  -> a Sillage deployment in Langfuse mode reads that project
```

The callback is enabled only when both Langfuse keys are configured. The running Sillage preview uses **direct capture**, so it does not read Langfuse. Its new launcher connection observes the supported SDK calls directly and does not require that callback. Merely running both apps without instrumentation and destination configuration would not connect them. Installation, current limitations and verification are documented in [onboarding](../../../docs/ONBOARDING.md) and the [instrumentation contract](../../../docs/INSTRUMENTATION.md).

The original client currently tries Groq and OpenRouter model names. Its model calls obtain credentials through LiteLLM's provider environment variables; the `GOOGLE_GEMINI_API_KEY` configuration field does not by itself select a Gemini model in that fallback chain. Real provider execution and external authentication remain separate setup requirements. The existing Langfuse SDK2 exporter also still needs the compatibility work described in [source migration](../../../docs/SOURCE_MIGRATION.md).

The fresh production build passed. Browser checks at 1280px and 390px verified the real landing page, API session checks, protected-dashboard redirect and no horizontal overflow or JavaScript page errors. External font requests were blocked during the check. This proves local rendering and unauthenticated routing; it does not prove Emergent sign-in, an analysis run or telemetry delivery. Evidence is under ignored `tools/reports/founder-preview/` at the repository root.

## Checks

```powershell
$env:CI = "true"
npm.cmd test -- --watchAll=false --runInBand
npm.cmd run build
```

Both a package-lock and a Yarn lockfile exist historically. npm and the tracked package-lock are authoritative; the old Yarn lock is preserved. The 2026-09-11 R0-01 implementation passed a clean npm install, four JSDOM route/session tests and a production build. Tests mock HTTP services and do not prove live OAuth or deployed SPA fallback. Guardian's product evidence is tracked in [VALIDATION.md](../../../docs/VALIDATION.md).

Unused template script injection, badge and template-project analytics have been removed. The app's explicit Emergent authentication integration remains. The repaired [verification harness](../../../tools/README.md) runs each backend independently and separates offline evidence from explicitly configured live traffic.
