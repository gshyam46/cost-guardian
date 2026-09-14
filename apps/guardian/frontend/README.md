# Sillage frontend

This is the React dashboard for the isolated Guardian service. It inspects captured usage, incidents and monitoring diagnostics. Authentication does not provision telemetry or start application instrumentation; `/setup` explains the current connection and worker state.

The shared design uses cream paper, brick actions and brown ink, with locally hosted **Instrument Serif** display type and **Manrope** interface text. `src/index.css` defines the palette, `src/product.css` styles the workspace, and `src/landing.css` / `src/public-access.css` style the public journey. `SillageBrand.jsx` supplies the wake wordmark; matching SVG/ICO/touch icons and font licenses ship with both builds. See [BRAND.md](../../../docs/BRAND.md) and [DESIGN_REFRESH.md](../../../docs/DESIGN_REFRESH.md).

Local review services refreshed on 2026-09-15: public mode at `http://127.0.0.1:3004` and the existing workspace at `http://127.0.0.1:8001/welcome`. The public preview uses the separate local `sillage_public_preview` database and a synthetic privacy contact; it is not the production registration service. Its availability state remains coming soon because no hosted workspace origin is configured.

## Public Vercel deployment

The public build serves the landing page at `/` and `/welcome`, the interactive sample at `/demo`, registration at `/signup`, the post-registration destination at `/waitlist`, and the data-use notice at `/privacy`. Navigation uses **Sign up / Sign in** and the form submits with **Register**. Optional company/project details stay collapsed. Only the exact committed-save acknowledgment clears the form and shows confirmed waitlist status; direct visits or reloads cannot reconstruct that claim from a URL or browser storage. `/signin` and `/setup` check an independent availability function and offer a link to the configured workspace when it responds. Registration records consented, unverified interest; it does not create an account, workspace or ingestion key. The [public launch contract](../../../docs/PUBLIC_LAUNCH.md) explains these boundaries.

Use **`apps/guardian/frontend` as the Vercel project Root Directory**. Do not select the repository root or the unrelated historical root `frontend` directory. The checked-in `vercel.json` uses Create React App, Node 24, `npm ci --ignore-scripts --no-audit --no-fund`, `npm run build:public`, and output directory `build`. Only explicit public page paths rewrite to `index.html`; `/api/availability` and `/api/interest` remain independent Node functions. Unknown API paths and private dashboard deep links do not fall through to the public HTML. No workspace API proxy is configured.

```powershell
cd apps/guardian/frontend
npm.cmd ci --ignore-scripts --no-audit --no-fund
$env:REACT_APP_PRIVACY_CONTACT_EMAIL = 'privacy@your-domain.example'
npm.cmd run test:public-build
npm.cmd run build:public
```

Replace the example contact with a real, monitored address before collecting public registrations. This is the only optional public environment value preserved by the build script. It validates the address and forces `REACT_APP_PUBLIC_SITE=true`, `REACT_APP_GUARDIAN_URL=/`, production mode, no source maps, and disabled visual-edit/health plugins. Other ambient `REACT_APP_*` settings and all server configuration are removed from the compiler process. The script copies only source/public assets and the named build configuration into a temporary directory; it never reads local `.env` contents or copies server handlers into the browser build. Package links keep build caches in that temporary directory. The result is written to this application's `build/`; local source environment files and installed dependencies remain intact. `.vercelignore` excludes hidden files, local environments, dependencies, caches and previous builds from upload.

Configure these **server-only** values in the intended Vercel environment; never prefix them with `REACT_APP_` or place them in `vercel.json`:

| Setting | Purpose |
| --- | --- |
| `SILLAGE_PUBLIC_ORIGIN` | Exact HTTPS origin of this public site, including the production custom domain. |
| `SILLAGE_WORKSPACE_URL` | Optional exact HTTPS origin of the existing Guardian workspace. Missing/unavailable configuration shows the independent coming-soon and registration flow. |
| `SILLAGE_INTEREST_MONGO_URL` | Dedicated MongoDB Atlas/replica-set connection string for the interest store. Keep this database and credential separate from monitoring data. |
| `SILLAGE_INTEREST_DB` | Explicit dedicated database name for interest and bounded abuse records. |
| `SILLAGE_INTEREST_HMAC_KEY` | Independent random server secret, 32–512 bytes, used to derive abuse keys without storing raw IP addresses. |

Trusted Vercel preview deployments can derive their public origin from platform-supplied `VERCEL_URL` when an explicit origin is absent. Do not point preview registrations at the production interest database. The Atlas Marketplace integration exposes `MONGODB_URI`; explicitly map the intended dedicated database connection to `SILLAGE_INTEREST_MONGO_URL`, rather than assuming the integration supplies the application's variable name. Choose a function/database region and network-access policy together. The installed MongoDB driver is pinned to **7.6.0**, with **@vercel/functions 3.9.7** for connection-pool lifecycle handling.

Provision the interest store and required indexes with the separate operator command before enabling collection. Runtime credentials should have only the permissions needed by the public handler; use a separate operator credential for bootstrap, export and deletion. The privacy contract retains interest records for up to **180 days**, includes explicit contact consent, and sends no automatic outreach. A submission is successful only after acknowledged storage; an unavailable database must leave the form retryable. Do not rely on the availability function as proof of identity, customer onboarding or complete telemetry.

Run operator commands from this application directory with the intended database configuration supplied securely in the process environment. These commands do not load `.env` files. The database must support replica-set transactions and majority/journaled writes; an isolated Atlas deployment is suitable. `mongodb+srv://` uses TLS by default; a standard `mongodb://` URI must explicitly enable TLS. Bootstrap is a separate operation:

