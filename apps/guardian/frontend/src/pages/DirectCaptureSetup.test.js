import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { MemoryRouter } from 'react-router-dom';
import GuardianSetup from './GuardianSetup';
import { GuardianAccessContext } from '@/contexts/GuardianAccess';
import guardianApi, { getGuardianApiOrigin, sendCaptureTest } from '@/services/guardianApi';

jest.mock('./GuardianLayout', () => ({ children }) => <main>{children}</main>);
jest.mock('@/services/guardianApi', () => ({ __esModule: true,
  captureRequestId: () => 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', getGuardianApiOrigin: jest.fn(), sendCaptureTest: jest.fn(),
  default: { getCapture: jest.fn(), getMonitoring: jest.fn(), getMonitoringPolicy: jest.fn(), getNotifications: jest.fn(), listIngestionKeys: jest.fn(), createIngestionKey: jest.fn(), revokeIngestionKey: jest.fn() },
}));

const project = { organization_id: 'org-1', project_id: 'project-1', environment: 'test', name: 'Synthetic Project' };
const capture = (overrides = {}) => ({ mode: 'direct', enabled: true, schema_version: 1,
  collector_path: '/api/guardian/ingest/events', can_manage_keys: true, project,
  limits: { max_batch_events: 100, max_body_bytes: 262144, max_active_keys: 10, max_keys: 100 },
  status: { last_test_received_at: null, last_received_at: null, received_events: 0, pending_events: 0,
    processed_events: 0, last_processed_at: null, conflicted_events: 0, worker_status: 'not_started' }, ...overrides });
const credential = (overrides = {}) => ({ id: 'a'.repeat(32), label: 'production-backend', prefix: 'cg_ingest_aaaaaaaa', status: 'active',
  created_at: '2026-09-12T10:00:00Z', expires_at: '2026-10-12T10:00:00Z', revoked_at: null, last_used_at: null, ...overrides });
const token = `cg_ingest_${'a'.repeat(32)}_${'S'.repeat(43)}`;
const deferred = () => { let resolve; let reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no; }); return { promise, resolve, reject }; };
let container;
let root;
let policyRole = 'owner';
const button = (label) => [...container.querySelectorAll('button')].find((node) => node.textContent === label);
const render = async (role = 'owner') => {
  policyRole = role;
  await act(async () => root.render(<GuardianAccessContext.Provider value={{ auth_mode: 'oidc', actor: { role }, project, permissions: ['read'] }}>
    <MemoryRouter><GuardianSetup /></MemoryRouter></GuardianAccessContext.Provider>));
};
const input = async (id, value) => act(async () => {
  const node = container.querySelector(`#${id}`);
  Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(node, value);
  node.dispatchEvent(new Event('input', { bubbles: true }));
});
const create = async () => { await input('ingestion-label', 'production-backend'); await act(async () => container.querySelector('form').dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }))); };

beforeEach(() => {
  jest.resetAllMocks(); localStorage.clear(); sessionStorage.clear();
  getGuardianApiOrigin.mockReturnValue(window.location.origin);
  guardianApi.getCapture.mockResolvedValue({ data: capture() });
  guardianApi.getMonitoring.mockResolvedValue({ data: {} });
  guardianApi.getNotifications.mockImplementation(async () => ({ data: { schema_version: 1, revision: 0, project, can_manage: policyRole === 'owner', updated_at: null,
    destination: { channel: 'slack', state: 'not_configured', verified: false, enabled: false }, worker: { status: 'unknown', last_seen_at: null }, deliveries: [], has_more: false } }));
  guardianApi.getMonitoringPolicy.mockImplementation(async () => ({ data: { schema_version: 1, revision: 0, updated_at: null, updated_by: null,
    project, can_manage: policyRole === 'owner', rules: { max_call_cost_usd: null, max_call_latency_ms: null, alert_on_errors: true } } }));
  guardianApi.listIngestionKeys.mockResolvedValue({ data: { credentials: [] } });
  guardianApi.createIngestionKey.mockResolvedValue({ status: 201, data: { credential: credential(), token } });
  guardianApi.revokeIngestionKey.mockResolvedValue({ status: 200, data: { credential: credential({ status: 'revoked', revoked_at: '2026-09-12T10:01:00Z' }) } });
  sendCaptureTest.mockResolvedValue({ batch_id: 'test-batch' });
  container = document.createElement('div'); document.body.appendChild(container); root = createRoot(container);
});
afterEach(async () => { await act(async () => root.unmount()); container.remove(); jest.restoreAllMocks(); });

