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
