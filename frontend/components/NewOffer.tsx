"use client";

import { useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { ArrowRight, Loader2 } from "lucide-react";
import { api, type OfferDetail, type SalaryStructure } from "@/lib/api";

type Tab = "upload" | "paste" | "manual";

const TABS: { id: Tab; label: string }[] = [
  { id: "upload", label: "Upload" },
  { id: "paste", label: "Paste" },
  { id: "manual", label: "Manual" },
];

const MANUAL_FIELDS: { key: keyof SalaryStructure; label: string }[] = [
  { key: "ctc", label: "Annual CTC *" },
  { key: "basic", label: "Basic" },
  { key: "hra", label: "HRA" },
  { key: "special_allowance", label: "Special allowance" },
  { key: "employer_pf", label: "Employer PF" },
  { key: "variable_pay", label: "Variable / bonus" },
  { key: "joining_bonus", label: "Joining bonus" },
];

/** Typical Indian CTC split, used only when the user gives just a CTC number. */
function typicalSplit(ctc: number, variable: number): Partial<SalaryStructure> {
  const fixed = ctc - variable;
  const basic = Math.round(fixed * 0.4);
  const hra = Math.round(basic * 0.5);
  const employer_pf = Math.round(basic * 0.12);
  const gratuity = Math.round(basic * 0.0481);
  return { basic, hra, employer_pf, gratuity, special_allowance: fixed - basic - hra - employer_pf - gratuity };
}

export function NewOffer() {
  const router = useRouter();
  const [tab, setTab] = useState<Tab>("upload");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  const [text, setText] = useState("");
  const [manual, setManual] = useState<Record<string, string>>({});
  const fileRef = useRef<HTMLInputElement>(null);

  async function run(fn: () => Promise<OfferDetail>) {
    setBusy(true);
    setError(null);
    try {
      const offer = await fn();
      router.push(`/offers/${offer.id}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Something went wrong");
      setBusy(false);
    }
  }

  function onFile(file: File | undefined) {
    if (!file) return;
    if (!/\.(pdf|txt)$/i.test(file.name)) {
      setError("Please upload a PDF or .txt file");
      return;
    }
    if (file.size > 4 * 1024 * 1024) {
      setError("Please keep the file under 4 MB");
      return;
    }
    run(() => api.uploadOffer(file));
  }

  function submitManual() {
    const num = (k: string) => Number((manual[k] ?? "").replace(/[,₹\s]/g, "")) || 0;
    const ctc = num("ctc");
    if (ctc <= 0) {
      setError("Enter at least the annual CTC");
      return;
    }
    const structure: Partial<SalaryStructure> = {
      company: manual.company || null,
      role: manual.role || null,
      location: manual.location || null,
    };
    for (const f of MANUAL_FIELDS) (structure as Record<string, unknown>)[f.key] = num(f.key);
    const full = num("basic") > 0 ? structure : { ...structure, ...typicalSplit(ctc, num("variable_pay")) };
    run(() => api.createManual(full, undefined, manual.company || undefined));
  }

  return (
    <div className="card">
      <div className="flex gap-8 border-b border-line">
        {TABS.map(({ id, label }) => (
          <button
            key={id}
            onClick={() => {
              setTab(id);
              setError(null);
            }}
            className={`-mb-px border-b pb-4 text-[11px] uppercase tracking-[0.22em] transition ${
              tab === id ? "border-ink text-ink" : "border-transparent text-muted hover:text-ink"
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      <div className="pt-8">
        {tab === "upload" && (
          <button
            type="button"
            disabled={busy}
            onClick={() => fileRef.current?.click()}
            onDragOver={(e) => {
              e.preventDefault();
              setDragging(true);
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={(e) => {
              e.preventDefault();
              setDragging(false);
              onFile(e.dataTransfer.files[0]);
            }}
            className={`flex w-full flex-col items-center justify-center rounded-[18px] px-6 py-20 text-center transition ${
              dragging ? "bg-accent-soft" : "bg-surface-2 hover:bg-[#eceae4]"
            }`}
          >
            {busy ? (
              <Loader2 className="animate-spin text-ink" size={22} strokeWidth={1.25} />
            ) : (
              <span className="serif text-5xl leading-none text-ink/80">+</span>
            )}
            <p className="serif mt-6 text-2xl">{busy ? "Reading your offer" : "Drop your offer letter"}</p>
            <p className="mt-2 text-sm text-muted">
              {busy ? "Extracting the structure and calculating your pay" : "PDF or text file · or click to browse"}
            </p>
            <input
              ref={fileRef}
              type="file"
              accept=".pdf,.txt,application/pdf,text/plain"
              className="hidden"
              onChange={(e) => onFile(e.target.files?.[0])}
            />
          </button>
        )}

        {tab === "paste" && (
          <div className="space-y-6">
            <textarea
              value={text}
              onChange={(e) => setText(e.target.value)}
              rows={10}
              placeholder={"Paste the compensation section of your offer letter.\n\nBasic Salary: ₹60,000 per month\nHRA: ₹30,000 per month\n…"}
              className="input-box resize-none leading-relaxed"
            />
            <button className="btn-primary w-full" disabled={busy || text.trim().length < 50} onClick={() => run(() => api.createFromText(text))}>
              {busy ? <Loader2 className="animate-spin" size={15} /> : null} Analyze text
            </button>
          </div>
        )}

        {tab === "manual" && (
          <div className="space-y-8">
            <div className="grid gap-6 sm:grid-cols-3">
              {(["company", "role", "location"] as const).map((k) => (
                <div key={k}>
                  <label className="label">{k}</label>
                  <input className="input" value={manual[k] ?? ""} onChange={(e) => setManual({ ...manual, [k]: e.target.value })} />
                </div>
              ))}
            </div>
            <div className="grid grid-cols-2 gap-6 sm:grid-cols-4">
              {MANUAL_FIELDS.map((f) => (
                <div key={f.key}>
                  <label className="label">{f.label}</label>
                  <input
                    className="input tabular"
                    inputMode="numeric"
                    placeholder="0"
                    value={manual[f.key] ?? ""}
                    onChange={(e) => setManual({ ...manual, [f.key]: e.target.value })}
                  />
                </div>
              ))}
            </div>
            <p className="text-sm text-muted">
              Only know the CTC? Leave the rest empty and we&apos;ll assume a typical split. You can refine it later.
            </p>
            <button className="btn-primary w-full" disabled={busy} onClick={submitManual}>
              {busy ? <Loader2 className="animate-spin" size={15} /> : null} Calculate take-home <ArrowRight size={15} strokeWidth={1.5} />
            </button>
          </div>
        )}

        {error && <p className="mt-6 border-l border-bad pl-4 text-sm text-bad">{error}</p>}

        {tab === "upload" && (
          <p className="mt-6 text-sm text-muted">
            No letter handy? Try a fictional sample:{" "}
            <button className="underline underline-offset-4 hover:text-ink" disabled={busy} onClick={() => run(() => api.loadSample("nimbus"))}>
              Nimbus Cloud
            </button>{" "}
            or{" "}
            <button className="underline underline-offset-4 hover:text-ink" disabled={busy} onClick={() => run(() => api.loadSample("quantora"))}>
              Quantora Labs
            </button>
          </p>
        )}

        <p className="mt-8 border-t border-line pt-5 text-xs leading-relaxed text-muted">
          <span className="text-ink/80">Private by design.</span> Your PDF is read in memory and never stored. We keep
          only the extracted text and figures, visible only in this browser. You can delete them any time, and everything
          is cleared automatically after every 50 uploads or comparisons.
        </p>
      </div>
    </div>
  );
}
