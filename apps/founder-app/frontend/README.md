# Founder demo frontend

This frontend belongs to the independent Founder Niche Discovery demo workload. Cost Guardian does not require this app, its authentication or its database to run.

For the product review and implementation plan, start at the [repository README](../../../README.md). The demo is maintained to exercise realistic multi-step LLM telemetry, not as a second launch product.

## Local setup

Use Node 24/npm 11. From this directory, in PowerShell:

```powershell
npm.cmd ci
Copy-Item .env.example .env
npm.cmd start
```

The backend runs separately on port 8000 with its own Python environment and configuration. The browser authentication flow currently depends on an external Emergent authentication service. Its credentials/availability and a complete browser run were not verified in the 2026-09-11 review.

The template sets port 3000 and the public backend URL at port 8000. Keep real secrets on the backend; never put provider credentials into React build variables.

## Checks

```powershell
$env:CI = "true"
npm.cmd test -- --watchAll=false --runInBand
npm.cmd run build
```

Both a package-lock and a Yarn lockfile exist historically. npm and the tracked package-lock are authoritative; the old Yarn lock is preserved. The 2026-09-11 R0-01 implementation passed a clean npm install, four JSDOM route/session tests and a production build. Tests mock HTTP services and do not prove live OAuth or deployed SPA fallback. Guardian's product evidence is tracked in [VALIDATION.md](../../../docs/VALIDATION.md).

Unused template script injection, badge and template-project analytics have been removed. The app's explicit Emergent authentication integration remains. The repaired [verification harness](../../../tools/README.md) runs each backend independently and separates offline evidence from explicitly configured live traffic.
