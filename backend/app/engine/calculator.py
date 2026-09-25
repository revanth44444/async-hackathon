"""Deterministic CTC → take-home calculator. Same input always yields the same output."""
from app.engine import tax as rules
from app.engine.schemas import (
    Adjustment,
    Assumptions,
    Bucket,
    CalculationResult,
    LineItem,
    Regime,
    RegimeResult,
    SalaryStructure,
    TaxBreakdown,
)

PF_WAGE_CEILING = 15_000 * 12
MEAL_EXEMPTION_OLD = 26_400  # ₹50/meal × 2 meals × 22 days × 12 months
LIMIT_80C = 150_000
LIMIT_80D = 100_000
LIMIT_24B = 200_000
LIMIT_80CCD1B = 50_000

COMPONENTS: list[tuple[str, str, str, str]] = [
    ("basic", "Basic Salary", "fixed", "Core fixed pay. PF, gratuity and HRA exemption are all calculated from this."),
    ("hra", "House Rent Allowance", "fixed", "Cash allowance for rent. Partly tax-exempt under the old regime if you pay rent."),
    ("special_allowance", "Special Allowance", "fixed", "Balancing fixed allowance. Fully taxable."),
    ("lta", "Leave Travel Allowance", "fixed", "Paid monthly or on claim. Exempt under the old regime only for actual domestic travel."),
    ("meal_allowance", "Meal / Food Allowance", "fixed", "Food coupons or card. Up to ₹26,400/yr exempt under the old regime."),
    ("other_allowances", "Other Allowances", "fixed", "Conveyance, internet, etc. Taxable unless reimbursed against bills."),
    ("employer_pf", "Employer PF", "retirement", "Employer's 12% EPF contribution. Goes to your PF account, not your bank."),
    ("gratuity", "Gratuity", "retirement", "Paid only if you stay 5+ years. Included in CTC but not in monthly pay."),
    ("employer_nps", "Employer NPS", "retirement", "Employer's NPS contribution. Tax-deductible up to 14% of basic (new regime)."),
    ("insurance", "Insurance & Benefits", "benefit", "Health/term insurance premiums paid by the employer. Non-cash."),
    ("variable_pay", "Variable / Performance Pay", "variable", "Target bonus. Actual payout depends on performance and is usually paid yearly or quarterly."),
    ("joining_bonus", "Joining Bonus", "one_time", "One-time payment, usually with a clawback if you leave early."),
    ("esop_value", "ESOPs / RSUs (annual)", "equity", "Equity value. Not cash, and taxed only when exercised or vested."),
]


def inr(v: float) -> str:
    """Indian digit grouping: 1234567 → ₹12,34,567."""
    n = int(round(v))
    sign, n = ("-" if n < 0 else ""), abs(n)
    s = str(n)
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        head = ",".join([head[max(0, i - 2):i] for i in range(len(head), 0, -2)][::-1])
        s = f"{head},{tail}"
    return f"{sign}₹{s}"


FIXED_KEYS = ("basic", "hra", "special_allowance", "lta", "meal_allowance", "other_allowances")
MIN_PLAUSIBLE_ANNUAL_CTC = 1_00_000  # below this, a lone "CTC" figure is almost certainly monthly


def _fixed(s: SalaryStructure) -> float:
    return sum(getattr(s, k) for k in FIXED_KEYS)


def _typical_split(fixed_pay: float) -> dict[str, float]:
    """Typical Indian structure for a fixed-pay amount: basic 40%, HRA half of basic, rest special allowance."""
    basic = round(fixed_pay * 0.40)
    hra = round(basic * 0.50)
    return {"basic": basic, "hra": hra, "special_allowance": round(fixed_pay - basic - hra)}


