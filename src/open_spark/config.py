"""Runtime configuration and OS-specific paths.

All paths use :class:`pathlib.Path`. No string concatenation, no os.path.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

APP_NAME = "open-spark"
KEYRING_SERVICE = "open-spark"


def app_data_dir() -> Path:
    """Per-user data dir for Open Spark's own state (config.json, overlays)."""
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    out = base / APP_NAME
    out.mkdir(parents=True, exist_ok=True)
    return out


def overlays_dir() -> Path:
    out = app_data_dir() / "overlays"
    out.mkdir(parents=True, exist_ok=True)
    return out


def obs_config_dirs() -> list[Path]:
    """Candidate OBS Studio config dirs, in priority order.

    Returns existing dirs first; non-existing candidates trail so the install
    script can pick the platform default to *create* if needed.
    """
    candidates: list[Path] = []
    home = Path.home()

    if sys.platform == "win32":
        appdata = Path(os.environ.get("APPDATA", home / "AppData" / "Roaming"))
        candidates.append(appdata / "obs-studio")
    elif sys.platform == "darwin":
        candidates.append(home / "Library" / "Application Support" / "obs-studio")
    else:
        # Native install
        xdg = Path(os.environ.get("XDG_CONFIG_HOME", home / ".config"))
        candidates.append(xdg / "obs-studio")
        # Flatpak
        candidates.append(home / ".var" / "app" / "com.obsproject.Studio" / "config" / "obs-studio")
        # Snap
        candidates.append(home / "snap" / "obs-studio" / "current" / ".config" / "obs-studio")

    existing = [p for p in candidates if p.exists()]
    missing = [p for p in candidates if not p.exists()]
    return existing + missing


class Settings(BaseSettings):
    """Process settings. Sourced from .env, env vars, then defaults."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="OPENSPARK_",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    host: str = "127.0.0.1"
    port: int = 8765

    obs_host: str = "127.0.0.1"
    obs_port: int = 4455
    mock_obs: bool = False

    default_model: str = "anthropic/claude-sonnet-4-6"
    llm_base_url: str = ""

    log_level: str = "INFO"

    # Overlay scene defaults
    obs_scene_name: str = "Open Spark"
    obs_source_prefix: str = "open-spark-overlay"

    @property
    def overlay_base_url(self) -> str:
        return f"http://{self.host}:{self.port}/overlays"

    def bind_address(self) -> tuple[str, int]:
        # Hard rule: never bind to a non-loopback address.
        host = self.host
        if host not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError(
                f"Refusing to bind to non-loopback host {host!r}. "
                "Open Spark is local-only by design."
            )
        return (host, self.port)


def get_settings() -> Settings:
    return Settings(_env_file=Path.cwd() / ".env" if (Path.cwd() / ".env").exists() else None)


# User-editable, non-secret config saved as JSON next to overlays.
USER_CONFIG_PATH = app_data_dir() / "config.json"
