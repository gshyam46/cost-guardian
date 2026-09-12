import { act } from 'react';
import { createRoot } from 'react-dom/client';
import App from './App';
import guardianApi, { announceLogout, clearApiKey, clearSessionAccess, setApiKey, setSessionAccess } from '@/services/guardianApi';
import { beginLogin, safeReturnPath } from '@/services/guardianIdentity';

jest.mock('@/services/guardianApi', () => ({
  __esModule: true,
  configureAuth: jest.fn(), setSessionAccess: jest.fn(), clearSessionAccess: jest.fn(), announceLogout: jest.fn(),
  getLoginUrl: () => '/api/guardian/auth/login', LOGOUT_NOTICE: 'guardian_session_logout',
  getApiKey: () => global.localStorage.getItem('guardian_api_key') || '',
  setApiKey: jest.fn((key) => global.localStorage.setItem('guardian_api_key', key)),
  clearApiKey: jest.fn(({ notify = true } = {}) => {
    global.localStorage.removeItem('guardian_api_key');
    if (notify) global.window.dispatchEvent(new CustomEvent('guardian-access-changed', { detail: { reason: 'disconnected' } }));
  }),
  default: {
    getAuthConfig: jest.fn(), logout: jest.fn(),
    getAccess: jest.fn(),
    getOverview: jest.fn(),
    getSummary: jest.fn(),
    getMonitoring: jest.fn(),
    getMetrics: jest.fn(),
    getTrends: jest.fn(),
    getIncident: jest.fn(),
    getNotifications: jest.fn(),
  },
}));
jest.mock('@/components/ui/sonner', () => ({ Toaster: () => null }));
jest.mock('sonner', () => ({ toast: { error: jest.fn(), success: jest.fn() } }));
jest.mock('@/services/guardianIdentity', () => ({ ...jest.requireActual('@/services/guardianIdentity'), beginLogin: jest.fn() }));

let container;
let root;
const accessBody = { authenticated: true, auth_mode: 'api_key', deployment_mode: 'single_project', permissions: ['read', 'resolve_incidents'] };
const sessionBody = (role = 'operator') => ({ authenticated: true, auth_mode: 'oidc', deployment_mode: 'single_project',
  permissions: role === 'viewer' ? ['read'] : ['read', 'resolve_incidents'],
  actor: { id: 'actor-1', name: 'Synthetic Member', role },
  project: { organization_id: 'synthetic-org', project_id: 'project-1', environment: 'test', name: 'Synthetic Project' },
  csrf_token: 'synthetic_csrf_token_12345678901234567890' });
const useOidc = (role = 'operator') => {
  guardianApi.getAuthConfig.mockResolvedValue({ data: { auth_mode: 'oidc', login_path: '/api/guardian/auth/login' } });
  guardianApi.getAccess.mockResolvedValue({ data: sessionBody(role) });
  guardianApi.logout.mockResolvedValue({ status: 204 });
  guardianApi.getNotifications.mockResolvedValue({ data: { schema_version: 1, revision: 0, project: sessionBody(role).project, can_manage: role === 'owner', updated_at: null,
    destination: { channel: 'slack', state: 'not_configured', verified: false, enabled: false }, worker: { status: 'unknown', last_seen_at: null }, deliveries: [], has_more: false } });
};
const deferred = () => {
  let resolve;
  let reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
};
const button = (text) => [...container.querySelectorAll('button')].find((node) => node.textContent === text);
const enterKey = async (key) => {
  const input = container.querySelector('input');
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(input, key);
    input.dispatchEvent(new Event('input', { bubbles: true }));
  });
  await act(async () => container.querySelector('form').dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })));
};

