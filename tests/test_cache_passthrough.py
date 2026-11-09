from chimp.app import CACHE_BODY_KEYS, _keep_cache_fields


def test_cache_fields_are_preserved_on_payload():
    payload = {
        "model": "auto",
        "prompt_cache_key": "thread-1",
        "prompt_cache_retention": "24h",
        "prompt_cache_options": {"ttl": "24h"},
        "messages": [{"role": "user", "content": "hi", "cache_control": {"type": "ephemeral"}}],
    }
    before = {key: payload[key] for key in CACHE_BODY_KEYS}
    payload["model"] = "chat-7b"
    _keep_cache_fields(payload)
    for key, value in before.items():
        assert payload[key] == value
    assert payload["messages"][0]["cache_control"] == {"type": "ephemeral"}
