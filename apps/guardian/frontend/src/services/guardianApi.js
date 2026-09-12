import axios from 'axios';
import { validAuthConfig, validAccess, validSessionOrigin } from './guardianIdentity';

const GUARDIAN_URL = (process.env.REACT_APP_GUARDIAN_URL || (process.env.NODE_ENV === 'production' ? window.location.origin : 'http://localhost:8001')).replace(/\/+$/, '');
const KEY_STORAGE = 'guardian_api_key';
export const LOGOUT_NOTICE = 'guardian_session_logout';
let credentialRevision = 0;
let authMode = null;
let sessionRevision = 0;
let csrfToken = '';

export const configureAuth = (body) => {
  if (!validAuthConfig(body)) throw new Error('Invalid authentication configuration.');
  if (body.auth_mode === 'oidc' && !validSessionOrigin(GUARDIAN_URL, window.location.origin)) {
    throw new Error('Guardian session access requires a same-origin deployment.');
  }
  authMode = body.auth_mode;
  sessionRevision += 1;
  csrfToken = '';
};
export const setSessionAccess = (body) => {
  if (authMode !== 'oidc' || !validAccess(body, 'oidc')) throw new Error('Invalid session access.');
  sessionRevision += 1;
  csrfToken = body.csrf_token;
};
export const clearSessionAccess = () => { sessionRevision += 1; csrfToken = ''; };
export const getLoginUrl = () => {
  if (authMode !== 'oidc') throw new Error('Session login is unavailable.');
  return new URL('/api/guardian/auth/login', new URL(GUARDIAN_URL, window.location.origin)).href;
};
export const announceLogout = () => {
  // This timestamp is a notification only; the server remains session authority.
  try { localStorage.setItem(LOGOUT_NOTICE, `${Date.now()}-${Math.random()}`); } catch { /* Broadcast remains available when storage is blocked. */ }
  try {
    const channel = new BroadcastChannel('guardian-session');
    channel.postMessage({ type: 'logout' });
    channel.close();
  } catch { /* A later focus/reload also revalidates the session. */ }
};

const changed = (reason) => window.dispatchEvent(new CustomEvent('guardian-access-changed', { detail: { reason } }));
const storageFailure = () => Object.assign(new Error('Browser storage is unavailable.'), { code: 'browser_storage_unavailable' });
export const getApiKey = () => {
  try { return localStorage.getItem(KEY_STORAGE) || ''; }
  catch { throw storageFailure(); }
};
export const setApiKey = (key, { notify = true } = {}) => {
  try { localStorage.setItem(KEY_STORAGE, key); }
  catch { throw storageFailure(); }
  credentialRevision += 1;
  if (notify) changed('changed');
};
export const clearApiKey = ({ notify = true, reason = 'disconnected' } = {}) => {
  credentialRevision += 1;
  try { localStorage.removeItem(KEY_STORAGE); }
  catch {
    changed('storage_error');
    throw storageFailure();
  }
  if (notify) changed(reason);
};
window.addEventListener('storage', (event) => {
  if (event.key === KEY_STORAGE || event.key === null) credentialRevision += 1;
});

const api = axios.create({
  baseURL: `${GUARDIAN_URL}/api`,
  headers: { 'Content-Type': 'application/json' },
});

api.interceptors.request.use((config) => {
  if (config.guardianPublic) return config;
  if (!authMode) throw new Error('Guardian authentication configuration is unavailable.');
  config.guardianMode = authMode;
  if (authMode === 'oidc') {
    delete config.headers['X-Guardian-Key'];
    config.withCredentials = true;
    config.guardianSessionRevision = sessionRevision;
    if (!['get', 'head', 'options'].includes(config.method)) {
      if (!csrfToken) throw new Error('Guardian session verification is required.');
      config.headers['X-Guardian-CSRF'] = csrfToken;
    }
    return config;
  }
  // Candidate checks carry their own in-memory key; never substitute a stored one.
  try {
    const key = config.guardianAccessCheck ? config.headers['X-Guardian-Key'] : getApiKey();
    if (key) config.headers['X-Guardian-Key'] = key;
    config.guardianCredentialRevision = credentialRevision;
    return config;
  } catch (error) {
    if (error?.code === 'browser_storage_unavailable') changed('storage_error');
    throw error;
  }
});
api.interceptors.response.use((response) => response, (error) => {
  const config = error.config;
  if (error.response?.status === 401 && config?.guardianMode === 'oidc' && !config.guardianAccessCheck
      && config.guardianSessionRevision === sessionRevision) {
    clearSessionAccess();
    changed('session_rejected');
  }
  if (error.response?.status === 401 && config && !config.guardianAccessCheck
      && config.guardianMode === 'api_key' && config.guardianCredentialRevision === credentialRevision) {
    try {
      const rejected = config.headers?.['X-Guardian-Key'];
      if (rejected && rejected === getApiKey()) clearApiKey({ reason: 'rejected' });
    } catch {
      // Storage failures also remove protected content through the access gate.
      changed('storage_error');
    }
  }
  return Promise.reject(error);
});

