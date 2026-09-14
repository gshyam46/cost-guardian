import { useEffect, useRef, useState } from 'react';
import { Button } from '@/components/ui/button';
import { getGuardianApiOrigin } from '@/services/guardianApi';

export const PYTHON_WHEEL = 'sillage_observe-0.2.0-py3-none-any.whl';
const quote = (value, shell) => shell === 'powershell' ? `'${value.replaceAll("'", "''")}'` : `'${value.replaceAll("'", "'\\''")}'`;

export function launcherCommands(origin, shell = 'powershell', target = 'uvicorn', capture = 'openinference', layer = 'auto') {
  const values = { SILLAGE_URL: origin || '<your Sillage address>', SILLAGE_INGEST_KEY: '<your application key>', SILLAGE_SERVICE_NAME: 'my-ai-app' };
  if (origin?.startsWith('http://')) values.SILLAGE_ALLOW_LOCAL = 'true';
  const standards = capture !== 'native';
  const selected = ['auto', 'openai', 'litellm', 'langchain'].includes(layer) ? layer : 'auto';
  const launch = standards ? `sillage-run --instrumentation openinference --instrumentors ${selected}` : 'sillage-run';
  return {
    install: `python -m pip install ${standards ? quote(`./${PYTHON_WHEEL}[openinference]`, shell) : `./${PYTHON_WHEEL}`}`,
    configure: Object.entries(values).map(([name, value]) => shell === 'powershell'
      ? `$env:${name} = ${quote(value, shell)}` : `export ${name}=${quote(value, shell)}`).join('\n'),
    check: `${launch} --check`,
    run: `${launch} -- python ${target === 'uvicorn' ? '-m uvicorn server:app' : 'app.py'}`,
  };
}

