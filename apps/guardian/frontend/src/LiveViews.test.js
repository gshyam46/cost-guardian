import { act } from 'react';
import { createRoot } from 'react-dom/client';
import App from './App';
import guardianApi from '@/services/guardianApi';
import { count } from '@/lib/liveFormat';
import useLiveData from '@/hooks/useLiveData';
import { BarChart } from '@/pages/MiniChart';
import { RunWaterfall } from '@/components/Charts';

jest.mock('@/services/guardianApi', () => ({
  __esModule: true,
  configureAuth: jest.fn(),
  getApiKey: () => 'test-key',
  clearApiKey: jest.fn(),
  default: {
    getLive: jest.fn(), getLiveRun: jest.fn(), getOverview: jest.fn(), getMetrics: jest.fn(),
    getTrends: jest.fn(), getMonitoring: jest.fn(), getSummary: jest.fn(), getAccess: jest.fn(), getAuthConfig: jest.fn(),
  },
}));
jest.mock('@/components/ui/sonner', () => ({ Toaster: () => null }));
jest.mock('sonner', () => ({ toast: { error: jest.fn(), success: jest.fn() } }));

const coverage = (overrides = {}) => ({
  status: 'complete', scope: 'window_generations', window_start: '2026-01-01T00:00:00Z',
  window_end: '2026-01-02T00:00:00Z', observed_count: 1, records_read: 1, pages_fetched: 1,
  invalid_count: 0, duplicate_count: 0, max_records: 1000, max_pages: 10, ...overrides,
});
const summary = (overrides = {}) => ({
  window_hours: 24, call_count: 1, error_count: 0, unknown_status_count: 1,
  total_cost_usd: null, known_cost_usd: 0, cost_known_count: 0, cost_unknown_count: 1,
  total_tokens: null, known_total_tokens: 0, tokens_known_count: 0, tokens_unknown_count: 1,
  avg_latency_ms: null, p95_latency_ms: null, latency_known_count: 0, latency_unknown_count: 1,
  last_call_at: '2026-01-01T00:00:00Z', ...overrides,
});
const call = (overrides = {}) => ({
  id: 'call-1', trace_id: 'trace-1', agent_name: 'RAG answer', model: 'test-model', status: 'unknown',
  started_at: '2026-01-01T00:00:00Z', cost_usd: null, total_tokens: null,
  input_tokens: null, output_tokens: null, latency_ms: null, time_to_first_token_ms: null,
  ...overrides,
});
const snapshot = (overrides = {}) => ({
  available: true, degraded: false, stale: false, fetched_at: '2026-01-02T00:00:00Z',
  coverage: coverage(),
  stats: { ...summary(), by_agent: [{ ...summary(), name: 'RAG answer', calls: 1, errors: 0,
    cost_usd: null, tokens: null }], by_model: [] },
  calls: [call()], runs: [], ...overrides,
});
let container;
let root;
const renderAt = async (path) => {
  window.history.replaceState({}, '', path);
  await act(async () => root.render(<App />));
};
beforeEach(() => {
  jest.clearAllMocks();
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
  guardianApi.getAuthConfig.mockResolvedValue({ data: { auth_mode: 'api_key', login_path: null } });
  guardianApi.getAccess.mockResolvedValue({ data: { authenticated: true, auth_mode: 'api_key', deployment_mode: 'single_project', permissions: ['read', 'resolve_incidents'] } });
  guardianApi.getLive.mockResolvedValue({ data: snapshot() });
  guardianApi.getLiveRun.mockResolvedValue({ data: {
    ...summary(), id: 'trace-1', name: 'RAG workflow', status: 'unknown', workflow_status: 'unknown',
    started_at: '2026-01-01T00:00:00Z', cost_usd: null, latency_ms: null,
    observation_state: 'observed', window_hours: 168,
    coverage: coverage({ scope: 'trace_generations' }), calls: [call()],
  } });
  guardianApi.getOverview.mockResolvedValue({ data: { open_incidents: 0, incidents_last_7_days: 0 } });
  guardianApi.getSummary.mockResolvedValue({ data: {
    overview: { open_incidents: 0, incidents_last_7_days: 0, open_by_severity: {}, open_by_detector: {} },
    trends: [], coverage: { status: 'complete', invalid_timestamp_count: 0 },
    timezone: 'UTC', as_of: '2026-01-14T12:00:00Z',
    window_start: '2026-01-01T00:00:00Z', window_end: '2026-01-14T12:00:00Z',
  } });
  guardianApi.getMetrics.mockResolvedValue({ data: [] });
  guardianApi.getTrends.mockResolvedValue({ data: [] });
  guardianApi.getMonitoring.mockResolvedValue({ data: { healthy: true, status: 'complete' } });
});
afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
  jest.restoreAllMocks();
});

