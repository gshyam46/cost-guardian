# Access and setup recovery contract (R2-03 prerequisite)

Recorded 2026-09-11 before implementation; updated 2026-09-12. This slice fixes entry and recovery in the existing single-project development deployment. It remains the `api_key` compatibility contract. Named OIDC sessions and roles extend it under [IDENTITY.md](IDENTITY.md). Scoped ingestion credentials and native terminal-event capture now follow [CAPTURE.md](CAPTURE.md); managed provisioning and complete activation remain open in [ONBOARDING.md](ONBOARDING.md).

## Access is independent of monitoring

Protected data routes now check the persisted source-mode binding after authentication, before using data or cached views. A database or capture-mode mismatch returns unavailable. The legacy `/access` check remains independent of Mongo; OIDC access still needs its session/identity binding. Successful access therefore remains distinct from usable capture or monitoring.

In `api_key` mode, `GET /api/guardian/access` authenticates the existing Guardian key without reading Mongo, creating indexes, reading telemetry or evaluating incident summaries. Successful access returns exactly `authenticated: true`, `auth_mode: "api_key"`, `deployment_mode: "single_project"` and `permissions: ["read", "resolve_incidents"]`. These describe the existing shared credential, not a named actor or new role system. No key, vendor credentials, host, database name or caller-supplied project scope is returned. Responses are not cacheable. Missing/rejected keys return 401; unavailable server access configuration returns a safe 503. Existing header/Bearer precedence remains compatible; malformed credentials cannot cause an internal server error.

Access success means the server accepts the credential. It does not establish database readiness, a connected source, healthy monitoring, real traffic, provisioning or activation. Summary date problems and source outages cannot turn a valid access check into a rejected credential.

## Browser lifecycle

A newly entered key stays in memory while a bounded, cancellable access request verifies it. Persist it only after a valid successful response. A rejected candidate is never saved. Validate a previously stored key before mounting protected pages; preserve the requested deep link. Reject malformed successful access bodies instead of treating any 200 as authenticated.

Startup rejection removes the rejected credential and shows the connection form. Transient unavailability retains it, shows retry/change-key choices, and keeps protected pages unmounted. A later 401 from an authenticated data request returns the app to connection recovery and removes protected content. A late failure from an old credential must not remove a newly verified replacement. Candidate verification must not inherit or overwrite its candidate with a stored key. A 403 or 503 is not automatic logout. Disconnect clears browser access and unmounts protected content without depending on a page reload. Cross-tab key changes trigger validation or disconnection; browser presence alone is not proof of authorization.

The current local key still resides in browser storage after verification. This repair does not make shared-key storage the hosted authentication design: the opt-in R2-01 OIDC implementation uses named identity and secure server-managed sessions instead. The browser loads public auth configuration before consulting any stored key and never reads or sends it in OIDC mode. Disconnection clears this browser's access; it does not revoke the server key or stop monitoring. Storage and network failures must produce recoverable messages without logging or rendering key values.

## Setup and investigation states

An authenticated read-only Setup page explains the current integration boundary and reads `/monitoring`. Distinguish source configuration, successful source traversal, processing progress and unavailable diagnostics. A configured client alone is not verified source access; zero rows in the latest check is not proof of never having traffic. Show last source/processing checkpoints and pending/quarantined work when present. Do not label the product active without the activation evidence required by ONBOARDING.

Teams without telemetry may enter Guardian, but this build still requires operator setup and application instrumentation. Managed capture, project provisioning and Python/JS guided recipes are not claimed available. The setup screen must not invite users to send provider secrets or use the all-access Guardian key as an ingestion token. Technical deployment instructions stay in the repository guide.

Incident detail must distinguish an actual 404 from access denial and temporary read failure, provide retry for transient failures and avoid showing old incident evidence under a changed URL. Access failures take precedence through the shared browser lifecycle.

## Acceptance and boundaries

Verify access with header/Bearer/missing/wrong/malformed credentials, fail-closed configuration and database/source objects that fail if touched. Demonstrate that valid access works while summary reads fail. Test candidate persistence, restored-key verification, deep links, timeout/retry, stale credential races, logout, cross-tab changes, response validation and incident-detail error categories. Exercise setup with unconfigured, configured-but-unchecked, empty successful check, pending/partial, stale and unavailable states. Real localhost HTTP and production-build browser checks must cover the new entry path. Record actual results in [VALIDATION.md](VALIDATION.md).

This legacy access/setup prerequisite creates no accounts, projects, tenant routing, ingestion endpoint or provider connection. Named-user roles and local session logout are defined separately by IDENTITY. The isolated deployment contract and launch gates remain unchanged.
