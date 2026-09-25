"use client";

import { useEffect, useState } from "react";
import { Loader2 } from "lucide-react";
import { api, type Assumptions, type OfferDetail, type SimulationResult } from "@/lib/api";
import { inr, signed, STATE_NAMES } from "@/lib/format";

function Slider({
  label,
  value,
  min,
  max,
  step,
  format,
  onChange,
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  step: number;
  format: (v: number) => string;
  onChange: (v: number) => void;
}) {
  return (
    <div>
      <div className="mb-2 flex items-baseline justify-between">
        <span className="label mb-0">{label}</span>
        <span className="tabular text-lg" style={{ fontWeight: 300 }}>
          {format(value)}
        </span>
      </div>
      <input type="range" min={min} max={max} step={step} value={value} onChange={(e) => onChange(Number(e.target.value))} className="w-full" />
    </div>
  );
}

function Money({ label, value, onChange }: { label: string; value: number; onChange: (v: number) => void }) {
  return (
    <div>
      <label className="label">{label}</label>
      <input
        className="input tabular"
        inputMode="numeric"
        value={value || ""}
        placeholder="0"
        onChange={(e) => onChange(Number(e.target.value.replace(/[^\d]/g, "")) || 0)}
      />
    </div>
  );
}

function Delta({ label, base, next, invert }: { label: string; base: number; next: number; invert?: boolean }) {
  const d = next - base;
  const good = invert ? d < 0 : d > 0;
  return (
    <div className="tile">
      <p className="eyebrow">{label}</p>
      <p className="tabular mt-3 text-2xl tracking-tight" style={{ fontWeight: 300 }}>
        {inr(next)}
      </p>
      <p className={`tabular mt-1 text-xs ${Math.abs(d) < 1 ? "text-muted" : good ? "text-good" : "text-bad"}`}>
        {Math.abs(d) < 1 ? "Unchanged" : `${signed(d)}`}
      </p>
    </div>
  );
}

function Toggle({ checked, onChange, children }: { checked: boolean; onChange: (v: boolean) => void; children: React.ReactNode }) {
  return (
    <label className="flex cursor-pointer items-center justify-between gap-4 border-b border-line py-3 text-sm">
      <span className="text-ink/80">{children}</span>
      <span className={`relative h-6 w-10 shrink-0 rounded-full transition ${checked ? "bg-ink" : "bg-line"}`}>
        <span className={`absolute top-0.5 size-5 rounded-full bg-white shadow-sm transition-all ${checked ? "left-[18px]" : "left-0.5"}`} />
      </span>
      <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} className="sr-only" />
    </label>
  );
}

