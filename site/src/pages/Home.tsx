import { Link, useSearchParams } from "react-router-dom";
import type { ReactNode } from "react";
import { Async, Stat, useTitle } from "../components/ui";
import { EntityOutcome, FunnelView, JoinMap, ShipPicker, SourceDot, SourceLegend, TraceChain } from "../components/story";
import { useData, type SourceKey, type Trace, type Traces, type YearsInfo } from "../data";
import { num, pct } from "../format";

const REPO = "https://github.com/maxsondcook/HarborLedger/blob/main/";
const jump = (id: string) => document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "start" });

export default function Home() {
  useTitle(null);
  const tr = useData<Traces>("traces.json");
  const [params, setParams] = useSearchParams();
  const rows = tr.data?.vessels ?? [];
  const selected = params.get("ship") && rows.some((r) => r.slug === params.get("ship")) ? params.get("ship")! : rows[0]?.slug ?? "";
  const trace = useData<Trace>(selected ? `trace/${selected}.json` : null);
  const f = tr.data?.funnel;
  const px = f?.accuracy[0];
  return (
    <>
      <section className="hero">
        <h1>Five public sources describe the same ships, and no two share a key. HarborLedger joins them into one graph.</h1>
        <p className="lede">
          Navy contracts name a hull in free text. Ship tracking (AIS) broadcasts an MMSI. Coast Guard inspections use their
          own vessel ID, and the federal register uses an official number. This page shows how those records are joined,
          what the joined data makes possible, and the one application I chose to build on it: a ledger of Navy
          repair cost growth.
        </p>
        {f && (
          <div className="kpis">
            <div><b>{num(f.raw.reduce((a, r) => a + r.n, 0))}</b><span>raw records</span></div>
            <div><b>{num(f.links)}</b><span>links tested, each with provenance</span></div>
            <div><b>{num(f.entities)}</b><span>real-world vessels resolved</span></div>
            {px && <div><b>{px.correct}/{px.n}</b><span>held-out AIS ↔ Coast Guard matches correct</span></div>}
          </div>
        )}
        <p className="small">
          <button className="linkbtn" onClick={() => jump("unite")}>1 · Uniting the data</button> ·{" "}
          <button className="linkbtn" onClick={() => jump("options")}>2 · What it makes possible</button> ·{" "}
          <button className="linkbtn" onClick={() => jump("built")}>3 · What I built</button>
        </p>
      </section>

      {/* ---------------- 1. Uniting the data ---------------- */}
      <div className="step-k" id="unite">Step 1 · Uniting the data</div>
      <h2>Which identifier joins each pair of sources</h2>
      <p className="muted small" style={{ maxWidth: 820 }}>
        Each source has its own identifier. The graph is joined one pair of sources at a time, on an identifier both of them
        record: hull number, IMO, MMSI, call sign or official number. No join uses a name alone. Every rule below writes
        edges with a confidence and its evidence. Rules below 0.5 are kept for audit but are not merged.
      </p>
      <Async state={tr}>{(d) => <JoinMap f={d.funnel} />}</Async>

      <h2>Follow one ship through the joins</h2>
      <p className="muted small" style={{ maxWidth: 820 }}>
        No single vessel is in all five sources. Navy ships join four (contracts, Wikipedia, AIS, Coast Guard inspections) and
        commercial ships three (AIS and both Coast Guard systems). Each card is one source's own record, under that source's own
        name and identifiers. Between the cards is the rule that joined them and the evidence it used.
      </p>
      <SourceLegend />
      <Async state={tr}>
        {(d) => <ShipPicker rows={d.vessels} selected={selected} onSelect={(s) => setParams({ ship: s }, { replace: true })} />}
      </Async>
      <Async state={trace}>
        {(t) => (
          <>
            <h3 style={{ margin: "14px 0 8px" }}>
              {t.name ?? t.hull}{t.hull && t.name ? ` (${t.hull})` : ""}: {t.records.length} records from {t.sources.length} sources
            </h3>
            <TraceChain t={t} />
            <h3 style={{ margin: "18px 0 0" }}>…resolved into one vessel</h3>
            <EntityOutcome t={t} />
          </>
        )}
      </Async>

      <h2>From raw records to vessels</h2>
      <Async state={tr}>
        {(d) => (
          <>
            <FunnelView f={d.funnel} />
            <p className="small">
              <Link to="/data">Sources, terms, held-out tests, misses and provenance on the Data engineering page →</Link>
            </p>
          </>
        )}
      </Async>

      {/* ---------------- 2. Options ---------------- */}
      <Options />

      {/* ---------------- 3. What I built ---------------- */}
      <Built />

      <h2>Explore the graph</h2>
      <div className="cards-2">
        <div className="card"><b><Link to="/vessels">Vessels</Link></b><p className="muted small">Every resolved vessel, with its identifiers, links, confidence and evidence.</p></div>
        <div className="card"><b><Link to="/yards">Shipyards and contractors</Link></b><p className="muted small">Who wins Navy repair work, under which legal entities, and who owns whom over time.</p></div>
      </div>
      <h2>Write-ups from the other questions</h2>
      <ul className="findings small">
        <li><a href={REPO + "docs/findings/collision-alerts-real-traffic-baseline.md"}>Straight-line collision alerts are right about half the time; context makes them better</a></li>
        <li><a href={REPO + "docs/findings/service-boats-inflate-near-miss-counts.md"}>Most "close calls" with large ships are service boats doing their job</a></li>
        <li><a href={REPO + "docs/findings/harbor-tugs-busier-than-inventory.md"}>Busy harbor tugs move more than the port's emissions inventory assumes</a></li>
        <li><a href={REPO + "docs/findings/weather-adds-little-to-coastal-trips.md"}>Weather adds about an hour to a big ship's coastal trip; schedules add far more</a></li>
        <li><a href="https://doi.org/10.5281/zenodo.24047861">Open close-quarters encounter benchmark (Zenodo, DOI 10.5281/zenodo.24047861)</a></li>
      </ul>
    </>
  );
}

