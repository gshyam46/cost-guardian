import { useCallback, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { toast } from 'sonner';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { ArrowLeft, ExternalLink, ChevronDown, ChevronRight } from 'lucide-react';
import GuardianLayout from './GuardianLayout';
import { RunWaterfall, STATUS, colorFor } from '@/components/Charts';
import guardianApi from '@/services/guardianApi';
import useLiveData from '@/hooks/useLiveData';

const money = (v) => `$${v.toFixed(5)}`;
const ms = (v) => (v >= 1000 ? `${(v / 1000).toFixed(2)}s` : `${Math.round(v)}ms`);

const Field = ({ label, value, tone }) => (
  <div>
    <div className="text-xs text-slate-500 uppercase tracking-wide">{label}</div>
    <div className="text-lg font-semibold tabular-nums mt-0.5" style={{ color: tone || '#0f172a' }}>
      {value}
    </div>
  </div>
);

/** One call, collapsed to a row and expandable to its model output.
 *
 *  The output is the reason this page exists: a latency number tells you a call was
 *  slow, but only the response tells you whether it was slow *and wrong*. */
const CallRow = ({ call, names, index }) => {
  const [open, setOpen] = useState(false);
  const failed = call.status === 'error';
  const Chevron = open ? ChevronDown : ChevronRight;

  return (
    <div className="border-b last:border-b-0">
      <button
        onClick={() => setOpen((v) => !v)}
        className="w-full px-5 py-3 flex items-center gap-3 hover:bg-slate-50 text-left transition-colors"
      >
        <Chevron className="h-4 w-4 text-slate-400 shrink-0" />
        <span className="text-xs text-slate-400 tabular-nums w-5">{index + 1}</span>
        <span
          className="h-2.5 w-2.5 rounded-sm shrink-0"
          style={{ backgroundColor: failed ? STATUS.critical : colorFor(call.agent_name, names) }}
        />
        <span className="font-medium text-sm text-slate-900 w-44 truncate">{call.agent_name}</span>
        <span className="text-xs text-slate-500 flex-1 truncate">{call.model}</span>
        {failed ? (
          <Badge className="bg-red-100 text-red-700 hover:bg-red-100">failed</Badge>
        ) : (
          <>
            <span className="text-xs tabular-nums text-slate-500 w-20 text-right">
              {call.input_tokens.toLocaleString()} in
            </span>
            <span className="text-xs tabular-nums text-slate-500 w-20 text-right">
              {call.output_tokens.toLocaleString()} out
            </span>
            <span className="text-xs tabular-nums text-slate-600 w-20 text-right">
              {ms(call.latency_ms)}
            </span>
            <span className="text-xs tabular-nums text-slate-600 w-20 text-right">
              {money(call.cost_usd)}
            </span>
          </>
        )}
      </button>

      {open && (
        <div className="px-5 pb-4 pt-1 bg-slate-50/60">
          {failed && call.status_message && (
            <div className="mb-3">
              <div className="text-xs font-medium text-slate-600 mb-1">Provider error</div>
              <pre className="text-xs bg-red-50 border border-red-200 text-red-900 rounded p-3 overflow-x-auto whitespace-pre-wrap">
                {call.status_message}
              </pre>
            </div>
          )}

          <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 mb-3 text-xs">
            <div>
              <div className="text-slate-500">Latency</div>
              <div className="tabular-nums text-slate-900">
                {failed ? '--' : ms(call.latency_ms)}
              </div>
            </div>
            <div>
              <div className="text-slate-500">Time to first token</div>
              <div className="tabular-nums text-slate-900">
                {call.time_to_first_token_ms ? ms(call.time_to_first_token_ms) : '--'}
              </div>
            </div>
            <div>
              <div className="text-slate-500">Tokens (in / out)</div>
              <div className="tabular-nums text-slate-900">
                {call.input_tokens.toLocaleString()} / {call.output_tokens.toLocaleString()}
              </div>
            </div>
            <div>
              <div className="text-slate-500">Cost</div>
              <div className="tabular-nums text-slate-900">{money(call.cost_usd)}</div>
            </div>
          </div>

          {call.output_preview ? (
            <div>
              <div className="text-xs font-medium text-slate-600 mb-1">
                Model output
                {call.output_truncated && (
                  <span className="font-normal text-slate-400">
                    {' '}
                    &mdash; first 400 characters
                  </span>
                )}
              </div>
              <pre className="text-xs bg-white border rounded p-3 overflow-x-auto whitespace-pre-wrap max-h-52 overflow-y-auto text-slate-700 font-mono leading-relaxed">
                {call.output_preview}
              </pre>
            </div>
          ) : (
            !failed && <div className="text-xs text-slate-400">No output captured.</div>
          )}
        </div>
      )}
    </div>
  );
};

const GuardianRunDetail = () => {
  const { traceId } = useParams();
  const navigate = useNavigate();

  const fetchRun = useCallback(async () => (await guardianApi.getLiveRun(traceId)).data, [traceId]);

  const { data: run, loading, refreshing, error, lastUpdated } = useLiveData(fetchRun, {
    intervalMs: 15000,
    refetchKey: traceId,
  });

  if (error && !run) toast.error('Run not found in Langfuse');

  if (loading) {
    return (
      <GuardianLayout>
        <div className="animate-pulse text-slate-600">Loading run...</div>
      </GuardianLayout>
    );
  }

  if (!run) {
    return (
      <GuardianLayout>
        <Button variant="ghost" size="sm" onClick={() => navigate('/live')} className="mb-4">
          <ArrowLeft className="h-4 w-4 mr-1" />
          Back to live activity
        </Button>
        <Card>
          <CardContent className="pt-6">
            <p className="text-sm text-slate-600">
              This run could not be loaded from Langfuse.
            </p>
          </CardContent>
        </Card>
      </GuardianLayout>
    );
  }

  const names = [...new Set(run.calls.map((c) => c.agent_name))];

  return (
    <GuardianLayout refreshing={refreshing} lastUpdated={lastUpdated}>
      <Button variant="ghost" size="sm" onClick={() => navigate('/live')} className="mb-4">
        <ArrowLeft className="h-4 w-4 mr-1" />
        Back to live activity
      </Button>

      <div className="flex items-start justify-between mb-5 gap-4">
        <div className="min-w-0">
          <div className="flex items-center gap-2 mb-1">
            <h2 className="text-xl font-semibold text-slate-900">{run.name}</h2>
            {run.error_count > 0 ? (
              <Badge className="bg-red-100 text-red-700 hover:bg-red-100">
                {run.error_count} failed {run.error_count === 1 ? 'call' : 'calls'}
              </Badge>
            ) : (
              <Badge className="bg-emerald-100 text-emerald-700 hover:bg-emerald-100">
                all calls succeeded
              </Badge>
            )}
          </div>
          <p className="text-xs text-slate-500 font-mono truncate">{run.id}</p>
          <p className="text-xs text-slate-500 mt-0.5">
            {new Date(run.started_at).toLocaleString()}
          </p>
        </div>
        {run.langfuse_url && (
          <a href={run.langfuse_url} target="_blank" rel="noreferrer" className="shrink-0">
            <Button variant="outline" size="sm">
              <ExternalLink className="h-4 w-4 mr-1" />
              Open in Langfuse
            </Button>
          </a>
        )}
      </div>

      <Card className="mb-5">
        <CardContent className="pt-5 grid grid-cols-2 sm:grid-cols-4 gap-6">
          <Field label="Duration" value={ms(run.latency_ms)} />
          <Field label="Calls" value={run.call_count} />
          <Field
            label="Failed"
            value={run.error_count}
            tone={run.error_count > 0 ? STATUS.critical : undefined}
          />
          <Field label="Cost" value={money(run.cost_usd)} />
        </CardContent>
      </Card>

      <Card className="mb-5">
        <CardHeader className="pb-3">
          <CardTitle className="text-base">Timeline</CardTitle>
          <CardDescription>
            Each call positioned by when it started and how long it ran.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <RunWaterfall calls={run.calls} names={names} />
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">Calls</CardTitle>
          <CardDescription>Click a call to see its output and token detail.</CardDescription>
        </CardHeader>
        <CardContent className="p-0">
          {run.calls.map((call, i) => (
            <CallRow key={call.id || i} call={call} names={names} index={i} />
          ))}
        </CardContent>
      </Card>
    </GuardianLayout>
  );
};

export default GuardianRunDetail;
