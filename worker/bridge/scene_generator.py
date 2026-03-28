"""Scene script generation — LLM prompting, parsing, and normalization.

Extracted from server.py to keep the main bridge file under the 660-line limit.
"""

from __future__ import annotations

import json
import os
import re
from urllib import request as urllib_request

from worker.bridge.templates import TEMPLATE_TYPES, build_template_prompt, _HOOK_EXEMPT

def _get_key(name: str) -> str:
    return os.environ.get(name, "")

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


def _extract_key_phrase(narration: str, max_len: int = 24) -> str:
    """Extract the most salient phrase from narration for display_text."""
    # Look for numbers with units
    number_pattern = re.compile(r'[\d,]+\.?\d*\s*[%원달러만억조배위개월년일초분시]')
    numbers = number_pattern.findall(narration)
    if numbers:
        return numbers[0].strip()
    # First clause up to Korean sentence delimiter
    for d in ("거든요.", "이에요.", "예요.", "했어요.", "는데요.", "잖아요.", "해요.", "돼요."):
        idx = narration.find(d)
        if 0 < idx < max_len:
            return narration[:idx].strip()
    # Fallback: first part before comma or period
    for d in (",", ".", "!", "?"):
        idx = narration.find(d)
        if 0 < idx < max_len:
            return narration[:idx].strip()
    return narration[:max_len].strip()


def _display_text_matches_narration(display_text: str, narration: str) -> bool:
    """Check if display_text shares key tokens with narration."""
    if not display_text or not narration:
        return False
    # Normalize: remove newlines, markdown, whitespace
    dt_clean = re.sub(r'[*\n\\n]', ' ', display_text).strip().lower()
    narr_clean = narration.lower()
    # Check if any word (>= 2 chars) from display_text appears in narration
    words = [w for w in re.split(r'\s+', dt_clean) if len(w) >= 2]
    return any(w in narr_clean for w in words) if words else False


def normalize_scenes(scenes: list[dict], topic: str, template_type: str = "") -> list[dict]:
    """Fill missing fields, validate display_text, apply hook optimization."""
    for s in scenes:
        s.setdefault("image_prompt", s.pop("visual_description", topic))
        s.setdefault("display_text", "")
        s.setdefault("emotion", "neutral")
        s.setdefault("image_source", "")
        s.setdefault("fallback_prompt", "")
        s.setdefault("transition", "Dissolve")
        s.setdefault("is_commentary", False)
        s.setdefault("rank", None)

        # Validate display_text matches narration; auto-fix if not
        narr = s.get("narration", "")
        dt = s.get("display_text", "")
        if narr and (not dt or not _display_text_matches_narration(dt, narr)):
            s["display_text"] = _extract_key_phrase(narr)

    if scenes and template_type not in _HOOK_EXEMPT:
        hook = scenes[0]
        hook["transition"] = "Fade_In"
        if hook.get("emotion") == "neutral":
            hook["emotion"] = "shock"

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
    if not _get_key("GROQ_API_KEY"):
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
            "Authorization": f"Bearer {_get_key("GROQ_API_KEY")}",
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


def _call_gemini(prompt: str, use_search: bool = False) -> str | None:
    if not _get_key("GEMINI_API_KEY"):
        return None
    model = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={_get_key("GEMINI_API_KEY")}"
    gen_config: dict = {"temperature": 0.7, "maxOutputTokens": 4096}
    # google_search tool is incompatible with responseMimeType: "application/json"
    if not use_search:
        gen_config["responseMimeType"] = "application/json"
    body: dict = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": gen_config,
    }
    if use_search:
        body["tools"] = [{"google_search": {}}]
    payload = json.dumps(body).encode("utf-8")
    req = urllib_request.Request(url, data=payload, headers={"Content-Type": "application/json"})
    try:
        with urllib_request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read())
            candidate = data["candidates"][0]
            if use_search and "groundingMetadata" in candidate:
                sources = candidate["groundingMetadata"].get("groundingChunks", [])
                if sources:
                    print(f"[gemini] Grounded with {len(sources)} web sources")
            return candidate["content"]["parts"][0]["text"]
    except Exception as e:
        print(f"[gemini] Failed: {e}")
        return None


