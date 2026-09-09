/**
 * Dependency-free inline SVG charts.
 *
 * The app has no charting library in package.json, and the Guardian MVP needs two
 * trend lines and one bar series -- not enough to justify pulling one in. If the
 * dashboard later needs real interactive charts, that's the point to add a library,
 * not now.
 */

const EmptyState = ({ label }) => (
  <div className="h-24 flex items-center justify-center text-xs text-slate-400">
    No {label} data yet
  </div>
);

export const LineChart = ({ points, label, formatValue = (v) => v, color = '#0f172a' }) => {
  if (!points || points.length === 0) return <EmptyState label={label} />;

  const width = 480;
  const height = 96;
  const padding = 4;
  const values = points.map((p) => p.value);
  const max = Math.max(...values);
  const min = Math.min(...values);
  const range = max - min || 1;

  const coords = points.map((point, i) => {
    const x = points.length === 1
      ? width / 2
      : padding + (i * (width - padding * 2)) / (points.length - 1);
    const y = height - padding - ((point.value - min) / range) * (height - padding * 2);
    return { x, y, ...point };
  });

  const path = coords.map((c, i) => `${i === 0 ? 'M' : 'L'} ${c.x} ${c.y}`).join(' ');

  return (
    <div>
      <svg viewBox={`0 0 ${width} ${height}`} className="w-full h-24" preserveAspectRatio="none">
        <path d={path} fill="none" stroke={color} strokeWidth="2" vectorEffect="non-scaling-stroke" />
        {coords.map((c) => (
          <circle key={c.label} cx={c.x} cy={c.y} r="2.5" fill={color} />
        ))}
      </svg>
      <div className="flex justify-between text-xs text-slate-500 mt-1">
        <span>{formatValue(min)}</span>
        <span className="text-slate-400">
          {points[0].label} → {points[points.length - 1].label}
        </span>
        <span>{formatValue(max)}</span>
      </div>
    </div>
  );
};

export const BarChart = ({ points, label }) => {
  if (!points || points.length === 0) return <EmptyState label={label} />;

  const max = Math.max(...points.map((p) => p.value), 1);

  return (
    <div>
      <div className="flex items-end gap-1 h-24">
        {points.map((point) => (
          <div key={point.label} className="flex-1 flex flex-col justify-end" title={`${point.label}: ${point.value}`}>
            <div
              className="bg-slate-800 rounded-sm min-h-[2px]"
              style={{ height: `${(point.value / max) * 100}%` }}
            />
          </div>
        ))}
      </div>
      <div className="flex justify-between text-xs text-slate-500 mt-1">
        <span>{points[0].label}</span>
        <span className="text-slate-400">peak {max}</span>
        <span>{points[points.length - 1].label}</span>
      </div>
    </div>
  );
};
