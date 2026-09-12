# Verification harness

Updated 2026-09-12. These commands establish engineering evidence for R0-01, the R1 source/measurement work and the R2 identity/native-capture slices. A passing offline check does not establish production readiness or a working customer onboarding journey.

## Safe default and independent environments

Monitoring rule acceptance is defined in [POLICIES.md](../docs/POLICIES.md). With a separately owned local test replica set, run `python tools/test_mongo_policies.py --mongo-url 'mongodb://127.0.0.1:27019/?replicaSet=guardian-r102&directConnection=true' --report tools/reports/mongo-policies-r302.json` using the existing backend interpreter. It exercises policy save/read-back, actual HTTP capture through threshold incidents and resolution, revision conflicts, audit rollback, logout and policy-pin ordering. Run it sequentially with other fault suites. No arguments print help without application imports, external traffic or configuration reads.

`python tools/verify_mvp.py` and `python tools/build_baseline.py` print help and exit successfully. They do not import either application, read `.env`, contact services or generate model traffic. `--help` is also safe with only Python's standard library installed.

The parent CLI uses only the standard library. Each child runs exactly one application's imports with its explicitly selected Python executable, backend working directory and environment. Python isolated mode disables inherited Python import paths. Only OS essentials survive from the parent environment; database settings, API/provider credentials, proxies and Python settings must come from the selected configuration. Each child disables automatic dotenv loading, including the application's normal `.env`.

The Guardian API binds an OS-selected loopback port. The parent makes actual HTTP requests over TCP, checks `X-Guardian-Key`, and verifies that missing credentials, incorrect credentials and the old Founder session cookie each return 401 on access, incidents and summary (nine denials). Keys are not put in command arguments. HTTP requests do not follow redirects or use ambient proxies. Owned processes are stopped after completion, failure, timeout or interruption; Windows cleanup includes the venv launcher's process tree.

## Offline verification

Install Guardian independently, from the repository root (PowerShell):

```powershell
python -m venv apps/guardian/backend/.venv
& apps/guardian/backend/.venv/Scripts/python.exe -m pip install -r apps/guardian/backend/requirements.txt -c apps/guardian/backend/requirements.constraints.txt
python -m unittest discover -s tools/tests -v
python tools/verify_mvp.py offline --guardian-python apps/guardian/backend/.venv/Scripts/python.exe
```

On Linux/macOS use `apps/guardian/backend/.venv/bin/python` as the interpreter path. The constraints snapshot pins resolved transitive versions; it is not a hash lock or dependency security audit.

The offline smoke sends six synthetic baseline observations and one synthetic expensive observation into the real Guardian worker. The worker runs real detectors and the incident engine, then uses `MongoIncidentStore` and `MongoMetricsStore` against `mongomock-motor`. The actual Guardian FastAPI app verifies access and serves the resulting incident, incident detail, summary and metrics over localhost HTTP. Access must return the explicit shared-key/single-project permissions contract; a malformed successful response or failed access check fails the smoke. This check does not establish a named-user session or customer activation.

The authorized summary must have complete timestamp coverage, reconciled breakdowns and exactly 14 ordered UTC calendar dates through today. Offline assertions require one open high-severity cost incident, one recent incident and one trend count on the created incident's actual UTC day; a run crossing midnight does not assume that the incident belongs to today. Seven calls must remain accounted for in metrics. A failed or partial summary fails verification.

No Langfuse or MongoDB server is used, and outbound socket dialing in the child is disabled. The API key is generated for that process. Report labels are `source=synthetic`, `persistence=mongomock`, `http_transport=localhost_tcp`. The harness explicitly replaces the transaction runner for its mock database; production has no such fallback. Initial accounting now includes all seven captured observations ($5.06), including baseline history. This verifies worker/component/storage-adapter/API wiring; it does not verify a live source adapter, MongoDB semantics, browser interactions or deployment recovery.

## Real Mongo transaction verification

`tools/test_mongo_ledger.py` uses the installed Guardian dependencies and a fresh, isolated single-node test replica set named `guardian-r102`. It requires an explicit loopback-only URI, no database name or credentials, and `enableTestCommands=1`. Never enable that option on an existing deployment. The CI job creates its own MongoDB 8.0.26 container. The Windows local run uses a verified official MongoDB archive under the ignored `.cache` directory.

