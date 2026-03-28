"""Scene script generation — LLM prompting, parsing, and normalization.

Extracted from server.py to keep the main bridge file under the 660-line limit.
"""

from __future__ import annotations

import json
import os
import re
from urllib import request as urllib_request

from worker.bridge.templates import TEMPLATE_TYPES, build_template_prompt, _HOOK_EXEMPT

GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")

# ---------------------------------------------------------------------------
# Template hints (for Groq short prompt)
# ---------------------------------------------------------------------------
_TEMPLATE_HINTS = {
    "community_read": "커뮤니티 글 읽어주기",
    "news_explainer": "뉴스 해설",
    "reddit_translation": "해외 글 번역",
    "ranking_list": "Top N 랭킹",
    "origin_story": "기원/역사 스토리",
    "vs_comparison": "A vs B 비교",
    "myth_buster": "팩트체크",
    "tutorial_steps": "단계별 튜토리얼",
    "before_after": "비포/애프터",
    "hot_take": "핫테이크/논쟁",
}

_SCENE_JSON_HINT = 'JSON 배열로 반환. 각 원소: {{"scene_num":N,"narration":"한국어 나레이션","display_text":"한국어 자막 2줄 이내","image_prompt":"구체적 영어 이미지 검색어","emotion":"neutral","image_source":"pexels","transition":"Dissolve"}}'

# --- Tone presets (종결어미) — independent from template ---
TONE_PRESETS = {
    "casual_heyo": {
        "label": "해요체 (캐주얼)",
        "rule": '종결어미: "~이에요", "~거든요", "~인데요", "~하더라고요" 체만 사용.',
        "example_endings": ["~이에요", "~거든요", "~인데요"],
    },
    "commentary": {
        "label": "해설체",
        "rule": '종결어미: "~인 거죠", "~한 셈이죠", "~라고 하죠" 체만 사용.',
        "example_endings": ["~인 거죠", "~한 셈이죠", "~라고 하죠"],
    },
    "banmal": {
        "label": "반말",
        "rule": '종결어미: "~임", "~인데", "~거든", "~한 거지" 체만 사용.',
        "example_endings": ["~임", "~인데", "~거든"],
    },
    "story": {
        "label": "이야기체",
        "rule": '종결어미: "~였는데요", "~했대요", "~이래요" 체만 사용.',
        "example_endings": ["~였는데요", "~했대요", "~이래요"],
    },
    "formal_soft": {
        "label": "존댓말 (부드러운)",
        "rule": '종결어미: "~합니다", "~인데요", "~이죠" 체만 사용.',
        "example_endings": ["~합니다", "~인데요", "~이죠"],
    },
}

# --- Template structure (구조만, 말투 없음) ---
_TEMPLATE_PROMPTS = {
    "community_read": (
        '유튜브 쇼츠 커뮤니티 글 읽어주기. 5~8개 씬으로 분할. '
        'emotion: 놀라운 부분 "shock", 웃긴 부분 "funny". '
    ),
    "news_explainer": (
        '유튜브 쇼츠 뉴스 해설. 8개 씬. '
        '구조: 충격(1) → 배경(2-3) → 핵심 숫자(4-5) → 전망(6-7) → 질문(8). '
        '숫자는 display_text에 크게. 씬1 emotion "shock". '
    ),
    "reddit_translation": (
        '해외 글 번역 읽어주기 유튜브 쇼츠. 6~8개 씬. 문화차이 괄호 설명. '
        'emotion: 리액션 "funny"/"shock". '
    ),
    "ranking_list": (
        'Top N 랭킹 유튜브 쇼츠. 구조: 인트로(1) → 항목(2씬씩) → 아웃트로. '
        '순위 씬에 "rank": N 필드 추가. '
    ),
    "origin_story": (
        '탄생 비화 유튜브 쇼츠. 8개 씬. '
        '구조: 의외(1) → 기원(2-3) → 전환(4-5) → 현재(6-7) → 정리(8). '
    ),
    "vs_comparison": (
        'A vs B 비교 유튜브 쇼츠. 8개 씬. '
        '구조: 훅(1) → A(2-3) → B(4-5) → 비교(6-7) → 결론(8). '
    ),
    "myth_buster": (
        '팩트체크 유튜브 쇼츠. 8개 씬. '
        '구조: 질문(1) → 통념(2) → 찬성(3-4) → 반대(5-6) → 판정(7) → 마무리(8). 판정 emotion "shock". '
    ),
    "tutorial_steps": (
        '단계별 튜토리얼 유튜브 쇼츠. 8개 씬. '
        '구조: 문제(1) → Step1(2-3) → Step2(4-5) → Step3(6-7) → 완성(8). Step에 "rank": N. '
    ),
    "before_after": (
        '비포/애프터 유튜브 쇼츠. 8개 씬. '
        '구조: Before(1-3) → 전환(4) → After(5-6) → 임팩트(7) → 마무리(8). '
        'Before "sad", 전환 "shock", After "funny". '
    ),
    "hot_take": (
        '핫테이크 유튜브 쇼츠. 8개 씬. '
        '구조: 주장(1) → 배경(2-3) → 찬성(4-5) → 반론(6) → 결론(7) → 댓글(8). 씬1 emotion "shock". '
    ),
}


