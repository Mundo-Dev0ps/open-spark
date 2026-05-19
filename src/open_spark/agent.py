"""Conversational agent loop.

The agent takes a chat transcript, hands the LLM the tool registry from
:mod:`open_spark.tools`, executes whatever tool calls the model emits
against OBS / the overlay store, feeds the results back, and repeats
until the model answers without calling a tool (or the step budget runs
out).

Safety:
* ``dry_run`` — destructive tools are NOT executed; the agent reports
  what it *would* do so the UI can ask the user to confirm.
* a hard ``max_steps`` cap stops runaway tool loops.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from . import tools

if TYPE_CHECKING:
    from .main import AppState

log = logging.getLogger(__name__)

SYSTEM_PROMPT_AGENT = """\
You are Open Spark, an assistant embedded inside OBS Studio. You help
the streamer build and tune their scene by calling tools.

Language:
* ALWAYS reply in the SAME language the user wrote their last message
  in (Spanish in → Spanish out, English in → English out). Match it.

Efficiency & correctness:
* Prefer doing over describing. If a tool exists for the request,
  call it.
* Call list_scenes ONCE at the very start if you need real scene
  names. NEVER invent a scene name like "main scene" — use the exact
  names list_scenes returns, or the user's current scene.
* Do NOT call the same tool twice with different guessed arguments to
  "try again". Inspect first, then act once with the right values.
* Reuse the source name you created (e.g. "Webcam") when applying
  filters to it — don't recreate it.
* Plan the whole request, then execute the minimum tool calls needed.
  Typical multi-part request = 1 list_scenes + one tool per element.
* Overlays are HTML Browser Sources (generate_overlay → inject_overlay
  with the SAME scene); camera/text/color/filters are native OBS.
* Be concise in your final message — a sentence or two, in the user's
  language, summarising what you did.
* Never invent tool names. Only call tools that exist.

Error recovery:
* If a tool result contains an "error" field, READ it. Fix the
  arguments (e.g. wrong scene name → call list_scenes, then retry with
  the correct one) and try again — do not just report failure to the
  user. Only surface an error to the user if you genuinely cannot
  recover after one corrective attempt.
