import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { MemoryRouter, Route, Routes, useNavigate } from 'react-router-dom';
import GuardianIncidentDetail from '@/pages/GuardianIncidentDetail';
import guardianApi from '@/services/guardianApi';
import { GuardianAccessContext } from '@/contexts/GuardianAccess';

jest.mock('@/services/guardianApi', () => ({
  __esModule: true, clearApiKey: jest.fn(),
  default: { getIncident: jest.fn(), resolveIncident: jest.fn(), getNotifications: jest.fn() },
}));
jest.mock('sonner', () => ({ toast: { error: jest.fn(), success: jest.fn() } }));

const incident = { id: 'first', title: 'First incident evidence', summary: 'Synthetic evidence',
  status: 'open', severity: 'high', detector: 'cost_anomaly', evidence: { count: 1 },
  created_at: '2026-01-01T00:00:00Z', trace_ids: [], trace_urls: [] };
const deferred = () => {
  let resolve;
  let reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
};
const Switch = () => {
  const navigate = useNavigate();
  return <button onClick={() => navigate('/incidents/second')}>Other incident</button>;
};
let root;
let container;
const button = (label) => [...container.querySelectorAll('button')].find((node) => node.textContent === label);
const render = async (permissions = ['read', 'resolve_incidents']) => {
  await act(async () => root.render(<GuardianAccessContext.Provider value={{ permissions, auth_mode: 'api_key' }}><MemoryRouter initialEntries={['/incidents/first']}>
    <Switch /><Routes><Route path="/incidents/:incidentId" element={<GuardianIncidentDetail />} /></Routes>
  </MemoryRouter></GuardianAccessContext.Provider>));
};

beforeEach(() => {
  jest.resetAllMocks();
  guardianApi.getIncident.mockResolvedValue({ data: incident });
  guardianApi.getNotifications.mockResolvedValue({ data: { schema_version: 1, revision: 0, project: null, can_manage: false, updated_at: null,
    destination: { channel: 'slack', state: 'not_configured', verified: false, enabled: false }, worker: { status: 'unknown', last_seen_at: null }, deliveries: [], has_more: false } });
  guardianApi.resolveIncident.mockResolvedValue({ data: { ...incident, status: 'resolved' } });
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
});
afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
});

test('viewer access can inspect evidence but cannot resolve an incident', async () => {
  await render(['read']);
  expect(container.textContent).toContain(incident.title);
  expect(button('Mark resolved')).toBeUndefined();
  expect(guardianApi.resolveIncident).not.toHaveBeenCalled();
});

test('delivery history failure does not hide incident evidence or claim no deliveries', async () => {
  guardianApi.getNotifications.mockRejectedValue({ response: { status: 503 } }); await render();
  expect(container.textContent).toContain(incident.title);
  expect(container.querySelector('pre').textContent).toContain('"count": 1');
  expect(container.textContent).toContain('Notification history is unavailable');
  expect(container.textContent).not.toContain('No recent delivery records');
  expect(button('Mark resolved')).toBeDefined();
});

test.each([
  [{ policy_revision: 3, policy_kind: 'absolute', metric: 'cost_usd', observed_value: '0.000000000002', threshold_value: '0.000000000001', comparison: 'gt', reason: 'cost_limit_exceeded' }, 'Observed call cost $0.000000000002 exceeded the saved $0.000000000001 limit.'],
  [{ policy_revision: 3, policy_kind: 'absolute', metric: 'latency_ms', observed_value: 1500, threshold_value: 1000, comparison: 'gt', reason: 'latency_limit_exceeded' }, 'Observed call duration 1,500 ms exceeded the saved 1,000 ms limit.'],
  [{ policy_revision: 3, policy_kind: 'reported_error', metric: 'status', observed_value: 'error', threshold_value: 'error', comparison: 'eq', reason: 'reported_call_error' }, 'The call reported an error while call-error alerts were enabled.'],
])('configured evidence is explained above raw values and retains an internal investigation path', async (evidence, expected) => {
  guardianApi.getIncident.mockResolvedValue({ data: { ...incident, evidence, trace_ids: ['trace-1'] } });
  await render(['read']);
  const explanation = container.querySelector('[aria-label="Monitoring rule evidence"]');
  expect(explanation.textContent).toContain(expected);
  expect(explanation.textContent).toContain('policy revision 3');
  expect(container.querySelector('pre').textContent).toContain(JSON.stringify(evidence, null, 2));
  expect(container.querySelector('a[href="/runs/trace-1"]')).not.toBeNull();
  expect(button('Mark resolved')).toBeUndefined();
});

