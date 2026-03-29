from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from worker.media.adapters import (
    AdapterExecutionContext,
    MediaAdapterStatus,
    MediaGenerationResult,
    probe_local_media_adapters,
    run_local_media_adapter,
)


@dataclass(slots=True)
class LocalMediaPlanSummary:
    totalScenes: int
    uploadedVisuals: int
    generationRequired: int
    imageGenerations: int
    videoGenerations: int
    uploadedAudio: int
    autoAudioFallbacks: int

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(slots=True)
class LocalMediaScenePlan:
    sceneId: str
    title: str
    visualKind: str
    visualSource: str
    visualAdapter: str | None
    visualOutputPath: str
    audioSource: str
    detail: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(slots=True)
class LocalMediaPlan:
    projectId: str
    manifestPath: str
    planPath: str
    generatedAt: str
    summary: LocalMediaPlanSummary
    adapters: dict[str, MediaAdapterStatus]
    scenes: list[LocalMediaScenePlan]

    def to_dict(self) -> dict:
        return {
            "projectId": self.projectId,
            "manifestPath": self.manifestPath,
            "planPath": self.planPath,
            "generatedAt": self.generatedAt,
            "summary": self.summary.to_dict(),
            "adapters": {
                key: status.to_dict()
                for key, status in self.adapters.items()
            },
            "scenes": [scene.to_dict() for scene in self.scenes],
        }


def _asset_lookup(manifest: dict, scene_id: str, role: str) -> dict:
    for asset in manifest["assets"]:
        if asset["sceneId"] == scene_id and asset["role"] == role:
            return asset
    raise KeyError(f"Missing manifest asset for scene={scene_id} role={role}")


def _visual_adapter_key(
    scene: dict,
    adapters: dict[str, MediaAdapterStatus] | None = None,
    override: str | None = None,
) -> str:
    """Choose the visual adapter key for a scene.

    If *override* is set and is a known adapter, use it directly.
    Otherwise prefers ready adapters: for images, tries imagen3 → pexels.
    For video, tries wan → sora2 → veo3.
    """
    if override:
        from worker.media.adapters import ADAPTER_CONFIG
        cfg = ADAPTER_CONFIG.get(override)
        if cfg and cfg["category"] in ("image", "video"):
            return override

    if scene.get("visualKind") == "image":
        if adapters:
            for candidate in ("imagen", "pexels"):
                status = adapters.get(candidate)
                if status and status.ready:
                    return candidate
        return "imagen"  # default image provider (Imagen 4 via Gemini API)
    else:
        if adapters:
            for candidate in ("wan", "sora2", "veo3"):
                status = adapters.get(candidate)
                if status and status.ready:
                    return candidate
        return "wan"


def _plan_path(project_root: Path, manifest: dict) -> Path:
    return project_root / manifest["cacheDir"] / "local-media-plan.json"


def _resolved_source(project_root: Path, relative_path: str | None) -> Path | None:
    if not relative_path:
        return None
    candidate = project_root / relative_path
    return candidate if candidate.exists() else None


def build_local_media_plan(
    manifest: dict,
    manifest_path: Path | str,
    project_root: Path | str = ".",
) -> LocalMediaPlan:
    resolved_project_root = Path(project_root).resolve()
    resolved_manifest_path = Path(manifest_path).resolve()
    adapters = probe_local_media_adapters(resolved_project_root)

    scenes: list[LocalMediaScenePlan] = []
    uploaded_visuals = 0
    generation_required = 0
    image_generations = 0
    video_generations = 0
    uploaded_audio = 0
    auto_audio_fallbacks = 0

    for scene in manifest["scenes"]:
        visual_asset = _asset_lookup(manifest, scene["sceneId"], "visual")
        audio_asset = _asset_lookup(manifest, scene["sceneId"], "audio")
        uploaded_visual = visual_asset.get("sourceOrigin") == "uploaded" and _resolved_source(
            resolved_project_root,
            visual_asset.get("sourcePath"),
        )
        uploaded_audio_asset = audio_asset.get("sourceOrigin") == "uploaded" and _resolved_source(
            resolved_project_root,
            audio_asset.get("sourcePath"),
        )

        if uploaded_visual:
            visual_source = "uploaded"
            visual_adapter = None
            detail = str(uploaded_visual)
            uploaded_visuals += 1
        else:
            visual_adapter = _visual_adapter_key(scene, adapters)
            visual_source = "local-generator"
            detail = adapters.get(visual_adapter, next(iter(adapters.values()))).detail if adapters else "no adapters"
            generation_required += 1
            if scene.get("visualKind") == "image":
                image_generations += 1
            else:
                video_generations += 1

        if uploaded_audio_asset:
            audio_source = "uploaded"
            uploaded_audio += 1
        else:
            audio_source = "windows-tts"
            auto_audio_fallbacks += 1

        scenes.append(
            LocalMediaScenePlan(
                sceneId=scene["sceneId"],
                title=scene["title"],
                visualKind=scene["visualKind"],
                visualSource=visual_source,
                visualAdapter=visual_adapter,
                visualOutputPath=str((resolved_project_root / visual_asset["outputPath"]).resolve()),
                audioSource=audio_source,
                detail=detail,
            )
        )

    return LocalMediaPlan(
        projectId=manifest["projectId"],
        manifestPath=str(resolved_manifest_path),
        planPath=str(_plan_path(resolved_project_root, manifest).resolve()),
        generatedAt=datetime.now().isoformat(timespec="seconds"),
        summary=LocalMediaPlanSummary(
            totalScenes=len(manifest["scenes"]),
            uploadedVisuals=uploaded_visuals,
            generationRequired=generation_required,
            imageGenerations=image_generations,
            videoGenerations=video_generations,
            uploadedAudio=uploaded_audio,
            autoAudioFallbacks=auto_audio_fallbacks,
        ),
        adapters=adapters,
        scenes=scenes,
    )


