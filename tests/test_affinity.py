from chimp.affinity import ModelHints, load_affinity


def test_curated_agentworld_scores_high_for_executor():
    catalog = load_affinity(huggingface_enrich=False)
    assert catalog.score("unsloth/Qwen-AgentWorld-35B-A3B-GGUF", "executor") >= 95
    assert catalog.score("unsloth/Qwen-AgentWorld-35B-A3B-GGUF", "triage") < 40


def test_lyrics_models_are_demoted():
    catalog = load_affinity(huggingface_enrich=False)
    assert catalog.score("mradermacher/Lyrics_Qwen2.5-1.5B-Instruct-GGUF", "auto") == 0


def test_unknown_coder_name_gets_a_boost():
    catalog = load_affinity(huggingface_enrich=False)
    plain = catalog.score("acme/mystery-9b", "executor")
    coder = catalog.score("acme/mystery-9b-coder", "executor")
    assert coder > plain


def test_param_band_marks_tiny_models_as_triage():
    catalog = load_affinity(huggingface_enrich=False)
    tiny = catalog.score("local/unknown-2b-chat", "triage")
    tiny_exec = catalog.score("local/unknown-2b-chat", "executor")
    assert tiny > tiny_exec


def test_huggingface_tags_can_enrich_an_unknown_model():
    catalog = load_affinity(huggingface_enrich=False)
    hints = ModelHints(params_b=35.0, tags=frozenset({"agent", "world-model"}), source="test")
    score = catalog.score("org/mystery-agent-moe", "executor", hints=hints)
    assert score >= 85


def test_coder_class_ranks_qwen_coder_above_agentworld():
    catalog = load_affinity(huggingface_enrich=False)
    coder = catalog.score("unsloth/Qwen3-Coder-30B-A3B-GGUF", "auto:coder")
    world = catalog.score("unsloth/Qwen-AgentWorld-35B-A3B-GGUF", "auto:coder")
    assert coder > world


def test_normalize_strips_chimpr_provider_prefix():
    from chimp.roles import normalize_role, strip_provider_prefix

    assert strip_provider_prefix("chimpr/auto:research") == "auto:research"
    assert normalize_role("chimpr/auto:coder") == "coder"
    assert normalize_role("auto:ops") == "ops"


def test_scoring_never_does_network_io_even_with_enrich_on(monkeypatch):
    import httpx

    def boom(*_args, **_kwargs):
        raise AssertionError("score() must not touch the network")

    monkeypatch.setattr(httpx, "get", boom)
    monkeypatch.setattr(httpx.Client, "send", boom)
    monkeypatch.setattr(httpx.AsyncClient, "send", boom)
    catalog = load_affinity(huggingface_enrich=True)
    catalog.score("org/mystery-agent-moe", "executor")


async def test_prefetch_fills_the_cache_that_scoring_reads():
    import httpx

    requested: list[str] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requested.append(request.url.path)
        return httpx.Response(200, json={"tags": ["agent", "world-model"], "safetensors": {"total": 35_000_000_000}})

    catalog = load_affinity(huggingface_enrich=True)
    before = catalog.score("org/mystery-agent-moe", "executor")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        fetched = await catalog.prefetch_huggingface(client, ["org/mystery-agent-moe", "org/mystery-agent-moe:2"])
        again = await catalog.prefetch_huggingface(client, ["org/mystery-agent-moe"])
    assert fetched == 1
    assert again == 0
    assert requested == ["/api/models/org/mystery-agent-moe"]
    assert catalog.score("org/mystery-agent-moe", "executor") > before


async def test_prefetch_is_a_no_op_when_enrich_is_off():
    import httpx

    catalog = load_affinity(huggingface_enrich=False)
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(500))) as client:
        assert await catalog.prefetch_huggingface(client, ["org/x"]) == 0