export const guardianApi = {
  getNotifications: (incidentId = null, { signal } = {}) => api.get('/guardian/notifications', { params: incidentId === null ? {} : { incident_id: incidentId }, timeout: 10000, signal }),
  notificationAction: (body, { signal } = {}) => api.post('/guardian/notifications/actions', body, { timeout: 40000, signal }),
  getMonitoringPolicy: ({ signal } = {}) => api.get('/guardian/monitoring-policy', { timeout: 10000, signal }),
  updateMonitoringPolicy: (body, { signal } = {}) => api.put('/guardian/monitoring-policy', body, { timeout: 40000, signal }),
  getCapture: ({ signal } = {}) => api.get('/guardian/capture', { timeout: 10000, signal }),
  listIngestionKeys: ({ signal } = {}) => api.get('/guardian/ingestion-keys', { timeout: 10000, signal }),
  createIngestionKey: (body, { signal } = {}) => api.post('/guardian/ingestion-keys', body, { timeout: 40000, signal }),
  revokeIngestionKey: (id, { signal } = {}) => api.post(`/guardian/ingestion-keys/${encodeURIComponent(id)}/revoke`, undefined, { timeout: 40000, signal }),
  getAuthConfig: ({ signal } = {}) => api.get('/guardian/auth/config', { timeout: 10000, signal, guardianPublic: true }),
  getAccess: (candidate, { signal } = {}) => api.get('/guardian/access', {
    headers: authMode === 'api_key' ? { 'X-Guardian-Key': candidate } : {}, timeout: 10000, signal, guardianAccessCheck: true,
  }),
  logout: ({ signal } = {}) => api.post('/guardian/auth/logout', undefined, { timeout: 10000, signal, guardianAccessCheck: true }),
  getHealth: () => api.get('/health'),
  getOverview: ({ signal } = {}) => api.get('/guardian/overview', { timeout: 25000, signal }),
  getSummary: (days = 14, { signal } = {}) => api.get('/guardian/summary', { params: { days }, timeout: 25000, signal }),
  getMonitoring: ({ signal } = {}) => api.get('/guardian/monitoring', { timeout: 10000, signal }),
  listIncidents: (status, { signal } = {}) =>
    api.get('/guardian/incidents', { params: status ? { status } : {}, timeout: 25000, signal }),
  getIncident: (id, { signal } = {}) => api.get(`/guardian/incidents/${encodeURIComponent(id)}`, { timeout: 25000, signal }),
  resolveIncident: (id, { signal } = {}) => api.post(`/guardian/incidents/${encodeURIComponent(id)}/resolve`, undefined, { timeout: 25000, signal }),
  getTrends: (days = 14, { signal } = {}) => api.get('/guardian/trends', { params: { days }, timeout: 25000, signal }),
  getMetrics: (hours = 48, { signal } = {}) => api.get('/guardian/metrics', { params: { hours }, timeout: 25000, signal }),

  // The API serves bounded, coverage-aware source reads behind a short memory cache.
  getLive: (hours = 24, runs = 8, calls = 60, { signal } = {}) =>
    api.get('/guardian/live', { params: { hours, runs, calls }, timeout: 25000, signal }),
  getLiveRun: (traceId, { signal, hours = 168 } = {}) =>
    api.get(`/guardian/live/runs/${encodeURIComponent(traceId)}`, { params: { hours }, timeout: 25000, signal }),
};

export const captureRequestId = () => {
  const entropy = globalThis.crypto;
  if (!entropy?.getRandomValues) throw new Error('secure_random_unavailable');
  if (typeof entropy.randomUUID === 'function') return entropy.randomUUID();
  const bytes = entropy.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6] & 15) | 64;
  bytes[8] = (bytes[8] & 63) | 128;
  const hex = [...bytes].map((value) => value.toString(16).padStart(2, '0')).join('');
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
};

// Machine intake deliberately bypasses the dashboard Axios client and session.
// Never follow redirects with an ingestion credential or attach browser cookies.
export const sendCaptureTest = async (token, { signal } = {}) => {
  if (signal?.aborted) throw new Error('capture_test_failed');
  if (authMode !== 'oidc' || !/^cg_ingest_[a-f0-9]{32}_[A-Za-z0-9_-]{43}$/.test(token)) throw new Error('capture_test_unavailable');
  const id = captureRequestId();
  const controller = new AbortController();
  const abort = () => controller.abort();
  if (signal?.aborted) controller.abort();
  signal?.addEventListener('abort', abort, { once: true });
  const timer = setTimeout(abort, 15000);
  const timestamp = new Date().toISOString();
  const body = { schema_version: 1, batch_id: id, test_mode: true, events: [{
    observation_id: `setup-test-${id}`, trace_id: `setup-${id}`, agent_name: 'guardian-setup', model: 'guardian/test',
    started_at: timestamp, ended_at: timestamp, status: 'unknown', cost_usd: null,
    input_tokens: null, output_tokens: null, total_tokens: null,
  }] };
  try {
    const response = await fetch(`${GUARDIAN_URL}/api/guardian/ingest/events`, {
      method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Guardian-Ingest-Key': token },
      credentials: 'omit', redirect: 'error', cache: 'no-store', referrerPolicy: 'no-referrer',
      body: JSON.stringify(body), signal: controller.signal,
    });
    if (response.status !== 202) throw Object.assign(new Error('capture_test_failed'), { status: response.status });
    const receipt = await response.json();
    if (!receipt || typeof receipt !== 'object' || Array.isArray(receipt) || Object.keys(receipt).length !== 7
        || receipt.batch_id !== id || receipt.test_mode !== true || receipt.processing !== 'test_only'
        || receipt.received !== 1 || receipt.duplicate !== 0 || receipt.conflict_candidates !== 0 || typeof receipt.replayed !== 'boolean') {
      throw new Error('capture_test_unconfirmed');
    }
    return { batch_id: receipt.batch_id };
  } catch (error) {
    throw Object.assign(new Error('capture_test_failed'), { status: error?.status });
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener('abort', abort);
  }
};

export default guardianApi;
