import { Link, useSearchParams } from "react-router-dom";
import type { ReactNode } from "react";
import { Async, useTitle } from "../components/ui";
import { EntityOutcome, FunnelView, ShipPicker, SourceDot, SourceLegend, TraceChain } from "../components/story";
import { useData, type SourceKey, type Trace, type Traces, type YearsInfo } from "../data";
import { num, pct } from "../format";

const REPO = "https://github.com/maxsondcook/HarborLedger/blob/main/";

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
        <h1>Five public sources name the same ship five different ways. HarborLedger resolves them into one vessel.</h1>
        <p className="lede">
          Navy contracts name a hull in free text. Ship tracking (AIS) broadcasts an MMSI. Coast Guard inspections use their
          own vessel ID, and the federal register uses an official number. No two sources share a key. HarborLedger extracts
          the identifiers, joins the records with tested rules, and gives every link a confidence score, a method and a
          source. Pick a vessel below to see the joins step by step.
        </p>
        {f && (
          <div className="kpis">
            <div><b>{num(f.raw.reduce((a, r) => a + r.n, 0))}</b><span>raw records</span></div>
            <div><b>{num(f.links)}</b><span>links tested, each with provenance</span></div>
            <div><b>{num(f.entities)}</b><span>real-world vessels resolved</span></div>
            {px && <div><b>{px.correct}/{px.n}</b><span>held-out AIS ↔ Coast Guard matches correct</span></div>}
          </div>
        )}
      </section>

      <h2>One ship, many records</h2>
      <p className="muted small" style={{ maxWidth: 820 }}>
        Five sources feed the graph; no single vessel is in all five. Navy ships join four (contracts, Wikipedia, AIS,
        Coast Guard inspections) and commercial ships three (AIS and both Coast Guard systems). Each card is one source's own record, using that source's own name and identifiers. Between the cards is the rule
        that joined them and the evidence it used. Joins use stable IDs (MMSI, IMO, call sign, official number, hull number),
        never a name alone.
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
            <p className="small" style={{ maxWidth: 860 }}>
              {d.funnel.accuracy.map((a, i) => (
                <span key={i}>
                  <b>{a.test}:</b> {a.correct}/{a.n} correct
                  {a.ci95 ? ` (95% CI ${Math.round(a.ci95[0] * 100)}–${Math.round(a.ci95[1] * 100)}%)` : ""}
                  {a.recall !== null && a.recall !== undefined ? `, recall ${pct(a.recall, 0).replace("+", "")}` : ""}.{" "}
                </span>
              ))}
              {d.funnel.bridge.links ? (
                <span>
                  <b>Navy hull ↔ AIS:</b> {d.funnel.bridge.links} links from Wikipedia infobox IMO/MMSI numbers; the call sign,
                  which the rule does not use, agrees on {d.funnel.bridge.call_sign_agrees}.{" "}
                </span>
              ) : null}
              <Link to="/data">How every join is built and tested →</Link>
            </p>
          </>
        )}
      </Async>

      <Answers />

      <h2>Explore it yourself</h2>
      <div className="cards-2">
        <div className="card"><b><Link to="/vessels">Vessels</Link></b><p className="muted small">Every resolved vessel, with its identifiers, links, confidence and evidence.</p></div>
        <div className="card"><b><Link to="/yards">Shipyards and contractors</Link></b><p className="muted small">Who wins Navy repair work, under which legal entities, and who owns whom over time.</p></div>
        <div className="card"><b><Link to="/ledger">Repair cost ledger</Link></b><p className="muted small">How much Navy repair jobs grow beyond their base award.</p></div>
        <div className="card"><b><Link to="/activity">Harbor activity</Link> · <Link to="/encounters">Encounters</Link> · <Link to="/ocean">Weather &amp; fishing</Link></b><p className="muted small">Tug hours, close-quarters encounters, and ships and fishing against ocean data.</p></div>
      </div>
      <h2>Write-ups and data</h2>
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

type LedgerRow = { closed: number; g_exopt: number | null };
type Enc = { alert_precision_traffic: number; likely_launch_vessels?: number[]; by_region: Record<string, { launch_share_of_large_encounters?: number | null }> };
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

