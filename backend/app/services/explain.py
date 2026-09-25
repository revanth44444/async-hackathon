"""Plain-language explanations.

The LLM never does arithmetic: it receives every figure already calculated *and formatted*, plus the tax
rules that apply to this offer. Every ₹ amount in its reply is then checked against the figures it was
given; replies with unsupported amounts are retried once and otherwise replaced by a deterministic text.
"""
import json
import logging
import re

from app.engine.calculator import MEAL_EXEMPTION_OLD, inr
from app.engine.schemas import CalculationResult
from app.engine.tax import STANDARD_DEDUCTION
from app.services.groq_client import AIUnavailable, chat

log = logging.getLogger(__name__)


def lakh(v: float) -> str:
    """₹16.21L / ₹1.2Cr, matching the frontend's compact notation."""
    if abs(v) >= 1e7:
        return f"₹{v / 1e7:.2f}".rstrip("0").rstrip(".") + "Cr"
    return f"₹{v / 1e5:.2f}".rstrip("0").rstrip(".") + "L"


def money(v: float) -> str:
    """Exact rupees, plus the lakh form for large amounts, e.g. '₹16,21,300 (₹16.21L)'."""
    return f"{inr(v)} ({lakh(v)})" if abs(v) >= 1e5 else inr(v)


def _inclusion(r: CalculationResult) -> tuple[bool, bool]:
    items = {c.key: c.in_ctc for c in r.components}
    return items.get("joining_bonus", False), items.get("esop_value", False)


def rules(r: CalculationResult) -> list[str]:
    """Plain statements of the tax rules that apply, so the model doesn't improvise tax law."""
    s, a = r.structure, r.assumptions
    joining_in, esop_in = _inclusion(r)
    out = [
        f"Tax year FY 2025-26. Figures use the {r.selected_regime} regime; the {r.recommended_regime} regime costs less for this offer.",
        f"New regime: standard deduction {inr(STANDARD_DEDUCTION['new'])}. HRA is fully taxable. There is no HRA exemption, "
        "and 80C, 80D and home-loan deductions are not allowed. Only employer NPS (up to 14% of basic) is deductible.",
        f"Old regime: standard deduction {inr(STANDARD_DEDUCTION['old'])}. HRA is partly exempt only if you pay rent "
        "and claim it. The exempt part depends on rent paid, basic pay and the city.",
    ]
    hra_ex = next((x.amount for x in r.regimes["old"].tax.exemptions if x.label.startswith("HRA")), 0)
    if s.hra > 0:
        out.append(
            f"With the rent entered (₹{a.monthly_rent:,.0f} a month), the old-regime HRA exemption is {inr(hra_ex)}."
            if a.monthly_rent > 0
            else "No rent has been entered, so no HRA exemption is applied in either regime."
        )
    if s.meal_allowance > 0:
        out.append(f"Meal allowance is taxable in the new regime; up to {inr(MEAL_EXEMPTION_OLD)} a year is exempt in the old regime.")
    if s.variable_pay > 0:
        out.append(f"Variable pay is a target, not guaranteed. Figures assume {a.variable_payout_pct:.0f}% is paid out.")
    if s.gratuity > 0:
        out.append("Gratuity is paid only after 5 years of service. It is not part of monthly pay.")
    if s.joining_bonus > 0:
        where = "included in the stated CTC" if joining_in else "outside the stated CTC"
        out.append(f"The joining bonus is a one-time payment in year one, {where}. It is not monthly pay and is taxed in the year it is paid.")
    if s.esop_value > 0:
        where = "included in the stated CTC" if esop_in else "outside the stated CTC"
        out.append(f"ESOPs/RSUs are not cash ({where}). They are taxed only when exercised or vested.")
    if s.employer_pf > 0 or r.employee_pf > 0:
        out.append("Employee and employer PF go into your PF account, not your bank account.")
    return out


