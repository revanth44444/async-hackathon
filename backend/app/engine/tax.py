"""Indian income-tax rules for salaried individuals, FY 2025-26 (AY 2026-27).

Pure functions only — no I/O, no AI. Every rupee shown in the app comes from here.
"""
from app.engine.schemas import Regime, SlabRow

INF = float("inf")

SLABS: dict[Regime, list[tuple[float, float, float]]] = {
    "new": [
        (0, 400_000, 0.00),
        (400_000, 800_000, 0.05),
        (800_000, 1_200_000, 0.10),
        (1_200_000, 1_600_000, 0.15),
        (1_600_000, 2_000_000, 0.20),
        (2_000_000, 2_400_000, 0.25),
        (2_400_000, INF, 0.30),
    ],
    "old": [
        (0, 250_000, 0.00),
        (250_000, 500_000, 0.05),
        (500_000, 1_000_000, 0.20),
        (1_000_000, INF, 0.30),
    ],
}

STANDARD_DEDUCTION: dict[Regime, float] = {"new": 75_000, "old": 50_000}

# Section 87A: (income limit, max rebate)
REBATE_87A: dict[Regime, tuple[float, float]] = {"new": (1_200_000, 60_000), "old": (500_000, 12_500)}

# (income above, surcharge rate); new regime is capped at 25%
SURCHARGE: dict[Regime, list[tuple[float, float]]] = {
    "new": [(5_000_000, 0.10), (10_000_000, 0.15), (20_000_000, 0.25)],
    "old": [(5_000_000, 0.10), (10_000_000, 0.15), (20_000_000, 0.25), (50_000_000, 0.37)],
}

CESS_RATE = 0.04
EMPLOYER_NPS_LIMIT_PCT_OF_BASIC: dict[Regime, float] = {"new": 0.14, "old": 0.10}

# State: (annual professional tax, minimum monthly gross for it to apply). Approximate.
PROFESSIONAL_TAX: dict[str, tuple[float, float]] = {
    "KA": (2_500, 25_000),  # ₹200 × 11 months + ₹300 in February
    "MH": (2_500, 10_000),
    "TN": (2_500, 21_000),
    "TS": (2_400, 20_000),
    "AP": (2_400, 20_000),
    "WB": (2_400, 40_000),
    "GJ": (2_400, 12_000),
    "KL": (2_500, 12_000),
    "MP": (2_500, 18_750),
    "DL": (0, 0),
    "HR": (0, 0),
    "UP": (0, 0),
    "RJ": (0, 0),
    "OTHER": (2_400, 15_000),
}


def slab_tax(taxable_income: float, regime: Regime) -> tuple[float, list[SlabRow]]:
    total = 0.0
    rows: list[SlabRow] = []
    for lower, upper, rate in SLABS[regime]:
        portion = max(0.0, min(taxable_income, upper) - lower)
        tax = portion * rate
        total += tax
        rows.append(
            SlabRow(
                lower=lower,
                upper=None if upper == INF else upper,
                rate=rate,
                taxable_amount=round(portion, 2),
                tax=round(tax, 2),
            )
        )
    return total, rows


def rebate_87a(taxable_income: float, tax: float, regime: Regime) -> float:
    limit, max_rebate = REBATE_87A[regime]
    if taxable_income <= limit:
        return min(tax, max_rebate)
    if regime == "new":
        # Marginal relief: tax payable cannot exceed the income earned above ₹12L
        excess = taxable_income - limit
        if tax > excess:
            return tax - excess
    return 0.0


def surcharge(taxable_income: float, tax: float, regime: Regime) -> float:
    brackets = SURCHARGE[regime]
    applicable = [(i, t, r) for i, (t, r) in enumerate(brackets) if taxable_income > t]
    if not applicable:
        return 0.0
    idx, threshold, rate = applicable[-1]
    amount = tax * rate
    # Marginal relief: extra (tax + surcharge) over the threshold can't exceed extra income
    prev_rate = brackets[idx - 1][1] if idx > 0 else 0.0
    tax_at_threshold, _ = slab_tax(threshold, regime)
    ceiling = tax_at_threshold * (1 + prev_rate) + (taxable_income - threshold)
    return max(0.0, min(amount, ceiling - tax))


def professional_tax(state: str, monthly_gross: float) -> float:
    annual, min_monthly = PROFESSIONAL_TAX.get(state.upper(), PROFESSIONAL_TAX["OTHER"])
    return annual if monthly_gross >= min_monthly else 0.0


def marginal_rate(taxable_income: float, regime: Regime) -> float:
    for lower, upper, rate in SLABS[regime]:
        if lower <= taxable_income < upper:
            return rate
    return SLABS[regime][-1][2]
