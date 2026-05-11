#!/usr/bin/env bash
# start.sh — Spark Libre dev stack launcher.
#
# Subcommands:
#   up         (default) build + start backend+obs, follow logs
#   up-d                 build + start in background, no log follow
#   app                  build + start ONLY the Python backend container
#                        (no OBS) — useful when you already have OBS
#                        running with the plugin loaded
#   obs                  build + start ONLY the OBS container (no app)
#                        — useful for quick plugin iteration when the
#                        backend is already up
#   down                 stop + remove containers
#   restart              down + up
#   build                rebuild images only
#   logs [svc]           tail logs of all services or one (backend|obs)
#   ps                   compose ps + healthchecks
#   test [path/expr]     run pytest in dev image (default: full suite)
#   shell [svc]          shell into a running container (default: backend)
#   smoke                quick API smoke test against backend (no OBS dep)
#   tray                 launch native desktop window + system-tray icon
#                        (requires `pip install --user 'spark-libre[tray]'`
#                         on the host; backend is auto-started if not up)
#   plugin-build         compile the native obs-spark-libre plugin in a
#                        builder container, drop the .so into the OBS
#                        container's portable plugin dir
#   plugin-reload        plugin-build + restart the obs container so the
#                        new .so is picked up
#   clean                stop + delete .data and .portable-obs (DESTRUCTIVE)
#   help                 print this header
#
# Usage examples:
#   ./start.sh                       # bring it all up, follow logs
#   ./start.sh test                  # run full test suite in container
#   ./start.sh test tests/test_api   # run a subset
#   ./start.sh logs obs              # tail just the OBS container
#   ./start.sh smoke                 # quick health check on the backend

set -euo pipefail

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$REPO_ROOT"

# UID is a read-only bash builtin; use HOST_UID/HOST_GID for compose.
export HOST_UID="$(id -u)"
export HOST_GID="$(id -g)"

# Display + audio + dbus env are needed by the OBS container.
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$HOST_UID}"
export WAYLAND_DISPLAY="${WAYLAND_DISPLAY:-wayland-0}"
export DISPLAY="${DISPLAY:-:0}"
export DBUS_SESSION_BUS_ADDRESS="${DBUS_SESSION_BUS_ADDRESS:-unix:path=$XDG_RUNTIME_DIR/bus}"

# FULL_CEF=1 → switch the OBS image to the variant that rebuilds the
# obs-browser plugin with Custom Browser Docks enabled. Slower first
# build (~10 min) and ~600 MB heavier, but needed for the embedded
# in-OBS dock UX.
if [[ "${FULL_CEF:-0}" == "1" ]]; then
  export OBS_DOCKERFILE="Containerfile.obs.fullcef"
fi

DC=(docker compose)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

log()  { printf '\033[1;36m>>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m!!\033[0m %s\n' "$*" >&2; }
fail() { printf '\033[1;31mxx\033[0m %s\n' "$*" >&2; exit 1; }

require_docker() {
  command -v docker >/dev/null 2>&1 || fail "docker not installed"
  docker compose version >/dev/null 2>&1 \
    || fail "docker compose plugin missing (need v2)"
}

require_env_file() {
  if [[ ! -f .env ]]; then
    log ".env missing — copying from .env.compose.example"
    cp .env.compose.example .env
    warn "Edit .env to set SPARK_OBS_PASSWORD and an *_API_KEY before starting OBS-dependent flows."
  fi
}

check_host_sockets() {
  local missing=0
  for s in \
      "$XDG_RUNTIME_DIR/$WAYLAND_DISPLAY:Wayland" \
      "$XDG_RUNTIME_DIR/pipewire-0:PipeWire" \
      "$XDG_RUNTIME_DIR/bus:DBus" ; do
    local path="${s%%:*}" name="${s##*:}"
    if [[ ! -S "$path" ]]; then
      warn "$name socket missing: $path"
      missing=1
    fi
  done
  if [[ "$missing" -eq 1 ]]; then
    warn "OBS GUI may fail to start. Continuing anyway."
  fi
}

