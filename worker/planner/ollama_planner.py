from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass
from typing import Any, Literal
from urllib import error, request

from worker.planner.sample_plan import ProjectPlan, SceneSpec, build_sample_project_plan

PlannerMode = Literal["auto", "ollama", "sample"]

DEFAULT_OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")
DEFAULT_OLLAMA_MODEL = (
    os.environ.get("VIDEO_STUDIO_OLLAMA_MODEL")
    or os.environ.get("OLLAMA_PLANNER_MODEL")
    or "qwen2.5:7b"
)


@dataclass(slots=True)
class PlannerMetadata:
    backend: str
    model: str | None
    fallbackUsed: bool
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class PlannerRuntimeStatus:
    ready: bool
    backend: str
    model: str | None
    availableModels: list[str]
    host: str
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
    if normalized in {"local", "sora2", "veo3"}:
        if budget_mode == "free" and normalized != "local":
            return "local"
        return normalized

    if budget_mode == "free":
        return "local"
    if native_audio_need >= 5:
        return "veo3"
    if human_realism >= 4:
        return "sora2"
    return "local"


def _extract_json_object(raw: str) -> dict[str, Any]:
    text = raw.strip()
    if not text:
        raise ValueError("ollama returned an empty response")

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
        raise ValueError("could not find JSON object in ollama response")

    return json.loads(text[start : end + 1])


def _http_json(url: str, payload: dict[str, Any] | None = None, timeout: int = 15) -> dict[str, Any]:
    data = None
    headers = {"Content-Type": "application/json"}
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    _MAX_RESPONSE = 1_048_576  # 1 MB
    req = request.Request(url=url, data=data, headers=headers, method="POST" if payload is not None else "GET")
    with request.urlopen(req, timeout=timeout) as response:
        body = response.read(_MAX_RESPONSE)
        return json.loads(body.decode("utf-8"))


def list_ollama_models(host: str = DEFAULT_OLLAMA_HOST, timeout: int = 4) -> list[str]:
    payload = _http_json(f"{host}/api/tags", timeout=timeout)
    models = payload.get("models", [])
    names: list[str] = []
    for model in models:
        if isinstance(model, dict) and model.get("name"):
            names.append(str(model["name"]))
    return names


def probe_planner_runtime(
    model: str = DEFAULT_OLLAMA_MODEL,
    host: str = DEFAULT_OLLAMA_HOST,
    timeout: int = 4,
) -> PlannerRuntimeStatus:
    try:
        models = list_ollama_models(host=host, timeout=timeout)
    except error.URLError as exc:
        return PlannerRuntimeStatus(
            ready=False,
            backend="sample",
            model=model,
            availableModels=[],
            host=host,
            detail=f"Ollama service unreachable: {exc.reason}",
        )
    except Exception as exc:  # pragma: no cover - defensive
        return PlannerRuntimeStatus(
            ready=False,
            backend="sample",
            model=model,
            availableModels=[],
            host=host,
            detail=f"Ollama probe failed: {exc}",
        )

    if model in models:
        return PlannerRuntimeStatus(
            ready=True,
            backend="ollama",
            model=model,
            availableModels=models,
            host=host,
            detail=f"Ollama planner ready with model {model}",
        )

    detail = f"Ollama is running but model {model} is not installed"
    if models:
        detail = f"{detail}. Installed models: {', '.join(models)}"

    return PlannerRuntimeStatus(
        ready=False,
        backend="sample",
        model=model,
        availableModels=models,
        host=host,
        detail=detail,
    )


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
        "You are a short-form video planning engine.\n"
        "Return JSON only. Do not use markdown.\n"
        "The JSON schema is:\n"
        "{\n"
        '  "title": "string",\n'
        '  "scenes": [\n'
        "    {\n"
        '      "title": "string",\n'
        '      "prompt": "string",\n'
        '      "durationSec": 4.0,\n'
        '      "priority": 1-5,\n'
        '      "humanRealism": 1-5,\n'
        '      "nativeAudioNeed": 1-5,\n'
        '      "canUseStillImage": true|false,\n'
        '      "subtitleText": "string",\n'
        '      "routeHint": "local" | "sora2" | "veo3"\n'
        "    }\n"
        "  ]\n"
        "}\n"
        "Rules:\n"
        "- Create exactly 4 scenes.\n"
        "- Total duration should feel like a 15 to 25 second short video.\n"
        "- Keep scene titles short and concrete.\n"
        "- `prompt` must describe the visual shot, not implementation details.\n"
        "- `subtitleText` must be one concise caption line.\n"
        "- Use `sora2` only for hero or realism-critical scenes.\n"
        "- Use `veo3` only if native audio really matters.\n"
        f"- Write the output in {language}.\n"
        f"- Budget mode is {budget_mode}.\n"
        f"User request: {prompt}"
    )


def _build_project_plan_from_ollama_payload(
    payload: dict[str, Any],
    prompt: str,
    budget_mode: str,
) -> ProjectPlan:
    raw_scenes = payload.get("scenes")
    if not isinstance(raw_scenes, list) or len(raw_scenes) < 4:
        raise ValueError("ollama response did not contain enough scenes")

    scenes = [
        _scene_from_payload(index, scene_payload if isinstance(scene_payload, dict) else {}, budget_mode)
        for index, scene_payload in enumerate(raw_scenes[:6])
    ]

    if len(scenes) < 4:
        raise ValueError("ollama planner produced fewer than 4 usable scenes")

    return ProjectPlan(
        version=1,
        title=str(payload.get("title") or "브랜드 프로모 릴스").strip() or "브랜드 프로모 릴스",
        sourcePrompt=prompt.strip(),
        aspectRatio="9:16",
        budgetMode=budget_mode,
        monthlyCapUsd=_default_monthly_cap(budget_mode),
        scenes=scenes,
    )


def build_ollama_project_plan(
    prompt: str,
    budget_mode: str,
    model: str = DEFAULT_OLLAMA_MODEL,
    host: str = DEFAULT_OLLAMA_HOST,
    timeout: int = 45,
) -> ProjectPlan:
    status = probe_planner_runtime(model=model, host=host)
    if not status.ready:
        raise RuntimeError(status.detail)

    response = _http_json(
        f"{host}/api/generate",
        payload={
            "model": model,
            "prompt": _build_prompt(prompt, budget_mode),
            "stream": False,
            "format": "json",
            "options": {
                "temperature": 0.2,
            },
        },
        timeout=timeout,
    )
    response_text = str(response.get("response") or "").strip()
    payload = _extract_json_object(response_text)
    return _build_project_plan_from_ollama_payload(payload, prompt=prompt, budget_mode=budget_mode)


def build_project_plan(
    prompt: str,
    budget_mode: str = "free",
    planner_mode: PlannerMode = "auto",
    model: str = DEFAULT_OLLAMA_MODEL,
    host: str = DEFAULT_OLLAMA_HOST,
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

    try:
        plan = build_ollama_project_plan(
            normalized_prompt,
            budget_mode=budget_mode,
            model=model,
            host=host,
        )
        return (
            plan,
            PlannerMetadata(
                backend="ollama",
                model=model,
                fallbackUsed=False,
                detail=f"Ollama planner generated a {len(plan.scenes)}-scene plan",
            ),
        )
    except Exception as exc:
        if planner_mode == "ollama":
            raise

        return (
            build_sample_project_plan(normalized_prompt, budget_mode=budget_mode),
            PlannerMetadata(
                backend="sample",
                model=model,
                fallbackUsed=True,
                detail=f"Ollama planner unavailable; fell back to sample planner: {exc}",
            ),
        )