/* ---------------- 2. What the unified data makes possible ---------------- */

type LedgerRow = { closed: number; g_exopt: number | null };
type Enc = { alert_precision_traffic: number; by_region: Record<string, { launch_share_of_large_encounters?: number | null }> };
type Act = { spb_assist_tugs: { n: number; active_hours_annualized_mean: number }; benchmarks: { POLA_2023_inventory_assist_tug_avg_hours: number } };
type Col = { models: { model: string; auc: number }[] };
type Wx = { leg_model_forecast?: { gain_from_conditions_hours: number } | null };

type Chip = SourceKey | string;
const SRC = new Set(["usaspending", "wikipedia", "ais", "psix", "mvus"]);
const Joins = ({ via }: { via: Chip[] }) => (
  <div className="joins">
    {via.map((c, i) => (
      <span key={i} style={{ display: "inline-flex", gap: 6, alignItems: "center" }}>
        {i > 0 && <span aria-hidden="true">+</span>}
        <span className="joinchip">{SRC.has(c) ? <SourceDot s={c as SourceKey} label /> : c}</span>
      </span>
    ))}
  </div>
);

function Option({ via, title, children, to, chosen = false }: { via: Chip[]; title: string; children: ReactNode; to: string; chosen?: boolean }) {
  return (
    <div className={`card ${chosen ? "chosen" : "explored"}`}>
      {chosen ? <span className="badge accent" style={{ marginBottom: 8 }}>Chosen · built in step 3</span> : <span className="badge" style={{ marginBottom: 8 }}>Explored</span>}
      <Joins via={via} />
      <b>{title}</b>
      <p className="small">
        {children}{" "}
        {chosen ? <button className="linkbtn" onClick={() => jump("built")}>See the build ↓</button> : <Link to={to}>See it →</Link>}
      </p>
    </div>
  );
}

const medianOf = (v: number[]) => { const s = [...v].sort((a, b) => a - b); return s.length ? s[Math.floor(s.length / 2)] : null; };

