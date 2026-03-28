"""
Shortform video template prompts for Gemini scene script generation.
"""
from __future__ import annotations

TEMPLATE_TYPES = (
    "community_read", "news_explainer", "reddit_translation", "ranking_list", "origin_story",
    "vs_comparison", "myth_buster", "tutorial_steps", "before_after", "hot_take",
)

_JSON_FORMAT = """Each element: {{ "scene_num": N, "narration": "spoken text", "display_text": "screen subtitle max 3 lines", "image_prompt": "English image search query", "image_source": "pexels", "emotion": "neutral|funny|serious|shock|sad", "fallback_prompt": "alt query", "transition": "Dissolve" }}"""

_HOOK_INSTRUCTION = """CRITICAL — Scene 1 MUST be a viewer-retention hook:
- narration: under 3 seconds when spoken (max 25 chars Korean / 12 words English)
- emotion: MUST be "shock" or "funny" (NEVER "neutral" for scene 1)
- display_text: ONE bold line, max 8 chars — a question or surprising claim
- image_prompt: the most visually striking image in the entire video
- transition: "Fade_In"
"""


_HOOK_EXEMPT = frozenset({"reddit_translation", "ranking_list", "tutorial_steps"})


def build_template_prompt(
    topic: str,
    lang_name: str,
    template_type: str,
    tone_rule: str = "",
) -> str:
    """Build a Gemini prompt. Topic is repeated at start and end to prevent drift.

    Templates in ``_HOOK_EXEMPT`` skip the hook instruction because their scene 1
    has a structural role (intro/rank/commentary) rather than a retention hook.
    *tone_rule* is appended when non-empty so Gemini respects the same speech style as Groq.
    """
    body = _build_template_body(topic, lang_name, template_type)
    if tone_rule:
        body += f"\n\n★ 말투 규칙 (절대 준수): {tone_rule}"
    if template_type in _HOOK_EXEMPT:
        return body
    return f"{_HOOK_INSTRUCTION}\n{body}"


