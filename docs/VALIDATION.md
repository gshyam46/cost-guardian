# Sillage: validation record

## OpenTelemetry and OpenInference: 2026-09-14

ADR-51 and [OPENTELEMETRY.md](OPENTELEMETRY.md) were recorded before implementation. The **0.2.0** wheel is `sillage_observe-0.2.0-py3-none-any.whl`, SHA256 **`23fd488393366ad0044eab68bed633a89c41b7029f8d4928c8ea2bf5db240ab9`**. The package suite passed **67 tests**: 23 processor, 16 upstream runtime and 28 native compatibility tests. These cover actual OTel providers, sampling/context preservation, private-provider ownership, strict numeric projection, ignored non-LLM/image spans, bounded context, privacy, existing instrumentor conflicts, literal CLI arguments and application behavior.

The exact wheel was installed outside the checkout and tested through an actual loopback HTTP collector, Mongo **8.0.26** and the direct worker. Four phases passed in **36.144 seconds**: programmatic OTel (4 calls), OpenAI 1.99.9 (12 calls), original Founder LiteLLM 1.80.0 (10 attempts), and LangChain Core 1.2.5 (2 LLM calls). Actual trace/span/parent IDs, concurrent agent context, existing provider/sampler/other processors, immutable replay/conflict behavior and numeric storage privacy passed. Non-LLM spans were not counted. Founder preserved five agent names and shared workflow grouping without changing its source. Report: `tools/reports/otel-installed.json`.

The OpenAI matrix was repeated with **2.54.0**, passing in **9.624 seconds**, with the same 12 captured operations and explicit upstream gaps. Four early-closed streams and one cancellation per version emitted no ended upstream span and therefore produced **no captured event**. Captured Responses operations, including a returned failure, lacked sufficient terminal attributes and remained unknown; normal Founder LiteLLM returns also remained unknown while its five thrown provider failures were errors. Complete Chat Completions had completion evidence where supplied. This is a documented capture/outcome limitation, not successful cancellation coverage. Report: `tools/reports/otel-openai2-installed.json`.

The exact same final wheel passed the existing native SDK/collector regression in **17.244 seconds**: **35 events, 230 known tokens, 9 errors, 5 interrupted outcomes kept unknown and 35 unknown costs**. Native replay/nested suppression and original Founder source integrity remained intact. Report: `tools/reports/instrumentation/report.json` (also `otel-native-regression.json`). These new reports supersede the historical 0.1.0 artifact evidence below. All provider responses were synthetic, with **zero paid model calls**. The owned test databases, Mongo listener and temporary environments were removed after verification. The final verifier-only Unicode assertion was strengthened after the run; the independent database privacy check already used unescaped canary matching and passed.

Review found an actual Python 3.11 download compatibility issue: `Path.is_junction()` exists only on newer Python. The corrected download reader retains symlink/reparse rejection through a guarded API and Windows `lstat` attributes. Its focused suite passed **53 tests, one Windows symlink-permission skip**, including missing-method and file/directory/ancestor reparse coverage (`tools/reports/integration-download-compatibility.xml`). The final complete backend suite passed **1,292 tests, two skips**. The complete final frontend passed **317 tests across 11 suites**, including visible unknown outcomes and preserved parent references; all **160 harness tests** passed. Reports: `tools/reports/experience-backend.xml`, `experience-frontend.json` and `experience-tools.txt`.

The final frontend builds from **55 allowlisted inputs**, using the existing locked dependencies with same-origin API configuration and no dotenv/source maps. Assets are **`main.02ced74a.js`** and **`main.e0f7f240.css`**, in `.cache/deployment-build-6693f8e5/frontend/build`; manifest SHA256 **`93ae0b918adddf46f57a9cb39198c5b3fbe0ee849083eeaada53a88e48670ddb`**. Offline packaging verification matches every current/staged source hash, all eleven Python wheel modules, package metadata/optional dependencies/RECORD, six manual helper modules and both Compose configurations. The exact wheel hash matches both installed acceptance reports; no metadata-only equivalence is needed for this version. Reports: `tools/reports/deployment-build.json` and `experience-packaging.json`. Docker was not started or built.

The final build passed **69 browser regression scenarios** (`tools/reports/browser-otel/report.json`) and **all eight native deployment phases in 55.790 seconds** (`tools/reports/experience-native/report.json`, completed 2026-09-14 06:09:12 UTC). The latter used actual signed localhost OIDC authorization/callback/session flows, production entrypoints, a separate worker and owned Mongo fixtures. It verified public landing/demo isolation, responsive Overview/run views, standards/native onboarding choices, authenticated exact-byte 0.2.0 downloads, receipt/test separation, real numeric intake through a resolved incident, replay, logout, restart persistence and database outage readiness recovery. No private API requests came from the public demo. Zero external browser requests and paid model calls occurred; cleanup completed. The desktop landing screenshot was also visually inspected.

Source syntax, Markdown links/fences, whitespace and workflow lint passed: **161 Python files, 36 active Markdown files and 480 local links** at the integrity snapshot (`tools/reports/deployment-integrity.json`). The review found no real credentials in the intended changed source. Local caches, generated wheels/builds, reports and unrelated obsolete root frontend build assets are excluded from the repository change set. Generated Windows cache databases discovered during the final staging review were removed from the index and specifically ignored. The founder's query text is retained with only trailing whitespace removed.

The local Sillage preview was refreshed on **2026-09-14 06:11:32 UTC** to this final build and the 0.2.0 download route: `http://127.0.0.1:8001/welcome`. The helper verified and replaced only the existing owned API process; Mongo, the identity fixture, worker and `guardian_preview_mvp2` data were retained. Refresh evidence: ignored `.cache/preview/experience-20260914T061100Z-c59c92d2/refresh.json`. Original Founder Path remains on `http://127.0.0.1:3002` with its earlier native 0.1.0 launcher runtime; it was not migrated to OpenInference or used for paid model calls during this slice. The current 0.2.0 Founder proof uses its original source with synthetic SDK transport in a separate temporary environment.

CI now builds the versioned wheel for authenticated downloads, runs the package compatibility matrix, and exercises installed native/OpenInference capture in separate SDK environments against the job-owned Mongo replica. Workflow lint and fresh dependency resolution passed locally; GitHub execution remains separate evidence. This does not establish PyPI publication, full OTLP/RAG capture, real customer activation, image execution or deployed TLS/identity-provider operation.

## Historical installable Python instrumentation: 2026-09-13

The pre-code contract is [INSTRUMENTATION.md](INSTRUMENTATION.md), implemented under ADR-50. The independent package passed **28 focused tests**, including helper-source parity, configuration privacy/conflicts, import timing, nested suppression, provider behavior, stream identity, single-process arguments and local readiness. `--check` reports valid configuration separately from adapter compatibility: no compatible installed SDK returns **exit 3** and `instrumentation_ready: false`. It sends no telemetry or provider requests.

Actual installed-SDK acceptance used Python **3.13.14**, OpenAI **1.99.9**, LiteLLM **1.80.0** and an owned Mongo **8.0.26** replica set. The wheel was installed in a temporary environment outside the checkout. Tests exercised synchronous/asynchronous create and structured parse, Responses/Chat streams and managers, early closure, provider errors, cancellation, and the original Founder `LlmChat` source. Five Founder agent labels each produced a failed attempt and successful fallback with one shared run ID; nested OpenAI calls were suppressed. The real HTTP collector and direct worker processed **35 events**, with **230 known tokens**, **9 errors**, **5 interrupted outcomes kept unknown**, and **35 unknown costs**. Raw content and credentials were absent from stored data. Provider transports were owned loopback HTTP or SDK mock transports; identity for this suite was a synthetic store fixture. There were **zero paid provider calls**. The temporary environment, marker-owned database and Mongo listener were cleaned up. This is actual SDK/pipeline evidence, not external sign-in or customer activation. Report: `tools/reports/instrumentation/report.json`.

The final downloadable artifact is `sillage_observe-0.1.0-py3-none-any.whl`, SHA256 **`a75974be424406aa30d8cc637cc84257162f7118e6583d050efed873f8fb540f`**. Native acceptance ran artifact `388d1d6fd2eef9f4d04433327d5c530e95d6835d52007477daf2ab4271c0abf6`; a subsequent README accuracy change altered only wheel `METADATA` and `RECORD`. All twelve other entries, including every executable module and console entry point, are identical. The final artifact was freshly installed and passed CLI checks again. The report records both hashes, entry comparisons and the metadata-only distinction. The served copy is under ignored `packages/sillage-python/dist/`.

The complete backend suite passed **1,284 tests with two skips**; the complete final frontend suite passed **299 tests across 11 suites**. These cover the authenticated, bounded wheel route, existing access/capture behavior, the new default launcher journey, literal shell templates, accessible controls, clipboard errors/stale completion and one-time key isolation. Reports: `tools/reports/experience-backend.xml`/`.txt` and `experience-frontend.json`/`.txt`. The installed-instrumentation harness adds four safe-default/argument/environment tests; no-argument help performs no app imports or network activity.

The current production UI is built from **55 allowlisted source inputs** with existing locked dependencies, relative API configuration and no dotenv/source maps. Its assets are **`main.6698e607.js`** and **`main.c833af5e.css`**, under `.cache/deployment-build-2c2a7a44/frontend/build`. The manifest SHA256 is `f73dba0fb304bba319e20480bffba20b734e197a958d5a238f317a74cc40b1fb`. Current source/artifact hashes are recorded in `tools/reports/deployment-build.json`.

The final build passed **69 browser regression scenarios** (`tools/reports/browser-instrumentation/report.json`). The new cases verify default launcher selection, configured API origin, PowerShell/Bash and script/Uvicorn commands, separate compatibility checking, credential-free templates, exact wheel bytes and mobile layout. Browser testing corrected ambiguous selector labels and a synthetic server's attachment re-request falling back to HTML. The actual backend attachment is independently checked below. The mobile installer screenshot was visually reviewed.

The complete **eight-phase native journey passed in 51.562 seconds**, finished **2026-09-12 21:46:00 UTC**. It used actual signed local OIDC, real browser sessions, native API/worker roles and owned Mongo fixtures; no session injection or private API interception. The authenticated package response and clicked download matched the final wheel exactly, with no-store headers and the configured origin; anonymous download was denied. Existing manual archives, real key/test separation, synthetic call processing, run/incident/resolve/replay, logout, controlled restart and database-outage/readiness recovery passed. The test's single synthetic production event remained one call, ten tokens, one error, unknown cost and measured zero duration. All marker-owned databases and Mongo listeners were cleaned. Report: `tools/reports/experience-native/report.json`.

The complete standard-library harness suite passed **155 tests in 59.885 seconds**, including the new installed-package safe-default checks (`tools/reports/experience-tools.txt`). Offline packaging verified all 55 current/staged frontend hashes, six manual helper inputs, nine wheel Python entries, metadata/RECORD and the console entry point. Both placeholder Compose configurations rendered with Compose 5.0.1. `tools/reports/experience-packaging.json` explicitly records that **no Docker engine was started and no image was built**.

Sillage's existing preview database, worker and identity fixture were preserved while replacing only the verified API process. It now serves this build at `http://127.0.0.1:8001/welcome` and `/setup`. Original Founder Path runs at `http://127.0.0.1:3002`, with a healthy original backend on port 8002 and its unchanged `founder_preview_mvp2` database. The final wheel was installed in the Founder's existing environment and all installed module bytes were checked. A seven-day application key was issued through actual preview-owner OIDC; the original backend now starts through `python -m sillage_observe -- python -m uvicorn server:app ...`, with both SDKs locally supported. The token was passed only through memory/stdin/environment; unsuccessful setup-attempt keys were revoked. No Founder source files were instrumented or synthetic calls inserted into preview data. Capture counts remained unchanged. Evidence: ignored `.cache/preview/founder-instrumentation.json` and `.cache/preview/founder-instrumented-92e7e4f6/restart.json`.

**Ready to capture is not verified real traffic.** Founder still needs its existing external Emergent sign-in and model-provider credentials for a real end-user analysis. Its Langfuse credentials are absent; Sillage's preview is direct mode. The package is not published to PyPI, broader SDK versions and subprocess/Node automatic capture remain outside the matrix, live exporter counters are not yet surfaced, full RAG/OTLP is not implemented, and container/TLS/customer activation gates remain open. The earlier experience slice below is historical evidence; reports with reused names contain the latest run.