def _call_llm(prompt: str, use_search: bool = False) -> tuple[str | None, str]:
    """Try Gemini first, Groq fallback.  Returns (text, provider)."""
    text = _call_gemini(prompt, use_search=use_search)
    if text:
        return text, "gemini"
    text = _call_groq(prompt)
    if text:
        return text, "groq"
    return None, "none"


def _enrich_image_prompts(scenes: list[dict], topic: str) -> None:
    """Step 2: Generate concrete image search terms for each scene (in-place)."""
    scene_summaries = []
    for s in scenes:
        scene_summaries.append(
            f'scene {s.get("scene_num", 0)}: "{s.get("narration", "")[:60]}" (emotion: {s.get("emotion", "neutral")})'
        )
    prompt = (
        f'Topic: "{topic}"\n\n'
        f'Below are scenes from a YouTube Shorts script. '
        f'For each scene, write a concrete English image generation prompt for AI (Imagen 3). '
        f'Rules:\n'
        f'- NEVER: "abstract concept", "technology background", "business meeting", "digital illustration"\n'
        f'- NEVER: generic stock photo descriptions\n'
        f'- ALWAYS: specific objects with descriptive adjectives and lighting\n'
        f'- GOOD: "golden bitcoin coins stacked on circuit board, dramatic blue lighting, close-up macro"\n'
        f'- GOOD: "young Korean woman excited at phone screen, cafe background, natural daylight"\n'
        f'- Each prompt must paint a SPECIFIC visual scene related to "{topic}"\n'
        f'- 8-20 words per prompt, descriptive and visual\n'
        f'- Include camera angle, lighting, and mood keywords\n\n'
        f'Scenes:\n' + '\n'.join(scene_summaries) + '\n\n'
        f'Return a JSON array of objects: [{{"scene_num": 1, "image_prompt": "..."}}]'
    )
    text, enrich_provider = _call_llm(prompt)
    if not text:
        print("[enrich] Step 2 skipped: no LLM response")
        return
    parsed = parse_scenes_json(text)
    if not parsed:
        print("[enrich] Step 2 skipped: failed to parse response")
        return
    prompt_map: dict[int, str] = {}
    for item in parsed:
        sn = item.get("scene_num")
        ip = item.get("image_prompt")
        if sn is not None and ip:
            try:
                prompt_map[int(sn)] = ip
            except (ValueError, TypeError):
                continue
    updated = 0
    for s in scenes:
        sn = s.get("scene_num")
        if sn in prompt_map:
            s["image_prompt"] = prompt_map[sn]
            updated += 1
    print(f"[enrich] Step 2: {updated}/{len(scenes)} image prompts enriched ({enrich_provider})")


_DURATION_SCENE_MAP = {"30s": 6, "1min": 10, "custom": 8}


def generate_scenes_llm(
    topic: str,
    lang: str,
    template_type: str = "news_explainer",
    tone: str = "casual_heyo",
    target_duration: str = "30s",
    custom_instruction: str = "",
) -> tuple[list[dict], str]:
    """Two-step generation: script first, then image prompts separately."""
    lang_name = "Korean" if not lang.startswith("en") else "English"
    if template_type not in TEMPLATE_TYPES:
        template_type = "news_explainer"
    if tone not in TONE_PRESETS:
        tone = "casual_heyo"
    tone_preset = TONE_PRESETS[tone]
    scene_count = _DURATION_SCENE_MAP.get(target_duration, 8)
    rich_prompt = build_template_prompt(
        topic, lang_name, template_type, tone_rule=tone_preset["rule"],
        scene_count=scene_count, custom_instruction=custom_instruction,
        target_duration=target_duration,
    )

    text, provider = _call_llm(rich_prompt, use_search=True)
    if text:
        scenes = parse_scenes_json(text)
        if scenes:
            scenes = normalize_scenes(scenes, topic, template_type)
            try:
                _enrich_image_prompts(scenes, topic)
            except Exception as e:
                print(f"[enrich] Step 2 failed, keeping original prompts: {e}")
            return scenes, provider

    fallback = generate_scenes_fallback(topic, lang)
    return normalize_scenes(fallback, topic, template_type), "template"


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