```powershell
& apps/guardian/backend/.venv/Scripts/python.exe tools/test_mongo_ledger.py --mongo-url 'mongodb://127.0.0.1:27019/?replicaSet=guardian-r102&directConnection=true'
```

The tool prints help without imports when called without arguments. It never reads application `.env` files. Each case creates a random marker-owned `guardian_r102_test_*` database, restricts failpoints to its own client application name, restores its failpoint and drops only that exact owned database. The JSON report records versions and individual checks. It covers transaction abort, committed-but-unacknowledged retry, concurrent replay, stale leases, restart/materialization, privacy, conflicts, overflow and resolved incident replay. This is transaction evidence on one local node, not a replica failover, backup/restore or live Langfuse compatibility drill. See [INGESTION.md](../docs/INGESTION.md) and [VALIDATION.md](../docs/VALIDATION.md).

Options: `--timeout 45` is the default overall work deadline in seconds; cleanup can take a further few seconds. `--report tools/reports/offline.json` chooses another report path; its parent directories are created. The default is the ignored `tools/verify_mvp_report.json`.

## Real Mongo incident summary verification

`tools/test_mongo_summaries.py` uses the same explicit loopback-only test replica set and marker-owned database cleanup as the ledger suite. Run the two suites sequentially because their fault cases use Mongo failpoints. No arguments or `--help` prints usage without importing application dependencies.

```powershell
& apps/guardian/backend/.venv/Scripts/python.exe tools/test_mongo_summaries.py --mongo-url 'mongodb://127.0.0.1:27019/?replicaSet=guardian-r102&directConnection=true'
```

Five checks exercise complete counts and the index plan over 42,077 synthetic incidents; legacy UTC/offset/invalid timestamps; corrupted canonical date arrays and unsupported years; the real store's UTC/BSON write contract; and authentication before database commands, safe aggregation failure and recovery. Current results are recorded in [VALIDATION.md](../docs/VALIDATION.md), with the local JSON under ignored `tools/reports/mongo-r103.json`. CI writes the same suite's output to `tools/reports/mongo-summaries.json`. The suite does not benchmark supported production load, contention or multi-node recovery.

## Real Mongo identity verification

The same database can also run the native capture suite described below; run all fault suites sequentially.

`tools/test_mongo_identity.py` uses the same isolated `guardian-r102` test replica set and marker-owned database cleanup as the ledger and summary suites. Run fault suites sequentially. The identity suite requires no provider account, uses synthetic members and opaque session tokens, and does not read the application's `.env`.

```powershell
& apps/guardian/backend/.venv/Scripts/python.exe tools/test_mongo_identity.py --mongo-url 'mongodb://127.0.0.1:27019/?replicaSet=guardian-r102&directConnection=true'
```

Eight cases cover browser-bound single-consumer login state, competing database scope bindings, audit-insert failure rolling back resolution, twelve concurrent resolutions preserving one timestamp/audit, both orderings of resolution versus logout, replacement-session rollback and an already-committed transaction with an uncertain acknowledgement. Command monitoring checks majority acknowledgement on flow consumption and logout without retaining secret query values. This is real local transaction evidence, separate from the signed-token/provider-transport tests and synthetic browser flow. It does not establish multi-node failover, a real provider registration or deployed TLS behavior. CI runs this suite in its existing isolated Mongo job and saves the report.

The backend suite now also includes `test_oidc_provider.py` (real RSA signatures over controlled HTTPX2 responses), `test_identity_api.py`, `test_identity_store.py`, `test_identity_settings.py` and `test_identity_logging.py`. These prove the local [identity contract](../docs/IDENTITY.md). The offline worker-to-HTTP smoke explicitly selects `api_key` mode and strips inherited OIDC credentials; its successful output does not substitute for those identity checks.

## Real Mongo notification delivery verification

