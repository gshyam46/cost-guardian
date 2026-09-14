# Sillage public frontend and registration

Recorded before implementation on 2026-09-14 under ADR-52. The founder requested a Vercel frontend, a helpful unavailable/coming-soon experience when the workspace backend cannot respond, and durable visitor registration details.

## Product contract

The public site and its small registration service must continue to work independently of the monitoring API and workers. The working first-release choice is early-access registration: name, email, optional company/use case, and explicit permission to contact the visitor about access. This is an unverified interest record, not a provisioned workspace or authenticated account. Do not collect passwords, provider credentials or identity-provider tokens in this form. Existing workspace sign-in remains owned by the current OIDC backend.

The Vercel build uses an explicit public-site flag. `/` and `/welcome` show the landing page; `/demo` remains an isolated interactive sample; `/signup` records early-access interest. `/signin` and `/setup` check a bounded same-origin availability function. That function checks only the operator-configured HTTPS workspace's `/api/ready` endpoint. A healthy result offers a link to the existing workspace's sign-in/onboarding route. Missing configuration, timeout, invalid response or unavailable readiness presents a friendly coming-soon/currently-unavailable page, retry and independent registration. Readiness is not proof of authentication, a source connection or complete telemetry.

Do not weaken the existing same-origin OIDC, cookie, CSRF or membership rules. The public site links to the workspace's own origin rather than trying to move its session cookies across origins. Ordinary self-hosted builds retain their current guarded root/dashboard behavior. The monitoring backend is not being migrated to serverless execution in this slice.

## Registration and storage

Add a same-origin Node function `POST /api/interest`, backed by a separate hosted MongoDB database/credential configured only in server environment variables. Never put database URLs, HMAC keys or administrative credentials in `REACT_APP_*`, browser storage, bundles or URLs. Return success only after acknowledged persistent storage; a storage timeout or missing configuration must show an explicit retryable failure and retain the visitor's form input.

The handler admits a strict versioned, size-bounded JSON body, validates fields and consent, rejects extra fields and unsupported origins/methods/content types, and uses a normalized email identity for atomic duplicate handling. Record first registration time, contact-consent text/version/time, source (signup/signin/onboarding) and unverified state. Do not expose a public registrations list or whether an email already exists. Store no raw IP addresses or request headers; abuse keys can use a server-side HMAC with bounded durable rate-limit records and TTL. Registration retries must not create multiple contacts or erase an earlier record.

Use bounded connection/query deadlines and pooled clients. Separate index/bootstrap and restricted operator export/deletion commands from the public handler. Any exported CSV must avoid spreadsheet formula execution. No automatic outreach is sent in this slice. Provide a short public data-use notice and a defined retention period for these interest records; account identity and telemetry retention remain separate contracts.

## Deployment and phases

1. Record product/storage/auth boundaries and inspect current Vercel support.
2. Implement independent availability and durable registration functions with meaningful persistence, validation, failure and duplicate tests.
3. Add public-mode routes, unavailable/registration pages, truthful submission states and responsive navigation while preserving current self-hosted access behavior.
4. Add Vercel configuration, explicit safe build settings and operator setup/export documentation. Build from source without local `.env` files or unrelated root frontend artifacts.
5. Verify backend-down/hanging/invalid and recovered flows, registration saved/duplicate/storage-failure behavior, public-page isolation and the deployed artifact when account/database access exists. Record exact evidence and outstanding deployment setup in VALIDATION.

Vercel project/account and hosted database access are not currently linked. Complete the reviewable code/configuration before requesting any final deployment setup. Do not silently provision paid services or claim that registrations are stored when the hosted database has not been connected.

## Implemented contract and operator handoff

The functions, public-mode routes, responsive unavailable/registration pages, explicit Vercel build and operator CLI are implemented. Setup commands, server environment names and project-root settings are in the [frontend operator guide](../apps/guardian/frontend/README.md#public-vercel-deployment). Deployment still requires an authenticated Vercel account/project, a dedicated hosted Mongo replica/Atlas database with bootstrap completed, and a real monitored privacy-contact address. Preview and production interest stores must be separate. The existing workspace URL is optional while access is coming soon.

The JSON request is schema version 1: required `name`, `email`, `consent: true`, and `source` (`signup`, `signin` or `onboarding`), plus optional `company` and `use_case`. Limits are 100/254/120/1,200 characters respectively, with a 4,096-byte raw JSON limit. HTTP 202 with `{registered: true, status: "interest_recorded", schema_version: 1}` confirms persisted interest only. Validation/rate/storage failures never receive that acknowledgment. Browser timeouts say saving could not be confirmed because a committed write might outlive the response; normalized duplicate handling makes retry safe.

The initial limits are 5 submissions per IP-derived 15-minute bucket, 60 globally per minute and 1,000 globally per day. Counter reservations and contact changes share a transaction, so rejected attempts roll back. Raw IPs are never persisted. Active duplicate submissions do not overwrite another person's contact details or extend retention. After logical expiry, a new submission with consent starts a new 180-day period. Mongo TTL cleanup runs asynchronously, so expired data is excluded from operator exports while awaiting removal. Outreach and email verification are not automated.

`tools/test_public_launch.cjs --help` is inert. The acceptance command runs the built public UI against actual Node HTTP functions and an explicitly supplied loopback Mongo replica, using synthetic contacts in a unique ownership-marked database. It verifies outage/recovery, confirmed writes, duplicate concurrency, persistence through a new client, transaction rate rollback, private export/deletion, logical expiry and browser auth isolation. It removes only its own marked database. The readiness transport is controlled test evidence; hosted Vercel routing, database networking and deployment remain separate checks. CI runs this journey with its own disposable Mongo container. Current measured results are in [VALIDATION.md](VALIDATION.md).

## Source references

- [Vercel Create React App support](https://vercel.com/docs/frameworks/frontend/create-react-app).
- [Vercel Node functions](https://vercel.com/docs/functions/runtimes/node-js).
- [Vercel Node versions](https://vercel.com/docs/functions/runtimes/node-js/node-js-versions).
- [MongoDB Atlas integration](https://vercel.com/marketplace/mongodbatlas/atlas).
- [Vercel plan boundary](https://vercel.com/docs/plans/hobby).
