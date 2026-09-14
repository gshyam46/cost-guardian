import { useCallback } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { DollarSign, Clock, AlertTriangle, Activity, Layers, ArrowUpRight } from 'lucide-react';
import GuardianLayout from './GuardianLayout';
import { LineChart, BarChart } from './MiniChart';
import guardianApi from '@/services/guardianApi';
import useLiveData from '@/hooks/useLiveData';
import { isKnown, money, duration, observedCost, count } from '@/lib/liveFormat';

const SEVERITY_STYLES = {
  high: 'bg-danger-100 text-danger-700', medium: 'bg-ochre-100 text-ochre-700', low: 'bg-ink-100 text-ink-700',
};
const StatCard = ({ icon: Icon, label, value, sub }) => (
  <Card><CardContent className="pt-6"><div className="flex items-start justify-between">
    <div><p className="text-sm text-ink-500">{label}</p>
      <p className="text-2xl font-semibold text-ink-900 mt-1">{value}</p>
      <p className="text-xs text-ink-500 mt-1">{sub}</p>
    </div><Icon className="h-5 w-5 text-ink-400" />
  </div></CardContent></Card>
);
const Notice = ({ children }) => <Card className="mb-4 border-ochre-200 bg-ochre-50">
  <CardContent className="py-3"><p role="status" className="text-sm text-ochre-900">{children}</p></CardContent>
</Card>;
const weightedMean = (parts) => {
  const weight = parts.reduce((total, part) => total + part.weight, 0);
  if (!weight) return null;
  const value = parts.reduce((total, part) => total + part.value * (part.weight / weight), 0);
  return isKnown(value) ? value : null;
};

