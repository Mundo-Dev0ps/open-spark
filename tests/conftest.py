"""Shared pytest fixtures.

Tests never touch the real keyring, real OBS, or real LLMs.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from open_spark import config as cfg_mod
from open_spark import llm as llm_mod
from open_spark.config import Settings
from open_spark.main import create_app
from open_spark.overlays import OverlayStore


@pytest.fixture
def tmp_app_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect Open Spark's data dir to a tmp path for the duration of the test."""
    monkeypatch.setattr(cfg_mod, "app_data_dir", lambda: tmp_path)
    monkeypatch.setattr(cfg_mod, "overlays_dir", lambda: tmp_path / "overlays")
    (tmp_path / "overlays").mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(cfg_mod, "USER_CONFIG_PATH", tmp_path / "config.json")
    # Also redirect the routes module's import-time alias.
    from open_spark.api import routes

    monkeypatch.setattr(routes, "USER_CONFIG_PATH", tmp_path / "config.json")
    return tmp_path


@pytest.fixture
def settings(tmp_app_dir: Path) -> Settings:
    return Settings(host="127.0.0.1", port=8765, mock_obs=True, log_level="WARNING")


@pytest.fixture
def overlay_store(tmp_app_dir: Path) -> OverlayStore:
    return OverlayStore(root=tmp_app_dir / "overlays")


@pytest.fixture
def fake_llm(monkeypatch: pytest.MonkeyPatch):
    """Replace the LLM call with a deterministic stub."""
    canned_html = (
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<style>html,body{background:transparent;margin:0;}</style></head>"
        "<body><h1>stub overlay</h1></body></html>"
    )

    async def _fake(prompt: str, *, model: str, base_url=None, style=None, quality_passes: int = 1):
        return llm_mod.LLMResult(
            html=canned_html, model=model, usage={"prompt_tokens": len(prompt)}
        )

    monkeypatch.setattr(llm_mod, "generate_overlay", _fake)
    return canned_html


@pytest.fixture
def app(settings: Settings, fake_llm, tmp_app_dir: Path):
    return create_app(settings)


@pytest.fixture
def client(app) -> Iterator:
    from fastapi.testclient import TestClient

    with TestClient(app) as c:
        yield c
