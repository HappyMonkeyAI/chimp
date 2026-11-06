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
                {"id": "coder", "state": "loaded", "type": "llm"},
                {"id": "vision", "state": "not-loaded", "type": "vlm"},
                {"id": "embed", "state": "loaded", "type": "embeddings"},
            ]
        }
    )
    assert [(item.id, item.loaded, item.kind) for item in records] == [
        ("coder", True, "chat"),
        ("vision", False, "chat"),
        ("embed", True, "embedding"),
    ]


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
