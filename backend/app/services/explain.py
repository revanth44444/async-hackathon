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


def _in_ctc(r: CalculationResult, key: str) -> bool:
    return next((c.in_ctc for c in r.components if c.key == key), False)


def rules(r: CalculationResult) -> list[str]:
    """Plain statements of the tax rules that apply, so the model doesn't improvise tax law."""
    s, a = r.structure, r.assumptions
    out = [
        f"Tax year FY 2025-26. Figures use the {r.selected_regime} regime; the {r.recommended_regime} regime costs less for this offer.",
        f"New regime: standard deduction {inr(STANDARD_DEDUCTION['new'])}. HRA is fully taxable. There is no HRA exemption, "
        "and 80C, 80D and home-loan deductions are not allowed. Only employer NPS (up to 14% of basic) is deductible.",
        f"Old regime: standard deduction {inr(STANDARD_DEDUCTION['old'])}. HRA is partly exempt only if you pay rent "
        "and claim it. The exempt part depends on rent paid, basic pay and the city.",
        "Whenever you mention HRA, name the regime: it is fully taxable under the new regime, but under the old regime "
        "part of it can be tax-free if you pay rent. Never call HRA simply 'tax-exempt' or 'fully taxable', and never "
        "say rent gives no tax benefit without adding that the old regime allows an HRA exemption.",
        "Monthly in-hand covers fixed pay only. Variable pay is paid yearly, so annual take-home is more than 12 times "
        "the monthly in-hand. Never say the annual figure 'translates to' or 'works out to' the monthly figure.",
    ]
    hra_ex = next((x.amount for x in r.regimes["old"].tax.exemptions if x.label.startswith("HRA")), 0)
    if s.hra > 0:
        out.append(
            f"With the rent entered ({inr(a.monthly_rent)} a month), the old-regime HRA exemption is {inr(hra_ex)}."
            if a.monthly_rent > 0
            else "No rent has been entered, so no HRA exemption is applied in either regime."
        )
    if s.meal_allowance > 0:
        out.append(f"Meal allowance is taxable in the new regime; up to {inr(MEAL_EXEMPTION_OLD)} a year is exempt in the old regime.")
    if s.variable_pay > 0:
        out.append(f"Variable pay is a target, not guaranteed. Figures assume {a.variable_payout_pct:.0f}% is paid out. "
                   "It is usually paid yearly, and usually forfeited if you leave before the payout date, unless the "
                   "letter says it is pro-rated. Never say leaving early does not affect it.")
    if s.gratuity > 0:
        out.append("Gratuity is paid only after 5 years of service. It is not part of monthly pay.")
    if s.joining_bonus > 0:
        where = "included in the stated CTC" if _in_ctc(r, "joining_bonus") else "outside the stated CTC"
        out.append(f"The joining bonus is a one-time payment in year one, {where}. It is not monthly pay and is taxed in the year it is paid. "
                   "Joining bonuses often must be repaid if you leave early: only say leaving early does not affect it "
                   "if the offer letter explicitly says so.")
    if s.retention_bonus > 0:
        when = f"after {s.retention_after_months:g} months of service" if s.retention_after_months > 0 else "after a qualifying period of service"
        out.append(f"The retention bonus of {inr(s.retention_bonus)} is not a joining bonus. It is paid only if you are still employed "
                   f"{when}. If you leave before then, you receive none of it. "
                   + ("It is included in year-one pay." if 0 < s.retention_after_months <= 12 else "It is not included in year-one pay."))
    if s.esop_value > 0:
        where = "included in the stated CTC" if _in_ctc(r, "esop_value") else "outside the stated CTC"
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
            {"name": c.label}
            | ({"one_time_amount": money(c.annual)} if c.category == "one_time" else {"per_year": money(c.annual)})
            | ({"per_month": inr(c.monthly)} if c.monthly is not None else {"note": "not paid monthly"})
            | ({"condition": c.description} if c.key in ("retention_bonus", "gratuity") else {})
            | ({} if c.in_ctc else {"ctc": "outside the stated CTC"})
            for c in r.components
        ],
        "monthly_in_hand_fixed_pay_only": inr(r.monthly_in_hand),
        "annual_take_home_including_variable_pay": money(r.annual_take_home),
        "year_one_take_home_including_one_time_bonuses_paid_in_year_one": money(r.year_one_take_home),
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


