import { useState } from 'react';
import { ArrowDown, ArrowRight, ArrowUpRight, Check, Plus } from 'lucide-react';
import { GuardianWordmark } from '@/components/SillageBrand';
import EvidenceDemo from '@/components/EvidenceDemo';
import '@/product.css';
import '@/landing.css';

export { GuardianWordmark } from '@/components/SillageBrand';
export { SAMPLE_RUNS } from '@/components/sampleRuns';

// Keep the public sample export used by existing consumers.
export function SampleTrace(props) {
  return <EvidenceDemo {...props} />;
}

const SOURCES = [
  {
    id: 'python', label: 'A Python application', description: 'No telemetry yet',
    heading: 'Start where the calls happen.',
    introduction: 'Install the Sillage package in your application environment and launch a supported Python app with sillage-run.',
    steps: [
      ['Your application', 'OpenAI, LiteLLM or LangChain LLM calls'],
      ['Sillage capture', 'Timing, status and available token counts'],
      ['Your workspace', 'Received calls, runs and rule evidence'],
    ],
    example: 'sillage-run --instrumentation openinference --instrumentors auto -- python app.py',
    exampleLabel: 'Launch command · after installation and configuration',
    note: 'Compatibility depends on the installed libraries. Check your environment first. One Python process; model-provider credentials stay with your application.',
  },
  {
    id: 'telemetry', label: 'Existing telemetry', description: 'OpenTelemetry or Langfuse',
    heading: 'Use the signal you already have.',
    introduction: 'Attach Sillage to an existing OpenTelemetry provider, or read model-call observations from a configured Langfuse source.',
    steps: [
      ['Your existing source', 'Supported LLM spans or Langfuse observations'],
      ['A configured connection', 'A span processor or the source reader'],
      ['Your workspace', 'Observed calls and source coverage'],
    ],
    example: 'Existing OpenTelemetry → Sillage span processor\nConfigured Langfuse → Sillage source reader',
    exampleLabel: 'Two connection paths · choose one for each call',
    note: 'The span processor accepts supported OpenInference / GenAI LLM spans. Langfuse uses a separately configured source mode. Neither path proves a complete application trace.',
  },
  {
    id: 'manual', label: 'Another application', description: 'Explicit integration',
    heading: 'Send the measurements you own.',
    introduction: 'Use the manual Node integration or the documented JSON interface to send a completed model call from your application.',
    steps: [
      ['Your application', 'One completed call or attempt'],
      ['An explicit event', 'Stable identity and supported measurements'],
      ['Your workspace', 'Receipt, processing and captured evidence'],
    ],
    example: 'Application → authenticated event intake\nWorker → measurements → rule evaluation',
    exampleLabel: 'Data path · application instrumentation required',
    note: 'This path requires an integration in your application. It does not automatically discover arbitrary apps, instrument Node packages or collect their contents.',
  },
];

