import os
import tempfile
from pathlib import Path

# Isolated DB and no AI for deterministic tests; must be set before the app is imported
os.environ["DATABASE_URL"] = f"sqlite:///{tempfile.mkdtemp()}/test.db"
os.environ["GROQ_API_KEY"] = ""

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

SAMPLES = Path(__file__).parent.parent / "samples"
ME = {"X-Client-Id": "test-client-aaaaaaaaaaaa"}
OTHER = {"X-Client-Id": "test-client-bbbbbbbbbbbb"}


def test_full_flow():
    with TestClient(app, headers=ME) as c:
        with open(SAMPLES / "nimbus_offer.pdf", "rb") as f:
            r = c.post("/api/offers/upload", files={"file": ("nimbus_offer.pdf", f, "application/pdf")})
        assert r.status_code == 201, r.text
        a = r.json()
        assert a["structure"]["basic"] == 720_000
        assert a["structure"]["joining_bonus"] == 100_000
        assert a["assumptions"]["state"] == "KA"
        assert a["result"]["warnings"] == []

        b = c.post("/api/offers", json={"structure": {"ctc": 2_400_000, "basic": 960_000, "special_allowance": 1_440_000}}).json()

        cmp = c.post("/api/compare", json={"offer_ids": [a["id"], b["id"]]}).json()
        assert cmp["best_monthly_in_hand"] == b["id"]
        assert cmp["verdict"].startswith("### Where each offer leads")  # deterministic fallback without AI

        sim = c.post("/api/simulate", json={"offer_id": a["id"], "hike_pct": 10}).json()
        assert sim["delta"]["monthly_in_hand"] > 0

        upd = c.put(f"/api/offers/{a['id']}", json={"assumptions": {**a["assumptions"], "variable_payout_pct": 0}}).json()
        assert upd["result"]["annual_take_home"] < a["result"]["annual_take_home"]

        exp = c.post(f"/api/offers/{a['id']}/explain").json()
        assert exp["method"] == "template" and "in-hand" in exp["explanation"]

        assert c.delete(f"/api/offers/{b['id']}").status_code == 204
        assert c.get(f"/api/offers/{b['id']}").status_code == 404


def test_rejects_non_pdf():
    with TestClient(app, headers=ME) as c:
        r = c.post("/api/offers/upload", files={"file": ("x.png", b"\x89PNG....", "image/png")})
        assert r.status_code == 415


def test_cleanup_after_n_activities(monkeypatch):
    from app.config import settings
    from app.db import SessionLocal
    from app.models import Counter, Offer

    monkeypatch.setattr(settings, "cleanup_every", 3)
    with SessionLocal() as db:  # start from a clean slate
        db.query(Offer).delete()
        db.query(Counter).delete()
        db.commit()

    manual = {"structure": {"ctc": 1_200_000, "basic": 480_000, "special_allowance": 720_000}}
    count = lambda c: len(c.get("/api/offers").json())  # noqa: E731
    with TestClient(app, headers=ME) as c:
        a = c.post("/api/offers", json=manual).json()  # activity 1
        b = c.post("/api/offers", json=manual).json()  # activity 2
        assert count(c) == 2
        r = c.post("/api/compare", json={"offer_ids": [a["id"], b["id"]], "ai_verdict": False})  # 3 → wipe
        assert r.status_code == 200 and len(r.json()["rows"]) == 2  # comparison still returned
        assert count(c) == 0
        c.post("/api/offers", json=manual)  # 1
        c.post("/api/offers", json=manual)  # 2
        new = c.post("/api/offers", json=manual).json()  # 3 → wipe, then this offer is saved
        offers = c.get("/api/offers").json()
        assert [o["id"] for o in offers] == [new["id"]]


def test_offers_are_private_to_their_browser():
    manual = {"structure": {"ctc": 1_200_000, "basic": 480_000, "special_allowance": 720_000}}
    with TestClient(app, headers=ME) as me, TestClient(app, headers=OTHER) as other:
        mine = me.post("/api/offers", json=manual).json()
        assert len(mine["id"]) >= 16 and not mine["id"].isdigit()  # unguessable ID
        assert mine["id"] in [o["id"] for o in me.get("/api/offers").json()]
        assert mine["id"] not in [o["id"] for o in other.get("/api/offers").json()]
        assert other.get(f"/api/offers/{mine['id']}").status_code == 404
        assert other.delete(f"/api/offers/{mine['id']}").status_code == 404
        assert other.post("/api/simulate", json={"offer_id": mine["id"]}).status_code == 404
        theirs = other.post("/api/offers", json=manual).json()
        assert other.post("/api/compare", json={"offer_ids": [mine["id"], theirs["id"]]}).status_code == 404
    with TestClient(app) as anon:
        assert anon.get("/api/offers").status_code == 400


def test_sample_letters_load_privately():
    with TestClient(app, headers=ME) as c:
        r = c.post("/api/offers/sample/nimbus")
        assert r.status_code == 201 and r.json()["source"] == "sample"
        assert c.post("/api/offers/sample/nope").status_code == 404


def test_letter_with_only_a_ctc_gets_an_estimated_split():
    # Fictional letter that states "Annual CTC ₹6,50,000" and nothing else
    with TestClient(app, headers=ME) as c, open(SAMPLES / "ctc_only_offer.pdf", "rb") as f:
        r = c.post("/api/offers/upload", files={"file": ("ctc_only_offer.pdf", f, "application/pdf")})
        assert r.status_code == 201, r.text
        d = r.json()
        assert d["structure"]["ctc"] == 650_000
        assert d["extraction_meta"]["estimated_split"] is True
        assert d["result"]["monthly_in_hand"] > 40_000
        assert d["result"]["warnings"] == []


def test_gross_only_and_empty_letters():
    with TestClient(app, headers=ME) as c:
        r = c.post("/api/offers/text", json={"text": "Offer from Orbit Labs Pvt Ltd. Your gross salary will be Rs 45,000 per month. Location: Hyderabad."})
        assert r.status_code == 201
        d = r.json()
        assert [e["kind"] for e in d["extraction_meta"]["estimates"]] == ["gross"]
        assert d["result"]["monthly_in_hand"] > 40_000
        r = c.post("/api/offers/text", json={"text": "Dear candidate, we are pleased to offer you a role. Compensation details will follow separately."})
        assert r.status_code == 422 and "CTC" in r.json()["detail"]
