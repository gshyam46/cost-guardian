import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { MemoryRouter } from 'react-router-dom';
import NotificationSetup from '@/pages/NotificationSetup';
import IncidentDeliveries from '@/pages/IncidentDeliveries';
import { GuardianAccessContext } from '@/contexts/GuardianAccess';
import guardianApi from '@/services/guardianApi';
import { validDelivery, validNotifications } from '@/lib/notificationModel';

jest.mock('@/services/guardianApi', () => ({ __esModule: true, default: { getNotifications: jest.fn(), notificationAction: jest.fn() } }));
const project = { organization_id: 'org', project_id: 'project', environment: 'test', name: 'Synthetic project' };
const access = { auth_mode: 'oidc', actor: { id: 'owner', name: 'Owner', role: 'owner' }, project, permissions: ['read', 'resolve_incidents'] };
const now = '2026-09-12T12:00:00Z';
const status = (changes = {}) => ({ schema_version: 1, revision: 0, project, can_manage: true, updated_at: null,
  destination: { channel: 'slack', state: 'configured', verified: false, enabled: false },
  worker: { status: 'unknown', last_seen_at: null }, deliveries: [], has_more: false, ...changes });
const delivery = (changes = {}) => ({ id: 'a'.repeat(64), incident_id: null, kind: 'test', state: 'queued', created_at: now, updated_at: now,
  attempt_count: 0, cycle: 1, next_attempt_at: now, last_outcome: null, can_retry: false, attempts: [], ...changes });
const failed = (changes = {}) => delivery({ state: 'unconfirmed', next_attempt_at: null, attempt_count: 1, last_outcome: 'network_unconfirmed', can_retry: true,
  attempts: [{ number: 1, started_at: now, finished_at: now, outcome: 'network_unconfirmed' }], ...changes });
const deferred = () => { let resolve, reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no; }); return { promise, resolve, reject }; };
let container, root;
const button = (label) => [...container.querySelectorAll('button')].find((node) => node.textContent === label);
const click = async (label) => act(async () => button(label).click());
const render = async (value = access, incidentId = null) => act(async () => root.render(<GuardianAccessContext.Provider value={value}>
  <MemoryRouter>{incidentId === null ? <NotificationSetup /> : <IncidentDeliveries incidentId={incidentId} />}</MemoryRouter></GuardianAccessContext.Provider>));
beforeEach(() => {
  jest.resetAllMocks();
  Object.defineProperty(global, 'crypto', { configurable: true, value: require('node:crypto').webcrypto });
  guardianApi.getNotifications.mockResolvedValue({ data: status() });
  guardianApi.notificationAction.mockResolvedValue({ status: 200, data: status({ revision: 1, updated_at: now }) });
  container = document.createElement('div'); document.body.appendChild(container); root = createRoot(container);
});
afterEach(async () => { await act(async () => root.unmount()); container.remove(); jest.useRealTimers(); });

test('cold loading and failure do not invent configuration or empty delivery history', async () => {
  const pending = deferred(); guardianApi.getNotifications.mockReturnValueOnce(pending.promise); await render();
  expect(container.textContent).toContain('Loading notification status');
  expect(container.textContent).not.toContain('No recent delivery records');
  await act(async () => pending.reject({ response: { status: 503, data: { detail: 'private-secret' } } }));
  expect(container.textContent).toContain('Notification status is unavailable');
  expect(container.textContent).not.toContain('private-secret');
  expect(button('Send test notification')).toBeUndefined();
  await click('Refresh notification status'); expect(container.textContent).toContain('Slack destination configured');
});

test.each(['not_configured', 'invalid'])('destination %s cannot be tested or enabled, but owners may disable it', async (state) => {
  guardianApi.getNotifications.mockResolvedValue({ data: status({ destination: { channel: 'slack', state, verified: false, enabled: false } }) });
  await render();
  expect(button('Send test notification').disabled).toBe(true); expect(button('Enable notifications').disabled).toBe(true);
  expect(button('Disable notifications').disabled).toBe(false);
  await click('Disable notifications'); expect(guardianApi.notificationAction.mock.calls[0][0].action).toBe('disable');
});