const SourceSnapshot = ({ data, loading, error }) => {
  const stats = data?.stats;
  const available = data?.available !== false && !data?.degraded && stats?.window_hours === 24;
  const direct = data?.source_kind === 'guardian_direct';
  const coverage = data?.coverage;
  const pending = (coverage?.pending_events || 0) + (coverage?.pending_observations || 0) + (coverage?.dirty_buckets || 0);
  const tokenValue = isKnown(stats?.total_tokens) ? count(stats.total_tokens)
    : stats?.tokens_known_count > 0 ? `${count(stats.known_total_tokens)} known` : 'Unknown';
  return <section aria-label="Source activity" className="mb-8">
    <div className="flex flex-wrap items-start justify-between gap-4 mb-5">
      <div><p className="text-xs uppercase tracking-widest text-brick-700 mb-2">Your application / last 24 hours</p>
        <h2 className="cg-page-title text-3xl font-semibold tracking-tight text-ink-900">Application activity</h2>
        <p className="text-sm text-ink-500 mt-2">Usage, performance and errors from the same captured observations as Live activity.</p>
      </div>
      <Link to="/live" className="inline-flex items-center gap-2 text-sm font-medium text-brick-800 py-2">Explore activity <ArrowUpRight className="h-4 w-4" /></Link>
    </div>
    {loading ? <p role="status" className="text-sm text-ink-500">Loading source activity...</p>
      : !available ? <Notice><strong>Source activity is unavailable.</strong> {data?.reason || 'Check your connection to see captured calls.'}
        {' '}A missing read does not mean zero traffic. <Link to="/setup" className="underline">Check connection</Link></Notice>
      : <>
        {(data.stale || error) && <Notice>Showing stale source activity from {data.fetched_at || 'an unknown time'}. The latest refresh failed.</Notice>}
        <div className="rounded-xl border border-brick-100 bg-brick-50/50 p-4 mb-5 text-sm">
          <strong>{direct ? 'Direct capture' : 'Langfuse source'}</strong>
          <p className="text-ink-600 mt-1">{direct
            ? 'Your application sends completed-call measurements to Sillage. The worker processes receipts into the observations shown here. Test receipts are excluded.'
            : 'Sillage reads generation observations from your connected Langfuse project. The worker separately checks them for incidents and builds hourly history.'}</p>
          <p className="text-xs text-ink-500 mt-2">{coverage?.status === 'complete' ? 'Source query complete' : 'Partial observation coverage'}
            {data.fetched_at && <> · source data from {data.fetched_at}</>}. Delayed telemetry and source retention can limit accessible history.</p>
        </div>
        {coverage?.status !== 'complete' && <Notice>These are accepted observations, not full-window totals.
          {pending > 0 && <> Processing is still catching up.</>}
          {coverage?.truncated && <> The query reached its read limit.</>}
          {(coverage?.invalid_count || 0) > 0 && <> {count(coverage.invalid_count)} records need review.</>}
        </Notice>}
        {stats.call_count === 0 ? <Card><CardContent className="py-7">
          <h3 className="font-semibold text-ink-900">{pending > 0 ? 'Your received events are being processed.' : 'Connect one real application call.'}</h3>
          <p className="text-sm text-ink-500 mt-2">{pending > 0
            ? 'Captured observations will appear when processing completes. Check connection status if the queue does not clear.'
            : 'No accepted LLM calls were returned in the last 24 hours. A connection test checks delivery; it does not populate production charts.'}</p>
          <Link to="/setup" className="inline-flex text-sm text-brick-800 font-medium mt-4 underline">Open connection setup</Link>
          <a href="/demo" className="inline-flex text-sm text-ink-600 ml-5 underline">Explore the sample workspace</a>
        </CardContent></Card> : <>
          <div className="grid grid-cols-2 xl:grid-cols-5 gap-3 mb-5">
            <StatCard icon={Activity} label="Captured calls (24h)" value={count(stats.call_count)} sub="Accepted source observations" />
            <StatCard icon={Layers} label="Token usage (24h)" value={tokenValue} sub={`${count(stats.tokens_unknown_count)} calls missing usage`} />
            <StatCard icon={Clock} label="p95 call latency (24h)" value={duration(stats.p95_latency_ms)} sub={`${count(stats.latency_known_count)} measured calls`} />
            <StatCard icon={AlertTriangle} label="Call errors (24h)" value={count(stats.error_count)} sub={`${count(stats.unknown_status_count)} outcomes unknown`} />
            <StatCard icon={DollarSign} label="Captured spend (24h)" value={observedCost(stats.total_cost_usd, stats.known_cost_usd, stats.cost_known_count)} sub={`${count(stats.cost_unknown_count)} calls missing cost`} />
          </div>
          <Card><CardHeader className="pb-3"><CardTitle className="text-base">Recent traces</CardTitle>
            <CardDescription>Follow related calls to inspect their measurements and timing.</CardDescription>
          </CardHeader><CardContent className="p-0">
            {(data.runs || []).map((run) => <Link key={run.id} to={`/runs/${encodeURIComponent(run.id)}`}
              className="flex items-center justify-between gap-4 px-6 py-3 border-t hover:bg-brick-50/50">
              <div className="min-w-0"><p className="text-sm font-medium truncate">{run.name}</p>
                <p className="text-xs text-ink-500">{count(run.call_count)} calls · {count(run.error_count)} errors</p></div>
              <span className="text-xs tabular-nums">{observedCost(run.cost_usd, run.known_cost_usd, run.cost_known_count)}</span>
            </Link>)}
            {!data.runs?.length && <p className="px-6 pb-5 text-sm text-ink-500">No trace rows were returned. <Link className="underline" to="/live">Inspect the call feed</Link>.</p>}
          </CardContent></Card>
        </>}
      </>}
  </section>;
};

