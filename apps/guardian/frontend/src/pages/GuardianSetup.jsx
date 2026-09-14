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
  <dt className="text-xs text-ink-500">{label}</dt>
  <dd className="mt-1 text-sm text-ink-800 break-words">{children}</dd>
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
        <p className="mb-2 text-xs font-medium uppercase tracking-wider text-brick-800">Application connection</p>
        <h1 className="text-3xl font-semibold tracking-tight text-ink-900">Connections</h1>
        <p className="mt-2 text-sm text-ink-600">
          Connect your app, see whether its calls arrive, and choose what should trigger an incident.
        </p>
      </div>
      <Button variant="outline" onClick={() => { capture.reload(); if (legacy) reload(); }} disabled={capture.loading || capture.refreshing || (legacy && (loading || refreshing))}>
        {capture.refreshing || (!direct && refreshing) ? 'Checking setup…' : 'Retry setup check'}
      </Button>
    </div>

    {capture.error && <div role="alert" className="mb-6 rounded-lg border border-ochre-200 bg-ochre-50 p-4 text-sm text-ochre-950">
      Capture setup is unavailable. Retry the setup check; current direct-capture configuration and receipt status cannot be established.
    </div>}
    {capture.loading && <p role="status" className="mb-4 text-sm text-ink-600">Checking capture configuration...</p>}
    {direct && <DirectCaptureSetup capture={capture.data} unavailable={!!capture.error} refreshCapture={capture.reload} />}

    {legacy && !capture.loading && <><Card className="mb-6">
      <CardHeader><div className="flex flex-wrap items-center justify-between gap-3"><CardTitle className="text-lg">Langfuse connection</CardTitle>
        <span className="rounded-full bg-ink-100 px-3 py-1 text-xs font-medium text-ink-700">Existing telemetry source</span></div></CardHeader>
      <CardContent className="py-4 text-sm text-ink-600">
        <p className="text-base font-medium text-ink-900">{error ? 'Connection status unavailable' : loading ? 'Checking connection evidence' : configured === false ? 'Waiting for source configuration' : configured === true ? `Source: ${readLabel.toLowerCase()} · Processing: ${workerLabel.toLowerCase()}` : 'Source status unavailable'}</p>
        <ol aria-label="How Langfuse data reaches Sillage" className="mt-5 grid grid-cols-1 sm:grid-cols-3 gap-4">
          <li><p className="font-medium text-ink-900">1. Your application</p><p className="mt-1">Sends its instrumented LLM calls to Langfuse.</p></li>
          <li><p className="font-medium text-ink-900">2. Configured Langfuse project</p><p className="mt-1">Sillage reads the observations using the operator's source configuration.</p></li>
          <li><p className="font-medium text-ink-900">3. Sillage dashboard</p><p className="mt-1">Captured activity shows source calls; the worker evaluates incidents and builds totals.</p></li>
        </ol>
        <details className="mt-5 rounded-lg bg-ink-50 p-4"><summary className="cursor-pointer font-medium text-ink-900">Manage this source connection</summary>
          <div className="mt-3 space-y-3"><p><strong className="text-ink-900">Existing source diagnostics are read-only.</strong> An operator must configure this deployment's telemetry source,
            and your application must emit its LLM call data. Use the repository's operator setup guide.</p>
            <p>This deployment uses its existing telemetry source. Direct capture requires a separately configured isolated project; source modes cannot be switched here. Do not enter provider secrets here or use your Sillage access key as an ingestion token.</p>
            <p>Your Sillage sign-in or access key opens this dashboard. It does not connect your application to Langfuse. To change the source project, rotate its credentials or disconnect it, ask the deployment operator to review the configured connection and its existing history.</p>
          </div>
        </details>
      </CardContent>
    </Card>

    {loading && <p role="status" className="text-sm text-ink-600">Checking monitoring diagnostics…</p>}
    {error && <div role="alert" className="mb-6 rounded-lg border border-ochre-200 bg-ochre-50 p-4 text-sm text-ochre-950">
      <p className="font-medium">Monitoring diagnostics are unavailable.</p>
      <p className="mt-1">Your access to Sillage is separate from these diagnostics. Retry the check or ask the deployment operator to investigate.</p>
      {data && <p className="mt-1">Showing previously fetched diagnostics. Current monitoring state is unknown.</p>}
    </div>}

    {!loading && data && <>
      {data.status === 'stale' && <div role="status" className="mb-6 rounded-lg border border-ochre-200 bg-ochre-50 p-4 text-sm text-ochre-950">
        <strong>Worker diagnostics are stale.</strong> The worker has not reported within its expected interval. Saved checkpoints do not establish current monitoring health.
      </div>}
      <details className="rounded-xl border border-ink-200 bg-card p-5" open>
      <summary className="cursor-pointer text-base font-semibold text-ink-900">Source receipt and processing details</summary>
      <div className="mt-4 grid grid-cols-1 lg:grid-cols-3 gap-4">
        <Card className="min-w-0"><CardHeader><CardTitle className="text-base">Source configuration</CardTitle></CardHeader>
          <CardContent>
            <p className="font-medium text-ink-900">{configured === true ? 'Configured' : configured === false ? 'Not configured' : 'Unknown'}</p>
            <p className="mt-2 text-sm text-ink-600">{configured === true
              ? 'A source configuration is present. This alone does not verify source access or arriving traffic.'
              : configured === false ? 'Telemetry setup is still required before Sillage can read your application calls.'
                : 'Source configuration could not be established from these diagnostics.'}</p>
            <dl className="mt-3">
              <Detail label="Last source checkpoint"><Timestamp value={data.source_watermark} /></Detail>
              <Detail label="Last source response"><Timestamp value={data.source_fetched_at} /></Detail>
            </dl>
          </CardContent>
        </Card>
        <Card className="min-w-0"><CardHeader><CardTitle className="text-base">Source reads</CardTitle></CardHeader>
          <CardContent>
            <p className="font-medium text-ink-900">{readLabel}</p>
            {readState === 'not_polled' && <p className="mt-2 text-sm text-ink-600">No source read has been reported yet.</p>}
            {configured === true && !data.source_watermark && <p className="mt-2 text-sm text-ink-600">No successful source checkpoint is recorded in these diagnostics.</p>}
            {noRecentRows && <p className="mt-2 text-sm text-ink-600">The latest successful read returned no observations. This does not establish that the project has never had traffic.</p>}
            {needsReview && <p className="mt-2 text-sm text-ink-600">The latest diagnostics include incomplete or rejected data. A saved checkpoint does not make that data complete.</p>}
            {data.read_error_code && <p className="mt-2 text-sm text-ochre-900">{labelFor(READ_REASONS, data.read_error_code, 'The source check needs operator review.')}</p>}
            <dl className="mt-3">
              <Detail label="Rows read in latest poll">{amount(data.records_read)}</Detail>
              <Detail label="Pages read in latest poll">{amount(data.pages_fetched)}</Detail>
              <Detail label="Last worker attempt"><Timestamp value={data.last_attempt_at} /></Detail>
            </dl>
          </CardContent>
        </Card>
        <Card className="min-w-0"><CardHeader><CardTitle className="text-base">Processing</CardTitle></CardHeader>
          <CardContent>
            <p className="font-medium text-ink-900">{workerLabel}</p>
            <p className="mt-2 text-sm text-ink-600">Captured source data may still be waiting for checks or hourly totals to be rebuilt.</p>
            <dl className="mt-3">
              <Detail label="Last processing checkpoint"><Timestamp value={data.processing_watermark} /></Detail>
              <Detail label="Observations awaiting checks">{amount(data.pending_observations)}</Detail>
              <Detail label="Hourly totals awaiting rebuild">{amount(data.dirty_buckets)}</Detail>
              <Detail label="Rejected or conflicting records">{amount(data.quarantined_records)}</Detail>
            </dl>
          </CardContent>
        </Card>
      </div></details>
    </>}

    <section className="mt-6 max-w-2xl" aria-labelledby="setup-next-step">
      <h2 id="setup-next-step" className="text-base font-semibold text-ink-900">Check one instrumented workflow</h2>
      <p className="mt-2 text-sm text-ink-600">After operator setup, run a workflow in your application. Check its observed calls and measurements,
        then verify that source and processing checkpoints advance. Missing data and pending work need investigation before relying on totals.</p>
      <div className="mt-3 flex flex-wrap gap-4 text-sm">
        <Link className="underline underline-offset-4 text-ink-800" to="/live">View live activity</Link>
        <Link className="underline underline-offset-4 text-ink-800" to="/">View overview</Link>
      </div>
    </section></>}
    <section className="mt-8 space-y-4" aria-labelledby="connection-alerts-title">
      <div><p className="text-xs font-medium uppercase tracking-wider text-ink-500">After your first call</p>
        <h2 id="connection-alerts-title" className="mt-2 text-xl font-semibold text-ink-900">Decide when to be notified</h2>
        <p className="mt-2 text-sm text-ink-600">Inspect your captured data first, then tune incident rules and an optional Slack destination.</p></div>
      <details id="connection-rules" className="rounded-xl border border-ink-200 bg-card p-5">
        <summary className="cursor-pointer text-base font-medium text-ink-900">Set monitoring rules <span className="ml-2 text-xs font-normal text-ink-500">Cost, duration and reported errors</span></summary>
        <MonitoringPolicySetup />
      </details>
      <details id="connection-notifications" className="rounded-xl border border-ink-200 bg-card p-5">
        <summary className="cursor-pointer text-base font-medium text-ink-900">Connect Slack notifications <span className="ml-2 text-xs font-normal text-ink-500">Optional · delivery status and retries</span></summary>
        <NotificationSetup />
      </details>
    </section>
  </GuardianLayout>;
}