test.each([
  { policy_revision: 1, policy_kind: 'absolute', metric: 'cost_usd', observed_value: null, threshold_value: '0', comparison: 'gt', reason: 'cost_limit_exceeded' },
  { policy_revision: 1, policy_kind: 'absolute', metric: 'cost_usd', observed_value: '0', threshold_value: '0', comparison: 'gt', reason: 'cost_limit_exceeded' },
  { policy_revision: 1, policy_kind: 'absolute', metric: 'cost_usd', observed_value: '0.1', threshold_value: '0.2', comparison: 'gt', reason: 'cost_limit_exceeded' },
  { policy_revision: 1, policy_kind: 'absolute', metric: 'latency_ms', observed_value: 10, threshold_value: 20, comparison: 'gt', reason: 'latency_limit_exceeded' },
  { policy_revision: 1, policy_kind: 'reported_error', metric: 'status', observed_value: 'unknown', threshold_value: 'error', comparison: 'eq', reason: 'reported_call_error' },
])('unknown or contradictory evidence does not receive an invented threshold explanation', async (evidence) => {
  guardianApi.getIncident.mockResolvedValue({ data: { ...incident, evidence } }); await render();
  expect(container.querySelector('[aria-label="Monitoring rule evidence"]')).toBeNull();
  expect(container.querySelector('pre')).not.toBeNull();
});

test('a confirmed404 remains on the requested detail route with a truthful absence message', async () => {
  guardianApi.getIncident.mockRejectedValue({ response: { status: 404 } });
  await render();
  expect(container.querySelector('h2').textContent).toBe('Incident not found');
  expect(container.querySelector('[role="alert"]').textContent).toContain('requested incident was not found');
  expect(button('Back to incidents')).toBeDefined();
  expect(button('Retry incident')).toBeUndefined();
});

test.each([[403, 'Access denied'], [503, 'Could not load incident'], ['network', 'Could not load incident']])(
  'HTTP or transport failure %s is not mislabeled as missing and can retry', async (status, title) => {
    guardianApi.getIncident.mockRejectedValue(status === 'network' ? new Error('private-error-detail') : { response: { status } });
    await render();
    expect(container.querySelector('h2').textContent).toBe(title);
    expect(container.textContent).not.toContain('Incident not found');
    expect(container.textContent).not.toContain('private-error-detail');
    guardianApi.getIncident.mockResolvedValue({ data: incident });
    await act(async () => button('Retry incident').click());
    expect(container.textContent).toContain(incident.title);
    expect(container.querySelector('[role="alert"]')).toBeNull();
  },
);

test('changing an incident ID immediately hides previously loaded evidence', async () => {
  await render();
  const next = deferred();
  guardianApi.getIncident.mockReturnValue(next.promise);
  await act(async () => button('Other incident').click());
  expect(container.textContent).not.toContain(incident.title);
  expect(container.textContent).toContain('Loading incident...');
  await act(async () => next.reject({ response: { status: 503 } }));
  expect(container.textContent).not.toContain(incident.title);
  expect(container.textContent).toContain('Could not load incident');
});

test('a delayed old read cannot replace evidence from the new incident', async () => {
  const first = deferred();
  const second = { ...incident, id: 'second', title: 'Second incident evidence' };
  guardianApi.getIncident.mockReturnValueOnce(first.promise).mockResolvedValue({ data: second });
  await render();
  const signal = guardianApi.getIncident.mock.calls[0][1].signal;
  await act(async () => button('Other incident').click());
  expect(signal.aborted).toBe(true);
  await act(async () => first.resolve({ data: incident }));
  expect(container.textContent).toContain(second.title);
  expect(container.textContent).not.toContain(incident.title);
});

test('a response for the wrong incident ID is rejected without rendering its evidence', async () => {
  guardianApi.getIncident.mockResolvedValue({ data: { ...incident, id: 'other' } });
  await render();
  expect(container.textContent).not.toContain(incident.title);
  expect(container.textContent).toContain('Could not load incident');
});

test('resolution requires confirmation and preserves evidence on a temporary failure', async () => {
  await render();
  guardianApi.resolveIncident.mockRejectedValue({ response: { status: 503 } });
  await act(async () => button('Mark resolved').click());
  expect(container.textContent).toContain('Could not confirm resolution');
  expect(container.textContent).toContain(incident.title);
  guardianApi.resolveIncident.mockResolvedValue({ data: { ...incident, status: 'resolved' } });
  await act(async () => button('Mark resolved').click());
  expect(button('Mark resolved')).toBeUndefined();
  expect(container.querySelector('[role="alert"]')).toBeNull();
});

test('a late resolution cannot replace the next incident after navigation', async () => {
  await render();
  const resolution = deferred();
  guardianApi.resolveIncident.mockReturnValue(resolution.promise);
  await act(async () => button('Mark resolved').click());
  const signal = guardianApi.resolveIncident.mock.calls[0][1].signal;
  guardianApi.getIncident.mockResolvedValue({ data: { ...incident, id: 'second', title: 'Second incident evidence' } });
  await act(async () => button('Other incident').click());
  expect(signal.aborted).toBe(true);
  await act(async () => resolution.resolve({ data: { ...incident, status: 'resolved' } }));
  expect(container.textContent).toContain('Second incident evidence');
  expect(container.textContent).not.toContain(incident.title);
  expect(button('Mark resolved')).toBeDefined();
});
