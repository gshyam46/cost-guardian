import { act } from 'react';
import { createRoot } from 'react-dom/client';
import App from './App';
import guardianApi from '@/services/guardianApi';

jest.mock('@/services/guardianApi', () => ({
  __esModule: true,
  configureAuth: jest.fn(),
  getApiKey: () => 'synthetic-test-key',
  clearApiKey: jest.fn(),
  default: { listIncidents: jest.fn(), getIncident: jest.fn(), getAccess: jest.fn(), getAuthConfig: jest.fn() },
}));
jest.mock('@/components/ui/sonner', () => ({ Toaster: () => null }));
jest.mock('sonner', () => ({ toast: { error: jest.fn(), success: jest.fn() } }));

const incident = {
  id: 'incident-42', title: 'Unexpected retry spend', summary: 'Investigate retry traffic',
  severity: 'high', status: 'open', detector: 'cost_anomaly', evidence: { cost_usd: 2 },
  created_at: '2026-01-01T00:00:00Z', trace_ids: ['trace-42'], trace_urls: [],
};
const deferred = () => {
  let resolve;
  let reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
};
let container;
let root;
const button = (label) => [...container.querySelectorAll('button')].find((node) => node.textContent === label);
const render = async () => { await act(async () => root.render(<App />)); };
const refresh = async () => { await act(async () => document.dispatchEvent(new Event('visibilitychange'))); };

beforeEach(() => {
  jest.resetAllMocks();
  jest.spyOn(document, 'visibilityState', 'get').mockReturnValue('visible');
  window.history.replaceState({}, '', '/incidents');
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
  guardianApi.getAuthConfig.mockResolvedValue({ data: { auth_mode: 'api_key', login_path: null } });
  guardianApi.getAccess.mockResolvedValue({ data: { authenticated: true, auth_mode: 'api_key', deployment_mode: 'single_project', permissions: ['read', 'resolve_incidents'] } });
  guardianApi.listIncidents.mockResolvedValue({ data: [incident] });
  guardianApi.getIncident.mockResolvedValue({ data: incident });
});

afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
  jest.restoreAllMocks();
});

test('an unresolved first request announces loading without claiming an empty list', async () => {
  guardianApi.listIncidents.mockReturnValue(new Promise(() => {}));
  await render();
  expect(container.querySelector('[role="status"]').textContent).toBe('Loading incidents...');
  expect(container.textContent).not.toContain('No open incidents');
  expect(container.querySelector('[role="alert"]')).toBeNull();
  expect(guardianApi.listIncidents).toHaveBeenCalledWith('open', { signal: expect.any(AbortSignal) });
});

test('only a successful current-filter response renders the empty state', async () => {
  guardianApi.listIncidents.mockResolvedValue({ data: [] });
  await render();
  expect(container.textContent).toContain('No open incidents');
  expect(button('Open').getAttribute('aria-pressed')).toBe('true');
  await act(async () => button('All').click());
  expect(container.textContent).toContain('No incidents');
  expect(container.textContent).not.toContain('No open incidents');
  expect(guardianApi.listIncidents).toHaveBeenLastCalledWith(null, { signal: expect.any(AbortSignal) });
  expect(button('All').getAttribute('aria-pressed')).toBe('true');
});

test.each([new Error('synthetic offline'), { response: { status: 401 } }])(
  'cold transport or auth failure remains unavailable and offers a working retry', async (failure) => {
    guardianApi.listIncidents.mockRejectedValue(failure);
    await render();
    expect(container.querySelector('[role="alert"]').textContent).toContain('Could not load incidents.');
    expect(container.textContent).not.toContain('No open incidents');
    const retry = deferred();
    guardianApi.listIncidents.mockReturnValue(retry.promise);
    await act(async () => button('Retry incidents').click());
    expect(button('Retrying incidents...').disabled).toBe(true);
    await act(async () => retry.resolve({ data: [incident] }));
    expect(container.textContent).toContain(incident.title);
    expect(container.querySelector('[role="alert"]')).toBeNull();
    expect(button('Open').getAttribute('aria-pressed')).toBe('true');
  },
);

test('an invalid response body cannot become a successful empty incident list', async () => {
  guardianApi.listIncidents.mockResolvedValue({ data: null });
  await render();
  expect(container.textContent).toContain('Could not load incidents.');
  expect(container.textContent).not.toContain('No open incidents');
});

test('a failed refresh retains same-filter rows with a stale warning and can recover to empty', async () => {
  await render();
  guardianApi.listIncidents.mockRejectedValue(new Error('synthetic outage'));
  await refresh();
  expect(container.textContent).toContain(incident.title);
  expect(container.querySelector('[role="alert"]').textContent).toContain('Could not refresh incidents.');
  expect(container.textContent).toContain('Showing the last successful response for this filter from');
  guardianApi.listIncidents.mockResolvedValue({ data: [] });
  await act(async () => button('Retry incidents').click());
  expect(container.textContent).toContain('No open incidents');
  expect(container.textContent).not.toContain(incident.title);
  expect(container.querySelector('[role="alert"]')).toBeNull();
});

test('an empty cached response is historical when its refresh fails', async () => {
  guardianApi.listIncidents.mockResolvedValue({ data: [] });
  await render();
  guardianApi.listIncidents.mockRejectedValue(new Error('synthetic outage'));
  await refresh();
  expect(container.textContent).toContain('That response contained no matching incidents; current results are unknown.');
  expect(container.textContent).not.toContain('No open incidents');
  expect(button('Retry incidents')).toBeDefined();
});

test('switching filters hides old rows while loading and after failure of the new filter', async () => {
  await render();
  const resolved = deferred();
  guardianApi.listIncidents.mockReturnValue(resolved.promise);
  await act(async () => button('Resolved').click());
  expect(container.textContent).toContain('Loading incidents...');
  expect(container.textContent).not.toContain(incident.title);
  expect(container.textContent).not.toContain('API checked');
  expect(guardianApi.listIncidents).toHaveBeenLastCalledWith('resolved', { signal: expect.any(AbortSignal) });
  await act(async () => resolved.reject(new Error('synthetic outage')));
  expect(container.textContent).toContain('Could not load incidents.');
  expect(container.textContent).not.toContain(incident.title);
  expect(container.textContent).not.toContain('No resolved incidents');
  expect(container.textContent).not.toContain('Showing the last successful response');
  expect(button('Resolved').getAttribute('aria-pressed')).toBe('true');
});

test('a previous filter response cannot overwrite the latest selected filter', async () => {
  const open = deferred();
  guardianApi.listIncidents.mockReturnValueOnce(open.promise).mockResolvedValue({ data: [] });
  await render();
  const openSignal = guardianApi.listIncidents.mock.calls[0][1].signal;
  await act(async () => button('Resolved').click());
  expect(openSignal.aborted).toBe(true);
  await act(async () => open.resolve({ data: [incident] }));
  expect(container.textContent).toContain('No resolved incidents');
  expect(container.textContent).not.toContain(incident.title);
});

test('selecting an incident still opens its evidence route', async () => {
  await render();
  const card = container.querySelector('.cursor-pointer');
  await act(async () => card.click());
  expect(window.location.pathname).toBe('/incidents/incident-42');
  expect(guardianApi.getIncident).toHaveBeenCalledWith('incident-42', { signal: expect.any(AbortSignal) });
  expect(container.querySelector('h2').textContent).toBe(incident.title);
});
