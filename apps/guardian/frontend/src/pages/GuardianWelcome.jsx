import { useState } from 'react';
import { ArrowDown, ArrowRight, ArrowUpRight, CircleDot, Code2, Play, ShieldCheck } from 'lucide-react';
import { GuardianWordmark } from '@/components/SillageBrand';
import '@/product.css';
import '@/landing.css';

export { GuardianWordmark } from '@/components/SillageBrand';

export const SAMPLE_RUNS = Object.freeze([
  { id: 'support', name: 'Support answer', state: 'Slow call', outcome: 'An answer took longer than the saved rule allows.', calls: [
    { name: 'Classify question', model: 'gpt-4.1-mini', ms: 280, input: 240, output: 32, cost: 0.0001472, state: 'Completed' },
    { name: 'Draft answer', model: 'gpt-4.1', ms: 3420, input: 1840, output: 386, cost: 0.006768, state: 'Slow call' },
    { name: 'Check answer', model: 'gpt-4.1-mini', ms: 410, input: 580, output: 46, cost: 0.0003056, state: 'Completed' },
  ] },
  { id: 'search', name: 'Document search', state: 'Completed', outcome: 'Both captured model calls completed. Retrieval contents are not captured.', calls: [
    { name: 'Rewrite question', model: 'gpt-4.1-mini', ms: 190, input: 160, output: 40, cost: 0.000128, state: 'Completed' },
    { name: 'Compose answer', model: 'gpt-4.1-mini', ms: 780, input: 1280, output: 210, cost: 0.000848, state: 'Completed' },
  ] },
  { id: 'handoff', name: 'Agent handoff', state: 'Reported error', outcome: 'The application reported an error. Missing usage and cost stay unknown.', calls: [
    { name: 'Route request', model: 'gpt-4.1-mini', ms: 240, input: 360, output: 28, cost: 0.0001888, state: 'Completed' },
    { name: 'Run specialist', model: 'gpt-4.1', ms: 1240, input: null, output: null, cost: null, state: 'Reported error' },
  ] },
]);

const formatCost = value => value === null ? 'Unknown' : `$${value.toFixed(5)}`;
const formatTime = value => value < 1000 ? `${value} ms` : `${(value / 1000).toFixed(2)} s`;

