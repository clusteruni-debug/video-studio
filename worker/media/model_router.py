from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal

from worker.media.adapters import ADAPTER_CONFIG
from worker.media.provider_policy import paid_providers_allowed
from worker.planner.sample_plan import ProjectPlan, SceneSpec

# Sora 2 retired 2026-04 (see memory/project-video-studio-ollama.md).
Route = Literal["local", "veo3"]

# Single source of truth for the premium VEO3 rate lives in adapters.py
# (ADAPTER_CONFIG["veo3"]["costPerUnit"]). Deriving it here keeps the cost
# estimate from silently drifting away from the adapter registry.
VEO3_FAST_RATE_PER_SEC = float(ADAPTER_CONFIG["veo3"]["costPerUnit"])


@dataclass(slots=True)
class ProviderAvailability:
    veo3: bool = False
    premium_enabled: bool = False


@dataclass(slots=True)
class RouteDecision:
    sceneId: str
    route: Route
    estimatedCostUsd: float
    reason: str

    def to_dict(self) -> dict:
        return asdict(self)



def choose_route(scene: SceneSpec, budget_mode: str, availability: ProviderAvailability) -> RouteDecision:
    if not paid_providers_allowed():
        return RouteDecision(scene.id, "local", 0.0, "paid providers disabled by zero-paid policy")

    if budget_mode == "free" or not availability.premium_enabled:
        return RouteDecision(scene.id, "local", 0.0, "free-mode or premium disabled")

    if scene.priority <= 3:
        return RouteDecision(scene.id, "local", 0.0, "scene priority below premium threshold")

    if scene.nativeAudioNeed >= 5 and availability.veo3:
        return RouteDecision(
            scene.id,
            "veo3",
            round(scene.durationSec * VEO3_FAST_RATE_PER_SEC, 2),
            "audio-first premium scene",
        )

    return RouteDecision(scene.id, "local", 0.0, "local fallback")


def route_project_plan(plan: ProjectPlan, availability: ProviderAvailability) -> list[RouteDecision]:
    return [choose_route(scene, plan.budgetMode, availability) for scene in plan.scenes]


def summarize_cost(decisions: list[RouteDecision]) -> float:
    return round(sum(item.estimatedCostUsd for item in decisions), 2)