test('cold transport failure renders unavailable without crashing or claiming zero traffic', async () => {
  guardianApi.getLive.mockRejectedValue(new Error('synthetic offline'));
  await renderAt('/live');
  expect(container.textContent).toContain('Telemetry is unavailable');
  expect(container.textContent).not.toContain('No LLM calls');
  expect(container.textContent).not.toContain('$0.');
});

test('direct capture live and run views state their source and content boundary', async () => {
  guardianApi.getLive.mockResolvedValue({ data: snapshot({ source_kind: 'guardian_direct', source_api: 'direct-v1' }) });
  await renderAt('/live');
  expect(container.textContent).toContain('Completed LLM calls captured directly by Sillage');
  expect(container.textContent).not.toContain('Observed LLM generations from Langfuse');
  const response = await guardianApi.getLiveRun();
  guardianApi.getLiveRun.mockResolvedValue({ data: { ...response.data, source_kind: 'guardian_direct' } });
  await act(async () => root.unmount()); root = createRoot(container);
  await renderAt('/runs/trace-1');
  expect(container.textContent).toContain('Direct capture does not collect prompts, outputs or document content');
});

test('failed source result never renders synthetic zero statistics', async () => {
  guardianApi.getLive.mockResolvedValue({ data: snapshot({
    degraded: true, stats: null, calls: [], coverage: coverage({ status: 'failed' }),
  }) });
  await renderAt('/live');
  expect(container.textContent).toContain('Telemetry is unavailable');
  expect(container.textContent).not.toContain('Known spend');
});

test('unknown cost tokens and latency render as unknown, including chart hover detail', async () => {
  await renderAt('/live');
  expect(container.textContent).toContain('Unknown');
  expect(container.textContent).not.toContain('$0.');
  expect(container.textContent).not.toContain('NaN');
  const bar = container.querySelector('.group.cursor-default');
  await act(async () => bar.dispatchEvent(new MouseEvent('mouseover', { bubbles: true })));
  expect(container.textContent).toContain('Unknown tokens');
});

test.each([['limit_reached', 1000], ['page_limit_reached', 10]])('partial %s results distinguish the read budget from observed totals', async (reason, observed) => {
  guardianApi.getLive.mockResolvedValue({ data: snapshot({
    coverage: coverage({ status: 'partial', truncated: true, reason, records_read: observed, pages_fetched: 10 }),
    stats: { ...summary({ call_count: observed }), by_agent: [], by_model: [] },
  }) });
  await renderAt('/live');
  expect(container.textContent).toContain('Partial observation coverage');
  expect(container.textContent).toContain('not full-window totals');
  expect(container.textContent).toContain('read budget allows up to 1,000 records or 10 pages');
  expect(container.textContent).toContain(`Showing 1 of ${observed} accepted observations`);
});

