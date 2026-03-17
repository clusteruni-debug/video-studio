from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

from worker.media.model_router import ProviderAvailability, RouteDecision, route_project_plan, summarize_cost
from worker.planner.ollama_planner import build_project_plan
from worker.planner.sample_plan import AspectRatio, ProjectPlan

RenderAssetRole = Literal["visual", "audio", "subtitle"]
VisualKind = Literal["image", "video"]
AudioKind = Literal["voiceover", "native", "none"]


@dataclass(slots=True)
class RenderAssetSpec:
    id: str
    sceneId: str
    role: RenderAssetRole
    provider: str
    kind: str
    prompt: str
    durationSec: float
    outputPath: str
    sourceOrigin: str | None = None
    sourcePath: str | None = None
    sourceLabel: str | None = None
    sourceMimeType: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(slots=True)
class RenderSceneSpec:
    sceneId: str
    title: str
    startSec: float
    endSec: float
    durationSec: float
    route: str
    visualKind: VisualKind
    audioKind: AudioKind
    subtitleText: str
    cacheDir: str
    assetIds: list[str]

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(slots=True)
class RenderManifest:
    version: int
    projectId: str
    title: str
    aspectRatio: AspectRatio
    storageRoot: str
    inputDir: str
    cacheDir: str
    renderDir: str
    concatFilePath: str
    subtitleFilePath: str
    outputPath: str
    totalDurationSec: float
    estimatedCostUsd: float
    scenes: list[RenderSceneSpec]
    assets: list[RenderAssetSpec]
    composeCommandPreview: str

    def to_dict(self) -> dict:
        return {
            **asdict(self),
            "scenes": [scene.to_dict() for scene in self.scenes],
            "assets": [asset.to_dict() for asset in self.assets],
        }


def slugify(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return normalized[:48] or "video-project"


def _visual_kind_for_scene(can_use_still_image: bool, route: str) -> VisualKind:
    if route == "local" and can_use_still_image:
        return "image"
    return "video"


def _audio_kind_for_scene(route: str) -> AudioKind:
    if route == "veo3":
        return "native"
    return "voiceover"


def build_render_manifest(
    plan: ProjectPlan,
    decisions: list[RouteDecision],
    project_id: str,
    estimated_cost_usd: float,
    storage_root: str = "storage",
) -> RenderManifest:
    title_slug = slugify(plan.title)
    input_dir = f"{storage_root}/inputs/{project_id}"
    cache_dir = f"{storage_root}/cache/{project_id}"
    render_dir = f"{storage_root}/renders/{project_id}"
    concat_file_path = f"{render_dir}/concat.txt"
    subtitle_file_path = f"{render_dir}/captions.srt"
    output_path = f"{render_dir}/{title_slug}.mp4"

    cursor = 0.0
    assets: list[RenderAssetSpec] = []
    scenes: list[RenderSceneSpec] = []

    route_by_scene_id = {decision.sceneId: decision for decision in decisions}

    for scene in plan.scenes:
        decision = route_by_scene_id.get(scene.id)
        route = decision.route if decision else "local"
        scene_cache_dir = f"{cache_dir}/{scene.id}"
        visual_kind = _visual_kind_for_scene(scene.canUseStillImage, route)
        audio_kind = _audio_kind_for_scene(route)
        asset_ids: list[str] = []

        visual_asset_id = f"{scene.id}-visual"
        assets.append(
            RenderAssetSpec(
                id=visual_asset_id,
                sceneId=scene.id,
                role="visual",
                provider=route,
                kind=visual_kind,
                prompt=scene.prompt,
                durationSec=round(scene.durationSec, 2),
                outputPath=f"{scene_cache_dir}/{scene.id}.{'png' if visual_kind == 'image' else 'mp4'}",
            )
        )
        asset_ids.append(visual_asset_id)

        audio_asset_id = f"{scene.id}-audio"
        assets.append(
            RenderAssetSpec(
                id=audio_asset_id,
                sceneId=scene.id,
                role="audio",
                provider=route if audio_kind == "native" else "piper",
                kind=audio_kind,
                prompt=scene.subtitleText,
                durationSec=round(scene.durationSec, 2),
                outputPath=f"{scene_cache_dir}/{scene.id}.wav",
            )
        )
        asset_ids.append(audio_asset_id)

        subtitle_asset_id = f"{scene.id}-subtitle"
        assets.append(
            RenderAssetSpec(
                id=subtitle_asset_id,
                sceneId=scene.id,
                role="subtitle",
                provider="local",
                kind="srt-line",
                prompt=scene.subtitleText,
                durationSec=round(scene.durationSec, 2),
                outputPath=f"{scene_cache_dir}/{scene.id}.srt",
            )
        )
        asset_ids.append(subtitle_asset_id)

        start_sec = round(cursor, 2)
        cursor = round(cursor + scene.durationSec, 2)
        end_sec = round(cursor, 2)
        scenes.append(
            RenderSceneSpec(
                sceneId=scene.id,
                title=scene.title,
                startSec=start_sec,
                endSec=end_sec,
                durationSec=round(scene.durationSec, 2),
                route=route,
                visualKind=visual_kind,
                audioKind=audio_kind,
                subtitleText=scene.subtitleText,
                cacheDir=scene_cache_dir,
                assetIds=asset_ids,
            )
        )

    compose_command_preview = (
        f'ffmpeg -y -f concat -safe 0 -i "{concat_file_path}" '
        f'-vf "subtitles={subtitle_file_path},scale=1080:1920" -c:v libx264 -c:a aac "{output_path}"'
    )

    return RenderManifest(
        version=1,
        projectId=project_id,
        title=plan.title,
        aspectRatio=plan.aspectRatio,
        storageRoot=storage_root,
        inputDir=input_dir,
        cacheDir=cache_dir,
        renderDir=render_dir,
        concatFilePath=concat_file_path,
        subtitleFilePath=subtitle_file_path,
        outputPath=output_path,
        totalDurationSec=round(cursor, 2),
        estimatedCostUsd=round(estimated_cost_usd, 2),
        scenes=scenes,
        assets=assets,
        composeCommandPreview=compose_command_preview,
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build a local render manifest for a project plan.")
    parser.add_argument("--prompt", required=True, help="Prompt to convert into a project plan")
    parser.add_argument(
        "--budget-mode",
        default="free",
        choices=["free", "standard", "premium"],
        help="Budget mode to apply to the project plan",
    )
    parser.add_argument(
        "--planner-mode",
        default="auto",
        choices=["auto", "ollama", "sample"],
        help="Planner backend preference. auto uses Ollama first and falls back safely.",
    )
    parser.add_argument("--project-id", default="project-sample", help="Project id for storage and output paths")
    parser.add_argument("--storage-root", default="storage", help="Relative storage root to use in the manifest")
    parser.add_argument("--sora2", action="store_true", help="Enable Sora 2 premium routing")
    parser.add_argument("--veo3", action="store_true", help="Enable Veo 3 premium routing")
    return parser


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()

    plan, _planner = build_project_plan(
        args.prompt,
        budget_mode=args.budget_mode,
        planner_mode=args.planner_mode,
    )
    availability = ProviderAvailability(
        sora2=args.sora2,
        veo3=args.veo3,
        premium_enabled=args.sora2 or args.veo3,
    )
    decisions = route_project_plan(plan, availability)
    manifest = build_render_manifest(
        plan=plan,
        decisions=decisions,
        project_id=args.project_id,
        estimated_cost_usd=summarize_cost(decisions),
        storage_root=args.storage_root,
    )

    print(json.dumps(manifest.to_dict(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
