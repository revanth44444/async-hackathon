"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { CtcDonut } from "@/components/charts";
import { AskBox, BreakdownEditor, Explanation, LetterNotes, RegimePanel, StatRow, Suggestions, Warnings } from "@/components/OfferSections";
import { Simulator } from "@/components/Simulator";
import { api, type OfferDetail } from "@/lib/api";
import { inr, lakh } from "@/lib/format";

export default function OfferPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const [offer, setOffer] = useState<OfferDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.getOffer(id).then(setOffer, (e) => setError(e.message));
  }, [id]);

  if (error)
    return (
      <div className="wrap py-32 text-center">
        <p className="serif text-3xl">{error}</p>
        <Link href="/" className="link-cta mt-8">
          Back home
        </Link>
      </div>
    );
  if (!offer) return <div className="wrap py-32 text-center text-sm text-muted">Loading offer…</div>;

  const r = offer.result;
  // Remount stateful sections whenever the saved numbers change
  const version = JSON.stringify([offer.structure, offer.assumptions]);
  const meta = [offer.role, offer.structure.location].filter(Boolean).join(" · ");

  return (
    <>
      <section className="spotlight text-white">
        <div className="wrap pb-16 pt-14 sm:pb-20">
          <div className="flex items-center justify-between">
            <Link href="/" className="text-[11px] uppercase tracking-[0.22em] text-white/50 transition hover:text-white">
              ← All offers
            </Link>
            <div className="flex items-center gap-8">
              <Link href={`/compare?ids=${offer.id}`} className="link-cta text-white/70">
                Compare
              </Link>
              <button
                className="link-cta text-white/40 hover:text-white"
                onClick={async () => {
                  await api.deleteOffer(offer.id);
                  router.push("/");
                }}
              >
                Delete
              </button>
            </div>
          </div>
          <p className="rise eyebrow mt-16 !text-white/50">{meta || "Offer"}</p>
          <h1 className="rise-2 serif mt-4 text-4xl sm:text-6xl">{offer.structure.company ?? offer.label}</h1>
          <div className="rise-3 mt-16 grid gap-10 sm:grid-cols-[1.4fr_1fr] sm:items-end">
            <div>
              <p className="tabular text-[64px] leading-none tracking-[-0.03em] sm:text-[112px]" style={{ fontWeight: 200 }}>
                {inr(r.monthly_in_hand)}
              </p>
              <p className="mt-4 text-white/55">a month, in hand, out of a {lakh(r.structure.ctc)} CTC.</p>
              <p className="mt-2 text-xs text-white/35">Only this browser can see this offer.</p>
            </div>
            {offer.structure.joining_bonus > 0 && (
              <p className="text-sm text-white/55 sm:text-right">
                Year one with the joining bonus, after tax
                <span className="tabular mt-1 block text-2xl text-white">{inr(r.year_one_take_home)}</span>
              </p>
            )}
          </div>
        </div>
      </section>

      <div className="wrap space-y-24 pt-16">
        <div className="space-y-6">
          <StatRow r={r} />
          <Warnings items={r.warnings} />
        </div>

        <section className="grid gap-16 lg:grid-cols-2">
          <div>
            <p className="eyebrow">Composition</p>
            <h2 className="section-title mt-3">Where your CTC goes</h2>
            <p className="mt-2 mb-10 text-sm text-muted">Every rupee of the package: what you receive and what you don&apos;t.</p>
            <CtcDonut buckets={r.ctc_buckets} ctc={r.structure.ctc} />
          </div>
          <RegimePanel r={r} />
        </section>

        <Simulator key={`sim-${version}`} offer={offer} onSaved={setOffer} />

        <section className="grid gap-16 lg:grid-cols-[1.15fr_1fr]">
          <BreakdownEditor key={`bd-${version}`} offer={offer} onSaved={setOffer} />
          <div className="space-y-16">
            <Suggestions items={offer.suggestions} />
            <LetterNotes notes={offer.extraction_meta.notes} />
          </div>
        </section>

        <section className="grid gap-16 lg:grid-cols-2">
          <Explanation key={`ex-${version}`} offerId={offer.id} initial={offer.explanation} />
          <AskBox offerId={offer.id} />
        </section>
      </div>
    </>
  );
}
