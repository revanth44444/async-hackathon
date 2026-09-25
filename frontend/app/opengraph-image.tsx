import { ImageResponse } from "next/og";

export const alt = "OfferLens: your CTC isn't your salary. See what actually reaches your bank.";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

export default function OpengraphImage() {
  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          flexDirection: "column",
          justifyContent: "space-between",
          padding: "72px 80px",
          color: "white",
          background:
            "radial-gradient(ellipse 22% 60% at 50% 0%, rgba(255,255,255,0.18), transparent 70%), radial-gradient(ellipse 70% 45% at 50% 100%, rgba(15,35,64,0.7), transparent 70%), #000",
        }}
      >
        <div style={{ fontSize: 22, letterSpacing: 10, color: "rgba(255,255,255,0.7)" }}>OFFERLENS</div>
        <div style={{ display: "flex", flexDirection: "column" }}>
          <div style={{ fontSize: 88, lineHeight: 1.02, letterSpacing: -2 }}>Your CTC isn&apos;t</div>
          <div style={{ fontSize: 88, lineHeight: 1.02, letterSpacing: -2, color: "rgba(255,255,255,0.6)" }}>your salary.</div>
          <div style={{ marginTop: 36, fontSize: 28, color: "rgba(255,255,255,0.6)" }}>
            Upload an offer letter to see your real monthly in-hand pay, explained line by line.
          </div>
        </div>
        <div style={{ fontSize: 18, letterSpacing: 5, color: "rgba(255,255,255,0.45)" }}>
          FY 2025–26 · BOTH TAX REGIMES · PRIVATE TO YOUR BROWSER
        </div>
      </div>
    ),
    size,
  );
}
