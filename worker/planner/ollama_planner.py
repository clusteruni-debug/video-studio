"""Project planner — Gemini primary, sample fallback.

Historical note: this file was originally the Ollama local-LLM planner. The
Ollama backend was retired (see ``memory/project-video-studio-ollama.md``
2026-04-02) and its code paths removed in the Tier 2 audit. The filename is
kept to avoid touching the four call sites in ``route_plan.py``,
``save_plan.py``, ``render_manifest.py``, and ``worker/planner/__init__.py``.
"""
from __future__ import annotations

import http.client
import json
import logging
import os
import re
from dataclasses import asdict, dataclass
from typing import Any, Literal
from urllib import request
from urllib.error import URLError

from worker.planner.sample_plan import ProjectPlan, SceneSpec, build_sample_project_plan

logger = logging.getLogger(__name__)

PlannerMode = Literal["auto", "gemini", "sample"]

DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"
GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

# Shared exception tuple for outbound HTTP helpers.
# ``http.client.HTTPException`` covers ``IncompleteRead`` / ``BadStatusLine`` /
# ``RemoteDisconnected`` (not ``OSError`` subclasses).
_HTTP_ERRORS: tuple[type[BaseException], ...] = (
    URLError, OSError, TimeoutError, http.client.HTTPException,
    json.JSONDecodeError, KeyError, IndexError, ValueError, UnicodeDecodeError,
)


@dataclass(slots=True)
class PlannerMetadata:
    backend: str
    model: str | None
    fallbackUsed: bool
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _default_monthly_cap(budget_mode: str) -> float:
    if budget_mode == "premium":
        return 100.0
    if budget_mode == "standard":
        return 30.0
    return 0.0


def _clamp_score(value: Any) -> int:
    try:
        numeric = int(round(float(value)))
    except (TypeError, ValueError):
        return 3

    return max(1, min(numeric, 5))


def _bool_value(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on"}
    return default


def _duration_value(value: Any) -> float:
    try:
        numeric = round(float(value), 2)
    except (TypeError, ValueError):
        return 4.0

    return max(2.0, min(numeric, 8.0))


def _route_hint(raw: Any, budget_mode: str, human_realism: int, native_audio_need: int) -> str:
    normalized = str(raw or "").strip().lower()
    if normalized in {"local", "veo3"}:
        if budget_mode == "free" and normalized != "local":
            return "local"
        return normalized

    if budget_mode == "free":
        return "local"
    if native_audio_need >= 5:
        return "veo3"
    if human_realism >= 4:
        # Sora 2 was retired (2026-04); fall through to the local path.
        return "local"
    return "local"


def _extract_json_object(raw: str) -> dict[str, Any]:
    text = raw.strip()
    if not text:
        raise ValueError("LLM returned an empty response")

    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    code_fence = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, flags=re.DOTALL)
    if code_fence:
        try:
            return json.loads(code_fence.group(1))
        except json.JSONDecodeError:
            pass  # fall through to brace-matching extraction

    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("could not find JSON object in LLM response")

    return json.loads(text[start : end + 1])


def _scene_from_payload(index: int, payload: dict[str, Any], budget_mode: str) -> SceneSpec:
    human_realism = _clamp_score(payload.get("humanRealism"))
    native_audio_need = _clamp_score(payload.get("nativeAudioNeed"))
    route_hint = _route_hint(payload.get("routeHint"), budget_mode, human_realism, native_audio_need)

    return SceneSpec(
        id=f"scene-{index + 1:02d}",
        title=str(payload.get("title") or f"장면 {index + 1}").strip() or f"장면 {index + 1}",
        prompt=str(payload.get("prompt") or payload.get("subtitleText") or "짧은 브랜드 장면").strip(),
        durationSec=_duration_value(payload.get("durationSec")),
        priority=_clamp_score(payload.get("priority")),
        humanRealism=human_realism,
        nativeAudioNeed=native_audio_need,
        canUseStillImage=_bool_value(payload.get("canUseStillImage"), default=False),
        subtitleText=str(payload.get("subtitleText") or payload.get("title") or "짧은 카피").strip(),
        routeHint=route_hint,
    )


def _build_prompt(prompt: str, budget_mode: str) -> str:
    language = "한국어" if re.search(r"[가-힣]", prompt) else "the same language as the user prompt"
    return (
        "You are a Korean short-form video (릴스/숏츠) planning engine.\n"
        "Return JSON only. Do not use markdown.\n"
        "The JSON schema is:\n"
        "{\n"
        '  "title": "string",\n'
        '  "bgmMood": "upbeat" | "calm" | "cinematic" | "tense" | "energetic",\n'
        '  "scenes": [\n'
        "    {\n"
        '      "title": "string",\n'
        '      "prompt": "string (image generation prompt - describe the visual scene vividly)",\n'
        '      "durationSec": 4.0,\n'
        '      "priority": 1-5,\n'
        '      "humanRealism": 1-5,\n'
        '      "nativeAudioNeed": 1-5,\n'
        '      "canUseStillImage": true,\n'
        '      "subtitleText": "string (short, punchy caption for this scene)",\n'
        '      "routeHint": "local"\n'
        "    }\n"
        "  ]\n"
        "}\n"
        "Rules:\n"
        "- Create exactly 4 scenes.\n"
        "- Total duration should feel like a 15 to 25 second short video.\n"
        "- Keep scene titles short (2-4 words).\n"
        "- `prompt` must describe the VISUAL SCENE for AI image generation: people, setting, mood, lighting, camera angle. Be specific and cinematic.\n"
        "- `subtitleText` is the narration text that will be spoken aloud (TTS). Write 1-2 natural Korean sentences per scene (15-30 words). Conversational, emotionally engaging, like talking to a friend. Tell a story across 4 scenes with buildup and payoff. No generic marketing copy.\n"
        "- Always set `canUseStillImage` to true and `routeHint` to `local`.\n"
        "- Each scene's subtitleText must be DIFFERENT and advance the narrative.\n"
        f"- Write ALL text in {language}.\n"
        f"- Budget mode is {budget_mode}.\n"
        f"User request: {prompt}"
    )


