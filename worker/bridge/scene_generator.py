"""Scene script generation — LLM prompting, parsing, and normalization.

Extracted from server.py to keep the main bridge file under the 660-line limit.
"""

from __future__ import annotations

import http.client
import json
import logging
import os
import re
from urllib import request as urllib_request
from urllib.error import URLError

from worker.bridge.templates import TEMPLATE_TYPES, build_template_prompt, _HOOK_EXEMPT

logger = logging.getLogger(__name__)

# Shared exception tuple for outbound LLM HTTP calls (Groq, Gemini, etc.).
# ``http.client.HTTPException`` covers ``IncompleteRead`` / ``BadStatusLine`` /
# ``RemoteDisconnected`` etc. which are NOT ``OSError`` subclasses and would
# otherwise crash the Flask thread on mid-body connection close.
_LLM_HTTP_ERRORS: tuple[type[BaseException], ...] = (
    URLError, OSError, TimeoutError, http.client.HTTPException,
    json.JSONDecodeError, KeyError, IndexError, ValueError, UnicodeDecodeError,
)

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


def _strip_foreign_scripts(text: str) -> str:
    """Remove non-Korean foreign scripts that LLMs sometimes mix into Korean output.
    Strips: CJK ideographs (漢字), Japanese katakana/hiragana, fullwidth Latin."""
    # CJK Unified Ideographs + Extension A
    text = re.sub(r'[\u4e00-\u9fff\u3400-\u4dbf]+', '', text)
    # Japanese Hiragana + Katakana
    text = re.sub(r'[\u3040-\u309f\u30a0-\u30ff]+', '', text)
    # Fullwidth Latin letters only (Ａ-Ｚ, ａ-ｚ) — preserve fullwidth punctuation ！？
    text = re.sub(r'[\uff21-\uff3a\uff41-\uff5a]+', '', text)
    return text


def normalize_scenes(scenes: list[dict], topic: str, template_type: str = "") -> list[dict]:
    """Fill missing fields, validate display_text, apply hook optimization.

    NOTE: This function is a general normalizer called from multiple paths
    (LLM generation, fallback, and potentially user-edited scenes).
    Do NOT clear image_source here — that belongs in _clear_llm_image_sources().
    """
    for s in scenes:
        s.setdefault("image_prompt", s.pop("visual_description", topic))
        s.setdefault("display_text", "")
        s.setdefault("emotion", "neutral")
        s.setdefault("image_source", "")
        s.setdefault("fallback_prompt", "")
        s.setdefault("transition", "Dissolve")
        s.setdefault("is_commentary", False)
        s.setdefault("rank", None)

        # Strip stray CJK ideographs from Korean narration/display_text
        narr = s.get("narration", "")
        if narr:
            s["narration"] = _strip_foreign_scripts(narr)
        dt_raw = s.get("display_text", "")
        if dt_raw:
            s["display_text"] = _strip_foreign_scripts(dt_raw)

        # Validate display_text matches narration; auto-fix if not
        narr = s.get("narration", "")
        dt = s.get("display_text", "")
        if narr and (not dt or not _display_text_matches_narration(dt, narr)):
            s["display_text"] = _extract_key_phrase(narr)

    # Hook optimization is handled by _enforce_hook() in generate_scenes_llm
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
    except _LLM_HTTP_ERRORS as e:
        logger.warning("groq call failed: %s", e)
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
                    logger.info("gemini grounded with %d web sources", len(sources))
            result_text = candidate["content"]["parts"][0]["text"]
            # --- Usage logging ---
            try:
                from worker.usage.db import log_usage
                usage_meta = data.get("usageMetadata", {})
                tokens_in = usage_meta.get("promptTokenCount", 0)
                tokens_out = usage_meta.get("candidatesTokenCount", 0)
                log_usage(
                    provider="gemini-2.5-flash",
                    category="llm",
                    model=model,
                    cost_usd=0.0,
                    tokens_in=tokens_in,
                    tokens_out=tokens_out,
                    units=1.0,
                    is_free=1,
                    metadata={"use_search": use_search},
                )
            except Exception as _log_err:
                # Usage DB is non-critical diagnostics; an insert failure
                # must never break the LLM call flow.
                logger.debug("gemini usage log failed: %s", _log_err)
            return result_text
    except _LLM_HTTP_ERRORS as e:
        logger.warning("gemini call failed: %s", e)
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
        logger.info("enrich step 2 skipped: no LLM response")
        return
    parsed = parse_scenes_json(text)
    if not parsed:
        logger.info("enrich step 2 skipped: failed to parse response")
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
    logger.info(
        "enrich step 2: %d/%d image prompts enriched (%s)",
        updated, len(scenes), enrich_provider,
    )


def _clear_llm_image_sources(scenes: list[dict]) -> None:
    """Clear LLM-generated image_source values so auto-route handles provider selection.
    Only "tenor" (Gemini routing token for Klipy GIFs) is preserved.
    Called ONLY on raw LLM output, never on user-edited scenes."""
    for s in scenes:
        if s.get("image_source", "") not in ("tenor", ""):
            s["image_source"] = ""


_DURATION_SCENE_MAP = {"30s": 6, "1min": 10, "custom": 8}

# Words that indicate an abstract/generic image prompt — filter these out
_ABSTRACT_IMAGE_WORDS = re.compile(
    r'\b(abstract concept|technology background|business meeting|digital illustration'
    r'|generic background|simple background|plain background)\b', re.IGNORECASE
)


