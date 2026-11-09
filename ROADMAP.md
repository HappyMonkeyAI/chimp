# ROADMAP — chimp

Future work and product ideas. Not a delivery promise. Research links stay in [`LINKS.md`](LINKS.md); this file tracks *what we might build*.

## Shipped (high level)

- OpenAI-compatible local router with warm → expand → unknown → cold placement
- Role aliases + packaged affinity map (`models.yaml`)
- LM Studio context widen; stream hold for clients like OpenBot/Pi
- `tier: secondary` cloud fallbacks (Groq / Mistral / LLM7)
- Public MIT repo; gitignored local `config.yaml`; Windows/Linux install scripts
- Optional Docker image + `compose.yaml` (native installers remain primary)

## Near-term (router)

| Idea | Notes | Status |
|---|---|---|
| Sticky / prefix-cache-aware placement | Pin by `prompt_cache_key` / session header / message-prefix hash so LAN GPUs reuse KV; see `LINKS.md` | shipped |
| Pass through cloud cache fields | Forward OpenAI/Anthropic cache knobs on secondary endpoints | shipped |
| OpenBot `auto:<class>` aliases | Explicit work-class in the model id (see below); easiest win vs content classifiers | shipped |
| Startup inventory → affinity refresh | On boot (unless `--no-enrich`), rebuild/refresh live model tags from endpoints into affinity view | shipped |
| Small-model / System One advisor | Optional classify among *legal* warm candidates only; never replace warm/busy/tier gates | shipped |
| Status UI + GHCR image path | `GET /ui`, `scripts/open-status.ps1`, `ghcr.io/happymonkeyai/chimp` workflow | shipped |
| Exact response cache (narrow) | Optional; only for idempotent low-temp probes — not prompt caching | idea |

### OpenBot work-classes (from live roster, 2026-11-09)

All 22 agents currently use `chimpr/auto`, so they share one affinity pool — that matches the “laptop coder / remote AgentWorld” pattern from curated `models.yaml`, not per-request intent.

Proposed model ids OpenBot can set per agent (chimp aliases + affinity roles):

| Alias | Intent | Example agents |
|---|---|---|
| `auto` | Any warm chat (today’s behavior) | default / CEO when undecided |
| `auto:coder` | Code, PRs, bugs, security review | Software Engineer, Bug Fixer, PR Shepherd, Security Reviewer, Change Reviewer |
| `auto:ops` | Builds, deploy, MCP, local wiring | Ops |
| `auto:research` | Sourced answers, prospects, crypto desk | Research Desk, Prospect Researcher, Crypto Desk |
| `auto:writer` | Briefs, copy, scope, content plans | Copy Editor, Scope Writer, Search Content Planner, Handoff Spec Writer |
| `auto:design` | UI critique / prototype / a11y | Design Critic, Prototype Builder, Accessibility Desk |
| `auto:qa` | Pass/fail, repro, smoke | QA Tester |
| `auto:docs` | Registry, roster, drift | Archivist |
| `auto:skills` | Skill/agent/routine design | Skill Smith, Dr. Eggbot |
| `auto:assistant` | Calendar/inbox brief | Chief of Staff |
| `auto:coord` | Multi-desk coordination | CEO |

Implementation sketch: treat `auto:coder` like today’s `executor` role for affinity; list them from `/v1/models`; keep warm→busy→tier gates first.

## Product — desktop app

**Electron (or sibling stack) desktop shell**, in the spirit of other tools under `Documents/development` (`vibes-desktop`, `prompt-os-desktop`, `qwen3-asr-desktop`, ZeroG FileMan, etc.).

Possible scope (refine before building):

- Tray / background host for the chimp process
- Live view of `GET /status` (endpoints, inflight, warm models, tier)
- Edit/select `config.yaml` without hand-editing YAML
- One-click start/stop; maybe “open OpenBot / Vibes base URL” helpers
- Later: placement explain (`x-chimp-*` reasons), affinity tweaks UI

Prerequisite called out in README: status API is already the data plane; a desktop UI can wait until that view is worth operating.

## Later / maybe

- Web dashboard on the same status API (lighter than Electron)
- GitHub Models path adapter (`/chat/completions` without `/v1`)
- Broader free-provider catalog sync from local-ai-planner allowlist
- Packaging: `winget` / Homebrew cask once install scripts prove out
- Publish `ghcr.io/happymonkeyai/chimp` image (Compose currently builds locally)

## How to use this file

- New idea → row or bullet under the right section with `idea` / `next` / `doing` / `done`
- Decisions that close research → short note here + detail in `LINKS.md` if link-heavy
- Do not dump session chatter; keep one line of intent per item
