import { useEffect, useState } from "react";

// Static JSON written by `python3 -I run.py export` into site/public/data/.
const BASE = `${import.meta.env.BASE_URL}data/`;
const cache = new Map<string, Promise<unknown>>();

export function load<T>(path: string): Promise<T> {
  if (!cache.has(path)) {
    cache.set(
      path,
      fetch(BASE + path).then((r) => {
        if (!r.ok) throw new Error(`${path}: HTTP ${r.status}`);
        return r.json();
      }),
    );
  }
  return cache.get(path) as Promise<T>;
}

export type Loadable<T> = { data?: T; error?: string; loading: boolean };

export function useData<T>(path: string | null): Loadable<T> {
  const [state, setState] = useState<Loadable<T>>({ loading: !!path });
  useEffect(() => {
    if (!path) return;
    let live = true;
    setState({ loading: true });
    load<T>(path)
      .then((data) => live && setState({ data, loading: false }))
      .catch((e: Error) => live && setState({ error: e.message, loading: false }));
    return () => {
      live = false;
    };
  }, [path]);
  return state;
}

// ---------- types mirroring harborledger/export.py ----------
export type VesselIndex =
  | { slug: string; kind: "ais"; name: string; group: string; flag: string; coastwise: boolean | null; linked: boolean; conf: number | null }
  | { slug: string; kind: "navy"; name: string | null; hull: string; group: string; n_contracts: number; dollars_allocated: number };

export type Edge = { rel: string; dst: string; confidence: number; method: string; evidence: string | null; license: string; via?: string };
export type Identifier = { scheme: string; value: string; valid_from: string | null; valid_to: string | null; source: string; license: string };

export type AisVessel = {
  id: string; slug: string; kind: "ais"; name: string; group: string; flag: string;
  identifiers: Identifier[]; links: Edge[]; active_in: { dst: string; evidence: string }[];
  register: null | {
    service: string; coastwise_unrestricted: string; coastwise_any: number; registry: string; fishery: string;
    builder: string; build_year: string; complete_build_country: string; owner_org: string;
    gross_ton: string; length: string; cod_status: string;
  };
};

export type Availability = {
  piid: string; avail_type: string; firm: string | null; first_action: string; pop_end: string; closed: number;
  base: number; options: number; total: number; g_exopt: number | null; n_mods: number; delay_flag: number;
};

export type NavyVessel = {
  id: string; slug: string; kind: "navy"; name: string | null; hull: string; hull_class: string; name_source: string | null;
  contracts: {
    contract_id: string; piid: string; description: string; recipient_name: string; start_date: string; end_date: string;
    award_amount: number; avail_type: string | null; confidence: number; method: string; evidence: string; firm: string | null; n_hulls: number;
  }[];
  availabilities: Availability[];
};

export type YardIndex = { slug: string; name: string; kind: string; n_contracts: number; dollars: number; repair_dollars: number; n_avail: number; median_growth_closed: number | null };

export type Yard = YardIndex & {
  id: string; notes: string;
  legal_entities: { uei: string; names: string[] }[];
  parents: { dst: string; valid_from: string | null; valid_to: string | null; confidence: number; method: string; source_ref: string }[];
  children: string[];
  contracts: { contract_id: string; piid: string; description: string; recipient_name: string; start_date: string; end_date: string; award_amount: number; psc: string; pop_state: string; avail_type: string | null }[];
  availabilities: { piid: string; hull: string; avail_type: string; first_action: string; closed: number; g_exopt: number | null }[];
};

export type Meta = {
  built_at: string;
  counts: Record<string, number>;
  sources: Record<string, { license: string; files: number; latest_fetch: string }>;
};