ensure_x_auth() {
  # XWayland / Xorg drop the container's access on every reboot. Without
  # this, the OBS container's Qt fails with `qt.qpa.xcb: could not connect
  # to display :0` and exits 139 (SIGSEGV). Idempotent.
  if command -v xhost >/dev/null 2>&1; then
    xhost +SI:localuser:"$(id -un)" >/dev/null 2>&1 \
      || warn "xhost call failed; OBS container may not reach the X display"
  fi
}

# ---------------------------------------------------------------------------
# Subcommands
# ---------------------------------------------------------------------------

ensure_host_dirs() {
  # Pre-create bind-mount targets so Docker doesn't make them root-owned.
  mkdir -p .data/overlays .portable-obs
}

cmd_up() {
  require_env_file
  ensure_host_dirs
  ensure_x_auth
  check_host_sockets
  log "building images (HOST_UID=$HOST_UID HOST_GID=$HOST_GID)"
  "${DC[@]}" build
  log "starting stack"
  "${DC[@]}" up -d
  log "tailing logs (Ctrl-C exits log view; containers keep running)"
  "${DC[@]}" logs -f
}

cmd_up_d() {
  require_env_file
  ensure_host_dirs
  ensure_x_auth
  check_host_sockets
  "${DC[@]}" build
  "${DC[@]}" up -d
  "${DC[@]}" ps
}

cmd_app() {
  # Backend-only on-demand. Skips the OBS container and its display
  # passthrough so this works on headless hosts and CI too.
  require_env_file
  ensure_host_dirs
  log "starting backend only (no OBS container)"
  "${DC[@]}" build backend
  "${DC[@]}" up -d --no-deps backend
  "${DC[@]}" ps
  log "backend up at http://127.0.0.1:8765/ui/"
}

cmd_obs_only() {
  require_env_file
  ensure_host_dirs
  ensure_x_auth
  check_host_sockets
  log "starting OBS container only (no backend)"
  "${DC[@]}" build obs
  "${DC[@]}" up -d --no-deps obs
  "${DC[@]}" ps
}

cmd_down() {
  "${DC[@]}" down
}

cmd_restart() {
  "${DC[@]}" down
  cmd_up
}

cmd_build() {
  "${DC[@]}" build "$@"
}

cmd_logs() {
  "${DC[@]}" logs -f "$@"
}

cmd_ps() {
  "${DC[@]}" ps
}

cmd_test() {
  log "building dev image (test profile)"
  "${DC[@]}" --profile test build tests
  log "running pytest ${*:-(full suite)}"
  "${DC[@]}" --profile test run --rm tests pytest -q "$@"
}

cmd_shell() {
  local svc="${1:-backend}"
  if "${DC[@]}" ps --services --filter status=running | grep -qx "$svc"; then
    "${DC[@]}" exec "$svc" /bin/sh
  else
    log "$svc not running, starting one-shot shell in dev image"
    "${DC[@]}" --profile test run --rm --entrypoint /bin/sh tests
  fi
}

cmd_smoke() {
  log "smoke: starting backend in mock mode (no OBS, no LLM)"
  docker run -d --rm --name spark-smoke --network=host \
      -e SPARK_USE_ENV_SECRETS=1 \
      -e SPARK_MOCK_OBS=1 \
      -e ANTHROPIC_API_KEY=sk-fake \
      spark-libre/backend:dev >/dev/null
  trap 'docker stop spark-smoke >/dev/null 2>&1 || true' EXIT
  for i in 1 2 3 4 5; do
    sleep 1
    if curl -fsS http://127.0.0.1:8765/api/status >/dev/null; then
      log "backend reachable, /api/status:"
      curl -fsS http://127.0.0.1:8765/api/status | python3 -m json.tool
      log "smoke OK"
      return 0
    fi
  done
  fail "backend never became reachable; check 'docker logs spark-smoke'"
}

