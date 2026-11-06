"""OpenAI-compatible proxy that places each request and forwards it."""

from __future__ import annotations

import asyncio
import contextlib
import hmac
import json
import logging
import time
from collections import deque
from contextlib import asynccontextmanager
from typing import Any

import httpx
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response, StreamingResponse
from starlette.routing import Route

from chimp import __version__
from chimp.config import EndpointConfig, Settings
from chimp.inventory import Inventory, auth_headers
from chimp.route import (
    ContextOverflow,
    Placement,
    RouteError,
    base_model_id,
    estimate_tokens,
    overflow_tokens,
    place,
    target_context,
)

log = logging.getLogger("chimp")

PROXY_PATHS = {
    "/v1/chat/completions": "chat",
    "/v1/completions": "chat",
    "/v1/responses": "chat",
    "/v1/embeddings": "embedding",
}
HOP_BY_HOP = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
    "host",
    "content-length",
    "authorization",
}


class Gate:
    """Hold an in-flight count so two requests cannot claim the same free slot."""

    def __init__(self) -> None:
        self.inflight: dict[str, int] = {}
        self._lock = asyncio.Lock()

    async def acquire(
        self,
        settings: Settings,
        inventory: Inventory,
        requested: str | None,
        purpose: str,
        exclude: frozenset[str] = frozenset(),
        needed_tokens: int | None = None,
    ) -> Placement:
        async with self._lock:
            placement = place(
                settings,
                inventory.snapshots(),
                self.inflight,
                requested,
                purpose=purpose,
                exclude=exclude,
                needed_tokens=needed_tokens,
            )
            name = placement.endpoint.name
            self.inflight[name] = self.inflight.get(name, 0) + 1
            return placement

    async def release(self, name: str) -> None:
        async with self._lock:
            self.inflight[name] = max(0, self.inflight.get(name, 0) - 1)


def build_app(settings: Settings, client: httpx.AsyncClient | None = None) -> Starlette:
    owns_client = client is None
    if client is None:
        client = httpx.AsyncClient(
            timeout=httpx.Timeout(settings.request_timeout_seconds, connect=10.0),
        )
    inventory = Inventory(settings.endpoints, client)
    gate = Gate()
    decisions: deque[dict[str, Any]] = deque(maxlen=50)

    @asynccontextmanager
    async def lifespan(_app: Starlette):
        await inventory.refresh_all()
        stop = asyncio.Event()

        async def poll() -> None:
            while not stop.is_set():
                try:
                    await asyncio.wait_for(stop.wait(), timeout=settings.poll_interval_seconds)
                except TimeoutError:
                    await inventory.refresh_all()

        task = asyncio.create_task(poll())
        try:
            yield
        finally:
            stop.set()
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
            if owns_client:
                await client.aclose()

    app = Starlette(
        lifespan=lifespan,
        routes=[
            Route("/health", _health, methods=["GET"]),
            Route("/status", _status, methods=["GET"]),
            Route("/v1/models", _models, methods=["GET"]),
            Route("/v1/chat/completions", _proxy, methods=["POST"]),
            Route("/v1/completions", _proxy, methods=["POST"]),
            Route("/v1/responses", _proxy, methods=["POST"]),
            Route("/v1/embeddings", _proxy, methods=["POST"]),
            Route("/", _root, methods=["GET"]),
        ],
    )
    app.state.settings = settings
    app.state.client = client
    app.state.inventory = inventory
    app.state.gate = gate
    app.state.decisions = decisions
    return app


async def _root(_request: Request) -> JSONResponse:
    return JSONResponse(
        {
            "service": "chimp",
            "version": __version__,
            "status": "/status",
            "models": "/v1/models",
        }
    )


async def _health(_request: Request) -> JSONResponse:
    return JSONResponse({"status": "ok", "version": __version__})