def build_scene_prompt(topic: str, template_type: str, tone: str = "casual_heyo") -> str:
    """Build a short Korean prompt for Groq (topic-faithful, tone-enforced)."""
    structure = _TEMPLATE_PROMPTS.get(template_type, _TEMPLATE_PROMPTS["news_explainer"])
    tone_preset = TONE_PRESETS.get(tone, TONE_PRESETS["casual_heyo"])
    tone_rule = tone_preset["rule"]
    examples = tone_preset["example_endings"]
    return (
        f'주제: {topic}\n\n'
        f'{structure}\n'
        f'★ 말투 통일 (절대 규칙): {tone_rule} 다른 종결어미 절대 섞지 마.\n'
        f'나레이션 예시 톤: "{examples[0]}", "{examples[1]}", "{examples[2]}"\n\n'
        f'추가 규칙:\n'
        f'- 나레이션 한 문장 최대 25자.\n'
        f'- 자막(display_text)은 핵심만, 2줄 이내.\n'
        f'- image_prompt는 "{topic}" 직접 관련 영어. 일반적 표현 금지.\n'
        f'- emotion 다양하게: shock, serious, funny, neutral.\n\n'
        f'{_SCENE_JSON_HINT}'
    )


def normalize_scenes(scenes: list[dict], topic: str, template_type: str = "") -> list[dict]:
    """Fill missing fields and apply hook optimization (exempt templates skip hook)."""
    for s in scenes:
        s.setdefault("image_prompt", s.pop("visual_description", topic))
        s.setdefault("display_text", "")
        s.setdefault("emotion", "neutral")
        s.setdefault("image_source", "")
        s.setdefault("fallback_prompt", "")
        s.setdefault("transition", "Dissolve")
        s.setdefault("is_commentary", False)
        s.setdefault("rank", None)

    if scenes and template_type not in _HOOK_EXEMPT:
        hook = scenes[0]
        hook["transition"] = "Fade_In"
        if hook.get("emotion") == "neutral":
            hook["emotion"] = "shock"
        # Truncate long narrations to first sentence boundary under 30 chars
        narr = hook.get("narration", "")
        if len(narr) > 30:
            for delim in (".", "!", "?", "。", "！", "？"):
                idx = narr.find(delim)
                if 0 < idx < 30:
                    hook["narration"] = narr[: idx + 1]
                    break

    return scenes


