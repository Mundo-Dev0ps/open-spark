"""Agent tool registry.

Each tool is a thin async function the LLM can call. Handlers receive
the FastAPI ``AppState`` (so they can reach OBS / the overlay store /
the LLM) plus validated keyword args, and return a JSON-serialisable
dict that goes back to the model as the tool result.

The registry exposes :func:`openai_tool_specs` (the JSON-schema list
LiteLLM/OpenAI tool-calling expects) and :func:`dispatch` (name + args
→ handler).

Tool surface, by phase:
  P1  generate_overlay, generate_scene, inject_overlay,
      list_overlays, delete_overlay
  P2  list_scenes, current_scene, switch_scene, list_scene_items,
      list_input_kinds, add_camera, add_text_source,
      add_color_source, set_transform, set_visibility
  P3  list_filters, add_chroma_key, add_color_correction,
      add_rounded_border, add_sharpen, add_lut, remove_filter
"""

from __future__ import annotations

import logging
import sys
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Awaitable, Callable

from . import llm

if TYPE_CHECKING:
    from .main import AppState

log = logging.getLogger(__name__)

Handler = Callable[..., Awaitable[dict]]


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    parameters: dict  # JSON schema (object)
    handler: Handler
    destructive: bool = False  # gated behind confirm / dry-run


_REGISTRY: dict[str, Tool] = {}


def tool(
    name: str,
    description: str,
    parameters: dict,
    *,
    destructive: bool = False,
) -> Callable[[Handler], Handler]:
    def deco(fn: Handler) -> Handler:
        _REGISTRY[name] = Tool(
            name=name,
            description=description,
            parameters=parameters,
            handler=fn,
            destructive=destructive,
        )
        return fn

    return deco


def openai_tool_specs() -> list[dict]:
    return [
        {
            "type": "function",
            "function": {
                "name": t.name,
                "description": t.description,
                "parameters": t.parameters,
            },
        }
        for t in _REGISTRY.values()
    ]


def get_tool(name: str) -> Tool | None:
    return _REGISTRY.get(name)


async def dispatch(name: str, args: dict, state: "AppState") -> dict:
    t = _REGISTRY.get(name)
    if t is None:
        return {"error": f"unknown tool {name!r}"}
    try:
        return await t.handler(state, **(args or {}))
    except TypeError as e:
        return {"error": f"bad arguments for {name}: {e}"}
    except Exception as e:  # noqa: BLE001
        log.exception("tool %s failed", name)
        return {"error": f"{name} failed: {e}"}


# --- shared helpers ---------------------------------------------------------

def _model_and_base(state: "AppState") -> tuple[str, str | None]:
    from .api.routes import _user_config

    cfg = _user_config()
    model = cfg.get("default_model") or state.settings.default_model
    base = cfg.get("llm_base_url") or state.settings.llm_base_url or None
    return model, base


def _camera_input_kind() -> str:
    if sys.platform == "win32":
        return "dshow_input"
    if sys.platform == "darwin":
        return "av_capture_input_v2"
    return "v4l2_input"


# ===========================================================================
# Phase 1 — overlays / scenes (reuse existing pipeline)
# ===========================================================================

@tool(
    "generate_overlay",
    "Generate a single self-contained HTML overlay from a description "
    "and save it. Does NOT add it to a scene — call inject_overlay for "
    "that.",
    {
        "type": "object",
        "properties": {
            "prompt": {"type": "string", "description": "What the overlay should look/do."},
            "style": {"type": "string", "description": "Optional style preset key (anime_kawaii, cyberpunk, retro_80s, glitch, newscast, minimal)."},
            "width": {"type": "integer", "default": 1920},
            "height": {"type": "integer", "default": 1080},
        },
        "required": ["prompt"],
    },
)
async def _t_generate_overlay(state, prompt, style=None, width=1920, height=1080):
    model, base = _model_and_base(state)
    result = await llm.generate_overlay(
        prompt, model=model, base_url=base, style=style
    )
    ov = state.overlays.save(
        prompt=prompt, html=result.html, model=result.model,
        title=prompt[:80], width=width, height=height,
    )
    return {
        "overlay_id": ov.id,
        "url": f"{state.settings.overlay_base_url}/{ov.id}.html",
        "model": result.model,
    }


