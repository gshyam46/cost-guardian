#!/usr/bin/env node
/* Production-build browser check. Synthetic APIs only; no customer connection. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const http = require('node:http');
const path = require('node:path');

const args = process.argv.slice(2);
if (!args.length || args.includes('--help')) {
  console.log('Usage: node tools/browser_smoke.cjs --playwright <installed playwright module directory>');
  process.exit(0);
}
if (args.length !== 2 || args[0] !== '--playwright') throw new Error('Expected explicit --playwright module directory');
const { chromium } = require(path.resolve(args[1]));
const root = path.resolve(__dirname, '..');
const build = path.join(root, 'apps/guardian/frontend/build');
const reports = path.join(root, 'tools/reports/browser-providers');
assert(fs.existsSync(path.join(build, 'index.html')), 'Build Guardian before running the browser smoke');
fs.mkdirSync(reports, { recursive: true });

const now = new Date().toISOString();
const windowStart = new Date(Date.now() - 86400000).toISOString();
const stats = {
  window_hours: 24, call_count: 2, error_count: 0, unknown_status_count: 1,
  total_cost_usd: null, known_cost_usd: 0.25, cost_known_count: 1, cost_unknown_count: 1,
  total_tokens: null, known_total_tokens: 20, tokens_known_count: 1, tokens_unknown_count: 1,
  avg_latency_ms: 1200, p95_latency_ms: 1200, latency_known_count: 1, latency_unknown_count: 1,
  aggregate_issues: [], last_call_at: now, by_agent: [], by_model: [],
};
const coverage = {
  status: 'partial', window_start: windowStart, window_end: now, fetched_at: now,
  observed_count: 2, records_read: 3, invalid_count: 1, duplicate_count: 0,
  pages_fetched: 1, max_records: 1000, max_pages: 10, reason: 'invalid_observation',
  truncated: false, scope: 'window_generations', issues: { missing_observation_id: 1 },
};
const calls = [
  { id: 'synthetic-call-1', trace_id: 'synthetic-run', agent_name: 'answer-generator', model: 'synthetic-model',
    started_at: now, latency_ms: 1200, cost_usd: 0.25, total_tokens: 20, status: 'success' },
  { id: 'synthetic-call-2', trace_id: 'synthetic-run', agent_name: 'retrieval-agent', model: 'synthetic-model',
    started_at: now, latency_ms: null, cost_usd: null, total_tokens: null, status: 'unknown' },
];
const live = { available: true, degraded: false, stale: false, fetched_at: now, coverage, stats, calls, runs: [] };
const ledgerMetric = {
  hour: now.slice(0, 13) + ':00:00+00:00', agent_name: 'answer-generator', call_count: 1, error_count: 1,
  total_cost_usd: 0.75, known_cost_usd: 0.75, cost_known_count: 1, cost_unknown_count: 0,
  total_tokens: 20, known_total_tokens: 20, tokens_known_count: 1, tokens_unknown_count: 0,
  avg_latency_ms: 500, latency_known_count: 1, latency_unknown_count: 0, unknown_status_count: 0,
  coverage_status: 'known', accounting_status: 'ledger-1', conflict_count: 0, aggregate_issues: [],
};
const ledgerMonitoring = {
  source_configured: true, healthy: true, stale: false, status: 'complete', read_status: 'complete',
  last_successful_checkpoint: now, source_watermark: now, processing_watermark: now,
  source_fetched_at: now, last_attempt_at: now, records_read: 2, pages_fetched: 1,
  pending_observations: 0, dirty_buckets: 0, quarantined_records: 0, accounting_status: 'ledger-1',
};
const validAccess = {
  authenticated: true, auth_mode: 'api_key', deployment_mode: 'single_project',
  permissions: ['read', 'resolve_incidents'],
};
const csrfToken = 'browser_synthetic_csrf_12345678901234567890';
const oidcAccess = role => ({ authenticated: true, auth_mode: 'oidc', deployment_mode: 'single_project',
  permissions: role === 'viewer' ? ['read'] : ['read', 'resolve_incidents'],
  actor: { id: 'synthetic-member', name: 'Synthetic Member', role },
  project: { organization_id: 'synthetic-org', project_id: 'synthetic-project', environment: 'test', name: 'Synthetic Project' },
  csrf_token: csrfToken });
const ledgerCoverageText = 'Hourly totals count captured observations once. Late arrivals are checked within a rolling 24-hour window; earlier history and upstream retention may limit coverage.';
const incident = { id: 'synthetic-incident', title: 'Synthetic retry failure', summary: 'Inspect the synthetic failed call',
  status: 'open', severity: 'high', detector: 'reliability_anomaly', evidence: { calls: 1 }, created_at: now, trace_ids: [], trace_urls: [] };
let scenario = 'partial';
let accessMode = 'valid';
let accessGate = null;
let authMode = 'api_key';
let oidcRole = 'viewer';
let oidcSession = false;
let resolved = false;
let captureMode = 'langfuse';
let ingestionKeys = [];
let issuedTokens = new Map();
let issuedCount = 0;
const captureStatus = { last_test_received_at: null, last_received_at: null, received_events: 0,
  pending_events: 0, processed_events: 0, last_processed_at: null, conflicted_events: 0, worker_status: 'not_started' };
const captureBody = () => ({ mode: captureMode, enabled: captureMode === 'direct', schema_version: 1,
  collector_path: '/api/guardian/ingest/events', can_manage_keys: captureMode === 'direct' && oidcRole === 'owner',
  project: authMode === 'oidc' ? oidcAccess(oidcRole).project : null,
  limits: { max_batch_events: 100, max_body_bytes: 262144, max_active_keys: 10, max_keys: 100 },
  status: captureMode === 'direct' ? { ...captureStatus } : null });
let policyRevision = 0;
let policyRules = { max_call_cost_usd: null, max_call_latency_ms: null, alert_on_errors: true };
const policyBody = () => ({ schema_version: 1, revision: policyRevision,
  updated_at: policyRevision ? now : null,
  updated_by: policyRevision ? { id: 'synthetic-member', name: 'Synthetic Member', role: 'owner' } : null,
  rules: { ...policyRules }, can_manage: authMode === 'oidc' && oidcRole === 'owner',
  project: authMode === 'oidc' ? oidcAccess(oidcRole).project : null });
let notificationRevision = 0;
let notificationDestination = { channel: 'slack', state: 'not_configured', verified: false, enabled: false };
let notificationWorker = { status: 'unknown', last_seen_at: null };
let notificationDeliveries = [];
const notificationRequests = new Set();
const notificationBody = (incidentId = null) => ({ schema_version: 1, revision: notificationRevision,
  project: authMode === 'oidc' ? oidcAccess(oidcRole).project : null,
  can_manage: authMode === 'oidc' && oidcRole === 'owner', updated_at: notificationRevision ? now : null,
  destination: { ...notificationDestination }, worker: { ...notificationWorker },
  deliveries: notificationDeliveries.filter(row => incidentId === null || row.incident_id === incidentId)
    .map(row => ({ ...row, can_retry: authMode === 'oidc' && oidcRole === 'owner' && row.can_retry })), has_more: false });
const delivery = (id, kind = 'test', state = 'queued') => ({ id, incident_id: kind === 'test' ? null : 'synthetic-incident',
  kind, state, created_at: now, updated_at: now, attempt_count: 0, cycle: 1,
  next_attempt_at: state === 'queued' ? now : null, last_outcome: null, can_retry: false, attempts: [] });
const settleDelivery = (row, outcome = 'accepted') => Object.assign(row, { state: outcome === 'accepted' ? 'accepted' : 'unconfirmed',
  updated_at: now, attempt_count: row.attempt_count + 1, next_attempt_at: null, last_outcome: outcome,
  can_retry: outcome !== 'accepted', attempts: [...row.attempts, { number: row.attempt_count + 1,
    started_at: now, finished_at: now, outcome }] });
const currentIncident = () => scenario.startsWith('policy-incident') || scenario.startsWith('notification-incident') ? {
  ...incident, title: 'Synthetic call cost limit exceeded', detector: 'cost_anomaly',
  trace_ids: ['synthetic-policy-run'], agent_name: 'answer-generator',
  evidence: { policy_revision: 1, policy_kind: 'absolute', metric: 'cost_usd',
    observed_value: '0.08', threshold_value: '0.05', comparison: 'gt', reason: 'cost_limit_exceeded', model: 'synthetic-model' },
} : incident;
const seen = [];
const browserErrors = [];
const routeErrors = [];
const server = http.createServer((req, res) => {
  try {
    const pathname = decodeURIComponent(new URL(req.url, 'http://localhost').pathname);
    let file = path.resolve(build, '.' + pathname);
    if (!file.startsWith(build + path.sep) && file !== build) {
      res.writeHead(403).end(); return;
    }
    if (!fs.existsSync(file) || !fs.statSync(file).isFile()) file = path.join(build, 'index.html');
    const types = { '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.json': 'application/json', '.svg': 'image/svg+xml' };
    res.writeHead(200, { 'Content-Type': types[path.extname(file)] || 'application/octet-stream' });
    fs.createReadStream(file).pipe(res);
  } catch { res.writeHead(400).end(); }
});

(async () => {
  let browser, page;
  try {
    await new Promise((resolve, reject) => { server.once('error', reject); server.listen(0, '127.0.0.1', resolve); });
    const origin = `http://127.0.0.1:${server.address().port}`;
    browser = await chromium.launch({ channel: 'msedge', headless: true });
    const context = await browser.newContext({ viewport: { width: 1440, height: 1050 }, serviceWorkers: 'block' });
    await context.addInitScript(() => {
      // Seed once per isolated context. Reload must preserve actual disconnect,
      // rejected-key removal and newly verified persistence behavior.
      if (!localStorage.getItem('browser_smoke_initialized')) {
        localStorage.setItem('browser_smoke_initialized', '1');
        localStorage.setItem('guardian_api_key', 'browser-smoke-key');
      }
    });
    await context.route('**/*', async route => {
      try {
      const url = new URL(route.request().url());
      if (url.pathname.startsWith('/api/guardian/')) {
        seen.push({ scenario, accessMode, authMode, path: url.pathname, method: route.request().method() });
        if (url.pathname === '/api/guardian/auth/config') {
          assert(!route.request().headers()['x-guardian-key'], 'Public config received a shared key');
          assert(!route.request().headers()['x-guardian-csrf'], 'Public config received CSRF material');
          if (scenario === 'config-unavailable') return route.fulfill({ status: 503, json: { detail: 'Synthetic configuration unavailable' } });
          return route.fulfill({ json: { auth_mode: authMode, login_path: authMode === 'oidc' ? '/api/guardian/auth/login' : null } });
        }
        if (authMode === 'oidc') {
          assert.equal(url.origin, origin, 'Production OIDC API request is not same-origin');
          assert(!route.request().headers()['x-guardian-key'], 'OIDC request received a shared key');
          if (url.pathname === '/api/guardian/ingest/events') {
            const headers = route.request().headers();
            assert(!headers.cookie && !headers.authorization && !headers['x-guardian-csrf'], 'Machine intake inherited dashboard credentials');
            const key = headers['x-guardian-ingest-key'];
            assert([...issuedTokens.values()].includes(key), 'Machine intake did not use a just-issued synthetic token');
            const batch = route.request().postDataJSON();
            assert.equal(batch.schema_version, 1); assert.equal(batch.test_mode, true);
            assert.equal(batch.events.length, 1); assert.equal(batch.events[0].cost_usd, null);
            assert.equal(batch.events[0].total_tokens, null);
            captureStatus.last_test_received_at = now;
            return route.fulfill({ status: 202, json: { batch_id: batch.batch_id, received: 1, duplicate: 0,
              conflict_candidates: 0, test_mode: true, replayed: false, processing: 'test_only' } });
          }
          if (url.pathname === '/api/guardian/auth/login') {
            assert.equal(route.request().method(), 'GET');
            assert.equal(url.search, '', 'Browser supplied an arbitrary server return URL');
            oidcSession = true;
            await context.addCookies([{ name: 'guardian_session', value: 'synthetic-opaque-browser-session', url: origin, httpOnly: true, sameSite: 'Lax' }]);
            return route.fulfill({ status: 302, headers: { location: origin + '/?guardian_login=complete' } });
          }
          if (!oidcSession || scenario === 'oidc-expired-data' && url.pathname === '/api/guardian/monitoring') {
            return route.fulfill({ status: 401, json: { detail: 'Synthetic session absent' } });
          }
          assert((route.request().headers().cookie || '').includes('guardian_session=synthetic-opaque-browser-session'), 'OIDC API request did not carry its HttpOnly session cookie');
          if (url.pathname === '/api/guardian/access') {
            if (scenario === 'oidc-access-unavailable') return route.fulfill({ status: 503, json: { detail: 'Synthetic session lookup unavailable' } });
            const body = oidcAccess(oidcRole);
            if (scenario === 'oidc-invalid-access') body.permissions = ['read', 'resolve_incidents'];
            return route.fulfill({ json: body });
          }
          if (['POST', 'PUT'].includes(route.request().method())) {
            assert.equal(route.request().headers()['x-guardian-csrf'], csrfToken, 'OIDC mutation omitted current CSRF');
            assert.equal(route.request().headers().origin, origin, 'OIDC mutation has an unexpected Origin');
          }
          if (url.pathname === '/api/guardian/auth/logout') {
            if (scenario === 'oidc-logout-failed') return route.fulfill({ status: 503, json: { detail: 'Synthetic logout unavailable' } });
            oidcSession = false;
            return route.fulfill({ status: 204, headers: { 'set-cookie': 'guardian_session=; Max-Age=0; Path=/; HttpOnly; SameSite=Lax' } });
          }
        }
        if (url.pathname === '/api/guardian/access') {
          const key = route.request().headers()['x-guardian-key'];
          const expected = accessMode === 'rejected' ? 'browser-rejected-key'
            : accessMode === 'expired' ? 'browser-expired-key' : 'browser-smoke-key';
          assert(key === expected, `Access credential mismatch (${scenario}, ${accessMode}, ${route.request().method()}, ${key ? 'present' : 'missing'})`);
          if (accessMode === 'rejected' || accessMode === 'expired') {
            return route.fulfill({ status: 401, json: { detail: 'Synthetic credential rejection' } });
          }
          if (accessMode === 'unavailable') return route.fulfill({ status: 503, json: { detail: 'Synthetic access unavailable' } });
          if (accessMode === 'held') await accessGate;
          return route.fulfill({ json: validAccess });
        }
        if (authMode === 'api_key' && route.request().headers()['x-guardian-key'] !== 'browser-smoke-key') {
          const fullHeaders = await route.request().allHeaders();
          console.error(JSON.stringify({ diagnostic: 'protected_header_mismatch', scenario, path: url.pathname,
            method: route.request().method(), resource: route.request().resourceType(),
            navigation: route.request().isNavigationRequest(),
            abbreviated_header_present: !!route.request().headers()['x-guardian-key'],
            full_header_present: !!fullHeaders['x-guardian-key'],
            full_header_matches_fixture: fullHeaders['x-guardian-key'] === 'browser-smoke-key',
            aborted: route.request().failure()?.errorText === 'net::ERR_ABORTED' }));
          assert.fail(`Protected credential mismatch (${scenario}, ${url.pathname}, ${route.request().method()})`);
        }
        if (url.pathname === '/api/guardian/notifications') {
          assert.equal(route.request().method(), 'GET');
          if (scenario === 'notification-unavailable' || scenario === 'notification-incident-unavailable') {
            return route.fulfill({ status: 503, json: { detail: { code: 'notifications_unavailable' } } });
          }
          const body = notificationBody(url.searchParams.get('incident_id'));
          if (scenario === 'notification-malformed') body.destination = { ...body.destination, enabled: true, verified: false };
          return route.fulfill({ json: body });
        }
        if (url.pathname === '/api/guardian/notifications/actions') {
          assert.equal(route.request().method(), 'POST');
          assert.equal(authMode, 'oidc'); assert.equal(oidcRole, 'owner', 'Nonowner attempted notification mutation');
          const payload = route.request().postDataJSON();
          assert.deepEqual(Object.keys(payload).sort(), payload.action === 'retry'
            ? ['action', 'delivery_id', 'expected_revision', 'request_id'] : ['action', 'expected_revision', 'request_id']);
          assert.match(payload.request_id, /^[a-f0-9-]{36}$/i);
          assert(!notificationRequests.has(payload.request_id), 'Browser repeated a notification command');
          notificationRequests.add(payload.request_id);
          assert.equal(payload.expected_revision, notificationRevision, 'Notification action used unconfirmed revision');
          if (scenario === 'notification-conflict') {
            notificationRevision += 1;
            return route.fulfill({ status: 409, json: { detail: { code: 'notification_revision_conflict' } } });
          }
          notificationRevision += 1;
          if (payload.action === 'test') {
            if (notificationDestination.state === 'changed') {
              notificationDeliveries.forEach(row => { if (['queued', 'retrying'].includes(row.state)) Object.assign(row,
                { state: 'cancelled', next_attempt_at: null, last_outcome: 'destination_changed' }); });
              notificationDestination = { channel: 'slack', state: 'configured', enabled: false, verified: false };
            }
            notificationDeliveries.unshift(delivery(notificationRevision.toString(16).padStart(64, '0')));
          } else if (payload.action === 'enable') {
            assert(notificationDestination.verified); notificationDestination.enabled = true;
          } else if (payload.action === 'disable') {
            notificationDestination.enabled = false;
            notificationDeliveries.forEach(row => { if (row.kind === 'incident' && ['queued', 'retrying'].includes(row.state))
              Object.assign(row, { state: 'cancelled', next_attempt_at: null, can_retry: false, last_outcome: 'notifications_disabled' }); });
          } else if (payload.action === 'retry') {
            const row = notificationDeliveries.find(item => item.id === payload.delivery_id);
            assert(row?.can_retry); Object.assign(row, { state: 'queued', cycle: row.cycle + 1, next_attempt_at: now,
              last_outcome: 'retry_requested', can_retry: false });
          } else assert.fail('Unsupported synthetic notification action');
          if (scenario === 'notification-action-lost') return route.fulfill({ status: 503, json: { detail: { code: 'notifications_unavailable' } } });
          return route.fulfill({ json: notificationBody() });
        }
        if (url.pathname === '/api/guardian/monitoring-policy') {
          if (route.request().method() === 'GET') {
            if (scenario === 'policy-read-unavailable') return route.fulfill({ status: 503, json: { detail: { code: 'policy_unavailable' } } });
            if (scenario === 'policy-malformed') return route.fulfill({ json: { ...policyBody(), rules: { ...policyRules, max_call_cost_usd: -1 } } });
            return route.fulfill({ json: policyBody() });
          }
          assert.equal(route.request().method(), 'PUT');
          assert.equal(authMode, 'oidc'); assert.equal(oidcRole, 'owner', 'Nonowner attempted policy mutation');
          const payload = route.request().postDataJSON();
          assert.deepEqual(Object.keys(payload).sort(), ['expected_revision', 'rules']);
          assert.deepEqual(Object.keys(payload.rules).sort(), ['alert_on_errors', 'max_call_cost_usd', 'max_call_latency_ms']);
          assert.equal(payload.expected_revision, policyRevision, 'Policy save used an unconfirmed revision');
          if (scenario === 'policy-conflict') {
            policyRevision += 1; policyRules = { max_call_cost_usd: '0.08', max_call_latency_ms: 800, alert_on_errors: true };
            return route.fulfill({ status: 409, json: { detail: { code: 'policy_revision_conflict' } } });
          }
          policyRevision += 1; policyRules = { ...payload.rules };
          if (scenario === 'policy-save-lost') return route.fulfill({ status: 503, json: { detail: { code: 'policy_unavailable' } } });
          return route.fulfill({ json: policyBody() });
        }
        if (url.pathname === '/api/guardian/capture') {
          if (scenario === 'direct-capture-unavailable') return route.fulfill({ status: 503, json: { detail: 'Synthetic capture unavailable' } });
          return route.fulfill({ json: captureBody() });
        }
        if (url.pathname === '/api/guardian/ingestion-keys') {
          assert.equal(captureMode, 'direct');
          if (route.request().method() === 'GET') return route.fulfill({ json: { credentials: ingestionKeys } });
          assert.equal(oidcRole, 'owner', 'Nonowner attempted key creation');
          const body = route.request().postDataJSON();
          assert.match(body.request_id, /^[a-f0-9-]{36}$/);
          assert.equal(body.expires_in_days, 30); assert(body.label.length > 0 && body.label.length <= 80);
          const id = (++issuedCount).toString(16).padEnd(32, 'a');
          const credential = { id, label: body.label, prefix: `cg_ingest_${id.slice(0, 8)}`, status: 'active',
            created_at: now, expires_at: new Date(Date.now() + 30 * 86400000).toISOString(), revoked_at: null, last_used_at: null };
          const token = `cg_ingest_${id}_${'S'.repeat(43)}`;
          ingestionKeys.push(credential); issuedTokens.set(id, token);
          if (scenario === 'direct-create-lost') return route.fulfill({ status: 503, json: { detail: 'Synthetic lost response' } });
          return route.fulfill({ status: 201, json: { credential, token } });
        }
        if (url.pathname.startsWith('/api/guardian/ingestion-keys/') && url.pathname.endsWith('/revoke')) {
          assert.equal(oidcRole, 'owner', 'Nonowner attempted key revocation');
          const id = url.pathname.split('/').at(-2);
          const credential = ingestionKeys.find(item => item.id === id);
          assert(credential, 'Unknown synthetic credential');
          if (scenario === 'direct-revoke-failed') return route.fulfill({ status: 503, json: { detail: 'Synthetic revoke unavailable' } });
          credential.status = 'revoked'; credential.revoked_at = now; issuedTokens.delete(id);
          return route.fulfill({ json: { credential } });
        }
        if (url.pathname === '/api/guardian/monitoring' && scenario === 'setup-access-rejected') {
          return route.fulfill({ status: 401, json: { detail: 'Synthetic credential expiry' } });
        }
        if ((url.pathname === '/api/guardian/summary' && scenario === 'summary-failed')
          || (url.pathname === '/api/guardian/monitoring' && scenario === 'setup-unavailable')
          || (url.pathname === '/api/guardian/incidents' && ['incidents-failed', 'incidents-stale', 'incidents-filter-failed'].includes(scenario))) {
          return route.fulfill({ status: 503, json: { detail: 'Synthetic read unavailable' } });
        }
        let body;
        if (url.pathname === '/api/guardian/live') {
          if (scenario === 'failed') body = { available: true, degraded: true, reason: 'Synthetic source unavailable', stats: null, calls: [], runs: [], coverage: { status: 'failed' } };
          else if (scenario === 'rejected') body = { ...live, calls: [], stats: { ...stats, call_count: 0, unknown_status_count: 0, total_cost_usd: 0, known_cost_usd: 0, cost_known_count: 0, cost_unknown_count: 0, total_tokens: 0, known_total_tokens: 0, tokens_known_count: 0, tokens_unknown_count: 0, latency_known_count: 0, latency_unknown_count: 0, avg_latency_ms: null, p95_latency_ms: null }, coverage: { ...coverage, records_read: 1, observed_count: 0 } };
          else body = captureMode === 'direct' ? { ...live, source_kind: 'guardian_direct', source_api: 'direct-v1', source_api_version: 'direct-v1' } : live;
        } else if (url.pathname === '/api/guardian/live/runs/synthetic-empty-run') body = {
          id: 'synthetic-empty-run', name: 'Trace synthetic-empty-run', calls: [],
          window_hours: 168, observation_state: scenario === 'run-partial' ? 'undetermined' : 'not_observed',
          call_count: 0, error_count: 0, workflow_status: 'unknown', started_at: null,
          latency_ms: null, cost_usd: null, total_tokens: null, known_cost_usd: null,
          coverage: { ...coverage, status: scenario === 'run-partial' ? 'partial' : 'complete',
            reason: scenario === 'run-partial' ? 'invalid_observation' : null,
            observed_count: 0, records_read: scenario === 'run-partial' ? 1 : 0,
            invalid_count: scenario === 'run-partial' ? 1 : 0,
            window_start: new Date(Date.now() - 7 * 86400000).toISOString() },
        };
        else if (url.pathname === '/api/guardian/live/runs/synthetic-policy-run') body = {
          ...stats, id: 'synthetic-policy-run', name: 'Trace synthetic-policy-run', calls: [{ ...calls[0], trace_id: 'synthetic-policy-run', cost_usd: 0.08 }],
          window_hours: 168, observation_state: 'observed', workflow_status: 'unknown', status: 'unknown',
          call_count: 1, error_count: 0, unknown_status_count: 0, started_at: now, latency_ms: null,
          cost_usd: 0.08, known_cost_usd: 0.08, cost_known_count: 1, cost_unknown_count: 0,
          total_tokens: 20, known_total_tokens: 20, tokens_known_count: 1, tokens_unknown_count: 0,
          source_kind: 'guardian_direct', source_api: 'direct-v1', langfuse_url: null,
          coverage: { ...coverage, status: 'complete', reason: null, observed_count: 1, records_read: 1, invalid_count: 0 },
        };
        else if (url.pathname === '/api/guardian/summary') body = {
          overview: { open_incidents: scenario === 'summary-partial' ? 4 : 0,
            open_by_severity: {}, open_by_detector: {}, incidents_last_7_days: 0 },
          trends: scenario === 'summary-partial' ? [{ date: now.slice(0, 10), count: 0 }] : [],
          coverage: { status: scenario === 'summary-partial' ? 'partial' : 'complete',
            invalid_timestamp_count: scenario === 'summary-partial' ? 2 : 0 },
          as_of: now, timezone: 'UTC', window_start: new Date(Date.now() - 13 * 86400000).toISOString().slice(0, 10) + 'T00:00:00Z', window_end: now,
        };
        else if (url.pathname === '/api/guardian/overview') body = { open_incidents: 0, open_by_severity: {}, open_by_detector: {}, incidents_last_7_days: 0 };
        else if (url.pathname === '/api/guardian/incidents') body = scenario === 'incidents-ready' ? [incident] : [];
        else if (url.pathname === '/api/guardian/incidents/synthetic-incident') body = { ...currentIncident(), status: resolved ? 'resolved' : 'open' };
        else if (url.pathname === '/api/guardian/incidents/synthetic-incident/resolve') {
          assert(oidcRole !== 'viewer', 'Viewer UI attempted an incident mutation');
          resolved = true;
          body = { ...currentIncident(), status: 'resolved', resolved_at: now };
        }
        else if (url.pathname === '/api/guardian/metrics' && (scenario.startsWith('ledger-') || scenario === 'summary-partial')) body = [scenario !== 'ledger-pending'
          ? ledgerMetric : { ...ledgerMetric, total_cost_usd: null, known_cost_usd: null,
            cost_known_count: 0, cost_unknown_count: 1, conflict_count: 1 }];
        else if (url.pathname === '/api/guardian/monitoring' && scenario.startsWith('setup-')) {
          body = { ...ledgerMonitoring };
          if (scenario === 'setup-unconfigured' || scenario === 'setup-unchecked') body = {
            source_configured: scenario === 'setup-unchecked', healthy: false, stale: true,
            status: scenario === 'setup-unchecked' ? 'not_polled' : 'not_configured',
            read_status: null, source_watermark: null, processing_watermark: null,
            records_read: null, pages_fetched: null, pending_observations: null, dirty_buckets: null, quarantined_records: null,
          };
          else if (scenario === 'setup-empty') body = { ...body, records_read: 0 };
          else if (scenario === 'setup-pending') body = { ...body, healthy: false, status: 'pending', read_status: 'partial',
            read_error_code: 'quarantined_observations', processing_watermark: windowStart,
            pending_observations: 3, dirty_buckets: 2, quarantined_records: 1 };
          else if (scenario === 'setup-stale') body = { ...body, healthy: false, stale: true, status: 'stale' };
          else if (scenario === 'setup-unknown') body = {};
        }
        else if (url.pathname === '/api/guardian/monitoring') body = scenario.startsWith('ledger-') || scenario === 'summary-partial'
          ? (scenario !== 'ledger-pending' ? ledgerMonitoring : {
            ...ledgerMonitoring, healthy: false, status: 'pending', read_status: 'partial',
            read_error_code: 'quarantined_observations', last_successful_checkpoint: windowStart,
            processing_watermark: windowStart, pending_observations: 3, dirty_buckets: 2, quarantined_records: 1,
          })
          : { source_configured: true, healthy: false, stale: true, status: 'stale', last_successful_checkpoint: windowStart, read_status: 'complete' };
        else body = [];
        return route.fulfill({ json: body });
      }
      // No external destination is reachable, even if a build points at one.
      if (url.origin !== origin) return route.abort('blockedbyclient');
      return route.continue();
      } catch (error) {
        routeErrors.push(error.message);
        console.error(error.message);
        await route.abort('failed').catch(() => {});
      }
    });
    page = await context.newPage();
    let navigations = 0;
    page.on('framenavigated', frame => { if (frame === page.mainFrame()) navigations += 1; });
    page.on('pageerror', error => browserErrors.push(error.message));
    await page.goto(origin + '/live', { waitUntil: 'domcontentloaded' });
    await page.getByText('Partial observation coverage.', { exact: true }).waitFor();
    await page.getByText('retrieval-agent', { exact: true }).waitFor();
    assert.equal(seen[0].path, '/api/guardian/auth/config', 'Stored access started before auth mode discovery');
    assert.equal(seen[1].path, '/api/guardian/access', 'Protected reads started before restored access validation');
    assert((await page.locator('body').innerText()).includes('Unknown'));
    await page.screenshot({ path: path.join(reports, 'partial-desktop.png'), fullPage: true });
    await page.setViewportSize({ width: 390, height: 844 });
    await page.screenshot({ path: path.join(reports, 'partial-mobile.png'), fullPage: true });

    scenario = 'rejected';
    await page.reload();
    await page.getByText('Partial observation coverage.', { exact: true }).waitFor();
    const rejectedText = await page.locator('body').innerText();
    assert(rejectedText.includes('Unknown'));
    assert(!rejectedText.includes('No LLM calls were returned'));
    assert(!rejectedText.includes('$0.00'));

    scenario = 'failed';
    await page.reload();
    await page.getByText('Telemetry is unavailable.', { exact: true }).waitFor();
    assert(!(await page.locator('body').innerText()).includes('No LLM calls were returned'));
    await page.screenshot({ path: path.join(reports, 'unavailable-mobile.png'), fullPage: true });
    await page.goto(origin + '/');
    await page.getByText('Ingestion needs attention: stale.', { exact: true }).waitFor();
    await page.screenshot({ path: path.join(reports, 'monitoring-mobile.png'), fullPage: true });

    scenario = 'run-empty';
    await page.goto(origin + '/runs/synthetic-empty-run');
    await page.getByText('No generation calls observed in this query window. This does not establish that the trace is missing.', { exact: true }).waitFor();
    assert(!(await page.locator('body').innerText()).includes('$0.00'));
    assert((await page.locator('body').innerText()).includes('last 168 hours'));
    await page.screenshot({ path: path.join(reports, 'empty-run-mobile.png'), fullPage: true });
    scenario = 'run-partial';
    await page.reload();
    await page.getByText('No accepted generation calls could be established from this partial read. Trace existence remains undetermined.', { exact: true }).waitFor();
    assert(!(await page.locator('body').innerText()).includes('No generation calls observed in this query window.'));
    await page.screenshot({ path: path.join(reports, 'partial-run-mobile.png'), fullPage: true });

    scenario = 'ledger-healthy';
    await page.goto(origin + '/');
    await page.getByText(ledgerCoverageText, { exact: true }).waitFor();
    await page.getByText(`Last successful ingestion checkpoint: ${now}.`, { exact: true }).waitFor();
    const healthySpend = await page.getByText('Known recorded spend (48h)', { exact: true }).locator('..').innerText();
    assert(healthySpend.includes('$0.75'));
    assert(healthySpend.includes('1 recorded calls; 0 with unknown cost'));
    const healthyText = await page.locator('body').innerText();
    assert(!healthyText.includes('Hourly accounting is provisional.'));
    assert(!healthyText.includes('Ingestion needs attention:'));
    assert(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), 'Healthy mobile overview overflows horizontally');
    await page.screenshot({ path: path.join(reports, 'ledger-healthy-mobile.png'), fullPage: true });

    scenario = 'ledger-pending';
    await page.reload();
    await page.getByText(ledgerCoverageText, { exact: true }).waitFor();
    await page.getByText('Ingestion needs attention: pending.', { exact: true }).waitFor();
    const pendingText = await page.locator('body').innerText();
    assert(pendingText.includes('3 observations await checks; 2 hourly totals await rebuilding.'));
    assert(pendingText.includes('1 rejected or conflicting records need review. Totals may be incomplete.'));
    assert(pendingText.includes(`Last successful ingestion checkpoint: ${windowStart}.`));
    assert(!pendingText.includes('Hourly accounting is provisional.'));
    const pendingSpend = await page.getByText('Known recorded spend (48h)', { exact: true }).locator('..').innerText();
    assert(pendingSpend.includes('Unknown'));
    assert(pendingSpend.includes('1 recorded calls; 1 with unknown cost'));
    assert(!pendingSpend.includes('$0.00') && !pendingSpend.includes('$0.75'));
    assert(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), 'Pending mobile overview overflows horizontally');
    await page.screenshot({ path: path.join(reports, 'ledger-pending-mobile.png'), fullPage: true });

    scenario = 'summary-partial';
    await page.reload();
    await page.getByText('Recent incident count incomplete', { exact: true }).waitFor();
    const partialSummaryText = await page.locator('body').innerText();
    assert(partialSummaryText.includes('2 incidents have invalid timestamps.'));
    assert(partialSummaryText.includes('Open counts remain available; recent counts and daily trends are incomplete.'));
    assert(partialSummaryText.includes('Chart dates and hours are UTC; the current hour and today are partial.'));
    assert(partialSummaryText.includes('Last 14 UTC calendar days, including today (partial).'));
    assert(!partialSummaryText.includes('0 in the last 7'));
    assert(partialSummaryText.includes('peak 0'));
    assert(!partialSummaryText.includes('peak 1'));
    await page.screenshot({ path: path.join(reports, 'partial-summary-mobile.png'), fullPage: true });

    scenario = 'summary-failed';
    await page.reload();
    await page.getByText('Could not load Guardian data. Traffic and cost totals are unavailable.', { exact: true }).waitFor();
    assert(!(await page.locator('body').innerText()).includes('Open incidents'));

    scenario = 'incidents-empty';
    await page.goto(origin + '/incidents', { waitUntil: 'domcontentloaded' });
    await page.getByText('No open incidents', { exact: true }).waitFor();
    assert.equal(await page.getByRole('alert').count(), 0);

    scenario = 'incidents-failed';
    await page.reload();
    await page.getByRole('alert').getByText('Could not load incidents.', { exact: true }).waitFor();
    assert(!(await page.locator('body').innerText()).includes('No open incidents'));
    await page.screenshot({ path: path.join(reports, 'incidents-unavailable-mobile.png'), fullPage: true });
    scenario = 'incidents-ready';
    await page.getByRole('button', { name: 'Retry incidents', exact: true }).click();
    await page.getByText(incident.title, { exact: true }).waitFor();
    assert.equal(await page.getByRole('alert').count(), 0);

    scenario = 'incidents-stale';
    await page.evaluate(() => document.dispatchEvent(new Event('visibilitychange')));
    await page.getByRole('alert').getByText('Could not refresh incidents.', { exact: true }).waitFor();
    assert((await page.locator('body').innerText()).includes('Showing the last successful response for this filter from'));
    assert((await page.locator('body').innerText()).includes(incident.title));
    await page.screenshot({ path: path.join(reports, 'incidents-stale-mobile.png'), fullPage: true });

    scenario = 'incidents-filter-failed';
    await page.getByRole('button', { name: 'Resolved', exact: true }).click();
    await page.getByRole('alert').getByText('Could not load incidents.', { exact: true }).waitFor();
    const failedFilterText = await page.locator('body').innerText();
    assert(!failedFilterText.includes(incident.title));
    assert(!failedFilterText.includes('No resolved incidents'));
    assert(!failedFilterText.includes('Showing the last successful response'));
    assert.equal(await page.getByRole('button', { name: 'Resolved', exact: true }).getAttribute('aria-pressed'), 'true');
    scenario = 'incidents-empty';
    await page.getByRole('button', { name: 'Retry incidents', exact: true }).click();
    await page.getByText('No resolved incidents', { exact: true }).waitFor();
    assert.equal(await page.getByRole('alert').count(), 0);

    scenario = 'setup-unconfigured';
    await page.goto(origin + '/setup');
    await page.getByRole('heading', { name: 'Setup and monitoring', exact: true }).waitFor();
    await page.getByText('Local shared-key access shows monitoring rules read-only.', { exact: true }).waitFor();
    assert.equal(await page.getByRole('form', { name: 'Edit monitoring rules' }).count(), 0);
    await page.getByText('Not configured', { exact: true }).waitFor();
    assert((await page.locator('body').innerText()).includes('source modes cannot be switched here'));
    assert(!(await page.locator('body').innerText()).includes('Worker diagnostics are stale.'));
    assert.equal(await page.locator('input').count(), 0);
    assert(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), 'Setup mobile view overflows horizontally');
    await page.screenshot({ path: path.join(reports, 'setup-unconfigured-mobile.png'), fullPage: true });

    scenario = 'setup-unchecked';
    await page.reload();
    await page.getByText('No source read has been reported yet.', { exact: true }).waitFor();
    assert((await page.locator('body').innerText()).includes('This alone does not verify source access or arriving traffic.'));
    assert((await page.locator('body').innerText()).includes('No successful source checkpoint is recorded'));
    assert(!(await page.locator('body').innerText()).includes('Worker diagnostics are stale.'));

    scenario = 'setup-empty';
    await page.reload();
    await page.getByText('The latest successful read returned no observations. This does not establish that the project has never had traffic.', { exact: true }).waitFor();
    await page.screenshot({ path: path.join(reports, 'setup-empty-mobile.png'), fullPage: true });

    scenario = 'setup-pending';
    await page.reload();
    await page.getByText('Work pending', { exact: true }).waitFor();
    const setupDetail = async label => page.getByText(label, { exact: true }).locator('..').locator('dd').innerText();
    assert.equal(await setupDetail('Observations awaiting checks'), '3');
    assert.equal(await setupDetail('Hourly totals awaiting rebuild'), '2');
    assert.equal(await setupDetail('Rejected or conflicting records'), '1');
    assert.notEqual(await setupDetail('Last source checkpoint'), await setupDetail('Last processing checkpoint'));
    await page.screenshot({ path: path.join(reports, 'setup-pending-mobile.png'), fullPage: true });

    scenario = 'setup-stale';
    await page.reload();
    await page.getByText('Worker diagnostics are stale.', { exact: true }).waitFor();
    assert((await page.locator('body').innerText()).includes('Saved checkpoints do not establish current monitoring health.'));

    scenario = 'setup-unknown';
    await page.reload();
    await page.getByText('Source configuration could not be established from these diagnostics.', { exact: true }).waitFor();
    assert.equal(await setupDetail('Observations awaiting checks'), 'Unknown');

    scenario = 'setup-unavailable';
    await page.reload();
    await page.getByRole('alert').getByText('Monitoring diagnostics are unavailable.', { exact: true }).waitFor();
    assert.equal(await page.evaluate(() => localStorage.getItem('guardian_api_key')), 'browser-smoke-key');
    await page.screenshot({ path: path.join(reports, 'setup-unavailable-mobile.png'), fullPage: true });
    scenario = 'setup-pending';
    await page.getByRole('button', { name: 'Retry setup check', exact: true }).click();
    await page.getByText('Work pending', { exact: true }).waitFor();
    assert.equal(await page.getByRole('alert').count(), 0);

    const beforeDisconnect = navigations;
    await page.getByRole('button', { name: 'Disconnect', exact: true }).click();
    await page.getByLabel('Guardian API key', { exact: true }).waitFor();
    assert.equal(navigations, beforeDisconnect, 'Disconnect depended on a page reload');
    assert.equal(await page.evaluate(() => localStorage.getItem('guardian_api_key')), null);
    assert.equal(await page.getByRole('heading', { name: 'Setup and monitoring', exact: true }).count(), 0);

    accessMode = 'rejected';
    let beforeAccess = seen.length;
    await page.getByLabel('Guardian API key', { exact: true }).fill('browser-rejected-key');
    await page.getByRole('button', { name: 'Connect', exact: true }).click();
    await page.getByRole('alert').getByText('That key was rejected by the Guardian API.', { exact: true }).waitFor();
    assert.equal(await page.evaluate(() => localStorage.getItem('guardian_api_key')), null, 'Rejected candidate was persisted');
    assert(seen.slice(beforeAccess).every(request => request.path === '/api/guardian/access'), 'Rejected candidate mounted protected data');
    await page.screenshot({ path: path.join(reports, 'connect-rejected-mobile.png'), fullPage: true });

    accessMode = 'held';
    let releaseAccess;
    accessGate = new Promise(resolve => { releaseAccess = resolve; });
    await page.getByLabel('Guardian API key', { exact: true }).fill('browser-smoke-key');
    await page.getByRole('button', { name: 'Connect', exact: true }).click();
    await page.getByRole('button', { name: 'Connecting...', exact: true }).waitFor();
    assert.equal(await page.evaluate(() => localStorage.getItem('guardian_api_key')), null, 'Unverified candidate was persisted');
    assert.equal(await page.getByRole('heading', { name: 'Setup and monitoring', exact: true }).count(), 0);
    accessMode = 'valid';
    releaseAccess();
    await page.getByRole('heading', { name: 'Setup and monitoring', exact: true }).waitFor();
    await page.getByText('Work pending', { exact: true }).waitFor();
    assert.equal(new URL(page.url()).pathname, '/setup', 'Verified access lost requested deep link');
    assert.equal(await page.evaluate(() => localStorage.getItem('guardian_api_key')), 'browser-smoke-key');

    accessMode = 'expired';
    await page.evaluate(() => localStorage.setItem('guardian_api_key', 'browser-expired-key'));
    beforeAccess = seen.length;
    await page.reload();
    await page.getByRole('alert').getByText('That key was rejected by the Guardian API.', { exact: true }).waitFor();
    assert.equal(await page.evaluate(() => localStorage.getItem('guardian_api_key')), null, 'Rejected restored key was retained');
    assert(seen.slice(beforeAccess).every(request => ['/api/guardian/access', '/api/guardian/auth/config'].includes(request.path)), 'Expired restored key mounted protected data');

    accessMode = 'unavailable';
    await page.evaluate(() => localStorage.setItem('guardian_api_key', 'browser-smoke-key'));
    beforeAccess = seen.length;
    await page.reload();
    await page.getByRole('button', { name: 'Retry access', exact: true }).waitFor();
    assert.equal(await page.evaluate(() => localStorage.getItem('guardian_api_key')), 'browser-smoke-key', 'Transient access failure erased stored key');
    assert.equal(await page.getByRole('heading', { name: 'Setup and monitoring', exact: true }).count(), 0);
    assert(seen.slice(beforeAccess).every(request => ['/api/guardian/access', '/api/guardian/auth/config'].includes(request.path)), 'Unavailable access mounted protected data');
    await page.screenshot({ path: path.join(reports, 'access-unavailable-mobile.png'), fullPage: true });

    // Valid access remains usable while a separately queried summary is partial.
    scenario = 'summary-partial';
    await page.goto(origin + '/');
    await page.getByRole('button', { name: 'Retry access', exact: true }).waitFor();
    accessMode = 'valid';
    await page.getByRole('button', { name: 'Retry access', exact: true }).click();
    await page.getByText('Recent incident count incomplete', { exact: true }).waitFor();
    assert.equal(await page.getByLabel('Guardian API key', { exact: true }).count(), 0);
    assert.equal(await page.evaluate(() => localStorage.getItem('guardian_api_key')), 'browser-smoke-key');

    scenario = 'setup-access-rejected';
    await page.goto(origin + '/setup');
    await page.getByLabel('Guardian API key', { exact: true }).waitFor();
    await page.getByRole('alert').getByText('Access was rejected. Connect again to continue.', { exact: true }).waitFor();
    assert.equal(await page.evaluate(() => localStorage.getItem('guardian_api_key')), null);
    assert.equal(await page.getByRole('heading', { name: 'Setup and monitoring', exact: true }).count(), 0);

    // A real browser storage event in another tab must unmount this tab's data.
    scenario = 'setup-empty';
    await page.getByLabel('Guardian API key', { exact: true }).fill('browser-smoke-key');
    await page.getByRole('button', { name: 'Connect', exact: true }).click();
    await page.getByRole('heading', { name: 'Setup and monitoring', exact: true }).waitFor();
    const secondTab = await context.newPage();
    secondTab.on('pageerror', error => browserErrors.push(error.message));
    await secondTab.goto(origin + '/setup');
    await secondTab.getByRole('heading', { name: 'Setup and monitoring', exact: true }).waitFor();
    await secondTab.getByRole('button', { name: 'Disconnect', exact: true }).click();
    await secondTab.getByLabel('Guardian API key', { exact: true }).waitFor();
    await page.getByLabel('Guardian API key', { exact: true }).waitFor();
    assert.equal(await page.getByRole('heading', { name: 'Setup and monitoring', exact: true }).count(), 0);
    await secondTab.close();

    scenario = 'config-unavailable';
    beforeAccess = seen.length;
    await page.reload();
    await page.getByText('Could not load Guardian sign-in configuration. Retry when the service is available.', { exact: true }).waitFor();
    assert(seen.slice(beforeAccess).every(request => request.path === '/api/guardian/auth/config'));
    assert.equal(await page.locator('input').count(), 0);

    authMode = 'oidc';
    scenario = 'oidc-entry';
    await page.evaluate(() => localStorage.setItem('guardian_api_key', 'browser-legacy-key-not-for-oidc'));
    await context.addInitScript(() => {
      window.guardianLegacyKeyReads = 0;
      const getItem = Storage.prototype.getItem;
      Storage.prototype.getItem = function (key) {
        if (key === 'guardian_api_key') window.guardianLegacyKeyReads += 1;
        return getItem.call(this, key);
      };
    });
    await page.goto(origin + '/incidents/synthetic-incident', { waitUntil: 'domcontentloaded' });
    await page.getByRole('button', { name: 'Sign in with your organization', exact: true }).waitFor();
    assert.equal(await page.locator('input').count(), 0);
    assert.equal(await page.evaluate(() => window.guardianLegacyKeyReads), 0);
    await page.screenshot({ path: path.join(reports, 'oidc-entry-mobile.png'), fullPage: true });

    scenario = 'oidc-viewer';
    await page.getByRole('button', { name: 'Sign in with your organization', exact: true }).click();
    await page.getByRole('heading', { name: incident.title, exact: true }).waitFor();
    assert.equal(new URL(page.url()).pathname, '/incidents/synthetic-incident');
    assert.equal(await page.getByRole('button', { name: 'Mark resolved', exact: true }).count(), 0);
    assert((await page.locator('body').innerText()).includes('Synthetic Member · viewer'));
    assert((await page.locator('body').innerText()).includes('Synthetic Project · test'));
    assert(!(await page.locator('body').innerText()).includes(csrfToken));
    assert(!(await page.evaluate(() => document.cookie)).includes('guardian_session'));
    assert.equal(await page.evaluate(() => window.guardianLegacyKeyReads), 0);
    assert.equal(await page.evaluate(() => sessionStorage.getItem('guardian_login_return')), null);
    assert(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), 'Viewer mobile incident detail overflows horizontally');
    await page.screenshot({ path: path.join(reports, 'oidc-viewer-mobile.png'), fullPage: true });

    oidcRole = 'operator';
    scenario = 'oidc-operator';
    await page.reload();
    await page.getByRole('button', { name: 'Mark resolved', exact: true }).waitFor();
    await page.screenshot({ path: path.join(reports, 'oidc-operator-mobile.png'), fullPage: true });
    assert(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), 'Operator mobile incident detail overflows horizontally');
    await page.getByRole('button', { name: 'Mark resolved', exact: true }).click();
    await page.getByText('resolved', { exact: true }).waitFor();
    assert.equal(await page.getByRole('button', { name: 'Mark resolved', exact: true }).count(), 0);
    assert(seen.some(request => request.scenario === scenario && request.path.endsWith('/resolve')));
    assert.equal(await page.evaluate(() => window.guardianLegacyKeyReads), 0);

    scenario = 'oidc-logout-failed';
    const beforeOidcLogout = navigations;
    await page.getByRole('button', { name: 'Sign out', exact: true }).click();
    await page.getByRole('button', { name: 'Retry sign-out', exact: true }).waitFor();
    assert(!(await page.locator('body').innerText()).includes(incident.title));
    assert((await page.locator('body').innerText()).includes('session may still be active'));
    assert(oidcSession, 'A failed synthetic logout revoked the fixture session');
    assert.equal(navigations, beforeOidcLogout, 'OIDC logout depended on reloading');
    await page.screenshot({ path: path.join(reports, 'oidc-logout-failed-mobile.png'), fullPage: true });
    scenario = 'oidc-logout-retry';
    await page.getByRole('button', { name: 'Retry sign-out', exact: true }).click();
    await page.getByRole('button', { name: 'Sign in with your organization', exact: true }).waitFor();
    assert(!oidcSession);
    assert.equal(await page.evaluate(() => localStorage.guardian_api_key), 'browser-legacy-key-not-for-oidc');

    scenario = 'oidc-expired-data';
    await page.getByRole('button', { name: 'Sign in with your organization', exact: true }).click();
    await page.getByRole('heading', { name: incident.title, exact: true }).waitFor();
    await page.getByRole('link', { name: 'Setup', exact: true }).click();
    await page.getByText('Your Guardian session has ended. Sign in again to continue.', { exact: true }).waitFor();
    assert.equal(await page.getByRole('heading', { name: 'Setup and monitoring', exact: true }).count(), 0);
    assert.equal(await page.evaluate(() => window.guardianLegacyKeyReads), 0);

    scenario = 'oidc-access-unavailable';
    await page.reload();
    await page.getByRole('button', { name: 'Retry access', exact: true }).waitFor();
    assert.equal(await page.getByRole('heading', { name: 'Setup and monitoring', exact: true }).count(), 0);
    assert.equal(await page.getByRole('button', { name: 'Use a different key', exact: true }).count(), 0);
    scenario = 'setup-empty';
    await page.getByRole('button', { name: 'Retry access', exact: true }).click();
    await page.getByRole('heading', { name: 'Setup and monitoring', exact: true }).waitFor();

    oidcRole = 'viewer';
    scenario = 'oidc-invalid-access';
    await page.reload();
    await page.getByRole('button', { name: 'Retry access', exact: true }).waitFor();
    assert.equal(await page.getByRole('heading', { name: 'Setup and monitoring', exact: true }).count(), 0);
    assert.equal(await page.getByRole('button', { name: 'Use a different key', exact: true }).count(), 0);

    scenario = 'oidc-unsafe-return';
    await page.evaluate(() => sessionStorage.setItem('guardian_login_return', '//outside.invalid/steal'));
    await page.goto(origin + '/?guardian_login=complete', { waitUntil: 'domcontentloaded' });
    await page.getByText('Open incidents', { exact: true }).waitFor();
    assert.equal(page.url(), origin + '/');
    assert.equal(await page.evaluate(() => sessionStorage.getItem('guardian_login_return')), null);
    assert.equal(await page.evaluate(() => window.guardianLegacyKeyReads), 0);

    scenario = 'oidc-failed-callback';
    await page.evaluate(() => sessionStorage.setItem('guardian_login_return', '/incidents/synthetic-incident'));
    beforeAccess = seen.length;
    await page.goto(origin + '/?guardian_login=failed', { waitUntil: 'domcontentloaded' });
    await page.getByText('Sign-in could not be completed. Try signing in again.', { exact: true }).waitFor();
    assert(seen.slice(beforeAccess).every(request => request.path === '/api/guardian/auth/config'));

    scenario = 'setup-empty';
    await page.getByRole('button', { name: 'Sign in with your organization', exact: true }).click();
    await page.getByRole('heading', { name: incident.title, exact: true }).waitFor();
    assert.equal(new URL(page.url()).pathname, '/incidents/synthetic-incident', 'Failed-login retry lost its original safe deep link');
    await page.getByRole('link', { name: 'Overview', exact: true }).click();
    await page.getByText('Open incidents', { exact: true }).waitFor();
    const oidcTab = await context.newPage();
    oidcTab.on('pageerror', error => browserErrors.push(error.message));
    await oidcTab.goto(origin + '/setup', { waitUntil: 'domcontentloaded' });
    await oidcTab.getByRole('heading', { name: 'Setup and monitoring', exact: true }).waitFor();
    await oidcTab.getByRole('button', { name: 'Sign out', exact: true }).click();
    await oidcTab.getByRole('button', { name: 'Sign in with your organization', exact: true }).waitFor();
    await page.getByRole('button', { name: 'Sign in with your organization', exact: true }).waitFor();
    assert.equal(await page.getByText('Open incidents', { exact: true }).count(), 0);
    assert.equal(await page.evaluate(() => window.guardianLegacyKeyReads), 0);
    await oidcTab.close();

    captureMode = 'direct'; oidcRole = 'owner'; scenario = 'direct-owner';
    await page.getByRole('button', { name: 'Sign in with your organization', exact: true }).click();
    await page.getByText('Open incidents', { exact: true }).waitFor();
    await page.getByRole('link', { name: 'Setup', exact: true }).click();
    await page.getByRole('heading', { name: 'Send events directly', exact: true }).waitFor();
    await page.getByRole('button', { name: 'Create ingestion key', exact: true }).waitFor();
    assert((await page.locator('body').innerText()).includes('No real event receipt is recorded'));
    assert((await page.locator('body').innerText()).includes('Worker has not reported yet'));
    assert(!(await page.locator('body').innerText()).includes('Last source checkpoint'));
    assert(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), 'Direct owner mobile setup overflows horizontally');
    await page.screenshot({ path: path.join(reports, 'direct-owner-mobile.png'), fullPage: true });

    scenario = 'provider-recipes';
    const providerHeading = page.getByRole('heading', { name: 'Connect your OpenAI calls', exact: true });
    await providerHeading.waitFor();
    const providerCard = providerHeading.locator('..').locator('..');
    const recipe = page.getByLabel('OpenAI integration code', { exact: true });
    const providerApi = page.getByLabel('OpenAI API', { exact: true });
    const streamingRecipe = page.getByLabel('Streaming response', { exact: true });
    await page.getByText('Token usage is reported; USD cost stays unknown.', { exact: true }).waitFor();
    assert.equal(await page.getByRole('tab', { name: 'Python', exact: true }).getAttribute('aria-selected'), 'true');
    assert((await recipe.innerText()).includes('openai_call'));
    const advanced = page.getByText('Advanced: Guardian JSON version 1 · Node fetch example', { exact: true });
    assert.equal(await advanced.locator('..').getAttribute('open'), null);
    const recipeVariants = new Set();
    for (const language of ['Python', 'Node']) {
      await page.getByRole('tab', { name: language, exact: true }).click();
      for (const api of ['responses', 'chat_completions']) {
        await providerApi.selectOption(api);
        for (const streaming of [false, true]) {
          await streamingRecipe.setChecked(streaming);
          const code = await recipe.innerText();
          assert(code.includes(language === 'Python' ? (streaming ? 'openai_stream' : 'openai_call') : (streaming ? 'openaiStream' : 'openaiCall')));
          assert(code.includes(api === 'responses' ? 'responses.create' : 'chat.completions.create'));
          if (api === 'chat_completions' && streaming) assert(code.includes('include_usage'));
          assert(![...issuedTokens.values()].some(token => code.includes(token)));
          assert(!code.includes('browser-smoke-key') && !code.includes(csrfToken));
          recipeVariants.add(code);
        }
      }
    }
    assert.equal(recipeVariants.size, 8);
    assert(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), 'Provider recipe overflows mobile');
    await providerCard.screenshot({ path: path.join(reports, 'provider-node-chat-stream-mobile.png') });
    await context.grantPermissions(['clipboard-read', 'clipboard-write'], { origin });
    await page.getByRole('button', { name: 'Copy integration code', exact: true }).click();
    await page.getByText('Integration code copied. Adapt it at your existing application call site.', { exact: true }).waitFor();
    // Windows clipboard storage canonicalizes line endings to CRLF.
    assert.equal((await page.evaluate(() => navigator.clipboard.readText())).replace(/\r\n/g, '\n'), await recipe.innerText());
    await advanced.click();
    assert.notEqual(await advanced.locator('..').getAttribute('open'), null);
    assert((await advanced.locator('..').innerText()).includes('HTTP 202 is durable receipt, not completed processing or monitoring readiness.'));
    await advanced.click();
    await page.getByRole('tab', { name: 'Python', exact: true }).click();
    await providerApi.selectOption('responses'); await streamingRecipe.setChecked(false);
    assert.equal(seen.filter(request => request.scenario === scenario && request.method === 'POST').length, 0,
      'Reading or copying provider recipes sent application traffic');
    await page.setViewportSize({ width: 1280, height: 1000 });
    await providerCard.screenshot({ path: path.join(reports, 'provider-python-responses-desktop.png') });
    await page.setViewportSize({ width: 390, height: 844 });

    scenario = 'direct-create';
    await page.getByLabel('Key label', { exact: true }).fill('server-main');
    await page.getByRole('button', { name: 'Create ingestion key', exact: true }).click();
    await page.getByLabel('One-time ingestion key', { exact: true }).waitFor();
    const shownKey = await page.getByLabel('One-time ingestion key', { exact: true }).inputValue();
    assert.match(shownKey, /^cg_ingest_[a-f0-9]{32}_[A-Za-z0-9_-]{43}$/);
    assert(!(await page.evaluate(() => JSON.stringify({ local: { ...localStorage }, session: { ...sessionStorage } }))).includes(shownKey));
    assert(!(await page.locator('pre').allTextContents()).join('\n').includes(shownKey));
    scenario = 'direct-test';
    await page.getByRole('button', { name: 'Send test event', exact: true }).click();
    await page.getByText('Test event received. This handshake creates no production observations, totals or incidents and does not verify real application traffic.', { exact: true }).waitFor();
    assert.equal(captureStatus.received_events, 0); assert.equal(captureStatus.processed_events, 0);
    await page.getByRole('button', { name: 'Dismiss key', exact: true }).click();
    assert.equal(await page.getByLabel('One-time ingestion key', { exact: true }).count(), 0);
    assert(!(await page.locator('body').innerText()).includes(shownKey));
    await page.screenshot({ path: path.join(reports, 'direct-test-only-mobile.png'), fullPage: true });

    scenario = 'direct-revoke-failed';
    await page.getByRole('button', { name: 'Revoke server-main', exact: true }).click();
    await page.getByText('Revocation was not confirmed. The key may still accept events. Refresh the list and retry revocation if needed.', { exact: true }).waitFor();
    assert.equal(ingestionKeys[0].status, 'active');
    scenario = 'direct-revoke-retry';
    await page.getByRole('button', { name: 'Revoke server-main', exact: true }).click();
    await page.getByText(ingestionKeys[0].prefix + ' · revoked', { exact: true }).waitFor();

    scenario = 'direct-create-lost';
    await page.getByLabel('Key label', { exact: true }).fill('lost-key');
    await page.getByRole('button', { name: 'Create ingestion key', exact: true }).click();
    await page.getByText('Key creation was not confirmed. A key may have been created, but its secret cannot be recovered. Refresh the list, compare label and creation time, and revoke any unrecoverable key before creating another.', { exact: true }).waitFor();
    await page.getByRole('button', { name: 'Revoke lost-key', exact: true }).waitFor();
    assert.equal(await page.getByLabel('One-time ingestion key', { exact: true }).count(), 0);
    assert.equal(seen.filter(request => request.scenario === scenario && request.path === '/api/guardian/ingestion-keys' && request.method === 'POST').length, 1);
    assert(await page.getByRole('button', { name: 'Create ingestion key', exact: true }).isDisabled());
    scenario = 'direct-lost-recovery';
    await page.getByRole('button', { name: 'Revoke lost-key', exact: true }).click();
    await page.getByText(ingestionKeys[1].prefix + ' · revoked', { exact: true }).waitFor();
    await page.getByRole('button', { name: 'I reviewed the key list', exact: true }).click();
    assert(!(await page.getByRole('button', { name: 'Create ingestion key', exact: true }).isDisabled()));

    scenario = 'direct-secret-focus';
    await page.getByLabel('Key label', { exact: true }).fill('focus-key');
    await page.getByRole('button', { name: 'Create ingestion key', exact: true }).click();
    await page.getByLabel('One-time ingestion key', { exact: true }).waitFor();
    await page.evaluate(() => window.dispatchEvent(new Event('focus')));
    await page.getByRole('heading', { name: 'Send events directly', exact: true }).waitFor();
    assert.equal(await page.getByLabel('One-time ingestion key', { exact: true }).count(), 0);

    scenario = 'direct-viewer'; oidcRole = 'viewer';
    await page.reload();
    await page.getByText('focus-key', { exact: true }).waitFor();
    assert.equal(await page.getByRole('button', { name: 'Create ingestion key', exact: true }).count(), 0);
    assert.equal(await page.getByRole('button', { name: 'Revoke focus-key', exact: true }).count(), 0);

    scenario = 'direct-pending';
    Object.assign(captureStatus, { last_received_at: now, received_events: 3, pending_events: 2,
      processed_events: 1, conflicted_events: 1, last_processed_at: now, worker_status: 'stale' });
    await page.getByRole('button', { name: 'Retry setup check', exact: true }).click();
    await page.getByText('Worker heartbeat is stale', { exact: true }).waitFor();
    const captureDetail = async label => page.getByText(label, { exact: true }).locator('..').locator('dd').innerText();
    assert.equal(await captureDetail('Events awaiting processing'), '2');
    assert.equal(await captureDetail('Processed events'), '1');
    assert.equal(await captureDetail('Conflicted events'), '1');
    assert(!(await page.locator('body').innerText()).includes('Monitoring is active'));
    assert(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), 'Direct pending mobile setup overflows horizontally');
    await page.screenshot({ path: path.join(reports, 'direct-pending-mobile.png'), fullPage: true });

    scenario = 'direct-processed';
    Object.assign(captureStatus, { pending_events: 0, processed_events: 3, conflicted_events: 0, worker_status: 'current' });
    await page.getByRole('button', { name: 'Retry setup check', exact: true }).click();
    await page.getByText('Recent worker heartbeat', { exact: true }).waitFor();
    assert.equal(await captureDetail('Processed events'), '3');
    scenario = 'direct-capture-unavailable';
    await page.getByRole('button', { name: 'Retry setup check', exact: true }).click();
    await page.getByText('These are previously fetched capture details. Current receipt and processing state is unknown.', { exact: true }).waitFor();
    assert.equal(await captureDetail('Processed events'), '3');
    scenario = 'direct-live';
    await page.getByRole('link', { name: 'Live activity', exact: true }).click();
    await page.getByText(/Completed LLM calls captured directly by Guardian/).waitFor();
    assert(!(await page.locator('body').innerText()).includes('Observed LLM generations from Langfuse'));

    scenario = 'policy-owner'; oidcRole = 'owner';
    await page.goto(origin + '/setup', { waitUntil: 'domcontentloaded' });
    await page.getByText('Default monitoring rules', { exact: true }).waitFor();
    const costInput = page.getByLabel('Maximum cost per call (USD)', { exact: true });
    const latencyInput = page.getByLabel('Maximum duration per call (milliseconds)', { exact: true });
    const saveRules = page.getByRole('button', { name: 'Save monitoring rules', exact: true });
    const reloadRules = page.getByRole('button', { name: 'Reload saved rules', exact: true });
    assert.equal(await costInput.inputValue(), '');
    assert(await saveRules.isDisabled());
    await costInput.fill('-1');
    await page.getByText('Use a nonnegative USD decimal with up to 12 decimal places and a whole-number duration within the allowed range.', { exact: true }).waitFor();
    assert(await saveRules.isDisabled());
    assert(!seen.some(request => request.scenario === scenario && request.method === 'PUT'));
    await costInput.fill('0'); await latencyInput.fill('0');
    await page.getByLabel('Create incidents for reported call errors', { exact: true }).uncheck();
    scenario = 'policy-save-zero';
    await saveRules.click();
    await page.getByText('Monitoring rules saved as revision 1.', { exact: true }).waitFor();
    assert.deepEqual(policyRules, { max_call_cost_usd: '0', max_call_latency_ms: 0, alert_on_errors: false });
    await page.getByText('Above $0 USD', { exact: true }).waitFor();
    assert((await page.locator('body').innerText()).includes('These rules create incidents; notification delivery is configured separately, and spending limits are not enforced.'));
    assert(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), 'Owner policy editor overflows on mobile');
    await page.screenshot({ path: path.join(reports, 'policy-owner-zero-mobile.png'), fullPage: true });
    await page.locator('[aria-labelledby="monitoring-policy-title"]').screenshot({ path: path.join(reports, 'policy-rules-card-mobile.png') });

    scenario = 'policy-dirty-refresh';
    await costInput.fill('0.04'); await latencyInput.fill('1000');
    policyRevision = 2; policyRules = { max_call_cost_usd: '0.02', max_call_latency_ms: 800, alert_on_errors: true };
    await reloadRules.click();
    await page.getByText('Latest saved rules loaded. Your unsaved edits are preserved; compare them with the current values before saving.', { exact: true }).waitFor();
    assert.equal(await costInput.inputValue(), '0.04'); assert.equal(await latencyInput.inputValue(), '1000');
    await page.getByText('Above $0.02 USD', { exact: true }).waitFor();

    scenario = 'policy-conflict';
    await saveRules.click();
    await page.getByText('Another save changed the rules. Reload the saved rules before saving your edits.', { exact: true }).waitFor();
    assert(await saveRules.isDisabled()); assert.equal(await costInput.inputValue(), '0.04');
    await page.screenshot({ path: path.join(reports, 'policy-conflict-mobile.png'), fullPage: true });
    scenario = 'policy-ready';
    await reloadRules.click();
    await page.getByText('Saved revision 3', { exact: true }).waitFor();
    assert.equal(await costInput.inputValue(), '0.04');
    scenario = 'policy-save-lost';
    await saveRules.click();
    await page.getByText('The save was not confirmed. It may have reached Guardian. Reload the saved rules before trying again.', { exact: true }).waitFor();
    assert(await saveRules.isDisabled());
    assert.equal(seen.filter(request => request.scenario === scenario && request.method === 'PUT').length, 1);
    assert.equal(policyRevision, 4);
    scenario = 'policy-ready';
    await reloadRules.click();
    await page.getByText('Saved revision 4', { exact: true }).waitFor();
    assert(await saveRules.isDisabled(), 'Readback of the committed save should not suggest duplicate mutation');

    scenario = 'policy-read-unavailable';
    await reloadRules.click();
    await page.getByText('Showing previously fetched rules; current settings are unconfirmed.', { exact: true }).waitFor();
    await page.getByText('Saved revision 4', { exact: true }).waitFor();
    assert(await saveRules.isDisabled());
    await page.reload();
    await page.getByText('Monitoring rules are unavailable. Reload the rules to check the current settings.', { exact: true }).waitFor();
    assert.equal(await page.getByRole('form', { name: 'Edit monitoring rules' }).count(), 0);
    assert.equal(await page.getByText('Saved revision 4', { exact: true }).count(), 0);
    scenario = 'policy-malformed';
    await reloadRules.click();
    await page.getByText('Monitoring rules are unavailable. Reload the rules to check the current settings.', { exact: true }).waitFor();
    assert.equal(await page.getByRole('form', { name: 'Edit monitoring rules' }).count(), 0);
    scenario = 'policy-ready';
    await reloadRules.click();
    await page.getByText('Saved revision 4', { exact: true }).waitFor();
    await costInput.fill('0.09');
    oidcRole = 'operator'; scenario = 'policy-role-loss';
    await page.evaluate(() => window.dispatchEvent(new Event('focus')));
    await page.getByText('Only the project owner can edit monitoring rules.', { exact: true }).waitFor();
    assert.equal(await costInput.count(), 0); assert.equal(await saveRules.count(), 0);
    assert.equal(seen.filter(request => request.scenario === scenario && request.method === 'PUT').length, 0);
    await page.screenshot({ path: path.join(reports, 'policy-operator-readonly-mobile.png'), fullPage: true });
    oidcRole = 'viewer'; scenario = 'policy-viewer';
    await page.reload();
    await page.getByText('Only the project owner can edit monitoring rules.', { exact: true }).waitFor();
    assert.equal(await saveRules.count(), 0);

    oidcRole = 'operator'; scenario = 'policy-incident'; resolved = false;
    await page.goto(origin + '/incidents/synthetic-incident', { waitUntil: 'domcontentloaded' });
    await page.getByText('Observed call cost $0.08 exceeded the saved $0.05 limit.', { exact: true }).waitFor();
    await page.getByText('Evaluated with saved policy revision 1. Later rule changes do not change this evidence.', { exact: true }).waitFor();
    assert(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), 'Configured incident evidence overflows on mobile');
    await page.screenshot({ path: path.join(reports, 'policy-incident-evidence-mobile.png'), fullPage: true });
    await page.setViewportSize({ width: 1280, height: 900 });
    await page.locator('[aria-label="Monitoring rule evidence"]').screenshot({ path: path.join(reports, 'policy-threshold-evidence-desktop.png') });
    await page.setViewportSize({ width: 390, height: 844 });
    await page.getByRole('link', { name: 'Inspect captured run synthetic-policy-run', exact: true }).click();
    await page.getByRole('heading', { name: 'Trace synthetic-policy-run', exact: true }).waitFor();
    assert.equal(await page.getByRole('link', { name: /View in Langfuse/ }).count(), 0);
    await page.goto(origin + '/incidents/synthetic-incident', { waitUntil: 'domcontentloaded' });
    await page.getByRole('button', { name: 'Mark resolved', exact: true }).click();
    await page.getByText('resolved', { exact: true }).waitFor();
    await page.reload();
    await page.getByText('resolved', { exact: true }).waitFor();
    await page.getByText('Observed call cost $0.08 exceeded the saved $0.05 limit.', { exact: true }).waitFor();
    assert.equal(await page.getByRole('button', { name: 'Mark resolved', exact: true }).count(), 0);

    // Notifications use synthetic durable state here; the separate Mongo proof
    // exercises actual owner HTTP, transactions and the localhost receiver.
    oidcRole = 'owner'; scenario = 'notification-owner';
    await page.goto(origin + '/setup', { waitUntil: 'domcontentloaded' });
    const notificationCard = page.locator('[aria-labelledby="notification-setup-title"]');
    const refreshNotifications = page.getByRole('button', { name: 'Refresh notification status', exact: true });
    const sendTest = page.getByRole('button', { name: 'Send test notification', exact: true });
    const enableNotifications = page.getByRole('button', { name: 'Enable notifications', exact: true });
    const disableNotifications = page.getByRole('button', { name: 'Disable notifications', exact: true });
    await notificationCard.getByText('Slack destination not configured', { exact: true }).waitFor();
    assert(await sendTest.isDisabled()); assert(await enableNotifications.isDisabled());
    notificationDestination.state = 'configured';
    await refreshNotifications.click();
    await notificationCard.getByText('Slack destination configured', { exact: true }).waitFor();
    await sendTest.click();
    await notificationCard.getByText('Test request queued. Refresh notification status to check whether Slack accepted it.', { exact: true }).waitFor();
    assert(await sendTest.isDisabled()); assert(await enableNotifications.isDisabled());
    assert.equal(notificationDeliveries.length, 1);
    settleDelivery(notificationDeliveries[0]); notificationDestination.verified = true;
    notificationWorker = { status: 'healthy', last_seen_at: now };
    await refreshNotifications.click();
    await notificationCard.getByText('Accepted by Slack', { exact: true }).waitFor();
    await enableNotifications.click();
    await notificationCard.getByText('New incident notifications enabled', { exact: true }).waitFor();
    assert(await enableNotifications.isDisabled());
    notificationWorker.status = 'stale';
    await refreshNotifications.click();
    await notificationCard.getByText('Delivery worker heartbeat is stale', { exact: true }).waitFor();
    await notificationCard.getByText('New incident notifications enabled', { exact: true }).waitFor();
    assert(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), 'Notification card overflows mobile');
    await notificationCard.screenshot({ path: path.join(reports, 'notification-enabled-stale-mobile.png') });

    scenario = 'notification-incident'; resolved = false;
    const failedDelivery = delivery('f'.repeat(64), 'incident');
    settleDelivery(failedDelivery, 'timeout_unconfirmed'); notificationDeliveries.unshift(failedDelivery);
    await refreshNotifications.click();
    await notificationCard.getByText('Acceptance unconfirmed', { exact: true }).waitFor();
    await notificationCard.getByText('An unconfirmed attempt may already have reached Slack.', { exact: true }).waitFor();
    await notificationCard.getByRole('link', { name: 'View incident', exact: true }).click();
    await page.getByRole('heading', { name: 'Notification history', exact: true }).waitFor();
    await page.getByText('Observed call cost $0.08 exceeded the saved $0.05 limit.', { exact: true }).waitFor();
    await page.getByRole('button', { name: 'Retry notification', exact: true }).click();
    await page.getByText('Retry request accepted. Refresh notification status to check the delivery result.', { exact: true }).waitFor();
    assert.equal(failedDelivery.cycle, 2);
    assert.equal(await page.getByText('Test notification', { exact: true }).count(), 0, 'Incident retry displayed unfiltered test history');
    settleDelivery(failedDelivery);
    await refreshNotifications.click();
    await page.getByText('Accepted by Slack', { exact: true }).waitFor();
    await page.setViewportSize({ width: 1280, height: 1000 });
    await page.getByRole('heading', { name: 'Notification history', exact: true }).scrollIntoViewIfNeeded();
    await page.screenshot({ path: path.join(reports, 'notification-incident-history-desktop.png'), fullPage: true });
    await page.getByRole('link', { name: 'Inspect captured run synthetic-policy-run', exact: true }).click();
    await page.getByRole('heading', { name: 'Trace synthetic-policy-run', exact: true }).waitFor();
    await page.goto(origin + '/incidents/synthetic-incident', { waitUntil: 'domcontentloaded' });
    await page.getByRole('button', { name: 'Mark resolved', exact: true }).click();
    await page.getByText('resolved', { exact: true }).waitFor();
    await page.reload();
    await page.getByText('resolved', { exact: true }).waitFor();
    await page.getByText('Accepted by Slack', { exact: true }).waitFor();

    scenario = 'notification-action-lost';
    await page.goto(origin + '/setup', { waitUntil: 'domcontentloaded' });
    await notificationCard.getByText('New incident notifications enabled', { exact: true }).waitFor();
    await disableNotifications.click();
    await notificationCard.getByText('The notification action was not confirmed. It may have reached Guardian. Refresh before trying again.', { exact: true }).waitFor();
    assert(await disableNotifications.isDisabled()); assert(await sendTest.isDisabled());
    assert.equal(seen.filter(request => request.scenario === scenario && request.method === 'POST').length, 1);
    scenario = 'notification-ready';
    await refreshNotifications.click();
    await notificationCard.getByText('New incident notifications disabled', { exact: true }).waitFor();
    scenario = 'notification-conflict';
    await enableNotifications.click();
    await notificationCard.getByText('Notification settings or delivery state changed. Refresh before trying again.', { exact: true }).waitFor();
    assert(await enableNotifications.isDisabled());
    scenario = 'notification-ready';
    await refreshNotifications.click();
    await notificationCard.getByText('New incident notifications disabled', { exact: true }).waitFor();

    scenario = 'notification-unavailable';
    await refreshNotifications.click();
    await notificationCard.getByText('Showing previously fetched notification status; the current state is unconfirmed.', { exact: true }).waitFor();
    assert(await enableNotifications.isDisabled());
    await page.reload();
    await notificationCard.getByText('Notification status is unavailable. Refresh to check the current settings.', { exact: true }).waitFor();
    assert.equal(await sendTest.count(), 0);
    scenario = 'notification-malformed';
    await refreshNotifications.click();
    await notificationCard.getByText('Notification status is unavailable. Refresh to check the current settings.', { exact: true }).waitFor();
    assert.equal(await enableNotifications.count(), 0);
    scenario = 'notification-incident-unavailable';
    await page.goto(origin + '/incidents/synthetic-incident', { waitUntil: 'domcontentloaded' });
    await page.getByText('Notification history is unavailable. Refresh to check delivery status.', { exact: true }).waitFor();
    await page.getByText('Observed call cost $0.08 exceeded the saved $0.05 limit.', { exact: true }).waitFor();
    await page.getByText('resolved', { exact: true }).waitFor();

    scenario = 'notification-rotation';
    notificationDestination = { channel: 'slack', state: 'changed', verified: false, enabled: false };
    notificationWorker.status = 'blocked';
    const oldPending = delivery('a'.repeat(64)); notificationDeliveries.unshift(oldPending);
    await page.goto(origin + '/setup', { waitUntil: 'domcontentloaded' });
    await notificationCard.getByText('Slack destination changed', { exact: true }).waitFor();
    assert(await enableNotifications.isDisabled());
    await sendTest.click();
    await notificationCard.getByText('Slack destination configured', { exact: true }).waitFor();
    await notificationCard.getByText('Test request queued. Refresh notification status to check whether Slack accepted it.', { exact: true }).waitFor();
    assert.equal(oldPending.state, 'cancelled'); assert(await enableNotifications.isDisabled());
    await page.setViewportSize({ width: 390, height: 844 });
    await notificationCard.screenshot({ path: path.join(reports, 'notification-rotation-test-mobile.png') });

    scenario = 'notification-role-loss'; oidcRole = 'operator';
    await page.evaluate(() => window.dispatchEvent(new Event('focus')));
    await notificationCard.getByText('Only the project owner can test, change or retry notifications.', { exact: true }).waitFor();
    assert.equal(await sendTest.count(), 0); assert.equal(await disableNotifications.count(), 0);
    oidcRole = 'viewer';
    await page.reload();
    await notificationCard.getByText('Only the project owner can test, change or retry notifications.', { exact: true }).waitFor();
    assert.equal(await page.getByRole('button', { name: 'Retry notification', exact: true }).count(), 0);
    authMode = 'api_key';
    await page.evaluate(() => localStorage.setItem('guardian_api_key', 'browser-smoke-key'));
    await page.reload();
    await notificationCard.getByText('Local shared-key access shows notifications read-only.', { exact: true }).waitFor();
    assert.equal(await sendTest.count(), 0);
    assert.equal(seen.filter(request => request.scenario === scenario && request.method === 'POST').length, 0);

    assert.deepEqual(browserErrors, []);
    assert.deepEqual(routeErrors, []);
    const manifest = JSON.parse(fs.readFileSync(path.join(build, 'asset-manifest.json'), 'utf8'));
    const report = { ok: true, browser: browser.version(), scenarios: ['partial_desktop_mobile', 'rejected_only_unknown_spend', 'cold_unavailable', 'stale_worker', 'bounded_empty_run', 'undetermined_partial_run', 'ledger_healthy_captured_once', 'ledger_pending_quarantine_unknown_spend', 'partial_summary_utc_zero_peak', 'summary_unavailable', 'incidents_successful_empty', 'incidents_cold_failure_retry', 'incidents_stale_same_filter', 'incidents_filter_failure_retry', 'restored_access_before_protected_reads', 'setup_unconfigured_read_only', 'setup_configured_unchecked', 'setup_empty_latest_read', 'setup_pending_checkpoint_separation', 'setup_stale_unknown', 'setup_unavailable_retry', 'disconnect_without_reload', 'candidate_rejected_not_persisted', 'candidate_verified_before_persist_deeplink', 'restored_expired_key_removed', 'restored_unavailable_retained_retry', 'valid_access_with_partial_summary', 'data_401_unmounts_protected_content', 'cross_tab_disconnect', 'public_config_fail_closed', 'oidc_entry_no_shared_key', 'oidc_viewer_cookie_safe_deeplink', 'oidc_operator_resolution_csrf_origin', 'oidc_logout_failure_closed', 'oidc_logout_retry_revokes', 'oidc_data_expiry_unmounts', 'oidc_access_unavailable_retry', 'oidc_invalid_role_permissions_fail_closed', 'oidc_unsafe_return_rejected', 'oidc_failed_callback_no_loop', 'oidc_cross_tab_logout'], api_transport: 'synthetic_browser_routes', identity_provider: 'synthetic_login_redirect_only', application: 'Guardian production build', bundle: manifest.files['main.js'], mobile_viewport: { width: 390, height: 844 }, real_services: false, checked_at: new Date().toISOString() };
    report.scenarios.push('direct_owner_no_receipt', 'direct_key_create_one_time', 'direct_test_cookie_free_no_production',
      'direct_key_dismiss', 'direct_revoke_failure_retry', 'direct_lost_create_recovery', 'direct_secret_cleared_on_focus',
      'direct_viewer_read_only', 'direct_pending_stale_worker', 'direct_processed_receipt_distinction',
      'direct_capture_unavailable_retains_labelled_counts', 'direct_live_source_caption');
    report.scenarios.push('policy_owner_validation_zero_limits_and_key_readonly', 'policy_dirty_refresh_and_conflict_readback',
      'policy_lost_save_readback_no_duplicate', 'policy_stale_cold_and_malformed_read_recovery',
      'policy_role_loss_operator_viewer_readonly', 'policy_threshold_evidence_run_resolve');
    report.scenarios.push('notification_owner_test_accepted_enable_worker_stale', 'notification_unconfirmed_retry_incident_run_resolve',
      'notification_lost_action_conflict_readback', 'notification_stale_cold_malformed_history_independent',
      'notification_rotated_destination_requires_new_test', 'notification_role_loss_operator_viewer_key_readonly');
    report.scenarios.push('provider_eight_recipes_unknown_cost_no_provider_calls', 'provider_clipboard_safe_advanced_json_and_mobile');
    fs.writeFileSync(path.join(reports, 'report.json'), JSON.stringify(report, null, 2) + '\n');
    console.log(JSON.stringify(report));
  } catch (error) {
    if (page) {
      await page.screenshot({ path: path.join(reports, 'failure.png'), fullPage: true }).catch(() => {});
      console.error(JSON.stringify({ diagnostic: 'browser_failure', scenario, accessMode, authMode,
        page_path: new URL(page.url()).pathname, body_text: (await page.locator('body').innerText()).slice(-1500),
        stored_key_present: await page.evaluate(() => !!localStorage.getItem('guardian_api_key')).catch(() => null) }));
    }
    if (page && scenario.startsWith('notification-')) {
      await page.screenshot({ path: path.join(reports, 'notification-failure.png'), fullPage: true }).catch(() => {});
      console.error(JSON.stringify({ scenario, visible_text: (await page.locator('body').innerText()).slice(-6000),
        requests: seen.filter(request => request.scenario === scenario).map(request => ({ path: request.path, method: request.method })) }));
    }
    if (page && scenario.startsWith('policy-')) {
      const card = page.locator('[aria-labelledby="monitoring-policy-title"]');
      if (await card.count()) {
        await card.screenshot({ path: path.join(reports, 'policy-failure.png') }).catch(() => {});
        console.error(JSON.stringify({ scenario, policy_card_text: (await card.innerText()).slice(0, 4000),
          requests: seen.filter(request => request.scenario === scenario).map(request => ({ path: request.path, method: request.method })) }));
      }
    }
    throw error;
  } finally {
    if (browser) await browser.close();
    await new Promise(resolve => server.close(resolve));
  }
})().catch(error => { console.error(error.message); process.exitCode = 1; });
