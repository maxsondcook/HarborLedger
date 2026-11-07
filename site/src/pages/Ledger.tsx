import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { HBar, Histogram, SERIES } from "../components/charts";
import { Async, Stat, useTitle } from "../components/ui";
import { useData, type YardIndex } from "../data";
import { money, num, pct } from "../format";

type Row = {
  contract_id: string; piid: string; hull: string; hull_slug: string; hull_class: string; avail_type: string;
  firm: string | null; recipient_name: string; pop_state: string; first_action: string; start_fy: number; pop_end: string;
  closed: number; base: number; options: number; total: number; g_exopt: number | null; g_exopt_noC: number | null;
  n_mods: number; delay_flag: number;
};
type ModelWin = {
  window_days: number; label: string; n_train: number; n_test: number;
  models: Record<string, { mae: number; medae: number; mae_vs_global_median: number }>;
  pass_preregistered: boolean; gbm_vs_global_median_gain_ci95: [number, number]; gbm_minus_persistence_mae_gain_ci95: [number, number];
};
type DelayRes = { window_days: number; rate_test: number; auc_gbm: number; auc_office_rate_only: number; median_final_growth_if_late: number; median_final_growth_if_not: number };
type Model = { windows: ModelWin[]; delay: DelayRes[]; censoring: { open_availabilities: { n: number; mean_growth_so_far: number } } };

const median = (v: number[]) => { const s = [...v].sort((a, b) => a - b); return s.length ? s[Math.floor(s.length / 2)] : NaN; };
const q = (v: number[], p: number) => { const s = [...v].sort((a, b) => a - b); return s.length ? s[Math.min(s.length - 1, Math.round(p * (s.length - 1)))] : NaN; };
const MODEL_LABEL: Record<string, string> = {
  global_median: "Always predict the median",
  median_by_type: "Median by availability type",
  persistence: "Growth so far (persistence)",
  persistence_plus_median_remaining: "Growth so far + typical remainder",
  gbm: "Gradient-boosted model",
};

export default function Ledger() {
  useTitle("Navy repair cost ledger");
  const led = useData<Row[]>("ledger.json");
  const model = useData<Model>("growth_model.json");
  const yards = useData<YardIndex[]>("yards.json");
  return (
    <>
      <h1>Navy repair cost ledger</h1>
      <p className="lede">
        Every non-nuclear Navy repair availability with a base award of at least $5M (FY2015–2026) that could be tied
        to one ship. Growth is measured beyond the base award <i>and</i> the options the Navy priced in advance:
        <span className="mono"> (total − base − options) / (base + options)</span>. Open availabilities are still
        accruing changes, so their growth is a lower bound and they are excluded from the statistics.
      </p>
      <Async state={led}>{(rows) => <Body rows={rows} model={model.data} names={Object.fromEntries((yards.data ?? []).map((y) => [y.slug, y.name]))} />}</Async>
    </>
  );
}

function Body({ rows, model, names }: { rows: Row[]; model?: Model; names: Record<string, string> }) {
  const closed = rows.filter((r) => r.closed && r.g_exopt !== null);
  const g = closed.map((r) => r.g_exopt as number);
  const byType = groupMedian(closed, (r) => r.avail_type, 8);
  const byFirm = groupMedian(closed, (r) => (r.firm ? names[r.firm] ?? r.firm : "Unmapped contractors"), 8);
  const ca = closed.filter((r) => r.pop_state === "CA").map((r) => r.g_exopt as number);
  return (
    <>
      <div className="grid">
        <Stat k="Availabilities" v={num(rows.length)} sub={`${num(closed.length)} closed · ${num(rows.length - closed.length)} open`} />
        <Stat k="Median growth (closed)" v={pct(median(g))} sub={`middle half ${pct(q(g, 0.25))} to ${pct(q(g, 0.75))}`} />
        <Stat k="90th percentile" v={pct(q(g, 0.9))} sub="one in ten grows at least this much" />
        <Stat k="California only" v={pct(median(ca))} sub={`${ca.length} closed availabilities`} />
      </div>

      <div className="figure">
        <h3>How much repair availabilities grow</h3>
        <p className="cap">Closed availabilities, growth beyond base + options. Values outside −50% to +150% are counted in the edge bins.</p>
        <Histogram
          values={g.map((v) => Math.max(-0.5, Math.min(1.5, v)))}
          bins={Array.from({ length: 21 }, (_, i) => -0.5 + i * 0.1)}
          fmt={(v) => pct(v, 0)}
          refs={[{ v: median(g), text: `median ${pct(median(g))}` }]}
          label="Histogram of availability cost growth"
        />
      </div>

      <div>
        <div className="figure">
          <h3>Median growth by availability type</h3>
          <p className="cap">Types with at least 8 closed availabilities.</p>
          <HBar rows={byType} fmt={(v) => pct(v, 0)} label="Median growth by availability type" />
        </div>
        <div className="figure">
          <h3>Median growth by yard</h3>
          <p className="cap">Firms with at least 8 closed availabilities. Differences mix yard performance with the ships and work they get.</p>
          <HBar rows={byFirm} fmt={(v) => pct(v, 0)} color={SERIES[1]} label="Median growth by yard" />
        </div>
      </div>

      {model && <ModelSection model={model} />}
      <AvailTable rows={rows} />
    </>
  );
}

