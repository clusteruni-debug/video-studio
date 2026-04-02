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
    bgmMood: str = "upbeat"

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
    is_cafe_prompt = (
        "cafe" in lowered
        or "coffee" in lowered
        or "bakery" in lowered
        or "카페" in normalized_prompt
        or "커피" in normalized_prompt
        or "베이커리" in normalized_prompt
    )
    is_productivity_prompt = (
        "app" in lowered
        or "software" in lowered
        or "productivity" in lowered
        or "앱" in normalized_prompt
        or "생산성" in normalized_prompt
        or "소프트웨어" in normalized_prompt
    )
    is_beauty_prompt = (
        "beauty" in lowered
        or "cosmetic" in lowered
        or "skincare" in lowered
        or "화장품" in normalized_prompt
        or "뷰티" in normalized_prompt
        or "코스메틱" in normalized_prompt
        or "스킨케어" in normalized_prompt
    )

    if is_cafe_prompt:
        scenes = [
            _make_scene(
                "scene-01",
                "따뜻한 첫 장면",
                "부드러운 아침빛 속 라테 김이 오르는 고급 오프닝 컷",
                4.0,
                5,
                4,
                2,
                False,
                "조금 더 느리고 부드러운 아침을 시작해 보세요.",
                "sora2" if budget_mode != "free" else "local",
            ),
            _make_scene(
                "scene-02",
                "시그니처 메뉴",
                "질감 있는 테이블 위에 페이스트리와 커피를 정갈하게 배치한 장면",
                5.0,
                3,
                2,
                1,
                True,
                "갓 구운 페이스트리와 천천히 내린 커피, 서두를 필요 없는 시간.",
            ),
            _make_scene(
                "scene-03",
                "머무는 분위기",
                "동네 손님들이 편안하게 머무는 카페 내부와 자연스러운 움직임",
                6.0,
                4,
                3,
                2,
                False,
                "카페인은 이유일 뿐, 결국 남는 건 분위기입니다.",
            ),
            _make_scene(
                "scene-04",
                "방문 유도",
                "노을빛이 스치는 매장 전면과 초대하듯 보이는 사인",
                4.0,
                4,
                2,
                1,
                True,
                "오늘 들러서 새로운 일상으로 만들어 보세요.",
            ),
        ]
        title = "따뜻한 카페 릴스"
        bgm_mood = "calm"
    elif is_productivity_prompt:
        scenes = [
            _make_scene(
                "scene-01",
                "문제 제기",
                "복잡한 알림과 쌓인 업무가 정돈된 인터페이스로 전환되는 장면",
                3.5,
                4,
                2,
                1,
                False,
                "할 일은 너무 많고 집중은 자꾸 끊기지 않나요?",
            ),
            _make_scene(
                "scene-02",
                "핵심 기능",
                "한 번의 탭으로 업무를 정리하는 미니멀한 모바일 대시보드",
                5.0,
                3,
                1,
                1,
                True,
                "빠르게 기록하고, 정리하고, 끝내는 흐름을 보여줍니다.",
            ),
            _make_scene(
                "scene-03",
                "효과 강조",
                "짧고 빠른 인터페이스 흐름과 진행 피드백을 묶은 장면",
                6.0,
                4,
                1,
                1,
                False,
                "한 번 정리하고 더 오래 집중하고 더 많이 끝내세요.",
            ),
            _make_scene(
                "scene-04",
                "설치 유도",
                "앱스토어 스타일의 정돈된 엔딩 카드와 로고 마감",
                3.5,
                4,
                1,
                1,
                True,
                "지금 설치하고 하루의 흐름을 다시 가져오세요.",
            ),
        ]
        title = "생산성 앱 릴스"
        bgm_mood = "energetic"
    elif is_beauty_prompt:
        scenes = [
            _make_scene(
                "scene-01",
                "첫 질감 클로즈업",
                "유리 용기와 크림 텍스처를 고급스럽게 잡아내는 첫 장면",
                4.0,
                5,
                4,
                1,
                False,
                "손끝에 닿기 전부터 질감이 다르게 느껴지는 제품입니다.",
                "sora2" if budget_mode != "free" else "local",
            ),
            _make_scene(
                "scene-02",
                "핵심 성분 소개",
                "깨끗한 배경 위에 핵심 성분과 패키지를 함께 정리하는 장면",
                5.0,
                3,
                2,
                1,
                True,
                "복잡한 설명 대신 핵심 성분과 사용감을 짧게 전달합니다.",
            ),
            _make_scene(
                "scene-03",
                "사용 분위기",
                "아침 루틴 속에서 자연스럽게 제품을 사용하는 무드 컷",
                5.5,
                4,
                3,
                2,
                False,
                "하루의 분위기를 정리하는 루틴처럼 보이게 구성합니다.",
            ),
            _make_scene(
                "scene-04",
                "구매 유도 엔딩",
                "로고와 제품명, 한 줄 카피로 마무리하는 엔딩 카드",
                4.0,
                4,
                1,
                1,
                True,
                "지금 보고 바로 기억나는 제품 티저로 마감합니다.",
            ),
        ]
        title = "뷰티 제품 티저"
        bgm_mood = "cinematic"
    else:
        # Use the user's prompt to generate contextual scenes (all still-image for free mode)
        short_prompt = normalized_prompt[:60]
        scenes = [
            _make_scene(
                "scene-01",
                "시작",
                f"{short_prompt}의 시작을 알리는 장면",
                4.0,
                5,
                3,
                1,
                True,
                f"{short_prompt}, 이야기가 시작됩니다.",
            ),
            _make_scene(
                "scene-02",
                "핵심",
                f"{short_prompt}의 가장 인상적인 순간",
                5.0,
                3,
                2,
                1,
                True,
                "이 순간이 바로 핵심입니다.",
            ),
            _make_scene(
                "scene-03",
                "분위기",
                f"{short_prompt}의 감성을 담은 장면",
                5.0,
                3,
                2,
                1,
                True,
                "이 분위기를 느껴보세요.",
            ),
            _make_scene(
                "scene-04",
                "마무리",
                f"{short_prompt}의 여운이 남는 장면",
                4.0,
                4,
                1,
                1,
                True,
                "다시 찾고 싶은 순간입니다.",
            ),
        ]
        title = short_prompt
        bgm_mood = "upbeat"

    return ProjectPlan(
        version=1,
        title=title,
        sourcePrompt=normalized_prompt,
        aspectRatio="9:16",
        budgetMode=budget_mode,
        monthlyCapUsd=_default_monthly_cap(budget_mode),
        scenes=scenes,
        bgmMood=bgm_mood,
    )