test('rejected-only reads do not claim an empty successful window', async () => {
  guardianApi.getLive.mockResolvedValue({ data: snapshot({
    coverage: coverage({ status: 'partial', invalid_count: 1, reason: 'invalid_observation' }),
    stats: { ...summary({ call_count: 0, total_cost_usd: 0, cost_unknown_count: 0 }), by_agent: [], by_model: [] }, calls: [],
  }) });
  await renderAt('/live');
  expect(container.textContent).toContain('1 rejected');
  expect(container.textContent).not.toContain('No LLM calls were returned');
  expect(container.textContent).not.toContain('$0.');
});

test('stale telemetry retains its visible fetched time and warning', async () => {
  guardianApi.getLive.mockResolvedValue({ data: snapshot({ stale: true }) });
  await renderAt('/live');
  expect(container.textContent).toContain('Showing stale telemetry');
  expect(container.textContent).toContain('source data from');
});

test('switching windows hides prior-window totals until the new query resolves', async () => {
  await renderAt('/live');
  guardianApi.getLive.mockReturnValue(new Promise(() => {}));
  const button = [...container.querySelectorAll('button')].find((node) => node.textContent === '1h');
  await act(async () => button.click());
  expect(container.textContent).toContain('Loading the selected window');
  expect(container.textContent).not.toContain('Known spend');
});

test('run detail preserves unknown values and never infers workflow success', async () => {
  await renderAt('/runs/trace-1');
  expect(container.textContent).toContain('Workflow outcome unknown');
  expect(container.textContent).not.toContain('all calls succeeded');
  expect(container.textContent).not.toContain('$0.');
  const callButton = [...container.querySelectorAll('button')].find((node) => node.textContent.includes('RAG answer'));
  await act(async () => callButton.click());
  expect(container.textContent).toContain('Unknown / Unknown');
  expect(container.textContent).not.toContain('NaN');
  expect(container.textContent).toContain('First observed call:');
  expect(container.textContent).toContain('Query window: last 168 hours');
  expect(container.textContent).toContain('Source retention may shorten accessible history');
});

test.each(['unknown', undefined, null])('run detail labels call outcome %j before expansion without relabeling success or failure', async (status) => {
  const response = await guardianApi.getLiveRun();
  const unknownCall = call({ id: 'unknown-call', agent_name: 'Planner', status });
  if (status === undefined) delete unknownCall.status;
  guardianApi.getLiveRun.mockResolvedValue({ data: {
    ...response.data, source_kind: 'guardian_direct', call_count: 3, error_count: 1,
    calls: [unknownCall, call({ id: 'success-call', agent_name: 'Answer', status: 'success' }),
      call({ id: 'failed-call', agent_name: 'Reviewer', status: 'error' })],
  } });
  await renderAt('/runs/trace-1');
  const rows = [...container.querySelectorAll('.cg-call-row')];
  const unknownRow = rows.find((node) => node.textContent.includes('Planner'));
  const successRow = rows.find((node) => node.textContent.includes('Answer'));
  const failedRow = rows.find((node) => node.textContent.includes('Reviewer'));
  expect(unknownRow.textContent).toContain('Outcome unknown');
  expect(unknownRow.getAttribute('aria-expanded')).toBe('false');
  expect(successRow.textContent).not.toContain('Outcome unknown');
  expect(successRow.textContent).not.toContain('failed');
  expect(failedRow.textContent).toContain('failed');
  expect(failedRow.textContent).not.toContain('Outcome unknown');
  await act(async () => unknownRow.click());
  expect(unknownRow.getAttribute('aria-expanded')).toBe('true');
  expect(unknownRow.textContent).toContain('Outcome unknown');
});

