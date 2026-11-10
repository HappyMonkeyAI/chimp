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
import yaml
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, Response, StreamingResponse
from starlette.routing import Route

from chimp import __version__
from chimp.advisor import advise
from chimp.config import ConfigError, EndpointConfig, Settings, load_settings
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
from chimp.sticky import StickyTable
from chimp.ui import config_page_html, status_page_html

# Cloud / OpenAI-compatible prompt-cache knobs — never strip from the JSON body (T6).
CACHE_BODY_KEYS = frozenset(
    {
        "prompt_cache_key",
        "prompt_cache_retention",
        "prompt_cache_options",
    }
)

log = logging.getLogger("chimp")

PROXY_PATHS = {
    "/v1/chat/completions": "chat",
    "/v1/completions": "chat",
    "/v1/responses": "chat",
    "/v1/embeddings": "embedding",
}
PRIVATE_HEADERS = frozenset({"cookie", "x-forwarded-for", "x-real-ip", "forwarded"})
# Errors raised before the upstream could have received the request body.
FAILOVER_ERRORS = (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout)
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
        sticky=None,
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
                sticky=sticky,
            )
            name = placement.endpoint.name
            self.inflight[name] = self.inflight.get(name, 0) + 1
            return placement

    async def release(self, name: str) -> None:
        self.release_now(name)

    def release_now(self, name: str) -> None:
        # No await: safe to call from cancellation and finally paths.
        # Acquire's lock only guards place()+increment, which never yields.
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
    sticky = StickyTable(ttl_seconds=settings.sticky_ttl_seconds, enabled=settings.sticky)
    refreshes: dict[str, asyncio.Task[None]] = {}

    @asynccontextmanager
    async def lifespan(_app: Starlette):
        await inventory.refresh_all()
        await _prefetch_hints(settings, inventory, client)
        if settings.enrich_on_start:
            _seed_affinity_from_inventory(settings, inventory)
        stop = asyncio.Event()

        async def poll() -> None:
            while not stop.is_set():
                try:
                    await asyncio.wait_for(stop.wait(), timeout=settings.poll_interval_seconds)
                except TimeoutError:
                    await inventory.refresh_all()
                    await _prefetch_hints(settings, inventory, client)

        task = asyncio.create_task(poll())
        try:
            yield
        finally:
            stop.set()
            task.cancel()
            pending = list(refreshes.values())
            for item in pending:
                item.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
            for item in pending:
                with contextlib.suppress(asyncio.CancelledError):
                    await item
            if owns_client:
                await client.aclose()

    app = Starlette(
        lifespan=lifespan,
        routes=[
            Route("/health", _health, methods=["GET"]),
            Route("/status", _status, methods=["GET"]),
            Route("/ui", _ui, methods=["GET"]),
            Route("/ui/config", _ui_config, methods=["GET", "POST"]),
            Route("/ui/config.yaml", _ui_config_yaml, methods=["GET"]),
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
    app.state.sticky = sticky
    app.state.refreshes = refreshes
    return app


def _refresh_soon(app: Starlette, endpoint: EndpointConfig) -> None:
    """Re-probe one endpoint in the background after a cold load, so the next
    placement sees the model as warm instead of waiting for the poll."""
    pending: dict[str, asyncio.Task[None]] = app.state.refreshes
    if endpoint.name in pending:
        return
    inventory: Inventory = app.state.inventory

    async def run() -> None:
        try:
            await inventory.remember(await inventory.probe(endpoint))
        finally:
            pending.pop(endpoint.name, None)

    pending[endpoint.name] = asyncio.create_task(run())


async def _root(_request: Request) -> JSONResponse:
    return JSONResponse(
        {
            "service": "chimp",
            "version": __version__,
            "status": "/status",
            "ui": "/ui",
            "models": "/v1/models",
        }
    )


async def _ui(_request: Request) -> Response:
    # Shell only: every byte of data comes from /status, which stays behind auth.
    return Response(status_page_html(), media_type="text/html; charset=utf-8")


YAML_TYPES = ("text/yaml", "application/yaml", "application/x-yaml", "text/plain")
MAX_CONFIG_BYTES = 256 * 1024


async def _ui_config(request: Request) -> Response:
    if request.method == "GET":
        # Shell only; the YAML itself is fetched from /ui/config.yaml with a bearer token.
        return HTMLResponse(config_page_html())
    denied = _authorize(request)
    if denied is not None:
        return denied
    settings: Settings = request.app.state.settings
    if not settings.api_key:
        return _error(
            403,
            "config_write_disabled",
            "Set api_key in config.yaml to enable writes from /ui/config.",
        )
    content_type = (request.headers.get("content-type") or "").split(";")[0].strip().lower()
    if content_type not in YAML_TYPES:
        # Rejects form posts, which browsers send cross-site without a preflight.
        return _error(415, "unsupported_media_type", "POST the config as text/yaml.")
    path = settings.config_path
    if path is None:
        return _error(409, "no_config_path", "No config path is bound (started without load_settings path).")
    raw = await request.body()
    if len(raw) > MAX_CONFIG_BYTES:
        return _error(413, "config_too_large", f"Config must be under {MAX_CONFIG_BYTES} bytes.")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return _error(400, "invalid_encoding", "Config must be UTF-8.")
    tmp = path.with_name(f".{path.name}.tmp")
    try:
        tmp.write_text(text, encoding="utf-8")
        try:
            load_settings(tmp)
        except (ConfigError, ValueError, TypeError) as exc:
            return _error(400, "invalid_config", f"Not saved: {exc}")
        except yaml.YAMLError as exc:
            return _error(400, "invalid_config", f"Not saved: YAML did not parse: {exc}")
        tmp.replace(path)
    except OSError as exc:
        return _error(500, "config_write_failed", f"Could not write {path}: {exc}")
    finally:
        tmp.unlink(missing_ok=True)
    return JSONResponse({"saved": str(path), "message": f"Saved {path}. Restart chimp to apply."})


async def _ui_config_yaml(request: Request) -> Response:
    denied = _authorize(request)
    if denied is not None:
        return denied
    path = request.app.state.settings.config_path
    if path is None or not path.is_file():
        return _error(404, "no_config_path", "No config file is bound.")
    try:
        body = path.read_text(encoding="utf-8")
    except OSError as exc:
        return _error(500, "config_read_failed", f"Could not read {path}: {exc}")
    return Response(
        body,
        media_type="text/yaml; charset=utf-8",
        headers={"x-chimp-config-path": str(path), "cache-control": "no-store"},
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
                "tier": endpoint.tier,
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
    sticky: StickyTable = request.app.state.sticky
    pins = [
        {
            "key": pin.key,
            "endpoint": pin.endpoint,
            "model": pin.model_id,
            "expires_at": pin.expires_at,
        }
        for pin in sticky.active()
    ]
    return JSONResponse(
        {
            "service": "chimp",
            "version": __version__,
            "endpoints": endpoints,
            "sticky": pins,
            "advisor": {
                "enabled": settings.advisor.enabled,
                "model": settings.advisor.model if settings.advisor.enabled else None,
            },
            "recent": list(request.app.state.decisions),
        }
    )


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

    aliases = sorted(settings.aliases.values(), key=_alias_sort_key)
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


def _alias_sort_key(alias: Any) -> tuple[int, str]:
    name = str(getattr(alias, "name", ""))
    if name == "auto":
        return (0, name)
    if name.startswith("auto:"):
        return (1, name)
    return (2, name)


def _live_ids(inventory: Inventory) -> list[str]:
    ids: list[str] = []
    for snapshot in inventory.snapshots().values():
        if not snapshot.healthy:
            continue
        for model in snapshot.models:
            if model.id not in ids:
                ids.append(model.id)
    return ids


async def _prefetch_hints(settings: Settings, inventory: Inventory, client: httpx.AsyncClient) -> None:
    """Hugging Face lookups happen here, off the placement path (place() never does I/O)."""
    try:
        fetched = await settings.affinity.prefetch_huggingface(client, _live_ids(inventory))
    except Exception as exc:  # noqa: BLE001 — enrich is best-effort
        log.warning("huggingface prefetch failed: %s", exc)
        return
    if fetched:
        log.info("huggingface enrich: cached hints for %s new repos", fetched)


def _seed_affinity_from_inventory(settings: Settings, inventory: Inventory) -> None:
    ids = _live_ids(inventory)
    if not ids:
        log.info("affinity enrich: no live models yet")
        return
    report = settings.affinity.seed_live(ids)
    top = sorted(report.items(), key=lambda item: item[1].get("auto", 0), reverse=True)[:8]
    summary = ", ".join(f"{model_id}={scores.get('auto', 0)}" for model_id, scores in top)
    log.info("affinity enrich: scored %s live models; top auto: %s", len(ids), summary or "-")


def _is_open_auto(model_id: str | None) -> bool:
    """True when the client left model open (auto / provider-prefixed auto)."""
    if not model_id or not str(model_id).strip():
        return True
    from chimp.roles import strip_provider_prefix

    name = strip_provider_prefix(str(model_id)).strip().casefold()
    return name == "auto"


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
    if role and _is_open_auto(requested_text):
        requested_text = role

    settings: Settings = request.app.state.settings
    client: httpx.AsyncClient = request.app.state.client
    inventory: Inventory = request.app.state.inventory
    gate: Gate = request.app.state.gate
    sticky: StickyTable = request.app.state.sticky
    exclude: set[str] = set()
    widened: set[str] = set()
    last_transport: Exception | None = None
    needed = estimate_tokens(payload)
    sticky_key = sticky.resolve_key(payload, request.headers)
    sticky_pin = sticky.get(sticky_key)
    advisor_used = False

    # A live pin already decides placement; asking the advisor would only risk moving
    # the conversation off its warm KV cache (ADR-0003).
    if settings.advisor.enabled and sticky_pin is None and _is_open_auto(requested_text) and purpose == "chat":
        candidates = _live_chat_ids(inventory)
        hint = await advise(client, settings.advisor, payload, candidates)
        if hint:
            requested_text = hint
            advisor_used = True

    while True:
        try:
            placement = await gate.acquire(
                settings,
                inventory,
                requested_text,
                purpose,
                frozenset(exclude),
                needed_tokens=needed,
                sticky=sticky_pin,
            )
        except RouteError as exc:
            if sticky_pin is not None and sticky_pin.endpoint in exclude:
                sticky.clear(sticky_key)
                sticky_pin = None
            if last_transport is not None:
                # Details are logged; clients get no internal hostnames or addresses.
                return _error(502, "upstream_unavailable", "No upstream could be reached.")
            return _error(exc.status, exc.code, exc.message)
        if sticky_pin is not None and placement.reason != "sticky" and placement.endpoint.name != sticky_pin.endpoint:
            # Pin missed (busy/unavailable) — drop so the next turn can re-pin.
            sticky.clear(sticky_key)
            sticky_pin = None
        model_id = placement.model_id
        try:
            if placement.reason == "expand" and placement.context_target and placement.endpoint.name not in widened:
                try:
                    model_id = await _widen_context(client, inventory, placement, placement.context_target)
                except Exception as exc:
                    gate.release_now(placement.endpoint.name)
                    exclude.add(placement.endpoint.name)
                    log.warning("could not widen context on %s: %s", placement.endpoint.name, exc)
                    continue
                widened.add(placement.endpoint.name)
            payload["model"] = model_id
            _keep_cache_fields(payload)
            if placement.endpoint.kind == "lmstudio":
                try:
                    await _drop_smaller_siblings(client, inventory, placement.endpoint, model_id)
                except Exception as exc:
                    log.warning("could not unload the smaller context on %s: %s", placement.endpoint.name, exc)
        except BaseException:
            # Cancelled mid-load (shutdown, client gone): the slot must not leak.
            gate.release_now(placement.endpoint.name)
            raise
        reason = placement.reason
        if advisor_used and reason != "sticky":
            reason = f"{reason}+advisor"
        sticky.remember(sticky_key, placement.endpoint.name, model_id)
        _remember(request, placement, reason=reason, sticky_key=sticky_key)
        log.info(
            "route %s -> %s model=%s reason=%s tokens=%s sticky=%s",
            placement.requested,
            placement.endpoint.name,
            model_id,
            reason,
            needed,
            sticky_key or "-",
        )
        try:
            response = await _dispatch(request, client, gate, placement, payload, reason=reason)
            if placement.reason == "cold" and response.status_code < 400:
                # Headers arrived, so the upstream has finished loading the model.
                _refresh_soon(request.app, placement.endpoint)
            return response
        except ContextOverflow as overflow:
            if await _retry_wider(client, inventory, placement, overflow.tokens, widened):
                needed = max(needed, overflow.tokens)
                continue
            exclude.add(placement.endpoint.name)
            log.warning("%s context still too small for %s tokens", placement.endpoint.name, overflow.tokens)
        except FAILOVER_ERRORS as exc:
            # The request never reached the upstream, so another endpoint may take it.
            exclude.add(placement.endpoint.name)
            sticky.clear_endpoint(placement.endpoint.name)
            last_transport = exc
            log.warning("upstream %s unreachable, failing over: %s", placement.endpoint.name, exc)
        except httpx.TransportError as exc:
            # The upstream may already be generating; retrying elsewhere would duplicate GPU work.
            sticky.clear(sticky_key)
            log.warning("upstream %s failed mid-request: %r", placement.endpoint.name, exc)
            return _error(502, "upstream_failed", f"Upstream {placement.endpoint.name!r} failed mid-request.")


def _remember(
    request: Request,
    placement: Placement,
    reason: str | None = None,
    sticky_key: str | None = None,
) -> None:
    request.app.state.decisions.append(
        {
            "time": time.time(),
            "requested": placement.requested,
            "endpoint": placement.endpoint.name,
            "model": placement.model_id,
            "reason": reason or placement.reason,
            "sticky": sticky_key,
            "path": request.url.path,
        }
    )


def _live_chat_ids(inventory: Inventory) -> list[str]:
    ids: list[str] = []
    for snapshot in inventory.snapshots().values():
        if not snapshot.healthy:
            continue
        for model in snapshot.models:
            if model.kind in {"embedding", "embed"}:
                continue
            if model.id not in ids:
                ids.append(model.id)
    return ids


def _keep_cache_fields(payload: dict[str, Any]) -> None:
    """Cache knobs stay on the payload (T6); only explicit nulls are dropped so upstreams don't reject them."""
    for key in CACHE_BODY_KEYS:
        if key in payload and payload[key] is None:
            del payload[key]


async def _dispatch(
    request: Request,
    client: httpx.AsyncClient,
    gate: Gate,
    placement: Placement,
    payload: dict[str, Any],
    reason: str | None = None,
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
    except BaseException:
        gate.release_now(endpoint.name)
        raise

    closed = False

    async def close_upstream() -> None:
        # Idempotent; the slot is freed before the await so cancellation cannot skip it.
        nonlocal closed
        if closed:
            return
        closed = True
        gate.release_now(endpoint.name)
        await stream_cm.__aexit__(None, None, None)

    try:
        return await _relay(upstream, placement, payload, reason, close_upstream, stream)
    except BaseException:
        await close_upstream()
        raise


async def _relay(
    upstream: httpx.Response,
    placement: Placement,
    payload: dict[str, Any],
    reason: str | None,
    close_upstream,
    stream: bool,
) -> Response:
    response_headers = _response_headers(
        upstream,
        placement,
        str(payload.get("model") or placement.model_id),
        reason=reason,
    )
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

    # Decoded bytes (also replays an already-read body, as mock transports produce): content-encoding is not forwarded, so raw gzip would reach clients unlabelled.
    incoming = upstream.aiter_bytes()
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

    return _ClosingStream(chunks(), close_upstream, status_code=upstream.status_code, headers=response_headers)


class _ClosingStream(StreamingResponse):
    """Free the upstream and its slot even if the body iterator never starts or is abandoned."""

    def __init__(self, content, on_close, **kwargs) -> None:
        super().__init__(content, **kwargs)
        self._on_close = on_close

    async def __call__(self, scope, receive, send) -> None:
        try:
            await super().__call__(scope, receive, send)
        finally:
            await self._on_close()


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
    # Cookies and chimp's own control headers are for chimp only, never for an upstream
    # (secondary tier is a third-party cloud API).
    headers = {
        key: value
        for key, value in request.headers.items()
        if key.lower() not in HOP_BY_HOP and key.lower() not in PRIVATE_HEADERS and not key.lower().startswith("x-chimp-")
    }
    headers.update(auth_headers(api_key))
    headers["content-type"] = "application/json"
    # We do not forward content-encoding, so ask upstream for plain bytes.
    headers["accept-encoding"] = "identity"
    return headers


def _response_headers(
    upstream: httpx.Response,
    placement: Placement,
    model_id: str,
    reason: str | None = None,
) -> dict[str, str]:
    headers = {
        "x-chimp-endpoint": placement.endpoint.name,
        "x-chimp-model": model_id,
        "x-chimp-reason": reason or placement.reason,
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