beforeEach(() => {
  jest.clearAllMocks();
  Object.values(guardianApi).forEach((method) => method.mockReset());
  setApiKey.mockImplementation((key) => localStorage.setItem('guardian_api_key', key));
  clearApiKey.mockImplementation(({ notify = true } = {}) => {
    localStorage.removeItem('guardian_api_key');
    if (notify) window.dispatchEvent(new CustomEvent('guardian-access-changed', { detail: { reason: 'disconnected' } }));
  });
  localStorage.clear();
  sessionStorage.clear();
  window.history.replaceState({}, '', '/');
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
  guardianApi.getAccess.mockResolvedValue({ data: accessBody });
  guardianApi.getNotifications.mockResolvedValue({ data: { schema_version: 1, revision: 0, project: null, can_manage: false, updated_at: null,
    destination: { channel: 'slack', state: 'not_configured', verified: false, enabled: false }, worker: { status: 'unknown', last_seen_at: null }, deliveries: [], has_more: false } });
  guardianApi.getAuthConfig.mockResolvedValue({ data: { auth_mode: 'api_key', login_path: null } });
  guardianApi.getOverview.mockResolvedValue({ data: {} });
  guardianApi.getSummary.mockResolvedValue({ data: {
    overview: {}, trends: [], coverage: { status: 'complete', invalid_timestamp_count: 0 }, timezone: 'UTC',
  } });
  guardianApi.getMonitoring.mockResolvedValue({ data: { healthy: false, status: 'not_polled' } });
  guardianApi.getMetrics.mockResolvedValue({ data: [] });
  guardianApi.getTrends.mockResolvedValue({ data: [] });
  guardianApi.getIncident.mockResolvedValue({ data: {
    id: 'incident-42', title: 'Unexpected retry spend', summary: 'Investigate retry traffic',
    severity: 'high', status: 'open', detector: 'cost_spike', evidence: { cost_usd: 2 },
    created_at: '2026-01-01T00:00:00Z', trace_ids: ['trace-42'], trace_urls: [],
  } });
});

afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
  jest.restoreAllMocks();
});

test('an incident deep link requires connection before fetching protected data', async () => {
  window.history.replaceState({}, '', '/incidents/incident-42');
  await act(async () => root.render(<App />));

  expect(container.textContent).toContain('Guardian API key');
  expect(guardianApi.getIncident).not.toHaveBeenCalled();
  expect(window.location.pathname).toBe('/incidents/incident-42');
});

test('a connected incident deep link fetches and renders the requested evidence', async () => {
  localStorage.setItem('guardian_api_key', 'test-key');
  window.history.replaceState({}, '', '/incidents/incident-42');
  await act(async () => root.render(<App />));

  expect(guardianApi.getAccess).toHaveBeenCalledWith('test-key', { signal: expect.any(AbortSignal) });
  expect(guardianApi.getIncident).toHaveBeenCalledWith('incident-42', { signal: expect.any(AbortSignal) });
  expect(container.querySelector('h2').textContent).toBe('Unexpected retry spend');
  expect(container.querySelector('pre').textContent).toContain('"cost_usd": 2');
  expect(container.querySelector('a[href="/incidents"]')).not.toBeNull();
});

test('a successful connection preserves and opens the original deep link', async () => {
  window.history.replaceState({}, '', '/incidents/incident-42');
  await act(async () => root.render(<App />));

  const input = container.querySelector('input');
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(input, 'test-key');
    input.dispatchEvent(new Event('input', { bubbles: true }));
  });
  await act(async () => {
    container.querySelector('form').dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
  });

  expect(guardianApi.getAccess).toHaveBeenCalledTimes(1);
  expect(guardianApi.getOverview).not.toHaveBeenCalled();
  expect(guardianApi.getIncident).toHaveBeenCalledWith('incident-42', { signal: expect.any(AbortSignal) });
  expect(window.location.pathname).toBe('/incidents/incident-42');
  expect(container.textContent).toContain('Unexpected retry spend');
});

