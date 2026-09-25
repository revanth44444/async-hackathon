"""Payslip check: compare a real payslip with what the offer promised.

The model (or a keyword fallback) only reads the payslip into monthly line items. The comparison, the tolerance and
every finding are computed here, so the check is reproducible. Payslips are never stored.
"""
import logging
import re

from pydantic import BaseModel

from app.engine.calculator import inr
from app.engine.schemas import CalculationResult
from app.services.groq_client import AIUnavailable, chat_json

log = logging.getLogger(__name__)

EARNING_CATS = ["basic", "hra", "special_allowance", "lta", "meal_allowance", "other_allowances",
                "variable_pay", "one_time", "reimbursement"]
DEDUCTION_CATS = ["employee_pf", "professional_tax", "income_tax", "other"]

PROMPT = f"""You read Indian salary payslips. Return ONLY a JSON object:
{{
  "month": string|null,
  "paid_days": number|null, "month_days": number|null,
  "earnings": [{{"label": string, "amount": number, "category": string}}],
  "deductions": [{{"label": string, "amount": number, "category": string}}],
  "gross_earnings": number|null, "net_pay": number|null
}}
Rules:
- Amounts are THIS MONTH's amounts in INR as plain numbers. Ignore year-to-date (YTD) columns.
- earnings category: one of {", ".join(EARNING_CATS)}. Conveyance, internet, telephone and similar → other_allowances.
  Bonus, incentive, performance pay → variable_pay. Joining/sign-on/retention bonus, arrears → one_time.
- deductions category: one of {", ".join(DEDUCTION_CATS)}. EPF/PF → employee_pf. PT/professional tax →
  professional_tax. TDS/income tax → income_tax. Anything else → other.
- paid_days / month_days: days paid and days in the month if shown (e.g. "Paid days 30", "LOP 2"). Else null.
- Never invent numbers. Use null when unknown."""


class PayslipLine(BaseModel):
    label: str
    expected: float | None  # monthly amount the offer implies (pro-rated for a partial month)
    actual: float | None  # from the payslip
    difference: float | None  # actual - expected
    status: str  # "match" | "higher" | "lower" | "missing" | "extra" | "moved" | "info"
    note: str | None = None


class PayslipCheck(BaseModel):
    month: str | None
    prorated: float | None  # share of the month paid, when less than a full month
    lines: list[PayslipLine]
    one_time: list[str]  # one-time items on the payslip, left out of the comparison
    findings: list[str]
    verdict: str
    method: str  # "ai" | "heuristic"


def _num(v) -> float | None:
    try:
        return float(v) if v is not None and float(v) >= 0 else None
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------- reading the payslip

EARN_KEYS = [
    (r"\bbasic\b", "basic"), (r"\bhra\b|house rent", "hra"), (r"special|flexi", "special_allowance"),
    (r"\blta\b|leave travel", "lta"), (r"meal|food", "meal_allowance"),
    (r"joining|sign[- ]?on|retention|arrear", "one_time"), (r"bonus|incentive|variable|performance", "variable_pay"),
    (r"reimburse", "reimbursement"), (r"conveyance|allowance|internet|telephone", "other_allowances"),
]
DED_KEYS = [(r"\bpf\b|provident|epf", "employee_pf"), (r"professional tax|\bp\.?\s?t\b", "professional_tax"),
            (r"\btds\b|income tax", "income_tax")]
AMOUNT = re.compile(r"(\d[\d,]*(?:\.\d+)?)")


def _heuristic(text: str) -> dict:
    earnings, deductions = [], []
    data: dict = {"earnings": earnings, "deductions": deductions}
    for raw in text.splitlines():
        # "Basic 40,000 | Provident Fund 1,800" style rows: split side-by-side columns
        for cell in re.split(r"\s*\|\s*(?=[A-Za-z])", raw):
            low = cell.lower()
            nums = [float(x.replace(",", "")) for x in AMOUNT.findall(cell) if float(x.replace(",", "")) >= 1]
            if not nums:
                continue
            amt = nums[0]
            if re.search(r"net pay|take home|net salary", low):
                data["net_pay"] = amt
            elif re.search(r"gross", low):
                data["gross_earnings"] = amt
            elif re.search(r"paid days|days paid", low):
                data["paid_days"] = amt
            elif cat := next((c for p, c in DED_KEYS if re.search(p, low)), None):
                deductions.append({"label": cell.split(":")[0].strip()[:40], "amount": amt, "category": cat})
            elif cat := next((c for p, c in EARN_KEYS if re.search(p, low)), None):
                earnings.append({"label": cell.split(":")[0].strip()[:40], "amount": amt, "category": cat})
    return data


