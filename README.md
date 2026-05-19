# Open Spark

**Build and tune your OBS scene by talking to it.** Describe an overlay,
a camera layout, a filter, or a whole scene in plain language — a local
LLM agent calls OBS for you and makes it happen.

Local-first. LLM-agnostic. No telemetry. No cloud. Your API keys never
leave your machine.

> **Status:** early MVP. Linux (native plugin + container stack),
> Windows / macOS plugin builds via CI. Not on PyPI yet.

---

## What it does

- **Conversational agent inside OBS.** A docked chat panel (native Qt
  plugin, in OBS under *View → Docks → Open Spark*). Type
  *"add my webcam bottom-right with a chroma key and a neon frame, then
  a countdown timer top-center"* and it does it — camera, transforms,
  filters, audio, recording/streaming control, scene presets, and
  HTML overlays.
- **Natural-language overlays.** The LLM writes HTML/CSS/JS; the backend
  serves it locally; OBS picks it up as a Browser Source.
- **Safe by default.** Destructive actions (deleting a scene, etc.) run
  in *dry-run* and ask for confirmation first.
- **Bring your own model.** Anthropic, OpenAI, Gemini, Groq, Mistral,
  Cohere, DeepSeek, NVIDIA NIM, OpenRouter, or local Ollama / vLLM /
  LM Studio. **Free options exist** (NVIDIA NIM free credits, OpenRouter
  `:free` models) — no paid key required to try it.

## How it fits together

```
+--------------------------+   obs-websocket   +-----------------------+
|  OBS Studio              |<----------------->|  Open Spark backend   |
|  · Open Spark dock (Qt)  |       HTTP        |  FastAPI @127.0.0.1    |
|  · Browser / camera /    |<----------------->|  agent + tool calling |
|    filters / scenes      |                   |  LiteLLM (any model)  |
+--------------------------+                   |  secrets (env/keyring)|
                                               +-----------------------+
```

Everything runs in containers via `start.sh`. The container's OBS uses
a **portable** config under `./.portable-obs/` — your host's real OBS
install is never touched.

---

## Install

### Prerequisites

- Docker + Docker Compose v2
- Linux with X11/Wayland for the containerized OBS (the backend alone is
  cross-platform)
- An LLM API key (or a free one — see *Configure LLM* below)

### 1. Get the code & configure

```bash
git clone https://github.com/Mundo-Dev0ps/open-spark.git
cd open-spark
cp .env.compose.example .env
# edit .env: set ONE provider key + OPENSPARK_DEFAULT_MODEL
```

`.env` is gitignored and is for **local testing only**. In production,
secrets live in the OS keyring instead.

### 2. Bring up the stack

```bash
./start.sh            # build + start backend + OBS, follow logs
./start.sh smoke      # quick health check (no OBS needed)
```

The agent backend listens on `http://127.0.0.1:8765`.

### 3. Load the OBS plugin

```bash
./start.sh plugin-reload   # compile the native plugin + restart OBS
```

In OBS: **View → Docks → Open Spark**. Drag it beside the canvas. The
dock has two tabs: **Agent** (chat) and **Settings**.

> `obs-websocket` is auto-configured by the plugin — no manual setup.

### Other useful commands

| Command | What it does |
|---|---|
| `./start.sh app` | backend only (use your own OBS + plugin) |
| `./start.sh obs` | OBS container only (fast plugin iteration) |
| `./start.sh down` | stop & remove containers |
| `./start.sh logs [backend\|obs]` | tail logs |
| `./start.sh test` | run the pytest suite in-container |
| `./start.sh plugin-build` | compile plugin without restarting OBS |
| `./start.sh clean` | **destructive** — wipe `.data` + portable OBS |

Run `./start.sh help` for the full list.

---

## Configure LLM

Pick a provider, set its key in `.env` (local) or via the dock
**Settings** tab → *Save key* (keyring). Set `OPENSPARK_DEFAULT_MODEL`
to a `provider/model` id.

Free / cheap to start:

| Provider | Where | Model id example |
|---|---|---|
| NVIDIA NIM | build.nvidia.com (free credits) | `nvidia_nim/meta/llama-3.3-70b-instruct` |
| OpenRouter | openrouter.ai (`:free` tier) | `openrouter/qwen/qwen-2.5-coder-32b-instruct:free` |
| Anthropic | console.anthropic.com | `anthropic/claude-sonnet-4-6` |
| OpenAI | platform.openai.com | `openai/gpt-4o` |
| Ollama (local) | self-hosted | `ollama/llama3.1` (+ `OPENSPARK_LLM_BASE_URL`) |

**The agent needs a model that supports tool/function calling.** The
Settings tab validates your pick and suggests known-good models if it
won't work. Overlay generation works on any model.

---

## Using the agent

Type what you want in the **Agent** tab. Slash shortcuts run locally
(they never hit the LLM):

| Command | Action |
|---|---|
| `/help` | list shortcuts |
| `/clear` (`/new`, `/reset`) | wipe the conversation |
| `/undo` | remove inputs the agent added last turn |
| `/dry [on\|off]` | toggle dry-run (confirm destructive). No arg = flip |
| `/tools` | list everything the agent can do |
| `/status` | backend + OBS connection state |

The agent acts only on your most recent message and operates on exactly
the targets you name. Destructive actions need confirmation unless
dry-run is off.

---

## Packaging (Linux)

Self-hosted artifacts are produced by CI on `v*` tags:

- `.rpm` / `.deb` — `packaging/rpm/obs-open-spark.spec`, fpm-built
- Flatpak extension — `packaging/flatpak/com.obsproject.Studio.Plugin.OpenSpark*.yml`

**Flathub:** ships as an addon that extends the OBS Studio Flatpak:

```bash
flatpak install flathub com.obsproject.Studio.Plugin.OpenSpark
```

Submission is a manual PR to `flathub/flathub` — full steps in
`packaging/README.md`.

---

## Project layout

```
src/open_spark/
  main.py           FastAPI app + lifespan
  config.py         Settings (env "OPENSPARK_" prefix + JSON)
  agent.py          tool-calling agent loop + model validation
  tools.py          ~34 OBS tools (overlays, camera, filters, audio…)
  llm.py            LiteLLM wrapper, overlay prompts, style presets
  obs_client.py     obs-websocket client + MockOBSClient (tests)
  secrets_store.py  env / keyring secrets
  api/              FastAPI routers
plugin/             native Qt OBS plugin (C++/CMake)
packaging/          rpm spec + Flatpak manifest
scripts/            export_openapi, install_dock
tests/              pytest suite (mock OBS)
start.sh            containerized dev stack launcher
```

API spec: `openapi.yaml` (kept in sync by CI).

## Development

See `docs/development.md`. Tests, lint, and OpenAPI sync run in CI
(`.github/workflows/`).

## License

MIT
