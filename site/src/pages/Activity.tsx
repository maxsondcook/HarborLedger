import { Link } from "react-router-dom";
import { HBar, LineChart, SERIES } from "../components/charts";
import { Async, Stat, useTitle } from "../components/ui";
import { useData } from "../data";
import { num } from "../format";

type Summary = {
  days: number; tugs_seen: number; coverage_days?: number;
  mode_hours_all_tugs: Record<string, number>;
  region_active_hours: Record<string, number>;
  share_active_hours_within_2mi_dac: number;
  spb_assist_tugs: {
    n: number; active_hours_annualized_mean: number; active_hours_annualized_median: number;
    active_hours_annualized_iqr: [number, number]; dac_share_of_active: number;
    e4_cap_1300_dac_hours_exceeded_annualized: number; e4_cap_2600_total_hours_exceeded_annualized: number;
  };
  by_month_spb_assist?: Record<string, { days_of_ais: number; mean_active_hours_per_tug_per_30d: number; median: number }>;
  seasonality_peak_to_trough?: number;
  benchmarks: { POLA_2023_inventory_assist_tug_avg_hours: number; CARB_2021_ship_assist_main_engine_hours: number };
};
type Monthly = { month: string; region: string; mode: string; near_dac: boolean; hours: number }[];
type Tug = { mmsi: number; name: string; days_seen: number; hours_active: number; hours_assist: number; hours_active_dac: number; spb_share: number; active_hours_annualized: number; assist_tug: boolean };

const REGION_LABEL: Record<string, string> = { san_pedro_bay: "San Pedro Bay", sf_bay: "SF Bay", san_diego: "San Diego", other: "Elsewhere" };
const MODE_LABEL: Record<string, string> = { idle: "Idle (< 0.5 kn)", assist: "Ship assist (near a moving large ship)", maneuver: "Maneuvering (0.5–5 kn)", transit: "Transit (≥ 5 kn)" };

export default function Activity() {
  useTitle("Harbor activity");
  const s = useData<Summary>("activity.json");
  const m = useData<Monthly>("activity_monthly.json");
  const tugs = useData<Tug[]>("activity_tugs.json");
  return (
    <>
      <h1>Harbor activity: tugs</h1>
      <p className="lede">
        Tug operating hours from AIS (vessel types 31, 32 and 52) in California waters, by operating mode, port area
        and month. AIS shows movement, not engine state, so these are <b>activity hours</b>, not engine hours. Each
        position is weighted by the time to the vessel's next report, capped at 10 minutes so gaps are not credited.
      </p>
      <Async state={s}>{(sum) => <Body s={sum} monthly={m.data} tugs={tugs.data} />}</Async>
    </>
  );
}

