# Research links

Curated notes from design research. Add new finds under the right topic; prefer primary docs over secondary blogs when both exist.

## Prompt / prefix caching (providers)

What cloud APIs call “prompt caching” is usually **KV reuse of an identical prompt prefix on the model server**, not a proxy storing full replies.

| Source | Notes |
|---|---|
| [OpenAI — Prompt caching](https://developers.openai.com/api/docs/guides/prompt-caching) | Automatic for supported models; exact prefix match; `prompt_cache_key` / `prompt_cache_options` on newer models |
| [OpenAI — Prompt Caching 201](https://developers.openai.com/cookbook/examples/prompt_caching_201) | Min length ~1024 tokens; same-machine routing matters; monitor hit rates |
| [OpenAI — Prompt Caching announcement](https://openai.com/index/api-prompt-caching/) | Early product framing (TTL / org isolation) |
| [Anthropic — Prompt caching](https://platform.claude.com/docs/en/build-with-claude/prompt-caching) | Opt-in `cache_control` (automatic or per-block); short TTL refreshed on hit |
| [API Price Index — which APIs offer caching](https://apipriceindex.com/guides/prompt-caching/) | Cross-vendor price/TTL/min-prefix table |
| [Extenify — OpenAI / Claude / Gemini compared](https://extenify.app/blog/llm-prompt-caching) | Activation model + usage field names |
| [Vercel — caching across providers](https://vercel.com/i/prompt-caching-across-providers) | Automatic vs explicit; hit-rate caveats |

## Local engines (KV / prefix already on the backend)

| Source | Notes |
|---|---|
| [llama.cpp server README](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md) | `--cache-prompt` default on; `tokens_cached` / `cache_reuse` |
| [Local LLM prompt caching overview](https://intelligibberish.com/articles/local-llm-prompt-caching/) | llama.cpp / Ollama / vLLM / LM Studio comparison |
| [Anthony Tadros — prefix must start at token 0](https://anthonytadros.me/writing/prompt-cache-prefix-match/) | Volatile content early in the prompt kills reuse (LM Studio / llama.cpp) |
| [LM Studio #1563 — KV reuse gaps on some models](https://github.com/lmstudio-ai/lmstudio-bug-tracker/issues/1563) | Not all architectures get silent reuse |

## Cache-aware / sticky routers (GitHub)

Patterns useful for chimp: **sticky pin by session or prefix hash** on top of warm/affinity placement — not a proxy-owned KV store.

| Repo | Stars (approx when noted) | Why it matters |
|---|---|---|
| [thushan/olla](https://github.com/thushan/olla) | ~337 | Sticky sessions; key sources: session header, **prefix_hash**, auth, IP — closest design fit |
| [olla sticky-sessions docs](https://github.com/thushan/olla/blob/main/docs/content/concepts/sticky-sessions.md) | — | Concrete key-source table to mirror |
| [zxuhan/llm-router](https://github.com/zxuhan/llm-router) (`llm-cache-router`) | small | Per-worker radix trees of hashed prefix chunks; `prefixaware` strategy |
| [vllm-project/router](https://github.com/vllm-project/router) | ~504 | Official policies include `cache_aware`, consistent hash |
| [Ray Serve — PrefixCacheAffinityRouter](https://docs.ray.io/en/latest/serve/llm/user-guides/prefix-aware-routing.html) | — | Load-balance vs prefix-match tiers |
| [llm-d — precise prefix-cache routing](https://llm-d.ai/docs/well-lit-paths/foundations/precise-prefix-cache-routing) | — | ZMQ KV events + tokenize-before-route (heavy) |
| [DigitalOcean — prefix-aware routing](https://www.digitalocean.com/blog/reduce-llm-inference-costs-prefix-caching) | — | Block-hash index scoring write-up |
| [wtfsayo/session-router](https://github.com/wtfsayo/session-router) | new | Session stickiness + prompt-cache **switching cost** in the score |
| [neiromaster/proxitor](https://github.com/neiromaster/proxitor) | new | Provider pinning + cache breakpoint shaping (OpenRouter thrash) |
| [flouthoc/sors](https://github.com/flouthoc/sors) | tiny | Reorder static→dynamic blocks (risky for agents) |
| [danielebruneo/KeepRoLLMing](https://github.com/danielebruneo/KeepRoLLMing) | ~14 | Local OpenAI proxy: sticky + fallback + context |
| [peva3/SmarterRouter](https://github.com/peva3/SmarterRouter) | ~158 | VRAM-aware local gateway (sibling product shape) |
| [smg-project/smg](https://github.com/smg-project/smg) | ~703 | Full gateway w/ KV-cache-aware routing (overkill to copy) |
| [beettlle/pi-smart-router](https://github.com/beettlle/pi-smart-router) | small | Pi agent middleware: session pin + cache-aware economics |
| [bet0x/vllm-router FEATURES](https://github.com/bet0x/vllm-router/blob/main/FEATURES.md) | — | Exact + semantic response cache; LMCache-aware route |

## Chimp takeaways (2026-11-08)

1. Do **not** store KV tensors in the proxy — backends (llama.cpp / Unsloth / LM Studio / vLLM) already own that.
2. Highest-value feature: **sticky placement** by `prompt_cache_key` / `X-Chimp-Session` / hash of stable message prefix, ranked under existing warm → expand → affinity rules.
3. Pass through cloud cache fields on `tier: secondary` endpoints.
4. Exact full-response caching is a separate, narrow feature (e.g. `temperature=0` probes only).
5. X bookmarks pass (@HappyMonkeyAI, ~99 recent): no strong prompt/prefix-cache hits; GitHub pass was the useful signal.

## How to extend this file

- New topic = new `##` section.
- Prefer tables: Source | Notes (or Repo | Why).
- Date a “takeaways” subsection when a research pass closes a decision.
