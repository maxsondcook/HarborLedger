import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { Async, useTitle } from "../components/ui";
import { useData, type YardIndex } from "../data";
import { money, num, pct } from "../format";

type SortKey = "dollars" | "repair_dollars" | "n_contracts" | "n_avail";

export default function Yards() {
  useTitle("Shipyards and contractors");
  const idx = useData<YardIndex[]>("yards.json");
  const [sort, setSort] = useState<SortKey>("dollars");
  const [q, setQ] = useState("");
  return (
    <>
      <h1>Shipyards and contractors</h1>
      <p className="lede">
        Curated firms behind Navy shipbuilding and repair awards (NAICS 336611, $5M and up, FY2015–2026). Each
        firm groups one or more legal entities (UEIs) and carries dated ownership, because the government's own
        parent-company data is fragmented and sometimes wrong.
      </p>
      <div className="controls">
        <input type="search" placeholder="Search firm" value={q} onChange={(e) => setQ(e.target.value)} />
        <select value={sort} onChange={(e) => setSort(e.target.value as SortKey)} aria-label="Sort by">
          <option value="dollars">Sort by total award value</option>
          <option value="repair_dollars">Sort by repair value</option>
          <option value="n_contracts">Sort by number of awards</option>
          <option value="n_avail">Sort by ledger availabilities</option>
        </select>
      </div>
      <Async state={idx}>
        {(all) => <YardTable all={all} sort={sort} q={q} />}
      </Async>
    </>
  );
}

function YardTable({ all, sort, q }: { all: YardIndex[]; sort: SortKey; q: string }) {
  const rows = useMemo(() => {
    const s = q.trim().toUpperCase();
    return all.filter((y) => y.n_contracts > 0 && (!s || y.name.toUpperCase().includes(s)))
      .sort((a, b) => (b[sort] ?? 0) - (a[sort] ?? 0));
  }, [all, sort, q]);
  return (
    <div className="tablewrap">
      <table>
        <thead><tr><th>Firm</th><th>Kind</th><th className="num">Awards</th><th className="num">Total value</th><th className="num">Repair value</th><th className="num">Ledger availabilities</th><th className="num">Median growth (closed)</th></tr></thead>
        <tbody>
          {rows.map((y) => (
            <tr key={y.slug}>
              <td><Link to={`/yards/${y.slug}`}>{y.name}</Link></td>
              <td className="muted">{y.kind}</td>
              <td className="num">{num(y.n_contracts)}</td>
              <td className="num">{money(y.dollars)}</td>
              <td className="num">{money(y.repair_dollars)}</td>
              <td className="num">{num(y.n_avail)}</td>
              <td className="num">{pct(y.median_growth_closed)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
