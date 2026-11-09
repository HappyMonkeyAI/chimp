from chimp.affinity import load_affinity
from chimp.config import EndpointConfig, Settings
from chimp.inventory import ModelRecord, Snapshot
from chimp.route import RouteError, place


def _settings() -> Settings:
    laptop = EndpointConfig("laptop", "unsloth", "http://laptop", None, 1)
    desktop = EndpointConfig("desktop", "lmstudio", "http://desktop", None, 1)
    return Settings(
        listen_host="127.0.0.1",
        listen_port=8787,
        api_key=None,
        poll_interval_seconds=10,
        request_timeout_seconds=30,
        endpoints=(laptop, desktop),
        aliases={
            "executor": _alias("executor", ("qwen3-coder", "qwen3-32b")),
            "auto": _alias("auto", ()),
        },
        affinity=load_affinity(huggingface_enrich=False),
    )


def _alias(name: str, models: tuple[str, ...]):
    from chimp.config import AliasConfig

    return AliasConfig(name, models)


def _snap(name: str, models: list[tuple[str, bool | None]]) -> Snapshot:
    return Snapshot(
        name=name,
        healthy=True,
        models=tuple(ModelRecord(model_id, loaded) for model_id, loaded in models),
        error=None,
        checked_at=0,
    )


def test_warm_beats_a_higher_preference_that_is_cold():
    settings = _settings()
    snapshots = {
        "laptop": _snap("laptop", [("qwen3-32b", True)]),
        "desktop": _snap("desktop", [("qwen3-coder", False), ("qwen3-32b", False)]),
    }
    chosen = place(settings, snapshots, {}, "executor")
    assert chosen.endpoint.name == "laptop"
    assert chosen.model_id == "qwen3-32b"
    assert chosen.reason == "warm"


def test_warm_preferred_model_wins_when_both_are_loaded():
    settings = _settings()
    snapshots = {
        "laptop": _snap("laptop", [("qwen3-32b", True)]),
        "desktop": _snap("desktop", [("qwen3-coder", True)]),
    }
    chosen = place(settings, snapshots, {}, "executor")
    assert chosen.endpoint.name == "desktop"
    assert chosen.model_id == "qwen3-coder"
    assert chosen.reason == "warm"


def test_cold_load_when_nothing_warm_is_free():
    settings = _settings()
    snapshots = {
        "laptop": _snap("laptop", [("qwen3-coder", True)]),
        "desktop": _snap("desktop", [("qwen3-coder", False)]),
    }
    chosen = place(settings, snapshots, {"laptop": 1}, "executor")
    assert chosen.endpoint.name == "desktop"
    assert chosen.reason == "cold"


def test_busy_when_the_only_match_is_at_capacity():
    settings = _settings()
    snapshots = {
        "laptop": _snap("laptop", [("qwen3-coder", True)]),
        "desktop": _snap("desktop", [("other", True)]),
    }
    try:
        place(settings, snapshots, {"laptop": 1}, "executor")
    except RouteError as exc:
        assert exc.status == 429
    else:
        raise AssertionError("expected 429")


def test_auto_uses_any_loaded_chat_model_and_skips_embeddings():
    settings = _settings()
    snapshots = {
        "laptop": _snap_kinds("laptop", [("nomic-embed", True, "embedding"), ("chat-7b", True, "chat")]),
        "desktop": _snap("desktop", []),
    }
    chosen = place(settings, snapshots, {}, "auto")
    assert chosen.model_id == "chat-7b"
    assert chosen.reason == "warm"


def test_concrete_model_id_passes_through():
    settings = _settings()
    snapshots = {
        "laptop": _snap("laptop", [("gemma-3", True)]),
        "desktop": _snap("desktop", [("gemma-3", False)]),
    }
    chosen = place(settings, snapshots, {}, "gemma-3")
    assert chosen.endpoint.name == "laptop"
    assert chosen.reason == "warm"


def test_unknown_loaded_state_beats_a_confirmed_cold_model():
    settings = _settings()
    snapshots = {
        "laptop": _snap("laptop", [("qwen3-coder", None)]),
        "desktop": _snap("desktop", [("qwen3-coder", False)]),
    }
    chosen = place(settings, snapshots, {}, "executor")
    assert chosen.endpoint.name == "laptop"
    assert chosen.reason == "unknown"


def test_secondary_cloud_is_used_only_when_primary_cannot_serve():
    from chimp.affinity import load_affinity

    settings = Settings(
        listen_host="127.0.0.1",
        listen_port=8787,
        api_key=None,
        poll_interval_seconds=10,
        request_timeout_seconds=30,
        endpoints=(
            EndpointConfig("laptop", "unsloth", "http://laptop", None, 1, "primary"),
            EndpointConfig("groq", "openai", "http://groq", None, 2, "secondary"),
        ),
        aliases={"auto": _alias("auto", ())},
        affinity=load_affinity(huggingface_enrich=False),
    )
    # Primary down, secondary healthy with a chat model.
    snapshots = {
        "laptop": Snapshot("laptop", False, (), "down", 0),
        "groq": Snapshot("groq", True, (ModelRecord("llama-3.1-8b-instant", None),), None, 0),
    }
    chosen = place(settings, snapshots, {}, "auto")
    assert chosen.endpoint.name == "groq"
    assert chosen.model_id == "llama-3.1-8b-instant"

    # Primary healthy again: keep the request on the LAN GPU.
    snapshots["laptop"] = Snapshot(
        "laptop",
        True,
        (ModelRecord("unsloth/Qwen-AgentWorld-35B-A3B-GGUF", True),),
        None,
        0,
    )
    chosen = place(settings, snapshots, {}, "auto")
    assert chosen.endpoint.name == "laptop"


