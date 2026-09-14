import { useCallback, useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Card, CardContent, CardHeader } from '@/components/ui/card';
import { useGuardianAccess } from '@/contexts/GuardianAccess';
import useLiveData from '@/hooks/useLiveData';
import guardianApi, { captureRequestId, getGuardianApiOrigin, sendCaptureTest } from '@/services/guardianApi';
import { credentialList, validCreatedCredential, validCredential } from '@/lib/captureModel';
import { providerModules, providerRecipe } from '@/lib/providerRecipes';
import PythonLauncherSetup from './PythonLauncherSetup';

const count = (value) => Number.isSafeInteger(value) && value >= 0 ? value.toLocaleString('en-US') : 'Unknown';
const time = (value) => value ? new Date(value).toISOString().replace('T', ' ').replace('Z', ' UTC') : 'Not recorded';
const Row = ({ label, children }) => <div className="py-2"><dt className="text-xs text-ink-500">{label}</dt>
  <dd className="mt-1 text-sm text-ink-800 break-words">{children}</dd></div>;

const SetupStep = ({ id, number, title, description, state, open, toggle, children }) => <details id={`connection-${id}`}
  open={open} className="rounded-xl border border-ink-200 bg-card overflow-hidden scroll-mt-6">
  <summary onClick={(event) => { event.preventDefault(); toggle(); }} className="flex cursor-pointer list-none items-start gap-4 p-5 focus-visible:outline focus-visible:outline-2 focus-visible:outline-brick-700">
    <span aria-hidden="true" className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-ink-100 text-sm font-semibold text-ink-700">{number}</span>
    <span className="flex-1 min-w-0"><span className="block text-base font-semibold text-ink-900">{title}</span>
      <span className="mt-1 block text-sm text-ink-600">{description}</span><span className="mt-2 block text-xs text-ink-500 sm:hidden">{state}</span></span>
    <span className="shrink-0 text-xs text-ink-500 pt-1"><span className="hidden sm:inline">{state}</span><span aria-hidden="true" className="ml-3 text-lg">{open ? '−' : '+'}</span></span>
  </summary>
  <div className="border-t border-ink-100 p-5">{children}</div>
</details>;

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
    console.warn("Sillage receipt not confirmed", response.status);
  }
} catch {
  console.warn("Sillage receipt not confirmed; retry the same batch separately.");
}
// Export failure does not throw into your customer workflow.
// HTTP 202 confirms receipt, not completed processing.`;