test('direct owner setup distinguishes no real receipt and stopped worker from source polling', async () => {
  await render();
  expect(container.textContent).toContain('Send events directly');
  expect(container.textContent).toContain('No real event receipt is recorded');
  expect(container.textContent).toContain('Worker has not reported yet');
  expect(container.textContent).not.toContain('Last source checkpoint');
  expect(button('Create ingestion key')).toBeDefined();
  expect(container.textContent).not.toMatch(/Monitoring is active|Monitoring is healthy/);
});

test('fresh onboarding explains the application key and opens only the first step', async () => {
  await render();
  expect(container.querySelector('h1').textContent).toBe('Connections');
  expect(container.querySelector('[data-testid="connection-status"]').textContent).toBe('Waiting for your first app call');
  expect(container.textContent).toContain('Your sign-in gives you access to the dashboard');
  expect(container.textContent).toContain('Sillage does not need your OpenAI or other provider API key');
  expect(container.querySelector('#connection-keys').open).toBe(true);
  for (const id of ['integrate', 'test', 'verify', 'rules', 'notifications']) {
    expect(container.querySelector(`#connection-${id}`).open).toBe(false);
  }
  expect(container.querySelectorAll('[aria-label="How application data reaches Sillage"] > li')).toHaveLength(3);
  expect(sendCaptureTest).not.toHaveBeenCalled();
  expect(guardianApi.createIngestionKey).not.toHaveBeenCalled();
});

test('launcher is the default integration and optional testing follows real-call verification', async () => {
  await render(); await create();
  expect(button('Python: install + run').getAttribute('aria-pressed')).toBe('true');
  expect(container.querySelector('#provider-integration-title').closest('[hidden]')).not.toBeNull();
  expect(container.textContent).toContain('Langfuse is not used by this workspace');
  await act(async () => button('Continue to install').click());
  expect(container.querySelector('#connection-integrate').open).toBe(true);
  expect(container.querySelector('#one-time-ingestion-key').value).toBe(token);
  expect(container.querySelector('[aria-label="Sillage server configuration"]').textContent).not.toContain(token);
  const steps = [...container.querySelectorAll('details[id^="connection-"]')].map(node => node.id);
  expect(steps.indexOf('connection-test')).toBeGreaterThan(steps.indexOf('connection-verify'));
  expect(sendCaptureTest).not.toHaveBeenCalled();
});

test('a known active key guides the user to integration without treating it as traffic', async () => {
  guardianApi.listIngestionKeys.mockResolvedValue({ data: { credentials: [credential()] } });
  await render();
  expect(button('Integrate your app')).toBeDefined();
  await act(async () => button('Integrate your app').click());
  expect(container.querySelector('#connection-integrate').open).toBe(true);
  expect(container.querySelector('[data-testid="connection-status"]').textContent).toBe('Waiting for your first app call');
  expect(container.querySelector('#connection-verify summary').textContent).toContain('Awaiting app call');
  expect(container.textContent).toContain('this Sillage deployment\'s base address, without /api');
  expect(container.textContent).toContain('This is not your OpenAI key or dashboard sign-in');
});

