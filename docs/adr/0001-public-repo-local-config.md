# ADR-0001: Public repo, local machine config

## Status

Accepted — 2026-11-08

## Context

chimp needed a public MIT GitHub presence while the operator continues to run a private LAN topology (real hostnames, tunnels, API keys) and Spine session notes.

## Decision

- Ship `config.example.yaml` with placeholder hosts and `${ENV:-}` keys only.
- Gitignore `config.yaml`, `config.local.yaml`, `.env*`, and `.agent/` (memories stay on the machine).
- MIT LICENSE attributed to Stephen Phillips; `pyproject.toml` authors/license match.
- Agents Protocol thin stubs are committed; Spine checkpoints under `.agent/` remain local unless explicitly re-tracked later.

## Consequences

- Clone → copy example → edit local config; install scripts preserve an existing `config.yaml`.
- Old session notes may still exist in git history from before untracking `.agent/` — acceptable risk for a freshly publicized private history; scrub only if needed.
