"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { ArrowUpRight, X } from "lucide-react";
import { NewOffer } from "@/components/NewOffer";
import { api, type OfferSummary } from "@/lib/api";
import { inr, lakh } from "@/lib/format";

const STEPS = [
  { n: "01", title: "Reads the letter", text: "The PDF is parsed and AI maps every line to a component of your CTC." },
  { n: "02", title: "Exact arithmetic", text: "A deterministic engine applies FY 25–26 slabs, rebates, PF and professional tax." },
  { n: "03", title: "Simulate", text: "Change the hike, rent, bonus payout and regime, and watch your pay update live." },
  { n: "04", title: "Compare", text: "Put offers side by side on guaranteed cash, not headline numbers." },
];

export default function Home() {
  const [offers, setOffers] = useState<OfferSummary[] | null>(null);

  useEffect(() => {
    api.listOffers().then(setOffers, () => setOffers([]));
  }, []);

  async function remove(id: number) {
    await api.deleteOffer(id);
    setOffers((o) => o?.filter((x) => x.id !== id) ?? null);
  }

  return (
    <>
      {/* Hero — cinematic, dark, headline bottom-left */}
      <section className="spotlight relative -mt-px flex min-h-[78vh] items-end overflow-hidden text-white">
        <div className="wrap pb-16 pt-40 sm:pb-24">
          <p className="rise eyebrow !text-white/60">OfferLens</p>
          <h1 className="rise-2 serif mt-5 max-w-4xl text-[44px] leading-[1.02] sm:text-[84px]">
            Your CTC isn&apos;t
            <br />
            <span className="italic text-white/70">your salary.</span>
          </h1>
          <div className="rise-3 mt-10 flex flex-col gap-10 sm:flex-row sm:items-end sm:justify-between">
            <p className="max-w-md text-[17px] leading-relaxed text-white/60">
              Upload an offer letter to see what actually reaches your bank each month, under both tax regimes and
              explained line by line.
            </p>
            <div className="flex items-center gap-8">
              <a href="#start" className="rounded-full bg-white px-6 py-3 text-sm text-black transition hover:bg-white/85">
                Decode an offer
              </a>
              <Link href="/compare" className="link-cta text-white/80">
                Compare
              </Link>
            </div>
          </div>
        </div>
      </section>

      {/* Start */}
      <section id="start" className="wrap scroll-mt-20 pt-24 sm:pt-32">
        <div className="grid gap-16 lg:grid-cols-[1fr_1.15fr]">
          <div>
            <p className="eyebrow">Begin</p>
            <h2 className="serif mt-4 text-4xl leading-tight sm:text-5xl">Decode an offer</h2>
            <p className="mt-5 max-w-md text-muted">
              PDF, pasted text or just a CTC number. We&apos;ll handle the rest.
            </p>
            <ol className="mt-12 divide-y divide-line border-y border-line">
              {STEPS.map((s) => (
                <li key={s.n} className="flex gap-6 py-5">
                  <span className="tabular text-xs text-muted">{s.n}</span>
                  <div>
                    <p className="text-[15px] text-ink">{s.title}</p>
                    <p className="mt-1 text-sm text-muted">{s.text}</p>
                  </div>
                </li>
              ))}
            </ol>
          </div>
          <div className="lg:self-start">
            <NewOffer />
          </div>
        </div>
      </section>

      {/* Offers */}
      <section className="wrap pt-28">
        <div className="mb-10 flex items-end justify-between gap-4">
          <div>
            <p className="eyebrow">Library</p>
            <h2 className="serif mt-3 text-3xl sm:text-4xl">Your offers</h2>
            <p className="mt-2 text-sm text-muted">Shared demo space. Cleared automatically after every 50 uploads or comparisons.</p>
          </div>
          {offers && offers.length >= 2 && (
            <Link href="/compare" className="link-cta">
              Compare offers
            </Link>
          )}
        </div>
        {offers === null ? (
          <p className="text-sm text-muted">Loading…</p>
        ) : offers.length === 0 ? (
          <p className="border-t border-line pt-6 text-sm text-muted">Nothing here yet. Your decoded offers will appear here.</p>
        ) : (
          <div className="grid overflow-hidden rounded-[22px] bg-surface sm:grid-cols-2 lg:grid-cols-3" style={{ boxShadow: "inset 0 0 0 1px var(--border)" }}>
            {offers.map((o) => (
              <div
                key={o.id}
                className="group relative p-7 transition hover:bg-surface-2"
                style={{ boxShadow: "1px 0 0 var(--border), 0 1px 0 var(--border)" }}
              >
                <Link href={`/offers/${o.id}`} className="absolute inset-0" aria-label={`Open ${o.label}`} />
                <div className="flex items-start justify-between gap-3">
                  <p className="eyebrow truncate">{o.role ?? (o.source === "manual" ? "Manual entry" : "Offer letter")}</p>
                  <button
                    onClick={() => remove(o.id)}
                    className="relative z-10 -m-1 p-1 text-muted opacity-0 transition hover:text-bad group-hover:opacity-100"
                    aria-label="Delete offer"
                  >
                    <X size={14} strokeWidth={1.5} />
                  </button>
                </div>
                <p className="serif mt-3 truncate text-2xl">{o.company ?? o.label}</p>
                <p className="tabular mt-10 text-[34px] leading-none tracking-tight text-ink">{inr(o.monthly_in_hand)}</p>
                <div className="mt-3 flex items-center justify-between text-sm text-muted">
                  <span>per month in-hand · {lakh(o.ctc)} CTC</span>
                  <ArrowUpRight size={16} strokeWidth={1.25} className="transition group-hover:text-ink" />
                </div>
              </div>
            ))}
          </div>
        )}
      </section>
    </>
  );
}
