"""Load the router config from YAML, expanding ${ENV} placeholders."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

if TYPE_CHECKING:
    from chimp.affinity import AffinityCatalog

_ENV = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")
KINDS = {"unsloth", "lmstudio", "llamaswap", "openai"}


class ConfigError(ValueError):
    """The config file is missing a required field or has a bad value."""


@dataclass(frozen=True)
class EndpointConfig:
    name: str
    kind: str
    base_url: str
    api_key: str | None
    max_concurrent: int = 1


@dataclass(frozen=True)
class AliasConfig:
    name: str
    models: tuple[str, ...]


@dataclass(frozen=True)
class Settings:
    listen_host: str
    listen_port: int
    api_key: str | None
    poll_interval_seconds: float
    request_timeout_seconds: float
    endpoints: tuple[EndpointConfig, ...]
    aliases: dict[str, AliasConfig]
    affinity: AffinityCatalog
    huggingface_enrich: bool = False


def expand_env(value: object) -> object:
    if isinstance(value, str):
        return _ENV.sub(_replace_env, value)
    if isinstance(value, list):
        return [expand_env(item) for item in value]
    if isinstance(value, dict):
        return {key: expand_env(item) for key, item in value.items()}
    return value


def _replace_env(match: re.Match[str]) -> str:
    name, default = match.group(1), match.group(2)
    if name in os.environ:
        return os.environ[name]
    if default is not None:
        return default
    return ""


def load_settings(path: Path) -> Settings:
    if not path.is_file():
        raise ConfigError(
            f"Config not found at {path}. Copy config.example.yaml to config.yaml and edit the endpoints."
        )
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ConfigError("Config root must be a mapping.")
    data = expand_env(raw)
    assert isinstance(data, dict)
    host, port = _parse_listen(str(data.get("listen") or "127.0.0.1:8787"))
    endpoints = tuple(_parse_endpoint(item) for item in _as_list(data.get("endpoints"), "endpoints"))
    if not endpoints:
        raise ConfigError("Config needs at least one endpoint.")
    names = [item.name for item in endpoints]
    if len(names) != len(set(names)):
        raise ConfigError("Endpoint names must be unique.")
    aliases = _parse_aliases(data.get("aliases") or {})
    api_key = _blank_to_none(data.get("api_key"))
    huggingface_enrich = bool(data.get("huggingface_enrich") or False)
    affinity_path = _optional_path(data.get("models_path"), path.parent)
    from chimp.affinity import load_affinity

    try:
        affinity = load_affinity(affinity_path, huggingface_enrich=huggingface_enrich)
    except Exception as exc:
        raise ConfigError(f"Could not load models affinity map: {exc}") from exc
    return Settings(
        listen_host=host,
        listen_port=port,
        api_key=api_key,
        poll_interval_seconds=float(data.get("poll_interval_seconds") or 10),
        request_timeout_seconds=float(data.get("request_timeout_seconds") or 600),
        endpoints=endpoints,
        aliases=aliases,
        affinity=affinity,
        huggingface_enrich=huggingface_enrich,
    )


def _parse_listen(value: str) -> tuple[str, int]:
    host, separator, port = value.rpartition(":")
    if not separator:
        raise ConfigError(f"listen must look like 127.0.0.1:8787, got {value!r}.")
    host = host or "127.0.0.1"
    try:
        parsed = int(port)
    except ValueError as exc:
        raise ConfigError(f"listen port is not an integer: {value!r}.") from exc
    if parsed < 1 or parsed > 65535:
        raise ConfigError(f"listen port out of range: {parsed}.")
    return host, parsed


def _parse_endpoint(item: object) -> EndpointConfig:
    if not isinstance(item, dict):
        raise ConfigError("Each endpoint must be a mapping.")
    name = str(item.get("name") or "").strip()
    kind = str(item.get("kind") or "").strip().lower()
    base_url = _normalize_base_url(str(item.get("base_url") or ""))
    if not name:
        raise ConfigError("Every endpoint needs a name.")
    if kind not in KINDS:
        raise ConfigError(f"Endpoint {name!r} kind must be one of {sorted(KINDS)}.")
    if not base_url:
        raise ConfigError(f"Endpoint {name!r} needs a base_url.")
    max_concurrent = int(item.get("max_concurrent") or 1)
    if max_concurrent < 1:
        raise ConfigError(f"Endpoint {name!r} max_concurrent must be at least 1.")
    return EndpointConfig(
        name=name,
        kind=kind,
        base_url=base_url,
        api_key=_blank_to_none(item.get("api_key")),
        max_concurrent=max_concurrent,
    )


def _normalize_base_url(url: str) -> str:
    cleaned = url.strip().rstrip("/")
    if cleaned.endswith("/v1"):
        cleaned = cleaned[: -len("/v1")]
    return cleaned


def _parse_aliases(raw: object) -> dict[str, AliasConfig]:
    if not isinstance(raw, dict):
        raise ConfigError("aliases must be a mapping of role name to models.")
    aliases: dict[str, AliasConfig] = {}
    for name, spec in raw.items():
        models: list[str] = []
        if isinstance(spec, dict):
            listed = spec.get("models") or []
            if not isinstance(listed, list):
                raise ConfigError(f"Alias {name!r} models must be a list.")
            models = [str(item) for item in listed if str(item).strip()]
        elif isinstance(spec, list):
            models = [str(item) for item in spec if str(item).strip()]
        elif spec not in (None, ""):
            raise ConfigError(f"Alias {name!r} must be a list or a mapping with models.")
        aliases[str(name)] = AliasConfig(name=str(name), models=tuple(models))
    return aliases


def _as_list(value: object, label: str) -> list[object]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ConfigError(f"{label} must be a list.")
    return value


def _blank_to_none(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _optional_path(value: object, base: Path) -> Path | None:
    text = _blank_to_none(value)
    if text is None:
        return None
    path = Path(text)
    if not path.is_absolute():
        path = base / path
    return path
