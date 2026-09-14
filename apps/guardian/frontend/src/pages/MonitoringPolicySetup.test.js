import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { MemoryRouter } from 'react-router-dom';
import MonitoringPolicySetup from './MonitoringPolicySetup';
import { GuardianAccessContext } from '@/contexts/GuardianAccess';
import guardianApi from '@/services/guardianApi';
import { draftRules, validMonitoringPolicy, validPolicyRules } from '@/lib/policyModel';

jest.mock('@/services/guardianApi', () => ({ __esModule: true, default: { getMonitoringPolicy: jest.fn(), updateMonitoringPolicy: jest.fn() } }));
const project = { organization_id: 'org', project_id: 'project', environment: 'test', name: 'Synthetic project' };
const access = { auth_mode: 'oidc', actor: { id: 'owner', name: 'Project owner', role: 'owner' }, project, permissions: ['read', 'resolve_incidents'] };
const defaults = { max_call_cost_usd: null, max_call_latency_ms: null, alert_on_errors: true };
const policy = (revision = 0, rules = defaults, changes = {}) => ({ schema_version: 1, revision, rules,
  updated_at: revision ? '2026-09-12T12:00:00Z' : null, updated_by: revision ? access.actor : null, can_manage: true, project, ...changes });
const deferred = () => { let resolve, reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no; }); return { promise, resolve, reject }; };
let container, root;
const button = (label) => [...container.querySelectorAll('button')].find((node) => node.textContent === label);
const render = async (value = access) => act(async () => root.render(<GuardianAccessContext.Provider value={value}>
  <MemoryRouter><MonitoringPolicySetup /></MemoryRouter></GuardianAccessContext.Provider>));
const input = async (id, value) => act(async () => {
  const node = container.querySelector(`#${id}`);
  Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(node, value);
  node.dispatchEvent(new Event('input', { bubbles: true }));
});
const save = async () => act(async () => container.querySelector('form').dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })));
const reload = async () => act(async () => button('Reload saved rules').click());
beforeEach(() => {
  jest.resetAllMocks();
  guardianApi.getMonitoringPolicy.mockResolvedValue({ status: 200, data: policy() });
  guardianApi.updateMonitoringPolicy.mockImplementation(async ({ expected_revision, rules }) => ({ status: 200, data: policy(expected_revision + 1, rules) }));
  container = document.createElement('div'); document.body.appendChild(container); root = createRoot(container);
});
afterEach(async () => { await act(async () => root.unmount()); container.remove(); jest.useRealTimers(); });

test('cold loading and failure never invent defaults; explicit reload recovers', async () => {
  const pending = deferred(); guardianApi.getMonitoringPolicy.mockReturnValueOnce(pending.promise);
  await render();
  expect(container.textContent).toContain('Loading monitoring rules');
  expect(container.textContent).not.toContain('Absolute cost limit disabled');
  expect(container.querySelector('form')).toBeNull();
  await act(async () => pending.reject({ response: { status: 503, data: { detail: 'private-server-body' } } }));
  expect(container.textContent).toContain('Monitoring rules are unavailable');
  expect(container.textContent).not.toContain('private-server-body');
  await reload();
  expect(container.textContent).toContain('Default monitoring rules');
  expect(container.textContent).not.toContain('Saved revision 0');
});

test('owner edits exact zero limits and error toggle without a provider or baseline prerequisite', async () => {
  await render(); await input('policy-cost', '0'); await input('policy-latency', '0');
  await act(async () => container.querySelector('#policy-errors').click());
  await save();
  expect(guardianApi.updateMonitoringPolicy).toHaveBeenCalledWith({ expected_revision: 0,
    rules: { max_call_cost_usd: '0', max_call_latency_ms: 0, alert_on_errors: false } }, { signal: expect.any(AbortSignal) });
  expect(container.textContent).toContain('Monitoring rules saved as revision 1');
  expect(container.textContent).toContain('Above $0 USD');
  expect(container.textContent).toContain('Above 0 ms');
  expect(container.textContent).toContain('Existing relative cost and latency checks remain active');
  expect(container.textContent).toContain('does not establish capture or worker health');
  expect(container.textContent).toContain('do not rescore historical incidents');
});

