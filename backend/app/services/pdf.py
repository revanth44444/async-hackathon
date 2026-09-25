import io

import pdfplumber


class PDFError(Exception):
    pass


def extract_text(data: bytes, max_pages: int = 15) -> str:
    """Pull text and tables out of an offer-letter PDF. Tables are flattened as 'a | b | c' rows,
    which keeps component/monthly/annual columns aligned for the extractor."""
    try:
        parts: list[str] = []
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            for page in pdf.pages[:max_pages]:
                parts.append(page.extract_text() or "")
                for table in page.extract_tables():
                    rows = [" | ".join((c or "").strip() for c in row) for row in table]
                    parts.append("[TABLE]\n" + "\n".join(rows))
    except Exception as exc:  # pdfplumber raises a variety of parser errors
        raise PDFError(f"Could not read PDF: {exc}") from exc

    text = "\n".join(p for p in parts if p.strip()).strip()
    if not text:
        raise PDFError("No text found in PDF. It may be a scanned image. Paste the text instead.")
    return text