The final read-only check of the refreshed preview passed normal OIDC login, default launcher visibility, explicit direct source, current API origin and authenticated wheel download with the final hash. Founder UI/API and its instrumented process remained healthy. Desktop/mobile installer viewports were visually reviewed, with no page errors, new ingestion keys or provider requests. Report: `tools/reports/instrumentation-preview.json`. Final artifact checks found no issues across 154 Python files, 35 active Markdown files, 454 local links and Git whitespace (`tools/reports/deployment-integrity.json`).

## Product experience and Sillage rename: 2026-09-13

This continuation implements [query.md](query.md), the pre-code [experience contract](EXPERIENCE.md), and the founder-selected [Sillage name](BRAND.md) on `mvp2.0` after commit `11a9e535`. Internal configuration, API paths, stored identities and helper imports remain compatible. Earlier evidence below describes preceding slices, not this changed frontend.

The full backend suite passed **1,259 tests with two Windows/platform skips in 18.87 seconds**. The 2,620 warnings are the existing mongomock UTC deprecation. This includes protected helper archive reads, authentication before file access, fixed language/file allowlists, exact content and bounded failure behavior, plus public static route boundaries. Reports: `tools/reports/experience-backend.xml` and `experience-backend.txt`.

The full frontend suite passed **291 tests across 10 suites in 7.076 seconds**. Tests cover public pages without private/auth requests or credential mutation, meaningful demo interactions, existing sign-in and CSRF/stale-response boundaries, guided connection states, helper origins including supported separate localhost ports, source/accounting independence, and known failed/zero-duration rendering. Windows staged CRA/Jest needs the explicit test glob `--testMatch=**/*.test.js` because its generated absolute glob mixes path separators; no tests are skipped through a pass-with-no-tests flag. Reports: `tools/reports/experience-frontend.json` and `.txt`.

The production frontend was built from **53 allowlisted inputs**, existing locked dependencies and the explicit same-origin/no-dotenv/no-source-map build settings. Final assets are `main.41a1e6b8.js` and `main.c447d394.css`, with manifest SHA256 `c16246b88122788011c31651d7abf39a974e120884540a87549e23ae0710f0e2`. The build lives at `.cache/deployment-build-05742e99/frontend/build`; current input hashes and flags are recorded in `tools/reports/deployment-build.json`.

Actual native acceptance passed **all eight phases in 42.198 seconds**, finished **2026-09-12 20:23:27 UTC** (2026-09-13 locally). `tools/reports/experience-native/report.json` records real application commands, Mongo 8.0.26, Edge 152.0.4191.66 and signed local OIDC. Public landing/demo worked at desktop/mobile widths, three run selections/filter/call inspection/demo resolution made **zero private API requests**, and authenticated Overview-to-demo navigation retained the real session when returning. The sign-in route and Connect action restored Connections through genuine browser login; no session insertion, cookie injection or private API replacement was used.

Both clicked helper downloads returned the expected `sillage-python.zip`/`sillage-node.zip` attachments with no-store headers, the exact three shipped source modules and README. The fixture verifies response headers through the existing authenticated browser context and reconciles downloaded bytes; it does not assume Chromium emits a page-response event for attachment navigation. The real journey then created an app key, verified a test excluded from production data, sent one synthetic error through actual intake/worker processing and showed **one call, ten tokens, one error and unknown cost** in Overview. The run retained measured **0 ms**. Resolution, replay, logout, API/worker restart, Mongo transport failure/readiness 503 and recovery all passed. New marker-owned fixture databases and Mongo processes on ports 27021/27022 were cleaned; the user's preview database was untouched. Paid provider calls and external requests were zero.

The same final build passed **67 production-browser regression scenarios**, retaining access/role/CSRF/expiry, credential, source/unknown-data, policy and notification checks (`tools/reports/browser-experience/report.json`). This found and corrected the mobile layout hiding the signed-in member and project; both are now visible, and mobile call rows wrap so names and measurements remain readable. Desktop landing/Overview and mobile demo/run screenshots were visually reviewed.

Offline packaging checks passed for both base and notification Compose configurations (Compose 5.0.1). All 53 staged source hashes and build flags match current source; the Docker allowlist/COPY rules ship exactly six helper modules to the configured integration directory. `tools/reports/experience-packaging.json` records current proof without claiming a Docker engine startup or image build. The full standard-library harness suite passed **151 tests in 59.662 seconds** (`tools/reports/experience-tools.txt`). Artifact checks found no issues across Python syntax, active Markdown fences/local links and Git whitespace; unchanged workflows also pass the existing linter (`tools/reports/deployment-integrity.json`).

The user's existing preview was refreshed at **2026-09-12 20:26:08 UTC** with this verified build. `/welcome` and `/demo` return 200 with the Sillage title and current JS/CSS filenames; `/api/health` and `/api/ready` report healthy/ready. The browser was opened at `http://127.0.0.1:8001/welcome`. Only the verified API processes were replaced. Mongo, the signing local identity fixture, the worker, existing sessions and the `guardian_preview_mvp2` database remain in place; no bootstrap, new sample insertion or database reset was performed. The preview project display name is Sillage Preview while its stored identity binding stays unchanged. The local refresh record is `.cache/preview/experience-20260912T202534Z-e5c1f2db/refresh.json`.

Local synthetic acceptance does not establish self-service registration, managed provisioning, full RAG capture, real customer activation, Docker image execution or deployed TLS/IdP operation; those remain explicit release gaps. The public demo uses browser-only illustrative measurements, and its local resolution action never changes the real preview workspace.

## Earlier deployment evidence

Updated 2026-09-12 (local date), changes based on application commit `a66caf7`. Current implementation evidence appears first; earlier slices and the initial documentation-only review are retained below. Report timestamps are UTC. This is not a release certificate.

## Direct/OIDC deployment and actual onboarding: current evidence

[DEPLOYMENT.md](DEPLOYMENT.md) and ADR-47 recorded the contract before implementation. The package adds bounded secret-file configuration, inert/offline CLI checks, transactional bootstrap, independent API/worker/notification roles, read-only readiness, constrained same-origin static serving and [operator commands](../deploy/guardian/README.md). It retains one isolated direct/OIDC project with an external database, identity provider and TLS ingress.

The complete backend suite passed **1,230 tests, one skip in 52.39 seconds**, including 50 new runtime/configuration/bootstrap tests and 45 static-boundary tests. The skip requires real symlink creation privileges unavailable to this Windows process; the forced symlink-guard regression passed. The 2,566 warnings are the existing mongomock `datetime.utcnow` deprecation, including two from the new tests. `tools/reports/deployment-backend.xml` records 1,231 collected cases, zero failures/errors and the skip. Tests cover offline help/check behavior, secret bounds/conflicts and fixed errors, Mongo TLS/auth/option validation, initialized-binding readiness, bootstrap refusal/replay, cancellation, exact UI/API routing, cache policy, traversal and invalid build artifacts.

An isolated source stage built successfully with Node **24.20.0** and the existing locked frontend dependencies. Only 50 allowlisted source/config/package inputs were copied; no application `.env`, development plugin or secret was included. Seven explicit build flags select relative same-origin API, production/CI, no source maps and disabled visual-edit/health/hot-reload hooks. The resulting JavaScript is **`main.4d62c32f.js` (152.14 kB gzip)** and CSS **`main.0bf8fa0a.css` (5.52 kB gzip)**. The production static loader accepts this actual manifest/build. `tools/reports/deployment-build.json` records input hashes, flags and output paths. The existing Node `fs.F_OK` tooling deprecation is unrelated to application behavior. Frontend source did not change, so the preceding 260 frontend assertions remain prior-slice evidence rather than a new run.

Docker Compose **5.0.1** validated both the base three-role package and merged four-role notification package offline. Structural checks confirm consistent settings/secret mounts, successful-bootstrap dependencies, only API publication on host loopback, read-only runtime filesystems, dropped capabilities and a 60-second supervisor grace. All 50 staged input hashes and seven build flags match the Docker build recipe. `tools/reports/deployment-packaging.json`, checked **2026-09-12 10:52:05 UTC**, records these checks and registry-verified pinned Node **24.21.0** / Python **3.13.15** base-image manifests. Manifest availability and Compose validation do not establish a successful image build. **The Docker engine remained stopped; no application image was built or run locally.** Linux installation, runtime UID 10001 secret-file access and actual container startup/shutdown remain separate checks.

The actual native acceptance suite passed **all eight phases in 53.858 seconds**, finished **2026-09-12 13:51:17 UTC**. `tools/reports/deployment-native/report.json` records actual deployment commands/lifespan, a separate worker process, Mongo **8.0.26**, Edge **152.0.4191.66** and a signing localhost OIDC HTTP fixture. The browser completed two real authorization/callback/session flows, including a fresh login after restart: two approvals, token exchanges and JWKS requests, with four discovery reads. No session insertion, cookie injection or substituted API response was used. Browser requests stayed on the two owned origins. The frontend manifest SHA256 is `8d5371d60c94bfbe9e08a46f44bfec94c522da44a0a556d554b43dcdb4e349e4`.

The verified journey restored `/setup` after login, confirmed the owner and HttpOnly session, created a write-only key, and sent an actual test receipt with zero production metrics. One synthetic terminal error then traversed the real sender/API/worker path, producing one call with **8 input, 2 output and 10 total tokens**, unknown cost and one incident. The browser waited for committed resolution, replayed the unchanged event without duplication/reopening, opened the internal run and logged out to a confirmed 401. Separate API/worker restart preserved the call and resolution, followed by the second login/logout. Cutting the actual Mongo TCP transport produced readiness 503 while liveness stayed 200; readiness recovered after restoration. Screenshots contain the run and mobile Setup only after the one-time credential was dismissed. These synthetic production-path events are not customer traffic or paid model calls.

Database acceptance also proves standalone refusal without initialization writes, successful/repeated/concurrent bootstrap and mismatched-binding refusal without state changes. A validator on the suite-owned notification-head collection rejects a late initialization write; an actual Mongo profiler record confirms error **121**, and identity/source/ledger/policy/notification heads plus the initialization marker all remain absent. After removing only that validator, normal bootstrap succeeds. An earlier artificial pre-command commit rejection left server transaction locks because pinned PyMongo marks the local transaction committed even on that error; it was replaced with the database-enforced write rejection. This suite therefore claims normal transaction rollback, not commit-ambiguity or failover certification. Existing dedicated ledger/identity commit-ambiguity results remain separate evidence.

Harness repairs preserve the real product commands: Windows uses a hidden waiting child because the local Windows Store interpreter crashed before startup on `os.execve`; only required Windows program-directory variables were added for the installed Edge lookup. Resolution now waits for its actual successful POST before asserting durable state. Cleanup fails and retains the owned database if child termination cannot be confirmed. The final native report confirms child/browser/listener cleanup and removal of its marker-owned case database. Windows verification uses owned process-tree termination and does not claim POSIX signal behavior. Native evidence does not establish public TLS, an actual customer IdP, a real provider call, live Slack or customer activation. Hosted workflows, multi-node recovery, load, backup/restore, retention/offboarding and the other [launch gates](LAUNCH.md) remain open.

Both final screenshots were physically reviewed: the desktop run and mobile capture card are readable, with separate test/real receipts, accepted/processed counts and no exposed key. A narrow existing display defect remains tracked in [PLAN.md](PLAN.md): a zero-duration error call gets a full-width minimum timeline bar, and the run view hides its known duration. The stored token/cost/duration accounting remains unchanged. No UI source change was made in this deployment slice.

`tools/reports/deployment-native/runtime-inputs.json` records hashes for 70 runtime inputs and the actual Python **3.13.14**, Uvicorn **0.25.0**, PyMongo **4.5.0**, Motor **3.3.1**, Authlib **1.8.0**, HTTPX2 **2.12.0** and JOSE RFC **1.7.5** versions. These native versions are distinct from the unbuilt image base tags above. Both owned Mongo servers were shut down after executable/data-path/role verification: replica PID **29892** on **27019** and standalone PID **26392** on **27020** are absent, as are their listeners. No test databases or active failpoints remained. `.cache/mongodb/deployment-15f8258a/{replica,standalone}/instance.json` records shutdown; cached binaries and data were retained.

The final sequential standard-library suite passed **151 tests in 61.363 seconds**, including nine deployment-fixture/entrypoint/environment/cleanup checks and the existing exporter/provider harness assertions. `tools/reports/deployment-stdlib.txt` and `deployment-stdlib.json` record the output and explicit child exit code zero. Reproduce with `python -S -m unittest discover -s tools/tests -v`. Python AST, active Markdown links/fences, new-source whitespace and tracked diff checks pass; actionlint **1.7.11** validates both workflows. `tools/reports/deployment-integrity.json` records the final source/document/workflow snapshot. The added `native-deployment` CI job stages the frontend cleanly and uses Docker only for its owned Mongo fixtures; hosted execution and Guardian image build/run were not performed.

