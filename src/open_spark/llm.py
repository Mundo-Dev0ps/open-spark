"""LLM wrapper around LiteLLM. Provider-agnostic.

Two generation modes:

* :func:`generate_overlay`        — single self-contained HTML overlay.
* :func:`generate_scene_layout`   — structured scene blueprint with
  multiple overlays positioned on a canvas.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field

from . import secrets_store

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You produce PREMIUM-quality overlays for OBS Studio Browser Sources —
the kind a paid streamer would buy from a designer, not a free template
clone. Every output should feel intentional, layered, polished.

Output rules — non-negotiable:
1. Return EXACTLY one HTML document, starting with <!doctype html>.
2. The <head> MUST include <meta charset="utf-8"> as the first child so
   accented characters (ó, ñ, ¡) render correctly.
3. No prose, no code fences, no commentary before or after the HTML.
4. Self-contained: inline all CSS in <style>, inline all JS in <script>.
   No external URLs, fonts, images, or scripts.
5. Default body background transparent
   (`html, body { background: transparent; margin: 0; overflow: hidden; }`)
   unless the user explicitly asks for opaque.
6. Default canvas: 1920x1080. Use viewport units; do not hardcode pixels
   unless the user requests a fixed size.
7. No `alert`, `prompt`, `confirm`, `XMLHttpRequest`, `fetch`.

Quality bar — apply ALL of these to every overlay:

A. Typography
   - Use a stack of 2-3 fallbacks ending in a generic family.
   - Set explicit `font-weight` (700-900 for headlines, 400-500 body),
     `letter-spacing` (often negative for display, 0.05em-0.2em for
     small caps), and `line-height` (1.0-1.15 for headlines).
   - At least one element should use SVG-text or `text-stroke` /
     `-webkit-text-stroke` for definition.

B. Color & light
   - Layer at least TWO of: linear-gradient, radial-gradient,
     conic-gradient, mix-blend-mode, or backdrop-filter blur.
   - Drop shadows MUST stack (e.g. 3 box-shadow layers at increasing
     blur for a soft halo). Single flat colors look cheap — avoid them
     unless the brief is explicitly minimal.
   - Pick a deliberate palette (3-5 colors max) and stick to it.

C. Motion
   - Use `cubic-bezier(0.22, 1, 0.36, 1)` easing or similar premium
     curves; never default ease/linear unless the look is glitch.
   - Animations are looped, 0.6s-1.4s, and combine 2+ properties
     (e.g. transform + opacity + filter).
   - Add at least one micro-detail: pulsing dot, particle, gradient
     pan, subtle ribbon, scanline drift, depending on the style.

D. Composition
   - Never center one bare label on an empty canvas. Surround the
     primary element with ornaments: corner brackets, frame strokes,
     a key-line, side decorations, supporting microcopy.
   - Establish hierarchy: a dominant headline, supporting info,
     decorative accents.
   - Respect safe areas — keep content >= 24px from any edge.

E. Code hygiene
   - Comments inside <style> labelling each major block (palette,
     animation, layout) help maintainability.
   - Prefer CSS variables for the palette so a single tweak changes
     the whole feel.

If the user prompt is short or vague, INVENT plausible details
(streamer name placeholder, fake username, sample message, fake
viewer count, etc.) so the overlay looks alive instead of empty.
"""