"""

# Tool results fed back to the model are capped so a giant list/HTML
# payload doesn't blow the context window or token budget.
_MAX_TOOL_RESULT_CHARS = 1500


def _trim_result(payload: dict) -> str:
    s = json.dumps(payload, default=str)
    if len(s) <= _MAX_TOOL_RESULT_CHARS:
        return s
    extra = len(s) - _MAX_TOOL_RESULT_CHARS
    return s[:_MAX_TOOL_RESULT_CHARS] + "… (+" + str(extra) + " chars truncated)"


# Tool → key in its result dict that names a created OBS input, so a
# turn's additions can be undone by RemoveInput.
_CREATES_INPUT = {
    "add_camera": "added",
    "add_text_source": "added",
    "add_color_source": "added",
    "inject_overlay": "injected",
}


@dataclass
class AgentStep:
    tool: str
    args: dict
    result: dict
    executed: bool  # False when skipped due to dry_run


@dataclass
class AgentResult:
    final_message: str
    steps: list[AgentStep] = field(default_factory=list)
    messages: list[dict] = field(default_factory=list)  # full transcript
    pending_confirmation: list[dict] = field(default_factory=list)
    created_inputs: list[str] = field(default_factory=list)  # for undo
    model: str = ""
    usage: dict = field(default_factory=dict)


# Curated fallback when LiteLLM has no metadata for a model. Substring
# match against the model id (provider/name). These families reliably
# support OpenAI-style tool calling.
_TOOL_OK_SUBSTRINGS = (
    "anthropic/claude",
    "openai/gpt-4", "openai/gpt-5", "openai/o1", "openai/o3", "openai/o4",
    "gemini/gemini-1.5", "gemini/gemini-2",
    "groq/llama-3.3", "groq/llama-3.1", "groq/qwen",
    "deepseek/deepseek-chat", "deepseek/deepseek-v3",
    "mistral/mistral-large", "mistral/mistral-small",
    "cohere/command-r",
    # NVIDIA NIM models that expose tool calling
    "nvidia_nim/meta/llama-3.3", "nvidia_nim/meta/llama-3.1-405",
    "nvidia_nim/meta/llama-3.1-70", "nvidia_nim/qwen/qwen2.5-72",
    "nvidia_nim/qwen/qwen2.5-coder-32",
    "nvidia_nim/mistralai/mistral-large",
    "nvidia_nim/nvidia/llama-3.1-nemotron-70",
    # OpenRouter passthrough (provider/model after the openrouter/ prefix)
    "openrouter/anthropic/claude", "openrouter/openai/gpt-4",
    "openrouter/meta-llama/llama-3.3", "openrouter/qwen/qwen-2.5-72",
    "openrouter/qwen/qwen-2.5-coder-32",
)

# Shown to the user when their pick is rejected.
SUGGESTED_TOOL_MODELS = [
    "nvidia_nim/meta/llama-3.3-70b-instruct",
    "nvidia_nim/qwen/qwen2.5-coder-32b-instruct",
    "openrouter/qwen/qwen-2.5-coder-32b-instruct:free",
    "anthropic/claude-sonnet-4-6",
    "openai/gpt-4o",
]


def tool_support(model: str) -> tuple[bool | None, str]:
    """Return (supported, reason).

    True  — known to support tool calling
    False — known NOT to (reject before wasting an LLM call)
    None  — unknown; allow but caller may warn
    """
    if not model:
        return False, "no model set"
    m = model.strip().lower()

    # 1. LiteLLM's own metadata is authoritative when present.
    try:
        import litellm

        if litellm.supports_function_calling(model=model):
            return True, "litellm: supports function calling"
    except Exception:  # noqa: BLE001 — unknown model / no metadata
        pass

    # 2. Curated substring allowlist.
    for s in _TOOL_OK_SUBSTRINGS:
        if s in m:
            return True, f"allowlisted family ({s})"

    # 3. Obvious red flags — tiny / base models that don't tool-call.
    for bad in ("ollama/", "-1b", "-1.5b", "-2b", "-3b", "-7b-base",
                "embed", "tinyllama", "phi-2"):
        if bad in m:
            return False, f"likely no tool calling ({bad})"

    return None, "unknown model — tool calling not verified"


def _coerce_args(raw: Any) -> dict:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            return json.loads(raw or "{}")
        except json.JSONDecodeError:
            return {}
    return {}


async def stream_agent(
    *,
    user_messages: list[dict],
    state: "AppState",
    model: str,
    base_url: str | None = None,
    max_steps: int = 8,
    dry_run: bool = False,
):
    """Async generator yielding agent events as they happen:

    * ``{"type": "step", "step": {...}}``       — a tool call finished
    * ``{"type": "final", "result": AgentResult}`` — loop done (last)

    :func:`run_agent` consumes this for the non-streaming endpoint; the
    SSE endpoint forwards each event to the client live.
    """
    import litellm

    from .llm import _ensure_api_key_env

    _ensure_api_key_env(model)

    messages: list[dict] = [
        {"role": "system", "content": SYSTEM_PROMPT_AGENT},
        *user_messages,
    ]
    specs = tools.openai_tool_specs()
    result = AgentResult(final_message="", model=model)
    resp = None

    for _ in range(max_steps):
        kwargs: dict = {
            "model": model,
            "messages": messages,
            "tools": specs,
            "tool_choice": "auto",
            "temperature": 0.4,
        }
        if base_url:
            kwargs["api_base"] = base_url

        resp = await litellm.acompletion(**kwargs)
        msg = resp["choices"][0]["message"]
        tool_calls = msg.get("tool_calls") or []

        messages.append(
            {
                "role": "assistant",
                "content": msg.get("content") or "",
                **({"tool_calls": tool_calls} if tool_calls else {}),
            }
        )

        if not tool_calls:
            result.final_message = msg.get("content") or ""
            break

        for tc in tool_calls:
            fn = tc["function"]
            name = fn["name"]
            args = _coerce_args(fn.get("arguments"))
            tdef = tools.get_tool(name)

            if dry_run and tdef is not None and tdef.destructive:
                payload = {
                    "skipped": True,
                    "reason": "dry_run: destructive tool needs confirmation",
                }
                step = AgentStep(name, args, payload, executed=False)
                result.pending_confirmation.append(
                    {"tool": name, "args": args}
                )
            else:
                payload = await tools.dispatch(name, args, state)
                step = AgentStep(name, args, payload, executed=True)
                key = _CREATES_INPUT.get(name)
                if key and isinstance(payload, dict):
                    created = payload.get(key)
                    if isinstance(created, str) and created:
                        result.created_inputs.append(created)

            result.steps.append(step)
            yield {
                "type": "step",
                "step": {
                    "tool": step.tool,
                    "args": step.args,
                    "result": step.result,
                    "executed": step.executed,
                },
            }

            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc.get("id"),
                    "name": name,
                    "content": _trim_result(payload),
                }
            )
    else:
        result.final_message = (
            result.final_message
            or "Reached the action limit. Tell me the next step explicitly."
        )

    usage = getattr(resp, "usage", {}) or {} if resp is not None else {}
    if hasattr(usage, "model_dump"):
        usage = usage.model_dump()
    result.usage = dict(usage)
    result.messages = messages
    yield {"type": "final", "result": result}


async def run_agent(
    *,
    user_messages: list[dict],
    state: "AppState",
    model: str,
    base_url: str | None = None,
    max_steps: int = 8,
    dry_run: bool = False,
) -> AgentResult:
    """Non-streaming wrapper: drains :func:`stream_agent`."""
    result = AgentResult(final_message="", model=model)
    async for ev in stream_agent(
        user_messages=user_messages,
        state=state,
        model=model,
        base_url=base_url,
        max_steps=max_steps,
        dry_run=dry_run,
    ):
        if ev["type"] == "final":
            result = ev["result"]
    return result
