import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import models  # noqa: F401  (registers tables)
from app.config import settings
from app.db import Base, engine
from app.routers import calc, offers

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(engine)
    yield


app = FastAPI(
    title="OfferLens API",
    description="Offer letter → CTC structure → take-home pay. AI reads, Python calculates.",
    version="1.0.0",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
    allow_origin_regex=settings.cors_origin_regex,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(offers.router)
app.include_router(calc.router)


@app.get("/api/health")
def health():
    return {"status": "ok", "ai_enabled": settings.ai_enabled, "db": engine.dialect.name}