## R2-02 OpenAI usage integration: earlier slice evidence

The [PROVIDERS.md](PROVIDERS.md) contract preceded code; ADR-46 records the usage and cost-provenance decision. Python sync/async and Node async helpers wrap the application's existing OpenAI Responses or single-choice Chat Completions operation, including streams. Setup provides language/API/stream recipes, with advanced raw JSON retained. No backend event schema, canonical fingerprint, application dependency or pricing migration was introduced. The source-module [integration guide](../examples/native-capture/README.md) covers setup, consumption, shutdown and real-traffic verification.

| Check | Result | Evidence boundary |
|---|---|---|
| Python adapter assertions | **25 passed**, 0.512s | Both APIs, sync/async, strict counters, safe stored fields, failure isolation, cancellation and terminal/conflicting stream snapshots; includes shared fixture subcases |
| Built-in Node adapter assertions | **44 passed**, 1.478s | Includes 21 shared usage fixtures, result/chunk/error identity, getter/proxy avoidance, terminal usage, early return, cancellation and consumer-thrown errors |
| Full standard-library verification suite | **142 passed**, 71.878s | Existing capture/export/harness regressions plus Python usage, Node adapter runner and 12 provider-harness checks; no skips; `tools/reports/tools-providers.txt` |
| Full Guardian frontend suite | **260 passed** across nine suites, 15.337s | Provider choices, safe recipe copying and existing credential/policy/notification behavior; generated Node recipes execute in tests |
| Generated recipe execution | **8 variants plus 2 async-consumer rejection cases passed** | Actual adapters with local stub clients/exporters, including Python syntax/execution and Node request options; no network |
| Guardian production build | **Passed** | Node 24.20.0/npm 11.19.0; `main.a2ad0a2e.js` 152.17 kB gzip and `main.6f24fda8.css` 5.56 kB gzip; existing `fs.F_OK` tooling deprecation only |
| Actual SDK -> HTTP intake -> Mongo pipelines | **4 passed**, 27.467s | Python OpenAI 1.99.9 sync clients and Node OpenAI 7.15.0 async clients; both APIs, JSON/fragmented SSE fixtures and real Guardian API/worker/database |
| Actual AsyncOpenAI parsing | **4 paths and 6 extra-field checks passed** | OpenAI 1.99.9/httpx 0.28.1/Pydantic 2.12.4/Python 3.13.14; MockTransport with DNS/socket guards and a recording exporter, separate from the real HTTP/Mongo pipelines |
| Production-build browser journey | **67 scenarios passed** | Edge 152.0.4191.66; final bundle above, synthetic API interception and clipboard checks; desktop/mobile screenshots inspected |

The final Mongo report is `tools/reports/mongo-providers-r202.json`, finished **2026-09-12 09:16:35 UTC**, using Mongo 8.0.26 with case cleanup complete. Each language/API pipeline retains six production observations and one separate test event from seven synthetic provider requests. Responses has 30 known total tokens, including terminal failed-response usage; Chat has 20, with its HTTP error usage unknown. All six production costs remain unknown. Each pipeline checks worker processing, numeric run evidence, one error incident, resolution, consumer mutation isolation and unchanged canonical replay after hiding a committed receipt. The replay assertion establishes stable canonical intake/accounting, not an independent raw-wire byte hash. Raw content and credential canaries are absent from persisted Guardian data. The prior exporter suite supplies separate immutable-byte retry evidence.

`tools/reports/python-async-providers.json`, finished **2026-09-12 09:16:57 UTC**, covers actual AsyncOpenAI Responses/Chat calls and streams using fragmented MockTransport bodies. It preserves result/chunk identity and stream cleanup, with 8 input/2 output/10 total tokens per completed path and unknown cost. Six additional SDK-object assertions cover valid, negative and excessive `cache_write_tokens` stored in Pydantic's extra slot. Both SDK proofs record source SHA256 values. Guardian's application requirements remain unchanged; Node's SDK is an isolated pinned development fixture, and CI installs Python's SDK in a separate constrained environment. Reproduction commands are in [tools/README.md](../tools/README.md). Hosted CI was not run.

Independent review repaired impossible subset/total relations, contradictory valid snapshots separated by invalid usage, the Python SDK's otherwise-ignored extra storage, and Node recipes with an undeclared request-options variable or unawaited consumer Promise. Measurement extraction reads only requested stored keys through builtin descriptors; it never calls model serializers or accesses response content. A valid completion can retain unknown usage; contradictory lifecycle or valid usage snapshots make the whole stream unknown. No summed cumulative snapshots or invented USD prices are introduced.

Earlier Python integration attempts exceeded the inherited 45-second whole-case deadline without a semantic assertion failure. The provider suite now explicitly allows 90 seconds for a case containing two independently 30-second-bounded SDK processes and records safe phase timings. The final four-case run completed in 27.467 seconds; no operating-system cause is claimed for the earlier delay. Independent review also replaced direct-child-only termination with owned process-tree cleanup and added synchronized real descendant-listener timeout/cancellation regressions. Child entrypoints reject external Guardian/provider origins before constructing a client. These are test-harness changes, not production timeout changes.

The final browser report is `tools/reports/browser-providers/report.json`, checked **2026-09-12 09:20:03 UTC** against the build above. Provider scenarios cover language/API/stream selection, copied code, one-time credential separation and advanced JSON, preserving existing access, capture, policy and notification journeys. The clipboard assertion normalizes Windows CRLF to LF before exact content comparison; the first attempt failed only on this platform representation. Both provider desktop/mobile screenshots were independently inspected. Browser close took several minutes after the assertions, then completed naturally with exit code zero; no forced termination occurred, and the owned Node/Edge processes and listener were absent afterward. Its cause remains unproven. API responses are synthetic (`real_services:false`), so this does not establish deployed customer onboarding.

The final combined standard-library run passed sequentially after browser/SDK work completed, including actual descendant-process timeout/cancellation cleanup. Reproduce with `python -S -m unittest discover -s tools/tests -v`; the nested Node runner contains the 44 assertions above rather than adding 44 to the Python test count. Syntax, Markdown link/fence and diff integrity checks cover the updated source/docs; actionlint 1.7.11 validates both workflows. `tools/reports/provider-integrity.json` records the source/document check counts. No hosted workflow or broader dependency audit was run.

All marker-owned case databases were removed. Mongo PID **26628** was stopped after executable/hash/data-path/listener verification; the process and port 27019 were absent afterward. `.cache/mongodb/r2-02-providers-6ffc3a77/instance.json` records successful shutdown at **2026-09-12 09:19:22 UTC**. Cached binaries and data were retained.

The previous **1,135-test backend** and **33-case ledger/capture/notification Mongo** results below remain evidence for unchanged backend source; they were not rerun in this client/frontend slice. Actual paid-provider traffic, deployed OIDC/TLS, a real Slack channel, customer activation, pricing provenance, broader providers, RAG outcomes, retention/offboarding and operating gates remain open. No complete release gate is closed by synthetic fixtures or local SDK compatibility.

## R3-03 notification delivery: historical evidence

The [NOTIFICATIONS.md](NOTIFICATIONS.md) contract preceded implementation; ADR-45 records the accepted architecture. Named owners can test and enable one operator-configured Slack destination, inspect delivery history and retry eligible terminal deliveries. New incidents and their redacted outbox jobs commit together. A separate delivery worker handles admission, receiver pacing, bounded attempts and fenced completion. Both native capture and Langfuse ledger paths retain their existing incident identity and replay behavior.

| Check | Result | Evidence boundary |
|---|---|---|
| Full Guardian backend suite | **1,135 passed**, 29.26s | Includes 63 notification API/authority/schema cases and 40 delivery/transport cases; no expected failures |
| Guardian frontend suite | **248 passed** across nine suites, 27.436s | Owner/read-only actions, uncertain command read-back, rotation recovery, active-destination retesting and independent incident history |
| Guardian production build | **Passed** | `main.89ff137c.js`, 149.24 kB gzip; `main.2d6a8613.css`, 5.54 kB gzip |
| Combined standard-library suite | **104 passed**, 66.357s | Includes five notification harness safety cases and existing exporter/harness checks |
| Real Mongo notification suite | **7 passed**, 15.684s | Actual API/worker/Mongo/local HTTP receiver journey and transaction/failure boundaries |
| Existing real Mongo ledger/capture suites | **13 + 13 passed** | New outbox hook preserves replay, ingestion, authority and atomic completion; capture suite 14.356s |
| Production-build browser checks | **65 scenarios passed** | Headless Edge 152.0.4191.66; previous 59 journeys plus six notification groups |

The seven notification cases run against one owned MongoDB **8.0.26** loopback replica member. The customer path queues a test through the actual owner API, sends it to the synthetic HTTP receiver, records acceptance, enables delivery, accepts a native error event, processes its incident/outbox, sends the incident notification, opens history/run evidence, resolves the incident and replays the source without another incident or delivery. A second test to the same active destination preserves activation; changing a destination requires fresh verification and never redirects old jobs.

Fault evidence covers incident/outbox/detector-completion rollback and later recovery, audited command rollback and concurrent revisions, both logout orderings, concurrent claims, expired workers and stale acknowledgements, disable/rotation, HTTP rate limits, body/deadline limits and redaction. A command that commits before logout may correctly return 401 during its separate authenticated read-back; durable receipt, audit, settings and outbox prove the committed result. Rejected receiver requests stop automatic sending; after fixing the receiver, an explicit owner retry starts a new bounded cycle and can succeed. Unconfirmed attempts retain their history and duplicate risk.

Transport/core tests additionally cover destination-wide `Retry-After` even with malformed receiver bodies, exact acceptance, bounded raw reads, proxy/redirect refusal, log canaries, the final retry/cycle caps and a commit acknowledgement that consumes the send lease. Such an expired admission cannot initiate HTTP. Receiver acceptance remains distinct from human acknowledgement; no live Slack message, provider call or customer traffic was used.

Reports: `tools/reports/backend-r303.xml`, `tools/reports/mongo-{ledger,capture,notifications}-r303.json`, and `tools/reports/browser-notifications/report.json`. Final notification Mongo evidence finished **2026-09-12 06:21:36 UTC**; browser evidence was checked **06:13:36 UTC**. The browser report uses synthetic API responses (`real_services: false`), independently of the actual API/Mongo/receiver harness. Mobile setup and rotation screenshots, plus desktop incident delivery history, were visually inspected; controls/evidence remained readable without clipping.

Earlier verification runs exposed two existing five-second harness deadlines during an overlapping run. Both original assertions passed in isolation and the final complete 104-test run, without relaxing them. A browser harness assertion was updated for the intentionally changed policy/notification copy. An earlier protected-request credential mismatch in an old setup scenario did not recur in the final 65-case run; no product cause was established. The final notification harness also distinguishes manual retry eligibility from automatic retry scheduling instead of treating them as the same flag.

All marker-owned case databases and local receiver/browser processes were cleaned. Owned Mongo PID **4660** was stopped after verifying its executable hash, exact data path and sole loopback listener; both process and port 27019 were absent afterward. `.cache/mongodb/r3-03-notifications-3d3d60e0/instance.json` records the stopped instance; its isolated data directory and cached binary/archive were retained. No dependency was added. Workflow syntax, Python syntax, active Markdown links/fences and whitespace checks passed. CI now includes the notification Mongo suite/artifact, but hosted CI was not run.

Deployed OIDC/TLS/Slack acceptance, process supervision and external dead-man monitoring, supported provider usage extraction, runnable customer deployment/onboarding, grouped response, workflow outcomes, retention/offboarding and operating/load evidence remain open. This completes the bounded local delivery slice; it does not certify production readiness. Next implementation stays focused on provider integration and runnable onboarding under [PLAN.md](PLAN.md).

## R3-02 customer monitoring rules: earlier slice evidence

The [POLICIES.md](POLICIES.md) contract preceded implementation. Named project owners can save absolute cost/duration limits and reported-error controls in Setup. The worker pins a validated revision at first evaluation, and incident details explain the measured value against that revision's threshold. Strict equality and unknown measurements do not trigger a configured limit. Later edits and replay cannot rescore completed history or reopen resolved findings. Local shared-key mode and other named roles can inspect rules without editing.