SYSTEM_PROMPT_SCENE = """\
You design PREMIUM-quality OBS Studio scene layouts — the kind that
would belong in a paid streamer kit. Every source you emit must hit the
quality bar in section "Per-source HTML quality" below; cheap, flat, or
bare layouts are a hard failure.

Output rules — non-negotiable:
1. Return EXACTLY one JSON object. No prose, no code fences, no comments.
2. <head> of every source HTML MUST start with <meta charset="utf-8">.
3. The JSON object MUST conform to this schema:

{
  "scene_name": string,
  "canvas": {"width": int, "height": int},
  "sources": [
    {
      "role": string,            // see role list below
      "name": string,            // short human-readable id, kebab-case
      "html": string,            // self-contained HTML overlay
      "transform": {"x": int, "y": int, "width": int, "height": int}
    }
  ]
}

4. Roles (pick the closest match per source, repeat as needed):
   - "background"     full-canvas backdrop (animated allowed, opaque OK)
   - "webcam_frame"   stylized border/frame around an empty area where
                      the user will later drop a real webcam source
   - "chat"           chat box / message feed mock
   - "alerts"         follow / sub / donation alert area
   - "counter"        viewer count / timer / progress
   - "title"          stream title / banner
   - "lower_third"    name + tagline strip
   - "ticker"         scrolling text strip
   - "ornament"       purely decorative element
   - "stats"          info card (uptime, song now playing, etc.)

5. Per-source HTML quality (apply ALL — this is the premium bar):
   - starts with <!doctype html>
   - <head> first child is <meta charset="utf-8">
   - inline CSS in <style>, inline JS in <script>
   - NO external URLs, fonts, images, scripts
   - background transparent EXCEPT for role "background"
   - body sized to viewport (use 100vw / 100vh)
   - body { overflow: hidden } so content never bleeds past bounds
   - ticker / scroll: animation MUST stay within container; parent
     uses overflow:hidden
   - Typography: explicit font-weight + letter-spacing + line-height,
     2-3 fallbacks ending in a generic family. Use text-shadow or
     `-webkit-text-stroke` for at least one element.
   - Effects: layer ≥2 of linear-gradient / radial-gradient /
     conic-gradient / mix-blend-mode / backdrop-filter. Drop
     shadows STACK (3-layer halo). Flat single-color blocks are a
     fail unless the role is "minimal".
   - Motion: premium easing (`cubic-bezier(0.22, 1, 0.36, 1)`,
     `cubic-bezier(0.65, 0, 0.35, 1)`, etc.), looped, 0.6-1.4s,
     combining transform + opacity + filter.
   - Composition: ornaments around any primary element (corner
     brackets, key-lines, microcopy). Never bare-centred text.
   - Invent plausible placeholder content (fake username, sample
     chat line, viewer count, song title) so the source looks
     populated even before the streamer fills it in.
   - animations loop or react to time without input
   - no fetch / XHR / alert / prompt / confirm

6. Layout rules — TREAT THE CANVAS AS A 12-COLUMN x 6-ROW GRID:
   - column width  = canvas.width  / 12   (e.g. 160px @ 1920)
   - row height    = canvas.height / 6    (e.g. 180px @ 1080)
   - snap every transform x/y/width/height to integer multiples of
     these grid units (1 col, 1 row minimum).
   - "background" role MUST cover the entire canvas
     (x=0, y=0, width=canvas.width, height=canvas.height).
   - NO TWO non-background sources may share any pixel of canvas area.
     Compute rectangles before emitting — overlapping rectangles are a
     hard failure.
   - keep every transform fully inside the canvas (x+width <= canvas.width,
     y+height <= canvas.height).
   - 3 to 6 non-background sources. Add exactly one "background" source
     unless the user explicitly says no background.

7. Match the visual style the user describes (anime, cyberpunk, retro,
   minimal, glitch, newscast, etc.) consistently across all sources of
   the scene. If the user does not specify a style, pick a coherent
   single style and apply it to every source.

Return JSON ONLY.
"""


# --- Style presets ---------------------------------------------------------

