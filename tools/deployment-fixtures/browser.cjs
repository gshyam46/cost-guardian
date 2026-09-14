#!/usr/bin/env node
/* Actual local OIDC and Guardian routes. No substituted API responses. */
const fs = require('node:fs');
const path = require('node:path');
const { randomUUID, createHash } = require('node:crypto');
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
  let server, browser, context, page, reportDir, phase = 'configuration', result, clean = false;
  try {
    const config = JSON.parse(fs.readFileSync(0, 'utf8'));
    reportDir = config.report_dir;
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
    context = await browser.newContext({ viewport: { width: 1280, height: 960 }, serviceWorkers: 'block', acceptDownloads: true });
    const blocked = [], errors = [], publicApiRequests = [];
    let exploringPublic = config.phase === 'first';
    context.on('request', request => {
      if (exploringPublic && new URL(request.url()).pathname.startsWith('/api/')) publicApiRequests.push(true);
    });
    await context.route('**/*', route => {
      const target = new URL(route.request().url());
      if (![config.origin, config.issuer].includes(target.origin)) {
        blocked.push(true); return route.abort();
      }
      return route.continue();
    });
    page = await context.newPage();
    page.setDefaultTimeout(12000);
    page.on('pageerror', () => errors.push(true));
    if (config.phase === 'first') {
      phase = 'public_landing_and_interactive_demo';
      await page.goto(config.origin + '/welcome');
      await page.getByRole('heading', { name: 'See what your AI is doing.', exact: true }).waitFor();
      check(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), 'landing_desktop_overflow');
      await page.screenshot({ path: path.join(config.report_dir, 'public-landing-desktop.png'), fullPage: true });
      await page.setViewportSize({ width: 390, height: 844 });
      check(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), 'landing_mobile_overflow');
      await page.screenshot({ path: path.join(config.report_dir, 'public-landing-mobile.png'), fullPage: true });
      await page.getByRole('link', { name: 'Explore the demo', exact: true }).first().click();
      await page.waitForURL(config.origin + '/demo');
      await page.getByRole('heading', { name: 'A slow answer, explained.', exact: true }).waitFor();
      await page.getByText('Sample workspace', { exact: true }).first().waitFor();
      for (const [name, call] of [['Document search', 'Rewrite question'], ['Agent handoff', 'Run specialist'], ['Support answer', 'Draft answer']]) {
        const selected = page.getByRole('button', { name, exact: true });
        await selected.click();
        check(await selected.getAttribute('aria-pressed') === 'true', 'demo_trace_selection_missing');
        await page.getByLabel('Sample trace detail', { exact: true }).getByRole('heading', { name: call, exact: true }).waitFor();
      }
      await page.getByRole('button', { name: 'Needs attention', exact: true }).click();
      check(await page.getByRole('button', { name: 'Document search', exact: true }).count() === 0, 'demo_run_filter_ignored');
      await page.getByRole('button', { name: 'All calls', exact: true }).click();
      await page.getByRole('button', { name: 'Document search', exact: true }).waitFor();
      await page.getByLabel('Sample call timeline', { exact: true }).getByRole('button', { name: /^Classify question/ }).click();
      await page.getByLabel('Sample trace detail', { exact: true }).getByRole('heading', { name: 'Classify question', exact: true }).waitFor();
      await page.getByLabel('Sample call timeline', { exact: true }).getByRole('button', { name: /^Draft answer/ }).click();
      await page.getByRole('button', { name: 'Inspect incident', exact: true }).click();
      await page.getByRole('button', { name: 'Mark demo incident resolved', exact: true }).click();
      check(await page.getByRole('button', { name: 'Resolved in this demo', exact: true }).isDisabled(), 'demo_resolution_unconfirmed');
      await page.screenshot({ path: path.join(config.report_dir, 'public-demo-incident-mobile.png'), fullPage: true });
      await page.getByRole('button', { name: 'Back to trace', exact: true }).click();
      check(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), 'demo_mobile_overflow');
      await page.screenshot({ path: path.join(config.report_dir, 'public-demo-mobile.png'), fullPage: true });
      await page.setViewportSize({ width: 1280, height: 960 });
      check(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), 'demo_desktop_overflow');
      await page.screenshot({ path: path.join(config.report_dir, 'public-demo-desktop.png'), fullPage: true });
      check(!publicApiRequests.length, 'public_demo_requested_api');
      exploringPublic = false;
      // Opening the public product must not create an authenticated session.
      check((await context.request.get(config.origin + '/api/guardian/access')).status() === 401, 'demo_created_private_access');
      await page.getByRole('link', { name: 'Connect your app', exact: true }).first().click();
      await page.waitForURL(config.origin + '/setup');
    } else {
      await page.goto(config.origin + '/setup');
    }
    phase = 'actual_oidc_login';
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
    let trace = config.trace_id, incidentId = config.incident_id, pythonPackageEvidence;
    if (config.phase === 'first') {
      phase = 'python_launcher_default_onboarding';
      const integration = page.locator('#connection-integrate');
      if (await integration.getAttribute('open') === null) await integration.locator(':scope > summary').click();
      await page.getByRole('heading', { name: 'Install once. Run your app with Sillage.', exact: true }).waitFor();
      check(await page.getByRole('button', { name: 'Python: install + run', exact: true }).getAttribute('aria-pressed') === 'true', 'python_launcher_not_default');
      check(!await page.getByRole('heading', { name: 'Connect your OpenAI calls', exact: true }).isVisible(), 'manual_recipes_visible_by_default');
      const wheelName = 'sillage_observe-0.2.0-py3-none-any.whl';
      const installed = page.getByLabel('Install Sillage', { exact: true });
      const configured = page.getByLabel('Sillage server configuration', { exact: true });
      const launched = page.getByLabel('Start your app with Sillage', { exact: true });
      check(await installed.innerText() === `python -m pip install './${wheelName}[openinference]'`, 'wheel_install_command_invalid');
      let template = await configured.innerText();
      check(template.includes(`$env:SILLAGE_URL = '${config.origin}'`) && template.includes('<your application key>')
        && template.includes("$env:SILLAGE_ALLOW_LOCAL = 'true'"), 'launcher_configuration_wrong_origin');
      check(await page.getByLabel('Check your Python environment', { exact: true }).innerText() === 'sillage-run --instrumentation openinference --instrumentors auto --check', 'launcher_local_check_command_invalid');
      check(await launched.innerText() === 'sillage-run --instrumentation openinference --instrumentors auto -- python -m uvicorn server:app', 'launcher_uvicorn_command_invalid');
      await page.locator('#launcher-layer').selectOption('litellm');
      check((await launched.innerText()).includes('--instrumentors litellm'), 'launcher_layer_choice_ignored');
      await page.locator('#launcher-capture').selectOption('native');
      check(await installed.innerText() === 'python -m pip install ./' + wheelName, 'native_install_command_invalid');
      check(await launched.innerText() === 'sillage-run -- python -m uvicorn server:app', 'native_launch_command_invalid');
      await page.locator('#launcher-capture').selectOption('openinference');
      await page.locator('#launcher-layer').selectOption('auto');
      await page.getByLabel('Terminal', { exact: true }).selectOption('bash');
      check((await configured.innerText()).includes(`export SILLAGE_URL='${config.origin}'`), 'launcher_bash_configuration_invalid');
      await page.getByLabel('How you start your app', { exact: true }).selectOption('script');
      check(await launched.innerText() === 'sillage-run --instrumentation openinference --instrumentors auto -- python app.py', 'launcher_script_command_invalid');
      await page.getByLabel('Terminal', { exact: true }).selectOption('powershell');
      await page.getByLabel('How you start your app', { exact: true }).selectOption('uvicorn');
      phase = 'authenticated_python_wheel_download';
      const wheelTarget = config.origin + '/api/guardian/integrations/python.whl';
      const wheelResponse = await context.request.get(wheelTarget, { timeout: 10000 });
      check(wheelResponse.status() === 200 && wheelResponse.headers()['content-type'] === 'application/octet-stream'
        && wheelResponse.headers()['cache-control'] === 'no-store'
        && wheelResponse.headers()['content-disposition'] === `attachment; filename="${wheelName}"`, 'python_wheel_response_invalid');
      const wheelBytes = await wheelResponse.body();
      const expectedWheel = fs.readFileSync(config.python_wheel);
      check(wheelBytes.length > 0 && wheelBytes.length <= 2097152 && wheelBytes.equals(expectedWheel), 'python_wheel_response_bytes_mismatch');
      const wheelLink = page.getByRole('link', { name: 'Download Python package', exact: true });
      check(await wheelLink.getAttribute('href') === wheelTarget, 'python_wheel_link_wrong_origin');
      // Attachment navigation does not reliably emit Page.response in Chromium.
      // Keep HTTP validation independent from the user-triggered download event.
      const wheelDownloadPending = page.waitForEvent('download');
      await wheelLink.click();
      const wheelDownload = await wheelDownloadPending;
      check(wheelDownload.suggestedFilename() === wheelName, 'python_wheel_attachment_name_invalid');
      const wheelDestination = path.join(config.report_dir, wheelName);
      await wheelDownload.saveAs(wheelDestination);
      const digest = bytes => createHash('sha256').update(bytes).digest('hex');
      check(digest(fs.readFileSync(wheelDestination)) === digest(expectedWheel), 'python_wheel_download_hash_mismatch');
      pythonPackageEvidence = { artifact: wheelName, sha256: digest(expectedWheel), exact_artifact_bytes: true,
        authenticated_browser: true, no_store: true, download_origin_verified: true, default_launcher: true,
        powershell_and_bash: true, script_and_uvicorn: true };
      const untouchedKeys = (await json('/api/guardian/ingestion-keys')).credentials;
      check(Array.isArray(untouchedKeys) && untouchedKeys.length === 0, 'package_download_created_ingestion_key');
      phase = 'authenticated_helper_downloads';
      await page.getByRole('button', { name: 'Manual Python / Node', exact: true }).click();
      for (const [language, extension] of [['Python', 'py'], ['Node', 'mjs']]) {
        await page.getByRole('tab', { name: language, exact: true }).click();
        const target = config.origin + '/api/guardian/integrations/' + language.toLowerCase() + '.zip';
        phase = 'authenticated_helper_http_' + language.toLowerCase();
        const response = await context.request.get(target, { timeout: 10000 });
        check(response.status() === 200 && response.headers()['content-type'].startsWith('application/zip')
          && response.headers()['cache-control'] === 'no-store', 'helper_download_response_invalid');
        const archiveBytes = await response.body();
        phase = 'authenticated_helper_click_' + language.toLowerCase();
        const downloadPending = page.waitForEvent('download');
        await page.getByRole('link', { name: 'Download ' + language + ' helpers', exact: true }).click();
        // Chromium downloads need not emit Page.response. Verify actual HTTP
        // headers separately and reconcile the user-triggered attachment bytes.
        const download = await downloadPending;
        check(download.suggestedFilename() === 'sillage-' + language.toLowerCase() + '.zip', 'helper_download_name_invalid');
        const destination = path.join(config.report_dir, download.suggestedFilename());
        phase = 'authenticated_helper_archive_' + language.toLowerCase();
        await download.saveAs(destination);
        check(fs.readFileSync(destination).equals(archiveBytes), 'helper_download_bytes_mismatch');
        const verifyArchive = [
          'import json,pathlib,sys,zipfile',
          'archive,source,suffix=pathlib.Path(sys.argv[1]),pathlib.Path(sys.argv[2]),sys.argv[3]',
          'modules=[name+"."+suffix for name in ("guardian_capture","guardian_exporter","guardian_openai")]',
          'with zipfile.ZipFile(archive) as bundle:',
          ' assert len(bundle.infolist())==4 and set(bundle.namelist())==set(modules+["README.md"])',
          ' assert sum(item.file_size for item in bundle.infolist())<524288',
          ' assert all(bundle.read(name)==source.joinpath(name).read_bytes() for name in modules)',
          ' assert 0<len(bundle.read("README.md"))<16384',
          'print(json.dumps({"module_count":3,"exact_source_bytes":True}))',
        ].join('\n');
        const inspected = spawnSync(config.guardian_python, ['-I', '-S', '-c', verifyArchive, destination, config.module_dir, extension],
          { encoding: 'utf8', timeout: 10000, windowsHide: true });
        check(inspected.status === 0 && JSON.parse(inspected.stdout).exact_source_bytes === true, 'downloaded_helper_archive_invalid');
      }
      await integration.locator(':scope > summary').click();
      phase = 'connected_overview_to_public_demo';
      await page.goto(config.origin + '/');
      const sampleLink = page.getByRole('link', { name: 'Explore the sample workspace', exact: true });
      await sampleLink.waitFor();
      exploringPublic = true;
      await sampleLink.click();
      await page.waitForURL(config.origin + '/demo');
      await page.getByText('Sample workspace', { exact: true }).first().waitFor();
      check(!publicApiRequests.length, 'connected_demo_requested_private_api');
      exploringPublic = false;
      await page.getByRole('link', { name: 'Connect your app', exact: true }).first().click();
      await page.waitForURL(config.origin + '/setup');
      await page.getByRole('heading', { name: 'Send events directly', exact: true }).waitFor();
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
      check(run.calls[0].total_tokens === 10 && run.calls[0].cost_usd === null && run.cost_usd === null
        && run.calls[0].latency_ms === 0, 'token_cost_or_zero_duration_mismatch');
      const metrics = await json('/api/guardian/metrics');
      check(metrics.length === 1 && metrics[0].call_count === 1 && metrics[0].known_total_tokens === 10 && metrics[0].cost_unknown_count === 1, 'accounting_did_not_reconcile');
      incidentId = incidents[0].id;
      phase = 'overview_shows_actual_captured_activity';
      await page.goto(config.origin + '/');
      await page.getByText('Captured calls (24h)', { exact: true }).waitFor();
      const overviewValue = label => page.getByText(label, { exact: true }).locator('..').locator('p').nth(1).innerText();
      check(await overviewValue('Captured calls (24h)') === '1', 'overview_actual_call_count_missing');
      check(await overviewValue('Token usage (24h)') === '10', 'overview_actual_tokens_missing');
      check(await overviewValue('Captured spend (24h)') === 'Unknown', 'overview_unknown_cost_invented');
      check(await overviewValue('Call errors (24h)') === '1', 'overview_actual_error_count_missing');
      await page.screenshot({ path: path.join(config.report_dir, 'actual-overview-desktop.png'), fullPage: true });
      await page.setViewportSize({ width: 390, height: 844 });
      check(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), 'overview_mobile_overflow');
      await page.screenshot({ path: path.join(config.report_dir, 'actual-overview-mobile.png'), fullPage: true });
      await page.setViewportSize({ width: 1280, height: 960 });
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
      await page.getByText('0ms', { exact: true }).first().waitFor();
      // Screenshots happen only after the one-time credential was dismissed.
      await page.screenshot({ path: path.join(config.report_dir, 'actual-run-desktop.png'), fullPage: true });
      await page.setViewportSize({ width: 390, height: 844 });
      check(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), 'run_mobile_overflow');
      await page.screenshot({ path: path.join(config.report_dir, 'actual-run-mobile.png'), fullPage: true });
      await page.goto(config.origin + '/setup');
      await page.getByRole('heading', { name: 'Send events directly', exact: true }).waitFor();
      await page.setViewportSize({ width: 390, height: 844 });
      check(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), 'setup_mobile_overflow');
      await page.evaluate(() => window.scrollTo({ top: 0, left: 0, behavior: 'instant' }));
      await page.screenshot({ path: path.join(config.report_dir, 'actual-setup-mobile.png'), fullPage: true });
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
    if (config.phase === 'first') {
      phase = 'public_signin_and_post_logout_demo';
      await page.goto(config.origin + '/signin');
      await page.getByRole('button', { name: 'Sign in with your organization', exact: true }).waitFor();
      check(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), 'signin_mobile_overflow');
      await page.screenshot({ path: path.join(config.report_dir, 'actual-signin-mobile.png'), fullPage: true });
      exploringPublic = true;
      await page.goto(config.origin + '/demo');
      await page.getByText('Sample workspace', { exact: true }).first().waitFor();
      check(!publicApiRequests.length, 'signed_out_demo_requested_api');
      exploringPublic = false;
      check((await context.request.get(config.origin + '/api/guardian/access')).status() === 401, 'signed_out_demo_restored_session');
    }
    check(!blocked.length && !errors.length, 'browser_network_or_runtime_violation');
    result = { status: 'passed', phase: config.phase, trace_id: trace, incident_id: incidentId,
      actual_oidc: true, http_only_session: true, test_separation: true, production_events: 1,
      known_total_tokens: 10, cost_unknown: true, resolved: true, logout_denied: true,
      browser_version: browser.version(), external_requests: 0 };
    if (config.phase === 'first') result.public_experience = { responsive_landing: true, interactive_demo: true,
      selected_runs: 3, run_filter: true, selected_call: true, incident_round_trip: true, demo_resolution: true,
      protected_requests: publicApiRequests.length,
      demo_created_private_access: false, connect_restored_setup: true, signed_out_demo_accessible: true,
      explicit_signin_route: true, connected_overview_to_demo: true };
    if (config.phase === 'first') result.actual_dashboard = { overview_calls: 1, overview_tokens: 10,
      overview_errors: 1, overview_cost: 'unknown', zero_duration_visible: true, responsive_overview_and_run: true };
    if (config.phase === 'first') result.integration_downloads = { languages: ['python', 'node'], authenticated_browser: true,
      source_modules_per_archive: 3, readme: true, exact_source_bytes: true, no_store: true };
    if (config.phase === 'first') result.python_package = pythonPackageEvidence;
  } catch (error) {
    result = { status: 'failed', phase, code: /^[a-z_]{1,80}$/.test(error.message) ? error.message
      : error.code === 'MODULE_NOT_FOUND' ? 'browser_dependency_missing' : 'browser_step_failed' };
    // Keep a useful UI diagnostic without ever capturing a one-time credential.
    if (page && reportDir && phase !== 'owner_key_and_test_receipt') {
      try {
        if (!await page.getByLabel('One-time ingestion key', { exact: true }).count()) {
          await page.screenshot({ path: path.join(reportDir, 'browser-failure.png'), fullPage: true, timeout: 5000 });
          result.diagnostic_screenshot = 'browser-failure.png';
        }
      } catch { /* Diagnostics must not obscure the original failed phase. */ }
    }
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
