---
kind: checkpoint
created: 2026-11-06T17:19:44Z
agent: cursor
sha: de5235d
branch: main
verification: {V0: pass, V1: pass, V2: skip}
id: 2026-11-06T1719Z-pi-auto-400-was-gemma-loaded-at-n-ctx-8192-chimp
---
# Checkpoint: Pi auto 400 was gemma loaded at n_ctx 8192. Chimp now estimates tokens, widens…

## Summary

Pi auto 400 was gemma loaded at n_ctx 8192. Chimp now estimates tokens, widens LM Studio context in place when the loaded window is too small, and retries once if the upstream still returns exceed_context_size_error.

## Done

- Context fields on model records from LM Studio loaded vs max context
- place() prefers expand over cold swap when the loaded window is too small
- Proxy posts /api/v1/models/load before chat and retries once on context overflow
- 23 tests passed; router restarted; short auto request stayed warm

## Next

- Retry Pi chimpr/auto; first long prompt reloads gemma to a larger window and will be slower
- Commit stream-hold and context routing when asked

## Blockers

- (none)

## Decisions

- Widen the already-loaded LM Studio model instead of cold-loading an unloaded Unsloth model with unknown context
