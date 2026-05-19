"""HTTP routes. All routers attached here."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse

from .. import __version__, agent, llm, secrets_store
from ..config import USER_CONFIG_PATH
from .schemas import (
    AgentChatRequest,
    AgentChatResponse,
    AgentToolCall,
    GenerateRequest,
    GenerateResponse,
    InjectRequest,
    InjectResponse,
    RefineOverlayRequest,
    RefineOverlayResponse,
    RegenerateOverlayRequest,
    RegenerateOverlayResponse,
    SceneSourceInfo,
    SceneTemplateRequest,
    SceneTemplateResponse,
    SceneTransform,
    SecretPayload,
    SettingsPayload,
    StatusResponse,
)

if TYPE_CHECKING:
    from ..main import AppState

log = logging.getLogger(__name__)

router = APIRouter()


def _state(request: Request) -> "AppState":
    return request.app.state.spark


def _user_config() -> dict:
    if USER_CONFIG_PATH.exists():
        try:
            return json.loads(USER_CONFIG_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
    return {}


def _save_user_config(data: dict) -> None:
    USER_CONFIG_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")


@router.get("/healthz")
async def healthz(request: Request) -> dict:
    """Liveness/readiness probe. Never raises; reports component state
    so a supervisor / compose healthcheck can act on it."""
    state = _state(request)
    obs_ok = False
    try:
        obs_ok = await state.obs.is_connected()
    except Exception:  # noqa: BLE001
        obs_ok = False
    return {
        "status": "ok",
        "version": __version__,
        "obs_connected": obs_ok,
        "mock_obs": state.settings.mock_obs,
    }


@router.get("/api/status", response_model=StatusResponse)
async def status(request: Request) -> StatusResponse:
    state = _state(request)
    settings = state.settings
    user_cfg = _user_config()
    model = user_cfg.get("default_model", settings.default_model)
    provider = model.split("/", 1)[0] if "/" in model else model

    return StatusResponse(
        obs_connected=await state.obs.is_connected(),
        mock_obs=settings.mock_obs,
        default_model=model,
        has_default_llm_key=secrets_store.has_llm_api_key(provider),
        overlay_count=len(state.overlays.list()),
        version=__version__,
    )


@router.post("/api/generate", response_model=GenerateResponse)
async def generate(request: Request, payload: GenerateRequest) -> GenerateResponse:
    state = _state(request)
    user_cfg = _user_config()
    model = payload.model or user_cfg.get("default_model") or state.settings.default_model
    base_url = user_cfg.get("llm_base_url") or state.settings.llm_base_url or None
    passes = int(
        user_cfg.get(
            "overlay_quality_passes", state.settings.overlay_quality_passes
        )
    )

    try:
        result = await llm.generate_overlay(
            payload.prompt, model=model, base_url=base_url,
            style=payload.style, quality_passes=passes,
        )
    except Exception as e:
        log.exception("LLM call failed")
        raise HTTPException(status_code=502, detail=f"LLM error: {e}") from e

    overlay = state.overlays.save(
        prompt=payload.prompt,
        html=result.html,
        model=result.model,
        title=payload.title or "",
        width=payload.width,
        height=payload.height,
    )
    url = f"{state.settings.overlay_base_url}/{overlay.id}.html"
    return GenerateResponse(
        overlay_id=overlay.id,
        html=result.html,
        model=result.model,
        url=url,
        title=overlay.title,
        usage=result.usage,
    )


@router.post("/api/inject", response_model=InjectResponse)
async def inject(request: Request, payload: InjectRequest) -> InjectResponse:
    state = _state(request)
    overlay = state.overlays.get(payload.overlay_id)
    if overlay is None:
        raise HTTPException(status_code=404, detail="overlay not found")

    url = f"{state.settings.overlay_base_url}/{overlay.id}.html"
    name = payload.source_name or f"{state.settings.obs_source_prefix}-{overlay.slug}"

    if not await state.obs.is_connected():
        raise HTTPException(status_code=503, detail="OBS not connected")

    # Resolution order for the target scene:
    #   1. explicit payload.scene (the caller knows best)
    #   2. user_config override (set via Settings tab)
    #   3. the user's CURRENTLY ACTIVE scene in OBS — so inject lands
    #      on the scene the user is actually looking at
    #   4. settings.obs_scene_name fallback ("Open Spark")
    user_cfg = _user_config()
    scene = (
        payload.scene
        or user_cfg.get("obs_scene_name")
        or await state.obs.current_scene_name()
        or state.settings.obs_scene_name
    )

    try:
        info = await state.obs.upsert_browser_source(
            name=name, url=url, width=overlay.width, height=overlay.height, scene=scene
        )
    except Exception as e:
        log.exception("OBS injection failed")
        raise HTTPException(status_code=502, detail=f"OBS error: {e}") from e

    return InjectResponse(
        name=info["name"],
        url=info["url"],
        scene=info["scene"],
        action=info.get("action"),
        mock=info.get("mock", False),
    )


@router.post("/api/scenes/templates", response_model=SceneTemplateResponse)
async def scene_template(
    request: Request, payload: SceneTemplateRequest
) -> SceneTemplateResponse:
    """Generate a multi-source OBS scene from one prompt.

    Pipeline: LLM → JSON layout → save each HTML as overlay → OBS scene
    with positioned Browser Sources.
    """
    state = _state(request)
    user_cfg = _user_config()
    model = payload.model or user_cfg.get("default_model") or state.settings.default_model
    base_url = user_cfg.get("llm_base_url") or state.settings.llm_base_url or None

    try:
        layout = await llm.generate_scene_layout(
            payload.prompt,
            model=model,
            base_url=base_url,
            canvas_width=payload.canvas_width,
            canvas_height=payload.canvas_height,
            style=payload.style,
        )
    except ValueError as e:
        log.warning("scene layout parse failed: %s", e)
        raise HTTPException(status_code=502, detail=f"LLM layout parse failed: {e}") from e
    except Exception as e:
        log.exception("LLM scene call failed")
        raise HTTPException(status_code=502, detail=f"LLM error: {e}") from e

    # Save each source's HTML as an overlay so the backend can serve it.
    saved: list[tuple[str, llm.SceneSourceLayout, str]] = []
    base = state.settings.overlay_base_url
    for s in layout.sources:
        overlay = state.overlays.save(
            prompt=f"[scene:{layout.scene_name}] role={s.role} :: {payload.prompt}",
            html=s.html,
            model=layout.model,
            title=s.name,
            width=s.transform["width"],
            height=s.transform["height"],
        )
        url = f"{base}/{overlay.id}.html"
        saved.append((overlay.id, s, url))

    if not await state.obs.is_connected():
        raise HTTPException(status_code=503, detail="OBS not connected")

    scene_name = payload.scene_name or layout.scene_name
    prefix = state.settings.obs_source_prefix

    obs_sources = [
        {
            "name": f"{prefix}-{overlay_id}-{s.name}"[:140],
            "url": url,
            "role": s.role,
            "transform": dict(s.transform),
        }
        for overlay_id, s, url in saved
    ]

    try:
        result = await state.obs.upsert_scene_layout(
            scene_name=scene_name, sources=obs_sources, replace=payload.replace
        )
    except Exception as e:
        log.exception("OBS scene layout failed")
        raise HTTPException(status_code=502, detail=f"OBS error: {e}") from e

    sources_info = [
        SceneSourceInfo(
            overlay_id=overlay_id,
            name=obs_sources[i]["name"],
            role=s.role,
            url=url,
            transform=SceneTransform(**s.transform),
        )
        for i, (overlay_id, s, url) in enumerate(saved)
    ]

    return SceneTemplateResponse(
        scene=result["scene"],
        model=layout.model,
        sources=sources_info,
        usage=layout.usage,
        mock=result.get("mock", False),
    )


@router.post(
    "/api/overlays/{overlay_id}/regenerate",
    response_model=RegenerateOverlayResponse,
)
async def regenerate_overlay(
    request: Request, overlay_id: str, payload: RegenerateOverlayRequest
) -> RegenerateOverlayResponse:
    """Re-run the LLM and overwrite an existing overlay's HTML in place.

    The overlay URL stays the same, so any OBS Browser Source pointing
    at it picks up the new content on a Refresh (or via reinject).
    """
    state = _state(request)
    overlay = state.overlays.get(overlay_id)
    if overlay is None:
        raise HTTPException(status_code=404, detail="overlay not found")

    user_cfg = _user_config()
    model = payload.model or user_cfg.get("default_model") or state.settings.default_model
    base_url = user_cfg.get("llm_base_url") or state.settings.llm_base_url or None
    prompt = payload.prompt or overlay.prompt

    try:
        result = await llm.generate_overlay(
            prompt, model=model, base_url=base_url, style=payload.style
        )
    except Exception as e:
        log.exception("LLM regenerate failed")
        raise HTTPException(status_code=502, detail=f"LLM error: {e}") from e

    updated = state.overlays.update_html(
        overlay_id, html=result.html, model=result.model, prompt=prompt
    )
    if updated is None:
        # Race: deleted between get() and update.
        raise HTTPException(status_code=404, detail="overlay vanished mid-regenerate")

    url = f"{state.settings.overlay_base_url}/{overlay_id}.html"

    # Best-effort: nudge OBS to reload any Browser Source currently using
    # this overlay. We bump the URL with a cache-busting timestamp; if no
    # matching source exists, this is a no-op.
    obs_action: str | None = None
    if await state.obs.is_connected():
        try:
            from time import time as _now

            bust_url = f"{url}?t={int(_now())}"
            # We only know the prefix used for single-shot inject and the
            # prefix used for scene_template inject. Try the standard one.
            standard_name = f"{state.settings.obs_source_prefix}-{updated.slug}"
            await state.obs.upsert_browser_source(
                name=standard_name,
                url=bust_url,
                width=updated.width,
                height=updated.height,
            )
            obs_action = "refreshed"
        except Exception as e:
            log.warning("OBS refresh after regenerate failed: %s", e)

    return RegenerateOverlayResponse(
        overlay_id=overlay_id,
        url=url,
        model=result.model,
        title=updated.title,
        obs_action=obs_action,
    )


@router.post(
    "/api/overlays/{overlay_id}/refine",
    response_model=RefineOverlayResponse,
)
async def refine_overlay(
    request: Request, overlay_id: str, payload: RefineOverlayRequest
) -> RefineOverlayResponse:
    """Iterative-edit an existing overlay.

    The user submits an instruction (e.g. "make the chat box smaller and
    push it down 80px"). Backend loads the current HTML, asks the LLM
    to patch it, then overwrites the file in place — overlay id and
    URL stay stable so the OBS Browser Source picks up the change on
    a cache-bust refresh.
    """
    state = _state(request)
    overlay = state.overlays.get(overlay_id)
    if overlay is None:
        raise HTTPException(status_code=404, detail="overlay not found")

    html_path = state.overlays.html_path(overlay_id)
    if html_path is None or not html_path.exists():
        raise HTTPException(
            status_code=404, detail="overlay html file missing")
    existing_html = html_path.read_text(encoding="utf-8")

    user_cfg = _user_config()
    model = payload.model or user_cfg.get("default_model") or state.settings.default_model
    base_url = user_cfg.get("llm_base_url") or state.settings.llm_base_url or None

    try:
        result = await llm.refine_overlay(
            existing_html=existing_html,
            instruction=payload.instruction,
            model=model,
            base_url=base_url,
            style=payload.style,
        )
    except Exception as e:
        log.exception("LLM refine failed")
        raise HTTPException(status_code=502, detail=f"LLM error: {e}") from e

    updated = state.overlays.update_html(
        overlay_id, html=result.html, model=result.model
    )
    if updated is None:
        raise HTTPException(status_code=404, detail="overlay vanished mid-refine")

    url = f"{state.settings.overlay_base_url}/{overlay_id}.html"

    obs_action: str | None = None
    if await state.obs.is_connected():
        try:
            from time import time as _now

            bust_url = f"{url}?t={int(_now())}"
            standard_name = f"{state.settings.obs_source_prefix}-{updated.slug}"
            await state.obs.upsert_browser_source(
                name=standard_name,
                url=bust_url,
                width=updated.width,
                height=updated.height,
            )
            obs_action = "refreshed"
        except Exception as e:
            log.warning("OBS refresh after refine failed: %s", e)

    return RefineOverlayResponse(
        overlay_id=overlay_id,
        url=url,
        model=result.model,
        title=updated.title,
        obs_action=obs_action,
    )


@router.post("/api/agent/chat", response_model=AgentChatResponse)
async def agent_chat(
    request: Request, payload: AgentChatRequest
) -> AgentChatResponse:
    """Conversational agent: chat in, OBS actions out.

    The LLM is given the full tool registry (overlays, scenes, camera,
    transforms, filters, …) and drives a tool-calling loop against the
    live OBS session. ``dry_run`` makes destructive tools report instead
    of execute so the UI can confirm first.
    """
    state = _state(request)
    user_cfg = _user_config()
    # Agent prefers a dedicated tool-calling model: explicit request →
    # user agent_model → settings.agent_model → default_model chain.
    model = (
        payload.model
        or user_cfg.get("agent_model")
        or state.settings.agent_model
        or user_cfg.get("default_model")
        or state.settings.default_model
    )
    base_url = user_cfg.get("llm_base_url") or state.settings.llm_base_url or None

    supported, reason = agent.tool_support(model)
    if supported is False:
        raise HTTPException(
            status_code=400,
            detail={
                "error": f"model {model!r} does not support tool calling "
                f"({reason}). The agent needs a tool-calling model.",
                "suggestions": agent.SUGGESTED_TOOL_MODELS,
            },
        )

    try:
        res = await agent.run_agent(
            user_messages=[m.model_dump() for m in payload.messages],
            state=state,
            model=model,
            base_url=base_url,
            max_steps=payload.max_steps,
            dry_run=payload.dry_run,
        )
    except Exception as e:
        log.exception("agent loop failed")
        raise HTTPException(status_code=502, detail=f"agent error: {e}") from e

    _persist_agent_session(res)

    return AgentChatResponse(
        final_message=res.final_message,
        steps=[
            AgentToolCall(
                tool=s.tool, args=s.args, result=s.result, executed=s.executed
            )
            for s in res.steps
        ],
        pending_confirmation=res.pending_confirmation,
        created_inputs=res.created_inputs,
        model=res.model,
        usage=res.usage,
    )


def _agent_session_path():
    from ..config import app_data_dir

    return app_data_dir() / "agent_last_session.json"


def _persist_agent_session(res) -> None:
    """Save the last agent transcript + created inputs so the dock can
    resume the conversation and offer an undo after a restart."""
    try:
        payload = {
            "messages": [
                m for m in res.messages if m.get("role") in ("user", "assistant")
            ],
            "created_inputs": res.created_inputs,
            "final_message": res.final_message,
        }
        p = _agent_session_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    except Exception as e:  # noqa: BLE001
        log.warning("could not persist agent session: %s", e)


@router.get("/api/agent/session")
async def agent_session() -> dict:
    """Return the last persisted agent transcript (for dock resume)."""
    p = _agent_session_path()
    if not p.exists():
        return {"messages": [], "created_inputs": []}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"messages": [], "created_inputs": []}


@router.delete("/api/agent/session")
async def agent_session_clear() -> dict:
    """Wipe the persisted transcript so the next chat starts fresh —
    avoids an old goal contaminating a new conversation."""
    p = _agent_session_path()
    try:
        p.unlink(missing_ok=True)
    except OSError:
        pass
    return {"cleared": True}


@router.post("/api/agent/undo")
async def agent_undo(request: Request, payload: dict) -> dict:
    """Remove inputs the agent created (whole turn undo).

    ``inputs`` in the body overrides; otherwise the last persisted
    session's created_inputs are removed via RemoveInput.
    """
    state = _state(request)
    inputs = payload.get("inputs") or []
    if not inputs:
        sess = await agent_session()
        inputs = sess.get("created_inputs", [])
    if not await state.obs.is_connected():
        raise HTTPException(status_code=503, detail="OBS not connected")

    removed: list[str] = []
    errors: list[str] = []
    for name in inputs:
        try:
            await state.obs.raw_request("RemoveInput", {"inputName": name})
            removed.append(name)
        except Exception as e:  # noqa: BLE001
            errors.append(f"{name}: {e}")
    return {"removed": removed, "errors": errors}


@router.post("/api/agent/chat/stream")
async def agent_chat_stream(request: Request, payload: AgentChatRequest):
    """Server-Sent Events variant of /api/agent/chat.

    Emits one ``event: step`` per tool call as it completes and a final
    ``event: final`` with the summary, so the dock can render tool
    cards live instead of staring at a spinner for the whole loop.
    """
    state = _state(request)
    user_cfg = _user_config()
    model = (
        payload.model
        or user_cfg.get("agent_model")
        or state.settings.agent_model
        or user_cfg.get("default_model")
        or state.settings.default_model
    )
    base_url = user_cfg.get("llm_base_url") or state.settings.llm_base_url or None

    supported, reason = agent.tool_support(model)
    if supported is False:
        raise HTTPException(
            status_code=400,
            detail={
                "error": f"model {model!r} does not support tool calling "
                f"({reason}).",
                "suggestions": agent.SUGGESTED_TOOL_MODELS,
            },
        )

    async def event_stream():
        try:
            async for ev in agent.stream_agent(
                user_messages=[m.model_dump() for m in payload.messages],
                state=state,
                model=model,
                base_url=base_url,
                max_steps=payload.max_steps,
                dry_run=payload.dry_run,
            ):
                if ev["type"] == "step":
                    yield (
                        "event: step\ndata: "
                        + json.dumps(ev["step"], default=str)
                        + "\n\n"
                    )
                else:
                    res = ev["result"]
                    _persist_agent_session(res)
                    final = {
                        "final_message": res.final_message,
                        "pending_confirmation": res.pending_confirmation,
                        "created_inputs": res.created_inputs,
                        "model": res.model,
                        "usage": res.usage,
                    }
                    yield (
                        "event: final\ndata: "
                        + json.dumps(final, default=str)
                        + "\n\n"
                    )
        except Exception as e:  # noqa: BLE001
            log.exception("agent stream failed")
            yield (
                "event: error\ndata: "
                + json.dumps({"error": str(e)})
                + "\n\n"
            )

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/api/agent/model-check")
async def agent_model_check(model: str) -> dict:
    """Validate a model id for tool calling before the user saves it.

    Returns {supported: true|false|null, reason, suggestions}. The
    plugin Settings tab calls this to show an inline green/red badge.
    """
    supported, reason = agent.tool_support(model)
    return {
        "model": model,
        "supported": supported,  # JSON: true / false / null
        "reason": reason,
        "suggestions": agent.SUGGESTED_TOOL_MODELS,
    }


@router.get("/api/agent/tools")
async def agent_tools() -> dict:
    """Expose the tool catalogue (names + descriptions) for the UI."""
    from .. import tools as _tools

    return {
        "tools": [
            {
                "name": t.name,
                "description": t.description,
                "destructive": t.destructive,
            }
            for t in _tools._REGISTRY.values()
        ]
    }


@router.get("/api/styles")
async def list_styles() -> list[dict]:
    """Available style preset keys for the UI dropdown."""
    return [{"key": k, "summary": v[:120]} for k, v in llm.STYLE_PREAMBLES.items()]


@router.get("/api/overlays")
async def list_overlays(request: Request) -> list[dict]:
    state = _state(request)
    base = state.settings.overlay_base_url
    return [
        {
            "id": o.id,
            "title": o.title,
            "slug": o.slug,
            "model": o.model,
            "created_at": o.created_at,
            "url": f"{base}/{o.id}.html",
        }
        for o in state.overlays.list()
    ]


@router.delete("/api/overlays/{overlay_id}")
async def delete_overlay(request: Request, overlay_id: str) -> dict:
    state = _state(request)
    if not state.overlays.delete(overlay_id):
        raise HTTPException(status_code=404, detail="overlay not found")
    return {"deleted": overlay_id}


@router.delete("/api/overlays")
async def delete_all_overlays(request: Request) -> dict:
    """Wipe every saved overlay. Files + index. Idempotent."""
    state = _state(request)
    count = state.overlays.clear()
    return {"deleted_count": count}


@router.get("/overlays/{overlay_id}.html")
async def serve_overlay(request: Request, overlay_id: str) -> FileResponse:
    state = _state(request)
    path = state.overlays.html_path(overlay_id)
    if path is None or not path.exists():
        raise HTTPException(status_code=404, detail="overlay not found")
    return FileResponse(path, media_type="text/html; charset=utf-8")


@router.get("/api/settings")
async def get_settings(request: Request) -> dict:
    state = _state(request)
    user_cfg = _user_config()
    return {
        "default_model": user_cfg.get("default_model", state.settings.default_model),
        "agent_model": user_cfg.get("agent_model", state.settings.agent_model),
        "overlay_quality_passes": user_cfg.get(
            "overlay_quality_passes", state.settings.overlay_quality_passes
        ),
        "llm_base_url": user_cfg.get("llm_base_url", state.settings.llm_base_url),
        "obs_host": user_cfg.get("obs_host", state.settings.obs_host),
        "obs_port": user_cfg.get("obs_port", state.settings.obs_port),
        "obs_scene_name": user_cfg.get("obs_scene_name", state.settings.obs_scene_name),
        "providers_with_key": [
            p
            for p in (
                "anthropic",
                "openai",
                "gemini",
                "groq",
                "mistral",
                "cohere",
                "deepseek",
                "ollama",
            )
            if secrets_store.has_llm_api_key(p)
        ],
    }


@router.put("/api/settings")
async def update_settings(payload: SettingsPayload) -> dict:
    cfg = _user_config()
    for key, value in payload.model_dump(exclude_none=True).items():
        cfg[key] = value
    _save_user_config(cfg)
    return {"saved": True, "settings": cfg}


@router.post("/api/secrets")
async def set_secret(payload: SecretPayload) -> dict:
    if payload.kind == "llm":
        if not payload.provider:
            raise HTTPException(status_code=422, detail="provider required for llm secrets")
        secrets_store.set_llm_api_key(payload.provider, payload.value)
        return {"saved": True, "kind": "llm", "provider": payload.provider}
    if payload.kind == "obs":
        secrets_store.set_obs_password(payload.value)
        return {"saved": True, "kind": "obs"}
    raise HTTPException(status_code=422, detail=f"unknown secret kind: {payload.kind}")


@router.delete("/api/secrets/llm/{provider}")
async def delete_llm_secret(provider: str) -> dict:
    secrets_store.delete_llm_api_key(provider)
    return {"deleted": provider}