test('custom-provider setup exposes the metadata contract without requiring an OpenAI client', async () => {
  await render('viewer');
  await act(async () => button('Manual Python / Node').click());
  await act(async () => button('Other providers / custom JSON').click());
  expect(container.querySelector('#provider-integration-title').textContent).toBe('Connect another provider');
  const json = [...container.querySelectorAll('details')].find((node) => node.querySelector('summary')?.textContent.startsWith('Advanced: Sillage JSON'));
  expect(json.open).toBe(true);
  expect(json.textContent).toContain('REPLACE_WITH_CALL_START_UTC');
  expect(json.textContent).toContain('X-Guardian-Ingest-Key');
  expect(container.textContent).toContain('an ingestion key alone does not capture calls automatically');
  expect(guardianApi.createIngestionKey).not.toHaveBeenCalled();
  expect(sendCaptureTest).not.toHaveBeenCalled();
});

test('helper download follows the selected language on the authenticated same-origin route', async () => {
  await render(); await create();
  await act(async () => button('Manual Python / Node').click());
  const download = () => container.querySelector('a[download^="sillage-"]');
  expect(download().getAttribute('href')).toBe(window.location.origin + '/api/guardian/integrations/python.zip');
  expect(download().textContent).toContain('Download Python helpers');
  expect(download().getAttribute('download')).toBe('sillage-python.zip');
  await act(async () => button('Node').click());
  expect(download().getAttribute('href')).toBe(window.location.origin + '/api/guardian/integrations/node.zip');
  expect(download().textContent).toContain('Download Node helpers');
  expect(download().outerHTML).not.toContain(token);
  expect(container.querySelector('#one-time-ingestion-key').value).toBe(token);
});

test('split-origin local setup uses the configured API address for downloads and app configuration', async () => {
  getGuardianApiOrigin.mockReturnValue('http://localhost:8001');
  await render();
  await act(async () => button('Manual Python / Node').click());
  expect(container.querySelector('a[download^="sillage-"]').getAttribute('href')).toBe('http://localhost:8001/api/guardian/integrations/python.zip');
  const url = [...container.querySelectorAll('dt')].find((node) => node.textContent === 'GUARDIAN_URL');
  expect(url.nextElementSibling.textContent).toContain('http://localhost:8001');
});

test('unconfirmed API configuration does not create a download link or invent an application URL', async () => {
  getGuardianApiOrigin.mockReturnValue(null);
  await render();
  expect(container.querySelector('a[download]')).toBeNull();
  expect(container.textContent).toContain('The capture address is unavailable');
  const url = [...container.querySelectorAll('dt')].find((node) => node.textContent === 'GUARDIAN_URL');
  expect(url.nextElementSibling.textContent).toContain('Unavailable');
});

test('observed processing links to evidence without claiming complete monitoring', async () => {
  guardianApi.getCapture.mockResolvedValue({ data: capture({ status: { ...capture().status,
    last_received_at: '2026-09-12T10:00:00Z', received_events: 2, processed_events: 2,
    last_processed_at: '2026-09-12T10:00:05Z', worker_status: 'current' } }) });
  await render();
  expect(container.querySelector('[data-testid="connection-status"]').textContent).toBe('Application events processed');
  await act(async () => button('Check processing').click());
  expect(container.querySelector('#connection-verify').open).toBe(true);
  expect(container.textContent).toContain('Overview totals and incident checks can finish after inbox processing');
  expect(container.textContent).not.toMatch(/Monitoring is active|Monitoring is healthy|All calls captured/);
});

test('unknown receipt timing is not presented as a never-connected application', async () => {
  guardianApi.getCapture.mockResolvedValue({ data: capture({ status: { ...capture().status, received_events: 4 } }) });
  await render();
  expect(container.querySelector('[data-testid="connection-status"]').textContent).toBe('Receipt timing is unconfirmed');
  expect(container.querySelector('[data-testid="connection-status"]').textContent).not.toContain('first app call');
});

test('revoked key metadata explains replacement and does not mark a usable connection', async () => {
  guardianApi.listIngestionKeys.mockResolvedValue({ data: { credentials: [credential({ status: 'revoked', revoked_at: '2026-09-12T10:01:00Z' })] } });
  await render();
  expect(container.textContent).toContain('0 active keys');
  expect(button('Integrate your app')).toBeUndefined();
  expect(button('Connect your first app')).toBeDefined();
  expect(container.textContent).toContain('Revoked keys cannot be restored');
  expect(container.textContent).toContain('does not delete project history');
});