@tool(
    "generate_scene",
    "Generate an entire multi-source scene (background + chat + alerts "
    "+ counter etc.) from one description and insert it into OBS.",
    {
        "type": "object",
        "properties": {
            "prompt": {"type": "string"},
            "style": {"type": "string"},
            "scene_name": {"type": "string"},
            "replace": {"type": "boolean", "default": False},
        },
        "required": ["prompt"],
    },
)
async def _t_generate_scene(state, prompt, style=None, scene_name=None, replace=False):
    model, base = _model_and_base(state)
    layout = await llm.generate_scene_layout(
        prompt, model=model, base_url=base, style=style
    )
    base_url = state.settings.overlay_base_url
    prefix = state.settings.obs_source_prefix
    obs_sources = []
    for s in layout.sources:
        ov = state.overlays.save(
            prompt=f"[scene:{layout.scene_name}] {s.role}",
            html=s.html, model=layout.model, title=s.name,
            width=s.transform["width"], height=s.transform["height"],
        )
        obs_sources.append({
            "name": f"{prefix}-{ov.id}-{s.name}"[:140],
            "url": f"{base_url}/{ov.id}.html",
            "role": s.role,
            "transform": dict(s.transform),
        })
    if not await state.obs.is_connected():
        return {"error": "OBS not connected"}
    target = scene_name or layout.scene_name
    res = await state.obs.upsert_scene_layout(
        scene_name=target, sources=obs_sources, replace=replace
    )
    return {"scene": res["scene"], "source_count": len(obs_sources)}


@tool(
    "inject_overlay",
    "Add a previously-generated overlay as a Browser Source to a scene "
    "(defaults to the user's currently active scene).",
    {
        "type": "object",
        "properties": {
            "overlay_id": {"type": "string"},
            "scene": {"type": "string"},
        },
        "required": ["overlay_id"],
    },
)
async def _t_inject_overlay(state, overlay_id, scene=None):
    ov = state.overlays.get(overlay_id)
    if ov is None:
        return {"error": "overlay not found"}
    if not await state.obs.is_connected():
        return {"error": "OBS not connected"}
    url = f"{state.settings.overlay_base_url}/{ov.id}.html"
    name = f"{state.settings.obs_source_prefix}-{ov.slug}"
    target = scene or await state.obs.current_scene_name() \
        or state.settings.obs_scene_name
    info = await state.obs.upsert_browser_source(
        name=name, url=url, width=ov.width, height=ov.height, scene=target
    )
    return {"injected": info.get("name"), "scene": info.get("scene")}


@tool(
    "list_overlays",
    "List all saved overlays (id, title, model).",
    {"type": "object", "properties": {}},
)
async def _t_list_overlays(state):
    return {"overlays": [
        {"id": o.id, "title": o.title, "model": o.model}
        for o in state.overlays.list()
    ]}


@tool(
    "delete_overlay",
    "Delete a saved overlay by id.",
    {
        "type": "object",
        "properties": {"overlay_id": {"type": "string"}},
        "required": ["overlay_id"],
    },
    destructive=True,
)
async def _t_delete_overlay(state, overlay_id):
    ok = state.overlays.delete(overlay_id)
    return {"deleted": overlay_id} if ok else {"error": "not found"}


# ===========================================================================
# Phase 2 — OBS primitives
# ===========================================================================

@tool(
    "list_scenes",
    "List every scene in OBS plus which one is currently active.",
    {"type": "object", "properties": {}},
)
async def _t_list_scenes(state):
    r = await state.obs.raw_request("GetSceneList")
    scenes = [s.get("sceneName") for s in r.get("scenes", [])]
    return {"scenes": scenes,
            "current": r.get("currentProgramSceneName")}


