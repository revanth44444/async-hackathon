"use client";

import { useState } from "react";
import ReactMarkdown from "react-markdown";
import { ArrowUp, Loader2 } from "lucide-react";
import { api, type CalculationResult, type NumericField, type OfferDetail, type Regime, type SalaryStructure, type Suggestion } from "@/lib/api";
import { inr, lakh, pct } from "@/lib/format";

function SectionHead({ eyebrow, title, sub, action }: { eyebrow: string; title: string; sub?: string; action?: React.ReactNode }) {
  return (
    <div className="mb-10 flex items-end justify-between gap-4">
      <div>
        <p className="eyebrow">{eyebrow}</p>
        <h2 className="section-title mt-3">{title}</h2>
        {sub && <p className="mt-2 text-sm text-muted">{sub}</p>}
      </div>
      {action}
    </div>
  );
}

export function StatRow({ r }: { r: CalculationResult }) {
  const sel = r.regimes[r.selected_regime];
  const stats = [
    { label: "Annual take-home", value: lakh(r.annual_take_home), sub: `with ${r.assumptions.variable_payout_pct}% variable payout` },
    { label: "Income tax", value: inr(sel.tax.total_tax), sub: `${r.selected_regime} regime · ${pct(sel.tax.effective_rate, 1)} effective` },
    { label: "Provident fund", value: inr(r.employee_pf + r.structure.employer_pf), sub: "saved for you each year" },
    { label: "Reaches you", value: pct(r.in_hand_pct_of_ctc), sub: "of the CTC, as cash" },
  ];
  return (
    <div className="grid grid-cols-2 border-y border-line lg:grid-cols-4">
      {stats.map((s) => (
        <div
          key={s.label}
          className="border-line py-8 pr-6 even:border-l even:pl-6 [&:nth-child(n+3)]:border-t lg:border-l lg:pl-8 lg:first:border-l-0 lg:first:pl-0 lg:[&:nth-child(n+3)]:border-t-0"
        >
          <p className="eyebrow">{s.label}</p>
          <p className="tabular mt-4 text-3xl tracking-tight sm:text-[34px]" style={{ fontWeight: 200 }}>
            {s.value}
          </p>
          <p className="mt-2 text-xs text-muted">{s.sub}</p>
        </div>
      ))}
    </div>
  );
}

export function Warnings({ items }: { items: string[] }) {
  if (!items.length) return null;
  return (
    <div className="space-y-2">
      {items.map((w) => (
        <p key={w} className="border-l border-bad pl-4 text-sm text-bad">
          {w}
        </p>
      ))}
    </div>
  );
}

const EDITABLE: { key: NumericField; label: string; group: string }[] = [
  { key: "basic", label: "Basic salary", group: "Fixed pay" },
  { key: "hra", label: "House rent allowance", group: "Fixed pay" },
  { key: "special_allowance", label: "Special allowance", group: "Fixed pay" },
  { key: "lta", label: "Leave travel allowance", group: "Fixed pay" },
  { key: "meal_allowance", label: "Meal allowance", group: "Fixed pay" },
  { key: "other_allowances", label: "Other allowances", group: "Fixed pay" },
  { key: "employer_pf", label: "Employer PF", group: "Retirement" },
  { key: "gratuity", label: "Gratuity", group: "Retirement" },
  { key: "employer_nps", label: "Employer NPS", group: "Retirement" },
  { key: "insurance", label: "Insurance & benefits", group: "Benefits" },
  { key: "variable_pay", label: "Variable pay", group: "Not paid monthly" },
  { key: "joining_bonus", label: "Joining bonus", group: "Not paid monthly" },
  { key: "esop_value", label: "ESOPs per year", group: "Not paid monthly" },
];

/** Items that must never be shown as a monthly figure. */
const NOT_MONTHLY: Partial<Record<NumericField, string>> = {
  variable_pay: "Yearly",
  joining_bonus: "One-time",
  esop_value: "Vests yearly",
};