test('stored credentials gate protected reads until an access-only check succeeds', async () => {
  localStorage.setItem('guardian_api_key', 'stored-key');
  const access = deferred();
  guardianApi.getAccess.mockReturnValue(access.promise);
  await act(async () => root.render(<App />));
  expect(container.textContent).toContain('Checking Guardian access');
  expect(guardianApi.getSummary).not.toHaveBeenCalled();
  expect(guardianApi.getMonitoring).not.toHaveBeenCalled();
  await act(async () => access.resolve({ data: accessBody }));
  expect(guardianApi.getSummary).toHaveBeenCalledTimes(1);
});

test('candidate keys stay in memory until verified and rejected candidates are not saved', async () => {
  const access = deferred();
  guardianApi.getAccess.mockReturnValue(access.promise);
  await act(async () => root.render(<App />));
  await enterKey('candidate-secret');
  expect(localStorage.getItem('guardian_api_key')).toBeNull();
  expect(setApiKey).not.toHaveBeenCalled();
  expect(container.textContent).toContain('Connecting...');
  await act(async () => access.reject({ response: { status: 401 } }));
  expect(container.querySelector('[role="alert"]').textContent).toContain('key was rejected');
  expect(localStorage.getItem('guardian_api_key')).toBeNull();
  expect(container.textContent).not.toContain('candidate-secret');
});

test.each([{}, { ...accessBody, authenticated: false }, { ...accessBody, permissions: ['read'] }, null])(
  'an invalid successful access body never persists a candidate or mounts protected content', async (data) => {
    guardianApi.getAccess.mockResolvedValue({ data });
    await act(async () => root.render(<App />));
    await enterKey('candidate-secret');
    expect(setApiKey).not.toHaveBeenCalled();
    expect(guardianApi.getSummary).not.toHaveBeenCalled();
    expect(container.textContent).toContain('Could not verify Guardian access');
  },
);

test('startup rejection removes the stored key and preserves the requested route', async () => {
  localStorage.setItem('guardian_api_key', 'rejected-key');
  window.history.replaceState({}, '', '/incidents/incident-42');
  guardianApi.getAccess.mockRejectedValue({ response: { status: 401 } });
  await act(async () => root.render(<App />));
  expect(localStorage.getItem('guardian_api_key')).toBeNull();
  expect(container.textContent).toContain('Guardian API key');
  expect(window.location.pathname).toBe('/incidents/incident-42');
  expect(guardianApi.getIncident).not.toHaveBeenCalled();
});

test.each([403, 503, 'timeout'])('startup %s preserves credentials and supports retry without protected reads', async (status) => {
  localStorage.setItem('guardian_api_key', 'stored-key');
  guardianApi.getAccess.mockRejectedValue(status === 'timeout' ? new Error('synthetic timeout') : { response: { status } });
  await act(async () => root.render(<App />));
  expect(localStorage.getItem('guardian_api_key')).toBe('stored-key');
  expect(guardianApi.getSummary).not.toHaveBeenCalled();
  expect(button('Use a different key')).toBeDefined();
  guardianApi.getAccess.mockResolvedValue({ data: accessBody });
  await act(async () => button('Retry access').click());
  expect(guardianApi.getSummary).toHaveBeenCalledTimes(1);
});

test('a valid key enters even when the incident summary is unavailable', async () => {
  guardianApi.getSummary.mockRejectedValue({ response: { status: 503 } });
  await act(async () => root.render(<App />));
  await enterKey('valid-key');
  expect(localStorage.getItem('guardian_api_key')).toBe('valid-key');
  expect(container.textContent).toContain('Could not load Guardian data');
  expect(container.textContent).not.toContain('no API key configured');
});

test('disconnect removes protected content without reloading or losing the route', async () => {
  localStorage.setItem('guardian_api_key', 'stored-key');
  window.history.replaceState({}, '', '/incidents/incident-42');
  await act(async () => root.render(<App />));
  expect(container.textContent).toContain('Unexpected retry spend');
  await act(async () => button('Disconnect').click());
  expect(clearApiKey).toHaveBeenCalled();
  expect(container.textContent).not.toContain('Unexpected retry spend');
  expect(container.textContent).toContain('Guardian API key');
  expect(window.location.pathname).toBe('/incidents/incident-42');
});