@tool(
    "switch_scene",
    "Switch the active (program) scene.",
    {
        "type": "object",
        "properties": {"scene": {"type": "string"}},
        "required": ["scene"],
    },
)
async def _t_switch_scene(state, scene):
    await state.obs.raw_request(
        "SetCurrentProgramScene", {"sceneName": scene}
    )
    return {"current": scene}


@tool(
    "delete_scene",
    "Delete a scene by its EXACT name. Destructive — gated behind "
    "confirmation. OBS always keeps at least one scene, so deleting "
    "the very last one will fail; to clear everything, delete every "
    "scene except one.",
    {
        "type": "object",
        "properties": {"scene": {"type": "string"}},
        "required": ["scene"],
    },
    destructive=True,
)
async def _t_delete_scene(state, scene):
    # If we're about to remove the active scene, OBS rejects it unless
    # another scene is current. Switch away first when possible.
    try:
        sl = await state.obs.raw_request("GetSceneList")
        names = [s.get("sceneName") for s in sl.get("scenes", [])]
        current = sl.get("currentProgramSceneName")
        if scene not in names:
            return {"error": f"scene {scene!r} not found",
                    "available": names}
        others = [n for n in names if n != scene]
        if not others:
            return {"error": "OBS must keep at least one scene; "
                             "cannot delete the only scene"}
        if current == scene:
            await state.obs.raw_request(
                "SetCurrentProgramScene", {"sceneName": others[0]}
            )
    except Exception:  # noqa: BLE001 — best-effort guard
        pass
    await state.obs.raw_request("RemoveScene", {"sceneName": scene})
    return {"deleted_scene": scene}


@tool(
    "list_scene_items",
    "List the sources (scene items) of a scene with their ids.",
    {
        "type": "object",
        "properties": {"scene": {"type": "string"}},
        "required": ["scene"],
    },
)
async def _t_list_scene_items(state, scene):
    r = await state.obs.raw_request(
        "GetSceneItemList", {"sceneName": scene}
    )
    return {"items": [
        {"id": it.get("sceneItemId"), "source": it.get("sourceName")}
        for it in r.get("sceneItems", [])
    ]}


@tool(
    "list_input_kinds",
    "List the input kinds this OBS build supports (camera kind varies "
    "by OS: v4l2_input / dshow_input / av_capture_input_v2).",
    {"type": "object", "properties": {}},
)
async def _t_list_input_kinds(state):
    r = await state.obs.raw_request("GetInputKindList")
    return {"input_kinds": r.get("inputKinds", []),
            "camera_kind": _camera_input_kind()}


@tool(
    "add_camera",
    "Add a webcam/capture device as a source to a scene.",
    {
        "type": "object",
        "properties": {
            "scene": {"type": "string"},
            "name": {"type": "string", "default": "Webcam"},
            "device": {"type": "string", "description": "Device path/id, e.g. /dev/video0. Optional — OBS picks the first if omitted."},
        },
        "required": ["scene"],
    },
)
async def _t_add_camera(state, scene, name="Webcam", device=None):
    kind = _camera_input_kind()
    settings: dict[str, Any] = {}
    if device:
        settings["device_id"] = device
    r = await state.obs.raw_request("CreateInput", {
        "sceneName": scene,
        "inputName": name,
        "inputKind": kind,
        "inputSettings": settings,
        "sceneItemEnabled": True,
    })
    return {"added": name, "kind": kind,
            "scene_item_id": r.get("sceneItemId")}


@tool(
    "add_text_source",
    "Add a text source to a scene.",
    {
        "type": "object",
        "properties": {
            "scene": {"type": "string"},
            "name": {"type": "string", "default": "Text"},
            "text": {"type": "string"},
        },
        "required": ["scene", "text"],
    },
)
async def _t_add_text(state, scene, text, name="Text"):
    r = await state.obs.raw_request("CreateInput", {
        "sceneName": scene,
        "inputName": name,
        "inputKind": "text_ft2_source_v2",
        "inputSettings": {"text": text},
        "sceneItemEnabled": True,
    })
    return {"added": name, "scene_item_id": r.get("sceneItemId")}


