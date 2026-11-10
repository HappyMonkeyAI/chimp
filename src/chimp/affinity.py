"""Role affinity scores for known and unknown models."""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

import httpx
import yaml

from chimp.roles import ROLES, normalize_role

log = logging.getLogger("chimp.affinity")

_PARAM_RE = re.compile(
    r"(?P<n>\d+(?:\.\d+)?)\s*[bB](?:illion)?|(?P<m>\d+(?:\.\d+)?)\s*[mM](?:illion)?"
)


@dataclass(frozen=True)
class RoleScores:
    auto: int = 50
    planner: int = 50
    executor: int = 50
    reviewer: int = 50
    triage: int = 40
    coder: int = 50
    ops: int = 50
    research: int = 50
    writer: int = 50
    design: int = 50
    qa: int = 50
    docs: int = 50
    skills: int = 50
    assistant: int = 50
    coord: int = 50

    def get(self, role: str) -> int:
        key = normalize_role(role)
        return int(getattr(self, key, self.auto))


@dataclass(frozen=True)
class CuratedModel:
    match: str
    roles: RoleScores
    notes: str = ""


@dataclass
class ModelHints:
    params_b: float | None = None
    tags: frozenset[str] = field(default_factory=frozenset)
    context: int | None = None
    source: str = "local"


@dataclass
class AffinityCatalog:
    curated: tuple[CuratedModel, ...]
    demote_substrings: tuple[str, ...]
    boost_substrings: dict[str, RoleScores]
    by_params: tuple[tuple[float, RoleScores], ...]
    default_roles: RoleScores
    huggingface_enrich: bool = False
    _hf_cache: dict[str, ModelHints | None] = field(default_factory=dict, repr=False)
    _live_scores: dict[str, dict[str, int]] = field(default_factory=dict, repr=False)

    def seed_live(self, model_ids: list[str], roles: tuple[str, ...] = ("auto", "coder", "research")) -> dict[str, dict[str, int]]:
        """Score live inventory ids (warms HF cache when enrich is on). Returns role→score map."""
        report: dict[str, dict[str, int]] = {}
        for model_id in model_ids:
            per_role = {role: self.score(model_id, role) for role in roles}
            self._live_scores[model_id] = per_role
            report[model_id] = per_role
        return report

    def score(self, model_id: str, role: str, hints: ModelHints | None = None) -> int:
        role = normalize_role(role)
        folded = model_id.casefold()
        for entry in self.curated:
            if entry.match.casefold() in folded:
                return max(0, min(100, entry.roles.get(role)))

        effective = hints or ModelHints()
        if self.huggingface_enrich and effective.params_b is None and not effective.tags:
            # Cache read only: score() runs inside placement and must never do I/O.
            fetched = self.cached_hints(model_id)
            if fetched is not None:
                effective = fetched

        if any(token in folded for token in self.demote_substrings):
            return 0

        scores = self._band_scores(effective.params_b if effective.params_b is not None else _guess_params_b(model_id))
        total = scores.get(role)
        for token, boost in self.boost_substrings.items():
            if token in folded or token in {tag.casefold() for tag in effective.tags}:
                total += boost.get(role)
        for tag in effective.tags:
            low = tag.casefold()
            if low in {"agent", "tool_use", "tools", "code", "coder", "conversational"}:
                if role in {"auto", "executor", "coder", "ops", "skills", "coord"}:
                    total += 8
            if low in {"world-model", "environment-simulation"} and role in {
                "auto",
                "executor",
                "coder",
                "coord",
                "skills",
            }:
                total += 10
            if low in {"research", "web", "search"} and role in {"research", "writer", "docs"}:
                total += 8
        return max(0, min(100, total))

    def _band_scores(self, params_b: float | None) -> RoleScores:
        if params_b is None:
            return self.default_roles
        for maximum, scores in self.by_params:
            if params_b < maximum:
                return scores
        return self.default_roles

    def cached_hints(self, model_id: str) -> ModelHints | None:
        repo = _hf_repo_id(model_id)
        return self._hf_cache.get(repo) if repo else None

    async def prefetch_huggingface(
        self,
        client: httpx.AsyncClient,
        model_ids: list[str],
        concurrency: int = 4,
    ) -> int:
        """Fill the Hugging Face cache for repos not seen yet. Returns how many were fetched."""
        if not self.huggingface_enrich:
            return 0
        repos: list[str] = []
        for model_id in model_ids:
            repo = _hf_repo_id(model_id)
            if repo and repo not in self._hf_cache and repo not in repos:
                repos.append(repo)
        if not repos:
            return 0
        gate = asyncio.Semaphore(concurrency)

        async def fetch(repo: str) -> None:
            async with gate:
                self._hf_cache[repo] = await _fetch_hf_hints(client, repo)

        await asyncio.gather(*(fetch(repo) for repo in repos))
        return len(repos)


