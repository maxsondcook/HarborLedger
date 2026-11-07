import { useEffect, useRef, useState, type ReactNode } from "react";

// Small dependency-free SVG charts. Conventions (dataviz method): one y-axis, thin marks,
// rounded data-ends at the baseline side, recessive grid, hover tooltip on every mark,
// text in text colors (never the series color), legends for >= 2 series.

export const SERIES = ["var(--series-1)", "var(--series-2)", "var(--series-3)", "var(--series-4)"];

type Tip = { x: number; y: number; body: ReactNode } | null;

function useTip() {
  const [tip, setTip] = useState<Tip>(null);
  const show = (e: React.MouseEvent, body: ReactNode) => {
    const host = (e.currentTarget as Element).closest(".chart-wrap") as HTMLElement | null;
    if (!host) return;
    const r = host.getBoundingClientRect();
    setTip({ x: e.clientX - r.left, y: e.clientY - r.top, body });
  };
  const el = tip ? <div className="tip" style={{ left: tip.x, top: tip.y }}>{tip.body}</div> : null;
  return { show, hide: () => setTip(null), el };
}

/** Measure the wrapper so charts draw at real pixel width and text stays a readable size on phones. */
function useWidth(fallback: number) {
  const ref = useRef<HTMLDivElement>(null);
  const [w, setW] = useState(fallback);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const ro = new ResizeObserver(([e]) => setW(Math.max(280, Math.round(e.contentRect.width))));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return [ref, w] as const;
}

const clip = (s: string, n: number) => (s.length > n ? s.slice(0, n - 1) + "…" : s);

function ticks(min: number, max: number, n = 5): number[] {
  const span = max - min || 1;
  const step0 = span / n;
  const mag = 10 ** Math.floor(Math.log10(step0));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= step0) ?? step0;
  const out: number[] = [];
  for (let v = Math.ceil(min / step) * step; v <= max + 1e-9; v += step) out.push(+v.toFixed(10));
  return out;
}

/** Horizontal bars: one value per category, with optional value labels. */
export function HBar({ rows, fmt, color = SERIES[0], label }: {
  rows: { key: string; value: number; note?: string }[]; fmt: (v: number) => string; color?: string; label?: string;
}) {
  const t = useTip();
  const [ref, width] = useWidth(640);
  const maxChars = width < 500 ? 22 : 40;
  const longest = Math.max(4, ...rows.map((r) => Math.min(maxChars, r.key.length)));
  const left = Math.min(width * 0.45, Math.max(70, 14 + longest * 6.6)), right = 52, rowH = 24, top = 18;
  const h = top + rows.length * rowH + 22;
  const vals = rows.map((r) => r.value);
  const min = Math.min(0, ...vals), max = Math.max(0, ...vals);
  const x = (v: number) => left + ((v - min) / (max - min || 1)) * (width - left - right);
  return (
    <div className="chart-wrap" ref={ref}>
      <svg className="chart" viewBox={`0 0 ${width} ${h}`} width={width} height={h} role="img" aria-label={label}>
        {ticks(min, max, width < 500 ? 3 : 5).map((v) => (
          <g key={v}>
            <line className="gridline" x1={x(v)} x2={x(v)} y1={top - 4} y2={h - 20} />
            <text x={x(v)} y={h - 6} textAnchor="middle">{fmt(v)}</text>
          </g>
        ))}
        <line className="axisline" x1={x(0)} x2={x(0)} y1={top - 4} y2={h - 20} />
        {rows.map((r, i) => {
          const y = top + i * rowH;
          const x0 = x(Math.min(0, r.value)), x1 = x(Math.max(0, r.value));
          return (
            <g key={r.key} onMouseMove={(e) => t.show(e, <><b>{r.key}</b>: {fmt(r.value)}{r.note ? <div className="muted">{r.note}</div> : null}</>)} onMouseLeave={t.hide}>
              <rect className="hit" x={0} y={y} width={width} height={rowH} />
              <text className="label" x={left - 8} y={y + rowH / 2 + 4} textAnchor="end">{clip(r.key, maxChars)}</text>
              <rect x={x0} y={y + 5} width={Math.max(1, x1 - x0)} height={rowH - 10} rx={4} fill={color} />
              {/* negative values: label to the right of the zero line so it never collides with the row name */}
              <text x={x1 + 6} y={y + rowH / 2 + 4} textAnchor="start">{fmt(r.value)}</text>
            </g>
          );
        })}
      </svg>
      {t.el}
    </div>
  );
}

