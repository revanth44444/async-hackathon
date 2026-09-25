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
    if abs(gap) > 0.01 * s.ctc and abs(gap - s.joining_bonus - s.esop_value) > 0.01 * s.ctc:
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

    components = [
        LineItem(
            key=key,
            label=label,
            annual=round(getattr(s, key), 2),
            monthly=round(getattr(s, key) / 12, 2),
            category=cat,
            description=desc,
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
        Bucket(label="One-time / ESOPs / unallocated", amount=gap),
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
