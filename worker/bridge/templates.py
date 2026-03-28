"""
Shortform video template prompts for Gemini scene script generation.

Each template includes one golden example scene to anchor quality expectations.
"""
from __future__ import annotations

TEMPLATE_TYPES = (
    "community_read", "news_explainer", "reddit_translation", "ranking_list", "origin_story",
    "vs_comparison", "myth_buster", "tutorial_steps", "before_after", "hot_take",
)

_JSON_FORMAT = """Each element: {{ "scene_num": N, "narration": "spoken text", "display_text": "screen subtitle max 3 lines", "image_prompt": "English image search query", "image_source": "pexels", "emotion": "neutral|funny|serious|shock|sad", "fallback_prompt": "alt query", "transition": "Dissolve" }}"""

_QUALITY_RULES = """
NARRATION QUALITY RULES (must follow):
- Each narration must contain a SPECIFIC fact, number, name, or anecdote — never vague filler
- BAD: "큰 의미를 부여하고 있어요" / "많은 변화가 있었어요" / "주목받고 있어요"
- GOOD: "시가총액이 2조 달러를 넘겼거든요" / "2009년 사토시가 처음 만들었는데요" / "테슬라가 15억 달러어치 샀어요"
- Max 25 chars per narration sentence
- display_text: only the key number or keyword, max 2 lines
"""

_HOOK_INSTRUCTION = """CRITICAL — Scene 1 MUST be a viewer-retention hook:
- narration: under 3 seconds when spoken (max 25 chars Korean / 12 words English)
- emotion: MUST be "shock" or "funny" (NEVER "neutral" for scene 1)
- display_text: ONE bold line, max 8 chars — a question or surprising claim
- image_prompt: the most visually striking image in the entire video
- transition: "Fade_In"
"""


_HOOK_EXEMPT = frozenset({"reddit_translation", "ranking_list", "tutorial_steps"})

