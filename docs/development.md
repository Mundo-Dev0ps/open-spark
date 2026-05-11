# Development guide

## Recommended: full Docker Compose stack (no host install)

This is a **test-only** stack — run everything in containers, leave your
real host OBS untouched. Tested on Linux + Wayland + AMD/Intel iGPU.

```bash
cp .env.compose.example .env
# Edit .env: set SPARK_OBS_PASSWORD and one *_API_KEY
docker compose up --build
xdg-open http://127.0.0.1:8765
```

What you get:

- `backend` — FastAPI on `127.0.0.1:8765`, secrets read from env (no
  keyring required), bind rule preserved (`network_mode: host`).
- `obs` — OBS Studio in a container, GUI rendered on your host display
  (Wayland/X11 socket passthrough), `obs-websocket` on
  `127.0.0.1:4455`.

First time only: in OBS, **Tools → WebSocket Server Settings → Enable
Server**, set the password to whatever you put in `.env`. The backend
healthcheck waits up to 2 minutes (`start_period: 120s`) for that.

Run tests inside the same image (no host venv needed):

```bash
docker compose --profile test run --rm tests pytest -q
```

The `tests` profile builds the `dev` stage of the Dockerfile (which adds
the `tests/` tree). It's separate from `up` so production-style runs stay
slim.

NVENC / hybrid-graphics laptops: the stack uses the iGPU only on
purpose — overlays don't need NVENC. If you want NVIDIA passthrough,
use the legacy `scripts/run_obs_container.sh`, which CDI-detects NVIDIA
when `nvidia-container-toolkit` is installed.

## Run the backend without OBS (legacy host install)

```bash
pip install -e ".[dev]"
spark-libre --mock --reload
```

Mock mode replaces the OBS WebSocket client with `MockOBSClient`, an
in-memory fake. `/api/inject` will succeed and the response will include
`"mock": true`.

Open <http://127.0.0.1:8765/> in any browser to drive the UI from outside
OBS.

## Run against a containerized OBS (recommended on Linux)

The `scripts/run_obs_container.sh` launcher builds and runs OBS Studio
inside a rootless Podman container. Your real OBS config is never
touched. State persists in `./.portable-obs/`.

```bash
./scripts/run_obs_container.sh             # auto-build + run
REBUILD=1 ./scripts/run_obs_container.sh   # force image rebuild
IMAGE=localhost/spark-obs:dev ./scripts/run_obs_container.sh
```

Internals:

- Image: `scripts/Containerfile.obs` (Fedora 41 + obs-studio + Mesa +
  PipeWire + libva + v4l-utils).
- Networking: `--network=host`. obs-websocket inside the container
  listens on `127.0.0.1:4455` of the host.
- UID mapping: `--userns=keep-id` preserves host UID/GID inside the
  container. The `./.portable-obs/` bind mount stays writable from
  both sides.
- GPU groups: `--group-add` with the host's `render` and `video` GIDs
  so `/dev/dri` and `/dev/video*` are usable inside.

Once OBS is up:

1. Tools → WebSocket Server Settings → Enable Server, set a password.
2. Save the password to keyring on the host (the container shares the
   host's network, but the keyring lives on the host):
   ```bash
   python -c "import keyring; keyring.set_password('spark-libre','obs-ws-password','PASSWORD')"
   ```
3. Run `spark-libre` on the host. Lifespan logs
   `connected to OBS WebSocket`.
4. Generate an overlay in the dock; click Inject.

## Run against the host's real OBS in --portable (fallback)

If you can't use Podman (or you're on Windows), the legacy script boots
the host's OBS install in portable mode:

```bash
./scripts/run_portable_obs.sh   # Linux / Flatpak
./scripts/run_portable_obs.ps1  # Windows
```

Less isolation than the container path: still uses host binaries and
host GPU/audio drivers, only OBS state is segregated.

## Install the dock into the portable OBS

```bash
spark-libre-install-dock --config-dir ./.portable-obs/config/obs-studio
```

(`--list-candidates` prints the auto-detected dirs.)

## Layout cheatsheet

```
src/spark_libre/
  __main__.py        spark-libre CLI
  main.py            FastAPI factory + lifespan
  config.py          pathlib-only path resolution per OS
  secrets_store.py   keyring wrapper
  obs_client.py      real + mock OBS clients (same protocol)
  llm.py             LiteLLM call + sanitization
  overlays.py        on-disk store with JSON index
  api/
    routes.py        all HTTP routes
    schemas.py       pydantic v2 models
  scripts/
    install_dock.py  registers Custom Browser Dock in OBS global.ini
  static/            vanilla UI (index, settings, app.js)
```

## Testing

In container (preferred — no host venv):

```bash
docker compose --profile test run --rm tests pytest -q
```

Or, if you have a host venv:

```bash
pytest -q
```

Tests use `MockOBSClient`, never touch real OBS, never hit the network.
LLM calls are stubbed via dependency injection.

`tests/test_secrets_env.py` covers the env-var fallback used inside
containers when `SPARK_USE_ENV_SECRETS=1`.
