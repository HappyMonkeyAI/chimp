---
kind: checkpoint
created: 2026-11-07T17:04:20Z
agent: cursor
sha: de6d31c
branch: main
id: 2026-11-07T1704Z-openbot-tool-cooling-spin-on-remote-unsloth-was
---
# Checkpoint: OpenBot tool-cooling spin on remote Unsloth was slot contention plus cold model…

## Summary

OpenBot tool-cooling spin on remote Unsloth was slot contention plus cold model thrash: auto kept cold-picking alternating Qwen ids, and parallel tool turns hit max_concurrent=1 as 429.

## Done

- Confirmed from logs: desktop dropped, remote cold routes alternated DavidAU vs empero, 429s during busy slot

## Next

- If fixing: sticky last model for unsloth auto, and/or queue on 429 instead of hard reject; pin preferred remote model in aliases

## Blockers

- (none)

## Decisions

- (none)