| Check | Result | Evidence boundary |
|---|---|---|
| Full Guardian backend suite | **1,032 passed**, 14.27s | Includes 62 policy API/authority/schema cases and independent staged-evaluation/pin regressions; no remaining expected failures |
| Guardian frontend suite | **221 passed** across eight suites, 4.395s | Owner/read-only access, validation, draft preservation, conflicts, ambiguous saves, scope changes and readable threshold evidence |
| Guardian production build | **Passed** | `main.82dd13de.js`, 144.8 kB gzip; `main.2d6a8613.css`, 5.54 kB gzip |
| Combined standard-library suite | **99 passed**, 32.113s | Includes five new policy-harness safety cases and all previous exporter/harness tests; the Node wrapper runs its 31 nested cases |
| Real Mongo monitoring-policy suite | **7 passed**, 4.977s | Actual HTTP customer path plus real revision, audit, logout and pin/save transaction races |
| Existing real Mongo ledger suite | **13 passed**, 5.085s command time | Rerun because policy pinning/staged decisions change the common ledger path |
| Existing real Mongo capture suite | **13 passed**, 7.217s | Key, receipt, quota, authority and worker-ack regressions retained |
| Existing real Mongo exporter suite | **2 passed**, 6.595s | Both languages retain immutable committed-receipt replay and reconciled accounting |
| Production-build browser checks | **59 scenarios passed** | Final bundle, headless Edge 152.0.4191.66; previous 53 scenarios plus six grouped monitoring-rule journeys |

The seven policy cases use MongoDB **8.0.26** with one owned loopback replica member, Python **3.13.14** and the existing backend environment. Their HTTP path saves revision 1, accepts **five production events and one separate test event**, creates **three cold-start findings**, opens run evidence and resolves all three. Saving revision 2 and replaying the original batch preserves the **three resolved incidents and their revision-1 evidence**. Cost equality and unknown cost produce no limit finding; `0.050000000001` exceeds an exact `0.05` limit, and duration evidence remains exactly 1,001 ms. These are synthetic application events over actual API/worker/Mongo transport, without external provider or customer traffic.

Real transactions establish one winner for concurrent saves, lost-success read-back without another revision, audit-failure rollback and both logout/save orderings. Policy pin/save ordering is tested both with an existing empty collection and during first collection creation; a catalog conflict retries to the winning committed revision. A pinned row keeps its rules through later changes, while a partially evaluated legacy row keeps initial defaults. Immediate absolute/error checks can commit when a relative baseline is unavailable/overbound; relative work remains pending.

The first integration run exposed floating-point duration noise in previously stored native measurements. The policy evaluator now derives canonical direct duration using integer time components before comparison; unknown duration stays unknown. Stored ingestion values and fingerprints remain unchanged to preserve replay compatibility. No tolerance was added to the exact integration assertion. The cost detector's known-zero baseline now reports material transitions of at least one cent; the original $2 regression assertion passed unchanged and its final expected-failure marker was removed. Previously completed cost-rule version-1 decisions remain completed.

Reports: `tools/reports/backend-r302.xml`, `tools/reports/mongo-policies-r302.json` (finished **2026-09-11 21:48:24 UTC**), and `tools/reports/mongo-{ledger,capture,exporters}-r302.json`. Run backend pytest from `apps/guardian/backend`, frontend tests/build from `apps/guardian/frontend`, and `python -S -m unittest discover -s tools/tests -v` from the root. The actual policy command is documented in [tools/README.md](../tools/README.md); it requires a separately owned test replica set. Four Mongo suites ran sequentially: **35 cases passed**, with all owned case databases/failpoints cleaned. Mongo PID **34708** was shut down after exact executable/hash/data-path/listener checks; its PID and port 27019 were absent afterward. Cached data was retained.

CI now includes the policy Mongo suite and artifact alongside the existing sequential fault suites. Hosted CI was not run. No dependency was added. Current mock-library/Node deprecation notices remain non-failing warnings. Real OIDC/TLS deployment, supported provider usage extraction, notifications, workflow outcomes, retention/offboarding, operational recovery/load and independent customer activation remain open. This feature provides usable configured incidents inside Guardian; it does not establish launch readiness or automatic spending enforcement.

Browser report: `tools/reports/browser-policies/report.json`, checked **2026-09-11 21:58:33 UTC**, matches final `main.82dd13de.js`. Six new grouped journeys cover owner editing/zero/invalid limits, preserved drafts and conflict recovery, ambiguous-save read-back, unavailable/malformed reads, role loss/read-only access, and threshold evidence through run navigation and resolution. All earlier 53 scenarios remain included. Mobile rule controls and desktop threshold evidence were visually inspected; no clipping or unreadable controls were found. The first browser attempt used stale expected notice wording; the harness text was corrected while preserving revision and draft-value assertions. Browser scenarios use synthetic API fixtures and remain distinct from the actual API/Mongo proof above. Browser/server helpers exited after the run.

Final integrity checks parsed **131 Python files**, checked **25 active Markdown files** and their local links/fences, validated the browser script syntax, passed actionlint 1.7.11 for both workflows and passed `git diff --check`. The final Mongo reports reconcile to 35 passing cases with cleanup complete. No unexpected literal Windows cache directory was present.

## R2-02 background exporters and call lifecycle (historical evidence)

The [EXPORTING.md](EXPORTING.md) contract preceded code. Python and Node now provide bounded process queues, one sender, immutable retries, prefix flush, bounded close and fixed diagnostics. Explicit call/stream helpers preserve application results, exceptions and chunk order; Python also supports async calls/streams. The API schema, backend production behavior and frontend were not changed in this slice. These are source recipes, not published SDK packages or automatic provider instrumentation.

| Check | Result | Evidence boundary |
|---|---|---|
| Full Guardian backend suite | **928 passed, 1 strict expected failure** in 28.29s | All prior assertions plus two independent Python/Node/backend wire-admission contract tests |
| Combined standard-library suite | **94 passed** in 55.116s | Includes 31 Python exporter cases, five new integration-harness boundary cases, the existing 19 manual-sender cases and one wrapper running all 31 Node exporter cases |
| Focused Node exporter suite | **31 passed** in 5.307s | Deterministic validation, capacity, retry, lifecycle and shutdown checks; repeated inside the combined suite |
| Real Mongo exporter pipelines | **2 passed** in 10.081s | Final Python and Node source hashes verified before/after actual localhost HTTP intake and Mongo processing |

Runtime versions: Python **3.13.14**, Node **24.20.0**, MongoDB **8.0.26**, Windows. No dependency was added. Focused Python checks also passed 31 cases in 3.941s. Backend report: `tools/reports/backend-exporters-r202.xml`. Final integration report: `tools/reports/mongo-exporters-r202.json`, finished **2026-09-11 20:48:08 UTC**. The combined 94 count includes the Node runner as one test; its 31 nested cases are not another 31 Python tests.

Each real integration creates one separate test event and eight production events using synthetic normal calls, streams, early close, failure and explicit retry. The first production receipt commits and its acknowledgement is deliberately hidden behind HTTP 503. The exporter retries the exact incoming request bytes and batch identity; two transport attempts leave **eight calls, $0.06 known subtotal, four unknown-cost events, ten known tokens, two errors and two incidents**. An early stream remains unknown. Caller mutation cannot replace observed zero with another value; provider results/errors retain their identity and chunks retain order. Test traffic stays outside production totals, ingestion credentials cannot read the dashboard, raw-content canaries stay out of persisted evidence, and an idle worker rerun leaves totals unchanged.

Failure coverage includes bounded admission with in-flight work counted, forbidden fields/getters/custom serialization, strict original microsecond timestamps, unchanged retry bodies, HTTP-date/delta retry floors, five-attempt/age limits, credential rejection, prefix flush with later producers, expired unsent neighbors and expiry during batch construction, cancellation, once-only completion and a real blocked receipt during forced close. Unconfirmed means no validated receipt, not proven remote loss. Python exposes an operation still running after its close deadline; Node aborts its request. Windows PID simulation verifies inherited Python instance refusal; no actual POSIX fork or process-crash durability was established.

Reproduce the backend and combined checks from the stated directories:

```powershell
# From apps/guardian/backend:
& .venv/Scripts/python.exe -m pytest tests/ -q -rx --strict-markers --junitxml=../../../tools/reports/backend-exporters-r202.xml

# From the repository root; Node must be available:
& apps/guardian/backend/.venv/Scripts/python.exe -S -m unittest discover -s tools/tests -v

# Only after starting a separately owned local test replica set:
& apps/guardian/backend/.venv/Scripts/python.exe tools/test_mongo_exporters.py --mongo-url 'mongodb://127.0.0.1:27019/?replicaSet=guardian-r102&directConnection=true' --report tools/reports/mongo-exporters-r202.json
```

The integration harness is inert without explicit arguments, passes synthetic credentials through stdin, scrubs inherited application configuration and kills/reaps timed-out children. Case databases and scoped failpoints were cleaned. The final owned Mongo process (PID 5336) was shut down after executable/hash/data-path/listener checks; its PID and port 27019 were absent afterward. Earlier owned PID 31152 was also stopped; cached data was retained. Windows Store launcher delays initially exceeded a focused smoke test's five-second startup budget; that test now uses the base interpreter and a bounded 20-second startup budget. The final combined run passed without weakening exporter assertions.

Final integrity checks parsed 120 Python files, checked 24 active Markdown files and their local links/fences, matched all six integration source hashes, passed actionlint 1.7.11 for both workflows and passed `git diff --check`. No unexpected literal Windows cache directory was present.

CI installs Node for the Python wire/runner checks and runs the actual Mongo exporter suite sequentially with the existing fault suites, saving its report. Hosted CI was not run. Frontend code was unchanged; the prior 189 tests, build and 53 browser scenarios below remain historical evidence, not reruns in this slice. The existing R3-02 zero-cost-baseline policy remains one strict expected failure. Actual provider adapters, deployed OIDC/TLS, managed provisioning, workflow/RAG outcomes, retention/deletion, notifications and independent customer activation remain open. Local process delivery does not establish launch readiness.

## R2-01/R2-02 scoped keys and native capture (historical evidence)

The contract in [CAPTURE.md](CAPTURE.md) preceded implementation. An operator-configured OIDC project can now issue expiring, revocable, write-only ingestion keys and receive allowlisted terminal-call JSON without Langfuse. Numeric events enter a durable inbox, then the existing leased ledger, metrics and cost/reliability detectors. Direct live/run views contain only numeric evidence. Setup separates test receipt, real receipt, backlog and worker heartbeat; none is presented as customer activation. [ADR-41/42](DECISIONS.md) and [PLAN.md](PLAN.md) record the decision and remaining work.

| Check | Result | Evidence boundary |
|---|---|---|
| Full Guardian backend suite | **926 passed, 1 strict expected failure** in 21.90s | New credential, schema, intake, source-mode, worker and direct-read regressions plus all earlier assertions |
| Real Mongo native capture suite | **13 passed**, 11.242s | MongoDB 8.0.26, one owned loopback replica-set member; actual authority/transaction faults and localhost HTTP |
| Existing real Mongo ledger suite | **13 passed**, 7.272s command time | Rerun because source-mode claims now fence ledger transactions; replay, recovery and lease checks retained |
| Existing actual localhost HTTP smoke | **Passed** | Explicit legacy/Langfuse mode, nine auth denials, seven calls, one incident, complete 14-day UTC summary; synthetic source/mock persistence |
| Harness and native sender tests | **57 passed** in 45.402s | Standard-library run, including 19 Python/Node sender cases over real localhost HTTP; no provider/customer traffic |
| Guardian frontend tests | **189 passed** across seven suites in 13.23s | Mode/status/key/receipt validation, authority separation, one-time secret lifecycle, stale-request recovery and prior UI regressions |
| Guardian production build | **Passed** | Final `main.56d49234.js`, 141.41 kB gzip; `main.1cea3737.css`, 5.5 kB gzip |
| Production-build browser checks | **53 scenarios passed** | Headless Edge 152.0.4191.66, final bundle, synthetic API/session fixtures; includes all earlier 41 scenarios |

Credential tests cover owner-only changes, exact Origin/CSRF, one-time display, expiry, revocation, lost-response replay and redacted audit. Intake tests reject unknown/content fields, duplicate JSON/header keys, invalid numbers/tokens/times, oversized/encoded bodies and wrong authority before body processing. Raw event values and secret canaries are absent from safe errors and persisted numeric projections. Time validation rejects submillisecond end-before-start before flooring to Mongo precision. Test-only events cannot change production totals.