async def _fetch_hf_hints(client: httpx.AsyncClient, repo: str) -> ModelHints | None:
    try:
        response = await client.get(
            f"https://huggingface.co/api/models/{repo}",
            timeout=5.0,
            follow_redirects=True,
        )
        if response.status_code >= 400:
            return None
        return _hints_from_hf(response.json())
    except Exception as exc:  # noqa: BLE001 — enrich is best-effort
        log.debug("huggingface enrich failed for %s: %s", repo, exc)
        return None


def load_affinity(path: Path | None = None, *, huggingface_enrich: bool = False) -> AffinityCatalog:
    target = path or packaged_models_path()
    raw = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
    curated: list[CuratedModel] = []
    for item in raw.get("models") or []:
        if not isinstance(item, dict):
            continue
        match = str(item.get("match") or "").strip()
        if not match:
            continue
        curated.append(
            CuratedModel(
                match=match,
                roles=_role_scores(item.get("roles") or {}),
                notes=str(item.get("notes") or ""),
            )
        )
    heuristics = raw.get("heuristics") or {}
    demote = tuple(str(item).casefold() for item in (heuristics.get("demote_substrings") or []))
    boost: dict[str, RoleScores] = {}
    for key, value in (heuristics.get("boost_substrings") or {}).items():
        boost[str(key).casefold()] = _role_scores(value if isinstance(value, dict) else {})
    bands: list[tuple[float, RoleScores]] = []
    for item in heuristics.get("by_params_b") or []:
        if not isinstance(item, dict):
            continue
        bands.append((float(item.get("max") or 1000), _role_scores(item.get("roles") or {})))
    return AffinityCatalog(
        curated=tuple(curated),
        demote_substrings=demote,
        boost_substrings=boost,
        by_params=tuple(bands),
        default_roles=_role_scores(heuristics.get("default_roles") or {}),
        huggingface_enrich=huggingface_enrich,
    )


def packaged_models_path() -> Path:
    return Path(__file__).with_name("models.yaml")


def _role_scores(raw: object) -> RoleScores:
    data = raw if isinstance(raw, dict) else {}
    auto = int(data.get("auto", 50))
    executor = int(data.get("executor", auto))
    planner = int(data.get("planner", auto))
    reviewer = int(data.get("reviewer", auto))
    triage = int(data.get("triage", 40))
    # OpenBot classes inherit nearest Vibes role when omitted in YAML.
    return RoleScores(
        auto=auto,
        planner=planner,
        executor=executor,
        reviewer=reviewer,
        triage=triage,
        coder=int(data.get("coder", executor)),
        ops=int(data.get("ops", executor)),
        research=int(data.get("research", planner)),
        writer=int(data.get("writer", reviewer)),
        design=int(data.get("design", reviewer)),
        qa=int(data.get("qa", reviewer)),
        docs=int(data.get("docs", planner)),
        skills=int(data.get("skills", executor)),
        assistant=int(data.get("assistant", triage if triage > 50 else auto)),
        coord=int(data.get("coord", auto)),
    )


def _guess_params_b(model_id: str) -> float | None:
    best: float | None = None
    for match in _PARAM_RE.finditer(model_id.replace("_", "-")):
        if match.group("n"):
            value = float(match.group("n"))
        else:
            value = float(match.group("m")) / 1000.0
        if best is None or value > best:
            best = value
    return best


def _hf_repo_id(model_id: str) -> str | None:
    cleaned = model_id
    head, sep, tail = cleaned.rpartition(":")
    if sep and (tail.isdigit() or tail.upper().startswith(("Q", "UD-", "IQ", "BF"))):
        cleaned = head
    if ":" in cleaned:
        cleaned = cleaned.split(":", 1)[0]
    if "/" not in cleaned:
        return None
    return cleaned


def _hints_from_hf(payload: object) -> ModelHints:
    if not isinstance(payload, dict):
        return ModelHints(source="huggingface")
    tags = {str(item) for item in (payload.get("tags") or []) if item}
    card = payload.get("cardData") if isinstance(payload.get("cardData"), dict) else {}
    for item in card.get("tags") or []:
        tags.add(str(item))
    params_b = None
    gguf = payload.get("gguf") if isinstance(payload.get("gguf"), dict) else {}
    total = gguf.get("total")
    if isinstance(total, (int, float)) and total > 0:
        params_b = float(total) / 1_000_000_000.0 if total > 1000 else float(total)
    safetensors = payload.get("safetensors") if isinstance(payload.get("safetensors"), dict) else {}
    st_total = safetensors.get("total")
    if params_b is None and isinstance(st_total, (int, float)) and st_total > 0:
        params_b = float(st_total) / 1_000_000_000.0 if st_total > 1000 else float(st_total)
    context = gguf.get("context_length")
    return ModelHints(
        params_b=params_b,
        tags=frozenset(tags),
        context=int(context) if isinstance(context, int) else None,
        source="huggingface",
    )


# Re-export for older imports
_normalize_role = normalize_role