export function Simulator({ offer, onSaved }: { offer: OfferDetail; onSaved: (o: OfferDetail) => void }) {
  const [a, setA] = useState<Assumptions>(offer.assumptions);
  const [hike, setHike] = useState(0);
  const [sim, setSim] = useState<SimulationResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);

  const set = <K extends keyof Assumptions>(k: K, v: Assumptions[K]) => setA((prev) => ({ ...prev, [k]: v }));

  useEffect(() => {
    let cancelled = false;
    const t = setTimeout(() => {
      setLoading(true);
      api
        .simulate(offer.id, a, hike, {})
        .then((res) => !cancelled && setSim(res))
        .catch(() => {})
        .finally(() => !cancelled && setLoading(false));
    }, 250);
    return () => {
      cancelled = true;
      clearTimeout(t);
    };
  }, [a, hike, offer.id]);

  const dirty = JSON.stringify(a) !== JSON.stringify(offer.assumptions);
  const s = sim?.scenario;
  const b = sim?.baseline;

  return (
    <section>
      <div className="mb-10 flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="eyebrow">Simulate</p>
          <h2 className="section-title mt-3">What if</h2>
          <p className="mt-2 text-sm text-muted">Adjust anything. Your pay updates as you go.</p>
        </div>
        <div className="flex items-center gap-6">
          <button
            className="text-[11px] uppercase tracking-[0.22em] text-muted hover:text-ink"
            onClick={() => {
              setA(offer.assumptions);
              setHike(0);
            }}
          >
            Reset
          </button>
          <button
            className="btn-primary"
            disabled={!dirty || saving}
            title="Save these assumptions (not the hike) to the offer"
            onClick={async () => {
              setSaving(true);
              try {
                onSaved(await api.updateOffer(offer.id, { assumptions: a }));
              } finally {
                setSaving(false);
              }
            }}
          >
            Save assumptions
          </button>
        </div>
      </div>

      <div className="grid gap-12 lg:grid-cols-[1fr_1fr]">
        <div className="space-y-9">
          <div className="grid grid-cols-3 rounded-full bg-surface-2 p-1 text-sm">
            {(["auto", "new", "old"] as const).map((r) => (
              <button
                key={r}
                onClick={() => set("regime", r)}
                className={`rounded-full py-2 transition ${a.regime === r ? "bg-surface text-ink shadow-[0_1px_3px_rgba(0,0,0,0.08)]" : "text-muted"}`}
              >
                {r === "auto" ? "Best regime" : r === "new" ? "New regime" : "Old regime"}
              </button>
            ))}
          </div>
          <Slider label="Salary hike" value={hike} min={-20} max={100} step={1} format={(v) => `${v > 0 ? "+" : ""}${v}%`} onChange={setHike} />
          <Slider
            label="Variable payout"
            value={a.variable_payout_pct}
            min={0}
            max={150}
            step={5}
            format={(v) => `${v}%`}
            onChange={(v) => set("variable_payout_pct", v)}
          />
          <div className="grid grid-cols-2 gap-8">
            <div>
              <label className="label">Work state</label>
              <select className="input cursor-pointer" value={a.state} onChange={(e) => set("state", e.target.value)}>
                {Object.entries(STATE_NAMES).map(([k, v]) => (
                  <option key={k} value={k}>
                    {v}
                  </option>
                ))}
              </select>
            </div>
            <Money label="Rent a month" value={a.monthly_rent} onChange={(v) => set("monthly_rent", v)} />
          </div>
          <div>
            <Toggle checked={a.metro} onChange={(v) => set("metro", v)}>
              Metro city for HRA
            </Toggle>
            <Toggle checked={a.pf_on_capped_wage} onChange={(v) => set("pf_on_capped_wage", v)}>
              PF capped at ₹1,800 a month
            </Toggle>
          </div>
          <details className="group">
            <summary className="flex cursor-pointer list-none items-center justify-between text-[11px] uppercase tracking-[0.22em] text-muted hover:text-ink">
              Old-regime deductions <span className="transition group-open:rotate-45">+</span>
            </summary>
            <div className="mt-6 grid grid-cols-2 gap-8">
              <Money label="80C beyond EPF" value={a.investments_80c} onChange={(v) => set("investments_80c", v)} />
              <Money label="80D health cover" value={a.medical_80d} onChange={(v) => set("medical_80d", v)} />
              <Money label="Home loan interest" value={a.home_loan_interest} onChange={(v) => set("home_loan_interest", v)} />
              <Money label="Own NPS 80CCD(1B)" value={a.nps_80ccd1b} onChange={(v) => set("nps_80ccd1b", v)} />
            </div>
          </details>
        </div>

        <div className="space-y-4">
          {s && b ? (
            <>
              <div className="spotlight rounded-[22px] p-8 text-white">
                <div className="flex items-center justify-between">
                  <p className="text-[11px] uppercase tracking-[0.22em] text-white/50">Monthly in-hand</p>
                  {loading && <Loader2 size={13} className="animate-spin text-white/50" />}
                </div>
                <p className="tabular mt-10 text-6xl tracking-[-0.03em] sm:text-7xl" style={{ fontWeight: 200 }}>
                  {inr(s.monthly_in_hand)}
                </p>
                <p className="tabular mt-3 text-sm text-white/55">
                  {Math.abs(sim.delta.monthly_in_hand) < 1 ? "Same as now" : `${signed(sim.delta.monthly_in_hand)} a month compared with now`}
                </p>
                <p className="mt-10 text-xs text-white/45">
                  Best regime here: <span className="capitalize text-white/80">{s.recommended_regime}</span>
                  {s.regime_savings > 0 && ` · saves ${inr(s.regime_savings)}`}
                </p>
              </div>
              <div className="grid grid-cols-2 gap-4">
                <Delta label="Annual take-home" base={b.annual_take_home} next={s.annual_take_home} />
                <Delta
                  label={`Tax · ${s.selected_regime}`}
                  base={b.regimes[b.selected_regime].tax.total_tax}
                  next={s.regimes[s.selected_regime].tax.total_tax}
                  invert
                />
                <Delta label="CTC" base={b.structure.ctc} next={s.structure.ctc} />
                <Delta label="Year one" base={b.year_one_take_home} next={s.year_one_take_home} />
              </div>
            </>
          ) : (
            <div className="grid h-80 place-items-center rounded-[22px] bg-surface-2">
              <Loader2 className="animate-spin text-muted" strokeWidth={1.25} />
            </div>
          )}
        </div>
      </div>
    </section>
  );
}