cmd_tray() {
  require_env_file
  ensure_host_dirs
  # Bring up backend+OBS if backend isn't reachable.
  if ! curl -fsS http://127.0.0.1:8765/api/status >/dev/null 2>&1; then
    log "backend not reachable; bringing stack up in the background"
    "${DC[@]}" up -d
  fi
  if ! command -v spark-libre-tray >/dev/null 2>&1; then
    cat >&2 <<'EOF'
spark-libre-tray entry point not found.

Install on the host (NOT in the container — tray needs a real display):

    pip install --user 'spark-libre[tray]' \
        --no-binary=keyring,jeepney,SecretStorage  # optional

Linux notes:
  * Wayland or X11 must be available.
  * Qt6 + QtWebEngine are pulled by the [tray] extra.
  * On NVIDIA hybrid laptops, prefix with `__NV_PRIME_RENDER_OFFLOAD=1` if
    the window appears black.
EOF
    return 4
  fi
  log "launching native window"
  exec spark-libre-tray "$@"
}

cmd_plugin_build() {
  ensure_host_dirs
  local img="spark-libre/plugin-builder:dev"
  # OBS scans the XDG user-plugin layout
  #   $XDG_CONFIG_HOME/obs-studio/plugins/<name>/bin/64bit/<name>.so
  # In our container XDG_CONFIG_HOME=/portable/config, so install there.
  local plugin_root="$REPO_ROOT/.portable-obs/config/obs-studio/plugins/obs-spark-libre"
  local plugin_bin="$plugin_root/bin/64bit"
  local plugin_data="$plugin_root/data/locale"
  mkdir -p "$plugin_bin" "$plugin_data"

  log "building plugin builder image"
  docker build -t "$img" \
      -f "$REPO_ROOT/scripts/Containerfile.plugin-builder" \
      "$REPO_ROOT/scripts"

  log "compiling obs-spark-libre.so (WebEngine=${WITH_WEBENGINE:-OFF})"
  docker run --rm \
      -v "$REPO_ROOT/plugin:/src:ro" \
      -v "$plugin_bin:/out:rw" \
      -e "SPARK_WITH_WEBENGINE=${WITH_WEBENGINE:-OFF}" \
      --user "$HOST_UID:$HOST_GID" \
      "$img"

  cp -f "$REPO_ROOT/plugin/data/locale/"*.ini "$plugin_data/" 2>/dev/null || true

  log "plugin written to $plugin_bin/obs-spark-libre.so"
  ls -la "$plugin_bin/" 2>&1
}

cmd_plugin_reload() {
  cmd_plugin_build
  log "restarting obs container so the new plugin is picked up"
  "${DC[@]}" restart obs
  log "tail OBS logs to confirm load:  ./start.sh logs obs | grep spark-libre"
}

cmd_clean() {
  warn "About to delete .data/ and .portable-obs/ AND remove all containers."
  read -r -p "Type 'yes' to confirm: " ans
  [[ "$ans" == "yes" ]] || { log "aborted"; exit 0; }
  "${DC[@]}" down -v
  rm -rf .data .portable-obs
  log "cleaned"
}

cmd_help() {
  # Print the leading comment block only (lines 2..first blank).
  awk 'NR>1 && /^$/ {exit} NR>1' "${BASH_SOURCE[0]}"
}

# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

require_docker

action="${1:-up}"
shift || true

case "$action" in
  up)       cmd_up "$@" ;;
  up-d)     cmd_up_d "$@" ;;
  app)      cmd_app "$@" ;;
  obs)      cmd_obs_only "$@" ;;
  down)     cmd_down "$@" ;;
  restart)  cmd_restart "$@" ;;
  build)    cmd_build "$@" ;;
  logs)     cmd_logs "$@" ;;
  ps|status) cmd_ps "$@" ;;
  test)     cmd_test "$@" ;;
  shell)    cmd_shell "$@" ;;
  smoke)    cmd_smoke "$@" ;;
  tray)     cmd_tray "$@" ;;
  plugin-build)  cmd_plugin_build "$@" ;;
  plugin-reload) cmd_plugin_reload "$@" ;;
  clean)    cmd_clean "$@" ;;
  help|-h|--help) cmd_help ;;
  *)        fail "unknown command: $action (try './start.sh help')" ;;
esac
