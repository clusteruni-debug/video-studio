from __future__ import annotations

import argparse
import json
import logging
import os

from worker.media.model_router import ProviderAvailability, route_project_plan, summarize_cost
from worker.planner.ollama_planner import build_project_plan


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate a project plan and route its scenes.")
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
    parser.add_argument("--veo3", action="store_true", help="Enable Veo 3 premium routing")
    # Deprecated no-op retained so existing verify scripts and the Node bridge
    # still parse. Sora 2 was retired 2026-04; passing this flag has no effect.
    parser.add_argument("--sora2", action="store_true", help=argparse.SUPPRESS)
    return parser


def main() -> int:
    import sys
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stderr,  # keep stdout clean for JSON payload
    )
    parser = _build_parser()
    args = parser.parse_args()

    plan, planner = build_project_plan(
        args.prompt,
        budget_mode=args.budget_mode,
        planner_mode=args.planner_mode,
    )
    availability = ProviderAvailability(
        veo3=args.veo3,
        premium_enabled=bool(args.veo3),
        sora2=args.sora2,  # deprecated no-op
    )
    decisions = route_project_plan(plan, availability)

    payload = {
        "plan": plan.to_dict(),
        "planner": planner.to_dict(),
        "routes": [decision.to_dict() for decision in decisions],
        "estimatedTotalCostUsd": summarize_cost(decisions),
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
