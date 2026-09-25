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
    assert r.professional_tax == 2_500  # Karnataka: ₹200 × 11 + ₹300 in February
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


def test_one_time_items_have_no_monthly_figure_and_know_if_they_are_in_ctc():
    # Joining bonus on top of an 18L CTC (outside), ESOPs inside a 25.77L CTC
    nimbus = calculate(SalaryStructure(ctc=1_800_000, basic=720_000, special_allowance=1_080_000, joining_bonus=100_000))
    jb = next(c for c in nimbus.components if c.key == "joining_bonus")
    assert jb.monthly is None and jb.in_ctc is False
    assert not nimbus.warnings

    quantora = calculate(SalaryStructure(ctc=2_577_000, basic=1_000_000, special_allowance=941_000, esop_value=636_000))
    esop = next(c for c in quantora.components if c.key == "esop_value")
    assert esop.monthly is None and esop.in_ctc is True
    assert any(b.label == "ESOPs / RSUs" for b in quantora.ctc_buckets)
    assert sum(b.amount for b in quantora.ctc_buckets) == pytest.approx(2_577_000, abs=5)


# ---- incomplete letters must never compute on ₹0 ------------------------------------------------
from app.engine.calculator import complete_structure  # noqa: E402


def test_ctc_only_letter_is_split_and_reconciles():
    s, est = complete_structure(SalaryStructure(ctc=650_000))
    r = calculate(s)
    assert [e["kind"] for e in est] == ["split"]
    assert r.monthly_in_hand > 40_000 and not r.warnings
    assert sum(b.amount for b in r.ctc_buckets) == pytest.approx(650_000, abs=5)


def test_ctc_with_variable_only_keeps_variable_outside_fixed_split():
    s, _ = complete_structure(SalaryStructure(ctc=1_500_000, variable_pay=150_000))
    assert s.variable_pay == 150_000
    assert calculate(s).fixed_cash + s.employer_pf + s.gratuity == pytest.approx(1_350_000, abs=5)


def test_monthly_ctc_is_annualised():
    s, est = complete_structure(SalaryStructure(ctc=60_000))
    assert s.ctc == 720_000 and est[0]["kind"] == "monthly_ctc"


def test_gross_only_letter_derives_ctc():
    s, est = complete_structure(SalaryStructure(), stated_gross=540_000)
    r = calculate(s)
    assert est[0]["kind"] == "gross"
    assert r.fixed_cash == pytest.approx(540_000, abs=2)
    assert r.structure.ctc > 540_000  # employer PF and gratuity on top


def test_partial_breakup_balances_into_special_allowance():
    s, est = complete_structure(SalaryStructure(ctc=1_000_000, basic=400_000))
    assert est[0]["kind"] == "balance" and est[0]["amount"] == 600_000
    assert not calculate(s).warnings


def test_complete_letters_are_left_alone():
    full = SalaryStructure(ctc=1_800_000, basic=720_000, hra=360_000, special_allowance=421_056, employer_pf=86_400,
                           gratuity=34_632, insurance=17_912, variable_pay=160_000)
    s, est = complete_structure(full)
    assert est == [] and s == full


from app.services.extraction import _annualise_esop  # noqa: E402


def test_esop_total_grant_is_annualised():
    text = "You will also be granted ESOPs worth Rs. 25,44,000 vesting over 4 years (25% per year, 1-year cliff)."
    s = _annualise_esop(SalaryStructure(ctc=1_941_000, esop_value=2_544_000), text)
    assert s.esop_value == 636_000
    # Already annual: left alone
    assert _annualise_esop(SalaryStructure(ctc=1_941_000, esop_value=636_000), text).esop_value == 636_000


def test_ctc_and_gross_without_breakup_splits_the_stated_gross():
    # "12 LPA including a ₹1.2L bonus; monthly gross ₹81,000" — the letter's own gross must be the fixed cash
    s, est = complete_structure(SalaryStructure(ctc=1_200_000, variable_pay=120_000), stated_gross=81_000)
    fixed = s.basic + s.hra + s.special_allowance
    assert fixed == 972_000 and s.basic == 388_800
    assert s.employer_pf == 21_600 and s.gratuity == round(388_800 * 0.0481)  # PF at the ₹1,800/month cap
    assert s.insurance == 1_080_000 - 972_000 - 21_600 - s.gratuity  # the rest of the CTC is benefits
    assert [e["kind"] for e in est] == ["gross"] and "gross salary" in est[0]["message"]
    r = calculate(s)
    assert r.warnings == []
    assert round(r.monthly_in_hand) == round((972_000 - 21_600 - r.professional_tax) / 12)


def test_implausible_gross_above_ctc_falls_back_to_ctc_split():
    s, est = complete_structure(SalaryStructure(ctc=1_200_000), stated_gross=1_500_000)
    assert [e["kind"] for e in est] == ["split"]



def test_unstated_pf_defaults_to_the_statutory_cap():
    # CTC only, high enough that 12% of basic would exceed ₹1,800 a month
    s, _ = complete_structure(SalaryStructure(ctc=2_000_000))
    assert s.employer_pf == 21_600
    assert round(s.basic + s.hra + s.special_allowance + s.employer_pf + s.gratuity) == 2_000_000
    # Small CTC: 12% of basic is under the cap, so it stays 12%
    s, _ = complete_structure(SalaryStructure(ctc=300_000))
    assert s.employer_pf == round(0.12 * s.basic) < 21_600
    # A breakup without a PF line: employee PF uses the cap too
    r = calculate(SalaryStructure(ctc=1_500_000, basic=600_000, hra=300_000, special_allowance=600_000))
    assert r.employee_pf == 21_600
