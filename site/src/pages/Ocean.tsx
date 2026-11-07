import { useMemo, useState } from "react";
import { HBar, LineChart, SERIES } from "../components/charts";
import { Async, Stat, useTitle } from "../components/ui";
import { useData } from "../data";
import { num } from "../format";

type SpeedRow = { hs_lo: number; hs_hi: number; sea_rel: string; n: number; median_ratio: number; ci95: [number, number] };
type Weather = {
  years: number[];
  coverage: { vessel_hours: number; with_waves: number; with_wind: number; big_ship_open_water_hours: number; big_ships: number };
  speed_loss: SpeedRow[];
  legs: { n: number; ships: number; northbound: number; southbound: number; median_hours: number; median_track_nm: number };
  leg_model: {
    n_train: number; n_test: number; mae_hours: Record<string, number>; gain_from_conditions_hours: number; gain_ci95: [number, number];
    median_leg_hours_test: number;
    weather_added_hours_by_head_sea: { northbound: boolean; head_hs_lo: number; head_hs_hi: number; median_added_h: number; n: number }[];
  };
  small_craft: { class: string; hs_lo: number; hs_hi: number; median_rel: number; days: number }[];
  operability: { station: string; name: string; month: number; hours: number; [k: string]: number | string }[];
  notes: string[];
};
type Fishing = {
  n_train: number; n_test: number; fished_share_test: number;
  models: Record<string, { auc_fished: number; mae_hours: number }>;
  auc_gain_from_ocean_ci95: [number, number];
  by_sst: { sst: string; fished_share: number; hours_per_cell_week: number; n: number }[];
  by_front: { sst_front: string; fished_share: number; n: number }[];
  weekly_corr_spearman: Record<string, number>;
  weekly: { week: string; fishing_h: number; cuti: number | null; sst: number }[];
  notes: string[];
};

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const binLabel = (lo: number, hi: number) => (hi >= 9 ? `${lo}+ m` : `${lo}–${hi} m`);

export default function Ocean() {
  useTitle("Weather and fishing");
  const w = useData<Weather>("weather.json");
  const f = useData<Fishing>("fishing.json");
  return (
    <>
      <h1>Weather, sea state and fishing</h1>
      <p className="lede">
        Every hour of every vessel's AIS track joined to the nearest NOAA buoy's waves and wind, plus satellite
        sea-surface temperature, chlorophyll and the CUTI/BEUTI upwelling indices. Conditions come from the nearest
        buoy, not the ship itself, so local shelter behind headlands and islands is smoothed over.
      </p>
      <Async state={w}>{(d) => <WeatherBody d={d} />}</Async>
      <h2 id="fishing">Fishing and ocean conditions</h2>
      <Async state={f}>{(d) => <FishingBody d={d} />}</Async>
    </>
  );
}

