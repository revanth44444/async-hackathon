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
        assert cmp["verdict"].startswith("### The trade-offs") and "### Where each offer leads" in cmp["verdict"]

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


# Fictional letter with a retention bonus, RSU grant, service bond and long notice period
ORBITRA = """Offer of Employment - Orbitra Fintech Pvt Ltd, Hyderabad
Your total Cost to Company is Rs. 22,00,000 per annum.
Basic: Rs 75,000 per month
HRA: Rs 30,000 per month
Special Allowance: Rs 42,500 per month
Employer PF: Rs 1,800 per month
Gratuity: Rs 43,290
Group Health Insurance premium: Rs 15,000
Performance bonus (target, up to 15% of fixed): Rs 1,62,110
Retention bonus of Rs 1,00,000 payable after completing 18 months.
You will be granted RSUs worth Rs 8,00,000 vesting over 4 years.
A service bond of 2 years applies; leaving earlier requires repayment of training costs of Rs 2,00,000. Notice period is 90 days."""


def test_retention_bonus_is_conditional_and_not_in_year_one():
    with TestClient(app, headers=ME) as c:
        d = c.post("/api/offers/text", json={"text": ORBITRA}).json()
        s, r = d["structure"], d["result"]
        assert s["retention_bonus"] == 100_000 and s["retention_after_months"] == 18 and s["joining_bonus"] == 0
        assert r["year_one_take_home"] == r["annual_take_home"]
        comp = {x["key"]: x for x in r["components"]}
        assert comp["retention_bonus"]["monthly"] is None and "18 months" in comp["retention_bonus"]["description"]
        assert comp["gratuity"]["monthly"] is None
        assert s["esop_value"] == 200_000
        assert any("more than the stated CTC" in w for w in r["warnings"])


def test_red_flags_and_negotiation_email():
    with TestClient(app, headers=ME) as c:
        d = c.post("/api/offers/text", json={"text": ORBITRA}).json()
        keys = {f["key"] for f in d["red_flags"]["flags"]}
        assert {"service_bond", "notice_period", "retention_conditional", "esop_in_ctc", "ctc_mismatch"} <= keys
        assert 0 <= d["red_flags"]["score"] < 80 and d["red_flag_score"] == d["red_flags"]["score"]
        points = {p["key"] for p in d["negotiation_points"]}
        assert {"fixed_pay", "service_bond", "notice_period", "retention_schedule"} <= points
        e = c.post(f"/api/offers/{d['id']}/negotiation-email",
                   json={"points": ["service_bond", "notice_period"], "candidate_name": "Asha"}).json()
        assert e["method"] == "template" and "Asha" in e["body"]
        assert "service bond" in e["body"] and "notice period" in e["body"] and "fixed pay" not in e["body"]
        listed = next(o for o in c.get("/api/offers").json() if o["id"] == d["id"])
        assert listed["red_flag_level"] == d["red_flags"]["level"]
        other = TestClient(app, headers=OTHER)
        assert other.post(f"/api/offers/{d['id']}/negotiation-email", json={}).status_code == 404


def test_loading_a_sample_twice_reuses_it():
    with TestClient(app, headers={"X-Client-Id": "test-client-cccccccccccc"}) as c:
        first = c.post("/api/offers/sample/quantora").json()
        again = c.post("/api/offers/sample/quantora").json()
        assert first["id"] == again["id"]
        assert first["structure"]["esop_value"] == 636_000


def test_stale_esop_grant_is_corrected_on_read():
    from app.db import SessionLocal
    from app.models import Offer
    with TestClient(app, headers=ME) as c:
        d = c.post("/api/offers/text", json={"text": ORBITRA}).json()
        with SessionLocal() as db:  # simulate an offer saved before the ESOP fix
            o = db.get(Offer, d["id"])
            o.structure = {**o.structure, "esop_value": 800_000}
            db.commit()
        assert c.get(f"/api/offers/{d['id']}").json()["structure"]["esop_value"] == 200_000