/** Histogram of values in fixed-width bins, with optional reference lines. */
export function Histogram({ values, bins, fmt, refs = [], height = 240, label }: {
  values: number[]; bins: number[]; fmt: (v: number) => string; refs?: { v: number; text: string }[]; height?: number; label?: string;
}) {
  const t = useTip();
  const [ref, width] = useWidth(720);
  const left = 44, right = 12, top = 16, bottom = 30;
  const counts = bins.slice(0, -1).map((b, i) => values.filter((v) => v >= b && (i === bins.length - 2 ? v <= bins[i + 1] : v < bins[i + 1])).length);
  const maxC = Math.max(1, ...counts);
  const x = (v: number) => left + ((v - bins[0]) / (bins[bins.length - 1] - bins[0])) * (width - left - right);
  const y = (c: number) => height - bottom - (c / maxC) * (height - top - bottom);
  return (
    <div className="chart-wrap" ref={ref}>
      <svg className="chart" viewBox={`0 0 ${width} ${height}`} width={width} height={height} role="img" aria-label={label}>
        {ticks(0, maxC, 4).map((c) => (
          <g key={c}>
            <line className="gridline" x1={left} x2={width - right} y1={y(c)} y2={y(c)} />
            <text x={left - 6} y={y(c) + 4} textAnchor="end">{c}</text>
          </g>
        ))}
        {counts.map((c, i) => {
          const x0 = x(bins[i]) + 1, x1 = x(bins[i + 1]) - 1;
          return (
            <g key={i} onMouseMove={(e) => t.show(e, <><b>{fmt(bins[i])} to {fmt(bins[i + 1])}</b>: {c}</>)} onMouseLeave={t.hide}>
              <rect className="hit" x={x0} y={top} width={x1 - x0} height={height - top - bottom} />
              {c > 0 && <rect x={x0} y={y(c)} width={Math.max(1, x1 - x0)} height={height - bottom - y(c)} rx={3} fill={SERIES[0]} />}
            </g>
          );
        })}
        <line className="axisline" x1={left} x2={width - right} y1={height - bottom} y2={height - bottom} />
        {ticks(bins[0], bins[bins.length - 1], width < 500 ? 4 : 8).map((v) => <text key={v} x={x(v)} y={height - 10} textAnchor="middle">{fmt(v)}</text>)}
        {refs.map((r) => (
          <g key={r.text}>
            <line x1={x(r.v)} x2={x(r.v)} y1={top - 6} y2={height - bottom} stroke="var(--text)" strokeDasharray="3 3" strokeWidth={1} />
            <text className="label" x={x(r.v) + 4} y={top + 2}>{r.text}</text>
          </g>
        ))}
      </svg>
      {t.el}
    </div>
  );
}

/** Multi-series line chart over a shared category axis (e.g. months), with crosshair tooltip. */
export function LineChart({ xs, series, fmt, height = 260, label }: {
  xs: string[]; series: { name: string; values: (number | null)[] }[]; fmt: (v: number) => string; height?: number; label?: string;
}) {
  const t = useTip();
  const [ref, width] = useWidth(720);
  const every = Math.max(1, Math.ceil(xs.length / Math.max(4, Math.floor(width / 60))));
  const [hover, setHover] = useState<number | null>(null);
  const left = 48, right = width >= 500 ? 90 : 12, top = 14, bottom = 30;
  const all = series.flatMap((s) => s.values.filter((v): v is number => v !== null));
  const hasNeg = all.some((v) => v < 0);
  const rawMax = Math.max(hasNeg ? 0 : 1, ...all), rawMin = Math.min(0, ...all);
  const pad = (rawMax - rawMin || 1) * 0.06;
  const max = rawMax + pad, min = hasNeg ? rawMin - pad : 0;
  const x = (i: number) => left + (xs.length === 1 ? 0.5 : i / (xs.length - 1)) * (width - left - right);
  const y = (v: number) => height - bottom - ((v - min) / (max - min)) * (height - top - bottom);
  return (
    <div className="chart-wrap" ref={ref}>
      {series.length > 1 && (
        <div className="legend">{series.map((s, i) => <span key={s.name}><i style={{ background: SERIES[i % SERIES.length] }} />{s.name}</span>)}</div>
      )}
      <svg className="chart" viewBox={`0 0 ${width} ${height}`} width={width} height={height} role="img" aria-label={label}
        onMouseLeave={() => { setHover(null); t.hide(); }}>
        {ticks(min, max, 4).map((v) => (
          <g key={v}>
            <line className="gridline" x1={left} x2={width - right} y1={y(v)} y2={y(v)} />
            <text x={left - 6} y={y(v) + 4} textAnchor="end">{fmt(v)}</text>
          </g>
        ))}
        {hasNeg && <line className="axisline" x1={left} x2={width - right} y1={y(0)} y2={y(0)} />}
        {xs.map((lab, i) => i % every === 0 && <text key={lab} x={x(i)} y={height - 10} textAnchor="middle">{lab}</text>)}
        {series.map((s, si) => {
          const pts = s.values.map((v, i) => (v === null ? null : `${x(i)},${y(v)}`)).filter(Boolean).join(" ");
          const lastI = s.values.map((v, i) => (v === null ? -1 : i)).reduce((a, b) => Math.max(a, b), -1);
          return (
            <g key={s.name}>
              <polyline points={pts} fill="none" stroke={SERIES[si % SERIES.length]} strokeWidth={2} strokeLinejoin="round" />
              {s.values.map((v, i) => v !== null && <circle key={i} cx={x(i)} cy={y(v)} r={hover === i ? 5 : 3.5} fill={SERIES[si % SERIES.length]} stroke="var(--surface)" strokeWidth={2} />)}
              {lastI >= 0 && series.length <= 4 && width >= 500 && <text className="label" x={x(lastI) + 8} y={y(s.values[lastI] as number) + 4}>{s.name}</text>}
            </g>
          );
        })}
        {hover !== null && <line x1={x(hover)} x2={x(hover)} y1={top} y2={height - bottom} stroke="var(--axis)" strokeDasharray="3 3" />}
        {xs.map((lab, i) => (
          <rect key={lab} className="hit" x={x(i) - (width - left - right) / Math.max(1, xs.length - 1) / 2} y={top}
            width={(width - left - right) / Math.max(1, xs.length - 1)} height={height - top - bottom}
            onMouseMove={(e) => { setHover(i); t.show(e, <><b>{lab}</b>{series.map((s) => <div key={s.name}>{s.name}: {s.values[i] === null ? "—" : fmt(s.values[i] as number)}</div>)}</>); }} />
        ))}
      </svg>
      {t.el}
    </div>
  );
}