# ---------------------------------------------------------------------------
# Golden examples — one per template, showing the quality bar we expect
# ---------------------------------------------------------------------------
_EXAMPLES = {
    "news_explainer": '''
Example (topic: "삼성전자 3나노 수율 돌파"):
[
  {"scene_num":1,"narration":"삼성이 드디어 해냈어요!","display_text":"3나노 수율 돌파","emotion":"shock","transition":"Fade_In"},
  {"scene_num":2,"narration":"3나노 공정 수율이 60%를 넘겼거든요.","display_text":"수율 60%+","emotion":"serious","transition":"Dissolve"},
  {"scene_num":3,"narration":"TSMC도 아직 못 한 수치예요.","display_text":"TSMC 대비\\n앞서는 수치","emotion":"serious","transition":"Dissolve"}
]
(continue this quality for all 8 scenes — every narration needs a concrete fact)
''',
    "community_read": '''
Example (topic: "자취방 월세 50만원인데 관리비가 30만원"):
[
  {"scene_num":1,"narration":"월세보다 관리비가 더 비쌌대요!","display_text":"관리비 30만?","emotion":"shock","transition":"Fade_In"},
  {"scene_num":2,"narration":"월세가 50만원이었는데요.","display_text":"월세 50만원","emotion":"neutral","transition":"Dissolve"},
  {"scene_num":3,"narration":"관리비 고지서를 보니까 30만원이 찍혀있었대요.","display_text":"관리비 30만원\\n청구서","emotion":"shock","transition":"Dissolve"}
]
(continue — use specific numbers, direct quotes, reactions from the post)
''',
    "reddit_translation": '''
Example (topic: "미국인이 한국 편의점 가서 충격받은 이야기"):
[
  {"scene_num":1,"narration":"한국 편의점에서 삼각김밥을 처음 봤대요.","display_text":"삼각김밥 충격","emotion":"funny","transition":"Dissolve"},
  {"scene_num":2,"narration":"참치마요 하나에 1200원이라고요.","display_text":"1200원\\n(약 $0.90)","emotion":"shock","transition":"Dissolve","is_commentary":false},
  {"scene_num":3,"narration":"미국 편의점 샌드위치가 8달러인데 비교가 안 된대요.","display_text":"미국 $8 vs\\n한국 $0.90","emotion":"funny","transition":"Dissolve","is_commentary":true}
]
(continue — translate naturally, add price/cultural comparisons)
''',
    "ranking_list": '''
Example (topic: "세계에서 가장 비싼 운동화 Top 5"):
[
  {"scene_num":1,"narration":"5위부터 시작할게요!","display_text":"Top 5 운동화","emotion":"neutral","transition":"Dissolve"},
  {"scene_num":2,"narration":"5위, 에어맥스 1/97 숀 워더스푼.","display_text":"5위\\n숀 워더스푼","emotion":"neutral","transition":"Slide_Left","rank":5},
  {"scene_num":3,"narration":"리셀가가 500만원을 넘겼거든요.","display_text":"리셀가 500만원+","emotion":"shock","transition":"Dissolve"}
]
(continue — each rank scene must have "rank": N and a specific price/stat)
''',
    "origin_story": '''
Example (topic: "라면의 탄생"):
[
  {"scene_num":1,"narration":"라면이 원래 전쟁 때문에 생긴 거 알아요?","display_text":"전쟁이 만든\\n라면?","emotion":"shock","transition":"Fade_In"},
  {"scene_num":2,"narration":"1958년 일본, 안도 모모후쿠가 발명했어요.","display_text":"1958년\\n안도 모모후쿠","emotion":"neutral","transition":"Dissolve"},
  {"scene_num":3,"narration":"전후 식량난에 미국이 밀가루를 원조했거든요.","display_text":"미국 밀가루\\n원조","emotion":"serious","transition":"Dissolve"}
]
(continue — use years, names, specific historical events)
''',
    "vs_comparison": '''
Example (topic: "아이폰 vs 갤럭시"):
[
  {"scene_num":1,"narration":"둘 중 뭐가 더 나을까요?","display_text":"아이폰 vs\\n갤럭시","emotion":"shock","transition":"Fade_In"},
  {"scene_num":2,"narration":"아이폰 16 프로 카메라는 4800만 화소예요.","display_text":"아이폰\\n4800만 화소","emotion":"serious","transition":"Dissolve"},
  {"scene_num":3,"narration":"갤럭시 S25 울트라는 2억 화소거든요.","display_text":"갤럭시\\n2억 화소","emotion":"shock","transition":"Dissolve"}
]
(continue — always include specific specs, prices, benchmark numbers)
''',
    "myth_buster": '''
Example (topic: "달걀 하루 3개 먹으면 콜레스테롤 위험할까"):
[
  {"scene_num":1,"narration":"달걀 3개, 진짜 위험할까요?","display_text":"달걀 3개\\n위험?","emotion":"shock","transition":"Fade_In"},
  {"scene_num":2,"narration":"하루 3개 이상이면 콜레스테롤 폭발한다고 했죠.","display_text":"콜레스테롤\\n폭발설","emotion":"serious","transition":"Dissolve"},
  {"scene_num":3,"narration":"2024년 하버드 연구에서 3개까지 안전하다고 나왔어요.","display_text":"하버드 연구\\n3개 안전","emotion":"shock","transition":"Dissolve"}
]
(continue — cite specific studies, numbers, verdicts)
''',
    "tutorial_steps": '''
Example (topic: "에어팟 프로 노이즈캔슬링 설정법"):
[
  {"scene_num":1,"narration":"노캔이 안 되면 이거 확인해보세요.","display_text":"노캔 안 될 때","emotion":"neutral","transition":"Dissolve"},
  {"scene_num":2,"narration":"설정 → 블루투스 → 에어팟 옆 i 버튼.","display_text":"Step 1\\n설정 > 블루투스","emotion":"neutral","transition":"Dissolve","rank":1},
  {"scene_num":3,"narration":"노이즈 컨트롤에서 '소음 차단' 선택하세요.","display_text":"Step 2\\n소음 차단 선택","emotion":"neutral","transition":"Dissolve","rank":2}
]
(continue — each step must be a specific, actionable instruction)
''',
    "before_after": '''
Example (topic: "1년 운동 변화"):
[
  {"scene_num":1,"narration":"1년 전엔 계단 3층도 못 올라갔어요.","display_text":"Before\\n계단 3층 실패","emotion":"sad","transition":"Fade_In"},
  {"scene_num":2,"narration":"체지방률이 32%였거든요.","display_text":"체지방률\\n32%","emotion":"sad","transition":"Dissolve"},
  {"scene_num":3,"narration":"매일 30분씩 러닝부터 시작했어요.","display_text":"매일 30분\\n러닝 시작","emotion":"neutral","transition":"Dissolve"}
]
(continue — use specific measurements, timelines, before/after numbers)
''',
    "hot_take": '''
Example (topic: "대학교 안 가도 된다"):
[
  {"scene_num":1,"narration":"솔직히 대학 안 가도 돼요.","display_text":"대학\\n필요 없다?","emotion":"shock","transition":"Fade_In"},
  {"scene_num":2,"narration":"빌 게이츠, 저커버그 다 중퇴했잖아요.","display_text":"빌 게이츠\\n저커버그 중퇴","emotion":"serious","transition":"Dissolve"},
  {"scene_num":3,"narration":"근데 대졸 평균 연봉이 3400만원 더 높거든요.","display_text":"연봉 차이\\n3400만원","emotion":"serious","transition":"Dissolve"}
]
(continue — mix strong opinions with counter-data)
''',
}


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
    body += _QUALITY_RULES
    example = _EXAMPLES.get(template_type, "")
    if example:
        body += f"\n{example}"
    if tone_rule:
        body += f"\n★ 말투 규칙 (절대 준수): {tone_rule}"
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
