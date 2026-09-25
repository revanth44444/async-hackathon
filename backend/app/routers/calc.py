from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.deps import client_id
from app.engine import tax as rules
from app.engine.calculator import calculate
from app.engine.flags import red_flags
from app.engine.insights import CompareResult, CompareRow, SimulationResult, compare_metrics, simulate
from app.engine.schemas import Assumptions, CalculationResult, SalaryStructure
from app.models import Offer
from app.services.cleanup import record_activity
from app.routers.offers import refresh
from app.services.explain import compare_verdict

router = APIRouter(prefix="/api", tags=["calculator"])


class CalcRequest(BaseModel):
    structure: SalaryStructure
    assumptions: Assumptions = Field(default_factory=Assumptions)


class SimulateRequest(BaseModel):
    offer_id: str | None = None
    structure: SalaryStructure | None = None  # used when offer_id is not given
    assumptions: Assumptions = Field(default_factory=Assumptions)
    hike_pct: float = Field(0, ge=-50, le=300)
    overrides: dict[str, float] = Field(default_factory=dict)


class CompareRequest(BaseModel):
    offer_ids: list[str] = Field(min_length=2, max_length=4)
    assumptions: Assumptions | None = None  # apply the same assumptions to all offers for a fair comparison
    ai_verdict: bool = True


@router.get("/meta")
def meta():
    return {
        "ai_enabled": settings.ai_enabled,
        "model": settings.groq_model if settings.ai_enabled else None,
        "tax_year": "FY 2025-26",
        "states": sorted(k for k in rules.PROFESSIONAL_TAX if k != "OTHER") + ["OTHER"],
    }


@router.post("/calculate", response_model=CalculationResult)
def calc(body: CalcRequest):
    return calculate(body.structure, body.assumptions)


@router.post("/simulate", response_model=SimulationResult)
def simulate_endpoint(body: SimulateRequest, owner: str = Depends(client_id), db: Session = Depends(get_db)):
    if body.offer_id is not None:
        o = db.get(Offer, body.offer_id)
        if not o or o.owner_id != owner:
            raise HTTPException(404, "Offer not found")
        refresh(o, db)
        s, base_a = SalaryStructure(**o.structure), Assumptions(**o.assumptions)
    elif body.structure:
        s, base_a = body.structure, body.assumptions
    else:
        raise HTTPException(422, "Provide offer_id or structure")
    unknown = set(body.overrides) - set(SalaryStructure.model_fields)
    if unknown:
        raise HTTPException(422, f"Unknown fields in overrides: {sorted(unknown)}")
    return simulate(s, base_a, body.assumptions, body.hike_pct, body.overrides)


@router.post("/compare", response_model=CompareResult)
def compare(body: CompareRequest, owner: str = Depends(client_id), db: Session = Depends(get_db)):
    rows: list[CompareRow] = []
    for oid in dict.fromkeys(body.offer_ids):
        o = db.get(Offer, oid)
        if not o or o.owner_id != owner:
            raise HTTPException(404, "Offer not found")
        refresh(o, db)
        a = body.assumptions or Assumptions(**o.assumptions)
        r = calculate(SalaryStructure(**o.structure), a)
        meta = o.extraction_meta or {}
        report = red_flags(r, o.raw_text or "", meta.get("notes"), bool(meta.get("estimated_split")))
        rows.append(CompareRow(offer_id=o.id, label=o.label, result=r, red_flags=report))
    if len(rows) < 2:
        raise HTTPException(422, "Pick at least two different offers")
    result = compare_metrics(rows)
    if body.ai_verdict:
        winners, suits = result.winners(), result.suitability()
        result.verdict = compare_verdict([(r.label, r.result) for r in rows], winners, suits)
    record_activity(db)
    db.commit()
    return result