export default function PythonLauncherSetup() {
  const [shell, setShell] = useState('powershell');
  const [target, setTarget] = useState('uvicorn');
  const [capture, setCapture] = useState('openinference');
  const [layer, setLayer] = useState('auto');
  const [copied, setCopied] = useState('');
  const version = useRef(0);
  useEffect(() => () => { version.current += 1; }, []);
  const origin = getGuardianApiOrigin();
  const commands = launcherCommands(origin, shell, target, capture, layer);
  const change = (setter, value) => { version.current += 1; setCopied(''); setter(value); };
  const copy = async name => {
    const current = ++version.current;
    try {
      if (!navigator.clipboard?.writeText) throw new Error();
      await navigator.clipboard.writeText(commands[name]);
      if (version.current === current) setCopied(`${name === 'install' ? 'Install command' : name === 'configure' ? 'Configuration template' : name === 'check' ? 'Compatibility check' : 'Launch command'} copied.`);
    } catch { if (version.current === current) setCopied('Clipboard access failed. Select and copy the displayed commands.'); }
  };
  const code = (name, label) => <div className="rounded-lg border bg-slate-50 overflow-hidden"><div className="flex items-center justify-between gap-3 border-b px-4 py-2"><span className="text-xs font-medium text-slate-600">{label}</span><Button size="sm" variant="ghost" onClick={() => copy(name)} aria-label={`Copy ${name} commands`}>Copy</Button></div><pre aria-label={label} tabIndex={0} className="p-4 text-xs overflow-x-auto whitespace-pre-wrap break-words"><code>{commands[name]}</code></pre></div>;
  return <section aria-labelledby="python-launcher-title" className="space-y-5 text-sm text-slate-600">
    <div><h2 id="python-launcher-title" className="text-lg font-semibold text-slate-900">Install once. Run your app with Sillage.</h2><p className="mt-2">Capture supported Python model calls without copying helper files or editing every call. Your application keeps its existing provider client, credentials and responses.</p><p className="mt-2 text-xs">OpenInference captures supported SDK or framework calls; Sillage preserves their trace and parent IDs. Agent names require supplied context. An unlabelled app uses your service name.</p></div>
    <div className="flex flex-wrap gap-4"><div><label htmlFor="launcher-shell" className="text-xs font-medium text-slate-700">Terminal</label><select id="launcher-shell" className="mt-1 block rounded-md border bg-white px-3 py-2 text-sm" value={shell} onChange={event => change(setShell, event.target.value)}><option value="powershell">PowerShell</option><option value="bash">Bash / zsh</option></select></div><div><label htmlFor="launcher-target" className="text-xs font-medium text-slate-700">How you start your app</label><select id="launcher-target" className="mt-1 block rounded-md border bg-white px-3 py-2 text-sm" value={target} onChange={event => change(setTarget, event.target.value)}><option value="uvicorn">Uvicorn / FastAPI</option><option value="script">Python script</option></select></div></div>
    <div className="flex flex-wrap gap-4"><div><label htmlFor="launcher-capture" className="text-xs font-medium text-slate-700">Capture method</label><select id="launcher-capture" className="mt-1 block rounded-md border bg-white px-3 py-2 text-sm" value={capture} onChange={event => change(setCapture, event.target.value)}><option value="openinference">OpenInference / OpenTelemetry</option><option value="native">Native compatibility</option></select></div>{capture === 'openinference' && <div><label htmlFor="launcher-layer" className="text-xs font-medium text-slate-700">Library your app calls</label><select id="launcher-layer" className="mt-1 block rounded-md border bg-white px-3 py-2 text-sm" value={layer} onChange={event => change(setLayer, event.target.value)}><option value="auto">Detect one compatible layer</option><option value="openai">OpenAI</option><option value="litellm">LiteLLM</option><option value="langchain">LangChain</option></select></div>}</div>
    <p className="text-xs">{capture === 'openinference' ? 'Select the library that owns your calls. Detection selects one compatible layer; it does not prove your app uses it. Combining overlapping instrumentors can duplicate calls or lose workflow grouping.' : 'The original native adapter remains available for OpenAI 1.99.9 and non-streaming LiteLLM 1.80.0. Use one capture method per call.'}</p>
    <div className="space-y-3"><h3 className="font-semibold text-slate-900">1. Install in your application's Python environment</h3><p>Download the wheel, activate your app's existing environment, and run this command from the download folder.</p>{origin ? <a className="inline-flex rounded-md bg-teal-900 px-4 py-2 font-medium text-white hover:bg-teal-800 focus-visible:outline focus-visible:outline-2 focus-visible:outline-teal-700" href={`${origin}/api/guardian/integrations/python.whl`} download={PYTHON_WHEEL}>Download Python package</a> : <p role="status">The capture address is unavailable. Retry workspace sign-in before downloading the package.</p>}{code('install', 'Install Sillage')}<p className="text-xs">The Sillage wheel is not published on PyPI. The OpenInference extra installs its tested open-source tracing dependencies; keep your app's model SDK and check dependency compatibility in its development environment.</p></div>
    <div className="space-y-3"><h3 className="font-semibold text-slate-900">2. Tell it where your calls belong</h3><p>Replace the placeholder with the key from <strong>Create an application key</strong> above. Keep these values in server-side configuration. Leave your model-provider settings as they are.</p>{code('configure', 'Sillage server configuration')}<p className="text-xs">The displayed template never includes your one-time key. The local HTTP flag appears only for this development address; production uses HTTPS.</p></div>
    <div className="space-y-3"><h3 className="font-semibold text-slate-900">3. Check compatibility, then start your original application</h3>{code('check', 'Check your Python environment')}<p className="text-xs">Check that the SDK your app uses reports <code>supported: true</code>. Fix configuration or compatibility errors before continuing. <code>--check</code> checks local settings only. It does not contact the collector or prove that a call arrived.</p><p>Return to your application's usual working folder. Replace <code>{target === 'uvicorn' ? 'server:app' : 'app.py'}</code> with your existing entry point and keep its normal arguments and port. Use the same Python environment, then trigger one normal model call.</p>{code('run', 'Start your app with Sillage')}</div>
    {copied && <p role="status" className="text-sm text-teal-900">{copied}</p>}
    <details className="rounded-lg border p-4"><summary className="cursor-pointer font-medium text-slate-800">Already using OpenTelemetry?</summary><div className="mt-3 space-y-3 text-xs"><p>Keep your existing instrumentation and provider. After installing the tracing extra and setting the Sillage configuration above, attach this processor once at startup. In this example, <code>provider</code> is your existing SDK TracerProvider.</p><pre aria-label="Existing OpenTelemetry integration" tabIndex={0} className="rounded border bg-slate-50 p-3 whitespace-pre-wrap break-words"><code>{`from sillage_observe import Configuration\nfrom sillage_observe.otel import SillageSpanProcessor\n\nprovider.add_span_processor(\n    SillageSpanProcessor(Configuration.from_env())\n)`}</code></pre><p>Keep your provider's normal flush/shutdown lifecycle and other exporters. Use this path instead of adding launcher instrumentation to the same calls. Only supported OpenInference/GenAI LLM spans become Sillage calls; this is not an OTLP receiver address.</p></div></details>
    <details className="rounded-lg border p-4"><summary className="cursor-pointer font-medium text-slate-800">Supported capture and limits</summary><div className="mt-3 space-y-2 text-xs"><p>Check the installed SDK and instrumentor versions with <code>--check</code>. LangChain capture covers its LLM callbacks; an arbitrary SDK call inside a generic function may need a different capture layer.</p><p>OpenInference can miss early-closed or cancelled streams when the upstream library never ends their span. Some Responses and LiteLLM calls arrive with unknown outcomes because terminal evidence is missing. Use native compatibility for its separately supported terminal handling; neither mode establishes complete workflow coverage.</p><p>Use one Python process. Reloaders, multiple workers, child processes and automatic Node instrumentation remain outside this launcher. Native LiteLLM streaming is not covered. The original app's provider dependencies remain required.</p><p>Captured fields are model, technical labels, actual trace/span/parent IDs, timing, status and available tokens. Prompts, answers, retrieved documents and provider keys stay out of this collector. Provider-side price estimates are ignored; cost remains unknown.</p><p>Agent, chain, tool and retrieval spans are not stored as LLM calls. A parent reference may point to an uncaptured framework span. Missing or late agent context uses the service name; a grouped trace does not prove a complete workflow or its success.</p><p>Delivery runs in a bounded background queue. Normal shutdown flushes it for a limited time; a killed process can lose pending telemetry.</p></div></details>
  </section>;
}
