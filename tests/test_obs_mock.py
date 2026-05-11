"""Mock OBS client behavior."""

from __future__ import annotations

import pytest

from spark_libre.obs_client import MockOBSClient


@pytest.mark.asyncio
async def test_mock_lifecycle():
    obs = MockOBSClient()
    assert not await obs.is_connected()
    await obs.connect()
    assert await obs.is_connected()
    await obs.disconnect()
    assert not await obs.is_connected()


@pytest.mark.asyncio
async def test_upsert_creates_then_updates():
    obs = MockOBSClient()
    await obs.connect()

    first = await obs.upsert_browser_source("ovr", "http://127.0.0.1:8765/overlays/a.html")
    assert first["mock"] is True
    assert first["scene"] == "Spark Libre"
    assert obs.sources["ovr"].url.endswith("a.html")

    await obs.upsert_browser_source("ovr", "http://127.0.0.1:8765/overlays/b.html")
    assert obs.sources["ovr"].url.endswith("b.html")
    assert len(obs.sources) == 1


@pytest.mark.asyncio
async def test_upsert_creates_missing_scene():
    obs = MockOBSClient()
    await obs.connect()
    await obs.upsert_browser_source("x", "http://127.0.0.1:8765/overlays/a.html", scene="Custom")
    assert "Custom" in await obs.list_scenes()
