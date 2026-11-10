from chimp.inventory import merge_running, parse_lmstudio_models, parse_openai_models, parse_running


def test_unsloth_loaded_flag_and_default_when_the_flag_is_absent():
    flagged = parse_openai_models(
        {"data": [{"id": "a", "loaded": True}, {"id": "b", "loaded": False}]},
        loaded_default=True,
    )
    assert [(item.id, item.loaded) for item in flagged] == [("a", True), ("b", False)]

    implied = parse_openai_models({"data": [{"id": "gemma"}]}, loaded_default=True)
    assert implied[0].loaded is True

    unknown = parse_openai_models({"data": [{"id": "gemma"}]}, loaded_default=None)
    assert unknown[0].loaded is None


def test_lmstudio_state_and_kind():
    records = parse_lmstudio_models(
        {
            "data": [
                {"id": "coder", "state": "loaded", "type": "llm", "loaded_context_length": 8192, "max_context_length": 131072},
                {"id": "vision", "state": "not-loaded", "type": "vlm", "max_context_length": 262144},
                {"id": "embed", "state": "loaded", "type": "embeddings"},
            ]
        }
    )
    assert [(item.id, item.loaded, item.kind) for item in records] == [
        ("coder", True, "chat"),
        ("vision", False, "chat"),
        ("embed", True, "embedding"),
    ]
    assert records[0].context == 8192
    assert records[0].max_context == 131072
    assert records[1].context == 262144


def test_llamaswap_running_list_marks_ready_models():
    catalog = parse_openai_models(
        {"data": [{"id": "coder"}, {"id": "chat"}]},
        loaded_default=None,
    )
    running = parse_running(
        {"running": [{"model": "coder", "state": "ready"}, {"model": "chat", "state": "starting"}]}
    )
    merged = merge_running(catalog, running)
    by_id = {item.id: item.loaded for item in merged}
    assert by_id == {"coder": True, "chat": False}


def test_legacy_running_object():
    assert parse_running({"model": "coder", "state": "ready"}) == {"coder": "ready"}
    assert parse_running({}) == {}


async def test_refresh_probes_endpoints_in_parallel():
    import asyncio
    import time

    import httpx

    from chimp.config import EndpointConfig
    from chimp.inventory import Inventory

    async def slow(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(0.3)
        return httpx.Response(200, json={"data": [{"id": request.url.host}]})

    endpoints = tuple(EndpointConfig(f"e{i}", "openai", f"http://e{i}", None) for i in range(4))
    async with httpx.AsyncClient(transport=httpx.MockTransport(slow)) as client:
        inventory = Inventory(endpoints, client)
        started = time.perf_counter()
        await inventory.refresh_all()
        elapsed = time.perf_counter() - started
    assert elapsed < 0.9  # serial would be ~1.2 s
    assert sorted(inventory.snapshots()) == ["e0", "e1", "e2", "e3"]
    assert inventory.snapshots()["e2"].models[0].id == "e2"
