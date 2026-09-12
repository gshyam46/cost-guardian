import { act } from 'react';
import { createRoot } from 'react-dom/client';
import App from './App';
import guardianApi, { announceLogout, clearApiKey, clearSessionAccess, configureAuth, getApiKey, sendCaptureTest, setApiKey, setSessionAccess } from '@/services/guardianApi';
import { validSessionOrigin } from '@/services/guardianIdentity';

// Exercise Axios's actual interceptor chain without dialing a network service.
let mockAdapter;
jest.mock('axios', () => {
  const actual = jest.requireActual('axios/dist/node/axios.cjs');
  return { ...actual, create: (config) => actual.create({ ...config, adapter: (request) => mockAdapter(request) }) };
});
jest.mock('@/components/ui/sonner', () => ({ Toaster: () => null }));
jest.mock('sonner', () => ({ toast: { error: jest.fn(), success: jest.fn() } }));

const accessBody = { authenticated: true, auth_mode: 'api_key', deployment_mode: 'single_project', permissions: ['read', 'resolve_incidents'] };
const oidcConfig = { auth_mode: 'oidc', login_path: '/api/guardian/auth/login' };
const sessionBody = { authenticated: true, auth_mode: 'oidc', deployment_mode: 'single_project',
  permissions: ['read', 'resolve_incidents'], actor: { id: 'test-actor', name: 'Test Member', role: 'operator' },
  project: { organization_id: 'test-org', project_id: 'test-project', environment: 'test', name: 'Test Project' },
  csrf_token: 'synthetic_session_csrf_12345678901234567890' };
const incident = { id: 'private-incident', title: 'Protected fixture evidence', summary: 'Synthetic evidence',
  severity: 'high', status: 'open', detector: 'cost_anomaly', evidence: {},
  created_at: '2026-01-01T00:00:00Z', trace_ids: [], trace_urls: [] };
const reply = (config, data) => ({ status: 200, statusText: 'OK', config, headers: {}, data });
const notifications = (config) => ({ schema_version: 1, revision: 0, project: config.guardianMode === 'oidc' ? sessionBody.project : null,
  can_manage: false, updated_at: null, destination: { channel: 'slack', state: 'not_configured', verified: false, enabled: false },
  worker: { status: 'unknown', last_seen_at: null }, deliveries: [], has_more: false });
let root;
let container;
let changes;
let listener;

beforeEach(() => {
  Object.defineProperty(global, 'crypto', { configurable: true, value: require('node:crypto').webcrypto });
  localStorage.clear();
  setApiKey('current-key');
  configureAuth({ auth_mode: 'api_key', login_path: null });
  changes = [];
  listener = (event) => changes.push(event.detail);
  window.addEventListener('guardian-access-changed', listener);
  mockAdapter = jest.fn(async (config) => reply(config, config.url === '/guardian/auth/config'
    ? { auth_mode: 'api_key', login_path: null } : config.url === '/guardian/access' ? accessBody
      : config.url === '/guardian/notifications' ? notifications(config) : incident));
  window.history.replaceState({}, '', '/incidents/private-incident');
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
  window.removeEventListener('guardian-access-changed', listener);
  jest.restoreAllMocks();
  delete global.fetch;
});

test('candidate requests use their own key, remain bounded and do not persist it', async () => {
  const controller = new AbortController();
  await guardianApi.getAccess('candidate-key', { signal: controller.signal });
  const request = mockAdapter.mock.calls[0][0];
  expect(request.url).toBe('/guardian/access');
  expect(request.headers['X-Guardian-Key']).toBe('candidate-key');
  expect(request.timeout).toBe(10000);
  expect(request.signal).toBe(controller.signal);
  expect(getApiKey()).toBe('current-key');
});

test('candidate rejection does not revoke the previously stored credential', async () => {
  mockAdapter.mockImplementation(async (config) => { throw { config, response: { status: 401 } }; });
  await expect(guardianApi.getAccess('bad-candidate')).rejects.toMatchObject({ response: { status: 401 } });
  expect(getApiKey()).toBe('current-key');
  expect(changes).toEqual([]);
});