STYLE_PREAMBLES: dict[str, str] = {
    "anime_kawaii": (
        "Visual style: PREMIUM anime/kawaii streamer kit (think Hololive "
        "talent overlay).\n"
        "Palette: #ffd1ec pastel pink, #ff7ed4 magenta, #c89cff lilac, "
        "#9be8ff soft cyan, white highlights, #2a1334 deep purple base.\n"
        "Typography: italic 800-weight sans-serif (e.g. \"Nunito\", "
        "\"Quicksand\", system-ui) for headlines, 600 for body. Letter-"
        "spacing -0.02em for display. Add white text-stroke 2px on hot "
        "pink fills.\n"
        "Effects: glassmorphism cards (rgba bg + backdrop-filter blur "
        "12px), 3-layer drop shadow halo (0 0 6px, 0 0 18px, 0 0 42px) "
        "in magenta. Floating sparkles ✦ animated with random delays. "
        "Sakura petal accents drifting downward. Ribbon banners across "
        "headlines. Round corners 14-22px on cards.\n"
        "Motion: bouncy `cubic-bezier(0.34, 1.56, 0.64, 1)` for entries, "
        "soft pulse glow loop 1.4s, gentle rotation 3-5deg on sparkles."
    ),
    "cyberpunk": (
        "Visual style: PREMIUM cyberpunk / Edgerunners HUD.\n"
        "Palette: #00f0ff electric cyan, #ff2bd6 hot magenta, #fde400 "
        "warning yellow accents, #0a0014 deep base, scanlines #ffffff10.\n"
        "Typography: monospace 700-900 uppercase (\"JetBrains Mono\", "
        "\"Fira Code\", ui-monospace). Letter-spacing 0.18em. Headlines "
        "use `-webkit-text-stroke: 1px #00f0ff;` over a magenta fill.\n"
        "Effects: animated grid-floor in perspective with vanishing "
        "point. RGB chromatic aberration (3-layer text-shadow: -2px 0 "
        "magenta, 2px 0 cyan, 0 0 10px white). Scanline overlay "
        "(repeating-linear-gradient at 0.5px). Lens flare via "
        "radial-gradient. Corner bracket SVG ornaments [ ].\n"
        "Motion: `cubic-bezier(0.65, 0, 0.35, 1)`. Periodic glitch "
        "stutter 0.05s offset every 4-6s. Scanline drift loop 8s."
    ),
    "minimal": (
        "Visual style: PREMIUM editorial minimal (think Apple keynote).\n"
        "Palette: pure white #ffffff or jet #0a0a0a, ONE accent (e.g. "
        "#ff5500 or #00d4aa). Greys #707070, #b0b0b0.\n"
        "Typography: light 200-300 weight sans (\"Inter\", \"Helvetica "
        "Neue\", system-ui), tight tracking on display (-0.04em). Body "
        "400, line-height 1.5.\n"
        "Effects: single hairline rule in accent color, thin geometric "
        "shapes (1-2px). Subtle tonal gradient on background (3-5% "
        "delta). Small caps for labels with 0.2em tracking.\n"
        "Motion: fades only, 600-800ms with `cubic-bezier(0.22, 1, 0.36, 1)`. "
        "No bounce, no pulse. One discrete reveal per animation."
    ),
    "retro_80s": (
        "Visual style: PREMIUM 80s synthwave / Stranger Things title card.\n"
        "Palette: sunset gradient #ff6e00 → #ff2bd6 → #6a00ff → #1a004a. "
        "Chrome accents #f0f0f0 to #888 vertical gradient.\n"
        "Typography: italic outlined display serif or geometric sans "
        "(\"Bebas Neue\"-style fallback). Bold 800, italic, "
        "`-webkit-text-stroke: 2px #fff` over a transparent fill creates "
        "the iconic outlined chrome.\n"
        "Effects: neon grid floor in perspective (#ff2bd6 → fade), "
        "horizon glow radial-gradient orange/pink. VHS noise overlay "
        "(thin repeating linear gradient + animated translateY). Palm "
        "silhouette SVGs at edges. Chrome shine sweeping across "
        "headlines via `linear-gradient` mask animation.\n"
        "Motion: slow pan grid-floor 12s loop, chrome shine sweep 3s, "
        "neon pulse 1.8s. Easing `cubic-bezier(0.45, 0, 0.55, 1)`."
    ),
    "glitch": (
        "Visual style: PREMIUM glitch art / vaporwave datamosh.\n"
        "Palette: monochrome white/black base, hot red #ff003c, electric "
        "cyan #00f0ff offsets.\n"
        "Typography: bold display 900, occasionally fragmented by random "
        "skewX 1-3deg per character. Letter-spacing 0.1em.\n"
        "Effects: 4-6px RGB channel split via 2 absolute-positioned "
        "duplicates (red translateX -4, cyan translateX 4, mix-blend-"
        "mode screen). Random datamosh slices: 4-8 horizontal bands "
        "with clip-path + transform translateX swapping every 0.2s. "
        "Hard grain noise via repeating-radial-gradient. Scanline "
        "stutter.\n"
        "Motion: `steps(4)` for stutter on text, ease-out for slice "
        "swaps. Brief 80ms desync flashes every 3-5s."
    ),
    "newscast": (
        "Visual style: PREMIUM TV newscast lower-third (CNN/BBC tier).\n"
        "Palette: deep navy #0a2240, broadcast red #c8102e, white "
        "#ffffff, gold accent #d4af37 on key bars.\n"
        "Typography: bold serif headlines (\"Roboto Slab\", \"Merriweather\"-"
        "style fallback) for the name, sans-serif 500 (\"Roboto\", "
        "\"Inter\") for the subline. Tracking 0.02em.\n"
        "Effects: solid colored bars NO transparency (opaque chrome). "
        "Subtle vertical reflective gradient on bars (3% lighter at "
        "top). Thin gold key-line 2px above the lower-third. Animated "
        "ticker with marquee. Network logo block in corner.\n"
        "Motion: bars wipe in from left over 600ms `cubic-bezier(0.65, "
        "0, 0.35, 1)`, ticker constant linear scroll, breaking-news "
        "pulse on red blocks every 2s."
    ),
}


