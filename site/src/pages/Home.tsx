import { Link } from "react-router-dom";
import { Async, Stat, useTitle } from "../components/ui";
import { useData, type Meta, type YearsInfo } from "../data";
import { num, pct } from "../format";

export default function Home() {
  useTitle(null);
  const meta = useData<Meta>("meta.json");
  return (
    <>
      <h1>California's working waterfront, in public data</h1>
      <p className="lede">
        HarborLedger links records that were never designed to be joined: Navy repair and shipbuilding contracts,
        ship tracking (AIS), Coast Guard inspection and documentation records, shipyard ownership, and port
        activity. Every link between two records carries a confidence score, the method that made it, and its
        source, so you can see why the site thinks two records describe the same ship.
      </p>
      <Async state={meta}>
        {(m) => (
          <div className="grid">
            <Stat k="Navy contracts" v={num(m.counts.contracts)} sub={`${num(m.counts.contract_actions)} modifications`} />
            <Stat k="Repair availabilities" v={num(m.counts.availabilities)} sub="cost-growth ledger" />
            <Stat k="Vessel records" v={num(m.counts.vessels)} sub="AIS, Coast Guard, register, Navy hulls" />
            <Stat k="Links (edges)" v={num(m.counts.edges)} sub="each with confidence + provenance" />
            <Stat k="Curated firms" v={num(m.counts.firms)} sub="with dated ownership" />
          </div>
        )}
      </Async>
      <Findings />
      <h2>Explore</h2>
      <div className="cards-2">
        <div className="card">
          <b><Link to="/vessels">Vessels</Link></b>
          <p className="muted small">Commercial vessels seen off California, matched to Coast Guard records and the federal vessel register (coastwise rights, builder, owner), plus Navy hulls named in repair contracts.</p>
        </div>
        <div className="card">
          <b><Link to="/yards">Shipyards and contractors</Link></b>
          <p className="muted small">Who wins Navy shipbuilding and repair work, under which legal entities, and who owns whom over time.</p>
        </div>
        <div className="card">
          <b><Link to="/ledger">Repair cost ledger</Link></b>
          <p className="muted small">How much Navy surface-ship repair jobs grow beyond their base award, and how early that growth shows up in public records.</p>
        </div>
        <div className="card">
          <b><Link to="/activity">Harbor activity</Link> · <Link to="/encounters">Encounters</Link></b>
          <p className="muted small">Tug operating hours by mode and season, and close-quarters vessel encounters drawn from AIS.</p>
        </div>
      </div>
    </>
  );
}

type LedgerRow = { closed: number; g_exopt: number | null };
type Enc = { alert_precision_traffic: number; alert_precision_by_tcpa_min: Record<string, number>; likely_launch_vessels?: number[]; by_region: Record<string, { launch_share_of_large_encounters?: number | null }> };
type Act = { spb_assist_tugs: { n: number; active_hours_annualized_mean: number }; benchmarks: { POLA_2023_inventory_assist_tug_avg_hours: number }; seasonality_peak_to_trough?: number };
type Px = { correct: number; n: number; same_as: number; vessels: number };
type Gm = { windows: { window_days: number; label: string; models: Record<string, { mae_vs_global_median: number }> }[] };

/** Headline findings, each computed from the exported data so the home page never drifts from the analysis. */
function Findings() {
  const led = useData<LedgerRow[]>("ledger.json").data;
  const latest = useData<YearsInfo>("years.json").data?.latest ?? null;
  const enc = useData<Enc>(latest ? `encounters_${latest}.json` : null).data;
  const act = useData<Act>(latest ? `activity_${latest}.json` : null).data;
  const px = useData<Px>("psix_match.json").data;
  const gm = useData<Gm>("growth_model.json").data;
  const g = (led ?? []).filter((r) => r.closed && r.g_exopt !== null).map((r) => r.g_exopt as number).sort((a, b) => a - b);
  const med = g.length ? g[Math.floor(g.length / 2)] : null;
  const w180 = gm?.windows.find((w) => w.window_days === 180 && w.label === "g_exopt");
  const spb = enc?.by_region?.san_pedro_bay?.launch_share_of_large_encounters;
  const pc = (x: number) => `${Math.round(x * 100)}%`;
  return (
    <>
      <h2>What the data shows</h2>
      {latest && <p className="muted small">Ship-tracking findings use AIS year {latest}; earlier years are on each page.</p>}
      <ul className="findings">
        {med !== null && w180 && (
          <li>
            <b>Navy repair jobs grow a median {pct(med)}</b> beyond their base award and pre-priced options, and the growth is
            mostly visible early: by day 180, "growth so far" alone cuts forecast error by {pc(w180.models.persistence.mae_vs_global_median)}, and
            a gradient-boosted model adds almost nothing on top. <Link to="/ledger">Ledger →</Link>
          </li>
        )}
        {enc && (
          <li>
            <b>Straight-line collision alerts come true {pc(enc.alert_precision_traffic)} of the time</b>:{" "}
            {pc(enc.alert_precision_by_tcpa_min["0-2"])} when raised under 2 minutes ahead, {pc(enc.alert_precision_by_tcpa_min["5-10"])} at 5–10 minutes.
            That is the baseline a collision-avoidance model has to beat. <Link to="/encounters">Encounters →</Link>
          </li>
        )}
        {enc && spb !== undefined && spb !== null && (
          <li>
            <b>Most close passes with large ships in San Pedro Bay involve service boats</b>: {enc.likely_launch_vessels?.length ?? "Many"} small vessels that come
            alongside many different large ships account for {pc(spb)} of large-vessel encounters there, and their AIS type
            rarely says so.
          </li>
        )}
        {act && (
          <li>
            <b>Busy harbor tugs log about {num(act.spb_assist_tugs.active_hours_annualized_mean)} active hours a year</b> on AIS, above the
            {" "}{num(act.benchmarks.POLA_2023_inventory_assist_tug_avg_hours)} hours in the Port of LA's inventory; season does not explain the gap
            {act.seasonality_peak_to_trough ? ` (busiest month only ${act.seasonality_peak_to_trough}× the quietest)` : ""}. <Link to="/activity">Activity →</Link>
          </li>
        )}
        {px && (
          <li>
            <b>Ship tracking and Coast Guard records can be joined reliably</b> for commercial vessels: {num(px.same_as)} of {num(px.vessels)} matched, and {px.correct} of {px.n}{" "}
            randomly reviewed matches were correct. <Link to="/methods">Methods →</Link>
          </li>
        )}
      </ul>
    </>
  );
}
