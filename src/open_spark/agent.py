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

Principles:
* Prefer doing over describing. If the user asks for something you have
  a tool for, call it.
* Inspect before mutating: when unsure of scene/source names or item
  ids, call list_scenes / list_scene_items / list_filters first.
* One coherent change per user turn; chain tool calls as needed, then
  give a short confirmation of what you did.
* Overlays are HTML Browser Sources; camera/text/color/filters are
  native OBS. Pick the right tool family for the request.
* Be concise in your final message — a sentence or two, not an essay.
* Never invent tool names. Only call tools that exist.
"""


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
    model: str = ""
    usage: dict = field(default_factory=dict)


def _coerce_args(raw: Any) -> dict:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            return json.loads(raw or "{}")
        except json.JSONDecodeError:
            return {}
    return {}


async def run_agent(
    *,
    user_messages: list[dict],
    state: "AppState",
    model: str,
    base_url: str | None = None,
    max_steps: int = 8,
    dry_run: bool = False,
) -> AgentResult:
    """Drive the tool-calling loop.

    ``user_messages`` is the prior chat as a list of
    ``{"role": "user"|"assistant", "content": str}``.
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
        choice = resp["choices"][0]
        msg = choice["message"]
        tool_calls = msg.get("tool_calls") or []

        # Record assistant turn (with any tool calls) verbatim.
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
                result.pending_confirmation.append(
                    {"tool": name, "args": args}
                )
                result.steps.append(
                    AgentStep(name, args, payload, executed=False)
                )
            else:
                payload = await tools.dispatch(name, args, state)
                result.steps.append(
                    AgentStep(name, args, payload, executed=True)
                )

            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc.get("id"),
                    "name": name,
                    "content": json.dumps(payload, default=str),
                }
            )
    else:
        # step budget exhausted without a tool-free reply
        result.final_message = (
            result.final_message
            or "Reached the action limit. Tell me the next step explicitly."
        )

    usage = getattr(resp, "usage", {}) or {}
    if hasattr(usage, "model_dump"):
        usage = usage.model_dump()
    result.usage = dict(usage)
    result.messages = messages
    return result
