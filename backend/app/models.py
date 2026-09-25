import secrets
from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _public_id() -> str:
    """Unguessable offer ID for URLs (16 URL-safe chars, ~96 bits)."""
    return secrets.token_urlsafe(12)


class Offer(Base):
    # "offers" held the pre-privacy schema (integer IDs, no owner); this table replaces it
    __tablename__ = "offer_records"

    id: Mapped[str] = mapped_column(String(24), primary_key=True, default=_public_id)
    owner_id: Mapped[str] = mapped_column(String(64), index=True)
    label: Mapped[str] = mapped_column(String(200))
    company: Mapped[str | None] = mapped_column(String(200))
    role: Mapped[str | None] = mapped_column(String(200))
    source: Mapped[str] = mapped_column(String(20))  # pdf | text | manual
    filename: Mapped[str | None] = mapped_column(String(300))
    raw_text: Mapped[str | None] = mapped_column(Text)
    extraction_meta: Mapped[dict] = mapped_column(JSON, default=dict)
    structure: Mapped[dict] = mapped_column(JSON)
    assumptions: Mapped[dict] = mapped_column(JSON)
    result: Mapped[dict] = mapped_column(JSON)
    explanation: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)


class Counter(Base):
    """Simple named counters, e.g. activity since the last automatic cleanup."""

    __tablename__ = "counters"

    name: Mapped[str] = mapped_column(String(50), primary_key=True)
    value: Mapped[int] = mapped_column(Integer, default=0)
