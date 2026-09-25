"use client";

import { Suspense, useEffect, useState } from "react";
import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";
import { api, type OfferDetail } from "@/lib/api";
import { inr, lakh, pct } from "@/lib/format";

/** One-page summary laid out for A4, saved as PDF through the browser's print dialog (keeps ₹ and fonts intact). */
function Summary() {
  const { id } = useParams<{ id: string }>();
  const autoPrint = useSearchParams().get("print") === "1";
  const [offer, setOffer] = useState<OfferDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.getOffer(id).then(setOffer, (e) => setError(e.message));
  }, [id]);

  useEffect(() => {
    if (!offer || !autoPrint) return;
    const t = setTimeout(() => window.print(), 600); // let fonts settle before the dialog opens
    return () => clearTimeout(t);
  }, [offer, autoPrint]);

  if (error) return <p className="wrap py-32 text-center">{error}</p>;
  if (!offer) return <p className="wrap py-32 text-center text-sm text-muted">Preparing summary…</p>;

  const r = offer.result;
  const s = offer.structure;
  const sel = r.regimes[r.selected_regime];
  const meta = [s.role, s.location].filter(Boolean).join(" · ");
  const when = (key: string): string | null =>
    ({
      gratuity: "After 5 years",
      retention_bonus: s.retention_after_months > 0 ? `After ${s.retention_after_months} months` : "If you stay",
      joining_bonus: "One-time",
      variable_pay: "Yearly",
      esop_value: "Vests yearly",
    })[key] ?? null;

  return (
    <div className="mx-auto max-w-[780px] px-6 py-10 text-[13px] leading-relaxed text-ink print:max-w-none print:p-0">
      <div className="mb-8 flex items-center justify-between print:hidden">
        <Link href={`/offers/${offer.id}`} className="link-cta">
          ← Back to offer
        </Link>
        <button className="btn-primary" onClick={() => window.print()}>
          Save as PDF
        </button>
      </div>

      <header className="border-b border-ink pb-5">
        <p className="text-[10px] uppercase tracking-[0.24em] text-muted">
          OfferLens summary · {new Date().toLocaleDateString("en-IN", { dateStyle: "medium" })}
        </p>
        <h1 className="serif mt-2 text-3xl">{s.company ?? offer.label}</h1>
        {meta && <p className="mt-1 text-muted">{meta}</p>}
      </header>

      <section className="mt-6 grid grid-cols-3 gap-4 border-b border-line pb-6">
        {[
          ["In hand each month", inr(r.monthly_in_hand), "fixed pay, after tax and PF"],
          ["Stated CTC", lakh(s.ctc), `${pct(r.in_hand_pct_of_ctc)} reaches you as cash`],
          ["Annual take-home", lakh(r.annual_take_home), `with ${r.assumptions.variable_payout_pct}% variable payout`],
          ["Year one", lakh(r.year_one_take_home), "including one-time bonuses paid in year one"],
          ["Income tax", inr(sel.tax.total_tax), `${r.selected_regime} regime · ${pct(sel.tax.effective_rate, 1)} effective`],
          ["Red-flag score", `${offer.red_flags.score}/100`, offer.red_flags.level],
        ].map(([label, value, sub]) => (
          <div key={label}>
            <p className="text-[10px] uppercase tracking-[0.2em] text-muted">{label}</p>
            <p className="tabular mt-1 text-xl">{value}</p>
            <p className="text-[11px] text-muted">{sub}</p>
          </div>
        ))}
      </section>

      <section className="mt-6 break-inside-avoid">
        <h2 className="serif text-lg">Salary components</h2>
        <table className="mt-2 w-full">
          <thead>
            <tr className="text-left text-[10px] uppercase tracking-[0.18em] text-muted">
              <th className="py-1 font-normal">Component</th>
              <th className="py-1 text-right font-normal">Monthly</th>
              <th className="py-1 text-right font-normal">Annual</th>
            </tr>
          </thead>
          <tbody>
            {r.components.map((c) => (
              <tr key={c.key} className="border-t border-line">
                <td className="py-1">
                  {c.label}
                  {!c.in_ctc && <span className="ml-2 text-[10px] uppercase tracking-[0.15em] text-muted">outside CTC</span>}
                </td>
                <td className="tabular py-1 text-right text-muted">{c.monthly !== null ? inr(c.monthly) : (when(c.key) ?? "Not monthly")}</td>
                <td className="tabular py-1 text-right">{inr(c.annual)}</td>
              </tr>
            ))}
            <tr className="border-t border-ink">
              <td className="py-1">Stated CTC</td>
              <td />
              <td className="tabular py-1 text-right">{inr(s.ctc)}</td>
            </tr>
          </tbody>
        </table>
        {offer.extraction_meta.estimated_split && (
          <p className="mt-2 text-[11px] text-muted">The letter had no full breakup, so this split is an estimate.</p>
        )}
      </section>

      <section className="mt-6 grid grid-cols-2 gap-6 break-inside-avoid">
        {(["new", "old"] as const).map((k) => (
          <div key={k} className="border-t border-line pt-3">
            <p className="text-[10px] uppercase tracking-[0.2em] text-muted">
              {k} regime{r.recommended_regime === k ? " · recommended" : ""}
            </p>
            <p className="tabular mt-1 text-lg">{inr(r.regimes[k].tax.total_tax)} tax a year</p>
            <p className="text-muted">{inr(r.regimes[k].monthly_in_hand)} a month in hand</p>
          </div>
        ))}
      </section>

      <section className="mt-6 break-inside-avoid">
        <h2 className="serif text-lg">Three years out</h2>
        <table className="mt-2 w-full">
          <thead>
            <tr className="text-left text-[10px] uppercase tracking-[0.18em] text-muted">
              <th className="py-1 font-normal">Year</th>
              <th className="py-1 text-right font-normal">Monthly in hand</th>
              <th className="py-1 text-right font-normal">Take-home</th>
              <th className="py-1 text-right font-normal">One-time</th>
              <th className="py-1 text-right font-normal">Cash total</th>
            </tr>
          </thead>
          <tbody>
            {offer.projection.years.map((y) => (
              <tr key={y.year} className="border-t border-line">
                <td className="py-1">Year {y.year}</td>
                <td className="tabular py-1 text-right">{inr(y.monthly_in_hand)}</td>
                <td className="tabular py-1 text-right">{inr(y.take_home)}</td>
                <td className="tabular py-1 text-right">{y.one_time > 0 ? inr(y.one_time) : "—"}</td>
                <td className="tabular py-1 text-right">{inr(y.cash_total)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="mt-2 text-[11px] text-muted">{offer.projection.notes[0]}</p>
      </section>

      {offer.red_flags.flags.length > 0 && (
        <section className="mt-6 break-inside-avoid">
          <h2 className="serif text-lg">Red flags</h2>
          <ul className="mt-2 space-y-1.5">
            {offer.red_flags.flags.map((f) => (
              <li key={f.key}>
                <span className="text-[10px] uppercase tracking-[0.15em] text-muted">{f.severity}</span> <span>{f.title}.</span>{" "}
                <span className="text-muted">{f.detail}</span>
              </li>
            ))}
          </ul>
        </section>
      )}

      {!!offer.extraction_meta.notes?.length && (
        <section className="mt-6 break-inside-avoid">
          <h2 className="serif text-lg">From the letter</h2>
          <ul className="mt-2 list-disc space-y-1 pl-5 text-muted">
            {offer.extraction_meta.notes.map((n) => (
              <li key={n}>{n}</li>
            ))}
          </ul>
        </section>
      )}

      <p className="mt-10 border-t border-line pt-3 text-[10px] text-muted">
        Estimates under FY 2025–26 Indian income-tax rules, not tax advice. Generated by OfferLens: AI reads the letter, a
        deterministic engine does the maths.
      </p>
    </div>
  );
}

export default function SummaryPage() {
  return (
    <Suspense fallback={<p className="wrap py-32 text-center text-sm text-muted">Preparing summary…</p>}>
      <Summary />
    </Suspense>
  );
}
