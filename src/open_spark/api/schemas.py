"""Request/response models. Pydantic v2."""

from __future__ import annotations

from pydantic import BaseModel, Field


class GenerateRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=4000)
    model: str | None = None
    title: str | None = None
    width: int = 1920
    height: int = 1080
    style: str | None = None  # optional preset key, see llm.STYLE_PREAMBLES


class GenerateResponse(BaseModel):
    overlay_id: str
    html: str
    model: str
    url: str
    title: str
    usage: dict


class InjectRequest(BaseModel):
    overlay_id: str
    scene: str | None = None
    source_name: str | None = None


class InjectResponse(BaseModel):
    name: str
    url: str
    scene: str
    action: str | None = None
    mock: bool


class SettingsPayload(BaseModel):
    """Editable runtime settings. Secrets handled separately."""

    default_model: str | None = None
    llm_base_url: str | None = None
    obs_host: str | None = None
    obs_port: int | None = None
    obs_scene_name: str | None = None


class SecretPayload(BaseModel):
    kind: str  # "llm" | "obs"
    provider: str | None = None  # required when kind == "llm"
    value: str = Field(min_length=1)


class StatusResponse(BaseModel):
    obs_connected: bool
    mock_obs: bool
    default_model: str
    has_default_llm_key: bool
    overlay_count: int
    version: str


# --- Agent ------------------------------------------------------------------

class AgentMessage(BaseModel):
    role: str  # "user" | "assistant"
    content: str


class AgentChatRequest(BaseModel):
    messages: list[AgentMessage] = Field(min_length=1)
    model: str | None = None
    dry_run: bool = False
    max_steps: int = Field(default=14, ge=1, le=24)


class AgentToolCall(BaseModel):
    tool: str
    args: dict
    result: dict
    executed: bool


class AgentChatResponse(BaseModel):
    final_message: str
    steps: list[AgentToolCall]
    pending_confirmation: list[dict]
    model: str
    usage: dict


# --- Scene templates ---------------------------------------------------------

class SceneTransform(BaseModel):
    x: int = 0
    y: int = 0
    width: int = 1920
    height: int = 1080


class SceneTemplateRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=4000)
    model: str | None = None
    scene_name: str | None = None
    canvas_width: int = 1920
    canvas_height: int = 1080
    replace: bool = False  # if True, clear existing scene items before adding
    style: str | None = None  # optional preset key, see llm.STYLE_PREAMBLES


class RegenerateOverlayRequest(BaseModel):
    prompt: str | None = None  # if omitted, reuses the original overlay prompt
    style: str | None = None
    model: str | None = None


class RegenerateOverlayResponse(BaseModel):
    overlay_id: str
    url: str
    model: str
    title: str
    obs_action: str | None = None  # "refreshed" if a Browser Source was bumped


class RefineOverlayRequest(BaseModel):
    """Iterative-edit payload.

    The user describes a *delta* ("make the background darker, add
    scanlines"). Backend feeds the LLM the existing HTML plus the delta
    and asks for a patched version. The overlay id + URL stay the same
    so the OBS Browser Source can pick up the new content with a
    cache-bust refresh.
    """
    instruction: str = Field(min_length=1, max_length=2000)
    style: str | None = None
    model: str | None = None


class RefineOverlayResponse(BaseModel):
    overlay_id: str
    url: str
    model: str
    title: str
    obs_action: str | None = None


class SceneSourceInfo(BaseModel):
    overlay_id: str
    name: str
    role: str
    url: str
    transform: SceneTransform


class SceneTemplateResponse(BaseModel):
    scene: str
    model: str
    sources: list[SceneSourceInfo]
    usage: dict
    mock: bool
