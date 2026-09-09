import { useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { toast } from 'sonner';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { DollarSign, Clock, AlertTriangle, Activity } from 'lucide-react';
import GuardianLayout from './GuardianLayout';
import { LineChart, BarChart } from './MiniChart';
import guardianApi from '@/services/guardianApi';
import useLiveData from '@/hooks/useLiveData';

const SEVERITY_STYLES = {
  high: 'bg-red-100 text-red-700',
  medium: 'bg-amber-100 text-amber-700',
  low: 'bg-slate-100 text-slate-700',
};

const StatCard = ({ icon: Icon, label, value, sub }) => (
  <Card>
    <CardContent className="pt-6">
      <div className="flex items-start justify-between">
        <div>
          <p className="text-sm text-slate-500">{label}</p>
          <p className="text-2xl font-semibold text-slate-900 mt-1">{value}</p>
          {sub && <p className="text-xs text-slate-400 mt-1">{sub}</p>}
        </div>
        <Icon className="h-5 w-5 text-slate-400" />
      </div>
    </CardContent>
  </Card>
);

/** Collapse per-agent hourly rollups into one point per hour. */
const byHour = (metrics) => {
  const buckets = new Map();
  metrics.forEach((m) => {
    const existing = buckets.get(m.hour) || { cost: 0, calls: 0, errors: 0, latencySum: 0 };
    existing.cost += m.total_cost_usd;
    existing.calls += m.call_count;
    existing.errors += m.error_count;
    existing.latencySum += m.avg_latency_ms * m.call_count;
    buckets.set(m.hour, existing);
  });
  return [...buckets.entries()]
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([hour, v]) => ({
      hour,
      label: hour.slice(11, 16),
      cost: v.cost,
      calls: v.calls,
      errors: v.errors,
      avgLatency: v.calls ? v.latencySum / v.calls : 0,
    }));
};

const GuardianOverview = () => {
  const navigate = useNavigate();

  const fetchAll = useCallback(async () => {
    const [overviewRes, metricsRes, trendsRes] = await Promise.all([
      guardianApi.getOverview(),
      guardianApi.getMetrics(48),
      guardianApi.getTrends(14),
    ]);
    return { overview: overviewRes.data, metrics: metricsRes.data, trends: trendsRes.data };
  }, []);

  const { data, loading, refreshing, error, lastUpdated } = useLiveData(fetchAll);

  // Only shout about a failure that left us with nothing to show. A refresh that
  // fails while good data is already on screen is a transient blip, not an event
  // worth a toast every polling interval.
  if (error && !data) toast.error('Could not load Guardian data');

  const overview = data?.overview ?? null;
  const metrics = data?.metrics ?? [];
  const trends = data?.trends ?? [];

  const hourly = byHour(metrics);
  const totalCost = hourly.reduce((sum, h) => sum + h.cost, 0);
  const totalCalls = hourly.reduce((sum, h) => sum + h.calls, 0);
  const totalErrors = hourly.reduce((sum, h) => sum + h.errors, 0);
  const avgLatency = totalCalls
    ? hourly.reduce((sum, h) => sum + h.avgLatency * h.calls, 0) / totalCalls
    : 0;

  if (loading) {
    return (
      <GuardianLayout>
        <div className="animate-pulse text-slate-600">Loading Guardian data...</div>
      </GuardianLayout>
    );
  }

  return (
    <GuardianLayout refreshing={refreshing} lastUpdated={lastUpdated}>
      {totalCalls === 0 && (
        <Card className="mb-6 border-amber-200 bg-amber-50">
          <CardContent className="pt-6">
            <p className="text-sm text-amber-900 font-medium">No telemetry yet</p>
            <p className="text-sm text-amber-800 mt-1">
              Guardian has not seen any LLM calls. Set <code>LANGFUSE_PUBLIC_KEY</code> and{' '}
              <code>LANGFUSE_SECRET_KEY</code> in <code>apps/guardian/backend/.env</code>, run any
              instrumented app, and start the worker with{' '}
              <code>python -m guardian.worker</code>.
            </p>
          </CardContent>
        </Card>
      )}

      <div className="grid grid-cols-1 md:grid-cols-4 gap-4 mb-6">
        <StatCard
          icon={AlertTriangle}
          label="Open incidents"
          value={overview?.open_incidents ?? 0}
          sub={`${overview?.incidents_last_7_days ?? 0} in the last 7 days`}
        />
        <StatCard
          icon={DollarSign}
          label="Spend (48h)"
          value={`$${totalCost.toFixed(4)}`}
          sub={`${totalCalls} LLM calls`}
        />
        <StatCard
          icon={Clock}
          label="Avg latency"
          value={`${Math.round(avgLatency)}ms`}
          sub="across all agents"
        />
        <StatCard
          icon={Activity}
          label="Errors (48h)"
          value={totalErrors}
          sub={totalCalls ? `${((totalErrors / totalCalls) * 100).toFixed(1)}% of calls` : '—'}
        />
      </div>

      {overview && Object.keys(overview.open_by_severity || {}).length > 0 && (
        <div className="flex gap-2 mb-6">
          {Object.entries(overview.open_by_severity).map(([severity, count]) => (
            <Badge key={severity} className={SEVERITY_STYLES[severity] || SEVERITY_STYLES.low}>
              {severity}: {count}
            </Badge>
          ))}
          {Object.entries(overview.open_by_detector || {}).map(([detector, count]) => (
            <Badge key={detector} variant="outline">
              {detector}: {count}
            </Badge>
          ))}
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-4">
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-base">Cost per hour</CardTitle>
            <CardDescription>Last 48 hours, all agents</CardDescription>
          </CardHeader>
          <CardContent>
            <LineChart
              points={hourly.map((h) => ({ label: h.label, value: h.cost }))}
              label="cost"
              formatValue={(v) => `$${v.toFixed(4)}`}
            />
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-base">Average latency per hour</CardTitle>
            <CardDescription>Last 48 hours, all agents</CardDescription>
          </CardHeader>
          <CardContent>
            <LineChart
              points={hourly.map((h) => ({ label: h.label, value: h.avgLatency }))}
              label="latency"
              formatValue={(v) => `${Math.round(v)}ms`}
              color="#0369a1"
            />
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-base">Errors per hour</CardTitle>
            <CardDescription>Failed LLM calls</CardDescription>
          </CardHeader>
          <CardContent>
            <LineChart
              points={hourly.map((h) => ({ label: h.label, value: h.errors }))}
              label="error"
              formatValue={(v) => `${v}`}
              color="#b91c1c"
            />
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-base">Incidents per day</CardTitle>
            <CardDescription>Last 14 days</CardDescription>
          </CardHeader>
          <CardContent>
            <BarChart
              points={trends.map((t) => ({ label: t.date.slice(5), value: t.count }))}
              label="incident"
            />
          </CardContent>
        </Card>
      </div>

      <button
        onClick={() => navigate('/incidents')}
        className="text-sm text-slate-600 hover:text-slate-900 underline"
      >
        View all incidents →
      </button>
    </GuardianLayout>
  );
};

export default GuardianOverview;