def _apply_style(prompt: str, style: str | None) -> str:
    """Prepend a style-preamble to the user prompt if the style is known."""
    if not style:
        return prompt
    preamble = STYLE_PREAMBLES.get(style.lower().strip())
    if not preamble:
        return prompt
    return f"{preamble}\n\nUser request: {prompt}"


@dataclass
class LLMResult:
    html: str
    model: str
    usage: dict


@dataclass
class SceneSourceLayout:
    role: str
    name: str
    html: str
    transform: dict  # {x, y, width, height}


@dataclass
class SceneLayoutResult:
    scene_name: str
    canvas: dict  # {width, height}
    sources: list[SceneSourceLayout] = field(default_factory=list)
    model: str = ""
    usage: dict = field(default_factory=dict)


def _provider_of(model: str) -> str:
    # litellm format is "<provider>/<model>"
    return model.split("/", 1)[0] if "/" in model else "openai"


def _ensure_api_key_env(model: str) -> None:
    """LiteLLM reads keys from env vars; bridge from keyring on the fly."""
    import os

    provider = _provider_of(model)
    env_var = {
        "anthropic": "ANTHROPIC_API_KEY",
        "openai": "OPENAI_API_KEY",
        "gemini": "GEMINI_API_KEY",
        "groq": "GROQ_API_KEY",
        "mistral": "MISTRAL_API_KEY",
        "cohere": "COHERE_API_KEY",
        "deepseek": "DEEPSEEK_API_KEY",
        "nvidia_nim": "NVIDIA_NIM_API_KEY",
        "nvidia": "NVIDIA_NIM_API_KEY",
        "openrouter": "OPENROUTER_API_KEY",
    }.get(provider)

    if env_var and not os.environ.get(env_var):
        # secrets_store handles both keyring (host install) and the
        # env-mode user_secrets.json the dock Settings tab writes to.
        secret = secrets_store.get_llm_api_key(provider)
        if secret:
            os.environ[env_var] = secret
            log.debug("Populated %s from secrets_store for litellm", env_var)


_HTML_FENCE_RE = re.compile(r"^```(?:html)?\s*\n(.*?)\n```\s*$", re.DOTALL)
_META_CHARSET_RE = re.compile(r"<meta[^>]+charset", re.IGNORECASE)
_HEAD_OPEN_RE = re.compile(r"<head\b[^>]*>", re.IGNORECASE)