const DirectProcessing = ({ capture }) => {
  if (!capture) return <Notice>Direct capture processing status is unavailable. <Link className="underline" to="/setup">Check connection</Link>.</Notice>;
  const pending = capture.pending_events > 0;
  const conflicts = capture.conflicted_events > 0;
  const workerAttention = capture.worker_status !== 'current';
  return <Card className="mb-5"><CardContent className="py-4">
    <p className="font-medium text-sm">Direct capture processing</p>
    <p className="text-sm text-ink-600 mt-1">{count(capture.received_events)} production events received · {count(capture.processed_events)} processed · {count(capture.pending_events)} awaiting processing.</p>
    <p className="text-xs text-ink-500 mt-2">{capture.worker_status === 'current' ? 'Recent worker heartbeat.'
      : capture.worker_status === 'stale' ? 'The worker heartbeat is stale.' : 'The worker has not reported yet.'}
      {' '}A heartbeat alone does not confirm successful monitoring.
      {capture.last_processed_at && <> Last processed event: {capture.last_processed_at}.</>}
    </p>
    {(pending || conflicts || workerAttention) && <p role="status" className="text-sm text-ochre-800 mt-2">
      {pending && <>Received events are waiting for the worker. </>}
      {conflicts && <>{count(capture.conflicted_events)} conflicting observations need review. </>}
      <Link to="/setup" className="underline">Check connection and processing status</Link>.
    </p>}
    {capture.received_events === 0 && capture.last_test_received_at && <p className="text-sm text-ink-600 mt-2">A test receipt arrived. Send a real application call to start filling production views.</p>}
  </CardContent></Card>;
};

const byHour = (metrics) => {
  const buckets = new Map();
  metrics.forEach((m) => {
    const row = buckets.get(m.hour) || {
      calls: 0, errors: 0, knownCost: 0, priced: 0, unpriced: 0, legacy: 0,
      latencyParts: [], measured: 0, missingLatency: 0, latencyUnavailable: false, costUnavailable: false,
    };
    const legacy = m.coverage_status !== 'known';
    if (m.conflict_count > 0) row.costUnavailable = true;
    row.calls += m.call_count;
    row.errors += m.error_count;
    row.legacy += legacy ? m.call_count : 0;
    row.unpriced += legacy ? m.call_count : m.cost_unknown_count;
    row.priced += legacy ? 0 : m.cost_known_count;
    if (!legacy && isKnown(m.known_cost_usd)) row.knownCost += m.known_cost_usd;
    else if (!legacy && m.cost_known_count > 0) row.costUnavailable = true;
    if (!legacy) row.measured += m.latency_known_count;
    if (!legacy && isKnown(m.avg_latency_ms) && m.latency_known_count > 0) {
      row.latencyParts.push({ value: m.avg_latency_ms, weight: m.latency_known_count });
    }
    else if (!legacy && m.latency_known_count > 0) row.latencyUnavailable = true;
    row.missingLatency += legacy ? m.call_count : m.latency_unknown_count;
    buckets.set(m.hour, row);
  });
  return [...buckets.entries()].sort(([a], [b]) => a.localeCompare(b)).map(([hour, row]) => ({
    ...row, hour, label: hour.slice(5, 16).replace('T', ' '),
    cost: row.unpriced || row.legacy || row.costUnavailable || !isKnown(row.knownCost) ? null : row.knownCost,
    avgLatency: row.latencyUnavailable ? null : weightedMean(row.latencyParts),
  }));
};