test.each(['viewer', 'operator'])('%s sees redacted keys and receipt state without management controls', async (role) => {
  guardianApi.listIngestionKeys.mockResolvedValue({ data: { credentials: [credential()] } });
  await render(role);
  expect(container.textContent).toContain('production-backend');
  expect(container.textContent).toContain('cg_ingest_aaaaaaaa');
  expect(container.querySelector('form')).toBeNull();
  expect(button('Revoke')).toBeUndefined();
  expect(guardianApi.createIngestionKey).not.toHaveBeenCalled();
});

test('owner role alone cannot override the capture management flag', async () => {
  guardianApi.getCapture.mockResolvedValue({ data: capture({ can_manage_keys: false }) });
  await render();
  expect(button('Create ingestion key')).toBeUndefined();
});

test('cold capture outage keeps mode unknown and can retry without a source diagnostic request', async () => {
  guardianApi.getCapture.mockRejectedValueOnce({ response: { status: 503 } });
  await render();
  expect(container.textContent).toContain('Capture setup is unavailable');
  expect(container.textContent).not.toContain('Existing source diagnostics');
  expect(guardianApi.getMonitoring).not.toHaveBeenCalled();
  expect(button('Retry setup check').disabled).toBe(false);
  await act(async () => button('Retry setup check').click());
  expect(container.textContent).toContain('Send events directly');
});

test('a test receipt does not establish real traffic or completed processing', async () => {
  guardianApi.getCapture.mockResolvedValue({ data: capture({ status: { ...capture().status, last_test_received_at: '2026-09-12T10:00:00Z' } }) });
  await render();
  expect(container.textContent).toContain('2026-09-12 10:00:00.000 UTC');
  expect(container.textContent).toContain('A successful test alone does not establish application traffic');
});

test('received work, processing backlog, conflicts and stale heartbeat remain distinct', async () => {
  guardianApi.getCapture.mockResolvedValue({ data: capture({ status: { ...capture().status,
    last_received_at: '2026-09-12T10:00:00Z', received_events: 4, pending_events: 3, processed_events: 1,
    conflicted_events: 1, worker_status: 'stale' } }) });
  await render();
  expect(container.textContent).toContain('Worker heartbeat is stale');
  const detail = (label) => [...container.querySelectorAll('dt')].find((node) => node.textContent === label).nextElementSibling.textContent;
  expect(detail('Accepted real events')).toBe('4'); expect(detail('Events awaiting processing')).toBe('3');
  expect(detail('Processed events')).toBe('1'); expect(detail('Conflicted events')).toBe('1');
  expect(container.textContent).toContain('Accepted data may still await checks and totals');
});

test.each([null, [], capture({ collector_path: 'https://outside.invalid/collect' }), capture({ project: { ...project, project_id: 'different' } }),
  capture({ status: { ...capture().status, pending_events: -1 } })])('malformed or wrong-scope capture response fails safely', async (data) => {
  guardianApi.getCapture.mockResolvedValue({ data }); await render();
  expect(container.textContent).toContain('Capture setup is unavailable');
  expect(button('Create ingestion key')).toBeUndefined();
  expect(guardianApi.listIngestionKeys).not.toHaveBeenCalled();
  expect(container.textContent).not.toContain('outside.invalid');
  expect(container.textContent).not.toContain('This deployment uses its existing telemetry source');
  expect(container.textContent).not.toContain('Last source checkpoint');
});

test('unexpected secret fields in polled metadata are rejected instead of retained or displayed', async () => {
  guardianApi.listIngestionKeys.mockResolvedValue({ data: { credentials: [{ ...credential(), token: 'private-leak-canary' }] } });
  await render();
  expect(container.textContent).toContain('Ingestion key metadata is unavailable');
  expect(container.textContent).not.toContain('private-leak-canary');
  expect(button('Create ingestion key').disabled).toBe(true);
});