def complete_structure(s: SalaryStructure, stated_gross: float = 0.0) -> tuple[SalaryStructure, list[dict]]:
    """Make an incomplete letter calculable instead of producing ₹0.

    Handles, in order: a monthly CTC written without saying so, a CTC with no breakup, a gross salary with no
    CTC, and a partial breakup that leaves part of the CTC unaccounted for. Every assumption is returned as an
    estimate record so the UI and AI can say exactly what was guessed.
    """
    estimates: list[dict] = []
    s = s.model_copy()
    fixed = _fixed(s)

    if 0 < s.ctc < MIN_PLAUSIBLE_ANNUAL_CTC and fixed <= 0:
        estimates.append({"kind": "monthly_ctc", "amount": s.ctc * 12,
                          "message": f"The CTC of {inr(s.ctc)} looks like a monthly figure, so we used {inr(s.ctc * 12)} a year."})
        s.ctc *= 12
    if 0 < stated_gross < MIN_PLAUSIBLE_ANNUAL_CTC:
        stated_gross *= 12

    if fixed <= 0 and s.ctc > 0:
        # CTC only: split the fixed part of the CTC, with employer PF and gratuity inside it
        fixed_ctc = s.ctc - s.variable_pay - s.joining_bonus - s.esop_value - s.insurance - s.employer_nps
        # fixed_ctc = fixed pay + 12% PF + 4.81% gratuity on basic (basic = 40% of fixed pay)
        fixed_pay = fixed_ctc / (1 + 0.40 * (0.12 + 0.0481))
        s = s.model_copy(update=_typical_split(fixed_pay))
        if s.employer_pf <= 0:
            s.employer_pf = round(s.basic * 0.12)
        if s.gratuity <= 0:
            s.gratuity = round(s.basic * 0.0481)
        s.special_allowance += round(fixed_ctc - _fixed(s) - s.employer_pf - s.gratuity)  # absorb rounding
        estimates.append({"kind": "split", "amount": s.ctc,
                          "message": "The letter states only the total CTC, so the salary split is a typical estimate "
                          "(basic 40% of fixed pay, HRA half of basic, 12% PF)."})
    elif fixed <= 0 and stated_gross > 0:
        # Gross only: the gross is the fixed cash; employer PF and gratuity sit on top to form the CTC
        s = s.model_copy(update=_typical_split(stated_gross))
        s.employer_pf = s.employer_pf or round(s.basic * 0.12)
        s.gratuity = s.gratuity or round(s.basic * 0.0481)
        s.ctc = 0  # derived from the components below
        estimates.append({"kind": "gross", "amount": stated_gross,
                          "message": f"The letter states a gross salary of {inr(stated_gross)} a year but no CTC or "
                          "breakup, so the split is a typical estimate and the CTC is derived from it."})
    elif fixed > 0 and s.ctc > 0:
        recurring = fixed + s.employer_pf + s.gratuity + s.employer_nps + s.insurance + s.variable_pay
        joining_in, esop_in = ctc_inclusion(s, recurring)
        gap = s.ctc - recurring - (s.joining_bonus if joining_in else 0) - (s.esop_value if esop_in else 0)
        if gap > 0.01 * s.ctc:
            s.special_allowance += round(gap)
            estimates.append({"kind": "balance", "amount": round(gap),
                              "message": f"{inr(gap)} of the stated CTC wasn't itemised in the letter. We added it to "
                              "special allowance, which is how most companies balance a CTC."})
    return s, estimates


def ctc_inclusion(s: SalaryStructure, recurring_ctc: float) -> tuple[bool, bool]:
    """Whether the stated CTC includes the joining bonus / ESOPs, inferred from the gap between the
    stated CTC and the recurring components. Letters differ, so we check which combination fits."""
    gap = s.ctc - recurring_ctc
    tol = max(0.01 * s.ctc, 1)
    for joining, esop in ((True, True), (True, False), (False, True)):
        expected = (s.joining_bonus if joining else 0) + (s.esop_value if esop else 0)
        if expected > 0 and abs(gap - expected) <= tol:
            return joining and s.joining_bonus > 0, esop and s.esop_value > 0
    return False, False


def _employee_pf(s: SalaryStructure, a: Assumptions) -> float:
    if not a.include_employee_pf:
        return 0.0
    if a.pf_on_capped_wage:
        return 0.12 * min(s.basic, PF_WAGE_CEILING)
    return s.employer_pf if s.employer_pf > 0 else 0.12 * s.basic


def _hra_exemption(s: SalaryStructure, a: Assumptions) -> float:
    rent = a.monthly_rent * 12
    if s.hra <= 0 or rent <= 0:
        return 0.0
    return max(0.0, min(s.hra, rent - 0.10 * s.basic, (0.50 if a.metro else 0.40) * s.basic))


