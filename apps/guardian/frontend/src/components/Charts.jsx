import { useState } from 'react';
import { isKnown, money, duration, count } from '@/lib/liveFormat';

/**
 * Dependency-free inline SVG/HTML charts for the live dashboard.
 *
 * Still no charting library, for the reason MiniChart.jsx gives: these are a handful
 * of forms, and a library would be more configuration than code. What is new here vs
 * MiniChart is that these carry a hover layer -- an HTML chart is interactive by
 * nature, and a bar the user cannot interrogate is throwing away the medium.
 *
 * Colour: the five agent slots below are the first five categorical hues of the
 * validated reference palette, in fixed order. Three of them sit under 3:1 against a
 * light surface, so every bar here ships a visible direct label -- the documented
 * relief for that, and the reason no value in this file is encoded by colour alone.
 * Colour follows the agent, never its rank, so filtering the set never repaints the
 * survivors.
 */

export const SERIES = ['#2a78d6', '#eb6834', '#1baf7a', '#eda100', '#e87ba4'];

export const STATUS = {
  good: '#0ca30c',
  warning: '#fab219',
  critical: '#d03b3b',
};

/** Stable colour per name, so an agent keeps its hue across every chart on the page. */
export const colorFor = (name, names) => {
  const index = names.indexOf(name);
  return SERIES[(index < 0 ? 0 : index) % SERIES.length];
};

const Empty = ({ label }) => (
  <div className="h-32 flex items-center justify-center text-xs text-slate-400">
    No {label} yet
  </div>
);

/**
 * Horizontal bars, one row per category.
 *
 * Horizontal rather than vertical because the categories are agent names -- long,
 * variable-length text that would need rotating under a vertical axis, and rotated
 * labels are a readability tax paid on every glance.
 */
