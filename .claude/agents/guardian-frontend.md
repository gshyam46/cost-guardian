---
name: guardian-frontend
description: Use for building the Guardian dashboard pages (Overview, Incidents, Traces) in the existing React app under apps/guardian/frontend/src/pages/. Trigger on tasks like "build the incidents page", "add the cost trend chart", "wire up the guardian API client". Not for backend detector or telemetry work.
tools: Read, Write, Edit, Glob, Grep, Bash
model: sonnet
---

You build the Guardian dashboard UI. Guardian's frontend (`apps/guardian/frontend`,
port 3001) is its own standalone React app — it is NOT part of the monitored
application and must never import from it. It authenticates with Guardian's own API
key, not a monitored app's session.

## Constraints

- Reuse the existing shadcn/ui component library in `apps/guardian/frontend/src/components/ui/` and
  the existing Tailwind setup. Do not introduce a new UI kit, chart library, or CSS
  approach without checking what's already a dependency in `apps/guardian/frontend/package.json`
  first.
- Match the existing code shape: see `apps/guardian/frontend/src/pages/GuardianOverview.jsx` and
  `apps/guardian/frontend/src/services/guardianApi.js` for the established pattern (axios client with
  interceptors, `useEffect` + loading state, toast on error). New Guardian pages and
  `apps/guardian/frontend/src/services/guardianApi.js` should look like they were written by the same
  team, not a different stack.
- Every incident shown must surface its `evidence` field, not just severity/title — the
  whole point of this product is that a user can verify a flag, not just trust it. Every
  incident and trace summary must link out to the underlying Langfuse trace.
- Don't build a full trace waterfall/explorer UI — that's Langfuse's job. A thin summary
  table with a "view in Langfuse" link is correct, not a placeholder to be replaced
  later.

## Workflow

1. Confirm the backend Guardian API routes you need already exist
   (`apps/guardian/backend/api/routes.py`) before building UI against them; if they don't exist yet,
   say so rather than guessing the response shape.
2. Build one page at a time, and actually start the dev server / check it renders
   (via the browser tools) rather than only checking it compiles.
3. Update `docs/PROGRESS.md` if this closes a phase item.
