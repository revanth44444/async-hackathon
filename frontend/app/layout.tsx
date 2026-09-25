import type { Metadata } from "next";
import { Bodoni_Moda, Inter } from "next/font/google";
import Link from "next/link";
import { AiBadge } from "@/components/AiBadge";
import "./globals.css";

const inter = Inter({ variable: "--font-inter", subsets: ["latin"], weight: ["200", "300", "400"] });
const bodoni = Bodoni_Moda({ variable: "--font-bodoni", subsets: ["latin"], weight: ["400"], style: ["normal", "italic"] });

export const metadata: Metadata = {
  title: "OfferLens — know your real salary",
  description: "Upload an offer letter, see your real in-hand salary, compare offers and simulate what-ifs.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={`${inter.variable} ${bodoni.variable} h-full`}>
      <body className="flex min-h-full flex-col">
        <div className="bg-accent py-2 text-center text-[10px] uppercase tracking-[0.24em] text-white/80">
          Salary estimates for FY 2025–26 · Indian income-tax rules
        </div>
        <header className="sticky top-0 z-30 border-b border-line/70 bg-bg/80 backdrop-blur-xl">
          <div className="wrap flex h-16 items-center gap-10">
            <Link href="/" className="serif text-[19px] uppercase tracking-[0.32em] text-ink">
              OfferLens
            </Link>
            <nav className="hidden items-center gap-8 text-[11px] uppercase tracking-[0.22em] text-muted sm:flex">
              <Link href="/" className="transition hover:text-ink">
                Analyze
              </Link>
              <Link href="/compare" className="transition hover:text-ink">
                Compare
              </Link>
            </nav>
            <div className="ml-auto flex items-center gap-6">
              <Link href="/compare" className="text-[11px] uppercase tracking-[0.22em] text-muted sm:hidden">
                Compare
              </Link>
              <AiBadge />
            </div>
          </div>
        </header>
        <main className="flex-1">{children}</main>
        <footer className="mt-24 border-t border-line">
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
