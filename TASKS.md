# TASKS.md — task board

Status: `todo` → `doing` → `review` → `done`. One board only.

## P0 — Agents Protocol bootstrap

- [x] T1 Thin stubs: AGENTS, CONTEXT, MCP, SPEC, PLAN, TASKS, ROADMAP, LINKS
- [x] T2 `docs/adr/` + Cursor `sessionStart` spine hook
- [x] T3 Commit + push protocol docs with pending install/LINKS/ROADMAP work
- [x] T4 Register `chimp` in `~/.spine/registry.json` (absolute path still works)

## P1 — Near-term router (from ROADMAP)

- [ ] T5 Sticky / prefix-cache-aware placement design → SPEC criteria → implement
- [ ] T6 Pass through cloud prompt-cache fields on secondary endpoints
- [ ] T7 System One advisor tie-break (optional; after sticky)

## P2 — Packaging / product

- [x] T8 Optional Docker Compose + Dockerfile + `config.docker.yaml`
- [ ] T9 Electron (or sibling) desktop shell over `/status` — only after status UX is worth operating
- [ ] T10 Publish GHCR image for Compose `image:` pull (optional)

## Done recently (pre-board)

- Warm→expand→unknown→cold placement; affinity; secondary tier; MIT public repo; install.ps1/sh; gitignored local config
