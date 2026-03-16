from __future__ import annotations

import argparse
import json
from dataclasses import asdict

from worker.media.model_router import ProviderAvailability, route_project_plan, summarize_cost
from worker.planner.sample_plan import build_sample_project_plan


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate a sample project plan and route its scenes.")
    parser.add_argument("--prompt", required=True, help="Prompt to convert into a sample project plan")
    parser.add_argument(
        "--budget-mode",
        default="free",
        choices=["free", "standard", "premium"],
        help="Budget mode to apply to the sample plan",
    )
    parser.add_argument("--sora2", action="store_true", help="Enable Sora 2 premium routing")
    parser.add_argument("--veo3", action="store_true", help="Enable Veo 3 premium routing")
    return parser


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()

    plan = build_sample_project_plan(args.prompt, budget_mode=args.budget_mode)
    availability = ProviderAvailability(
        sora2=args.sora2,
        veo3=args.veo3,
        premium_enabled=args.sora2 or args.veo3,
    )
    decisions = route_project_plan(plan, availability)

    payload = {
        "plan": plan.to_dict(),
        "routes": [decision.to_dict() for decision in decisions],
        "estimatedTotalCostUsd": summarize_cost(decisions),
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
