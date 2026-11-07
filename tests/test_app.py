import asyncio
import json

import httpx
import pytest

from chimp.affinity import load_affinity
from chimp.app import build_app
from chimp.config import AliasConfig, EndpointConfig, Settings


def _settings() -> Settings:
    return Settings(
        listen_host="127.0.0.1",
        listen_port=8787,
        api_key="router-secret",
        poll_interval_seconds=3600,
        request_timeout_seconds=30,
        endpoints=(
            EndpointConfig("warm", "unsloth", "http://warm", "upstream-warm", 1),
            EndpointConfig("cold", "openai", "http://cold", None, 1),
        ),
        aliases={
            "executor": AliasConfig("executor", ("coder",)),
            "auto": AliasConfig("auto", ()),
        },
        affinity=load_affinity(huggingface_enrich=False),
    )


def _handler(hold: asyncio.Event, started: asyncio.Event):
    async def handle(request: httpx.Request) -> httpx.Response:
        host = request.url.host
        if request.url.path == "/v1/models":
            if host == "warm":
                body = {"data": [{"id": "coder", "loaded": True}, {"id": "embed", "loaded": True, "owned_by": "embed"}]}
            else:
                body = {"data": [{"id": "coder", "loaded": False}, {"id": "chat", "loaded": False}]}
            return httpx.Response(200, json=body)
        if request.url.path == "/v1/chat/completions":
            payload = json.loads(request.content.decode())
            if host == "warm":
                assert request.headers["authorization"] == "Bearer upstream-warm"
            if payload.get("boom") and host == "warm":
                raise httpx.ConnectError("down")
            if payload.get("stream"):
                started.set()
                await hold.wait()
                return httpx.Response(
                    200,
                    headers={"content-type": "text/event-stream"},
                    content=b"data: [DONE]\n\n",
                )
            return httpx.Response(200, json={"model": payload["model"], "choices": []})
        return httpx.Response(404, json={"missing": request.url.path})

    return handle


@pytest.fixture
async def client():
    hold = asyncio.Event()
    started = asyncio.Event()
    upstream = httpx.AsyncClient(transport=httpx.MockTransport(_handler(hold, started)))
    app = build_app(_settings(), client=upstream)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://chimp") as api:
            yield api, hold, started


def _auth() -> dict[str, str]:
    return {"authorization": "Bearer router-secret"}


async def test_chat_rewrites_the_alias_onto_the_warm_model(client):
    api, _hold, _started = client
    response = await api.post(
        "/v1/chat/completions",
        headers=_auth(),
        json={"model": "executor", "messages": [{"role": "user", "content": "ping"}]},
    )
    assert response.status_code == 200
    assert response.json()["model"] == "coder"
    assert response.headers["x-chimp-endpoint"] == "warm"
    assert response.headers["x-chimp-reason"] == "warm"


async def test_missing_token_is_rejected_and_health_stays_open(client):
    api, _hold, _started = client
    denied = await api.get("/status")
    assert denied.status_code == 401
    health = await api.get("/health")
    assert health.status_code == 200


async def test_second_request_cold_loads_when_the_warm_slot_is_held(client):
    api, hold, started = client

    async def occupy():
        async with api.stream(
            "POST",
            "/v1/chat/completions",
            headers=_auth(),
            json={"model": "executor", "stream": True, "messages": []},
        ) as response:
            assert response.status_code == 200
            await response.aread()

    task = asyncio.create_task(occupy())
    await asyncio.wait_for(started.wait(), timeout=2)
    cold = await api.post(
        "/v1/chat/completions",
        headers=_auth(),
        json={"model": "executor", "messages": []},
    )
    assert cold.status_code == 200
    assert cold.headers["x-chimp-endpoint"] == "cold"
    assert cold.headers["x-chimp-reason"] == "cold"
    hold.set()
    await task

    status = await api.get("/status", headers=_auth())
    inflight = {item["name"]: item["inflight"] for item in status.json()["endpoints"]}
    assert inflight == {"warm": 0, "cold": 0}


