"""Tests for the scene-template generation pipeline.

Covers:

* :func:`llm._extract_json` — fence stripping, slice extraction, errors.
* :func:`llm._validate_layout` — defaults, background coercion, html
  doctype repair, missing-source rejection.
* MockOBSClient.upsert_scene_layout — replace semantics, transform copy.
* The ``POST /api/scenes/templates`` route end-to-end with a stub LLM.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from open_spark import llm
from open_spark.obs_client import MockOBSClient

# --- _extract_json -----------------------------------------------------------


def test_extract_json_pure() -> None:
    payload = {"a": 1, "b": [1, 2]}
    assert llm._extract_json(json.dumps(payload)) == payload


def test_extract_json_with_fence() -> None:
    raw = '```json\n{"a": 1}\n```'
    assert llm._extract_json(raw) == {"a": 1}


def test_extract_json_with_prose_around() -> None:
    raw = (
        'Sure, here is the JSON:\n\n{"scene_name": "X", "sources": []}'
        "\n\nLet me know if you want changes."
    )
    assert llm._extract_json(raw) == {"scene_name": "X", "sources": []}


def test_extract_json_no_object_raises() -> None:
    with pytest.raises(ValueError):
        llm._extract_json("nothing JSON here")


# --- _validate_layout --------------------------------------------------------

_MIN_HTML = "<!doctype html><html><body>x</body></html>"


def test_validate_layout_minimal_ok() -> None:
    data = {
        "scene_name": "Demo",
        "canvas": {"width": 1920, "height": 1080},
        "sources": [
            {
                "role": "title",
                "name": "title-1",
                "html": _MIN_HTML,
                "transform": {"x": 0, "y": 0, "width": 1920, "height": 200},
            }
        ],
    }
    layout = llm._validate_layout(data, default_canvas=(1920, 1080))
    assert layout.scene_name == "Demo"
    assert layout.canvas == {"width": 1920, "height": 1080}
    assert len(layout.sources) == 1
    assert layout.sources[0].role == "title"


def test_validate_layout_background_role_full_canvas() -> None:
    data = {
        "scene_name": "BG",
        "sources": [
            {
                "role": "background",
                "name": "bg",
                "html": _MIN_HTML,
                "transform": {"x": 100, "y": 100, "width": 50, "height": 50},
            }
        ],
    }
    layout = llm._validate_layout(data, default_canvas=(1920, 1080))
    t = layout.sources[0].transform
    assert (t["x"], t["y"], t["width"], t["height"]) == (0, 0, 1920, 1080)


def test_validate_layout_repairs_missing_doctype() -> None:
    data = {
        "scene_name": "X",
        "sources": [
            {
                "role": "title",
                "name": "title",
                "html": "<div>Hi</div>",
                "transform": {"x": 0, "y": 0, "width": 100, "height": 50},
            }
        ],
    }
    layout = llm._validate_layout(data, default_canvas=(1920, 1080))
    assert layout.sources[0].html.lower().startswith("<!doctype html>")


def test_validate_layout_rejects_no_sources() -> None:
    with pytest.raises(ValueError):
        llm._validate_layout({"scene_name": "X", "sources": []}, default_canvas=(1920, 1080))


def test_validate_layout_rejects_source_without_html() -> None:
    data = {"scene_name": "X", "sources": [{"role": "x", "name": "y"}]}
    with pytest.raises(ValueError):
        llm._validate_layout(data, default_canvas=(1920, 1080))


def test_ensure_meta_charset_injects_when_missing() -> None:
    html = "<!doctype html><html><head><title>X</title></head><body>ñ</body></html>"
    out = llm._ensure_meta_charset(html)
    assert '<meta charset="utf-8">' in out.lower().replace("'", '"')


def test_ensure_meta_charset_noop_when_present() -> None:
    html = "<!doctype html><html><head><meta charset='utf-8'></head></html>"
    out = llm._ensure_meta_charset(html)
    assert out == html


def test_validate_layout_injects_charset_into_repaired_html() -> None:
    data = {
        "scene_name": "X",
        "sources": [
            {
                "role": "title",
                "name": "title",
                "html": "<div>Notificación</div>",
                "transform": {"x": 0, "y": 0, "width": 100, "height": 50},
            }
        ],
    }
    layout = llm._validate_layout(data, default_canvas=(1920, 1080))
    assert "charset" in layout.sources[0].html.lower()


def test_validate_layout_clamps_negative_positions() -> None:
    data = {
        "scene_name": "X",
        "sources": [
            {
                "role": "title",
                "name": "t",
                "html": _MIN_HTML,
                "transform": {"x": -50, "y": -10, "width": 0, "height": -1},
            }
        ],
    }
    layout = llm._validate_layout(data, default_canvas=(1920, 1080))
    t = layout.sources[0].transform
    assert t["x"] == 0 and t["y"] == 0
    assert t["width"] >= 1 and t["height"] >= 1


# --- MockOBSClient.upsert_scene_layout --------------------------------------


@pytest.mark.asyncio
async def test_mock_upsert_scene_layout_creates_scene() -> None:
    client = MockOBSClient()
    await client.connect()
    sources = [
        {
            "name": "open-spark-overlay-bg",
            "url": "http://x/bg.html",
            "role": "background",
            "transform": {"x": 0, "y": 0, "width": 1920, "height": 1080},
        },
        {
            "name": "open-spark-overlay-chat",
            "url": "http://x/chat.html",
            "role": "chat",
            "transform": {"x": 0, "y": 200, "width": 400, "height": 700},
        },
    ]
    result = await client.upsert_scene_layout("Demo", sources)
    assert result["scene"] == "Demo"
    assert result["mock"] is True
    assert "Demo" in client.scenes
    assert len(result["sources"]) == 2
    items = client.scene_items["Demo"]
    assert items == ["open-spark-overlay-bg", "open-spark-overlay-chat"]
    bg = client.sources["open-spark-overlay-bg"]
    assert bg.transform == {"x": 0, "y": 0, "width": 1920, "height": 1080}


@pytest.mark.asyncio
async def test_mock_upsert_scene_layout_replace_clears_old_items() -> None:
    client = MockOBSClient()
    await client.connect()
    first = [
        {
            "name": "old",
            "url": "http://x/old.html",
            "role": "title",
            "transform": {"x": 0, "y": 0, "width": 100, "height": 100},
        }
    ]
    await client.upsert_scene_layout("Demo", first)
    assert "old" in client.sources

    second = [
        {
            "name": "new",
            "url": "http://x/new.html",
            "role": "title",
            "transform": {"x": 10, "y": 10, "width": 200, "height": 200},
        }
    ]
    await client.upsert_scene_layout("Demo", second, replace=True)
    assert "old" not in client.sources
    assert client.scene_items["Demo"] == ["new"]


# --- API endpoint -----------------------------------------------------------

_LLM_FAKE_REPLY = json.dumps(
    {
        "scene_name": "Stream Demo",
        "canvas": {"width": 1920, "height": 1080},
        "sources": [
            {
                "role": "background",
                "name": "bg",
                "html": _MIN_HTML,
                "transform": {"x": 0, "y": 0, "width": 1920, "height": 1080},
            },
            {
                "role": "chat",
                "name": "chat",
                "html": _MIN_HTML,
                "transform": {"x": 0, "y": 200, "width": 400, "height": 700},
            },
            {
                "role": "counter",
                "name": "counter",
                "html": _MIN_HTML,
                "transform": {"x": 1500, "y": 0, "width": 400, "height": 100},
            },
        ],
    }
)


class _FakeChoice:
    def __init__(self, content: str) -> None:
        self.message = type("M", (), {"content": content})()


class _FakeResp:
    def __init__(self, content: str) -> None:
        self.choices = [_FakeChoice(content)]
        self.usage = {"prompt_tokens": 10, "completion_tokens": 50}

    def __getitem__(self, key: str) -> Any:
        if key == "choices":
            return [{"message": {"content": self.choices[0].message.content}}]
        raise KeyError(key)


def test_scene_templates_endpoint(client, monkeypatch: pytest.MonkeyPatch) -> None:
    """End-to-end POST /api/scenes/templates with a stubbed LLM call."""

    async def fake_acompletion(**kwargs: Any) -> _FakeResp:
        # Sanity: the system prompt should be the scene one.
        msgs = kwargs["messages"]
        assert any("OBS Studio scene layouts" in m["content"] for m in msgs)
        return _FakeResp(_LLM_FAKE_REPLY)

    import litellm

    monkeypatch.setattr(litellm, "acompletion", fake_acompletion)

    r = client.post(
        "/api/scenes/templates",
        json={"prompt": "anime kawaii streaming setup, magenta neon"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["scene"] == "Stream Demo"
    assert body["mock"] is True
    assert len(body["sources"]) == 3
    roles = [s["role"] for s in body["sources"]]
    assert roles == ["background", "chat", "counter"]
    # Each source has a served URL
    for s in body["sources"]:
        served = client.get(s["url"].replace("http://127.0.0.1:8765", ""))
        assert served.status_code == 200
        assert "<!doctype html>" in served.text.lower()


def test_scene_templates_endpoint_rejects_no_sources(
    client, monkeypatch: pytest.MonkeyPatch
) -> None:
    bad_reply = json.dumps({"scene_name": "X", "sources": []})

    async def fake_acompletion(**kwargs: Any) -> _FakeResp:
        return _FakeResp(bad_reply)

    import litellm

    monkeypatch.setattr(litellm, "acompletion", fake_acompletion)

    r = client.post("/api/scenes/templates", json={"prompt": "x"})
    assert r.status_code == 502
    assert "no sources" in r.json()["detail"].lower()


# --- Overlap resolver --------------------------------------------------------


def _src(role: str, name: str, x: int, y: int, w: int, h: int) -> llm.SceneSourceLayout:
    return llm.SceneSourceLayout(
        role=role,
        name=name,
        html=_MIN_HTML,
        transform={"x": x, "y": y, "width": w, "height": h},
    )


def test_resolve_overlaps_disjoint_unchanged() -> None:
    a = _src("title", "a", 0, 0, 400, 100)
    b = _src("counter", "b", 500, 0, 200, 100)
    out = llm._resolve_overlaps([a, b], canvas=(1920, 1080))
    assert out[0].transform == a.transform
    assert out[1].transform == b.transform


def test_resolve_overlaps_moves_collider() -> None:
    a = _src("title", "a", 0, 0, 400, 200)
    b = _src("chat", "b", 100, 100, 300, 300)  # overlaps a
    out = llm._resolve_overlaps([a, b], canvas=(1920, 1080))
    assert out[0].transform == a.transform  # first wins
    assert not llm._rects_overlap(out[0].transform, out[1].transform)


def test_resolve_overlaps_background_allowed_under() -> None:
    bg = _src("background", "bg", 0, 0, 1920, 1080)
    chat = _src("chat", "chat", 0, 200, 400, 700)  # fully inside bg
    out = llm._resolve_overlaps([bg, chat], canvas=(1920, 1080))
    # Chat must NOT have been moved out of the background.
    assert out[1].transform == chat.transform


def test_resolve_overlaps_clamps_to_canvas() -> None:
    a = _src("title", "a", 1900, 1070, 400, 200)  # extends past 1920/1080
    out = llm._resolve_overlaps([a], canvas=(1920, 1080))
    t = out[0].transform
    assert t["x"] + t["width"] <= 1920
    assert t["y"] + t["height"] <= 1080


# --- Style presets -----------------------------------------------------------


def test_apply_style_known_key_prepends_preamble() -> None:
    out = llm._apply_style("hello", "anime_kawaii")
    out_l = out.lower()
    # Style preamble may use "anime kawaii" or "anime/kawaii"; both match.
    assert "anime" in out_l and "kawaii" in out_l
    assert "hello" in out


def test_apply_style_unknown_key_passthrough() -> None:
    out = llm._apply_style("hello", "does_not_exist")
    assert out == "hello"


def test_apply_style_none_passthrough() -> None:
    assert llm._apply_style("hello", None) == "hello"


def test_styles_endpoint_returns_known_keys(client) -> None:
    r = client.get("/api/styles")
    assert r.status_code == 200
    keys = {item["key"] for item in r.json()}
    assert "anime_kawaii" in keys
    assert "cyberpunk" in keys


# --- Regenerate endpoint -----------------------------------------------------


def test_regenerate_overlay_overwrites_html(client, monkeypatch: pytest.MonkeyPatch) -> None:
    # First, generate one through the existing fake_llm fixture.
    r = client.post("/api/generate", json={"prompt": "neon timer"})
    assert r.status_code == 200, r.text
    overlay_id = r.json()["overlay_id"]

    served_before = client.get(f"/overlays/{overlay_id}.html").text

    new_html = (
        "<!doctype html><html><head><meta charset='utf-8'></head>"
        "<body>NEW REGEN PAYLOAD</body></html>"
    )

    from open_spark import llm as llm_mod

    async def _fake(prompt: str, *, model: str, base_url=None, style=None):
        return llm_mod.LLMResult(html=new_html, model="stub", usage={})

    monkeypatch.setattr(llm_mod, "generate_overlay", _fake)

    r = client.post(
        f"/api/overlays/{overlay_id}/regenerate",
        json={"prompt": None, "style": "cyberpunk"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["overlay_id"] == overlay_id
    assert body["model"] == "stub"

    served_after = client.get(f"/overlays/{overlay_id}.html").text
    assert served_after != served_before
    assert "NEW REGEN PAYLOAD" in served_after


def test_regenerate_overlay_404_on_missing(client) -> None:
    r = client.post(
        "/api/overlays/does-not-exist/regenerate",
        json={"prompt": "x"},
    )
    assert r.status_code == 404


# --- Refine endpoint --------------------------------------------------------


def test_refine_overlay_patches_html(client, monkeypatch: pytest.MonkeyPatch) -> None:
    """POST /api/overlays/{id}/refine swaps the HTML via a delta."""
    # First generate an overlay so there's something to refine.
    r = client.post("/api/generate", json={"prompt": "neon timer"})
    assert r.status_code == 200, r.text
    overlay_id = r.json()["overlay_id"]
    before = client.get(f"/overlays/{overlay_id}.html").text

    refined_html = (
        "<!doctype html><html><head><meta charset='utf-8'></head>"
        "<body><h1>REFINED</h1></body></html>"
    )

    from open_spark import llm as llm_mod

    async def _fake_refine(*, existing_html, instruction, model, base_url=None, style=None):
        # Sanity: the route MUST hand us the existing HTML
        # so the LLM can patch instead of regenerate from scratch.
        assert existing_html
        assert instruction.startswith("make")
        return llm_mod.LLMResult(html=refined_html, model="stub", usage={})

    monkeypatch.setattr(llm_mod, "refine_overlay", _fake_refine)

    r = client.post(
        f"/api/overlays/{overlay_id}/refine",
        json={"instruction": "make the bg darker"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["overlay_id"] == overlay_id
    assert body["model"] == "stub"

    after = client.get(f"/overlays/{overlay_id}.html").text
    assert after != before
    assert "REFINED" in after


def test_refine_overlay_404_on_missing(client) -> None:
    r = client.post("/api/overlays/nope/refine", json={"instruction": "x"})
    assert r.status_code == 404


# --- Inject defaults to active scene ----------------------------------------


def test_inject_uses_current_scene_when_no_scene_provided(client, overlay_store, settings) -> None:
    """If the caller didn't specify a scene, inject lands on whatever
    the user currently has selected in OBS, NOT on the hard-coded
    "Open Spark" scene which the user probably can't see."""
    # Generate so we have something to inject.
    r = client.post("/api/generate", json={"prompt": "x"})
    assert r.status_code == 200, r.text
    overlay_id = r.json()["overlay_id"]

    # Mock OBS reports two scenes; the LAST is the current one.
    state = client.app.state.spark
    state.obs.scenes = ["UserScene", "ProgramScene"]

    r = client.post("/api/inject", json={"overlay_id": overlay_id})
    assert r.status_code == 200, r.text
    assert r.json()["scene"] == "ProgramScene"


def test_inject_explicit_scene_wins(client) -> None:
    r = client.post("/api/generate", json={"prompt": "x"})
    overlay_id = r.json()["overlay_id"]
    r = client.post(
        "/api/inject",
        json={"overlay_id": overlay_id, "scene": "ExplicitScene"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["scene"] == "ExplicitScene"
