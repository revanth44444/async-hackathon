"""Typed inputs/outputs for the deterministic salary engine. All amounts are annual INR."""
from typing import Literal

from pydantic import BaseModel, Field

Regime = Literal["new", "old"]


class SalaryStructure(BaseModel):
    company: str | None = None
    role: str | None = None
    location: str | None = None
    ctc: float = 0

    # Fixed cash components (paid monthly)
    basic: float = 0
    hra: float = 0
    special_allowance: float = 0
    lta: float = 0
    meal_allowance: float = 0
    other_allowances: float = 0

    # Employer retirement contributions (part of CTC, not in-hand)
    employer_pf: float = 0
    gratuity: float = 0
    employer_nps: float = 0

    # Benefits / variable / one-time
    insurance: float = 0
    variable_pay: float = 0
    joining_bonus: float = 0
    esop_value: float = 0  # annualised vesting value; not taxed until exercise


class Assumptions(BaseModel):
    regime: Literal["auto", "new", "old"] = "auto"
    state: str = "KA"
    metro: bool = False  # HRA metros are only Mumbai, Delhi, Kolkata, Chennai
    variable_payout_pct: float = Field(100, ge=0, le=200)
    include_employee_pf: bool = True
    pf_on_capped_wage: bool = False  # 12% of min(basic, ₹15,000/month)
    monthly_rent: float = Field(0, ge=0)
    investments_80c: float = Field(0, ge=0)  # beyond EPF
    medical_80d: float = Field(0, ge=0)
    home_loan_interest: float = Field(0, ge=0)
    nps_80ccd1b: float = Field(0, ge=0)


class LineItem(BaseModel):
    key: str
    label: str
    annual: float
    monthly: float | None  # None for items that are not paid monthly (variable, one-time, equity)
    category: Literal["fixed", "retirement", "benefit", "variable", "one_time", "equity"]
    description: str
    in_ctc: bool = True  # False for one-time items the stated CTC does not include


class SlabRow(BaseModel):
    lower: float
    upper: float | None
    rate: float
    taxable_amount: float
    tax: float


class Adjustment(BaseModel):
    label: str
    amount: float


class TaxBreakdown(BaseModel):
    regime: Regime
    gross_income: float
    exemptions: list[Adjustment]
    deductions: list[Adjustment]
    taxable_income: float
    slabs: list[SlabRow]
    base_tax: float
    rebate: float
    surcharge: float
    cess: float
    total_tax: float
    effective_rate: float
    marginal_rate: float


class RegimeResult(BaseModel):
    tax: TaxBreakdown  # tax on fixed + variable (at payout %)
    tax_on_fixed: float
    monthly_tax: float
    monthly_in_hand: float
    annual_take_home: float
    year_one_take_home: float


class Bucket(BaseModel):
    label: str
    amount: float


class CalculationResult(BaseModel):
    structure: SalaryStructure
    assumptions: Assumptions
    components: list[LineItem]
    fixed_cash: float
    variable_paid: float
    employee_pf: float
    professional_tax: float
    regimes: dict[Regime, RegimeResult]
    selected_regime: Regime
    recommended_regime: Regime
    regime_savings: float
    monthly_in_hand: float
    annual_take_home: float
    year_one_take_home: float
    in_hand_pct_of_ctc: float
    ctc_buckets: list[Bucket]
    warnings: list[str]