# Fictional letter: 60-day notice, non-compete, joining bonus clawback
KESTREL = """Letter of Offer - Kestrel Retail Pvt Ltd, Mumbai
Dear Rohan Mehta, we are delighted to offer you the position of Associate Consultant.
Annual CTC: Rs 9,60,000
Basic Salary: 3,84,000
House Rent Allowance: 1,92,000
Meal Coupons: 26,400
Special Allowance: 2,57,530
Employer Contribution to PF: 21,600
Gratuity: 18,470
Annual Performance Incentive (target): 60,000
In addition, you will receive a one-time joining bonus of Rs 75,000 with your first salary. The joining bonus is recoverable in full if you resign within 12 months of joining.
Notice period: 2 months. You agree to a non-compete for 12 months after leaving the company."""


def test_sixty_day_notice_is_not_a_red_flag_and_advice_never_repeats_the_letter():
    with TestClient(app, headers=ME) as c:
        d = c.post("/api/offers/text", json={"text": KESTREL}).json()
        flags = {f["key"]: f for f in d["red_flags"]["flags"]}
        assert "notice_period" not in flags and "non_compete" in flags
        assert d["red_flags"]["notice_days"] == 60
        claw = flags["joining_clawback"]["detail"]
        assert "joining.” Ask" in claw  # the quotation closes with a full stop
        points = {p["key"]: p for p in d["negotiation_points"]}
        assert points["notice_period"]["ask"] == "Ask to reduce the notice period to 30 days."
        assert "non-compete" in points["non_compete"]["ask"]


def test_questions_get_the_offer_red_flags_as_known_risks(monkeypatch):
    import app.services.explain as ex
    seen = {}

    def fake_chat(messages, **kw):
        seen["prompt"] = messages[-1]["content"]
        seen["system"] = messages[0]["content"]
        return "Noted."
    monkeypatch.setattr(ex, "chat", fake_chat)
    with TestClient(app, headers=ME) as c:
        d = c.post("/api/offers/text", json={"text": KESTREL}).json()
        c.post(f"/api/offers/{d['id']}/ask", json={"question": "If I quit after 8 months to join a competitor, what do I lose?"})
    assert "KNOWN RISKS IN THIS OFFER" in seen["prompt"] and "Non-compete" in seen["prompt"]
    assert "forfeited if you leave before the payout date" in seen["prompt"]
    assert "never say something is the only thing you lose" in seen["system"]


def test_manual_entry_reads_state_from_city_or_explicit_choice():
    with TestClient(app, headers=ME) as c:
        d = c.post("/api/offers", json={"structure": {"ctc": 1_200_000, "location": "Mumbai"}}).json()
        assert d["assumptions"]["state"] == "MH" and d["assumptions"]["metro"] is True
        assert d["result"]["professional_tax"] == 2_500
        d = c.post("/api/offers", json={"structure": {"ctc": 1_200_000, "location": "Kolkata"},
                                        "assumptions": {"state": "TN"}}).json()
        assert d["assumptions"]["state"] == "TN"


def test_compare_reports_ties_instead_of_picking_one():
    with TestClient(app, headers=ME) as c:
        s = {"ctc": 900_000, "basic": 360_000, "hra": 180_000, "special_allowance": 338_400, "employer_pf": 21_600}
        a = c.post("/api/offers", json={"structure": s}).json()
        b = c.post("/api/offers", json={"structure": {**s, "ctc": 1_000_000, "special_allowance": 438_400}}).json()
        cmp = c.post("/api/compare", json={"offer_ids": [a["id"], b["id"]]}).json()
        assert cmp["best_retirement"] is None and cmp["lowest_tax"] is None  # same PF, both ₹0 tax
        assert cmp["best_monthly_in_hand"] == b["id"]
        assert "Tied on most retirement savings" in cmp["verdict"] and "Tied on lowest income tax" in cmp["verdict"]


def test_letter_with_ctc_and_monthly_gross_uses_the_gross():
    text = ("Congratulations! We are happy to offer you the Software Engineer role at Zentrix Labs Pvt Ltd, Chennai. "
            "Your annual CTC will be Rs 12,00,000. Your monthly gross salary will be Rs 81,000.")
    with TestClient(app, headers=ME) as c:
        d = c.post("/api/offers/text", json={"text": text}).json()
        s = d["structure"]
        assert s["basic"] + s["hra"] + s["special_allowance"] == 972_000
        assert d["extraction_meta"]["estimated_split"] is True
        assert d["result"]["monthly_in_hand"] < 81_000 - 3_888 + 1
