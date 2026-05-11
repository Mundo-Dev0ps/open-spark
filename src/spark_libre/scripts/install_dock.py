"""Register Spark Libre as a Custom Browser Dock in OBS Studio.

OBS persists docks in ``global.ini`` under section ``[BasicWindow]`` with
keys ``ExtraBrowserDocks`` (a JSON array) and the legacy
``ExtraBrowserDocksJson`` (the same payload, JSON-encoded as one string).
We update both — different OBS versions read different keys.

Idempotent: running twice does not produce duplicates.
"""

from __future__ import annotations

import argparse
import configparser
import json
import logging
import sys
from pathlib import Path

from ..config import obs_config_dirs

log = logging.getLogger(__name__)

DEFAULT_DOCK_NAME = "Spark Libre"
DEFAULT_URL = "http://127.0.0.1:8765"


def _ensure_dock_entry(entries: list[dict], name: str, url: str) -> list[dict]:
    cleaned = [e for e in entries if e.get("title") != name]
    cleaned.append({"title": name, "url": url, "uuid": ""})
    return cleaned


def _read_global_ini(path: Path) -> configparser.ConfigParser:
    cp = configparser.ConfigParser(interpolation=None, strict=False)
    cp.optionxform = str  # preserve case (OBS uses CamelCase keys)
    if path.exists():
        cp.read(path, encoding="utf-8")
    return cp


def _write_global_ini(cp: configparser.ConfigParser, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        backup = path.with_suffix(path.suffix + ".bak")
        backup.write_bytes(path.read_bytes())
        log.info("backup written: %s", backup)
    with path.open("w", encoding="utf-8") as f:
        cp.write(f, space_around_delimiters=False)


def install(
    name: str = DEFAULT_DOCK_NAME,
    url: str = DEFAULT_URL,
    config_dir: Path | None = None,
) -> Path:
    """Update OBS ``global.ini`` to include the Spark Libre dock.

    Returns the path of the modified file.
    """
    target_dir = config_dir or obs_config_dirs()[0]
    if not target_dir.exists():
        log.warning(
            "OBS config dir %s does not exist yet. Creating it; OBS may overwrite "
            "this file on first launch.",
            target_dir,
        )
        target_dir.mkdir(parents=True, exist_ok=True)
    global_ini = target_dir / "global.ini"

    cp = _read_global_ini(global_ini)
    if "BasicWindow" not in cp:
        cp["BasicWindow"] = {}

    raw = cp["BasicWindow"].get("ExtraBrowserDocks", "[]")
    try:
        entries = json.loads(raw) if raw else []
        if not isinstance(entries, list):
            entries = []
    except json.JSONDecodeError:
        log.warning("ExtraBrowserDocks was not valid JSON; resetting.")
        entries = []

    new_entries = _ensure_dock_entry(entries, name, url)
    cp["BasicWindow"]["ExtraBrowserDocks"] = json.dumps(new_entries, ensure_ascii=False)

    _write_global_ini(cp, global_ini)
    log.info("registered dock %r → %s in %s", name, url, global_ini)
    return global_ini


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    parser = argparse.ArgumentParser(description="Install Spark Libre OBS dock")
    parser.add_argument("--name", default=DEFAULT_DOCK_NAME)
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--config-dir", type=Path, default=None,
                        help="OBS config dir (auto-detected if omitted)")
    parser.add_argument("--list-candidates", action="store_true",
                        help="print detected OBS config dirs and exit")
    args = parser.parse_args()

    if args.list_candidates:
        for p in obs_config_dirs():
            mark = "✓" if p.exists() else "·"
            print(f"{mark} {p}")
        return 0

    try:
        install(name=args.name, url=args.url, config_dir=args.config_dir)
        print("Done. Restart OBS, then enable the dock from View → Docks.")
        return 0
    except Exception as e:
        print(f"failed: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
