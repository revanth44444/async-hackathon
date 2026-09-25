import { getClientId } from "@/lib/client-id";

export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export type Regime = "new" | "old";

export interface SalaryStructure {
  company: string | null;
  role: string | null;
  location: string | null;
  ctc: number;
  basic: number;
  hra: number;
  special_allowance: number;
  lta: number;
  meal_allowance: number;
  other_allowances: number;
  employer_pf: number;
  gratuity: number;
  employer_nps: number;
  insurance: number;
  variable_pay: number;
  joining_bonus: number;
  esop_value: number;
}

export type NumericField = Exclude<keyof SalaryStructure, "company" | "role" | "location">;

export interface Assumptions {
  regime: "auto" | Regime;
  state: string;
  metro: boolean;
  variable_payout_pct: number;
  include_employee_pf: boolean;
  pf_on_capped_wage: boolean;
  monthly_rent: number;
  investments_80c: number;
  medical_80d: number;
  home_loan_interest: number;
  nps_80ccd1b: number;
}

export interface LineItem {
  key: NumericField;
  label: string;
  annual: number;
  monthly: number | null;
  category: "fixed" | "retirement" | "benefit" | "variable" | "one_time" | "equity";
  description: string;
  in_ctc: boolean;
}

export interface Adjustment {
  label: string;
  amount: number;
}

export interface TaxBreakdown {
  regime: Regime;
  gross_income: number;
  exemptions: Adjustment[];
  deductions: Adjustment[];
  taxable_income: number;
  slabs: { lower: number; upper: number | null; rate: number; taxable_amount: number; tax: number }[];
  base_tax: number;
  rebate: number;
  surcharge: number;
  cess: number;
  total_tax: number;
  effective_rate: number;
  marginal_rate: number;
}

export interface RegimeResult {
  tax: TaxBreakdown;
  tax_on_fixed: number;
  monthly_tax: number;
  monthly_in_hand: number;
  annual_take_home: number;
  year_one_take_home: number;
}

export interface CalculationResult {
  structure: SalaryStructure;
  assumptions: Assumptions;
  components: LineItem[];
  fixed_cash: number;
  variable_paid: number;
  employee_pf: number;
  professional_tax: number;
  regimes: Record<Regime, RegimeResult>;
  selected_regime: Regime;
  recommended_regime: Regime;
  regime_savings: number;
  monthly_in_hand: number;
  annual_take_home: number;
  year_one_take_home: number;
  in_hand_pct_of_ctc: number;
  ctc_buckets: Adjustment[];
  warnings: string[];
}

export interface Suggestion {
  title: string;
  detail: string;
  annual_impact: number;
}

export interface OfferSummary {
  id: string;
  label: string;
  company: string | null;
  role: string | null;
  source: "pdf" | "text" | "manual" | "sample";
  ctc: number;
  monthly_in_hand: number;
  annual_take_home: number;
  created_at: string;
}

export interface ExtractionMeta {
  method?: "ai" | "heuristic" | "manual";
  candidate_name?: string | null;
  joining_date?: string | null;
  components?: { label: string; annual_amount: number; category: string }[];
  notes?: string[];
  estimated_split?: boolean;
  estimates?: { kind: "split" | "gross" | "balance" | "monthly_ctc"; amount: number; message: string }[];
}

export interface OfferDetail extends OfferSummary {
  filename: string | null;
  structure: SalaryStructure;
  assumptions: Assumptions;
  result: CalculationResult;
  extraction_meta: ExtractionMeta;
  explanation: string | null;
  suggestions: Suggestion[];
  has_raw_text: boolean;
}

export interface SimulationResult {
  baseline: CalculationResult;
  scenario: CalculationResult;
  delta: { monthly_in_hand: number; annual_take_home: number; income_tax: number };
}

export interface CompareResult {
  rows: { offer_id: string; label: string; result: CalculationResult }[];
  best_monthly_in_hand: string;
  best_annual_take_home: string;
  best_year_one: string;
  best_fixed_pay: string;
  best_retirement: string;
  lowest_tax: string;
  verdict: string | null;
}

export interface Meta {
  ai_enabled: boolean;
  model: string | null;
  tax_year: string;
  states: string[];
}

export class ApiError extends Error {
  constructor(message: string, public status: number) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, {
      ...init,
      headers: {
        ...(init?.body instanceof FormData ? {} : { "Content-Type": "application/json" }),
        "X-Client-Id": getClientId(),
        ...init?.headers,
      },
    });
  } catch {
    throw new ApiError(`Can't reach the API at ${API_URL}. Is the backend running?`, 0);
  }
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    const detail = typeof body.detail === "string" ? body.detail : Array.isArray(body.detail) ? body.detail[0]?.msg : null;
    throw new ApiError(detail ?? `Request failed (${res.status})`, res.status);
  }
  return res.status === 204 ? (undefined as T) : res.json();
}

const post = <T>(path: string, body: unknown) => request<T>(path, { method: "POST", body: JSON.stringify(body) });

export const api = {
  meta: () => request<Meta>("/api/meta"),
  listOffers: () => request<OfferSummary[]>("/api/offers"),
  getOffer: (id: string) => request<OfferDetail>(`/api/offers/${id}`),
  uploadOffer: (file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    return request<OfferDetail>("/api/offers/upload", { method: "POST", body: fd });
  },
  loadSample: (name: "nimbus" | "quantora") => post<OfferDetail>(`/api/offers/sample/${name}`, {}),
  createFromText: (text: string) => post<OfferDetail>("/api/offers/text", { text }),
  createManual: (structure: Partial<SalaryStructure>, assumptions?: Partial<Assumptions>, label?: string) =>
    post<OfferDetail>("/api/offers", { structure, assumptions, label }),
  updateOffer: (id: string, body: { label?: string; structure?: SalaryStructure; assumptions?: Assumptions }) =>
    request<OfferDetail>(`/api/offers/${id}`, { method: "PUT", body: JSON.stringify(body) }),
  deleteOffer: (id: string) => request<void>(`/api/offers/${id}`, { method: "DELETE" }),
  explain: (id: string, refresh = false) =>
    post<{ explanation: string; method?: string }>(`/api/offers/${id}/explain?refresh=${refresh}`, {}),
  ask: (id: string, question: string) => post<{ answer: string }>(`/api/offers/${id}/ask`, { question }),
  simulate: (offerId: string, assumptions: Assumptions, hikePct: number, overrides: Partial<Record<NumericField, number>>) =>
    post<SimulationResult>("/api/simulate", { offer_id: offerId, assumptions, hike_pct: hikePct, overrides }),
  compare: (offerIds: string[], assumptions?: Assumptions) =>
    post<CompareResult>("/api/compare", { offer_ids: offerIds, assumptions }),
};
