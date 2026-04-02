from __future__ import annotations

import argparse
import base64
import json
import mimetypes
from datetime import datetime
from pathlib import Path

from worker.media.runtime import write_local_media_plan
from worker.media.model_router import ProviderAvailability, route_project_plan, summarize_cost
from worker.planner.ollama_planner import build_project_plan
from worker.render.render_manifest import build_render_manifest, slugify


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Save a planned project and render manifest under storage/.")
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
        choices=["auto", "gemini", "sample"],
        help="Planner backend preference. auto uses Gemini first and falls back safely.",
    )
    parser.add_argument("--sora2", action="store_true", help="Enable Sora 2 premium routing")
    parser.add_argument("--veo3", action="store_true", help="Enable Veo 3 premium routing")
    parser.add_argument(
        "--project-id",
        help="Optional explicit project id to reuse an existing storage target",
    )
    parser.add_argument(
        "--project-root",
        default=".",
        help="Project root directory where storage/ lives",
    )
    return parser


def _asset_by_scene_and_role(manifest, scene_id: str, role: str):
    for asset in manifest.assets:
        if asset.sceneId == scene_id and asset.role == role:
            return asset
    raise KeyError(f"Missing manifest asset for scene={scene_id} role={role}")


def _scene_by_id(manifest, scene_id: str):
    for scene in manifest.scenes:
        if scene.sceneId == scene_id:
            return scene
    raise KeyError(f"Missing manifest scene for scene={scene_id}")


def _safe_upload_filename(file_name: str, role: str) -> str:
    original = Path(file_name or f"{role}-asset").name
    suffix = Path(original).suffix.lower()
    stem = slugify(Path(original).stem or f"{role}-asset")
    fallback_suffix = ".png" if role == "visual" else ".wav"
    return f"{stem or f'{role}-asset'}{suffix or fallback_suffix}"


def _guess_visual_kind(file_name: str, mime_type: str | None) -> str:
    mime = (mime_type or mimetypes.guess_type(file_name)[0] or "").lower()
    suffix = Path(file_name).suffix.lower()
    if mime.startswith("video/") or suffix in {".mp4", ".mov", ".webm", ".mkv"}:
        return "video"
    return "image"


def _apply_scene_assets(
    manifest,
    scene_assets: list[dict] | None,
    project_root: Path,
    input_dir: Path,
) -> list[dict]:
    saved_uploads: list[dict] = []

    for item in scene_assets or []:
        scene_id = str(item.get("sceneId", "")).strip()
        role = str(item.get("role", "")).strip()
        encoded = str(item.get("base64", "")).strip()
        file_name = str(item.get("fileName", "")).strip()
        mime_type = str(item.get("mimeType", "")).strip() or None

        if not scene_id or role not in {"visual", "audio", "sfx"} or not encoded or not file_name:
            continue

        asset = _asset_by_scene_and_role(manifest, scene_id, role)
        scene = _scene_by_id(manifest, scene_id)

        upload_dir = input_dir / "uploads" / scene_id
        upload_dir.mkdir(parents=True, exist_ok=True)
        target_file = upload_dir / _safe_upload_filename(file_name, role)
        target_file.write_bytes(base64.b64decode(encoded))
        relative_path = target_file.relative_to(project_root).as_posix()

        asset.provider = "upload"
        asset.sourceOrigin = "uploaded"
        asset.sourcePath = relative_path
        asset.sourceLabel = file_name
        asset.sourceMimeType = mime_type

        if role == "visual":
            visual_kind = _guess_visual_kind(file_name, mime_type)
            asset.kind = visual_kind
            asset.prompt = f"Uploaded visual asset: {file_name}"
            asset.outputPath = relative_path
            scene.visualKind = visual_kind
        elif role == "sfx":
            asset.kind = "uploaded-sfx"
            asset.prompt = f"Uploaded SFX asset: {file_name}"
            asset.outputPath = relative_path
        else:
            asset.kind = "uploaded-audio"
            asset.prompt = f"Uploaded audio asset: {file_name}"
            scene.audioKind = "native"

        saved_uploads.append(
            {
                "sceneId": scene_id,
                "role": role,
                "fileName": file_name,
                "storedPath": relative_path,
                "mimeType": mime_type,
            }
        )

    return saved_uploads


