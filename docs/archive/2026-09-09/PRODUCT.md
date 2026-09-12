> Historical snapshot preserved during the 2026-09-11 review. Claims below describe prior work and are superseded by the current docs. Internal relative links may refer to the original file locations.

# Cost Guardian — Product

## What this is not

Not another LLM observability platform. Langfuse, Helicone, and similar tools already
solve trace capture, token/cost accounting, latency, and trace exploration well. Cost
Guardian does not compete with that layer — it sits on top of it.

## What this is

A plug-and-play **AI reliability / incident-intelligence layer** for early-stage AI
startups: founders and small engineering teams who already have (or can trivially add)
observability, but don't have the bandwidth to constantly interpret it.

Positioning: *"You already have observability. Cost Guardian helps you understand it."*

```
Application → existing telemetry (Langfuse/OTel/logs) → Cost Guardian → detection →
correlation → incident intelligence → engineer/founder
```

## The core loop it should eventually answer

1. What is happening?
2. Is something actually wrong?
3. Why is it probably happening?
4. What should the engineer investigate next?

## Signals are not the product

Four unrelated metric alerts (latency ↑, tokens ↑, quality ↓, retrieval latency ↑) are
noise. The differentiated value is **correlating them into one incident with a
timeline**:

> "AI workflow regression beginning shortly after deployment X; context size increased
> significantly, retrieval latency increased, and the affected behavior is concentrated
> in workflow Y."

`signal → correlation → incident → investigation → evidence-backed explanation` is the
real roadmap. The MVP only builds the first step (signal → incident) with deterministic
detectors; correlation and investigation are staged for after the MVP proves the
detectors themselves are reliable enough to trust.

## MVP detector scope (deliberately narrow)

| Detector | Why this one, now | Deferred alternative |
|---|---|---|
| Cost/token anomaly | Statistical, no ground-truth-label problem, cheap, directly maps to "cost where high, calls drift" | — |
| Reliability anomaly (latency/error rate) | Same — statistical, deterministic, no label problem | Quality/hallucination scoring (needs an evaluation method — real research question, not solved by a regex) |
| PII detection | Regex against known formats (email/phone/SSN/card) is precise and has a testable ground truth | Prompt injection — heuristic keyword matching is high-false-positive and not reliably evaluable without a labeled adversarial-prompt corpus. Picked PII first per the "choose the more reliable/evaluable first implementation" constraint; injection detection is next, once there's a benchmark to grade it against |

Hallucination and context-loss heuristics from the old `observability/` module are
**not** in the MVP — they need an evaluation methodology (what's "ground truth" for a
hallucination?) before they're worth shipping as a claim, not just a heuristic.

## Future: Agentic SRE investigator (explicitly not in MVP)

A later phase may add an AI agent that, once a deterministic detector raises an
incident, investigates by querying traces, logs, deployments, GitHub diffs, and prior
incidents — and must separate **observed facts** from **correlations** from
**hypotheses**, with evidence, never fabricating a root cause. This requires the
incident data model and detector outputs (Phase 3) to exist first, since the
investigator's job is to explain an incident, not to generate more of them.

## Research framing (intentionally not locked)

This project doubles as a research platform, not just a product. Candidate directions
to actually investigate against literature once the MVP produces real incident data:

- Agent-assisted incident diagnosis for AI/LLM applications
- Anomaly detection specifically for AI-application telemetry (vs. generic APM, where
  token/cost/context-window signals don't have established baselines)
- Multi-signal correlation (cost + latency + quality + context) into a single incident
- Runtime behavioral signals for detecting AI agent failures (loops, repeated tool
  calls, context blowup)

The final research question should come out of what the MVP's real incident data
actually looks like, not be picked in advance.

## Target user

Seed / early-Series-A AI startups, small eng teams, no dedicated SRE or AI-reliability
function. They're already shipping an AI product; they are not staffed to watch
dashboards.
