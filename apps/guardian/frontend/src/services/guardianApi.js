import axios from 'axios';

const GUARDIAN_URL = process.env.REACT_APP_GUARDIAN_URL || 'http://localhost:8001';
const KEY_STORAGE = 'guardian_api_key';

export const getApiKey = () => localStorage.getItem(KEY_STORAGE) || '';
export const setApiKey = (key) => localStorage.setItem(KEY_STORAGE, key);
export const clearApiKey = () => localStorage.removeItem(KEY_STORAGE);

const api = axios.create({
  baseURL: `${GUARDIAN_URL}/api`,
  headers: { 'Content-Type': 'application/json' },
});

// Guardian authenticates with its own API key, not a monitored app's session cookie --
// it's a separate service and shares no origin or session with anything it watches.
api.interceptors.request.use((config) => {
  const key = getApiKey();
  if (key) config.headers['X-Guardian-Key'] = key;
  return config;
});

export const guardianApi = {
  getHealth: () => api.get('/health'),
  getOverview: () => api.get('/guardian/overview'),
  listIncidents: (status) =>
    api.get('/guardian/incidents', { params: status ? { status } : {} }),
  getIncident: (id) => api.get(`/guardian/incidents/${id}`),
  resolveIncident: (id) => api.post(`/guardian/incidents/${id}/resolve`),
  getTrends: (days = 14) => api.get('/guardian/trends', { params: { days } }),
  getMetrics: (hours = 48) => api.get('/guardian/metrics', { params: { hours } }),
};

export default guardianApi;