test('blank fields disable absolute limits and numeric boundaries are checked locally', async () => {
  guardianApi.getMonitoringPolicy.mockResolvedValue({ data: policy(1, { ...defaults, max_call_cost_usd: '1', max_call_latency_ms: 5 }) });
  await render(); await input('policy-cost', ''); await input('policy-latency', ''); await save();
  expect(guardianApi.updateMonitoringPolicy.mock.calls[0][0].rules).toEqual(defaults);
  for (const [id, value] of [['policy-cost', '-1'], ['policy-cost', '1e-3'], ['policy-cost', '0.0000000000001'], ['policy-latency', '86400001'], ['policy-latency', '0.5']]) {
    await input(id, value);
    expect(button('Save monitoring rules').disabled).toBe(true);
  }
  expect(guardianApi.updateMonitoringPolicy).toHaveBeenCalledTimes(1);
});

test.each(['operator', 'viewer'])('%s cannot edit even if the response incorrectly grants manage capability', async (role) => {
  await render({ ...access, actor: { ...access.actor, role } });
  expect(container.textContent).toContain('Monitoring rules are unavailable');
  expect(container.querySelector('form')).toBeNull();
});

test.each(['operator', 'viewer'])('%s can inspect a validated read-only policy', async (role) => {
  guardianApi.getMonitoringPolicy.mockResolvedValue({ data: policy(1, defaults, { can_manage: false }) });
  await render({ ...access, actor: { ...access.actor, role } });
  expect(container.textContent).toContain('Saved revision 1');
  expect(container.textContent).toContain('Only the project owner can edit');
  expect(container.querySelector('form')).toBeNull();
});

test('owner requires server capability and shared-key access remains read-only', async () => {
  guardianApi.getMonitoringPolicy.mockResolvedValue({ data: policy(0, defaults, { can_manage: false }) });
  await render(); expect(container.querySelector('form')).toBeNull();
  guardianApi.getMonitoringPolicy.mockResolvedValue({ data: policy(0, defaults, { can_manage: false, project: null }) });
  await render({ auth_mode: 'api_key', permissions: ['read', 'resolve_incidents'] });
  expect(container.textContent).toContain('Local shared-key access shows monitoring rules read-only');
  expect(container.querySelector('form')).toBeNull();
});

test('refresh preserves edits made before and while a read is in flight', async () => {
  await render(); await input('policy-cost', '2');
  const pending = deferred(); guardianApi.getMonitoringPolicy.mockReturnValueOnce(pending.promise);
  await reload(); await input('policy-latency', '99');
  await act(async () => pending.resolve({ data: policy(1, { ...defaults, max_call_cost_usd: '5' }) }));
  expect(container.querySelector('#policy-cost').value).toBe('2');
  expect(container.querySelector('#policy-latency').value).toBe('99');
  expect(container.textContent).toContain('Above $5 USD');
  expect(container.textContent).toContain('Your unsaved edits are preserved');
  await save();
  expect(guardianApi.updateMonitoringPolicy.mock.calls[0][0].expected_revision).toBe(1);
});

test('a refresh failure labels old values and blocks save until a fresh valid read', async () => {
  await render(); await input('policy-cost', '2');
  guardianApi.getMonitoringPolicy.mockRejectedValueOnce({ response: { status: 503 } });
  await reload();
  expect(container.textContent).toContain('Showing previously fetched rules; current settings are unconfirmed');
  expect(button('Save monitoring rules').disabled).toBe(true);
  expect(container.querySelector('#policy-cost').value).toBe('2');
  await reload(); expect(button('Save monitoring rules').disabled).toBe(false);
});

