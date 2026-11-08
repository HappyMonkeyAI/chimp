# PLAN.md — architecture & phases

## System overview

```
Client (Vibes / OpenBot / Pi / …)
        │  OpenAI-compatible HTTP
        ▼
┌─────────────────────────────────────┐
│  chimp (Starlette)                  │
│  /v1/chat/completions  /v1/models   │
│  /status  /health                   │
│                                     │
│  inventory poll ──► Snapshot        │
│  place() ──► Placement              │
│  httpx stream ──► upstream          │
└──────────────┬──────────────────────┘
               │
     ┌─────────┼─────────┬────────────┐
     ▼         ▼         ▼            ▼
 Unsloth   LM Studio  Remote     Secondary
 (primary) (primary)  Unsloth    Groq/Mistral/LLM7
```

## Module map

```
src/chimp/
  server.py      CLI / uvicorn entry
  app.py         routes, proxy, status
  config.py      YAML + env expansion, tiers
  inventory.py   poll backends → Snapshot
  route.py       place() ranking
  affinity.py    models.yaml + heuristics (+ optional HF)
  models.yaml    packaged role affinities
```

## Phases

| Phase | Intent | Status |
|-------|--------|--------|
| P0 | Proxy + warm/cold placement + aliases | done |
| P1 | Context expand + stream hold for clients | done |
| P2 | Affinity map | done |
| P3 | Secondary cloud tier + public MIT + installers | done (commit pending for install/docs) |
| P4 | Agents Protocol spine + Spine hook | doing |
| P5 | Sticky / prefix-cache-aware placement | planned (ROADMAP / LINKS) |
| P6 | Electron desktop on `/status` | planned (ROADMAP) |

## Non-goals (this plan)

- Replacing Unsloth/LM Studio
- Owning KV tensors in-process
- Multi-tenant SaaS control plane
