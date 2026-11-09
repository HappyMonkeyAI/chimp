# CONTEXT.md — chimp

## Stack / nature

Local OpenAI-compatible **router/proxy** (not a model server). Clients (Vibes, OpenBot, Pi, …) point at one URL; chimp inventories backends, counts in-flight streams, and places each request on a free endpoint that already has a suitable model loaded when possible.

| Layer | Choice | Notes |
|-------|--------|-------|
| Language | Python ≥3.11 | `pyproject.toml` / setuptools |
| HTTP | Starlette + uvicorn + httpx | Stream-preserving proxy |
| Config | YAML + `${ENV:-}` expansion | `config.yaml` gitignored; `config.example.yaml` public |
| Affinity | Packaged `models.yaml` | Optional HF enrich; override via `models_path` |
| Install | `install.ps1` / `install.sh` | One-liner from GitHub raw |
| Optional run | Docker Compose | `Dockerfile` + `compose.yaml`; still needs host/LAN GPU URLs |
| License | MIT | Stephen Phillips |

## Architecture decisions

| ADR | Summary |
|-----|---------|
| [ADR-0001](docs/adr/0001-public-repo-local-config.md) | Public MIT tree; machine config and `.agent/` stay local |
| [ADR-0002](docs/adr/0002-secondary-cloud-tier.md) | `tier: secondary` cloud only when no primary can serve |
| [ADR-0003](docs/adr/0003-sticky-placement.md) | Sticky pins by `prompt_cache_key` / `X-Chimp-Session` / prefix hash |
| Protocol | [AgentsProtocol ADR-0005](https://github.com/HappyMonkeyAI/AgentsProtocol/blob/main/docs/adr/0005-spine-warm-start.md) | Spine warm-start adopted via thin stubs + Cursor hook |

## Placement rules (high signal)

Order: **warm → expand → unknown → cold** (then `sticky` when a pin matches a free legal candidate). Within a step: role / `auto:<class>` preference, then affinity, then primary over secondary. Unhealthy endpoints are skipped — failover to the next healthy primary is expected. HTTP 429 if every match is busy — do not evict a warm model to satisfy a waiter. Response headers: `x-chimp-endpoint`, `x-chimp-model`, `x-chimp-reason`.

Plain `auto` remains valid (any warm chat). `auto:<class>` only changes affinity ranking among legal candidates. Affinity does not demote broken AWQ builds — pin a known-good id when a peer is bad.

Endpoint kinds: `unsloth`, `lmstudio`, `llamaswap`, `openai`. Status UI: `GET /ui` (and `GET/POST /ui/config` for the bound gitignored file).

## Rules

- `config.yaml` never enters git; document shapes in `config.example.yaml` / `config.docker.yaml` only. Do not overwrite a live `config.yaml` with the Docker example without a backup.
- Research links → `LINKS.md`; future product ideas → `ROADMAP.md`.
- Sticky / prefix-cache-aware routing is shipped (ADR-0003) — backends own KV cache; chimp only improves locality.
- Secondary cloud keys come from the environment, not committed files.
- Published image: `ghcr.io/happymonkeyai/chimp` (tagged releases, e.g. `v0.1.0`).

## What not to do

- Store real LAN IPs, tunnels, or API keys in tracked example files.
- Implement GPU KV caching inside the proxy.
- Treat secondary cloud as equal to a warm local GPU when a primary is free.
- Mark behavior Done on narrative alone — need pytest and, for stream/placement changes, a live check.
- Block the session if Spine MCP is missing.

## Related trees

- Clients: Vibes / OpenBot / Pi → `http://127.0.0.1:8787/v1`
- Protocol: `Documents/development/AgentsProtocol`
- Sibling desktops (future Electron idea): `vibes-desktop`, `prompt-os-desktop`, …
