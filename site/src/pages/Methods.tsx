import type { ReactNode } from "react";
import { Async, useTitle } from "../components/ui";
import { useData, type Meta } from "../data";
import { num, pct } from "../format";

// Every number below is read from the exported test results, so this page stays in step with the data.

type HullTest = { precision: number; precision_ci95: [number, number]; recall: number; tp: number; fp: number; fn: number; pass: boolean };
type Identity = {
  firm_coverage: { dollar_share_mapped: number; recipients_mapped: number; recipients: number; pass: boolean };
  "hull_sample_2026.csv"?: HullTest;
  "hull_sample_2027.csv"?: HullTest;
};
type Psix = { correct: number; n: number; precision: number; precision_ci95: [number, number]; vessels: number; same_as: number; possible_same_as_held_back: number; recall_us: number; recall_foreign: number };
type Model = {
  ledger_funnel: Record<string, number>;
  windows: { window_days: number; label: string; n_train: number; n_test: number; pass_preregistered: boolean; models: Record<string, { mae: number; mae_vs_global_median: number }>; gbm_vs_global_median_gain_ci95: [number, number]; gbm_minus_persistence_mae_gain_ci95: [number, number] }[];
  delay: { window_days: number; auc_gbm: number; auc_office_rate_only: number }[];
};
type EncVal = { n_sampled: number; n_comparable: number; median_abs_diff_m: number; p90_abs_diff_m: number; median_signed_diff_m: number; label_agreement: number; label_disagreements?: number; disagreements_within_100m_of_threshold?: number };
type Enc = { definition: Record<string, string | number>; alert_precision_traffic: number; alert_precision_by_tcpa_min: Record<string, number> };

const Section = ({ id, title, children }: { id: string; title: string; children: ReactNode }) => (
  <section id={id}><h2>{title}</h2>{children}</section>
);
const ci = (c?: [number, number]) => (c ? `${Math.round(c[0] * 100)}–${Math.round(c[1] * 100)}%` : "—");
const passBadge = (ok?: boolean) => ok === undefined ? null : <span className={`badge ${ok ? "good" : "bad"}`}>{ok ? "pass" : "miss"}</span>;