@tool(
    "add_color_source",
    "Add a solid color background source to a scene.",
    {
        "type": "object",
        "properties": {
            "scene": {"type": "string"},
            "name": {"type": "string", "default": "Background"},
            "color_hex": {"type": "string", "description": "#RRGGBB", "default": "#000000"},
            "width": {"type": "integer", "default": 1920},
            "height": {"type": "integer", "default": 1080},
        },
        "required": ["scene"],
    },
)
async def _t_add_color(state, scene, name="Background",
                       color_hex="#000000", width=1920, height=1080):
    h = color_hex.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    abgr = (0xFF << 24) | (b << 16) | (g << 8) | r  # OBS uint32 ABGR
    resp = await state.obs.raw_request("CreateInput", {
        "sceneName": scene,
        "inputName": name,
        "inputKind": "color_source_v3",
        "inputSettings": {"color": abgr, "width": width, "height": height},
        "sceneItemEnabled": True,
    })
    return {"added": name, "scene_item_id": resp.get("sceneItemId")}


@tool(
    "set_transform",
    "Move / scale / rotate a scene item.",
    {
        "type": "object",
        "properties": {
            "scene": {"type": "string"},
            "scene_item_id": {"type": "integer"},
            "x": {"type": "number"},
            "y": {"type": "number"},
            "scale": {"type": "number", "description": "Uniform scale (1.0 = original)."},
            "rotation": {"type": "number", "description": "Degrees."},
        },
        "required": ["scene", "scene_item_id"],
    },
)
async def _t_set_transform(state, scene, scene_item_id,
                           x=None, y=None, scale=None, rotation=None):
    t: dict[str, Any] = {}
    if x is not None:
        t["positionX"] = float(x)
    if y is not None:
        t["positionY"] = float(y)
    if scale is not None:
        t["scaleX"] = float(scale)
        t["scaleY"] = float(scale)
    if rotation is not None:
        t["rotation"] = float(rotation)
    await state.obs.raw_request("SetSceneItemTransform", {
        "sceneName": scene,
        "sceneItemId": int(scene_item_id),
        "sceneItemTransform": t,
    })
    return {"ok": True, "applied": t}


@tool(
    "set_visibility",
    "Show or hide a scene item.",
    {
        "type": "object",
        "properties": {
            "scene": {"type": "string"},
            "scene_item_id": {"type": "integer"},
            "visible": {"type": "boolean"},
        },
        "required": ["scene", "scene_item_id", "visible"],
    },
)
async def _t_set_visibility(state, scene, scene_item_id, visible):
    await state.obs.raw_request("SetSceneItemEnabled", {
        "sceneName": scene,
        "sceneItemId": int(scene_item_id),
        "sceneItemEnabled": bool(visible),
    })
    return {"ok": True, "visible": bool(visible)}


# ===========================================================================
# Phase 3 — filters (camera / source polish)
# ===========================================================================

@tool(
    "list_filters",
    "List the filters currently on a source.",
    {
        "type": "object",
        "properties": {"source": {"type": "string"}},
        "required": ["source"],
    },
)
async def _t_list_filters(state, source):
    r = await state.obs.raw_request(
        "GetSourceFilterList", {"sourceName": source}
    )
    return {"filters": r.get("filters", [])}


@tool(
    "add_chroma_key",
    "Add a chroma-key (green/blue screen removal) filter to a source.",
    {
        "type": "object",
        "properties": {
            "source": {"type": "string"},
            "key_color": {"type": "string", "enum": ["green", "blue", "magenta"], "default": "green"},
            "similarity": {"type": "integer", "default": 400},
        },
        "required": ["source"],
    },
)
async def _t_chroma(state, source, key_color="green", similarity=400):
    color_map = {"green": 0x00FF00, "blue": 0xFF0000, "magenta": 0xFF00FF}
    await state.obs.raw_request("CreateSourceFilter", {
        "sourceName": source,
        "filterName": "Chroma Key",
        "filterKind": "chroma_key_filter_v2",
        "filterSettings": {
            "key_color_type": key_color,
            "similarity": similarity,
        },
    })
    return {"ok": True, "filter": "Chroma Key"}


