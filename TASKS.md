# TASKS.md — development plan

Status: `todo` → `doing` → `review` → `done`. Ordered for value vs risk. Detail lives in [`ROADMAP.md`](ROADMAP.md); research in [`LINKS.md`](LINKS.md).

## Wave 0 — Done (baseline)

- [x] Warm → expand → unknown → cold placement; affinity; secondary tier
- [x] Public MIT + installers + Docker Compose optional lane
- [x] Agents Protocol stubs + Spine hook (T1–T4, T8)

## Wave 1 — OpenBot intent (highest leverage)

Goal: stop every desk sharing one `auto` pool; keep host failover as-is.

| ID | Task | Acceptance | Effort | Status |
|----|------|------------|--------|--------|
| T11a | Add aliases `auto:coder`, `auto:ops`, … | Listed on `GET /v1/models` | S | done |
| T11b | Extend affinity roles for those classes | Unit tests prefer coder-ish ids | M | done |
| T11c | Accept `chimpr/auto:<class>` and `chimp/auto:<class>` | Provider-prefixed ids route | S | done |
| T11d | Docs: README + OpenBot mapping table | Operator can re-point desks | S | done |
| T11e | Live: point OpenBot agents to `auto:<class>` | All 22 remapped via openbot-cli (2026-11-09) | S | done |

**Exit:** OpenBot can steer class without a classifier LLM.

## Wave 2 — Smarter inventory at boot

| ID | Task | Acceptance | Effort | Status |
|----|------|------------|--------|--------|
| T12a | Startup poll before serving | Lifespan `refresh_all` | S | done |
| T12b | Optional enrich live ids into affinity | `seed_live`; curated wins | M | done |
| T12c | `--no-enrich` / `CHIMP_NO_ENRICH=1` | Enrich skipped | S | done |
| T12d | Document boot enrich vs periodic poll | README note | S | done |

**Exit:** Boot remap is default; bypass is one flag.

## Wave 3 — Cache locality

| ID | Task | Acceptance | Effort | Status |
|----|------|------------|--------|--------|
| T5a | Sticky key ADR | `docs/adr/0003-sticky-placement.md` | S | done |
| T5b | Pin warm endpoint+model for TTL | Unit tests pin / expire / busy failover | M | done |
| T5c | SPEC + `/status` active pins | S5 sticky checkbox + status JSON | S | done |
| T6 | Pass through cloud prompt-cache fields | Unit test; body unchanged | S | done |

**Exit:** Multi-turn threads prefer the same warm host when free.

## Wave 4 — Advisory classify (optional)

| ID | Task | Acceptance | Effort | Status |
|----|------|------------|--------|--------|
| T7a | Config: advisor endpoint | Disabled by default | S | done |
| T7b | Among legal candidates only | Timeout → affinity | M | done |
| T7c | Log / `x-chimp-reason` when advisor used | `warm+advisor` | S | done |

**Exit:** Bare `auto` can get a cheap hint; explicit `auto:*` stays authoritative.

## Wave 5 — Packaging polish

| ID | Task | Acceptance | Effort | Status |
|----|------|------------|--------|--------|
| T10 | Publish `ghcr.io/happymonkeyai/chimp` + Compose image option | Workflow + compose/README | M | done |

## Wave 6 — Desktop / status UI

| ID | Task | Acceptance | Effort | Status |
|----|------|------------|--------|--------|
| T9a | Thin tray/host helper | `scripts/open-status.ps1` | L | done |
| T9b | Status UI over `/status` | `GET /ui` | L | done |
| T9c | Config editor | `GET/POST /ui/config` saves gitignored `config.yaml` | L | done |

Prefer web dashboard over Electron — shipped as `/ui`.

## Backlog (do not start until Waves 1–3 earn their keep)

- Exact response cache (`temperature=0` probes only)
- GitHub Models path adapter
- Provider catalog sync from local-ai-planner
- winget / Homebrew

## Suggested next slice

Operator: remap OpenBot desks to `auto:<class>` (T11e) and cut a `v*` tag to publish GHCR.
