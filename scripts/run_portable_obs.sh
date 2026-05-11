#!/usr/bin/env bash
# Boot OBS in --portable mode against ./.portable-obs/ so dev work doesn't
# touch your real OBS config. Linux.
#
# Usage: ./scripts/run_portable_obs.sh
#
# Detection order: native obs > Flatpak.

set -euo pipefail

PORTABLE_DIR="$(cd "$(dirname "$0")/.." && pwd)/.portable-obs"
mkdir -p "$PORTABLE_DIR"

if command -v obs >/dev/null 2>&1; then
    echo "Launching native OBS with portable_mode at $PORTABLE_DIR"
    cd "$PORTABLE_DIR"
    exec obs --portable --multi
fi

if command -v flatpak >/dev/null 2>&1 \
   && flatpak info com.obsproject.Studio >/dev/null 2>&1; then
    echo "Launching Flatpak OBS in portable mode at $PORTABLE_DIR"
    # Flatpak sandboxes home; expose the portable dir read-write.
    exec flatpak run \
        --filesystem="$PORTABLE_DIR" \
        com.obsproject.Studio --portable --multi
fi

echo "OBS not found. Install OBS Studio (native or Flatpak)." >&2
exit 1
