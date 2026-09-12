#!/usr/bin/env node
/* Actual local OIDC and Guardian routes. No substituted API responses. */
const fs = require('node:fs');
const path = require('node:path');
const { randomUUID } = require('node:crypto');
const { pathToFileURL } = require('node:url');
const { spawnSync } = require('node:child_process');
if (process.argv.slice(2).join(' ') !== '--run') {
  console.log('Usage: node browser.cjs --run < synthetic-config.json');
  process.exit(0);
}
const check = (value, code) => { if (!value) throw new Error(code); };
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
async function bounded(promise, ms) {
  let timer;
  try { return await Promise.race([promise, new Promise((_, reject) => { timer = setTimeout(() => reject(Error('cleanup_timeout')), ms); })]); }
  finally { clearTimeout(timer); }
}
(async () => {
  let server, browser, context, phase = 'configuration', result, clean = false;
  try {
    const config = JSON.parse(fs.readFileSync(0, 'utf8'));
    for (const name of ['origin', 'issuer']) {
      const target = new URL(config[name]);
      check(target.protocol === 'http:' && target.hostname === '127.0.0.1' && target.port
        && config[name] === target.origin, 'fixture_origin_invalid');
    }
    const { chromium } = require(config.playwright);
    phase = 'browser_launch';
    server = await chromium.launchServer({ ...(process.platform === 'win32' ? { channel: 'msedge' } : {}), headless: true });
    phase = 'browser_connect';
    browser = await chromium.connect(server.wsEndpoint());
    phase = 'browser_context';
    context = await browser.newContext({ viewport: { width: 1280, height: 960 }, serviceWorkers: 'block' });
    const blocked = [], errors = [];
    await context.route('**/*', route => {
      const target = new URL(route.request().url());
      if (![config.origin, config.issuer].includes(target.origin)) {
        blocked.push(true); return route.abort();
      }
      return route.continue();
    });
    const page = await context.newPage();
    page.setDefaultTimeout(12000);
    page.on('pageerror', () => errors.push(true));
    phase = 'actual_oidc_login';
    await page.goto(config.origin + '/setup');
    await page.getByRole('button', { name: 'Sign in with your organization', exact: true }).click();
    await page.getByRole('button', { name: 'Continue as Synthetic Owner', exact: true }).click();
    await page.waitForURL(config.origin + '/setup');
    await page.getByRole('heading', { name: 'Send events directly', exact: true }).waitFor();
    const json = async route => {
      const response = await context.request.get(config.origin + route, { timeout: 10000 });
      check(response.status() === 200, 'authenticated_read_failed');
      return response.json();
    };
    const access = await json('/api/guardian/access');
    check(access.auth_mode === 'oidc' && access.actor.role === 'owner' && access.actor.name === 'Synthetic Owner', 'verified_owner_missing');
    const cookies = await context.cookies();
    check(cookies.some(cookie => cookie.name === 'guardian_session' && cookie.httpOnly && cookie.sameSite === 'Lax'), 'http_only_session_missing');
    check(!(await page.evaluate(() => document.cookie)).includes('guardian_session'), 'session_cookie_script_visible');
    check(!(await page.evaluate(() => localStorage.getItem('guardian_api_key'))), 'shared_key_used_for_oidc');
    let trace = config.trace_id, incidentId = config.incident_id;
    if (config.phase === 'first') {
      phase = 'owner_key_and_test_receipt';
      check((await json('/api/guardian/metrics')).length === 0, 'fresh_metrics_not_empty');
      await page.getByLabel('Key label', { exact: true }).fill('Deployment proof');
      await page.getByRole('button', { name: 'Create ingestion key', exact: true }).click();
      const secret = page.getByLabel('One-time ingestion key', { exact: true });
      await secret.waitFor();
      let token = await secret.inputValue();
      check(/^cg_ingest_[a-f0-9]{32}_[A-Za-z0-9_-]{43}$/.test(token), 'key_shape_invalid');
      await page.getByRole('button', { name: 'Send test event', exact: true }).click();
      await page.getByText('Test event received. This handshake creates no production observations, totals or incidents and does not verify real application traffic.', { exact: true }).waitFor();
      check((await json('/api/guardian/metrics')).length === 0 && (await json('/api/guardian/incidents')).length === 0, 'test_receipt_polluted_production');
      await page.getByRole('button', { name: 'Dismiss key', exact: true }).click();
      await secret.waitFor({ state: 'hidden' });
      check(!(await page.evaluate(() => JSON.stringify({ local: {...localStorage}, session: {...sessionStorage} }))).includes(token), 'key_persisted_in_browser');
      phase = 'actual_native_intake';
      const { sendBatch } = await import(pathToFileURL(path.join(config.module_dir, 'guardian_capture.mjs')));
      trace = 'deployment-run-' + randomUUID();
      const stamp = new Date().toISOString();
      const batch = { schema_version: 1, batch_id: randomUUID(), test_mode: false, events: [{
        observation_id: randomUUID(), trace_id: trace, agent_name: 'deployment-fixture', model: 'synthetic/model',
        started_at: stamp, ended_at: stamp, status: 'error', input_tokens: 8, output_tokens: 2, total_tokens: 10, cost_usd: null,
      }] };
      const send = () => sendBatch(batch, { origin: config.origin, token, allowLocal: true, maxAttempts: 1 });
      check((await send()).ok, 'real_event_receipt_missing');
      phase = 'independent_worker_processing';
      const deadline = Date.now() + 30000;
      let incidents, run;
      while (Date.now() < deadline) {
        incidents = await json('/api/guardian/incidents');
        if (incidents.length === 1) {
          run = await json('/api/guardian/live/runs/' + trace);
          if (run.calls?.length === 1) break;
        }
        await delay(300);
      }
      check(incidents?.length === 1 && run?.calls?.length === 1, 'worker_did_not_process_event');
      check(run.calls[0].total_tokens === 10 && run.calls[0].cost_usd === null && run.cost_usd === null, 'token_or_unknown_cost_mismatch');
      const metrics = await json('/api/guardian/metrics');
      check(metrics.length === 1 && metrics[0].call_count === 1 && metrics[0].known_total_tokens === 10 && metrics[0].cost_unknown_count === 1, 'accounting_did_not_reconcile');
      incidentId = incidents[0].id;
      phase = 'incident_run_resolve_replay';
      await page.goto(config.origin + '/incidents/' + incidentId);
      const committed = page.waitForResponse(response => response.url() === config.origin + '/api/guardian/incidents/' + incidentId + '/resolve'
        && response.request().method() === 'POST');
      await page.getByRole('button', { name: 'Mark resolved', exact: true }).click();
      const resolution = await committed;
      check(resolution.status() === 200 && (await resolution.json()).status === 'resolved', 'resolution_response_not_committed');
      await page.getByRole('button', { name: /^(Mark resolved|Resolving\.\.\.)$/ }).waitFor({ state: 'hidden' });
      check((await json('/api/guardian/incidents/' + incidentId)).status === 'resolved', 'resolution_not_durable');
      check((await send()).ok, 'canonical_replay_rejected');
      token = '';
      await delay(1500);
      incidents = await json('/api/guardian/incidents');
      check(incidents.length === 1 && incidents[0].status === 'resolved', 'replay_duplicated_or_reopened_incident');
      await page.goto(config.origin + '/runs/' + trace);
      await page.getByText('synthetic/model', { exact: true }).first().waitFor();
      // Screenshots happen only after the one-time credential was dismissed.
      await page.screenshot({ path: path.join(config.report_dir, 'actual-run-desktop.png'), fullPage: true });
      await page.goto(config.origin + '/setup');
      await page.getByRole('heading', { name: 'Send events directly', exact: true }).waitFor();
      await page.setViewportSize({ width: 390, height: 844 });
      check(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), 'setup_mobile_overflow');
      await page.locator('#direct-capture-title').locator('..').locator('..').screenshot({ path: path.join(config.report_dir, 'actual-setup-mobile.png') });
    } else {
      phase = 'restart_preserved_state';
      check((await json('/api/guardian/incidents/' + incidentId)).status === 'resolved', 'restart_lost_resolution');
      const run = await json('/api/guardian/live/runs/' + trace);
      check(run.calls.length === 1 && run.calls[0].total_tokens === 10 && run.calls[0].cost_usd === null, 'restart_changed_accounting');
    }
    phase = 'actual_logout';
    await page.getByRole('button', { name: 'Sign out', exact: true }).click();
    await page.getByRole('button', { name: 'Sign in with your organization', exact: true }).waitFor();
    check((await context.request.get(config.origin + '/api/guardian/access')).status() === 401, 'logout_did_not_revoke');
    check(!blocked.length && !errors.length, 'browser_network_or_runtime_violation');
    result = { status: 'passed', phase: config.phase, trace_id: trace, incident_id: incidentId,
      actual_oidc: true, http_only_session: true, test_separation: true, production_events: 1,
      known_total_tokens: 10, cost_unknown: true, resolved: true, logout_denied: true,
      browser_version: browser.version(), external_requests: 0 };
  } catch (error) {
    result = { status: 'failed', phase, code: /^[a-z_]{1,80}$/.test(error.message) ? error.message
      : error.code === 'MODULE_NOT_FOUND' ? 'browser_dependency_missing' : 'browser_step_failed' };
  } finally {
    try {
      if (context) await bounded(context.close(), 10000);
      if (browser) await bounded(browser.close(), 10000);
      if (server) await bounded(server.close(), 10000);
      clean = true;
    } catch {
      const owned = server?.process();
      if (owned && owned.exitCode === null) {
        if (process.platform === 'win32') spawnSync(path.join(process.env.SYSTEMROOT, 'System32', 'taskkill.exe'), ['/PID', String(owned.pid), '/T', '/F'], { windowsHide: true, stdio: 'ignore', timeout: 5000 });
        else { try { await bounded(server.kill(), 5000); } catch {} }
      }
      result = { status: 'failed', phase: 'cleanup', code: 'browser_cleanup_timeout' };
    }
    result.cleanup_complete = clean;
    console.log(JSON.stringify(result));
    process.exitCode = result.status === 'passed' ? 0 : 1;
  }
})();
