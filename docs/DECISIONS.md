# Cost Guardian — Architectural Decisions

Short-form log. Each entry: decision, why, what it rules out.

---

**⚠️ `backend/.env` was untracked from git on 2026-09-09 — historical keys are
compromised.** The file was committed in `6b20601` and `bbb6820`, and the repo has a
GitHub remote (`gshyam46/cost-guardian`). It has now been added to `.gitignore` and
removed from the index (`git rm --cached`, file left on disk), so newly-added
credentials — Langfuse, the replacement Groq key, and the Atlas connection string with
its password — will never be committed. **This does not retroactively protect anything
already in history.** Any key present in those two commits must be rotated:
`OPENROUTER_API_KEY` (highest priority — still live with credit on it),
`GOOGLE_GEMINI_API_KEY`, `GOOGLE_API_KEY`, `EMERGENT_LLM_KEY`. The original Groq key is
already dead so it carries no residual risk. Rotating is the fix; rewriting history
(`filter-repo`/BFG) only helps if the repo has never been cloned or forked.

**Build on Langfuse rather than a custom trace store.** Trace capture, cost
computation, and a trace explorer UI are commoditized and expensive to build well.
Langfuse Cloud's free tier removes the entire "build a database + UI for raw traces"
scope. Rules out: self-hosting Langfuse for the MVP (revisit only if a customer needs
data residency).

**PII detector ships before prompt-injection detector.** PII has a mechanically
checkable ground truth (regex against known formats: email, SSN, card, IP). Prompt
injection heuristics are keyword-based and high-false-positive with no labeled
benchmark to grade against yet. Rules out: shipping an unvalidated "injection risk
score" as a product claim.

**Detectors are pure functions: `evaluate(baseline, candidates) -> list[DetectorResult]`.**
No network/DB/filesystem access inside a detector. This is what makes every detector
unit-testable in milliseconds with hand-built fixtures, independent of whether Langfuse
or Mongo are reachable. Rules out: detectors that call an LLM or a database directly.

**`IncidentStore` is an interface (`InMemoryIncidentStore` / `MongoIncidentStore`), not
a concrete Mongo class.** Lets `incident_engine.py`'s dedup/severity logic be tested
without a running database. This paid off immediately: this environment has no
reachable MongoDB at all, and detector + incident-engine logic was still fully
verified.

**`backend/observability/` (the old Datadog-based module) is left in place, untouched,
not imported anywhere.** It's dead code, not live code — deleting it isn't required for
the MVP and isn't worth the risk of removing something without being asked to.

**`LlmChat` no longer takes `session_id` at construction time.** Agent instances are
long-lived singletons (`NicheDiscoveryOrchestrator()` is instantiated once at module
load in `api/analysis.py`), so a per-instance session id baked in at `__init__` was
already wrong before Langfuse entered the picture — every request from process start
would have shared one session id. `run_id`/`agent_name`/`user_id` are now passed
per-call to `send_message()` instead.

**Guardian API reuses the app's existing session auth**, not a separate auth system.
Deliberate MVP scope cut for a single-tenant "watch my own app" product. Rules out:
serving a second customer's data through this API as-is — real multi-tenancy needs
per-customer Guardian API keys (Phase 5/7 concern, not before).

**Trace deep-links are built directly, not via the SDK.** _(Revised 2026-09-09 after
live testing.)_ Originally this called the SDK's `get_trace_url()` on the theory that
letting the client resolve the project id beats tracking our own. Against the real
SDK that turned out to be wrong: langfuse 2.x's `get_trace_url()` takes **no
arguments** and only returns a URL for the SDK's *current* trace context, which is
useless for the worker's job of linking arbitrary historical trace ids — every link
silently came back `None`. Now built as `{LANGFUSE_HOST}/trace/{trace_id}` (confirmed
HTTP 200 against the live project, as is the longer project-scoped form). Still
computed at response time rather than stored, so a host change never leaves stale
links in Mongo. Lesson recorded because it generalises: the mocked tests passed
because the mock encoded my *assumption* about the SDK, not its behaviour.

**LLM provider chain is Groq-first, chosen by live probing rather than inheritance.**
The chain inherited from the original codebase was 100% dead —
`groq/llama-3.3-70b-versatile` and `llama-3.1-8b-instant` aren't available on the
account, `openrouter/allenai/olmo-3-32b-think` 404s, `openrouter/arcee/trinity-mini`
was withdrawn. Every model in the current chain was probed live with an agent-sized
prompt before being added. Groq leads on latency (~1-2s vs >30s and upstream
rate-limiting on OpenRouter's shared free pool); one OpenRouter model is kept last as
a cross-provider fallback so a Groq outage doesn't halt the pipeline. Request timeout
raised 30s → 120s: the original value was shorter than a real agent response takes.

**Agent LLM calls use JSON mode (`response_format={"type": "json_object"}`), not just
retries.** Every caller of `LlmChat` is an agent that must return parseable JSON. A
3-attempt re-ask was added first, but the larger responses (~9k chars) came back
malformed often enough to exhaust all three and kill the run. JSON mode constrains
decoding so validity is guaranteed rather than hoped for, and as a side benefit stops
models wrapping output in markdown fences (~2.5k chars vs ~6.2k for the same content).
The re-ask loop is kept as a second line of defence.

**Langfuse fetches paginate at 100 items.** The API rejects `limit > 100` with a 400
("Too big: expected number to be <=100"); we were asking for 200 and 500, so every
worker poll failed. `fetch_recent_generations()` now pages. Worth noting the test
written alongside the fix immediately caught a follow-on bug where a final partial
page could overshoot the caller's requested limit.

**Fixed a CSS variable namespace collision between `App.css` and shadcn's
`index.css`.** `App.css` defined `--primary`/`--secondary`/`--accent`/`--border` as
hex colors at `:root`, colliding with shadcn's design tokens of the same names (which
use a space-separated HSL-triplet format consumed as `hsl(var(--x))`). App.css loads
after index.css, so its hex values won the cascade, and `hsl(#0EA5E9)` etc. are
invalid CSS — the declarations were silently dropped app-wide. Found via a Guardian
incidents-page filter button rendering with invisible white-on-white text. Renamed
App.css's custom properties to `--brand-*` rather than touching shadcn's `index.css`
(the generated/framework file, conventionally left alone) or avoiding
`variant="default"` in Guardian's own components (that would hide the bug rather than
fix it, and it affects every other page's default-variant buttons too, not just
Guardian's).

**Guardian's own dashboard does not add a settings/API-key page yet.** There's
nothing to configure until multi-tenancy exists (Phase 7) — a single-tenant MVP has
exactly one Langfuse project and one Mongo database, both already configured via
`backend/.env`. Adding a settings page now would be UI for a feature that doesn't
exist.

**No download-and-run-a-real-MongoDB-binary workaround for this environment's missing
Mongo.** The official Windows MongoDB zip is ~620MB; downloading it to unblock one
session's verification is a worse trade than being explicit about the blocker and
using `mongomock`/`InMemoryIncidentStore` for what can be verified offline. Rules out:
treating "no live Mongo" as something to route around rather than surface to the user.
