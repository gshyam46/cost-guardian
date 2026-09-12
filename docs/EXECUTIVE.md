# Cost Guardian: executive assessment

Reviewed 2026-09-11 at application baseline `a66caf7`; updated through 2026-09-12 with R0-01, bounded R1 source/ledger/summary work, named OIDC access and native numeric intake with scoped keys. These slices are implemented locally. Cutover, real source/identity-provider compatibility and operating gates remain open; managed onboarding and the customer response loop remain unfinished.

**Verdict: a useful engineering prototype with a credible problem to pursue, but not ready for customer production use.** Keep the standalone service, pure detectors, and evidence-based approach. Redirect effort toward trustworthy data, onboarding, and helping customers take action. A successful demo and the historical “91% of MVP” estimate do not establish launch readiness.

The founder clarified the audience: **AI SaaS, RAG, and agent product teams must be able to onboard without existing telemetry, observability, or a Langfuse account.** Existing Langfuse users remain a supported path. Universal compatibility is a longer-term ambition; publish the integrations actually tested.

## Product investment

Help a small AI product team answer: “Which workflow got more expensive or less reliable, what is affected, what should we investigate, and did our change help?” Make the first useful result easy to obtain. Track cost per successful workflow and retry waste, with missing business outcomes clearly labelled.

The product boundary expands to:

`guided setup -> trusted telemetry -> meaningful incident -> notification -> investigation -> verified recovery`

Langfuse already offers configurable alerts and external delivery. Helicone also provides cost and error alerts. Therefore “the alerts Langfuse doesn't have” is not a defensible pitch. Easy setup, workflow context, lower noise and useful customer actions are hypotheses to validate against these alternatives. [Langfuse alerts](https://langfuse.com/docs/observability/features/alerts), [Helicone alerts](https://docs.helicone.ai/features/alerts).

## Most urgent gaps

The latest customer features connect [Monitoring rules](POLICIES.md) to [Slack delivery](NOTIFICATIONS.md): owners configure useful per-call rules, test/enable a destination and see delivery history beside incident evidence. First-call checks work without statistical history; incident creation and queued delivery commit together. Local API/Mongo/receiver evidence covers investigation, resolution, replay and delivery failure recovery. Supported provider usage extraction and runnable customer deployment/onboarding are the next priorities. Actual customer activation and live Slack acceptance remain unverified.

| Gap | Customer consequence | Action |
|---|---|---|
| Bounded ledger recovery is implemented, but historical gaps, source delay and high-volume limits remain unverified | Monitoring may stall or have incomplete history outside its supported window | Finish R1-02 cutover, load/retention and recovery evidence; publish the tested envelope |
| Existing incremental aggregates cannot establish observation identity | Older deployments cannot safely switch writers without a cutover decision | R1-02: automate backup/cutover/reconciliation/rollback; preserve historical limits |
| Incident totals/calendar are repaired locally, but query and legacy-conversion costs are not a production capacity result | Large histories may return unavailable when query budgets are exceeded | R1-03: validate index deployment, legacy costs, metric/list scaling and supported load |
| Default v2 reads are locally verified, but live server/exporter compatibility is unverified; Founder still uses old ingestion | Source visibility may be delayed and setup may fail on an untested version | R1-01: modern exporter migration and actual supported-version evidence before beta |
| Stable findings now survive replay, but incident grouping and lifecycle are incomplete | Customers still lack a useful response workflow across related failures | R3: retain finding identity while adding grouping, ownership, delivery and recovery |
| Named OIDC access and direct numeric capture now work without Langfuse, but still require operator configuration and application export code | Supported developers have a practical entry path; independent customer activation remains unproven | R2: validate actual provider/deployment and Python/JS customer recipes, then managed instrumentation and provisioning |
| Slack delivery is implemented locally; ownership workflow and measured recovery remain open | Customers can receive incidents, but still need clearer coordination and proof that mitigation worked | R3: validate deployed delivery, then finish the response loop |
| Named sessions, scoped write-only keys and action audit have local evidence; Langfuse content previews, account administration and retention remain unfinished | The hosted access/privacy and offboarding journey is incomplete | R0/R2/R5: deployed identity validation, safe Langfuse content defaults and lifecycle |
| Langfuse generations and direct terminal-call metrics are captured; retrieval context and settled workflow outcomes are absent | RAG and impact claims exceed coverage | R1/R2: normalized spans and application outcomes |
| Live release evidence is incomplete | Offline checks cannot prove customer activation or source behavior | R0: repaired independent-app harness now passes offline; live checks remain pending |

## Sequence

1. **R0:** restore reproducibility, close credential-history questions, interview users.
2. **R1:** make ingestion and numbers trustworthy; establish telemetry/workflow contracts.
3. **R2:** onboard a team with no observability account; retain connect-existing Langfuse.
4. **R3:** deliver actionable incidents, notifications, feedback and recovery evidence.
5. **R4:** assisted private beta; compare value with native alternatives.
6. **R5:** paid self-service, supported by isolation, lifecycle, billing and operating evidence.

