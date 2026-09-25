import io

import pdfplumber


class PDFError(Exception):
    pass


class UnsupportedFile(PDFError):
    """Not a PDF, image or text file."""


class ScannedPDF(PDFError):
    """The PDF has no text layer: it's a scan or photo, so it needs OCR."""


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
        raise ScannedPDF("No text found in PDF. It may be a scanned image.")
    return text


IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".heic")


def read_document(data: bytes, filename: str) -> tuple[str, bool]:
    """Text from an uploaded offer letter or payslip: .txt/.md, PDF, or an image. Returns (text, used_ocr).
    Scanned PDFs and images are transcribed with the vision model; the file itself is never stored."""
    from app.services.groq_client import AIUnavailable
    from app.services.ocr import ocr_image, ocr_pdf

    name = filename.lower()
    if name.endswith((".txt", ".md")):
        return data.decode("utf-8", errors="ignore"), False
    try:
        if data[:4] == b"%PDF":
            try:
                return extract_text(data), False
            except ScannedPDF:
                return ocr_pdf(data), True
        if name.endswith(IMAGE_EXTS) or data[:3] == b"\xff\xd8\xff" or data[:8] == b"\x89PNG\r\n\x1a\n":
            return ocr_image(data), True
    except AIUnavailable as exc:
        raise PDFError("This looks like a scanned document or photo, and the text reader is unavailable right now. "
                       "Paste the text instead.") from exc
    except PDFError:
        raise
    except Exception as exc:  # corrupt image or PDF
        raise PDFError("We couldn't open this file. Try a clearer photo or PDF, or paste the text instead.") from exc
    raise UnsupportedFile("Upload a PDF, a photo of the letter, or a .txt file")
