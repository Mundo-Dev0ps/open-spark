"""API smoke tests against the FastAPI app with mock OBS + stub LLM."""

from __future__ import annotations


def test_status(client):
    r = client.get("/api/status")
    assert r.status_code == 200
    data = r.json()
    assert data["mock_obs"] is True
    assert data["obs_connected"] is True
    assert data["overlay_count"] == 0


def test_generate_inject_serve(client):
    r = client.post("/api/generate", json={"prompt": "a glowing timer"})
    assert r.status_code == 200, r.text
    body = r.json()
    overlay_id = body["overlay_id"]
    assert body["html"].lower().startswith("<!doctype html>")
    assert body["url"].endswith(f"/overlays/{overlay_id}.html")

    served = client.get(f"/overlays/{overlay_id}.html")
    assert served.status_code == 200
    assert "<!doctype html>" in served.text.lower()

    r = client.post("/api/inject", json={"overlay_id": overlay_id})
    assert r.status_code == 200, r.text
    inj = r.json()
    assert inj["mock"] is True
    assert overlay_id[:6] in inj["url"] or inj["url"].endswith(".html")


def test_generate_then_list(client):
    client.post("/api/generate", json={"prompt": "a", "title": "My Timer"})
    client.post("/api/generate", json={"prompt": "b"})
    r = client.get("/api/overlays")
    assert r.status_code == 200
    items = r.json()
    assert len(items) == 2
    assert items[0]["title"] in {"My Timer", "b"}


def test_inject_unknown_overlay(client):
    r = client.post("/api/inject", json={"overlay_id": "doesnotexist"})
    assert r.status_code == 404


def test_settings_roundtrip(client):
    r = client.put(
        "/api/settings",
        json={"default_model": "openai/gpt-4o-mini", "obs_scene_name": "My Scene"},
    )
    assert r.status_code == 200

    r = client.get("/api/settings")
    assert r.status_code == 200
    s = r.json()
    assert s["default_model"] == "openai/gpt-4o-mini"
    assert s["obs_scene_name"] == "My Scene"


def test_settings_rejects_non_loopback():
    """Settings must refuse to bind to a non-loopback host."""
    from spark_libre.config import Settings

    s = Settings(host="0.0.0.0", port=8765)
    import pytest

    with pytest.raises(ValueError, match="loopback"):
        s.bind_address()
