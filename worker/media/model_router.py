from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal

from worker.media.adapters import ADAPTER_CONFIG
from worker.media.provider_policy import estimate_scene_cost
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


@dataclass(slots=True)
class SceneCostBreakdown:
    """Per-scene cost breakdown across all media categories."""
    sceneId: str
    image: float = 0.0
    video: float = 0.0
    tts: float = 0.0
    bgm: float = 0.0
    sfx: float = 0.0

    @property
    def total(self) -> float:
        return round(self.image + self.video + self.tts + self.bgm + self.sfx, 4)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["total"] = self.total
        return d


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


def estimate_scene_costs(
    scene_id: str,
    duration_sec: float,
    provider_selections: dict[str, str],
) -> SceneCostBreakdown:
    """Compute per-category cost for a single scene given its provider selections.

    Parameters
    ----------
    provider_selections : dict
        ``{category: provider_key}`` e.g. ``{"image": "pollinations", "tts": "edge-tts"}``
    """
    costs = SceneCostBreakdown(sceneId=scene_id)
    for category, provider_key in provider_selections.items():
        cost = estimate_scene_cost(category, provider_key, duration_sec=duration_sec)
        if hasattr(costs, category):
            setattr(costs, category, cost)
    return costs


def estimate_project_costs(
    scenes: list[dict],
    provider_selections: dict[str, dict[str, str]],
) -> dict:
    """Compute full project cost breakdown.

    Parameters
    ----------
    scenes : list of scene dicts (need sceneId and durationSec)
    provider_selections : ``{sceneId: {category: providerKey}}``

    Returns
    -------
    dict with total, perScene list, and category breakdown
    """
    breakdowns: list[SceneCostBreakdown] = []
    for scene in scenes:
        scene_id = scene.get("sceneId", "")
        duration_sec = scene.get("durationSec", 5.0)
        selections = provider_selections.get(scene_id, {})
        breakdown = estimate_scene_costs(scene_id, duration_sec, selections)
        breakdowns.append(breakdown)

    total = round(sum(b.total for b in breakdowns), 4)
    category_totals: dict[str, float] = {}
    for b in breakdowns:
        for cat in ("image", "video", "tts", "bgm", "sfx"):
            category_totals[cat] = category_totals.get(cat, 0.0) + getattr(b, cat)

    return {
        "total": total,
        "perScene": [b.to_dict() for b in breakdowns],
        "breakdown": {k: round(v, 4) for k, v in category_totals.items()},
    }
