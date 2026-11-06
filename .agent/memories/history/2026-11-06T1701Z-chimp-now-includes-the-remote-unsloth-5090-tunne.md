---
kind: checkpoint
created: 2026-11-06T17:01:08Z
agent: cursor
verification: {V0: pass, V1: pass, V2: skip, V3: skip, V4: skip}
id: 2026-11-06T1701Z-chimp-now-includes-the-remote-unsloth-5090-tunne
---
# Checkpoint: Chimp now includes the remote Unsloth 5090 tunnel. It is healthy and idle, so a…

## Summary

Chimp now includes the remote Unsloth 5090 tunnel. It is healthy and idle, so auto still uses the loaded desktop model.

## Done

- Added the remote Unsloth endpoint and restarted chimp.
- Probe returned healthy with 10 models, none loaded.

## Next

- Load a model in Unsloth Studio if the 5090 should take work while the desktop is busy.

## Blockers

- Nothing is loaded in Unsloth yet, so auto stays on the desktop model that is already warm.

## Decisions

- remote-unsloth is the Cloudflare Unsloth Studio tunnel. Its key lives only in gitignored config.yaml.
