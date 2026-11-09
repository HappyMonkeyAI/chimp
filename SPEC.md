# SPEC.md — chimp acceptance criteria

Each criterion is independently verifiable. Evidence: unit | integration | live.

## S1 — Install & config

- [x] `pip install -e .` (or install scripts) produces a `chimp` console entrypoint. *(live — install.ps1 smoke 2026-11-08)*
- [x] Missing `config.yaml` can be created from `config.example.yaml` without committing secrets. *(unit/live)*
- [x] `${ENV:-}` placeholders expand; blank → omitted key. *(unit — tests/test_config.py)*

## S2 — Health & status

- [x] `GET /health` stays open even when `api_key` is set. *(unit/integration)*
- [x] `GET /status` reports endpoints (incl. `tier`), inflight, and inventory snapshot fields clients need. *(unit)*

## S3 — Placement

- [x] Prefers a free endpoint with a matching **loaded** model (warm) over cold load. *(unit — test_route)*
- [x] LM Studio path can widen context when the prompt exceeds the loaded window (expand). *(unit + prior live)*
- [x] Busy pool returns HTTP 429 rather than evicting warm models. *(unit)*
- [x] `tier: secondary` is used only when no primary candidate can serve. *(unit — test_secondary_cloud…)*
- [x] Role affinity scores influence ranking among legal models. *(unit — test_affinity / test_route)*

## S4 — Proxy fidelity

- [x] `POST /v1/chat/completions` streams SSE through when upstream streams. *(prior live OpenBot/Pi)*
- [x] Response headers include `x-chimp-endpoint`, `x-chimp-model`, `x-chimp-reason`. *(unit/integration)*

## S5 — Public hygiene

- [x] `config.yaml` and `.agent/` are gitignored; MIT LICENSE present; example hosts are placeholders. *(repo check 2026-11-08)*
- [x] Sticky / prefix-cache-aware placement by `prompt_cache_key` / `X-Chimp-Session` / prefix hash; TTL pins; busy skips pin. *(unit — tests/test_sticky.py; ADR-0003)*
- [x] Cloud prompt-cache body fields pass through unchanged. *(unit — tests/test_cache_passthrough.py)*
- [x] Status UI at `GET /ui` mirrors `/status` endpoints, sticky pins, recent placements. *(unit — tests/test_app.py)*

## S6 — Quality gate

- [x] `pytest` passes on a clean checkout with `[dev]` extras. *(V0 — 50 passed at Waves 1–6 / `v0.1.0`)*
