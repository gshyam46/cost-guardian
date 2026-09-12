# Guardian dashboard

This is the React dashboard for the isolated Guardian service. It inspects captured usage, incidents and monitoring diagnostics. Authentication does not provision telemetry or start application instrumentation; `/setup` explains the current connection and worker state.

The [direct/OIDC deployment package](../../../deploy/guardian/README.md) builds this UI with explicit same-origin settings and serves it through the API process. Its bootstrap, static routing and readiness contract is in [DEPLOYMENT.md](../../../docs/DEPLOYMENT.md); local developer servers below remain a separate path.

## Direct event capture

An operator can configure a new isolated OIDC project with `GUARDIAN_CAPTURE_MODE=direct` to accept Guardian JSON version 1 without a Langfuse account. Existing Langfuse deployments retain their source path. Source modes are pinned to the database; Setup does not switch or migrate them. See [CAPTURE.md](../../../docs/CAPTURE.md) for the exact backend configuration, schema, bounds and deployment rules.

In direct mode, `/setup` shows redacted credentials and separate test receipt, real receipt, pending/processed events, conflicts and worker heartbeat diagnostics. A current owner can create a labelled key lasting 1–90 days and revoke existing keys. Other members can inspect metadata. The key is scoped to write events for the server-selected project; it cannot read dashboard data.

Copy a new key before leaving Setup or switching away from the browser. It appears once in component memory and is cleared on dismissal, navigation, session revalidation or logout; it is never saved in browser storage or embedded in the example snippet. Put it in your application server's secret configuration. If creation was not confirmed or the response was lost, refresh the metadata list, identify the label/creation time, and revoke an unrecoverable key before creating another. Creation is never automatically retried.

**Send test event** uses only the just-created ingestion key through a separate request that omits browser cookies, dashboard keys and CSRF. Send it while the one-time display is still open. A test receipt creates no production observations, totals or incidents. Setup leads with Python/Node OpenAI Responses and Chat Completions recipes, including streaming, under [PROVIDERS.md](../../../docs/PROVIDERS.md); advanced versioned JSON remains available for other providers. Add the explicit helper around the application's existing operation, run real traffic and inspect separate receipt/processing states. Missing usage and USD cost remain unknown. Receipt or a recent worker heartbeat alone does not establish complete monitoring coverage; automatic OTLP/framework instrumentation remains planned.

The supplied [background exporters](../../../docs/EXPORTING.md) own a bounded per-process queue outside the model response path. Follow the [integration and shutdown recipes](../../../examples/native-capture/README.md); this queue is in memory and does not survive process termination. The lower-level manual sender must run in an application-owned background queue/job rather than delay the customer response.

Revocation stops future accepted intake when confirmed; already accepted work may finish processing. Signing out or removing the creator does not revoke project ingestion keys. Unknown or unavailable status is shown explicitly, and failed revocation remains unconfirmed until a subsequent successful response.

## Local development

Use Node 24 and npm 11. `package-lock.json` is authoritative for installation; the historical Yarn lock is not the supported install path.

```powershell
cd apps/guardian/frontend
npm.cmd ci
Copy-Item .env.example .env
npm.cmd start
```

The development dashboard defaults to port 3001 and the API to `http://localhost:8001`. The public `/api/guardian/auth/config` response chooses the sign-in flow before the browser consults any saved key:

- `api_key`: enter an operator-supplied Guardian key. The dashboard validates it before saving it locally. Disconnect removes this browser's key; it does not revoke the server credential.
- `oidc`: choose **Sign in with your organization**. The server completes the identity-provider exchange, verifies membership and issues an HttpOnly session cookie. The dashboard never reads or sends a saved shared key in this mode. Actor, project, permissions and CSRF are kept in memory. Viewers can inspect incidents; owners and operators can resolve them.

Local OIDC requires the backend's explicit `GUARDIAN_ALLOW_INSECURE_LOCAL_AUTH=true` exception and loopback issuer/UI/API configuration. Use the same loopback hostname for the UI and API so browser SameSite cookie rules work consistently across ports. See [IDENTITY.md](../../../docs/IDENTITY.md) for the exact operator configuration; no provider secret belongs in this frontend's environment.

## Production build and serving

Serve the UI and `/api` through one HTTPS origin. Forward `/api/guardian/auth/login` and `/api/guardian/auth/callback` to the Guardian backend, and serve `index.html` for application deep links such as `/incidents/<id>`. The backend's public and UI origins must match this deployment.

`REACT_APP_GUARDIAN_URL` is a public build-time setting. With no override, production requests use the current page origin. A development `.env` can override that default, so explicitly use `/` when producing a portable same-origin bundle:

```powershell
$env:REACT_APP_GUARDIAN_URL = '/'
$env:CI = 'true'
npm.cmd test -- --watchAll=false --runInBand
npm.cmd run build
```

OIDC rejects remote cross-origin and non-HTTPS deployments; the explicit loopback development exception remains available. API-key development can still target a separate configured API origin. The public auth configuration verifies configuration shape, not provider or telemetry health.

Organization sign-in restores only a validated local application pathname after a verified callback. **Sign out** immediately removes protected views and requests server session revocation; a failure shows **Retry sign-out** and does not claim the session ended. Retry verifies the current session before attempting logout. Other tabs revalidate after a nonsecret logout notification or when focused. Guardian logout does not sign out the identity-provider account.

The frontend tests use controlled transport fixtures. The production browser walkthrough in [browser_smoke.cjs](../../../tools/browser_smoke.cjs) also uses synthetic APIs and session cookies; it does not establish a deployed provider/TLS integration. Current release checks and remaining gates are tracked in [VALIDATION.md](../../../docs/VALIDATION.md).
