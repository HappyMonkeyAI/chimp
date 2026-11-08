# MCP.md — Intent → server routing

Portable intent map for chimp. **Listed ≠ mounted** — confirm live tools before claiming unavailable (Agents Protocol ADR-0003). No secrets here.

## Project intents

| Intent | Server (typical) | Use when | Notes |
|--------|------------------|----------|-------|
| Session warm-start / memory | `spine` | Every session start/end | `session_brief` / `checkpoint` / `record_memory` / `audit`; pass absolute `project` path |
| UI design memory (later desktop) | `spine-design` | Electron/web UI work | Only when a UI exists; `design_brief` → `ensure_capture` |
| Host CPU/RAM admission | `resource_sentinel` | Full pytest matrix, multi-agent, heavy installs | Snapshot → slot → lease |
| Cross-agent tasks / CLI suggest | `agent_communication` | Offload or coordinate | Fail closed if peer down |
| Live browser QA | `browseros-neo` | V3 against a status UI later | Not needed for headless router slices |
| Knowledge / prior art | `neo4j-semantic-search` | Architecture RECON | Optional |
| GitHub public repo ops | `gh` CLI / github MCP | Releases, issues | Prefer over inventing remote state |
| X research | `plugin-x-x` / X tools | Bookmark/search passes | See LINKS.md research notes |

## Machine-local overlay

Copy [`MCP.local.md.example`](MCP.local.md.example) → `MCP.local.md` (gitignored) for this machine’s paths, LAN hints, and mounted-vs-missing notes. Never put API keys in either file.

## Discovery checklist

1. `spine` brief for this absolute path returns git + doc map.
2. Local backends in `config.yaml` answer `/v1/models` (or LM Studio `/api/v0/models`).
3. `pytest` in `.venv` is green before claiming V0.
4. Record gaps in `MCP.local.md` or TASKS.md — do not invent tools.
