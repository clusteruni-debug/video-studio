from __future__ import annotations

import base64
import binascii
import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from worker.bridge.image_router import route_image
from worker.bridge.routes_gates import build_hot_topic_candidates
from worker.bridge.scene_generator import generate_scenes_llm, wrap_narration
from worker.media.adapters import ADAPTER_CONFIG, probe_local_media_adapters
from worker.media.model_router import ProviderAvailability
from worker.planner.save_plan import save_project_bundle

logger = logging.getLogger(__name__)

AUTO_STUDIO_SCHEMA = "video-studio.auto-studio.run.v1"
AUTO_STUDIO_PROVIDER_SCHEMA = "video-studio.auto-studio.asset-provider-registry.v1"
AUTO_STUDIO_LATEST_SCHEMA = "video-studio.auto-studio.latest.v1"
AUTO_STUDIO_IMPORT_SCHEMA = "video-studio.auto-studio.operator-import-provenance.v1"
DEFAULT_DISCOVERY_SEED = "오늘 한국에서 가장 뜨거운 소재"
DEFAULT_ASSET_PROVIDER = "auto-image"
HANDOFF_STATUSES = {"queued", "prompt-copied", "operator-generated", "imported", "blocked", "fallback-used"}
HANDOFF_EXECUTION_MODES = ["auto-route", "command", "operator-handoff", "manual-import", "api"]
HANDOFF_REQUIRED_MODES = {"operator-handoff", "manual-import"}
AUTO_STUDIO_IMPORT_MAX_BYTES = 200 * 1024 * 1024


def _now_stamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def _slug(value: str) -> str:
    normalized = re.sub(r"[^0-9a-zA-Z가-힣]+", "-", value.strip().lower()).strip("-")
    return normalized[:56] or "auto-studio"


def _safe_text(value: object, fallback: str = "", max_chars: int = 1200) -> str:
    text = " ".join(str(value or fallback).replace("\r", " ").replace("\n", " ").split())
    return text[:max_chars]


def _scene_id(index: int) -> str:
    return f"scene-{index + 1:02d}"


def _bool_payload(payload: dict[str, Any], key: str, default: bool = False) -> bool:
    value = payload.get(key)
    if isinstance(value, bool):
        return value
    if value in (None, ""):
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def _int_payload(payload: dict[str, Any], key: str, default: int, *, minimum: int, maximum: int) -> int:
    try:
        value = int(payload.get(key, default))
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(maximum, value))


def _provider_status(adapters: dict[str, Any], key: str) -> dict[str, Any]:
    status = adapters.get(key)
    if status:
        return status.to_dict()
    config = ADAPTER_CONFIG.get(key, {})
    return {
        "key": key,
        "label": config.get("label", key),
        "mode": "not-registered",
        "outputKind": config.get("outputKind", "video"),
        "model": config.get("model", "external"),
        "ready": False,
        "fallbackAvailable": True,
        "entryPoint": None,
        "commandPreview": None,
        "detail": "Provider slot is not registered in the local adapter table.",
    }


