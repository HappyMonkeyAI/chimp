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
