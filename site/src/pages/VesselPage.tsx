import { Link, useParams } from "react-router-dom";
import { Async, Confidence, useTitle } from "../components/ui";
import { useData, type AisVessel, type NavyVessel } from "../data";
import { GROUP_LABEL, money, pct } from "../format";

export default function VesselPage() {
  const { slug } = useParams();
  const page = useData<AisVessel | NavyVessel>(slug ? `vessels/${slug}.json` : null);
  useTitle(page.data ? (page.data.kind === "navy" ? `${page.data.name ?? "Hull"} (${page.data.hull})` : page.data.name || "Vessel") : "Vessel");
  return (
    <>
      <p className="small"><Link to="/vessels">← Vessels</Link></p>
      <Async state={page}>{(v) => (v.kind === "ais" ? <Ais v={v} /> : <Navy v={v} />)}</Async>
    </>
  );
}

const SCHEME: Record<string, string> = {
  mmsi: "MMSI", imo: "IMO", call_sign: "Call sign", ais_name: "AIS name",
  psix_vessel_id: "PSIX vessel ID", uscg_identification: "USCG identification",
};

function Ais({ v }: { v: AisVessel }) {
  const r = v.register;
  return (
    <>
      <h1>{v.name || "(no name)"}</h1>
      <p className="lede">
        {GROUP_LABEL[v.group] ?? v.group} · {v.flag === "US" ? "U.S.-flag" : "foreign-flag"} · seen in California AIS during 2024
      </p>
      <div className="cards-2">
        <div className="card">
          <h2 style={{ marginTop: 0 }}>Identifiers</h2>
          <dl className="facts">
            {v.identifiers.map((i) => (
              <div key={i.scheme + i.value} style={{ display: "contents" }}>
                <dt>{SCHEME[i.scheme] ?? i.scheme}</dt>
                <dd className="mono">{i.value}{i.valid_from ? <span className="muted small"> · {i.valid_from} → {i.valid_to}</span> : null}</dd>
              </div>
            ))}
          </dl>
        </div>
        <div className="card">
          <h2 style={{ marginTop: 0 }}>Federal vessel register</h2>
          {r ? (
            <dl className="facts">
              <dt>Service</dt><dd>{r.service || "—"}</dd>
              <dt>Coastwise trade</dt><dd>{r.coastwise_unrestricted === "X" ? <span className="badge accent">unrestricted</span> : r.coastwise_any ? <span className="badge">limited</span> : "no"}</dd>
              <dt>Registry (foreign trade)</dt><dd>{r.registry === "X" ? "yes" : "no"}</dd>
              <dt>Builder</dt><dd>{r.builder || "—"}{r.build_year ? `, ${r.build_year}` : ""}{r.complete_build_country ? ` (${r.complete_build_country})` : ""}</dd>
              <dt>Registered owner</dt><dd>{r.owner_org || <span className="muted">individual or not listed</span>}<div className="muted small">Title holder on the Certificate of Documentation; can be a bank or lessor.</div></dd>
              <dt>Size</dt><dd>{r.length ? `${r.length} ft` : "—"}{r.gross_ton ? ` · ${r.gross_ton} GT` : ""}</dd>
              <dt>Document status</dt><dd>{r.cod_status || "—"}</dd>
            </dl>
          ) : (
            <p className="muted small">{v.flag === "US" ? "No confident link to the USCG register." : "Foreign vessels are not in the U.S. register."}</p>
          )}
        </div>
      </div>
      <h2>Links to other records</h2>
      <div className="tablewrap">
        <table>
          <thead><tr><th>Relation</th><th>Record</th><th>Confidence · method</th><th>Evidence</th></tr></thead>
          <tbody>
            {v.links.length === 0 && <tr><td colSpan={4} className="muted">No Coast Guard record matched this vessel.</td></tr>}
            {v.links.map((l, i) => (
              <tr key={i}>
                <td>{l.rel === "SAME_AS" ? "same vessel" : "possible match (held for review)"}{l.via ? <span className="muted small"> via {l.via}</span> : null}</td>
                <td className="mono">{l.dst}</td>
                <td><Confidence value={l.confidence} method={l.method} /></td>
                <td className="small muted">{l.evidence}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {v.active_in.length > 0 && (
        <>
          <h2>Activity (tug hours, 2024)</h2>
          <ul>{v.active_in.map((a) => <li key={a.dst}><b>{a.dst.replace("area:", "").replace(/_/g, " ")}</b>: <span className="muted">{a.evidence}</span></li>)}</ul>
        </>
      )}
    </>
  );
}

// Military Sealift Command classes carry the USNS prefix; commissioned warships are USS.
const MSC = new Set(["AO", "AOE", "AKE", "AKR", "AH", "EPF", "ESD", "ARS", "ATS", "AGOS", "AGS", "AGM", "ACS", "AP", "ARC"]);
const prefix = (cls: string) => (MSC.has(cls) ? "USNS" : "USS");

function Navy({ v }: { v: NavyVessel }) {
  const asserted = v.contracts.filter((c) => c.confidence >= 0.5);
  return (
    <>
      <h1>{v.name ? `${prefix(v.hull_class)} ${v.name}` : "Unnamed hull"} <span className="mono muted">({v.hull})</span></h1>
      <p className="lede">Navy hull identified from contract descriptions. Name source: {v.name_source ?? "none"}.</p>
      {v.availabilities.length > 0 && (
        <>
          <h2>Repair availabilities in the cost-growth ledger</h2>
          <div className="tablewrap">
            <table>
              <thead><tr><th>Contract</th><th>Type</th><th>Yard</th><th>Start</th><th className="num">Base + options</th><th className="num">Total</th><th className="num">Growth beyond options</th><th>Status</th></tr></thead>
              <tbody>
                {v.availabilities.map((a) => (
                  <tr key={a.piid}>
                    <td className="mono">{a.piid}</td>
                    <td>{a.avail_type}</td>
                    <td>{a.firm ? <Link to={`/yards/${a.firm}`}>{a.firm}</Link> : "—"}</td>
                    <td>{a.first_action}</td>
                    <td className="num">{money(a.base + a.options)}</td>
                    <td className="num">{money(a.total)}</td>
                    <td className="num">{pct(a.g_exopt)}</td>
                    <td>{a.closed ? "closed" : <span className="badge warn">open (lower bound)</span>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
      <h2>Contracts naming this hull ({asserted.length})</h2>
      <div className="tablewrap">
        <table>
          <thead><tr><th>Contract</th><th>Description</th><th>Contractor</th><th>Start</th><th className="num">Award value</th><th>Link</th></tr></thead>
          <tbody>
            {v.contracts.map((c) => (
              <tr key={c.contract_id} style={c.confidence < 0.5 ? { opacity: 0.55 } : undefined}>
                <td className="mono">{c.piid}</td>
                <td className="small">{c.description}</td>
                <td>{c.firm ? <Link to={`/yards/${c.firm}`}>{c.recipient_name}</Link> : c.recipient_name}</td>
                <td>{c.start_date}</td>
                <td className="num">{money(c.award_amount)}{c.n_hulls > 1 ? <div className="muted small">shared by {c.n_hulls} hulls</div> : null}</td>
                <td><Confidence value={c.confidence} method={c.method} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="muted small">Faded rows are below the 0.5 threshold (for example, “DDG 51” used as the class name) and are not counted.</p>
    </>
  );
}