test.each(['guardian_direct', 'langfuse'])('run detail shows existing %s parent references without creating a workflow tree', async (source) => {
  const response = await guardianApi.getLiveRun();
  guardianApi.getLiveRun.mockResolvedValue({ data: {
    ...response.data, source_kind: source, call_count: 2,
    calls: [call({ id: 'parent-call', agent_name: 'Planner' }),
      call({ id: 'child-call', agent_name: 'Answer', parent_observation_id: 'parent-call' })],
  } });
  await renderAt('/runs/trace-1');
  const child = [...container.querySelectorAll('button')].find((node) => node.textContent.includes('Answer'));
  await act(async () => child.click());
  expect(container.textContent).toContain('Parent observation ID: parent-call');
  expect(container.textContent).toContain('Parent is present among captured calls.');
  expect(container.textContent).not.toContain('Parent not present');
  expect(container.textContent).toContain('Workflow outcome unknown');
  expect(container.querySelectorAll('.cg-call-row')).toHaveLength(2);
});

test('uncollected framework parent remains a reference and does not become a counted call', async () => {
  const response = await guardianApi.getLiveRun();
  guardianApi.getLiveRun.mockResolvedValue({ data: {
    ...response.data, source_kind: 'guardian_direct',
    coverage: coverage({ status: 'partial', truncated: true, reason: 'limit_reached' }),
    calls: [call({ parent_observation_id: '00000000000000a1' })],
  } });
  await renderAt('/runs/trace-1');
  await act(async () => container.querySelector('.cg-call-row').click());
  expect(container.textContent).toContain('Parent observation ID: 00000000000000a1');
  expect(container.textContent).toContain('Parent not present among captured calls. It may be a framework span or outside this query.');
  expect(container.textContent).toContain('Partial observation coverage');
  expect(container.textContent).toContain('Workflow outcome unknown');
  expect(container.querySelectorAll('.cg-call-row')).toHaveLength(1);
});

test.each([undefined, null, '', 'call-1', 'invalid parent', 'parent\n', 'p'.repeat(129), '\u00e9', { id: 'parent' }])(
  'missing or invalid parent %j does not create a parent or assert a root', async (parent) => {
    const response = await guardianApi.getLiveRun();
    guardianApi.getLiveRun.mockResolvedValue({ data: {
      ...response.data, calls: [call({ parent_observation_id: parent })],
    } });
    await renderAt('/runs/trace-1');
    await act(async () => container.querySelector('.cg-call-row').click());
    expect(container.textContent).not.toContain('Parent observation ID:');
    expect(container.textContent).not.toContain('Root span');
    expect(container.textContent).toContain('Observation ID: call-1');
    expect(container.textContent).toContain('Workflow outcome unknown');
  },
);

test.each([404, 503])('run source HTTP %i never establishes trace absence', async (status) => {
  guardianApi.getLiveRun.mockRejectedValue({ response: { status } });
  await renderAt('/runs/trace-1');
  expect(container.textContent).toContain('unavailable');
  expect(container.textContent).not.toContain('not found');
});

test.each([
  ['not_observed', 'complete', 'No generation calls observed in this query window'],
  ['undetermined', 'partial', 'Trace existence remains undetermined'],
])('bounded empty run %s has no spend claim or inferred workflow facts', async (state, status, wording) => {
  guardianApi.getLiveRun.mockResolvedValue({ data: {
    ...summary({ call_count: 0 }), id: 'trace-1', name: 'Trace trace-1',
    observation_state: state, window_hours: 168, calls: [],
    coverage: coverage({ scope: 'trace_generations', status }),
  } });
  await renderAt('/runs/trace-1');
  expect(container.textContent).toContain(wording);
  expect(container.textContent).toContain('Query window: last 168 hours');
  expect(container.textContent).not.toContain('Known observed cost');
  expect(container.textContent).not.toContain('no errors observed');
  expect(container.textContent).not.toContain('$0.');
  expect(container.textContent).not.toContain('not found');
});

