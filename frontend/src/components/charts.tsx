/* Hand-rolled single-series charts following the dataviz mark specs:
   bars ≤24px thick with a 4px rounded data-end (square at the baseline),
   2px surface gaps, hairline gridlines, text in ink tokens (never the series
   color), no legend for a single series — the title names it. */

const SERIES = "#2a78d6"; // validated: ≥3:1 on the white card surface

export interface ChartDatum {
  key: string;
  value: number;
  title?: string; // native tooltip text
}

/** Horizontal bar list: label · bar · value at the tip. */
export function HBars({ data, format }: { data: ChartDatum[]; format: (v: number) => string }) {
  const max = Math.max(...data.map((d) => d.value), 0);
  if (max <= 0) return <p className="muted">Nothing to chart yet.</p>;
  return (
    <div className="hbars">
      {data.map((d) => (
        <div className="hbar-row" key={d.key} title={d.title ?? `${d.key}: ${format(d.value)}`}>
          <span className="hbar-label">{d.key}</span>
          <span className="hbar-track">
            <span
              className="hbar-fill"
              style={{ width: `${Math.max((d.value / max) * 100, 0.5)}%`, background: SERIES }}
            />
          </span>
          <span className="hbar-value">{format(d.value)}</span>
        </div>
      ))}
    </div>
  );
}

/** Vertical columns with a rounded cap, hairline gridline at a clean max,
    the peak value directly labeled (the rest via tooltip + axis). */
export function Columns({ data, format }: { data: ChartDatum[]; format: (v: number) => string }) {
  const max = Math.max(...data.map((d) => d.value), 0);
  if (max <= 0) return <p className="muted">Nothing to chart yet.</p>;

  const H = 150;
  const top = 18; // room for the peak label
  const niceMax = niceCeil(max);
  const colW = Math.min(24, Math.max(10, Math.floor(560 / data.length) - 6));
  const gap = Math.max(2, Math.floor(colW / 3));
  const width = data.length * (colW + gap) + 44;
  const peak = data.reduce((a, b) => (b.value > a.value ? b : a), data[0]);

  const bar = (x: number, y: number, w: number, h: number) => {
    const r = Math.min(4, h);
    return `M ${x} ${y + h} L ${x} ${y + r} Q ${x} ${y} ${x + r} ${y}
            L ${x + w - r} ${y} Q ${x + w} ${y} ${x + w} ${y + r} L ${x + w} ${y + h} Z`;
  };

  const scaleY = (v: number) => (v / niceMax) * (H - top);

  return (
    <svg
      className="columns"
      viewBox={`0 0 ${width} ${H + 22}`}
      style={{ width: "100%", maxWidth: `${width}px` }}
      role="img"
    >
      {/* gridline at the clean max + baseline */}
      <line x1={0} x2={width} y1={H - scaleY(niceMax)} y2={H - scaleY(niceMax)}
        stroke="#e1e0d9" strokeWidth={1} />
      <text x={0} y={H - scaleY(niceMax) - 3} fontSize={10} fill="#898781">
        {format(niceMax)}
      </text>
      <line x1={0} x2={width} y1={H} y2={H} stroke="#c3c2b7" strokeWidth={1} />

      {data.map((d, i) => {
        const h = scaleY(d.value);
        const x = 22 + i * (colW + gap);
        return (
          <g key={d.key}>
            <title>{d.title ?? `${d.key}: ${format(d.value)}`}</title>
            {d.value > 0 && <path d={bar(x, H - h, colW, h)} fill={SERIES} />}
            {d === peak && (
              <text x={x + colW / 2} y={H - h - 5} fontSize={10.5} fill="#1f2328"
                textAnchor="middle" fontWeight={600}>
                {format(d.value)}
              </text>
            )}
            <text x={x + colW / 2} y={H + 14} fontSize={10} fill="#898781" textAnchor="middle">
              {d.key.length > 5 ? `’${d.key.slice(-2)}` : d.key}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

/** Single-series line: 2px round-joined line, 10% area wash, ≥8px end dot
    with a 2px surface ring, end value directly labeled. */
export function LineChart({
  data,
  format,
}: {
  data: { key: string; value: number }[];
  format: (v: number) => string;
}) {
  if (data.length === 0) return <p className="muted">Nothing to chart yet.</p>;
  const max = Math.max(...data.map((d) => d.value));
  if (max <= 0) return <p className="muted">Nothing to chart yet.</p>;
  if (data.length === 1) {
    return (
      <p className="muted">
        One data point so far ({data[0].key}: {format(data[0].value)}) — the line appears as
        history accumulates.
      </p>
    );
  }

  const W = 560;
  const H = 150;
  const top = 16;
  const right = 70; // room for the end label
  const niceMax = niceCeil(max);
  const x = (i: number) => (i / (data.length - 1)) * (W - right);
  const y = (v: number) => H - (v / niceMax) * (H - top);
  const path = data.map((d, i) => `${i === 0 ? "M" : "L"} ${x(i)} ${y(d.value)}`).join(" ");
  const area = `${path} L ${x(data.length - 1)} ${H} L 0 ${H} Z`;
  const last = data[data.length - 1];

  const ticks = Math.max(2, Math.floor(data.length / 6));

  return (
    <svg className="linechart" viewBox={`0 0 ${W} ${H + 20}`} style={{ width: "100%" }} role="img">
      <line x1={0} x2={W} y1={y(niceMax)} y2={y(niceMax)} stroke="#e1e0d9" strokeWidth={1} />
      <text x={0} y={y(niceMax) - 3} fontSize={10} fill="#898781">{format(niceMax)}</text>
      <line x1={0} x2={W} y1={H} y2={H} stroke="#c3c2b7" strokeWidth={1} />

      <path d={area} fill="#2a78d6" opacity={0.1} />
      <path d={path} fill="none" stroke="#2a78d6" strokeWidth={2}
        strokeLinejoin="round" strokeLinecap="round" />

      {data.map((d, i) => (
        <g key={d.key}>
          <title>{`${d.key}: ${format(d.value)}`}</title>
          <circle cx={x(i)} cy={y(d.value)} r={7} fill="transparent" />
          {i % ticks === 0 && i < data.length - 1 && (
            <text x={x(i)} y={H + 14} fontSize={10} fill="#898781" textAnchor="middle">
              {d.key}
            </text>
          )}
        </g>
      ))}

      {/* end dot with surface ring + direct label */}
      <circle cx={x(data.length - 1)} cy={y(last.value)} r={6} fill="#fff" />
      <circle cx={x(data.length - 1)} cy={y(last.value)} r={4} fill="#2a78d6" />
      <text x={x(data.length - 1) + 9} y={y(last.value) + 4} fontSize={11}
        fill="#1f2328" fontWeight={600}>
        {format(last.value)}
      </text>
      <text x={x(data.length - 1)} y={H + 14} fontSize={10} fill="#898781" textAnchor="middle">
        {last.key}
      </text>
    </svg>
  );
}

function niceCeil(v: number): number {
  const pow = Math.pow(10, Math.floor(Math.log10(v)));
  for (const m of [1, 2, 2.5, 5, 10]) {
    if (m * pow >= v) return m * pow;
  }
  return 10 * pow;
}