test('a current authenticated request rejection clears the key and unmounts protected evidence', async () => {
  await act(async () => root.render(<App />));
  expect(container.textContent).toContain(incident.title);
  mockAdapter.mockImplementation(async (config) => { throw { config, response: { status: 401 } }; });
  await act(async () => { await guardianApi.getMonitoring().catch(() => {}); });
  expect(getApiKey()).toBe('');
  expect(container.textContent).not.toContain(incident.title);
  expect(container.textContent).toContain('Access was rejected. Connect again');
  expect(changes).toEqual([{ reason: 'rejected' }]);
});

test.each([403, 503])('data HTTP %i does not log out or discard protected evidence', async (status) => {
  await act(async () => root.render(<App />));
  mockAdapter.mockImplementation(async (config) => { throw { config, response: { status } }; });
  await act(async () => { await guardianApi.getMonitoring().catch(() => {}); });
  expect(getApiKey()).toBe('current-key');
  expect(container.textContent).toContain(incident.title);
  expect(changes).toEqual([]);
});

test.each(['replacement-key', 'current-key'])('late data rejection cannot revoke a verified replacement (%s)', async (replacement) => {
  let fail;
  let began;
  const started = new Promise((resolve) => { began = resolve; });
  mockAdapter.mockImplementationOnce((config) => new Promise((_resolve, reject) => {
    fail = () => reject({ config, response: { status: 401 } });
    began();
  }));
  const pending = guardianApi.getMonitoring().catch(() => {});
  await started;
  clearApiKey();
  await guardianApi.getAccess(replacement);
  setApiKey(replacement);
  fail();
  await pending;
  expect(getApiKey()).toBe(replacement);
  expect(changes.some((change) => change.reason === 'rejected')).toBe(false);
});

test('a cross-tab replacement protects the new key from an old request rejection', async () => {
  let fail;
  let began;
  const started = new Promise((resolve) => { began = resolve; });
  mockAdapter.mockImplementationOnce((config) => new Promise((_resolve, reject) => {
    fail = () => reject({ config, response: { status: 401 } });
    began();
  }));
  const pending = guardianApi.getMonitoring().catch(() => {});
  await started;
  localStorage.setItem('guardian_api_key', 'cross-tab-key');
  window.dispatchEvent(new StorageEvent('storage', { key: 'guardian_api_key', newValue: 'cross-tab-key' }));
  fail();
  await pending;
  expect(getApiKey()).toBe('cross-tab-key');
  expect(changes).toEqual([]);
});

test('storage loss during a data request unmounts protected content and emits only safe recovery state', async () => {
  await act(async () => root.render(<App />));
  const before = mockAdapter.mock.calls.length;
  jest.spyOn(Storage.prototype, 'getItem').mockImplementation(() => { throw new Error('private-browser-diagnostic'); });
  await act(async () => { await guardianApi.getMonitoring().catch(() => {}); });
  expect(mockAdapter).toHaveBeenCalledTimes(before);
  expect(container.textContent).not.toContain(incident.title);
  expect(container.textContent).toContain('Browser storage is unavailable');
  expect(JSON.stringify(changes)).not.toMatch(/current-key|private-browser/);
  expect(changes).toEqual([{ reason: 'storage_error' }]);
});

test('failed browser-storage removal still unmounts protected content on disconnect', async () => {
  await act(async () => root.render(<App />));
  jest.spyOn(Storage.prototype, 'removeItem').mockImplementation(() => { throw new Error('private-storage-detail'); });
  const disconnect = [...container.querySelectorAll('button')].find((button) => button.textContent === 'Disconnect');
  await act(async () => disconnect.click());
  expect(container.textContent).not.toContain(incident.title);
  expect(container.textContent).toContain('Browser storage is unavailable');
  expect(container.textContent).not.toContain('private-storage-detail');
});

