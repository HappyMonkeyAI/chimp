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

## Review hardening (2026-11-10 code review)

| ID | Task | Acceptance | Size | Status |
|----|------|------------|------|--------|
| R1 | `/ui/config` writes: key required, `text/yaml` only, validate + atomic replace | Unit tests: 403 no key, 415 form, 400 invalid keeps file | S | done |
| R2 | `/ui` usable with `api_key`: shells open, key via `#key=` fragment | Unit test: `/ui` 200 without header, `/status` 401 | S | done |
| R3 | Gzipped upstream SSE relayed decoded; upstream asked for `identity` | Real-socket unit test | S | done |
| R4 | Advisor skipped when a sticky pin exists | Unit tests: pin kept, advisor not called; unpinned still advised | S | done |
| R5 | Fail over only on connect errors; don't retry `ReadTimeout`; generic 502 text | Unit test: read timeout → 502, no second endpoint hit | S | done |
| R6 | HF enrich off the placement path (no sync `httpx.get` under the gate lock) | `place()` does no I/O | M | done |
| R7 | Release inflight slot on `CancelledError` between acquire and dispatch | Unit test: cancelled widen leaves inflight 0 | S | done |
| R8 | Small fixes: sticky expiry sweep, parallel probes, `x or default` config zeros, header allowlist for secondary, drop `is_stream_consumed` branch | Per-item tests | M | todo |

## Backlog (do not start until Waves 1–3 earn their keep)

- Exact response cache (`temperature=0` probes only)
- GitHub Models path adapter
- Provider catalog sync from local-ai-planner
- winget / Homebrew

## Suggested next slice

Soak live class routing when multiple models are warm; optional backlog (exact response cache, GitHub Models adapter) only after that earns its keep.
