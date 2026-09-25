"""Negotiation email helper.

What to ask for is decided in Python from the offer's red flags and tax-saving suggestions. The model only turns
the chosen points into a polite email, and every ₹ amount it writes is checked against the figures it was given.
"""
import json
import re

from pydantic import BaseModel

from app.engine.calculator import inr
from app.engine.flags import RedFlagReport
from app.engine.insights import Suggestion
from app.engine.schemas import CalculationResult
from app.services.explain import allowed_amounts, facts, verified_chat
from app.services.groq_client import AIUnavailable


class NegotiationPoint(BaseModel):
    key: str
    ask: str  # one line, phrased as the request
    why: str  # one line of reasoning the candidate can use


class NegotiationEmail(BaseModel):
    subject: str
    body: str
    method: str  # "ai" | "template"


def negotiation_points(r: CalculationResult, report: RedFlagReport, tips: list[Suggestion]) -> list[NegotiationPoint]:
    s = r.structure
    flagged = {f.key for f in report.flags}
    out = [NegotiationPoint(key="fixed_pay", ask="Ask whether the fixed pay can be raised.",
                            why=f"Fixed pay is what arrives every month: {inr(r.monthly_in_hand)} in hand today.")]
    if "variable_share" in flagged:
        out.append(NegotiationPoint(key="variable_to_fixed", ask="Ask to move part of the variable pay into fixed pay.",
                                    why=f"{inr(s.variable_pay)} of the CTC is variable and not guaranteed."))
    if nps := next((t for t in tips if "NPS" in t.title), None):
        out.append(NegotiationPoint(key="corporate_nps", ask="Ask whether the corporate NPS option is available.",
                                    why=f"It would save about {inr(nps.annual_impact)} a year in tax at no cost to the company."))
    if "service_bond" in flagged:
        out.append(NegotiationPoint(key="service_bond", ask="Ask to waive or shorten the service bond.",
                                    why="A bond makes leaving early costly."))
    if "joining_clawback" in flagged:
        out.append(NegotiationPoint(key="joining_clawback", ask="Ask for the joining bonus clawback to be pro-rated.",
                                    why=f"The {inr(s.joining_bonus)} joining bonus must be repaid if you leave early."))
    if "retention_conditional" in flagged:
        out.append(NegotiationPoint(key="retention_schedule", ask="Ask whether the retention bonus can be paid in instalments.",
                                    why=f"The {inr(s.retention_bonus)} retention bonus is paid only if you are still employed at the date."))
    days = report.notice_days
    if days is not None and days >= 60:
        target = 60 if days > 60 else 30  # never ask for what the letter already gives
        out.append(NegotiationPoint(key="notice_period", ask=f"Ask to reduce the notice period to {target} days.",
                                    why=f"The letter asks for {days} days, which can hold up a future move."))
    if report.has_non_compete:
        out.append(NegotiationPoint(key="non_compete", ask="Ask to narrow or remove the non-compete clause.",
                                    why="It limits where you can work after leaving. Ask for a shorter duration and a clear list of competitors."))
    if "esop_in_ctc" in flagged:
        out.append(NegotiationPoint(key="esop_details", ask="Ask for the ESOP grant details: vesting schedule, strike price and exit terms.",
                                    why=f"{inr(s.esop_value)} a year of the CTC is equity, not cash."))
    if flagged & {"no_breakup", "ctc_mismatch"}:
        out.append(NegotiationPoint(key="breakup", ask="Ask HR for a complete, itemised salary breakup.",
                                    why="The letter's breakup is missing or doesn't add up to the CTC."))
    if s.joining_bonus <= 0:
        out.append(NegotiationPoint(key="joining_bonus", ask="Ask whether a joining bonus is possible.",
                                    why="It can offset a bonus or notice-period buyout you give up by leaving your current job."))
    return out


SYSTEM = """You write short, courteous salary negotiation emails for Indian job candidates to send to a recruiter or HR.
Tone: grateful for the offer, confident, specific, never demanding or apologetic. 120 to 200 words.
Include ONLY the requests listed under ASKS, in that order, each in one or two sentences. Do not add other requests.
Copy rupee amounts exactly as written in the data. Never invent figures, competing offers, deadlines or personal facts.
Do not mention tax regimes, calculations, this tool or any AI. Plain text only: no markdown, no bullet symbols.
Reply in exactly this format:
Subject: <subject line>

<email body, ending with a sign-off and the candidate's name>"""


def _template(r: CalculationResult, points: list[NegotiationPoint], name: str) -> NegotiationEmail:
    s = r.structure
    role = f" for the {s.role} role" if s.role else ""
    company = s.company or "the company"
    asks = "\n".join(f"{i}. {p.ask} {p.why}".strip() for i, p in enumerate(points, 1))
    body = (
        f"Dear Hiring Team,\n\nThank you for the offer{role} at {company}. I'm excited about the opportunity and "
        f"would like to discuss a few points before accepting:\n\n{asks}\n\n"
        f"I'd be glad to talk these through at your convenience. Thank you again for your time and the offer.\n\n"
        f"Best regards,\n{name}"
    )
    return NegotiationEmail(subject=f"Offer{role}: a few points to discuss", body=body, method="template")


def negotiation_email(r: CalculationResult, points: list[NegotiationPoint], goal: str | None,
                      candidate_name: str | None) -> NegotiationEmail:
    name = (candidate_name or "").strip() or "[Your name]"
    if not points:
        points = [NegotiationPoint(key="fixed_pay", ask="Ask whether the fixed pay can be raised.", why="")]
    asks = [{"ask": p.ask, "reason": p.why} for p in points]
    prompt = (
        f"CANDIDATE NAME: {name}\nCOMPANY: {r.structure.company or 'unknown'}\nROLE: {r.structure.role or 'unknown'}\n\n"
        f"ASKS:\n{json.dumps(asks, ensure_ascii=False)}\n\n"
        + (f"CANDIDATE'S OWN GOAL (weave it in politely, without adding numbers it doesn't state):\n{goal}\n\n" if goal else "")
        + f"DATA:\n{json.dumps(facts(r), ensure_ascii=False)}"
    )
    try:
        text = verified_chat(
            [{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}],
            allowed_amounts([r], prompt),
            temperature=0.4,
            max_tokens=900,
        )
    except AIUnavailable:
        text = None
    m = re.match(r"\s*Subject:\s*(.+?)\s*\n+(.*)", text or "", re.S)
    if not m:
        return _template(r, points, name)
    return NegotiationEmail(subject=m.group(1).strip(), body=m.group(2).strip(), method="ai")
