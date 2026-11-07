"""Choose a free endpoint, preferring a suitable model that is already loaded."""

from __future__ import annotations

import json
from dataclasses import dataclass

from chimp.config import EndpointConfig, Settings
from chimp.inventory import ModelRecord, Snapshot


class RouteError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


class ContextOverflow(Exception):
    def __init__(self, tokens: int) -> None:
        super().__init__(f"prompt needs about {tokens} tokens")
        self.tokens = tokens


def overflow_tokens(body: bytes) -> int | None:
    text = body.decode("utf-8", errors="ignore")
    decoder = json.JSONDecoder()
    index = 0
    while True:
        start = text.find("{", index)
        if start < 0:
            return None
        try:
            payload, end = decoder.raw_decode(text, start)
        except json.JSONDecodeError:
            index = start + 1
            continue
        index = end
        if not isinstance(payload, dict):
            continue
        error = payload.get("error")
        if not isinstance(error, dict):
            continue
        marker = f"{error.get('type', '')} {error.get('message', '')}".casefold()
        if "exceed_context_size" not in marker and "context size" not in marker:
            continue
        prompt = error.get("n_prompt_tokens")
        if isinstance(prompt, str) and prompt.isdigit():
            prompt = int(prompt)
        if isinstance(prompt, int) and prompt > 0:
            return prompt + 2048
        return 32768


@dataclass(frozen=True)
class Placement:
    endpoint: EndpointConfig
    model_id: str
    requested: str
    reason: str
    context_target: int | None = None
    max_context: int | None = None


def place(
    settings: Settings,
    snapshots: dict[str, Snapshot],
    inflight: dict[str, int],
    requested: str | None,
    purpose: str = "chat",
    exclude: frozenset[str] = frozenset(),
    needed_tokens: int | None = None,
) -> Placement:
    label, preferred = resolve_model(requested, settings)
    free: list[tuple[EndpointConfig, ModelRecord, int, str]] = []
    busy = False
    healthy = 0
    saw_model = False

    for endpoint in settings.endpoints:
        if endpoint.name in exclude:
            continue
        snapshot = snapshots.get(endpoint.name)
        if snapshot is None or not snapshot.healthy:
            continue
        healthy += 1
        active = inflight.get(endpoint.name, 0)
        choices = candidate_models(snapshot.models, preferred, purpose)
        if not choices:
            continue
        saw_model = True
        for choice in choices:
            if not preferred and settings.affinity.score(choice.id, label) <= 0:
                continue
            reason = _fit(endpoint, choice, needed_tokens)
            if reason is None:
                continue
            if active >= endpoint.max_concurrent:
                busy = True
                continue
            free.append((endpoint, choice, active, reason))

    if healthy == 0:
        raise RouteError(503, "no_endpoints", "No configured endpoint is reachable.")

    order = ("warm", "expand", "unknown", "cold")
    pool: list[tuple[EndpointConfig, ModelRecord, int, str]] = []
    chosen_reason = ""
    for reason in order:
        pool = [item for item in free if item[3] == reason]
        if pool:
            chosen_reason = reason
            break
    if not pool and busy:
        raise RouteError(
            429,
            "endpoints_busy",
            f"Every endpoint that can serve {label!r} is already at capacity.",
        )
    if not pool:
        if needed_tokens is not None and saw_model:
            raise RouteError(
                400,
                "context_length_exceeded",
                f"No reachable model can hold about {needed_tokens} tokens for {label!r}.",
            )
        raise RouteError(404, "model_not_found", f"No reachable endpoint has a model for {label!r}.")

    endpoint, record, _active, _reason = min(pool, key=lambda item: _rank(item, preferred, label, settings))
    target = None
    if chosen_reason == "expand" and needed_tokens is not None and record.max_context is not None:
        target = target_context(needed_tokens, record.max_context)
    return Placement(
        endpoint=endpoint,
        model_id=record.id,
        requested=label,
        reason=chosen_reason,
        context_target=target,
        max_context=record.max_context,
    )