test('overview flags legacy accounting and stalled monitoring without inventing known cost', async () => {
  guardianApi.getMetrics.mockResolvedValue({ data: [{
    hour: '2026-01-01T00:00:00Z', agent_name: 'RAG answer', call_count: 3, error_count: 0,
    total_cost_usd: 99, avg_latency_ms: 100, coverage_status: 'legacy',
  }] });
  guardianApi.getMonitoring.mockResolvedValue({ data: {
    healthy: false, stale: true, status: 'stale', last_successful_checkpoint: '2026-01-01T00:00:00Z',
  } });
  await renderAt('/');
  expect(container.textContent).toContain('Hourly accounting is provisional');
  expect(container.textContent).toContain('legacy rollups');
  expect(container.textContent).toContain('Ingestion needs attention');
  expect(container.textContent).toContain('2026-01-01T00:00:00Z');
  expect(container.textContent).not.toContain('$99');
  expect(container.textContent).toContain('Unknown');
});

test('overview latency weights only measured calls and tolerates independent monitoring failure', async () => {
  guardianApi.getMetrics.mockResolvedValue({ data: [1, 9].map((measured, index) => ({
    hour: '2026-01-01T00:00:00Z', agent_name: 'agent-' + index, call_count: 10, error_count: 0,
    total_cost_usd: 0, known_cost_usd: 0, cost_known_count: 10, cost_unknown_count: 0,
    coverage_status: 'known', avg_latency_ms: index ? 300 : 100,
    latency_known_count: measured, latency_unknown_count: 10 - measured,
  })) });
  guardianApi.getMonitoring.mockRejectedValue(new Error('synthetic health failure'));
  await renderAt('/');
  expect(container.textContent).toContain('Worker monitoring is unavailable');
  expect(container.textContent).toContain('280ms');
  expect(container.textContent).toContain('20 recorded calls');
});

test('ledger overview explains captured scope and durable processing gaps', async () => {
  guardianApi.getMetrics.mockResolvedValue({ data: [{
    hour: '2026-01-01T00:00:00Z', agent_name: 'agent', call_count: 2, error_count: 0,
    accounting_status: 'ledger-1', coverage_status: 'known', known_cost_usd: 2,
    total_cost_usd: null, cost_known_count: 1, cost_unknown_count: 1,
    avg_latency_ms: 100, latency_known_count: 1, latency_unknown_count: 1,
  }] });
  guardianApi.getMonitoring.mockResolvedValue({ data: {
    healthy: false, stale: false, status: 'pending', pending_observations: 3,
    dirty_buckets: 1, quarantined_records: 2,
  } });
  await renderAt('/');
  expect(container.textContent).toContain('Hourly totals count captured observations once');
  expect(container.textContent).toContain('rolling 24-hour window');
  expect(container.textContent).toContain('3 observations await checks');
  expect(container.textContent).toContain('2 rejected or conflicting records need review');
  expect(container.textContent).not.toContain('Hourly accounting is provisional');
});

test('cold overview failure renders unavailable rather than empty accounting', async () => {
  guardianApi.getMetrics.mockRejectedValue(new Error('synthetic API failure'));
  await renderAt('/');
  expect(container.textContent).toContain('Traffic and cost totals are unavailable');
  expect(container.textContent).not.toContain('No telemetry yet');
});

test('overview consumes one combined summary and labels UTC calendar windows', async () => {
  await renderAt('/');
  expect(guardianApi.getSummary).toHaveBeenCalledTimes(1);
  expect(guardianApi.getSummary).toHaveBeenCalledWith(14, { signal: expect.any(AbortSignal) });
  expect(guardianApi.getOverview).not.toHaveBeenCalled();
  expect(guardianApi.getTrends).not.toHaveBeenCalled();
  expect(container.textContent).toContain('7 UTC calendar days, including today');
  expect(container.textContent).toContain('Last 14 UTC calendar days, including today (partial).');
  expect(container.textContent).toContain('Chart dates and hours are UTC; the current hour and today are partial.');
});

test('summary failure cannot become zero incidents or an empty trend', async () => {
  guardianApi.getSummary.mockRejectedValue(new Error('synthetic unavailable summary'));
  await renderAt('/');
  expect(container.textContent).toContain('Could not load Sillage data.');
  expect(container.textContent).not.toContain('Open incidents');
  expect(container.textContent).not.toContain('No incident data yet');
});