test('a changed destination can be retested despite an old destination pending test', async () => {
  guardianApi.getNotifications.mockResolvedValue({ data: status({ destination: { channel: 'slack', state: 'changed', verified: false, enabled: false }, deliveries: [delivery()] }) });
  guardianApi.notificationAction.mockResolvedValue({ status: 200, data: status({ revision: 1, updated_at: now,
    deliveries: [delivery({ id: 'b'.repeat(64) }), delivery({ state: 'cancelled', next_attempt_at: null, last_outcome: 'destination_changed' })] }) });
  await render();
  expect(button('Send test notification').disabled).toBe(false);
  expect(button('Enable notifications').disabled).toBe(true);
  expect(container.textContent).not.toContain('A test is pending');
  await click('Send test notification');
  expect(guardianApi.notificationAction.mock.calls[0][0].action).toBe('test');
  expect(container.textContent).toContain('Slack destination configured');
  expect(container.textContent).toContain('Test request queued');
  expect(container.textContent).toContain('New incident notifications disabled');
  expect(button('Send test notification').disabled).toBe(true);
  expect(button('Enable notifications').disabled).toBe(true);
});

test('a new test at the same verified destination preserves existing enabled notifications', async () => {
  const destination = { channel: 'slack', state: 'configured', verified: true, enabled: true };
  guardianApi.getNotifications.mockResolvedValue({ data: status({ revision: 2, updated_at: now, destination }) });
  guardianApi.notificationAction.mockResolvedValue({ status: 200, data: status({ revision: 3, updated_at: now, destination, deliveries: [delivery()] }) });
  await render(); await click('Send test notification');
  expect(container.textContent).toContain('New incident notifications enabled');
  expect(container.textContent).toContain('Slack accepted a test for the current destination');
  expect(container.textContent).toContain('A test is pending');
  expect(button('Disable notifications').disabled).toBe(false);
});

test('a queued test does not enable notifications or claim Slack acceptance', async () => {
  guardianApi.notificationAction.mockResolvedValue({ status: 200, data: status({ revision: 1, updated_at: now, deliveries: [delivery()] }) });
  await render(); await click('Send test notification');
  const body = guardianApi.notificationAction.mock.calls[0][0];
  expect(body).toMatchObject({ expected_revision: 0, action: 'test' });
  expect(Object.keys(body).sort()).toEqual(['action', 'expected_revision', 'request_id']);
  expect(body.request_id).toMatch(/^[a-f0-9-]{36}$/);
  expect(container.textContent).toContain('Test request queued');
  expect(container.textContent).toContain('New incident notifications disabled');
  expect(container.textContent).not.toContain('Accepted by Slack');
  expect(button('Send test notification').disabled).toBe(true); expect(button('Enable notifications').disabled).toBe(true);
});

test('refresh discovers verified acceptance and enabling remains separate from worker health', async () => {
  await render();
  guardianApi.getNotifications.mockResolvedValue({ data: status({ revision: 1, updated_at: now,
    destination: { channel: 'slack', state: 'configured', verified: true, enabled: false },
    deliveries: [failed({ state: 'accepted', can_retry: false, last_outcome: 'accepted', attempts: [{ number: 1, started_at: now, finished_at: now, outcome: 'accepted' }] })] }) });
  await click('Refresh notification status');
  expect(container.textContent).toContain('Accepted by Slack'); expect(button('Enable notifications').disabled).toBe(false);
  guardianApi.notificationAction.mockResolvedValue({ status: 200, data: status({ revision: 2, updated_at: now,
    destination: { channel: 'slack', state: 'configured', verified: true, enabled: true }, worker: { status: 'stale', last_seen_at: now } }) });
  await click('Enable notifications');
  expect(container.textContent).toContain('New incident notifications enabled');
  expect(container.textContent).toContain('Delivery worker heartbeat is stale');
  expect(container.textContent).not.toMatch(/Monitoring is active|Someone read/);
});

test.each(['operator', 'viewer'])('%s reads valid status without mutation controls', async (role) => {
  guardianApi.getNotifications.mockResolvedValue({ data: status({ can_manage: false, deliveries: [failed()] }) });
  await render({ ...access, actor: { ...access.actor, role } });
  expect(container.textContent).toContain('Acceptance unconfirmed');
  expect(button('Send test notification')).toBeUndefined(); expect(button('Retry notification')).toBeUndefined();
});