Real Mongo proves credential/audit rollback, concurrent request/active-limit enforcement, preserved revoke actor/time, uncertain committed key acknowledgements, receipt/admission rollback, concurrent and cross-batch replay, quota/backpressure rollback, and revoke versus intake in both orderings. Worker acceptance and inbox acknowledgement commit or roll back together. Concurrent initial Langfuse/direct source claims produce one winner; the losing mode cannot create credentials/audit or later take over that binding. This closes the startup race identified during independent review.

The capture suite's actual HTTP case creates a key using an owner session and CSRF, rejects four wrong authorities, records a separate test handshake and queues two real numeric events while the worker is stopped. Processing then yields **two calls, $0.03 and one incident**, with internal run evidence and no Langfuse client constructed. These are synthetic events over real API/localhost/Mongo transport. The identity provider is not involved, so this does not establish real sign-in, deployed TLS, provider instrumentation or a customer outcome.

Backend report: `tools/reports/backend-r202.xml`. Database reports: `tools/reports/mongo-capture-r202.json` (finished 2026-09-11 19:59:34 UTC) and `tools/reports/mongo-ledger-r202.json` (20:04:45 UTC). Legacy smoke: `tools/reports/offline-r202.json`. Reproduce with the commands in [tools/README.md](../tools/README.md), using the existing isolated backend interpreter and separately started owned test replica set. Run fault suites sequentially.

The dependency-free [Python/Node senders](../examples/native-capture/README.md) retain request bytes/IDs across retries, reject redirects, validate receipt identity/counts and return safe diagnostics. Tests cover explicit offline help, machine headers without dashboard authority, untrusted/oversized/contradictory receipts, duplicate/conflict counts and Retry-After guidance without immediate retry storms. They require an application's existing background queue; they do not guarantee delivery, shutdown flushing or provider integration. A Windows test environment initially omitted an OS variable and generated a literal cache folder in the workspace; the environment was corrected and generated caches retained under ignored `.cache`. The final run created no replacement cache.

Browser report: `tools/reports/browser-capture/report.json`, checked 2026-09-11 20:11:36 UTC, matches the final build manifest. The twelve new scenarios exercise owner creation, one-time display/dismissal, test requests without dashboard cookies, failed revoke/retry, lost-create recovery, secret clearing on focus, viewer access, backlog/stale worker, receipt versus processing, unavailable state and direct source captions. Mobile owner/pending layouts were visually checked for readable controls and overflow. Independent review also added regressions for unknown mode incorrectly showing Langfuse setup, contradictory test receipts and active metadata containing a revocation timestamp. A synthetic browser result is separate from actual API/Mongo HTTP proof and unperformed deployed provider/TLS acceptance.

The owned Mongo process was shut down after executable/data-path/listener validation; clean exit, PID 30360 absence and port 27019 release were verified. Owned case databases and scoped failpoints were cleaned up, with local instance data retained. Browser/server and test/build helpers exited. Final integrity checks parsed 113 Python files, checked 23 active Markdown files and their local links/fences, passed actionlint 1.7.11 for both workflows and passed `git diff --check`. The CI Mongo job now includes the capture suite; hosted workflows were not run. Local sender checks used Python 3.13.14 and Node 24.20.0. Existing Mongo-mock/Node deprecation notices do not constitute failing checks.

The unchanged strict expected failure is R3-02's zero-cost-baseline policy. One earlier long concurrent test run let a real test lease expire and failed an old v2 request-count assertion; the original test passed in isolation and in the final full suite without relaxing its assertion. This does not replace production load/lease validation. No new dependency was added. Hosted CI, real OIDC/TLS, provider/framework integration, automatic instrumentation, OTLP/backing provisioning, retention/offboarding, notification delivery and real customer activation remain open. R2 remains in progress.

## R2-01 named access for an isolated project (historical evidence)

The contract in [IDENTITY.md](IDENTITY.md) preceded implementation. Opt-in OIDC adds signed identity verification, opaque server sessions, configured owner/operator/viewer membership, a fixed organization/project/environment/connection/issuer/client binding, exact Origin/CSRF protection and transactional incident-resolution audit. Legacy API-key mode remains compatible. The browser loads auth configuration first, ignores saved keys in OIDC mode and keeps actor/project/permissions/CSRF in memory. Named access does not provision telemetry or complete the no-observability onboarding journey.

| Check | Result | Evidence boundary |
|---|---|---|
| Full Guardian backend suite | **772 passed, 1 strict expected failure** in 10.50s | Existing regressions plus provider, configuration, logging, route/session/role and audit acceptance; synthetic/local I/O |
| Real Mongo identity suite | **8 passed**, 4.177s command time | MongoDB 8.0.26, one owned loopback replica-set member; real transactions, command monitoring and scoped faults |
| Harness isolation/preflight tests | **38 passed** in 13.002s | Standard-library-only run; explicit legacy mode strips inherited OIDC settings and secrets |
| Actual localhost HTTP smoke | **Passed** | Nine auth denials, legacy access contract, seven calls, one incident and complete 14-day UTC summary; real worker/API, synthetic source and mock persistence |
| Guardian frontend tests | **150 passed** across six suites | Mode bootstrap, cookies/CSRF, strict identity validation, viewer controls, logout retry, cross-tab/session races and prior access/setup regressions |
| Guardian production build | **Passed** | `main.505a4c9a.js`, 135.35 kB gzip; `main.73517333.css`, 5.45 kB gzip |
| Production-build browser checks | **41 scenarios passed** | Headless Edge 152.0.4191.66, final bundle; synthetic API responses and HttpOnly cookie fixture |
| Dependency consistency | **Passed** | `pip check`; Authlib 1.8.0/HTTPX2 installed and constrained separately from existing telemetry HTTPX 0.28.1 |

The remaining strict expected failure is unchanged: R3-02 zero-cost-baseline policy suppresses a material spend event. Identity work neither weakens that assertion nor marks the policy complete.

Provider tests use actual RSA signatures and controlled HTTPX2 transport. They exercise code/PKCE exchange, issuer/audience/authorized-party/nonce validation (including `nonce_supported:false`), typed expiry/issuance checks, rejected algorithms/signatures, current JWKS keys, bounded bodies/deadlines and safe logs. Configuration and formatter tests cover invalid/oversized/nested membership, URL boundaries, exact duplicate/Unicode mutation headers, production/development cookie options and callback-query redaction, including slash redirects, encoded paths and literal apostrophes. No external identity account was contacted.

Real Mongo verifies sixteen concurrent state consumers produce one winner; conflicting project bindings cannot both succeed; an audit-insert failure rolls back resolution; twelve concurrent resolutions preserve one timestamp/audit; logout and resolution serialize in both orderings; failed old-session revocation rolls back replacement-session insertion; and an uncertain committed acknowledgement retries commit without rerunning the action. Command monitoring confirms majority acknowledgement for state consumption and logout while retaining no query/token values. Reports record successful owned database/failpoint cleanup. The owned Mongo process was stopped after executable/data-path checks; its process and port 27019 listener were verified absent, with cached data retained. These are local single-node results, not a production failover drill.

Browser evidence adds config failure, OIDC entry without key reads, viewer/operator flows, valid CSRF/Origin, logout failure/retry, session expiry/unavailability, invalid role/permission response, failed callback and cross-tab logout to the previous 29 scenarios. Component/service tests also cover retrying logout after the browser's session/CSRF changes, preserving a safe deep link on failed sign-in and preventing focus from silently reopening an old session after failed sign-in. Final operator/viewer/entry/logout-failure mobile screenshots were inspected; the incident title/actions now fit at 390px without horizontal overflow. This browser harness intercepts API calls; it does not establish actual IdP registration, backend/provider/browser integration over deployed TLS, or a customer activation result.

Reports: `tools/reports/backend-r201.xml`, `tools/reports/mongo-identity-r201.json` (finished 2026-09-11 08:06:42 UTC), `tools/reports/offline-r201.json` (08:12:34 UTC) and `tools/reports/browser-r201/report.json` (08:16:27 UTC). The older R2-03 browser assertion discussed below remains historical, non-reproduced evidence; its diagnostic cause has not been retroactively assigned. This slice adds new checks without relaxing authentication assertions.

Reproduce using the installed isolated environments; the Mongo command requires a separately started owned local replica set as described in [tools/README.md](../tools/README.md):

```powershell
Push-Location apps/guardian/backend
.\.venv\Scripts\python.exe -m pytest tests/ -q -rx --strict-markers --junitxml=../../../tools/reports/backend-r201.xml
.\.venv\Scripts\python.exe -m pip check
Pop-Location
& apps/guardian/backend/.venv/Scripts/python.exe -S -m unittest discover -s tools/tests -v
& apps/guardian/backend/.venv/Scripts/python.exe tools/test_mongo_identity.py --mongo-url 'mongodb://127.0.0.1:27019/?replicaSet=guardian-r102&directConnection=true'
& apps/guardian/backend/.venv/Scripts/python.exe tools/verify_mvp.py offline --guardian-python apps/guardian/backend/.venv/Scripts/python.exe --report tools/reports/offline-r201.json
Push-Location apps/guardian/frontend
$env:CI = "true"
npm.cmd test -- --watchAll=false --runInBand
npm.cmd run build
Pop-Location
node tools/browser_smoke.cjs --playwright .cache/browser-check/node_modules/playwright
```

Final integrity checks parsed 96 repository Python files and verified active Markdown links/fences. Cached actionlint 1.7.11 accepted both workflows, and `git diff --check` passed. Existing Node `fs.F_OK` and Mongo-mock `datetime.utcnow` deprecation warnings remain. The CI Mongo job now includes the identity suite; hosted CI has not been run. API/UI deployment, real IdP registration and TLS callbacks, member/session administration, scoped ingestion credentials, managed capture, privacy/retention and real customer activation remain open. Existing ledger and summary fault results below are historical and were not rerun for this identity slice. R2 remains in progress.

## R2-03 access/setup prerequisite (historical evidence)

The contract in [ACCESS.md](ACCESS.md) preceded implementation. The new `/api/guardian/access` endpoint verifies the existing shared credential independently of summaries, database queries/indexes and telemetry. It returns a fixed single-project permission description, with noncacheable success and authentication errors. A malformed presented credential cannot turn a rejected key into a server error. This is a repair to the current development access mode; named identity, project provisioning and managed capture remain unfinished.

| Check | Result | Evidence boundary |
|---|---|---|
| Full Guardian backend suite | **519 passed, 1 strict expected failure** in 13.30s | Includes 20 new access cases; no external source/provider traffic |
| Access endpoint cases | **20 passed**, included above | Real ASGI routing/header parsing; database/source/cache sentinels fail if touched; header/Bearer precedence, malformed headers, safe missing configuration, noncacheable responses and independence from summary503 |
| Harness isolation/preflight tests | **38 passed** in 14.868s | Standard-library-only run (`-S`); rejects failed/malformed access and an accidentally unauthenticated endpoint |
| Actual localhost HTTP smoke | **Passed** | Nine auth denials, explicit shared-key access, seven captured calls, one incident and a complete 14-day UTC summary; real worker/API with synthetic source and mock persistence |
| Guardian frontend tests | **92 passed** across six suites in 3.65s | Final rerun includes mobile header and first-setup state corrections, candidate/stored access gates, real Axios interceptors, credential races, storage failures, deep links, setup states and incident-detail recovery |
| Guardian production build | **Passed** | `main.fe4e3dd1.js`, 132.82 kB gzip; `main.af505236.css`, 5.44 kB gzip |
| Production-build browser checks | **29 scenarios passed** | Headless Edge 152.0.4191.66, normal and slower walkthroughs against the final bundle; synthetic API transport with strict auth assertions |

Reports: `tools/reports/backend-r203.xml` and `tools/reports/offline-r203.json` (finished 2026-09-11 06:42:20 UTC). The remaining expected failure is the unchanged R3-02 zero-cost-baseline policy gap. This slice does not change ledger writes, summary aggregation or database schema; the 18 real Mongo checks from R1-03 below are historical database evidence and were not rerun for the auth-only endpoint.

Browser credentials remain in memory until the access-only response is validated; protected pages mount only after restored access is checked. Tests verify rejected-candidate nonpersistence, startup401 removal, transient403/503/timeout retention and retry, deep-link preservation, cross-tab changes, same-key replacement races, disconnect without reload and safe storage-failure recovery. Service tests exercise the installed Axios interceptor chain with an offline adapter and a mounted App, including a later data401 removing protected evidence while an old request cannot revoke a replacement credential.