def _build_template_body(topic: str, lang_name: str, template_type: str) -> str:
    """Internal: return the template-specific prompt body (without hook prefix)."""

    if template_type == "community_read":
        return f"""Write a YouTube Shorts script about: "{topic}"

You are reading a Korean community post aloud. Split into 5-8 slides.
- narration: natural spoken {lang_name}, convert slang to formal
- display_text: max 4 lines, 12 chars/line
- emotion: "funny"/"shock" for reactions, "neutral" for facts
- transition: "Fade_In" for scene 1, "Dissolve" for rest

Return ONLY a JSON array about "{topic}". {_JSON_FORMAT}"""

    if template_type == "news_explainer":
        return f"""Write a YouTube Shorts news explainer about: "{topic}"

Structure in {lang_name}: Hook(1) → Context(2-3) → Core facts(4-5) → Outlook(6-7) → CTA(8)
- narration: formal, short sentences
- display_text: key numbers on separate line, max 3 lines
- image_prompt: related to "{topic}", NOT generic AI images
- emotion: "shock" for hook, "serious" for data, "neutral" for CTA

Return ONLY a JSON array about "{topic}". {_JSON_FORMAT}"""

    if template_type == "reddit_translation":
        return f"""Translate and narrate this foreign post for Korean YouTube Shorts: "{topic}"

- Translate naturally into {lang_name}, add cultural commentary slides (is_commentary: true)
- narration style: conversational "~인데요", "~거든요"
- emotion: "funny"/"shock" for reactions, "neutral" for explanations

Return ONLY a JSON array about "{topic}". {_JSON_FORMAT}
Extra field for commentary: "is_commentary": true"""

    if template_type == "ranking_list":
        return f"""Write a Top-N ranking YouTube Shorts about: "{topic}"

Structure in {lang_name}: Intro(1) → Per item: rank scene + explanation scene → Outro
- Rank scenes: set "rank": N, display_text: "3위\\n항목명"
- transition: "Slide_Left" for ranks

Return ONLY a JSON array about "{topic}". {_JSON_FORMAT}
Extra field on rank scenes: "rank": N"""

    if template_type == "vs_comparison":
        return f"""Write a YouTube Shorts A-vs-B comparison about: "{topic}"

Structure in {lang_name}: Hook(1) → Side A overview(2-3) → Side B overview(4-5) → Key differences(6-7) → Verdict(8)
- narration: balanced, factual tone in {lang_name}
- display_text: side labels "A" / "B" clearly marked, max 3 lines
- emotion: "shock" for hook, "serious" for analysis, "neutral" for verdict
- image_prompt: product/concept images directly related to "{topic}"

Return ONLY a JSON array about "{topic}". {_JSON_FORMAT}"""

    if template_type == "myth_buster":
        return f"""Write a YouTube Shorts myth-busting / fact-check about: "{topic}"

Structure in {lang_name}: Hook question(1) → Common belief(2) → Evidence for(3-4) → Evidence against(5-6) → Verdict(7) → CTA(8)
- narration: investigative, "{lang_name}" style "사실일까요?", "확인해보겠습니다"
- display_text: "사실" / "거짓" verdict labels, max 3 lines
- emotion: "shock" for hook & reveals, "serious" for evidence, "neutral" for CTA
- image_prompt: evidence-related visuals for "{topic}"

Return ONLY a JSON array about "{topic}". {_JSON_FORMAT}"""

    if template_type == "tutorial_steps":
        return f"""Write a YouTube Shorts step-by-step tutorial about: "{topic}"

Structure in {lang_name}: Problem(1) → Step 1(2-3) → Step 2(4-5) → Step 3(6-7) → Result(8)
- Step scenes: set "rank": N for step number (1, 2, 3)
- narration: instructional, clear {lang_name}
- display_text: "Step N" + brief action, max 3 lines
- emotion: "neutral" for steps, "funny" or "shock" for result reveal

Return ONLY a JSON array about "{topic}". {_JSON_FORMAT}
Extra field on step scenes: "rank": N"""

    if template_type == "before_after":
        return f"""Write a YouTube Shorts before/after transformation about: "{topic}"

Structure in {lang_name}: Before hook(1) → Before details(2-3) → Transition moment(4) → After reveal(5-6) → Impact(7) → CTA(8)
- narration: dramatic build-up in {lang_name}, contrast "before" vs "after"
- display_text: "Before" / "After" labels, max 3 lines
- emotion: "sad" or "serious" for before, "shock" for transition, "funny" for after reveal
- image_prompt: contrasting visuals for "{topic}"

Return ONLY a JSON array about "{topic}". {_JSON_FORMAT}"""

    if template_type == "hot_take":
        return f"""Write a YouTube Shorts hot-take / opinion piece about: "{topic}"

Structure in {lang_name}: Bold statement(1) → Context(2-3) → Supporting argument(4-5) → Counter-argument(6) → Conclusion(7) → Engagement CTA(8)
- narration: opinionated, conversational {lang_name} "~라고 생각합니다", "~일 수도 있습니다"
- display_text: provocative one-liners, max 3 lines
- emotion: "shock" for opener, "serious" for arguments, "funny" for CTA
- CTA: ask viewers to comment their opinion

Return ONLY a JSON array about "{topic}". {_JSON_FORMAT}"""

    # origin_story (default fallback)
    return f"""Write a history/origin storytelling YouTube Shorts about: "{topic}"

Narrative arc in {lang_name}: Hook(1) → Origin(2-3) → Turning point(4-5) → Now(6-7) → Punchline(8)
- narration: storytelling "~였는데요", "~했다고 합니다"
- image_prompt: era-specific descriptions related to "{topic}"

Return ONLY a JSON array about "{topic}". {_JSON_FORMAT}"""