export function SampleTrace({ compact = false, publicSite = false }) {
  const [runId, setRunId] = useState('support');
  const [callIndex, setCallIndex] = useState(1);
  const [view, setView] = useState('trace');
  const [filter, setFilter] = useState('all');
  const [resolved, setResolved] = useState(false);
  const run = SAMPLE_RUNS.find(item => item.id === runId);
  const call = run.calls[callIndex];
  const selected = id => { setRunId(id); setCallIndex(id === 'search' ? 0 : 1); setView('trace'); setResolved(false); };
  const maxDuration = Math.max(...run.calls.map(item => item.ms));
  return <section className={`cg-sample ${compact ? 'cg-sample-compact' : ''}`} aria-label="Sample workspace">
    <div className="cg-sample-top"><span><CircleDot size={13} /> Sample workspace</span><span className="cg-sample-badge">DEMO DATA</span></div>
    <div className="cg-sample-body">
      <div className="cg-sample-title"><div><p className="cg-eyebrow">A CALL TELLS A STORY</p><h2>{run.id === 'support' ? 'A slow answer, explained.' : run.id === 'search' ? 'A search, step by step.' : 'A failed handoff, explained.'}</h2></div><span className="cg-sample-index">{String(SAMPLE_RUNS.findIndex(item => item.id === run.id) + 1).padStart(2, '0')} / 03</span></div>
      {!compact && <div className="cg-demo-filters" aria-label="Filter sample runs"><button aria-pressed={filter === 'all'} onClick={() => setFilter('all')}>All calls</button><button aria-pressed={filter === 'attention'} onClick={() => { setFilter('attention'); if (runId === 'search') selected('support'); }}>Needs attention</button></div>}
      <div className="cg-run-tabs" aria-label="Sample runs">{SAMPLE_RUNS.filter(item => filter === 'all' || item.state !== 'Completed').map(item => <button key={item.id} aria-pressed={run.id === item.id} onClick={() => selected(item.id)}><span className={`cg-status-dot ${item.state === 'Completed' ? 'cg-good' : item.state === 'Slow call' ? 'cg-warn' : 'cg-error'}`} />{item.name}</button>)}</div>
      <div className="cg-sample-summary"><span><strong>{run.calls.length}</strong> observed calls</span><span>{run.calls.some(item => item.cost === null) ? 'Partial cost coverage' : `${formatCost(run.calls.reduce((sum, item) => sum + item.cost, 0))} sample cost`}</span></div>
      {view === 'trace' ? <div className="cg-trace-grid">
        <div className="cg-waterfall" aria-label="Sample call timeline">{run.calls.map((item, index) => <button className="cg-trace-row" key={item.name} aria-pressed={index === callIndex} onClick={() => setCallIndex(index)}><span className="cg-trace-name"><Code2 size={14} />{item.name}</span><span className="cg-track"><span style={{ width: `${Math.max(5, item.ms / maxDuration * 100)}%` }} className={item.state === 'Completed' ? 'cg-bar-good' : item.state === 'Slow call' ? 'cg-bar-warn' : 'cg-bar-error'} /></span><span className="cg-trace-duration">{formatTime(item.ms)}</span></button>)}<p className="cg-timeline-caption">Select a call to inspect its measurements. Bars show call duration.</p></div>
        <div className="cg-call-detail" aria-label="Sample trace detail" aria-live="polite"><div className="cg-detail-head"><span className="cg-eyebrow">SELECTED CALL</span><span className={`cg-state ${call.state === 'Completed' ? '' : 'cg-state-attention'}`}>{call.state}</span></div><h3>{call.name}</h3><p className="cg-model">{call.model}</p><dl><div><dt>Duration</dt><dd>{formatTime(call.ms)}</dd></div><div><dt>Input / output tokens</dt><dd>{call.input === null ? 'Unknown' : `${call.input.toLocaleString()} / ${call.output.toLocaleString()}`}</dd></div><div><dt>Reported cost</dt><dd>{formatCost(call.cost)}</dd></div></dl><p className="cg-detail-note">{call.state === 'Slow call' ? '3.42 s exceeds the sample rule of 2.00 s. The recorded rule explains the incident.' : call.state === 'Reported error' ? 'The app reported a failure. No usage or price was supplied for this call.' : 'A completed call with known measurements. No sample rule was exceeded.'}</p>{call.state !== 'Completed' && <button className="cg-text-action" onClick={() => setView('incident')}>Inspect incident <ArrowUpRight size={14} /></button>}</div>
      </div> : <div className="cg-demo-incident" aria-live="polite"><span className="cg-eyebrow">SAMPLE INVESTIGATION</span><h3>{run.state === 'Completed' ? 'No incident for these calls' : resolved ? 'Sample incident resolved' : run.state === 'Slow call' ? 'Draft answer exceeded its duration limit' : 'Specialist call reported an error'}</h3><p>{run.outcome}</p><div className="cg-investigation-steps"><span><b>01</b> Inspect the captured measurement</span><span><b>02</b> Compare it with the saved rule</span><span><b>03</b> Record the resolution</span></div>{run.state !== 'Completed' && <button className="cg-button-primary" onClick={() => setResolved(true)} disabled={resolved}>{resolved ? 'Resolved in this demo' : 'Mark demo incident resolved'}</button>}<button className="cg-text-action" onClick={() => setView('trace')}>Back to trace <ArrowRight size={14} /></button><p className="cg-detail-note">Demo changes last only while this page is open. Resolution records an action; it does not fix the application.</p></div>}
    </div>
    <div className="cg-sample-footer"><span><ShieldCheck size={14} />Illustrative measurements. No customer data.</span><a href={publicSite ? '/signup' : '/setup'}>{publicSite ? 'Sign up' : 'Start tracking'} <ArrowRight size={14} /></a></div>
  </section>;
}

