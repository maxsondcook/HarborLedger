import { Link, useParams } from "react-router-dom";
import { Async, Confidence, Stat, useTitle } from "../components/ui";
import { useData, type Yard } from "../data";
import { money, nodeSlug, num, pct } from "../format";

export default function YardPage() {
  const { slug } = useParams();
  const page = useData<Yard>(slug ? `yards/${slug}.json` : null);
  useTitle(page.data?.name ?? "Shipyard");
  return (
    <>
      <p className="small"><Link to="/yards">← Shipyards</Link></p>
      <Async state={page}>{(y) => <YardView y={y} />}</Async>
    </>
  );
}

function YardView({ y }: { y: Yard }) {
  return (
    <>
      <h1>{y.name}</h1>
      <p className="lede">{y.kind}{y.notes ? ` · ${y.notes}` : ""}</p>
      <div className="grid">
        <Stat k="Awards ($5M+)" v={num(y.n_contracts)} />
        <Stat k="Total award value" v={money(y.dollars)} />
        <Stat k="Repair value (J-codes)" v={money(y.repair_dollars)} />
        <Stat k="Median growth, closed availabilities" v={pct(y.median_growth_closed)} sub={`${y.availabilities.filter((a) => a.closed).length} closed`} />
      </div>

      {(y.parents.length > 0 || y.children.length > 0) && (
        <>
          <h2>Ownership</h2>
          <div className="tablewrap">
            <table>
              <thead><tr><th>Relation</th><th>Firm</th><th>From</th><th>To</th><th>Confidence</th><th>Source</th></tr></thead>
              <tbody>
                {y.parents.map((p, i) => (
                  <tr key={"p" + i}>
                    <td>part of</td>
                    <td><Link to={`/yards/${p.dst}`}>{p.dst}</Link></td>
                    <td>{p.valid_from ?? "—"}</td>
                    <td>{p.valid_to ?? "present"}</td>
                    <td><Confidence value={p.confidence} /></td>
                    <td className="small muted">{p.source_ref}</td>
                  </tr>
                ))}
                {y.children.map((c) => (
                  <tr key={"c" + c}><td>owns</td><td><Link to={`/yards/${c}`}>{c}</Link></td><td colSpan={4} className="muted small">see that firm's page for dates</td></tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}

      {y.legal_entities.length > 0 && (
        <>
          <h2>Legal entities (UEIs)</h2>
          <ul>
            {y.legal_entities.map((e) => <li key={e.uei}><span className="mono">{e.uei}</span> <span className="muted">{e.names.join(" · ")}</span></li>)}
          </ul>
        </>
      )}

      {y.availabilities.length > 0 && (
        <>
          <h2>Availabilities in the cost-growth ledger</h2>
          <div className="tablewrap">
            <table>
              <thead><tr><th>Contract</th><th>Hull</th><th>Type</th><th>Start</th><th className="num">Growth beyond options</th><th>Status</th></tr></thead>
              <tbody>
                {y.availabilities.map((a) => (
                  <tr key={a.piid}>
                    <td className="mono">{a.piid}</td>
                    <td className="mono"><Link to={`/vessels/${nodeSlug("hull:" + a.hull)}`}>{a.hull}</Link></td>
                    <td>{a.avail_type}</td>
                    <td>{a.first_action}</td>
                    <td className="num">{pct(a.g_exopt)}</td>
                    <td>{a.closed ? "closed" : <span className="badge warn">open</span>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}

      <h2>Largest awards</h2>
      <div className="tablewrap">
        <table>
          <thead><tr><th>Contract</th><th>Description</th><th>Start</th><th>State</th><th className="num">Value</th></tr></thead>
          <tbody>
            {y.contracts.slice(0, 50).map((c) => (
              <tr key={c.contract_id}>
                <td className="mono">{c.piid}</td>
                <td className="small">{c.description}</td>
                <td>{c.start_date}</td>
                <td>{c.pop_state}</td>
                <td className="num">{money(c.award_amount)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {y.n_contracts > 50 && <p className="muted small">Showing the 50 largest of {num(y.n_contracts)} awards.</p>}
    </>
  );
}
