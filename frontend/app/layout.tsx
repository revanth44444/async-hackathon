import type { Metadata } from "next";
import { Bodoni_Moda, Inter } from "next/font/google";
import Link from "next/link";
import { AiBadge } from "@/components/AiBadge";
import "./globals.css";

const inter = Inter({ variable: "--font-inter", subsets: ["latin"], weight: ["200", "300", "400"] });
const bodoni = Bodoni_Moda({ variable: "--font-bodoni", subsets: ["latin"], weight: ["400"], style: ["normal", "italic"] });

const SITE_URL = process.env.NEXT_PUBLIC_SITE_URL ?? "https://offerlens-sand.vercel.app";
const DESCRIPTION = "Upload an offer letter and see your real monthly in-hand salary, both tax regimes, explained line by line.";

export const metadata: Metadata = {
  metadataBase: new URL(SITE_URL),
  title: "OfferLens — know your real salary",
  description: DESCRIPTION,
  openGraph: {
    title: "OfferLens — your CTC isn't your salary",
    description: DESCRIPTION,
    url: SITE_URL,
    siteName: "OfferLens",
    type: "website",
    locale: "en_IN",
  },
  twitter: { card: "summary_large_image", title: "OfferLens — your CTC isn't your salary", description: DESCRIPTION },
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={`${inter.variable} ${bodoni.variable} h-full`}>
      <body className="flex min-h-full flex-col">
        <div className="bg-accent py-2 text-center print:hidden text-[10px] uppercase tracking-[0.24em] text-white/80">
          Salary estimates for FY 2025–26 · Indian income-tax rules
        </div>
        <header className="sticky top-0 z-30 print:hidden border-b border-line/70 bg-bg/80 backdrop-blur-xl">
          <div className="wrap flex h-16 items-center gap-5 sm:gap-10">
            <Link href="/" className="serif text-[15px] uppercase tracking-[0.24em] text-ink sm:text-[19px] sm:tracking-[0.32em]">
              OfferLens
            </Link>
            <nav className="flex items-center gap-5 text-[11px] uppercase tracking-[0.22em] text-muted sm:gap-8">
              <Link href="/" className="transition hover:text-ink">
                Analyze
              </Link>
              <Link href="/compare" className="transition hover:text-ink">
                Compare
              </Link>
            </nav>
            <div className="ml-auto flex items-center gap-6">
              <AiBadge />
            </div>
          </div>
        </header>
        <main className="flex-1">{children}</main>
        <footer className="mt-24 border-t border-line print:hidden">
          <div className="wrap flex flex-col items-start justify-between gap-6 py-12 sm:flex-row sm:items-end">
            <div>
              <p className="serif text-lg uppercase tracking-[0.32em]">OfferLens</p>
              <p className="mt-2 max-w-sm text-sm text-muted">
                AI reads the letter. A deterministic engine does the maths. Estimates only, not tax advice.
              </p>
            </div>
            <p className="text-[10px] uppercase tracking-[0.22em] text-muted">Made for the hackathon · 2026</p>
          </div>
        </footer>
      </body>
    </html>
  );
}
