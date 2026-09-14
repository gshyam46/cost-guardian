# Run an isolated Sillage deployment

The image builds `sillage_observe-0.2.0-py3-none-any.whl` in a separate pinned Python stage and serves it through the authenticated `/api/guardian/integrations/python.whl` route. Connections defaults to installing the wheel with its `[openinference]` extra and selecting one instrumentation layer. Those optional tracing dependencies are installed from the customer's configured Python package index; application SDKs remain customer-owned. Native compatibility and manual Python/Node archives remain available. Source checkouts must build the wheel into `packages/sillage-python/dist` using the [package build instructions](../../packages/sillage-python/README.md). An absent artifact returns a fixed unavailable response, never a package-index redirect. [OpenTelemetry contract](../../docs/OPENTELEMETRY.md).

Sillage is the product name; existing `GUARDIAN_*` settings, paths and commands remain compatible. After startup, `/welcome` and `/demo` provide a public introduction without private API requests. `/signin` and `/setup` enter the existing workspace access flow. Connections serves authenticated Python/Node helper archives using the exact source modules shipped at `/opt/guardian/integrations` (`GUARDIAN_INTEGRATIONS_DIR` in the image). These downloads contain instructions and modules, never credentials. See [experience decisions](../../docs/EXPERIENCE.md) and [the onboarding journey](../../docs/ONBOARDING.md).

This package runs the no-Langfuse path: named OIDC access, numeric direct capture, monitoring rules and incident investigation. It includes the production UI, API, ingestion worker and optional Slack worker. It requires an existing Mongo replica set and OIDC client; it does not provision those services. The implementation contract is in [DEPLOYMENT.md](../../docs/DEPLOYMENT.md), with current local evidence and outstanding release gates in [VALIDATION.md](../../docs/VALIDATION.md).

## Prepare one isolated project

