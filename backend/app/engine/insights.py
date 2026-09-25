"""Simulations, deterministic tax-saving suggestions and offer comparison."""
from pydantic import BaseModel

from app.engine.calculator import calculate, inr
from app.engine.flags import RedFlagReport
from app.engine.schemas import Assumptions, CalculationResult, SalaryStructure

CASH_FIELDS = ("basic", "hra", "special_allowance", "lta", "meal_allowance", "other_allowances")
SCALABLE = CASH_FIELDS + ("ctc", "employer_pf", "gratuity", "employer_nps", "variable_pay")


class Suggestion(BaseModel):
    title: str
    detail: str
    annual_impact: float  # positive = more money / less tax


class Delta(BaseModel):
    monthly_in_hand: float
    annual_take_home: float
    income_tax: float


class SimulationResult(BaseModel):
    baseline: CalculationResult
    scenario: CalculationResult
    delta: Delta


def apply_hike(s: SalaryStructure, pct: float) -> SalaryStructure:
    f = 1 + pct / 100
    return s.model_copy(update={k: getattr(s, k) * f for k in SCALABLE})


def simulate(
    s: SalaryStructure,
    base_a: Assumptions,
    scenario_a: Assumptions,
    hike_pct: float = 0,
    overrides: dict | None = None,
) -> SimulationResult:
    baseline = calculate(s, base_a)
    scen_s = apply_hike(s, hike_pct).model_copy(update=overrides or {})
    scenario = calculate(scen_s, scenario_a)
    tax = lambda r: r.regimes[r.selected_regime].tax.total_tax  # noqa: E731
    return SimulationResult(
        baseline=baseline,
        scenario=scenario,
        delta=Delta(
            monthly_in_hand=round(scenario.monthly_in_hand - baseline.monthly_in_hand, 2),
            annual_take_home=round(scenario.annual_take_home - baseline.annual_take_home, 2),
            income_tax=round(tax(scenario) - tax(baseline), 2),
        ),
    )


def suggestions(s: SalaryStructure, a: Assumptions) -> list[Suggestion]:
    base = calculate(s, a)
    base_tax = base.regimes[base.selected_regime].tax.total_tax
    out: list[Suggestion] = []

    if a.regime != "auto" and base.selected_regime != base.recommended_regime and base.regime_savings > 0:
        out.append(
            Suggestion(
                title=f"Switch to the {base.recommended_regime} regime",
                detail=f"With your current inputs the {base.recommended_regime} regime costs less in tax.",
                annual_impact=base.regime_savings,
            )
        )

    # Restructure part of special allowance into employer NPS (80CCD(2), 14% of basic in new regime)
    room = min(s.special_allowance, 0.14 * s.basic - s.employer_nps)
    if room > 10_000 and base_tax > 0:
        alt = calculate(s.model_copy(update={"special_allowance": s.special_allowance - room, "employer_nps": s.employer_nps + room}), a)
        saved = base_tax - alt.regimes[alt.selected_regime].tax.total_tax
        if saved > 1_000:
            out.append(
                Suggestion(
                    title="Ask HR for the corporate NPS option",
                    detail=f"Moving {inr(room)} a year of special allowance into employer NPS saves about {inr(saved)} in tax. "
                    "The money is locked in until retirement.",
                    annual_impact=round(saved, 2),
                )
            )

    old = base.regimes["old"].tax
    if base.selected_regime == "old" or base.regime_savings < 50_000:
        used_80c = next((d.amount for d in old.deductions if d.label.startswith("80C")), 0)
        if used_80c < 150_000:
            room_80c = 150_000 - used_80c
            alt = calculate(s, a.model_copy(update={"investments_80c": a.investments_80c + room_80c, "regime": "old"}))
            saved = old.total_tax - alt.regimes["old"].tax.total_tax
            if saved > 1_000:
                out.append(
                    Suggestion(
                        title="Fill your 80C limit (old regime)",
                        detail=f"Investing another {inr(room_80c)} in ELSS/PPF would cut old-regime tax by about {inr(saved)}.",
                        annual_impact=round(saved, 2),
                    )
                )

    if s.variable_pay > 0.15 * s.ctc:
        out.append(
            Suggestion(
                title="Variable pay is a large share of CTC",
                detail=f"{s.variable_pay / s.ctc:.0%} of your CTC is variable. Ask for the historical payout percentage, "
                "or negotiate to move some of it into fixed pay.",
                annual_impact=0,
            )
        )
    return sorted(out, key=lambda x: -x.annual_impact)


