import { useCallback, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { toast } from 'sonner';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Activity, AlertTriangle, DollarSign, Timer, ChevronRight, ExternalLink } from 'lucide-react';
import GuardianLayout from './GuardianLayout';
import { BarList, LatencyScatter, STATUS, colorFor } from '@/components/Charts';
import guardianApi from '@/services/guardianApi';
import useLiveData from '@/hooks/useLiveData';

const WINDOWS = [
  { hours: 1, label: '1h' },
  { hours: 6, label: '6h' },
  { hours: 24, label: '24h' },
  { hours: 168, label: '7d' },
];

const money = (v) => `$${v.toFixed(v < 0.01 ? 5 : 4)}`;
const ms = (v) => (v >= 1000 ? `${(v / 1000).toFixed(1)}s` : `${Math.round(v)}ms`);

const ago = (iso) => {
  if (!iso) return '--';
  const seconds = Math.floor((Date.now() - new Date(iso).getTime()) / 1000);
  if (seconds < 60) return `${seconds}s ago`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
  return `${Math.floor(seconds / 86400)}d ago`;
};

/** A headline number. `tone` colours only the supporting line, never the number
 *  itself -- the figure stays in primary ink so it is never encoded by colour. */
const Stat = ({ icon: Icon, label, value, sub, tone }) => (
  <Card>
    <CardContent className="pt-5 pb-4">
      <div className="flex items-start justify-between">
        <div className="min-w-0">
          <p className="text-xs text-slate-500 uppercase tracking-wide">{label}</p>
          <p className="text-2xl font-semibold text-slate-900 mt-1 tabular-nums">{value}</p>
          {sub && (
            <p className="text-xs mt-1 truncate" style={{ color: tone || '#64748b' }}>
              {sub}
            </p>
          )}
        </div>
        <Icon className="h-4 w-4 text-slate-300 shrink-0" />
      </div>
    </CardContent>
  </Card>
);

const StatusDot = ({ status }) => (
  <span
    className="inline-block h-2 w-2 rounded-full shrink-0"
    style={{ backgroundColor: status === 'error' ? STATUS.critical : STATUS.good }}
  />
);

