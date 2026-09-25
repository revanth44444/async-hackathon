"""Thin Groq client (OpenAI-compatible REST). AI is used for reading and explaining, never for math."""
import json
import logging

import httpx

from app.config import settings

log = logging.getLogger(__name__)
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"


class AIUnavailable(Exception):
    pass


def chat(messages: list[dict], *, json_mode: bool = False, temperature: float = 0.2, max_tokens: int = 2048) -> str:
    if not settings.ai_enabled:
        raise AIUnavailable("GROQ_API_KEY is not set")
    payload: dict = {
        "model": settings.groq_model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    if "gpt-oss" in settings.groq_model:
        # Reasoning model: keep thinking short, and budget tokens for it on top of the answer
        payload["reasoning_effort"] = "low"
        payload["max_tokens"] = max_tokens + 2048
    try:
        resp = httpx.post(
            GROQ_URL,
            json=payload,
            headers={"Authorization": f"Bearer {settings.groq_api_key}"},
            timeout=60,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]
    except (httpx.HTTPError, KeyError, IndexError) as exc:
        log.warning("Groq call failed: %s", exc)
        raise AIUnavailable(str(exc)) from exc


def chat_json(messages: list[dict], **kw) -> dict:
    raw = chat(messages, json_mode=True, temperature=0, **kw)
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise AIUnavailable(f"Model returned invalid JSON: {exc}") from exc