def facts(r: CalculationResult) -> dict:
    """Every figure the model may use, pre-formatted. Nothing here needs further arithmetic."""
    sel = r.regimes[r.selected_regime]
    return {
        "company": r.structure.company,
        "role": r.structure.role,
        "stated_ctc": money(r.structure.ctc),
        "components": [
            {"name": c.label, "per_year": money(c.annual)}
            | ({"per_month": inr(c.monthly)} if c.monthly is not None else {"note": "not paid monthly"})
            | ({} if c.in_ctc else {"ctc": "outside the stated CTC"})
            for c in r.components
        ],
        "monthly_in_hand": inr(r.monthly_in_hand),
        "annual_take_home": money(r.annual_take_home),
        "year_one_take_home_including_joining_bonus": money(r.year_one_take_home),
        "share_of_ctc_reaching_bank": f"{r.in_hand_pct_of_ctc * 100:.0f}%",
        "fixed_pay_before_deductions_per_year": money(r.fixed_cash),
        "variable_pay_target": money(r.structure.variable_pay),
        "variable_payout_assumed": f"{r.assumptions.variable_payout_pct:.0f}%",
        "employee_pf_per_year": money(r.employee_pf),
        "retirement_savings_per_year_pf_and_nps_both_sides": money(r.employee_pf + r.structure.employer_pf + r.structure.employer_nps),
        "professional_tax_per_year": inr(r.professional_tax),
        "income_tax_new_regime_per_year": money(r.regimes["new"].tax.total_tax),
        "income_tax_old_regime_per_year": money(r.regimes["old"].tax.total_tax),
        "regime_used": r.selected_regime,
        "recommended_regime": r.recommended_regime,
        "tax_saving_with_recommended_regime": money(r.regime_savings),
        "effective_tax_rate": f"{sel.tax.effective_rate * 100:.1f}%",
        "where_the_ctc_goes": {b.label: money(b.amount) for b in r.ctc_buckets},
        "warnings": r.warnings,
    }


SYSTEM = """You are a calm, discreet compensation adviser helping an Indian job seeker understand an offer.
Every figure is pre-calculated and pre-formatted for you. Copy rupee amounts exactly as written.
Never add, subtract, multiply, divide, round, convert or estimate any number. Never write a rupee amount that is not in the data.
If a figure you want is not provided, describe it in words instead.
Tax statements must follow the RULES given. Do not state any other tax rule.
Style: understated and editorial, like a private banker's note. Short paragraphs and simple bullet lists only.
Use "###" for section headings. No tables, no emojis, no exclamation marks, no bold or italics.
Never mention JSON, field names, data, rules lists or the engine. Speak directly to the reader as "you"."""

# ---------------------------------------------------------------- amount verification

_AMOUNT = re.compile(r"₹\s?(\d[\d,]*(?:\.\d+)?)\s*(crores?|cr\b|lakhs?|lacs?|l\b|k\b)?", re.I)


def _parse(match: re.Match) -> tuple[float, float]:
    """(value, tolerance) for a ₹ amount; tolerance reflects the precision it was written with."""
    num, unit = match.group(1).replace(",", ""), (match.group(2) or "").lower()
    decimals = len(num.split(".")[1]) if "." in num else 0
    mult = 1e7 if unit.startswith("cr") else 1e5 if unit.startswith(("l", "lakh", "lac")) else 1e3 if unit == "k" else 1
    return float(num) * mult, max(1.0, 0.5 * 10 ** -decimals * mult)


def _numbers(obj) -> list[float]:
    if isinstance(obj, bool):
        return []
    if isinstance(obj, (int, float)):
        return [float(obj)] if obj > 0 else []
    if isinstance(obj, dict):
        return [n for v in obj.values() for n in _numbers(v)]
    if isinstance(obj, (list, tuple)):
        return [n for v in obj for n in _numbers(v)]
    return []


def allowed_amounts(results: list[CalculationResult], *texts: str) -> list[float]:
    """Every figure the model was shown: raw engine numbers plus any ₹ amount in the prompt/letter."""
    values = [n for r in results for n in _numbers(r.model_dump())]
    for t in texts:
        values += [_parse(m)[0] for m in _AMOUNT.finditer(t or "")]
    return values


def unsupported_amounts(answer: str, allowed: list[float]) -> list[str]:
    bad = []
    for m in _AMOUNT.finditer(answer):
        value, tol = _parse(m)
        if not any(abs(value - a) <= tol for a in allowed):
            bad.append(m.group(0).strip())
    return bad


def verified_chat(messages: list[dict], allowed: list[float], **kw) -> str | None:
    """Ask the model; if it writes an amount we didn't give it, retry once, then give up (None)."""
    answer = chat(messages, **kw)
    bad = unsupported_amounts(answer, allowed)
    if not bad:
        return answer
    log.warning("AI used unsupported amounts %s; retrying", bad)
    retry = messages + [
        {"role": "assistant", "content": answer},
        {
            "role": "user",
            "content": f"These amounts do not appear in the data: {', '.join(bad)}. Rewrite the whole answer using "
            "only amounts copied exactly from the data, or describe them in words.",
        },
    ]
    answer = chat(retry, **kw)
    bad = unsupported_amounts(answer, allowed)
    if bad:
        log.warning("AI still used unsupported amounts %s; using fallback", bad)
        return None
    return answer


# ---------------------------------------------------------------- public API


