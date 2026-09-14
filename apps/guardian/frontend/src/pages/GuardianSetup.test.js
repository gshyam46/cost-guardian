import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { MemoryRouter } from 'react-router-dom';
import GuardianSetup from './GuardianSetup';
import { GuardianAccessContext } from '@/contexts/GuardianAccess';
import guardianApi from '@/services/guardianApi';

jest.mock('./GuardianLayout', () => ({ children }) => <main>{children}</main>);
jest.mock('@/services/guardianApi', () => ({ __esModule: true, default: { getMonitoring: jest.fn(), getCapture: jest.fn(), getMonitoringPolicy: jest.fn(), getNotifications: jest.fn() } }));

const monitoring = (changes = {}) => ({
  source_configured: true, healthy: true, stale: false, status: 'complete', read_status: 'complete',
  source_watermark: '2026-09-11T10:00:00Z', processing_watermark: '2026-09-11T09:59:00Z',
  source_fetched_at: '2026-09-11T10:00:01Z', last_attempt_at: '2026-09-11T09:59:30Z',
  records_read: 7, pages_fetched: 1, pending_observations: 0, dirty_buckets: 0, quarantined_records: 0,
  ...changes,
});
let container;
let root;
const render = async () => act(async () => root.render(<GuardianAccessContext.Provider value={{ auth_mode: 'api_key', permissions: ['read', 'resolve_incidents'] }}>
  <MemoryRouter><GuardianSetup /></MemoryRouter></GuardianAccessContext.Provider>));
const detail = (label) => [...container.querySelectorAll('dt')].find((node) => node.textContent === label)?.nextElementSibling.textContent;
const retry = async () => act(async () => container.querySelector('button').click());

beforeEach(() => {
  jest.clearAllMocks();
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
  guardianApi.getMonitoring.mockResolvedValue({ data: monitoring() });
  guardianApi.getNotifications.mockResolvedValue({ data: { schema_version: 1, revision: 0, project: null, can_manage: false, updated_at: null,
    destination: { channel: 'slack', state: 'not_configured', verified: false, enabled: false }, worker: { status: 'unknown', last_seen_at: null }, deliveries: [], has_more: false } });
  guardianApi.getMonitoringPolicy.mockResolvedValue({ data: { schema_version: 1, revision: 0, updated_at: null, updated_by: null,
    project: null, can_manage: false, rules: { max_call_cost_usd: null, max_call_latency_ms: null, alert_on_errors: true } } });
  guardianApi.getCapture.mockResolvedValue({ data: { mode: 'langfuse', enabled: false, schema_version: 1,
    collector_path: '/api/guardian/ingest/events', can_manage_keys: false, project: null, status: null,
    limits: { max_batch_events: 100, max_body_bytes: 262144, max_active_keys: 10, max_keys: 100 } } });
});
afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
});

test('unconfigured setup is read-only and explains the current instrumentation boundary', async () => {
  guardianApi.getMonitoring.mockResolvedValue({ data: monitoring({ source_configured: false, status: 'not_configured', read_status: null,
    stale: true, last_attempt_at: null, source_watermark: null, processing_watermark: null }) });
  await render();
  expect(container.textContent).toContain('Not configured');
  expect(container.textContent).toContain('source modes cannot be switched here');
  expect(container.textContent).toContain('Do not enter provider secrets');
  expect(container.textContent).not.toContain('Worker diagnostics are stale');
  expect(container.querySelector('input')).toBeNull();
  expect([...container.querySelectorAll('a')].map((link) => link.getAttribute('href'))).toEqual(['/live', '/', '/incidents']);
});

test('Langfuse setup explains the source path and keeps optional settings out of the first step', async () => {
  await render();
  expect(container.querySelector('h1').textContent).toBe('Connections');
  expect(container.textContent).toContain('Langfuse connection');
  expect(container.querySelectorAll('[aria-label="How Langfuse data reaches Sillage"] > li')).toHaveLength(3);
  expect(container.textContent).toContain('It does not connect your application to Langfuse');
  expect(container.querySelector('#connection-rules').open).toBe(false);
  expect(container.querySelector('#connection-notifications').open).toBe(false);
  expect(container.querySelector('#monitoring-policy-title')).not.toBeNull();
});

test('configured but unchecked never becomes verified or active monitoring', async () => {
  guardianApi.getMonitoring.mockResolvedValue({ data: monitoring({ status: 'not_polled', read_status: null, source_watermark: null,
    stale: true, last_attempt_at: null, processing_watermark: null }) });
  await render();
  expect(container.textContent).toContain('A source configuration is present. This alone does not verify');
  expect(container.textContent).toContain('No source read has been reported yet');
  expect(container.textContent).toContain('No successful source checkpoint is recorded');
  expect(container.textContent).not.toMatch(/Active|Verified source|Monitoring is healthy/);
  expect(container.textContent).not.toContain('Worker diagnostics are stale');
});

