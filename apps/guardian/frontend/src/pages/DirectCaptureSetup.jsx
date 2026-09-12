import { useCallback, useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Card, CardContent, CardHeader } from '@/components/ui/card';
import { useGuardianAccess } from '@/contexts/GuardianAccess';
import useLiveData from '@/hooks/useLiveData';
import guardianApi, { captureRequestId, sendCaptureTest } from '@/services/guardianApi';
import { credentialList, validCreatedCredential, validCredential } from '@/lib/captureModel';
import { providerModules, providerRecipe } from '@/lib/providerRecipes';

const count = (value) => Number.isSafeInteger(value) && value >= 0 ? value.toLocaleString('en-US') : 'Unknown';
const time = (value) => value ? new Date(value).toISOString().replace('T', ' ').replace('Z', ' UTC') : 'Not recorded';
const Row = ({ label, children }) => <div className="py-2"><dt className="text-xs text-slate-500">{label}</dt>
  <dd className="mt-1 text-sm text-slate-800 break-words">{children}</dd></div>;

const example = `// Invoke from your existing background telemetry queue/job.
// Keep this wait outside the model response path.
// This example does not create a background queue.
// Keep this batch and its IDs unchanged if retrying this request.
const batch = {
  schema_version: 1,
  batch_id: crypto.randomUUID(),
  test_mode: false,
  events: [{
    observation_id: "unique-completed-attempt-id",
    trace_id: "unique-workflow-id",
    agent_name: "answer-generator",
    model: "provider/model-name",
    started_at: "REPLACE_WITH_CALL_START_UTC",
    ended_at: "REPLACE_WITH_CALL_END_UTC",
    status: "success",
    cost_usd: null,
    input_tokens: null,
    output_tokens: null,
    total_tokens: null
  }]
};
try {
  const response = await fetch(
    process.env.GUARDIAN_URL + "/api/guardian/ingest/events", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Guardian-Ingest-Key": process.env.GUARDIAN_INGEST_KEY
      },
      body: JSON.stringify(batch),
      signal: AbortSignal.timeout(10000),
      redirect: "error"
    }
  );
  if (response.status !== 202) {
    console.warn("Guardian receipt not confirmed", response.status);
  }
} catch {
  console.warn("Guardian receipt not confirmed; retry the same batch separately.");
}
// Export failure does not throw into your customer workflow.
// HTTP 202 confirms receipt, not completed processing.`;