function Options() {
  const led = useData<LedgerRow[]>("ledger.json").data;
  const latest = useData<YearsInfo>("years.json").data?.latest ?? null;
  const enc = useData<Enc>(latest ? `encounters_${latest}.json` : null).data;
  const act = useData<Act>(latest ? `activity_${latest}.json` : null).data;
  const col = useData<Col>("collision.json").data;
  const wx = useData<Wx>("weather.json").data;
  const med = medianOf((led ?? []).filter((r) => r.closed && r.g_exopt !== null).map((r) => r.g_exopt as number));
  const spb = enc?.by_region?.san_pedro_bay?.launch_share_of_large_encounters;
  const full = col?.models.find((m) => m.model === "full model"), kin = col?.models.find((m) => m.model.startsWith("kinematic"));
  const pc = (x: number) => `${Math.round(x * 100)}%`;
  return (
    <>
      <div className="step-k" id="options">Step 2 · What the unified data makes possible</div>
      <h2>Questions none of the sources can answer alone</h2>
      <p className="muted small" style={{ maxWidth: 820 }}>
        Each question below needs at least one join from step 1. The chips show which sources it combines. I tried each one far
        enough to get a first number, then chose one to build properly.
      </p>
      <div className="answers">
        <Option chosen via={["usaspending", "wikipedia"]} to="/ledger"
          title={med !== null ? `How much do Navy repair jobs grow past their award? (median ${pct(med).replace("+", "")})` : "How much do Navy repair jobs grow past their award?"}>
          Needs the ship named in each contract's free text resolved to a hull, and every later modification tied back to its job.
        </Option>
        {enc && full && kin && (
          <Option via={["ais", "NOAA buoys", "vessel types"]} to="/encounters"
            title={`Which collision alerts come true? (${pc(enc.alert_precision_traffic)}; context lifts AUC ${kin.auc.toFixed(2)} → ${full.auc.toFixed(2)})`}>
            Pairs of AIS tracks joined minute by minute, then to sea state and vessel type, tested on the following year. Published as an open benchmark.
          </Option>
        )}
        {act && (
          <Option via={["ais", "psix", "mvus", "CalEPA tracts"]} to="/activity"
            title={`How busy are harbor tugs? (~${num(act.spb_assist_tugs.active_hours_annualized_mean)} active hours vs ${num(act.benchmarks.POLA_2023_inventory_assist_tug_avg_hours)} in the port's inventory)`}>
            Needs tugs identified through Coast Guard records and their tracks split into work modes.
          </Option>
        )}
        {spb !== undefined && spb !== null && (
          <Option via={["ais", "vessel behaviour"]} to="/encounters"
            title={`Who is in large-ship close calls? (${pc(spb)} in San Pedro Bay involve service boats)`}>
            Their AIS type rarely says so. They show up when each small vessel is joined to how many different large ships it meets.
          </Option>
        )}
        {wx?.leg_model_forecast && (
          <Option via={["ais", "NOAA buoys", "NOAA forecasts"]} to="/ocean"
            title={`Does a wave forecast predict coastal trip time? (error cut by ${wx.leg_model_forecast.gain_from_conditions_hours.toFixed(2)} h)`}>
            Coastal legs cut from AIS, joined to the forecast available at departure along the route.
          </Option>
        )}
      </div>
    </>
  );
}

/* ---------------- 3. What I built ---------------- */

type ModelWin = {
  window_days: number; label: string; n_test: number; pass_preregistered: boolean;
  models: Record<string, { mae: number }>; gbm_minus_persistence_mae_gain_ci95: [number, number];
};
type DelayRes = { window_days: number; auc_gbm: number; auc_office_rate_only: number; rate_test: number };
type GrowthModel = { ledger_funnel: Record<string, number>; windows: ModelWin[]; delay: DelayRes[] };

const LEDGER_STEPS: [string, string][] = [
  ["contracts", "Navy repair and construction contracts, FY2015–2026"],
  ["single_vessel", "Tied to exactly one ship by the hull join"],
  ["repair_type", "Repair availabilities (not new construction)"],
  ["non_nuclear", "Non-nuclear"],
  ["not_planning", "Not planning-only contracts"],
  ["base_ge_5m", "Base award of at least $5M"],
  ["closed", "Closed, so final growth is known"],
];