test.each([credential({ revoked_at: '2026-09-12T10:01:00Z' }), credential({ expires_at: '2026-09-11T10:00:00Z' })])(
  'inconsistent key status or expiry cannot be displayed as usable metadata', async (value) => {
    guardianApi.listIngestionKeys.mockResolvedValue({ data: { credentials: [value] } });
    await render(); expect(container.textContent).toContain('Ingestion key metadata is unavailable');
    expect(button('Revoke')).toBeUndefined();
  },
);

test('only a confirmed create response reveals a key once without storing it', async () => {
  await render(); await create();
  expect(guardianApi.createIngestionKey).toHaveBeenCalledWith({ request_id: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', label: 'production-backend', expires_in_days: 30 }, { signal: expect.any(AbortSignal) });
  expect(container.querySelector('#one-time-ingestion-key').value).toBe(token);
  expect(JSON.stringify(localStorage)).not.toContain(token); expect(JSON.stringify(sessionStorage)).not.toContain(token);
  expect(container.querySelector('pre').textContent).not.toContain(token);
  await act(async () => button('Dismiss key').click());
  expect(container.querySelector('#one-time-ingestion-key')).toBeNull();
  expect(container.textContent).not.toContain(token);
  expect(button('Create ingestion key')).toBeDefined();
});

test('an in-flight create cannot be submitted twice or reveal after unmount', async () => {
  const pending = deferred(); guardianApi.createIngestionKey.mockReturnValue(pending.promise);
  await render(); await create();
  await act(async () => container.querySelector('form').dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })));
  expect(guardianApi.createIngestionKey).toHaveBeenCalledTimes(1);
  const { signal } = guardianApi.createIngestionKey.mock.calls[0][1];
  await act(async () => root.unmount()); expect(signal.aborted).toBe(true);
  await act(async () => pending.resolve({ status: 201, data: { credential: credential(), token } }));
  expect(container.textContent).toBe('');
});

test.each([{ response: { status: 503 } }, { response: { status: 409 } }])('ambiguous creation never automatically retries or invents a recoverable secret', async (error) => {
  guardianApi.createIngestionKey.mockRejectedValue(error); await render(); await create();
  expect(container.textContent).toContain('its secret cannot be recovered');
  expect(button('Create ingestion key').disabled).toBe(true);
  expect(guardianApi.createIngestionKey).toHaveBeenCalledTimes(1);
  expect(container.querySelector('#one-time-ingestion-key')).toBeNull();
});

test('a malformed created token is never revealed as a valid key', async () => {
  guardianApi.createIngestionKey.mockResolvedValue({ status: 201, data: { credential: credential(), token: 'private-invalid-token' } });
  await render(); await create();
  expect(container.textContent).not.toContain('private-invalid-token');
  expect(container.querySelector('#one-time-ingestion-key')).toBeNull();
  expect(container.textContent).toContain('Key creation was not confirmed');
});

test('clipboard failure leaves a selectable key and accurate manual-copy guidance', async () => {
  await render(); await create();
  Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText: jest.fn().mockRejectedValue(new Error('private-clipboard-error')) } });
  await act(async () => button('Copy key').click());
  expect(container.textContent).toContain('Select the displayed key and copy it manually');
  expect(container.textContent).not.toContain('private-clipboard-error');
  expect(container.querySelector('textarea').readOnly).toBe(true);
});

test('the explicit test uses only the just-created key and describes a test-only receipt', async () => {
  await render(); await create(); await act(async () => button('Send test event').click());
  expect(sendCaptureTest).toHaveBeenCalledWith(token, { signal: expect.any(AbortSignal) });
  expect(container.textContent).toContain('Test event received');
  expect(container.textContent).toContain('creates no production observations, totals or incidents');
  expect(container.textContent).toContain('No real event receipt is recorded');
});