function Answer({ via, title, children, to }: { via: Chip[]; title: string; children: ReactNode; to: string }) {
  return (
    <div className="card">
      <Joins via={via} />
      <b>{title}</b>
      <p className="small">{children} <Link to={to}>See it →</Link></p>
    </div>
  );
}

/** Findings, each labelled with the joins that made it possible; numbers come from the exported results. */
function Answers() {
  const led = useData<LedgerRow[]>("ledger.json").data;
  const latest = useData<YearsInfo>("years.json").data?.latest ?? null;
  const enc = useData<Enc>(latest ? `encounters_${latest}.json` : null).data;
  const act = useData<Act>(latest ? `activity_${latest}.json` : null).data;
  const col = useData<Col>("collision.json").data;
  const wx = useData<Wx>("weather.json").data;
  const tr = useData<Traces>("traces.json").data;
  const g = (led ?? []).filter((r) => r.closed && r.g_exopt !== null).map((r) => r.g_exopt as number).sort((a, b) => a - b);
  const med = g.length ? g[Math.floor(g.length / 2)] : null;
  const spb = enc?.by_region?.san_pedro_bay?.launch_share_of_large_encounters;
  const full = col?.models.find((m) => m.model === "full model"), kin = col?.models.find((m) => m.model.startsWith("kinematic"));
  const navyRows = tr?.vessels.filter((v) => v.kind === "navy") ?? [];
  const navy = navyRows.length;
  const pc = (x: number) => `${Math.round(x * 100)}%`;
  return (
    <>
      <h2>What the graph lets you answer</h2>
      <p className="muted small" style={{ maxWidth: 820 }}>Each answer depends on a join that none of the sources supports on its own. The chips show which sources it needed.</p>
      <div className="answers">
        {med !== null && (
          <Answer via={["usaspending", "wikipedia"]} title={`Navy repair jobs grow a median ${pct(med).replace("+", "")} past their award`} to="/ledger">
            Needs contract text resolved to specific hulls, and every modification tied back to its job.
          </Answer>
        )}
        {navy > 0 && (
          <Answer via={["usaspending", "wikipedia", "ais", "psix"]} title={`${navy} Navy ships: their repair contracts and their tracks in one place`} to={`/?ship=${navyRows[0]?.slug ?? ""}`}>
            Contracts name hulls; AIS names MMSIs. Wikipedia infobox IMO and MMSI numbers bridge the two on stable IDs, so a supply
            ship's repair bill sits next to where it actually sailed.
          </Answer>
        )}
        {enc && full && kin && (
          <Answer via={["ais", "NOAA buoys", "vessel types"]} title={`Collision alerts come true ${pc(enc.alert_precision_traffic)} of the time; context lifts AUC ${kin.auc.toFixed(2)} → ${full.auc.toFixed(2)}`} to="/encounters">
            Pairs of AIS tracks are joined minute by minute, then to sea state and vessel type, and tested on the following year.
          </Answer>
        )}
        {spb !== undefined && spb !== null && (
          <Answer via={["ais", "vessel behaviour"]} title={`${pc(spb)} of large-ship close calls in San Pedro Bay involve service boats`} to="/encounters">
            Their AIS type rarely says so. They show up when you join each small vessel to how many different large ships it meets.
          </Answer>
        )}
        {act && (
          <Answer via={["ais", "psix", "mvus", "CalEPA tracts"]} title={`Harbor tugs log ~${num(act.spb_assist_tugs.active_hours_annualized_mean)} active hours vs ${num(act.benchmarks.POLA_2023_inventory_assist_tug_avg_hours)} in the port's inventory`} to="/activity">
            Needs tugs identified through Coast Guard records, their tracks split into work modes, and the hours placed against disadvantaged-community tracts.
          </Answer>
        )}
        {wx?.leg_model_forecast && (
          <Answer via={["ais", "NOAA buoys", "NOAA forecasts"]} title={`A wave forecast cuts coastal trip-time error by ${wx.leg_model_forecast.gain_from_conditions_hours.toFixed(2)} h`} to="/ocean">
            Coastal legs cut from AIS are joined to the forecast available at departure, sampled along the route.
          </Answer>
        )}
      </div>
    </>
  );
}
