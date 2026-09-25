import pytest

from app.engine import tax as rules
from app.engine.calculator import calculate, compute_tax
from app.engine.schemas import Assumptions, SalaryStructure


def _tax(regime: str, taxable: float) -> float:
    """Total tax (incl. rebate, surcharge, cess) for a given taxable income."""
    base, _ = rules.slab_tax(taxable, regime)
    after = base - rules.rebate_87a(taxable, base, regime)
    sur = rules.surcharge(taxable, after, regime)
    return round((after + sur) * 1.04)


@pytest.mark.parametrize(
    "regime,taxable,expected",
    [
        ("new", 1_200_000, 0),  # full 87A rebate
        ("new", 1_210_000, 10_400),  # marginal relief: 10,000 + cess
        ("new", 1_600_000, 124_800),
        ("new", 2_400_000, 312_000),
        ("old", 500_000, 0),
        ("old", 1_000_000, 117_000),
    ],
)
def test_slab_tax(regime, taxable, expected):
    assert _tax(regime, taxable) == expected


def test_surcharge_marginal_relief_just_above_50l():
    taxable = 5_010_000
    base, _ = rules.slab_tax(taxable, "new")
    assert base == 1_083_000
    assert rules.surcharge(taxable, base, "new") == pytest.approx(7_000)


def test_hra_exemption_old_regime():
    s = SalaryStructure(basic=600_000, hra=300_000)
    a = Assumptions(monthly_rent=25_000)
    t = compute_tax("old", s, a, fixed_cash=900_000, employee_pf=0, professional_tax=0)
    hra = next(x for x in t.exemptions if x.label.startswith("HRA"))
    assert hra.amount == 240_000  # rent − 10% basic


def test_12_75_lakh_gross_is_tax_free_under_new_regime():
    s = SalaryStructure(basic=637_500, special_allowance=637_500)
    r = calculate(s, Assumptions(regime="new", include_employee_pf=False, state="DL"))
    assert r.regimes["new"].tax.total_tax == 0
    assert r.monthly_in_hand == pytest.approx(1_275_000 / 12)


def test_typical_18_lpa_offer():
    s = SalaryStructure(
        ctc=1_800_000,
        basic=720_000,
        hra=360_000,
        special_allowance=421_056,
        employer_pf=86_400,
        gratuity=34_632,
        insurance=17_912,
        variable_pay=160_000,
    )
    r = calculate(s, Assumptions(state="KA"))
    assert not r.warnings
    assert r.employee_pf == 86_400
    assert r.professional_tax == 2_400
    assert r.selected_regime == "new"
    # Buckets reconcile back to CTC
    assert sum(b.amount for b in r.ctc_buckets) == pytest.approx(1_800_000, abs=5)
    assert 100_000 < r.monthly_in_hand < 115_000


def test_variable_payout_changes_annual_not_monthly():
    s = SalaryStructure(basic=800_000, special_allowance=800_000, variable_pay=200_000)
    full = calculate(s, Assumptions(variable_payout_pct=100))
    half = calculate(s, Assumptions(variable_payout_pct=50))
    assert full.monthly_in_hand == half.monthly_in_hand
    assert full.annual_take_home > half.annual_take_home


def test_old_regime_recommended_with_heavy_deductions():
    s = SalaryStructure(basic=800_000, hra=400_000, special_allowance=800_000, employer_pf=96_000)
    a = Assumptions(
        monthly_rent=30_000,
        investments_80c=90_000,
        medical_80d=50_000,
        home_loan_interest=200_000,
        nps_80ccd1b=50_000,
    )
    r = calculate(s, a)
    assert r.recommended_regime == "old"
    assert r.regimes["old"].tax.total_tax < r.regimes["new"].tax.total_tax


def test_ctc_mismatch_warns():
    r = calculate(SalaryStructure(ctc=2_000_000, basic=500_000))
    assert any("stated CTC" in w for w in r.warnings)


def test_deterministic():
    s = SalaryStructure(basic=900_000, hra=450_000, special_allowance=300_000, variable_pay=150_000)
    assert calculate(s).model_dump() == calculate(s).model_dump()