test('an ingestion-key rejection does not claim a dashboard session rejection', async () => {
  sendCaptureTest.mockRejectedValue({ status: 401 }); await render(); await create();
  await act(async () => button('Send test event').click());
  expect(container.textContent).toContain('The ingestion key was rejected');
  expect(container.textContent).toContain('Send events directly');
});

test('failed revocation retains key status and successful retry clears its revealed secret', async () => {
  guardianApi.listIngestionKeys.mockResolvedValue({ data: { credentials: [credential()] } });
  guardianApi.revokeIngestionKey.mockRejectedValueOnce({ response: { status: 503 } });
  await render(); await create(); await act(async () => button('Revoke').click());
  expect(container.textContent).toContain('The key may still accept events');
  expect(container.textContent).toContain('cg_ingest_aaaaaaaa · active');
  await act(async () => button('Revoke').click());
  expect(container.textContent).toContain('Key revoked');
  expect(container.querySelector('#one-time-ingestion-key')).toBeNull();
});

test('lost capture refresh keeps previous counts labelled unknown and disables key mutation', async () => {
  await render(); guardianApi.getCapture.mockRejectedValueOnce(new Error('private-status-error'));
  await act(async () => button('Retry setup check').click());
  expect(container.querySelector('[data-testid="connection-status"]').textContent).toBe('Connection status unavailable');
  expect(container.querySelector('#connection-verify summary').textContent).toContain('Unknown');
  expect(container.textContent).toContain('Current receipt and processing state is unknown');
  expect(button('Create ingestion key')).toBeUndefined();
  expect(container.textContent).not.toContain('private-status-error');
});

test('unavailable counters never become a zero or no-real-traffic claim', async () => {
  guardianApi.getCapture.mockResolvedValue({ data: capture({ status: { ...capture().status,
    received_events: null, pending_events: null, processed_events: null, conflicted_events: null } }) });
  await render();
  expect(container.textContent).toContain('Receipt timing is unknown');
  expect(container.textContent).not.toContain('No real event receipt is recorded');
  for (const label of ['Accepted real events', 'Events awaiting processing', 'Processed events', 'Conflicted events', 'Waiting to process']) {
    const measurement = [...container.querySelectorAll('dt')].find((node) => node.textContent === label);
    expect(measurement).toBeDefined();
    expect(measurement.nextElementSibling.textContent).toBe('Unknown');
    expect(measurement.nextElementSibling.textContent).not.toBe('0');
  }
});

test('a late clipboard result cannot claim that a replacement key was copied', async () => {
  const clipboard = deferred();
  Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText: jest.fn(() => clipboard.promise) } });
  await render(); await create();
  await act(async () => button('Copy key').click());
  await act(async () => button('Dismiss key').click());
  await create();
  await act(async () => clipboard.resolve());
  expect(container.textContent).not.toContain('Copied. Store it');
});

test('a verified role downgrade immediately clears the one-time reveal', async () => {
  await render(); await create();
  expect(container.querySelector('textarea').value).toBe(token);
  await render('viewer');
  expect(container.querySelector('textarea')).toBeNull();
  expect(button('Create ingestion key')).toBeUndefined();
});