function groupMedian(rows: Row[], key: (r: Row) => string, minN: number) {
  const m = new Map<string, number[]>();
  rows.forEach((r) => { const k = key(r); m.set(k, [...(m.get(k) ?? []), r.g_exopt as number]); });
  return [...m.entries()].filter(([, v]) => v.length >= minN)
    .map(([k, v]) => ({ key: k, value: median(v), note: `${v.length} closed availabilities` }))
    .sort((a, b) => b.value - a.value);
}

function ModelSection({ model }: { model: Model }) {
  const [w, setW] = useState(90);
  const win = model.windows.find((x) => x.window_days === w && x.label === "g_exopt");
  const delay = model.delay.find((d) => d.window_days === w);
  if (!win) return null;
  const order = ["global_median", "median_by_type", "persistence", "persistence_plus_median_remaining", "gbm"];
  return (
    <>
      <h2>Can public data warn early?</h2>
      <p className="lede">
        Train on availabilities that started in FY{2015}–2021, test on FY2022 onward, using only contract actions dated
        within the first {w} days. The pre-registered bar was a 15% lower error than always predicting the median.
      </p>
      <div className="controls">
        <select value={w} onChange={(e) => setW(+e.target.value)} aria-label="Window">
          <option value={90}>First 90 days</option>
          <option value={180}>First 180 days</option>
        </select>
        <span className={`badge ${win.pass_preregistered ? "good" : "bad"}`}>{win.pass_preregistered ? "passes" : "misses"} the pre-registered 15% bar</span>
        <span className="muted small">train {win.n_train} · test {win.n_test}</span>
      </div>
      <div className="figure">
        <h3>Mean absolute error on the test years (lower is better)</h3>
        <HBar rows={order.filter((k) => win.models[k]).map((k) => ({
          key: MODEL_LABEL[k], value: win.models[k].mae,
          note: `${pct(win.models[k].mae_vs_global_median)} vs median baseline · median error ${pct(win.models[k].medae)}`,
        }))} fmt={(v) => v.toFixed(3)} label="Model error comparison" />
      </div>
      <div className="note">
        {w === 90
          ? `At 90 days the model's gain over the median baseline is ${pct(win.models.gbm.mae_vs_global_median)} (95% CI ${pct(win.gbm_vs_global_median_gain_ci95[0], 0)} to ${pct(win.gbm_vs_global_median_gain_ci95[1], 0)}), just short of the bar.`
          : `At 180 days the gain is large, but almost all of it comes from growth that is already on the books: "growth so far" alone does nearly as well.`}{" "}
        Its improvement over persistence (growth so far) has a 95% interval that includes zero. Public modification
        histories make growth visible early; they do not yet make it forecastable beyond what is visible.
      </div>
      {delay && (
        <div className="figure">
          <h3>Schedule-slip proxy</h3>
          <p className="cap">
            Label: a later modification mentions an extension, period-of-performance change or late-delivery penalty
            ({pct(delay.rate_test, 0).replace("+", "")} of test availabilities). Model AUC {delay.auc_gbm.toFixed(2)}, but
            the contracting office's historical rate alone scores {delay.auc_office_rate_only.toFixed(2)}: much of the signal is
            how each office words its modifications. Flagged availabilities do end with more growth
            ({pct(delay.median_final_growth_if_late)} vs {pct(delay.median_final_growth_if_not)} median).
          </p>
        </div>
      )}
    </>
  );
}

function AvailTable({ rows }: { rows: Row[] }) {
  const [type, setType] = useState("");
  const [status, setStatus] = useState("closed");
  const [s, setS] = useState("");
  const types = useMemo(() => [...new Set(rows.map((r) => r.avail_type))].sort(), [rows]);
  const view = rows.filter((r) => (!type || r.avail_type === type) && (status === "all" || (status === "closed" ? r.closed : !r.closed))
    && (!s || `${r.hull} ${r.recipient_name} ${r.piid}`.toUpperCase().includes(s.toUpperCase())))
    .sort((a, b) => (b.g_exopt ?? -9) - (a.g_exopt ?? -9));
  return (
    <>
      <h2>All availabilities</h2>
      <div className="controls">
        <input type="search" placeholder="Search hull, yard or contract" value={s} onChange={(e) => setS(e.target.value)} />
        <select value={type} onChange={(e) => setType(e.target.value)} aria-label="Type"><option value="">All types</option>{types.map((t) => <option key={t}>{t}</option>)}</select>
        <select value={status} onChange={(e) => setStatus(e.target.value)} aria-label="Status"><option value="closed">Closed</option><option value="open">Open</option><option value="all">All</option></select>
        <span className="muted small">{view.length} shown</span>
      </div>
      <div className="tablewrap">
        <table>
          <thead><tr><th>Hull</th><th>Type</th><th>Yard</th><th>Start</th><th className="num">Base + options</th><th className="num">Total</th><th className="num">Growth</th><th className="num">Mods</th></tr></thead>
          <tbody>
            {view.slice(0, 300).map((r) => (
              <tr key={r.contract_id}>
                <td className="mono"><Link to={`/vessels/${r.hull_slug}`}>{r.hull}</Link></td>
                <td>{r.avail_type}</td>
                <td>{r.firm ? <Link to={`/yards/${r.firm}`}>{r.recipient_name}</Link> : r.recipient_name}</td>
                <td>{r.first_action}</td>
                <td className="num">{money(r.base + r.options)}</td>
                <td className="num">{money(r.total)}</td>
                <td className="num">{pct(r.g_exopt)}{!r.closed && <span className="muted small"> (so far)</span>}</td>
                <td className="num">{r.n_mods}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}