async def test_a_failed_connection_frees_only_its_own_slot():
    hold = asyncio.Event()
    started = asyncio.Event()
    upstream = httpx.AsyncClient(transport=httpx.MockTransport(_handler(hold, started)))
    settings = _settings()
    settings = Settings(
        listen_host=settings.listen_host,
        listen_port=settings.listen_port,
        api_key=settings.api_key,
        poll_interval_seconds=settings.poll_interval_seconds,
        request_timeout_seconds=settings.request_timeout_seconds,
        endpoints=(
            EndpointConfig("warm", "unsloth", "http://warm", "upstream-warm", 2),
            settings.endpoints[1],
        ),
        aliases=settings.aliases,
        affinity=settings.affinity,
    )
    app = build_app(settings, client=upstream)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://chimp") as api:

            async def occupy():
                async with api.stream(
                    "POST",
                    "/v1/chat/completions",
                    headers=_auth(),
                    json={"model": "executor", "stream": True, "messages": []},
                ) as response:
                    assert response.status_code == 200
                    await response.aread()

            task = asyncio.create_task(occupy())
            await asyncio.wait_for(started.wait(), timeout=2)
            failed = await api.post(
                "/v1/chat/completions",
                headers=_auth(),
                json={"model": "executor", "messages": [], "boom": True},
            )
            assert failed.status_code == 200
            assert failed.headers["x-chimp-endpoint"] == "cold"
            status = await api.get("/status", headers=_auth())
            inflight = {item["name"]: item["inflight"] for item in status.json()["endpoints"]}
            assert inflight["warm"] == 1
            hold.set()
            await task


async def test_models_list_names_the_endpoint_that_owns_each_model(client):
    api, _hold, _started = client
    response = await api.get("/v1/models", headers=_auth())
    owned = {(item["id"], item["owned_by"], item["loaded"]) for item in response.json()["data"]}
    assert ("auto", "chimp", None) in owned
    assert ("executor", "chimp", None) in owned
    assert ("coder", "warm", True) in owned
    assert ("coder", "cold", False) not in owned


async def test_streamed_chunks_reach_the_client_intact():
    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        data = b""
        while b"\r\n\r\n" not in data:
            data += await reader.read(4096)
        head, _, rest = data.partition(b"\r\n\r\n")
        length = 0
        for line in head.split(b"\r\n")[1:]:
            if line.lower().startswith(b"content-length:"):
                length = int(line.split(b":", 1)[1].strip())
        while len(rest) < length:
            rest += await reader.read(4096)
        if head.startswith(b"GET"):
            payload = b'{"object":"list","data":[{"id":"coder","loaded":true}]}'
            writer.write(
                b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: "
                + str(len(payload)).encode()
                + b"\r\n\r\n"
                + payload
            )
        else:
            body = b"data: hi\n\n"
            writer.write(b"HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\nTransfer-Encoding: chunked\r\n\r\n")
            writer.write(f"{len(body):X}\r\n".encode() + body + b"\r\n0\r\n\r\n")
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    upstream = httpx.AsyncClient()
    settings = Settings(
        listen_host="127.0.0.1",
        listen_port=8787,
        api_key=None,
        poll_interval_seconds=3600,
        request_timeout_seconds=30,
        endpoints=(EndpointConfig("box", "openai", f"http://127.0.0.1:{port}", None, 1),),
        aliases={"auto": AliasConfig("auto", ())},
        affinity=load_affinity(huggingface_enrich=False),
    )
    app = build_app(settings, client=upstream)
    try:
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://chimp") as api:
                async with api.stream(
                    "POST",
                    "/v1/chat/completions",
                    json={"model": "auto", "stream": True, "messages": []},
                ) as response:
                    assert response.status_code == 200
                    text = (await response.aread()).decode()
        assert text == "data: hi\n\n"
    finally:
        server.close()
        await server.wait_closed()
        await upstream.aclose()