const recipeCode = () => container.querySelector('pre[aria-label="OpenAI integration code"]').textContent;
const executeNodeRecipe = async (code, api, streaming, consumer) => {
  const value = Object.freeze({ synthetic: true });
  const createResponse = jest.fn(() => streaming ? [value] : value);
  const client = { responses: { create: createResponse }, chat: { completions: { create: createResponse } } };
  const Exporter = jest.fn();
  const call = jest.fn(async (_exporter, _metadata, operation) => operation());
  const stream = jest.fn(async function* (_exporter, _metadata, operation) { yield* await operation(); });
  const consume = consumer || jest.fn(async () => {});
  const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor;
  const operation = new AsyncFunction('BackgroundExporter', 'openaiCall', 'openaiStream', 'client', 'requestArgs', 'consumeChunk', 'process',
    code.split('\n').filter((line) => !line.startsWith('import ')).join('\n'));
  await operation(Exporter, call, stream, client, { input: 'synthetic input', model: 'old-model' }, consume,
    { env: { GUARDIAN_URL: 'https://guardian.invalid', GUARDIAN_INGEST_KEY: 'synthetic-only', OPENAI_MODEL: 'synthetic/model' } });
  expect(Exporter).toHaveBeenCalledTimes(1);
  expect(Exporter).toHaveBeenCalledWith({ origin: 'https://guardian.invalid', token: 'synthetic-only', testMode: false });
  expect(createResponse).toHaveBeenCalledTimes(1);
  expect(createResponse.mock.calls[0][0]).toMatchObject({ input: 'synthetic input', model: 'synthetic/model', stream: streaming });
  expect(createResponse.mock.calls[0][1]).toEqual({ signal: undefined });
  const selected = streaming ? stream : call;
  expect(selected.mock.calls[0][1]).toEqual({ agent_name: 'answer-generator', model: 'synthetic/model' });
  expect(selected.mock.calls[0][3]).toEqual({ api, signal: undefined });
  if (api === 'chat_completions') expect(createResponse.mock.calls[0][0].n).toBe(1);
  if (api === 'chat_completions' && streaming) expect(createResponse.mock.calls[0][0].stream_options).toEqual({ include_usage: true });
  if (streaming) expect(consume).toHaveBeenCalledWith(value);
};
const chooseApi = async (value) => act(async () => {
  const select = container.querySelector('#provider-api'); select.value = value;
  select.dispatchEvent(new Event('change', { bubbles: true }));
});

test('provider onboarding defaults to Python Responses with unknown cost and server-only configuration', async () => {
  await render();
  expect(button('Python').getAttribute('aria-selected')).toBe('true');
  expect(container.querySelector('#provider-api').value).toBe('responses');
  expect(container.querySelector('input[type="checkbox"]').checked).toBe(false);
  expect(recipeCode()).toContain('from guardian_openai import openai_call');
  expect(recipeCode()).toContain('client.responses.create(**observed_args)');
  expect(recipeCode()).toContain('os.environ["GUARDIAN_INGEST_KEY"]');
  expect(recipeCode()).toContain('os.environ["OPENAI_MODEL"]');
  expect(recipeCode()).toContain('test_mode=False');
  expect(recipeCode()).not.toMatch(/gpt-|sk-|cg_ingest_|cost_usd/);
  expect(container.textContent).toContain('guardian_capture.py');
  expect(container.textContent).toContain('guardian_exporter.py');
  expect(container.textContent).toContain('guardian_openai.py');
  expect(container.textContent).toContain('Token usage is reported; USD cost stays unknown.');
  expect(container.textContent).toContain('Configure duration/error rules and Slack notifications');
  expect([...container.querySelectorAll('a')].some((link) => link.textContent === 'captured activity' && link.getAttribute('href') === '/live')).toBe(true);
  const advanced = [...container.querySelectorAll('details')].find((node) => node.querySelector('summary')?.textContent.startsWith('Advanced: Sillage JSON'));
  expect(advanced.open).toBe(false); expect(advanced.textContent).toContain('REPLACE_WITH_CALL_START_UTC');
  expect(sendCaptureTest).not.toHaveBeenCalled(); expect(guardianApi.createIngestionKey).not.toHaveBeenCalled();
});

