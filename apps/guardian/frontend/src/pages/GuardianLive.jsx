import { useCallback, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Activity, AlertTriangle, DollarSign, Timer, ChevronRight, Layers, Search } from 'lucide-react';
import GuardianLayout from './GuardianLayout';
import { BarList, LatencyScatter, STATUS, colorFor } from '@/components/Charts';
import guardianApi from '@/services/guardianApi';
import useLiveData from '@/hooks/useLiveData';
import { isKnown, money, duration, count, observedCost } from '@/lib/liveFormat';

const WINDOWS = [
  { hours: 1, label: '1h' }, { hours: 6, label: '6h' },
  { hours: 24, label: '24h' }, { hours: 168, label: '7d' },
];
const ago = (iso) => {
  if (!iso) return 'unknown time';
  const seconds = Math.max(0, Math.floor((Date.now() - new Date(iso).getTime()) / 1000));
  if (!Number.isFinite(seconds)) return 'unknown time';
  if (seconds < 60) return `${seconds}s ago`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  return `${Math.floor(seconds / 3600)}h ago`;
};
const Stat = ({ icon: Icon, label, value, sub }) => (
  <Card><CardContent className="pt-5 pb-4">
    <div className="flex items-start justify-between">
      <div><p className="text-xs text-ink-500 uppercase tracking-wide">{label}</p>
        <p className="text-2xl font-semibold text-ink-900 mt-1 tabular-nums">{value}</p>
        {sub && <p className="text-xs text-ink-500 mt-1">{sub}</p>}
      </div><Icon className="h-4 w-4 text-ink-300 shrink-0" />
    </div>
  </CardContent></Card>
);
const StatusDot = ({ status }) => (
  <span title={status === 'error' ? 'Observed error' : status === 'success' ? 'Observation completed' : 'Outcome unknown'}
    className="inline-block h-2 w-2 rounded-full shrink-0"
    style={{ backgroundColor: status === 'error' ? STATUS.critical : status === 'success' ? STATUS.good : 'var(--sillage-muted)' }} />
);
const Notice = ({ children }) => (
  <Card className="mb-5 border-ochre-200 bg-ochre-50">
    <CardContent className="py-3"><div role="status" className="text-sm text-ochre-900">{children}</div></CardContent>
  </Card>
);