The notification contract is [NOTIFICATIONS.md](../docs/NOTIFICATIONS.md). Its harness uses synthetic OIDC members, actual Guardian HTTP routes, marker-owned Mongo databases and an owned localhost receiver. An injected HTTP transport rewrites the synthetic Slack URL to that receiver; production URL validation stays active and no Slack message is sent. Run this fault suite sequentially with the existing real Mongo suites.

```powershell
& apps/guardian/backend/.venv/Scripts/python.exe tools/test_mongo_notifications.py --mongo-url 'mongodb://127.0.0.1:27019/?replicaSet=guardian-r102&directConnection=true' --report tools/reports/mongo-notifications-r303.json
```

No arguments or `--help` are safe without application packages and perform no network or database work. Explicit execution rejects remote/credentialed database URLs and reports outside `tools/reports`. Seven grouped checks cover the owner test/enable/incident/history/run/resolve/replay journey, audited command rollback/races, actual HTTP rate/rejection/deadline/body limits, atomic incident/outbox/completion rollback, concurrent/crashed workers and stale acknowledgements, disable/rotation, and logout command ordering. A committed command can correctly lose its separate authenticated read-back if logout wins afterward; its durable receipt, audit and state remain the proof.

The production-build browser runner now includes notification setup and incident history. Its synthetic API routes prove browser behavior separately from the real API/Mongo/receiver harness. Current outputs are under `tools/reports/browser-notifications`; see [VALIDATION.md](../docs/VALIDATION.md) for results and runtime limits. The CI workflow includes the notification Mongo suite and report artifact; hosted CI was not run, and local validation does not establish deployed Slack acceptance.

## Explicit live verification

Live mode makes provider calls and writes telemetry/Guardian data. It requires `live --allow-live`, separate interpreter paths, and two dedicated env files. Nothing in normal CI invokes it.

1. Create a dedicated Langfuse test project and provider credentials with suitable test limits. Do not select a customer/production project. Keep other workloads and Guardian workers off this test project/database for the verification run.
2. Create distinct test database names prefixed `guardian_verify_`. The Guardian database must have no collections; the harness checks this before a paid workload. It never deletes existing data to make this check pass.
3. Install Founder's dependencies in its own environment:

```powershell
python -m venv apps/founder-app/backend/.venv
& apps/founder-app/backend/.venv/Scripts/python.exe -m pip install -r apps/founder-app/backend/requirements.txt -c apps/founder-app/backend/requirements.constraints.txt
```

4. Save the following separate files as `tools/.harness/founder/.env` and `tools/.harness/guardian/.env`, replacing placeholders. Files named `.env` are ignored by Git. Do not put credentials in tracked examples or command arguments.

Founder test file:

```dotenv
GUARDIAN_HARNESS_TEST_ONLY=1
MONGO_URL=mongodb://127.0.0.1:27017
DB_NAME=guardian_verify_founder_run01
LANGFUSE_PUBLIC_KEY=replace-with-dedicated-test-project-public-key
LANGFUSE_SECRET_KEY=replace-with-dedicated-test-project-secret-key
LANGFUSE_HOST=https://cloud.langfuse.com
GROQ_API_KEY=replace-with-test-provider-key
```

Guardian test file:

```dotenv
GUARDIAN_HARNESS_TEST_ONLY=1
MONGO_URL=mongodb://127.0.0.1:27017
GUARDIAN_DB_NAME=guardian_verify_guardian_run01
GUARDIAN_API_KEY=replace-with-a-random-test-key-at-least-16-characters
LANGFUSE_PUBLIC_KEY=replace-with-the-same-test-project-public-key
LANGFUSE_SECRET_KEY=replace-with-the-same-test-project-secret-key
LANGFUSE_HOST=https://cloud.langfuse.com
LANGFUSE_READ_API=v2
```

The Langfuse host and keys must match exactly across the two files; use the host for your actual test project/region. Database names must be different and match `guardian_verify_[a-z0-9_]{1,40}`. The test-only marker is an operator assertion: names/markers cannot prove that remote credentials actually belong to a test project. The current sample app requires `GROQ_API_KEY` or `OPENROUTER_API_KEY` because those are the providers used by its fallback chain.