test('incident requests preserve encoded IDs and cancellation while resolution uses the current key', async () => {
  const controller = new AbortController();
  await guardianApi.getIncident('id/with space', { signal: controller.signal });
  await guardianApi.resolveIncident('id/with space', { signal: controller.signal });
  const requests = mockAdapter.mock.calls.map(([config]) => config);
  expect(requests[0].url).toBe('/guardian/incidents/id%2Fwith%20space');
  expect(requests[1].url).toBe('/guardian/incidents/id%2Fwith%20space/resolve');
  expect(requests[1].method).toBe('post');
  expect(requests.every((request) => request.timeout === 25000 && request.signal === controller.signal
    && request.headers['X-Guardian-Key'] === 'current-key')).toBe(true);
});

test.each(['api_key', 'oidc'])('public config is credential-free even after %s has been configured', async (authMode) => {
  configureAuth(authMode === 'oidc' ? oidcConfig : { auth_mode: 'api_key', login_path: null });
  jest.spyOn(Storage.prototype, 'getItem').mockImplementation(() => { throw new Error('storage must not be accessed'); });
  await guardianApi.getAuthConfig();
  const request = mockAdapter.mock.calls[0][0];
  expect(request.url).toBe('/guardian/auth/config');
  expect(request.headers['X-Guardian-Key']).toBeUndefined();
  expect(request.headers['X-Guardian-CSRF']).toBeUndefined();
  expect(request.withCredentials).not.toBe(true);
  expect(request.timeout).toBe(10000);
});

test('OIDC reads and mutations never consult or send a legacy key; mutations use the in-memory session CSRF', async () => {
  configureAuth(oidcConfig);
  jest.spyOn(Storage.prototype, 'getItem').mockImplementation(() => { throw new Error('legacy storage must not be read'); });
  await guardianApi.getAccess('must-not-send-this-key');
  setSessionAccess(sessionBody);
  await guardianApi.getIncident('private-incident');
  await guardianApi.resolveIncident('private-incident');
  await guardianApi.logout();
  const requests = mockAdapter.mock.calls.map(([request]) => request);
  expect(requests.every((request) => request.withCredentials === true && !request.headers['X-Guardian-Key'])).toBe(true);
  expect(requests.slice(0, 2).every((request) => !request.headers['X-Guardian-CSRF'])).toBe(true);
  expect(requests.slice(2).every((request) => request.headers['X-Guardian-CSRF'] === sessionBody.csrf_token)).toBe(true);
  expect(requests[3].url).toBe('/guardian/auth/logout');
  expect(requests[3].method).toBe('post');
});

test('OIDC mutations without a verified current session are stopped before transport', async () => {
  configureAuth(oidcConfig);
  await expect(guardianApi.resolveIncident('private-incident')).rejects.toThrow('session verification is required');
  expect(mockAdapter).not.toHaveBeenCalled();
  setSessionAccess(sessionBody);
  clearSessionAccess();
  await expect(guardianApi.logout()).rejects.toThrow('session verification is required');
  expect(mockAdapter).not.toHaveBeenCalled();
});

test('a current OIDC data401 clears protected state without deleting the legacy key', async () => {
  mockAdapter.mockImplementation(async (config) => reply(config, config.url === '/guardian/auth/config'
    ? oidcConfig : config.url === '/guardian/access' ? sessionBody : incident));
  await act(async () => root.render(<App />));
  expect(container.textContent).toContain(incident.title);
  mockAdapter.mockImplementation(async (config) => { throw { config, response: { status: 401 } }; });
  await act(async () => { await guardianApi.getMonitoring().catch(() => {}); });
  expect(container.textContent).not.toContain(incident.title);
  expect(container.textContent).toContain('session has ended');
  expect(localStorage.getItem('guardian_api_key')).toBe('current-key');
  expect(changes).toEqual([{ reason: 'session_rejected' }]);
  await expect(guardianApi.resolveIncident('private-incident')).rejects.toThrow('session verification is required');
});