const GuardianLive = () => {
  const navigate = useNavigate();
  const [hours, setHours] = useState(24);
  const [search, setSearch] = useState('');
  const fetchAll = useCallback(async ({ signal } = {}) => (await guardianApi.getLive(hours, 8, 60, { signal })).data, [hours]);
  const { data, loading, refreshing, error, lastUpdated } = useLiveData(fetchAll, {
    intervalMs: 12000, refetchKey: hours,
  });
  const stats = data?.stats;
  const coverage = data?.coverage;
  const calls = data?.calls ?? [];
  const runs = data?.runs ?? [];
  const changingWindow = stats && stats.window_hours !== hours;
  const failed = !data || data.degraded || !stats;
  const incomplete = coverage?.status !== 'complete';
  const stale = data?.stale || (error && data);
  const agentNames = (stats?.by_agent ?? []).map((a) => a.name);
  const knownStatuses = stats ? stats.call_count - (stats.unknown_status_count || 0) : 0;
  const errorRate = knownStatuses ? `${((stats.error_count / knownStatuses) * 100).toFixed(1)}%` : 'Unknown';
  const filteredCalls = calls.filter((call) => [call.agent_name, call.model, call.trace_id, call.status]
    .some((value) => String(value || '').toLowerCase().includes(search.trim().toLowerCase())));
  const tokens = isKnown(stats?.total_tokens) ? count(stats.total_tokens)
    : stats?.tokens_known_count > 0 ? `${count(stats.known_total_tokens)} known` : 'Unknown';

  if (loading) return <GuardianLayout><p>{data ? 'Loading the selected window. Previous-window values are hidden.'
    : 'Loading live telemetry...'}</p></GuardianLayout>;
  return (
    <GuardianLayout refreshing={refreshing} lastUpdated={lastUpdated}>
      <div className="flex flex-wrap items-center justify-between mb-5 gap-3">
        <div><h2 className="cg-page-title text-xl font-semibold text-ink-900">Live activity</h2>
          <p className="text-sm text-ink-500">{!data ? 'Captured LLM usage, timing and errors'
            : data.source_kind === 'guardian_direct' ? 'Completed LLM calls captured directly by Sillage' : 'Observed LLM generations from Langfuse'}
            {data?.fetched_at && <> — source data from {ago(data.fetched_at)}</>}
          </p>
        </div>
        <div className="flex gap-1">{WINDOWS.map((w) => (
          <Button key={w.hours} size="sm" variant={hours === w.hours ? 'default' : 'outline'}
            onClick={() => setHours(w.hours)}>{w.label}</Button>
        ))}</div>
      </div>
      {data?.available === false ? (
        <Notice><strong>Sillage cannot see your telemetry.</strong> {data.reason} <Link className="underline" to="/setup">Check connection</Link>.</Notice>
      ) : changingWindow ? (
        <Notice>Loading the selected window. Previous-window values are hidden.</Notice>
      ) : failed ? (
        <Notice><strong>Telemetry is unavailable.</strong> {data?.reason || 'Sillage could not read telemetry. Refresh to try again.'}
          {' '}No traffic or spend total can be established from this read.
        </Notice>
      ) : (
        <>
          <div className="flex flex-wrap items-center justify-between gap-3 text-xs text-ink-500 mb-5">
            <p>{data.source_kind === 'guardian_direct'
              ? 'Application → Sillage collector → worker → captured observations. Test receipts are excluded.'
              : 'Application → Langfuse project → Sillage source query. Hourly history and incident checks run separately.'}</p>
            <Link to="/setup" className="font-medium text-brick-800 underline">Manage connection</Link>
          </div>
          {stale && <Notice><strong>Showing stale telemetry.</strong> The latest refresh failed.
            These observations were fetched {ago(data.fetched_at)}.</Notice>}
          {incomplete && <Notice><strong>Partial observation coverage.</strong> These are observed results, not full-window totals.
            {' '}{count(coverage?.records_read)} records read across {count(coverage?.pages_fetched)} pages.
            {' '}{count(coverage?.invalid_count)} rejected; {count(coverage?.duplicate_count)} repeated.
            {coverage?.truncated && <> The read budget allows up to {count(coverage.max_records)} records or {count(coverage.max_pages)} pages.</>}
            {coverage?.reason && <> Read status: {coverage.reason}.</>}
          </Notice>}
          {stats.aggregate_issues?.length > 0 && <Notice>Some aggregate amounts exceed the supported numeric range and are shown as unknown.
            {' '}{stats.aggregate_issues.join(', ')}.</Notice>}
          {coverage?.status === 'complete' && <p className="text-xs text-ink-500 mb-4">
            Source query complete for {coverage.window_start} to {coverage.window_end}. Source retention may shorten accessible history; delayed telemetry may still arrive.
          </p>}
          {stats.call_count === 0 && !incomplete ? (
            <Card><CardContent className="py-10 text-center">
              <Activity className="h-6 w-6 text-ink-300 mx-auto mb-3" />
              <p>No LLM calls were returned for this source window.</p>
              <p className="text-sm text-ink-500">This describes the completed query; it does not establish that instrumentation is working.</p>
              <Link className="inline-flex text-sm text-brick-800 underline mt-4" to="/setup">Connect your app and verify a real call</Link>
            </CardContent></Card>
          ) : (
            <>
              <div className="grid grid-cols-2 xl:grid-cols-5 gap-3 mb-5">
                <Stat icon={Activity} label="Observed calls" value={count(stats.call_count)}
                  sub={stats.last_call_at ? `last ${ago(stats.last_call_at)}` : 'No accepted observations'} />
                <Stat icon={Layers} label="Observed tokens" value={tokens}
                  sub={`${count(stats.tokens_known_count)} calls with usage; ${count(stats.tokens_unknown_count)} missing`} />
                <Stat icon={AlertTriangle} label="Observed error rate" value={errorRate}
                  sub={`${count(stats.error_count)} errors / ${count(knownStatuses)} known outcomes; ${count(stats.unknown_status_count || 0)} unknown`} />
                <Stat icon={DollarSign} label="Known spend"
                  value={incomplete && stats.cost_known_count === 0 ? 'Unknown'
                    : observedCost(stats.total_cost_usd, stats.known_cost_usd, stats.cost_known_count)}
                  sub={`${count(stats.cost_unknown_count)} calls missing cost; ${count(stats.tokens_unknown_count)} missing token totals`} />
                <Stat icon={Timer} label="p95 observed latency" value={duration(stats.p95_latency_ms)}
                  sub={`${count(stats.latency_known_count)} measured; avg ${duration(stats.avg_latency_ms)}`} />
              </div>
              {(stats.by_model || []).length > 0 && <Card className="mb-5"><CardHeader className="pb-3">
                <CardTitle className="text-base">Model usage</CardTitle>
                <CardDescription>Compare accepted observations by model across the selected window.</CardDescription>
              </CardHeader><CardContent className="p-0 overflow-x-auto">
                <table className="w-full text-sm"><thead className="text-xs text-ink-500 border-t bg-ink-50/50">
                  <tr><th className="text-left px-6 py-3 font-medium">Model</th><th className="text-right p-3 font-medium">Calls</th>
                    <th className="text-right p-3 font-medium">Tokens</th><th className="text-right p-3 font-medium">Errors</th>
                    <th className="text-right p-3 font-medium">Avg latency</th><th className="text-right px-6 py-3 font-medium">Known cost</th></tr>
                </thead><tbody>{stats.by_model.map((model) => <tr key={model.name} className="border-t">
                  <td className="px-6 py-3 font-medium">{model.name}</td><td className="text-right p-3 tabular-nums">{count(model.calls)}</td>
                  <td className="text-right p-3 tabular-nums">{isKnown(model.tokens) ? count(model.tokens)
                    : model.tokens_known_count > 0 ? `${count(model.known_total_tokens)} known` : 'Unknown'}</td>
                  <td className="text-right p-3 tabular-nums">{count(model.errors)}</td><td className="text-right p-3 tabular-nums">{duration(model.avg_latency_ms)}</td>
                  <td className="text-right px-6 py-3 tabular-nums">{observedCost(model.cost_usd, model.known_cost_usd, model.cost_known_count)}</td>
                </tr>)}</tbody></table>
              </CardContent></Card>}
              <Card className="mb-5"><CardHeader className="pb-2">
                <CardTitle className="text-base">Latency per call</CardTitle>
                <CardDescription>Displayed feed only: {calls.length} of {stats.call_count} accepted observations.
                  Missing durations are not plotted.</CardDescription>
              </CardHeader><CardContent><LatencyScatter calls={calls} names={agentNames} /></CardContent></Card>
              <div className="grid lg:grid-cols-2 gap-5 mb-5">
                <Card><CardHeader className="pb-3"><CardTitle className="text-base">Known spend by agent</CardTitle>
                  <CardDescription>Known subtotals across accepted observations; unpriced calls are excluded.</CardDescription>
                </CardHeader><CardContent><BarList
                  rows={stats.by_agent.map((row) => ({ ...row, chart_cost: row.cost_known_count > 0 ? row.known_cost_usd : null }))}
                  valueKey="chart_cost" format={money} label="known agent cost" names={agentNames} />
                </CardContent></Card>
                <Card><CardHeader className="pb-3"><CardTitle className="text-base">Observed latency by agent</CardTitle>
                  <CardDescription>Averages use measured durations only.</CardDescription>
                </CardHeader><CardContent><BarList rows={stats.by_agent} valueKey="avg_latency_ms"
                  format={duration} label="agent latency" names={agentNames} />
                </CardContent></Card>
              </div>
              <Card className="mb-5"><CardHeader className="pb-3">
                <CardTitle className="text-base">Recent traces</CardTitle>
                <CardDescription>Traces with observed generation calls in the selected window. Counts and costs cover these calls; workflow outcomes are unknown.</CardDescription>
              </CardHeader><CardContent className="p-0"><div className="divide-y">
                {runs.map((run) => <button key={run.id} onClick={() => navigate(`/runs/${encodeURIComponent(run.id)}`)}
                  className="w-full flex items-center gap-4 px-6 py-3 hover:bg-ink-50 text-left">
                  <StatusDot status={run.status} /><div className="min-w-0 flex-1">
                    <div className="text-sm font-medium truncate">{run.name}</div>
                    <div className="text-xs text-ink-500">{ago(run.started_at)} · {run.call_count} observed calls · {run.error_count} observed errors</div>
                  </div><span className="text-xs">{observedCost(run.cost_usd, run.known_cost_usd, run.cost_known_count)}</span>
                  <ChevronRight className="h-4 w-4 text-ink-300" />
                </button>)}
                {!runs.length && <p className="px-6 py-3 text-sm text-ink-500">No trace rows are available.</p>}
              </div></CardContent></Card>
              <Card><CardHeader className="pb-3"><CardTitle className="text-base">Call feed</CardTitle>
                <CardDescription>Newest first. Showing {calls.length} of {stats.call_count} accepted observations; summaries use all accepted rows.</CardDescription>
                <label className="flex items-center gap-2 border rounded-lg px-3 py-2 mt-3 text-sm">
                  <Search className="h-4 w-4 text-ink-400" />
                  <input aria-label="Search displayed calls" value={search} onChange={(event) => setSearch(event.target.value)}
                    placeholder="Search displayed calls by model, agent, trace or status" className="w-full bg-transparent outline-none" />
                </label>
                {search.trim() && <p className="text-xs text-ink-500">{filteredCalls.length} matching displayed calls. Window summaries are unchanged.</p>}
              </CardHeader><CardContent className="p-0"><div className="divide-y max-h-[420px] overflow-y-auto">
                {filteredCalls.map((call) => <div key={call.id} className="px-6 py-2.5 flex items-center gap-3 text-sm">
                  <StatusDot status={call.status} />
                  <span className="h-2 w-2 rounded-sm shrink-0" style={{ backgroundColor: colorFor(call.agent_name, agentNames) }} />
                  {call.trace_id ? <Link to={`/runs/${encodeURIComponent(call.trace_id)}`} className="font-medium w-40 truncate text-brick-800 hover:underline">{call.agent_name}</Link>
                    : <span className="font-medium w-40 truncate">{call.agent_name}</span>}
                  <span className="text-xs text-ink-400 flex-1 truncate">{call.model}</span>
                  <span className="text-xs w-20 text-right">{duration(call.latency_ms)}</span>
                  <span className="text-xs w-24 text-right">{count(call.total_tokens)} tokens</span>
                  <span className="text-xs w-24 text-right">{money(call.cost_usd)}</span>
                </div>)}
                {!filteredCalls.length && <p className="px-6 py-5 text-sm text-ink-500">No displayed calls match this search.</p>}
              </div></CardContent></Card>
            </>
          )}
        </>
      )}
    </GuardianLayout>
  );
};
export default GuardianLive;