def compute_tax(
    regime: Regime,
    s: SalaryStructure,
    a: Assumptions,
    *,
    fixed_cash: float,
    employee_pf: float,
    professional_tax: float,
    extra_income: float = 0.0,
) -> TaxBreakdown:
    gross = fixed_cash + s.employer_nps + extra_income

    exemptions: list[Adjustment] = []
    deductions: list[Adjustment] = [Adjustment(label="Standard deduction", amount=rules.STANDARD_DEDUCTION[regime])]

    nps_limit = rules.EMPLOYER_NPS_LIMIT_PCT_OF_BASIC[regime] * s.basic
    if s.employer_nps > 0:
        deductions.append(Adjustment(label="Employer NPS — 80CCD(2)", amount=min(s.employer_nps, nps_limit)))

    if regime == "old":
        hra_ex = _hra_exemption(s, a)
        if hra_ex > 0:
            exemptions.append(Adjustment(label="HRA exemption — 10(13A)", amount=hra_ex))
        if s.meal_allowance > 0:
            exemptions.append(Adjustment(label="Meal coupons", amount=min(s.meal_allowance, MEAL_EXEMPTION_OLD)))
        if professional_tax > 0:
            deductions.append(Adjustment(label="Professional tax — 16(iii)", amount=professional_tax))
        c80 = min(LIMIT_80C, employee_pf + a.investments_80c)
        if c80 > 0:
            deductions.append(Adjustment(label="80C (EPF + investments)", amount=c80))
        if a.medical_80d > 0:
            deductions.append(Adjustment(label="80D health insurance", amount=min(a.medical_80d, LIMIT_80D)))
        if a.home_loan_interest > 0:
            deductions.append(Adjustment(label="Home loan interest — 24(b)", amount=min(a.home_loan_interest, LIMIT_24B)))
        if a.nps_80ccd1b > 0:
            deductions.append(Adjustment(label="Own NPS — 80CCD(1B)", amount=min(a.nps_80ccd1b, LIMIT_80CCD1B)))

    total_off = sum(x.amount for x in exemptions) + sum(x.amount for x in deductions)
    taxable = max(0.0, round((gross - total_off) / 10) * 10)

    base, slabs = rules.slab_tax(taxable, regime)
    rebate = rules.rebate_87a(taxable, base, regime)
    after_rebate = base - rebate
    sur = rules.surcharge(taxable, after_rebate, regime)
    cess = (after_rebate + sur) * rules.CESS_RATE
    total = round((after_rebate + sur + cess) / 10) * 10

    return TaxBreakdown(
        regime=regime,
        gross_income=round(gross, 2),
        exemptions=exemptions,
        deductions=deductions,
        taxable_income=taxable,
        slabs=slabs,
        base_tax=round(base, 2),
        rebate=round(rebate, 2),
        surcharge=round(sur, 2),
        cess=round(cess, 2),
        total_tax=total,
        effective_rate=round(total / gross, 4) if gross else 0.0,
        marginal_rate=rules.marginal_rate(taxable, regime) if total > 0 else 0.0,
    )