def test_auto_prefers_agentworld_over_lyrics_when_both_are_cold():
    settings = _settings()
    snapshots = {
        "laptop": Snapshot(
            "laptop",
            True,
            (
                ModelRecord("mradermacher/Lyrics_Qwen2.5-1.5B-Instruct-GGUF", False),
                ModelRecord("unsloth/Qwen-AgentWorld-35B-A3B-GGUF", False),
            ),
            None,
            0,
        ),
    }
    chosen = place(settings, snapshots, {}, "auto")
    assert chosen.model_id == "unsloth/Qwen-AgentWorld-35B-A3B-GGUF"
    assert chosen.reason == "cold"


def test_auto_skips_a_warm_lyrics_model_for_an_agent_fit():
    settings = _settings()
    snapshots = {
        "laptop": Snapshot(
            "laptop",
            True,
            (
                ModelRecord("mradermacher/Lyrics_Qwen2.5-1.5B-Instruct-GGUF", True),
                ModelRecord("unsloth/Qwen-AgentWorld-35B-A3B-GGUF", False),
            ),
            None,
            0,
        ),
    }
    chosen = place(settings, snapshots, {}, "auto")
    assert chosen.model_id == "unsloth/Qwen-AgentWorld-35B-A3B-GGUF"
    assert chosen.reason == "cold"


def test_a_loaded_window_that_cannot_hold_the_prompt_is_widened_in_place():
    settings = _settings()
    snapshots = {
        "laptop": Snapshot(
            "laptop",
            True,
            (ModelRecord("other", False, context=131072, max_context=131072),),
            None,
            0,
        ),
        "desktop": Snapshot(
            "desktop",
            True,
            (ModelRecord("gemma", True, "chat", 8192, 131072),),
            None,
            0,
        ),
    }
    chosen = place(settings, snapshots, {}, "auto", needed_tokens=20000)
    assert chosen.endpoint.name == "desktop"
    assert chosen.model_id == "gemma"
    assert chosen.reason == "expand"
    assert chosen.context_target == 32768


def test_a_wider_loaded_instance_beats_expanding_the_small_one():
    settings = _settings()
    snapshots = {
        "desktop": Snapshot(
            "desktop",
            True,
            (
                ModelRecord("google/gemma-4-e2b", True, "chat", 8192, 131072),
                ModelRecord("google/gemma-4-e2b:2", True, "chat", 131072, 131072),
            ),
            None,
            0,
        ),
    }
    chosen = place(settings, snapshots, {}, "auto", needed_tokens=20000)
    assert chosen.model_id == "google/gemma-4-e2b:2"
    assert chosen.reason == "warm"


def test_context_error_inside_a_stream_chunk_is_recognized():
    from chimp.route import overflow_tokens

    body = b'data: {"error":{"code":400,"message":"request (19305 tokens) exceeds the available context size (8192 tokens)","type":"exceed_context_size_error","n_prompt_tokens":19305,"n_ctx":8192}}\n\n'
    assert overflow_tokens(body) == 21353


def test_a_model_already_wide_enough_stays_warm():
    settings = _settings()
    snapshots = {
        "laptop": Snapshot("laptop", True, (ModelRecord("other", False),), None, 0),
        "desktop": Snapshot(
            "desktop",
            True,
            (ModelRecord("gemma", True, "chat", 32768, 131072),),
            None,
            0,
        ),
    }
    chosen = place(settings, snapshots, {}, "auto", needed_tokens=20000)
    assert chosen.reason == "warm"
    assert chosen.model_id == "gemma"


def test_unreachable_fleet_is_503():
    settings = _settings()
    down = Snapshot("laptop", False, (), "connect", 0)
    try:
        place(settings, {"laptop": down, "desktop": down}, {}, "executor")
    except RouteError as exc:
        assert exc.status == 503
    else:
        raise AssertionError("expected 503")


def test_auto_coder_prefers_coder_model_over_agentworld_when_both_warm():
    settings = _settings()
    snapshots = {
        "laptop": _snap("laptop", [("unsloth/Qwen3-Coder-30B-A3B-GGUF", True)]),
        "desktop": _snap("desktop", [("unsloth/Qwen-AgentWorld-35B-A3B-GGUF", True)]),
    }
    chosen = place(settings, snapshots, {}, "auto:coder")
    assert chosen.model_id == "unsloth/Qwen3-Coder-30B-A3B-GGUF"
    assert chosen.endpoint.name == "laptop"
    assert chosen.requested == "auto:coder"


def test_chimpr_auto_coder_prefix_resolves_like_auto_coder():
    from chimp.route import resolve_model

    settings = _settings()
    label, preferred = resolve_model("chimpr/auto:coder", settings)
    assert label == "auto:coder"
    assert preferred == ()
    chosen = place(
        settings,
        {
            "laptop": _snap("laptop", [("unsloth/Qwen3-Coder-30B-A3B-GGUF", True)]),
            "desktop": _snap("desktop", [("unsloth/Qwen-AgentWorld-35B-A3B-GGUF", True)]),
        },
        {},
        "chimpr/auto:coder",
    )
    assert chosen.model_id == "unsloth/Qwen3-Coder-30B-A3B-GGUF"


def _snap_kinds(name: str, models: list[tuple[str, bool | None, str]]) -> Snapshot:
    return Snapshot(
        name=name,
        healthy=True,
        models=tuple(ModelRecord(model_id, loaded, kind) for model_id, loaded, kind in models),
        error=None,
        checked_at=0,
    )