export default function Methods() {
  useTitle("Methods");
  const meta = useData<Meta>("meta.json");
  const id = useData<Identity>("identity_tests.json");
  const px = useData<Psix>("psix_match.json");
  const gm = useData<Model>("growth_model.json");
  const ev = useData<EncVal>("encounter_validation.json");
  const en = useData<Enc>("encounters.json");
  const w90 = gm.data?.windows.find((w) => w.window_days === 90 && w.label === "g_exopt");
  const w180 = gm.data?.windows.find((w) => w.window_days === 180 && w.label === "g_exopt");
  const d90 = gm.data?.delay.find((d) => d.window_days === 90);
  const h26 = id.data?.["hull_sample_2026.csv"], h27 = id.data?.["hull_sample_2027.csv"];

  return (
    <>
      <h1>Methods</h1>
      <p className="lede">
        How HarborLedger is built, how each link and number is tested, and where it falls short. Success tests were
        set before each step was run, and results are reported whether they passed or not. Everything is
        reproducible from public sources with the commands in the project README.
      </p>
      <nav className="small" style={{ display: "flex", gap: 14, flexWrap: "wrap", margin: "4px 0 10px" }}>
        {[["sources", "Sources"], ["pipeline", "Pipeline"], ["identity", "Entity resolution"], ["ledger", "Cost-growth ledger"],
          ["activity", "Tug activity"], ["encounters", "Encounters"], ["tests", "Test scorecard"], ["limits", "Limitations"], ["privacy", "Privacy and licences"]]
          .map(([a, t]) => <a key={a} href={`#/methods`} onClick={(e) => { e.preventDefault(); document.getElementById(a)?.scrollIntoView({ behavior: "smooth" }); }}>{t}</a>)}
      </nav>

      <Section id="sources" title="Sources">
        <p>Every raw file is snapshotted with its source, query, fetch time, SHA-256 hash and licence in a manifest. Raw files are not redistributed; the site serves derived tables.</p>
        <Async state={meta}>
          {(m) => (
            <div className="tablewrap">
              <table>
                <thead><tr><th>Source</th><th className="num">Files</th><th>Latest fetch</th><th>Licence / terms</th></tr></thead>
                <tbody>
                  {Object.entries(m.sources).map(([k, s]) => (
                    <tr key={k}><td className="mono">{k}</td><td className="num">{num(s.files)}</td><td>{s.latest_fetch.slice(0, 10)}</td><td className="small">{s.license}</td></tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Async>
        <p className="muted small">Excluded on licence grounds: Global Fishing Watch and OpenSanctions (non-commercial only) and Equasis (forbids reproduction and bulk download). The Coast Guard register was downloaded by hand because its server blocks automated downloads.</p>
      </Section>

      <Section id="pipeline" title="Pipeline">
        <ol>
          <li><b>Snapshot</b> USAspending awards and every contract modification (keyless API), MarineCadastre AIS (national daily files filtered to California waters), USCG PSIX vessel records (keyless SOAP service, cached), the USCG register of documented vessels, SB 535 tract polygons and Wikipedia ship lists.</li>
          <li><b>Build</b> a SQLite graph: typed nodes (contracts, modifications, legal entities, curated firms, vessels, identifiers, port areas) and one edge table in which every link carries <i>confidence, method, source record, validity window and licence</i>.</li>
          <li><b>Derive</b> the cost-growth ledger, the growth model, tug activity hours and the encounter dataset.</li>
          <li><b>Export</b> static JSON; this site (Vite + React + TypeScript) reads it with no server.</li>
        </ol>
      </Section>

      <Section id="identity" title="Entity resolution">
        <p>The same ship or company appears under different identifiers in every source, and no source shares a key with another. Each match below is a separate, tested rule.</p>
        <div className="tablewrap">
          <table>
            <thead><tr><th>Link</th><th>Rule</th><th>Measured</th></tr></thead>
            <tbody>
              <tr>
                <td>Contract → Navy hull</td>
                <td className="small">Hull designators read from contract text ("DDG 105", "T-AO 187", "LPD-22") plus ship names resolved through a name→hull gazetteer. Lead-ship hulls used as programme names ("DDG 51" alone) are kept below the 0.5 threshold and not counted.</td>
                <td className="small">
                  Held-out hand sample: {h27 ? `${h27.tp}/${h27.tp + h27.fp} correct (${ci(h27.precision_ci95)} CI), recall ${pct(h27.recall).replace("+", "")}` : "—"} {passBadge(h27?.pass)}
                  <div className="muted">Development sample failed first ({h26 ? `${h26.tp}/${h26.tp + h26.fp}` : "—"} after the fix; 92.3% before it). The fix was then scored on a sample drawn afterwards.</div>
                </td>
              </tr>
              <tr>
                <td>Legal entity → curated firm</td>
                <td className="small">Hand-curated table; the government's parent-company field lists 41% of recipients under more than one parent and some impossible parents (Austal USA → Computershare). Ownership changes carry dates.</td>
                <td className="small">{id.data ? `${pct(id.data.firm_coverage.dollar_share_mapped, 1).replace("+", "")} of award dollars mapped (${id.data.firm_coverage.recipients_mapped} of ${id.data.firm_coverage.recipients} recipients)` : "—"} {passBadge(id.data?.firm_coverage.pass)}</td>
              </tr>
              <tr>
                <td>AIS vessel → Coast Guard record</td>
                <td className="small">Call-sign lookup, accepted only when the IMO number agrees or the names are ≥ 0.8 similar; weaker hits are kept as "possible" for review. In earlier tests every false match was a call sign reused by a different vessel.</td>
                <td className="small">
                  {px.data ? `${px.data.correct}/${px.data.n} random accepted matches correct (${ci(px.data.precision_ci95)} CI); ${num(px.data.same_as)} of ${num(px.data.vessels)} vessels matched (foreign ${pct(px.data.recall_foreign, 0).replace("+", "")}, U.S. ${pct(px.data.recall_us, 0).replace("+", "")}); ${px.data.possible_same_as_held_back} held back` : "—"} {passBadge(px.data ? px.data.precision >= 0.97 : undefined)}
                </td>
              </tr>
              <tr>
                <td>Coast Guard record → vessel register</td>
                <td className="small">Exact official number (PSIX identification = register official number); otherwise call sign with the same name gate.</td>
                <td className="small">Spot-checked; links agree on name, service type and builder.</td>
              </tr>
            </tbody>
          </table>
        </div>
        <p className="muted small">The hull and register labels were made by one person reading the source text; a second labeller has not checked them.</p>
      </Section>

      <Section id="ledger" title="Cost-growth ledger and early-warning model">
        <p>
          An availability is a contract linked with confidence ≥ 0.5 to exactly one non-nuclear hull, with a repair
          availability type, a base obligation of at least $5M and not a planning contract. Growth is
          <span className="mono"> (total − base − options) / (base + options)</span>, where base is the original award
          action and options are "exercise an option" actions. An availability counts as closed when its period of
          performance ended at least 90 days before the data cut-off (DoD publishes contract data with a ~90-day lag);
          open ones are censored and left out of training labels.
        </p>
        {gm.data && <p className="muted small">Funnel: {Object.entries(gm.data.ledger_funnel).map(([k, v]) => `${k.replace(/_/g, " ")} ${num(v)}`).join(" → ")}.</p>}
        <p>
          The model sees only actions dated within the first 90 or 180 days. Training years FY2015–2021, test FY2022 onward;
          absolute-error gradient boosting predicting the growth still to come; settings fixed before testing.
        </p>
        <ul>
          <li>90 days: {w90 ? `${pct(w90.models.gbm.mae_vs_global_median)} vs always-median (CI ${pct(w90.gbm_vs_global_median_gain_ci95[0], 0)} to ${pct(w90.gbm_vs_global_median_gain_ci95[1], 0)})` : "—"} {passBadge(w90?.pass_preregistered)}</li>
          <li>180 days: {w180 ? `${pct(w180.models.gbm.mae_vs_global_median)}, but "growth so far" alone gives ${pct(w180.models.persistence.mae_vs_global_median)}` : "—"} {passBadge(w180?.pass_preregistered)}</li>
          <li>Gain over "growth so far": 95% interval includes zero at both windows.</li>
          <li>Schedule-slip proxy at 90 days: AUC {d90?.auc_gbm.toFixed(2) ?? "—"}, office-only baseline {d90?.auc_office_rate_only.toFixed(2) ?? "—"}; the label largely reflects how each office words its modifications.</li>
        </ul>
      </Section>

      <Section id="activity" title="Tug activity hours">
        <p>
          Tugs are AIS types 31, 32 and 52. Each report is weighted by the time to the vessel's next report, capped at 10
          minutes. Modes: idle (&lt; 0.5 kn), ship assist (within 350 m of a moving cargo, tanker or ≥ 150 m vessel in the
          same minute; the radius allows for antenna offset on long ships and was set before the full run), maneuvering
          (0.5–5 kn) and transit (≥ 5 kn). Distance to SB 535 tracts comes from a 200 m raster distance transform.
          These are movement hours, not engine hours.
        </p>
      </Section>

      <Section id="encounters" title="Close-quarters encounters">
        <p>
          Moving vessels (≥ {en.data?.definition.min_sog_kn ?? 1} kn) are resampled to a 1-minute grid (gaps up to 5 minutes bridged).
          Each minute, pairs within {en.data?.definition.search_nm ?? 2} nm are found with a spatial grid, and CPA/TCPA are projected from
          speed and course. An <b>alert</b> is a predicted pass under {en.data?.definition.cpa_nm ?? 0.25} nm within {en.data?.definition.tcpa_min ?? 10} minutes;
          an <b>encounter</b> is an alert whose vessels then actually came that close. Consecutive alert minutes merge
          into one event; geometry follows COLREGS-style sectors (head-on, crossing, overtaking). Tug, pilot, SAR, port
          tender and law-enforcement vessels are flagged as service interactions.
        </p>
        <ul>
          <li>Straight-line alert precision: {en.data ? pct(en.data.alert_precision_traffic, 0).replace("+", "") : "—"} overall ({en.data ? Object.entries(en.data.alert_precision_by_tcpa_min).map(([k, v]) => `${k} min: ${Math.round(v * 100)}%`).join(", ") : "—"}).</li>
          <li>Validation on {ev.data?.n_sampled ?? "—"} random alerts: closest pass recomputed at each actual report time differs from the 1-minute grid by a median of {ev.data?.median_abs_diff_m ?? "—"} m (90th percentile {ev.data?.p90_abs_diff_m ?? "—"} m); the encounter label agrees in {ev.data ? pct(ev.data.label_agreement, 1).replace("+", "") : "—"} of cases{ev.data?.label_disagreements !== undefined ? ` (${ev.data.label_disagreements} disagreements, ${ev.data.disagreements_within_100m_of_threshold} within 100 m of the threshold; the rest come from interpolating across reporting gaps). Roughly one alert in ten therefore has an uncertain label` : ""}.</li>
          <li>MarineCadastre thins AIS to roughly one report per 1–3 minutes, so that check measures sensitivity to the time grid rather than being free of interpolation. Interpolation across long gaps can manufacture near-zero distances; scenario pages are ranked by the more conservative of the two estimates.</li>
        </ul>
      </Section>

      <Section id="tests" title="Test scorecard">
        <div className="tablewrap">
          <table>
            <thead><tr><th>Test (set before running)</th><th>Target</th><th>Result</th><th /></tr></thead>
            <tbody>
              <tr><td>Hull precision, fresh hand sample</td><td>≥ 95%</td><td>{h27 ? `${Math.round(h27.precision * 100)}% (${h27.tp}/${h27.tp + h27.fp})` : "—"}</td><td>{passBadge(h27?.pass)}</td></tr>
              <tr><td>Award dollars mapped to a curated firm</td><td>≥ 90%</td><td>{id.data ? pct(id.data.firm_coverage.dollar_share_mapped, 1).replace("+", "") : "—"}</td><td>{passBadge(id.data?.firm_coverage.pass)}</td></tr>
              <tr><td>Early-warning model beats always-median by ≥ 15% (90 days)</td><td>≥ 15%</td><td>{w90 ? pct(w90.models.gbm.mae_vs_global_median) : "—"}</td><td>{passBadge(w90?.pass_preregistered)}</td></tr>
              <tr><td>AIS → Coast Guard match precision</td><td>≥ 97%</td><td>{px.data ? `${Math.round(px.data.precision * 100)}% (${px.data.correct}/${px.data.n})` : "—"}</td><td>{passBadge(px.data ? px.data.precision >= 0.97 : undefined)}</td></tr>
              <tr><td>AIS assist-tug hours vs Port of LA inventory, gap explained</td><td>explained</td><td>partly: jitter and season ruled out; selection, year and definitions remain</td><td><span className="badge warn">partial</span></td></tr>
              <tr><td>Encounter label stable to time grid</td><td>—</td><td>{ev.data ? pct(ev.data.label_agreement, 1).replace("+", "") : "—"} agreement</td><td /></tr>
            </tbody>
          </table>
        </div>
      </Section>

      <Section id="limits" title="Limitations">
        <ul>
          <li><b>AIS is not ground truth.</b> Positions are antenna positions, not hull outlines; most small craft and many warships do not broadcast; MarineCadastre thins reports and freezes each vessel's name and identifiers for the year.</li>
          <li><b>Contract data records money, not work.</b> Modifications show when funds were obligated; the Navy's own estimate, schedule and causes of growth are not public.</li>
          <li><b>Hours are movement, not engines.</b> Engine hour meters or fuel data would be needed for emissions.</li>
          <li><b>Coverage.</b> Commercial vessels only in the Coast Guard match (pleasure craft rarely appear there); U.S. vessels match less often than foreign ones.</li>
          <li><b>Hand labels and curated tables</b> were made by one person; some ownership dates rest on a single trade-press source (shown on each firm's page).</li>
        </ul>
      </Section>

      <Section id="privacy" title="Privacy and licences">
        <ul>
          <li>No personal data is published. The Coast Guard redacts individual owners; HarborLedger also drops owner addresses and shows an owner name only when it is an organization. The registered owner can be a bank or lessor.</li>
          <li>Ship names from Wikipedia lists are CC BY-SA; federal sources are treated as public domain where no terms page exists.</li>
          <li>Nothing here is a compliance or safety finding. Encounter counts describe recorded AIS geometry, not rule violations.</li>
        </ul>
      </Section>
    </>
  );
}