The parser accepts `KEY=value`, matching single/double quoted values, blank lines and full-line comments. It rejects duplicate/unknown keys and interpolation such as `${OTHER_KEY}`. It does not support `export` statements or inline comments. Each application's normal `apps/.../backend/.env` path is rejected even if it contains test-looking values.

5. Run from the repository root:

```powershell
python tools/verify_mvp.py live --allow-live --founder-python apps/founder-app/backend/.venv/Scripts/python.exe --guardian-python apps/guardian/backend/.venv/Scripts/python.exe --founder-env tools/.harness/founder/.env --guardian-env tools/.harness/guardian/.env
```

Guardian preflight checks dependencies, MongoDB reachability/emptiness and a bounded read through the selected adapter before the Founder workload begins. Default `v2` uses HTTPX Observations v2; explicit `v1` uses legacy SDK2. The report records and cross-checks API mode. The Founder child runs its actual five-agent pipeline with a synthetic customer profile. Guardian requires those five agent names under each actual run ID. Successful generations must have model, positive tokens, latency and cost; a free or unpriced model does not establish cost mapping for this check.

The worker gets an explicit test cursor just before the first workload, so a pipeline taking longer than five minutes is included. The harness captures the typed `SourceReadResult` used by `poll_once`, requires complete traversal, verifies that the intended runs were in its actual candidate set, and reconciles stored count/cost/token/error/latency totals per hour and agent against that set. It uses the shared source adapter; a partial/failed read is not successful empty traffic. A preceding source probe or unrelated traffic cannot substitute for this evidence.

The parent finally checks the actual localhost API and authentication. No deterministic anomaly is injected in live mode, and the run can succeed with zero incidents. This is real source ingestion/rollup/API evidence; it does not assert an organic anomaly, delivered notification, customer outcome, UI journey or production deployment. Those require later launch-gate checks. An anomaly injected directly at a detector would be a separate component check, never live source end-to-end evidence.

Live defaults: `--timeout 900`, `--poll-timeout 120` (seconds). The overall work deadline applies to children and HTTP calls. Model/SDK requests that cannot cancel internally are stopped with the owned child process. Neither providers nor Langfuse are assumed to be fast enough: missing arrivals fail the check.

Founder remains on SDK2's legacy exporter. Modern reads do not migrate that writer. On Cloud, older exporter data may take up to 15 minutes to reach v2; the default two-minute poll wait cannot certify it. A dedicated compatibility experiment may explicitly increase both budgets, but eventual arrival does not prove worker late-arrival safety. Self-hosted v4 requires a compatible exporter. This unchanged workload/manual workflow is not a verified modern end-to-end path. [Migration contract](../docs/SOURCE_MIGRATION.md).

## Build real baseline history

```powershell
python tools/build_baseline.py live --allow-live --founder-python apps/founder-app/backend/.venv/Scripts/python.exe --guardian-python apps/guardian/backend/.venv/Scripts/python.exe --founder-env tools/.harness/founder/.env --guardian-env tools/.harness/guardian/.env --runs 6 --pause-seconds 45
```

This reuses the same isolated harness and failure exit codes. It runs 1-20 real workloads (default six), varies the synthetic profile, waits between runs and validates all resulting telemetry together. Default total timeout is 3600 seconds. It creates real history for later detector evaluations; the batch itself does not guarantee a triggered anomaly. Use a fresh Guardian database for each invocation. Reports use the same default filename as verification unless `--report` is supplied.

## Reports and failure handling

Exit codes are 0 for success/help, 1 for verification/configuration/report failure, 2 for invalid CLI arguments, and 130 for interruption. An unsuccessful Founder workload makes baseline building fail instead of returning success. An invalid CLI invocation prints usage before any work and does not write a report.

Reports contain fixed evidence labels, step outcomes, aggregate counts, UTC timestamps and allowlisted failure codes. They exclude raw child logs, arbitrary exception messages, URLs, env values, trace IDs, model responses and credentials. A child SDK log cannot be copied into a report. Reports are replaced atomically and `ok` refers only to the stated scope.

