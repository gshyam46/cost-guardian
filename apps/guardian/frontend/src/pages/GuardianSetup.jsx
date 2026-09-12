import { useCallback } from 'react';
import { Link } from 'react-router-dom';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import guardianApi from '@/services/guardianApi';
import useLiveData from '@/hooks/useLiveData';
import GuardianLayout from './GuardianLayout';
import DirectCaptureSetup from './DirectCaptureSetup';
import MonitoringPolicySetup from './MonitoringPolicySetup';
import NotificationSetup from './NotificationSetup';
import { useGuardianAccess } from '@/contexts/GuardianAccess';
import { validCapture } from '@/lib/captureModel';

const READ_STATES = {
  complete: 'Complete', partial: 'Partial', failed: 'Failed', pending: 'In progress',
  reading: 'Checking', not_polled: 'Not checked yet',
};
const WORKER_STATES = {
  complete: 'Complete', pending: 'Work pending', reading: 'Checking', stale: 'Stale',
  not_polled: 'Not checked yet', not_configured: 'Source not configured',
  detector_degraded: 'Checks need attention', read_blocked: 'Source read blocked',
  blocked: 'Processing blocked', source_configuration_changed: 'Configuration changed',
};
const READ_REASONS = {
  authentication_failed: 'The telemetry source rejected its configured credential.',
  not_configured: 'The telemetry source is not configured.',
  invalid_configuration: 'The telemetry source configuration needs correction.',
  unsupported_api: 'The source does not support the configured read interface.',
  rate_limited: 'The telemetry source is limiting requests.',
  upstream_error: 'The telemetry source could not complete the request.',
  read_timeout: 'The source read timed out.', source_timeout: 'The source read timed out.',
  source_busy: 'The source reader is busy.',
  quarantined_observations: 'Rejected or conflicting observations need review before relying on complete totals.',
  checkpoint_outside_window: 'The saved checkpoint is outside the supported window. An operator must plan a backfill.',
  legacy_metrics_migration_required: 'Existing totals require a planned accounting cutover.',
  query_mismatch: 'The source configuration changed during a saved traversal. An operator must review the change.',
};

const amount = (value) => Number.isSafeInteger(value) && value >= 0 ? value.toLocaleString('en-US') : 'Unknown';
const labelFor = (labels, key, fallback) => typeof key === 'string' && Object.prototype.hasOwnProperty.call(labels, key)
  ? labels[key] : fallback;
const Timestamp = ({ value }) => {
  if (value === null || value === undefined || value === '') return <>Not recorded</>;
  const parsed = typeof value === 'string' && /(?:Z|[+-]\d{2}:\d{2})$/.test(value) ? new Date(value) : null;
  if (!parsed || !Number.isFinite(parsed.getTime())) return <>Unknown timestamp</>;
  const utc = parsed.toISOString();
  return <time dateTime={utc}>{utc.replace('T', ' ').replace('Z', ' UTC')}</time>;
};
const Detail = ({ label, children }) => <div className="py-2">
  <dt className="text-xs text-slate-500">{label}</dt>
  <dd className="mt-1 text-sm text-slate-800 break-words">{children}</dd>
</div>;