test.each([
  ['Python', 'responses', true, 'openai_stream', 'client.responses.create'],
  ['Python', 'chat_completions', false, 'openai_call', 'client.chat.completions.create'],
  ['Python', 'chat_completions', true, 'openai_stream', 'client.chat.completions.create'],
  ['Node', 'responses', false, 'openaiCall', 'client.responses.create'],
  ['Node', 'responses', true, 'openaiStream', 'client.responses.create'],
  ['Node', 'chat_completions', false, 'openaiCall', 'client.chat.completions.create'],
  ['Node', 'chat_completions', true, 'openaiStream', 'client.chat.completions.create'],
])('%s %s streaming=%s selects the matching helper and required terminal-usage options', async (language, api, streaming, helper, endpoint) => {
  await render('viewer');
  await act(async () => button(language).click()); await chooseApi(api);
  if (streaming) await act(async () => container.querySelector('input[type="checkbox"]').click());
  const code = recipeCode();
  expect(code).toContain(helper); expect(code).toContain(endpoint);
  expect(code).toContain(`api${language === 'Python' ? '=' : ':'}`);
  expect(code).toContain(api);
  if (api === 'chat_completions') expect(code).toContain(language === 'Python' ? '"n": 1' : 'n: 1');
  if (api === 'chat_completions' && streaming) {
    expect(code).toContain(language === 'Python' ? '"include_usage": True' : 'include_usage: true');
    expect(container.textContent).toContain('missing or interrupted final usage stays unknown');
  } else expect(code).not.toContain('include_usage');
  if (streaming) expect(code).toContain(language === 'Python' ? 'with closing(' : 'for await (const chunk');
  if (language === 'Node') {
    expect(code).toContain('{ ...requestOptions, signal }');
    expect(code).toContain('testMode: false');
    expect(container.textContent).toContain('guardian_openai.mjs');
    if (streaming) expect(code).toContain('await consumeChunk(chunk);');
    await executeNodeRecipe(code, api, streaming);
  }
  expect(sendCaptureTest).not.toHaveBeenCalled(); expect(guardianApi.createIngestionKey).not.toHaveBeenCalled();
});

test('Node streaming recipe awaits an async consumer and preserves its rejection', async () => {
  await render(); await act(async () => button('Node').click());
  await act(async () => container.querySelector('input[type="checkbox"]').click());
  const failure = new Error('synthetic consumer failure');
  await expect(executeNodeRecipe(recipeCode(), 'responses', true, async () => { throw failure; })).rejects.toBe(failure);
});

test('language tabs support keyboard selection without changing API or stream choices', async () => {
  await render(); await chooseApi('chat_completions');
  await act(async () => container.querySelector('input[type="checkbox"]').click());
  await act(async () => button('Python').dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true })));
  expect(button('Node').getAttribute('aria-selected')).toBe('true');
  expect(document.activeElement).toBe(button('Node'));
  expect(recipeCode()).toContain('openaiStream'); expect(recipeCode()).toContain('include_usage: true');
  await act(async () => button('Node').dispatchEvent(new KeyboardEvent('keydown', { key: 'Home', bubbles: true })));
  expect(button('Python').getAttribute('aria-selected')).toBe('true');
  expect(recipeCode()).toContain('openai_stream');
});

test('copying a recipe uses only displayed placeholders even while a key is revealed', async () => {
  const writeText = jest.fn().mockResolvedValue();
  Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText } });
  await render(); await create();
  await act(async () => button('Copy integration code').click());
  expect(writeText).toHaveBeenCalledWith(recipeCode()); expect(writeText.mock.calls[0][0]).not.toContain(token);
  expect(container.textContent).toContain('Integration code copied.');
  expect(container.querySelector('#one-time-ingestion-key').value).toBe(token);
  expect(JSON.stringify(localStorage)).not.toContain(token); expect(JSON.stringify(sessionStorage)).not.toContain(token);
});

test('recipe clipboard failure is safe and a late copy cannot confirm a different recipe', async () => {
  const pending = deferred();
  const writeText = jest.fn().mockRejectedValueOnce(new Error('private clipboard detail')).mockReturnValueOnce(pending.promise);
  Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText } });
  await render(); await act(async () => button('Copy integration code').click());
  expect(container.textContent).toContain('Select and copy the integration code below');
  expect(container.textContent).not.toContain('private clipboard detail');
  await act(async () => button('Copy integration code').click());
  await act(async () => button('Node').click());
  await act(async () => pending.resolve());
  expect(container.textContent).not.toContain('Integration code copied.');
  expect(container.textContent).not.toContain('Clipboard access failed.');
  expect(recipeCode()).toContain('openaiCall');
});
