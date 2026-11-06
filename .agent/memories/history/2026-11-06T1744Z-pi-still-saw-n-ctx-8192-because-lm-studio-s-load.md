---
kind: checkpoint
created: 2026-11-06T17:44:15Z
agent: cursor
sha: de5235d
branch: main
id: 2026-11-06T1744Z-pi-still-saw-n-ctx-8192-because-lm-studio-s-load
---
# Checkpoint: Pi still saw n_ctx 8192 because LM Studio's load API created a second instance…

## Summary

Pi still saw n_ctx 8192 because LM Studio's load API created a second instance and chimp kept calling the original. Routing now uses the wider instance and the 8192 copy has been unloaded.

## Done

- LM Studio load spawned gemma-4-e2b:2 at 131072 and left the original at 8192
- Router now prefers the instance whose loaded window fits and unloads the smaller copy
- Oversized test request returned 200 on google/gemma-4-e2b:2; only that instance remains loaded

## Next

- Retry Pi chimpr/auto

## Blockers

- (none)

## Decisions

- (none)