test('invalid timestamps preserve open counts but mark recent counts and trends incomplete', async () => {
  guardianApi.getSummary.mockResolvedValue({ data: {
    overview: { open_incidents: 4, incidents_last_7_days: 0, open_by_severity: {}, open_by_detector: {} },
    trends: [{ date: '2026-01-14', count: 0 }],
    coverage: { status: 'partial', invalid_timestamp_count: 2 }, timezone: 'UTC',
  } });
  await renderAt('/');
  expect(container.textContent).toContain('2 incidents have invalid timestamps.');
  expect(container.textContent).toContain('Open counts remain available; recent counts and daily trends are incomplete.');
  const label = [...container.querySelectorAll('p')].find((node) => node.textContent === 'Open incidents');
  expect(label.parentElement.textContent).toContain('4');
  expect(label.parentElement.textContent).toContain('Recent incident count incomplete');
  expect(container.textContent).not.toContain('0 in the last 7');
});

test('all-zero daily chart reports a zero peak without dividing by zero', async () => {
  await act(async () => root.render(<BarChart points={[
    { label: '01-13', value: 0 }, { label: '01-14', value: 0 },
  ]} label="incident" />));
  expect(container.textContent).toContain('peak 0');
  expect(container.textContent).not.toContain('peak 1');
  expect(container.innerHTML).not.toMatch(/NaN|Infinity/);
});

test('known-count overflow rollups cannot render as free', async () => {
  guardianApi.getMetrics.mockResolvedValue({ data: [{
    hour: '2026-01-01T00:00:00Z', agent_name: 'agent', call_count: 2, error_count: 0,
    coverage_status: 'known', cost_known_count: 2, cost_unknown_count: 0,
    total_cost_usd: null, known_cost_usd: null, avg_latency_ms: null,
    latency_known_count: 2, latency_unknown_count: 0, aggregate_issues: ['cost_total_out_of_range'],
  }] });
  await renderAt('/');
  expect(container.textContent).toContain('Some numeric aggregates are unavailable');
  expect(container.textContent).not.toContain('$0.');
  expect(container.textContent).not.toContain('NaN');
});

test('numeric display does not silently round unsafe integer token counts', () => {
  expect(count(Number.MAX_SAFE_INTEGER + 1)).toBe('Out of display range');
  expect(count(0)).toBe('0');
  expect(count(null)).toBe('Unknown');
});

test('checkpoint outside the query window explains required backfill', async () => {
  guardianApi.getMonitoring.mockResolvedValue({ data: {
    healthy: false, status: 'read_blocked', read_error_code: 'checkpoint_outside_window',
  } });
  await renderAt('/');
  expect(container.textContent).toContain('Historical backfill is required');
});

test.each(['resolve', 'reject'])('late query %s cannot replace or invalidate a newer result', async (settlement) => {
  const deferred = () => {
    let resolve;
    let reject;
    const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
    return { promise, resolve, reject };
  };
  const first = deferred();
  const second = deferred();
  const requests = [];
  const Probe = ({ query }) => {
    const state = useLiveData(({ signal }) => {
      requests.push({ query, signal });
      return query === 'first' ? first.promise : second.promise;
    }, { refetchKey: query });
    return <p>{state.data || 'loading'}:{state.error ? 'failed' : 'ok'}</p>;
  };
  await act(async () => root.render(<Probe query="first" />));
  await act(async () => root.render(<Probe query="second" />));
  expect(requests[0].signal.aborted).toBe(true);
  await act(async () => second.resolve('new-query-data'));
  await act(async () => first[settlement](settlement === 'resolve' ? 'old-query-data' : new Error('old failure')));
  expect(container.textContent).toBe('new-query-data:ok');
});

