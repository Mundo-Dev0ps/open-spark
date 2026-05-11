# Spark Libre — Handoff Prompt

Pegar este archivo entero al iniciar otro agente. Incluye contexto
original + estado actual del repo + próximos pasos.

---

## Brief original

Plugin para OBS llamado **Spark Libre** (nombre provisional).

Backend en Python que el usuario instala como app externa. La UI vive
dentro de OBS como Custom Browser Dock apuntando a
`http://127.0.0.1:8765`.

### Lo que hace

- Panel web embebido en OBS donde el usuario describe un overlay en
  lenguaje natural
- Un LLM genera el overlay como HTML+CSS+JS
- El backend lo sirve en una URL local y lo inyecta en OBS como Browser
  Source via `obs-websocket`
- El usuario puede configurar qué LLM usar (proveedor, modelo, API key)

### Stack

- FastAPI + uvicorn para el servidor local
- `obsws-python` para comunicarse con OBS
- LiteLLM para abstracción de LLMs (Claude, OpenAI, Gemini, Groq, Ollama
  local, etc.)
- `keyring` para guardar API keys seguro
- UI en HTML+CSS+JS vanilla (servida como archivos estáticos por
  FastAPI)

### Compatibilidad

- Linux (incluyendo Flatpak de OBS) y Windows desde el día uno
- Usar `pathlib.Path` para todas las rutas
- Vincular servidor solo a `127.0.0.1`
- Detectar config dir de OBS en ambas plataformas
- Autostart: `.desktop` en Linux, registro en Windows

### MVP — alcance

1. Estructura de carpetas del proyecto
2. `main.py` que arranca FastAPI y conecta con OBS WebSocket
3. Endpoint `/api/generate` que recibe un prompt, llama al LLM y
   devuelve HTML
4. Endpoint `/api/inject` que toma ese HTML y crea/actualiza un Browser
   Source en OBS
5. UI básica funcional: campo de texto, botón generar, preview del HTML,
   botón inyectar en OBS
6. Pantalla de configuración: selector de proveedor LLM, campo de
   modelo, campo de API key (guardada con keyring), campo de endpoint
   custom para Ollama
7. Script de instalación que registra el Custom Browser Dock en el
   config de OBS automáticamente

### Para probar sin romper OBS real

- OBS aislado en contenedor Podman rootless (no en `--portable` nativo)
- El backend tiene un modo `--mock` que simula OBS WebSocket para
  desarrollar sin OBS abierto

---

## Estado actual del repo

Ubicación: `/home/mundo-devops/mundo-devops/repos/apps/open-spark/`

### Layout

```
open-spark/
├── pyproject.toml          # spark-libre + spark-libre-install-dock entry points
├── README.md
├── .gitignore
├── .env.example
├── src/spark_libre/
│   ├── __main__.py         # CLI: --mock / --reload / --port
│   ├── main.py             # FastAPI factory + lifespan, mount /ui, redirect /
│   ├── config.py           # Settings (pydantic), pathlib OBS dir detect
│   │                       # (Linux/Flatpak/Snap/Win/Mac), bind_address()
│   │                       # refuses non-loopback
│   ├── secrets_store.py    # keyring wrapper (LLM keys + OBS pwd)
│   ├── obs_client.py       # OBSClient (obsws-python async via to_thread)
│   │                       # + MockOBSClient
│   ├── llm.py              # LiteLLM call, sanitize fence, OBS overlay
│   │                       # system prompt
│   ├── overlays.py         # OverlayStore, _index.json + per-overlay HTML
│   ├── api/
│   │   ├── routes.py       # /api/{status,generate,inject,overlays,
│   │   │                   #       settings,secrets}, /overlays/{id}.html
│   │   └── schemas.py
│   ├── scripts/
│   │   └── install_dock.py # patches global.ini ExtraBrowserDocks,
│   │                       # idempotent, .bak backup
│   └── static/             # index.html, settings.html, app.js,
│                           # settings.js, style.css
├── scripts/
│   ├── Containerfile.obs        # Fedora 41 + obs-studio 31 + Mesa +
│   │                            # PipeWire + libva + v4l-utils
│   ├── run_obs_container.sh     # podman rootless, autodetect
│   │                            # Wayland/X11/GPU/audio/webcam/DBus
│   ├── run_portable_obs.sh      # legacy fallback (host OBS --portable)
│   └── run_portable_obs.ps1     # idem, Windows
├── docs/
│   ├── development.md
│   └── handoff-prompt.md   # este archivo
└── tests/                  # 15 tests, mock OBS, stub LLM
```