def _evaluate_script_quality(scenes: list[dict], topic: str, template_type: str) -> tuple[int, str]:
    """Score a script 0-10 via LLM. Returns (score, feedback)."""
    scene_summary = json.dumps(
        [{"scene_num": s.get("scene_num"), "narration": s.get("narration", "")[:80],
          "display_text": s.get("display_text", ""), "emotion": s.get("emotion")}
         for s in scenes[:6]], ensure_ascii=False
    )
    prompt = (
        f'You are a YouTube Shorts script quality evaluator.\n'
        f'Topic: "{topic}" / Template: {template_type}\n\n'
        f'Score this script 0-10 on these criteria:\n'
        f'1. Hook strength (scene 1 grabs attention?)\n'
        f'2. Fact density (specific numbers, names, anecdotes?)\n'
        f'3. Flow (natural progression, no repetition?)\n'
        f'4. display_text quality (key phrases from narration?)\n\n'
        f'Scenes:\n{scene_summary}\n\n'
        f'Return JSON: {{"score": N, "feedback": "one-line improvement suggestion"}}'
    )
    text, _ = _call_llm(prompt)
    if not text:
        return 7, ""  # If LLM fails, pass by default
    try:
        # Strip fenced code blocks (```json ... ```)
        clean = text.strip()
        if clean.startswith("```"):
            parts = clean.split("\n", 1)
            clean = parts[1] if len(parts) > 1 else clean[3:]
            clean = clean.rsplit("```", 1)[0].strip()
        result = json.loads(clean)
        score = int(result.get("score", 7))
        feedback = result.get("feedback", "")
        return min(max(score, 0), 10), feedback
    except (json.JSONDecodeError, ValueError, TypeError, IndexError):
        return 7, ""


def _filter_image_prompts(scenes: list[dict], topic: str) -> None:
    """Post-hoc filter: reject abstract image prompts, fallback to topic-based prompt."""
    for s in scenes:
        prompt = s.get("image_prompt", "")
        if _ABSTRACT_IMAGE_WORDS.search(prompt):
            s["image_prompt"] = s.get("fallback_prompt") or f"photograph related to {topic}, natural lighting"
            logger.info("filter scene %s: abstract prompt replaced", s.get('scene_num'))


def _enforce_hook(scenes: list[dict], template_type: str = "") -> None:
    """Validate scene 1 hook: emotion, transition, display_text length."""
    if not scenes or template_type in _HOOK_EXEMPT:
        return
    hook = scenes[0]
    hook["transition"] = "Fade_In"
    if hook.get("emotion") not in ("shock", "funny"):
        hook["emotion"] = "shock"
    dt = hook.get("display_text", "")
    if len(dt) > 25:
        hook["display_text"] = dt[:25].rsplit(" ", 1)[0] if " " in dt[:25] else dt[:25]


def generate_scenes_llm(
    topic: str,
    lang: str,
    template_type: str = "news_explainer",
    tone: str = "casual_heyo",
    target_duration: str = "30s",
    custom_instruction: str = "",
) -> tuple[list[dict], str]:
    """Three-step generation: script → quality gate → image prompts."""
    lang_name = "Korean" if not lang.startswith("en") else "English"
    if template_type not in TEMPLATE_TYPES:
        template_type = "news_explainer"
    if tone not in TONE_PRESETS:
        tone = "casual_heyo"
    tone_preset = TONE_PRESETS[tone]
    scene_count = _DURATION_SCENE_MAP.get(target_duration, 8)

    max_attempts = 2
    best_scenes = None
    best_score = 0
    best_provider = "none"

    for attempt in range(max_attempts):
        extra = ""
        if attempt > 0 and best_scenes:
            extra = f"\n★ 이전 생성 피드백: 점수 {best_score}/10. 더 구체적인 팩트와 숫자를 포함하세요."
        rich_prompt = build_template_prompt(
            topic, lang_name, template_type, tone_rule=tone_preset["rule"],
            scene_count=scene_count,
            custom_instruction=(custom_instruction + extra).strip(),
            target_duration=target_duration,
        )
        text, provider = _call_llm(rich_prompt, use_search=True)
        if not text:
            continue
        scenes = parse_scenes_json(text)
        if not scenes:
            continue
        scenes = normalize_scenes(scenes, topic, template_type)
        _clear_llm_image_sources(scenes)

        # Quality gate: evaluate and keep best
        try:
            score, feedback = _evaluate_script_quality(scenes, topic, template_type)
        except _LLM_HTTP_ERRORS as e:
            logger.warning("quality evaluation error: %s", e)
            score, feedback = 7, ""
        logger.info(
            "quality attempt %d: score=%d/10 feedback=%s",
            attempt + 1, score, feedback[:60],
        )

        if score > best_score:
            best_scenes = scenes
            best_score = score
            best_provider = provider
        if score >= 7:
            break  # Good enough

    if best_scenes:
        _enforce_hook(best_scenes, template_type)
        try:
            _enrich_image_prompts(best_scenes, topic)
        except _LLM_HTTP_ERRORS as e:
            logger.warning("enrich step 2 failed, keeping original prompts: %s", e)
        _filter_image_prompts(best_scenes, topic)
        return best_scenes, best_provider

    fallback = generate_scenes_fallback(topic, lang)
    fallback = normalize_scenes(fallback, topic, template_type)
    _enforce_hook(fallback, template_type)
    return fallback, "template"


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
