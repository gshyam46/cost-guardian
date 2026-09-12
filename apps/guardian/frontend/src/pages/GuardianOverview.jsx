import { useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { DollarSign, Clock, AlertTriangle, Activity } from 'lucide-react';
import GuardianLayout from './GuardianLayout';
import { LineChart, BarChart } from './MiniChart';
import guardianApi from '@/services/guardianApi';
import useLiveData from '@/hooks/useLiveData';
import { isKnown, money, duration, observedCost, count } from '@/lib/liveFormat';

const SEVERITY_STYLES = {
  high: 'bg-red-100 text-red-700', medium: 'bg-amber-100 text-amber-700', low: 'bg-slate-100 text-slate-700',
};
const StatCard = ({ icon: Icon, label, value, sub }) => (
  <Card><CardContent className="pt-6"><div className="flex items-start justify-between">
    <div><p className="text-sm text-slate-500">{label}</p>
      <p className="text-2xl font-semibold text-slate-900 mt-1">{value}</p>
      <p className="text-xs text-slate-500 mt-1">{sub}</p>
    </div><Icon className="h-5 w-5 text-slate-400" />
  </div></CardContent></Card>
);
const Notice = ({ children }) => <Card className="mb-4 border-amber-200 bg-amber-50">
  <CardContent className="py-3"><p role="status" className="text-sm text-amber-900">{children}</p></CardContent>
</Card>;
const weightedMean = (parts) => {
  const weight = parts.reduce((total, part) => total + part.weight, 0);
  if (!weight) return null;
  const value = parts.reduce((total, part) => total + part.value * (part.weight / weight), 0);
  return isKnown(value) ? value : null;
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

  if (loading) return <GuardianLayout><p>Loading Guardian data...</p></GuardianLayout>;
  return (
    <GuardianLayout refreshing={refreshing} lastUpdated={lastUpdated}>
      {monitoringError ? <Notice>Worker monitoring is unavailable. Its current ingestion state cannot be established.</Notice>
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
      {monitoring?.healthy && <p className="text-xs text-slate-500 mb-4">
        Last successful ingestion checkpoint: {monitoring.last_successful_checkpoint || 'none recorded'}.
      </p>}
      {!data ? <Notice>Could not load Guardian data. Traffic and cost totals are unavailable.</Notice> : (
        <>
          {error && <Notice>Overview refresh failed. Showing previously fetched values from {lastUpdated?.toLocaleString()}.</Notice>}
          {summaryIncomplete && <Notice>{count(data.coverage.invalid_timestamp_count)} incidents have invalid timestamps.
            {' '}Open counts remain available; recent counts and daily trends are incomplete.</Notice>}
          {ledgerAccounting
            ? <p className="text-xs text-slate-500 mb-4">Hourly totals count captured observations once. Late arrivals are checked within a rolling 24-hour window; earlier history and upstream retention may limit coverage.</p>
            : <Notice>Hourly accounting is provisional. Replays and late observations in legacy totals are not reconciled.</Notice>}
          {aggregateUnavailable && <Notice>Some numeric aggregates are unavailable or exceed the supported range. They are shown as unknown.</Notice>}
          {legacy > 0 && <Notice>{count(legacy)} recorded calls use legacy rollups with unknown measurement coverage.
            They are excluded from known cost and measured-latency summaries.</Notice>}
          {totalCalls === 0 && <Notice><strong>No telemetry yet in these rollups.</strong>
            {' '}No recorded observations were returned for the last 48 hours. Check ingestion status and the live source view.</Notice>}
          <div className="grid grid-cols-1 md:grid-cols-4 gap-4 mb-6">
            <StatCard icon={AlertTriangle} label="Open incidents" value={count(overview?.open_incidents)}
              sub={summaryIncomplete ? 'Recent incident count incomplete'
                : `${count(overview?.incidents_last_7_days)} in the last 7 UTC calendar days, including today`} />
            <StatCard icon={DollarSign} label="Known recorded spend (48h)"
              value={observedCost(unpriced || costUnavailable ? null : knownCost, costUnavailable ? null : knownCost, priced)}
              sub={`${count(totalCalls)} recorded calls; ${count(unpriced)} with unknown cost`} />
            <StatCard icon={Clock} label="Measured avg latency" value={duration(avgLatency)}
              sub={`${count(measured)} measured durations; ${count(sum('missingLatency'))} unknown`} />
            <StatCard icon={Activity} label="Observed errors (48h)" value={count(totalErrors)}
              sub={`${count(totalCalls)} recorded calls; workflow outcomes not inferred`} />
          </div>
          {overview && Object.keys(overview.open_by_severity || {}).length > 0 && <div className="flex gap-2 mb-6">
            {Object.entries(overview.open_by_severity).map(([severity, value]) =>
              <Badge key={severity} className={SEVERITY_STYLES[severity] || SEVERITY_STYLES.low}>{severity}: {value}</Badge>)}
            {Object.entries(overview.open_by_detector || {}).map(([detector, value]) =>
              <Badge key={detector} variant="outline">{detector}: {value}</Badge>)}
          </div>}
          <p className="text-xs text-slate-500 mb-4">Chart dates and hours are UTC; the current hour and today are partial.</p>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-4">
            <Card><CardHeader className="pb-2"><CardTitle className="text-base">Recorded cost per hour</CardTitle>
              <CardDescription>Captured observations. Gaps indicate hours with unknown cost coverage.</CardDescription>
            </CardHeader><CardContent><LineChart points={hourly.map((h) => ({ label: h.label, value: h.cost }))}
              label="known cost" formatValue={money} /></CardContent></Card>
            <Card><CardHeader className="pb-2"><CardTitle className="text-base">Measured latency per hour</CardTitle>
              <CardDescription>Known durations only; missing measurements do not become zero.</CardDescription>
            </CardHeader><CardContent><LineChart points={hourly.map((h) => ({ label: h.label, value: h.avgLatency }))}
              label="measured latency" formatValue={duration} color="#0369a1" /></CardContent></Card>
            <Card><CardHeader className="pb-2"><CardTitle className="text-base">Recorded errors per hour</CardTitle>
              <CardDescription>Observed LLM errors within captured telemetry.</CardDescription>
            </CardHeader><CardContent><LineChart points={hourly.map((h) => ({ label: h.label, value: h.errors }))}
              label="error" color="#b91c1c" /></CardContent></Card>
            <Card><CardHeader className="pb-2"><CardTitle className="text-base">Incidents per day</CardTitle>
              <CardDescription>Last 14 UTC calendar days, including today (partial).</CardDescription>
            </CardHeader><CardContent><BarChart points={(data.trends || []).map((t) => ({ label: t.date.slice(5), value: t.count }))}
              label="incident" /></CardContent></Card>
          </div>
          <button onClick={() => navigate('/incidents')} className="text-sm text-slate-600 hover:text-slate-900 underline">View all incidents →</button>
        </>
      )}
    </GuardianLayout>
  );
};
export default GuardianOverview;
