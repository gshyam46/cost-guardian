import { useCallback, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { ArrowLeft, ExternalLink, ChevronDown, ChevronRight } from 'lucide-react';
import GuardianLayout from './GuardianLayout';
import { RunWaterfall, STATUS, colorFor } from '@/components/Charts';
import guardianApi from '@/services/guardianApi';
import useLiveData from '@/hooks/useLiveData';
import { money, duration as ms, count, observedCost } from '@/lib/liveFormat';

const Field = ({ label, value, tone }) => (
  <div>
    <div className="text-xs text-slate-500 uppercase tracking-wide">{label}</div>
    <div className="text-lg font-semibold tabular-nums mt-0.5" style={{ color: tone || '#0f172a' }}>
      {value}
    </div>
  </div>
);

/** Inspect captured measurements and optional source-provided output previews. */
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
              {count(call.input_tokens)} in
            </span>
            <span className="text-xs tabular-nums text-slate-500 w-20 text-right">
              {count(call.output_tokens)} out
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
              <div className="text-xs font-medium text-slate-600 mb-1">Provider error
                {call.status_message_truncated && <span> — first 400 characters</span>}
              </div>
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
                {ms(call.time_to_first_token_ms)}
              </div>
            </div>
            <div>
              <div className="text-slate-500">Tokens (in / out)</div>
              <div className="tabular-nums text-slate-900">
                {count(call.input_tokens)} / {count(call.output_tokens)}
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

  const fetchRun = useCallback(async ({ signal } = {}) => (await guardianApi.getLiveRun(traceId, { signal })).data, [traceId]);

  const { data: run, loading, refreshing, error, lastUpdated } = useLiveData(fetchRun, {
    intervalMs: 15000,
    refetchKey: traceId,
  });

  if (loading || (run && run.id !== traceId && !error)) {
    return (
      <GuardianLayout>
        <div className="animate-pulse text-slate-600">Loading run...</div>
      </GuardianLayout>
    );
  }

  if (!run || run.id !== traceId || error?.response?.status === 404) {
    return (
      <GuardianLayout>
        <Button variant="ghost" size="sm" onClick={() => navigate('/live')} className="mb-4">
          <ArrowLeft className="h-4 w-4 mr-1" />
          Back to live activity
        </Button>
        <Card>
          <CardContent className="pt-6">
            <p className="text-sm text-slate-600">
              This trace is unavailable. Guardian could not read its telemetry.
            </p>
          </CardContent>
        </Card>
      </GuardianLayout>
    );
  }

  const names = [...new Set(run.calls.map((c) => c.agent_name))];
  const empty = run.calls.length === 0;
  const notObserved = run.observation_state === 'not_observed';

  return (
    <GuardianLayout refreshing={refreshing} lastUpdated={lastUpdated}>
      {(run.stale || error) && <Card className="mb-4 border-amber-200 bg-amber-50"><CardContent className="py-3">
        <p role="status">Showing stale trace data. The last successful read was {run.fetched_at || 'at an unknown time'}.</p>
      </CardContent></Card>}
      {run.coverage?.status !== 'complete' && <Card className="mb-4 border-amber-200 bg-amber-50"><CardContent className="py-3">
        <p role="status">Partial observation coverage. Counts and known costs describe accepted observations only.
          {' '}{count(run.coverage?.invalid_count)} rejected; {count(run.coverage?.duplicate_count)} repeated.
          {run.coverage?.truncated && <> The read budget allows up to {count(run.coverage.max_records)} records or {count(run.coverage.max_pages)} pages.</>}
          {run.coverage?.reason && <> Read status: {run.coverage.reason}.</>}
        </p>
      </CardContent></Card>}
      {run.aggregate_issues?.length > 0 && <Card className="mb-4 border-amber-200 bg-amber-50"><CardContent className="py-3">
        <p role="status">Some aggregate amounts exceed the supported numeric range and are shown as unknown.</p>
      </CardContent></Card>}
      {empty && <Card className="mb-4"><CardContent className="py-4">
        <p role="status">{notObserved ? 'No generation calls observed in this query window. This does not establish that the trace is missing.'
          : 'No accepted generation calls could be established from this partial read. Trace existence remains undetermined.'}</p>
        <p className="text-sm text-slate-500 mt-1">Spend, usage and workflow duration cannot be established from this read.</p>
      </CardContent></Card>}
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
                {run.error_count} observed {run.error_count === 1 ? 'error' : 'errors'}
              </Badge>
            ) : (
              <Badge variant="outline">
                {empty ? 'No accepted observations' : 'no errors observed'}
              </Badge>
            )}
          </div>
          <p className="text-xs text-slate-500 font-mono truncate">{run.id}</p>
          <p className="text-xs text-slate-500 mt-0.5">
            First observed call: {run.started_at ? new Date(run.started_at).toLocaleString() : 'Unknown'}
          </p>
          <p className="text-sm text-slate-500 mt-1">Workflow outcome unknown. LLM observations do not establish a completed customer operation.</p>
          <p className="text-xs text-slate-500 mt-2 break-words">Query window: last {run.window_hours || 168} hours, from {run.coverage?.window_start || 'unknown'} to {run.coverage?.window_end || 'unknown'}.</p>
          <p className="text-xs text-slate-500 mt-1">Source retention may shorten accessible history. A complete query covers accessible observations in this window; delayed telemetry may still arrive.</p>
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

      {!empty && <><Card className="mb-5">
        <CardContent className="pt-5 grid grid-cols-2 sm:grid-cols-4 gap-6">
          <Field label="Workflow duration" value="Unknown" />
          <Field label="Observed calls" value={run.call_count} />
          <Field
            label="Observed errors"
            value={run.error_count}
            tone={run.error_count > 0 ? STATUS.critical : undefined}
          />
          <Field label="Known observed cost" value={observedCost(run.cost_usd, run.known_cost_usd, run.cost_known_count)} />
        </CardContent>
        <CardContent><p className="text-xs text-slate-500">{count(run.cost_unknown_count)} observations missing cost;
          {' '}{count(run.tokens_unknown_count)} missing token totals; {count(run.latency_unknown_count)} missing duration.</p></CardContent>
      </Card>

      <Card className="mb-5">
        <CardHeader className="pb-3">
          <CardTitle className="text-base">Timeline</CardTitle>
          <CardDescription>
            Measured calls positioned by source start time and duration. Observations without a duration are not plotted.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <RunWaterfall calls={run.calls} names={names} />
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">Calls</CardTitle>
          <CardDescription>{run.source_kind === 'guardian_direct'
            ? 'Inspect terminal-call measurements. Direct capture does not collect prompts, outputs or document content.'
            : 'Click a call to inspect its captured measurements and available output.'}</CardDescription>
        </CardHeader>
        <CardContent className="p-0">
          {run.calls.map((call, i) => (
            <CallRow key={call.id || i} call={call} names={names} index={i} />
          ))}
        </CardContent>
      </Card></>}
    </GuardianLayout>
  );
};

export default GuardianRunDetail;
