---
kind: checkpoint
created: 2026-11-06T16:09:28Z
agent: cursor
verification: {V0: pass, V1: pass, V2: skip, V3: skip, V4: skip}
id: 2026-11-06T1609Z-openbot-could-not-connect-because-chimp-was-not
---
# Checkpoint: OpenBot could not connect because chimp was not running. The router now listens…

## Summary

OpenBot could not connect because chimp was not running. The router now listens on 8787 and advertises auto, which resolved warm to the loaded LM Studio model.

## Done

- GET /v1/models always lists the auto alias first.
- Chimp is running on 127.0.0.1:8787 against LM Studio.
- A one-token auto request routed warm to google/gemma-4-e2b.

## Next

- Add the laptop Unsloth base URL when that machine is reachable.
- Click Find models in OpenBot and save model id auto.

## Blockers

- Laptop Unsloth is not listening on this machine's port 8888, so only desktop LM Studio is in config.yaml.

## Decisions

- OpenBot model id auto is a router alias that resolves to a free endpoint with a chat model already loaded.