test('cross-tab changes unmount protected content and revalidate before returning', async () => {
  localStorage.setItem('guardian_api_key', 'first-key');
  await act(async () => root.render(<App />));
  const access = deferred();
  guardianApi.getAccess.mockReturnValue(access.promise);
  await act(async () => {
    localStorage.setItem('guardian_api_key', 'second-key');
    window.dispatchEvent(new StorageEvent('storage', { key: 'guardian_api_key', newValue: 'second-key' }));
  });
  expect(container.textContent).toContain('Checking Guardian access');
  expect(container.textContent).not.toContain('Open incidents');
  expect(guardianApi.getAccess).toHaveBeenLastCalledWith('second-key', { signal: expect.any(AbortSignal) });
  await act(async () => access.resolve({ data: accessBody }));
  expect(container.textContent).toContain('Open incidents');
  await act(async () => {
    localStorage.removeItem('guardian_api_key');
    window.dispatchEvent(new StorageEvent('storage', { key: 'guardian_api_key', newValue: null }));
  });
  expect(container.textContent).toContain('Guardian API key');
});

test('stored access response cannot mount content after an undelivered cross-tab replacement', async () => {
  localStorage.setItem('guardian_api_key', 'old-key');
  const access = deferred();
  guardianApi.getAccess.mockReturnValue(access.promise);
  await act(async () => root.render(<App />));
  localStorage.setItem('guardian_api_key', 'new-key');
  await act(async () => access.resolve({ data: accessBody }));
  expect(container.textContent).toContain('Browser access changed');
  expect(guardianApi.getSummary).not.toHaveBeenCalled();
  expect(localStorage.getItem('guardian_api_key')).toBe('new-key');
});

test('a rejected old startup request cannot remove a replacement key or mount old content', async () => {
  localStorage.setItem('guardian_api_key', 'old-key');
  const old = deferred();
  guardianApi.getAccess.mockReturnValueOnce(old.promise).mockResolvedValue({ data: accessBody });
  await act(async () => root.render(<App />));
  await act(async () => {
    localStorage.setItem('guardian_api_key', 'new-key');
    window.dispatchEvent(new StorageEvent('storage', { key: 'guardian_api_key', newValue: 'new-key' }));
  });
  await act(async () => old.reject({ response: { status: 401 } }));
  expect(localStorage.getItem('guardian_api_key')).toBe('new-key');
  expect(container.textContent).toContain('Open incidents');
});

test('storage failures fail closed with a safe recoverable message', async () => {
  jest.spyOn(Storage.prototype, 'getItem').mockImplementation(() => { throw new Error('private-storage-error'); });
  await act(async () => root.render(<App />));
  expect(container.textContent).toContain('Browser storage is unavailable');
  expect(container.textContent).not.toContain('private-storage-error');
  expect(guardianApi.getAccess).not.toHaveBeenCalled();
  expect(button('Retry access')).toBeDefined();
});

test('an unknown connected route recovers to the overview', async () => {
  localStorage.setItem('guardian_api_key', 'test-key');
  window.history.replaceState({}, '', '/missing-page');
  await act(async () => root.render(<App />));

  expect(window.location.pathname).toBe('/');
  expect(container.textContent).toContain('No telemetry yet');
  expect(guardianApi.getSummary).toHaveBeenCalledWith(14, { signal: expect.any(AbortSignal) });
});