export function BreakdownEditor({ offer, onSaved }: { offer: OfferDetail; onSaved: (o: OfferDetail) => void }) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<SalaryStructure>(offer.structure);
  const [saving, setSaving] = useState(false);
  const desc = Object.fromEntries(offer.result.components.map((c) => [c.key, c.description]));
  const outsideCtc = new Set(offer.result.components.filter((c) => !c.in_ctc).map((c) => c.key));
  const outsideTotal = offer.result.components.filter((c) => !c.in_ctc).reduce((sum, c) => sum + c.annual, 0);
  const rows = editing ? EDITABLE : EDITABLE.filter((f) => offer.structure[f.key] > 0);
  const groups = [...new Set(rows.map((r) => r.group))];
  const source =
    offer.extraction_meta.method === "ai"
      ? "Read by AI from your letter. Please verify."
      : offer.extraction_meta.method === "heuristic"
        ? "Read by keyword matching. Please verify."
        : "Entered by you.";

  async function save() {
    setSaving(true);
    try {
      onSaved(await api.updateOffer(offer.id, { structure: draft }));
      setEditing(false);
    } finally {
      setSaving(false);
    }
  }

  const num = (v: string) => Number(v.replace(/[^\d.]/g, "")) || 0;

  return (
    <div>
      <SectionHead
        eyebrow="Structure"
        title="Salary components"
        sub={source}
        action={
          editing ? (
            <div className="flex items-center gap-5">
              <button
                className="text-[11px] uppercase tracking-[0.22em] text-muted hover:text-ink"
                onClick={() => {
                  setDraft(offer.structure);
                  setEditing(false);
                }}
              >
                Cancel
              </button>
              <button className="btn-primary" onClick={save} disabled={saving}>
                {saving && <Loader2 size={14} className="animate-spin" />} Save
              </button>
            </div>
          ) : (
            <button className="link-cta" onClick={() => setEditing(true)}>
              Edit
            </button>
          )
        }
      />

      <table className="w-full text-[15px]">
        <thead>
          <tr className="text-left">
            <th className="eyebrow pb-3" />
            <th className="eyebrow pb-3 text-right">Monthly</th>
            <th className="eyebrow pb-3 text-right">Annual</th>
          </tr>
        </thead>
        {groups.map((g) => (
          <tbody key={g}>
            <tr>
              <td colSpan={3} className="pt-8 pb-2 text-[10px] uppercase tracking-[0.2em] text-muted">
                {g}
              </td>
            </tr>
            {rows
              .filter((f) => f.group === g)
              .map((f) => (
                <tr key={f.key} className="border-t border-line">
                  <td className="py-3 pr-2">
                    <span title={desc[f.key]} className={desc[f.key] ? "cursor-help" : ""}>
                      {f.label}
                    </span>
                    {!editing && NOT_MONTHLY[f.key] && offer.structure[f.key] > 0 && (
                      <span className="ml-3 text-[10px] uppercase tracking-[0.18em] text-muted">
                        {outsideCtc.has(f.key) ? "Outside CTC" : "In CTC"}
                      </span>
                    )}
                  </td>
                  <td className="tabular py-3 text-right text-muted">
                    {NOT_MONTHLY[f.key] ?? inr((editing ? draft : offer.structure)[f.key] / 12)}
                  </td>
                  <td className="py-3 text-right">
                    {editing ? (
                      <input
                        className="input tabular w-28 py-1 text-right"
                        inputMode="numeric"
                        value={draft[f.key] || ""}
                        placeholder="0"
                        onChange={(e) => setDraft({ ...draft, [f.key]: num(e.target.value) })}
                      />
                    ) : (
                      <span className="tabular">{inr(offer.structure[f.key])}</span>
                    )}
                  </td>
                </tr>
              ))}
          </tbody>
        ))}
        <tfoot>
          <tr className="border-t border-ink">
            <td className="serif pt-4 text-lg">Stated CTC</td>
            <td />
            <td className="pt-4 text-right">
              {editing ? (
                <input
                  className="input tabular w-28 py-1 text-right"
                  inputMode="numeric"
                  value={draft.ctc || ""}
                  onChange={(e) => setDraft({ ...draft, ctc: num(e.target.value) })}
                />
              ) : (
                <span className="tabular text-lg">{inr(offer.structure.ctc)}</span>
              )}
            </td>
          </tr>
          {!editing && outsideTotal > 0 && (
            <tr>
              <td colSpan={3} className="pt-2 text-sm text-muted">
                Plus {inr(outsideTotal)} outside the CTC ({[...outsideCtc].map((k) => EDITABLE.find((f) => f.key === k)?.label.toLowerCase()).join(", ")}).
              </td>
            </tr>
          )}
        </tfoot>
      </table>
    </div>
  );
}