test('revision conflict cannot be retried until read-back and preserves the unsaved draft', async () => {
  await render(); await input('policy-cost', '2');
  guardianApi.updateMonitoringPolicy.mockRejectedValueOnce({ response: { status: 409 } }); await save();
  expect(container.textContent).toContain('Another save changed the rules');
  expect(button('Save monitoring rules').disabled).toBe(true);
  await save(); expect(guardianApi.updateMonitoringPolicy).toHaveBeenCalledTimes(1);
  guardianApi.getMonitoringPolicy.mockResolvedValue({ data: policy(1, { ...defaults, max_call_cost_usd: '5' }) });
  await reload(); expect(container.querySelector('#policy-cost').value).toBe('2');
  await save(); expect(guardianApi.updateMonitoringPolicy.mock.calls[1][0].expected_revision).toBe(1);
});

test('lost save acknowledgement reads back an already committed result without another update', async () => {
  await render(); await input('policy-cost', '2');
  guardianApi.updateMonitoringPolicy.mockRejectedValueOnce(new Error('private-network-error')); await save();
  expect(container.textContent).toContain('The save was not confirmed');
  expect(container.textContent).not.toContain('Monitoring rules saved as');
  guardianApi.getMonitoringPolicy.mockResolvedValue({ data: policy(1, { ...defaults, max_call_cost_usd: '2' }) });
  await reload();
  expect(container.textContent).toContain('Saved revision 1');
  expect(button('Save monitoring rules').disabled).toBe(true);
  expect(guardianApi.updateMonitoringPolicy).toHaveBeenCalledTimes(1);
});

test('malformed save acknowledgement cannot claim success or allow an automatic retry', async () => {
  await render(); await input('policy-cost', '2');
  guardianApi.updateMonitoringPolicy.mockResolvedValueOnce({ status: 200, data: policy(1, { ...defaults, max_call_cost_usd: '999' }) }); await save();
  expect(container.textContent).toContain('The save was not confirmed');
  expect(container.textContent).not.toContain('Above $999');
  expect(button('Save monitoring rules').disabled).toBe(true);
});

test('a canonical equivalent decimal acknowledgement is accepted exactly once', async () => {
  await render(); await input('policy-cost', '2.000');
  guardianApi.updateMonitoringPolicy.mockResolvedValueOnce({ status: 200, data: policy(1, { ...defaults, max_call_cost_usd: '2' }) }); await save();
  expect(container.textContent).toContain('Monitoring rules saved as revision 1');
});

test('saving has one in-flight mutation and duplicate submits do not create updates', async () => {
  await render(); await input('policy-cost', '2');
  const pending = deferred(); guardianApi.updateMonitoringPolicy.mockReturnValueOnce(pending.promise);
  await save(); await save();
  expect(guardianApi.updateMonitoringPolicy).toHaveBeenCalledTimes(1);
  expect(button('Reload saved rules').disabled).toBe(true);
  await act(async () => pending.resolve({ status: 200, data: policy(1, { ...defaults, max_call_cost_usd: '2' }) }));
});

test('role loss aborts a save and a late success cannot restore editing or announce success', async () => {
  await render(); await input('policy-cost', '2');
  const pending = deferred(); guardianApi.updateMonitoringPolicy.mockReturnValueOnce(pending.promise); await save();
  const signal = guardianApi.updateMonitoringPolicy.mock.calls[0][1].signal;
  guardianApi.getMonitoringPolicy.mockResolvedValue({ data: policy(0, defaults, { can_manage: false }) });
  await render({ ...access, actor: { ...access.actor, role: 'viewer' } });
  expect(signal.aborted).toBe(true);
  await act(async () => pending.resolve({ status: 200, data: policy(1, { ...defaults, max_call_cost_usd: '2' }) }));
  expect(container.querySelector('form')).toBeNull();
  expect(container.textContent).not.toContain('Monitoring rules saved as');
});

test('unmount aborts reads and saves with late completions fenced', async () => {
  const pending = deferred(); guardianApi.getMonitoringPolicy.mockReturnValueOnce(pending.promise); await render();
  const signal = guardianApi.getMonitoringPolicy.mock.calls[0][0].signal;
  await act(async () => root.unmount()); root = createRoot(container);
  expect(signal.aborted).toBe(true);
  await act(async () => pending.resolve({ data: policy() }));
  expect(container.textContent).toBe('');
  await render(); await input('policy-cost', '2');
  const write = deferred(); guardianApi.updateMonitoringPolicy.mockReturnValueOnce(write.promise); await save();
  const writeSignal = guardianApi.updateMonitoringPolicy.mock.calls[0][1].signal;
  await act(async () => root.unmount()); root = createRoot(container);
  expect(writeSignal.aborted).toBe(true);
  await act(async () => write.resolve({ status: 200, data: policy(1, { ...defaults, max_call_cost_usd: '2' }) }));
  expect(container.textContent).toBe('');
});

