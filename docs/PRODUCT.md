# Cost Guardian: product direction

Updated 2026-09-11. This defines intended behavior; [PROGRESS.md](PROGRESS.md) describes what exists.

## Customer and problem

Serve teams shipping AI SaaS, RAG and agent workflows, including teams without telemetry or observability. A founder/engineering lead buys; an engineer investigates; a product owner needs customer-impact evidence. First partners should own a deployed application, have access to its server code/integration settings, and experience recurring cost or reliability problems.

Start with a small tested integration set. “Any AI team can benefit” describes the market, not universal provider/framework support on day one. A team unable to instrument or export telemetry cannot receive workflow monitoring by entering a URL or provider key alone.

Customer jobs:

- Distinguish spend growth caused by traffic, model changes, larger context, retries or inefficient workflows.
- Learn about important failures without watching dashboards.
- Identify affected workflows/environments and investigate with evidence.
- Verify mitigation at comparable traffic and workload mix.
- Obtain this capability without operating an observability stack.

## Promise and activation

**Know which AI workflows need attention, understand the evidence, and verify the improvement.**

Proposed activation target: a developer on a supported stack sees a real workflow within 15 minutes, without a Langfuse account. This is a beta measurement target, not a guarantee. Test-event receipt, real traffic, and sufficient baseline history are separate milestones.

| Setup path | Customer does | Guardian owns |
|---|---|---|
| Start monitoring, no telemetry | Creates project, chooses integration, adds scoped configuration/instrumentation, tests, runs app | Ingestion, backing telemetry provisioning, validation, retention and health |
| Connect existing Langfuse | Selects host/region, supplies project credentials securely, maps workflow/environment | Diagnostics, safe import/backfill, baseline readiness and incident workflow |

Both reach the same product. Managed capture may use Langfuse internally without requiring the customer to operate it. Customers without Langfuse need useful evidence in Guardian's authenticated UI; an inaccessible external trace link is not a complete experience. See [ONBOARDING.md](ONBOARDING.md).

## Private beta scope

| Capability | Required behavior | Current state |
|---|---|---|
| Managed onboarding | Tested Python and JavaScript/TypeScript paths, including a RAG example | Absent |
| Trusted costs | Coverage labels, known/unknown pricing, replay-safe totals, workflow attribution | Partial; defects identified |
| Cost policy | Absolute budget/burn thresholds plus evaluated relative-change detection | Per-call, per-agent z-score only |
| Reliability | Terminal workflow outcome, recovered retries, grouped error-rate/latency policy | Every failed generation is a high-severity candidate |
| RAG visibility | Workflow, retrieval timing/count, embedding usage/cost where known, generation, application outcome | Only generations consumed |
| Response | Reliable notification, owner, acknowledge/snooze/resolve, runbook and recovery check | List/detail/manual resolve |
| Feedback | Useful/noisy/expected-change reason and action | Absent |
| Access/privacy | Named users, roles, scoped keys, content defaults, retention/export/delete | Shared key; output previews |
| Operations | Source freshness, ingestion lag/rejections, restore and support path | Basic API liveness and some stale-read UI |

RAG operational health is different from answer correctness. Fast or nonempty retrieval does not establish groundedness. Quality evaluation needs a dataset, scoring method and feedback.

## End-to-end journey

1. Evaluate supported integrations, limits, data handling, pricing basis and a labelled sample incident.
2. Finish one setup path; receive specific, actionable errors.
3. See real traffic, freshness, field coverage and detector warm-up.
4. Set important workflows, environment, budget/latency policy, owner and destination.
5. Receive a grouped incident with impact, confidence/coverage and evidence.
6. Compare baseline/current windows, attempts and retrieval; follow a short investigation guide.
7. Record mitigation or expected-change dismissal; no automatic customer-system modifications.
8. Verify post-change outcomes; show recovery pending when traffic is insufficient.
9. Review weekly outcomes; manage keys, retention, export, cancellation and deletion.

## Measure value

- Activation: started setups reaching real attributed traffic and a tested notification destination; split by setup path/integration.
- Time to first value: setup start to correctly attributed real workflow; measure test receipt and baseline readiness separately.
- Usefulness: actionable / reviewed incidents, with sample size and review window.
- Noise: non-actionable notifications per project/week, including repeated and incorrectly grouped events.
- Response: upstream availability to detection, delivery, acknowledgement, mitigation and verified recovery.
- Retention: ongoing production telemetry plus useful actions over successive weeks; visits alone are insufficient.
- Business value: confirmed mitigations and cost per successful workflow before/after, with traffic/model-mix caveats.

Cost per successful workflow needs an application-defined terminal outcome. Do not infer success from absence of an ERROR span. Include observed failed attempts and embedding/tool charges, and disclose excluded infrastructure/external charges. Without outcomes, show cost per observed run and outcome coverage. Observed costs are telemetry-derived, not an invoice reconciliation service.

Define the initial efficiency metric explicitly: spend on finalized workflows (successful and failed, including their attempts) divided by successful workflow completions in the same cohort/window. Report pending/unknown-outcome workflows and unpriced observations separately. If there are no successful completions, the metric is unavailable, not zero. Show spend on successful runs alone as a separate measure when useful. This prevents failed work from disappearing from the economics.

## Positioning and commercial discovery

Native alerts already exist in [Langfuse](https://langfuse.com/docs/observability/features/alerts) and [Helicone](https://docs.helicone.ai/features/alerts). Guardian must demonstrate a better setup-to-action experience. The code does not yet establish that advantage.

Conduct 8-10 problem interviews and recruit three design partners spanning AI SaaS, RAG and agent workflows. Ask about their last incident, current tools, time spent, buyer and missing information. Observe setup/investigation, and compare with native alert configuration. These interviews are planned; none were conducted in this review.

Test subscription per workspace with an observation allowance and transparent caps/overages. Price, allowance and margin remain open. Avoid incident-based pricing, which rewards noise. Track storage, upstream API, ingestion compute, delivery and support costs; include inference costs if an investigator is later added. Managed telemetry can materially change economics. Manual invoicing can serve pilots before automated billing.

If partners only need thresholds, refine the onboarding offer or narrow to a demonstrated workflow/RAG problem. If repeated value does not emerge, pause platform expansion.

Initial distribution is founder-led: recruit through existing engineering relationships and relevant AI-builder communities, publish a realistic supported-stack setup walkthrough and a measured incident case study with permission, and invite teams with a recent recurring problem into an assisted pilot. Recruitment and messages require the founder's execution/authorization; none were sent during this review. Track qualified conversation -> setup started -> real traffic -> useful action -> paid continuation. Avoid paid acquisition until activation and continued usefulness are demonstrated. A broad “AI tools” audience is not a substitute for a buyer with an immediate problem.

## Boundaries

The initial product provides asynchronous monitoring and guided response. It cannot guarantee overspend prevention, leak prevention or hallucination detection. Existing regex PII is experimental pattern matching, not proof of a leak or compliance. Target content scanning is optional and off by default. Research and AI investigation follow reliable data and customer validation. Founder Niche Discovery stays a test workload.