const GuardianOverview = () => {
  const navigate = useNavigate();
  const fetchAll = useCallback(async ({ signal } = {}) => {
    const [summary, metrics] = await Promise.all([
      guardianApi.getSummary(14, { signal }), guardianApi.getMetrics(48, { signal }),
    ]);
    return { ...summary.data, metrics: metrics.data };
  }, []);
  const fetchMonitoring = useCallback(async ({ signal } = {}) => (await guardianApi.getMonitoring({ signal })).data, []);
  const { data, loading, refreshing, error, lastUpdated } = useLiveData(fetchAll);
  const { data: monitoring, error: monitoringError } = useLiveData(fetchMonitoring);
  const fetchSource = useCallback(async ({ signal } = {}) => (await guardianApi.getLive(24, 5, 8, { signal })).data, []);
  const source = useLiveData(fetchSource, { intervalMs: 12000 });
  const overview = data?.overview;
  const summaryIncomplete = data?.coverage?.status === 'partial';
  const hourly = byHour(data?.metrics || []);
  const sum = (field) => hourly.reduce((total, row) => total + row[field], 0);
  const totalCalls = sum('calls');
  const totalErrors = sum('errors');
  const priced = sum('priced');
  const unpriced = sum('unpriced');
  const knownCost = sum('knownCost');
  const measured = sum('measured');
  const avgLatency = hourly.some((h) => h.measured > 0 && !isKnown(h.avgLatency)) ? null
    : weightedMean(hourly.filter((h) => h.measured > 0).map((h) => ({ value: h.avgLatency, weight: h.measured })));
  const legacy = sum('legacy');
  const ledgerAccounting = (data?.metrics || []).length > 0
    && data.metrics.every((metric) => metric.accounting_status === 'ledger-1');
  const costUnavailable = hourly.some((h) => h.costUnavailable) || !isKnown(knownCost);
  const aggregateUnavailable = costUnavailable || (measured > 0 && !isKnown(avgLatency))
    || (data?.metrics || []).some((m) => m.aggregate_issues?.length > 0);

  return (
    <GuardianLayout refreshing={refreshing} lastUpdated={lastUpdated}>
      <SourceSnapshot data={source.data} loading={source.loading} error={source.error} />
      <div className="mb-4"><h2 className="text-xl font-semibold tracking-tight">Analysis &amp; hourly history</h2>
        <p className="text-sm text-ink-500 mt-1">Worker-processed accounting covers 48 hours. Source activity above covers 24 hours; processing time and these different windows can change the totals.</p></div>
      {monitoringError ? <Notice>Worker monitoring is unavailable. Its current ingestion state cannot be established.</Notice>
        : monitoring?.source_kind === 'guardian_direct' ? <DirectProcessing capture={monitoring.capture} />
        : monitoring && !monitoring.healthy && <Notice>
          <strong>Ingestion needs attention: {monitoring.status.replaceAll('_', ' ')}.</strong>
          {monitoring.read_error_code && <> Read reason: {monitoring.read_error_code}.</>}
          {monitoring.read_error_code === 'checkpoint_outside_window' && <> Historical backfill is required before ingestion can safely resume.</>}
          {monitoring.read_error_code === 'legacy_metrics_migration_required' && <> Existing totals need a planned cutover before observation accounting can start.</>}
          {(monitoring.pending_observations > 0 || monitoring.dirty_buckets > 0) && <>
            {' '}{count(monitoring.pending_observations)} observations await checks; {count(monitoring.dirty_buckets)} hourly totals await rebuilding.
          </>}
          {monitoring.quarantined_records > 0 && <> {count(monitoring.quarantined_records)} rejected or conflicting records need review. Totals may be incomplete.</>}
          {' '}Last successful ingestion checkpoint: {monitoring.last_successful_checkpoint || 'none recorded'}.
          {monitoring.stale && <> The worker has not reported within its expected interval.</>}
        </Notice>}
      {monitoring?.healthy && <p className="text-xs text-ink-500 mb-4">
        Last successful ingestion checkpoint: {monitoring.last_successful_checkpoint || 'none recorded'}.
      </p>}
      {loading ? <p role="status">Loading hourly history...</p> : !data ? <Notice>Could not load Sillage data. Traffic and cost totals are unavailable for hourly history. Source activity is read separately above.</Notice> : (
        <>
          {error && <Notice>Overview refresh failed. Showing previously fetched values from {lastUpdated?.toLocaleString()}.</Notice>}
          {summaryIncomplete && <Notice>{count(data.coverage.invalid_timestamp_count)} incidents have invalid timestamps.
            {' '}Open counts remain available; recent counts and daily trends are incomplete.</Notice>}
          {ledgerAccounting
            ? <p className="text-xs text-ink-500 mb-4">Hourly totals count captured observations once. {source.data?.source_kind === 'guardian_direct'
              ? 'Direct capture assigns accepted events to the hour they occurred; delayed processing can update earlier totals.'
              : 'Late arrivals are checked within a rolling 24-hour window; earlier history and upstream retention may limit coverage.'}</p>
            : data.metrics.length > 0 && <Notice>Hourly accounting is provisional. Replays and late observations in legacy totals are not reconciled.</Notice>}
          {aggregateUnavailable && <Notice>Some numeric aggregates are unavailable or exceed the supported range. They are shown as unknown.</Notice>}
          {legacy > 0 && <Notice>{count(legacy)} recorded calls use legacy rollups with unknown measurement coverage.
            They are excluded from known cost and measured-latency summaries.</Notice>}
          {totalCalls === 0 && <Notice><strong>No hourly history has been returned yet.</strong>
            {' '}{source.data?.stats?.call_count > 0 ? 'Calls are visible in source activity above. Hourly totals are produced separately by the worker.'
              : 'Hourly history appears after real calls have been processed.'}
            {' '}<Link to="/setup" className="underline">Check connection and processing</Link>.</Notice>}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-4">
            <StatCard icon={AlertTriangle} label="Open incidents" value={count(overview?.open_incidents)}
              sub={summaryIncomplete ? 'Recent incident count incomplete'
                : `${count(overview?.incidents_last_7_days)} in the last 7 UTC calendar days, including today`} />
            <StatCard icon={DollarSign} label="Known recorded spend (48h)"
              value={totalCalls > 0 ? observedCost(unpriced || costUnavailable ? null : knownCost, costUnavailable ? null : knownCost, priced) : 'Unknown'}
              sub={`${count(totalCalls)} recorded calls; ${count(unpriced)} with unknown cost`} />
          </div>
          <p className="text-xs text-ink-500 mb-6">Processed 48h history: {count(totalCalls)} recorded calls · {count(totalErrors)} observed errors · measured average {duration(avgLatency)}
            {' '}across {count(measured)} known durations; {count(sum('missingLatency'))} missing. Workflow outcomes are not inferred.</p>
          {overview && Object.keys(overview.open_by_severity || {}).length > 0 && <div className="flex gap-2 mb-6">
            {Object.entries(overview.open_by_severity).map(([severity, value]) =>
              <Badge key={severity} className={SEVERITY_STYLES[severity] || SEVERITY_STYLES.low}>{severity}: {value}</Badge>)}
            {Object.entries(overview.open_by_detector || {}).map(([detector, value]) =>
              <Badge key={detector} variant="outline">{detector}: {value}</Badge>)}
          </div>}
          <p className="text-xs text-ink-500 mb-4">Chart dates and hours are UTC; the current hour and today are partial.</p>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-4">
            <Card><CardHeader className="pb-2"><CardTitle className="text-base">Recorded cost per hour</CardTitle>
              <CardDescription>Captured observations. Gaps indicate hours with unknown cost coverage.</CardDescription>
            </CardHeader><CardContent><LineChart points={hourly.map((h) => ({ label: h.label, value: h.cost }))}
              label="known cost" formatValue={money} /></CardContent></Card>
            <Card><CardHeader className="pb-2"><CardTitle className="text-base">Measured latency per hour</CardTitle>
              <CardDescription>Known durations only; missing measurements do not become zero.</CardDescription>
            </CardHeader><CardContent><LineChart points={hourly.map((h) => ({ label: h.label, value: h.avgLatency }))}
              label="measured latency" formatValue={duration} color="var(--sillage-ochre)" /></CardContent></Card>
            <Card><CardHeader className="pb-2"><CardTitle className="text-base">Recorded errors per hour</CardTitle>
              <CardDescription>Observed LLM errors within captured telemetry.</CardDescription>
            </CardHeader><CardContent><LineChart points={hourly.map((h) => ({ label: h.label, value: h.errors }))}
              label="error" color="var(--sillage-brick)" /></CardContent></Card>
            <Card><CardHeader className="pb-2"><CardTitle className="text-base">Incidents per day</CardTitle>
              <CardDescription>Last 14 UTC calendar days, including today (partial).</CardDescription>
            </CardHeader><CardContent><BarChart points={(data.trends || []).map((t) => ({ label: t.date.slice(5), value: t.count }))}
              label="incident" /></CardContent></Card>
          </div>
          <button onClick={() => navigate('/incidents')} className="text-sm text-ink-600 hover:text-ink-900 underline">View all incidents →</button>
        </>
      )}
    </GuardianLayout>
  );
};
export default GuardianOverview;
