from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.deps import client_id
from app.engine.calculator import calculate, complete_structure
from app.engine.insights import Suggestion, suggestions
from app.engine.schemas import Assumptions, CalculationResult, SalaryStructure
from app.models import Offer
from app.services.cleanup import record_activity
from app.services.explain import answer_question, explain_offer
from app.services.extraction import extract_structure
from app.services.pdf import PDFError, extract_text

router = APIRouter(prefix="/api/offers", tags=["offers"])


class OfferSummary(BaseModel):
    id: str
    label: str
    company: str | None
    role: str | None
    source: str
    ctc: float
    monthly_in_hand: float
    annual_take_home: float
    created_at: datetime


class OfferDetail(OfferSummary):
    filename: str | None
    structure: SalaryStructure
    assumptions: Assumptions
    result: CalculationResult
    extraction_meta: dict
    explanation: str | None
    suggestions: list[Suggestion]
    has_raw_text: bool


class ManualCreate(BaseModel):
    label: str | None = None
    structure: SalaryStructure
    assumptions: Assumptions = Field(default_factory=Assumptions)


class TextCreate(BaseModel):
    text: str = Field(min_length=50, max_length=100_000)
    label: str | None = None


class OfferUpdate(BaseModel):
    label: str | None = None
    structure: SalaryStructure | None = None
    assumptions: Assumptions | None = None


class Question(BaseModel):
    question: str = Field(min_length=3, max_length=500)


def _summary(o: Offer) -> OfferSummary:
    return OfferSummary(
        id=o.id,
        label=o.label,
        company=o.company,
        role=o.role,
        source=o.source,
        ctc=o.result["structure"]["ctc"],
        monthly_in_hand=o.result["monthly_in_hand"],
        annual_take_home=o.result["annual_take_home"],
        created_at=o.created_at,
    )


def _detail(o: Offer) -> OfferDetail:
    s, a = SalaryStructure(**o.structure), Assumptions(**o.assumptions)
    return OfferDetail(
        **_summary(o).model_dump(),
        filename=o.filename,
        structure=s,
        assumptions=a,
        result=CalculationResult(**o.result),
        extraction_meta=o.extraction_meta or {},
        explanation=o.explanation,
        suggestions=suggestions(s, a),
        has_raw_text=bool(o.raw_text),
    )


def _apply(o: Offer, s: SalaryStructure, a: Assumptions) -> None:
    result = calculate(s, a)
    o.structure = result.structure.model_dump()
    o.assumptions = a.model_dump()
    o.result = result.model_dump(mode="json")
    o.company, o.role = s.company, s.role
    o.explanation = None  # numbers changed, so the old explanation is stale


SAMPLES = {"nimbus": "nimbus_offer.pdf", "quantora": "quantora_offer.pdf"}
SAMPLES_DIR = Path(__file__).resolve().parents[2] / "samples"


def _record_estimates(meta: dict, estimates: list[dict]) -> None:
    """Store what was guessed so the page and the AI explanation can say so plainly."""
    meta["estimates"] = estimates
    meta["estimated_split"] = any(e["kind"] in ("split", "gross") for e in estimates)


def _get(db: Session, offer_id: str, owner: str) -> Offer:
    o = db.get(Offer, offer_id)
    if not o or o.owner_id != owner:  # same 404 either way, so IDs can't be probed
        raise HTTPException(404, "Offer not found")
    return o


def _create_from_text(db: Session, owner: str, text: str, source: str, label: str | None, filename: str | None) -> Offer:
    structure, meta = extract_structure(text)
    structure, estimates = complete_structure(structure, meta.get("stated_gross_annual") or 0)
    if structure.ctc <= 0 and structure.basic <= 0 and structure.special_allowance <= 0:
        raise HTTPException(
            422,
            "We couldn't find a CTC, gross salary or salary breakup in this document. "
            "Try pasting the compensation section, or enter your CTC manually.",
        )
    _record_estimates(meta, estimates)
    record_activity(db)
    a = Assumptions(state=meta.get("state") or "KA", metro=meta.get("metro", False))
    default_label = " · ".join(x for x in (structure.company, structure.role) if x) or (filename or "Untitled offer")
    o = Offer(
        owner_id=owner,
        label=label or default_label,
        source=source,
        filename=filename,
        raw_text=text,
        extraction_meta=meta,
    )
    _apply(o, structure, a)
    db.add(o)
    db.commit()
    return o


@router.get("", response_model=list[OfferSummary])
def list_offers(owner: str = Depends(client_id), db: Session = Depends(get_db)):
    q = select(Offer).where(Offer.owner_id == owner).order_by(Offer.created_at.desc())
    return [_summary(o) for o in db.scalars(q)]