function ManualProviderIntegration() {
  const [method, setMethod] = useState('openai');
  const [language, setLanguage] = useState('python');
  const [api, setApi] = useState('responses');
  const [streaming, setStreaming] = useState(false);
  const [copyStatus, setCopyStatus] = useState('');
  const version = useRef(0);
  useEffect(() => () => { version.current += 1; }, []);
  const change = (setter, value) => { version.current += 1; setCopyStatus(''); setter(value); };
  const code = providerRecipe(language, api, streaming);
  const captureOrigin = getGuardianApiOrigin();
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
  return <section aria-labelledby="provider-integration-title" className="text-sm text-ink-600 space-y-4">
      <div aria-label="Capture integration" className="flex flex-wrap gap-2">
        <Button variant={method === 'openai' ? 'default' : 'outline'} aria-pressed={method === 'openai'} onClick={() => change(setMethod, 'openai')}>OpenAI helpers</Button>
        <Button variant={method === 'custom' ? 'default' : 'outline'} aria-pressed={method === 'custom'} onClick={() => change(setMethod, 'custom')}>Other providers / custom JSON</Button>
      </div>
      <h2 id="provider-integration-title" className="font-semibold text-base text-ink-900">{method === 'openai' ? 'Connect your OpenAI calls' : 'Connect another provider'}</h2>
      <div hidden={method !== 'openai'} className="space-y-4">
      <p>Choose your application's language. Add the helper around an existing model call; it sends call duration, status and reported token usage to Sillage in the background. Keep your existing OpenAI client and provider key in your application.</p>
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
        <p><strong className="text-ink-900">1. Download the capture files.</strong> Extract these three files into your server application and keep them together. These are repository source modules, not published packages.</p>
        {captureOrigin ? <a href={`${captureOrigin}/api/guardian/integrations/${language}.zip`} download={`sillage-${language}.zip`}
          className="inline-flex items-center rounded-md border border-brick-800 px-4 py-2 font-medium text-brick-900 hover:bg-brick-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-brick-700">
          Download {language === 'python' ? 'Python' : 'Node'} helpers
        </a> : <p role="status">The capture address is unavailable. Retry workspace sign-in before downloading helpers.</p>}
        <ul className="list-disc pl-5 font-mono text-xs space-y-1">{providerModules(language).map((name) => <li key={name}>{name}</li>)}</ul>
        <p className="text-xs">Using a repository checkout? The same files are in <code>examples/native-capture/</code>. Keep your provider client and its credentials in your application.</p>
        <div className="flex flex-wrap items-end gap-4">
          <div><label htmlFor="provider-api" className="block mb-1">OpenAI API</label>
            <select id="provider-api" value={api} onChange={(event) => change(setApi, event.target.value)} className="border rounded-md bg-card px-3 py-2 text-ink-900">
              <option value="responses">Responses</option><option value="chat_completions">Chat Completions</option>
            </select></div>
          <label className="flex items-center gap-2 py-2"><input type="checkbox" checked={streaming} onChange={(event) => change(setStreaming, event.target.checked)} />Streaming response</label>
        </div>
        <div className="rounded-lg border border-ink-200 bg-ink-50 p-4">
          <p className="font-medium text-ink-900">2. Set these in your application's server configuration</p>
          <dl className="mt-3 space-y-3 text-xs">
            <div><dt className="font-mono font-semibold text-ink-800">GUARDIAN_URL</dt><dd className="mt-1">{captureOrigin || 'Unavailable'} — this Sillage deployment's base address, without /api.</dd></div>
            <div><dt className="font-mono font-semibold text-ink-800">GUARDIAN_INGEST_KEY</dt><dd className="mt-1">The ingestion key you create in step 1. This is not your OpenAI key or dashboard sign-in.</dd></div>
            <div><dt className="font-mono font-semibold text-ink-800">OPENAI_MODEL</dt><dd className="mt-1">The model your application already uses.</dd></div>
          </dl>
        </div>
        <p><strong className="text-ink-900">3. Wrap your existing call.</strong> Replace the existing-client, request-argument and stream-consumer variables with your application's own code. Use a technical agent/model label; do not put customer identifiers in metadata.</p>
        <Button variant="outline" onClick={copyCode}>Copy integration code</Button>
        {copyStatus && <p role="status">{copyStatus}</p>}
        <pre aria-label="OpenAI integration code" tabIndex={0} className="p-3 bg-ink-50 border rounded text-xs overflow-x-auto whitespace-pre-wrap break-words"><code>{code}</code></pre>
        <details className="rounded-lg border border-ink-200 p-3"><summary className="cursor-pointer font-medium text-ink-800">Runtime and streaming details</summary>
          <div className="mt-3 space-y-2 text-xs">
            <p>Create one exporter per long-running application process; reuse it across calls. Flush/close belongs in controlled shutdown, not after every call. Check exporter diagnostics for rejected or unconfirmed events; delivery is not guaranteed across a process crash.</p>
            {language === 'node' && <p>Use your existing <code>requestOptions</code> object, or an empty object when you have no request options. Pass the same AbortSignal to the provider and helper when cancellation is possible.</p>}
            {language === 'python' && <p>This recipe uses the synchronous client. For an async client use <code>async_openai_call</code>; async streams use <code>async_openai_stream</code> with <code>contextlib.aclosing</code> for early exit. During async shutdown, run the exporter's blocking close through <code>asyncio.to_thread</code>.</p>}
            {api === 'chat_completions' && <p>Chat Completions supports a single choice (<code>n=1</code>).{streaming && ' The recipe requests the final usage chunk with include_usage: true; missing or interrupted final usage stays unknown.'}</p>}
          </div>
        </details>
      </div>
      <p><strong>Token usage is reported; USD cost stays unknown.</strong> These adapters do not infer prices. Cost alerts need an independently known amount; unknown cost is never zero. Queued, incomplete or interrupted calls do not establish successful completion.</p>
      <p>After one real call, check the receipt and processing counts above, then open <Link to="/live" className="underline">captured activity</Link> and its run to verify tokens. Configure duration/error rules and Slack notifications below to turn a detected incident into an alert.</p>
      </div>
      {method === 'custom' && <p>Instrument completed calls from your existing provider client or framework. Sillage accepts the metadata contract below; an ingestion key alone does not capture calls automatically.</p>}
      <details open={method === 'custom' ? true : undefined}><summary className="cursor-pointer font-medium text-ink-900">Advanced: Sillage JSON version 1 · Node fetch example</summary>
        <div className="mt-3 space-y-3"><p>Use this manual sender from your existing background telemetry queue or job. It does not create a queue. Replace identifiers and UTC times with one completed call's values. Each application retry attempt gets its own observation ID; retrying delivery keeps the same batch and event body.</p>
          <p>Use test_mode: true for a handshake and test_mode: false for real call metadata. HTTP 202 is durable receipt, not completed processing or monitoring readiness.</p>
          <pre className="p-3 bg-ink-50 border rounded text-xs overflow-x-auto whitespace-pre-wrap break-words">{example}</pre>
          <p>Limit: 100 events and 256 KiB per batch; calls must start within the accepted 24-hour window. This raw JSON pattern can support other providers with explicit instrumentation.</p></div>
      </details>
  </section>;
}

function ProviderIntegration() {
  const [method, setMethod] = useState('launcher');
  return <div className="space-y-5">
    <div className="flex flex-wrap gap-2" aria-label="Choose an integration method">
      <Button aria-pressed={method === 'launcher'} variant={method === 'launcher' ? 'default' : 'outline'} onClick={() => setMethod('launcher')}>Python: install + run</Button>
      <Button aria-pressed={method === 'manual'} variant={method === 'manual' ? 'default' : 'outline'} onClick={() => setMethod('manual')}>Manual Python / Node</Button>
    </div>
    <p className="text-xs text-ink-500">Use one integration method for each call. Combining a manual wrapper with automatic capture can count it twice.</p>
    <div hidden={method !== 'launcher'}><PythonLauncherSetup /></div>
    <div hidden={method !== 'manual'}><ManualProviderIntegration /></div>
  </div>;
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
  const [openSteps, setOpenSteps] = useState({ keys: true, integrate: false, test: false, verify: false });
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
  const hasReceipt = !!status.last_received_at && status.received_events > 0;
  const hasProcessed = hasReceipt && status.processed_events > 0 && !!status.last_processed_at;
  const knownKeys = !keys.loading && !keys.error && keys.data;
  const activeKeys = knownKeys ? keys.data.filter((credential) => credential.status === 'active').length : null;
  const keyReady = !unavailable && (activeKeys > 0 || !!revealed);
  const connection = unavailable ? { label: 'Connection status unavailable', detail: 'Retry the setup check to see current receipt and processing status.', tone: 'amber' }
    : status.conflicted_events > 0 ? { label: 'Some events need review', detail: 'Conflicting events were received. Check the event identifiers in your exporter before relying on complete totals.', tone: 'amber' }
      : !hasReceipt ? (status.received_events === 0 && !status.last_received_at
        ? { label: 'Waiting for your first app call', detail: keyReady ? 'An ingestion key is available. Add it to your application, then run one instrumented workflow.' : 'Create an ingestion key below to connect your application.', tone: 'quiet' }
        : { label: 'Receipt timing is unconfirmed', detail: 'Check receipt and processing details below; the available counts do not establish a current application connection.', tone: 'quiet' })
        : status.worker_status !== 'current' ? { label: 'Events received · processing needs attention', detail: 'Your application reached Sillage. Ask your deployment operator to check the worker, then refresh this page.', tone: 'amber' }
          : status.pending_events > 0 ? { label: 'Events received · processing in progress', detail: 'Leave your application running. Refresh the receipt and processing counts to check that the backlog decreases.', tone: 'quiet' }
            : hasProcessed ? { label: 'Application events processed', detail: 'Open a captured run to check its measurements. Overview totals and incident checks can finish after inbox processing.', tone: 'teal' }
              : { label: 'Receipt recorded · processing unconfirmed', detail: 'Your application reached Sillage. Refresh the checks and verify its run before relying on totals.', tone: 'quiet' };
  const toggleStep = (id) => setOpenSteps((previous) => ({ ...previous, [id]: !previous[id] }));
  const showStep = (id) => {
    setOpenSteps((previous) => ({ ...previous, [id]: true }));
    document.getElementById(`connection-${id}`)?.scrollIntoView?.({ behavior: 'smooth', block: 'start' });
  };
  const stepProps = (id) => ({ id, open: openSteps[id] || (id === 'keys' && !!revealed), toggle: () => toggleStep(id) });

  return <section aria-labelledby="direct-capture-title" className="space-y-5">
    <Card className="border-ink-200 overflow-hidden"><CardHeader className="pb-3">
      <div className="flex flex-wrap items-center justify-between gap-3"><h2 id="direct-capture-title" className="font-semibold text-lg">Send events directly</h2>
        <span className="rounded-full bg-ink-100 px-3 py-1 text-xs font-medium text-ink-700">Direct capture · {capture.project.environment}</span></div>
      <p className="text-sm text-ink-600">{capture.project.name} · No Langfuse account needed</p>
      <p className="text-sm text-ink-600">Data source: your application → Sillage. Langfuse is not used by this workspace.</p>
    </CardHeader><CardContent className="space-y-5">
      <div className={`rounded-lg p-4 ${connection.tone === 'teal' ? 'bg-brick-50 text-brick-950' : connection.tone === 'amber' ? 'bg-ochre-50 text-ochre-950' : 'bg-ink-50 text-ink-800'}`}>
        <p className="font-semibold" data-testid="connection-status">{connection.label}</p><p className="mt-1 text-sm">{connection.detail}</p>
      </div>
      <dl className="grid grid-cols-1 sm:grid-cols-3 gap-x-5 border-b border-ink-100 pb-3">
        <Row label="Last app event received">{time(status.last_received_at)}</Row>
        <Row label="Waiting to process">{count(status.pending_events)}</Row>
        <Row label="Processing worker">{workerText}</Row>
      </dl>
      <ol aria-label="How application data reaches Sillage" className="grid grid-cols-1 sm:grid-cols-3 gap-4 text-sm">
        <li><span className="text-xs font-medium uppercase tracking-wider text-ink-500">01 · Your application</span><p className="mt-1 font-medium text-ink-900">An instrumented model call</p><p className="mt-1 text-ink-600">The installed library sends timing, status and usage.</p></li>
        <li><span className="text-xs font-medium uppercase tracking-wider text-ink-500">02 · Sillage collector</span><p className="mt-1 font-medium text-ink-900">Receipt is acknowledged</p><p className="mt-1 text-ink-600">Your app's ingestion key identifies this project.</p></li>
        <li><span className="text-xs font-medium uppercase tracking-wider text-ink-500">03 · Your dashboard</span><p className="mt-1 font-medium text-ink-900">Calls, runs and incident checks</p><p className="mt-1 text-ink-600">A worker processes accepted events into measurements.</p></li>
      </ol>
      <div className="flex flex-wrap items-center gap-2 border-t border-ink-100 pt-4">
        <Button variant="outline" onClick={() => showStep(hasReceipt ? 'verify' : keyReady ? 'integrate' : 'keys')}>{hasReceipt ? 'Check processing' : keyReady ? 'Integrate your app' : 'Connect your first app'}</Button>
        <Button variant="ghost" onClick={() => showStep('keys')}>Manage keys</Button>
        <span className="text-xs text-ink-500">{activeKeys === null ? 'Checking key status' : `${activeKeys} active ${activeKeys === 1 ? 'key' : 'keys'}`}</span>
      </div>
    </CardContent></Card>

    <div className="rounded-lg border border-ink-200 bg-card px-5 py-4 text-sm text-ink-600">
      <p className="font-medium text-ink-900">Which key is this asking for?</p>
      <p className="mt-1">Your sign-in gives you access to the dashboard. An <strong>ingestion key</strong> lets your application send telemetry to this project. Create that key here; Sillage does not need your OpenAI or other provider API key.</p>
      <details className="mt-3"><summary className="cursor-pointer text-xs font-medium text-ink-700">What data will appear?</summary>
        <p className="mt-2 text-xs">Only metadata is accepted. Prompts, outputs, documents, customer identifiers and provider secrets are not accepted. Missing cost or usage remains unknown. This connection sends completed LLM-call metadata; it does not automatically discover your application or capture every RAG step. This collector is not an OTLP endpoint.</p>
      </details>
    </div>

    <SetupStep {...stepProps('keys')} number="1" title="Create an application key" description="Give your backend permission to send call metadata."
      state={unavailable || keys.error ? 'Unknown' : keyReady ? 'Key available' : 'Start here'}>
      <h2 className="font-semibold text-base text-ink-900">Ingestion keys</h2>
      <p className="mt-2 text-sm text-ink-600">Write-only keys belong to this project and cannot read Sillage data. Signing out does not revoke them.</p>
      {!canManage && <p className="mt-2 text-sm text-ink-600">Only a current project owner can create or revoke ingestion keys. Members can inspect redacted status.</p>}
      {keys.loading && <p role="status" className="mt-3 text-sm">Loading ingestion key metadata...</p>}
      {keys.error && <p role="alert" className="mt-3 text-sm text-ochre-900">Ingestion key metadata is unavailable.{keys.data && ' Showing the last successful list; current key status is unknown.'}</p>}
      <Button className="mt-3" variant="outline" onClick={keys.reload} disabled={keys.loading || keys.refreshing}>Refresh key list</Button>
      {message && <p role="status" className="mt-3 text-sm text-ochre-900">{message}</p>}
      {canManage && !revealed && <form onSubmit={create} className="mt-4 space-y-3 max-w-lg">
        <div><label htmlFor="ingestion-label" className="block text-sm mb-1">Key label</label>
          <Input id="ingestion-label" value={label} onChange={(event) => setLabel(event.target.value)} maxLength={80} disabled={!!busy} placeholder="production-backend" /></div>
        <div><label htmlFor="ingestion-days" className="block text-sm mb-1">Expires in days (1–90)</label>
          <Input id="ingestion-days" type="number" min="1" max="90" step="1" value={days} onChange={(event) => setDays(event.target.value)} disabled={!!busy} /></div>
        {uncertainCreate && <div className="text-sm text-ochre-900"><p>After reviewing and revoking any unrecoverable key, you can start a new creation request.</p>
          <Button className="mt-2" variant="outline" type="button" disabled={!recoveryReady || keys.loading || keys.refreshing || !!keys.error || !!busy} onClick={() => { setUncertainCreate(false); failedSequence.current = null; setMessage(''); }}>I reviewed the key list</Button></div>}
        <Button type="submit" disabled={!!busy || !label.trim() || !Number.isInteger(Number(days)) || Number(days) < 1 || Number(days) > 90 || uncertainCreate || keys.loading || !!keys.error}>{busy === 'create' ? 'Creating key...' : 'Create ingestion key'}</Button>
      </form>}
      {revealed && <div className="mt-4 border border-ochre-300 bg-ochre-50 rounded-md p-4 space-y-3">
        <h3 className="font-semibold text-sm">Copy this key now</h3>
        <p className="text-sm">Shown once. Copy before leaving this page or switching away from the browser; session revalidation clears the display. Keep it in your application server secret configuration. Sending a test is optional.</p>
        <label htmlFor="one-time-ingestion-key" className="text-sm block">One-time ingestion key</label>
        <textarea id="one-time-ingestion-key" className="w-full border rounded p-2 font-mono text-xs break-all" rows={3} readOnly value={revealed.token} spellCheck={false} />
        <div className="flex flex-wrap gap-2"><Button onClick={copy}>Copy key</Button><Button variant="outline" onClick={dismiss}>Dismiss key</Button>
          <Button variant="outline" onClick={test} disabled={!!busy || !canManage}>{busy === 'test' ? 'Sending test...' : 'Send test event'}</Button></div>
        {copyMessage && <p role="status" className="text-sm">{copyMessage}</p>}
        {testMessage && <p role="status" className="text-sm">{testMessage}</p>}
        <Button variant="outline" onClick={() => showStep('integrate')}>Continue to install</Button>
      </div>}
      {!keys.loading && keys.data && <div className="mt-4 space-y-3">
        {keys.data.length === 0 && !revealed && <p className="text-sm text-ink-600">{keys.error ? 'The previous list contained no keys; current status is unknown.' : 'No ingestion keys have been created.'}</p>}
        {keys.data.map((credential) => <div key={credential.id} className="rounded-md border p-3">
          <div className="flex flex-wrap items-start justify-between gap-2"><div className="min-w-0"><p className="font-medium text-sm break-words">{credential.label}</p>
            <p className="font-mono text-xs mt-1">{credential.prefix} · {credential.status}</p></div>
            {canManage && credential.status !== 'revoked' && <Button variant="outline" size="sm" disabled={!!busy || !!keys.error} onClick={() => revoke(credential)} aria-label={`Revoke ${credential.label}`}>{busy === credential.id ? 'Revoking...' : 'Revoke'}</Button>}</div>
          <dl className="grid grid-cols-1 sm:grid-cols-2 gap-x-4"><Row label="Created">{time(credential.created_at)}</Row><Row label="Expires">{time(credential.expires_at)}</Row>
            <Row label="Last used">{time(credential.last_used_at)}</Row><Row label="Revoked">{time(credential.revoked_at)}</Row></dl>
        </div>)}
      </div>}
      <details className="mt-4 text-xs text-ink-600"><summary className="cursor-pointer font-medium text-ink-700">Rotate a key or disconnect an application</summary>
        <p className="mt-2">To rotate a key, create a replacement, update the application's server secret and verify a real receipt before revoking the old key. To stop new telemetry, stop the exporter or revoke every key used by that application. Revoking a key keeps already accepted data and does not delete project history.</p>
        <p className="mt-2">Expired keys must be replaced. Revoked keys cannot be restored. At most 10 active and 100 retained keys are allowed; use one descriptive label per backend or environment.</p>
      </details>
    </SetupStep>

    <SetupStep {...stepProps('integrate')} number="2" title="Install and start your app" description="Use the Python launcher, or choose a manual integration."
      state={hasReceipt && !unavailable ? 'Receipt observed' : 'Install + run'}>
      <ProviderIntegration />
    </SetupStep>

    <SetupStep {...stepProps('verify')} number="3" title="Verify your first real call" description="Follow one app call from receipt to its captured run."
      state={unavailable ? 'Unknown' : hasProcessed ? 'Processing observed' : hasReceipt ? 'Received' : 'Awaiting app call'}>
      <div className="space-y-4 text-sm text-ink-600">
        <p>Run one workflow in your application with capture enabled. Confirm a new receipt below, then open its run in captured activity and check the model, duration and token usage.</p>
        <dl className="grid grid-cols-1 sm:grid-cols-2 gap-x-5">
          <Row label="Latest real event receipt">{time(status.last_received_at)}</Row>
          <Row label="Last processing time">{time(status.last_processed_at)}</Row>
          <Row label="Accepted real events">{count(status.received_events)}</Row>
          <Row label="Processed events">{count(status.processed_events)}</Row>
          <Row label="Events awaiting processing">{count(status.pending_events)}</Row>
          <Row label="Conflicted events">{count(status.conflicted_events)}</Row>
          <Row label="Worker diagnostics">{workerText}</Row>
        </dl>
        <p className="text-xs">Counts cover this project's retained capture inbox, not the dashboard's selected time window.</p>
        {unavailable ? <p>These are previously fetched capture details. Current receipt and processing state is unknown.</p>
          : status.last_received_at ? <p>Real event receipt is recorded. Accepted data may still await checks and totals; receipt does not establish complete workflow coverage.</p>
            : status.received_events === 0 ? <p>No real event receipt is recorded. A successful test alone does not establish application traffic.</p>
              : <p>Receipt timing is unknown. Counts alone do not establish current application traffic.</p>}
        <div className="flex flex-wrap items-center gap-4"><Button variant="outline" onClick={refreshCapture}>Refresh receipt and processing</Button>
          <Link to="/live" className="underline underline-offset-4 text-brick-800">Open captured activity</Link>
          <Link to="/" className="underline underline-offset-4 text-brick-800">Open overview</Link></div>
        <details><summary className="cursor-pointer font-medium text-ink-800">I sent a call, but I don't see it</summary>
          <ol className="mt-3 list-decimal space-y-2 pl-5">
            <li>No receipt: check this deployment's URL, the server's ingestion key and exporter diagnostics. Verify the request was sent with test mode off.</li>
            <li>Receipt but pending processing: check that the worker is reporting and the pending count decreases.</li>
            <li>Activity but no Overview totals: verify the call's UTC time and the dashboard window, then allow checks and hourly totals to finish. Inbox processing alone does not confirm totals.</li>
            <li>Missing cost or tokens: Sillage only shows measurements the app sends. OpenAI helper recipes report available tokens but leave USD cost unknown.</li>
          </ol>
        </details>
      </div>
    </SetupStep>

    <SetupStep {...stepProps('test')} number="?" title="Optional: test your key" description="Check the collector separately from a real application call."
      state={unavailable ? 'Unknown' : status.last_test_received_at ? 'Test received' : 'Awaiting test'}>
      <div className="space-y-3 text-sm text-ink-600">
        <p>A test sends one empty metadata event. It checks the ingestion key and collector, and creates no production observations, totals or incidents.</p>
        <dl><Row label="Latest test receipt">{time(status.last_test_received_at)}</Row></dl>
        {revealed ? <><p>Use <strong>Send test event</strong> beside your newly created key. Do this before switching away from the browser.</p>
          <Button variant="outline" onClick={() => showStep('keys')}>Open key and send test</Button></>
          : <p>If you already stored a key, send a test from your application by setting <code>test_mode=True</code> in the Python exporter or <code>testMode: true</code> in Node. For raw JSON use <code>test_mode: true</code>. Existing secrets are never displayed again.</p>}
        <p>A browser test cannot verify network access from your application server. After testing, use <code>test_mode=False</code> / <code>testMode: false</code> for real call metadata.</p>
      </div>
    </SetupStep>

  </section>;
}