def answer_question(r: CalculationResult, question: str, raw_text: str | None, risks: list[str] | None = None) -> str:
    """`risks` are the offer's red flags (title and detail), so answers about leaving, switching jobs or
    joining a competitor can't skip a clause the page has already flagged."""
    context = _payload(r)
    if risks:
        context += "\n\nKNOWN RISKS IN THIS OFFER:\n" + "\n".join(f"- {x}" for x in risks)
    if raw_text:
        context += f"\n\nOFFER LETTER TEXT (for policy questions):\n{raw_text[:8000]}"
    try:
        text = verified_chat(
            [
                {"role": "system", "content": SYSTEM + " Answer in under 150 words. If the data can't answer it, say so. "
                 "If the question is about leaving, resigning, switching jobs or joining another company, address every "
                 "KNOWN RISK that could apply (clawbacks, bonds, notice period, non-compete, forfeited variable or "
                 "retention pay), and never say something is the only thing you lose."},
                {"role": "user", "content": f"{context}\n\nQUESTION: {question}"},
            ],
            allowed_amounts([r], context),
            temperature=0.2,
            max_tokens=600,
        )
    except AIUnavailable:
        return "AI answers are unavailable right now. The calculated breakdown on this page is still accurate."
    return text or "I couldn't answer that reliably from the calculated figures. The breakdown on this page has the exact numbers."


def tradeoffs(labelled: list[tuple[str, CalculationResult]]) -> str:
    """Per-offer facts on the risky and non-cash parts of each package, written from the numbers directly."""
    lines = ["### The trade-offs\n"]
    for label, r in labelled:
        s = r.structure
        parts = [f"{inr(r.monthly_in_hand)} a month guaranteed in hand"]
        parts.append(
            f"variable pay of {inr(s.variable_pay)}, {s.variable_pay / s.ctc:.0%} of CTC, not guaranteed"
            if s.variable_pay > 0 and s.ctc > 0 else "no variable pay"
        )
        if s.esop_value > 0:
            parts.append(f"ESOPs/RSUs of {inr(s.esop_value)} a year, not cash")
        if s.joining_bonus > 0:
            parts.append(f"a one-time joining bonus of {inr(s.joining_bonus)}")
        if s.retention_bonus > 0:
            when = f"after {s.retention_after_months:g} months" if s.retention_after_months > 0 else "later"
            parts.append(f"a retention bonus of {inr(s.retention_bonus)}, paid {when} only if you stay")
        lines.append(f"- {label}: {'; '.join(parts)}.")
    return "\n".join(lines)


def compare_verdict(labelled: list[tuple[str, CalculationResult]], winners: dict[str, str], suits: str) -> str:
    """Written entirely from computed figures. An AI version attached real amounts to the wrong offer
    (e.g. one offer's ESOPs to another), which amount verification can't catch, so none is used here."""
    return f"{tradeoffs(labelled)}\n\n{winners_summary(winners, suits)}"


def winners_summary(winners: dict[str, str], suits: str) -> str:
    """Who leads on what, plus the recommendation."""
    by_offer: dict[str, list[str]] = {}
    for metric, label in winners.items():
        by_offer.setdefault(label, []).append(metric[0].lower() + metric[1:])
    lines = ["### Where each offer leads\n"]
    lines += [f"- {label}: {'; '.join(metrics)}." for label, metrics in by_offer.items()]
    if len(by_offer) > 1:
        lines.append("\nNo single offer wins on everything.")
    lines += ["\n### Our recommendation\n", suits]
    return "\n".join(lines)
