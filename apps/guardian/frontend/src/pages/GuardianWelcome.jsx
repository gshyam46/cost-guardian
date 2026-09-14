import { useState } from 'react';
import { ArrowRight, ArrowUpRight, Check, ChevronRight, CircleDot, Code2, Layers3, Play, Radio, ShieldCheck } from 'lucide-react';
import '@/product.css';

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

export function GuardianWordmark({ light = false }) {
  return <span className={`cg-wordmark ${light ? 'cg-wordmark-light' : ''}`}><span className="cg-mark" aria-hidden="true"><Layers3 size={19} strokeWidth={1.8} /></span><span className="cg-wordmark-weight">sillage<span className="cg-wordmark-dot">.</span></span></span>;
}

const formatCost = value => value === null ? 'Unknown' : `$${value.toFixed(5)}`;
const formatTime = value => value < 1000 ? `${value} ms` : `${(value / 1000).toFixed(2)} s`;

export function SampleTrace({ compact = false }) {
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
    <div className="cg-sample-footer"><span><ShieldCheck size={14} />Illustrative measurements. No customer data.</span><a href="/setup">Connect your app <ArrowRight size={14} /></a></div>
  </section>;
}

export default function GuardianWelcome({ demo = false, publicSite = false }) {
  return <div className="cg-public">
    <header className="cg-public-header"><a href="/welcome" aria-label="Sillage home"><GuardianWordmark /></a><nav aria-label="Public navigation"><a href="/welcome#how-it-works">How it works</a><a href="/demo" aria-current={demo ? 'page' : undefined}>Interactive demo</a>{publicSite && <a href="/signup">Join early access</a>}<a href="/signin">Sign in <ArrowUpRight size={14} /></a></nav><a className="cg-button-primary cg-header-cta" href={publicSite ? '/signup' : '/setup'}>{publicSite ? 'Join early access' : 'Connect your app'} <ArrowRight size={15} /></a></header>
    <main>
      {demo ? <section className="cg-demo-heading"><p className="cg-eyebrow">EXPLORE BEFORE YOU CONNECT</p><h1>Your first investigation.<br /><em>No setup required.</em></h1><p>Switch runs, select a call, inspect a rule and try a resolution. This sample workspace stays separate from your application.</p></section> : <section className="cg-hero"><div className="cg-hero-copy"><p className="cg-eyebrow"><span className="cg-status-dot cg-good" /> BUILT FOR TEAMS SHIPPING AI</p><h1>See what your<br />AI is <em>doing.</em></h1><p className="cg-hero-description">Follow your model calls. Understand token usage, reported spend and failures. Get from “something feels off” to the call that explains it.</p><div className="cg-hero-actions"><a className="cg-button-primary" href="/setup">Connect your app <ArrowRight size={17} /></a><a className="cg-button-secondary" href="/demo"><Play size={14} /> Explore the demo</a></div><p className="cg-hero-footnote">Python + Node helpers · Existing Langfuse support<br />Your model-provider key stays with your application.</p></div><div className="cg-hero-aside"><div className="cg-aside-rule"><span>FROM A CALL TO AN ANSWER</span><span>↓</span></div><div className="cg-hero-measurement"><span>Duration limit exceeded</span><strong>3.42<span>s</span></strong><p>One model call crossed its 2 s rule.<br />Now you know where to look.</p></div><div className="cg-aside-bottom"><Radio size={19} /><span>Capture → understand → investigate</span></div></div></section>}
      <div className={demo ? 'cg-demo-workspace' : 'cg-landing-workspace'}><SampleTrace compact={!demo} /></div>
      <section className="cg-how" id="how-it-works"><div><p className="cg-eyebrow">KNOW WHERE THE DATA COMES FROM</p><h2>Your app makes the call.<br /><em>Sillage makes it visible.</em></h2></div><div className="cg-how-steps"><article><span className="cg-step-number">01</span><h3>Connect the source</h3><p>Install the Python package and start your app with sillage-run, or use the manual Node integration. Already use Langfuse? Use its configured source workspace.</p></article><article><span className="cg-step-number">02</span><h3>Check a real call</h3><p>Run a normal app workflow. See received events, processing progress and the measurements that actually arrived. A connection test is optional.</p></article><article><span className="cg-step-number">03</span><h3>Follow the evidence</h3><p>Set call-level rules. Open an incident, inspect the observed run and record a resolution. Optionally route new incidents to Slack.</p></article></div></section>
      <section className="cg-boundaries"><div><span className="cg-eyebrow">WHAT YOU CAN SEE</span><h2>Useful measurements.<br />Clear limits.</h2><p>Direct capture records technical call labels, status, timing, tokens and any cost you explicitly report. Unknown values stay visible.</p></div><div className="cg-coverage-list">{['Call and model timelines', 'Input, output and total token usage', 'Reported cost with missing-data coverage', 'Saved rules and incident evidence'].map(item => <p key={item}><Check size={15} />{item}</p>)}<p className="cg-coverage-note">Direct capture does not collect raw prompts, responses or retrieved documents. The Python launcher and OpenAI helpers do not estimate USD prices. Full RAG tracing and self-service workspace provisioning are still in progress.</p></div></section>
      <section className="cg-start"><div><p className="cg-eyebrow">FROM EXPLORING TO OBSERVING</p><h2>{publicSite ? 'Help shape what comes next.' : 'Connect your first application.'}</h2><p>{publicSite ? <>Tell us what you're building and register your interest.<br />We'll keep you posted about early access.</> : <>Have workspace access? Sign in and follow the connection guide.<br />New to this deployment? Your workspace owner sets up your access.</>}</p></div><a className="cg-button-primary" href={publicSite ? '/signup' : '/setup'}>{publicSite ? 'Register your interest' : 'Start connecting'} <ChevronRight size={17} /></a></section>
    </main>
    <footer className="cg-public-footer"><GuardianWordmark /><span>The wake your AI leaves behind. Evidence you can inspect.</span>{publicSite && <a href="/privacy">Registration privacy</a>}<a href="/signin">Open your workspace <ArrowUpRight size={14} /></a></footer>
  </div>;
}