test.each([sessionBody.csrf_token, 'replacement_session_csrf_12345678901234567890']) (
  'late OIDC data401 cannot revoke a reverified session (%s)', async (csrfToken) => {
    configureAuth(oidcConfig);
    setSessionAccess(sessionBody);
    let fail;
    let began;
    const started = new Promise((resolve) => { began = resolve; });
    mockAdapter.mockImplementationOnce((config) => new Promise((_resolve, reject) => {
      fail = () => reject({ config, response: { status: 401 } });
      began();
    }));
    const old = guardianApi.getMonitoring().catch(() => {});
    await started;
    clearSessionAccess();
    setSessionAccess({ ...sessionBody, csrf_token: csrfToken });
    fail();
    await old;
    expect(changes).toEqual([]);
    await guardianApi.resolveIncident('private-incident');
    expect(mockAdapter.mock.calls[1][0].headers['X-Guardian-CSRF']).toBe(csrfToken);
  },
);

test.each([403, 503])('OIDC data %i preserves the session and does not emit logout', async (status) => {
  configureAuth(oidcConfig);
  setSessionAccess(sessionBody);
  mockAdapter.mockImplementationOnce(async (config) => { throw { config, response: { status } }; });
  await expect(guardianApi.resolveIncident('private-incident')).rejects.toMatchObject({ response: { status } });
  expect(changes).toEqual([]);
  await guardianApi.resolveIncident('private-incident');
  expect(mockAdapter.mock.calls[1][0].headers['X-Guardian-CSRF']).toBe(sessionBody.csrf_token);
});

test('logout notification contains no session or CSRF material and preserves legacy storage', () => {
  configureAuth(oidcConfig);
  setSessionAccess(sessionBody);
  const writes = jest.spyOn(Storage.prototype, 'setItem');
  announceLogout();
  expect(writes).toHaveBeenCalledTimes(1);
  expect(writes.mock.calls[0][0]).toBe('guardian_session_logout');
  expect(writes.mock.calls[0][1]).not.toMatch(/current-key|csrf|test-actor/);
  expect(localStorage.getItem('guardian_api_key')).toBe('current-key');
});

test.each([
  ['https://guardian.example', 'https://guardian.example', true],
  ['/', 'https://guardian.example', true],
  ['https://api.example', 'https://guardian.example', false],
  ['http://guardian.example', 'http://guardian.example', false],
  ['http://localhost:8001', 'http://localhost:3001', true],
  ['http://127.0.0.1:8001', 'http://localhost:3001', true],
  ['http://localhost:8001', 'https://guardian.example', false],
  ['https://user:secret@guardian.example', 'https://guardian.example', false],
  ['https://guardian.example/another-api', 'https://guardian.example', false],
  ['https://guardian.example?redirect=elsewhere', 'https://guardian.example', false],
  ['javascript:alert(1)', 'https://guardian.example', false],
])('session deployment origin boundary %s from %s is %s', (api, ui, valid) => {
  expect(validSessionOrigin(api, ui)).toBe(valid);
});

test('an explicit same-origin build path produces /api requests and a fixed local login URL', async () => {
  const previous = process.env.REACT_APP_GUARDIAN_URL;
  process.env.REACT_APP_GUARDIAN_URL = '/';
  try {
    let isolated;
    jest.isolateModules(() => { isolated = require('@/services/guardianApi'); });
    isolated.configureAuth(oidcConfig);
    await isolated.default.getAccess();
    expect(mockAdapter.mock.calls[0][0].baseURL).toBe('/api');
    expect(isolated.getLoginUrl()).toBe(window.location.origin + '/api/guardian/auth/login');
  } finally {
    if (previous === undefined) delete process.env.REACT_APP_GUARDIAN_URL;
    else process.env.REACT_APP_GUARDIAN_URL = previous;
  }
});

