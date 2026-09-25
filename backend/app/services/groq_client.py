"""Thin Groq client (OpenAI-compatible REST). AI is used for reading and explaining, never for math."""
import json
import logging
import time

import httpx

from app.config import settings

log = logging.getLogger(__name__)
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"


class AIUnavailable(Exception):
    pass


def _call(model: str, messages: list[dict], json_mode: bool, temperature: float, max_tokens: int) -> httpx.Response:
    payload: dict = {"model": model, "messages": messages, "temperature": temperature, "max_tokens": max_tokens}
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    if "gpt-oss" in model:
        # Reasoning model: keep thinking short, and budget tokens for it on top of the answer
        payload["reasoning_effort"] = "low"
        payload["max_tokens"] = max_tokens + 2048
    return httpx.post(
        GROQ_URL,
        json=payload,
        headers={"Authorization": f"Bearer {settings.groq_api_key}"},
        timeout=60,
    )


def chat(messages: list[dict], *, json_mode: bool = False, temperature: float = 0.2, max_tokens: int = 2048) -> str:
    """Primary model first; on a rate limit fall back to the smaller model, then wait briefly and retry once."""
    if not settings.ai_enabled:
        raise AIUnavailable("GROQ_API_KEY is not set")
    attempts = [(settings.groq_model, 0.0), (settings.groq_fallback_model, 0.0), (settings.groq_model, 4.0)]
    last_error = "no attempt made"
    for model, wait in attempts:
        if not model:
            continue
        if wait:
            time.sleep(wait)
        try:
            resp = _call(model, messages, json_mode, temperature, max_tokens)
            if resp.status_code == 429:
                last_error = f"rate limited on {model}"
                log.warning("Groq %s", last_error)
                continue
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]
        except (httpx.HTTPError, KeyError, IndexError) as exc:
            last_error = str(exc)
            log.warning("Groq call failed on %s: %s", model, exc)
            break  # not a rate limit, so retrying won't help
    raise AIUnavailable(last_error)


def chat_json(messages: list[dict], **kw) -> dict:
    raw = chat(messages, json_mode=True, temperature=0, **kw)
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise AIUnavailable(f"Model returned invalid JSON: {exc}") from exc
