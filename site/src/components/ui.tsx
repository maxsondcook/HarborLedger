import { useEffect, type ReactNode } from "react";
import type { Loadable } from "../data";

export function Confidence({ value, method }: { value: number | null | undefined; method?: string }) {
  if (value === null || value === undefined) return <span className="badge">no link</span>;
  const cls = value >= 0.9 ? "good" : value >= 0.5 ? "warn" : "bad";
  return (
    <span className={`badge ${cls}`} title={method ? `method: ${method}` : undefined}>
      {value.toFixed(2)}
      {method ? ` · ${method}` : ""}
    </span>
  );
}

export function Stat({ k, v, sub }: { k: string; v: ReactNode; sub?: ReactNode }) {
  return (
    <div className="card">
      <div className="k">{k}</div>
      <div className="v">{v}</div>
      {sub ? <div className="muted small">{sub}</div> : null}
    </div>
  );
}

export function Async<T>({ state, children }: { state: Loadable<T>; children: (d: T) => ReactNode }) {
  if (state.loading) return <p className="muted">Loading…</p>;
  if (state.error) return <p className="badge bad">Could not load data: {state.error}</p>;
  if (!state.data) return null;
  return <>{children(state.data)}</>;
}

/** Set the browser-tab title for a page. */
export function useTitle(title: string | null | undefined) {
  useEffect(() => {
    document.title = title ? `${title} · HarborLedger` : "HarborLedger";
  }, [title]);
}

/** Year picker for the per-year AIS views; hidden when only one year exists. */
export function YearSelect({ year, years, onChange }: { year: number | null; years: number[]; onChange: (y: number) => void }) {
  if (years.length < 2 || year === null) return year ? <span className="badge accent">AIS year {year}</span> : null;
  return (
    <select value={year} onChange={(e) => onChange(Number(e.target.value))} aria-label="AIS year">
      {years.map((y) => <option key={y} value={y}>AIS year {y}</option>)}
    </select>
  );
}