def _template(r: CalculationResult) -> str:
    s = r.structure
    lines = [
        "### What you'll actually receive\n",
        f"Your CTC is {money(s.ctc)}, and your estimated monthly in-hand pay is {inr(r.monthly_in_hand)}. "
        f"Over a year that comes to {money(r.annual_take_home)}, which is {r.in_hand_pct_of_ctc:.0%} of the CTC. "
        f"This assumes {r.assumptions.variable_payout_pct:.0f}% of the variable pay is paid out.\n",
        "### Where the rest of the CTC goes\n",
    ]
    lines += [f"- {b.label}: {money(b.amount)}" for b in r.ctc_buckets]
    lines += [
        "\n### Tax regime\n",
        f"New regime tax: {money(r.regimes['new'].tax.total_tax)}. Old regime tax: {money(r.regimes['old'].tax.total_tax)}. "
        f"The {r.recommended_regime} regime costs less with your current inputs.",
        "",
        *[f"- {x}" for x in rules(r)],
    ]
    if r.warnings:
        lines += ["\n### Check these\n"] + [f"- {w}" for w in r.warnings]
    return "\n".join(lines)


def _payload(r: CalculationResult) -> str:
    return f"DATA:\n{json.dumps(facts(r), ensure_ascii=False)}\n\nRULES:\n" + "\n".join(f"- {x}" for x in rules(r))


def explain_offer(r: CalculationResult, notes: list[str] | None = None) -> tuple[str, str]:
    prompt = (
        "Explain this offer to the candidate in 5 short sections: "
        "1) In-hand vs CTC in one line, 2) What each component means for them (group non-cash items), "
        "3) Why tax is what it is and which regime to pick, 4) Red flags or things to negotiate or ask HR "
        "(e.g. high variable share, gratuity in CTC, clawbacks), 5) One-line bottom line.\n\n"
        f"{_payload(r)}\n\nOFFER LETTER NOTES:\n{json.dumps(notes or [], ensure_ascii=False)}"
    )
    try:
        text = verified_chat(
            [{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}],
            allowed_amounts([r], prompt),
            temperature=0.2,
        )
    except AIUnavailable:
        text = None
    return (text, "ai") if text else (_template(r), "template")


def answer_question(r: CalculationResult, question: str, raw_text: str | None) -> str:
    context = _payload(r)
    if raw_text:
        context += f"\n\nOFFER LETTER TEXT (for policy questions):\n{raw_text[:8000]}"
    try:
        text = verified_chat(
            [
                {"role": "system", "content": SYSTEM + " Answer in under 150 words. If the data can't answer it, say so."},
                {"role": "user", "content": f"{context}\n\nQUESTION: {question}"},
            ],
            allowed_amounts([r], context),
            temperature=0.2,
            max_tokens=600,
        )
    except AIUnavailable:
        return "AI answers are unavailable right now. The calculated breakdown on this page is still accurate."
    return text or "I couldn't answer that reliably from the calculated figures. The breakdown on this page has the exact numbers."


def compare_verdict(labelled: list[tuple[str, CalculationResult]], winners: dict[str, str]) -> str | None:
    """`winners` maps each metric to the offer that leads on it (decided in Python, not by the model)."""
    data = {label: facts(r) for label, r in labelled}
    offer_rules = {label: rules(r) for label, r in labelled}
    prompt = (
        "Compare these offers for the candidate. Focus on guaranteed monthly in-hand pay, variable risk, "
        "long-term and non-cash value, and one-time bonuses. The WINNERS below are final. Never say an offer leads "
        "on a measure it does not win. If different offers win different measures, say so plainly and explain "
        "the trade-off. End with which offer suits someone who values certainty and which suits someone "
        "comfortable with variable pay. Max 200 words.\n\n"
        f"WINNERS:\n{json.dumps(winners, ensure_ascii=False)}\n\nDATA:\n{json.dumps(data, ensure_ascii=False)}\n\n"
        f"RULES:\n{json.dumps(offer_rules, ensure_ascii=False)}"
    )
    try:
        return verified_chat(
            [{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}],
            allowed_amounts([r for _, r in labelled], prompt),
            temperature=0.2,
            max_tokens=800,
        )
    except AIUnavailable:
        return None


def winners_summary(winners: dict[str, str]) -> str:
    """Deterministic verdict used when the AI is unavailable or fails verification."""
    by_offer: dict[str, list[str]] = {}
    for metric, label in winners.items():
        by_offer.setdefault(label, []).append(metric[0].lower() + metric[1:])
    lines = ["### Where each offer leads\n"]
    lines += [f"- {label}: {'; '.join(metrics)}." for label, metrics in by_offer.items()]
    if len(by_offer) > 1:
        lines.append(
            "\nNo single offer wins on everything. If certainty matters most, weigh guaranteed monthly in-hand and fixed "
            "pay. If you are comfortable with performance-linked pay, weigh the annual take-home with variable pay."
        )
    return "\n".join(lines)