test('shared-key mode is read-only and never becomes destination authority', async () => {
  guardianApi.getNotifications.mockResolvedValue({ data: status({ project: null, can_manage: false }) });
  await render({ auth_mode: 'api_key', permissions: ['read', 'resolve_incidents'] });
  expect(container.textContent).toContain('Local shared-key access shows notifications read-only');
  expect(button('Disable notifications')).toBeUndefined();
});

test('stale successful values remain labelled and actions stop after a refresh failure', async () => {
  await render(); guardianApi.getNotifications.mockRejectedValueOnce(new Error('private')); await click('Refresh notification status');
  expect(container.textContent).toContain('Showing previously fetched notification status; the current state is unconfirmed');
  expect(container.textContent).toContain('Slack destination configured');
  expect(button('Send test notification').disabled).toBe(true);
  await click('Refresh notification status'); expect(button('Send test notification').disabled).toBe(false);
});

test.each([409, 503, 403])('action HTTP %i blocks another attempt until read-back', async (code) => {
  await render(); guardianApi.notificationAction.mockRejectedValueOnce({ response: { status: code } }); await click('Send test notification');
  expect(button('Send test notification').disabled).toBe(true);
  expect(container.textContent).not.toContain('Test request queued');
  await click('Send test notification'); expect(guardianApi.notificationAction).toHaveBeenCalledTimes(1);
  guardianApi.getNotifications.mockResolvedValue({ data: status({ revision: 1, updated_at: now, deliveries: [delivery()] }) });
  await click('Refresh notification status');
  expect(container.textContent).toContain('A test is pending'); expect(button('Send test notification').disabled).toBe(true);
});

test('malformed action acknowledgement is never confirmation, while concurrent higher revisions are valid', async () => {
  await render(); guardianApi.notificationAction.mockResolvedValueOnce({ status: 200, data: status() }); await click('Send test notification');
  expect(container.textContent).toContain('The notification action was not confirmed');
  await click('Refresh notification status');
  guardianApi.notificationAction.mockResolvedValueOnce({ status: 200, data: status({ revision: 3, updated_at: now }) }); await click('Send test notification');
  expect(container.textContent).toContain('Test request queued');
});

test('mutation is single-flight and role loss aborts/fences a late success', async () => {
  await render(); const pending = deferred(); guardianApi.notificationAction.mockReturnValueOnce(pending.promise);
  await click('Send test notification'); await click('Send test notification');
  expect(guardianApi.notificationAction).toHaveBeenCalledTimes(1);
  const signal = guardianApi.notificationAction.mock.calls[0][1].signal;
  guardianApi.getNotifications.mockResolvedValue({ data: status({ can_manage: false }) });
  await render({ ...access, actor: { ...access.actor, role: 'viewer' } });
  expect(signal.aborted).toBe(true);
  await act(async () => pending.resolve({ status: 200, data: status({ revision: 1, updated_at: now }) }));
  expect(container.textContent).not.toContain('Test request queued'); expect(button('Send test notification')).toBeUndefined();
});

test('unmount aborts an in-flight read with no late content application', async () => {
  const pending = deferred(); guardianApi.getNotifications.mockReturnValueOnce(pending.promise); await render();
  const signal = guardianApi.getNotifications.mock.calls[0][1].signal;
  await act(async () => root.unmount()); root = createRoot(container);
  expect(signal.aborted).toBe(true); await act(async () => pending.resolve({ data: status() })); expect(container.textContent).toBe('');
});

test('eligible retries explain duplicate risk and preserve delivery identity', async () => {
  guardianApi.getNotifications.mockResolvedValue({ data: status({ deliveries: [failed()] }) }); await render();
  expect(container.textContent).toContain('Retrying can send another copy');
  await click('Retry notification');
  expect(guardianApi.notificationAction.mock.calls[0][0]).toMatchObject({ action: 'retry', delivery_id: 'a'.repeat(64), expected_revision: 0 });
});

test('noneligible failed deliveries do not expose retry controls', async () => {
  guardianApi.getNotifications.mockResolvedValue({ data: status({ deliveries: [failed({ cycle: 3, attempt_count: 15, can_retry: false })] }) }); await render();
  expect(container.textContent).toContain('cycle 3 of 3'); expect(button('Retry notification')).toBeUndefined();
});

