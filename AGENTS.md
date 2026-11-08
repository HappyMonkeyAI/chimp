# AGENTS.md — chimp

Thin project stub. Shared behavior law lives in [Agents Protocol](https://github.com/HappyMonkeyAI/AgentsProtocol). Do not paste the full protocol here.

## Prime Directive

Minimize friction, maximize momentum. Keep chimp a focused OpenAI-compatible LAN router: warm VRAM first, honest placement headers, no secret config in git.

## Core orchestration

- **[Echo]** Synthesize lessons into `.agent/memories/` (local; gitignored).
- **[Ripple]** Map blast radius (placement, config schema, client stream semantics) before non-trivial changes.
- **[Pulse]** After >3 corrections, stop, revert, replan.
- **[Adaptive escalation]** Cheapest adequate model first; escalate one tier after two failed repairs.
- **[Steer]** Honor mid-turn course changes.
- **[Thrust]** Batch safe tool calls; serialize destructive ones.
- **[Sanity]** Ground every session (Spine preferred — below).

## Session start and end (Spine)

If the `spine` MCP is available, call `session_brief(project=<absolute path to this repo>)` first; use `get_section` / `recall` instead of reading CONTEXT.md or history whole. Without MCP, run `spine --project . brief` from the repo root. If neither works, ground from README → CONTEXT → MCP.md → this file → TASKS.md — never block the session.

Before stopping meaningful work: `checkpoint(agent="cursor", done, next, blockers)`. Durable why/gotcha/decision facts via `record_memory`. Commit memory files with the work they describe when they are tracked; this repo keeps `.agent/` local-only by default.

## Tool discipline

- Route by intent via [`MCP.md`](MCP.md) (protocol ADR-0003). Listed ≠ mounted.
- Prefer Spine brief over dumping PROGRESS/CONTEXT.
- Heavy builds/tests: ask `resource_sentinel` before saturating the desktop.
- Never commit `config.yaml`, `.env`, or real API keys. Public examples use `${ENV:-}` only.

## Coding standards

- Lead with the answer; surgical diffs.
- Placement changes need unit tests in `tests/test_route.py` (or sibling).
- Autonomous verification: fix your own failures; worker narrative ≠ Done.

## Workflow

Quick Mode for small asks. Deep Mode: RECON → converge → lock. Spec-first when >3 files or behavior surface changes.

### Verification Ladder (project slice)

| Stage | Requirement |
|-------|-------------|
| V0 | `pytest` for touched behavior |
| V1 | Config/schema + status/placement contract still coherent |
| V2 | Owner checks SPEC acceptance independently when behavior changes |
| V3 | Live: `/health`, `/status`, one chat completion through a warm endpoint |
| V4 | Failures → TASKS.md → re-verify |

## Documentation

| File | Role |
|------|------|
| `README.md` | Humans + install |
| `CONTEXT.md` | Stack, rules, what not to do |
| `AGENTS.md` | This stub |
| `MCP.md` | Intent → MCP |
| `SPEC.md` | Acceptance criteria |
| `PLAN.md` | Architecture / phases |
| `TASKS.md` | Task board |
| `ROADMAP.md` | Future ideas |
| `LINKS.md` | External research |
| `docs/adr/` | Project decisions |

Update CONTEXT/ADRs when architecture changes. TASKS.md is the only task board.