def parse_scenes_json(text: str) -> list[dict] | None:
    """Parse LLM output into a list of scene dicts."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1]
        text = text.rsplit("```", 1)[0].strip()
    text = re.sub(r",\s*([}\]])", r"\1", text)
    try:
        result = json.loads(text)
        if isinstance(result, dict):
            for v in result.values():
                if isinstance(v, list) and v and isinstance(v[0], dict):
                    return v
        if isinstance(result, list):
            return result
    except json.JSONDecodeError:
        pass
    return None


def _call_groq(prompt: str) -> str | None:
    if not GROQ_API_KEY:
        return None
    model = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")
    payload = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.7,
        "max_tokens": 4096,
        "response_format": {"type": "json_object"},
    }).encode("utf-8")
    req = urllib_request.Request(
        "https://api.groq.com/openai/v1/chat/completions",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {GROQ_API_KEY}",
            "User-Agent": "VideoStudio/1.0",
        },
    )
    try:
        with urllib_request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
            return data["choices"][0]["message"]["content"]
    except Exception as e:
        print(f"[groq] Failed: {e}")
        return None


def _call_gemini(prompt: str) -> str | None:
    if not GEMINI_API_KEY:
        return None
    model = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={GEMINI_API_KEY}"
    payload = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.7, "maxOutputTokens": 4096, "responseMimeType": "application/json"},
    }).encode("utf-8")
    req = urllib_request.Request(url, data=payload, headers={"Content-Type": "application/json"})
    try:
        with urllib_request.urlopen(req, timeout=45) as resp:
            data = json.loads(resp.read())
            return data["candidates"][0]["content"]["parts"][0]["text"]
    except Exception as e:
        print(f"[gemini] Failed: {type(e).__name__}")
        return None


def generate_scenes_llm(
    topic: str,
    lang: str,
    template_type: str = "news_explainer",
    tone: str = "casual_heyo",
) -> tuple[list[dict], str]:
    """Generate scene script.  Groq first (topic-faithful), Gemini fallback, then template."""
    lang_name = "Korean" if not lang.startswith("en") else "English"
    if template_type not in TEMPLATE_TYPES:
        template_type = "news_explainer"
    if tone not in TONE_PRESETS:
        tone = "casual_heyo"
    tone_preset = TONE_PRESETS[tone]
    short_prompt = build_scene_prompt(topic, template_type, tone)
    rich_prompt = build_template_prompt(topic, lang_name, template_type, tone_rule=tone_preset["rule"])

    text = _call_groq(short_prompt)
    if text:
        scenes = parse_scenes_json(text)
        if scenes:
            return normalize_scenes(scenes, topic, template_type), "groq"

    text = _call_gemini(rich_prompt)
    if text:
        scenes = parse_scenes_json(text)
        if scenes:
            return normalize_scenes(scenes, topic, template_type), "gemini"

    return generate_scenes_fallback(topic, lang), "template"


def generate_scenes_fallback(topic: str, lang: str) -> list[dict]:
    """Hardcoded template fallback."""
    templates = {
        "ko": [
            ("{topic}, 지금부터 알아보겠습니다.", "Title card about {topic}"),
            ("{topic}의 시작은 어디서부터일까요? 그 기원을 살펴봅니다.", "Origin history of {topic}"),
            ("{topic}이 세상에 가져온 변화는 놀랍습니다.", "Impact and changes from {topic}"),
            ("현재 {topic}은 어떤 모습일까요? 최신 트렌드를 확인합니다.", "Current state of {topic}"),
            ("{topic}의 미래는 무궁무진합니다. 함께 지켜봐 주세요.", "Future possibilities of {topic}"),
        ],
        "en": [
            ("Let's explore {topic}.", "Title card about {topic}"),
            ("Where did {topic} begin? Let's look at its origins.", "Origin history of {topic}"),
            ("The impact of {topic} has been remarkable.", "Impact and changes from {topic}"),
            ("What does {topic} look like today?", "Current state of {topic}"),
            ("The future of {topic} is full of possibilities.", "Future possibilities of {topic}"),
        ],
    }
    lang_key = "en" if lang.startswith("en") else "ko"
    return [
        {
            "scene_num": i + 1,
            "narration": n.format(topic=topic),
            "image_prompt": ip.format(topic=topic),
            "display_text": "",
            "emotion": "neutral",
            "image_source": "",
            "fallback_prompt": "",
            "transition": "Fade_In" if i == 0 else "Dissolve",
            "is_commentary": False,
            "rank": None,
        }
        for i, (n, ip) in enumerate(templates[lang_key])
    ]


def wrap_narration(scenes: list[dict]) -> None:
    """Force line-wrap long narrations.  Korean-aware: split at sentence
    endings (。！？) rather than arbitrary midpoints."""
    _KOREAN_DELIMS = ".!?。！？,，"
    for s in scenes:
        narr = s.get("narration", "")
        if len(narr) <= 20:
            continue
        mid = len(narr) // 2
        best = mid
        for offset in range(min(8, mid)):
            for pos in [mid + offset, mid - offset]:
                if 0 < pos < len(narr) and narr[pos] in _KOREAN_DELIMS:
                    best = pos + 1
                    break
            else:
                continue
            break
        s["narration"] = narr[:best].rstrip() + "\n" + narr[best:].lstrip()