def _build_project_plan_from_payload(
    payload: dict[str, Any],
    prompt: str,
    budget_mode: str,
) -> ProjectPlan:
    raw_scenes = payload.get("scenes")
    if not isinstance(raw_scenes, list) or len(raw_scenes) < 4:
        raise ValueError("LLM response did not contain enough scenes")

    scenes = [
        _scene_from_payload(index, scene_payload if isinstance(scene_payload, dict) else {}, budget_mode)
        for index, scene_payload in enumerate(raw_scenes[:6])
    ]

    if len(scenes) < 4:
        raise ValueError("LLM planner produced fewer than 4 usable scenes")

    valid_moods = {"upbeat", "calm", "cinematic", "tense", "energetic"}
    raw_mood = str(payload.get("bgmMood") or "upbeat").strip().lower()
    bgm_mood = raw_mood if raw_mood in valid_moods else "upbeat"

    return ProjectPlan(
        version=1,
        title=str(payload.get("title") or "브랜드 프로모 릴스").strip() or "브랜드 프로모 릴스",
        sourcePrompt=prompt.strip(),
        aspectRatio="9:16",
        budgetMode=budget_mode,
        monthlyCapUsd=_default_monthly_cap(budget_mode),
        scenes=scenes,
        bgmMood=bgm_mood,
    )


def _get_gemini_api_key() -> str:
    """Read Gemini API key from environment."""
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass
    return (
        os.environ.get("GEMINI_API_KEY", "").strip()
        or os.environ.get("GOOGLE_API_KEY", "").strip()
    )


def build_gemini_project_plan(
    prompt: str,
    budget_mode: str,
    model: str = DEFAULT_GEMINI_MODEL,
    timeout: int = 30,
) -> ProjectPlan:
    """Generate a project plan using Google Gemini API."""
    api_key = _get_gemini_api_key()
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is not set")

    url = GEMINI_API_URL.format(model=model)
    system_prompt = _build_prompt(prompt, budget_mode)
    payload = json.dumps({
        "contents": [{"parts": [{"text": system_prompt}]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "temperature": 0.7,
        },
    }, ensure_ascii=False).encode("utf-8")

    req = request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json", "x-goog-api-key": api_key},
    )
    with request.urlopen(req, timeout=timeout) as response:
        body = json.loads(response.read(1_048_576).decode("utf-8"))

    candidates = body.get("candidates", [])
    if not candidates:
        raise ValueError("No candidates in Gemini response")

    parts = candidates[0].get("content", {}).get("parts", [])
    response_text = ""
    for part in parts:
        if part.get("text"):
            response_text += part["text"]

    if not response_text.strip():
        raise ValueError("Empty text in Gemini response")

    parsed = _extract_json_object(response_text)
    return _build_project_plan_from_payload(parsed, prompt=prompt, budget_mode=budget_mode)


def build_project_plan(
    prompt: str,
    budget_mode: str = "free",
    planner_mode: PlannerMode = "auto",
) -> tuple[ProjectPlan, PlannerMetadata]:
    normalized_prompt = prompt.strip()
    if planner_mode == "sample":
        return (
            build_sample_project_plan(normalized_prompt, budget_mode=budget_mode),
            PlannerMetadata(
                backend="sample",
                model=None,
                fallbackUsed=False,
                detail="Forced sample planner mode",
            ),
        )

    # Primary: try Gemini API
    gemini_error: str | None = None
    if planner_mode in ("auto", "gemini"):
        try:
            plan = build_gemini_project_plan(
                normalized_prompt,
                budget_mode=budget_mode,
            )
            return (
                plan,
                PlannerMetadata(
                    backend="gemini",
                    model=DEFAULT_GEMINI_MODEL,
                    fallbackUsed=False,
                    detail=f"Gemini planner generated a {len(plan.scenes)}-scene plan",
                ),
            )
        except _HTTP_ERRORS as exc:
            if planner_mode == "gemini":
                raise
            gemini_error = f"{type(exc).__name__}: {exc}"
            logger.info("gemini planner unavailable, falling back to sample: %s", gemini_error)
        except RuntimeError as exc:
            # `build_gemini_project_plan` raises RuntimeError when the API
            # key is missing — that is expected and should fall through to
            # the sample planner without noise.
            if planner_mode == "gemini":
                raise
            gemini_error = f"{type(exc).__name__}: {exc}"
            logger.info("gemini planner disabled, using sample: %s", gemini_error)

    # Fallback: sample planner
    return (
        build_sample_project_plan(normalized_prompt, budget_mode=budget_mode),
        PlannerMetadata(
            backend="sample",
            model=None,
            fallbackUsed=True,
            detail=f"Fell back to sample planner: {gemini_error or 'gemini not attempted'}",
        ),
    )
