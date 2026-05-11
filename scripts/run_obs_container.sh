#!/usr/bin/env bash
# Boot OBS Studio inside a rootless Podman container, isolated from the
# host's real OBS install. Auto-detects:
#   - Display server (Wayland preferred, X11 fallback)
#   - GPU (Intel/AMD via /dev/dri, NVIDIA via CDI if nvidia-container-toolkit is installed)
#   - Audio (PipeWire socket preferred, PulseAudio fallback)
#   - Webcams (/dev/video*)
#   - DBus session bus (for portals)
#
# obs-websocket inside the container listens on 4455 by default; we use
# `--network=host` so the Open Spark backend on the host can reach
# 127.0.0.1:4455 with no port-forwarding gymnastics.
#
# Usage:
#   ./scripts/run_obs_container.sh                 # auto build + run
#   IMAGE=localhost/spark-obs ./scripts/run_obs_container.sh
#   REBUILD=1 ./scripts/run_obs_container.sh       # force rebuild

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PORTABLE_DIR="${PORTABLE_DIR:-$REPO_ROOT/.portable-obs}"
IMAGE="${IMAGE:-localhost/spark-obs:latest}"
CONTAINERFILE="$REPO_ROOT/scripts/Containerfile.obs"
CONTAINER_NAME="${CONTAINER_NAME:-spark-obs}"

mkdir -p "$PORTABLE_DIR"

if ! command -v podman >/dev/null 2>&1; then
    echo "podman not found. Install with: sudo dnf install podman" >&2
    exit 1
fi

if [[ "${REBUILD:-0}" == "1" ]] || ! podman image exists "$IMAGE"; then
    echo ">> building $IMAGE"
    podman build -t "$IMAGE" -f "$CONTAINERFILE" "$REPO_ROOT/scripts"
fi

# Refuse to run a stale container with the same name.
if podman container exists "$CONTAINER_NAME"; then
    podman rm -f "$CONTAINER_NAME" >/dev/null
fi

declare -a FLAGS=(
    --rm
    -it
    --name "$CONTAINER_NAME"
    --userns=keep-id
    --network=host
    --security-opt label=disable
    --ipc=host
)

# ----- GPU: Intel / AMD via /dev/dri -----
if [[ -d /dev/dri ]]; then
    FLAGS+=(--device /dev/dri)
fi
for grp in render video; do
    gid="$(getent group "$grp" 2>/dev/null | cut -d: -f3 || true)"
    [[ -n "$gid" ]] && FLAGS+=(--group-add "$gid")
done

# ----- GPU: NVIDIA via CDI (requires nvidia-container-toolkit) -----
if command -v nvidia-smi >/dev/null 2>&1; then
    if podman info --format '{{.Host.CgroupManager}}' >/dev/null 2>&1; then
        FLAGS+=(--device nvidia.com/gpu=all)
        echo ">> NVIDIA detected; passing --device nvidia.com/gpu=all"
    fi
fi

# ----- Webcams -----
shopt -s nullglob
for cam in /dev/video*; do
    FLAGS+=(--device "$cam")
done
shopt -u nullglob

# ----- Audio: PipeWire socket -----
RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
PIPEWIRE_SOCK="$RUNTIME_DIR/pipewire-0"
if [[ -S "$PIPEWIRE_SOCK" ]]; then
    FLAGS+=(
        -v "$PIPEWIRE_SOCK:$PIPEWIRE_SOCK"
        -e "PIPEWIRE_RUNTIME_DIR=$RUNTIME_DIR"
        -e "XDG_RUNTIME_DIR=$RUNTIME_DIR"
    )
fi
PULSE_DIR="$RUNTIME_DIR/pulse"
if [[ -d "$PULSE_DIR" ]]; then
    FLAGS+=(-v "$PULSE_DIR:$PULSE_DIR")
fi

# ----- Display: Wayland first, X11 fallback -----
DISPLAY_OK=0
if [[ -n "${WAYLAND_DISPLAY:-}" && -S "$RUNTIME_DIR/$WAYLAND_DISPLAY" ]]; then
    FLAGS+=(
        -e "WAYLAND_DISPLAY=$WAYLAND_DISPLAY"
        -v "$RUNTIME_DIR/$WAYLAND_DISPLAY:$RUNTIME_DIR/$WAYLAND_DISPLAY"
    )
    DISPLAY_OK=1
    echo ">> using Wayland display $WAYLAND_DISPLAY"
fi
if [[ -n "${DISPLAY:-}" ]]; then
    FLAGS+=(
        -e "DISPLAY=$DISPLAY"
        -v /tmp/.X11-unix:/tmp/.X11-unix
    )
    if command -v xhost >/dev/null 2>&1; then
        xhost +SI:localuser:"$(id -un)" >/dev/null 2>&1 || true
    fi
    DISPLAY_OK=1
fi
if [[ "$DISPLAY_OK" -eq 0 ]]; then
    echo "ERROR: no Wayland or X11 display detected" >&2
    exit 2
fi

# ----- DBus session bus (xdg-desktop-portal, tray, screencast) -----
if [[ -n "${DBUS_SESSION_BUS_ADDRESS:-}" ]]; then
    FLAGS+=(-e "DBUS_SESSION_BUS_ADDRESS=$DBUS_SESSION_BUS_ADDRESS")
    sock="${DBUS_SESSION_BUS_ADDRESS#unix:path=}"
    sock="${sock%%,*}"
    [[ -S "$sock" ]] && FLAGS+=(-v "$sock:$sock")
fi

# ----- Portable OBS state -----
FLAGS+=(-v "$PORTABLE_DIR:/portable:Z")

echo ">> launching $IMAGE  (portable dir: $PORTABLE_DIR)"
echo ">> obs-websocket will listen on 127.0.0.1:4455 once enabled in OBS Tools menu"
exec podman run "${FLAGS[@]}" "$IMAGE" "$@"