function SourceExplorer({ startUrl, startLabel }) {
  const [sourceId, setSourceId] = useState('python');
  const source = SOURCES.find(item => item.id === sourceId);

  return <section id="how-it-works" className="sg-landing-sources" aria-labelledby="source-heading">
    <div className="sg-landing-source-intro">
      <p className="sg-landing-index">Connect your application</p>
      <h2 id="source-heading">A way in,<br />wherever you start.</h2>
      <p>Your application runs as usual. Sillage works with the measurements it sends.</p>
      <div className="sg-landing-source-options" role="group" aria-label="Explore connection paths">
        {SOURCES.map((item, index) => <button key={item.id} type="button" aria-pressed={sourceId === item.id} aria-controls="source-explanation" onClick={() => setSourceId(item.id)}>
          <span className="sg-landing-source-number" aria-hidden="true">0{index + 1}</span>
          <span><strong>{item.label}</strong><small>{item.description}</small></span>
          <ArrowUpRight size={18} aria-hidden="true" />
        </button>)}
      </div>
    </div>
    <div id="source-explanation" className="sg-landing-source-detail" aria-live="polite" aria-atomic="true">
      <div className="sg-landing-source-heading"><span className="sg-landing-index">{source.description}</span><h3>{source.heading}</h3><p>{source.introduction}</p></div>
      <ol className="sg-landing-flow" aria-label={`${source.label} data path`}>
        {source.steps.map(([label, detail], index) => <li key={label}><span className="sg-landing-flow-node" aria-hidden="true">{index === 2 ? <Check size={13} /> : '0' + (index + 1)}</span><div><strong>{label}</strong><span>{detail}</span></div></li>)}
      </ol>
      <div className="sg-landing-source-example"><p>{source.exampleLabel}</p><pre><code>{source.example}</code></pre></div>
      <p className="sg-landing-source-note">{source.note}</p>
      <a className="sg-landing-text-link" href={startUrl}>{startLabel}<ArrowRight size={15} aria-hidden="true" /></a>
    </div>
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
        <a href={demo ? '/welcome#how-it-works' : '#how-it-works'}>How it works</a>
        <a href="/demo" aria-current={demo ? 'page' : undefined}>Interactive demo</a>
        <a href="/signin">Sign in <ArrowUpRight size={13} aria-hidden="true" /></a>
      </nav>
      <a className="sg-landing-button sg-landing-header-action" href={startUrl}>{startLabel}<ArrowRight size={15} aria-hidden="true" /></a>
    </header>

    <main id="main-content" className="sg-landing-shell">
      <section className="sg-landing-intro" aria-labelledby="landing-heading">
        <div className="sg-landing-title-block">
          <p className="sg-landing-index sg-landing-intro-tag">{demo ? 'An investigation you can explore' : 'Your model calls, in context'}</p>
          <h1 id="landing-heading">{demo ? 'Follow a call. Find the cause.' : 'See the calls behind the answer.'}</h1>
        </div>
        <div className="sg-landing-intro-note">
          <p>{demo ? 'Replay a sample run, inspect a call and adjust a duration rule. See exactly what changes.' : 'Get to know what happens inside your AI app. Follow a model call, spot a slow step and find the details that help you improve it.'}</p>
          <div className="sg-landing-actions">
            <a className="sg-landing-button" href={startUrl}>{startLabel}<ArrowRight size={17} aria-hidden="true" /></a>
            <a className="sg-landing-text-link" href={demo ? '#investigation' : '/demo'}>{demo ? 'Try the investigation' : 'Explore the demo'}<ArrowDown size={15} aria-hidden="true" /></a>
          </div>
          <p className="sg-landing-fineprint">{demo ? 'Illustrative data. No account needed to explore.' : 'Your app makes the calls. Your provider key stays there.'}</p>
        </div>
      </section>

      <section id="investigation" className="sg-landing-investigation" aria-label="Interactive investigation">
        <div className="sg-landing-section-rule"><p className="sg-landing-index">Press play. Follow the wake.</p><span>Replay · inspect · compare<ArrowDown size={14} aria-hidden="true" /></span></div>
        <SampleTrace compact={!demo} publicSite={publicSite} />
      </section>

      <SourceExplorer startUrl={startUrl} startLabel={startLabel} />

      <section className="sg-landing-notes" aria-labelledby="evidence-heading">
        <div><p className="sg-landing-index">A few things to know</p><h2 id="evidence-heading">Keep the evidence<br />in perspective.</h2></div>
        <div className="sg-landing-questions">
          <details open><summary>What reaches the workspace?<Plus size={16} aria-hidden="true" /></summary><div><p>Call timing, model identity, reported status and available token counts. Check receipt and processing before treating a connection as working. Runs group the calls that arrived.</p></div></details>
          <details><summary>What does a cost tell me?<Plus size={16} aria-hidden="true" /></summary><div><p>Reported cost is shown when the source supplies it. Unknown values stay unknown. The Python launcher does not estimate USD prices, and a partial total does not establish your provider bill.</p></div></details>
          <details><summary>What stays outside the record?<Plus size={16} aria-hidden="true" /></summary><div><p>Direct capture does not collect raw prompts, responses or retrieved documents. Agent, tool and retrieval spans are not stored as model calls. A grouped run does not prove that the whole workflow succeeded.</p></div></details>
          <details><summary>What happens after a rule is exceeded?<Plus size={16} aria-hidden="true" /></summary><div><p>Inspect the incident and its captured measurements, then record a resolution. Optional Slack delivery brings new incidents to your team. Resolving an incident records an action; it does not repair the application.</p></div></details>
        </div>
      </section>

      <section className="sg-landing-start" aria-labelledby="start-heading"><div><h2 id="start-heading">Put your next call in view.</h2><p>{publicSite ? 'Sign up, or sign in to your existing workspace.' : 'Connect a source and inspect your first real call.'}</p></div><a className="sg-landing-button" href={startUrl}>{startLabel}<ArrowRight size={18} aria-hidden="true" /></a></section>
    </main>

    <footer className="sg-landing-footer sg-landing-shell"><a href={publicSite ? '/' : '/welcome'} aria-label="Sillage home"><GuardianWordmark /></a><p>The wake your AI leaves behind.</p><nav aria-label="Footer navigation">{publicSite && <a href="/privacy">Privacy</a>}<a href="/signin">Sign in <ArrowUpRight size={13} aria-hidden="true" /></a></nav></footer>
  </div>;
}