def write_local_media_plan(
    manifest: dict,
    manifest_path: Path | str,
    project_root: Path | str = ".",
) -> LocalMediaPlan:
    plan = build_local_media_plan(
        manifest=manifest,
        manifest_path=manifest_path,
        project_root=project_root,
    )
    target_path = Path(plan.planPath)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_text(json.dumps(plan.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    return plan


def generate_local_visual_asset(
    manifest: dict,
    manifest_path: Path | str,
    scene: dict,
    project_root: Path | str = ".",
    adapters: dict[str, MediaAdapterStatus] | None = None,
    provider_override: str | None = None,
) -> MediaGenerationResult:
    resolved_project_root = Path(project_root).resolve()
    resolved_manifest_path = Path(manifest_path).resolve()
    visual_asset = _asset_lookup(manifest, scene["sceneId"], "visual")
    source_visual = _resolved_source(resolved_project_root, visual_asset.get("sourcePath"))
    scene_cache_dir = resolved_project_root / scene["cacheDir"]

    if visual_asset.get("sourceOrigin") == "uploaded" and source_visual:
        return MediaGenerationResult(
            sceneId=scene["sceneId"],
            sceneTitle=scene["title"],
            adapterKey=None,
            mode="uploaded",
            outputKind=scene["visualKind"],
            status="uploaded",
            outputPath=str(source_visual),
            detail=f"uploaded asset will be used: {source_visual}",
            attempted=False,
            succeeded=None,
        )

    adapter_statuses = adapters or probe_local_media_adapters(resolved_project_root)
    adapter_key = _visual_adapter_key(scene, adapter_statuses, override=provider_override)
    adapter_status = adapter_statuses.get(adapter_key)
    if not adapter_status:
        # Fallback to first available adapter status for this category
        fallback_key = "imagen" if scene.get("visualKind") == "image" else "wan"
        adapter_status = adapter_statuses.get(fallback_key, next(iter(adapter_statuses.values())))
    prompt_path = scene_cache_dir / f"{scene['sceneId']}.{adapter_key}.prompt.txt"
    request_path = scene_cache_dir / f"{scene['sceneId']}.{adapter_key}.request.json"
    log_path = scene_cache_dir / f"{scene['sceneId']}.{adapter_key}.command.log"
    output_path = resolved_project_root / visual_asset["outputPath"]

    scene_cache_dir.mkdir(parents=True, exist_ok=True)
    prompt_path.write_text(
        "\n".join(
            [
                scene["title"],
                "",
                visual_asset["prompt"],
                "",
                f"Duration: {scene['durationSec']:.2f}",
                f"Route: {scene['route']}",
                f"Output: {output_path}",
            ]
        ),
        encoding="utf-8",
    )
    request_payload = {
        "projectId": manifest["projectId"],
        "sceneId": scene["sceneId"],
        "title": scene["title"],
        "prompt": visual_asset["prompt"],
        "visualKind": scene["visualKind"],
        "durationSec": scene["durationSec"],
        "route": scene["route"],
        "manifestPath": str(resolved_manifest_path),
        "outputPath": str(output_path),
        "cacheDir": str(scene_cache_dir),
        "adapter": adapter_key,
        "adapterStatus": adapter_status.to_dict(),
    }
    request_path.write_text(json.dumps(request_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    return run_local_media_adapter(
        adapter_key,
        AdapterExecutionContext(
            adapterKey=adapter_key,
            sceneId=scene["sceneId"],
            sceneTitle=scene["title"],
            prompt=visual_asset["prompt"],
            durationSec=scene["durationSec"],
            projectRoot=str(resolved_project_root),
            cacheDir=str(scene_cache_dir),
            route=scene["route"],
            manifestPath=str(resolved_manifest_path),
            promptPath=str(prompt_path),
            requestPath=str(request_path),
            logPath=str(log_path),
            outputPath=str(output_path),
        ),
        project_root=resolved_project_root,
    )


def summarize_generation_results(results: list[MediaGenerationResult]) -> dict:
    summary = {
        "totalScenes": len(results),
        "uploaded": 0,
        "generated": 0,
        "placeholder": 0,
        "attempted": 0,
        "succeeded": 0,
        "failed": 0,
    }

    for result in results:
        status = result.status if result.status in {"uploaded", "generated", "placeholder"} else "placeholder"
        summary[status] += 1
        if result.attempted:
            summary["attempted"] += 1
        if result.succeeded is True:
            summary["succeeded"] += 1
        if result.succeeded is False:
            summary["failed"] += 1

    return summary


def write_local_media_report(
    render_dir: Path | str,
    plan: LocalMediaPlan,
    results: list[MediaGenerationResult],
) -> str:
    resolved_render_dir = Path(render_dir).resolve()
    resolved_render_dir.mkdir(parents=True, exist_ok=True)
    report_path = resolved_render_dir / "local-media-report.json"
    payload = {
        "projectId": plan.projectId,
        "planPath": plan.planPath,
        "generatedAt": datetime.now().isoformat(timespec="seconds"),
        "summary": summarize_generation_results(results),
        "scenes": [result.to_dict() for result in results],
    }
    report_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(report_path)