async def _status(request: Request) -> Response:
    denied = _authorize(request)
    if denied is not None:
        return denied
    settings: Settings = request.app.state.settings
    inventory: Inventory = request.app.state.inventory
    gate: Gate = request.app.state.gate
    endpoints = []
    for endpoint in settings.endpoints:
        snapshot = inventory.snapshots().get(endpoint.name)
        endpoints.append(
            {
                "name": endpoint.name,
                "kind": endpoint.kind,
                "base_url": endpoint.base_url,
                "max_concurrent": endpoint.max_concurrent,
                "inflight": gate.inflight.get(endpoint.name, 0),
                "healthy": bool(snapshot and snapshot.healthy),
                "error": None if snapshot is None else snapshot.error,
                "checked_at": None if snapshot is None else snapshot.checked_at,
                "models": [
                    {"id": model.id, "loaded": model.loaded, "kind": model.kind}
                    for model in (snapshot.models if snapshot else ())
                ],
            }
        )
    return JSONResponse({"service": "chimp", "version": __version__, "endpoints": endpoints, "recent": list(request.app.state.decisions)})


async def _models(request: Request) -> Response:
    denied = _authorize(request)
    if denied is not None:
        return denied
    settings: Settings = request.app.state.settings
    inventory: Inventory = request.app.state.inventory
    return JSONResponse({"object": "list", "data": catalog(settings, inventory)})


def catalog(settings: Settings, inventory: Inventory) -> list[dict[str, Any]]:
    """Aliases first, so a client can save `auto` before any backend is warm."""
    cards: dict[str, dict[str, Any]] = {}
    order: list[str] = []

    def add(model_id: str, owner: str, loaded: bool | None) -> None:
        current = cards.get(model_id)
        if current is None:
            cards[model_id] = _model_card(model_id, owner, loaded)
            order.append(model_id)
            return
        if current["loaded"] is True or loaded is not True:
            return
        cards[model_id] = _model_card(model_id, owner, loaded)

    aliases = sorted(settings.aliases.values(), key=lambda item: (item.name != "auto", item.name))
    for alias in aliases:
        add(alias.name, "chimp", None)
    for name, snapshot in inventory.snapshots().items():
        if not snapshot.healthy:
            continue
        for model in snapshot.models:
            add(model.id, name, model.loaded)
    return [cards[model_id] for model_id in order]


def _model_card(model_id: str, owner: str, loaded: bool | None) -> dict[str, Any]:
    return {
        "id": model_id,
        "object": "model",
        "created": 0,
        "owned_by": owner,
        "loaded": loaded,
    }


async def _proxy(request: Request) -> Response:
    denied = _authorize(request)
    if denied is not None:
        return denied
    purpose = PROXY_PATHS.get(request.url.path, "chat")
    try:
        payload = await request.json()
    except json.JSONDecodeError:
        return _error(400, "invalid_json", "Request body must be JSON.")
    if not isinstance(payload, dict):
        return _error(400, "invalid_json", "Request body must be a JSON object.")

    requested = payload.get("model")
    requested_text = requested if isinstance(requested, str) else None
    role = request.headers.get("x-chimp-role")
    if (not requested_text or requested_text in {"auto", "chimp/auto"}) and role:
        requested_text = role

    settings: Settings = request.app.state.settings
    client: httpx.AsyncClient = request.app.state.client
    inventory: Inventory = request.app.state.inventory
    gate: Gate = request.app.state.gate
    exclude: set[str] = set()
    widened: set[str] = set()
    last_transport: Exception | None = None
    needed = estimate_tokens(payload)

    while True:
        try:
            placement = await gate.acquire(
                settings,
                inventory,
                requested_text,
                purpose,
                frozenset(exclude),
                needed_tokens=needed,
            )
        except RouteError as exc:
            if last_transport is not None:
                return _error(502, "upstream_unavailable", f"Upstream connection failed: {last_transport}")
            return _error(exc.status, exc.code, exc.message)
        model_id = placement.model_id
        if placement.reason == "expand" and placement.context_target and placement.endpoint.name not in widened:
            try:
                model_id = await _widen_context(client, inventory, placement, placement.context_target)
            except Exception as exc:
                await gate.release(placement.endpoint.name)
                exclude.add(placement.endpoint.name)
                log.warning("could not widen context on %s: %s", placement.endpoint.name, exc)
                continue
            widened.add(placement.endpoint.name)
        payload["model"] = model_id
        if placement.endpoint.kind == "lmstudio":
            try:
                await _drop_smaller_siblings(client, inventory, placement.endpoint, model_id)
            except Exception as exc:
                log.warning("could not unload the smaller context on %s: %s", placement.endpoint.name, exc)
        _remember(request, placement)
        log.info(
            "route %s -> %s model=%s reason=%s tokens=%s",
            placement.requested,
            placement.endpoint.name,
            model_id,
            placement.reason,
            needed,
        )
        try:
            return await _dispatch(request, client, gate, placement, payload)
        except ContextOverflow as overflow:
            if await _retry_wider(client, inventory, placement, overflow.tokens, widened):
                needed = max(needed, overflow.tokens)
                continue
            exclude.add(placement.endpoint.name)
            log.warning("%s context still too small for %s tokens", placement.endpoint.name, overflow.tokens)
        except httpx.TransportError as exc:
            exclude.add(placement.endpoint.name)
            last_transport = exc
            log.warning("upstream %s failed before a response: %s", placement.endpoint.name, exc)