Setup's 14 focused cases are included in the frontend total. They distinguish configuration from source/processing evidence and cover unconfigured/unchecked, empty successful reads, pending/quarantined work, stale/unavailable diagnostics, invalid response shapes, unknown values, naive timestamps and prototype-like state strings. Visual review found and corrected a first-setup warning: an unconfigured or not-yet-polled worker is not labelled stale merely because no heartbeat exists. No setup state claims managed provisioning or product activation. Incident-detail tests distinguish actual404 from403/transient errors, verify retry and prevent changed-URL reads or old resolve responses from replacing current evidence.

Browser evidence is `tools/reports/browser-r203/report.json`, checked 2026-09-11 07:23:41 UTC, for `main.fe4e3dd1.js`. It includes the preceding 14 summary/incident/live scenarios plus restored-access gating, unconfigured/unchecked/empty/pending/stale/unknown/unavailable setup, retry, disconnect without reload, rejected-candidate nonpersistence, held validation before saving, expired stored access, outage retention/retry, access during partial summaries, data401 recovery and real cross-tab disconnection. Updated mobile Setup and access-outage screenshots were inspected; the header uses a separate readable API timestamp line on narrow displays. All owned browser/server helpers were cleaned up.

One earlier browser run failed a missing-key assertion on `/access` late in the walkthrough. Its original diagnostic did not record method/scenario, so its cause remains unattributed. A small cross-origin request probe and both final normal/slower runs did not reproduce it. No authentication assertion was relaxed. The harness now records safe method/scenario diagnostics and catches route failures while preserving browser/server cleanup. Keep this as a non-reproduced harness failure for follow-up, not a confirmed application bug or a proven preflight explanation.

Integrity checks parsed 82 repository Python files, checked 20 active Markdown files and their local links/fences, and passed `git diff --check`. No dependency installation or database migration was needed. The existing Node `fs.F_OK` deprecation warning remains. Hosted CI, deployed routing, live source/exporter compatibility and real customer onboarding remain unverified. Named identity, scoped ingestion keys, provisioning, content-safe defaults and full onboarding acceptance remain open R2 gates.

Reproduce from the repository root with the existing isolated dependencies:

```powershell
Push-Location apps/guardian/backend
.\.venv\Scripts\python.exe -m pytest tests/ -q -rx --strict-markers --junitxml=../../../tools/reports/backend-r203.xml
Pop-Location
& apps/guardian/backend/.venv/Scripts/python.exe -S -m unittest discover -s tools/tests -v
& apps/guardian/backend/.venv/Scripts/python.exe tools/verify_mvp.py offline --guardian-python apps/guardian/backend/.venv/Scripts/python.exe --report tools/reports/offline-r203.json
Push-Location apps/guardian/frontend
$env:CI = "true"
npm.cmd test -- --watchAll=false --runInBand
npm.cmd run build
Pop-Location
node tools/browser_smoke.cjs --playwright .cache/browser-check/node_modules/playwright
```

## R1-03 incident summaries and read states (historical evidence)

The following records the summary slice before access/setup recovery. Current test/build/browser results appear above when verified.

The contract in [SUMMARIES.md](SUMMARIES.md) preceded implementation. Incident totals now aggregate in Mongo instead of truncating raw lists at 1,000 or 10,000 rows. One authenticated summary response combines open counts, bounded breakdowns, UTC calendar trends including today and explicit date coverage. New incident writes add a canonical BSON UTC date while preserving the public ISO field. Existing rows are not mass-rewritten. The incident screen now distinguishes successful empty results, initial failures with retry, and stale rows for the same filter.

| Check | Result | Evidence boundary |
|---|---|---|
| Full Guardian backend suite | **499 passed, 1 strict expected failure** in 9.08s | Includes 29 new summary acceptance cases; mock storage plus controlled source transport |
| Real Mongo incident summary suite | **5 passed** | MongoDB 8.0.26, one isolated replica-set member; actual date conversion, indexes, writer and scoped aggregate failure |
| Real Mongo ledger recovery suite rerun | **13 passed** | Checks new incident writes against existing transaction/replay/lease recovery contracts |
| Guardian frontend tests | **42 passed** | Summary consumption, calendar/zero chart and incident loading/error/stale/filter/retry states |
| Harness isolation/preflight tests | **35 passed** in 10.890s | Standard-library-only run (`-S`); includes summary auth/coverage/count/window checks and a midnight-crossing fixture |
| Actual localhost HTTP smoke | **Passed** | Synthetic source -> real worker/detectors/store classes with mongomock -> actual TCP API; six auth denials, seven calls and one incident reconciled into the summary |
| Guardian production build | **Passed** | `main.7e406084.js`, 128.54 kB gzip; `main.c6afa910.css`, 5.34 kB gzip |
| Production-build browser checks | **14 scenarios passed** | Headless Edge 152.0.4191.66, synthetic API transport; desktop/mobile rendering and interactions |

The one remaining expected failure is the existing R3-02 policy gap: explicitly free baseline history suppresses a material $2 call. Its assertion remains unchanged. No expected-failure marker hides a summary defect.

Summary tests verify more than 1,000 open and 10,000 dated incidents, exact category reconciliation, unknown legacy categories, UTC year/month/leap-day boundaries, inclusion of today, exclusion of future and exact-cutoff events, seven-day reconciliation and smaller requested trend windows. They also exercise safe dispatch/cursor/index errors, index-initialization retry/caching, request cancellation and bounded waits. Tests use real Mongo for legacy date operators instead of implementing a pretend aggregation engine in mocks.

The real Mongo volume fixture contains **42,077 incidents**, including **1,505 open** and **12,070 within the trend window**. Its winning query plan fetches exactly **12,075 candidate documents** and examines **13,576 index keys**, avoiding unrelated valid native history. Separate checks flag malformed or timezone-naive legacy dates and canonical fields containing arrays or unsupported years; these cannot produce a falsely complete dated summary. The real store round-trip verifies UTC/BSON serialization and rejection of naive creation times. Missing authentication is rejected before any database command, including index initialization. A scoped server error returns safe 503 responses and normal reads recover after the fault is removed. This fixture is not a supported-load benchmark.

The API's `as_of` is a millisecond UTC cutoff for dated events. Open counts reflect statuses encountered by the aggregation; this does not claim a historical status snapshot. Legacy rows still require conversion scans. Index initialization has per-command server deadlines and a shared application wait, is serialized, and is cached only after successful completion. First read after process startup requires index-creation permission; deployment preparation remains necessary.

Reports: `tools/reports/backend-r103.xml`, `tools/reports/mongo-r103.json` (finished 2026-09-11 06:17:18 UTC), `tools/reports/mongo-ledger-r103.json` (06:19:39 UTC), and `tools/reports/browser-r103/report.json` (06:11:58 UTC). Both Mongo suites report successful marker-owned database/failpoint cleanup. Browser mobile screenshots for failed reads, stale rows and partial summaries were inspected. Reports and screenshots are ignored generated artifacts; this Markdown records the verified scope.

The final offline report is `tools/reports/offline-r103.json` (finished 2026-09-11 06:24:43 UTC). It records one open/recent incident, complete date coverage and 14 UTC trend days. Authentication is checked on both the incident and summary endpoints with missing/wrong keys and the old session cookie. The full synthetic journey uses no source server or external provider; the separate real Mongo tests establish database behavior. The owned Mongo process was gracefully stopped after executable, data-path and server PID checks, and its process and listener were verified absent. Cached binaries/data were retained.

Integrity checks parsed 81 repository Python files and both CI workflow YAML files, checked 19 active Markdown files and local links with balanced fences, and passed `git diff --check`. Cached actionlint 1.7.11 passed both workflows with no diagnostics (optional ShellCheck/Pyflakes disabled). The existing Node `fs.F_OK` deprecation warning remains. No new dependency installation or Founder migration was needed. The pre-existing untracked root `frontend/` directory was untouched.

Reproduce from the repository root with the existing isolated dependencies and a separately started fresh local test replica set:

```powershell
Push-Location apps/guardian/backend
.\.venv\Scripts\python.exe -m pytest tests/ -q -rx --strict-markers --junitxml=../../../tools/reports/backend-r103.xml
Pop-Location
& apps/guardian/backend/.venv/Scripts/python.exe tools/test_mongo_summaries.py --mongo-url 'mongodb://127.0.0.1:27019/?replicaSet=guardian-r102&directConnection=true'
& apps/guardian/backend/.venv/Scripts/python.exe tools/test_mongo_ledger.py --mongo-url 'mongodb://127.0.0.1:27019/?replicaSet=guardian-r102&directConnection=true'
& apps/guardian/backend/.venv/Scripts/python.exe tools/verify_mvp.py offline --guardian-python apps/guardian/backend/.venv/Scripts/python.exe --report tools/reports/offline-r103.json
```

CI now runs the real summary suite in its isolated Mongo job and saves its JSON artifact; hosted CI has not been run in this session. Remaining R1 gates include real source/exporter compatibility, historical cutover/rollback, legacy conversion and supported-load/retention validation, the 5,000-bucket metrics limit and incident-list pagination. Managed onboarding for teams without observability, identity, credential closure and the incident-to-action workflow also remain unfinished. No production data, keys, settings or checkpoint were migrated. R1 and the product remain in progress.

## R1-02 durable ingestion (historical evidence)

The following records the ledger slice before R1-03. Its test/build counts and summary defects describe that earlier snapshot; current results appear above.

The contract in [INGESTION.md](INGESTION.md) preceded implementation. This slice adds a transaction-backed observation ledger, resumable v2 pages, durable quarantine and detector work, connection leases, rebuilt hourly totals and atomic observation-level incident identity. Initial import includes the captured 24-hour history; overlapping reads account for late observations by identity. The original late-arrival, replay and distinct-agent assertions now pass unchanged. Only the zero-cost-baseline policy assertion remains a strict expected failure under R3-02.

| Check | Result | Evidence boundary |
|---|---|---|
| Full Guardian backend suite | **470 passed, 1 strict expected failure** in 40.31s | Production logic, controlled source transport, explicitly mocked transactions |
| Real Mongo recovery suite | **13 passed** | MongoDB 8.0.26, one fresh localhost-only replica-set member; real transactions and scoped failpoints |
| Guardian frontend tests | **28 passed** | Includes ledger scope, pending processing and quarantine presentation |
| Harness isolation/preflight tests | **30 passed** | Standard-library-only suite, including transaction refusal before source/provider work |
| Guardian production build | **Passed** | `main.cba40eac.js`, 128.05 kB gzip; CSS 5.34 kB |
| Actual localhost HTTP smoke | **Passed** | Synthetic source, real worker/detectors/API, mock persistence; three auth denials, one incident and seven captured calls/$5.06 |
| Production-build browser checks | **8 scenarios passed** | Headless Edge 152.0.4191.66, synthetic API transport; desktop and mobile checks |

Real Mongo cases cover body abort, restart between ingestion and projection, concurrent replay, expired-owner fencing, conflicting copies, an already-committed transaction with an uncertain acknowledgement, transient transaction retry, page/checkpoint atomicity, incident/work atomicity and resolved replay, refusal to overwrite legacy totals, BSON aggregate overflow and known-invalid identity order. The final case runs production v2 source parsing, the worker, real Mongo and authenticated ASGI endpoints through empty → delayed observation → replay. It retains exactly one call/$0.75/20 tokens and one incident, with aligned source/processing watermarks and no pending work or cursor disclosure. Source HTTP is a controlled HTTPX transport; this is not a live Langfuse pairing.

The uncertain-commit test exposed a Motor 3.3.1 implementation problem: its transaction context manager commits outside its documented retry loop. Guardian now owns the explicit commit boundary, retries an uncertain commit on the same session/transaction, retries transient transaction bodies, and bounds retries by a monotonic deadline. The real failpoint test verifies at least two commit attempts, one callback execution and one accepted identity. No installed package was modified.

Independent review also added executable checks for stale-worker health writes, query mismatch refusing a changed source scope, known-ID quarantine before or after a valid copy, counting disputed attribution only once, and descending pages delivering a candidate before its baseline. Detection stays pending until the fixed traversal is exhausted. Existing incident evidence is marked conflicted when its measurement loses trust; replay preserves human resolution.