function Built() {
  const gm = useData<GrowthModel>("growth_model.json");
  const led = useData<LedgerRow[]>("ledger.json").data;
  const closed = (led ?? []).filter((r) => r.closed && r.g_exopt !== null).map((r) => r.g_exopt as number);
  const med = medianOf(closed);
  const over25 = closed.length ? closed.filter((g) => g > 0.25).length / closed.length : null;
  return (
    <>
      <div className="step-k" id="built">Step 3 · What I built</div>
      <h2>The Navy repair cost ledger</h2>
      <div className="why">
        <div className="card"><b>It needs the hardest join</b><span className="small muted">Contracts never carry a hull field. Every number here depends on reading the ship out of free text, which was tested on a held-out sample.</span></div>
        <div className="card"><b>It is about public money</b><span className="small muted">Ship repair that runs over its award delays ships returning to the fleet. The ledger measures that growth job by job.</span></div>
        <div className="card"><b>It can be tested honestly</b><span className="small muted">Modifications arrive over time, so an early-warning model can be trained on earlier years and scored on later ones against targets set beforehand.</span></div>
      </div>

      <Async state={gm}>
        {(m) => {
          const top = m.ledger_funnel.contracts || 1;
          const w180 = m.windows.find((w) => w.window_days === 180 && w.label === "g_exopt");
          const d180 = m.delay.find((d) => d.window_days === 180);
          return (
            <>
              <h3 style={{ margin: "16px 0 4px" }}>From contracts to a clean ledger</h3>
              <div className="lf" role="list">
                {LEDGER_STEPS.filter(([k]) => m.ledger_funnel[k] !== undefined).map(([k, label]) => (
                  <div key={k} className="lf-row" role="listitem">
                    <span>{label}</span>
                    <span className="lf-bar" aria-hidden="true"><i style={{ width: `${(100 * m.ledger_funnel[k]) / top}%` }} /></span>
                    <span className="n">{num(m.ledger_funnel[k])}</span>
                  </div>
                ))}
              </div>

              <h3 style={{ margin: "18px 0 8px" }}>Results</h3>
              <div className="grid">
                {med !== null && <Stat k="Median cost growth" v={pct(med).replace("+", "")} sub={`beyond base award and priced options · ${num(closed.length)} closed jobs`} />}
                {over25 !== null && <Stat k="Jobs growing more than 25%" v={`${Math.round(over25 * 100)}%`} sub="of closed availabilities" />}
                {d180 && <Stat k="Late-delay warning at day 180" v={`AUC ${d180.auc_gbm.toFixed(2)}`} sub={`vs ${d180.auc_office_rate_only.toFixed(2)} from the contracting office's history alone`} />}
                {w180 && (
                  <Stat k="Final growth forecast at day 180" v={`MAE ${w180.models.gbm.mae.toFixed(3)}`}
                    sub={`vs ${w180.models.global_median.mae.toFixed(3)} for the median; passes its preset target`} />
                )}
              </div>
              {w180 && (
                <p className="note small">
                  <b>Where it fell short:</b> by day 180 the growth already in the modifications predicts final growth almost as
                  well as the model does (MAE {w180.models.persistence.mae.toFixed(3)} vs {w180.models.gbm.mae.toFixed(3)}; the
                  gain's 95% CI is {w180.gbm_minus_persistence_mae_gain_ci95[0].toFixed(3)} to {w180.gbm_minus_persistence_mae_gain_ci95[1].toFixed(3)}).
                  The delay flag adds less than its AUC suggests: the label is a delay or penalty keyword in a later modification,
                  so it partly records how each contracting office words its paperwork, and the office's own history scores close
                  behind. Trained on jobs starting FY2021 or earlier, tested on FY2022 and later.
                </p>
              )}
              <Link className="cta" to="/ledger">Open the repair cost ledger →</Link>
            </>
          );
        }}
      </Async>
    </>
  );
}