```text
node server/interest-admin.cjs --help
node server/interest-admin.cjs bootstrap --confirm-bootstrap
node server/interest-admin.cjs export --output <new-private-file.csv>
node server/interest-admin.cjs delete --email <single-email> --confirm-delete
```

Use a new private export path outside the checkout and restrict access to the resulting CSV; export protects spreadsheet cells from formula execution. Deletion applies to the requested contact record. Runtime MongoDB permissions are `find`, `insert`, `update` on `interest_contacts` and `interest_rate_limits`, and `find` on `interest_schema`; runtime credentials do not need index creation or deletion. Bootstrap needs index creation on the contact/rate collections and schema-marker updates. Use an export credential with contact read access or a deletion credential with contact removal access when performing those operations. Rate-limit records expire after their window plus 24 hours. Keep administrative commands and credentials outside the public functions.

Workspace authentication remains at the configured workspace origin. Its OIDC callback, membership, session cookies and CSRF controls are unchanged. The public deployment does not replace the API, ingestion worker, notification worker or replica-set bootstrap. Existing shared-key/OIDC self-hosted deployments continue to use the ordinary `npm run build` command and same-origin serving described below.

The Vercel account/project and hosted database are **not linked or deployed by this change**. Confirm the account, project, domain, real privacy contact, database/bootstrap and production secrets before publishing. A commercial launch requires an appropriate Vercel plan; Hobby is for personal, non-commercial use. [Vercel CRA support](https://vercel.com/docs/frameworks/frontend/create-react-app), [Node functions](https://vercel.com/docs/functions/runtimes/node-js), [Atlas integration](https://vercel.com/marketplace/mongodbatlas/atlas), [plan boundary](https://vercel.com/docs/plans/hobby).

The [direct/OIDC deployment package](../../../deploy/guardian/README.md) builds this UI with explicit same-origin settings and serves it through the API process. Its bootstrap, static routing and readiness contract is in [DEPLOYMENT.md](../../../docs/DEPLOYMENT.md); local developer servers below remain a separate path.

## Direct event capture

An operator can configure a new isolated OIDC project with `GUARDIAN_CAPTURE_MODE=direct` to accept Guardian JSON version 1 without a Langfuse account. Existing Langfuse deployments retain their source path. Source modes are pinned to the database; Setup does not switch or migrate them. See [CAPTURE.md](../../../docs/CAPTURE.md) for the exact backend configuration, schema, bounds and deployment rules.

In direct mode, `/setup` shows redacted credentials and separate test receipt, real receipt, pending/processed events, conflicts and worker heartbeat diagnostics. A current owner can create a labelled key lasting 1–90 days and revoke existing keys. Other members can inspect metadata. The key is scoped to write events for the server-selected project; it cannot read dashboard data.

Copy a new key before leaving Setup or switching away from the browser. It appears once in component memory and is cleared on dismissal, navigation, session revalidation or logout; it is never saved in browser storage or embedded in the example snippet. Put it in your application server's secret configuration. If creation was not confirmed or the response was lost, refresh the metadata list, identify the label/creation time, and revoke an unrecoverable key before creating another. Creation is never automatically retried.

Connections leads with the installable **0.2.0 Python wheel** and its `[openinference]` extra. Configure the collector address and scoped app key, select the SDK layer the application actually uses, check compatibility, then start the original application through `sillage-run --instrumentation openinference --instrumentors <one-layer> -- python app.py`. Supported OpenAI, LiteLLM and LangChain integrations capture calls at runtime without copying helper files or editing each call. Use the exact tested versions and launch commands in the [package guide](../../../packages/sillage-python/README.md) and [onboarding guide](../../../docs/ONBOARDING.md). The wheel is downloaded from the authenticated workspace; it is not published on PyPI. Bare `sillage-run` retains the native compatibility adapter.

Applications with an existing OpenTelemetry provider can attach `SillageSpanProcessor` once using the `[otel]` extra, preserving their provider, sampler and exporters. Existing Langfuse users can retain their configured source. Manual Python/Node OpenAI Responses and Chat Completions helpers remain available under [PROVIDERS.md](../../../docs/PROVIDERS.md), with advanced versioned JSON for other integrations. Select one capture owner per call to avoid duplicates. A compatibility check does not send data: run a real application action and inspect both receipt and processing before treating it as connected.

**Send test event** is optional and uses only the just-created ingestion key through a separate request that omits browser cookies, dashboard keys and CSRF. Send it while the one-time display is still open. A test receipt creates no production observations, totals or incidents. Missing usage, USD cost and terminal outcomes remain unknown. The standards bridge requires an ended upstream LLM span; some early-closed streams and cancelled calls produce no event. A receipt or recent worker heartbeat does not establish complete monitoring coverage. General OTLP reception, full retrieval/tool/workflow storage and arbitrary SDK coverage remain unfinished; see [INSTRUMENTATION.md](../../../docs/INSTRUMENTATION.md) and [OPENTELEMETRY.md](../../../docs/OPENTELEMETRY.md).

The installed launcher owns a bounded background exporter and shutdown. Manual integrations use the supplied [background exporters](../../../docs/EXPORTING.md) and [shutdown recipes](../../../examples/native-capture/README.md). These queues stay outside the model response path but remain in memory and do not survive process termination. The lower-level manual sender requires an application-owned background queue/job.

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
