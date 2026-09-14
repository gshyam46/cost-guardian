import { useEffect, useMemo, useState } from 'react';
import { ArrowRight, ArrowUpRight, Pause, Play, RotateCcw } from 'lucide-react';
import { SAMPLE_RUNS } from './sampleRuns';
import '@/evidence-demo.css';

const SAVED_RULE_MS = 2000;
const formatCost = value => value === null ? 'Unknown' : `$${value.toFixed(5)}`;
const formatTime = value => value < 1000 ? `${value} ms` : `${(value / 1000).toFixed(2)} s`;
const totalDuration = run => run.calls.reduce((sum, call) => sum + call.ms, 0);
const measurement = (call, lens) => lens === 'duration' ? call.ms
  : lens === 'cost' ? call.cost
    : call.input === null || call.output === null ? null : call.input + call.output;
const formatMeasurement = (value, lens) => value === null ? 'Unknown'
  : lens === 'duration' ? formatTime(value)
    : lens === 'cost' ? formatCost(value) : `${value.toLocaleString()} tokens`;
const stateClass = state => state === 'Completed' ? 'complete' : state === 'Slow call' ? 'slow' : 'error';

function SampleFlow({ run, captured, position, callIndex, onSelect }) {
  let elapsed = 0;
  const ends = run.calls.map(call => { elapsed += call.ms; return elapsed; });
  const coordinates = (index, vertical) => {
    const start = (index + .5) * 1000 / run.calls.length;
    const end = (index + 1.5) * 1000 / run.calls.length;
    return vertical
      ? [[80, start], [15, start + 85], [15, end - 85], [80, end]]
      : [[start, 100], [start + 85, 16], [end - 85, 16], [end, 100]];
  };
  const point = (points, progress) => [0, 1].map(axis =>
    Math.pow(1 - progress, 3) * points[0][axis]
    + 3 * Math.pow(1 - progress, 2) * progress * points[1][axis]
    + 3 * (1 - progress) * progress * progress * points[2][axis]
    + Math.pow(progress, 3) * points[3][axis]);
  return <div className="sg-evidence-flow" aria-label="Sample call flow" style={{ '--flow-count': run.calls.length }}>
    {[false, true].map(vertical => <svg className={`sg-evidence-flow-paths${vertical ? ' sg-evidence-flow-vertical' : ''}`} key={String(vertical)} viewBox={vertical ? '0 0 160 1000' : '0 0 1000 160'} preserveAspectRatio="none" fill="none" aria-hidden="true">
      {run.calls.slice(0, -1).map((call, index) => {
        const points = coordinates(index, vertical);
        const path = `M ${points[0]} C ${points[1]} ${points[2]} ${points[3]}`;
        const progress = Math.max(0, Math.min(1, (position - ends[index]) / (ends[index + 1] - ends[index])));
        const marker = point(points, progress);
        return <g key={call.name}>
          <path className="sg-evidence-flow-track" d={path} vectorEffect="non-scaling-stroke" />
          <path className="sg-evidence-flow-progress" d={path} pathLength="1" strokeDasharray="1" strokeDashoffset={1 - progress} vectorEffect="non-scaling-stroke" />
          {progress > 0 && progress < 1 && <circle className="sg-evidence-flow-marker" cx={marker[0]} cy={marker[1]} r={vertical ? 4 : 5} />}
        </g>;
      })}
    </svg>)}
    <div className="sg-evidence-flow-nodes">{run.calls.map((call, index) => <button className="sg-evidence-flow-node" type="button" key={call.name} aria-label={`Inspect ${call.name} in flow`} aria-pressed={index < captured && index === callIndex} disabled={index >= captured} onClick={() => onSelect(index)}>
      <span className="sg-evidence-flow-node-dot" aria-hidden="true"><span /></span>
      <span className="sg-evidence-flow-node-copy"><strong>{call.name}</strong><span>{index >= captured ? 'Waiting for capture' : index === callIndex ? 'In view' : 'Explore this call'}</span></span>
      <ArrowUpRight size={15} aria-hidden="true" />
    </button>)}</div>
  </div>;
}
export default function EvidenceDemo({ compact = false, publicSite = false }) {
  const [runId, setRunId] = useState('support');
  const [callIndex, setCallIndex] = useState(1);
  const [view, setView] = useState('trace');
  const [filter, setFilter] = useState('all');
  const [resolved, setResolved] = useState(false);
  const [lens, setLens] = useState('duration');
  const [position, setPosition] = useState(() => totalDuration(SAMPLE_RUNS[0]));
  const [playing, setPlaying] = useState(false);
  const [rule, setRule] = useState(SAVED_RULE_MS);
  const run = SAMPLE_RUNS.find(item => item.id === runId);
  const duration = totalDuration(run);
  const callEnds = useMemo(() => {
    let elapsed = 0;
    return run.calls.map(call => { elapsed += call.ms; return elapsed; });
  }, [run]);
  const captured = callEnds.filter(end => end <= position).length;
  const call = callIndex !== null && callIndex < captured ? run.calls[callIndex] : null;
  const maxMeasurement = Math.max(1e-10, ...run.calls.map(item => measurement(item, lens) ?? 0));
  const exceeding = run.calls.filter(item => item.ms > rule).length;

  // Playback is a local illustration in sample-list order, not a live trace clock.
  useEffect(() => {
    if (!playing) return undefined;
    const timer = window.setInterval(() => {
      setPosition(current => Math.min(duration, current + 100));
    }, 100);
    return () => window.clearInterval(timer);
  }, [playing, duration]);

  useEffect(() => {
    if (!playing) return;
    if (captured > 0) setCallIndex(captured - 1);
    if (position >= duration) setPlaying(false);
  }, [playing, captured, position, duration]);

  const selectRun = id => {
    const next = SAMPLE_RUNS.find(item => item.id === id);
    setPlaying(false);
    setRunId(id);
    setPosition(totalDuration(next));
    setCallIndex(id === 'search' ? 0 : 1);
    setView('trace');
    setResolved(false);
    setRule(SAVED_RULE_MS);
    setLens('duration');
  };
  const replay = () => {
    if (playing) { setPlaying(false); return; }
    if (position >= duration) { setPosition(0); setCallIndex(null); }
    setView('trace');
    setPlaying(true);
  };
  const scrub = value => {
    const parsed = Number(value);
    if (!Number.isFinite(parsed)) return;
    const next = Math.max(0, Math.min(duration, parsed));
    setPlaying(false);
    setPosition(next);
    const count = callEnds.filter(end => end <= next).length;
    setCallIndex(count > 0 ? count - 1 : null);
    setView('trace');
  };
  const restart = () => { setPlaying(false); setPosition(0); setCallIndex(null); setView('trace'); };
  const replayLabel = playing ? 'Pause replay' : position === 0 || position >= duration ? 'Replay sample' : 'Continue replay';
  const runIndex = SAMPLE_RUNS.findIndex(item => item.id === run.id) + 1;

  return <section className={`sg-evidence${compact ? ' sg-evidence-compact' : ''}`} aria-label="Sample workspace">
    <div className="sg-evidence-mast">
      <span className="sg-evidence-mast-name"><span className="sg-evidence-square" aria-hidden="true" />Sample workspace</span>
      <span className="sg-evidence-demo-label">DEMO DATA</span>
    </div>
    <div className="sg-evidence-heading">
      <div><h2>{run.id === 'support' ? 'A slow answer, explained.' : run.id === 'search' ? 'A search, step by step.' : 'A failed handoff, explained.'}</h2></div>
      <span className="sg-evidence-index">{String(runIndex).padStart(2, '0')} / 03</span>
    </div>
    <div className="sg-evidence-selection">
      {!compact && <div className="sg-evidence-filters" aria-label="Filter sample runs">
        <button type="button" aria-pressed={filter === 'all'} onClick={() => { setPlaying(false); setFilter('all'); }}>All calls</button>
        <button type="button" aria-pressed={filter === 'attention'} onClick={() => { setPlaying(false); setFilter('attention'); if (runId === 'search') selectRun('support'); }}>Needs attention</button>
      </div>}
      <div className="sg-evidence-runs" aria-label="Sample runs">{SAMPLE_RUNS.filter(item => filter === 'all' || item.state !== 'Completed').map(item => <button type="button" key={item.id} aria-pressed={run.id === item.id} onClick={() => selectRun(item.id)}><span className={`sg-evidence-status sg-evidence-${stateClass(item.state)}`} aria-hidden="true" />{item.name}</button>)}</div>
    </div>

    <div className="sg-evidence-playback" aria-label="Sample replay controls">
      <div className="sg-evidence-transport">
        <button className="sg-evidence-play" type="button" onClick={replay}>{playing ? <Pause size={14} aria-hidden="true" /> : <Play size={14} aria-hidden="true" />}{replayLabel}</button>
        <button className="sg-evidence-restart" type="button" onClick={restart} aria-label="Restart replay" title="Restart replay"><RotateCcw size={16} aria-hidden="true" /></button>
        <span className="sg-evidence-captured" aria-live="polite" aria-atomic="true">{captured} / {run.calls.length} calls captured</span>
      </div>
      <div className="sg-evidence-scrub">
        <input type="range" aria-label="Replay position" aria-valuetext={`${formatTime(position)} of ${formatTime(duration)}; ${captured} of ${run.calls.length} calls captured`} min="0" max={duration} step="10" value={position} onChange={event => scrub(event.target.value)} />
        <div className="sg-evidence-clock"><output aria-label="Replay elapsed">{formatTime(position)}</output><span>{formatTime(duration)}</span></div>
      </div>
      <p className="sg-evidence-playback-note">Illustrative replay. Sample-list order, using recorded durations.</p>
    </div>

    <SampleFlow run={run} captured={captured} position={position} callIndex={callIndex} onSelect={index => { setPlaying(false); setCallIndex(index); setView('trace'); }} />
    <div className="sg-evidence-toolbar">
      <div className="sg-evidence-summary"><span><strong>{run.calls.length}</strong> observed calls</span><span>{run.calls.some(item => item.cost === null) ? 'Partial cost coverage' : `${formatCost(run.calls.reduce((sum, item) => sum + item.cost, 0))} sample cost`}</span></div>
      <div className="sg-evidence-lenses" role="group" aria-label="Measurement lens">{['duration', 'tokens', 'cost'].map(item => <button type="button" key={item} aria-pressed={lens === item} onClick={() => setLens(item)}>{item[0].toUpperCase() + item.slice(1)}</button>)}</div>
    </div>

    {view === 'trace' ? <div className="sg-evidence-desk">
      <div className="sg-evidence-timeline" aria-label="Sample call timeline">
        <div className="sg-evidence-column-labels" aria-hidden="true"><span>OBSERVED CALL</span><span>{lens === 'duration' ? 'DURATION' : lens === 'tokens' ? 'TOTAL TOKENS' : 'REPORTED COST'}</span></div>
        {run.calls.map((item, index) => {
          const available = index < captured;
          const value = measurement(item, lens);
          return <button className={`sg-evidence-call${available ? '' : ' sg-evidence-pending'}`} type="button" key={item.name} aria-pressed={available && index === callIndex} disabled={!available} onClick={() => { setPlaying(false); setCallIndex(index); }}>
            <span className="sg-evidence-call-top"><span className="sg-evidence-call-name"><span className="sg-evidence-call-number" aria-hidden="true">{String(index + 1).padStart(2, '0')}</span>{item.name}</span><span className="sg-evidence-call-measurement">{available ? formatMeasurement(value, lens) : 'Pending'}</span></span>
            <span className={`sg-evidence-meter${available && value === null ? ' sg-evidence-meter-unknown' : ''}`} aria-hidden="true">{available && value !== null && <span className={`sg-evidence-meter-fill sg-evidence-${stateClass(item.state)}`} style={{ width: `${Math.max(0, value / maxMeasurement * 100)}%` }} />}</span>
          </button>;
        })}
        <p className="sg-evidence-caption">{lens === 'duration' ? 'Bars compare recorded call durations.' : lens === 'tokens' ? 'Bars compare input + output tokens. Missing usage stays unknown.' : 'Bars compare reported costs. Missing prices stay unknown.'} Select a captured call to inspect it.</p>
      </div>
      <div className="sg-evidence-detail" aria-label="Sample trace detail" aria-live="polite" aria-atomic="true">
        {call ? <>
          <div className="sg-evidence-detail-head"><span className="sg-evidence-label">SELECTED CALL</span><span className={`sg-evidence-state sg-evidence-state-${stateClass(call.state)}`}>{call.state}</span></div>
          <h3>{call.name}</h3><p className="sg-evidence-model">{call.model}</p>
          <dl><div><dt>Duration</dt><dd>{formatTime(call.ms)}</dd></div><div><dt>Input / output tokens</dt><dd>{call.input === null || call.output === null ? 'Unknown' : `${call.input.toLocaleString()} / ${call.output.toLocaleString()}`}</dd></div><div><dt>Reported cost</dt><dd>{formatCost(call.cost)}</dd></div></dl>
          <p className="sg-evidence-detail-note">{call.state === 'Slow call' ? '3.42 s exceeds the sample rule of 2.00 s. The recorded rule explains the incident.' : call.state === 'Reported error' ? 'The app reported a failure. No usage or price was supplied for this call.' : 'A completed call with known measurements. No sample rule was exceeded.'}</p>
          {call.state !== 'Completed' && <button className="sg-evidence-text-action" type="button" onClick={() => { setPlaying(false); setView('incident'); }}>Inspect incident <ArrowUpRight size={14} aria-hidden="true" /></button>}
        </> : <div className="sg-evidence-empty"><span className="sg-evidence-label">AWAITING EVIDENCE</span><h3>Waiting for a captured call.</h3><p>Play the sample or move the timeline forward. Measurements appear when a sample call completes.</p></div>}
      </div>
    </div> : <div className="sg-evidence-incident" aria-live="polite">
      <span className="sg-evidence-label">SAMPLE INVESTIGATION</span><h3>{run.state === 'Completed' ? 'No incident for these calls' : resolved ? 'Sample incident resolved' : run.state === 'Slow call' ? 'Draft answer exceeded its duration limit' : 'Specialist call reported an error'}</h3>
      <p>{run.outcome}</p>
      <ol className="sg-evidence-investigation-steps"><li>Inspect the captured measurement</li><li>Compare it with the saved rule</li><li>Record the resolution</li></ol>
      <div className="sg-evidence-incident-actions">{run.state !== 'Completed' && <button className="sg-evidence-action" type="button" onClick={() => setResolved(true)} disabled={resolved}>{resolved ? 'Resolved in this demo' : 'Mark demo incident resolved'}</button>}<button className="sg-evidence-text-action" type="button" onClick={() => setView('trace')}>Back to trace <ArrowRight size={14} aria-hidden="true" /></button></div>
      <p className="sg-evidence-detail-note">Demo changes last only while this page is open. Resolution records an action; it does not fix the application.</p>
    </div>}

    <div className="sg-evidence-rule" aria-label="Demo rule simulation">
      <div className="sg-evidence-rule-heading"><span className="sg-evidence-label">WHAT WOULD YOUR RULE CATCH?</span><h3>Try a duration limit.</h3><p>Compare all {run.calls.length} sample calls with a different threshold.</p></div>
      <div className="sg-evidence-rule-control">
        <div className="sg-evidence-rule-value"><label htmlFor={`demo-rule-${run.id}`}>Demo duration rule</label><output htmlFor={`demo-rule-${run.id}`}>{formatTime(rule)}</output></div>
        <input id={`demo-rule-${run.id}`} type="range" aria-label="Demo duration rule" aria-valuetext={formatTime(rule)} min="500" max="5000" step="100" value={rule} onChange={event => setRule(Math.max(500, Math.min(5000, Number(event.target.value))))} />
        <div className="sg-evidence-rule-scale" aria-hidden="true"><span>500 ms</span><span>5.00 s</span></div>
        <output className="sg-evidence-rule-result" aria-label="Demo rule comparison" aria-live="polite">{exceeding} of {run.calls.length} calls would exceed {formatTime(rule)}.</output>
        <div className="sg-evidence-rule-reset"><span>Recorded rule: 2.00 s</span><button type="button" onClick={() => setRule(SAVED_RULE_MS)} disabled={rule === SAVED_RULE_MS}>Reset demo rule</button></div>
      </div>
      <p className="sg-evidence-rule-note">Local comparison only. The recorded incident and its saved rule stay unchanged. Reported errors are unaffected.</p>
    </div>
    <div className="sg-evidence-footer"><span>Illustrative measurements. No customer data.</span><a href={publicSite ? '/signup' : '/setup'}>{publicSite ? 'Sign up' : 'Start tracking'} <ArrowRight size={14} aria-hidden="true" /></a></div>
  </section>;
}
