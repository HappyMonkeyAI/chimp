import time

from chimp.affinity import load_affinity
from chimp.config import AliasConfig, EndpointConfig, Settings
from chimp.inventory import ModelRecord, Snapshot
from chimp.route import place
from chimp.sticky import StickyPin, StickyTable


def _settings() -> Settings:
    return Settings(
        listen_host="127.0.0.1",
        listen_port=8787,
        api_key=None,
        poll_interval_seconds=10,
        request_timeout_seconds=30,
        endpoints=(
            EndpointConfig("laptop", "unsloth", "http://laptop", None, 1),
            EndpointConfig("desktop", "lmstudio", "http://desktop", None, 1),
        ),
        aliases={"auto": AliasConfig("auto", ())},
        affinity=load_affinity(huggingface_enrich=False),
    )


def _snap(name: str, models: list[tuple[str, bool | None]]) -> Snapshot:
    return Snapshot(
        name=name,
        healthy=True,
        models=tuple(ModelRecord(model_id, loaded) for model_id, loaded in models),
        error=None,
        checked_at=0,
    )


def test_sticky_prefers_pinned_endpoint_when_free():
    settings = _settings()
    snapshots = {
        "laptop": _snap("laptop", [("chat-a", True)]),
        "desktop": _snap("desktop", [("chat-b", True)]),
    }
    pin = StickyPin(key="sess:desk", endpoint="desktop", model_id="chat-b", expires_at=time.time() + 60)
    chosen = place(settings, snapshots, {}, "auto", sticky=pin)
    assert chosen.endpoint.name == "desktop"
    assert chosen.model_id == "chat-b"
    assert chosen.reason == "sticky"


def test_sticky_expires_and_falls_back():
    table = StickyTable(ttl_seconds=1)
    table.remember("sess:x", "laptop", "chat-a", now=100.0)
    assert table.get("sess:x", now=100.5) is not None
    assert table.get("sess:x", now=102.0) is None


def test_sticky_skips_busy_pin():
    settings = _settings()
    snapshots = {
        "laptop": _snap("laptop", [("chat-a", True)]),
        "desktop": _snap("desktop", [("chat-b", True)]),
    }
    pin = StickyPin(key="sess:desk", endpoint="desktop", model_id="chat-b", expires_at=time.time() + 60)
    chosen = place(settings, snapshots, {"desktop": 1}, "auto", sticky=pin)
    assert chosen.endpoint.name == "laptop"
    assert chosen.reason == "warm"


def test_resolve_key_prefers_prompt_cache_key():
    table = StickyTable()
    key = table.resolve_key({"prompt_cache_key": "abc", "messages": [{"role": "user", "content": "hi"}]}, {})
    assert key == "pck:abc"
