"""Agent loop + tool registry tests.

litellm.acompletion is stubbed with a scripted sequence of replies so
we exercise the multi-step tool loop deterministically against the
MockOBSClient (no real OBS, no real LLM).
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from open_spark import agent, tools

# --- registry sanity --------------------------------------------------------


def test_tool_specs_are_openai_shaped() -> None:
    specs = tools.openai_tool_specs()
    assert specs, "registry must not be empty"
    for s in specs:
        assert s["type"] == "function"
        fn = s["function"]
        assert fn["name"]
        assert fn["description"]
        assert fn["parameters"]["type"] == "object"


def test_core_tools_present() -> None:
    names = {s["function"]["name"] for s in tools.openai_tool_specs()}
    for expected in (
        "generate_overlay",
        "generate_scene",
        "inject_overlay",
        "list_scenes",
        "switch_scene",
        "add_camera",
        "set_transform",
        "add_chroma_key",
        "add_color_correction",
        "add_sharpen",
        "remove_filter",
    ):
        assert expected in names, f"missing tool {expected}"


@pytest.mark.asyncio
async def test_dispatch_unknown_tool() -> None:
    out = await tools.dispatch("does_not_exist", {}, None)
    assert "error" in out


# --- agent loop -------------------------------------------------------------


class _Resp:
    """Minimal litellm-style response wrapper."""

    def __init__(self, message: dict) -> None:
        self._message = message
        self.usage = {"prompt_tokens": 1, "completion_tokens": 1}

    def __getitem__(self, k: str) -> Any:
        if k == "choices":
            return [{"message": self._message}]
        raise KeyError(k)


def _script(monkeypatch, replies: list[dict]) -> None:
    """Feed acompletion a queue of message dicts, one per call."""
    import litellm

    q = list(replies)

    async def fake_acompletion(**kwargs: Any) -> _Resp:
        # Tools must always be offered to the model.
        assert kwargs.get("tools")
        return _Resp(q.pop(0))

    monkeypatch.setattr(litellm, "acompletion", fake_acompletion)


@pytest.mark.asyncio
async def test_agent_executes_tool_then_answers(
    monkeypatch: pytest.MonkeyPatch, settings, tmp_app_dir
) -> None:
    from open_spark.main import AppState
    from open_spark.obs_client import MockOBSClient
    from open_spark.overlays import OverlayStore

    obs = MockOBSClient()
    await obs.connect()
    st = AppState(
        settings=settings,
        obs=obs,
        overlays=OverlayStore(root=tmp_app_dir / "overlays"),
    )

    _script(
        monkeypatch,
        [
            # 1st turn: call list_scenes
            {
                "content": "",
                "tool_calls": [
                    {
                        "id": "c1",
                        "function": {"name": "list_scenes", "arguments": "{}"},
                    }
                ],
            },
            # 2nd turn: no tool calls → final answer
            {"content": "You have these scenes ready.", "tool_calls": []},
        ],
    )

    res = await agent.run_agent(
        user_messages=[{"role": "user", "content": "what scenes do I have?"}],
        state=st,
        model="stub/model",
    )
    assert res.final_message == "You have these scenes ready."
    assert len(res.steps) == 1
    assert res.steps[0].tool == "list_scenes"
    assert res.steps[0].executed is True
    assert "scenes" in res.steps[0].result


@pytest.mark.asyncio
async def test_agent_dry_run_skips_destructive(
    monkeypatch: pytest.MonkeyPatch, settings, tmp_app_dir
) -> None:
    from open_spark.main import AppState
    from open_spark.obs_client import MockOBSClient
    from open_spark.overlays import OverlayStore

    store = OverlayStore(root=tmp_app_dir / "overlays")
    ov = store.save(prompt="x", html="<!doctype html>", model="m")

    obs = MockOBSClient()
    await obs.connect()
    st = AppState(settings=settings, obs=obs, overlays=store)

    _script(
        monkeypatch,
        [
            {
                "content": "",
                "tool_calls": [
                    {
                        "id": "d1",
                        "function": {
                            "name": "delete_overlay",
                            "arguments": json.dumps({"overlay_id": ov.id}),
                        },
                    }
                ],
            },
            {"content": "Want me to actually delete it?", "tool_calls": []},
        ],
    )

    res = await agent.run_agent(
        user_messages=[{"role": "user", "content": "delete that overlay"}],
        state=st,
        model="stub/model",
        dry_run=True,
    )
    # destructive tool must NOT have run
    assert res.steps[0].executed is False
    assert res.pending_confirmation == [{"tool": "delete_overlay", "args": {"overlay_id": ov.id}}]
    # overlay still on disk
    assert store.get(ov.id) is not None


@pytest.mark.asyncio
async def test_agent_confirmation_summary(
    monkeypatch: pytest.MonkeyPatch, settings, tmp_app_dir
) -> None:
    """Blocked-delete final message must be a readable summary that:
    keeps the model's preamble, names each target, and tells the user
    nothing was deleted yet."""
    from open_spark.main import AppState
    from open_spark.obs_client import MockOBSClient
    from open_spark.overlays import OverlayStore

    obs = MockOBSClient()
    await obs.connect()
    st = AppState(
        settings=settings,
        obs=obs,
        overlays=OverlayStore(root=tmp_app_dir / "overlays"),
    )

    _script(
        monkeypatch,
        [
            {
                "content": "Voy a eliminar la escena «Intro».",
                "tool_calls": [
                    {
                        "id": "x1",
                        "function": {
                            "name": "delete_scene",
                            "arguments": json.dumps({"scene": "Intro"}),
                        },
                    }
                ],
            },
        ],
    )

    res = await agent.run_agent(
        user_messages=[{"role": "user", "content": "borra la escena Intro"}],
        state=st,
        model="stub/model",
        dry_run=True,
    )

    fm = res.final_message
    # model preamble preserved (user language)
    assert "Voy a eliminar la escena" in fm
    # exact target named
    assert "delete_scene" in fm and "Intro" in fm
    # explicit "nothing deleted yet" reassurance + confirm hint
    assert "confirm" in fm.lower()
    assert "yet" in fm.lower() or "todav" in fm.lower()
    assert res.steps[0].executed is False


@pytest.mark.asyncio
async def test_agent_step_budget(monkeypatch: pytest.MonkeyPatch, settings, tmp_app_dir) -> None:
    from open_spark.main import AppState
    from open_spark.obs_client import MockOBSClient
    from open_spark.overlays import OverlayStore

    obs = MockOBSClient()
    await obs.connect()
    st = AppState(
        settings=settings,
        obs=obs,
        overlays=OverlayStore(root=tmp_app_dir / "overlays"),
    )

    # Model keeps calling a tool forever.
    loop_reply = {
        "content": "",
        "tool_calls": [{"id": "x", "function": {"name": "list_scenes", "arguments": "{}"}}],
    }
    _script(monkeypatch, [loop_reply] * 10)

    res = await agent.run_agent(
        user_messages=[{"role": "user", "content": "loop"}],
        state=st,
        model="stub/model",
        max_steps=3,
    )
    assert len(res.steps) == 3  # capped
    assert "limit" in res.final_message.lower()


def test_agent_chat_endpoint(client, monkeypatch: pytest.MonkeyPatch) -> None:
    """End-to-end POST /api/agent/chat with a scripted single-shot reply."""
    import litellm

    async def fake_acompletion(**kwargs: Any) -> _Resp:
        return _Resp({"content": "Hi! Tell me what to build.", "tool_calls": []})

    monkeypatch.setattr(litellm, "acompletion", fake_acompletion)

    r = client.post(
        "/api/agent/chat",
        json={"messages": [{"role": "user", "content": "hello"}]},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["final_message"] == "Hi! Tell me what to build."
    assert body["steps"] == []


def test_agent_tools_catalogue(client) -> None:
    r = client.get("/api/agent/tools")
    assert r.status_code == 200
    names = {t["name"] for t in r.json()["tools"]}
    assert "add_chroma_key" in names
    assert any(t["destructive"] for t in r.json()["tools"])


# --- tool-support validation -------------------------------------------------


def test_tool_support_allowlisted() -> None:
    ok, _ = agent.tool_support("nvidia_nim/meta/llama-3.3-70b-instruct")
    assert ok is True
    ok, _ = agent.tool_support("anthropic/claude-sonnet-4-6")
    assert ok is True


def test_tool_support_rejects_tiny() -> None:
    ok, reason = agent.tool_support("ollama/llama3.2-1b")
    assert ok is False
    assert reason


def test_tool_support_unknown_is_none() -> None:
    ok, _ = agent.tool_support("some/totally-unheard-of-model-xyz")
    assert ok is None


def test_model_check_endpoint(client) -> None:
    r = client.get(
        "/api/agent/model-check",
        params={"model": "nvidia_nim/meta/llama-3.3-70b-instruct"},
    )
    assert r.status_code == 200
    assert r.json()["supported"] is True
    assert r.json()["suggestions"]


def test_agent_chat_rejects_unsupported_model(client, monkeypatch: pytest.MonkeyPatch) -> None:
    """A clearly tool-incapable model is rejected with 400 + suggestions
    instead of a cryptic 502 from the provider."""
    r = client.post(
        "/api/agent/chat",
        json={
            "messages": [{"role": "user", "content": "hi"}],
            "model": "ollama/llama3.2-1b",
        },
    )
    assert r.status_code == 400, r.text
    detail = r.json()["detail"]
    assert "tool calling" in detail["error"]
    assert detail["suggestions"]


@pytest.mark.asyncio
async def test_delete_scene_tool(settings, tmp_app_dir) -> None:
    from open_spark.main import AppState
    from open_spark.obs_client import MockOBSClient
    from open_spark.overlays import OverlayStore

    obs = MockOBSClient()
    obs.scenes = ["Scene", "Open Spark", "Doomed"]
    await obs.connect()
    st = AppState(settings=settings, obs=obs, overlays=OverlayStore(root=tmp_app_dir / "overlays"))

    out = await tools.dispatch("delete_scene", {"scene": "Doomed"}, st)
    assert out == {"deleted_scene": "Doomed"}
    assert "Doomed" not in obs.scenes

    # Unknown scene → error, not crash.
    bad = await tools.dispatch("delete_scene", {"scene": "Nope"}, st)
    assert "error" in bad


def test_delete_scene_is_destructive() -> None:
    t = tools.get_tool("delete_scene")
    assert t is not None and t.destructive is True


@pytest.mark.asyncio
async def test_new_tool_surface(settings, tmp_app_dir) -> None:
    from open_spark.main import AppState
    from open_spark.obs_client import MockOBSClient
    from open_spark.overlays import OverlayStore

    obs = MockOBSClient()
    await obs.connect()
    st = AppState(settings=settings, obs=obs, overlays=OverlayStore(root=tmp_app_dir / "overlays"))

    assert (await tools.dispatch("set_volume", {"source": "Mic", "db": -6}, st))["ok"]
    assert (await tools.dispatch("set_mute", {"source": "Mic", "muted": True}, st))["muted"] is True
    assert (
        await tools.dispatch("add_audio_filter", {"source": "Mic", "filter": "noise_suppress"}, st)
    )["ok"]
    assert (await tools.dispatch("recording_control", {"action": "start"}, st))["ok"]
    assert (
        await tools.dispatch(
            "place_source", {"scene": "Scene", "scene_item_id": 1, "anchor": "bottom-right"}, st
        )
    )["anchor"] == "bottom-right"
    bad = await tools.dispatch(
        "place_source", {"scene": "S", "scene_item_id": 1, "anchor": "nowhere"}, st
    )
    assert "error" in bad
    shot = await tools.dispatch("screenshot_program", {}, st)
    assert shot["ok"] and shot["url"].endswith(".png")
    sp = await tools.dispatch("save_scene_preset", {"scene": "Scene", "preset_name": "JC"}, st)
    assert sp["ok"]
    lp = await tools.dispatch("list_scene_presets", {}, st)
    assert any(p["name"] == "JC" for p in lp["presets"])


def test_streaming_control_is_destructive() -> None:
    t = tools.get_tool("streaming_control")
    assert t is not None and t.destructive is True


def test_healthz(client) -> None:
    r = client.get("/healthz")
    assert r.status_code == 200
    b = r.json()
    assert b["status"] == "ok"
    assert "obs_connected" in b