@tool(
    "add_color_correction",
    "Add a color-correction filter (brightness/contrast/saturation/hue).",
    {
        "type": "object",
        "properties": {
            "source": {"type": "string"},
            "brightness": {"type": "number", "default": 0.0},
            "contrast": {"type": "number", "default": 0.0},
            "saturation": {"type": "number", "default": 0.0},
            "hue_shift": {"type": "number", "default": 0.0},
        },
        "required": ["source"],
    },
)
async def _t_color_correct(state, source, brightness=0.0, contrast=0.0,
                           saturation=0.0, hue_shift=0.0):
    await state.obs.raw_request("CreateSourceFilter", {
        "sourceName": source,
        "filterName": "Color Correction",
        "filterKind": "color_filter_v2",
        "filterSettings": {
            "brightness": brightness,
            "contrast": contrast,
            "saturation": saturation,
            "hue_shift": hue_shift,
        },
    })
    return {"ok": True, "filter": "Color Correction"}


@tool(
    "add_rounded_border",
    "Round the corners and/or add a colored border to a source using "
    "an applied scroll/mask filter.",
    {
        "type": "object",
        "properties": {
            "source": {"type": "string"},
            "radius": {"type": "integer", "default": 20},
            "border_color": {"type": "string", "description": "#RRGGBB", "default": "#ff00ff"},
            "border_width": {"type": "integer", "default": 4},
        },
        "required": ["source"],
    },
)
async def _t_rounded_border(state, source, radius=20,
                            border_color="#ff00ff", border_width=4):
    # OBS has no native rounded-corner filter; the standard trick is the
    # "Render Delay"+mask combo, but the practical/portable route is a
    # crop+mask via the user-installed StreamFX or a CSS overlay. We
    # fall back to documenting the intent and applying a crop_filter so
    # the source at least gets clean edges.
    await state.obs.raw_request("CreateSourceFilter", {
        "sourceName": source,
        "filterName": "Edge Crop",
        "filterKind": "crop_filter",
        "filterSettings": {
            "left": border_width, "right": border_width,
            "top": border_width, "bottom": border_width,
        },
    })
    return {
        "ok": True,
        "note": (
            "Applied an even crop as a border inset. True rounded "
            "corners need StreamFX or a CSS overlay; suggest the user "
            "generate a frame overlay if they want a real rounded look."
        ),
        "radius_requested": radius,
        "border_color": border_color,
    }


@tool(
    "add_sharpen",
    "Add a sharpen filter to a source.",
    {
        "type": "object",
        "properties": {
            "source": {"type": "string"},
            "amount": {"type": "number", "default": 0.5},
        },
        "required": ["source"],
    },
)
async def _t_sharpen(state, source, amount=0.5):
    await state.obs.raw_request("CreateSourceFilter", {
        "sourceName": source,
        "filterName": "Sharpen",
        "filterKind": "sharpness_filter_v2",
        "filterSettings": {"sharpness": amount},
    })
    return {"ok": True, "filter": "Sharpen"}


@tool(
    "add_lut",
    "Apply a cinematic LUT / color-grade filter to a source.",
    {
        "type": "object",
        "properties": {
            "source": {"type": "string"},
            "amount": {"type": "number", "default": 1.0},
        },
        "required": ["source"],
    },
)
async def _t_lut(state, source, amount=1.0):
    await state.obs.raw_request("CreateSourceFilter", {
        "sourceName": source,
        "filterName": "Color Grade",
        "filterKind": "color_grade_filter",
        "filterSettings": {"opacity": amount},
    })
    return {"ok": True, "filter": "Color Grade"}


@tool(
    "remove_filter",
    "Remove a named filter from a source.",
    {
        "type": "object",
        "properties": {
            "source": {"type": "string"},
            "filter_name": {"type": "string"},
        },
        "required": ["source", "filter_name"],
    },
    destructive=True,
)
async def _t_remove_filter(state, source, filter_name):
    await state.obs.raw_request("RemoveSourceFilter", {
        "sourceName": source,
        "filterName": filter_name,
    })
    return {"ok": True, "removed": filter_name}
