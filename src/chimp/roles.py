"""Canonical placement roles / OpenBot work-classes."""

from __future__ import annotations

# Vibes-style roles + OpenBot auto:<class> work-classes (affinity keys).
VIBES_ROLES = ("auto", "planner", "executor", "reviewer", "triage")
OPENBOT_CLASSES = (
    "coder",
    "ops",
    "research",
    "writer",
    "design",
    "qa",
    "docs",
    "skills",
    "assistant",
    "coord",
)
ROLES = VIBES_ROLES + OPENBOT_CLASSES

# Aliases listed for clients (OpenBot model field / Vibes roles).
AUTO_CLASS_ALIASES = ("auto",) + tuple(f"auto:{name}" for name in OPENBOT_CLASSES)

PROVIDER_PREFIXES = frozenset({"chimp", "chimpr"})


def strip_provider_prefix(model_id: str) -> str:
    """chimpr/auto:coder -> auto:coder; leave real HF ids alone."""
    name = (model_id or "").strip()
    if "/" not in name:
        return name
    head, _, rest = name.partition("/")
    if head.casefold() in PROVIDER_PREFIXES and rest:
        return rest
    return name


def normalize_role(role: str) -> str:
    """Map request labels to an affinity role key."""
    name = strip_provider_prefix(role or "auto").strip().casefold()
    if not name or name == "auto":
        return "auto"
    if name.startswith("auto:"):
        name = name[5:]
    if name in ROLES:
        return name
    return "auto"


def default_auto_class_aliases() -> dict[str, tuple[str, ...]]:
    """Empty preference lists: any chat model, ranked by affinity for the class."""
    return {alias: () for alias in AUTO_CLASS_ALIASES}
