"""Session / prompt-cache sticky pins for cache locality (ADR-0003)."""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class StickyPin:
    key: str
    endpoint: str
    model_id: str
    expires_at: float


@dataclass
class StickyTable:
    ttl_seconds: float = 1800.0
    enabled: bool = True
    max_pins: int = 4096
    _pins: dict[str, StickyPin] = field(default_factory=dict)

    def resolve_key(self, payload: dict[str, Any], headers: Any) -> str | None:
        if not self.enabled:
            return None
        raw = payload.get("prompt_cache_key")
        if isinstance(raw, str) and raw.strip():
            return f"pck:{raw.strip()}"
        session = None
        if headers is not None:
            session = headers.get("x-chimp-session") or headers.get("X-Chimp-Session")
        if isinstance(session, str) and session.strip():
            return f"sess:{session.strip()}"
        prefix = _stable_prefix(payload)
        if prefix:
            digest = hashlib.sha256(prefix.encode("utf-8")).hexdigest()[:24]
            return f"pfx:{digest}"
        return None

    def get(self, key: str | None, now: float | None = None) -> StickyPin | None:
        if not key or not self.enabled:
            return None
        pin = self._pins.get(key)
        if pin is None:
            return None
        clock = time.time() if now is None else now
        if pin.expires_at <= clock:
            self._pins.pop(key, None)
            return None
        return pin

    def remember(self, key: str | None, endpoint: str, model_id: str, now: float | None = None) -> None:
        if not key or not self.enabled:
            return
        clock = time.time() if now is None else now
        self._pins.pop(key, None)  # re-insert so dict order stays oldest-first
        if len(self._pins) >= self.max_pins:
            # Bounded memory even when nobody polls /status: sweep, then evict oldest.
            self.active(now=clock)
            while len(self._pins) >= self.max_pins:
                self._pins.pop(next(iter(self._pins)))
        self._pins[key] = StickyPin(
            key=key,
            endpoint=endpoint,
            model_id=model_id,
            expires_at=clock + self.ttl_seconds,
        )

    def clear(self, key: str | None) -> None:
        if key:
            self._pins.pop(key, None)

    def clear_endpoint(self, endpoint: str) -> None:
        doomed = [key for key, pin in self._pins.items() if pin.endpoint == endpoint]
        for key in doomed:
            self._pins.pop(key, None)

    def active(self, now: float | None = None) -> list[StickyPin]:
        clock = time.time() if now is None else now
        alive: list[StickyPin] = []
        expired: list[str] = []
        for key, pin in self._pins.items():
            if pin.expires_at <= clock:
                expired.append(key)
            else:
                alive.append(pin)
        for key in expired:
            self._pins.pop(key, None)
        return alive


def _stable_prefix(payload: dict[str, Any]) -> str:
    messages = payload.get("messages")
    if not isinstance(messages, list):
        return ""
    parts: list[str] = []
    for message in messages[:4]:
        if not isinstance(message, dict):
            continue
        role = str(message.get("role") or "")
        if role not in {"system", "user", "developer"}:
            continue
        text = _flatten_content(message.get("content"))
        if text:
            parts.append(f"{role}:{text[:512]}")
        if role == "user" and parts:
            break
    return "\n".join(parts)[:2048]


def _flatten_content(value: object) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "".join(_flatten_content(item) for item in value)
    if isinstance(value, dict):
        return _flatten_content(value.get("text")) + _flatten_content(value.get("content"))
    return ""
