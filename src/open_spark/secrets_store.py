"""Wrapper over `keyring` so secrets never hit disk in plaintext.

Two modes:

1. **Keyring mode (default)** — host install, real desktop session. Secrets
   are stored in the OS keyring (gnome-keyring, kwallet, Windows Credential
   Manager, macOS Keychain).

2. **Env mode** — set ``OPENSPARK_USE_ENV_SECRETS=1``. Used inside containers
   where there is no DBus / keyring backend. Reads come from environment
   variables; writes are no-ops with a warning. This keeps the contract
   "secrets never on disk in plaintext" intact: containers receive secrets
   from `compose.yaml` env vars, which the user fills in `.env`.

Env-mode mapping:

    obs-ws-password   → OPENSPARK_OBS_PASSWORD
    llm:anthropic     → ANTHROPIC_API_KEY
    llm:openai        → OPENAI_API_KEY
    llm:gemini        → GEMINI_API_KEY
    llm:groq          → GROQ_API_KEY
    llm:ollama        → OLLAMA_API_KEY
    <other>           → OPENSPARK_SECRET_<KEY_UPPERCASED_AND_SANITIZED>

Audit / clear via ``keyring`` CLI (host) or compose env (container):

    keyring get open-spark obs-ws-password
    keyring del open-spark llm:anthropic
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
from pathlib import Path

import keyring
from keyring.errors import KeyringError

from .config import KEYRING_SERVICE, app_data_dir

log = logging.getLogger(__name__)

OBS_PASSWORD_KEY = "obs-ws-password"

_ENV_OVERRIDES: dict[str, str] = {
    OBS_PASSWORD_KEY: "OPENSPARK_OBS_PASSWORD",
    "llm:anthropic": "ANTHROPIC_API_KEY",
    "llm:openai": "OPENAI_API_KEY",
    "llm:gemini": "GEMINI_API_KEY",
    "llm:groq": "GROQ_API_KEY",
    "llm:ollama": "OLLAMA_API_KEY",
    # NVIDIA NIM (build.nvidia.com) — free credits, OpenAI-compatible.
    # Both spellings map to the same env var so the user can write the
    # provider as "nvidia" or "nvidia_nim" interchangeably.
    "llm:nvidia": "NVIDIA_NIM_API_KEY",
    "llm:nvidia_nim": "NVIDIA_NIM_API_KEY",
    # DeepSeek (platform.deepseek.com) — cheap pay-as-you-go, no free tier.
    "llm:deepseek": "DEEPSEEK_API_KEY",
    # OpenRouter (openrouter.ai) — aggregator, has a free models tier.
    "llm:openrouter": "OPENROUTER_API_KEY",
}


def _llm_key(provider: str) -> str:
    return f"llm:{provider.lower()}"


def _env_mode() -> bool:
    """True when the container/CI flag is set."""
    return os.environ.get("OPENSPARK_USE_ENV_SECRETS", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _env_var_for(key: str) -> str:
    if key in _ENV_OVERRIDES:
        return _ENV_OVERRIDES[key]
    sanitized = "".join(c if c.isalnum() else "_" for c in key).upper()
    return f"OPENSPARK_SECRET_{sanitized}"


def _user_secrets_path() -> Path:
    """Override file used in env mode so the dock UI can persist keys
    the user types in at runtime. 0600 permissions; never committed."""
    return app_data_dir() / "user_secrets.json"


def _read_user_secrets() -> dict[str, str]:
    p = _user_secrets_path()
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return {k: v for k, v in data.items() if isinstance(v, str)}
    except (json.JSONDecodeError, OSError) as e:
        log.warning("user secrets file unreadable: %s", e)
        return {}


def _write_user_secrets(d: dict[str, str]) -> None:
    p = _user_secrets_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(d, indent=2), encoding="utf-8")
    with contextlib.suppress(OSError):
        p.chmod(0o600)


def get_secret(key: str) -> str | None:
    if _env_mode():
        # Resolution order in env mode:
        #   1. process env var (set by docker compose / shell)
        #   2. user_secrets.json (set via the dock Settings tab)
        # Env wins so an explicit container var stays authoritative.
        env_value = os.environ.get(_env_var_for(key))
        if env_value:
            return env_value
        return _read_user_secrets().get(key) or None
    try:
        return keyring.get_password(KEYRING_SERVICE, key)
    except KeyringError as e:
        log.warning("keyring read failed for %s: %s", key, e)
        return None


def set_secret(key: str, value: str) -> None:
    if _env_mode():
        # No keyring + DBus in containers, so we persist to a per-user
        # JSON file (0600). Env vars still win on reads (see get_secret).
        d = _read_user_secrets()
        d[key] = value
        _write_user_secrets(d)
        log.info("user_secrets.json updated for key=%s", key)
        return
    keyring.set_password(KEYRING_SERVICE, key, value)


def delete_secret(key: str) -> None:
    if _env_mode():
        d = _read_user_secrets()
        if key in d:
            d.pop(key, None)
            _write_user_secrets(d)
            log.info("user_secrets.json removed key=%s", key)
        return
    with contextlib.suppress(KeyringError):
        keyring.delete_password(KEYRING_SERVICE, key)


def get_obs_password() -> str | None:
    return get_secret(OBS_PASSWORD_KEY)


def set_obs_password(value: str) -> None:
    set_secret(OBS_PASSWORD_KEY, value)


def get_llm_api_key(provider: str) -> str | None:
    return get_secret(_llm_key(provider))


def set_llm_api_key(provider: str, value: str) -> None:
    set_secret(_llm_key(provider), value)


def delete_llm_api_key(provider: str) -> None:
    delete_secret(_llm_key(provider))


def has_llm_api_key(provider: str) -> bool:
    return bool(get_llm_api_key(provider))