Reports: `tools/reports/backend-r102.xml`, `tools/reports/mongo-r102.json` (finished 2026-09-11 05:07:55 UTC), and `tools/reports/offline-r102.json`. The Mongo report records Python 3.13.14, PyMongo 4.5.0, Motor 3.3.1, each test result and successful cleanup. All random test databases and owned failpoints were cleaned. Reports are ignored generated artifacts; this Markdown record is tracked. The offline harness now accepts deterministic signal IDs and explicitly opts into mock transaction semantics. Manual live preflight checks transaction support before a paid workload and records v2 pages for reconciliation.

Browser evidence is `tools/reports/browser-r102/report.json`, finished 2026-09-11 05:11:02 UTC. The two new mobile scenarios show healthy ledger scope and pending/quarantined work, including unknown conflicted spend and no horizontal overflow. The previous six coverage/error/run scenarios also pass. The first sandboxed browser attempt timed out during navigation; the successful isolated headless run used the environment's approved execution path. Browser requests were synthetic and external destinations were blocked.

Integrity checks parsed 78 Python files, checked 17 active Markdown files and their local links, parsed the CI YAML and passed `git diff --check`. Browser mobile screenshots were inspected. The isolated Mongo process and its port were verified absent after testing; its ignored archive/data directory was retained. The pre-existing untracked root `frontend/` directory was untouched.

CI includes a separate isolated MongoDB 8.0.26 replica-set job for the same fault suite. That workflow has been written but has not been executed on hosted CI in this session.

Reproduce the database suite against a separately started, fresh local `guardian-r102` test instance with test commands enabled:

```powershell
& apps/guardian/backend/.venv/Scripts/python.exe tools/test_mongo_ledger.py --mongo-url 'mongodb://127.0.0.1:27019/?replicaSet=guardian-r102&directConnection=true'
& apps/guardian/backend/.venv/Scripts/python.exe tools/verify_mvp.py offline --guardian-python apps/guardian/backend/.venv/Scripts/python.exe --report tools/reports/offline-r102.json
```

Deployment remains blocked on broader launch work: real source/exporter delay and retention evidence, automatic historical cutover/rollback, supported-load validation and restore/failover drills, summary/trend query correctness, credential closure and the managed onboarding/customer workflow. The ledger deliberately refuses to mix old incremental totals, caps one bucket rebuild at 10,000 ledger rows and a detector baseline at 5,000 rows, and exposes pending/blocked work instead of truncated completion. No production data, keys, configuration or checkpoint was migrated. These results verify the bounded local implementation; R1 and the product are not declared launch-ready.

## R1-01 Observations v2 migration (historical evidence)

The following records the source migration before the durable ledger. Its four expected failures and lack of real Mongo evidence describe that earlier snapshot; current results are above.

The contract in [SOURCE_MIGRATION.md](SOURCE_MIGRATION.md) preceded code. Default source reads now use HTTPX Observations v2; `LANGFUSE_READ_API=v1` explicitly retains legacy compatibility. Live/run views group observations without deprecated trace-list/get requests. The shared contract, intended compatibility matrix and remaining release gates are documented; no live server/exporter pairing is declared verified.

| Check | Result | Boundary |
|---|---|---|
| Full Guardian backend suite | **352 passed, 4 strict expected failures** in 3.14s | Real application code, mocked storage/source transports; no live service |
| V2 source wire tests | **100 passed**, included above | Exact URL/auth/fields, host prefix, fixed bounds, cursors, pages, bytes, timeouts, configuration/failure semantics |
| Independent v2 worker/API integration | **19 passed**, included above | Actual v2 transport -> normalization -> worker/mock Mongo/API; no downgraded fallback, no checkpoint/write on incomplete reads |
| Legacy compatibility regressions | Passed within full suite | Explicit v1 fixtures and installed SDK2 HTTP transport; no live v3 server |
| Guardian frontend tests | **27 passed** | Observed/absent/undetermined run states, unknown amounts, page budgets and existing async/session regressions |
| Guardian production build | Passed | `main.5135b3e6.js`, 127.73 kB gzip; CSS 5.34 kB gzip |
| Browser production-build smoke | **Six scenarios passed** | Edge 152.0.4191.66, Playwright 1.63.0; desktop/mobile with synthetic API routes |
| Harness regression suite | **24 passed** in 7.045s | Includes API-mode mismatch before paid workload and source client cleanup on success/failure |
| Offline worker-to-HTTP smoke | Passed | Synthetic source -> real worker/detectors/stores with mongomock -> localhost HTTP; three auth denials, one incident, one metric call |

The four expected failures remain late-arrival loss, replay double counting, distinct-agent incident evidence loss and zero-baseline materiality policy. They were not relaxed or removed by the API migration. Source v2 cursors alone do not fix them.

Independent review found and repaired: request-count overflow from short cursor pages; generated zero aggregates hiding absent usage/cost; generic split fallback dropping invalid/custom/overflowing token buckets; contradictory cost/token totals appearing known; cursor and provider reason-phrase leakage through HTTPX logs; invalid host ports; and decompression before the byte cap. The final implementation requests identity encoding, rejects other encodings before decoding, checks deadlines per received chunk, and bounds both pages and accepted body bytes.

Present detail maps remain authoritative, including empty/partial maps. Contradictory totals become unknown and make the read partial. Fully known cost components use relative comparison tolerance `1e-12`, absolute tolerance zero; positive-versus-zero is always inconsistent. Explicit consistent zero remains a measurement. These are source consistency rules, not audited billing accuracy.

Browser checks include partial observations at desktop/mobile widths, rejected-only unknown spend, cold source failure, stale worker, complete bounded empty run and partial undetermined run. Empty-run mobile screenshots were inspected; no known-zero spend or false missing-trace claim appears. Six-scenario report: `tools/reports/browser-v2/report.json`, finished 2026-09-10 22:55:48 UTC (2026-09-11 IST). All API transport is synthetic and other destinations are blocked; no existing browser profile or customer key is used.

Final backend JUnit: `tools/reports/backend-v2.xml`, written 2026-09-10 23:00:04 UTC. Offline report: `tools/reports/offline-v2.json`, finished 2026-09-10 22:56:52 UTC. Generated reports/screenshots are ignored by Git. No dependency installation or Founder code migration was needed in this slice; older install/Founder results below remain historical evidence.

Integrity checks: 17 active Markdown files, 120 local links and balanced fences; 73 repository Python files parsed; browser harness syntax/help and `git diff --check` passed. No owned harness/browser helper process remained. The pre-existing untracked root `frontend/` directory was untouched.

Reproduce using the existing documented isolated installations:

```powershell
Push-Location apps/guardian/backend
.\.venv\Scripts\python.exe -m pytest tests/ -q -rx --strict-markers --junitxml=../../../tools/reports/backend-v2.xml
Pop-Location
.\apps\guardian\backend\.venv\Scripts\python.exe -m unittest discover -s tools/tests -v
.\apps\guardian\backend\.venv\Scripts\python.exe tools/verify_mvp.py offline --guardian-python .\apps\guardian\backend\.venv\Scripts\python.exe --report tools/reports/offline-v2.json
Push-Location apps/guardian/frontend
$env:CI = "true"
npm.cmd test -- --watchAll=false --runInBand
npm.cmd run build
Pop-Location
node tools/browser_smoke.cjs --playwright .cache/browser-check/node_modules/playwright
```

No real Langfuse/Mongo/provider workflow, hosted CI run, deployed onboarding/OAuth, load/restore drill or customer interview occurred. Founder still uses legacy SDK2 ingestion; older exporter data may be delayed beyond the manual harness's short wait. Verify actual source/exporter compatibility and implement durable reconciliation before beta. Source retention can shorten accessible history even when a query completes. Existing incremental accounting remains provisional, content previews remain an R2 privacy requirement, and no production data or checkpoint was migrated/reset.

## First R1 source/measurement slice (historical evidence)

The following is the initial shared-contract slice before the default v2 migration. Its test/build/browser counts and legacy-default statements are historical; current evidence is above.

Contract recorded in [TELEMETRY.md](TELEMETRY.md) before implementation. Source normalization/SDK traversal, worker/API/rollups and live/UI were implemented in parallel, followed by independent boundary review and integrated verification. Local platform remains CPython 3.13.14, Node 24.20.0 and npm 11.19.0 on Windows.

| Check | Result | Boundary |
|---|---|---|
| Full Guardian backend suite with strict expected failures | **214 passed, 4 xfailed** (2.99s) | Real application functions; mock Mongo and controlled source/HTTP transport |
| Original review regressions | Three repaired assertions pass; four strict expected failures remain | Source-error checkpoint, legacy token fallback and 250-row live totals fixed; late arrival, replay, distinct-agent evidence and zero-baseline policy remain |
| Installed Langfuse SDK request contract | Passed within backend suite | Actual generated legacy API path, request timeout/retry options and response mapping against `httpx.MockTransport`; no live server |
| Independent source -> worker -> store/API cases | 19 passed, included above | Partial/failed/capped/invalid reads preserve checkpoint/writes; unknown/legacy/overflow values stay explicit |
| Blocking source work/cancellation | Passed within backend suite | Event loop stays responsive; timeout/cancel retains capacity until physical thread ends; four-slot bound tested |
| Live reader/cache cases | 19 passed, included above | Pagination, source failure, unknowns, metadata overflow, monotonic expiry and wall-clock rollback |
| Worker attempt metadata | Passed within backend suite | Failed attempts do not reuse earlier read counts/timestamps; out-of-horizon checkpoint requires backfill |
| Harness process/unit suite | 22 passed (11.594s) | Existing isolation/deadline/cleanup/report checks; typed source contract integrated |
| Final offline HTTP smoke | Passed | Synthetic observations -> real worker/detectors/stores with mocked Mongo -> actual localhost HTTP; three auth denials, one incident, one metric call |
| Guardian frontend suite | **24 passed** | React/page/session components, nullable rendering, stale results, confirmed 404, cancellation and query response races; HTTP mocked |
| Guardian production build | Passed | `main.630cdd94.js` (127.45 kB gzip), `main.f29a9846.css` (5.33 kB gzip) |
| Local production-build browser check | Passed, four scenarios | Headless Edge 152.0.4191.66 through Playwright 1.63.0, desktop 1440x1050 and mobile 390x844; synthetic API transport only |

Browser scenarios: partial coverage/unknown measurements, rejected-only unknown spend, cold source failure, and stale worker status. Screenshots were inspected at desktop/mobile widths. Reports and screenshots are under ignored `tools/reports/browser-r1/`; the browser report finished 2026-09-10 22:18:59 UTC (2026-09-11 IST). No page errors were reported. This check blocks every nonlocal/nonfixture request and uses a disposable context with a synthetic key. It does not establish a customer connection, Founder OAuth, accessibility compliance or deployed routing.

Final backend JUnit: `tools/reports/backend-r1.xml`. Final offline report: `tools/reports/offline-r1.json`, finished 2026-09-10 22:22:25 UTC. Generated evidence is ignored by Git. Founder install/test/build evidence below belongs to R0-01; Founder was not changed or retested in this R1 slice.

Documentation/source integrity: 16 active Markdown files, 97 local links and balanced fences checked; 68 repository Python files parsed. Browser harness syntax/help checks and `git diff --check` passed. No owned harness/browser helper process remained. Pre-existing untracked root `frontend/` was untouched.

Reproduce from the repository root after the documented installations:

```powershell
Push-Location apps/guardian/backend
.\.venv\Scripts\python.exe -m pytest tests/ -q -rx --strict-markers --junitxml=../../../tools/reports/backend-r1.xml
Pop-Location
.\apps\guardian\backend\.venv\Scripts\python.exe -m unittest discover -s tools/tests -v
.\apps\guardian\backend\.venv\Scripts\python.exe tools/verify_mvp.py offline --guardian-python .\apps\guardian\backend\.venv\Scripts\python.exe --report tools/reports/offline-r1.json
Push-Location apps/guardian/frontend
$env:CI = "true"
npm.cmd test -- --watchAll=false --runInBand
npm.cmd run build
Pop-Location
node tools/browser_smoke.cjs --playwright .cache/browser-check/node_modules/playwright
```

Browser dependency/setup and synthetic transport limits are in [tools/README.md](../tools/README.md). New nullable API semantics require the matching frontend. No destructive data migration, cursor reset or backfill occurred; deploy neither component independently under the old numeric contract.

