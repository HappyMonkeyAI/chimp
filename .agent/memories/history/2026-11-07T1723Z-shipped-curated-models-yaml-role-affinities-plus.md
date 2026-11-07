---
kind: checkpoint
created: 2026-11-07T17:23:50Z
agent: cursor
sha: de6d31c
branch: main
id: 2026-11-07T1723Z-shipped-curated-models-yaml-role-affinities-plus
---
# Checkpoint: Shipped curated models.yaml role affinities plus name/size heuristics and optio…

## Summary

Shipped curated models.yaml role affinities plus name/size heuristics and optional HF enrich; place() ranks by affinity after warm/context gates and skips score-0 models for open auto.

## Done

- models.yaml from vibes dogfood + live catalogs
- affinity.py scoring + HF enricher
- Wired into place(); 32 tests pass; router restarted

## Next

- Optional: enable huggingface_enrich in config; System One tie-break among top candidates
- Commit when asked

## Blockers

- (none)

## Decisions

- (none)