export const BarList = ({ rows, valueKey, format, label, names }) => {
  const [hovered, setHovered] = useState(null);
  if (!rows || rows.length === 0) return <Empty label={label} />;

  const max = Math.max(...rows.map((r) => r[valueKey]).filter(isKnown), 0) || 1;

  return (
    <div className="space-y-2.5">
      {rows.map((row) => {
        const pct = isKnown(row[valueKey]) ? (row[valueKey] / max) * 100 : 0;
        const isHovered = hovered === row.name;
        return (
          <div
            key={row.name}
            className="group cursor-default"
            onMouseEnter={() => setHovered(row.name)}
            onMouseLeave={() => setHovered(null)}
          >
            <div className="flex items-center justify-between text-xs mb-1">
              <span className="flex items-center gap-1.5 text-slate-600 font-medium">
                <span
                  className="h-2 w-2 rounded-sm shrink-0"
                  style={{ backgroundColor: colorFor(row.name, names) }}
                />
                {row.name}
              </span>
              {/* The direct label is not decoration: it is the relief that lets these
                  hues be used on a light surface at all. */}
              <span className="text-slate-900 font-semibold tabular-nums">
                {format(row[valueKey])}
              </span>
            </div>
            <div className="h-2 w-full rounded-full bg-slate-100 overflow-hidden">
              <div
                className="h-full rounded-full transition-all duration-300"
                style={{
                  width: `${pct}%`,
                  backgroundColor: colorFor(row.name, names),
                  opacity: hovered && !isHovered ? 0.45 : 1,
                }}
              />
            </div>
            {isHovered && (
              <div className="mt-1 text-[11px] text-slate-500 tabular-nums">
                {row.calls} calls · {row.errors} errors · {count(row.tokens)} tokens ·
                avg {duration(row.avg_latency_ms)} · {count(row.cost_unknown_count)} costs unknown
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
};

/**
 * Per-call latency over time, newest on the right.
 *
 * Dots rather than a line: these are discrete calls by different agents, not samples
 * of one continuous signal, and joining them would imply a continuity that does not
 * exist. Only known durations are plotted; errors have hollow rings at their measured
 * duration. Missing timing evidence never becomes a zero-duration point.
 */
export const LatencyScatter = ({ calls, names }) => {
  const [hovered, setHovered] = useState(null);
  if (!calls || calls.length === 0) return <Empty label="calls" />;

  const width = 720;
  const height = 160;
  const pad = { top: 12, right: 12, bottom: 20, left: 46 };
  const ordered = [...calls].filter((c) => isKnown(c.latency_ms)).reverse();
  if (ordered.length === 0) return <Empty label="measured durations" />;
  const max = Math.max(...ordered.map((c) => c.latency_ms), 1000);

  // Log scale, because LLM latency routinely spans two orders of magnitude in one
  // window -- a 300ms call and an 81s outlier in the same series. On a linear axis the
  // outlier owns the whole range and flattens every other call onto the baseline,
  // which hides exactly the variation the chart exists to show. Ticks are labelled in
  // real units so the compression stays visible rather than implied.
  const MIN = 100; // floor: below this the axis is noise, not signal
  const logMin = Math.log10(MIN);
  const logMax = Math.log10(Math.max(max, MIN * 10));

  const x = (i) =>
    ordered.length === 1
      ? (pad.left + width - pad.right) / 2
      : pad.left + (i * (width - pad.left - pad.right)) / (ordered.length - 1);
  const y = (v) => {
    const clamped = Math.max(v, MIN);
    const t = (Math.log10(clamped) - logMin) / (logMax - logMin || 1);
    return height - pad.bottom - t * (height - pad.top - pad.bottom);
  };

  const ticks = [100, 1000, 10000, 100000].filter(
    (t) => t <= Math.max(max, MIN * 10) * 1.2 && t >= MIN,
  );

  return (
    <div className="relative">
      <svg viewBox={`0 0 ${width} ${height}`} className="w-full" style={{ height: 160 }}>
        {ticks.map((t) => (
          <g key={t}>
            <line
              x1={pad.left}
              x2={width - pad.right}
              y1={y(t)}
              y2={y(t)}
              stroke="#e2e8f0"
              strokeWidth="1"
            />
            <text x={pad.left - 8} y={y(t) + 3} textAnchor="end" fontSize="10" fill="#94a3b8">
              {t >= 1000 ? `${t / 1000}s` : `${t}ms`}
            </text>
          </g>
        ))}

        {ordered.map((call, i) => {
          const failed = call.status === 'error';
          const cy = y(call.latency_ms);
          const isHovered = hovered?.id === call.id;
          return (
            <circle
              key={call.id || i}
              cx={x(i)}
              cy={cy}
              r={isHovered ? 6 : 4.5}
              fill={failed ? 'none' : colorFor(call.agent_name, names)}
              stroke={failed ? STATUS.critical : '#ffffff'}
              strokeWidth={failed ? 2 : 1.5}
              opacity={hovered && !isHovered ? 0.4 : 1}
              onMouseEnter={() => setHovered(call)}
              onMouseLeave={() => setHovered(null)}
              style={{ cursor: 'pointer', transition: 'r 120ms' }}
            />
          );
        })}
      </svg>

      {hovered && (
        <div className="absolute top-0 right-0 bg-slate-900 text-white text-[11px] rounded-md px-2.5 py-2 shadow-lg pointer-events-none max-w-[280px]">
          <div className="font-semibold">{hovered.agent_name}</div>
          <div className="text-slate-300 tabular-nums">
            {duration(hovered.latency_ms)}{hovered.status === 'error' ? ' (error)' : ''}{' '}
            · {count(hovered.total_tokens)} tok · {money(hovered.cost_usd)}
          </div>
          <div className="text-slate-400 truncate">{hovered.model}</div>
        </div>
      )}
      <div className="text-[11px] text-slate-400 mt-1 flex items-center gap-3">
        <span>oldest → newest</span>
        <span>log scale</span>
        <span className="flex items-center gap-1">
          <span
            className="inline-block h-2.5 w-2.5 rounded-full border-2"
            style={{ borderColor: STATUS.critical }}
          />
          observed error
        </span>
      </div>
    </div>
  );
};

/**
 * One run's calls as a waterfall, positioned by real start time and duration.
 *
 * This is the view that answers "where did the 81 seconds go", which a table of
 * durations cannot: it shows position as well as length, so a retry storm or a long
 * gap between agents is visible as a shape rather than something to reconstruct by
 * mentally differencing timestamps.
 */
export const RunWaterfall = ({ calls, names }) => {
  const [hovered, setHovered] = useState(null);
  const measured = (calls || []).filter((c) => isKnown(c.latency_ms) && Number.isFinite(Date.parse(c.started_at)));
  if (measured.length === 0) return <Empty label="measured durations" />;

  const starts = measured.map((c) => new Date(c.started_at).getTime());
  const t0 = Math.min(...starts);
  const spans = measured.map((c, i) => ({
    call: c,
    offset: starts[i] - t0,
    duration: Math.max(c.latency_ms, 1),
  }));
  const total = Math.max(...spans.map((s) => s.offset + s.duration), 1);

  return (
    <div className="space-y-1.5">
      {spans.map(({ call, offset, duration }, i) => {
        const failed = call.status === 'error';
        const left = (offset / total) * 100;
        const width = Math.max((duration / total) * 100, 0.8);
        return (
          <div
            key={call.id || i}
            className="flex items-center gap-3"
            onMouseEnter={() => setHovered(call.id)}
            onMouseLeave={() => setHovered(null)}
          >
            <div className="w-36 shrink-0 text-xs text-slate-600 truncate text-right">
              {call.agent_name}
            </div>
            <div className="flex-1 h-6 relative rounded bg-slate-50">
              <div
                className="absolute top-1 h-4 rounded transition-opacity"
                style={{
                  left: `${left}%`,
                  width: `${width}%`,
                  backgroundColor: failed ? STATUS.critical : colorFor(call.agent_name, names),
                  // 2px surface gap so adjacent spans never fuse into one bar.
                  boxShadow: '0 0 0 2px #ffffff',
                  opacity: hovered && hovered !== call.id ? 0.45 : 1,
                }}
              />
            </div>
            <div className="w-24 shrink-0 text-xs tabular-nums text-slate-500 text-right">
              {failed ? (
                <span style={{ color: STATUS.critical }}>failed</span>
              ) : (
                `${Math.round(call.latency_ms).toLocaleString()}ms`
              )}
            </div>
          </div>
        );
      })}
      <div className="flex items-center gap-3 pt-1">
        <div className="w-36 shrink-0" />
        <div className="flex-1 flex justify-between text-[11px] text-slate-400 tabular-nums">
          <span>0ms</span>
          <span>{(total / 1000).toFixed(1)}s</span>
        </div>
        <div className="w-24 shrink-0" />
      </div>
    </div>
  );
};