| Failure code | Check next |
|---|---|
| `configuration_invalid` | Dedicated env paths, required keys, test markers, allowed key names, distinct prefixed DB names and matching Langfuse project |
| `interpreter_missing`, `dependency_missing`, `child_start_failed` | Explicit executable path; install that app's requirements with its constraints; check OS permission to start the interpreter |
| `test_database_not_empty` | Select a new empty Guardian test DB; do not erase customer data |
| `live_source_failed` | Test-project credentials/region/reachability, SDK read access, ingestion delay and grouped five-agent trace arrival |
| `live_mapping_failed` | Successful test generations' model/token/latency/positive-cost fields; use a supported priced model |
| `offline_worker_failed`, `live_worker_failed` | Worker regressions, actual candidate coverage and stored aggregate reconciliation |
| `founder_workload_failed` | Test provider availability/limits and Founder's own pipeline tests; do not paste raw provider secrets into reports |
| `api_verification_failed` | Guardian API health, header authentication and incident/metric contracts |
| `child_timeout` | Total deadline and ingestion deadline; inspect test systems before authorizing another paid run |
| `child_protocol_invalid`, `child_failed` | Independently verify the selected app's imports/tests; raw child output is intentionally suppressed |
| `report_write_failed` | Report path permissions and available storage |

Test telemetry and Guardian test records are retained for inspection. No remote project/database cleanup is automatic. Live services were not exercised as part of the 2026-09-11 implementation. See [VALIDATION.md](../docs/VALIDATION.md) for recorded results and remaining limits.

## Local production-build browser check

After building Guardian, install the browser harness outside the application dependency trees and run it from the repository root. This Windows check uses an installed Microsoft Edge in headless mode and a fresh isolated browser context:

```powershell
npm.cmd install --prefix .cache/browser-check --no-save --package-lock=false --no-audit --no-fund playwright@1.63.0
node tools/browser_smoke.cjs --playwright .cache/browser-check/node_modules/playwright
```

No arguments or `--help` prints usage without loading Playwright or starting a server. The explicit command serves the Guardian production build on an ephemeral loopback port, intercepts API calls with synthetic responses, validates the synthetic authentication header and blocks all other network destinations. It does not load an existing browser profile or use a customer API key.

Forty-one scenarios cover partial coverage at desktop/mobile widths, rejected-only unknown spend, unavailable source, stale worker, bounded empty run, partial undetermined run, ledger scope/backlog, incident load failure and retry, stale rows, successful empty results, filter changes and partial incident summaries. Access/setup scenarios add verification before protected reads and key persistence, rejected/expired keys, outage retention/retry, access during partial summaries, disconnect, data401 recovery, real cross-tab disconnection and read-only setup states. OIDC cases cover public configuration failure, key-free entry, viewer/operator permissions, cookie/CSRF/Origin checks, logout failure/retry, expiry/unavailability, malformed identity responses, failed callback and cross-tab logout. Screenshots and a JSON report are written under ignored `tools/reports/browser-r201/`; preceding evidence remains under `browser-r1/`, `browser-v2/`, `browser-r102/`, `browser-r103/` and `browser-r203/`. This is real browser rendering/navigation with mocked API transport, separate from actual API HTTP and unperformed live/deployed onboarding checks.

Browser route assertions remain strict and report safe method/scenario information on failure; browser/server cleanup runs on errors as well as success. [VALIDATION.md](../docs/VALIDATION.md) records one earlier non-reproduced access-route assertion alongside the final successful normal/slower walkthroughs. It has not been assigned a confirmed cause.