test('successful empty poll preserves historical checkpoint and does not claim never-used source', async () => {
  guardianApi.getMonitoring.mockResolvedValue({ data: monitoring({ records_read: 0 }) });
  await render();
  expect(container.textContent).toContain('The latest successful read returned no observations');
  expect(container.textContent).toContain('does not establish that the project has never had traffic');
  expect(detail('Rows read in latest poll')).toBe('0');
  expect(detail('Last source checkpoint')).toBe('2026-09-11 10:00:00.000 UTC');
});

test('partial pending work has distinct source and processing checkpoints and counts', async () => {
  guardianApi.getMonitoring.mockResolvedValue({ data: monitoring({
    healthy: false, status: 'pending', read_status: 'partial', read_error_code: 'quarantined_observations',
    pending_observations: 3, dirty_buckets: 2, quarantined_records: 1,
  }) });
  await render();
  expect(container.textContent).toContain('Partial');
  expect(container.textContent).toContain('Work pending');
  expect(container.textContent).toContain('A saved checkpoint does not make that data complete');
  expect(detail('Observations awaiting checks')).toBe('3');
  expect(detail('Hourly totals awaiting rebuild')).toBe('2');
  expect(detail('Rejected or conflicting records')).toBe('1');
  expect(detail('Last source checkpoint')).not.toBe(detail('Last processing checkpoint'));
});

test('stale diagnostics cannot imply current health even with saved complete state', async () => {
  guardianApi.getMonitoring.mockResolvedValue({ data: monitoring({ stale: true, status: 'stale' }) });
  await render();
  expect(container.querySelector('[role="status"]').textContent).toContain('Worker diagnostics are stale');
  expect(container.textContent).toContain('Saved checkpoints do not establish current monitoring health');
});

test('cold monitoring failure is recoverable without rendering exception or a zero count', async () => {
  guardianApi.getMonitoring.mockRejectedValueOnce(new Error('private-provider-secret'));
  await render();
  expect(container.querySelector('[role="alert"]').textContent).toContain('Monitoring diagnostics are unavailable');
  expect(container.textContent).not.toContain('private-provider-secret');
  expect(detail('Rows read in latest poll')).toBeUndefined();
  expect(detail('Last source checkpoint')).toBeUndefined();
  expect(container.textContent).toContain('Default monitoring rules');
  await retry();
  expect(container.querySelector('[role="alert"]')).toBeNull();
  expect(detail('Rows read in latest poll')).toBe('7');
});

test('failed refresh retains clearly labelled previous diagnostics', async () => {
  await render();
  guardianApi.getMonitoring.mockRejectedValueOnce(new Error('network unavailable'));
  await retry();
  expect(container.textContent).toContain('Showing previously fetched diagnostics. Current monitoring state is unknown');
  expect(detail('Rows read in latest poll')).toBe('7');
});

test('unknown fields and malformed numeric or date values are not fabricated or echoed', async () => {
  guardianApi.getMonitoring.mockResolvedValue({ data: {
    source_watermark: 'private-untrusted-timestamp', pending_observations: -1,
    dirty_buckets: 'private-untrusted-count', read_error_code: 'private-untrusted-reason',
  } });
  await render();
  expect(detail('Last source checkpoint')).toBe('Unknown timestamp');
  expect(detail('Observations awaiting checks')).toBe('Unknown');
  expect(detail('Hourly totals awaiting rebuild')).toBe('Unknown');
  expect(container.textContent).not.toContain('private-untrusted');
  expect(container.textContent).not.toMatch(/NaN|undefined/);
});

test.each([null, [], true])('malformed successful monitoring body %p remains unavailable', async (data) => {
  guardianApi.getMonitoring.mockResolvedValue({ data });
  await render();
  expect(container.querySelector('[role="alert"]').textContent).toContain('Monitoring diagnostics are unavailable');
  expect(detail('Rows read in latest poll')).toBeUndefined();
  expect(detail('Last source checkpoint')).toBeUndefined();
  expect(container.textContent).toContain('Default monitoring rules');
});

test('a timestamp without an explicit timezone is not presented as established UTC', async () => {
  guardianApi.getMonitoring.mockResolvedValue({ data: monitoring({ source_watermark: '2026-09-11T10:00:00' }) });
  await render();
  expect(detail('Last source checkpoint')).toBe('Unknown timestamp');
});

test('unknown prototype-like state labels cannot become React children or crash setup', async () => {
  guardianApi.getMonitoring.mockResolvedValue({ data: monitoring({
    read_status: '__proto__', status: 'constructor', read_error_code: '__proto__',
    quarantined_records: { valueOf: 'untrusted', toString: 'untrusted' },
  }) });
  await render();
  expect(container.textContent).toContain('The source check needs operator review');
  expect(detail('Rejected or conflicting records')).toBe('Unknown');
  expect(container.textContent).not.toContain('[object Object]');
});

test('the monitoring request receives a signal and unmount aborts it', async () => {
  guardianApi.getMonitoring.mockReturnValue(new Promise(() => {}));
  await render();
  const { signal } = guardianApi.getMonitoring.mock.calls[0][0];
  expect(signal.aborted).toBe(false);
  expect(container.querySelector('[role="status"]').textContent).toContain('Checking monitoring diagnostics');
  await act(async () => root.unmount());
  expect(signal.aborted).toBe(true);
});
