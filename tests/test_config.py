from pathlib import Path

import pytest

from chimp.config import ConfigError, load_settings


def test_env_expansion_and_v1_suffix(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("UNSLOTH_API_KEY", "sk-test")
    path = tmp_path / "config.yaml"
    path.write_text(
        """
listen: 0.0.0.0:8787
api_key: ${CHIMP_API_KEY:-}
aliases:
  executor:
    models: [coder]
endpoints:
  - name: laptop
    kind: unsloth
    base_url: http://127.0.0.1:8888/v1
    api_key: ${UNSLOTH_API_KEY}
    max_concurrent: 2
""",
        encoding="utf-8",
    )
    monkeypatch.delenv("CHIMP_API_KEY", raising=False)
    settings = load_settings(path)
    assert settings.listen_host == "0.0.0.0"
    assert settings.listen_port == 8787
    assert settings.api_key is None
    assert settings.endpoints[0].base_url == "http://127.0.0.1:8888"
    assert settings.endpoints[0].api_key == "sk-test"
    assert settings.endpoints[0].max_concurrent == 2
    assert settings.aliases["executor"].models == ("coder",)
    assert settings.affinity.score("unsloth/Qwen-AgentWorld-35B-A3B-GGUF", "executor") >= 95


def test_unknown_kind_is_rejected(tmp_path: Path):
    path = tmp_path / "config.yaml"
    path.write_text(
        """
endpoints:
  - name: x
    kind: mystery
    base_url: http://127.0.0.1:1
""",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError):
        load_settings(path)


def test_missing_file(tmp_path: Path):
    with pytest.raises(ConfigError):
        load_settings(tmp_path / "missing.yaml")


@pytest.mark.parametrize(
    "extra, message",
    [
        ("poll_interval_seconds: 0\n", "poll_interval_seconds must be at least 1"),
        ("sticky_ttl_seconds: 0\n", "sticky_ttl_seconds must be at least 1"),
        ("request_timeout_seconds: soon\n", "request_timeout_seconds must be a number"),
    ],
)
def test_explicit_bad_numbers_are_errors_not_defaults(tmp_path, extra, message):
    path = tmp_path / "config.yaml"
    path.write_text(extra + "endpoints:\n  - name: a\n    kind: openai\n    base_url: http://x\n", encoding="utf-8")
    with pytest.raises(ConfigError, match=message):
        load_settings(path)


@pytest.mark.parametrize("value, message", [("0", "at least 1"), ("lots", "must be a number"), ("1.5", "whole number")])
def test_max_concurrent_is_validated(tmp_path, value, message):
    path = tmp_path / "config.yaml"
    path.write_text(
        f"endpoints:\n  - name: a\n    kind: openai\n    base_url: http://x\n    max_concurrent: {value}\n",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match=message):
        load_settings(path)


def test_blank_env_placeholders_still_fall_back_to_defaults(tmp_path, monkeypatch):
    monkeypatch.delenv("CHIMP_POLL", raising=False)
    path = tmp_path / "config.yaml"
    path.write_text(
        "poll_interval_seconds: ${CHIMP_POLL:-}\nendpoints:\n  - name: a\n    kind: openai\n    base_url: http://x\n",
        encoding="utf-8",
    )
    assert load_settings(path).poll_interval_seconds == 10


def test_admin_key_loads_and_must_differ_from_api_key(tmp_path, monkeypatch):
    monkeypatch.setenv("CHIMP_API_KEY", "same")
    monkeypatch.setenv("CHIMP_ADMIN_KEY", "same")
    path = tmp_path / "config.yaml"
    path.write_text(
        "api_key: ${CHIMP_API_KEY:-}\nadmin_key: ${CHIMP_ADMIN_KEY:-}\n"
        "endpoints:\n  - name: a\n    kind: openai\n    base_url: http://x\n",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="admin_key must differ"):
        load_settings(path)
    monkeypatch.setenv("CHIMP_ADMIN_KEY", "different")
    assert load_settings(path).admin_key == "different"
    monkeypatch.delenv("CHIMP_ADMIN_KEY")
    assert load_settings(path).admin_key is None