test('polling does not overlap an unresolved request for the same query', async () => {
  jest.spyOn(document, 'visibilityState', 'get').mockReturnValue('visible');
  guardianApi.getLive.mockReturnValue(new Promise(() => {}));
  await renderAt('/live');
  await act(async () => {
    for (let index = 0; index < 5; index += 1) document.dispatchEvent(new Event('visibilitychange'));
  });
  expect(guardianApi.getLive).toHaveBeenCalledTimes(1);
});

test('a complete empty refresh replaces cached observations without claiming trace deletion', async () => {
  jest.spyOn(document, 'visibilityState', 'get').mockReturnValue('visible');
  await renderAt('/runs/trace-1');
  expect(container.textContent).toContain('RAG workflow');
  guardianApi.getLiveRun.mockResolvedValue({ data: {
    ...summary({ call_count: 0 }), id: 'trace-1', name: 'Trace trace-1',
    observation_state: 'not_observed', window_hours: 168, calls: [],
    coverage: coverage({ scope: 'trace_generations' }),
  } });
  await act(async () => document.dispatchEvent(new Event('visibilitychange')));
  expect(container.textContent).toContain('No generation calls observed in this query window');
  expect(container.textContent).not.toContain('not found');
  expect(container.textContent).not.toContain('RAG workflow');
  expect(container.textContent).not.toContain('Showing stale trace data');
});

test('overview shows source calls before hourly history exists and explains the different windows', async () => {
  guardianApi.getLive.mockResolvedValue({ data: snapshot({ source_kind: 'guardian_direct', stats: {
    ...summary({ call_count: 2, total_tokens: 120, tokens_known_count: 2, tokens_unknown_count: 0 }), by_agent: [], by_model: [],
  } }) });
  await renderAt('/');
  expect(guardianApi.getLive).toHaveBeenCalledWith(24, 5, 8, { signal: expect.any(AbortSignal) });
  expect(container.textContent).toContain('Captured calls (24h)');
  expect(container.textContent).toContain('120');
  expect(container.textContent).toContain('Calls are visible in source activity above');
  expect(container.textContent).toContain('Worker-processed accounting covers 48 hours');
  expect(container.textContent).not.toContain('No telemetry yet');
  expect(container.textContent).not.toContain('Hourly accounting is provisional');
});

test('overview source evidence survives a separate hourly summary failure', async () => {
  guardianApi.getSummary.mockRejectedValue(new Error('summary unavailable'));
  await renderAt('/');
  expect(container.textContent).toContain('Captured calls (24h)');
  expect(container.textContent).toContain('Could not load Sillage data');
  expect(container.textContent).not.toContain('Source activity is unavailable');
});

test('overview distinguishes an unavailable source from empty successful history', async () => {
  guardianApi.getLive.mockRejectedValue(new Error('source unavailable'));
  await renderAt('/');
  expect(container.textContent).toContain('Source activity is unavailable');
  expect(container.textContent).not.toContain('Captured calls (24h)');
  expect(container.textContent).not.toContain('Connect one real application call');
});

test('overview retains stale partial source evidence with missing usage kept unknown', async () => {
  guardianApi.getLive.mockResolvedValue({ data: snapshot({ stale: true,
    coverage: coverage({ status: 'partial', truncated: true }),
  }) });
  await renderAt('/');
  const source = container.querySelector('section[aria-label="Source activity"]');
  expect(source.textContent).toContain('Showing stale source activity');
  expect(source.textContent).toContain('not full-window totals');
  expect(source.textContent).toContain('query reached its read limit');
  expect(source.textContent).toContain('Unknown');
  expect(source.textContent).not.toContain('$0.');
});