def _strip_code_fence(text: str) -> str:
    m = _HTML_FENCE_RE.match(text.strip())
    return m.group(1) if m else text.strip()


_META_TAG = '<meta charset="utf-8">'


def _ensure_meta_charset(html: str) -> str:
    """Inject ``<meta charset="utf-8">`` if missing. Belt-and-suspenders.

    LLMs sometimes omit the charset tag, which makes accented characters
    (ó, ñ, ¡) render as mojibake when the iframe / Browser Source can't
    rely on an HTTP header.
    """
    if _META_CHARSET_RE.search(html):
        return html
    head = _HEAD_OPEN_RE.search(html)
    if head:
        i = head.end()
        return html[:i] + _META_TAG + html[i:]
    # No <head>: synthesize one. Insert right after <html...> if present,
    # otherwise prepend.
    html_open = re.search(r"<html\b[^>]*>", html, re.IGNORECASE)
    if html_open:
        i = html_open.end()
        return html[:i] + "<head>" + _META_TAG + "</head>" + html[i:]
    return "<head>" + _META_TAG + "</head>" + html


async def generate_overlay(
    prompt: str,
    *,
    model: str,
    base_url: str | None = None,
    style: str | None = None,
) -> LLMResult:
    """Call the configured LLM, return a sanitized HTML document."""
    import litellm

    _ensure_api_key_env(model)

    user_prompt = _apply_style(prompt, style)

    kwargs: dict = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.7,
    }
    if base_url:
        kwargs["api_base"] = base_url

    log.info("LLM call model=%s prompt_len=%d", model, len(prompt))
    resp = await litellm.acompletion(**kwargs)

    raw = resp["choices"][0]["message"]["content"] or ""
    html = _strip_code_fence(raw)

    if "<!doctype html" not in html.lower() and "<!DOCTYPE html" not in html:
        # Fall back: wrap whatever the model returned so it still renders.
        html = (
            "<!doctype html><html><head><meta charset='utf-8'>"
            "<style>html,body{background:transparent;margin:0;}</style>"
            f"</head><body>{html}</body></html>"
        )
    html = _ensure_meta_charset(html)

    usage = getattr(resp, "usage", {}) or {}
    if hasattr(usage, "model_dump"):
        usage = usage.model_dump()

    return LLMResult(html=html, model=model, usage=dict(usage))


# --- Iterative refine -------------------------------------------------------

SYSTEM_PROMPT_REFINE = """\
You patch an existing OBS overlay HTML based on the user's refinement
instruction. Apply the change(s) requested and keep everything else
identical. The same quality bar from your normal overlay generation
still applies (typography, layered effects, motion, composition).

Output rules — non-negotiable:
1. Return EXACTLY one HTML document starting with <!doctype html>.
2. No prose, no code fences, no commentary before or after the HTML.
3. Preserve the original document's <meta charset="utf-8">; never drop it.
4. Keep the same structural roles (background, banner, chat, etc.) the
   original had. Only modify what the user asked for and the side
   effects required to keep the layout coherent.
5. Same self-contained constraint: inline CSS/JS only, no external
   resources, no network APIs.
"""


