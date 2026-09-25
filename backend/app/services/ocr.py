"""Reads scanned PDFs and photos with a vision model, so image-only offer letters and payslips still work.

Pages are rendered to small greyscale JPEGs in memory and transcribed. Nothing is stored. The transcript then goes
through the normal text pipeline, where Python does all the maths.
"""
import base64
import io
import logging

import httpx
import pypdfium2 as pdfium
from PIL import Image, ImageOps

from app.config import settings
from app.services.groq_client import GROQ_URL, AIUnavailable

log = logging.getLogger(__name__)

MAX_PAGES = 4
MAX_SIDE = 1600  # px; enough for small print, small enough to upload fast
PROMPT = ("Transcribe all text in this document image exactly as written, line by line, keeping numbers and table "
          "rows intact (separate table cells with ' | '). Write each line once. Output only the transcribed text.")


def _jpeg(img: Image.Image) -> str:
    img = ImageOps.exif_transpose(img).convert("L")
    img.thumbnail((MAX_SIDE, MAX_SIDE))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=75)
    return base64.b64encode(buf.getvalue()).decode()


def dedupe(text: str) -> str:
    """Vision models sometimes transcribe a page twice. Cut the text where its first line starts repeating."""
    lines = [x.rstrip() for x in text.strip().splitlines()]
    first = next((x.strip() for x in lines if x.strip()), "")
    if first:
        for i in range(1, len(lines)):
            if lines[i].strip() == first:
                return "\n".join(lines[:i]).strip()
    return "\n".join(lines).strip()


def _transcribe(b64: str) -> str:
    if not settings.ai_enabled:
        raise AIUnavailable("GROQ_API_KEY is not set")
    try:
        resp = httpx.post(
            GROQ_URL,
            headers={"Authorization": f"Bearer {settings.groq_api_key}"},
            timeout=60,
            json={
                "model": settings.groq_vision_model,
                "temperature": 0,
                "max_tokens": 2500,
                "messages": [{"role": "user", "content": [
                    {"type": "text", "text": PROMPT},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                ]}],
            },
        )
    except httpx.HTTPError as exc:
        raise AIUnavailable(f"Vision request failed: {exc}") from exc
    if resp.status_code != 200:
        raise AIUnavailable(f"Vision model returned {resp.status_code}")
    return dedupe(resp.json()["choices"][0]["message"]["content"] or "")


def ocr_pdf(data: bytes) -> str:
    pdf = pdfium.PdfDocument(data)
    pages = [pdf[i].render(scale=2).to_pil() for i in range(min(len(pdf), MAX_PAGES))]
    return "\n\n".join(t for t in (_transcribe(_jpeg(p)) for p in pages) if t).strip()


def ocr_image(data: bytes) -> str:
    return _transcribe(_jpeg(Image.open(io.BytesIO(data))))
