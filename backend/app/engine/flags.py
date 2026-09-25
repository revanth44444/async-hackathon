"""Red flags in an offer, scored deterministically.

Every flag comes from a computed figure or a phrase in the letter itself, never from the model, so the score is
reproducible and each point deducted can be traced to a line of the offer.
"""
import re
from typing import Literal

from pydantic import BaseModel

from app.engine.calculator import inr
from app.engine.schemas import CalculationResult

Severity = Literal["high", "medium", "low"]
PENALTY: dict[Severity, int] = {"high": 20, "medium": 10, "low": 4}


class RedFlag(BaseModel):
    key: str
    title: str
    detail: str
    severity: Severity


class RedFlagReport(BaseModel):
    score: int  # 100 = nothing to worry about; lower = more red flags
    level: Literal["Low risk", "Some concerns", "High risk"]
    flags: list[RedFlag]


def _sentences(text: str) -> list[str]:
    return [x.strip() for x in re.split(r"\n|(?<![Rr]s)(?<!Pvt)(?<!Ltd)\.\s+", text or "") if x.strip()]


def _find(text: str, pattern: str) -> str | None:
    return next((s for s in _sentences(text) if re.search(pattern, s, re.I)), None)


def _notice_days(text: str) -> int | None:
    sentence = _find(text, r"notice")
    if not sentence:
        return None
    m = re.search(r"(\d+)\s*(days?|months?)", sentence, re.I)
    if not m:
        return None
    n = int(m.group(1))
    return n * 30 if m.group(2).lower().startswith("month") else n


def red_flags(r: CalculationResult, letter_text: str = "", notes: list[str] | None = None,
              estimated_split: bool = False) -> RedFlagReport:
    """`letter_text` is the offer letter (or empty for manual entries); `notes` are the extracted fine-print notes."""
    s = r.structure
    text = "\n".join([letter_text or "", *(notes or [])])
    flags: list[RedFlag] = []

    def add(key: str, severity: Severity, title: str, detail: str) -> None:
        flags.append(RedFlag(key=key, severity=severity, title=title, detail=detail))

    if s.ctc > 0 and s.variable_pay > 0:
        share = s.variable_pay / s.ctc
        if share >= 0.15:
            add("variable_share", "high" if share >= 0.25 else "medium", "Large variable component",
                f"{share:.0%} of the CTC ({inr(s.variable_pay)}) is variable and not guaranteed. "
                "Ask what share was actually paid out last year.")

    if s.esop_value > 0 and any(c.key == "esop_value" and c.in_ctc for c in r.components):
        add("esop_in_ctc", "medium", "Equity counted as salary",
            f"{inr(s.esop_value)} a year of the CTC is ESOPs/RSUs. It is not cash, and its value depends on the company.")

    if s.ctc > 0 and r.in_hand_pct_of_ctc < 0.70:
        add("low_cash_share", "medium", "Low share of CTC reaches your bank",
            f"Only {r.in_hand_pct_of_ctc:.0%} of the CTC arrives as take-home pay. The rest is tax, PF, benefits or non-cash.")

    if bond := _find(text, r"\bbond\b|minimum service|service agreement"):
        add("service_bond", "high", "Service bond", f"The letter says: “{bond[:180]}” Leaving early may cost you money.")

    if s.joining_bonus > 0 and (claw := _find(text, r"(joining|sign[- ]?on).*(recover|claw|repay|refund|return)|(recover|claw|repay|refund).*(joining|sign[- ]?on)")):
        add("joining_clawback", "medium", "Joining bonus can be clawed back",
            f"The letter says: “{claw[:180]}” Ask whether the repayment is pro-rated.")

    if s.retention_bonus > 0:
        when = f"after {s.retention_after_months:g} months" if s.retention_after_months > 0 else "only after a qualifying period"
        add("retention_conditional", "low", "Retention bonus is conditional",
            f"{inr(s.retention_bonus)} is paid {when}, and only if you are still employed. Leave earlier and you get none of it.")

    if (days := _notice_days(text)) is not None and days >= 60:
        add("notice_period", "medium" if days >= 90 else "low", f"{days}-day notice period",
            "A long notice period can delay your next move. Many employers accept 30 to 60 days.")

    if _find(text, r"non[- ]?compete|non[- ]?solicit"):
        add("non_compete", "medium", "Non-compete or non-solicit clause",
            "The letter restricts where you can work or whom you can approach after leaving. Ask for its duration and scope.")

    if s.gratuity > 0:
        add("gratuity_in_ctc", "low", "Gratuity is counted in the CTC",
            f"{inr(s.gratuity)} a year is paid only if you stay five years, but it inflates the headline CTC.")

    if estimated_split:
        add("no_breakup", "medium", "The letter doesn't itemise your salary",
            "Only a total was given, so the split here is an estimate. Ask HR for the full salary annexure.")

    if any("Components add up to" in w for w in r.warnings):
        add("ctc_mismatch", "medium", "Components don't match the stated CTC",
            "The itemised amounts don't add up to the CTC. Ask HR for a corrected breakup.")

    order = {"high": 0, "medium": 1, "low": 2}
    flags.sort(key=lambda f: order[f.severity])
    score = max(0, 100 - sum(PENALTY[f.severity] for f in flags))
    level = "Low risk" if score >= 80 else "Some concerns" if score >= 60 else "High risk"
    return RedFlagReport(score=score, level=level, flags=flags)