def read_payslip(text: str) -> tuple[dict, str]:
    try:
        data = chat_json([{"role": "system", "content": PROMPT},
                          {"role": "user", "content": f"Payslip text:\n\n{text[:12000]}"}], max_tokens=2000)
        if data.get("earnings") or data.get("net_pay"):
            return data, "ai"
    except AIUnavailable as exc:
        log.info("Payslip: falling back to keyword reading: %s", exc)
    return _heuristic(text), "heuristic"


# ---------------------------------------------------------------- comparison

def _tol(expected: float) -> float:
    return max(50.0, 0.015 * abs(expected))


def compare_payslip(r: CalculationResult, data: dict, method: str) -> PayslipCheck:
    s = r.structure
    earn: dict[str, float] = {}
    one_time: list[str] = []
    for e in data.get("earnings") or []:
        amt, cat = _num(e.get("amount")), e.get("category")
        if amt is None:
            continue
        if cat in ("one_time", "variable_pay", "reimbursement"):
            one_time.append(f"{e.get('label') or cat}: {inr(amt)}")
            earn[cat] = earn.get(cat, 0) + amt
        elif cat in EARNING_CATS:
            earn[cat] = earn.get(cat, 0) + amt
    ded: dict[str, float] = {}
    for d in data.get("deductions") or []:
        amt, cat = _num(d.get("amount")), d.get("category")
        if amt is not None and cat in DEDUCTION_CATS:
            ded[cat] = ded.get(cat, 0) + amt

    paid, days = _num(data.get("paid_days")), _num(data.get("month_days"))
    share = paid / days if paid and days and 0 < paid < days else None
    f = share or 1.0

    lines: list[PayslipLine] = []
    findings: list[str] = []

    def line(label: str, expected: float, actual: float | None, *, higher: str | None = None,
             lower: str | None = None, missing: str | None = None) -> None:
        exp = round(expected * f, 2)
        if actual is None:
            if exp <= 0:
                return
            lines.append(PayslipLine(label=label, expected=exp, actual=None, difference=None, status="missing", note=missing))
            if missing:
                findings.append(missing)
            return
        diff = round(actual - exp, 2)
        if abs(diff) <= _tol(exp):
            status, note = "match", None
        elif diff > 0:
            status, note = ("extra" if exp <= 0 else "higher"), higher
        else:
            status, note = "lower", lower
        if note:
            note = note.format(diff=inr(abs(diff)))
            findings.append(note)
        lines.append(PayslipLine(label=label, expected=exp, actual=actual, difference=diff, status=status, note=note))

    line("Basic salary", s.basic / 12, earn.get("basic"),
         lower="Basic is {diff} a month lower than the offer. PF, gratuity and HRA exemption all depend on it, so ask HR.",
         higher="Basic is {diff} a month higher than the offer.",
         missing="No basic salary on the payslip. Ask HR how your pay is structured.")
    line("House rent allowance", s.hra / 12, earn.get("hra"),
         lower="HRA is {diff} a month lower than the offer.",
         missing="HRA is missing from the payslip, though the offer includes it. Ask HR.")
    line("Special allowance", s.special_allowance / 12, earn.get("special_allowance"),
         lower="Special allowance is {diff} a month lower than the offer. It may have been moved into another component.")
    other_exp = (s.lta + s.meal_allowance + s.other_allowances) / 12
    other_act = sum(earn.get(k, 0) for k in ("lta", "meal_allowance", "other_allowances")) or None
    line("Other allowances", other_exp, other_act)

    fixed_act = sum(earn.get(k, 0) for k in ("basic", "hra", "special_allowance", "lta", "meal_allowance", "other_allowances"))
    line("Fixed pay (before deductions)", r.fixed_cash / 12, fixed_act or None,
         lower="Your fixed pay is {diff} a month lower than the offer promised. Raise this with HR first.",
         higher="Your fixed pay is {diff} a month higher than the offer.")
    line("Employee PF", r.employee_pf / 12, ded.get("employee_pf"),
         higher="{diff} a month more PF is deducted than the offer assumed (for example on full basic instead of the "
                "₹1,800 cap). It's still your savings, but less reaches your bank. You can ask HR to cap it.",
         lower="{diff} a month less PF is deducted than the offer assumed.")
    line("Professional tax", r.professional_tax / 12, ded.get("professional_tax"))
    expected_tds = r.regimes[r.selected_regime].tax_on_fixed / 12
    line("Income tax (TDS)", expected_tds, ded.get("income_tax", 0.0 if expected_tds <= 0 else None),
         higher="{diff} a month more tax is deducted than expected. Tell HR your tax regime and submit any rent or "
                "investment proofs. Extra tax deducted comes back as a refund when you file your return.",
         lower="{diff} a month less tax is deducted than expected, so you may owe tax when you file. Check which regime HR is using.")

    net = _num(data.get("net_pay"))
    if net is not None:
        extra = sum(earn.get(k, 0) for k in ("one_time", "variable_pay", "reimbursement"))
        # One-time pay is taxed too, so compare net pay only when there's none on this payslip
        if extra <= 0:
            line("Net pay (in hand)", r.monthly_in_hand, net,
                 lower="You received {diff} a month less than the offer's in-hand estimate.",
                 higher="You received {diff} a month more than the offer's in-hand estimate.")
        else:
            lines.append(PayslipLine(label="Net pay (in hand)", expected=None, actual=net, difference=None, status="info",
                                     note="Includes one-time pay, so it isn't compared with the monthly estimate."))

    # HRA folded into special allowance: same fixed pay, just restructured. Not a shortfall, but it matters for
    # the old-regime HRA exemption, so say that instead of "HRA is missing"
    by = {x.label: x for x in lines}
    hra, special, fixed_line = by.get("House rent allowance"), by.get("Special allowance"), by.get("Fixed pay (before deductions)")
    if (hra and special and fixed_line and hra.status in ("missing", "lower") and special.status == "higher"
            and fixed_line.status == "match"):
        shortfall = (hra.expected or 0) - (hra.actual or 0)
        if abs((special.difference or 0) - shortfall) <= _tol(shortfall):
            findings[:] = [x for x in findings if x != hra.note]
            hra.status = special.status = "moved"
            hra.note = special.note = None
            findings.insert(0, f"HRA of {inr(shortfall)} a month has been moved into special allowance, so your fixed pay "
                               "still matches the offer. If you pay rent and use the old tax regime, ask HR to show HRA "
                               "separately so you can claim the HRA exemption.")

    # Explain a lower net pay by the extra PF when that accounts for it
    net_line, pf_line = by.get("Net pay (in hand)"), by.get("Employee PF")
    if (net_line and pf_line and net_line.status == "lower" and pf_line.status == "higher"
            and abs(-(net_line.difference or 0) - (pf_line.difference or 0)) <= _tol(net_line.expected or 0)):
        i = findings.index(net_line.note) if net_line.note in findings else None
        net_line.note = (f"You received {inr(-(net_line.difference or 0))} a month less than the offer's in-hand estimate, "
                         "and the extra PF deduction accounts for almost all of it.")
        if i is not None:
            findings[i] = net_line.note

    if share:
        findings.insert(0, f"This payslip covers {paid:g} of {days:g} days, so the offer figures are pro-rated to match.")
    problems = [x for x in lines if x.status in ("lower", "missing")]
    if not lines:
        verdict = "We couldn't find salary figures on this payslip. Try a clearer copy, or paste the text."
    elif not problems and not any(x.status in ("higher", "extra") for x in lines):
        verdict = "Your payslip matches the offer."
    elif not problems:
        verdict = "Your payslip is in line with the offer, with a few differences worth a look."
    else:
        n = len(problems)
        verdict = f"{n} item{'s' if n > 1 else ''} on your payslip {'are' if n > 1 else 'is'} below what the offer promised."
    return PayslipCheck(month=data.get("month"), prorated=round(share, 4) if share else None, lines=lines,
                        one_time=one_time, findings=findings, verdict=verdict, method=method)