test('public auth configuration must finish before any saved credential is read', async () => {
  localStorage.setItem('guardian_api_key', 'old-shared-key');
  const config = deferred();
  guardianApi.getAuthConfig.mockReturnValue(config.promise);
  const reads = jest.spyOn(Storage.prototype, 'getItem');
  await act(async () => root.render(<App />));
  expect(reads).not.toHaveBeenCalled();
  expect(guardianApi.getAccess).not.toHaveBeenCalled();
  await act(async () => config.resolve({ data: { auth_mode: 'api_key', login_path: null } }));
  expect(guardianApi.getAccess).toHaveBeenCalledWith('old-shared-key', { signal: expect.any(AbortSignal) });
});

test.each([{}, { auth_mode: 'unsupported', login_path: null }, { auth_mode: 'oidc', login_path: '//evil.example/login' }])(
  'invalid auth config fails closed without a key fallback', async (data) => {
    guardianApi.getAuthConfig.mockResolvedValue({ data });
    const reads = jest.spyOn(Storage.prototype, 'getItem');
    await act(async () => root.render(<App />));
    expect(container.textContent).toContain('Could not load Guardian sign-in configuration');
    expect(container.querySelector('input')).toBeNull();
    expect(reads).not.toHaveBeenCalled();
    expect(guardianApi.getAccess).not.toHaveBeenCalled();
  },
);

test('unavailable configuration supports retry before consulting legacy storage', async () => {
  guardianApi.getAuthConfig.mockRejectedValueOnce({ response: { status: 503 } });
  await act(async () => root.render(<App />));
  expect(container.textContent).toContain('sign-in configuration');
  await act(async () => button('Retry access').click());
  expect(container.textContent).toContain('Guardian API key');
});

test('OIDC access works with blocked key storage and shows the verified member and scope', async () => {
  useOidc();
  jest.spyOn(Storage.prototype, 'getItem').mockImplementation(() => { throw new Error('legacy storage must not be read'); });
  await act(async () => root.render(<App />));
  expect(container.textContent).toContain('Synthetic Member');
  expect(container.textContent).toContain('Synthetic Project');
  expect(container.textContent).toContain('synthetic-org');
  expect(guardianApi.getAccess).toHaveBeenCalledWith(undefined, { signal: expect.any(AbortSignal) });
  expect(setSessionAccess).toHaveBeenCalledWith(sessionBody());
  expect(container.textContent).not.toContain(sessionBody().csrf_token);
  expect(container.querySelector('input')).toBeNull();
  expect(setApiKey).not.toHaveBeenCalled();
});

test('OIDC viewer deep links keep evidence visible and hide mutation controls', async () => {
  useOidc('viewer');
  window.history.replaceState({}, '', '/incidents/incident-42');
  await act(async () => root.render(<App />));
  expect(container.textContent).toContain('Unexpected retry spend');
  expect(container.textContent).toContain('viewer');
  expect(button('Mark resolved')).toBeUndefined();
});

test.each([
  { ...sessionBody(), permissions: ['read'] },
  { ...sessionBody('viewer'), permissions: ['read', 'resolve_incidents'] },
  { ...sessionBody(), csrf_token: 'short' },
  { ...sessionBody(), actor: { id: 'actor-1', name: 'Member', role: 'administrator' } },
  { ...sessionBody(), project: { project_id: 'one' } },
  accessBody,
])('OIDC access validates scope, role permissions and session CSRF before mounting', async (data) => {
  useOidc();
  guardianApi.getAccess.mockResolvedValue({ data });
  await act(async () => root.render(<App />));
  expect(container.textContent).toContain('Could not verify Guardian access');
  expect(guardianApi.getSummary).not.toHaveBeenCalled();
  expect(setSessionAccess).not.toHaveBeenCalled();
});

test('an absent OIDC session presents only the fixed organization sign-in action', async () => {
  useOidc();
  guardianApi.getAccess.mockRejectedValue({ response: { status: 401 } });
  await act(async () => root.render(<App />));
  expect(container.querySelector('input')).toBeNull();
  expect(clearApiKey).not.toHaveBeenCalled();
  await act(async () => button('Sign in with your organization').click());
  expect(beginLogin).toHaveBeenCalledWith('/api/guardian/auth/login', { preserveReturn: false });
});

