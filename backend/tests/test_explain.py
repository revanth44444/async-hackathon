from app.engine.calculator import calculate
from app.engine.schemas import Assumptions, SalaryStructure
from app.services.explain import allowed_amounts, facts, rules, unsupported_amounts

NIMBUS = SalaryStructure(
    ctc=1_800_004, basic=720_000, hra=360_000, special_allowance=421_056, employer_pf=86_400,
    gratuity=34_632, insurance=17_916, variable_pay=160_000, joining_bonus=100_000,
)


def test_wrong_lakh_conversion_is_caught():
    r = calculate(NIMBUS)
    allowed = allowed_amounts([r])
    # The reviewer's example: 16.2L written as "1.62 L"
    assert unsupported_amounts("Year one is about ₹1.62 L.", allowed) == ["₹1.62 L"]
    assert unsupported_amounts(f"Year one is ₹{r.year_one_take_home / 1e5:.1f}L.", allowed) == []
    assert unsupported_amounts("Your in-hand is ₹1,09,549 a month.", allowed) == []
    assert unsupported_amounts("You'd get ₹1,23,456 extra.", allowed) == ["₹1,23,456"]


def test_facts_are_preformatted_and_one_time_items_have_no_monthly_figure():
    f = facts(calculate(NIMBUS))
    assert f["annual_take_home"].startswith("₹14,") and "L)" in f["annual_take_home"]
    joining = next(c for c in f["components"] if c["name"] == "Joining Bonus")
    assert "per_month" not in joining and "one-time" in joining["note"]


def test_rules_state_hra_is_taxable_in_new_regime_and_joining_bonus_is_outside_ctc():
    text = " ".join(rules(calculate(NIMBUS, Assumptions())))
    assert "HRA is fully taxable" in text
    assert "No rent has been entered" in text
    assert "outside the stated CTC" in text
