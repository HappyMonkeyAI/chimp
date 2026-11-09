# ADR-0003: Sticky placement for cache locality

## Status

Accepted — 2026-11-09

## Context

LAN backends (llama.cpp / LM Studio / Unsloth) keep KV in VRAM. Multi-turn OpenBot desks lose reuse when chimp hops hosts between turns. Cloud secondaries also benefit from stable `prompt_cache_key` / `cache_control` fields. Chimp must not own a KV store — only improve locality on top of warm → expand → affinity.

## Decision

Sticky key sources, first match wins:

1. JSON body `prompt_cache_key` (string)
2. Request header `X-Chimp-Session`
3. SHA-256 prefix hash of stable early messages (system + first user text, truncated)

When a key is present and a pin exists within TTL:

- Prefer that endpoint + model if it is still a **legal free** candidate (healthy, under `max_concurrent`, affinity/gates still apply).
- Reason becomes `sticky` (still warm/expand/unknown/cold under the hood for ranking when the pin misses).
- Busy / missing / unhealthy → ignore pin, place normally, clear pin on hard miss of the pinned endpoint.

TTL defaults to 1800s; configurable via `sticky_ttl_seconds`. Disable with `sticky: false`.

Secondary tier: do not strip known cloud cache knobs from the JSON body (`prompt_cache_key`, `prompt_cache_retention`, `prompt_cache_options`, per-message `cache_control`).

## Consequences

- `/status` exposes active pins for operators.
- Explicit `auto:<class>` and hard capacity gates always beat stickiness.
- Prefix hashing is best-effort; clients that set `prompt_cache_key` or `X-Chimp-Session` get stronger locality.
