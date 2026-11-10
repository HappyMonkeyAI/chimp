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


async def test_ui_and_status_include_sticky(client):
    api, _hold, _started = client
    ui = await api.get("/ui", headers=_auth())
    assert ui.status_code == 200
    assert "text/html" in ui.headers["content-type"]
    assert b"Sticky pins" in ui.content
    status = await api.get("/status", headers=_auth())
    body = status.json()
    assert "sticky" in body
    assert "advisor" in body
    assert body["advisor"]["enabled"] is False


async def test_ui_shell_loads_without_a_header_while_status_stays_locked(client):
    api, _hold, _started = client
    ui = await api.get("/ui")
    assert ui.status_code == 200
    assert b"location.hash" in ui.content
    assert (await api.get("/status")).status_code == 401
    page = await api.get("/ui/config")
    assert page.status_code == 200
    assert b"/ui/config.yaml" in page.content


_GOOD_YAML = "endpoints:\n  - name: box\n    kind: openai\n    base_url: http://127.0.0.1:9\n"


@pytest.fixture
async def config_api(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(_GOOD_YAML, encoding="utf-8")

    async def make(api_key: str | None):
        from chimp.config import load_settings

        loaded = load_settings(path)
        settings = Settings(
            listen_host=loaded.listen_host,
            listen_port=loaded.listen_port,
            api_key=api_key,
            poll_interval_seconds=3600,
            request_timeout_seconds=30,
            endpoints=loaded.endpoints,
            aliases=loaded.aliases,
            affinity=loaded.affinity,
            enrich_on_start=False,
            config_path=path,
        )
        upstream = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"data": []})))
        app = build_app(settings, client=upstream)
        return app

    return path, make


async def _with_app(app):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://chimp")


async def test_ui_config_saves_valid_yaml_with_the_router_key(config_api):
    path, make = config_api
    app = await make("router-secret")
    async with app.router.lifespan_context(app):
        async with await _with_app(app) as api:
            raw = await api.get("/ui/config.yaml", headers=_auth())
            assert raw.status_code == 200
            assert "box" in raw.text
            assert (await api.get("/ui/config.yaml")).status_code == 401
            edited = _GOOD_YAML.replace("box", "edited")
            denied = await api.post("/ui/config", content=edited, headers={"content-type": "text/yaml"})
            assert denied.status_code == 401
            saved = await api.post(
                "/ui/config",
                content=edited,
                headers={**_auth(), "content-type": "text/yaml"},
            )
            assert saved.status_code == 200
            assert "edited" in path.read_text(encoding="utf-8")
    assert not any(item.name.endswith(".tmp") for item in path.parent.iterdir())


async def test_ui_config_refuses_writes_without_a_router_key(config_api):
    path, make = config_api
    app = await make(None)
    async with app.router.lifespan_context(app):
        async with await _with_app(app) as api:
            response = await api.post(
                "/ui/config",
                content=_GOOD_YAML.replace("box", "evil"),
                headers={"content-type": "text/yaml"},
            )
            assert response.status_code == 403
    assert "evil" not in path.read_text(encoding="utf-8")


async def test_ui_config_rejects_cross_site_form_posts(config_api):
    path, make = config_api
    app = await make("router-secret")
    async with app.router.lifespan_context(app):
        async with await _with_app(app) as api:
            response = await api.post(
                "/ui/config",
                content="body=" + _GOOD_YAML.replace("box", "evil"),
                headers={**_auth(), "content-type": "application/x-www-form-urlencoded"},
            )
            assert response.status_code == 415
    assert "evil" not in path.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "bad",
    [
        "endpoints: [\n",  # YAML syntax
        "endpoints:\n  - name: box\n    kind: nope\n    base_url: http://x\n",  # ConfigError
        "endpoints:\n  - name: box\n    kind: openai\n    base_url: http://x\n    max_concurrent: lots\n",  # ValueError
    ],
)
async def test_ui_config_keeps_the_old_file_when_the_new_one_is_invalid(config_api, bad):
    path, make = config_api
    app = await make("router-secret")
    async with app.router.lifespan_context(app):
        async with await _with_app(app) as api:
            response = await api.post("/ui/config", content=bad, headers={**_auth(), "content-type": "text/yaml"})
            assert response.status_code == 400
            assert response.json()["error"]["code"] == "invalid_config"
    assert path.read_text(encoding="utf-8") == _GOOD_YAML
    assert not any(item.name.endswith(".tmp") for item in path.parent.iterdir())


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