def _remember(request: Request, placement: Placement) -> None:
    request.app.state.decisions.append(
        {
            "time": time.time(),
            "requested": placement.requested,
            "endpoint": placement.endpoint.name,
            "model": placement.model_id,
            "reason": placement.reason,
            "path": request.url.path,
        }
    )


async def _dispatch(
    request: Request,
    client: httpx.AsyncClient,
    gate: Gate,
    placement: Placement,
    payload: dict[str, Any],
) -> Response:
    endpoint = placement.endpoint
    url = f"{endpoint.base_url}{request.url.path}"
    if request.url.query:
        url = f"{url}?{request.url.query}"
    headers = _forward_headers(request, endpoint.api_key)
    stream = payload.get("stream") is True
    stream_cm = client.stream("POST", url, headers=headers, json=payload)
    try:
        upstream = await stream_cm.__aenter__()
    except Exception:
        await gate.release(endpoint.name)
        raise

    async def close_upstream() -> None:
        try:
            await stream_cm.__aexit__(None, None, None)
        finally:
            await gate.release(endpoint.name)

    response_headers = _response_headers(upstream, placement, str(payload.get("model") or placement.model_id))
    if not stream or upstream.status_code >= 400:
        try:
            body = await upstream.aread()
        finally:
            await close_upstream()
        overflow = overflow_tokens(body)
        if overflow is not None:
            raise ContextOverflow(overflow)
        media = upstream.headers.get("content-type")
        return Response(body, status_code=upstream.status_code, headers=response_headers, media_type=media)

    media = (upstream.headers.get("content-type") or "").lower()
    if "event-stream" not in media:
        try:
            body = await upstream.aread()
        finally:
            await close_upstream()
        overflow = overflow_tokens(body)
        if overflow is not None:
            raise ContextOverflow(overflow)
        return Response(body, status_code=upstream.status_code, headers=response_headers, media_type=media or None)

    if upstream.is_stream_consumed:
        body = upstream.content
        overflow = overflow_tokens(body)
        if overflow is not None:
            await close_upstream()
            raise ContextOverflow(overflow)

        async def replay():
            try:
                yield body
            finally:
                await close_upstream()

        return StreamingResponse(replay(), status_code=upstream.status_code, headers=response_headers)

    incoming = upstream.aiter_raw()
    try:
        first = await anext(incoming)
    except StopAsyncIteration:
        await close_upstream()
        return Response(b"", status_code=upstream.status_code, headers=response_headers)
    overflow = overflow_tokens(first)
    if overflow is not None:
        await close_upstream()
        raise ContextOverflow(overflow)

    async def chunks():
        try:
            yield first
            async for chunk in incoming:
                yield chunk
        finally:
            await close_upstream()

    return StreamingResponse(chunks(), status_code=upstream.status_code, headers=response_headers)


async def _retry_wider(
    client: httpx.AsyncClient,
    inventory: Inventory,
    placement: Placement,
    tokens: int,
    widened: set[str],
) -> bool:
    maximum = placement.max_context
    if placement.endpoint.kind != "lmstudio" or placement.endpoint.name in widened:
        return False
    if maximum is None or tokens > maximum:
        return False
    try:
        await _widen_context(client, inventory, placement, target_context(tokens, maximum))
    except Exception as exc:
        log.warning("could not widen context on %s: %s", placement.endpoint.name, exc)
        return False
    widened.add(placement.endpoint.name)
    return True