function WeatherBody({ d }: { d: Weather }) {
  const hsBins = useMemo(() => [...new Set(d.speed_loss.map((r) => `${r.hs_lo}|${r.hs_hi}`))], [d]);
  const series = ["head", "beam", "following"].map((rel) => ({
    name: `${rel} seas`,
    values: hsBins.map((b) => {
      const r = d.speed_loss.find((x) => `${x.hs_lo}|${x.hs_hi}` === b && x.sea_rel === rel && x.n >= 30);
      return r ? Math.round((r.median_ratio - 1) * 1000) / 10 : null;
    }),
  }));
  const lm = d.leg_model;
  const order = ["distance / calm speed", "median for direction", "ship's own median leg", "model without sea conditions", "model with sea conditions"];
  const north = lm.weather_added_hours_by_head_sea.filter((r) => r.northbound && r.n >= 20);
  return (
    <>
      <div className="grid">
        <Stat k="Vessel-hours joined to buoys" v={num(d.coverage.vessel_hours)} sub={`${Math.round(d.coverage.with_waves * 100)}% with waves, ${Math.round(d.coverage.with_wind * 100)}% with wind`} />
        <Stat k="Big-ship open-water hours" v={num(d.coverage.big_ship_open_water_hours)} sub={`${num(d.coverage.big_ships)} cargo ships and tankers`} />
        <Stat k="LA ↔ SF coastal legs" v={num(d.legs.n)} sub={`${num(d.legs.ships)} ships · median ${d.legs.median_hours} h, ${d.legs.median_track_nm} nm`} />
      </div>

      <h2>How much big ships slow down</h2>
      <div className="figure">
        <h3>Speed change versus wave height, by sea direction</h3>
        <p className="cap">
          Median change in speed against each ship's own usual speed in the same area and season (which absorbs the
          voluntary 10-knot whale-protection zones). Steady open-water transits of cargo ships and tankers only.
        </p>
        <LineChart xs={hsBins.map((b) => { const [lo, hi] = b.split("|").map(Number); return binLabel(lo, hi); })} series={series} fmt={(v) => `${v > 0 ? "+" : ""}${v.toFixed(1)}%`} label="Speed change by wave height and sea direction" />
      </div>
      <div className="note">
        Big ships lose a few percent of speed in head seas of 3.5 m and more and almost nothing in beam or following
        seas, in line with published "involuntary speed loss" figures for large ships.
      </div>

      <h2>Can we predict the added time of a trip?</h2>
      <p className="lede">
        A coastal leg is a large ship's run between the Los Angeles/Long Beach and San Francisco approaches with no
        tracking gap over 3 hours. Northbound ships face California's prevailing northwesterly swell; southbound
        ships run with it. Trained on {num(lm.n_train)} legs from 2024, tested on {num(lm.n_test)} from 2025.
      </p>
      <div className="figure">
        <h3>Mean error predicting leg duration (hours, lower is better)</h3>
        <HBar rows={order.filter((k) => lm.mae_hours[k] !== undefined).map((k) => ({ key: k, value: lm.mae_hours[k] }))} fmt={(v) => `${v.toFixed(1)} h`} label="Leg duration error by method" />
      </div>
      <div className="note">
        Sea conditions cut the error by {lm.gain_from_conditions_hours} hours (95% CI {lm.gain_ci95[0]}–{lm.gain_ci95[1]}) on a typical
        {" "}{lm.median_leg_hours_test}-hour leg. The model uses the conditions that actually occurred, so this is the most a perfect
        forecast could achieve. Most of the remaining spread is not weather: ships routinely slow down to arrive
        when their berth is ready.
      </div>
      {north.length > 0 && (
        <div className="figure">
          <h3>Hours added by weather, northbound legs</h3>
          <p className="cap">Model's prediction under the leg's real conditions minus the same leg in calm seas, grouped by average head-sea wave height.</p>
          <HBar rows={north.map((r) => ({ key: `head seas ${binLabel(r.head_hs_lo < 0 ? 0 : r.head_hs_lo, r.head_hs_hi)}`, value: r.median_added_h, note: `${r.n} legs` }))} fmt={(v) => `${v.toFixed(1)} h`} color={SERIES[1]} label="Weather-added hours" />
        </div>
      )}

      <h2>Small craft stay in on rough days</h2>
      <SmallCraft rows={d.small_craft} />

      <h2>How often is the sea calm enough?</h2>
      <Operability rows={d.operability} />
      <ul className="small muted">{d.notes.map((n) => <li key={n}>{n}</li>)}</ul>
    </>
  );
}

function SmallCraft({ rows }: { rows: Weather["small_craft"] }) {
  const classes = [...new Set(rows.map((r) => r.class))];
  const bins = [...new Set(rows.map((r) => `${r.hs_lo}|${r.hs_hi}`))];
  const series = classes.map((c) => ({
    name: c,
    values: bins.map((b) => { const r = rows.find((x) => x.class === c && `${x.hs_lo}|${x.hs_hi}` === b && x.days >= 10); return r ? Math.round(r.median_rel * 100) : null; }),
  }));
  return (
    <div className="figure">
      <h3>Vessels at sea versus the day's maximum wave height</h3>
      <p className="cap">Vessels moving just outside each port area, as a percentage of the usual count for that port, month and weekday or weekend. Wave height from the port's offshore buoy.</p>
      <LineChart xs={bins.map((b) => { const [lo, hi] = b.split("|").map(Number); return hi >= 12 ? `${lo}+ m` : `${lo}–${hi} m`; })} series={series} fmt={(v) => `${v}%`} label="Small craft at sea by wave height" />
    </div>
  );
}

