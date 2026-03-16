from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal

from worker.planner.sample_plan import ProjectPlan, SceneSpec

Route = Literal["local", "sora2", "veo3"]

SORA2_RATE_PER_SEC = 0.10
VEO3_FAST_RATE_PER_SEC = 0.15


@dataclass(slots=True)
class ProviderAvailability:
    sora2: bool = False
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

    if scene.humanRealism >= 4 and availability.sora2:
        return RouteDecision(
            scene.id,
            "sora2",
            round(scene.durationSec * SORA2_RATE_PER_SEC, 2),
            "human realism requirement justifies premium video route",
        )

    return RouteDecision(scene.id, "local", 0.0, "local fallback")


def route_project_plan(plan: ProjectPlan, availability: ProviderAvailability) -> list[RouteDecision]:
    return [choose_route(scene, plan.budgetMode, availability) for scene in plan.scenes]


def summarize_cost(decisions: list[RouteDecision]) -> float:
    return round(sum(item.estimatedCostUsd for item in decisions), 2)
