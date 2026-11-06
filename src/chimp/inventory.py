"""Poll each endpoint for the models it has and which of them are loaded."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

import httpx

from chimp.config import EndpointConfig

log = logging.getLogger("chimp.inventory")

READY_STATES = {"ready", "loaded", "running"}
COLD_STATES = {"not-loaded", "unloaded", "unloading", "loading", "starting", "stopping", "stopped"}
PROBE_TIMEOUT = 5.0


@dataclass(frozen=True)
class ModelRecord:
    id: str
    loaded: bool | None
    kind: str = "any"


@dataclass(frozen=True)
class Snapshot:
    name: str
    healthy: bool
    models: tuple[ModelRecord, ...]
    error: str | None
    checked_at: float


class Inventory:
    def __init__(self, endpoints: tuple[EndpointConfig, ...], client: httpx.AsyncClient) -> None:
        self._endpoints = endpoints
        self._client = client
        self._snapshots: dict[str, Snapshot] = {}

    def snapshots(self) -> dict[str, Snapshot]:
        return dict(self._snapshots)

    async def refresh_all(self) -> None:
        for endpoint in self._endpoints:
            snapshot = await self.probe(endpoint)
            previous = self._snapshots.get(endpoint.name)
            self._snapshots[endpoint.name] = snapshot
            if previous is None or previous.healthy != snapshot.healthy:
                if snapshot.healthy:
                    loaded = [item.id for item in snapshot.models if item.loaded is True]
                    log.info("%s healthy, loaded=%s", endpoint.name, loaded or "-")
                else:
                    log.warning("%s unreachable: %s", endpoint.name, snapshot.error)

    async def probe(self, endpoint: EndpointConfig) -> Snapshot:
        try:
            models = await self._models_for(endpoint)
        except Exception as exc:
            return Snapshot(
                name=endpoint.name,
                healthy=False,
                models=(),
                error=_short_error(exc),
                checked_at=time.time(),
            )
        return Snapshot(
            name=endpoint.name,
            healthy=True,
            models=tuple(models),
            error=None,
            checked_at=time.time(),
        )

    async def _models_for(self, endpoint: EndpointConfig) -> list[ModelRecord]:
        headers = auth_headers(endpoint.api_key)
        if endpoint.kind == "lmstudio":
            return await self._probe_lmstudio(endpoint, headers)
        if endpoint.kind == "llamaswap":
            return await self._probe_llamaswap(endpoint, headers)
        loaded_default = True if endpoint.kind == "unsloth" else None
        payload = await self._get_json(endpoint, "/v1/models", headers)
        return parse_openai_models(payload, loaded_default=loaded_default)

    async def _probe_lmstudio(self, endpoint: EndpointConfig, headers: dict[str, str]) -> list[ModelRecord]:
        try:
            payload = await self._get_json(endpoint, "/api/v0/models", headers)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code != 404:
                raise
            payload = await self._get_json(endpoint, "/v1/models", headers)
            return parse_openai_models(payload, loaded_default=None)
        return parse_lmstudio_models(payload)

    async def _probe_llamaswap(self, endpoint: EndpointConfig, headers: dict[str, str]) -> list[ModelRecord]:
        catalog = parse_openai_models(
            await self._get_json(endpoint, "/v1/models", headers),
            loaded_default=None,
        )
        try:
            running = await self._get_json(endpoint, "/running", headers)
        except Exception as exc:
            log.info("%s /running unavailable (%s); loaded state left unknown", endpoint.name, _short_error(exc))
            return catalog
        return merge_running(catalog, parse_running(running))

    async def _get_json(self, endpoint: EndpointConfig, path: str, headers: dict[str, str]) -> object:
        response = await self._client.get(
            f"{endpoint.base_url}{path}",
            headers=headers,
            timeout=PROBE_TIMEOUT,
        )
        response.raise_for_status()
        if not response.content:
            return {}
        return response.json()


def auth_headers(api_key: str | None) -> dict[str, str]:
    if not api_key:
        return {}
    return {"Authorization": f"Bearer {api_key}"}


def parse_openai_models(payload: object, loaded_default: bool | None) -> list[ModelRecord]:
    data = _data_list(payload)
    saw_loaded = any(isinstance(item, dict) and "loaded" in item for item in data)
    records: list[ModelRecord] = []
    for item in data:
        if not isinstance(item, dict) or not item.get("id"):
            continue
        if "loaded" in item:
            loaded: bool | None = bool(item.get("loaded"))
        elif saw_loaded:
            loaded = False
        else:
            loaded = loaded_default
        records.append(ModelRecord(id=str(item["id"]), loaded=loaded, kind=_openai_kind(item)))
    return records


def parse_lmstudio_models(payload: object) -> list[ModelRecord]:
    records: list[ModelRecord] = []
    for item in _data_list(payload):
        if not isinstance(item, dict) or not item.get("id"):
            continue
        state = str(item.get("state") or "").strip().lower()
        if state in READY_STATES:
            loaded: bool | None = True
        elif state in COLD_STATES:
            loaded = False
        elif state == "":
            loaded = None
        else:
            loaded = False
        records.append(ModelRecord(id=str(item["id"]), loaded=loaded, kind=_lmstudio_kind(item)))
    return records


def parse_running(payload: object) -> dict[str, str]:
    """Return model id to llama-swap state. Accepts the current list and the older single-object shape."""
    if not isinstance(payload, dict):
        return {}
    running = payload.get("running")
    states: dict[str, str] = {}
    if isinstance(running, list):
        for item in running:
            if isinstance(item, str) and item:
                states[item] = "ready"
            elif isinstance(item, dict):
                model_id = item.get("model") or item.get("id")
                if model_id:
                    states[str(model_id)] = str(item.get("state") or "ready")
        return states
    model_id = payload.get("model")
    if isinstance(model_id, str) and model_id:
        states[model_id] = str(payload.get("state") or "ready")
    return states


def merge_running(catalog: list[ModelRecord], states: dict[str, str]) -> list[ModelRecord]:
    by_id = {item.id: item for item in catalog}
    for model_id, state in states.items():
        loaded = state.strip().lower() in READY_STATES
        previous = by_id.get(model_id)
        kind = previous.kind if previous else "any"
        by_id[model_id] = ModelRecord(id=model_id, loaded=loaded, kind=kind)
    for model_id, record in list(by_id.items()):
        if model_id not in states and record.loaded is None:
            by_id[model_id] = ModelRecord(id=model_id, loaded=False, kind=record.kind)
    return list(by_id.values())


def _data_list(payload: object) -> list[object]:
    if isinstance(payload, dict) and isinstance(payload.get("data"), list):
        return list(payload["data"])
    return []


def _openai_kind(item: dict[str, object]) -> str:
    owned = str(item.get("owned_by") or "")
    if "embed" in owned.casefold():
        return "embedding"
    return "any"


def _lmstudio_kind(item: dict[str, object]) -> str:
    model_type = str(item.get("type") or "").strip().lower()
    if model_type == "embeddings":
        return "embedding"
    if model_type in {"llm", "vlm"}:
        return "chat"
    return "any"


def _short_error(exc: Exception) -> str:
    text = f"{type(exc).__name__}: {exc}"
    return text[:240]
