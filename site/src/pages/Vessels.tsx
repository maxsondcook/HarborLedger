import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { Async, Confidence, useTitle } from "../components/ui";
import { useData, type VesselIndex } from "../data";
import { GROUP_LABEL, money, num } from "../format";

type Kind = "ais" | "navy";

export default function Vessels() {
  useTitle("Vessels");
  const idx = useData<VesselIndex[]>("vessels.json");
  const [kind, setKind] = useState<Kind>("ais");
  const [q, setQ] = useState("");
  const [group, setGroup] = useState("");
  const [flag, setFlag] = useState("");

  return (
    <>
      <h1>Vessels</h1>
      <p className="lede">
        {kind === "ais"
          ? "Commercial vessels seen in California AIS data, with their best link to a Coast Guard record. Links below 0.5 confidence are shown as unlinked."
          : "Navy hulls named in repair and construction contract descriptions. Contract value for awards naming several hulls is split equally between them."}
      </p>
      <div className="controls">
        <select value={kind} onChange={(e) => { setKind(e.target.value as Kind); setGroup(""); }} aria-label="Vessel type">
          <option value="ais">Commercial (AIS)</option>
          <option value="navy">Navy hulls</option>
        </select>
        <input type="search" placeholder={kind === "ais" ? "Search name" : "Search name or hull (e.g. DDG-105)"} value={q} onChange={(e) => setQ(e.target.value)} />
        {kind === "ais" && (
          <>
            <select value={group} onChange={(e) => setGroup(e.target.value)} aria-label="Group">
              <option value="">All types</option>
              {Object.entries(GROUP_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </select>
            <select value={flag} onChange={(e) => setFlag(e.target.value)} aria-label="Flag">
              <option value="">Any flag</option>
              <option value="US">U.S.</option>
              <option value="foreign">Foreign</option>
            </select>
          </>
        )}
      </div>
      <Async state={idx}>{(all) => <Table all={all} kind={kind} q={q} group={group} flag={flag} />}</Async>
    </>
  );
}

function Table({ all, kind, q, group, flag }: { all: VesselIndex[]; kind: Kind; q: string; group: string; flag: string }) {
  const rows = useMemo(() => {
    const s = q.trim().toUpperCase();
    return all.filter((v) => {
      if (v.kind !== kind) return false;
      if (v.kind === "ais") {
        if (group && v.group !== group) return false;
        if (flag && v.flag !== flag) return false;
        return !s || (v.name || "").toUpperCase().includes(s);
      }
      return !s || (v.name || "").toUpperCase().includes(s) || v.hull.includes(s);
    }).sort((a, b) =>
      a.kind === "navy" && b.kind === "navy" ? b.dollars_allocated - a.dollars_allocated : (a.name || "").localeCompare(b.name || ""),
    );
  }, [all, kind, q, group, flag]);

  return (
    <>
      <p className="muted small">{num(rows.length)} vessels</p>
      <div className="tablewrap">
        <table>
          <thead>
            {kind === "ais" ? (
              <tr><th>Name</th><th>Type</th><th>Flag</th><th>Coastwise</th><th>Best Coast Guard link</th></tr>
            ) : (
              <tr><th>Hull</th><th>Name</th><th className="num">Contracts</th><th className="num">Value (allocated)</th></tr>
            )}
          </thead>
          <tbody>
            {rows.slice(0, 500).map((v) =>
              v.kind === "ais" ? (
                <tr key={v.slug}>
                  <td><Link to={`/vessels/${v.slug}`}>{v.name || "(no name)"}</Link></td>
                  <td>{GROUP_LABEL[v.group] ?? v.group}</td>
                  <td>{v.flag === "US" ? "U.S." : "Foreign"}</td>
                  <td>{v.coastwise === null ? <span className="muted">—</span> : v.coastwise ? <span className="badge accent">yes</span> : "no"}</td>
                  <td><Confidence value={v.linked ? v.conf : null} /></td>
                </tr>
              ) : (
                <tr key={v.slug}>
                  <td className="mono"><Link to={`/vessels/${v.slug}`}>{v.hull}</Link></td>
                  <td>{v.name ?? <span className="muted">unknown</span>}</td>
                  <td className="num">{num(v.n_contracts)}</td>
                  <td className="num">{money(v.dollars_allocated)}</td>
                </tr>
              ),
            )}
          </tbody>
        </table>
      </div>
      {rows.length > 500 && <p className="muted small">Showing the first 500. Narrow the search to see more.</p>}
    </>
  );
}