export default function GuardianSetup() {
  const access = useGuardianAccess();
  const fetchCapture = useCallback(async ({ signal } = {}) => {
    const response = await guardianApi.getCapture({ signal });
    if (!validCapture(response?.data, access.project) || (response.data.mode === 'direct' && access.auth_mode !== 'oidc')) throw new Error('capture_response_unavailable');
    return response.data;
  }, [access.project, access.auth_mode]);
  const capture = useLiveData(fetchCapture);
  const direct = capture.data?.mode === 'direct';
  const legacy = capture.data?.mode === 'langfuse';
  const fetchMonitoring = useCallback(async ({ signal } = {}) => {
    const response = await guardianApi.getMonitoring({ signal });
    if (!response?.data || typeof response.data !== 'object' || Array.isArray(response.data)) {
      throw new Error('monitoring_response_unavailable');
    }
    return response.data;
  }, []);
  const { data, loading, refreshing, error, lastUpdated, reload } = useLiveData(fetchMonitoring, { enabled: legacy });
  const configured = data?.source_configured;
  const readState = data?.read_status || (data?.status === 'not_polled' ? 'not_polled' : null);
  const readLabel = labelFor(READ_STATES, readState, 'Unknown');
  const workerLabel = labelFor(WORKER_STATES, data?.status, 'Unknown');
  const noRecentRows = readState === 'complete' && data?.records_read === 0;
  const needsReview = (Number.isSafeInteger(data?.quarantined_records) && data.quarantined_records > 0) || data?.read_status === 'partial';

  return <GuardianLayout refreshing={direct ? capture.refreshing : refreshing} lastUpdated={direct ? capture.lastUpdated : lastUpdated}>
    <div className="flex flex-wrap items-start justify-between gap-4 mb-6">
      <div className="max-w-2xl">
        <h1 className="text-2xl font-semibold text-slate-900">Setup and monitoring</h1>
        <p className="mt-2 text-sm text-slate-600">
          Your credential grants access to Guardian. Source configuration, successful reads and processing progress are checked separately.
        </p>
      </div>
      <Button variant="outline" onClick={() => { capture.reload(); if (legacy) reload(); }} disabled={capture.loading || capture.refreshing || (legacy && (loading || refreshing))}>
        {capture.refreshing || (!direct && refreshing) ? 'Checking setup…' : 'Retry setup check'}
      </Button>
    </div>

    {capture.error && <div role="alert" className="mb-6 rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm text-amber-950">
      Capture setup is unavailable. Retry the setup check; current direct-capture configuration and receipt status cannot be established.
    </div>}
    {capture.loading && <p role="status" className="mb-4 text-sm text-slate-600">Checking capture configuration...</p>}
    {direct && <DirectCaptureSetup capture={capture.data} unavailable={!!capture.error} refreshCapture={capture.reload} />}

    {legacy && !capture.loading && <><Card className="mb-6">
      <CardContent className="py-4 text-sm text-slate-600">
        <p><strong className="text-slate-900">Existing source diagnostics are read-only.</strong> An operator must configure this deployment's telemetry source,
          and your application must emit its LLM call data. Use the repository's operator setup guide.</p>
        <p className="mt-2">This deployment uses its existing telemetry source. Direct capture requires a separately configured isolated project; source modes cannot be switched here. Do not enter provider secrets here or use your Guardian access key as an ingestion token.</p>
      </CardContent>
    </Card>

    {loading && <p role="status" className="text-sm text-slate-600">Checking monitoring diagnostics…</p>}
    {error && <div role="alert" className="mb-6 rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm text-amber-950">
      <p className="font-medium">Monitoring diagnostics are unavailable.</p>
      <p className="mt-1">Your access to Guardian is separate from these diagnostics. Retry the check or ask the deployment operator to investigate.</p>
      {data && <p className="mt-1">Showing previously fetched diagnostics. Current monitoring state is unknown.</p>}
    </div>}

    {!loading && data && <>
      {data.status === 'stale' && <div role="status" className="mb-6 rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm text-amber-950">
        <strong>Worker diagnostics are stale.</strong> The worker has not reported within its expected interval. Saved checkpoints do not establish current monitoring health.
      </div>}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <Card className="min-w-0"><CardHeader><CardTitle className="text-base">Source configuration</CardTitle></CardHeader>
          <CardContent>
            <p className="font-medium text-slate-900">{configured === true ? 'Configured' : configured === false ? 'Not configured' : 'Unknown'}</p>
            <p className="mt-2 text-sm text-slate-600">{configured === true
              ? 'A source configuration is present. This alone does not verify source access or arriving traffic.'
              : configured === false ? 'Telemetry setup is still required before Guardian can read your application calls.'
                : 'Source configuration could not be established from these diagnostics.'}</p>
            <dl className="mt-3">
              <Detail label="Last source checkpoint"><Timestamp value={data.source_watermark} /></Detail>
              <Detail label="Last source response"><Timestamp value={data.source_fetched_at} /></Detail>
            </dl>
          </CardContent>
        </Card>
        <Card className="min-w-0"><CardHeader><CardTitle className="text-base">Source reads</CardTitle></CardHeader>
          <CardContent>
            <p className="font-medium text-slate-900">{readLabel}</p>
            {readState === 'not_polled' && <p className="mt-2 text-sm text-slate-600">No source read has been reported yet.</p>}
            {configured === true && !data.source_watermark && <p className="mt-2 text-sm text-slate-600">No successful source checkpoint is recorded in these diagnostics.</p>}
            {noRecentRows && <p className="mt-2 text-sm text-slate-600">The latest successful read returned no observations. This does not establish that the project has never had traffic.</p>}
            {needsReview && <p className="mt-2 text-sm text-slate-600">The latest diagnostics include incomplete or rejected data. A saved checkpoint does not make that data complete.</p>}
            {data.read_error_code && <p className="mt-2 text-sm text-amber-900">{labelFor(READ_REASONS, data.read_error_code, 'The source check needs operator review.')}</p>}
            <dl className="mt-3">
              <Detail label="Rows read in latest poll">{amount(data.records_read)}</Detail>
              <Detail label="Pages read in latest poll">{amount(data.pages_fetched)}</Detail>
              <Detail label="Last worker attempt"><Timestamp value={data.last_attempt_at} /></Detail>
            </dl>
          </CardContent>
        </Card>
        <Card className="min-w-0"><CardHeader><CardTitle className="text-base">Processing</CardTitle></CardHeader>
          <CardContent>
            <p className="font-medium text-slate-900">{workerLabel}</p>
            <p className="mt-2 text-sm text-slate-600">Captured source data may still be waiting for checks or hourly totals to be rebuilt.</p>
            <dl className="mt-3">
              <Detail label="Last processing checkpoint"><Timestamp value={data.processing_watermark} /></Detail>
              <Detail label="Observations awaiting checks">{amount(data.pending_observations)}</Detail>
              <Detail label="Hourly totals awaiting rebuild">{amount(data.dirty_buckets)}</Detail>
              <Detail label="Rejected or conflicting records">{amount(data.quarantined_records)}</Detail>
            </dl>
          </CardContent>
        </Card>
      </div>
    </>}

    <section className="mt-6 max-w-2xl" aria-labelledby="setup-next-step">
      <h2 id="setup-next-step" className="text-base font-semibold text-slate-900">Check one instrumented workflow</h2>
      <p className="mt-2 text-sm text-slate-600">After operator setup, run a workflow in your application. Check its observed calls and measurements,
        then verify that source and processing checkpoints advance. Missing data and pending work need investigation before relying on totals.</p>
      <div className="mt-3 flex flex-wrap gap-4 text-sm">
        <Link className="underline underline-offset-4 text-slate-800" to="/live">View live activity</Link>
        <Link className="underline underline-offset-4 text-slate-800" to="/">View overview</Link>
      </div>
    </section></>}
    <MonitoringPolicySetup />
    <NotificationSetup />
  </GuardianLayout>;
}