function Body({ s, monthly, tugs }: { s: Summary; monthly?: Monthly; tugs?: Tug[] }) {
  const a = s.spb_assist_tugs;
  const months = Object.keys(s.by_month_spb_assist ?? {}).sort();
  const fullMonths = months.filter((k) => (s.by_month_spb_assist?.[k].days_of_ais ?? 0) >= 20);
  const regions = ["san_pedro_bay", "sf_bay", "san_diego"];
  const daysOf = (mo: string) => s.by_month_spb_assist?.[mo]?.days_of_ais ?? 0;
  const regionSeries = regions.map((r) => ({
    name: REGION_LABEL[r],
    values: fullMonths.map((mo) => {
      const h = (monthly ?? []).filter((x) => x.month === mo && x.region === r && x.mode !== "idle").reduce((t, x) => t + x.hours, 0);
      return daysOf(mo) ? (h * 30) / daysOf(mo) : null;
    }),
  }));
  const modeRows = Object.entries(s.mode_hours_all_tugs).map(([k, v]) => ({ key: MODE_LABEL[k] ?? k, value: v }));
  return (
    <>
      <div className="grid">
        <Stat k="Days of AIS" v={num(s.coverage_days ?? s.days)} sub={`${num(s.tugs_seen)} tugs seen`} />
        <Stat k="San Pedro Bay assist tugs" v={num(a.n)} sub="≥ half their time in the bay, regular ship work" />
        <Stat k="Their active hours / year" v={num(a.active_hours_annualized_mean)} sub={`median ${num(a.active_hours_annualized_median)} · IQR ${num(a.active_hours_annualized_iqr[0])}–${num(a.active_hours_annualized_iqr[1])}`} />
        <Stat k="Port of LA inventory figure" v={num(s.benchmarks.POLA_2023_inventory_assist_tug_avg_hours)} sub="operator-reported engine hours, 11 assist tugs, 2023" />
      </div>
      <div className="note">
        AIS-observed activity for the busiest bay tugs runs above the Port of LA's operator-reported figure. Season is not
        the reason (monthly activity varies little; see the chart), and in a July test raising the speed threshold to
        2 knots still left it above, so GPS jitter is not either. The tugs here are selected <i>because</i> they assist
        ships, include Long Beach boats, and the figures come from different years and definitions (movement vs engine
        hours). Engine hour-meter data from a fleet would settle it.
      </div>

      {fullMonths.length > 1 ? (
        <div className="figure">
          <h3>Active tug hours per 30 days, by port area</h3>
          <p className="cap">All tugs, non-idle hours, scaled to a 30-day month so months with missing AIS days compare. Months with fewer than 20 days of AIS are left out.{s.seasonality_peak_to_trough ? ` For the bay assist tugs, the busiest month is ${s.seasonality_peak_to_trough}× the quietest.` : ""}</p>
          <LineChart xs={fullMonths.map((x) => x.slice(5))} series={regionSeries} fmt={(v) => num(Math.round(v))} label="Monthly active tug hours by region" />
        </div>
      ) : (
        <p className="muted small">Seasonal view appears once more than one full month of AIS is processed.</p>
      )}

      <div className="figure">
        <h3>How tugs spend their AIS-observed time</h3>
        <p className="cap">All tugs, all days processed. Ship assist is a proximity proxy: within 350 m of a moving cargo, tanker or ≥ 150 m vessel.</p>
        <HBar rows={modeRows} fmt={(v) => `${num(Math.round(v))} h`} color={SERIES[2]} label="Tug hours by mode" />
      </div>

      <h2>Near disadvantaged communities</h2>
      <p className="lede">
        CARB's harbor-craft rule caps some Tier 4 vessels on extensions at 1,300 hours a year within 2 miles of an SB 535
        disadvantaged community. Census tracts around the Los Angeles and Oakland harbors extend over the water, so
        nearly all port work counts as "near".
      </p>
      <div className="grid">
        <Stat k="All tugs: active hours within 2 mi" v={`${Math.round(s.share_active_hours_within_2mi_dac * 100)}%`} />
        <Stat k="Bay assist tugs: within 2 mi" v={`${Math.round(a.dac_share_of_active * 100)}%`} />
        <Stat k="Assist tugs over 1,300 near-DAC h/yr" v={`${a.e4_cap_1300_dac_hours_exceeded_annualized} of ${a.n}`} sub="AIS movement hours, annualized; the cap applies only to vessels on an E4 extension" />
      </div>

      {tugs && (
        <>
          <h2>Tugs</h2>
          <div className="tablewrap">
            <table>
              <thead><tr><th>Tug</th><th className="num">Days seen</th><th className="num">Active h</th><th className="num">Assist h</th><th className="num">Active h near DAC</th><th className="num">Active h / year</th><th>Bay assist tug</th></tr></thead>
              <tbody>
                {tugs.slice(0, 120).map((t) => (
                  <tr key={t.mmsi}>
                    <td><Link to={`/vessels/mmsi-${t.mmsi}`}>{t.name || t.mmsi}</Link></td>
                    <td className="num">{t.days_seen}</td>
                    <td className="num">{num(Math.round(t.hours_active))}</td>
                    <td className="num">{num(Math.round(t.hours_assist))}</td>
                    <td className="num">{num(Math.round(t.hours_active_dac))}</td>
                    <td className="num">{num(Math.round(t.active_hours_annualized))}</td>
                    <td>{t.assist_tug ? <span className="badge accent">yes</span> : ""}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </>
  );
}