test('policy fetch is independent and never polls over an editing session', async () => {
  jest.useFakeTimers(); await render(); await input('policy-cost', '2');
  await act(async () => jest.advanceTimersByTime(60000));
  expect(guardianApi.getMonitoringPolicy).toHaveBeenCalledTimes(1);
  expect(container.querySelector('#policy-cost').value).toBe('2');
});

test.each([403, 422])('save HTTP %i stays truthful and retains the draft', async (status) => {
  await render(); await input('policy-cost', '2');
  guardianApi.updateMonitoringPolicy.mockRejectedValueOnce({ response: { status } }); await save();
  expect(container.textContent).toContain(status === 403 ? 'Only the project owner can save' : 'These rules were rejected');
  expect(container.querySelector('#policy-cost').value).toBe('2');
  expect(container.textContent).not.toContain('Monitoring rules saved as');
});

test('schema validation rejects malformed counters, scope, dates, metadata and numeric coercion', () => {
  expect(validMonitoringPolicy(policy(), access)).toBe(true);
  for (const changes of [{ unexpected: 'private' }, { revision: true }, { revision: Number.MAX_SAFE_INTEGER + 1 },
    { revision: -1 }, { project: { ...project, project_id: 'other' } }, { updated_at: '2026-09-12T12:00:00Z' },
    { rules: { ...defaults, extra: 1 } }, { rules: { ...defaults, alert_on_errors: 'true' } }]) {
    expect(validMonitoringPolicy({ ...policy(), ...changes }, access)).toBe(false);
  }
  expect(validMonitoringPolicy(policy(1, defaults, { updated_at: '2026-09-12T12:00:00' }), access)).toBe(false);
  expect(validMonitoringPolicy(policy(1, defaults, { updated_at: '2026-02-30T12:00:00Z' }), access)).toBe(false);
  expect(validMonitoringPolicy(policy(2147483648), access)).toBe(false);
  expect(validMonitoringPolicy(policy(1, defaults, { updated_by: { ...access.actor, role: 'operator' } }), access)).toBe(false);
  expect(validMonitoringPolicy(policy(1, defaults, { updated_by: { ...access.actor, role: 'viewer' } }), access)).toBe(false);
  expect(validMonitoringPolicy(policy(0, defaults, { project: null, can_manage: false }), { auth_mode: 'unknown' })).toBe(false);
  expect(validMonitoringPolicy(policy(0, defaults, { can_manage: false }), access)).toBe(false);
  expect(validMonitoringPolicy(policy(1, defaults, { updated_by: { ...access.actor, role: 'admin' } }), access)).toBe(false);
  for (const value of [0, true, '1e-3', '01', '1\n', '1000000000']) expect(validPolicyRules({ ...defaults, max_call_cost_usd: value })).toBe(false);
  for (const value of ['1', true, -1, 0.5, 86400001]) expect(validPolicyRules({ ...defaults, max_call_latency_ms: value })).toBe(false);
  expect(draftRules({ cost: '999999999.999999999999', latency: '86400000', errors: false })).toEqual({ max_call_cost_usd: '999999999.999999999999', max_call_latency_ms: 86400000, alert_on_errors: false });
});

test('malformed or wrong-project reads never expose their configuration or enable saving', async () => {
  guardianApi.getMonitoringPolicy.mockResolvedValueOnce({ data: policy(1, { ...defaults, max_call_cost_usd: '99' }, { project: { ...project, project_id: 'other' } }) });
  await render(); expect(container.textContent).toContain('Monitoring rules are unavailable');
  expect(container.textContent).not.toContain('Above $99'); expect(container.querySelector('form')).toBeNull();
});