function ProviderIntegration() {
  const [language, setLanguage] = useState('python');
  const [api, setApi] = useState('responses');
  const [streaming, setStreaming] = useState(false);
  const [copyStatus, setCopyStatus] = useState('');
  const version = useRef(0);
  useEffect(() => () => { version.current += 1; }, []);
  const change = (setter, value) => { version.current += 1; setCopyStatus(''); setter(value); };
  const code = providerRecipe(language, api, streaming);
  const copyCode = async () => {
    const currentVersion = ++version.current;
    try {
      if (!navigator.clipboard?.writeText) throw new Error('clipboard_unavailable');
      await navigator.clipboard.writeText(code);
      if (currentVersion === version.current) setCopyStatus('Integration code copied. Adapt it at your existing application call site.');
    } catch {
      if (currentVersion === version.current) setCopyStatus('Clipboard access failed. Select and copy the integration code below.');
    }
  };
  return <Card><CardHeader><h2 className="font-semibold leading-none tracking-tight text-base">Connect your OpenAI calls</h2></CardHeader>
    <CardContent className="text-sm text-slate-600 space-y-4">
      <p>Capture Responses or Chat Completions usage without Langfuse. These helpers use your existing OpenAI client and forward its results, errors and stream objects. Prompts, outputs and raw errors stay outside Guardian.</p>
      <div role="tablist" aria-label="Integration language" className="flex gap-2">
        {['python', 'node'].map((value) => <Button key={value} role="tab" id={`provider-tab-${value}`} aria-controls="provider-recipe-panel"
          aria-selected={language === value} tabIndex={language === value ? 0 : -1} variant={language === value ? 'default' : 'outline'}
          onClick={() => change(setLanguage, value)} onKeyDown={(event) => {
            if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
            event.preventDefault();
            const next = event.key === 'Home' ? 'python' : event.key === 'End' ? 'node' : language === 'python' ? 'node' : 'python';
            change(setLanguage, next); document.getElementById(`provider-tab-${next}`)?.focus();
          }}>{value === 'python' ? 'Python' : 'Node'}</Button>)}
      </div>
      <div role="tabpanel" id="provider-recipe-panel" aria-labelledby={`provider-tab-${language}`} className="space-y-3">
        <p>Copy these three files from <code>examples/native-capture/</code> into your server application and keep them together. These are repository source modules, not published packages.</p>
        <ul className="list-disc pl-5 font-mono text-xs space-y-1">{providerModules(language).map((name) => <li key={name}>{name}</li>)}</ul>
        <div className="flex flex-wrap items-end gap-4">
          <div><label htmlFor="provider-api" className="block mb-1">OpenAI API</label>
            <select id="provider-api" value={api} onChange={(event) => change(setApi, event.target.value)} className="border rounded-md bg-white px-3 py-2 text-slate-900">
              <option value="responses">Responses</option><option value="chat_completions">Chat Completions</option>
            </select></div>
          <label className="flex items-center gap-2 py-2"><input type="checkbox" checked={streaming} onChange={(event) => change(setStreaming, event.target.checked)} />Streaming response</label>
        </div>
        <p>Set <code>GUARDIAN_URL</code>, <code>GUARDIAN_INGEST_KEY</code> and your application's <code>OPENAI_MODEL</code> in server-side configuration. Keep your existing provider credentials with your client. Create one exporter per long-running application process; reuse it across calls.</p>
        <p>Replace the existing-client, request-argument and stream-consumer variables with your application's own code. Use a technical agent/model label; do not put customer identifiers in metadata.</p>
        {language === 'node' && <p className="text-xs">Use your existing <code>requestOptions</code> object, or an empty object when you have no request options. Pass the same AbortSignal to the provider and helper when cancellation is possible.</p>}
        {language === 'python' && <p className="text-xs">This recipe uses the synchronous client. For an async client use <code>async_openai_call</code>; async streams use <code>async_openai_stream</code> with <code>contextlib.aclosing</code> for early exit. During async shutdown, run the exporter's blocking close through <code>asyncio.to_thread</code>.</p>}
        {api === 'chat_completions' && <p className="text-xs">Chat Completions supports a single choice (<code>n=1</code>).{streaming && ' The recipe requests the final usage chunk with include_usage: true; missing or interrupted final usage stays unknown.'}</p>}
        <Button variant="outline" onClick={copyCode}>Copy integration code</Button>
        {copyStatus && <p role="status">{copyStatus}</p>}
        <pre aria-label="OpenAI integration code" tabIndex={0} className="p-3 bg-slate-50 border rounded text-xs overflow-x-auto whitespace-pre-wrap break-words"><code>{code}</code></pre>
      </div>
      <p><strong>Token usage is reported; USD cost stays unknown.</strong> These adapters do not infer prices. Cost alerts need an independently known amount; unknown cost is never zero. Queued, incomplete or interrupted calls do not establish successful completion.</p>
      <p>After one real call, check the receipt and processing counts above, then open <Link to="/live" className="underline">captured activity</Link> and its run to verify tokens. Configure duration/error rules and Slack notifications below to turn a detected incident into an alert.</p>
      <p className="text-xs">The exporter submits metadata in the background. Check its diagnostics for rejected or unconfirmed events; it does not guarantee delivery across a process crash. Flush/close belongs in controlled shutdown, not after every call. A test receipt creates no production metrics or incidents.</p>
      <details><summary className="cursor-pointer font-medium text-slate-900">Advanced: Guardian JSON version 1 · Node fetch example</summary>
        <div className="mt-3 space-y-3"><p>Use this manual sender from your existing background telemetry queue or job. It does not create a queue. Replace identifiers and UTC times with one completed call's values. Each application retry attempt gets its own observation ID; retrying delivery keeps the same batch and event body.</p>
          <p>Use test_mode: true for a handshake and test_mode: false for real call metadata. HTTP 202 is durable receipt, not completed processing or monitoring readiness.</p>
          <pre className="p-3 bg-slate-50 border rounded text-xs overflow-x-auto whitespace-pre-wrap break-words">{example}</pre>
          <p>Limit: 100 events and 256 KiB per batch; calls must start within the accepted 24-hour window. This raw JSON pattern can support other providers with explicit instrumentation.</p></div>
      </details>
    </CardContent>
  </Card>;
}

export default function DirectCaptureSetup({ capture, unavailable = false, refreshCapture }) {
  const access = useGuardianAccess();
  const canManage = access.auth_mode === 'oidc' && access.actor?.role === 'owner' && capture.can_manage_keys && !unavailable;
  const [keysVersion, setKeysVersion] = useState(0);
  const [recoveryReady, setRecoveryReady] = useState(false);
  const listSequence = useRef(0);
  const failedSequence = useRef(null);
  const fetchKeys = useCallback(async ({ signal } = {}) => {
    const sequence = ++listSequence.current;
    const credentials = credentialList((await guardianApi.listIngestionKeys({ signal })).data);
    if (!signal?.aborted && failedSequence.current !== null && sequence > failedSequence.current) setRecoveryReady(true);
    return credentials;
  }, []);
  const keys = useLiveData(fetchKeys, { intervalMs: 15000, refetchKey: keysVersion });
  const [label, setLabel] = useState('');
  const [days, setDays] = useState('30');
  const [revealed, setRevealed] = useState(null);
  const [busy, setBusy] = useState('');
  const [message, setMessage] = useState('');
  const [copyMessage, setCopyMessage] = useState('');
  const [testMessage, setTestMessage] = useState('');
  const [uncertainCreate, setUncertainCreate] = useState(false);
  const work = useRef(null);
  const revealVersion = useRef(0);
  useEffect(() => () => { work.current?.abort(); revealVersion.current += 1; }, []);
  useEffect(() => {
    if (access.auth_mode !== 'oidc' || access.actor?.role !== 'owner' || !capture.can_manage_keys) {
      work.current?.abort(); work.current = null; revealVersion.current += 1;
      setBusy(''); setRevealed(null); setCopyMessage(''); setTestMessage('');
    }
  }, [access.auth_mode, access.actor?.role, capture.can_manage_keys]);

  const begin = (action) => {
    if (work.current) return null;
    const controller = new AbortController();
    work.current = controller;
    setBusy(action);
    setMessage('');
    return controller;
  };
  const current = (controller) => work.current === controller && !controller.signal.aborted;
  const finish = (controller) => { if (current(controller)) { work.current = null; setBusy(''); } };
  const dismiss = () => {
    revealVersion.current += 1;
    work.current?.abort(); work.current = null;
    setBusy(''); setRevealed(null); setCopyMessage(''); setTestMessage('');
  };
  const create = async (event) => {
    event.preventDefault();
    const expiry = Number(days);
    if (!canManage || revealed || uncertainCreate || keys.error || !label.trim() || label.trim().length > 80
        || !Number.isInteger(expiry) || expiry < 1 || expiry > 90) return;
    const controller = begin('create');
    if (!controller) return;
    try {
      const response = await guardianApi.createIngestionKey({ request_id: captureRequestId(), label: label.trim(), expires_in_days: expiry }, { signal: controller.signal });
      if (!current(controller)) return;
      if (response.status !== 201 || !validCreatedCredential(response.data)) throw new Error('unconfirmed_creation');
      revealVersion.current += 1;
      setRevealed({ credential: response.data.credential, token: response.data.token });
      setCopyMessage(''); setTestMessage(''); setLabel('');
      setKeysVersion((version) => version + 1); refreshCapture();
    } catch (error) {
      if (!current(controller)) return;
      if (error?.response?.status === 403) setMessage('Only the current project owner can manage ingestion keys. Access was denied.');
      else if (error?.response?.status === 429) setMessage('The key limit or request limit was reached. Review existing credentials before creating another.');
      else {
        setUncertainCreate(true);
        failedSequence.current = listSequence.current; setRecoveryReady(false);
        setKeysVersion((version) => version + 1);
        setMessage('Key creation was not confirmed. A key may have been created, but its secret cannot be recovered. Refresh the list, compare label and creation time, and revoke any unrecoverable key before creating another.');
      }
    } finally { finish(controller); }
  };
  const revoke = async (credential) => {
    if (!canManage) return;
    const controller = begin(credential.id);
    if (!controller) return;
    try {
      const response = await guardianApi.revokeIngestionKey(credential.id, { signal: controller.signal });
      if (!current(controller)) return;
      if (response.status !== 200 || !validCredential(response.data?.credential)
          || response.data.credential.id !== credential.id || response.data.credential.status !== 'revoked') throw new Error('unconfirmed_revocation');
      if (revealed?.credential.id === credential.id) { revealVersion.current += 1; setRevealed(null); setTestMessage(''); setCopyMessage(''); }
      setMessage('Key revoked. Already accepted events may still finish processing.');
      setKeysVersion((version) => version + 1); refreshCapture();
    } catch (error) {
      if (current(controller)) setMessage(error?.response?.status === 403
        ? 'Only the current project owner can manage ingestion keys. Access was denied.'
        : 'Revocation was not confirmed. The key may still accept events. Refresh the list and retry revocation if needed.');
    } finally { finish(controller); }
  };
  const copy = async () => {
    if (!revealed) return;
    const value = revealed.token;
    const version = revealVersion.current;
    try {
      if (!navigator.clipboard?.writeText) throw new Error('clipboard_unavailable');
      await navigator.clipboard.writeText(value);
      if (version === revealVersion.current) setCopyMessage('Copied. Store it in your application server secret configuration.');
    } catch { if (version === revealVersion.current) setCopyMessage('Clipboard access failed. Select the displayed key and copy it manually.'); }
  };
  const test = async () => {
    if (!revealed || !canManage) return;
    const controller = begin('test');
    if (!controller) return;
    setTestMessage('');
    try {
      await sendCaptureTest(revealed.token, { signal: controller.signal });
      if (!current(controller)) return;
      setTestMessage('Test event received. This handshake creates no production observations, totals or incidents and does not verify real application traffic.');
      refreshCapture(); setKeysVersion((version) => version + 1);
    } catch (error) {
      if (current(controller)) setTestMessage(error?.status === 401
        ? 'The ingestion key was rejected. Check its expiry or revocation status.'
        : 'The test receipt was not confirmed. Check the capture status before trying again.');
    } finally { finish(controller); }
  };
  const status = capture.status;
  const workerText = { not_started: 'Worker has not reported yet', current: 'Recent worker heartbeat', stale: 'Worker heartbeat is stale' }[status.worker_status];

  return <section aria-labelledby="direct-capture-title" className="space-y-5">
    <Card><CardHeader><h2 id="direct-capture-title" className="font-semibold leading-none tracking-tight text-lg">Send events directly</h2></CardHeader>
      <CardContent className="text-sm text-slate-600 space-y-3">
        <p>Send completed LLM-call metadata to this project without a Langfuse account. Integrate the Python or Node OpenAI helper below, or instrument another provider with Guardian JSON version 1. This collector is not an OTLP endpoint.</p>
        <p><strong>{capture.project.name}</strong> · {capture.project.environment} · Organization: {capture.project.organization_id}</p>
        <p>Only metadata is accepted. Prompts, outputs, documents, customer identifiers and provider secrets are not accepted. Missing cost or usage remains unknown.</p>
        <dl className="grid grid-cols-1 sm:grid-cols-2 gap-x-5">
          <Row label="Latest test receipt">{time(status.last_test_received_at)}</Row>
          <Row label="Latest real event receipt">{time(status.last_received_at)}</Row>
          <Row label="Accepted real events">{count(status.received_events)}</Row>
          <Row label="Events awaiting processing">{count(status.pending_events)}</Row>
          <Row label="Processed events">{count(status.processed_events)}</Row>
          <Row label="Conflicted events">{count(status.conflicted_events)}</Row>
          <Row label="Last processing time">{time(status.last_processed_at)}</Row>
          <Row label="Worker diagnostics">{workerText}</Row>
        </dl>
        {unavailable ? <p>These are previously fetched capture details. Current receipt and processing state is unknown.</p>
          : status.last_received_at ? <p>Real event receipt is recorded. Accepted data may still await checks and totals; receipt does not establish complete workflow coverage.</p>
            : status.received_events === 0 ? <p>No real event receipt is recorded. A successful test alone does not establish application traffic.</p>
              : <p>Receipt timing is unknown. Counts alone do not establish current application traffic.</p>}
        <p>Processing counts describe the inbox. Incident checks or hourly rebuilding may still be pending; verify the resulting <Link to="/" className="underline">overview</Link> and <Link to="/live" className="underline">captured activity</Link>.</p>
      </CardContent></Card>

    <Card><CardHeader><h2 className="font-semibold leading-none tracking-tight text-base">Ingestion keys</h2></CardHeader><CardContent>
      <p className="text-sm text-slate-600">Write-only keys belong to this project and cannot read Guardian data. Signing out does not revoke them. At most 10 active and 100 retained keys are allowed.</p>
      {!canManage && <p className="mt-2 text-sm text-slate-600">Only a current project owner can create or revoke ingestion keys. Members can inspect redacted status.</p>}
      {keys.loading && <p role="status" className="mt-3 text-sm">Loading ingestion key metadata...</p>}
      {keys.error && <p role="alert" className="mt-3 text-sm text-amber-900">Ingestion key metadata is unavailable.{keys.data && ' Showing the last successful list; current key status is unknown.'}</p>}
      <Button className="mt-3" variant="outline" onClick={keys.reload} disabled={keys.loading || keys.refreshing}>Refresh key list</Button>
      {message && <p role="status" className="mt-3 text-sm text-amber-900">{message}</p>}
      {canManage && !revealed && <form onSubmit={create} className="mt-4 space-y-3 max-w-lg">
        <div><label htmlFor="ingestion-label" className="block text-sm mb-1">Key label</label>
          <Input id="ingestion-label" value={label} onChange={(event) => setLabel(event.target.value)} maxLength={80} disabled={!!busy} placeholder="production-backend" /></div>
        <div><label htmlFor="ingestion-days" className="block text-sm mb-1">Expires in days (1–90)</label>
          <Input id="ingestion-days" type="number" min="1" max="90" step="1" value={days} onChange={(event) => setDays(event.target.value)} disabled={!!busy} /></div>
        {uncertainCreate && <div className="text-sm text-amber-900"><p>After reviewing and revoking any unrecoverable key, you can start a new creation request.</p>
          <Button className="mt-2" variant="outline" type="button" disabled={!recoveryReady || keys.loading || keys.refreshing || !!keys.error || !!busy} onClick={() => { setUncertainCreate(false); failedSequence.current = null; setMessage(''); }}>I reviewed the key list</Button></div>}
        <Button type="submit" disabled={!!busy || !label.trim() || !Number.isInteger(Number(days)) || Number(days) < 1 || Number(days) > 90 || uncertainCreate || keys.loading || !!keys.error}>{busy === 'create' ? 'Creating key...' : 'Create ingestion key'}</Button>
      </form>}
      {revealed && <div className="mt-4 border border-amber-300 bg-amber-50 rounded-md p-4 space-y-3">
        <h3 className="font-semibold text-sm">Copy this key now</h3>
        <p className="text-sm">Shown once. Copy before leaving this page or switching away from the browser; session revalidation clears the display. Keep it in your application server secret configuration.</p>
        <label htmlFor="one-time-ingestion-key" className="text-sm block">One-time ingestion key</label>
        <textarea id="one-time-ingestion-key" className="w-full border rounded p-2 font-mono text-xs break-all" rows={3} readOnly value={revealed.token} spellCheck={false} />
        <div className="flex flex-wrap gap-2"><Button onClick={copy}>Copy key</Button><Button variant="outline" onClick={dismiss}>Dismiss key</Button>
          <Button variant="outline" onClick={test} disabled={!!busy || !canManage}>{busy === 'test' ? 'Sending test...' : 'Send test event'}</Button></div>
        {copyMessage && <p role="status" className="text-sm">{copyMessage}</p>}
        {testMessage && <p role="status" className="text-sm">{testMessage}</p>}
      </div>}
      {!keys.loading && keys.data && <div className="mt-4 space-y-3">
        {keys.data.length === 0 && !revealed && <p className="text-sm text-slate-600">{keys.error ? 'The previous list contained no keys; current status is unknown.' : 'No ingestion keys have been created.'}</p>}
        {keys.data.map((credential) => <div key={credential.id} className="rounded-md border p-3">
          <div className="flex flex-wrap items-start justify-between gap-2"><div className="min-w-0"><p className="font-medium text-sm break-words">{credential.label}</p>
            <p className="font-mono text-xs mt-1">{credential.prefix} · {credential.status}</p></div>
            {canManage && credential.status !== 'revoked' && <Button variant="outline" size="sm" disabled={!!busy || !!keys.error} onClick={() => revoke(credential)} aria-label={`Revoke ${credential.label}`}>{busy === credential.id ? 'Revoking...' : 'Revoke'}</Button>}</div>
          <dl className="grid grid-cols-1 sm:grid-cols-2 gap-x-4"><Row label="Created">{time(credential.created_at)}</Row><Row label="Expires">{time(credential.expires_at)}</Row>
            <Row label="Last used">{time(credential.last_used_at)}</Row><Row label="Revoked">{time(credential.revoked_at)}</Row></dl>
        </div>)}
      </div>}
    </CardContent></Card>

    <ProviderIntegration />
  </section>;
}
