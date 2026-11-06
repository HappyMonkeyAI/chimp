"""Choose a free endpoint, preferring a suitable model that is already loaded."""

from __future__ import annotations

from dataclasses import dataclass

from chimp.config import EndpointConfig, Settings
from chimp.inventory import ModelRecord, Snapshot


class RouteError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


@dataclass(frozen=True)
class Placement:
    endpoint: EndpointConfig
    model_id: str
    requested: str
    reason: str


def place(
    settings: Settings,
    snapshots: dict[str, Snapshot],
    inflight: dict[str, int],
    requested: str | None,
    purpose: str = "chat",
    exclude: frozenset[str] = frozenset(),
) -> Placement:
    label, preferred = resolve_model(requested, settings)
    free: list[tuple[EndpointConfig, ModelRecord, int]] = []
    busy = False
    healthy = 0

    for endpoint in settings.endpoints:
        if endpoint.name in exclude:
            continue
        snapshot = snapshots.get(endpoint.name)
        if snapshot is None or not snapshot.healthy:
            continue
        healthy += 1
        active = inflight.get(endpoint.name, 0)
        choice = pick_model(snapshot.models, preferred, purpose)
        if choice is None:
            continue
        if active >= endpoint.max_concurrent:
            busy = True
            continue
        free.append((endpoint, choice, active))

    if healthy == 0:
        raise RouteError(503, "no_endpoints", "No configured endpoint is reachable.")

    warm = [item for item in free if item[1].loaded is True]
    unknown = [item for item in free if item[1].loaded is None]
    cold = [item for item in free if item[1].loaded is False]
    if warm:
        pool, reason = warm, "warm"
    elif unknown:
        pool, reason = unknown, "unknown"
    elif cold:
        pool, reason = cold, "cold"
    elif busy:
        raise RouteError(
            429,
            "endpoints_busy",
            f"Every endpoint that can serve {label!r} is already at capacity.",
        )
    else:
        raise RouteError(
            404,
            "model_not_found",
            f"No reachable endpoint has a model for {label!r}.",
        )

    endpoint, record, _active = min(pool, key=lambda item: _rank(item, preferred))
    return Placement(endpoint=endpoint, model_id=record.id, requested=label, reason=reason)


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


def pick_model(models: tuple[ModelRecord, ...] | list[ModelRecord], preferred: tuple[str, ...], purpose: str) -> ModelRecord | None:
    usable = [item for item in models if _serves(item, purpose)]
    if not usable:
        return None
    if not preferred:
        loaded = [item for item in usable if item.loaded is True]
        if loaded:
            return loaded[0]
        unknown = [item for item in usable if item.loaded is None]
        if unknown:
            return unknown[0]
        return usable[0]

    present = [(index, _lookup(usable, model_id)) for index, model_id in enumerate(preferred)]
    present = [(index, record) for index, record in present if record is not None]
    if not present:
        return None
    loaded = [item for item in present if item[1].loaded is True]
    if loaded:
        return min(loaded, key=lambda item: item[0])[1]
    unknown = [item for item in present if item[1].loaded is None]
    if unknown:
        return min(unknown, key=lambda item: item[0])[1]
    return min(present, key=lambda item: item[0])[1]


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


def _rank(item: tuple[EndpointConfig, ModelRecord, int], preferred: tuple[str, ...]) -> tuple[int, int, str]:
    _endpoint, record, active = item
    preference = _preference_index(record.id, preferred)
    return (preference, active, _endpoint.name)


def _preference_index(model_id: str, preferred: tuple[str, ...]) -> int:
    if not preferred:
        return 0
    for index, candidate in enumerate(preferred):
        if candidate == model_id or candidate.casefold() == model_id.casefold():
            return index
    return len(preferred)
