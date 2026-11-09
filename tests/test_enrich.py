from pathlib import Path

import pytest

from chimp.affinity import load_affinity
from chimp.config import load_settings


def test_enrich_on_start_default_true(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("CHIMP_NO_ENRICH", raising=False)
    path = tmp_path / "config.yaml"
    path.write_text(
        """
endpoints:
  - name: x
    kind: openai
    base_url: http://127.0.0.1:1
""",
        encoding="utf-8",
    )
    settings = load_settings(path)
    assert settings.enrich_on_start is True


def test_no_enrich_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("CHIMP_NO_ENRICH", "1")
    path = tmp_path / "config.yaml"
    path.write_text(
        """
endpoints:
  - name: x
    kind: openai
    base_url: http://127.0.0.1:1
""",
        encoding="utf-8",
    )
    settings = load_settings(path)
    assert settings.enrich_on_start is False


def test_seed_live_scores_unknown_ids():
    catalog = load_affinity(huggingface_enrich=False)
    report = catalog.seed_live(["acme/mystery-9b-coder", "acme/mystery-lyrics"])
    assert report["acme/mystery-9b-coder"]["coder"] > report["acme/mystery-lyrics"]["coder"]
