# ADR-0002: Secondary cloud tier

## Status

Accepted — 2026-11-07

## Context

LAN GPUs (Unsloth / LM Studio) are the preferred serving plane. Free cloud OpenAI-compatible APIs (Groq, Mistral, LLM7, …) are useful when every primary is down or busy, but must not steal traffic from a warm local model.

## Decision

- Endpoints may set `tier: primary` (default) or `tier: secondary`.
- `place()` builds the free candidate pool as `primary_free or secondary_free` — secondaries only when the primary free set is empty.
- Ranking still prefers warm → expand → unknown → cold within that pool; affinity applies as usual.

## Consequences

- Cloud keys remain optional env vars; without them, inventory/chat may 401 — placement can still select the endpoint when primaries cannot serve.
- GitHub Models left commented until a non-`/v1` path adapter exists.