async def refine_overlay(
    *,
    existing_html: str,
    instruction: str,
    model: str,
    base_url: str | None = None,
    style: str | None = None,
) -> LLMResult:
    """Patch an existing overlay's HTML using a user-supplied delta."""
    import litellm

    _ensure_api_key_env(model)

    user_msg = _apply_style(instruction, style)

    kwargs: dict = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT_REFINE},
            {"role": "user",
             "content": (
                 "Existing overlay HTML:\n\n"
                 "```html\n"
                 f"{existing_html}\n"
                 "```\n\n"
                 f"Refinement request: {user_msg}"
             )},
        ],
        "temperature": 0.5,  # tighter than fresh-generate; we're patching
    }
    if base_url:
        kwargs["api_base"] = base_url

    log.info("LLM refine call model=%s instruction_len=%d existing_len=%d",
             model, len(instruction), len(existing_html))
    resp = await litellm.acompletion(**kwargs)

    raw = resp["choices"][0]["message"]["content"] or ""
    html = _strip_code_fence(raw)
    if "<!doctype html" not in html.lower() and "<!DOCTYPE html" not in html:
        # Fall back: wrap rather than fail hard.
        html = (
            "<!doctype html><html><head><meta charset='utf-8'>"
            "<style>html,body{background:transparent;margin:0;}</style>"
            f"</head><body>{html}</body></html>"
        )
    html = _ensure_meta_charset(html)

    usage = getattr(resp, "usage", {}) or {}
    if hasattr(usage, "model_dump"):
        usage = usage.model_dump()
    return LLMResult(html=html, model=model, usage=dict(usage))


# --- Scene layout generation ------------------------------------------------

_JSON_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)


def _extract_json(raw: str) -> dict:
    """Best-effort JSON extraction from a model reply.

    Tries, in order:
    1. Direct ``json.loads`` on the trimmed string.
    2. Strip ```` ```json ``` `` fences if present, retry.
    3. Slice from the first ``{`` to the last ``}``, retry.

    Raises :class:`ValueError` if all attempts fail.
    """
    s = (raw or "").strip()
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        pass

    fence = re.match(r"^```(?:json)?\s*\n?(.*?)\n?```\s*$", s, re.DOTALL)
    if fence:
        try:
            return json.loads(fence.group(1).strip())
        except json.JSONDecodeError:
            pass

    m = _JSON_OBJECT_RE.search(s)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError as e:
            raise ValueError(f"could not parse JSON from LLM reply: {e}") from e

    raise ValueError("LLM reply contains no JSON object")


def _validate_layout(data: dict, *, default_canvas: tuple[int, int]) -> SceneLayoutResult:
    """Coerce + validate the parsed JSON into a SceneLayoutResult.

    Permissive: missing optional fields get defaults, non-fatal type
    mismatches get coerced. Raises :class:`ValueError` on hard failures
    (no sources, missing required strings).
    """
    scene_name = str(data.get("scene_name") or "Open Spark Scene").strip() or "Open Spark Scene"
    canvas_raw = data.get("canvas") or {}
    cw = int(canvas_raw.get("width") or default_canvas[0])
    ch = int(canvas_raw.get("height") or default_canvas[1])

    raw_sources = data.get("sources") or []
    if not raw_sources:
        raise ValueError("layout has no sources")

    sources: list[SceneSourceLayout] = []
    for i, item in enumerate(raw_sources):
        if not isinstance(item, dict):
            raise ValueError(f"source #{i} is not a JSON object")
        role = str(item.get("role") or "ornament").strip() or "ornament"
        name = str(item.get("name") or f"{role}-{i+1}").strip() or f"{role}-{i+1}"
        html = item.get("html")
        if not isinstance(html, str) or "<" not in html:
            raise ValueError(f"source #{i} ({name}) has no usable html")
        if "<!doctype html" not in html.lower() and "<!DOCTYPE html" not in html:
            html = (
                "<!doctype html><html><head><meta charset='utf-8'>"
                "<style>html,body{background:transparent;margin:0;}</style>"
                f"</head><body>{html}</body></html>"
            )
        html = _ensure_meta_charset(html)
        t_raw = item.get("transform") or {}
        # background role: force full canvas
        if role == "background":
            transform = {"x": 0, "y": 0, "width": cw, "height": ch}
        else:
            transform = {
                "x": max(0, int(t_raw.get("x", 0))),
                "y": max(0, int(t_raw.get("y", 0))),
                "width": max(1, int(t_raw.get("width", cw))),
                "height": max(1, int(t_raw.get("height", ch))),
            }
        sources.append(SceneSourceLayout(role=role, name=name, html=html, transform=transform))

    sources = _resolve_overlaps(sources, canvas=(cw, ch))

    return SceneLayoutResult(
        scene_name=scene_name,
        canvas={"width": cw, "height": ch},
        sources=sources,
    )