test('failed login callback does not redirect or mount a previously existing session', async () => {
  useOidc();
  window.history.replaceState({}, '', '/?guardian_login=failed');
  await act(async () => root.render(<App />));
  expect(container.textContent).toContain('Sign-in could not be completed');
  expect(guardianApi.getAccess).not.toHaveBeenCalled();
  expect(beginLogin).not.toHaveBeenCalled();
  expect(window.location.search).toBe('');
  await act(async () => window.dispatchEvent(new Event('focus')));
  expect(guardianApi.getAccess).not.toHaveBeenCalled();
  await act(async () => button('Sign in with your organization').click());
  expect(beginLogin).toHaveBeenCalledWith('/api/guardian/auth/login', { preserveReturn: true });
});

test.each(['/incidents/incident-42', '//evil.example', '/\\evil.example', '/runs/%2f%2fevil.example', 'https://evil.example', '/api/guardian/auth/login']) (
  'successful callback restores only a safe known local path (%s)', async (path) => {
    useOidc();
    sessionStorage.setItem('guardian_login_return', path);
    window.history.replaceState({}, '', '/?guardian_login=complete');
    const request = deferred();
    guardianApi.getAccess.mockReturnValue(request.promise);
    await act(async () => root.render(<App />));
    expect(window.location.pathname).toBe('/');
    expect(guardianApi.getIncident).not.toHaveBeenCalled();
    await act(async () => request.resolve({ data: sessionBody() }));
    expect(window.location.pathname).toBe(path === '/incidents/incident-42' ? path : '/');
    expect(sessionStorage.getItem('guardian_login_return')).toBeNull();
  },
);

test.each(['/runs/%252f%252fevil', '/incidents/one?next=https://evil', '/live#fragment', '/live\n', '/runs/../setup', '/missing']) (
  'unsafe or unknown login return paths are rejected (%s)', (path) => expect(safeReturnPath(path)).toBe('/'),
);

test('server logout immediately removes evidence; failure stays closed and retry confirms logout', async () => {
  useOidc();
  window.history.replaceState({}, '', '/incidents/incident-42');
  await act(async () => root.render(<App />));
  const logout = deferred();
  guardianApi.logout.mockReturnValueOnce(logout.promise);
  await act(async () => button('Sign out').click());
  expect(container.textContent).not.toContain('Unexpected retry spend');
  expect(container.textContent).toContain('Signing out of Guardian');
  expect(announceLogout).not.toHaveBeenCalled();
  await act(async () => logout.reject({ response: { status: 503 } }));
  expect(container.textContent).toContain('session may still be active');
  expect(announceLogout).not.toHaveBeenCalled();
  await act(async () => window.dispatchEvent(new Event('focus')));
  expect(container.textContent).not.toContain('Unexpected retry spend');
  await act(async () => button('Retry sign-out').click());
  expect(container.textContent).toContain('Signed out of Guardian');
  expect(announceLogout).toHaveBeenCalledTimes(1);
  expect(clearSessionAccess).toHaveBeenCalledTimes(1);
  expect(clearApiKey).not.toHaveBeenCalled();
});

test('an unexpected successful logout body is not confirmed server logout', async () => {
  useOidc();
  guardianApi.logout.mockResolvedValue({ status: 200 });
  await act(async () => root.render(<App />));
  await act(async () => button('Sign out').click());
  expect(container.textContent).toContain('Could not confirm server sign-out');
  expect(announceLogout).not.toHaveBeenCalled();
});

