#!/usr/bin/env node
'use strict';

// Real Node handlers, transactional Mongo writes and the built public UI.
// Only synthetic contacts; the caller owns the loopback replica process.
const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');
const { randomUUID, createHash } = require('node:crypto');
const { parseArgs } = require('node:util');

const HELP = 'node tools/test_public_launch.cjs --static-dir <public-build> --dependencies <frontend-node_modules> --playwright <playwright-module> --mongo-url <owned-loopback-replica> --report-dir <new-report-directory>\nUses a unique marked test database, removes only that database, and never loads dotenv.\n';
const check = (value, code) => { if (!value) throw new Error(code); };

async function main(argv) {
  if (!argv.length || argv.includes('--help')) { process.stdout.write(HELP); return; }
  const { values: args } = parseArgs({ args: argv, options: Object.fromEntries(
    ['static-dir', 'dependencies', 'playwright', 'mongo-url', 'report-dir'].map(key => [key, { type: 'string' }])) });
  check(Object.keys(args).length === 5, 'all_arguments_required');
  const mongoTarget = new URL(args['mongo-url']);
  check(mongoTarget.protocol === 'mongodb:' && mongoTarget.hostname === '127.0.0.1' && mongoTarget.port
    && !mongoTarget.username && !mongoTarget.password && ['/', ''].includes(mongoTarget.pathname)
    && mongoTarget.searchParams.get('replicaSet') === 'guardian-r102'
    && mongoTarget.searchParams.get('directConnection') === 'true'
    && [...mongoTarget.searchParams].length === 2, 'owned_loopback_replica_required');
  const staticDir = fs.realpathSync(args['static-dir']);
  const manifestBytes = fs.readFileSync(path.join(staticDir, 'asset-manifest.json'));
  const manifest = JSON.parse(manifestBytes);
  check(Object.values(manifest.files).some(value => value.endsWith('.js')), 'built_assets_required');
  const reportDir = path.resolve(args['report-dir']);
  fs.mkdirSync(reportDir, { recursive: false });
  const { MongoClient } = require(path.resolve(args.dependencies, 'mongodb'));
  const { chromium } = require(path.resolve(args.playwright));
  const serverRoot = path.join(__dirname, '../apps/guardian/frontend/server');
  const { MongoInterestStore, COLLECTIONS, CLIENT_OPTIONS, bootstrap } = require(path.join(serverRoot, 'mongo.cjs'));
  const { PublicError, interestRecord, validateInterest, rateBuckets } = require(path.join(serverRoot, 'contract.cjs'));
  const { createInterestHandler } = require(path.join(serverRoot, 'interest.cjs'));
  const { createAvailabilityHandler } = require(path.join(serverRoot, 'availability.cjs'));
  const { exportContacts, run: admin } = require(path.join(serverRoot, 'interest-admin.cjs'));
  const identity = randomUUID();
  const dbName = 'sillage_interest_test_' + identity.replaceAll('-', '');
  const clients = [];
  const client = new MongoClient(args['mongo-url'], CLIENT_OPTIONS);
  clients.push(client);
  const db = client.db(dbName);
  const phases = [];
  const started = Date.now();
  let owned = false, server, browser, browserServer, phase = 'mongo_identity', success = false, clean = false, failureCode;
  let origin, availability = 'coming_soon', failStore = false, ip = '203.0.113.1', probes = 0;
  const requests = [], errors = [], blocked = [];
  const passed = name => { phases.push(name); process.stdout.write(JSON.stringify({ passed: name }) + '\n'); };
  const body = (email, extra = {}) => ({ schema_version: 1, name: 'Synthetic Founder', email,
    consent: true, source: 'signup', ...extra });
  try {
    const hello = await client.db('admin').command({ hello: 1 });
    check(hello.setName === 'guardian-r102' && hello.isWritablePrimary, 'replica_identity_mismatch');
    check(!(await client.db('admin').admin().listDatabases({ nameOnly: true })).databases.some(row => row.name === dbName), 'fixture_database_exists');
    await db.collection('_fixture_owner').insertOne({ _id: identity });
    owned = true;
    await bootstrap(client, dbName);
    const store = new MongoInterestStore(client, dbName);
    for (const collection of [COLLECTIONS.contacts, COLLECTIONS.rates]) {
      const indexes = await db.collection(collection).listIndexes().toArray();
      check(indexes.some(index => index.key.expiresAt === 1 && index.expireAfterSeconds === 0), 'ttl_index_missing');
    }
    passed('actual_replica_bootstrap_and_ttl_indexes');

    const env = { SILLAGE_INTEREST_HMAC_KEY: 'synthetic-public-launch-hmac-key-'.repeat(2) };
    const interest = createInterestHandler({ env, clientIp: () => ip,
      originCheck: req => { if (req.headers.origin !== origin) throw new PublicError('invalid_origin', 403); },
      store: { register: (...values) => { if (failStore) throw new Error('synthetic_database_outage'); return store.register(...values); } } });
    const coming = createAvailabilityHandler({ env: {} });
    const workspace = createAvailabilityHandler({ env: { SILLAGE_WORKSPACE_URL: 'https://workspace.example.test' },
      transport: async target => {
        check(target === 'https://workspace.example.test/api/ready', 'unexpected_readiness_target');
        probes += 1;
        if (availability === 'hanging') return new Promise(() => {});
        return availability === 'ready';
      } });
    const publicPaths = new Set(['/', '/welcome', '/demo', '/signin', '/setup', '/signup', '/privacy', '/waitlist']);
    const assetPaths = new Set(Object.values(manifest.files).map(value => new URL(value, 'http://fixture.test').pathname));
    for (const name of ['favicon.svg', 'favicon.ico', 'apple-touch-icon.png', 'manifest.json', 'HankenGrotesk-OFL.txt', 'IBMPlexMono-OFL.txt']) assetPaths.add('/' + name);
    const mime = { '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.png': 'image/png', '.svg': 'image/svg+xml', '.json': 'application/json', '.ico': 'image/x-icon', '.woff2': 'font/woff2', '.txt': 'text/plain' };
    server = http.createServer(async (req, res) => {
      const pathname = new URL(req.url, origin).pathname;
      if (pathname.startsWith('/api/')) requests.push({ pathname, authorization: !!req.headers.authorization, cookie: !!req.headers.cookie });
      if (pathname === '/api/interest') return interest(req, res);
      if (pathname === '/api/availability') return (availability === 'coming_soon' ? coming : workspace)(req, res);
      let relative = publicPaths.has(pathname) ? 'index.html' : assetPaths.has(pathname) ? pathname.slice(1) : null;
      if (!relative || !['GET', 'HEAD'].includes(req.method)) { res.writeHead(404); res.end(); return; }
      const target = path.resolve(staticDir, relative);
      if (!target.startsWith(staticDir + path.sep) || !fs.existsSync(target)) { res.writeHead(404); res.end(); return; }
      res.writeHead(200, { 'Content-Type': mime[path.extname(target)] || 'application/octet-stream', 'Cache-Control': 'no-store' });
      res.end(req.method === 'HEAD' ? undefined : fs.readFileSync(target));
    });
    await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
    origin = `http://127.0.0.1:${server.address().port}`;
    const post = input => fetch(origin + '/api/interest', { method: 'POST',
      headers: { Origin: origin, 'Content-Type': 'application/json' }, body: JSON.stringify(input) });
    phase = 'public_browser';
    browserServer = await chromium.launchServer({ ...(process.platform === 'win32' ? { channel: 'msedge' } : {}), headless: true });
    browser = await chromium.connect(browserServer.wsEndpoint());
    const context = await browser.newContext({ viewport: { width: 1280, height: 960 }, serviceWorkers: 'block' });
    await context.route('**/*', route => {
      if (new URL(route.request().url()).origin !== origin) { blocked.push(true); return route.abort(); }
      return route.continue();
    });
    await context.addInitScript(() => localStorage.setItem('guardian_api_key', 'synthetic-private-key-must-not-be-sent'));
    const page = await context.newPage();
    page.setDefaultTimeout(12000);
    page.on('pageerror', () => errors.push(true));
    await page.goto(origin);
    await page.getByRole('heading', { name: 'See the calls behind the answer.', exact: true }).waitFor();
    await page.evaluate(() => document.fonts.ready);
    check(await page.evaluate(async () => {
      const loaded = await Promise.all(['16px "Hanken Grotesk"', '12px "IBM Plex Mono"'].map(font => document.fonts.load(font)));
      return loaded.every(faces => faces.length > 0 && faces.every(face => face.status === 'loaded'));
    }), 'local_fonts_not_ready');
    check(await page.evaluate(() => getComputedStyle(document.documentElement).getPropertyValue('--sillage-paper').trim().toLowerCase()) === '#f6f0e6', 'cream_palette_missing');
    check((await context.request.get(origin + '/favicon.svg')).headers()['content-type'].startsWith('image/svg+xml'), 'brand_favicon_missing');
    check((await context.request.get(origin + '/apple-touch-icon.png')).status() === 200, 'touch_icon_missing');
    const sourcePaths = page.getByRole('group', { name: 'Explore connection paths', exact: true });
    for (const [name, heading] of [
      [/^Existing telemetry/, 'Use the signal you already have.'],
      [/^Another application/, 'Send the measurements you own.'],
      [/^A Python application/, 'Start where the calls happen.'],
    ]) {
      const source = sourcePaths.getByRole('button', { name });
      await source.focus();
      await page.keyboard.press('Enter');
      check(await source.getAttribute('aria-pressed') === 'true', 'source_path_keyboard_selection_failed');
      await page.locator('#source-explanation').getByRole('heading', { name: heading, exact: true }).waitFor();
    }
    await page.screenshot({ path: path.join(reportDir, 'landing-desktop.png'), fullPage: true });
    await page.setViewportSize({ width: 390, height: 844 });
    check(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), 'mobile_landing_overflow');
    await page.screenshot({ path: path.join(reportDir, 'landing-mobile.png'), fullPage: true });
    await page.setViewportSize({ width: 1280, height: 960 });
    await page.goto(origin + '/demo');
    await page.getByRole('heading', { name: 'A slow answer, explained.', exact: true }).waitFor();
    phase = 'interactive_sample_evidence';
    const replay = page.getByRole('slider', { name: 'Replay position', exact: true });
    const callTimeline = page.getByLabel('Sample call timeline', { exact: true });
    const callFlow = page.getByLabel('Sample call flow', { exact: true });
    const classifyNode = callFlow.getByRole('button', { name: 'Inspect Classify question in flow', exact: true });
    const draftNode = callFlow.getByRole('button', { name: 'Inspect Draft answer in flow', exact: true });
    const rule = page.getByRole('slider', { name: 'Demo duration rule', exact: true });
    const comparison = page.getByLabel('Demo rule comparison', { exact: true });
    check(await replay.inputValue() === await replay.getAttribute('max'), 'demo_must_start_with_complete_sample');
    check(await page.getByRole('button', { name: 'Pause replay', exact: true }).count() === 0, 'demo_autoplayed');
    await classifyNode.focus();
    await page.keyboard.press('Enter');
    check(await classifyNode.getAttribute('aria-pressed') === 'true', 'demo_flow_keyboard_selection_failed');
    await page.getByLabel('Sample trace detail', { exact: true }).getByRole('heading', { name: 'Classify question', exact: true }).waitFor();
    await page.getByRole('button', { name: 'Restart replay', exact: true }).click();
    check(await replay.inputValue() === '0', 'demo_restart_not_paused_at_start');
    check(await callTimeline.getByRole('button').count() > 0
      && await callTimeline.getByRole('button', { disabled: true }).count() === await callTimeline.getByRole('button').count(), 'demo_future_calls_exposed');
    await page.getByText('Waiting for a captured call.', { exact: true }).waitFor();
    await replay.focus();
    await page.keyboard.press('ArrowRight');
    check(Number(await replay.inputValue()) > 0, 'demo_scrubber_not_keyboard_operable');
    await page.keyboard.press('End');
    check(await replay.inputValue() === await replay.getAttribute('max'), 'demo_scrubber_cannot_reach_end');
    check(await callTimeline.getByRole('button', { disabled: true }).count() === 0, 'demo_scrubber_did_not_reveal_recorded_calls');
    check(await draftNode.isEnabled(), 'demo_scrubber_did_not_reveal_flow_call');
    await draftNode.click();
    check(await draftNode.getAttribute('aria-pressed') === 'true', 'demo_flow_captured_call_not_selected');
    await page.getByLabel('Sample trace detail', { exact: true }).getByRole('heading', { name: 'Draft answer', exact: true }).waitFor();
    await page.getByRole('button', { name: 'Replay sample', exact: true }).click();
    check(await draftNode.isDisabled(), 'demo_replay_exposed_pending_flow_call');
    await page.waitForFunction(() => Number(document.querySelector('[aria-label="Replay position"]').value) > 0);
    await page.getByRole('button', { name: 'Pause replay', exact: true }).click();
    const pausedAt = await replay.inputValue();
    await page.evaluate(() => new Promise(resolve => setTimeout(resolve, 180)));
    check(await replay.inputValue() === pausedAt, 'demo_pause_did_not_stop');
    await page.getByRole('button', { name: 'Continue replay', exact: true }).click();
    await page.waitForFunction(value => Number(document.querySelector('[aria-label="Replay position"]').value) > Number(value), pausedAt);
    await page.getByRole('button', { name: 'Pause replay', exact: true }).click();
    await replay.focus();
    await page.keyboard.press('End');
    const capturedTimeline = await callTimeline.innerText();
    const initialRule = await rule.inputValue();
    const initialComparison = await comparison.innerText();
    await rule.focus();
    await page.keyboard.press('End');
    check(await rule.inputValue() !== initialRule && await comparison.innerText() !== initialComparison, 'demo_rule_did_not_compare');
    check(await callTimeline.innerText() === capturedTimeline, 'demo_rule_mutated_captured_evidence');
    await page.getByRole('button', { name: 'Reset demo rule', exact: true }).click();
    check(await rule.inputValue() === initialRule && await comparison.innerText() === initialComparison, 'demo_rule_reset_failed');
    const lenses = page.getByRole('group', { name: 'Measurement lens', exact: true });
    for (const lens of ['Tokens', 'Cost', 'Duration']) {
      const button = lenses.getByRole('button', { name: lens, exact: true });
      await button.focus();
      await page.keyboard.press('Enter');
      check(await button.getAttribute('aria-pressed') === 'true', 'demo_lens_keyboard_selection_failed');
    }
    await page.getByRole('button', { name: 'Agent handoff', exact: true }).click();
    await lenses.getByRole('button', { name: 'Cost', exact: true }).click();
    check((await callTimeline.innerText()).includes('Unknown'), 'demo_unknown_cost_was_invented');
    await lenses.getByRole('button', { name: 'Tokens', exact: true }).click();
    check((await callTimeline.innerText()).includes('Unknown'), 'demo_unknown_tokens_were_invented');
    await page.emulateMedia({ reducedMotion: 'reduce' });
    await page.reload();
    await page.getByRole('heading', { name: 'A slow answer, explained.', exact: true }).waitFor();
    check(await page.evaluate(() => matchMedia('(prefers-reduced-motion: reduce)').matches), 'reduced_motion_fixture_not_active');
    check(await page.getByRole('button', { name: 'Pause replay', exact: true }).count() === 0, 'reduced_motion_demo_autoplayed');
    await replay.focus();
    await page.keyboard.press('Home');
    check(await replay.inputValue() === '0', 'reduced_motion_scrubber_cannot_rewind');
    for (let step = 0; step < 50; step += 1) await page.keyboard.press('ArrowRight');
    check(await replay.inputValue() === '500', 'reduced_motion_midpoint_scrub_failed');
    const flowMarkers = callFlow.locator('.sg-evidence-flow-marker');
    check(await flowMarkers.count() > 0
      && await flowMarkers.evaluateAll(markers => markers.every(marker => getComputedStyle(marker).display === 'none')), 'reduced_motion_flow_marker_visible');
    await page.keyboard.press('End');
    check(await replay.inputValue() === await replay.getAttribute('max'), 'reduced_motion_scrubber_cannot_complete');
    for (const width of [320, 390]) {
      await page.setViewportSize({ width, height: 844 });
      check(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), 'mobile_demo_overflow');
      await page.screenshot({ path: path.join(reportDir, `interactive-demo-${width}.png`), fullPage: true });
    }
    await page.emulateMedia({ reducedMotion: 'no-preference' });
    await page.setViewportSize({ width: 1280, height: 960 });
    check(requests.length === 0, 'public_demo_requested_private_api');
    passed('sample_replay_keyboard_scrub_lenses_local_rules_reduced_motion_and_mobile');
    passed('built_landing_and_demo_without_backend_or_session');

    phase = 'availability_browser';
    await page.goto(origin + '/signin');
    await page.getByRole('heading', { name: 'Sign-in is coming soon', exact: true }).waitFor();
    check(probes === 0, 'unconfigured_workspace_was_probed');
    await page.screenshot({ path: path.join(reportDir, 'coming-soon-desktop.png'), fullPage: true });
    availability = 'down';
    await page.getByRole('button', { name: 'Retry access', exact: true }).click();
    await page.getByRole('heading', { name: 'Currently unavailable', exact: true }).waitFor();
    availability = 'hanging';
    const beforeTimeout = Date.now();
    await page.getByRole('button', { name: 'Retry access', exact: true }).click();
    await page.getByRole('heading', { name: 'Currently unavailable', exact: true }).waitFor();
    check(Date.now() - beforeTimeout < 6000, 'availability_deadline_unbounded');
    availability = 'ready';
    await page.getByRole('button', { name: 'Retry access', exact: true }).click();
    await page.getByRole('heading', { name: 'Your workspace is ready.', exact: true }).waitFor();
    check(await page.getByRole('link', { name: 'Sign in to your workspace', exact: true }).getAttribute('href') === 'https://workspace.example.test/signin', 'signin_link_invalid');
    await page.goto(origin + '/setup');
    await page.getByRole('heading', { name: 'Your workspace is ready.', exact: true }).waitFor();
    check(await page.getByRole('link', { name: 'Sign in and connect', exact: true }).getAttribute('href') === 'https://workspace.example.test/setup', 'onboarding_link_invalid');
    passed('unconfigured_down_hanging_recovered_workspace_and_explicit_links');

    phase = 'browser_registration';
    availability = 'down';
    await page.goto(origin + '/setup');
    await page.getByRole('heading', { name: 'Currently unavailable', exact: true }).waitFor();
    await page.setViewportSize({ width: 390, height: 844 });
    check(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), 'mobile_form_overflow');
    await page.screenshot({ path: path.join(reportDir, 'unavailable-mobile.png'), fullPage: true });
    const fill = async (email, company = 'Synthetic Company') => {
      await page.getByLabel('Your name', { exact: false }).fill('Synthetic Founder');
      await page.getByLabel('Email', { exact: false }).fill(email);
      await page.locator('summary').filter({ hasText: 'Add company or project details' }).click();
      await page.getByLabel('Company', { exact: false }).fill(company);
      await page.getByLabel('What are you building?', { exact: false }).fill('Synthetic acceptance test. No real customer data.');
      await page.getByRole('checkbox').check();
    };
    const firstEmail = 'synthetic-founder@example.test';
    await fill(firstEmail, '=SYNTHETIC()');
    await page.getByRole('button', { name: 'Register', exact: true }).click();
    await page.getByRole('heading', { name: 'You\u2019re on the list.', exact: true }).waitFor();
    await page.waitForURL(origin + '/waitlist');
    check(await page.getByLabel('Your name', { exact: false }).count() === 0, 'saved_registration_retained_form');
    const contact = await db.collection(COLLECTIONS.contacts).findOne({ _id: firstEmail });
    check(contact?.source === 'onboarding' && contact.verified === false && contact.consent.accepted === true
      && contact.consent.version && contact.expiresAt - contact.createdAt === 180 * 86400000, 'persistent_contact_contract_invalid');
    await page.screenshot({ path: path.join(reportDir, 'registered-mobile.png'), fullPage: true });
    passed('backend_down_registration_committed_with_consent_and_retention');

    phase = 'waitlist_confirmation_boundary';
    await page.reload();
    await page.getByRole('heading', { name: 'Find your way into Sillage.', exact: true }).waitFor();
    check(await page.getByRole('heading', { name: 'You\u2019re on the list.', exact: true }).count() === 0, 'waitlist_reload_claimed_registration');
    await page.goto(origin + '/waitlist?registered=true');
    await page.getByRole('heading', { name: 'Find your way into Sillage.', exact: true }).waitFor();
    check(!(await page.locator('body').innerText()).includes('REGISTRATION RECEIVED'), 'waitlist_query_claimed_registration');
    await page.getByRole('heading', { name: 'Workspace sign-in is currently unavailable.', exact: true }).waitFor();
    passed('waitlist_only_confirms_actual_ack_not_reload_or_query');

    phase = 'registration_failure_retry';
    ip = '203.0.113.2';
    const beforeSignupProbes = probes;
    await page.goto(origin + '/signup');
    await page.getByRole('heading', { name: 'A clearer view of your AI.', exact: true }).waitFor();
    check(probes === beforeSignupProbes, 'signup_depends_on_backend_probe');
    const retryEmail = 'synthetic-retry@example.test';
    await fill(retryEmail);
    failStore = true;
    await page.getByRole('button', { name: 'Register', exact: true }).click();
    await page.getByRole('alert').waitFor();
    check((await page.getByRole('alert').innerText()).includes('could not confirm'), 'storage_failure_missing');
    check(await page.getByLabel('Email', { exact: false }).inputValue() === retryEmail, 'failed_submission_lost_input');
    check(await page.getByRole('heading', { name: 'You\u2019re on the list.', exact: true }).count() === 0 && page.url() === origin + '/signup', 'failed_write_claimed_saved');
    check(await db.collection(COLLECTIONS.contacts).countDocuments({ _id: retryEmail }) === 0, 'failed_write_created_contact');
    failStore = false;
    await page.getByRole('button', { name: 'Register', exact: true }).click();
    await page.getByRole('heading', { name: 'You\u2019re on the list.', exact: true }).waitFor();
    passed('actual_http_storage_failure_retains_input_and_retry_saves');

    phase = 'duplicate_persistence';
    ip = '203.0.113.3';
    const duplicate = await Promise.all([post(body(firstEmail.toUpperCase(), { name: 'Replacement must not win' })), post(body(firstEmail))]);
    check(duplicate.every(response => response.status === 202), 'concurrent_duplicate_failed');
    check(duplicate.every(response => response.headers.get('cache-control').includes('no-store')), 'private_response_cacheable');
    const reconnect = new MongoClient(args['mongo-url'], CLIENT_OPTIONS);
    clients.push(reconnect);
    const restored = await reconnect.db(dbName).collection(COLLECTIONS.contacts).findOne({ _id: firstEmail });
    check(restored?.name === contact.name && restored.createdAt.getTime() === contact.createdAt.getTime()
      && restored.expiresAt.getTime() === contact.expiresAt.getTime()
      && await reconnect.db(dbName).collection(COLLECTIONS.contacts).countDocuments({ _id: firstEmail }) === 1, 'duplicate_replaced_original_or_lost_persistence');
    passed('concurrent_normalized_duplicates_preserve_original_after_new_client');

    phase = 'durable_rate_limit';
    ip = '203.0.113.4';
    for (let i = 0; i < 5; i++) check((await post(body(`synthetic-rate-${i}@example.test`))).status === 202, 'rate_fixture_admission_failed');
    const contactCount = await db.collection(COLLECTIONS.contacts).countDocuments();
    const rateBefore = await db.collection(COLLECTIONS.rates).find({}).sort({ _id: 1 }).toArray();
    const limited = await post(body('synthetic-rejected@example.test'));
    check(limited.status === 429 && Number(limited.headers.get('retry-after')) > 0, 'durable_rate_not_enforced');
    check(await db.collection(COLLECTIONS.contacts).countDocuments() === contactCount, 'limited_contact_was_persisted');
    const rateAfter = await db.collection(COLLECTIONS.rates).find({}).sort({ _id: 1 }).toArray();
    check(JSON.stringify(rateBefore) === JSON.stringify(rateAfter), 'rejected_transaction_changed_rate_counters');
    check(!JSON.stringify(rateAfter).includes('203.0.113'), 'raw_ip_stored');
    passed('real_transaction_rate_limit_rollback_and_no_raw_ip');

    phase = 'operator_export_delete_expiry';
    const csvPath = path.join(reportDir, 'synthetic-contacts.csv');
    const exportResult = await exportContacts(db, csvPath);
    check(exportResult.exported === contactCount && fs.readFileSync(csvPath, 'utf8').includes("\"'=SYNTHETIC()\""), 'export_not_complete_or_formula_safe');
    fs.unlinkSync(csvPath); // Only this exact newly-created synthetic export.
    const deleted = await admin(['delete', '--email', retryEmail.toUpperCase(), '--confirm-delete'], {
      env: { SILLAGE_INTEREST_MONGO_URL: 'mongodb+srv://synthetic.example.test', SILLAGE_INTEREST_DB: dbName },
      createClient: () => { const c = new MongoClient(args['mongo-url'], CLIENT_OPTIONS); clients.push(c); return c; } });
    check(deleted.deleted === 1 && await db.collection(COLLECTIONS.contacts).countDocuments({ _id: retryEmail }) === 0
      && await db.collection(COLLECTIONS.contacts).countDocuments({ _id: firstEmail }) === 1, 'single_contact_delete_invalid');
    const renewalTime = new Date(contact.expiresAt.getTime() + 1);
    const expiredPath = path.join(reportDir, 'synthetic-expired.csv');
    const expired = await exportContacts(db, expiredPath, new Date(renewalTime.getTime() + 86400000));
    check(expired.exported === 0, 'logically_expired_contacts_exported');
    fs.unlinkSync(expiredPath);
    await store.register(interestRecord(validateInterest(body(firstEmail, { name: 'Synthetic Renewal' })), renewalTime),
      rateBuckets('203.0.113.8', env.SILLAGE_INTEREST_HMAC_KEY, renewalTime));
    const renewal = await db.collection(COLLECTIONS.contacts).findOne({ _id: firstEmail });
    check(renewal.name === 'Synthetic Renewal' && renewal.createdAt.getTime() === renewalTime.getTime(), 'expired_contact_not_renewed');
    passed('actual_private_export_formula_safety_exact_delete_and_logical_expiry');

    phase = 'public_privacy_and_isolation';
    await page.goto(origin + '/privacy');
    await page.getByRole('heading', { name: 'Registration & privacy.', exact: true }).waitFor();
    check(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), 'mobile_privacy_overflow');
    check(!errors.length && !blocked.length, 'browser_runtime_error_or_external_request');
    check(requests.every(request => ['/api/interest', '/api/availability'].includes(request.pathname)
      && !request.authorization && !request.cookie), 'public_flow_used_workspace_auth');
    check(await page.evaluate(() => localStorage.getItem('guardian_api_key')) === 'synthetic-private-key-must-not-be-sent', 'public_flow_modified_private_key');
    passed('public_privacy_mobile_and_auth_isolation');
    success = true;
  } catch (error) {
    failureCode = /^[a-z][a-z_]{0,100}$/.test(error?.message || '') ? error.message : 'fixture_operation_failed';
    throw error;
  } finally {
    if (browser) await browser.close();
    if (browserServer) await browserServer.close();
    if (server) { server.closeAllConnections(); await new Promise(resolve => server.close(resolve)); }
    if (owned) {
      const marker = await db.collection('_fixture_owner').findOne({ _id: identity });
      check(marker?._id === identity && dbName.startsWith('sillage_interest_test_'), 'cleanup_database_ownership_mismatch');
      await db.dropDatabase();
    }
    for (const connection of clients.reverse()) await connection.close();
    clean = true;
    fs.writeFileSync(path.join(reportDir, 'report.json'), JSON.stringify({ success, phase, failureCode, phases,
      elapsed_ms: Date.now() - started, cleanup_complete: clean,
      manifest_sha256: createHash('sha256').update(manifestBytes).digest('hex'),
      scope: 'Built public UI, actual Node HTTP functions and isolated Mongo replica; readiness transport is synthetic; no hosted Vercel or paid traffic.' }, null, 2) + '\n');
  }
  check(success && clean, 'public_launch_incomplete');
}

if (require.main === module) main(process.argv.slice(2)).catch(() => {
  process.stderr.write('Public launch acceptance failed; inspect the sanitized report phase.\n'); process.exitCode = 1;
});
module.exports = { main };
