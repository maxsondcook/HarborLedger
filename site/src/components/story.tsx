import { useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { useData, type Coast, type Funnel, type SourceKey, type Trace, type TraceIndexRow } from "../data";
import { GROUP_LABEL, money, num } from "../format";
import { Confidence } from "./ui";

export const SOURCE_ORDER: SourceKey[] = ["usaspending", "wikipedia", "ais", "psix", "mvus"];
export const SOURCE_SHORT: Record<SourceKey, string> = {
  usaspending: "Navy contracts", wikipedia: "Wikipedia", ais: "AIS tracking", psix: "Coast Guard PSIX", mvus: "Coast Guard register",
};

export function SourceDot({ s, off = false, label = false }: { s: SourceKey; off?: boolean; label?: boolean }) {
  return (
    <span className={`src-${s}`} title={SOURCE_SHORT[s]} style={{ display: "inline-flex", gap: 5, alignItems: "center", position: "relative" }}>
      <span className={`dot${off ? " off" : ""}`} aria-hidden="true" />
      {label ? <span>{SOURCE_SHORT[s]}</span> : <span className="sr-only">{SOURCE_SHORT[s]}{off ? " (none)" : ""}</span>}
    </span>
  );
}

export function SourceLegend() {
  return (
    <div className="legend" aria-label="Source colours">
      {SOURCE_ORDER.map((s) => <SourceDot key={s} s={s} label />)}
    </div>
  );
}

const kindLabel = (v: TraceIndexRow) =>
  v.kind === "navy" ? `Navy ${v.hull ?? ""}`.trim() : GROUP_LABEL[v.group ?? ""] ?? (v.group ?? "Vessel").toLowerCase();

/** Horizontally scrolling strip of showcase vessels; arrows and a group filter for keyboard and mouse users. */
export function ShipPicker({ rows, selected, onSelect }: { rows: TraceIndexRow[]; selected: string; onSelect: (slug: string) => void }) {
  const strip = useRef<HTMLDivElement>(null);
  const [filter, setFilter] = useState("all");
  const groups = useMemo(() => {
    const g = new Map<string, string>();
    rows.forEach((r) => g.set(r.kind === "navy" ? "navy" : r.group ?? "OTHER", r.kind === "navy" ? "Navy ships" : GROUP_LABEL[r.group ?? ""] ?? r.group ?? "Other"));
    return [...g.entries()];
  }, [rows]);
  const shown = rows.filter((r) => filter === "all" || (filter === "navy" ? r.kind === "navy" : r.kind !== "navy" && r.group === filter));
  const scroll = (dir: number) => strip.current?.scrollBy({ left: dir * 440, behavior: "smooth" });
  return (
    <>
      <div className="picker-nav">
        <label className="small muted" htmlFor="ship-filter">Show</label>
        <select id="ship-filter" value={filter} onChange={(e) => setFilter(e.target.value)}>
          <option value="all">All {rows.length} vessels</option>
          {groups.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
        </select>
        <span style={{ flex: 1 }} />
        <button type="button" onClick={() => scroll(-1)} aria-label="Scroll vessels left">←</button>
        <button type="button" onClick={() => scroll(1)} aria-label="Scroll vessels right">→</button>
      </div>
      <div className="picker-wrap">
        <div className="picker" ref={strip} role="list" aria-label="Choose a vessel">
          {shown.map((r) => (
            <div role="listitem" key={r.slug} style={{ display: "contents" }}>
              <button type="button" className="ship" aria-pressed={r.slug === selected} onClick={() => onSelect(r.slug)}>
                <span className="nm">{r.name ?? r.hull ?? r.slug}</span>
                <span className="meta">{kindLabel(r)} · {r.n_sources} sources{r.contracts ? ` · ${r.contracts} contracts` : ""}</span>
                <span className="dots">{SOURCE_ORDER.map((s) => <SourceDot key={s} s={s} off={!r.sources.includes(s)} />)}</span>
              </button>
            </div>
          ))}
        </div>
      </div>
    </>
  );
}

const fmtField = (k: string, v: string | number | null) => {
  if (v === null || v === undefined || v === "") return "—";
  if (k === "Award" && typeof v === "number") return money(v);
  return String(v);
};

/** Each source record as that source names the ship, with the rule that joined it to the next. */
export function TraceChain({ t }: { t: Trace }) {
  return (
    <div className="chain">
      {t.records.map((r, i) => (
        <div key={r.id}>
          <article className={`rec src-${r.source}`} aria-label={SOURCE_SHORT[r.source]}>
            <header>
              <span className="srcname">{i + 1}. {SOURCE_SHORT[r.source]}</span>
              <span className="muted small mono">{r.id}</span>
            </header>
            <div className="small muted" style={{ marginTop: 6 }}>calls it</div>
            <div className="as">{r.names_it_as ?? "—"}</div>
            <dl>
              {Object.entries(r.fields).filter(([, v]) => v !== null && v !== "").map(([k, v]) => (
                <div key={k}><dt>{k}</dt><dd className={k.startsWith("Description") ? "small" : ""}>{fmtField(k, v)}</dd></div>
              ))}
            </dl>
          </article>
          {r.join && i < t.records.length - 1 && (
            <div className="join">
              <div className="rule">
                <Confidence value={r.join.confidence} /> <b>joined by:</b> {r.join.rule}
              </div>
              {r.join.evidence && <div className="ev">{r.join.evidence}</div>}
            </div>
          )}
          {i < t.records.length - 1 && !r.join && (
            <div className="join"><div className="rule muted small">same record family (linked through the next record's rule)</div></div>
          )}
        </div>
      ))}
      {t.held_back.length > 0 && (
        <p className="muted small" style={{ marginTop: 10 }}>
          {t.held_back.length} weaker candidate link{t.held_back.length > 1 ? "s" : ""} below 0.5 confidence {t.held_back.length > 1 ? "were" : "was"} kept for audit but not merged:{" "}
          {t.held_back.map((h) => `${h.dst} (${h.method}, ${h.confidence.toFixed(2)})`).join("; ")}.
        </p>
      )}
    </div>
  );
}

/** 2025 hourly AIS positions over the Natural Earth coastline (equirectangular, cos-latitude corrected). */
export function TrackMap({ t }: { t: Trace }) {
  const coast = useData<Coast>("coast.json").data;
  const [hover, setHover] = useState<number | null>(null);
  if (!t.track) return <p className="muted small">No {t.track_year} AIS positions for this vessel.</p>;
  const pts = t.track.points;
  // frame on the 2nd-98th percentile so a few far-off positions don't shrink the usual working area
  const q = (a: number[], p: number) => a[Math.min(a.length - 1, Math.max(0, Math.round(p * (a.length - 1))))];
  const xs = pts.map((p) => p[0]).sort((a, b) => a - b), ys = pts.map((p) => p[1]).sort((a, b) => a - b);
  const [x0, x1, y0, y1] = [q(xs, 0.02), q(xs, 0.98), q(ys, 0.02), q(ys, 0.98)];
  const cx = (x0 + x1) / 2, cy = (y0 + y1) / 2;
  const k = Math.cos((cy * Math.PI) / 180);
  let spanX = Math.max((x1 - x0) * k, 0.12) * 1.25, spanY = Math.max(y1 - y0, 0.08) * 1.25;
  const W = 560, H = 380;
  if (spanX / spanY > W / H) spanY = spanX * (H / W); else spanX = spanY * (W / H);
  const px = (x: number) => W / 2 + ((x - cx) * k * W) / spanX;
  const py = (y: number) => H / 2 - ((y - cy) * H) / spanY;
  const inView = (x: number, y: number) => Math.abs((x - cx) * k) < spanX * 0.6 && Math.abs(y - cy) < spanY * 0.6;
  const path = (line: [number, number][]) => {
    let d = "", on = false;
    for (const [x, y] of line) {
      if (inView(x, y)) { d += `${on ? "L" : "M"}${px(x).toFixed(1)},${py(y).toFixed(1)}`; on = true; } else on = false;
    }
    return d;
  };
  const h = hover !== null ? pts[hover] : null;
  return (
    <div className="mapbox">
      <svg className="chart map" viewBox={`0 0 ${W} ${H}`} role="img" style={{ overflow: "hidden" }}
        aria-label={`${t.track_year} AIS track: ${num(t.track.hours)} vessel-hours over ${t.track.days} days`}
        onMouseLeave={() => setHover(null)}>
        <rect x={0} y={0} width={W} height={H} fill="transparent" />
        {coast?.lines.map((l, i) => { const d = path(l); return d ? <path key={i} className="coast" d={d} /> : null; })}
        {pts.map(([x, y], i) => !inView(x, y) ? null : (
          <circle key={i} className="pt" cx={px(x)} cy={py(y)} r={hover === i ? 5 : 2.2} opacity={hover === i ? 1 : 0.6}
            onMouseEnter={() => setHover(i)} />
        ))}
        {h && (
          <g pointerEvents="none">
            <rect x={Math.min(px(h[0]) + 8, W - 150)} y={Math.max(py(h[1]) - 34, 4)} width={142} height={28} rx={5} fill="var(--surface)" stroke="var(--border)" />
            <text x={Math.min(px(h[0]) + 16, W - 142)} y={Math.max(py(h[1]) - 16, 22)} style={{ fill: "var(--text)", fontSize: 12 }}>
              {h[1].toFixed(3)}°N {Math.abs(h[0]).toFixed(3)}°W · {h[2]} kn
            </text>
          </g>
        )}
        <text className="label" x={8} y={H - 8}>Coastline: Natural Earth (public domain) · one dot per sampled hour</text>
      </svg>
      <div className="small muted" style={{ padding: "4px 4px 0" }}>
        {num(t.track.hours)} vessel-hours seen on {t.track.days} days, {t.track.first} to {t.track.last}. Framed on its usual working area; {pts.filter(([x, y]) => !inView(x, y)).length || "no"} sampled positions fall outside the frame.
      </div>
    </div>
  );
}

export function EntityOutcome({ t }: { t: Trace }) {
  const e = t.encounters;
  return (
    <div className="entity">
      <div>
        <h3 style={{ margin: "0 0 6px" }}>Where it went in {t.track_year}</h3>
        <TrackMap t={t} />
      </div>
      <div style={{ display: "grid", gap: 12, alignContent: "start" }}>
        <div className="card">
          <div className="k">Navy contracts naming it</div>
          {t.contracts.n ? (
            <>
              <div className="v">{t.contracts.n} · {money(t.contracts.total)}</div>
              <ul className="small" style={{ margin: "6px 0 0", paddingLeft: 16 }}>
                {t.contracts.list.slice(0, 4).map((c) => (
                  <li key={c.piid}><span className="mono">{c.piid}</span> · {c.recipient} · {money(c.amount)} <span className="muted">({c.start?.slice(0, 4)})</span></li>
                ))}
              </ul>
            </>
          ) : <div className="muted small">None: commercial vessels are linked through the Coast Guard records instead.</div>}
        </div>
        <div className="card">
          <div className="k">Close-quarters alerts in {t.track_year}</div>
          <div className="v">{num(e.alerts)}</div>
          <div className="muted small">
            {num(e.realized)} came within 0.25 nm{e.service_share !== undefined ? ` · ${Math.round(e.service_share * 100)}% involved a service vessel` : ""}
          </div>
          {e.closest.length > 0 && (
            <ul className="small" style={{ margin: "6px 0 0", paddingLeft: 16 }}>
              {e.closest.slice(0, 3).map((c, i) => (
                <li key={i}>{c.day}: {c.min_sep_m} m from {c.other} <span className="muted">({c.geometry}, {c.region.replace(/_/g, " ")})</span></li>
              ))}
            </ul>
          )}
        </div>
        <div className="small">
          <Link to={`/vessels/${t.vessel_page}`}>Full vessel page →</Link> · <Link to="/encounters">All encounters →</Link>
        </div>
      </div>
    </div>
  );
}

export function FunnelView({ f }: { f: Funnel }) {
  const total = f.raw.reduce((a, r) => a + r.n, 0);
  return (
    <div className="funnel" role="list" aria-label="From raw records to vessels">
      <div className="stage" role="listitem">
        <div className="k">1 · Raw records</div>
        <b>{num(total)}</b>
        <ul>{f.raw.map((r) => <li key={r.source}><SourceDot s={r.source} label /><span>{num(r.n)}</span></li>)}</ul>
      </div>
      <div className="stage" role="listitem">
        <div className="k">2 · Identifiers extracted</div>
        <b>{num(f.identifiers)}</b>
        <div className="small muted">MMSI, IMO, call signs, official numbers, hull numbers read from free text, names</div>
      </div>
      <div className="stage" role="listitem">
        <div className="k">3 · Source records</div>
        <b>{num(f.records)}</b>
        <div className="small muted">one node per vessel record in each source</div>
      </div>
      <div className="stage" role="listitem">
        <div className="k">4 · Links tested</div>
        <b>{num(f.links)}</b>
        <div className="small muted">{num(f.links_asserted)} asserted (≥ 0.5) · {num(f.links_held_back)} kept for audit only</div>
      </div>
      <div className="stage" role="listitem">
        <div className="k">5 · Real-world vessels</div>
        <b>{num(f.entities)}</b>
        <div className="small muted">{num(f.entities_multi_source)} of them joined across two or more sources</div>
      </div>
    </div>
  );
}
