"""Plain-language explanations. The LLM receives numbers already computed by the engine and is told
not to calculate; a deterministic template is used when Groq is unavailable."""
import json

from app.engine.calculator import inr
from app.engine.schemas import CalculationResult
from app.services.groq_client import AIUnavailable, chat


def facts(r: CalculationResult) -> dict:
    sel = r.regimes[r.selected_regime]
    return {
        "company": r.structure.company,
        "role": r.structure.role,
        "ctc": r.structure.ctc,
        "components_annual": {c.label: c.annual for c in r.components},
        "fixed_cash_annual": r.fixed_cash,
        "variable_target": r.structure.variable_pay,
        "variable_payout_assumed_pct": r.assumptions.variable_payout_pct,
        "monthly_in_hand": r.monthly_in_hand,
        "annual_take_home": r.annual_take_home,
        "year_one_take_home_incl_joining_bonus": r.year_one_take_home,
        "in_hand_pct_of_ctc": round(r.in_hand_pct_of_ctc * 100, 1),
        "employee_pf_annual": r.employee_pf,
        "professional_tax_annual": r.professional_tax,
        "regime_used": r.selected_regime,
        "tax_new_regime": r.regimes["new"].tax.total_tax,
        "tax_old_regime": r.regimes["old"].tax.total_tax,
        "recommended_regime": r.recommended_regime,
        "effective_tax_rate_pct": round(sel.tax.effective_rate * 100, 1),
        "marginal_rate_pct": round(sel.tax.marginal_rate * 100),
        "ctc_split": {b.label: b.amount for b in r.ctc_buckets},
        "warnings": r.warnings,
    }


SYSTEM = """You are a calm, discreet compensation adviser helping an Indian job seeker understand an offer.
All numbers are pre-computed by a verified tax engine and given to you as data. Use ONLY those numbers.
Never calculate new figures or estimate anything not given. Format rupees in Indian style (₹12,34,567 or ₹12.3L).
Style: understated and editorial, like a private banker's note. Short paragraphs and simple bullet lists only.
Use "###" for section headings. No tables, no emojis, no exclamation marks, no bold or italics.
Never mention JSON, field names, data, or the engine. Speak directly to the reader as "you"."""


def _template(r: CalculationResult) -> str:
    s = r.structure
    lines = [
        f"### What you'll actually receive\n",
        f"Your CTC is **{inr(s.ctc)}**, but your estimated monthly in-hand pay is **{inr(r.monthly_in_hand)}**. "
        f"Over a year that comes to **{inr(r.annual_take_home)}** ({r.in_hand_pct_of_ctc:.0%} of CTC), "
        f"assuming {r.assumptions.variable_payout_pct:.0f}% of the variable pay is paid out.\n",
        "### Where the rest of the CTC goes\n",
    ]
    lines += [f"- **{b.label}**: {inr(b.amount)}" for b in r.ctc_buckets]
    lines += [
        "\n### Tax regime\n",
        f"New regime tax: {inr(r.regimes['new'].tax.total_tax)} · Old regime tax: {inr(r.regimes['old'].tax.total_tax)}. "
        f"The **{r.recommended_regime} regime** is cheaper by {inr(r.regime_savings)} with your current inputs.",
    ]
    if r.warnings:
        lines += ["\n### Check these\n"] + [f"- {w}" for w in r.warnings]
    return "\n".join(lines)


def explain_offer(r: CalculationResult, notes: list[str] | None = None) -> tuple[str, str]:
    prompt = (
        "Explain this offer to the candidate in 5 short sections: "
        "1) In-hand vs CTC in one line, 2) What each component means for them (group non-cash items), "
        "3) Why tax is what it is and which regime to pick, 4) Red flags or things to negotiate or ask HR "
        "(e.g. high variable share, gratuity in CTC, clawbacks), 5) One-line bottom line.\n\n"
        f"DATA:\n{json.dumps(facts(r))}\n\nOFFER LETTER NOTES:\n{json.dumps(notes or [])}"
    )
    try:
        return chat([{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}], temperature=0.3), "ai"
    except AIUnavailable:
        return _template(r), "template"


def answer_question(r: CalculationResult, question: str, raw_text: str | None) -> str:
    context = f"DATA:\n{json.dumps(facts(r))}"
    if raw_text:
        context += f"\n\nOFFER LETTER TEXT (for policy questions):\n{raw_text[:8000]}"
    try:
        return chat(
            [
                {"role": "system", "content": SYSTEM + " Answer in under 150 words. If the data can't answer it, say so."},
                {"role": "user", "content": f"{context}\n\nQUESTION: {question}"},
            ],
            temperature=0.3,
            max_tokens=600,
        )
    except AIUnavailable:
        return "AI answers need a `GROQ_API_KEY` on the backend. The calculated breakdown above is still accurate."


def compare_verdict(labelled: list[tuple[str, CalculationResult]]) -> str | None:
    data = {label: facts(r) for label, r in labelled}
    try:
        return chat(
            [
                {"role": "system", "content": SYSTEM},
                {
                    "role": "user",
                    "content": "Compare these offers for the candidate. Focus on guaranteed monthly in-hand pay, variable risk, "
                    "long-term/non-cash value and one-time bonuses. End with a clear recommendation and what would change it. "
                    f"Max 200 words.\n\n{json.dumps(data)}",
                },
            ],
            temperature=0.3,
            max_tokens=800,
        )
    except AIUnavailable:
        return None
