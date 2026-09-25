"""Offer-letter text → SalaryStructure.

The LLM only *reads and classifies* line items; Python does all the summing, so totals are
auditable. Without a Groq key we fall back to a keyword/regex parser.
"""
import logging
import re

from app.engine.schemas import SalaryStructure
from app.services.groq_client import AIUnavailable, chat_json

log = logging.getLogger(__name__)

CATEGORIES = [
    "basic", "hra", "special_allowance", "lta", "meal_allowance", "other_allowances",
    "employer_pf", "gratuity", "employer_nps", "insurance", "variable_pay",
    "joining_bonus", "esop_value", "ignore",
]

SYSTEM_PROMPT = f"""You extract compensation data from Indian job offer letters.
Return ONLY a JSON object with this shape:
{{
  "company": string|null, "role": string|null, "location": string|null (city),
  "candidate_name": string|null, "joining_date": string|null,
  "stated_ctc_annual": number|null,
  "stated_gross_annual": number|null,
  "components": [{{"label": string, "annual_amount": number, "category": string}}],
  "notes": [string]
}}
Rules:
- category must be one of: {", ".join(CATEGORIES)}.
- annual_amount is the ANNUAL amount in INR as a plain number. If only a monthly figure is given, multiply by 12.
- stated_ctc_annual and stated_gross_annual are ANNUAL too: a "monthly CTC" or "gross per month" must be multiplied by 12.
  stated_gross_annual is the gross / total fixed salary if the letter states one, else null.
- If a sentence says the CTC includes a bonus or variable pay, list that amount as a variable_pay component.
  Convert "12 LPA"/"12 lakhs" → 1200000, "1.2 Cr" → 12000000.
- List every individual pay component exactly once. Use category "ignore" for subtotals and totals
  (Gross, Total Fixed, CTC, Net) so nothing is double counted.
- Employer PF/provident fund → employer_pf. Performance/annual bonus/incentive → variable_pay.
  Sign-on/joining/relocation bonus → joining_bonus. ESOP/RSU → esop_value (annual vesting value if stated,
  else total grant / vesting years). Conveyance/telephone/internet/other allowances → other_allowances.
  Medical/health/term/accident insurance premium → insurance. Food coupons/meal card → meal_allowance.
- notes: short observations a candidate should know (clawbacks, notice period, bond, probation, vesting schedule).
- Never invent numbers that are not in the text. Use null when unknown."""

METRO_CITIES = {"mumbai", "delhi", "new delhi", "kolkata", "chennai"}
CITY_STATE = {
    "bangalore": "KA", "bengaluru": "KA", "mysore": "KA", "mumbai": "MH", "pune": "MH", "nagpur": "MH",
    "chennai": "TN", "coimbatore": "TN", "hyderabad": "TS", "kolkata": "WB", "ahmedabad": "GJ",
    "gandhinagar": "GJ", "kochi": "KL", "trivandrum": "KL", "thiruvananthapuram": "KL", "indore": "MP",
    "delhi": "DL", "new delhi": "DL", "gurgaon": "HR", "gurugram": "HR", "noida": "UP", "jaipur": "RJ",
    "visakhapatnam": "AP", "vijayawada": "AP",
}


def location_defaults(location: str | None) -> dict:
    loc = (location or "").lower()
    state = next((st for city, st in CITY_STATE.items() if city in loc), None)
    return {"state": state, "metro": any(c in loc for c in METRO_CITIES)}


def _aggregate(data: dict) -> SalaryStructure:
    totals = {c: 0.0 for c in CATEGORIES}
    for comp in data.get("components") or []:
        cat = comp.get("category")
        try:
            amt = float(comp.get("annual_amount") or 0)
        except (TypeError, ValueError):
            continue
        if cat in totals and amt > 0:
            totals[cat] += amt
    totals.pop("ignore")
    return SalaryStructure(
        company=data.get("company"),
        role=data.get("role"),
        location=data.get("location"),
        ctc=float(data.get("stated_ctc_annual") or 0),
        **totals,
    )


def _num(v) -> float:
    try:
        return max(0.0, float(v or 0))
    except (TypeError, ValueError):
        return 0.0


def _extract_ai(text: str) -> tuple[SalaryStructure, dict]:
    data = chat_json(
        [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"Offer letter text:\n\n{text[:15000]}"},
        ],
        max_tokens=3000,
    )
    meta = {
        "method": "ai",
        "stated_gross_annual": _num(data.get("stated_gross_annual")),
        "candidate_name": data.get("candidate_name"),
        "joining_date": data.get("joining_date"),
        "components": data.get("components") or [],
        "notes": data.get("notes") or [],
    }
    return _aggregate(data), meta


# ---------------------------------------------------------------- heuristic fallback

KEYWORDS: list[tuple[str, str]] = [
    (r"total|gross|net pay|\bctc\b|cost to company", "ignore"),
    (r"employer.{0,25}(pf|provident|epf)|(pf|provident fund).{0,15}employer", "employer_pf"),
    (r"employee.{0,25}(pf|provident)", "ignore"),
    (r"provident|\bepf\b|\bpf\b", "employer_pf"),
    (r"gratuity", "gratuity"),
    (r"\bnps\b|national pension", "employer_nps"),
    (r"insurance|mediclaim|medical cover", "insurance"),
    (r"joining|sign[- ]?on|relocation", "joining_bonus"),
    (r"\besops?\b|\brsus?\b|stock", "esop_value"),
    (r"variable|performance|bonus|incentive", "variable_pay"),
    (r"\bbasic\b", "basic"),
    (r"\bhra\b|house rent", "hra"),
    (r"special|flexi", "special_allowance"),
    (r"\blta\b|leave travel", "lta"),
    (r"meal|food|sodexo|zeta", "meal_allowance"),
    (r"conveyance|telephone|internet|mobile|allowance", "other_allowances"),
]
NUM_RE = re.compile(r"(?:₹|rs\.?|inr)?\s*(\d[\d,]*(?:\.\d+)?)\s*(lakhs?|lacs?|lpa|cr(?:ores?)?)?\b", re.I)
# Split on newlines and sentence ends, but not on "Rs." abbreviations
SEGMENT_RE = re.compile(r"\n|;\s*|(?<![Rr]s)(?<!Pvt)\.\s+")
MONTHLY_RE = re.compile(r"per month|monthly|p\.?\s?m\.?\b|/\s?month", re.I)