Defer autonomous remediation, AI root-cause claims, every-provider support, and generic security/quality scoring. Polling detects after an event; it does not stop spending or prevent a leak.

## Evidence and next work

Guardian defaults to direct HTTPX Observations v2 reads; legacy v1 requires explicit configuration and never activates automatically. Shared normalization preserves unknown measurements and explicit measured zero. The worker now persists bounded source pages, observation identity, quarantine and processing work in fenced Mongo transactions, then rebuilds affected totals. It captures new identities in a 24-hour overlap and accounts for the full initial import window. Source and processing completion remain separate. Live/run views expose bounded, stale and unknown evidence without inventing workflow success or duration. See [INGESTION.md](INGESTION.md), [SOURCE_MIGRATION.md](SOURCE_MIGRATION.md) and local results in [VALIDATION.md](VALIDATION.md).

All seven original probes are repaired, including the material transition from explicitly free calls to a charged call. Unknown prices never form a free baseline. Stable incident insertion preserves human resolution on replay. V2 resumes after five pages per poll, but bounded rebuild/baseline processing can retain a backlog. These repairs do not close the full R1 or launch gates.

Incident summaries now count all matching records instead of silently stopping at 1,000 open or 10,000 dated incidents. A single response provides UTC calendar trends including today and visible invalid-date coverage. Failed queries return unavailable, and failed incident-list requests show retry instead of a reassuring empty state. Legacy date handling is compatible without rewriting history; its operating cost still needs validation. [Summary contract](SUMMARIES.md).

Entry now discovers the configured auth mode and verifies access independently of monitoring. Opt-in OIDC gives operator-configured members owner/operator/viewer roles, secure opaque sessions and a fixed isolated-project binding; it never falls back to a saved shared key. Named incident resolution records the actor in the same transaction as the state change, and replay preserves the original resolution. Local shared-key mode remains compatible. Setup distinguishes configuration from observed reads and pending processing. [Access contract](ACCESS.md), [named identity contract](IDENTITY.md).

Independent local identity checks cover signed-token verification, browser-bound one-use state, configured scope/roles, expiry and revocation, safe failures and CSRF/Origin. Actual localhost Mongo checks establish audit rollback, concurrent resolution, both logout orderings, atomic session rotation and uncertain commit recovery. Actual IdP registration/TLS callbacks, membership administration and project provisioning remain unfinished.

The new [direct capture contract](CAPTURE.md) gives a developer without Langfuse a bounded practical route: create an owner-authorized write-only key and add the [Python or JavaScript recipe](../examples/native-capture/README.md) to export completed call metrics. The strict schema excludes prompts, responses and caller-controlled project scope. Keys are hashed, expire and can be revoked without altering accepted history. Receipt/quotas/inbox commit atomically, and the worker reuses the existing ledger and detectors. Actual local Mongo and loopback HTTP checks cover replay, backpressure, revocation races and two calls reaching totals and an incident without constructing a Langfuse client.

The next local slice adds [Python/Node background exporters](EXPORTING.md) and explicit normal/streaming call helpers. A developer no longer needs to build a process queue to keep export HTTP outside the provider request path. Counters expose overload and unconfirmed shutdown work, and real localhost API/Mongo tests show that retrying a lost committed receipt does not inflate totals. The helpers preserve provider behavior but still require explicit integration and observed measurements; provider-specific adapters remain next work.

The product must keep local queue acceptance, test handshake, real telemetry receipt and completed analysis distinct. A 202 acknowledges durable receipt only; a stopped worker can leave accepted work pending. Test traffic never enters production baselines. These slices do not provide automatic instrumentation, full RAG context, managed provisioning, retention/deletion or a measured activation-time claim. They advance the founder's no-observability requirement while leaving the full R2 gate open.

Real compatibility evidence remains urgent: Cloud removes legacy reads on **2026-11-16**, and self-hosted v4 omits them. The v2 reader is implemented, while Founder exporter migration and supported-version live checks remain open. Older ingestion can take up to 15 minutes to appear in v2; this delay is separate from Guardian processing time. V4 observations are immutable: resubmitting an ID is not a reliable revision update. The ledger now quarantines ambiguous conflicts in both modes until authoritative revision handling is established. [Source contract and primary references](SOURCE_MIGRATION.md).

Local browser checks use synthetic API responses; localhost Mongo transaction and summary checks have separate dated results in [VALIDATION.md](VALIDATION.md). Neither establishes customer activation or production failover. Real source services, hosted CI, operating recovery and willingness to pay remain unverified. Next engineering work completes **R1-02 cutover/recovery, R1-03 query/load validation, and R1-01 exporter/live compatibility**, while R0 credential closure and discovery/provisioning continue. [REVIEW.md](REVIEW.md) preserves original findings with repair status; [PLAN.md](PLAN.md) owns implementation order.