The default reader uses Observations v2 and never falls back automatically. Select `LANGFUSE_READ_API=v1` only where legacy reads remain supported; Cloud removes them on 2026-11-16. Real server/exporter compatibility still gates beta. [Migration guide](https://langfuse.com/faq/all/deprecated-api-migration), [telemetry contract](../docs/TELEMETRY.md).

## Native capture and sender verification

The background export continuation has its own actual HTTP/Mongo suite. With the owned local replica set running, use the existing Guardian interpreter and Node 24:

```powershell
& apps/guardian/backend/.venv/Scripts/python.exe tools/test_mongo_exporters.py --mongo-url 'mongodb://127.0.0.1:27019/?replicaSet=guardian-r102&directConnection=true' --report tools/reports/mongo-exporters-r202.json
```

Python and Node each send test-only and production fixture events through the actual API, then process/read the ledger, metrics and incidents. A deliberately hidden committed receipt requires replay with unchanged identity. Evidence checks unknown/zero cost, distinct application retries, terminal/early stream behavior, original provider result/exception identity and content canaries. No real model, identity-provider account or customer project is used. Fresh marker-owned case databases are removed afterward; the operator separately owns replica-set startup/shutdown. This suite complements the earlier capture transaction faults rather than replacing them.

The standard-library discovery command also runs Python exporter tests and a wrapper around the built-in Node test suite, including queue/byte bounds, immutable retries, prefix flush, forced-close counters and call lifecycle behavior. CI explicitly installs Node 24 for these jobs. Backend `test_exporter_contract.py` independently compares both clients with the existing strict server event schema; a missing Node runtime is an explicit skip locally. See [EXPORTING.md](../docs/EXPORTING.md) for the contract and [VALIDATION.md](../docs/VALIDATION.md) for actual results.

The strict Guardian JSON contract and operator steps are in [CAPTURE.md](../docs/CAPTURE.md). Run the real capture suite against a separately started owned loopback replica set; it uses synthetic named sessions, no identity/provider account and no application `.env`:

```powershell
& apps/guardian/backend/.venv/Scripts/python.exe tools/test_mongo_capture.py --mongo-url 'mongodb://127.0.0.1:27019/?replicaSet=guardian-r102&directConnection=true'
```

The suite covers owner-key/audit atomicity, request replay and active-key races, ambiguous committed acknowledgements, receipt/quota/backpressure rollback, key revoke versus intake in both orderings, worker inbox acknowledgement rollback/recovery, and initially competing source-mode claims. Its actual localhost HTTP case creates a key, distinguishes test receipt from real backlog, processes real numeric events and reads metrics, incidents and internal run evidence without constructing a Langfuse client. Database/failpoint ownership and cleanup follow the ledger suite; run them sequentially. It proves a local single-node path, not deployed OIDC/TLS, production failover or application instrumentation.

The standard-library suite includes real Python and Node sender transport checks against an owned local HTTP server: header authority, explicit offline help, test separation, immutable retry bytes, bounded Retry-After guidance, rejected redirects and untrusted/oversized receipt handling. Run with `python -S -m unittest discover -s tools/tests -v`; Node cases require `node` on PATH and explicitly skip when absent. The low-level `guardian_capture` manual senders use only the Python standard library or built-in Node APIs and leave background scheduling to the application. The bounded background exporters and provider helpers are documented in [EXPORTING.md](../docs/EXPORTING.md) and [PROVIDERS.md](../docs/PROVIDERS.md); their queues are in memory and do not survive process termination.

The existing offline worker smoke explicitly selects `api_key` and `langfuse`, stripping inherited OIDC/capture settings. It remains separate from the direct-capture API/database checks. Current reports and precise evidence limits are recorded in [VALIDATION.md](../docs/VALIDATION.md).

## Local OpenAI SDK compatibility proof

Install the verification SDKs separately from Guardian. These are test dependencies; the native integration examples use the application's existing OpenAI client.

```powershell
python -m venv .cache/provider-python
& .cache/provider-python/Scripts/python.exe -m pip install -c apps/founder-app/backend/requirements.constraints.txt openai==1.99.9 httpx==0.28.1 pydantic==2.12.4
npm.cmd ci --prefix tools/provider-fixtures --ignore-scripts --no-audit --no-fund
& apps/guardian/backend/.venv/Scripts/python.exe tools/test_mongo_providers.py --sdk-python .cache/provider-python/Scripts/python.exe --mongo-url 'mongodb://127.0.0.1:27019/?replicaSet=guardian-r102&directConnection=true' --report tools/reports/mongo-providers-r202.json
& .cache/provider-python/Scripts/python.exe -I tools/provider-fixtures/python_async_check.py --run
```

The four Mongo cases exercise Python OpenAI 1.99.9 and Node OpenAI 7.15.0 against owned localhost JSON and fragmented SSE responses for Responses and Chat Completions. They verify known versus missing usage, unknown USD cost, early stream closure, consumer mutation, error incidents, resolution, test-event separation and unchanged canonical batches after a committed receipt is hidden. Each case has a 90-second deadline containing two isolated SDK children, each bounded to 30 seconds. SDK children receive synthetic configuration through stdin with a scrubbed environment; they reject external provider and Guardian origins. No account, model-provider call, application `.env` or customer database is used. Reported source hashes identify the wrapper/exporter files exercised.

The Mongo server must already be an explicitly owned local `guardian-r102` replica set. Random marker-owned case databases are cleaned on success and failure; child process trees and owned HTTP listeners are closed before database cleanup. The server lifecycle remains separate. No arguments or `--help` prints usage without third-party imports or network activity. The asynchronous Python follow-up uses real SDK objects with HTTPX MockTransport and a recording exporter; it is separate from the actual HTTP/Mongo pipeline evidence. [PROVIDERS.md](../docs/PROVIDERS.md) records the supported surface and limits.

## Actual native deployment and browser acceptance

`test_deployment.py` exercises the [packaged entrypoints](../deploy/guardian/README.md) through actual local services. Supply the Guardian interpreter, an isolated Playwright 1.63 module directory/browser installation, and a production frontend build staged from the [Dockerfile's allowlisted inputs and explicit flags](../deploy/guardian/Dockerfile). Do not build this acceptance fixture from a development directory containing `.env` files. The CI `native-deployment` job records the clean source-staging/build recipe. No arguments or `--help` prints usage without loading application configuration or third-party packages.

Start two separately owned, empty loopback Mongo fixtures: a single-node `guardian-r102` replica set and a standalone server on a different port. The standalone server proves that bootstrap rejects a database without transaction support; it is not a supported product deployment. The harness checks these capabilities, allocates random marker-owned case databases and owns a separate TCP relay for database-outage simulation. Run database suites sequentially against these fixtures. This deployment suite uses a temporary validator and scoped profiler on its own case database for rollback proof; it does not require failpoints or test commands.

PowerShell from the repository root, replacing the two dependency/build placeholders with explicit local paths:

```powershell
& apps/guardian/backend/.venv/Scripts/python.exe tools/test_deployment.py --guardian-python apps/guardian/backend/.venv/Scripts/python.exe --mongo-url 'mongodb://127.0.0.1:27019/?replicaSet=guardian-r102&directConnection=true' --standalone-url 'mongodb://127.0.0.1:27020/?directConnection=true' --playwright '<isolated-playwright-module-directory>' --static-dir '<allowlisted-production-build-directory>' --report tools/reports/deployment-native/report.json
```

The harness starts real API/worker commands and lifespan plus a localhost signing OIDC server. The browser follows actual login, callback and server-session cookies; it creates a key, sends the Setup test, captures a synthetic terminal error through the real sender/API, waits for the worker, inspects unknown cost and known tokens, resolves the incident, replays the event and signs out. A second actual login checks retained state after process restart. A transport cut checks readiness 503 while liveness remains 200. No session insertion, cookie injection, API response substitution, application `.env`, external identity account or paid model call is used. Browser requests are confined to the two owned HTTP origins.

Children receive only allowlisted OS variables and synthetic explicit configuration through stdin. POSIX launchers exec the real module; Windows uses a hidden waiting child because this local Windows Store Python crashes before interpreter startup on `os.execve`. The real product command is unchanged. Reports contain fixed check labels and no secret values; screenshots are taken only after the one-time credential is dismissed. Confirm all child trees/listeners have stopped before deleting the marker-owned case databases. Uncertain child cleanup retains the database and fails the suite. Mongo server startup/shutdown remains separately operator-owned; retain cached binaries/data after stopping only the verified fixture processes.

This is **native-process acceptance**, even where CI uses Docker to supply its Mongo fixtures. It does not build/run Guardian's Docker image or establish public TLS, a customer IdP, POSIX shutdown semantics on Windows, production failover or customer activation. Current results and limits are in [VALIDATION.md](../docs/VALIDATION.md). The standard-library test command also checks inert entrypoints, environment isolation, fixture protocol/transport behavior and cleanup guards.
