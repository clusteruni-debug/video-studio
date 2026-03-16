from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

from worker.media.model_router import ProviderAvailability, route_project_plan, summarize_cost
from worker.planner.sample_plan import build_sample_project_plan
from worker.render.render_manifest import build_render_manifest, slugify


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Save a planned project and render manifest under storage/.")
    parser.add_argument("--prompt", required=True, help="Prompt to convert into a sample project plan")
    parser.add_argument(
        "--budget-mode",
        default="free",
        choices=["free", "standard", "premium"],
        help="Budget mode to apply to the project plan",
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


def save_project_bundle(
    prompt: str,
    budget_mode: str,
    availability: ProviderAvailability,
    project_id: str | None = None,
    project_root: str | Path = ".",
) -> dict:
    plan = build_sample_project_plan(prompt, budget_mode=budget_mode)
    decisions = route_project_plan(plan, availability)
    estimated_cost = summarize_cost(decisions)

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    resolved_project_id = project_id or f"{timestamp}-{slugify(plan.title)}"
    manifest = build_render_manifest(
        plan=plan,
        decisions=decisions,
        project_id=resolved_project_id,
        estimated_cost_usd=estimated_cost,
    )

    resolved_project_root = Path(project_root).resolve()
    input_dir = resolved_project_root / manifest.inputDir
    cache_dir = resolved_project_root / manifest.cacheDir
    render_dir = resolved_project_root / manifest.renderDir
    input_dir.mkdir(parents=True, exist_ok=True)
    cache_dir.mkdir(parents=True, exist_ok=True)
    render_dir.mkdir(parents=True, exist_ok=True)

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

    plan_path.write_text(json.dumps(plan.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    routes_path.write_text(
        json.dumps([decision.to_dict() for decision in decisions], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    manifest_path.write_text(json.dumps(manifest.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    notes_path.write_text(
        "\n".join(
            [
                f"project_id: {resolved_project_id}",
                f"input_dir: {input_dir}",
                f"cache_dir: {cache_dir}",
                f"render_dir: {render_dir}",
                f"compose_command: {manifest.composeCommandPreview}",
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
    }
    return {
        "saveResult": payload,
        "plan": plan.to_dict(),
        "routes": [decision.to_dict() for decision in decisions],
        "manifest": manifest.to_dict(),
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
        project_id=args.project_id,
        project_root=args.project_root,
    )
    print(json.dumps(payload["saveResult"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
