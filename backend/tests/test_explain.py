from app.engine.calculator import calculate
from app.engine.schemas import Assumptions, SalaryStructure
from app.engine.calculator import inr
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
    assert unsupported_amounts(f"Your in-hand is {inr(r.monthly_in_hand)} a month.", allowed) == []
    assert unsupported_amounts("You'd get ₹1,23,456 extra.", allowed) == ["₹1,23,456"]


def test_facts_are_preformatted_and_one_time_items_have_no_monthly_figure():
    f = facts(calculate(NIMBUS))
    assert f["annual_take_home"].startswith("₹14,") and "L)" in f["annual_take_home"]
    joining = next(c for c in f["components"] if c["name"] == "Joining Bonus")
    assert "per_month" not in joining and joining["ctc"] == "outside the stated CTC"


def test_rules_state_hra_is_taxable_in_new_regime_and_joining_bonus_is_outside_ctc():
    text = " ".join(rules(calculate(NIMBUS, Assumptions())))
    assert "HRA is fully taxable" in text
    assert "No rent has been entered" in text
    assert "outside the stated CTC" in text


def test_inr_rounds_half_up_like_the_frontend():
    assert inr(109_540.5) == "₹1,09,541"
    assert inr(109_541.5) == "₹1,09,542"


def test_rules_tie_hra_to_a_regime():
    text = " ".join(rules(calculate(NIMBUS)))
    assert "Whenever you mention HRA, name the regime" in text


from app.engine.insights import CompareRow, compare_metrics  # noqa: E402

QUANTORA = SalaryStructure(
    ctc=1_941_000, basic=700_000, hra=350_000, special_allowance=430_200, employer_pf=84_000,
    gratuity=33_670, variable_pay=315_000,
)


def _compare(*structs):
    return compare_metrics([CompareRow(offer_id=str(i), label=f"Offer {i}", result=calculate(s)) for i, s in enumerate(structs)])


def test_suitability_never_swaps_certainty_and_variable_pay():
    res = _compare(NIMBUS, QUANTORA)
    label = {r.offer_id: r.label for r in res.rows}
    suits = res.suitability()
    safe, upside = label[res.best_monthly_in_hand], label[res.best_annual_take_home]
    if safe == upside:
        assert suits.startswith(f"{safe} suits both")
    else:
        assert f"For certainty, {safe}" in suits and f"variable pay, {upside}" in suits


def test_suitability_splits_when_different_offers_lead():
    steady = SalaryStructure(ctc=1_500_000, basic=600_000, hra=300_000, special_allowance=528_000, employer_pf=72_000)
    risky = SalaryStructure(ctc=2_000_000, basic=400_000, hra=200_000, special_allowance=352_000, employer_pf=48_000, variable_pay=1_000_000)
    suits = _compare(steady, risky).suitability()
    assert "For certainty, Offer 0" in suits and "variable pay, Offer 1" in suits


def test_compare_verdict_attributes_each_figure_to_its_own_offer():
    from app.services.explain import compare_verdict, money
    res = _compare(NIMBUS, QUANTORA.model_copy(update={"esop_value": 636_000}))
    labelled = [(r.label, r.result) for r in res.rows]
    v = compare_verdict(labelled, res.winners(), res.suitability())
    nimbus_line = next(l for l in v.splitlines() if l.startswith("- Offer 0:"))
    quantora_line = next(l for l in v.splitlines() if l.startswith("- Offer 1:"))
    assert "ESOP" not in nimbus_line and money(636_000) in quantora_line
    assert money(100_000) in nimbus_line and "joining" not in quantora_line
    assert v.endswith(res.suitability())