test('direct monitoring uses nested receipt and worker facts rather than the legacy healthy false flag', async () => {
  guardianApi.getMonitoring.mockResolvedValue({ data: {
    source_kind: 'guardian_direct', healthy: false, status: 'direct_capture', capture: {
      worker_status: 'current', received_events: 2, processed_events: 2, pending_events: 0, conflicted_events: 0,
      last_processed_at: '2026-01-01T12:00:00Z',
    },
  } });
  await renderAt('/');
  expect(container.textContent).toContain('2 production events received');
  expect(container.textContent).toContain('Recent worker heartbeat');
  expect(container.textContent).not.toContain('Ingestion needs attention');
  expect(container.textContent).not.toContain('Monitoring active');
});

test('direct pending receipts and a test-only connection explain why production data is empty', async () => {
  guardianApi.getLive.mockResolvedValue({ data: snapshot({ source_kind: 'guardian_direct',
    stats: { ...summary({ call_count: 0 }), by_agent: [], by_model: [] }, calls: [],
    coverage: coverage({ status: 'partial', pending_events: 1, reason: 'capture_pending' }),
  }) });
  guardianApi.getMonitoring.mockResolvedValue({ data: { source_kind: 'guardian_direct', healthy: false, capture: {
    worker_status: 'stale', received_events: 0, processed_events: 0, pending_events: 1, conflicted_events: 0,
    last_test_received_at: '2026-01-01T12:00:00Z',
  } } });
  await renderAt('/');
  expect(container.textContent).toContain('Your received events are being processed');
  expect(container.textContent).toContain('worker heartbeat is stale');
  expect(container.textContent).toContain('A test receipt arrived');
  expect(container.textContent).not.toContain('Captured calls (24h)');
});

test('feed search filters displayed rows without changing source totals and links observations to traces', async () => {
  guardianApi.getLive.mockResolvedValue({ data: snapshot({ calls: [call({ model: 'matching-model' }), call({ id: 'call-2', model: 'other-model' })],
    stats: { ...summary({ call_count: 2, total_tokens: 120, tokens_known_count: 2 }), by_agent: [], by_model: [{
      ...summary(), name: 'matching-model', calls: 1, errors: 0, tokens: null,
    }] },
  }) });
  await renderAt('/live');
  expect(container.textContent).toContain('Observed tokens');
  expect(container.textContent).toContain('Model usage');
  const input = container.querySelector('input[aria-label="Search displayed calls"]');
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(input, 'matching-model');
    input.dispatchEvent(new Event('input', { bubbles: true }));
  });
  expect(container.textContent).toContain('1 matching displayed calls. Window summaries are unchanged');
  expect(container.textContent).not.toContain('other-model');
  expect(container.querySelector('a[href="/runs/trace-1"]')).not.toBeNull();
});

test('failed calls preserve measured duration in the row, expansion and timeline', async () => {
  const response = await guardianApi.getLiveRun();
  guardianApi.getLiveRun.mockResolvedValue({ data: { ...response.data, error_count: 1,
    calls: [call({ status: 'error', latency_ms: 250, total_tokens: 12, input_tokens: 10, output_tokens: 2 })],
  } });
  await renderAt('/runs/trace-1');
  const callButton = [...container.querySelectorAll('button')].find((node) => node.textContent.includes('RAG answer'));
  expect(callButton.textContent).toContain('250ms');
  await act(async () => callButton.click());
  expect(callButton.getAttribute('aria-expanded')).toBe('true');
  expect(container.textContent.match(/250ms/g).length).toBeGreaterThanOrEqual(3);
  expect(container.textContent).not.toContain('--');
});

test('zero-duration timeline uses a visible marker while retaining its measured zero span', async () => {
  await act(async () => root.render(<RunWaterfall names={['RAG answer']} calls={[call({ latency_ms: 0 })]} />));
  expect(container.textContent).toContain('0ms');
  expect(container.textContent).not.toContain('1ms');
  expect(container.textContent).not.toContain('0.0s');
  expect(container.innerHTML).not.toMatch(/NaN|Infinity/);
  expect(container.querySelector('[aria-label="RAG answer: 0ms"]')).not.toBeNull();
});
