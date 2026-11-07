import { useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { HBar, LineChart, SERIES } from "../components/charts";
import { Async, Stat, useTitle, YearSelect } from "../components/ui";
import { useData, useYear } from "../data";
import { num } from "../format";

type Tier = { all: number; large_no_pleasure: number; large_no_pleasure_per_1000_h: number };
type RegionSum = {
  moving_vessel_hours: number; traffic_alerts: number; traffic_encounters: number; alert_precision: number | null;
  encounters_per_1000_moving_vessel_hours: number; encounters_with_large_vessel: number;
  pleasure_share_of_encounters: number | null; geometry: Record<string, number>; median_min_sep_m: number | null;
  tiers: Record<string, Tier>;
};
type Summary = {
  definition: Record<string, string | number>; n_alerts: number; n_traffic_alerts: number; n_service_alerts: number;
  n_traffic_encounters: number; alert_precision_traffic: number; by_region: Record<string, RegionSum>;
  alert_precision_by_tcpa_min: Record<string, number>;
  likely_launch_vessels?: number[];
};
type Daily = { day: string; region: string; encounters: number; within_185m: number; within_93m: number; large_no_pleasure: number };
type Scenario = {
  id: string; day: string; region: string; mmsi_a: number; mmsi_b: number; name_a: string | null; name_b: string | null;
  type_a: number | null; type_b: number | null; len_a: number | null; len_b: number | null; geometry: string;
  min_sep_obs_m: number; raw_min_sep_m: number | null; cpa_pred_m: number; tcpa_pred_s: number; sog_a: number; sog_b: number;
  t_first: number; t_min_sep: number | null; minutes: number;
};
type ScenarioPage = Scenario & { tracks: Record<string, [number, number, number, number, number][]> };

const REGION = { san_pedro_bay: "San Pedro Bay", sf_bay: "SF Bay", san_diego: "San Diego" } as Record<string, string>;
const TYPE = (t: number | null) => t === null ? "unknown" : t >= 70 && t <= 79 ? "cargo" : t >= 80 && t <= 89 ? "tanker" : t >= 60 && t <= 69 ? "passenger" : t === 30 ? "fishing" : t === 31 || t === 32 || t === 52 ? "tug" : t === 36 || t === 37 ? "pleasure" : `type ${t}`;
const fmtTime = (ts: number) => new Date(ts * 1000).toISOString().slice(11, 16) + " UTC";

export default function Encounters() {
  useTitle("Close-quarters encounters");
  const [year, setYear, years] = useYear();
  const s = useData<Summary>(year ? `encounters_${year}.json` : null);
  const d = useData<Daily[]>(year ? `encounter_daily_${year}.json` : null);
  const sc = useData<Scenario[]>(year ? `encounter_scenarios_${year}.json` : null);
  return (
    <>
      <h1>Close-quarters encounters</h1>
      <p className="lede">
        Pairs of moving vessels (≥ 1 knot) that came close in California port areas, detected from AIS. Each minute,
        every nearby pair's <b>closest point of approach</b> (CPA) and <b>time to it</b> (TCPA) is projected from
        speed and course. A projected pass under a quarter mile within 10 minutes is an <i>alert</i>; an alert
        becomes an <i>encounter</i> when the vessels actually come that close. Tug, pilot, dredging, diving and law-enforcement
        work is close by design and is kept separate.
      </p>
      <div className="controls"><YearSelect year={year} years={years} onChange={setYear} /></div>
      <Async state={s}>{(sum) => <Body s={sum} daily={d.data} scenarios={sc.data} />}</Async>
    </>
  );
}

function Body({ s, daily, scenarios }: { s: Summary; daily?: Daily[]; scenarios?: Scenario[] }) {
  const [tier, setTier] = useState("0.10nm");
  const regions = Object.keys(s.by_region);
  const precision = Object.entries(s.alert_precision_by_tcpa_min).map(([k, v]) => ({ key: `alert ${k} min ahead`, value: v }));
  const days = useMemo(() => [...new Set((daily ?? []).map((x) => x.day))].sort(), [daily]);
  const monthly = days.length > 62;   // a year of daily points is unreadable: switch to monthly totals
  const buckets = monthly ? [...new Set(days.map((d) => d.slice(0, 7)))] : days;
  const series = regions.map((r) => ({
    name: REGION[r] ?? r,
    values: buckets.map((b) => (daily ?? []).filter((x) => x.region === r && (monthly ? x.day.startsWith(b) : x.day === b))
      .reduce((t, x) => t + x.large_no_pleasure, 0)),
  }));
  return (
    <>
      <div className="grid">
        <Stat k="Traffic alerts" v={num(s.n_traffic_alerts)} sub={`${num(s.n_service_alerts)} more were tug/pilot/service work`} />
        <Stat k="Became real encounters" v={`${Math.round(s.alert_precision_traffic * 100)}%`} sub={`${num(s.n_traffic_encounters)} passes under a quarter mile`} />
        {regions.map((r) => (
          <Stat key={r} k={`${REGION[r]}: per 1,000 moving-vessel hours`} v={num(s.by_region[r].encounters_per_1000_moving_vessel_hours)}
            sub={`${Math.round((s.by_region[r].pleasure_share_of_encounters ?? 0) * 100)}% involve a pleasure craft`} />
        ))}
      </div>

      <div className="figure">
        <h3>How often a straight-line alert comes true</h3>
        <p className="cap">Share of traffic alerts whose vessels actually passed within a quarter mile, by how far ahead the alert was raised. Constant speed-and-course projection is a common baseline in collision avoidance; its false-alarm rate grows quickly with look-ahead time.</p>
        <HBar rows={precision} fmt={(v) => `${Math.round(v * 100)}%`} color={SERIES[1]} label="Alert precision by look-ahead" />
      </div>

      <h2>Encounters involving a large vessel</h2>
      <p className="lede">Cargo or tanker vessels of any size, or anything 50 m or longer. Pleasure craft, military vessels and <i>likely launch or service boats</i> are left out: small non-pleasure vessels that came alongside {s.definition.likely_launch ? "10 or more different large ships" : "many large ships"} in the period, typically crew launches and bunker boats whose AIS type does not say so{s.likely_launch_vessels ? ` (${s.likely_launch_vessels.length} vessels)` : ""}.</p>
      <div className="controls">
        <select value={tier} onChange={(e) => setTier(e.target.value)} aria-label="Separation tier">
          <option value="0.25nm">Closer than 0.25 nm (463 m)</option>
          <option value="0.10nm">Closer than 0.10 nm (185 m)</option>
          <option value="0.05nm">Closer than 0.05 nm (93 m)</option>
        </select>
      </div>
      <div className="tablewrap">
        <table>
          <thead><tr><th>Port area</th><th className="num">Moving-vessel hours</th><th className="num">Encounters</th><th className="num">Per 1,000 h</th><th className="num">Median closest pass</th><th>Geometry (all traffic encounters)</th></tr></thead>
          <tbody>
            {regions.map((r) => {
              const x = s.by_region[r];
              const t = x.tiers?.[tier];
              return (
                <tr key={r}>
                  <td>{REGION[r]}</td>
                  <td className="num">{num(x.moving_vessel_hours)}</td>
                  <td className="num">{num(t?.large_no_pleasure)}</td>
                  <td className="num">{t ? t.large_no_pleasure_per_1000_h.toFixed(1) : "—"}</td>
                  <td className="num">{x.median_min_sep_m ? `${x.median_min_sep_m} m` : "—"}</td>
                  <td className="small">{Object.entries(x.geometry).map(([k, v]) => `${k} ${num(v)}`).join(" · ")}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {days.length > 1 && (
        <div className="figure">
          <h3>Large-vessel encounters per {monthly ? "month" : "day"} (under a quarter mile)</h3>
          <p className="cap">Excludes pleasure craft, military vessels and likely launch or service boats.</p>
          <LineChart xs={buckets.map((x) => (monthly ? x.slice(5) : x.slice(5)))} series={series} fmt={(v) => num(Math.round(v))} label="Large-vessel encounters by port area over time" />
        </div>
      )}

      {scenarios && (
        <>
          <h2>Closest large-vessel encounters</h2>
          <p className="lede">The {scenarios.length} closest passes with a large vessel, excluding pleasure craft, military vessels and likely launches; one per vessel pair per 15 minutes. Each opens a track plot from the raw AIS reports.</p>
          <div className="tablewrap">
            <table>
              <thead><tr><th>Date</th><th>Port area</th><th>Vessels</th><th>Geometry</th><th className="num">Closest pass (grid)</th><th className="num">Report-time check</th></tr></thead>
              <tbody>
                {scenarios.slice(0, 100).map((e) => (
                  <tr key={e.id}>
                    <td><Link to={`/encounters/${e.id}`}>{e.day}</Link></td>
                    <td>{REGION[e.region]}</td>
                    <td>{e.name_a || e.mmsi_a} <span className="muted small">({TYPE(e.type_a)})</span> × {e.name_b || e.mmsi_b} <span className="muted small">({TYPE(e.type_b)})</span></td>
                    <td>{e.geometry}</td>
                    <td className="num">{Math.round(e.min_sep_obs_m)} m</td>
                    <td className="num">{e.raw_min_sep_m === null ? "—" : `${Math.round(e.raw_min_sep_m)} m`}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="muted small">Ranked by the more conservative of two closest-pass estimates (1-minute grid and report-time check), because interpolating across gaps in the thinned AIS feed can produce near-zero distances that never happened. Small vessels typed as passenger craft that repeatedly come alongside tankers are usually crew launches or service boats; AIS vessel types cannot tell them apart from ordinary traffic. AIS positions are antenna positions, not hull outlines; two vessels of 200 m can show a separation of a few tens of metres while side by side. Report-time check: the other vessel's position interpolated to each actual report time.</p>
        </>
      )}
    </>
  );
}

export function EncounterPage() {
  const { id } = useParams();
  const p = useData<ScenarioPage>(id ? `encounters/${id}.json` : null);
  useTitle(p.data ? `${p.data.name_a || p.data.mmsi_a} × ${p.data.name_b || p.data.mmsi_b}` : "Encounter");
  return (
    <>
      <p className="small"><Link to="/encounters">← Encounters</Link></p>
      <Async state={p}>{(e) => <Scenario e={e} />}</Async>
    </>
  );
}

function Scenario({ e }: { e: ScenarioPage }) {
  const names: Record<string, string> = { [String(e.mmsi_a)]: e.name_a || String(e.mmsi_a), [String(e.mmsi_b)]: e.name_b || String(e.mmsi_b) };
  return (
    <>
      <h1>{names[String(e.mmsi_a)]} × {names[String(e.mmsi_b)]}</h1>
      <p className="lede">{REGION[e.region]} · {e.day} · {e.geometry} · first alert {fmtTime(e.t_first)}</p>
      <div className="grid">
        <Stat k="Closest pass (1-min tracks)" v={`${Math.round(e.min_sep_obs_m)} m`} sub={e.t_min_sep ? fmtTime(e.t_min_sep) : undefined} />
        <Stat k="Closest pass (report-time check)" v={e.raw_min_sep_m === null ? "—" : `${Math.round(e.raw_min_sep_m)} m`} />
        <Stat k="Predicted at first alert" v={`${Math.round(e.cpa_pred_m)} m`} sub={`in ${Math.round(e.tcpa_pred_s / 60)} min`} />
        <Stat k="Speeds at first alert" v={`${e.sog_a} / ${e.sog_b} kn`} sub={`${TYPE(e.type_a)} / ${TYPE(e.type_b)}`} />
      </div>
      <TrackPlot tracks={e.tracks} names={names} tMin={e.t_min_sep} />
      <p className="muted small">Local coordinates in metres relative to {names[String(e.mmsi_a)]}'s first position in the window; north is up. No basemap: the plot shows relative motion only. Markers every 2 minutes; the ring marks the moment of closest approach.</p>
    </>
  );
}

function TrackPlot({ tracks, names, tMin }: { tracks: ScenarioPage["tracks"]; names: Record<string, string>; tMin: number | null }) {
  const W = 720, H = 480, pad = 36;
  const pts = Object.values(tracks).flat();
  if (!pts.length) return null;
  const xs = pts.map((p) => p[1]), ys = pts.map((p) => p[2]);
  const [x0, x1, y0, y1] = [Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)];
  const span = Math.max(x1 - x0, y1 - y0, 200);
  const cx = (x0 + x1) / 2, cy = (y0 + y1) / 2;
  const scale = Math.min(W - 2 * pad, H - 2 * pad) / span;
  const X = (x: number) => W / 2 + (x - cx) * scale, Y = (y: number) => H / 2 - (y - cy) * scale;
  const bar = [50, 100, 200, 500, 1000, 2000, 5000].find((b) => b * scale > 60) ?? 100;
  const keys = Object.keys(tracks);
  return (
    <div className="figure">
      <div className="legend">{keys.map((k, i) => <span key={k}><i style={{ background: SERIES[i] }} />{names[k] ?? k}</span>)}</div>
      <svg className="chart" viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Vessel tracks around the encounter">
        <rect x={0} y={0} width={W} height={H} fill="none" stroke="var(--border)" />
        {keys.map((k, i) => {
          const tr = tracks[k];
          const at = tMin === null ? null : tr.reduce((b, p) => (Math.abs(p[0] - tMin) < Math.abs(b[0] - tMin) ? p : b), tr[0]);
          return (
            <g key={k}>
              <polyline points={tr.map((p) => `${X(p[1])},${Y(p[2])}`).join(" ")} fill="none" stroke={SERIES[i]} strokeWidth={2} strokeLinejoin="round" />
              {tr.filter((p, j) => j === 0 || Math.floor(p[0] / 120) !== Math.floor(tr[j - 1][0] / 120)).map((p) => (
                <circle key={p[0]} cx={X(p[1])} cy={Y(p[2])} r={3} fill={SERIES[i]} stroke="var(--surface)" strokeWidth={1.5} />
              ))}
              {at && <circle cx={X(at[1])} cy={Y(at[2])} r={8} fill="none" stroke="var(--text)" strokeWidth={1.5} />}
              <text className="label" x={X(tr[tr.length - 1][1]) + 6} y={Y(tr[tr.length - 1][2])}>{names[k] ?? k}</text>
            </g>
          );
        })}
        <line x1={pad} x2={pad + bar * scale} y1={H - 14} y2={H - 14} stroke="var(--text)" strokeWidth={2} />
        <text x={pad} y={H - 20}>{bar >= 1000 ? `${bar / 1000} km` : `${bar} m`}</text>
        <text x={W - 20} y={24} textAnchor="middle" className="label">N</text>
        <line x1={W - 20} x2={W - 20} y1={30} y2={50} stroke="var(--text)" strokeWidth={1.5} />
      </svg>
    </div>
  );
}