async def test_gzipped_upstream_stream_reaches_the_client_decoded():
    import gzip

    seen: dict[str, bytes] = {}
    sse = b'data: {"choices":[{"delta":{"content":"hi"}}]}\n\ndata: [DONE]\n\n'
    packed = gzip.compress(sse)

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        data = b""
        while b"\r\n\r\n" not in data:
            data += await reader.read(4096)
        head, _, rest = data.partition(b"\r\n\r\n")
        length = 0
        for line in head.split(b"\r\n")[1:]:
            if line.lower().startswith(b"content-length:"):
                length = int(line.split(b":", 1)[1].strip())
            if line.lower().startswith(b"accept-encoding:"):
                seen["accept-encoding"] = line.split(b":", 1)[1].strip()
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
            # Misbehaving upstream: compresses even when asked for identity.
            writer.write(
                b"HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\nContent-Encoding: gzip\r\nContent-Length: "
                + str(len(packed)).encode()
                + b"\r\n\r\n"
                + packed
            )
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
        endpoints=(EndpointConfig("cloud", "openai", f"http://127.0.0.1:{port}", None, 1, "secondary"),),
        aliases={"auto": AliasConfig("auto", ())},
        affinity=load_affinity(huggingface_enrich=False),
        enrich_on_start=False,
    )
    app = build_app(settings, client=upstream)
    try:
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://chimp") as api:
                async with api.stream(
                    "POST",
                    "/v1/chat/completions",
                    headers={"accept-encoding": "gzip"},
                    json={"model": "auto", "stream": True, "messages": []},
                ) as response:
                    assert response.status_code == 200
                    assert "content-encoding" not in response.headers
                    body = await response.aread()
        assert body == sse
        assert seen["accept-encoding"] == b"identity"
    finally:
        server.close()
        await server.wait_closed()
        await upstream.aclose()


def _advisor_app(calls: list[str]):
    from chimp.config import AdvisorConfig

    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.host == "advisor":
            calls.append(request.url.path)
            return httpx.Response(200, json={"choices": [{"message": {"content": "chat-a"}}]})
        if request.url.path == "/v1/models":
            return httpx.Response(200, json={"data": [{"id": "chat-a", "loaded": True}, {"id": "chat-b", "loaded": True}]})
        payload = json.loads(request.content.decode())
        return httpx.Response(200, json={"model": payload["model"], "choices": []})

    settings = Settings(
        listen_host="127.0.0.1",
        listen_port=8787,
        api_key=None,
        poll_interval_seconds=3600,
        request_timeout_seconds=30,
        endpoints=(EndpointConfig("desk", "unsloth", "http://desk", None, 2),),
        aliases={"auto": AliasConfig("auto", ())},
        affinity=load_affinity(huggingface_enrich=False),
        enrich_on_start=False,
        advisor=AdvisorConfig(enabled=True, base_url="http://advisor", model="tiny", timeout_seconds=1),
    )
    upstream = httpx.AsyncClient(transport=httpx.MockTransport(handle))
    return build_app(settings, client=upstream)


async def test_advisor_is_skipped_when_a_sticky_pin_already_decides():
    calls: list[str] = []
    app = _advisor_app(calls)
    async with app.router.lifespan_context(app):
        app.state.sticky.remember("sess:s1", "desk", "chat-b")
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://chimp") as api:
            response = await api.post(
                "/v1/chat/completions",
                headers={"x-chimp-session": "s1"},
                json={"model": "auto", "messages": []},
            )
    assert response.status_code == 200
    assert response.headers["x-chimp-model"] == "chat-b"
    assert response.headers["x-chimp-reason"] == "sticky"
    assert calls == []
    assert app.state.sticky.get("sess:s1").model_id == "chat-b"


async def test_advisor_still_steers_unpinned_bare_auto():
    calls: list[str] = []
    app = _advisor_app(calls)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://chimp") as api:
            response = await api.post("/v1/chat/completions", json={"model": "auto", "messages": []})
    assert response.status_code == 200
    assert response.headers["x-chimp-model"] == "chat-a"
    assert response.headers["x-chimp-reason"] == "warm+advisor"
    assert calls == ["/v1/chat/completions"]


async def test_a_read_timeout_is_not_replayed_on_another_endpoint():
    hits: list[str] = []

    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/models":
            return httpx.Response(200, json={"data": [{"id": "coder", "loaded": request.url.host == "warm"}]})
        hits.append(request.url.host)
        if request.url.host == "warm":
            raise httpx.ReadTimeout("upstream is still generating")
        return httpx.Response(200, json={"choices": []})

    upstream = httpx.AsyncClient(transport=httpx.MockTransport(handle))
    app = build_app(_settings(), client=upstream)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://chimp") as api:
            response = await api.post(
                "/v1/chat/completions",
                headers=_auth(),
                json={"model": "executor", "messages": []},
            )
            assert response.status_code == 502
            assert response.json()["error"]["code"] == "upstream_failed"
            assert hits == ["warm"]
            status = await api.get("/status", headers=_auth())
            inflight = {item["name"]: item["inflight"] for item in status.json()["endpoints"]}
            assert inflight == {"warm": 0, "cold": 0}


async def test_unreachable_upstreams_do_not_leak_addresses():
    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/models":
            return httpx.Response(200, json={"data": [{"id": "coder", "loaded": True}]})
        raise httpx.ConnectError("connect to 10.0.0.7:8888 refused")

    upstream = httpx.AsyncClient(transport=httpx.MockTransport(handle))
    app = build_app(_settings(), client=upstream)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://chimp") as api:
            response = await api.post(
                "/v1/chat/completions",
                headers=_auth(),
                json={"model": "executor", "messages": []},
            )
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "upstream_unavailable"
    assert "10.0.0.7" not in response.text
