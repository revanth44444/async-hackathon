# OfferLens: know your real salary

Upload an offer letter and OfferLens will:

- read the CTC structure from it
- calculate your real monthly in-hand pay under both Indian tax regimes
- explain every component in plain English
- let you simulate what-ifs (hike, rent, variable payout, regime, deductions)
- compare offers side by side

**Design principle: AI reads, Python calculates.** The LLM (Groq) only extracts and classifies line items and writes explanations. Every rupee on screen comes from a deterministic, unit-tested tax engine, so the numbers are reproducible and auditable.

```
┌──────────────┐  REST/JSON  ┌────────────────────────────── FastAPI ─────────────────────────────┐
│  Next.js 16  │ ──────────▶ │ PDF (pdfplumber) → Groq extraction → SalaryStructure               │
│  React 19    │             │                    (regex fallback)     │                           │
│  Tailwind 4  │ ◀────────── │                                         ▼                           │
│  Recharts    │             │  Deterministic engine (FY 2025-26) → CalculationResult → Postgres   │
└──────────────┘             │  Groq explanation / Q&A / compare verdict (numbers passed in)       │
                             └─────────────────────────────────────────────────────────────────────┘
```

## Features

| Feature | Where |
|---|---|
| PDF / text / manual input, with table-aware PDF extraction | `backend/app/services/pdf.py`, `extraction.py` |
| AI line-item classification, summed in Python | `extraction.py` (`_extract_ai`, `_aggregate`) |
| Works without an API key (keyword/regex parser) | `extraction.py` (`_extract_heuristic`) |
| FY25-26 slabs, 87A rebate + marginal relief, surcharge + marginal relief, 4% cess | `backend/app/engine/tax.py` |
| Take-home: employee PF, professional tax by state, HRA exemption, 80C/80D/24(b)/80CCD | `backend/app/engine/calculator.py` |
| Old vs new regime with auto-recommendation | `calculator.py` |
| Every CTC rupee reconciled into buckets (donut chart) | `ctc_buckets` |
| What-if simulator: hike %, payout %, rent, city, regime, deductions | `engine/insights.py` → `POST /api/simulate` |
| Deterministic tax-saving suggestions (corporate NPS, 80C, variable risk) | `insights.py` (`suggestions`) |
| Offer comparison + AI verdict | `POST /api/compare` |
| Plain-English explanation + "ask about this offer" chat | `services/explain.py` |
| Editable extracted values ("Fix values"), with recalculation | `PUT /api/offers/{id}` |

## Run locally

**Backend** (Python 3.11+)

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # add GROQ_API_KEY; remove DATABASE_URL to use SQLite
docker compose up -d db         # optional: PostgreSQL (from repo root)
uvicorn app.main:app --reload --port 8000
```

API docs: http://localhost:8000/docs

**Frontend**

```bash
cd frontend
npm install
cp .env.example .env.local
npm run dev                     # http://localhost:3000
```

**Demo data:** `python backend/samples/make_samples.py` generates two fictional offer letters (`nimbus_offer.pdf`, `quantora_offer.pdf`). Quantora's ₹25.77L "CTC" includes ₹6.36L/yr of ESOPs. It's a good demo of headline CTC versus real cash.

**Tests:** `cd backend && pytest` (engine tax cases + full API flow).

## REST API

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/offers/upload` | multipart PDF/.txt → extracted + calculated offer |
| POST | `/api/offers/text` | `{text}` → offer |
| POST | `/api/offers` | `{structure, assumptions}` manual entry |
| GET | `/api/offers`, `/api/offers/{id}` | list / detail (incl. suggestions) |
| PUT | `/api/offers/{id}` | fix values or change assumptions → recalculated |
| DELETE | `/api/offers/{id}` | delete |
| POST | `/api/offers/{id}/explain` | AI (or template) explanation, cached |
| POST | `/api/offers/{id}/ask` | `{question}` → AI answer grounded in computed numbers |
| POST | `/api/calculate` | stateless calculation |
| POST | `/api/simulate` | `{offer_id, assumptions, hike_pct, overrides}` → baseline, scenario, delta |
| POST | `/api/compare` | `{offer_ids[2-4]}` → side-by-side + AI verdict |
| GET | `/api/meta`, `/api/health` | AI status, states, tax year |

## Assumptions and limits

- FY 2025-26 (AY 2026-27) rules for resident salaried individuals under 60.
- Monthly in-hand = fixed pay − employee PF − professional tax − (tax on fixed pay ÷ 12). Variable pay is shown in the annual figure at the chosen payout %.
- Employee PF = the employer PF figure from the letter (else 12% of basic). The capped ₹1,800/month option is available.
- HRA metro = Mumbai, Delhi, Kolkata, Chennai only (Bengaluru, Hyderabad and Pune count as 40%).
- LTA is treated as taxable, and professional tax uses approximate state slabs. Estimates only, not tax advice.

## Deploy

- **Frontend:** Vercel (root `frontend`, env `NEXT_PUBLIC_API_URL`).
- **Backend:** Render/Railway/Fly (`uvicorn app.main:app --host 0.0.0.0 --port $PORT`, env `GROQ_API_KEY`, `DATABASE_URL`, `CORS_ORIGINS=<vercel url>`).
- **DB:** Neon/Supabase Postgres. `postgres://` URLs are handled automatically.
