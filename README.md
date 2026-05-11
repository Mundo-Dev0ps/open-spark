# Spark Libre

Generate OBS overlays from natural language. Local-first. LLM-agnostic.

> **Status:** early MVP. Not on PyPI yet. Linux + Windows.

## What it is

Backend in Python that runs on your machine. UI lives **inside OBS** as a
Custom Browser Dock pointed at `http://127.0.0.1:8765`. You type what you
want ("a neon countdown timer with a progress bar"), an LLM produces
HTML+CSS+JS, the backend serves it locally, and OBS picks it up as a
Browser Source via `obs-websocket`.

No telemetry. No cloud. Your API keys live in your OS keyring.

## Architecture

```
+---------------------------+         +-----------------------+
|   OBS Studio              |  WS     |  Spark Libre backend  |
|   - Custom Browser Dock --|---HTTP->|  FastAPI on 127.0.0.1 |
|   - Browser Source     <--|---------|  serves /overlays/*   |
+---------------------------+         |  obs-websocket client |
                                      |  LiteLLM (any model)  |
                                      |  keyring (secrets)    |
                                      +-----------------------+
```

## Quick start (dev)

```bash
git clone https://github.com/youruser/open-spark spark-libre
cd spark-libre
python -m venv .venv && source .venv/bin/activate   # Linux/macOS
# .venv\Scripts\activate                            # Windows PowerShell
pip install -e ".[dev]"

# 1. Run backend in mock mode (no OBS needed)
spark-libre --mock

# 2. Open http://127.0.0.1:8765 in any browser to drive it
```

To run against real OBS:

1. OBS → Tools → WebSocket Server Settings → Enable, set password.
2. Store the password: `python -c "import keyring; keyring.set_password('spark-libre','obs-ws-password','YOUR_PASSWORD')"`
3. `spark-libre`

## Install the OBS dock

```bash
spark-libre-install-dock
```

Edits OBS `global.ini` (Linux: `~/.config/obs-studio/`, Flatpak:
`~/.var/app/com.obsproject.Studio/config/obs-studio/`, Windows:
`%APPDATA%\obs-studio\`) to add a Custom Browser Dock entry pointing at
`http://127.0.0.1:8765`. Restart OBS, then dock shows up under
Docks menu.

## Test against a sandboxed OBS (don't risk your real config)

**Recommended (Linux, rootless Podman):**

```bash
./scripts/run_obs_container.sh
```

Builds and runs `localhost/spark-obs:latest` (Fedora + OBS Studio 31)
inside a rootless Podman container. Auto-passthrough for:

- Display: Wayland socket preferred, X11 fallback
- GPU: `/dev/dri` (Intel/AMD); NVIDIA via `--device nvidia.com/gpu=all`
  if `nvidia-container-toolkit` is installed
- Audio: PipeWire socket, with PulseAudio fallback
- Webcams: every `/dev/video*` on the host
- DBus session bus (xdg-desktop-portal, screencast)

The container's OBS uses `--portable` against `./.portable-obs/` (bind
mount) — your host's real OBS config is **never** touched. UID is
preserved via `--userns=keep-id`, so the bind-mount stays writable as
your host user.

`obs-websocket` (built into OBS 28+) listens on host port 4455 because
the container uses `--network=host`. No port forwarding needed.

**Fallback (no Podman, or Windows):**

```bash
./scripts/run_portable_obs.sh   # Linux native / Flatpak
./scripts/run_portable_obs.ps1  # Windows
```

These boot the host's OBS install with `--portable` against
`./.portable-obs/`. Less isolated than the container, but works without
Podman.

## Configure LLM

Open the dock (or `http://127.0.0.1:8765/settings`), pick provider, paste
API key. Stored via `keyring` on the OS credential store.

Supported via LiteLLM: Anthropic, OpenAI, Gemini, Groq, Mistral, Cohere,
local Ollama / vLLM / LM Studio (set custom base URL).

## Layout

```
src/spark_libre/
  main.py           FastAPI app + lifespan (boot OBS client, LLM)
  config.py         Settings (env + JSON), path resolution per OS
  secrets_store.py  keyring wrapper
  obs_client.py     obs-websocket client + MockOBSClient
  llm.py            LiteLLM wrapper with overlay-focused system prompt
  overlays.py       in-process registry + on-disk overlay storage
  api/              FastAPI routers
  static/           dock UI (vanilla HTML/CSS/JS)
scripts/            install_dock, portable OBS launchers
tests/              pytest suite (mock OBS)
```

## License

MIT