# --- Overlap resolution ----------------------------------------------------

def _rects_overlap(a: dict, b: dict) -> bool:
    """True if two transform rects share any pixel."""
    return not (
        a["x"] + a["width"] <= b["x"]
        or b["x"] + b["width"] <= a["x"]
        or a["y"] + a["height"] <= b["y"]
        or b["y"] + b["height"] <= a["y"]
    )


def _clamp_rect(t: dict, canvas: tuple[int, int]) -> dict:
    cw, ch = canvas
    width = max(1, min(int(t["width"]), cw))
    height = max(1, min(int(t["height"]), ch))
    x = max(0, min(int(t["x"]), cw - width))
    y = max(0, min(int(t["y"]), ch - height))
    return {"x": x, "y": y, "width": width, "height": height}


def _resolve_overlaps(
    sources: list[SceneSourceLayout], *, canvas: tuple[int, int]
) -> list[SceneSourceLayout]:
    """Repair overlapping non-background rects.

    Strategy: keep the first occurrence of any colliding pair; nudge the
    second one downward (or rightward as fallback) until it no longer
    intersects any earlier source. ``background`` role is allowed under
    everything and never moves.
    """
    cw, ch = canvas
    placed: list[SceneSourceLayout] = []
    for s in sources:
        if s.role == "background":
            placed.append(s)
            continue
        t = _clamp_rect(s.transform, canvas)
        attempts = 0
        while attempts < 200 and any(
            other.role != "background" and _rects_overlap(t, other.transform)
            for other in placed
        ):
            # Try moving down by 1 row first; if past canvas, snap to next
            # column to the right and reset y.
            t = dict(t)
            t["y"] = t["y"] + max(1, ch // 6)
            if t["y"] + t["height"] > ch:
                t["y"] = 0
                t["x"] = t["x"] + max(1, cw // 12)
                if t["x"] + t["width"] > cw:
                    # Out of canvas — accept the overlap and stop.
                    log.warning(
                        "overlap resolver gave up on source %s; placing as-is", s.name
                    )
                    break
            t = _clamp_rect(t, canvas)
            attempts += 1
        placed.append(
            SceneSourceLayout(role=s.role, name=s.name, html=s.html, transform=t)
        )
    return placed


async def generate_scene_layout(
    prompt: str,
    *,
    model: str,
    base_url: str | None = None,
    canvas_width: int = 1920,
    canvas_height: int = 1080,
    style: str | None = None,
) -> SceneLayoutResult:
    """Ask the LLM for a structured scene layout.

    Returns a :class:`SceneLayoutResult` with at least one source. Raises
    :class:`ValueError` on unrecoverable parse failures.
    """
    import litellm

    _ensure_api_key_env(model)

    body = _apply_style(prompt, style)
    user_prompt = (
        f"Canvas: {canvas_width}x{canvas_height}.\n\n"
        f"{body}"
    )
    kwargs: dict = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT_SCENE},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.6,
        # Some providers honor json mode; LiteLLM passes through.
        "response_format": {"type": "json_object"},
    }
    if base_url:
        kwargs["api_base"] = base_url

    log.info("LLM scene call model=%s prompt_len=%d", model, len(prompt))
    try:
        resp = await litellm.acompletion(**kwargs)
    except Exception:
        # Some providers reject response_format. Retry without it.
        kwargs.pop("response_format", None)
        log.info("retrying without response_format=json_object")
        resp = await litellm.acompletion(**kwargs)

    raw = resp["choices"][0]["message"]["content"] or ""
    data = _extract_json(raw)
    layout = _validate_layout(data, default_canvas=(canvas_width, canvas_height))
    layout.model = model
    usage = getattr(resp, "usage", {}) or {}
    if hasattr(usage, "model_dump"):
        usage = usage.model_dump()
    layout.usage = dict(usage)
    return layout