def _provider_contract(
    *,
    key: str,
    label: str,
    media_kind: str,
    execution_mode: str,
    handoff_kind: str = "",
    source_intent: str = "",
    ready: bool = False,
    default: bool = False,
    can_generate_now: bool = False,
    can_import_result: bool = False,
    requires_operator_proof: bool = False,
    expected_output_kind: str = "image",
    target_url: str = "",
    adapter_interface: str = "",
    proof_boundary: str = "",
    detail: str = "",
    status: dict[str, Any] | None = None,
    dev_proof_rail: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if execution_mode not in HANDOFF_EXECUTION_MODES:
        raise ValueError(f"unsupported execution mode: {execution_mode}")
    return {
        "key": key,
        "label": label,
        "mediaKind": media_kind,
        "mode": execution_mode,
        "executionMode": execution_mode,
        "handoffKind": handoff_kind,
        "sourceIntent": source_intent or key,
        "ready": bool(ready),
        "default": bool(default),
        "renderableNow": bool(can_generate_now),
        "canGenerateNow": bool(can_generate_now),
        "canImportResult": bool(can_import_result),
        "requiresOperatorProof": bool(requires_operator_proof),
        "expectedOutputKind": expected_output_kind,
        "targetUrl": target_url,
        "adapterInterface": adapter_interface,
        "proofBoundary": proof_boundary,
        "detail": detail,
        "status": status or {},
        "devProofRail": dev_proof_rail or None,
    }


def build_asset_provider_registry(project_root: str | Path = ".") -> dict[str, Any]:
    """Return the production-provider map used by Auto Studio.

    The registry separates current render intent from future extension slots.
    Grok is intentionally modeled as a manual browser-handoff provider because
    successful Grok production still requires generation/import proof.
    """
    resolved_project_root = Path(project_root).resolve()
    adapters = probe_local_media_adapters(resolved_project_root)
    gemini_status = _provider_status(adapters, "gemini-flash")
    pexels_video_status = _provider_status(adapters, "pexels-video")
    wan_status = _provider_status(adapters, "wan")
    grok_status = _provider_status(adapters, "grok")
    providers = [
        _provider_contract(
            key="auto-image",
            label="Auto image route",
            media_kind="image",
            execution_mode="auto-route",
            source_intent="auto",
            ready=True,
            default=True,
            can_generate_now=True,
            can_import_result=True,
            expected_output_kind="image/png",
            adapter_interface="image_router zero-paid policy with local/import fallback",
            proof_boundary="Draft-only auto route; publish-ready still needs source review, phone review, and platform metadata.",
            detail="Uses the existing image_router policy without presenting Grok/Gemini web surfaces as automatic generation.",
        ),
        _provider_contract(
            key="pexels-video",
            label="Pexels video fallback",
            media_kind="video",
            execution_mode="auto-route",
            source_intent="pexels-video",
            ready=bool(pexels_video_status["ready"]),
            can_generate_now=True,
            can_import_result=True,
            expected_output_kind="video/mp4",
            adapter_interface="stock video search/import",
            proof_boundary="Stock fallback can make a draft render, but it is not publish-ready fresh-source proof.",
            status=pexels_video_status,
        ),
        _provider_contract(
            key="wan",
            label="Wan local command",
            media_kind="video",
            execution_mode="command",
            handoff_kind="local-command",
            source_intent="wan",
            ready=bool(wan_status["ready"]),
            can_generate_now=bool(wan_status["ready"]),
            can_import_result=True,
            expected_output_kind="video/mp4",
            adapter_interface="operator-approved command adapter",
            proof_boundary="Command output must attach as SceneAssetPayload with request/prompt/log provenance before render-ready.",
            status=wan_status,
        ),
        _provider_contract(
            key="grok",
            label="Grok Imagine handoff",
            media_kind="video",
            execution_mode="operator-handoff",
            handoff_kind="grok-imagine",
            source_intent="grok",
            ready=False,
            can_generate_now=False,
            can_import_result=True,
            requires_operator_proof=True,
            expected_output_kind="video/mp4",
            target_url="https://grok.com/imagine",
            adapter_interface="operator opens Grok /imagine, generates, downloads MP4, then imports the local file",
            proof_boundary="Grok /c/* redirects and surface-only proof do not pass; local MP4 import proof is required.",
            status=grok_status,
            dev_proof_rail={
                "kind": "browser-control",
                "purpose": "development proof only",
                "acceptedAsProductFlow": False,
            },
        ),
        _provider_contract(
            key="gemini",
            label="Gemini web handoff",
            media_kind="image-or-video",
            execution_mode="operator-handoff",
            handoff_kind="gemini-web",
            source_intent="gemini",
            ready=False,
            can_generate_now=False,
            can_import_result=True,
            requires_operator_proof=True,
            expected_output_kind="image/png-or-video/mp4",
            target_url="https://gemini.google.com/app",
            adapter_interface="operator opens Gemini web, generates image/video, downloads PNG/MP4, then imports the local file",
            proof_boundary="Gemini web output is render-ready only after local PNG/MP4 import with provenance sidecar.",
            status=gemini_status,
            dev_proof_rail={
                "kind": "browser-control",
                "purpose": "development proof only",
                "acceptedAsProductFlow": False,
            },
        ),
        _provider_contract(
            key="seedance",
            label="Seedance manual slot",
            media_kind="video",
            execution_mode="manual-import",
            handoff_kind="future-video-manual",
            source_intent="seedance",
            ready=False,
            can_generate_now=False,
            can_import_result=True,
            requires_operator_proof=True,
            expected_output_kind="video/mp4",
            adapter_interface="future command adapter or operator handoff adapter",
            proof_boundary="Seedance is a manual/future slot until an adapter returns SceneAssetPayload with provenance.",
        ),
        _provider_contract(
            key="custom-external",
            label="Custom external model slot",
            media_kind="image-or-video",
            execution_mode="manual-import",
            handoff_kind="custom-external-manual",
            source_intent="custom-external",
            ready=False,
            can_generate_now=False,
            can_import_result=True,
            requires_operator_proof=True,
            expected_output_kind="image/png-or-video/mp4",
            adapter_interface="SceneAssetPayload-compatible adapter",
            proof_boundary="Adapter output must attach to sceneAssets with sourcePath/base64 and provenance.",
        ),
    ]
    return {
        "ok": True,
        "schema": AUTO_STUDIO_PROVIDER_SCHEMA,
        "projectRoot": str(resolved_project_root),
        "defaultProvider": DEFAULT_ASSET_PROVIDER,
        "executionModes": HANDOFF_EXECUTION_MODES,
        "devProofRail": {
            "browserControl": "development proof rail only; dashboard operator handoff remains the product flow",
        },
        "providers": providers,
        "extensionContract": {
            "input": "sceneId, prompt, durationSec, aspectRatio=9:16, providerOptions",
            "output": "SceneAssetPayload with role=visual and either sourcePath or base64",
            "proof": "provider, sourceProvider, sourceGeneratorRequestPath/logPath, sourceUrl or operator proof note",
        },
    }


def _provider_by_key(registry: dict[str, Any], key: str) -> dict[str, Any]:
    providers = registry.get("providers") if isinstance(registry, dict) else []
    for provider in providers or []:
        if provider.get("key") == key:
            return provider
    return next(
        (provider for provider in providers or [] if provider.get("key") == DEFAULT_ASSET_PROVIDER),
        {"key": DEFAULT_ASSET_PROVIDER, "sourceIntent": "auto", "mediaKind": "image"},
    )


def _select_candidate(discovery: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    explicit = payload.get("selectedCandidate")
    if isinstance(explicit, dict) and explicit.get("title"):
        return explicit
    candidates = [item for item in discovery.get("candidates", []) if isinstance(item, dict)]
    requested_id = str(payload.get("candidateId") or "").strip()
    if requested_id:
        for candidate in candidates:
            if str(candidate.get("id") or "") == requested_id:
                return candidate
    index = _int_payload(payload, "candidateIndex", 0, minimum=0, maximum=max(0, len(candidates) - 1))
    if candidates:
        return candidates[index]
    return {
        "id": "fallback-topic",
        "title": str(payload.get("seed") or DEFAULT_DISCOVERY_SEED),
        "centralQuestion": "Why is this topic worth explaining now?",
        "viewerPromise": "Turn a trending question into a source-aware short video draft.",
        "whyHot": "Fallback topic used because discovery returned no candidate.",
        "score": 0,
    }


def _creator_prompt(candidate: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    title = _safe_text(candidate.get("title"), DEFAULT_DISCOVERY_SEED, 120)
    central_question = _safe_text(candidate.get("centralQuestion"), f"{title}을 왜 지금 봐야 하는가?", 300)
    viewer_promise = _safe_text(candidate.get("viewerPromise"), "핵심 질문을 장면 단위로 정리합니다.", 300)
    why_hot = _safe_text(candidate.get("whyHot"), "현재성 있는 소재 후보입니다.", 300)
    style = _safe_text(payload.get("visualStyle"), "documentary vertical short, realistic, source-aware", 180)
    target = _safe_text(payload.get("targetDuration"), "30s", 20)
    scene_count = _int_payload(payload, "sceneCount", 5, minimum=3, maximum=8)
    research_terms = []
    for link in candidate.get("researchLinks") or []:
        if isinstance(link, dict) and link.get("query"):
            research_terms.append(str(link["query"]))
    topic_prompt = (
        f"{title}\n"
        f"Central question: {central_question}\n"
        f"Viewer promise: {viewer_promise}\n"
        f"Why now: {why_hot}"
    )
    custom_instruction = (
        f"Create {scene_count} scenes for a Korean vertical short. "
        f"Use a concrete hook in scene 1, then explain the topic as source-aware visual beats. "
        f"Visual style: {style}. Target duration: {target}. "
        f"Do not claim unverified facts; frame unknowns as questions. "
        f"Suggested research terms: {', '.join(research_terms[:4]) or title}."
    )
    return {
        "title": title,
        "topicPrompt": topic_prompt,
        "customInstruction": custom_instruction,
        "sceneCount": scene_count,
        "targetDuration": target,
        "visualStyle": style,
        "researchTerms": research_terms[:8],
    }


def _source_intent(provider: dict[str, Any]) -> str:
    key = str(provider.get("key") or DEFAULT_ASSET_PROVIDER)
    if key in {"grok", "gemini", "seedance", "custom-external"}:
        return key
    if key in {"wan", "ltx-video", "hunyuan-video"}:
        return key
    if key == "pexels-video":
        return "pexels-video"
    return "pexels"


def _provider_overrides_for(provider: dict[str, Any], draft_scenes: list[dict[str, Any]]) -> dict[str, str]:
    key = str(provider.get("key") or "")
    if key in {"gemini-flash", "wan", "ltx-video", "hunyuan-video", "pexels-video"}:
        return {str(scene["sceneId"]): key for scene in draft_scenes}
    return {}


def _grok_prompt(scene: dict[str, Any], creator_prompt: dict[str, Any]) -> str:
    visual = _safe_text(scene.get("image_prompt") or scene.get("display_text") or scene.get("narration"), max_chars=500)
    return " ".join(
        [
            visual,
            "Vertical 9:16 realistic short video, 4-6 seconds.",
            "No baked-in subtitles, no watermark, no logo.",
            f"Topic continuity: {creator_prompt['title']}.",
        ]
    )


def _expected_file_name(provider: dict[str, Any], scene_id: str) -> str:
    key = str(provider.get("key") or DEFAULT_ASSET_PROVIDER)
    expected_kind = str(provider.get("expectedOutputKind") or "")
    if "image/png" in expected_kind and "video/mp4" not in expected_kind:
        return f"{scene_id}.{key}.png"
    return f"{scene_id}.{key}.mp4"


def _proof_checklist(provider: dict[str, Any]) -> list[str]:
    key = str(provider.get("key") or DEFAULT_ASSET_PROVIDER)
    if key == "grok":
        return [
            "Open Grok /imagine in the operator's signed-in Chrome session.",
            "Copy/paste the scene prompt and generate manually.",
            "Do not accept /c/* redirect or surface-only visibility as proof.",
            "Download/save the MP4 locally.",
            "Import the local MP4 into this scene so Video Studio writes provenance sidecar.",
        ]
    if key == "gemini":
        return [
            "Open Gemini web in the operator's signed-in Chrome session.",
            "Copy/paste the scene prompt and generate image/video manually.",
            "Download/save the PNG or MP4 locally.",
            "Import the local file into this scene so Video Studio writes provenance sidecar.",
        ]
    if key == "wan":
        return [
            "Run the operator-approved local command adapter only when it is configured.",
            "Keep request, prompt, command, and log paths with the generated MP4.",
            "Import or attach the local MP4 as SceneAssetPayload before render-ready.",
        ]
    return [
        "Generate or prepare the asset outside Video Studio.",
        "Import the local PNG/MP4 into the matching scene.",
        "Record provider, prompt, source surface, proof mode, and operator note.",
    ]


def _build_handoff_queue(draft_scenes: list[dict[str, Any]], provider: dict[str, Any]) -> list[dict[str, Any]]:
    mode = str(provider.get("executionMode") or provider.get("mode") or "")
    if mode not in {"operator-handoff", "manual-import", "command"}:
        return []
    queue: list[dict[str, Any]] = []
    for scene in draft_scenes:
        scene_id = str(scene.get("sceneId") or _scene_id(len(queue)))
        prompt = str(scene.get("grok_prompt") or scene.get("image_prompt") or scene.get("display_text") or "")
        task_id = f"{scene_id}-{provider.get('key')}-handoff"
        queue.append(
            {
                "taskId": task_id,
                "sceneId": scene_id,
                "provider": provider.get("key"),
                "targetUrl": provider.get("targetUrl") or "",
                "prompt": prompt,
                "expectedFileName": _expected_file_name(provider, scene_id),
                "outputKind": provider.get("expectedOutputKind") or scene.get("upload_kind") or "video/mp4",
                "proofChecklist": _proof_checklist(provider),
                "status": "queued",
                "handoffKind": provider.get("handoffKind") or "",
                "proofBoundary": provider.get("proofBoundary") or "",
            }
        )
    return queue


def _render_readiness(
    draft_scenes: list[dict[str, Any]],
    *,
    provider: dict[str, Any],
    scene_assets: list[dict[str, Any]],
    handoff_queue: list[dict[str, Any]],
) -> dict[str, Any]:
    imported_scene_ids = {
        str(asset.get("sceneId"))
        for asset in scene_assets
        if asset.get("sceneId") and (asset.get("sourcePath") or asset.get("base64"))
    }
    queue_scene_ids = {str(item.get("sceneId")) for item in handoff_queue if item.get("sceneId")}
    missing = sorted(scene_id for scene_id in queue_scene_ids if scene_id not in imported_scene_ids)
    mode = str(provider.get("executionMode") or provider.get("mode") or "")
    import_required = mode in HANDOFF_REQUIRED_MODES or bool(provider.get("requiresOperatorProof"))
    render_ready = not (import_required and missing)
    return {
        "status": "render-ready" if render_ready else "render-blocked",
        "draftReady": bool(draft_scenes),
        "renderReady": render_ready,
        "publishReady": False,
        "missingImportProofSceneIds": missing,
        "importedSceneIds": sorted(imported_scene_ids),
        "draftReadyBoundary": "Draft-ready means storyboard/prompt/queue exists.",
        "renderReadyBoundary": "Handoff scenes require local imported SceneAssetPayload proof before render.",
        "publishReadyBoundary": "Publish-ready additionally requires source review, phone review, and platform metadata.",
        "proofBoundary": provider.get("proofBoundary") or "",
    }


def _draft_scene(
    scene: dict[str, Any],
    index: int,
    *,
    provider: dict[str, Any],
    creator_prompt: dict[str, Any],
) -> dict[str, Any]:
    scene_id = _scene_id(index)
    narration = _safe_text(scene.get("narration"), max_chars=900)
    display_text = _safe_text(scene.get("display_text") or narration, max_chars=140)
    image_prompt = _safe_text(scene.get("image_prompt") or display_text or creator_prompt["title"], max_chars=600)
    intent = _source_intent(provider)
    is_video_intent = intent in {"grok", "wan", "ltx-video", "hunyuan-video", "pexels-video"}
    return {
        "sceneId": scene_id,
        "scene_num": index + 1,
        "title": display_text or f"Scene {index + 1}",
        "narration": narration,
        "display_text": display_text,
        "image_prompt": image_prompt,
        "image_source": intent,
        "emotion": str(scene.get("emotion") or "neutral"),
        "duration": float(scene.get("duration") or scene.get("_tts_duration") or 4.0),
        "upload_kind": "video" if is_video_intent else "image",
        "handoff_provider": provider.get("key") if provider.get("requiresOperatorProof") or provider.get("executionMode") in {"operator-handoff", "manual-import", "command"} else "",
        "handoff_status": "queued" if provider.get("requiresOperatorProof") or provider.get("executionMode") in {"operator-handoff", "manual-import", "command"} else "",
        "caption_preset": "top-hook" if index == 0 else "lower-info",
        "grok_prompt": _grok_prompt(scene, creator_prompt),
        "source_rationale": _source_rationale(intent, index),
        "continuity_note": "Auto Studio draft: keep subject, palette, and source logic consistent across scenes.",
        "hook_note": "Open with the strongest question and visible motion." if index == 0 else "",
        "originality_evidence": "Auto-compiled from topic candidate; source ledger review remains required for publish-ready.",
        "quality_review_note": "",
        "visual_quality_verdict": "",
        "thumbnail_review_note": "",
        "audio_mix_review_note": "",
        "platform_comparison_note": "",
        "layout_variant_key": "",
        "layout_variant_label": "",
        "layout_variant_note": "",
    }


def _source_rationale(intent: str, index: int) -> str:
    if intent == "grok":
        return f"Grok Imagine is planned for scene {index + 1}; original MP4 import/proof is required before publish-ready."
    if intent == "gemini":
        return f"Gemini web handoff is planned for scene {index + 1}; local PNG/MP4 import proof is required before render."
    if intent in {"seedance", "custom-external"}:
        return f"{intent} is a manual/future slot for scene {index + 1}; imported SceneAssetPayload proof is required before render."
    if intent in {"wan", "ltx-video", "hunyuan-video"}:
        return f"{intent} local video adapter planned for scene {index + 1}; command output should attach as scene asset."
    if intent == "pexels-video":
        return f"Pexels video route planned for scene {index + 1}; operator can replace it with generated footage."
    return f"Auto image route planned for scene {index + 1}; generated/local image can be replaced in the editor."


def _client_image_url(path_or_url: str | None, project_root: Path) -> str | None:
    if not path_or_url:
        return None
    if path_or_url.startswith(("http://", "https://")):
        return path_or_url
    try:
        path = Path(path_or_url).resolve()
        cache_root = (project_root / "storage" / "cache").resolve()
        if path.parent == cache_root or path.is_relative_to(cache_root):
            return f"http://127.0.0.1:5161/api/images/{path.name}"
    except (OSError, ValueError, AttributeError):
        return None
    return None


def _generated_scene_assets(
    draft_scenes: list[dict[str, Any]],
    *,
    provider: dict[str, Any],
    project_root: Path,
    generate_assets: bool,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    assets: list[dict[str, Any]] = []
    generated: list[dict[str, Any]] = []
    warnings: list[str] = []
    if not generate_assets:
        return assets, generated, warnings
    if provider.get("key") in {"grok", "gemini", "wan", "seedance", "custom-external"}:
        warnings.append(f"{provider.get('key')} requires handoff/import; Auto Studio did not fake an asset.")
        return assets, generated, warnings

    for scene in draft_scenes:
        route_scene = {
            "image_prompt": scene.get("image_prompt"),
            "image_source": (
                "imagen" if provider.get("key") == "gemini-flash"
                else "" if provider.get("key") == "auto-image"
                else scene.get("image_source")
            ),
            "emotion": scene.get("emotion", "neutral"),
        }
        image_url, source = route_image(route_scene)
        item = {
            "sceneId": scene["sceneId"],
            "provider": source or provider.get("key"),
            "imageUrl": image_url,
            "attachedAsSceneAsset": False,
        }
        scene["_image_url"] = _client_image_url(image_url, project_root)
        if image_url and not image_url.startswith(("http://", "https://")):
            try:
                local = Path(image_url).resolve()
                local.relative_to(project_root.resolve())
            except (OSError, ValueError):
                warnings.append(f"{scene['sceneId']} generated file was outside the project root and was not attached.")
            else:
                mime_type = "image/png" if local.suffix.lower() == ".png" else "image/jpeg"
                scene["_server_asset_path"] = str(local)
                scene["_server_asset_mime"] = mime_type
                scene["_upload_name"] = local.name
                item["attachedAsSceneAsset"] = True
                assets.append(
                    {
                        "sceneId": scene["sceneId"],
                        "role": "visual",
                        "fileName": local.name,
                        "mimeType": mime_type,
                        "sourcePath": str(local),
                        "provider": source or provider.get("key"),
                        "sourceProvider": source or provider.get("key"),
                        "sourceOrigin": "auto-studio-generated",
                        "sourceLabel": f"Auto Studio {source or provider.get('key')} asset",
                    }
                )
        elif image_url:
            warnings.append(f"{scene['sceneId']} resolved to a remote asset; it is preview-only until imported.")
        else:
            warnings.append(f"{scene['sceneId']} did not resolve an image asset; render can fall back to title cards.")
        generated.append(item)
    return assets, generated, warnings


def _draft_result(
    draft_scenes: list[dict[str, Any]],
    *,
    template_type: str,
    total_duration: float,
    message: str,
) -> dict[str, Any]:
    return {
        "ok": True,
        "draft_id": "",
        "draft_path": None,
        "template_type": template_type,
        "scenes": [
            {
                "sceneId": scene["sceneId"],
                "scene_num": scene["scene_num"],
                "narration": scene["narration"],
                "display_text": scene["display_text"],
                "image_prompt": scene["image_prompt"],
                "emotion": scene["emotion"],
                "duration": scene["duration"],
                "has_image": bool(scene.get("_image_url") or scene.get("_server_asset_path")),
                "rank": None,
                "image_source": scene["image_source"],
                "_tts_url": None,
                "_image_url": scene.get("_image_url"),
                "_server_asset_path": scene.get("_server_asset_path"),
                "_server_asset_mime": scene.get("_server_asset_mime"),
                "_upload_name": scene.get("_upload_name"),
                "_upload_kind": scene.get("upload_kind"),
                "handoff_provider": scene.get("handoff_provider"),
                "handoff_status": scene.get("handoff_status"),
                "handoff_task_id": scene.get("handoff_task_id"),
                "handoff_expected_file": scene.get("handoff_expected_file"),
                "handoff_target_url": scene.get("handoff_target_url"),
                "handoff_output_kind": scene.get("handoff_output_kind"),
                "handoff_provenance_path": scene.get("handoff_provenance_path"),
                "caption_preset": scene.get("caption_preset"),
                "grok_prompt": scene.get("grok_prompt"),
                "source_rationale": scene.get("source_rationale"),
                "continuity_note": scene.get("continuity_note"),
                "hook_note": scene.get("hook_note"),
                "originality_evidence": scene.get("originality_evidence"),
                "quality_review_note": scene.get("quality_review_note"),
                "visual_quality_verdict": scene.get("visual_quality_verdict"),
                "thumbnail_review_note": scene.get("thumbnail_review_note"),
                "audio_mix_review_note": scene.get("audio_mix_review_note"),
                "platform_comparison_note": scene.get("platform_comparison_note"),
                "layout_variant_key": scene.get("layout_variant_key"),
                "layout_variant_label": scene.get("layout_variant_label"),
                "layout_variant_note": scene.get("layout_variant_note"),
            }
            for scene in draft_scenes
        ],
        "tts_provider": "edge",
        "total_duration": round(total_duration, 1),
        "steps": ["topic discovered", "prompt compiled", "scene draft ready"],
        "message": message,
    }


def _write_run_record(project_root: Path, payload: dict[str, Any]) -> tuple[str, str]:
    run_id = str(payload["runId"])
    root = project_root / "storage" / "auto-studio" / "runs" / run_id
    root.mkdir(parents=True, exist_ok=True)
    run_path = root / "run-summary.json"
    latest_path = project_root / "storage" / "auto-studio" / "latest.json"
    run_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    latest_path.parent.mkdir(parents=True, exist_ok=True)
    latest_path.write_text(
        json.dumps({"schema": AUTO_STUDIO_LATEST_SCHEMA, "runId": run_id, "runPath": str(run_path)}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return str(run_path), str(latest_path)


def _run_record_path(project_root: Path, run_id: str) -> Path:
    return project_root / "storage" / "auto-studio" / "runs" / run_id / "run-summary.json"


def _load_run_record(project_root: Path, run_id: str) -> tuple[dict[str, Any] | None, Path]:
    run_path = _run_record_path(project_root, run_id)
    if not run_path.exists():
        return None, run_path
    try:
        return json.loads(run_path.read_text(encoding="utf-8")), run_path
    except (OSError, json.JSONDecodeError):
        return None, run_path


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _relative_project_path(path: Path, project_root: Path) -> str:
    try:
        return path.resolve().relative_to(project_root.resolve()).as_posix()
    except (OSError, ValueError):
        return str(path)


def _local_preview_url(relative_source: str, mime_type: str) -> str | None:
    if mime_type == "video/mp4":
        from urllib.parse import quote

        return f"http://127.0.0.1:5161/api/local-video/preview?path={quote(relative_source, safe='')}"
    return None


def _decode_import_payload(payload: dict[str, Any]) -> tuple[bytes | None, str, str, str | None]:
    encoded = str(payload.get("fileBase64") or payload.get("file_base64") or payload.get("base64") or "").strip()
    file_name = Path(str(payload.get("fileName") or payload.get("file_name") or payload.get("name") or "").strip()).name
    if not encoded:
        return None, file_name, "", "fileBase64 is required"
    if not file_name:
        return None, file_name, "", "fileName is required"
    suffix = Path(file_name).suffix.lower()
    if suffix not in {".png", ".mp4"}:
        return None, file_name, "", "fileName must end with .png or .mp4"
    if encoded.lower().startswith("data:") and "," in encoded:
        encoded = encoded.split(",", 1)[1]
    try:
        data = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        return None, file_name, "", f"invalid fileBase64: {exc}"
    if not data:
        return None, file_name, "", "fileBase64 decoded to an empty file"
    if len(data) > AUTO_STUDIO_IMPORT_MAX_BYTES:
        return None, file_name, "", f"fileBase64 decoded file exceeds {AUTO_STUDIO_IMPORT_MAX_BYTES} bytes"
    if suffix == ".png":
        if not data.startswith(bytes.fromhex("89504e470d0a1a0a")):
            return None, file_name, "", "PNG import failed magic-byte validation"
        mime_type = "image/png"
    else:
        header = data[:64]
        if b"ftyp" not in header:
            return None, file_name, "", "MP4 import failed magic-byte validation"
        mime_type = "video/mp4"
    return data, file_name, mime_type, None


def update_handoff_task_status(payload: dict[str, Any], project_root: str | Path = ".") -> dict[str, Any]:
    resolved_project_root = Path(project_root).resolve()
    run_id = _slug(_safe_text(payload.get("runId"), "", 220))
    task_id = _safe_text(payload.get("taskId"), "", 220)
    status = _safe_text(payload.get("status"), "", 40)
    if not run_id or not task_id:
        return {"ok": False, "error": "runId and taskId are required"}
    if status not in HANDOFF_STATUSES:
        return {"ok": False, "error": f"status must be one of {', '.join(sorted(HANDOFF_STATUSES))}"}
    run, run_path = _load_run_record(resolved_project_root, run_id)
    if not run:
        return {"ok": False, "error": "auto-studio run not found"}
    queue = run.setdefault("assetPipeline", {}).setdefault("handoffQueue", [])
    updated = None
    for item in queue:
        if isinstance(item, dict) and str(item.get("taskId") or "") == task_id:
            item["status"] = status
            item["updatedAt"] = datetime.now().isoformat(timespec="seconds")
            if payload.get("operatorNote"):
                item["operatorNote"] = _safe_text(payload.get("operatorNote"), max_chars=500)
            if payload.get("sourceSurface"):
                item["sourceSurface"] = _safe_text(payload.get("sourceSurface"), max_chars=500)
            updated = item
            break
    if updated is None:
        return {"ok": False, "error": "handoff task not found"}
    _write_json(run_path, run)
    return {"ok": True, "runId": run_id, "task": updated, "handoffQueue": queue}


def import_auto_studio_asset(payload: dict[str, Any], project_root: str | Path = ".") -> dict[str, Any]:
    resolved_project_root = Path(project_root).resolve()
    run_id = _slug(_safe_text(payload.get("runId"), "", 220))
    scene_id = _slug(_safe_text(payload.get("sceneId"), "", 80))
    if not run_id or not scene_id:
        return {"ok": False, "error": "runId and sceneId are required"}
    file_bytes, file_name, mime_type, error = _decode_import_payload(payload)
    if error or file_bytes is None:
        return {"ok": False, "error": error or "invalid import file"}

    provider = _safe_text(payload.get("provider"), "manual-import", 80)
    handoff_task_id = _safe_text(payload.get("handoffTaskId") or payload.get("taskId"), f"{scene_id}-{provider}-handoff", 220)
    source_surface = _safe_text(payload.get("sourceSurface"), provider, 500)
    operator_note = _safe_text(payload.get("operatorNote"), "", 800)
    proof_mode = _safe_text(payload.get("proofMode"), "operator-local-import", 80)
    prompt = _safe_text(payload.get("prompt"), "", 2000)
    suffix = Path(file_name).suffix.lower()
    safe_stem = _slug(Path(file_name).stem) or f"{scene_id}-{provider}"
    target_name = f"{safe_stem}{suffix}"
    import_dir = resolved_project_root / "storage" / "auto-studio" / "imports" / run_id / scene_id
    target_path = import_dir / target_name
    import_dir.mkdir(parents=True, exist_ok=True)
    target_path.write_bytes(file_bytes)
    relative_source = _relative_project_path(target_path, resolved_project_root)
    sidecar_path = import_dir / f"{target_path.stem}.provenance.json"
    prompt_path = import_dir / f"{target_path.stem}.prompt.txt"
    if prompt:
        prompt_path.write_text(prompt + "\n", encoding="utf-8")
    sidecar = {
        "schema": AUTO_STUDIO_IMPORT_SCHEMA,
        "runId": run_id,
        "sceneId": scene_id,
        "provider": provider,
        "prompt": prompt,
        "handoffTaskId": handoff_task_id,
        "sourceSurface": source_surface,
        "operatorNote": operator_note,
        "importTime": datetime.now().isoformat(timespec="seconds"),
        "proofMode": proof_mode,
        "fileName": target_name,
        "mimeType": mime_type,
        "sourcePath": relative_source,
        "browserControlDevRail": False,
    }
    _write_json(sidecar_path, sidecar)
    relative_sidecar = _relative_project_path(sidecar_path, resolved_project_root)
    relative_prompt = _relative_project_path(prompt_path, resolved_project_root) if prompt else ""
    asset = {
        "sceneId": scene_id,
        "role": "visual",
        "fileName": target_name,
        "mimeType": mime_type,
        "sourcePath": relative_source,
        "previewUrl": _local_preview_url(relative_source, mime_type),
        "provider": provider,
        "sourceProvider": provider,
        "sourceOrigin": "operator-local-import",
        "sourceLabel": f"{provider} operator import",
        "kind": "video" if mime_type == "video/mp4" else "image",
        "operatorOwned": True,
        "sourceGenerator": "operator-handoff",
        "sourceGeneratorRequestPath": relative_sidecar,
        "sourceGeneratorPromptPath": relative_prompt,
        "provenancePath": relative_sidecar,
        "handoffTaskId": handoff_task_id,
    }

    run, run_path = _load_run_record(resolved_project_root, run_id)
    updated_run = None
    if run:
        pipeline = run.setdefault("assetPipeline", {})
        imported_assets = pipeline.setdefault("importedSceneAssets", [])
        imported_assets.append(asset)
        for item in pipeline.get("handoffQueue") or []:
            if not isinstance(item, dict):
                continue
            if str(item.get("taskId") or "") == handoff_task_id or str(item.get("sceneId") or "") == scene_id:
                item["status"] = "imported"
                item["importedAssetPath"] = relative_source
                item["provenancePath"] = relative_sidecar
                item["updatedAt"] = sidecar["importTime"]
        for scene in run.get("draftScenes") or []:
            if isinstance(scene, dict) and str(scene.get("sceneId") or "") == scene_id:
                scene["_server_asset_path"] = relative_source
                scene["_server_asset_mime"] = mime_type
                scene["_upload_name"] = target_name
                scene["_upload_kind"] = "video" if mime_type == "video/mp4" else "image"
                scene["handoff_status"] = "imported"
                scene["handoff_provenance_path"] = relative_sidecar
        draft_result = run.get("draftResult") if isinstance(run.get("draftResult"), dict) else {}
        for scene in draft_result.get("scenes") or []:
            if isinstance(scene, dict):
                candidate_scene_id = str(scene.get("sceneId") or f"scene-{int(scene.get('scene_num') or 0):02d}")
                if candidate_scene_id == scene_id:
                    scene["_server_asset_path"] = relative_source
                    scene["_server_asset_mime"] = mime_type
                    scene["_upload_name"] = target_name
                    scene["_upload_kind"] = "video" if mime_type == "video/mp4" else "image"
                    scene["has_image"] = True
                    scene["handoff_status"] = "imported"
                    scene["handoff_provenance_path"] = relative_sidecar
        draft_scenes = [scene for scene in run.get("draftScenes") or [] if isinstance(scene, dict)]
        provider_contract = pipeline.get("selectedProvider") if isinstance(pipeline.get("selectedProvider"), dict) else {}
        queue = [item for item in pipeline.get("handoffQueue") or [] if isinstance(item, dict)]
        scene_assets = [item for item in imported_assets if isinstance(item, dict)]
        pipeline["renderReadiness"] = _render_readiness(
            draft_scenes,
            provider=provider_contract,
            scene_assets=scene_assets,
            handoff_queue=queue,
        )
        _write_json(run_path, run)
        updated_run = run

    return {
        "ok": True,
        "schema": AUTO_STUDIO_IMPORT_SCHEMA,
        "runId": run_id,
        "sceneId": scene_id,
        "asset": asset,
        "provenancePath": relative_sidecar,
        "sidecar": sidecar,
        "run": updated_run,
    }


def load_latest_auto_studio(project_root: str | Path = ".") -> dict[str, Any]:
    resolved_project_root = Path(project_root).resolve()
    latest_path = resolved_project_root / "storage" / "auto-studio" / "latest.json"
    if not latest_path.exists():
        return {"ok": True, "schema": AUTO_STUDIO_LATEST_SCHEMA, "latest": None}
    try:
        latest = json.loads(latest_path.read_text(encoding="utf-8"))
        run_path = Path(str(latest.get("runPath") or ""))
        run = json.loads(run_path.read_text(encoding="utf-8")) if run_path.exists() else None
    except (OSError, json.JSONDecodeError):
        return {"ok": False, "schema": AUTO_STUDIO_LATEST_SCHEMA, "error": "latest-run-unreadable"}
    return {"ok": True, "schema": AUTO_STUDIO_LATEST_SCHEMA, "latest": latest, "run": run}


def run_auto_studio(payload: dict[str, Any], project_root: str | Path = ".") -> dict[str, Any]:
    payload = payload if isinstance(payload, dict) else {}
    resolved_project_root = Path(project_root).resolve()
    seed = _safe_text(payload.get("seed"), "", 180)
    template_type = _safe_text(payload.get("templateType"), "news_explainer", 80)
    tone = _safe_text(payload.get("tone"), "casual_heyo", 80)
    lang = _safe_text(payload.get("lang"), "ko", 8)
    target_duration = _safe_text(payload.get("targetDuration"), "30s", 20)
    render_mode = _safe_text(payload.get("renderMode"), "draft", 20)
    if render_mode not in {"draft", "smoke"}:
        render_mode = "draft"
    limit = _int_payload(payload, "limit", 3, minimum=1, maximum=6)
    generate_assets = _bool_payload(payload, "generateAssets", True)

    discovery = build_hot_topic_candidates(seed, limit=limit)
    candidate = _select_candidate(discovery, payload)
    creator_prompt = _creator_prompt(candidate, {**payload, "targetDuration": target_duration})
    registry = build_asset_provider_registry(resolved_project_root)
    requested_provider = _safe_text(payload.get("assetProvider"), DEFAULT_ASSET_PROVIDER, 80)
    provider = _provider_by_key(registry, requested_provider)
    provider_warning = ""

    scenes, planner_source = generate_scenes_llm(
        creator_prompt["topicPrompt"],
        lang,
        template_type,
        tone,
        target_duration=target_duration,
        custom_instruction=creator_prompt["customInstruction"],
    )
    wrap_narration(scenes)
    draft_scenes = [
        _draft_scene(scene, index, provider=provider, creator_prompt=creator_prompt)
        for index, scene in enumerate(scenes)
    ]
    scene_count = creator_prompt["sceneCount"]
    if len(draft_scenes) > scene_count:
        draft_scenes = draft_scenes[:scene_count]
    handoff_queue = _build_handoff_queue(draft_scenes, provider)
    queue_by_scene = {str(item["sceneId"]): item for item in handoff_queue}
    for scene in draft_scenes:
        task = queue_by_scene.get(str(scene.get("sceneId") or ""))
        if not task:
            continue
        scene["handoff_task_id"] = task["taskId"]
        scene["handoff_expected_file"] = task["expectedFileName"]
        scene["handoff_target_url"] = task["targetUrl"]
        scene["handoff_output_kind"] = task["outputKind"]
    total_duration = sum(float(scene.get("duration") or 4.0) for scene in draft_scenes)
    scene_assets, generated_assets, asset_warnings = _generated_scene_assets(
        draft_scenes,
        provider=provider,
        project_root=resolved_project_root,
        generate_assets=generate_assets,
    )
    if provider_warning:
        asset_warnings.insert(0, provider_warning)

    run_id = f"auto-studio-{_now_stamp()}-{_slug(str(candidate.get('title') or seed or DEFAULT_DISCOVERY_SEED))}"
    save_payload = save_project_bundle(
        prompt=creator_prompt["topicPrompt"],
        budget_mode="free",
        availability=ProviderAvailability(veo3=False, premium_enabled=False),
        planner_mode="sample",
        project_id=run_id,
        project_root=resolved_project_root,
        scene_assets=scene_assets,
        provider_overrides=_provider_overrides_for(provider, draft_scenes),
        draft_scenes=draft_scenes,
        subtitle_style=_safe_text(payload.get("subtitleStyle"), "", 80),
        bgm_enabled=_bool_payload(payload, "bgmEnabled", True),
        template_type=template_type,
    )

    render_readiness = _render_readiness(
        draft_scenes,
        provider=provider,
        scene_assets=scene_assets,
        handoff_queue=handoff_queue,
    )
    render_result = None
    if render_mode == "smoke" and render_readiness["renderReady"]:
        from worker.render.compose import compose_smoke_render

        render = compose_smoke_render(save_payload["saveResult"]["manifestPath"], project_root=resolved_project_root)
        render_result = render.to_dict()
    elif render_mode == "smoke" and not render_readiness["renderReady"]:
        asset_warnings.insert(0, "Render blocked: selected handoff provider needs local imported asset proof for every queued scene.")

    status = "manual-handoff-required" if provider.get("requiresOperatorProof") else "draft-ready"
    if render_result:
        status = "render-ready" if render_result.get("ok") else "render-blocked"
    elif not render_readiness["renderReady"] and render_mode == "smoke":
        status = "render-blocked"
    result = {
        "ok": True,
        "schema": AUTO_STUDIO_SCHEMA,
        "runId": run_id,
        "status": status,
        "publishReady": False,
        "releaseBoundary": "Auto Studio output is draft-ready/render-ready only. Publish-ready still requires source review, phone review, and platform metadata.",
        "seed": seed or DEFAULT_DISCOVERY_SEED,
        "discovery": discovery,
        "selectedCandidate": candidate,
        "creatorPrompt": creator_prompt,
        "assetPipeline": {
            "selectedProvider": provider,
            "registry": registry,
            "generatedAssets": generated_assets,
            "sceneAssetsAttached": len(scene_assets),
            "importedSceneAssets": [],
            "handoffQueue": handoff_queue,
            "renderReadiness": render_readiness,
            "warnings": asset_warnings,
            "futureProviderSlots": ["seedance", "custom-external"],
        },
        "draftScenes": draft_scenes,
        "draftResult": _draft_result(
            draft_scenes,
            template_type=template_type,
            total_duration=total_duration,
            message="Auto Studio draft ready",
        ),
        "projectSave": save_payload,
        "renderResult": render_result,
        "metrics": {
            "candidateCount": len(discovery.get("candidates", []) or []),
            "sceneCount": len(draft_scenes),
            "generatedAssetCount": len([item for item in generated_assets if item.get("imageUrl")]),
            "attachedSceneAssetCount": len(scene_assets),
            "paidProviderUsage": 0,
            "plannerSource": planner_source,
        },
        "nextActions": [
            "Review and edit scene narration, image prompts, and source intent in the dashboard.",
            "If Grok is selected, create the Grok handoff packet and import original MP4 proof before render/publish.",
            "Use Edit to run a draft MP4 render, then Review for phone/source proof.",
        ],
    }
    run_path, latest_path = _write_run_record(resolved_project_root, result)
    result["runPath"] = run_path
    result["latestPath"] = latest_path
    return result