test('incident retry validates unfiltered response and fetches filtered history before applying it', async () => {
  const row = failed({ kind: 'incident', incident_id: 'incident-1' });
  guardianApi.getNotifications.mockResolvedValueOnce({ data: status({ deliveries: [row] }) });
  await render(access, 'incident-1');
  guardianApi.notificationAction.mockResolvedValue({ status: 200, data: status({ revision: 1, updated_at: now,
    deliveries: [delivery(), { ...row, id: 'b'.repeat(64), incident_id: 'other-incident' }] }) });
  guardianApi.getNotifications.mockResolvedValue({ data: status({ revision: 1, updated_at: now,
    deliveries: [{ ...row, state: 'queued', can_retry: false, last_outcome: 'retry_requested' }] }) });
  await click('Retry notification');
  expect(guardianApi.getNotifications.mock.calls.map(([id]) => id)).toEqual(['incident-1', 'incident-1']);
  expect(container.textContent).toContain('Retry request accepted');
  expect(container.textContent).not.toContain('Test notification');
  expect(container.querySelectorAll('article')).toHaveLength(1);
});

test('post-action filtered read failure preserves labelled history and blocks another action', async () => {
  guardianApi.getNotifications.mockResolvedValueOnce({ data: status({ deliveries: [failed({ kind: 'incident', incident_id: 'incident-1' })] }) });
  await render(access, 'incident-1');
  guardianApi.getNotifications.mockRejectedValueOnce({ response: { status: 503 } }); await click('Retry notification');
  expect(container.textContent).toContain('The action was accepted, but delivery history could not be refreshed');
  expect(button('Retry notification').disabled).toBe(true);
});

test('changing incident cancels the old request and refuses wrong-incident rows', async () => {
  const pending = deferred(); guardianApi.getNotifications.mockReturnValueOnce(pending.promise); await render(access, 'incident-1');
  const signal = guardianApi.getNotifications.mock.calls[0][1].signal;
  guardianApi.getNotifications.mockResolvedValueOnce({ data: status({ deliveries: [failed({ kind: 'incident', incident_id: 'incident-1' })] }) });
  await render(access, 'incident-2'); expect(signal.aborted).toBe(true);
  await act(async () => pending.resolve({ data: status() }));
  expect(container.textContent).toContain('Notification history is unavailable'); expect(container.querySelector('article')).toBeNull();
});

test('bounded history and unknown safe codes render without disclosing code text', async () => {
  guardianApi.getNotifications.mockResolvedValue({ data: status({ has_more: true, deliveries: [failed({ last_outcome: 'some_unrecognized_private_code' })] }) }); await render();
  expect(container.textContent).toContain('older records are omitted');
  expect(container.textContent).toContain('Delivery could not be confirmed');
  expect(container.textContent).not.toContain('some_unrecognized_private_code');
});

test('manual status never creates a background request or automatically sends a test', async () => {
  jest.useFakeTimers(); await render(); await act(async () => jest.advanceTimersByTime(60000));
  expect(guardianApi.getNotifications).toHaveBeenCalledTimes(1); expect(guardianApi.notificationAction).not.toHaveBeenCalled();
});

test('strict response validation rejects secret fields, invalid state, scope, dates and counters', () => {
  expect(validNotifications(status(), access)).toBe(true);
  for (const changes of [{ secret: 'private' }, { revision: true }, { revision: 2147483648 }, { can_manage: false },
    { project: { ...project, project_id: 'other' } }, { has_more: 'false' }, { updated_at: '2026-02-30T10:00:00Z' },
    { destination: { ...status().destination, webhook_url: 'private' } }, { destination: { ...status().destination, enabled: true } },
    { worker: { status: 'healthy', last_seen_at: null } }, { deliveries: Array(51).fill(delivery()) }, { deliveries: [delivery(), delivery()] }]) {
    expect(validNotifications(status(changes), access)).toBe(false);
  }
  for (const changes of [{ id: 'private' }, { state: 'complete' }, { cycle: 0 }, { attempt_count: 16 }, { can_retry: true },
    { incident_id: 'wrong' }, { last_outcome: 'private\n' }, { created_at: '2026-09-12T10:00:00' },
    { attempts: [{ number: 1, started_at: now, finished_at: now, outcome: 'accepted', payload: 'private' }] }]) expect(validDelivery(delivery(changes))).toBe(false);
  expect(validNotifications(status({ can_manage: false, project: null }), { auth_mode: 'unknown' })).toBe(false);
});