### Lo que ya está hecho

- Estructura completa, package instalable (`pip install -e ".[dev]"`)
- 15/15 tests pasan (`pytest -q`)
- `spark-libre --mock` arranca, `/api/status`, `/api/generate`,
  `/api/inject`, `/api/overlays`, `/api/settings`, `/api/secrets`
  responden
- UI vanilla en `/ui/` (index + settings, JS llamando los endpoints)
- `install_dock.py` parchea `global.ini` `ExtraBrowserDocks`
  idempotente, con backup `.bak`
- **Container OBS** (`scripts/Containerfile.obs` +
  `run_obs_container.sh`) construido y verificado:
  - Imagen `localhost/spark-obs:latest` (1.19 GB) con OBS Studio 31.0.3
    y obs-websocket built-in
  - `--userns=keep-id`, `--network=host` (websocket en
    `127.0.0.1:4455` del host)
  - Autodetect Wayland/X11, GPU `/dev/dri`, NVIDIA CDI, PipeWire/Pulse,
    `/dev/video*`, DBus session bus
  - `/portable` bind-mount con `:Z` para SELinux

### Reglas duras del proyecto

- Solo bind a loopback (`127.0.0.1` / `localhost` / `::1`); cualquier
  otra cosa → `ValueError` en `Settings.bind_address()`
- Secrets exclusivamente en keyring del OS, nunca en disco plano
- Todas las rutas con `pathlib.Path`, jamás `os.path` o concat de
  strings
- Respeto del `AGENTS.md` global del usuario: TDD, gitleaks antes de
  commit, aprobación explícita por commit y push, no hardcoded secrets
- Caveman mode activo en respuestas (compresión, no en código/PRs/
  commits)

---

## Próximos pasos pendientes

Por orden sugerido:

1. **Test end-to-end manual** (usuario, no agente):
   ```bash
   ./scripts/run_obs_container.sh
   # OBS: Tools → WebSocket → Enable, password "test"
   python -c "import keyring; keyring.set_password('spark-libre','obs-ws-password','test')"
   spark-libre
   # http://127.0.0.1:8765 → generar overlay → Inject
   ```

2. **Commit inicial** (no se ha hecho; pide aprobación al usuario antes
   de `git add` + `git commit`).

3. **Plantillas de escena**: nuevo endpoint
   `/api/scenes/templates` que arme una escena entera de un prompt
   ("escena gaming: webcam abajo derecha, chat izquierda, contador
   centro"). Una request `CreateInput` por fuente vía `obs-websocket`.

4. **Dockerfile + CI** del backend (no del OBS, ese ya existe). El
   `AGENTS.md` global pide:
   - `Dockerfile` multi-stage, non-root, alpine/distroless, pinned
   - `.github/workflows/ci.yml`: install → ruff → pytest → build wheel
   - `pre-commit` o `husky+lint-staged`
   - `/healthz` endpoint
   - Vuln scan (`pip-audit`) en CI

5. **Empaquetado distribuible**:
   - Linux: `.desktop` autostart + AppImage o paquete `pip` puro con
     systemd user unit
   - Windows: instalador con registro en `HKCU\Software\Microsoft\
     Windows\CurrentVersion\Run`

6. **OpenAPI spec**: FastAPI ya genera `/api/docs`; añadir un export
   estático `openapi.yaml` y validarlo en CI.

7. **Ollama local**: probar `SPARK_LLM_BASE_URL=http://127.0.0.1:11434`
   con `ollama/llama3.1` end-to-end y documentarlo.

---

## Cómo retomar en un nuevo agente

```
Cargá el contexto del archivo open-spark/docs/handoff-prompt.md.
El proyecto vive en /home/mundo-devops/mundo-devops/repos/apps/open-spark/.
Estado actual: MVP backend + UI + container OBS funcionando, 15/15 tests pasan.
Siguiente prioridad: <elegir 1 a 7 de la lista de próximos pasos>.
Mantené caveman mode (full) en respuestas. Código/commits en estilo normal.
Antes de cualquier commit: scan de secrets con gitleaks y aprobación
explícita del usuario.
```