1. Allocate a dedicated database on an authenticated, TLS-enabled Mongo replica set. Standalone Mongo is unsupported. The initial package supports username/password URI authentication, including SRV with TLS; X.509 and workload-identity authentication are outside this package. The application needs database read/write, collection/index creation and transactions. Use a new database or an already compatible direct/OIDC database; bootstrap refuses incompatible or legacy state.
2. Register a confidential OIDC client supporting code flow, `client_secret_basic`, S256 PKCE and RS256 ID tokens. Register exactly `https://your-guardian-host/api/guardian/auth/callback`. Obtain the exact verified issuer subject of at least one owner. See the protocol constraints in [IDENTITY.md](../../docs/IDENTITY.md).
3. Arrange a same-origin HTTPS reverse proxy to the private API listener. The UI and `/api` share the public origin. Keep forwarded-header trust empty unless the exact proxy IPs are known and the proxy overwrites supplied forwarding headers. Do not set `*` or a CIDR. See [proxy requirements](../../docs/DEPLOYMENT.md#same-origin-ui-and-proxy).
4. Copy [the public configuration template](.env.example) to a private operator file outside the checkout. Fill the public origin, issuer/client, stable organization/project/environment/connection IDs, display name and dedicated database name. Supply absolute paths to three separate secret files: Mongo URI, OIDC client secret and membership JSON. Do not put their contents in the operator env file, image arguments, shell history or frontend variables.

Membership file shape:

```json
[{"subject":"exact-verified-owner-subject","role":"owner","name":"Team owner"}]
```

The Mongo secret contains one URI with credentials, replica-set/SRV configuration and valid TLS. Secret files must be readable by container UID **10001**; file-backed Compose secrets do not automatically remap host ownership with `uid`/`gid`. Grant the required read access on individual files while keeping their parent directory private. A trailing newline is accepted. Never mount the entire operator directory. The `_FILE` names in the template are host paths; Compose maps those files to fixed `/run/secrets/...` paths inside each role.

## Build, check and start

Run from the repository root with Docker Engine and Compose available. Replace `/absolute/private/guardian.env` with the prepared operator file. Use a clean operator environment with no inherited `GUARDIAN_*` overrides: exported shell variables take precedence over `--env-file`. The explicit file avoids Compose's implicit development `.env` selection; packaged Python entrypoints separately disable dotenv loading.

```sh
docker compose --env-file /absolute/private/guardian.env -f deploy/guardian/compose.yaml config --quiet
docker compose --env-file /absolute/private/guardian.env -f deploy/guardian/compose.yaml build
docker compose --env-file /absolute/private/guardian.env -f deploy/guardian/compose.yaml run --rm --no-deps bootstrap check
docker compose --env-file /absolute/private/guardian.env -f deploy/guardian/compose.yaml up -d
docker compose --env-file /absolute/private/guardian.env -f deploy/guardian/compose.yaml ps -a
```

`check` validates configuration and static assets without contacting services. On `up`, bootstrap must exit successfully before API and worker start. It creates indexes and atomically initializes the matching deployment, source and ledger state. Repeating bootstrap is safe for the same binding; it never resets data. A failed bootstrap blocks dependent startup. Inspect the fixed failure code and the configured values privately; do not delete a binding or database to bypass the failure.

Only `127.0.0.1:8001` is published by default; `GUARDIAN_HOST_PORT` can select another host port. A host reverse proxy can connect there. A proxy in another container needs an explicitly configured private network path: its `localhost` is not the host. Do not expose the backend publicly to bypass the TLS ingress setup.

`GET /api/health` reports process liveness. `GET /api/ready` returns 200 only after bounded database/configuration/initialized-binding checks, otherwise 503. Neither endpoint proves that the worker is processing traffic. The API's Compose healthcheck uses readiness; authenticated Setup shows worker activity and backlog. Compose restarts exited runtime roles, but an unhealthy healthcheck alone does not restart a running process. Monitor both failure states.

## Verify the customer path

Open the public HTTPS `/setup` URL and sign in as the configured owner. Confirm the expected project and create an ingestion key. While the one-time key is displayed, send the labelled Setup test and confirm that it creates a test receipt with no production metrics. Copy the key before dismissing or leaving Setup, then store it in the application's server-side secret store. Switching away can trigger access revalidation and clear the one-time display/test control; the key cannot be revealed again.

Follow the Python/Node [provider integration](../../examples/native-capture/README.md), or the advanced numeric event recipe, and run an actual application operation. Check the separate real receipt and completed processing states, then inspect Live activity and the internal run. Missing usage or cost must remain unknown. Configure a duration or reported-error rule, reproduce a safe application failure in your test environment, investigate its incident and resolve it. Replaying the same unchanged event must not duplicate measurements or reopen a resolved incident. Verify logout and the viewer role on the public deployment before allowing customer access.

For Slack, supply `GUARDIAN_SLACK_WEBHOOK_URL_SECRET_FILE` and use **both** files in every Compose command:

```sh
docker compose --env-file /absolute/private/guardian.env -f deploy/guardian/compose.yaml -f deploy/guardian/compose.notifications.yaml config --quiet
docker compose --env-file /absolute/private/guardian.env -f deploy/guardian/compose.yaml -f deploy/guardian/compose.notifications.yaml up -d --force-recreate
```

The override supplies the same destination secret to all roles and starts the notification worker. In Setup, send a destination test, wait for receiver acceptance and enable delivery. A queued job alone is not acceptance. See [notification semantics and rotation](../../docs/NOTIFICATIONS.md); this local packaging work does not certify live Slack delivery.

## Stop, change configuration and recover

Use the same env/Compose arguments with `stop` to stop the package without deleting its external database. Runtime shutdown attempts cooperative cancellation for 45 seconds and resource cleanup for another five seconds; Compose enforces the 60-second process deadline. Unfinished ingestion/delivery remains durable. An unconfirmed external delivery may need operator investigation before retrying.

Use consistent configuration across roles. After an ordinary secret or membership change, stop the roles, then run `up -d --force-recreate` with the same Compose files so bootstrap and all runtime roles load the new configuration. Do not change organization/project/environment/connection/issuer/client to rotate a secret. Those fields define the stored binding; changing them requires an explicit migration or a new isolated deployment.

Before an application upgrade, record the image digest and configuration revision, take and verify a database backup, and rehearse the new image against a restored isolated database. Bootstrap is initialization, not a migration or restore tool. Restore/rollback, production load, retention and offboarding drills remain open launch gates; do not roll back to an old incremental writer against ledger data. Keep secret values out of support bundles and logs.

## Native entrypoints and evidence

For an independently supervised Python deployment, install the constrained backend requirements and prepare a separately built static directory. The Compose env template is not a native runtime environment: native commands do not load an env file, and Compose translates some file-path names. Supply the identity/project values directly through your supervisor, together with these native variables (POSIX shell example; values are placeholders):

```sh
export GUARDIAN_AUTH_MODE=oidc GUARDIAN_CAPTURE_MODE=direct
export GUARDIAN_DB_NAME=cost_guardian
export MONGO_URL_FILE=/absolute/private/mongo-url.txt
export GUARDIAN_OIDC_CLIENT_SECRET_FILE=/absolute/private/oidc-client-secret.txt
export GUARDIAN_OIDC_MEMBERS_JSON_FILE=/absolute/private/oidc-members.json
export GUARDIAN_PUBLIC_URL=https://guardian.example.com
export GUARDIAN_UI_ORIGIN=https://guardian.example.com
export GUARDIAN_OIDC_ISSUER=https://identity.example.com
export GUARDIAN_OIDC_CLIENT_ID=guardian
export GUARDIAN_ORGANIZATION_ID=example-org GUARDIAN_PROJECT_ID=example-project
export GUARDIAN_PROJECT_NAME='Example Project' GUARDIAN_ENVIRONMENT=production
export GUARDIAN_CONNECTION_ID=primary GUARDIAN_POLL_INTERVAL_SECONDS=10
export GUARDIAN_STATIC_DIR=/absolute/path/to/frontend/build
export GUARDIAN_BIND_HOST=127.0.0.1 GUARDIAN_PORT=8001
export GUARDIAN_TRUSTED_PROXY_IPS=
```

Use `MONGO_URL_FILE`, not the Compose interpolation name `GUARDIAN_MONGO_URL_SECRET_FILE`. Optional native Slack configuration is `GUARDIAN_SLACK_WEBHOOK_URL_FILE`. Do not also set a direct secret value when its `_FILE` is present. Run these commands from `apps/guardian/backend` with the configured interpreter:

```sh
python -m deployment check
python -m deployment bootstrap
python -m deployment run api
```

Run `python -m deployment run worker` in a separate supervised process, and `python -m deployment run notifications` only with its configured destination. No-argument `python -m deployment` prints help without loading application configuration. Native supervisors need their own termination deadline; cooperative Python cancellation cannot guarantee a process exit when a task ignores cancellation. Native smoke verification, Docker image build, and a real deployed TLS/IdP/customer test are distinct results in [VALIDATION.md](../../docs/VALIDATION.md).
