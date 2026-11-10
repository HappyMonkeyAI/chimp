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


def test_sticky_table_stays_bounded_without_status_polls():
    table = StickyTable(ttl_seconds=60, max_pins=3)
    table.remember("old", "laptop", "a", now=0.0)
    for index in range(10):
        table.remember(f"k{index}", "laptop", "a", now=100.0 + index)
    assert len(table._pins) == 3
    assert table.get("old", now=110.0) is None
    assert table.get("k9", now=110.0) is not None


def test_re_pinning_a_key_refreshes_its_eviction_order():
    table = StickyTable(ttl_seconds=600, max_pins=2)
    table.remember("a", "laptop", "m", now=0.0)
    table.remember("b", "laptop", "m", now=1.0)
    table.remember("a", "laptop", "m", now=2.0)  # a is now newest
    table.remember("c", "laptop", "m", now=3.0)  # evicts b, not a
    assert table.get("a", now=4.0) is not None
    assert table.get("b", now=4.0) is None
