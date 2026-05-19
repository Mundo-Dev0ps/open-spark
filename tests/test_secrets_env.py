"""Env-var fallback for secrets_store, used inside containers.

When OPENSPARK_USE_ENV_SECRETS=1 we MUST NOT touch the OS keyring (it does not
exist in a stripped container anyway). All reads fall back to env vars,
all writes become no-ops with a warning.
"""

from __future__ import annotations

import pytest

from open_spark import secrets_store


@pytest.fixture
def env_mode(monkeypatch: pytest.MonkeyPatch):
    """Force env-secret mode and clear common provider vars."""
    monkeypatch.setenv("OPENSPARK_USE_ENV_SECRETS", "1")
    for var in (
        "OPENSPARK_OBS_PASSWORD",
        "ANTHROPIC_API_KEY",
        "OPENAI_API_KEY",
        "GEMINI_API_KEY",
        "GROQ_API_KEY",
        "NVIDIA_NIM_API_KEY",
        "DEEPSEEK_API_KEY",
        "OPENROUTER_API_KEY",
    ):
        monkeypatch.delenv(var, raising=False)
    yield monkeypatch


def test_env_mode_reads_obs_password(env_mode: pytest.MonkeyPatch) -> None:
    env_mode.setenv("OPENSPARK_OBS_PASSWORD", "swordfish")
    assert secrets_store.get_obs_password() == "swordfish"


def test_env_mode_obs_password_missing_returns_none(env_mode: pytest.MonkeyPatch) -> None:
    assert secrets_store.get_obs_password() is None


@pytest.mark.parametrize(
    ("provider", "var", "value"),
    [
        ("anthropic", "ANTHROPIC_API_KEY", "sk-ant-xyz"),
        ("openai", "OPENAI_API_KEY", "sk-openai-xyz"),
        ("gemini", "GEMINI_API_KEY", "AIza-xyz"),
        ("groq", "GROQ_API_KEY", "gsk_xyz"),
        ("nvidia", "NVIDIA_NIM_API_KEY", "nvapi-xyz"),
        ("nvidia_nim", "NVIDIA_NIM_API_KEY", "nvapi-xyz"),
        ("deepseek", "DEEPSEEK_API_KEY", "sk-deepseek-xyz"),
        ("openrouter", "OPENROUTER_API_KEY", "sk-or-xyz"),
    ],
)
def test_env_mode_reads_llm_keys(
    env_mode: pytest.MonkeyPatch, provider: str, var: str, value: str
) -> None:
    env_mode.setenv(var, value)
    assert secrets_store.get_llm_api_key(provider) == value
    assert secrets_store.has_llm_api_key(provider) is True


def test_env_mode_has_llm_api_key_false_when_unset(env_mode: pytest.MonkeyPatch) -> None:
    assert secrets_store.has_llm_api_key("anthropic") is False


def test_env_mode_set_persists_to_user_file(env_mode: pytest.MonkeyPatch, tmp_app_dir) -> None:
    """Writes go to .data/user_secrets.json; reads pick them up."""
    secrets_store.set_obs_password("typed-by-user")
    # No env var, so reads must fall through to the user file.
    assert secrets_store.get_obs_password() == "typed-by-user"


def test_env_mode_env_var_wins_over_user_file(env_mode: pytest.MonkeyPatch, tmp_app_dir) -> None:
    """Env vars are authoritative — UI-typed keys never override docker compose."""
    secrets_store.set_llm_api_key("anthropic", "from-ui")
    env_mode.setenv("ANTHROPIC_API_KEY", "from-env")
    assert secrets_store.get_llm_api_key("anthropic") == "from-env"


def test_env_mode_delete_clears_user_file(env_mode: pytest.MonkeyPatch, tmp_app_dir) -> None:
    secrets_store.set_llm_api_key("anthropic", "from-ui")
    assert secrets_store.get_llm_api_key("anthropic") == "from-ui"
    secrets_store.delete_llm_api_key("anthropic")
    assert secrets_store.get_llm_api_key("anthropic") is None


def test_env_mode_off_falls_through_to_keyring(monkeypatch: pytest.MonkeyPatch) -> None:
    """When the flag is unset/0 we go through keyring as before."""
    monkeypatch.delenv("OPENSPARK_USE_ENV_SECRETS", raising=False)
    fake: dict[tuple[str, str], str] = {}

    class FakeKeyring:
        @staticmethod
        def get_password(service: str, key: str) -> str | None:
            return fake.get((service, key))

        @staticmethod
        def set_password(service: str, key: str, value: str) -> None:
            fake[(service, key)] = value

        @staticmethod
        def delete_password(service: str, key: str) -> None:
            fake.pop((service, key), None)

    monkeypatch.setattr(secrets_store, "keyring", FakeKeyring)

    secrets_store.set_obs_password("hunter2")
    assert secrets_store.get_obs_password() == "hunter2"

    secrets_store.set_llm_api_key("openai", "sk-1")
    assert secrets_store.get_llm_api_key("openai") == "sk-1"
    secrets_store.delete_llm_api_key("openai")
    assert secrets_store.get_llm_api_key("openai") is None