const GuardianLive = () => {
  const navigate = useNavigate();
  const [hours, setHours] = useState(24);

  const fetchAll = useCallback(async () => (await guardianApi.getLive(hours, 8, 60)).data, [hours]);

  // 12s against a 20s server-side cache. Langfuse allows 15 requests/minute for the
  // whole project and the worker spends from the same budget, so polling harder would
  // not produce fresher numbers -- it would produce 429s.
  const { data, loading, refreshing, error, lastUpdated } = useLiveData(fetchAll, {
    intervalMs: 12000,
    refetchKey: hours,
  });

  if (error && !data) toast.error('Could not reach Guardian');

  const stats = data?.stats ?? null;
  const calls = data?.calls ?? [];
  const runs = data?.runs ?? [];
  const degraded = data?.degraded === true;

  if (loading) {
    return (
      <GuardianLayout>
        <div className="animate-pulse text-slate-600">Loading live telemetry...</div>
      </GuardianLayout>
    );
  }

  // Guardian having no Langfuse credentials and your app having made no calls are
  // completely different situations; showing an empty dashboard for both would be a
  // lie in one of the two cases.
  if (data && data.available === false) {
    return (
      <GuardianLayout refreshing={refreshing} lastUpdated={lastUpdated}>
        <Card className="border-amber-200 bg-amber-50">
          <CardContent className="pt-6">
            <p className="text-sm font-medium text-amber-900">Guardian cannot see your telemetry</p>
            <p className="text-sm text-amber-800 mt-1">
              {data.reason} Set <code>LANGFUSE_PUBLIC_KEY</code> and{' '}
              <code>LANGFUSE_SECRET_KEY</code> in <code>apps/guardian/backend/.env</code> and
              restart the API.
            </p>
          </CardContent>
        </Card>
      </GuardianLayout>
    );
  }

  const errorRate = stats?.call_count ? (stats.error_count / stats.call_count) * 100 : 0;
  const agentNames = (stats?.by_agent ?? []).map((a) => a.name);

  return (
    <GuardianLayout refreshing={refreshing} lastUpdated={lastUpdated}>
      <div className="flex items-center justify-between mb-5">
        <div>
          <h2 className="text-xl font-semibold text-slate-900">Live activity</h2>
          <p className="text-sm text-slate-500">
            Read from Langfuse, never stored by Guardian
            {data?.fetched_at && <> &mdash; source data from {ago(data.fetched_at)}</>}
          </p>
        </div>
        <div className="flex gap-1">
          {WINDOWS.map((w) => (
            <Button
              key={w.hours}
              size="sm"
              variant={hours === w.hours ? 'default' : 'outline'}
              onClick={() => setHours(w.hours)}
            >
              {w.label}
            </Button>
          ))}
        </div>
      </div>

      {degraded && (
        <Card className="mb-5 border-amber-200 bg-amber-50">
          <CardContent className="py-3">
            <p className="text-sm text-amber-900">
              <span className="font-medium">Showing no data because Guardian could not read.</span>{' '}
              {data.reason}
            </p>
          </CardContent>
        </Card>
      )}

      {data?.stale && !degraded && (
        <Card className="mb-5 border-slate-200 bg-slate-50">
          <CardContent className="py-3">
            <p className="text-sm text-slate-600">
              Langfuse did not answer the last refresh &mdash; these numbers are from{' '}
              {ago(data.fetched_at)} and will catch up shortly.
            </p>
          </CardContent>
        </Card>
      )}

      {stats?.call_count === 0 && !degraded ? (
        <Card className="border-slate-200">
          <CardContent className="pt-6 text-center py-10">
            <Activity className="h-6 w-6 text-slate-300 mx-auto mb-3" />
            <p className="text-sm font-medium text-slate-700">
              No LLM calls in the last {WINDOWS.find((w) => w.hours === hours)?.label}
            </p>
            <p className="text-sm text-slate-500 mt-1">
              Guardian is connected and watching. Run the demo app and calls will appear here
              within seconds.
            </p>
          </CardContent>
        </Card>
      ) : (
        <>
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 mb-5">
            <Stat
              icon={Activity}
              label="LLM calls"
              value={stats.call_count.toLocaleString()}
              sub={stats.last_call_at ? `last ${ago(stats.last_call_at)}` : null}
            />
            <Stat
              icon={AlertTriangle}
              label="Error rate"
              value={`${errorRate.toFixed(1)}%`}
              sub={`${stats.error_count} failed calls`}
              tone={errorRate > 10 ? STATUS.critical : errorRate > 0 ? STATUS.warning : undefined}
            />
            <Stat
              icon={DollarSign}
              label="Spend"
              value={money(stats.total_cost_usd)}
              sub={`${stats.total_tokens.toLocaleString()} tokens`}
            />
            <Stat
              icon={Timer}
              label="p95 latency"
              value={ms(stats.p95_latency_ms)}
              sub={`avg ${ms(stats.avg_latency_ms)}`}
            />
          </div>

          <Card className="mb-5">
            <CardHeader className="pb-2">
              <CardTitle className="text-base">Latency per call</CardTitle>
              <CardDescription>
                Every call in the window, oldest to newest. Hover a point for detail.
              </CardDescription>
            </CardHeader>
            <CardContent>
              <LatencyScatter calls={calls} names={agentNames} />
            </CardContent>
          </Card>

          <div className="grid lg:grid-cols-2 gap-5 mb-5">
            <Card>
              <CardHeader className="pb-3">
                <CardTitle className="text-base">Spend by agent</CardTitle>
                <CardDescription>Which agent is actually costing you money</CardDescription>
              </CardHeader>
              <CardContent>
                <BarList
                  rows={stats.by_agent}
                  valueKey="cost_usd"
                  format={money}
                  label="agent cost"
                  names={agentNames}
                />
              </CardContent>
            </Card>

            <Card>
              <CardHeader className="pb-3">
                <CardTitle className="text-base">Latency by agent</CardTitle>
                <CardDescription>Average across the window</CardDescription>
              </CardHeader>
              <CardContent>
                <BarList
                  rows={[...stats.by_agent].sort((a, b) => b.avg_latency_ms - a.avg_latency_ms)}
                  valueKey="avg_latency_ms"
                  format={ms}
                  label="agent latency"
                  names={agentNames}
                />
              </CardContent>
            </Card>
          </div>

          <Card className="mb-5">
            <CardHeader className="pb-3">
              <CardTitle className="text-base">Recent runs</CardTitle>
              <CardDescription>
                One row per pipeline execution. Click through for the call-by-call timeline.
              </CardDescription>
            </CardHeader>
            <CardContent className="p-0">
              <div className="divide-y">
                {runs.map((run) => (
                  <button
                    key={run.id}
                    onClick={() => navigate(`/runs/${run.id}`)}
                    className="w-full flex items-center gap-4 px-6 py-3 hover:bg-slate-50 text-left transition-colors"
                  >
                    <StatusDot status={run.status} />
                    <div className="min-w-0 flex-1">
                      <div className="text-sm font-medium text-slate-900 truncate">{run.name}</div>
                      <div className="text-xs text-slate-500">
                        {ago(run.started_at)} · {run.call_count} calls
                        {run.error_count > 0 && (
                          <span style={{ color: STATUS.critical }}> · {run.error_count} failed</span>
                        )}
                      </div>
                    </div>
                    <div className="hidden sm:flex items-center gap-1">
                      {run.agents.map((agent) => (
                        <span
                          key={agent}
                          title={agent}
                          className="h-2 w-2 rounded-sm"
                          style={{ backgroundColor: colorFor(agent, agentNames) }}
                        />
                      ))}
                    </div>
                    <div className="text-xs tabular-nums text-slate-600 w-20 text-right">
                      {ms(run.latency_ms)}
                    </div>
                    <div className="text-xs tabular-nums text-slate-600 w-20 text-right">
                      {money(run.cost_usd)}
                    </div>
                    <ChevronRight className="h-4 w-4 text-slate-300 shrink-0" />
                  </button>
                ))}
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-base">Call feed</CardTitle>
              <CardDescription>Newest first &mdash; every individual LLM call</CardDescription>
            </CardHeader>
            <CardContent className="p-0">
              <div className="divide-y max-h-[420px] overflow-y-auto">
                {calls.map((call) => (
                  <div key={call.id} className="px-6 py-2.5 flex items-center gap-3 text-sm">
                    <StatusDot status={call.status} />
                    <span
                      className="h-2 w-2 rounded-sm shrink-0"
                      style={{ backgroundColor: colorFor(call.agent_name, agentNames) }}
                    />
                    <span className="font-medium text-slate-800 w-40 truncate">
                      {call.agent_name}
                    </span>
                    <span className="text-xs text-slate-400 flex-1 truncate hidden md:block">
                      {call.status === 'error' && call.status_message
                        ? call.status_message.slice(0, 90)
                        : call.model}
                    </span>
                    <span className="text-xs tabular-nums text-slate-500 w-16 text-right">
                      {call.status === 'error' ? '--' : ms(call.latency_ms)}
                    </span>
                    <span className="text-xs tabular-nums text-slate-500 w-20 text-right hidden sm:block">
                      {call.total_tokens.toLocaleString()} tok
                    </span>
                    <span className="text-xs tabular-nums text-slate-500 w-20 text-right">
                      {money(call.cost_usd)}
                    </span>
                    <span className="text-xs text-slate-400 w-16 text-right hidden lg:block">
                      {ago(call.started_at)}
                    </span>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>
        </>
      )}
    </GuardianLayout>
  );
};

export default GuardianLive;