export default function GuardianWelcome({ demo = false, publicSite = false }) {
  const startUrl = publicSite ? '/signup' : '/setup';
  const startLabel = publicSite ? 'Sign up' : 'Start tracking';
  return <div className="sg-landing">
    <a className="sg-landing-skip" href="#main-content">Skip to content</a>
    <header className="sg-landing-header sg-landing-shell">
      <a className="sg-landing-brand" href={publicSite ? '/' : '/welcome'} aria-label="Sillage home"><GuardianWordmark /></a>
      <nav className="sg-landing-nav" aria-label="Public navigation">
        <a href="/welcome#how-it-works">How it works</a>
        <a href="/demo" aria-current={demo ? 'page' : undefined}>Interactive demo</a>
        <a href="/signin">Sign in <ArrowUpRight size={13} aria-hidden="true" /></a>
      </nav>
      <a className="sg-landing-button sg-landing-header-action" href={startUrl}>{startLabel}<ArrowRight size={15} aria-hidden="true" /></a>
    </header>
    <main id="main-content" className="sg-landing-shell">
      <section className={`sg-landing-intro ${demo ? 'sg-landing-intro-demo' : ''}`} aria-labelledby="landing-heading">
        <div>
          <p className="sg-landing-kicker">{demo ? 'THE SAMPLE WORKSPACE' : 'CLARITY FOR TEAMS BUILDING WITH AI'}</p>
          <h1 id="landing-heading">{demo ? <>Follow a call.<br /><em>Find the cause.</em></> : <>See the calls<br /><em>behind the answer.</em></>}</h1>
        </div>
        <div className="sg-landing-intro-note">
          <p>{demo ? 'A slow answer. A failed handoff. Start with a question, follow a call and inspect the evidence behind an incident.' : 'Understand where your application slows down, what each model call uses, and which failures need attention.'}</p>
          {demo ? <a className="sg-landing-text-link" href="#investigation">Try the investigation <ArrowDown size={16} aria-hidden="true" /></a> : <div className="sg-landing-actions"><a className="sg-landing-button" href={startUrl}>{startLabel}<ArrowRight size={17} aria-hidden="true" /></a><a className="sg-landing-text-link" href="/demo"><Play size={13} aria-hidden="true" /> Explore the demo</a></div>}
          <p className="sg-landing-fineprint">{demo ? 'No account or application connection needed. Every measurement below is illustrative.' : 'Your application makes the calls. Your model-provider key stays with your application.'}</p>
        </div>
      </section>

      <section id="investigation" className="sg-landing-investigation" aria-labelledby="investigation-heading">
        <div className="sg-landing-section-line"><span>01 / FOLLOW THE EVIDENCE</span><span>INTERACTIVE EXAMPLE <ArrowDown size={13} aria-hidden="true" /></span></div>
        <div className="sg-landing-investigation-intro"><h2 id="investigation-heading">An answer felt slow.<br /><em>Where did the time go?</em></h2><p>Select a run, then a call. Compare its measurements with the saved rule and try recording a resolution.</p></div>
        <SampleTrace compact={!demo} publicSite={publicSite} />
        <p className="sg-landing-margin-note">A resolution records your investigation. It does not fix the application or prove the whole workflow succeeded.</p>
      </section>

      <section id="how-it-works" className="sg-landing-workflow" aria-labelledby="workflow-heading">
        <div className="sg-landing-section-caption"><p className="sg-landing-kicker">02 / FROM YOUR APPLICATION</p><h2 id="workflow-heading">Keep building.<br /><em>Stay close to the details.</em></h2><p>Start with a supported source. Verify a real call. Build your understanding from what actually arrived.</p></div>
        <ol className="sg-landing-steps">
          <li><span aria-hidden="true">01</span><div><h3>Connect the way you work.</h3><p>Start your Python app with <code>sillage-run</code>, attach to existing OpenTelemetry, or use a configured Langfuse source. A manual Node integration is also available.</p></div></li>
          <li><span aria-hidden="true">02</span><div><h3>Follow a real call through.</h3><p>Run your application normally. Check receipt and processing, then inspect the captured timing, token usage and reported cost.</p></div></li>
          <li><span aria-hidden="true">03</span><div><h3>Turn a signal into an investigation.</h3><p>Set call-level rules, inspect the incident and its observed run, and record a resolution. Optional Slack delivery brings new incidents to your team.</p></div></li>
        </ol>
      </section>

      <section className="sg-landing-evidence" aria-labelledby="evidence-heading">
        <div className="sg-landing-section-caption"><p className="sg-landing-kicker">03 / KNOW WHAT YOU KNOW</p><h2 id="evidence-heading">Useful evidence.<br /><em>Honest boundaries.</em></h2></div>
        <div className="sg-landing-evidence-body"><dl className="sg-landing-ledger">
          <div><dt>Time</dt><dd>Call duration and latency, with missing measurements visible.</dd></div>
          <div><dt>Usage &amp; spend</dt><dd>Token counts and reported cost. Unknown values stay unknown.</dd></div>
          <div><dt>Failures</dt><dd>Reported errors, saved rules and the evidence behind an incident.</dd></div>
        </dl><p className="sg-landing-boundary-note"><ShieldCheck size={17} aria-hidden="true" /><span>Direct capture does not collect raw prompts, responses or retrieved documents. The Python launcher does not estimate USD prices. Full RAG tracing and self-service workspace provisioning are still in progress.</span></p></div>
      </section>

      <section className="sg-landing-start" aria-labelledby="start-heading"><div><p className="sg-landing-kicker">YOUR APPLICATION, IN VIEW</p><h2 id="start-heading">Make the next investigation clearer.</h2><p>{publicSite ? 'Sign up to register your details, or sign in to an existing workspace.' : 'Sign in to your workspace, connect a source and follow your first real call.'}</p></div><a className="sg-landing-button" href={startUrl}>{startLabel}<ArrowRight size={18} aria-hidden="true" /></a></section>
    </main>
    <footer className="sg-landing-footer sg-landing-shell"><a href={publicSite ? '/' : '/welcome'} aria-label="Sillage home"><GuardianWordmark /></a><p>The wake your AI leaves behind.</p><nav aria-label="Footer navigation">{publicSite && <a href="/privacy">Privacy</a>}<a href="/signin">Sign in <ArrowUpRight size={13} aria-hidden="true" /></a></nav></footer>
  </div>;
}