class CompareRow(BaseModel):
    offer_id: str
    label: str
    result: CalculationResult
    red_flags: RedFlagReport | None = None


class CompareResult(BaseModel):
    rows: list[CompareRow]
    # Each best_* is the leading offer's id, or None when two or more offers tie for the lead
    best_monthly_in_hand: str | None  # guaranteed: fixed pay after tax, PF and professional tax
    best_annual_take_home: str | None  # includes variable pay at the assumed payout
    best_year_one: str | None
    best_fixed_pay: str | None  # fixed pay before deductions
    best_retirement: str | None
    lowest_tax: str | None
    ties: dict[str, list[str]] = {}  # metric label → labels of the offers tied for the lead
    verdict: str | None = None

    def winners(self) -> dict[str, str]:
        """Human-readable metric → sole leading offer's label. Tied metrics are left out (see `ties`)."""
        label = {r.offer_id: r.label for r in self.rows}
        pairs = [
            ("Highest guaranteed monthly in-hand (after tax and PF)", self.best_monthly_in_hand),
            ("Highest annual take-home if variable pay is paid as assumed", self.best_annual_take_home),
            ("Highest year-one take-home including one-time bonuses", self.best_year_one),
            ("Highest fixed pay before tax and PF", self.best_fixed_pay),
            ("Most retirement savings (PF + NPS)", self.best_retirement),
            ("Lowest income tax", self.lowest_tax),
        ]
        return {metric: label[oid] for metric, oid in pairs if oid is not None}

    def suitability(self) -> str:
        """Which offer suits a certainty-seeker vs someone comfortable with variable pay, decided here so the
        model can't swap them. Certainty = most guaranteed monthly pay; variable comfort = most take-home
        if variable pay pays out."""
        label = {r.offer_id: r.label for r in self.rows}
        if self.best_monthly_in_hand is None or self.best_annual_take_home is None:
            return ("No single offer leads on both guaranteed monthly in-hand and take-home with variable pay, "
                    "so weigh the red flags and one-time bonuses to choose.")
        safe, upside = label[self.best_monthly_in_hand], label[self.best_annual_take_home]
        if safe == upside:
            return (f"{safe} suits both a candidate who values certainty and one comfortable with variable pay: "
                    "it leads on guaranteed monthly in-hand and on annual take-home with variable pay.")
        return (f"For certainty, {safe}: it pays the most guaranteed monthly in-hand. "
                f"For someone comfortable with variable pay, {upside}: it pays the most if variable pay is paid out.")


TIE_TOLERANCE = 1  # ₹: amounts within a rupee are the same number on screen


def compare_metrics(rows: list[CompareRow]) -> CompareResult:
    ties: dict[str, list[str]] = {}

    def best(metric: str, key, lowest=False) -> str | None:
        vals = [(key(r.result), r) for r in rows]
        top = (min if lowest else max)(v for v, _ in vals)
        leaders = [r for v, r in vals if abs(v - top) <= TIE_TOLERANCE]
        if len(leaders) > 1:
            ties[metric] = [r.label for r in leaders]
            return None
        return leaders[0].offer_id

    return CompareResult(
        rows=rows,
        best_monthly_in_hand=best("Highest guaranteed monthly in-hand (after tax and PF)", lambda r: r.monthly_in_hand),
        best_annual_take_home=best("Highest annual take-home if variable pay is paid as assumed", lambda r: r.annual_take_home),
        best_year_one=best("Highest year-one take-home including one-time bonuses", lambda r: r.year_one_take_home),
        best_fixed_pay=best("Highest fixed pay before tax and PF", lambda r: r.fixed_cash),
        best_retirement=best("Most retirement savings (PF + NPS)", lambda r: r.employee_pf + r.structure.employer_pf + r.structure.employer_nps),
        lowest_tax=best("Lowest income tax", lambda r: r.regimes[r.selected_regime].tax.total_tax, lowest=True),
        ties=ties,
    )
