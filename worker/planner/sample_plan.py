from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal

BudgetMode = Literal["free", "standard", "premium"]
RouteHint = Literal["local", "sora2", "veo3"]
AspectRatio = Literal["9:16"]


@dataclass(slots=True)
class SceneSpec:
    id: str
    title: str
    prompt: str
    durationSec: float
    priority: int
    humanRealism: int
    nativeAudioNeed: int
    canUseStillImage: bool
    subtitleText: str
    routeHint: RouteHint


@dataclass(slots=True)
class ProjectPlan:
    version: int
    title: str
    sourcePrompt: str
    aspectRatio: AspectRatio
    budgetMode: BudgetMode
    monthlyCapUsd: float
    scenes: list[SceneSpec]

    def to_dict(self) -> dict:
        return asdict(self)


def _default_monthly_cap(budget_mode: BudgetMode) -> float:
    if budget_mode == "premium":
        return 100.0
    if budget_mode == "standard":
        return 30.0
    return 0.0


def _make_scene(
    scene_id: str,
    title: str,
    prompt: str,
    duration_sec: float,
    priority: int,
    human_realism: int,
    native_audio_need: int,
    can_use_still_image: bool,
    subtitle_text: str,
    route_hint: RouteHint = "local",
) -> SceneSpec:
    return SceneSpec(
        id=scene_id,
        title=title,
        prompt=prompt,
        durationSec=round(duration_sec, 2),
        priority=max(1, min(priority, 5)),
        humanRealism=max(1, min(human_realism, 5)),
        nativeAudioNeed=max(1, min(native_audio_need, 5)),
        canUseStillImage=can_use_still_image,
        subtitleText=subtitle_text,
        routeHint=route_hint,
    )


def build_sample_project_plan(prompt: str, budget_mode: BudgetMode = "free") -> ProjectPlan:
    normalized_prompt = prompt.strip()
    lowered = normalized_prompt.lower()

    if "cafe" in lowered or "coffee" in lowered:
        scenes = [
            _make_scene(
                "scene-01",
                "Warm Hook",
                "Steam rising from a fresh latte in a soft morning light, premium social-video opening",
                4.0,
                5,
                4,
                2,
                False,
                "Start your day with a calmer rhythm.",
                "sora2" if budget_mode != "free" else "local",
            ),
            _make_scene(
                "scene-02",
                "Signature Menu",
                "Handcrafted pastries and coffee lineup on a textured wood table, editorial food styling",
                5.0,
                3,
                2,
                1,
                True,
                "Fresh pastry, slow coffee, no rush.",
            ),
            _make_scene(
                "scene-03",
                "Community Mood",
                "Neighborhood customers chatting softly in a cozy cafe interior, natural background movement",
                6.0,
                4,
                3,
                2,
                False,
                "Stay for the mood, not just the caffeine.",
            ),
            _make_scene(
                "scene-04",
                "Call To Action",
                "Cafe storefront at golden hour, warm ambient motion and inviting signage",
                4.0,
                4,
                2,
                1,
                True,
                "Visit today and make it your new routine.",
            ),
        ]
        title = "Warm Cafe Reel"
    elif "app" in lowered or "software" in lowered or "productivity" in lowered:
        scenes = [
            _make_scene(
                "scene-01",
                "Problem Hook",
                "Busy phone notifications and cluttered tasks collapsing into a clean interface transition",
                3.5,
                4,
                2,
                1,
                False,
                "Too many tasks, not enough focus?",
            ),
            _make_scene(
                "scene-02",
                "Core Product",
                "Minimal mobile app dashboard with one-tap task capture and clean charts",
                5.0,
                3,
                1,
                1,
                True,
                "Capture, sort, and finish work faster.",
            ),
            _make_scene(
                "scene-03",
                "Benefit Montage",
                "Fast-paced interface walkthrough with simple motion graphics and progress feedback",
                6.0,
                4,
                1,
                1,
                False,
                "Plan once. Focus longer. Ship more.",
            ),
            _make_scene(
                "scene-04",
                "Install CTA",
                "Clean logo lockup and app store style end card, polished social ad look",
                3.5,
                4,
                1,
                1,
                True,
                "Download now and reclaim your day.",
            ),
        ]
        title = "Productivity App Reel"
    else:
        scenes = [
            _make_scene(
                "scene-01",
                "Opening Statement",
                "Premium opening composition that introduces the brand mood in one striking social-video shot",
                4.0,
                5,
                4,
                2,
                False,
                "A sharper story starts here.",
                "sora2" if budget_mode == "premium" else "local",
            ),
            _make_scene(
                "scene-02",
                "Value Snapshot",
                "Visual summary of the main value proposition with bold typography and clean transitions",
                5.0,
                3,
                2,
                1,
                True,
                "Designed to look better and land faster.",
            ),
            _make_scene(
                "scene-03",
                "Proof Or Mood",
                "Text-driven short-form ad scene with stylish motion and tasteful background visuals",
                5.0,
                3,
                2,
                1,
                False,
                "Short-form content that feels intentional.",
            ),
            _make_scene(
                "scene-04",
                "Final CTA",
                "Closing action card with logo, URL, and direct invitation to act",
                4.0,
                4,
                1,
                1,
                True,
                "Try it now and launch your next reel faster.",
            ),
        ]
        title = "Brand Promo Reel"

    return ProjectPlan(
        version=1,
        title=title,
        sourcePrompt=normalized_prompt,
        aspectRatio="9:16",
        budgetMode=budget_mode,
        monthlyCapUsd=_default_monthly_cap(budget_mode),
        scenes=scenes,
    )