def calculate(s: SalaryStructure, a: Assumptions | None = None) -> CalculationResult:
    a = a or Assumptions()
    s = s.model_copy()
    warnings: list[str] = []

    fixed_cash = s.basic + s.hra + s.special_allowance + s.lta + s.meal_allowance + s.other_allowances
    variable_paid = s.variable_pay * a.variable_payout_pct / 100
    recurring_ctc = fixed_cash + s.employer_pf + s.gratuity + s.employer_nps + s.insurance + s.variable_pay

    if s.ctc <= 0:
        s.ctc = recurring_ctc
    gap = s.ctc - recurring_ctc
    joining_in, esop_in = ctc_inclusion(s, recurring_ctc)
    unallocated = gap - (s.joining_bonus if joining_in else 0) - (s.esop_value if esop_in else 0)
    if abs(unallocated) > 0.01 * s.ctc:
        warnings.append(
            f"Components add up to {inr(recurring_ctc)} but the stated CTC is {inr(s.ctc)}. "
            "Review the breakdown. Some components may be missing or misread."
        )
    if s.basic <= 0:
        warnings.append("No basic salary was found. PF, HRA and gratuity estimates depend on it.")
    if s.lta > 0:
        warnings.append("LTA is treated as fully taxable. The old-regime exemption needs actual travel bills.")

    employee_pf = _employee_pf(s, a)
    pt = rules.professional_tax(a.state, fixed_cash / 12)

    regimes: dict[Regime, RegimeResult] = {}
    for regime in ("new", "old"):
        kw = dict(fixed_cash=fixed_cash, employee_pf=employee_pf, professional_tax=pt)
        tax_fixed = compute_tax(regime, s, a, **kw).total_tax
        tax_full = compute_tax(regime, s, a, **kw, extra_income=variable_paid)
        tax_y1 = compute_tax(regime, s, a, **kw, extra_income=variable_paid + s.joining_bonus).total_tax

        annual = fixed_cash + variable_paid - employee_pf - pt - tax_full.total_tax
        regimes[regime] = RegimeResult(
            tax=tax_full,
            tax_on_fixed=tax_fixed,
            monthly_tax=round(tax_fixed / 12, 2),
            monthly_in_hand=round((fixed_cash - employee_pf - pt - tax_fixed) / 12, 2),
            annual_take_home=round(annual, 2),
            year_one_take_home=round(annual + s.joining_bonus - (tax_y1 - tax_full.total_tax), 2),
        )

    new_tax, old_tax = regimes["new"].tax.total_tax, regimes["old"].tax.total_tax
    recommended: Regime = "old" if old_tax < new_tax else "new"
    selected: Regime = recommended if a.regime == "auto" else a.regime
    chosen = regimes[selected]

    in_ctc = {"joining_bonus": joining_in, "esop_value": esop_in}
    components = [
        LineItem(
            key=key,
            label=label,
            annual=round(getattr(s, key), 2),
            monthly=None if cat in ("variable", "one_time", "equity") else round(getattr(s, key) / 12, 2),
            category=cat,
            description=desc,
            in_ctc=in_ctc.get(key, True),
        )
        for key, label, cat, desc in COMPONENTS
        if getattr(s, key) > 0
    ]

    variable_tax = chosen.tax.total_tax - chosen.tax_on_fixed
    buckets = [
        Bucket(label="Take-home (fixed pay)", amount=chosen.monthly_in_hand * 12),
        Bucket(label="Take-home (variable, post-tax)", amount=variable_paid - variable_tax),
        Bucket(label="Income tax", amount=chosen.tax.total_tax),
        Bucket(label="Employee PF", amount=employee_pf),
        Bucket(label="Professional tax", amount=pt),
        Bucket(label="Employer PF + NPS", amount=s.employer_pf + s.employer_nps),
        Bucket(label="Gratuity", amount=s.gratuity),
        Bucket(label="Insurance & benefits", amount=s.insurance),
        Bucket(label="Variable not paid out", amount=s.variable_pay - variable_paid),
        Bucket(label="Joining bonus (one-time)", amount=s.joining_bonus if joining_in else 0),
        Bucket(label="ESOPs / RSUs", amount=s.esop_value if esop_in else 0),
        Bucket(label="Unallocated", amount=unallocated),
    ]
    buckets = [Bucket(label=b.label, amount=round(b.amount, 2)) for b in buckets if b.amount > 0.5]

    return CalculationResult(
        structure=s,
        assumptions=a,
        components=components,
        fixed_cash=round(fixed_cash, 2),
        variable_paid=round(variable_paid, 2),
        employee_pf=round(employee_pf, 2),
        professional_tax=pt,
        regimes=regimes,
        selected_regime=selected,
        recommended_regime=recommended,
        regime_savings=abs(new_tax - old_tax),
        monthly_in_hand=chosen.monthly_in_hand,
        annual_take_home=chosen.annual_take_home,
        year_one_take_home=chosen.year_one_take_home,
        in_hand_pct_of_ctc=round(chosen.annual_take_home / s.ctc, 4) if s.ctc else 0.0,
        ctc_buckets=buckets,
        warnings=warnings,
    )
