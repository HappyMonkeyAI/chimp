# chimp

A local OpenAI-compatible proxy for the machines you already run. Point Vibes, OpenBot, or any other client at one URL. Chimp watches each endpoint, counts in-flight streams, and sends the request to a free machine that already has a suitable model loaded.

## Install

The installers check for Python 3.11+, create a venv, install the package, copy `config.example.yaml` → `config.yaml` when missing, and verify imports plus a config load.

**Windows (PowerShell):**

```powershell
irm https://raw.githubusercontent.com/SPhillips1337/chimp/main/install.ps1 | iex
```

**Linux / macOS:**

```bash
curl -fsSL https://raw.githubusercontent.com/SPhillips1337/chimp/main/install.sh | bash
```

Defaults to `%USERPROFILE%\chimp` or `~/chimp`. Override with `-Dir C:\path` / `--dir /path`, or `CHIMP_HOME`. Pass `-Dev` / `--dev` (or `CHIMP_DEV=1`) to include pytest. If you already cloned the repo, run `.\install.ps1` or `./install.sh` from that directory instead.

Then edit `config.yaml` and start:

```powershell
# Windows
~\chimp\.venv\Scripts\chimp
```

```bash
# Linux / macOS
~/chimp/.venv/bin/chimp
```

### Manual install

```powershell
# Windows
py -3.12 -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
copy config.example.yaml config.yaml
.venv\Scripts\chimp
```

```bash
# Linux / macOS
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
cp config.example.yaml config.yaml
.venv/bin/chimp
```

`config.yaml` is gitignored — keep your real LAN URLs and keys there (or point `CHIMP_CONFIG` at another path). Only `config.example.yaml` is meant for the public repo. Set `CHIMP_API_KEY` when the listen address is reachable beyond localhost.

Check placement with `GET /status`. `GET /health` stays open even when an API key is set, so a process monitor can probe it.

## How a request is placed

The `model` field is either a role alias (`executor`, `planner`, …) or a real model id. `auto` means any chat model. `X-Chimp-Role` is used only when `model` is omitted or `auto`.

1. Use a free endpoint where a matching model is already loaded.
2. If the loaded window is too small on LM Studio, widen that instance before answering.
3. If loaded state is unknown (a plain OpenAI endpoint), use a free endpoint that lists the model.
4. Load a matching model on a free endpoint only when nothing suitable is already warm.
5. Within each step, prefer models with a higher role affinity (packaged `models.yaml`, overridable via `models_path`). Unknown ids get size/name heuristics; optional `huggingface_enrich: true` fills tags/params from the Hub.
6. If every match is busy, return HTTP 429. Chimp does not evict a warm model to satisfy a request that can wait.
7. Endpoints with `tier: secondary` (free cloud APIs) are used only when no primary endpoint can take the request.

Response headers `x-chimp-endpoint`, `x-chimp-model`, and `x-chimp-reason` (`warm`, `expand`, `unknown`, or `cold`) say where it went. The JSON body is streamed through unchanged.

## Endpoints

| kind | What chimp reads |
|---|---|
| `unsloth` | `GET /v1/models`. A `loaded` flag wins. If the flag is absent, listed models are treated as loaded. |
| `lmstudio` | `GET /api/v0/models` (`state`: `loaded` or `not-loaded`). Falls back to `/v1/models`. |
| `llamaswap` | `GET /v1/models` plus `GET /running`. `state: ready` is loaded. |
| `openai` | `GET /v1/models` only. Loaded state stays unknown, so these lose to a confirmed warm model. |

`base_url` is the server root, for example `http://192.168.1.20:1234`. A trailing `/v1` is stripped. `max_concurrent` defaults to 1, which matches one generation at a time on a 5090.

## Vibes

In each role, set the base URL to `http://127.0.0.1:8787/v1` and the model to the alias (`executor`, `planner`, `reviewer`, `triage`). Constitutions stay in Vibes.

OpenBot's custom provider uses the same base URL. Find models lists `auto` even when a backend is down. Put `auto` in the model id: Chimp resolves it to a free endpoint whose chat model is already loaded. `executor`, `planner`, `reviewer`, and `triage` are listed the same way.

A connection test that generates one token occupies a slot for that call. A prompt that does not fit the loaded context asks LM Studio to widen that model's window before answering, up to the model's maximum.

## Tests

```powershell
.venv\Scripts\python -m pytest
```

## Docs (Agents Protocol)

Thin stubs aligned with [Agents Protocol](https://github.com/HappyMonkeyAI/AgentsProtocol); Spine warm-start via `.cursor/hooks.json`.

| File | Role |
|------|------|
| [`AGENTS.md`](AGENTS.md) | Agent law stub + Spine session start/end |
| [`CONTEXT.md`](CONTEXT.md) | Stack, rules, what not to do |
| [`MCP.md`](MCP.md) | Intent → MCP routing |
| [`SPEC.md`](SPEC.md) | Acceptance criteria |
| [`PLAN.md`](PLAN.md) | Architecture / phases |
| [`TASKS.md`](TASKS.md) | Task board |
| [`ROADMAP.md`](ROADMAP.md) | Future ideas (Electron desktop, sticky cache, …) |
| [`LINKS.md`](LINKS.md) | External research links |
| [`docs/adr/`](docs/adr/) | Project ADRs |

`GET /status` is the data a web dashboard or desktop app would show; see roadmap before building UI on top.