def _amounts(line: str) -> list[float]:
    line = re.sub(r"\d+(\.\d+)?\s*%", " ", line)
    out = []
    for num, unit in NUM_RE.findall(line):
        try:
            v = float(num.replace(",", ""))
        except ValueError:
            continue
        unit = unit.lower()
        if unit.startswith(("lakh", "lac", "lpa")):
            v *= 100_000
        elif unit.startswith("cr"):
            v *= 10_000_000
        if v >= 500 and not (1990 <= v <= 2100):  # skip small numbers and years
            out.append(v)
    return out


def _extract_heuristic(text: str) -> tuple[SalaryStructure, dict]:
    seen: set[tuple[str, float]] = set()
    components = []
    stated_ctc = stated_gross = 0.0
    for raw in SEGMENT_RE.split(text):
        line = raw.strip()
        amounts = _amounts(line)
        if not line or not amounts:
            continue
        low = line.lower()
        monthly = bool(MONTHLY_RE.search(low))
        if re.search(r"\bctc\b|cost to company", low):
            ctc = max(amounts) * (12 if monthly and len(amounts) == 1 else 1)
            stated_ctc = max(stated_ctc, ctc)
            # "CTC ₹15L which includes a bonus of ₹1.5L": the smaller figure is the variable part
            if len(amounts) >= 2 and re.search(r"variable|performance|bonus|incentive", low):
                bonus = min(amounts)
                if ("variable_pay", bonus) not in seen:
                    seen.add(("variable_pay", bonus))
                    components.append({"label": "Variable / bonus (in CTC)", "annual_amount": bonus, "category": "variable_pay"})
        elif re.search(r"\bgross\b|total fixed|fixed (salary|compensation|pay)", low):
            stated_gross = max(stated_gross, max(amounts) * (12 if monthly and len(amounts) == 1 else 1))
        cat = next((c for pat, c in KEYWORDS if re.search(pat, low)), None)
        if not cat or cat == "ignore":
            continue
        amt = max(amounts)
        if len(amounts) == 1 and MONTHLY_RE.search(low):
            amt *= 12
        if cat == "esop_value" and (yrs := re.search(r"over\s+(\d+)\s+years", low)):
            amt /= int(yrs.group(1))
        if (cat, amt) in seen:  # same row seen in both text and table extraction
            continue
        seen.add((cat, amt))
        components.append({"label": re.split(r"[:|₹\d]", line)[0].strip()[:60] or cat, "annual_amount": amt, "category": cat})

    company = None
    m = re.search(r"\b(?:at|join|with|from)\s+([A-Z][\w&.]*(?:\s+[A-Z][\w&.]*){0,3}\s+(?:Pvt\.?(?:\s+Ltd\.?)?|Private\s+Limited|Ltd\.?|Limited|Inc\.?))", text)
    if m:
        company = " ".join(m.group(1).split())
    location = next((c.title() for c in CITY_STATE if c in text.lower()), None)

    data = {"components": components, "stated_ctc_annual": stated_ctc, "company": company, "location": location}
    meta = {
        "method": "heuristic",
        "stated_gross_annual": stated_gross,
        "components": components,
        "notes": ["Parsed without AI (no GROQ_API_KEY). Check the extracted components carefully."],
    }
    return _aggregate(data), meta


VEST_RE = re.compile(r"(?:over|across)\s+(\d+)\s+years|(\d+)[- ]years?\s+vesting", re.I)


def _annualise_esop(structure: SalaryStructure, text: str) -> SalaryStructure:
    """The model sometimes returns the total grant ("₹25,44,000 vesting over 4 years") as esop_value, which is
    shown as a per-year figure. If esop_value equals the largest amount in a sentence that states a vesting
    period, divide it by that period."""
    if structure.esop_value <= 0:
        return structure
    for seg in SEGMENT_RE.split(text):
        low = seg.lower()
        if not re.search(r"\besops?\b|\brsus?\b|stock", low) or not (m := VEST_RE.search(low)):
            continue
        amounts, years = _amounts(seg), int(m.group(1) or m.group(2))
        if years > 1 and amounts and abs(max(amounts) - structure.esop_value) <= 1:
            return structure.model_copy(update={"esop_value": structure.esop_value / years})
    return structure


def extract_structure(text: str) -> tuple[SalaryStructure, dict]:
    try:
        structure, meta = _extract_ai(text)
        if structure.basic + structure.special_allowance + structure.ctc + meta["stated_gross_annual"] <= 0:
            raise AIUnavailable("AI found no salary components")
    except AIUnavailable as exc:
        log.info("Falling back to heuristic extraction: %s", exc)
        structure, meta = _extract_heuristic(text)
    structure = _annualise_esop(structure, text)
    meta.update(location_defaults(structure.location))
    return structure, meta