@router.post("/upload", response_model=OfferDetail, status_code=201)
async def upload_offer(
    file: UploadFile = File(...),
    label: str | None = Form(None),
    owner: str = Depends(client_id),
    db: Session = Depends(get_db),
):
    data = await file.read()
    if len(data) > settings.max_upload_mb * 1024 * 1024:
        raise HTTPException(413, f"File too large (max {settings.max_upload_mb} MB)")
    name = file.filename or "offer"
    if name.lower().endswith((".txt", ".md")):
        text = data.decode("utf-8", errors="ignore")
    elif data[:4] == b"%PDF":
        try:
            text = extract_text(data)
        except PDFError as exc:
            raise HTTPException(422, str(exc)) from exc
    else:
        raise HTTPException(415, "Upload a PDF or .txt offer letter")
    # The PDF bytes are only held in memory for this request; just the extracted text is stored
    return _detail(_create_from_text(db, owner, text, "pdf", label, name))


@router.post("/text", response_model=OfferDetail, status_code=201)
def create_from_text(body: TextCreate, owner: str = Depends(client_id), db: Session = Depends(get_db)):
    return _detail(_create_from_text(db, owner, body.text, "text", body.label, None))


@router.post("/sample/{name}", response_model=OfferDetail, status_code=201)
def create_sample(name: str, owner: str = Depends(client_id), db: Session = Depends(get_db)):
    """Loads one of the fictional demo letters into this visitor's private space."""
    if name not in SAMPLES:
        raise HTTPException(404, "Unknown sample")
    text = extract_text((SAMPLES_DIR / SAMPLES[name]).read_bytes())
    return _detail(_create_from_text(db, owner, text, "sample", None, SAMPLES[name]))


@router.post("", response_model=OfferDetail, status_code=201)
def create_manual(body: ManualCreate, owner: str = Depends(client_id), db: Session = Depends(get_db)):
    s = body.structure
    meta: dict = {"method": "manual"}
    s, estimates = complete_structure(s)
    _record_estimates(meta, estimates)
    record_activity(db)
    o = Offer(owner_id=owner, label=body.label or s.company or "Manual offer", source="manual", extraction_meta=meta)
    _apply(o, s, body.assumptions)
    db.add(o)
    db.commit()
    return _detail(o)


@router.get("/{offer_id}", response_model=OfferDetail)
def get_offer(offer_id: str, owner: str = Depends(client_id), db: Session = Depends(get_db)):
    return _detail(_get(db, offer_id, owner))


@router.put("/{offer_id}", response_model=OfferDetail)
def update_offer(offer_id: str, body: OfferUpdate, owner: str = Depends(client_id), db: Session = Depends(get_db)):
    o = _get(db, offer_id, owner)
    if body.label:
        o.label = body.label
    if body.structure or body.assumptions:
        s = body.structure or SalaryStructure(**o.structure)
        if body.structure:
            # Values the user typed are kept as-is; only a fully empty breakup is re-estimated
            s, estimates = complete_structure(s) if sum(getattr(s, k) for k in ("basic", "hra", "special_allowance")) <= 0 else (s, [])
            meta = dict(o.extraction_meta or {})
            _record_estimates(meta, estimates)
            o.extraction_meta = meta
        _apply(o, s, body.assumptions or Assumptions(**o.assumptions))
    db.commit()
    return _detail(o)


@router.delete("/{offer_id}", status_code=204)
def delete_offer(offer_id: str, owner: str = Depends(client_id), db: Session = Depends(get_db)):
    db.delete(_get(db, offer_id, owner))
    db.commit()


@router.post("/{offer_id}/explain")
def explain(offer_id: str, refresh: bool = False, owner: str = Depends(client_id), db: Session = Depends(get_db)):
    o = _get(db, offer_id, owner)
    if o.explanation and not refresh:
        return {"explanation": o.explanation, "cached": True}
    meta = o.extraction_meta or {}
    notes = [e["message"] for e in meta.get("estimates", [])] + (meta.get("notes") or [])
    text, method = explain_offer(CalculationResult(**o.result), notes)
    if method == "ai":  # don't cache the fallback, so adding a key later upgrades it
        o.explanation = text
        db.commit()
    return {"explanation": text, "method": method, "cached": False}


@router.post("/{offer_id}/ask")
def ask(offer_id: str, body: Question, owner: str = Depends(client_id), db: Session = Depends(get_db)):
    o = _get(db, offer_id, owner)
    return {"answer": answer_question(CalculationResult(**o.result), body.question, o.raw_text)}