function Operability({ rows }: { rows: Weather["operability"] }) {
  const [limit, setLimit] = useState("le_1.5m");
  const stations = [...new Map(rows.map((r) => [r.station, r.name])).entries()];
  const val = (s: string, m: number) => rows.find((r) => r.station === s && r.month === m)?.[limit] as number | undefined;
  const shade = (v?: number) => (v === undefined ? "transparent" : `color-mix(in srgb, var(--series-1) ${Math.round(v * 85) + 5}%, var(--surface))`);
  return (
    <div className="figure">
      <p className="cap">Share of hours with significant wave height at or below a limit, by buoy and month (2024–2025). A small uncrewed or patrol vessel limited to a given sea state can expect to operate roughly this share of the time.</p>
      <div className="controls">
        <select value={limit} onChange={(e) => setLimit(e.target.value)} aria-label="Wave-height limit">
          {["1", "1.5", "2", "2.5", "3"].map((t) => <option key={t} value={`le_${t}m`}>Waves ≤ {t} m</option>)}
        </select>
      </div>
      <div className="tablewrap">
        <table>
          <thead><tr><th>Buoy</th>{MONTHS.map((m) => <th key={m} className="num">{m}</th>)}</tr></thead>
          <tbody>
            {stations.map(([s, name]) => (
              <tr key={s}>
                <td className="small"><span className="mono">{s}</span> {String(name).split(" - ")[0].split("(")[0]}</td>
                {MONTHS.map((_, i) => { const v = val(s, i + 1); return <td key={i} className="num" style={{ background: shade(v) }}>{v === undefined ? "—" : `${Math.round(v * 100)}`}</td>; })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="muted small">Values are percentages of hours.</p>
    </div>
  );
}

function FishingBody({ d }: { d: Fishing }) {
  const order = ["seasonal persistence (cell x month, 2024)", "location + month only", "location + month + ocean conditions"];
  return (
    <>
      <p className="lede">
        Fishing hours are inferred from AIS fishing vessels moving at 1–5 knots on a turning track, outside harbors,
        summed per 0.25° cell and week. Only AIS-equipped boats are seen, mostly the larger ones.
      </p>
      <div className="figure">
        <h3>Predicting which cells are fished in a 2025 week (AUC, higher is better)</h3>
        <HBar rows={order.filter((k) => d.models[k]).map((k) => ({ key: k, value: d.models[k].auc_fished, note: `mean error ${d.models[k].mae_hours.toFixed(2)} h per cell-week` }))} fmt={(v) => v.toFixed(3)} color={SERIES[2]} label="Fishing model comparison" />
      </div>
      <div className="note">
        Ocean conditions add a small, consistent gain in predicting <i>where</i> fishing happens (AUC +{d.auc_gain_from_ocean_ci95[0]} to +{d.auc_gain_from_ocean_ci95[1]}, 95% CI), but not <i>how many hours</i>.
      </div>
      <div className="cards-2">
        <div className="figure">
          <h3>Fished share of cell-weeks by temperature-front strength</h3>
          <HBar rows={d.by_front.map((r, i) => ({ key: ["weakest fifth", "second", "middle", "fourth", "strongest fifth"][i] ?? r.sst_front, value: r.fished_share, note: `${r.n} cell-weeks` }))} fmt={(v) => `${Math.round(v * 100)}%`} label="Fishing by front strength" />
        </div>
        <div className="figure">
          <h3>Fished share of cell-weeks by sea-surface temperature</h3>
          <HBar rows={d.by_sst.map((r) => ({ key: `${r.sst.replace(/[()\]]/g, "").replace(", ", "–")} °C`, value: r.fished_share, note: `${r.n} cell-weeks` }))} fmt={(v) => `${Math.round(v * 100)}%`} color={SERIES[1]} label="Fishing by SST" />
        </div>
      </div>
      <ul className="small muted">
        {d.notes.map((n) => <li key={n}>{n}</li>)}
        <li>The speed-and-turning heuristic is confounded by sea state: boats that do go out in heavy seas move slowly and turn more, which looks like fishing. So fishing <i>share</i> is not reported against wave height; vessels-at-sea counts are used instead (above).</li>
      </ul>
    </>
  );
}