**Remaining gates:** supported Langfuse API migration and a real SDK/server compatibility matrix; durable pagination/quarantine, late revisions and replay reconciliation; real Mongo crash/concurrency/restore checks; incident overview/trend correctness and indexes; credential closure, hosted CI, managed onboarding, customer outcomes and launch operations. The legacy Cloud endpoints are scheduled for removal on 2026-11-16, so their replacement is R1-01/pre-beta work. [Official migration guide](https://langfuse.com/faq/all/deprecated-api-migration).

No live provider/Langfuse/Mongo service, deployed UI/OAuth journey, customer interview or release drill was performed. Passing local fixtures/browser tests does not close R1 or prove launch readiness.

## R0-01 implementation evidence (historical baseline)

The following records the baseline before R1 repairs. Its seven expected failures and four-test Guardian frontend count are historical; current results are above.

Local platform: Windows PowerShell, CPython 3.13.14, Node 24.20.0, npm 11.19.0. Both backends were installed into separate fresh `.venv` directories. Windows Store Python's venv launcher required execution outside the restricted sandbox; the same venv executables then ran successfully. This is a local environment limitation, not a product error.

| Check | Result | Boundary |
|---|---|---|
| Guardian clean requirements install and `pip check` | Passed | Existing direct pins retained; resolved transitive versions recorded in constraints |
| Founder clean install and `pip check` | Passed after fixing packaging 25/Langfuse `<25` conflict to 24.2 | No SDK/driver migration; full existing requirements retained |
| Founder standalone server/orchestrator import | Passed with dotenv disabled, no source keys, local model cost map | Imports only; no OAuth, database or model operation |
| Guardian backend suite | 86 passed, 7 strict expected failures | In-process services/mocked storage; no external source/database |
| Review cases with expected-failure handling disabled | 7 failed at intended assertions, 3 controls passed | Confirms the gaps remain real and their checks are not passing by changing expected behavior |
| Harness unit/process tests | 22 passed | Environment isolation, live gates, reports, process cleanup, deadlines and attribution |
| Offline harness | Passed | Synthetic source -> actual worker/detector/store classes with mongomock -> real localhost TCP HTTP |
| Guardian frontend clean npm install, tests, CI production build | Passed; 4 tests | Actual React/router/page components; HTTP mocked; not a real browser |
| Founder frontend clean npm install, tests, CI production build | Passed; 4 tests | Session/route gates with mocked services; live OAuth remains unverified |
| Frontend HTML inspection | React mount retained; unused injection/badge/PostHog absent in both builds | Explicit Founder OAuth integration remains |
| Workflow validation | actionlint 1.7.11 passed both workflows, no diagnostics | Structure/expressions only; optional ShellCheck/Pyflakes unavailable; no hosted job run |
| Constraint portability metadata | Requires-Python/dependency markers checked for configured matrix, passed | Does not prove target-platform wheels or runtime |

The seven strict expected failures cover source-error cursor advancement, late-event loss, replay accounting, same-trace evidence loss, token fallback, truncated live totals and the zero-cost baseline policy. Markers accept only `AssertionError`; unrelated exceptions fail the suite. An unexpected pass fails CI and must be reviewed with the corresponding product fix. No R1/R3 gap is considered fixed by these markers.

Commands, from each backend directory:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt -c requirements.constraints.txt
.\.venv\Scripts\python.exe -m pip check
```

Guardian backend tests, from `apps/guardian/backend`:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/ -q -rx --strict-markers
# Deliberately exits nonzero until the seven assigned product fixes land:
.\.venv\Scripts\python.exe -m pytest tests/test_review_regressions.py --runxfail -q --tb=short
```

Harness commands, from the repository root:

```powershell
.\apps\guardian\backend\.venv\Scripts\python.exe -m unittest discover -s tools/tests -v
.\apps\guardian\backend\.venv\Scripts\python.exe tools/verify_mvp.py offline --guardian-python .\apps\guardian\backend\.venv\Scripts\python.exe --report tools/reports/offline.json
```

Frontend commands, from each app's frontend directory:

```powershell
npm.cmd ci
$env:CI = "true"
npm.cmd test -- --watchAll=false --runInBand
npm.cmd run build
```

The offline smoke proves three auth denials (absent key, wrong key, legacy cookie) and authorized incident list/detail/metrics. Six synthetic baseline observations provide detector history; one $5 candidate is stored as one metric call and one cost incident. Synthetic labels are explicit and no production source data is used. Tests use isolated app configuration and external-network guards.

Final integrated run: backend `86 passed, 7 xfailed` (0.89s); harness `Ran 22 tests ... OK` (7.49s); offline smoke exited 0 with `auth_denials_checked=3`, `incidents_returned=1`, `metric_call_count=1`. Report at `tools/reports/offline.json`, finished 2026-09-10 21:42:32 UTC (2026-09-11 IST); backend JUnit at `tools/reports/backend.xml`. Generated reports are ignored by Git. No surviving harness child process was found after completion.

Final documentation/source check: 15 active Markdown files, 87 local links, balanced fences and 61 Python source files parsed successfully; `git diff --check` passed. Pre-existing untracked root `frontend/` was untouched, and the historical Founder Yarn lock has no content diff. This is syntax/document integrity evidence, not another runtime test.

Independent review reproduced an initial false-positive live check using unrelated worker traffic; the repaired harness captures actual worker candidates, checks intended run/agent coverage and reconciles persisted buckets. Live preflight checks source access and an empty test Guardian database before paid traffic. Reports contain fixed step names, counters and error codes; app logs, credentials and raw content are excluded. See [tools/README.md](../tools/README.md) for exact modes and failure codes, and [the workflow guide](../.github/README.md) for manual live setup.

Remaining warnings include inherited CRA dependency deprecations, npm core-js install-script notices, Node `fs.F_OK` deprecation and stale Founder Browserslist data. ESLint's direct peer conflict is fixed. These checks are not a dependency vulnerability audit; lifecycle/security review remains R0-02/R4-02.

No live provider/Langfuse/Mongo workflow, remote GitHub Actions job, deployed SPA fallback, real browser/OAuth walkthrough, concurrency/recovery/load drill, credential revocation, vulnerability audit or customer interview was completed in this slice. Constraints record resolved versions rather than package hashes; remote Python 3.11/Linux coverage awaits CI. R0 remains in progress and the product remains a prototype.

## Initial documentation-review evidence (historical)

Everything below records the checks available before R0-01 installed dependencies and added implementation. Statements about missing packages or unchanged code apply to that earlier review only.

## Environment and boundaries

- Windows PowerShell; Python 3.13.14 available through its explicit Windows Store application path; Node 24.20.0.
- Installed Pydantic 2.12.5 and python-dotenv 1.2.2 differ from repository pins. The checks are not a clean pinned-environment run.
- pytest, Motor and Langfuse packages are absent. No package installs or application dependency changes were made.
- No live Mongo/Langfuse/provider calls, customer messages, browser walkthrough, production frontend build, load/restore test, security scan or customer interview occurred.
- No secret values were read from historical commits or tested. Only credential-history metadata and existing written notes were reviewed.

## Checks performed

| Check | Result | What it proves / does not prove |
|---|---|---|
| Source/config/test/UI/harness inspection | Completed | Code-path findings; not production runtime observations |
| Existing pytest command | Could not run: `No module named pytest` | No current full-suite pass count is asserted |
| Python AST parse | 57 source files parsed | Syntax only; not import/dependency/runtime compatibility |
| Seven offline probes below | All reproduced described behavior | Defect evidence using actual functions with controlled dependencies |
| Current upstream documentation | Consulted official sources | Product overlap, API contract and maintenance guidance; not compatibility proof for this checkout |
| Git history metadata for `backend/.env` | Old file history confirmed | Does not establish current key validity/revocation |
| Markdown links/status consistency and diff whitespace | Checked after edits | Documentation integrity only; see final review status below |

The generic `python` alias first failed to launch scripts with a Windows logon-session error. The explicit executable at `C:\Users\ghg\AppData\Local\Microsoft\WindowsApps\PythonSoftwareFoundation.Python.3.13_qbz5n2kfra8p0\python.exe` ran the probes. The attempted backend-suite command was the equivalent of `python -m pytest tests/ -q`, from `apps/guardian/backend`; it exited before collection because pytest was missing.

## Offline probe details

Used standard Python, installed Pydantic, synthetic metadata and no network. Imported current source modules with a fake `config` (empty keys and `example.invalid` host), controlled source clients, the actual `InMemoryIncidentStore`, and a minimal collection implementing `$inc`/`$set`. The worker probe executed the actual AST-extracted `poll_once` function's empty-candidate path with controlled cursor storage; it did not execute the whole service or Mongo worker loop.

| Probe | Input / path | Observed result | Finding |
|---|---|---|---|
| Source failure/checkpoint | Client raises during `fetch_recent_generations`; pass returned list into `poll_once` | Fetch returned `[]`; cursor advanced | F01 |
| Late observation | Event starts before saved cursor and becomes visible later | Fails current `timestamp >= cursor` candidate filter | F01; filter proof, not a live delayed exporter |
| Replay accounting | Call `MongoMetricsStore.record` twice with identical $2 observation | `call_count=2`, cost=$4 | F02 |
| Dedup evidence | Two reliability results, different agents, same trace | One stored incident with first agent | F04 |
| Token fallback | `usageDetails={}`, `usage={input:12,output:8,total:20}` | Live `_tokens` returns total 0 | F05 |
| Live truncation | 100 returned rows plus metadata stating 250 total observations | Snapshot total=100, one upstream observation fetch, no partial flag | F03 |
| Zero baseline | Six zero-cost baseline samples and a $2 candidate | No cost detector result | F05/F11; existing policy behavior |

Actual probe output:

```text
CONFIRMED: upstream failure returned [] and poll_once advanced its cursor
CONFIRMED: subsequently delivered older-start observation fails candidate timestamp filter
CONFIRMED: replaying one $2 observation records 2 calls and $4
CONFIRMED: failures for two agents in one trace persist only one incident
CONFIRMED: live mapper empty usageDetails hides populated 20-token usage
CONFIRMED: live window reports 100 calls despite upstream metadata describing 250, no partial flag
CONFIRMED: cost detector does not fire for a $2 call against six zero-cost samples
```

Convert these into failing regression cases during R0-01, then close them with R1/R3 fixes. They do not replace real database atomicity/concurrency tests or source-adapter compatibility tests.

## Historical evidence

Earlier docs record a 2026-09-09 live demo, 83 passing tests, real incidents and browser exercises. Preserve these as historical records in [archive/2026-09-09/PROGRESS.md](archive/2026-09-09/PROGRESS.md). No safe live report artifact was available here to independently re-establish those results. The current harness has auth/import mismatches identified in F06; do not use historical success as proof that today's command works.

The controlled cost anomaly in that harness enters at the detector, bypassing Langfuse ingestion. Its API check uses in-process ASGI. Future reports must distinguish those from a real-source anomaly, external HTTP boundary and browser journey.

## Required implementation verification

1. Clean environment: locked installs, imports, existing backend tests and frontend build.
2. Adapter contract: actual supported Langfuse versions and fixtures, missing/revised prices, empty/partial/failure semantics, pagination and source delay.
3. Real Mongo replica set: unique indexes, transactions, concurrent leases, crash/replay, aggregate reconciliation and migration rollback.
4. UI/API: auth expiry/roles, setup, no-data/failure/stale states, pagination/time windows, accessibility and incident lifecycle.
5. End to end: no-telemetry and BYO setup, real SaaS/RAG/agent traffic, detection, delivery, investigation, mitigation and measured/pending recovery.
6. Operations/security: rate limits, load, retention, export/delete, key revocation, backup/restore, logging redaction and tenant boundary tests.
7. Product: labelled incident evaluation, native-alternative comparison, activation timing, costs and willingness to pay.

Detailed acceptance thresholds are in [LAUNCH.md](LAUNCH.md). No new implementation is marked complete by this review.

## Documentation verification

Completed: 13 active Markdown documents, 71 local links, 19 implementation ticket IDs, code-fence balance and seven archive notices checked. No broken active links or undefined ticket IDs were found. `git diff --check` passed. Changed tracked paths were restricted to Markdown and the historical-status notice in `docs/dashboard.html`; application code, dependencies and configuration templates remain unchanged. The pre-existing untracked root `frontend/` directory remains untouched.

Finding-to-ticket review: F01-F05 -> R1/R3; F06 -> R0-01; F07 -> R0-02; F08/F09 -> R1/R2; F10/F11 -> R3; F12/F14 -> R2 plus R1-03; F13 -> R1-03/R4-02/R5; F15 -> R4-02; F16 -> this documentation update and R0-03 customer discovery. Documenting a finding does not close its implementation ticket.
