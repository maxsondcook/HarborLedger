export const money = (x: number | null | undefined): string => {
  if (x === null || x === undefined || Number.isNaN(x)) return "—";
  const a = Math.abs(x);
  if (a >= 1e9) return `$${(x / 1e9).toFixed(a >= 1e10 ? 0 : 1)}B`;
  if (a >= 1e6) return `$${(x / 1e6).toFixed(a >= 1e8 ? 0 : 1)}M`;
  if (a >= 1e3) return `$${(x / 1e3).toFixed(0)}K`;
  return `$${x.toFixed(0)}`;
};

export const pct = (x: number | null | undefined, digits = 1): string =>
  x === null || x === undefined || Number.isNaN(x) ? "—" : `${x >= 0 ? "+" : ""}${(x * 100).toFixed(digits)}%`;

export const num = (x: number | null | undefined): string =>
  x === null || x === undefined ? "—" : x.toLocaleString("en-US");

export const nodeSlug = (id: string): string => id.replace(/:/g, "-").replace(/[^A-Za-z0-9_-]+/g, "-");

export const GROUP_LABEL: Record<string, string> = {
  TUG_TOW: "Tug / tow",
  PASSENGER: "Passenger",
  CARGO: "Cargo",
  TANKER: "Tanker",
  FISHING: "Fishing",
  OTHER: "Other",
};