test('key management uses the dashboard session and CSRF, never an ingestion credential', async () => {
  configureAuth(oidcConfig); setSessionAccess(sessionBody);
  const signal = new AbortController().signal;
  await guardianApi.getCapture({ signal }); await guardianApi.listIngestionKeys({ signal });
  await guardianApi.createIngestionKey({ request_id: 'synthetic-id', label: 'service', expires_in_days: 30 }, { signal });
  await guardianApi.revokeIngestionKey('id/with space', { signal });
  const requests = mockAdapter.mock.calls.map(([request]) => request);
  expect(requests.every((request) => request.withCredentials && request.signal === signal
    && !request.headers['X-Guardian-Ingest-Key'] && !request.headers['X-Guardian-Key'])).toBe(true);
  expect(requests.slice(2).every((request) => request.headers['X-Guardian-CSRF'] === sessionBody.csrf_token && request.timeout === 40000)).toBe(true);
  expect(requests[3].url).toBe('/guardian/ingestion-keys/id%2Fwith%20space/revoke');
});

test('test intake bypasses Axios and sends only a machine key with cookies omitted and redirects refused', async () => {
  configureAuth(oidcConfig); setSessionAccess(sessionBody);
  const token = `cg_ingest_${'a'.repeat(32)}_${'S'.repeat(43)}`;
  global.fetch = jest.fn(async (_url, options) => ({ status: 202, json: async () => ({ batch_id: JSON.parse(options.body).batch_id,
    received: 1, duplicate: 0, conflict_candidates: 0, test_mode: true, replayed: false, processing: 'test_only' }) }));
  await sendCaptureTest(token);
  expect(mockAdapter).not.toHaveBeenCalled();
  const [url, options] = global.fetch.mock.calls[0];
  expect(url).toMatch(/\/api\/guardian\/ingest\/events$/);
  expect(options.credentials).toBe('omit'); expect(options.redirect).toBe('error');
  expect(options.headers).toEqual({ 'Content-Type': 'application/json', 'X-Guardian-Ingest-Key': token });
  const body = JSON.parse(options.body);
  expect(body.test_mode).toBe(true); expect(body.schema_version).toBe(1); expect(body.events).toHaveLength(1);
  expect(body.batch_id).toMatch(/^[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$/);
  expect(body.events[0]).toMatchObject({ cost_usd: null, input_tokens: null, output_tokens: null, total_tokens: null, status: 'unknown' });
  expect(body.events[0].started_at).toMatch(/Z$/); expect(body.events[0].ended_at).toBe(body.events[0].started_at);
  expect(options.body).not.toContain(token); expect(options.body).not.toContain('current-key');
});

test('intake401 does not clear dashboard access or expose an upstream error body', async () => {
  configureAuth(oidcConfig); setSessionAccess(sessionBody);
  global.fetch = jest.fn(async () => ({ status: 401, json: jest.fn(() => { throw new Error('private-error-content'); }) }));
  await expect(sendCaptureTest(`cg_ingest_${'a'.repeat(32)}_${'S'.repeat(43)}`)).rejects.toMatchObject({ message: 'capture_test_failed', status: 401 });
  expect(changes).toEqual([]); await guardianApi.resolveIncident('private-incident');
  expect(mockAdapter.mock.calls[0][0].headers['X-Guardian-CSRF']).toBe(sessionBody.csrf_token);
});

test('test intake cannot claim success for an ordinary production receipt', async () => {
  configureAuth(oidcConfig);
  global.fetch = jest.fn(async (_url, options) => ({ status: 202, json: async () => ({ batch_id: JSON.parse(options.body).batch_id,
    received: 1, duplicate: 0, conflict_candidates: 0, test_mode: false, replayed: false, processing: 'queued' }) }));
  await expect(sendCaptureTest(`cg_ingest_${'a'.repeat(32)}_${'S'.repeat(43)}`)).rejects.toThrow('capture_test_failed');
});

test.each([{ received: 0 }, { duplicate: 100 }, { conflict_candidates: 100 }, { replayed: undefined }, { extra: 'unsupported' }])(
  'an inconsistent one-event test receipt %p cannot claim a confirmed handshake', async (overrides) => {
    configureAuth(oidcConfig);
    global.fetch = jest.fn(async (_url, options) => ({ status: 202, json: async () => ({ batch_id: JSON.parse(options.body).batch_id,
      received: 1, duplicate: 0, conflict_candidates: 0, test_mode: true, replayed: false, processing: 'test_only', ...overrides }) }));
    await expect(sendCaptureTest(`cg_ingest_${'a'.repeat(32)}_${'S'.repeat(43)}`)).rejects.toThrow('capture_test_failed');
  },
);

test('unmount cancellation reaches the independent intake fetch', async () => {
  configureAuth(oidcConfig);
  const controller = new AbortController();
  global.fetch = jest.fn((_url, options) => new Promise((_resolve, reject) => options.signal.addEventListener('abort', () => reject(new Error('aborted')))));
  const pending = sendCaptureTest(`cg_ingest_${'a'.repeat(32)}_${'S'.repeat(43)}`, { signal: controller.signal });
  controller.abort(); await expect(pending).rejects.toThrow('capture_test_failed');
  expect(global.fetch.mock.calls[0][1].signal.aborted).toBe(true);
});

test('monitoring policy reads and writes use the existing session and bounded cancellable requests', async () => {
  configureAuth(oidcConfig); setSessionAccess({ ...sessionBody, actor: { ...sessionBody.actor, role: 'owner' } });
  const controller = new AbortController();
  const body = { expected_revision: 0, rules: { max_call_cost_usd: '0', max_call_latency_ms: null, alert_on_errors: true } };
  await guardianApi.getMonitoringPolicy({ signal: controller.signal });
  await guardianApi.updateMonitoringPolicy(body, { signal: controller.signal });
  const [read, write] = mockAdapter.mock.calls.map(([request]) => request);
  expect(read.url).toBe('/guardian/monitoring-policy'); expect(write.url).toBe(read.url);
  expect(read.method).toBe('get'); expect(write.method).toBe('put');
  expect(read.timeout).toBe(10000); expect(write.timeout).toBe(40000);
  expect(read.signal).toBe(controller.signal); expect(write.signal).toBe(controller.signal);
  expect(read.withCredentials).toBe(true); expect(write.withCredentials).toBe(true);
  expect(read.headers['X-Guardian-Key']).toBeUndefined(); expect(write.headers['X-Guardian-Key']).toBeUndefined();
  expect(write.headers['X-Guardian-CSRF']).toBe(sessionBody.csrf_token);
  expect(JSON.parse(write.data)).toEqual(body);
});

test('a policy read in local shared-key mode retains its existing header boundary', async () => {
  await guardianApi.getMonitoringPolicy();
  const request = mockAdapter.mock.calls[0][0];
  expect(request.headers['X-Guardian-Key']).toBe('current-key');
  expect(request.headers['X-Guardian-CSRF']).toBeUndefined();
  expect(request.withCredentials).not.toBe(true);
});

test('notification history and actions use scoped session authority, signals and bounded requests', async () => {
  configureAuth(oidcConfig); setSessionAccess({ ...sessionBody, actor: { ...sessionBody.actor, role: 'owner' } });
  const controller = new AbortController();
  const body = { expected_revision: 1, request_id: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', action: 'retry', delivery_id: 'b'.repeat(64) };
  await guardianApi.getNotifications('incident-1', { signal: controller.signal });
  await guardianApi.notificationAction(body, { signal: controller.signal });
  const [read, write] = mockAdapter.mock.calls.map(([request]) => request);
  expect(read.url).toBe('/guardian/notifications'); expect(read.params).toEqual({ incident_id: 'incident-1' });
  expect(write.url).toBe('/guardian/notifications/actions'); expect(write.method).toBe('post');
  expect(read.timeout).toBe(10000); expect(write.timeout).toBe(40000);
  expect(read.signal).toBe(controller.signal); expect(write.signal).toBe(controller.signal);
  expect(read.withCredentials).toBe(true); expect(write.withCredentials).toBe(true);
  expect(write.headers['X-Guardian-CSRF']).toBe(sessionBody.csrf_token);
  expect(write.headers['X-Guardian-Key']).toBeUndefined(); expect(JSON.parse(write.data)).toEqual(body);
});
