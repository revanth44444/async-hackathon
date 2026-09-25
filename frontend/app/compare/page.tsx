"use client";

import { Suspense, useEffect, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import ReactMarkdown from "react-markdown";
import { Loader2 } from "lucide-react";
import { CompareStack } from "@/components/charts";
import { api, type CalculationResult, type CompareResult, type OfferSummary } from "@/lib/api";
import { inr, lakh, pct } from "@/lib/format";

type Metric = { label: string; get: (r: CalculationResult) => number; fmt?: (v: number) => string; best?: "max" | "min" };

const METRICS: Metric[] = [
  { label: "Stated CTC", get: (r) => r.structure.ctc, fmt: lakh },
  { label: "Monthly in-hand", get: (r) => r.monthly_in_hand, best: "max" },
  { label: "Annual take-home", get: (r) => r.annual_take_home, best: "max" },
  { label: "Year one, with joining bonus", get: (r) => r.year_one_take_home, best: "max" },
  { label: "Guaranteed fixed cash", get: (r) => r.fixed_cash, best: "max" },
  { label: "Variable pay (target)", get: (r) => r.structure.variable_pay },
  { label: "Income tax", get: (r) => r.regimes[r.selected_regime].tax.total_tax, best: "min" },
  { label: "Retirement savings", get: (r) => r.employee_pf + r.structure.employer_pf + r.structure.employer_nps, best: "max" },
  { label: "ESOPs per year", get: (r) => r.structure.esop_value },
  { label: "Share of CTC as cash", get: (r) => r.in_hand_pct_of_ctc, fmt: (v) => pct(v), best: "max" },
];

function CompareInner() {
  const params = useSearchParams();
  const [offers, setOffers] = useState<OfferSummary[] | null>(null);
  const [selected, setSelected] = useState<number[]>(() => (params.get("ids") ?? "").split(",").map(Number).filter(Boolean));
  const [data, setData] = useState<CompareResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.listOffers().then(setOffers, (e) => setError(e.message));
  }, []);

  function toggle(id: number) {
    setData(null);
    setSelected((s) => (s.includes(id) ? s.filter((x) => x !== id) : s.length >= 4 ? s : [...s, id]));
  }

  async function run() {
    setBusy(true);
    setError(null);
    try {
      setData(await api.compare(selected));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Comparison failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="wrap pt-20">
      <p className="eyebrow">Compare</p>
      <h1 className="serif mt-4 text-5xl sm:text-6xl">Side by side</h1>
      <p className="mt-5 max-w-lg text-muted">Choose two to four offers. We compare what you actually take home, not the headline CTC.</p>

      <div className="mt-14">
        {offers === null ? (
          <p className="text-sm text-muted">Loading…</p>
        ) : offers.length < 2 ? (
          <p className="text-sm text-muted">
            You need at least two offers.{" "}
            <Link href="/" className="link-cta ml-2">
              Add another
            </Link>
          </p>
        ) : (
          <>
            <div className="divide-y divide-line border-y border-line">
              {offers.map((o) => {
                const on = selected.includes(o.id);
                return (
                  <button key={o.id} onClick={() => toggle(o.id)} className="group flex w-full items-center gap-6 py-5 text-left">
                    <span className={`grid size-5 shrink-0 place-items-center rounded-full border transition ${on ? "border-ink bg-ink" : "border-line group-hover:border-muted"}`}>
                      {on && <span className="size-1.5 rounded-full bg-white" />}
                    </span>
                    <span className="serif flex-1 truncate text-xl">{o.label}</span>
                    <span className="tabular hidden text-sm text-muted sm:block">{lakh(o.ctc)} CTC</span>
                    <span className="tabular w-32 text-right text-sm">{inr(o.monthly_in_hand)}/mo</span>
                  </button>
                );
              })}
            </div>
            <button className="btn-primary mt-8" disabled={selected.length < 2 || busy} onClick={run}>
              {busy && <Loader2 size={14} className="animate-spin" />} Compare {selected.length} offers
            </button>
          </>
        )}
        {error && <p className="mt-6 border-l border-bad pl-4 text-sm text-bad">{error}</p>}
      </div>

      {data && (
        <div className="mt-24 space-y-24">
          <div className="overflow-x-auto">
            <table className="w-full min-w-[600px] text-[15px]">
              <thead>
                <tr>
                  <th />
                  {data.rows.map((r) => (
                    <th key={r.offer_id} className="pb-6 text-right align-bottom">
                      {r.offer_id === data.best_annual_take_home && <span className="eyebrow mb-2 block !text-good">Most cash</span>}
                      <Link href={`/offers/${r.offer_id}`} className="serif text-xl hover:opacity-60">
                        {r.label}
                      </Link>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {METRICS.map((m) => {
                  const vals = data.rows.map((r) => m.get(r.result));
                  const target = m.best === "max" ? Math.max(...vals) : m.best === "min" ? Math.min(...vals) : null;
                  return (
                    <tr key={m.label} className="border-t border-line">
                      <td className="py-4 pr-4 text-muted">{m.label}</td>
                      {vals.map((v, i) => (
                        <td key={i} className={`tabular py-4 text-right ${target !== null && v === target && new Set(vals).size > 1 ? "text-good" : ""}`}>
                          {(m.fmt ?? inr)(v)}
                        </td>
                      ))}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          <div>
            <p className="eyebrow">Composition</p>
            <h2 className="section-title mt-3">Where each CTC goes</h2>
            <p className="mt-2 mb-10 text-sm text-muted">Green reaches your bank. The rest is tax, locked-in savings or conditional pay.</p>
            <CompareStack data={data} />
          </div>

          {data.verdict && (
            <div className="max-w-3xl">
              <p className="eyebrow">Verdict</p>
              <h2 className="section-title mt-3">Our read</h2>
              <div className="prose-offer mt-8 text-[15px] text-ink/85">
                <ReactMarkdown>{data.verdict}</ReactMarkdown>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default function ComparePage() {
  return (
    <Suspense fallback={<div className="wrap py-32 text-center text-sm text-muted">Loading…</div>}>
      <CompareInner />
    </Suspense>
  );
}