def save_project_bundle(
    prompt: str,
    budget_mode: str,
    availability: ProviderAvailability,
    planner_mode: str = "auto",
    project_id: str | None = None,
    project_root: str | Path = ".",
    scene_assets: list[dict] | None = None,
    provider_overrides: dict[str, str] | None = None,
) -> dict:
    plan, planner = build_project_plan(
        prompt,
        budget_mode=budget_mode,
        planner_mode=planner_mode,
    )
    decisions = route_project_plan(plan, availability)
    estimated_cost = summarize_cost(decisions)

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    resolved_project_id = project_id or f"{timestamp}-{slugify(plan.title)}"
    manifest = build_render_manifest(
        plan=plan,
        decisions=decisions,
        project_id=resolved_project_id,
        estimated_cost_usd=estimated_cost,
        provider_overrides=provider_overrides,
    )

    resolved_project_root = Path(project_root).resolve()
    input_dir = resolved_project_root / manifest.inputDir
    cache_dir = resolved_project_root / manifest.cacheDir
    render_dir = resolved_project_root / manifest.renderDir
    input_dir.mkdir(parents=True, exist_ok=True)
    cache_dir.mkdir(parents=True, exist_ok=True)
    render_dir.mkdir(parents=True, exist_ok=True)

    saved_uploads = _apply_scene_assets(
        manifest=manifest,
        scene_assets=scene_assets,
        project_root=resolved_project_root,
        input_dir=input_dir,
    )

    for scene in plan.scenes:
        scene_dir = cache_dir / scene.id
        scene_dir.mkdir(parents=True, exist_ok=True)
        prompt_file = input_dir / f"{scene.id}.prompt.txt"
        prompt_file.write_text(
            f"{scene.title}\n\n{scene.prompt}\n\nSubtitle: {scene.subtitleText}\n",
            encoding="utf-8",
        )

    plan_path = input_dir / "project-plan.json"
    routes_path = input_dir / "routes.json"
    manifest_path = input_dir / "render-manifest.json"
    notes_path = input_dir / "operator-notes.txt"

    plan_dict = plan.to_dict()
    routes_dict = [decision.to_dict() for decision in decisions]
    manifest_dict = manifest.to_dict()

    plan_path.write_text(json.dumps(plan_dict, ensure_ascii=False, indent=2), encoding="utf-8")
    routes_path.write_text(
        json.dumps(routes_dict, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    manifest_path.write_text(json.dumps(manifest_dict, ensure_ascii=False, indent=2), encoding="utf-8")
    local_media_plan = write_local_media_plan(
        manifest=manifest_dict,
        manifest_path=manifest_path,
        project_root=resolved_project_root,
    )
    notes_path.write_text(
        "\n".join(
            [
                f"project_id: {resolved_project_id}",
                f"input_dir: {input_dir}",
                f"cache_dir: {cache_dir}",
                f"render_dir: {render_dir}",
                f"planner_backend: {planner.backend}",
                f"planner_model: {planner.model}",
                f"planner_detail: {planner.detail}",
                f"compose_command: {manifest.composeCommandPreview}",
                f"uploaded_assets: {len(saved_uploads)}",
                f"local_media_plan: {local_media_plan.planPath}",
                f"local_media_generation_required: {local_media_plan.summary.generationRequired}",
            ]
        ),
        encoding="utf-8",
    )

    payload = {
        "projectId": resolved_project_id,
        "inputDir": str(input_dir),
        "cacheDir": str(cache_dir),
        "renderDir": str(render_dir),
        "planPath": str(plan_path),
        "routesPath": str(routes_path),
        "manifestPath": str(manifest_path),
        "notesPath": str(notes_path),
        "estimatedTotalCostUsd": estimated_cost,
        "uploadedAssets": saved_uploads,
        "localMediaPlanPath": local_media_plan.planPath,
        "localMediaSummary": local_media_plan.summary.to_dict(),
    }
    return {
        "saveResult": payload,
        "planner": planner.to_dict(),
        "plan": plan_dict,
        "routes": routes_dict,
        "manifest": manifest_dict,
    }


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()

    availability = ProviderAvailability(
        sora2=args.sora2,
        veo3=args.veo3,
        premium_enabled=args.sora2 or args.veo3,
    )
    payload = save_project_bundle(
        prompt=args.prompt,
        budget_mode=args.budget_mode,
        availability=availability,
        planner_mode=args.planner_mode,
        project_id=args.project_id,
        project_root=args.project_root,
    )
    print(json.dumps(payload["saveResult"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