test('explicit sign-out retry revalidates a replaced session before using its fresh CSRF', async () => {
  useOidc();
  guardianApi.logout.mockRejectedValueOnce({ response: { status: 403 } }).mockResolvedValue({ status: 204 });
  await act(async () => root.render(<App />));
  await act(async () => button('Sign out').click());
  const replacement = { ...sessionBody(), csrf_token: 'fresh_session_csrf_12345678901234567890' };
  guardianApi.getAccess.mockResolvedValue({ data: replacement });
  await act(async () => button('Retry sign-out').click());
  expect(guardianApi.getAccess).toHaveBeenCalledTimes(2);
  expect(setSessionAccess).toHaveBeenLastCalledWith(replacement);
  expect(guardianApi.logout).toHaveBeenCalledTimes(2);
  expect(announceLogout).toHaveBeenCalledTimes(1);
  expect(container.textContent).toContain('Signed out of Guardian');
});

test.each([401, 503])('sign-out retry access %s does not blindly repeat a mutation', async (status) => {
  useOidc();
  guardianApi.logout.mockRejectedValueOnce({ response: { status: 503 } });
  await act(async () => root.render(<App />));
  await act(async () => button('Sign out').click());
  guardianApi.getAccess.mockRejectedValue({ response: { status } });
  await act(async () => button('Retry sign-out').click());
  expect(guardianApi.logout).toHaveBeenCalledTimes(1);
  expect(container.textContent).not.toContain('Open incidents');
  if (status === 401) {
    expect(container.textContent).toContain('session has ended');
    expect(announceLogout).toHaveBeenCalledTimes(1);
  } else {
    expect(container.textContent).toContain('session may still be active');
    expect(announceLogout).not.toHaveBeenCalled();
  }
});

test('cross-tab changes during sign-out stay closed and a stale logout success cannot finish a newer retry', async () => {
  useOidc();
  await act(async () => root.render(<App />));
  const oldLogout = deferred();
  const retryLogout = deferred();
  guardianApi.logout.mockReturnValueOnce(oldLogout.promise).mockReturnValueOnce(retryLogout.promise);
  await act(async () => button('Sign out').click());
  await act(async () => window.dispatchEvent(new StorageEvent('storage', { key: 'guardian_session_logout', newValue: 'nonsecret' })));
  await act(async () => window.dispatchEvent(new Event('focus')));
  expect(guardianApi.getAccess).toHaveBeenCalledTimes(1);
  expect(guardianApi.logout).toHaveBeenCalledTimes(1);
  expect(container.textContent).toContain('Browser session state changed');
  await act(async () => button('Retry sign-out').click());
  await act(async () => oldLogout.resolve({ status: 204 }));
  expect(container.textContent).toContain('Signing out of Guardian');
  expect(announceLogout).not.toHaveBeenCalled();
  await act(async () => retryLogout.resolve({ status: 204 }));
  expect(container.textContent).toContain('Signed out of Guardian');
  expect(announceLogout).toHaveBeenCalledTimes(1);
});

test('cross-tab logout revalidates server authority and stale earlier access cannot reopen evidence', async () => {
  useOidc();
  const old = deferred();
  guardianApi.getAccess.mockReturnValueOnce(old.promise).mockRejectedValue({ response: { status: 401 } });
  await act(async () => root.render(<App />));
  await act(async () => window.dispatchEvent(new StorageEvent('storage', { key: 'guardian_session_logout', newValue: 'nonsecret-notice' })));
  await act(async () => old.resolve({ data: sessionBody() }));
  expect(container.textContent).toContain('Sign in with your organization');
  expect(guardianApi.getSummary).not.toHaveBeenCalled();
});

test('OIDC ignores legacy cross-tab key changes and current-session401 removes protected views', async () => {
  useOidc();
  await act(async () => root.render(<App />));
  await act(async () => window.dispatchEvent(new StorageEvent('storage', { key: 'guardian_api_key', newValue: 'ignored-key' })));
  expect(guardianApi.getAccess).toHaveBeenCalledTimes(1);
  await act(async () => window.dispatchEvent(new CustomEvent('guardian-access-changed', { detail: { reason: 'session_rejected' } })));
  expect(container.textContent).toContain('session has ended');
  expect(container.textContent).not.toContain('Open incidents');
});
