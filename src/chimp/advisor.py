"""Optional advisory classifier for bare `auto` (Wave 4)."""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from chimp.config import AdvisorConfig
from chimp.roles import AUTO_CLASS_ALIASES, normalize_role

log = logging.getLogger("chimp.advisor")

_ALLOWED_CLASSES = frozenset(name.removeprefix("auto:") for name in AUTO_CLASS_ALIASES if name.startswith("auto:"))


async def advise(
    client: httpx.AsyncClient,
    advisor: AdvisorConfig,
    payload: dict[str, Any],
    candidate_ids: list[str],
) -> str | None:
    """Return auto:<class>, a candidate model id, or None on timeout/error."""
    if not advisor.enabled or not advisor.base_url:
        return None
    if not candidate_ids:
        return None
    prompt = _hint_prompt(payload, candidate_ids)
    url = f"{advisor.base_url.rstrip('/')}/v1/chat/completions"
    body = {
        "model": advisor.model,
        "temperature": 0,
        "max_tokens": 32,
        "messages": [
            {
                "role": "system",
                "content": (
                    "Pick the best work class or model id for this chat. "
                    "Reply with only one token from the allowed list."
                ),
            },
            {"role": "user", "content": prompt},
        ],
    }
    headers = {"content-type": "application/json"}
    if advisor.api_key:
        headers["authorization"] = f"Bearer {advisor.api_key}"
    try:
        response = await client.post(url, headers=headers, json=body, timeout=advisor.timeout_seconds)
        response.raise_for_status()
        data = response.json()
    except Exception as exc:
        log.info("advisor skipped: %s", exc)
        return None
    text = _extract_text(data).strip().strip("`\"'").casefold()
    if not text:
        return None
    for candidate in candidate_ids:
        if candidate.casefold() == text or candidate.casefold().endswith("/" + text):
            return candidate
    role = normalize_role(text)
    if role in _ALLOWED_CLASSES:
        return f"auto:{role}"
    if text.startswith("auto:") and text.removeprefix("auto:") in _ALLOWED_CLASSES:
        return text
    log.info("advisor reply ignored: %r", text)
    return None


def _hint_prompt(payload: dict[str, Any], candidate_ids: list[str]) -> str:
    sample = _sample_text(payload)[:1200]
    classes = ", ".join(sorted(_ALLOWED_CLASSES))
    models = ", ".join(candidate_ids[:24])
    return (
        f"Allowed classes: {classes}\n"
        f"Allowed models: {models}\n"
        f"User text:\n{sample or '(empty)'}"
    )


def _sample_text(payload: dict[str, Any]) -> str:
    messages = payload.get("messages")
    if isinstance(messages, list):
        chunks: list[str] = []
        for message in messages[-6:]:
            if isinstance(message, dict):
                content = message.get("content")
                if isinstance(content, str):
                    chunks.append(content)
                elif isinstance(content, list):
                    chunks.append(json.dumps(content)[:400])
        return "\n".join(chunks)
    for key in ("input", "prompt"):
        value = payload.get(key)
        if isinstance(value, str):
            return value
    return ""


def _extract_text(data: object) -> str:
    if not isinstance(data, dict):
        return ""
    choices = data.get("choices")
    if isinstance(choices, list) and choices:
        first = choices[0]
        if isinstance(first, dict):
            message = first.get("message")
            if isinstance(message, dict) and isinstance(message.get("content"), str):
                return message["content"]
            if isinstance(first.get("text"), str):
                return first["text"]
    return ""
