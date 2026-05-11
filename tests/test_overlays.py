"""OverlayStore round-trip."""

from __future__ import annotations

from open_spark.overlays import OverlayStore


def test_save_and_list(overlay_store: OverlayStore):
    ov = overlay_store.save(
        prompt="neon timer", html="<!doctype html><html></html>", model="anthropic/x"
    )
    assert ov.id
    assert ov.slug == "neon-timer"

    items = overlay_store.list()
    assert len(items) == 1
    assert items[0].id == ov.id

    path = overlay_store.html_path(ov.id)
    assert path is not None and path.exists()


def test_delete(overlay_store: OverlayStore):
    ov = overlay_store.save(prompt="x", html="<!doctype html>", model="m")
    assert overlay_store.delete(ov.id) is True
    assert overlay_store.list() == []
    assert overlay_store.delete(ov.id) is False


def test_slug_fallback(overlay_store: OverlayStore):
    ov = overlay_store.save(prompt="!!!", html="<!doctype html>", model="m")
    assert ov.slug


def test_clear_removes_all(overlay_store: OverlayStore):
    paths = []
    for i in range(3):
        ov = overlay_store.save(
            prompt=f"x{i}", html="<!doctype html>", model="m"
        )
        paths.append(overlay_store.html_path(ov.id))

    assert len(overlay_store.list()) == 3
    for p in paths:
        assert p and p.exists()

    deleted = overlay_store.clear()
    assert deleted == 3
    assert overlay_store.list() == []
    for p in paths:
        assert not p.exists()


def test_clear_empty_returns_zero(overlay_store: OverlayStore):
    assert overlay_store.clear() == 0


def test_clear_endpoint_wipes_index(client):
    """End-to-end DELETE /api/overlays."""
    # Generate three overlays through the route (uses the fake_llm fixture).
    for i in range(3):
        r = client.post("/api/generate", json={"prompt": f"timer {i}"})
        assert r.status_code == 200, r.text
    assert len(client.get("/api/overlays").json()) == 3

    r = client.delete("/api/overlays")
    assert r.status_code == 200
    assert r.json() == {"deleted_count": 3}
    assert client.get("/api/overlays").json() == []