async def _widen_context(
    client: httpx.AsyncClient,
    inventory: Inventory,
    placement: Placement,
    target: int,
) -> str:
    endpoint = placement.endpoint
    wanted = base_model_id(placement.model_id)
    snapshot = inventory.snapshots().get(endpoint.name)
    siblings = []
    if snapshot is not None:
        siblings = [
            item
            for item in snapshot.models
            if item.loaded is True and base_model_id(item.id) == wanted
        ]
    ready = [item for item in siblings if item.context is not None and item.context >= target]
    if ready:
        chosen = max(ready, key=lambda item: item.context or 0)
        for item in siblings:
            if item.id != chosen.id and (item.context or 0) < target:
                await _unload_instance(client, endpoint, item.id)
        await inventory.remember(await inventory.probe(endpoint))
        log.info("using %s %s at %s tokens", endpoint.name, chosen.id, chosen.context)
        return chosen.id
    for item in siblings:
        await _unload_instance(client, endpoint, item.id)
    response = await client.post(
        f"{endpoint.base_url}/api/v1/models/load",
        headers={**auth_headers(endpoint.api_key), "content-type": "application/json"},
        json={"model": wanted, "context_length": target, "echo_load_config": True},
        timeout=180,
    )
    response.raise_for_status()
    body = response.json() if response.content else {}
    instance = str(body.get("instance_id") or wanted)
    log.info("widened %s %s to %s tokens", endpoint.name, instance, target)
    await inventory.remember(await inventory.probe(endpoint))
    return instance


async def _drop_smaller_siblings(
    client: httpx.AsyncClient,
    inventory: Inventory,
    endpoint: EndpointConfig,
    chosen_id: str,
) -> None:
    snapshot = inventory.snapshots().get(endpoint.name)
    if snapshot is None:
        return
    chosen = next((item for item in snapshot.models if item.id == chosen_id), None)
    if chosen is None or chosen.context is None:
        return
    base = base_model_id(chosen_id)
    changed = False
    for item in snapshot.models:
        smaller = item.loaded is True and item.id != chosen_id and base_model_id(item.id) == base
        if smaller and item.context is not None and item.context < chosen.context:
            await _unload_instance(client, endpoint, item.id)
            changed = True
    if changed:
        await inventory.remember(await inventory.probe(endpoint))


async def _unload_instance(client: httpx.AsyncClient, endpoint: EndpointConfig, instance_id: str) -> None:
    response = await client.post(
        f"{endpoint.base_url}/api/v1/models/unload",
        headers={**auth_headers(endpoint.api_key), "content-type": "application/json"},
        json={"instance_id": instance_id},
        timeout=60,
    )
    if response.status_code >= 400:
        log.warning("unload %s on %s returned %s", instance_id, endpoint.name, response.status_code)
        return
    log.info("unloaded %s on %s", instance_id, endpoint.name)


def _forward_headers(request: Request, api_key: str | None) -> dict[str, str]:
    headers = {key: value for key, value in request.headers.items() if key.lower() not in HOP_BY_HOP}
    headers.update(auth_headers(api_key))
    headers["content-type"] = "application/json"
    return headers


def _response_headers(upstream: httpx.Response, placement: Placement, model_id: str) -> dict[str, str]:
    headers = {
        "x-chimp-endpoint": placement.endpoint.name,
        "x-chimp-model": model_id,
        "x-chimp-reason": placement.reason,
        "x-accel-buffering": "no",
    }
    content_type = upstream.headers.get("content-type")
    if content_type:
        headers["content-type"] = content_type
    return headers


def _authorize(request: Request) -> JSONResponse | None:
    expected = request.app.state.settings.api_key
    if not expected:
        return None
    provided = _bearer(request.headers.get("authorization"))
    if provided is None or not hmac.compare_digest(provided, expected):
        return _error(401, "unauthorized", "Missing or invalid bearer token.")
    return None


def _bearer(header: str | None) -> str | None:
    if not header:
        return None
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return None
    return token.strip()


def _error(status: int, code: str, message: str) -> JSONResponse:
    headers = {"retry-after": "2"} if status == 429 else None
    return JSONResponse(
        {"error": {"message": message, "type": code, "code": code}},
        status_code=status,
        headers=headers,
    )