export function RegimePanel({ r }: { r: CalculationResult }) {
  const [open, setOpen] = useState<Regime | null>(null);
  return (
    <div>
      <SectionHead
        eyebrow="Tax"
        title="New or old regime"
        sub={
          r.regime_savings > 0
            ? `The ${r.recommended_regime} regime saves ${inr(r.regime_savings)} a year with your current inputs.`
            : "Both regimes cost the same with your current inputs."
        }
      />
      <div className="grid gap-4 sm:grid-cols-2">
        {(["new", "old"] as const).map((k) => {
          const g = r.regimes[k];
          const best = r.recommended_regime === k;
          return (
            <div key={k} className={`rounded-[22px] p-6 ${best ? "bg-ink text-white" : "bg-surface-2"}`}>
              <div className="flex items-center justify-between">
                <p className="text-[11px] uppercase tracking-[0.22em] opacity-70">{k} regime</p>
                {best && <span className="size-1.5 rounded-full bg-white/70" title="Recommended" />}
              </div>
              <p className="tabular mt-8 text-4xl tracking-tight" style={{ fontWeight: 200 }}>
                {inr(g.tax.total_tax)}
              </p>
              <p className="mt-2 text-sm opacity-60">tax a year · {inr(g.monthly_in_hand)} a month in hand</p>
              {best && <p className="mt-1 text-sm opacity-60">Recommended for you</p>}
              <button onClick={() => setOpen(open === k ? null : k)} className="mt-6 border-b border-current pb-0.5 text-[10px] uppercase tracking-[0.2em] opacity-70 hover:opacity-100">
                {open === k ? "Hide workings" : "Show workings"}
              </button>
              {open === k && (
                <dl className="tabular mt-5 space-y-1.5 border-t border-current/15 pt-5 text-xs">
                  <Row label="Gross taxable salary" value={g.tax.gross_income} />
                  {[...g.tax.exemptions, ...g.tax.deductions].map((x) => (
                    <Row key={x.label} label={`− ${x.label}`} value={x.amount} muted />
                  ))}
                  <Row label="Taxable income" value={g.tax.taxable_income} />
                  {g.tax.slabs
                    .filter((s) => s.taxable_amount > 0)
                    .map((s) => (
                      <Row key={s.lower} label={`${lakh(s.lower)}–${s.upper ? lakh(s.upper) : "∞"} at ${pct(s.rate)}`} value={s.tax} muted />
                    ))}
                  {g.tax.rebate > 0 && <Row label="− Rebate 87A" value={g.tax.rebate} muted />}
                  {g.tax.surcharge > 0 && <Row label="+ Surcharge" value={g.tax.surcharge} muted />}
                  <Row label="+ Cess 4%" value={g.tax.cess} muted />
                  <Row label="Total tax" value={g.tax.total_tax} />
                </dl>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

function Row({ label, value, muted }: { label: string; value: number; muted?: boolean }) {
  return (
    <div className={`flex justify-between gap-3 ${muted ? "opacity-60" : ""}`}>
      <dt>{label}</dt>
      <dd>{inr(value)}</dd>
    </div>
  );
}

export function Explanation({ offerId, initial }: { offerId: string; initial: string | null }) {
  const [text, setText] = useState(initial);
  const [method, setMethod] = useState<string | undefined>(initial ? "ai" : undefined);
  const [busy, setBusy] = useState(false);

  async function load(refresh: boolean) {
    setBusy(true);
    try {
      const res = await api.explain(offerId, refresh);
      setText(res.explanation);
      setMethod(res.method ?? "ai");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      <SectionHead
        eyebrow="In plain words"
        title="Your offer, explained"
        action={
          text && (
            <button className="link-cta" onClick={() => load(true)} disabled={busy}>
              {busy ? "Writing…" : "Rewrite"}
            </button>
          )
        }
      />
      {text ? (
        <>
          <div className="prose-offer text-[15px] text-ink/85">
            <ReactMarkdown>{text}</ReactMarkdown>
          </div>
          {method === "template" && <p className="mt-4 text-xs text-muted">Template summary. AI is currently unavailable.</p>}
        </>
      ) : (
        <button className="btn-primary" onClick={() => load(false)} disabled={busy}>
          {busy && <Loader2 size={14} className="animate-spin" />}
          {busy ? "Writing your explanation" : "Explain my offer"}
        </button>
      )}
    </div>
  );
}

const QUICK_QUESTIONS = [
  "Is the variable pay guaranteed?",
  "What should I negotiate?",
  "What if I leave within a year?",
  "Why is gratuity in my CTC?",
];

export function AskBox({ offerId }: { offerId: string }) {
  const [q, setQ] = useState("");
  const [thread, setThread] = useState<{ q: string; a: string | null }[]>([]);

  async function ask(question: string) {
    if (question.trim().length < 3) return;
    setQ("");
    setThread((t) => [...t, { q: question, a: null }]);
    const { answer } = await api.ask(offerId, question).catch((e) => ({ answer: `Error: ${e.message}` }));
    setThread((t) => t.map((m, i) => (i === t.length - 1 ? { ...m, a: answer } : m)));
  }

  return (
    <div>
      <SectionHead eyebrow="Ask" title="Questions about this offer" />
      <div className="space-y-8">
        {thread.map((m, i) => (
          <div key={i} className="space-y-3">
            <p className="serif text-lg">{m.q}</p>
            <div className="prose-offer border-l border-line pl-5 text-[15px] text-ink/85">
              {m.a === null ? <Loader2 size={14} className="animate-spin text-muted" /> : <ReactMarkdown>{m.a}</ReactMarkdown>}
            </div>
          </div>
        ))}
      </div>
      {thread.length === 0 && (
        <div className="divide-y divide-line border-y border-line">
          {QUICK_QUESTIONS.map((x) => (
            <button key={x} onClick={() => ask(x)} className="flex w-full items-center justify-between py-4 text-left text-[15px] text-muted transition hover:text-ink">
              {x}
              <span className="text-xs">→</span>
            </button>
          ))}
        </div>
      )}
      <form
        className="mt-8 flex items-center gap-3 rounded-full bg-surface-2 py-1.5 pr-1.5 pl-5"
        onSubmit={(e) => {
          e.preventDefault();
          ask(q);
        }}
      >
        <input
          className="flex-1 bg-transparent text-[15px] outline-none placeholder:text-muted/70"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Ask anything about this offer"
        />
        <button className="grid size-9 place-items-center rounded-full bg-ink text-white transition hover:bg-accent" aria-label="Send">
          <ArrowUp size={16} strokeWidth={1.5} />
        </button>
      </form>
    </div>
  );
}

export function Suggestions({ items }: { items: Suggestion[] }) {
  if (!items.length) return null;
  return (
    <div>
      <SectionHead eyebrow="Opportunities" title="Worth a conversation" />
      <ul className="divide-y divide-line border-y border-line">
        {items.map((s) => (
          <li key={s.title} className="flex gap-6 py-5">
            <div className="flex-1">
              <p className="text-[15px]">{s.title}</p>
              <p className="mt-1 text-sm text-muted">{s.detail}</p>
            </div>
            {s.annual_impact > 0 && <span className="tabular shrink-0 text-sm text-good">+{inr(s.annual_impact)} a year</span>}
          </li>
        ))}
      </ul>
    </div>
  );
}

export function LetterNotes({ notes }: { notes?: string[] }) {
  if (!notes?.length) return null;
  return (
    <div>
      <SectionHead eyebrow="Fine print" title="From the letter" />
      <ul className="space-y-3 text-sm text-muted">
        {notes.map((n) => (
          <li key={n} className="border-l border-line pl-4">
            {n}
          </li>
        ))}
      </ul>
    </div>
  );
}