def resolve_model(requested: str | None, settings: Settings) -> tuple[str, tuple[str, ...]]:
    name = (requested or "").strip()
    if not name or name in {"auto", "chimp/auto"}:
        alias = settings.aliases.get("auto")
        if alias is not None:
            return alias.name, alias.models
        return "auto", ()
    alias = settings.aliases.get(name)
    if alias is not None:
        return alias.name, alias.models
    folded = {key.casefold(): value for key, value in settings.aliases.items()}
    match = folded.get(name.casefold())
    if match is not None:
        return match.name, match.models
    return name, (name,)


def candidate_models(
    models: tuple[ModelRecord, ...] | list[ModelRecord],
    preferred: tuple[str, ...],
    purpose: str,
) -> list[ModelRecord]:
    usable = [item for item in models if _serves(item, purpose)]
    if not preferred:
        return usable
    return [item for item in usable if any(_same_model(item.id, wanted) for wanted in preferred)]


def base_model_id(model_id: str) -> str:
    head, sep, tail = model_id.rpartition(":")
    if sep and tail.isdigit():
        return head
    return model_id


def _same_model(left: str, right: str) -> bool:
    return left.casefold() == right.casefold() or base_model_id(left).casefold() == base_model_id(right).casefold()


def _serves(model: ModelRecord, purpose: str) -> bool:
    if model.kind in {"any", purpose}:
        return True
    return purpose == "chat" and model.kind in {"llm", "vlm", "chat"}


def _lookup(models: list[ModelRecord], model_id: str) -> ModelRecord | None:
    for item in models:
        if item.id == model_id:
            return item
    folded = model_id.casefold()
    for item in models:
        if item.id.casefold() == folded:
            return item
    return None


def _rank(
    item: tuple[EndpointConfig, ModelRecord, int, str],
    preferred: tuple[str, ...],
    role: str,
    settings: Settings,
) -> tuple[int, int, int, str]:
    _endpoint, record, active, _reason = item
    preference = _preference_index(record.id, preferred)
    # Higher affinity wins: negate so min() keeps warm/busy order primary.
    affinity = -settings.affinity.score(record.id, role)
    return (preference, affinity, active, _endpoint.name)


def estimate_tokens(payload: dict[str, object]) -> int:
    """Conservative prompt size. Short chats stay under a small loaded window."""
    text = _collect_text(payload.get("messages"))
    text += _collect_text(payload.get("input"))
    text += _collect_text(payload.get("prompt"))
    tools = payload.get("tools")
    if tools is not None:
        text += str(tools)
    reserve = 4096
    for key in ("max_tokens", "max_completion_tokens"):
        value = payload.get(key)
        if isinstance(value, int) and value > 0:
            reserve = max(reserve, value)
            break
    return (len(text) // 2) + reserve


def target_context(needed: int, maximum: int) -> int:
    padded = max(needed + 8192, int(needed * 1.5))
    size = 8192
    while size < padded and size < maximum:
        size *= 2
    return min(max(size, 8192), maximum)


def _fit(endpoint: EndpointConfig, record: ModelRecord, needed: int | None) -> str | None:
    if needed is None:
        if record.loaded is True:
            return "warm"
        if record.loaded is None:
            return "unknown"
        return "cold"
    if record.loaded is True and _window_fits(record.context, needed):
        return "warm"
    if _can_expand(endpoint, record, needed):
        return "expand"
    if record.loaded is None and _window_fits(record.max_context or record.context, needed):
        return "unknown"
    if record.loaded is False and _window_fits(record.max_context or record.context, needed):
        return "cold"
    return None


def _window_fits(window: int | None, needed: int) -> bool:
    return window is None or window >= needed


def _can_expand(endpoint: EndpointConfig, record: ModelRecord, needed: int) -> bool:
    return (
        endpoint.kind == "lmstudio"
        and record.loaded is True
        and record.context is not None
        and record.max_context is not None
        and record.context < needed <= record.max_context
    )


def _collect_text(value: object) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "".join(_collect_text(item) for item in value)
    if isinstance(value, dict):
        parts = [_collect_text(value.get("content")), _collect_text(value.get("text"))]
        return "".join(parts)
    return ""


def _preference_index(model_id: str, preferred: tuple[str, ...]) -> int:
    if not preferred:
        return 0
    for index, candidate in enumerate(preferred):
        if candidate == model_id or candidate.casefold() == model_id.casefold():
            return index
    return len(preferred)
