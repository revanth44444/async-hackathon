const inrFmt = new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 0 });

/** ₹12,34,567 */
export const inr = (v: number) => inrFmt.format(Math.round(v));

/** ₹18.5L / ₹1.2Cr — compact Indian notation for headlines. */
export function lakh(v: number): string {
  const abs = Math.abs(v);
  if (abs >= 1e7) return `₹${(v / 1e7).toFixed(2).replace(/\.?0+$/, "")}Cr`;
  if (abs >= 1e5) return `₹${(v / 1e5).toFixed(2).replace(/\.?0+$/, "")}L`;
  return inr(v);
}

export const pct = (v: number, digits = 0) => `${(v * 100).toFixed(digits)}%`;

export const signed = (v: number) => `${v >= 0 ? "+" : "−"}${inr(Math.abs(v))}`;

export const STATE_NAMES: Record<string, string> = {
  KA: "Karnataka",
  MH: "Maharashtra",
  TN: "Tamil Nadu",
  TS: "Telangana",
  AP: "Andhra Pradesh",
  WB: "West Bengal",
  GJ: "Gujarat",
  KL: "Kerala",
  MP: "Madhya Pradesh",
  DL: "Delhi",
  HR: "Haryana",
  UP: "Uttar Pradesh",
  RJ: "Rajasthan",
  OTHER: "Other",
};

/** Chart/category colours (literal hex: SVG fill attributes can't resolve CSS variables). */
export const BUCKET_COLORS = [
  "#1f5c45", // take-home fixed — deep green
  "#9dbba8", // take-home variable — sage
  "#b5653e", // income tax — terracotta
  "#0f2340", // employee PF — navy
  "#b8b2a7", // professional tax — taupe
  "#56708f", // employer PF + NPS — steel blue
  "#c6a66a", // gratuity — gold
  "#a9bccd", // insurance — mist blue
  "#e2ddd3", // variable not paid — sand
  "#6e3b4a", // one-time / ESOPs — burgundy
];
