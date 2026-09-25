"""Generate two fictional offer-letter PDFs for demos: `python samples/make_samples.py`."""
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

OUT = Path(__file__).parent
styles = getSampleStyleSheet()

OFFERS = {
    "nimbus_offer.pdf": {
        "company": "Nimbus Cloud Technologies Pvt Ltd",
        "role": "Software Engineer II",
        "city": "Bengaluru",
        "intro": "We are delighted to offer you the position of Software Engineer II at Nimbus Cloud Technologies Pvt Ltd, "
        "based out of our Bengaluru office. Your annual Cost to Company (CTC) will be Rs. 18,00,000.",
        "rows": [
            ("Basic Salary", 60000),
            ("House Rent Allowance (HRA)", 30000),
            ("Special Allowance", 35088),
            ("Employer PF Contribution", 7200),
            ("Gratuity", 2886),
            ("Group Medical Insurance", 1493),
        ],
        "variable": ("Annual Performance Bonus (target)", 160000),
        "extra": "You will receive a one-time joining bonus of Rs. 1,00,000, payable with your first salary. "
        "The joining bonus must be repaid in full if you leave within 12 months of joining. Notice period: 60 days.",
    },
    "quantora_offer.pdf": {
        "company": "Quantora Labs Pvt Ltd",
        "role": "Backend Engineer",
        "city": "Mumbai",
        "intro": "Further to your interviews, we are pleased to offer you the role of Backend Engineer at Quantora Labs Pvt Ltd, "
        "Mumbai. Your total annual CTC is Rs. 25,77,000 including variable pay and ESOPs.",
        "rows": [
            ("Basic Salary", 55000),
            ("House Rent Allowance (HRA)", 27500),
            ("Special Allowance", 38650),
            ("Meal Card", 2200),
            ("Employer PF Contribution", 1800),
            ("Employer NPS Contribution", 5500),
            ("Gratuity", 2645),
            ("Health & Term Insurance", 2205),
        ],
        "variable": ("Variable Pay (target, paid annually)", 315000),
        "extra": "You will also be granted ESOPs worth Rs. 25,44,000 vesting over 4 years (25% per year, 1-year cliff). "
        "Notice period: 90 days.",
    },
}


def build(name: str, o: dict) -> None:
    doc = SimpleDocTemplate(str(OUT / name), pagesize=A4, topMargin=50)
    story = [
        Paragraph(o["company"], styles["Title"]),
        Paragraph("Offer of Employment", styles["Heading2"]),
        Spacer(1, 8),
        Paragraph("Dear Aarav Mehta,", styles["Normal"]),
        Spacer(1, 6),
        Paragraph(o["intro"], styles["Normal"]),
        Spacer(1, 12),
        Paragraph("Annexure A — Compensation Structure", styles["Heading3"]),
    ]
    rows = [["Component", "Monthly (Rs.)", "Annual (Rs.)"]]
    for label, monthly in o["rows"]:
        rows.append([label, f"{monthly:,}", f"{monthly * 12:,}"])
    fixed_total = sum(m * 12 for _, m in o["rows"])
    rows.append(["Total Fixed Compensation", "", f"{fixed_total:,}"])
    vlabel, vamt = o["variable"]
    rows.append([vlabel, "", f"{vamt:,}"])
    rows.append(["Total Cost to Company (CTC)", "", f"{fixed_total + vamt:,}"])
    t = Table(rows, colWidths=[250, 100, 110])
    t.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8eefc")),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
                ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
            ]
        )
    )
    story += [
        t,
        Spacer(1, 12),
        Paragraph(o["extra"], styles["Normal"]),
        Spacer(1, 18),
        Paragraph("Warm regards,<br/>Talent Acquisition Team", styles["Normal"]),
    ]
    doc.build(story)
    print("wrote", OUT / name, "CTC", fixed_total + vamt)


if __name__ == "__main__":
    for n, o in OFFERS.items():
        build(n, o)
