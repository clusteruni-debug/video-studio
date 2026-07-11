"""
Shortform video template prompts for Gemini scene script generation.

Each template includes one golden example scene to anchor quality expectations.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import date

TEMPLATE_TYPES = (
    "community_read", "news_explainer", "reddit_translation", "ranking_list", "origin_story",
    "vs_comparison", "myth_buster", "tutorial_steps", "before_after", "hot_take",
    "authentic_vlog", "persona_story", "kculture_fandom", "podcast_clip",
    "longform_deep_dive", "interview_documentary", "live_recap",
)

LIVE_CHANNEL_OPERATING_TEMPLATES = {
    "authentic_vlog_no_voice": {
        "key": "authentic_vlog_no_voice",
        "label": "A) authentic vlog / no-voice + BGM",
        "platform": "Shorts/Reels/TikTok 9:16",
        "templateTypes": ["authentic_vlog", "persona_story", "live_recap"],
        "captionPreset": {
            "scene1": "top-hook",
            "body": "lower-info or none",
            "maxDisplaySec": {"top-hook": 1.35, "lower-info": 1.8},
        },
        "safeZone": {
            "content": "x=60-950, y=100-1440",
            "caption": "top hook at y~150; lower info around y~1300-1420; never y>1536 or x>950",
            "mobileReadability": "one short viewer-facing phrase, max two compact lines",
        },
        "hookTextPosition": "Top center safe-zone for scene 1 only; body scenes use lower-mid captions or no text.",
        "bgmVoicePolicy": "No-voice by default. Use free/local BGM, native room tone, and subtle SFX. Add voice only when the operator explicitly asks.",
        "cutTransition": "0.35-0.50s fade/dissolve, handheld continuity, no decorative title-card interruption.",
        "thumbnailFirstFrameRule": "First frame must show a real action or object state, no baked-in title, watermark, UI, or generic beauty shot.",
        "sceneCountDurationRule": "4-6 scenes, 2.8-4.0s each, total 12-22s. Every scene needs visible first-second motion.",
        "longformExpansion": "Can expand into 16:9 episode openers by replacing top hooks with chapter titles and preserving direct footage first.",
    },
    "info_top_hook_lower_info": {
        "key": "info_top_hook_lower_info",
        "label": "B) information / top-hook + lower-info captions",
        "platform": "Shorts/Reels/TikTok 9:16",
        "templateTypes": ["news_explainer", "myth_buster", "tutorial_steps", "hot_take", "podcast_clip"],
        "captionPreset": {
            "scene1": "top-hook",
            "body": "lower-info",
            "maxDisplaySec": {"top-hook": 1.35, "lower-info": 1.8},
        },
        "safeZone": {
            "content": "x=60-950, y=100-1440",
            "caption": "top hook y~150, lower facts y~1300-1420, right rail clear",
            "mobileReadability": "one fact per caption; avoid dense slide text",
        },
        "hookTextPosition": "Top center safe-zone with the payoff visible in the underlying clip within two seconds.",
        "bgmVoicePolicy": "Voice-first. Use TTS/voiceover for the viewer-facing explanation; no-voice requires explicit human visual-led approval plus BGM/native-audio review.",
        "cutTransition": "Fast hard cut or short dissolve between evidence beats; avoid slow stock montage pacing.",
        "thumbnailFirstFrameRule": "Use the strongest first evidence frame, with a title candidate in the packet rather than baked into the video.",
        "sceneCountDurationRule": "4-7 scenes, 2.5-4.5s each. Scene 1 states the payoff, scenes 2+ prove it visually.",
        "longformExpansion": "Maps to 16:9 explainer chapters by replacing lower-info with chapter/evidence cards and slower cuts.",
    },
    "ranking_chapter_card_compact": {
        "key": "ranking_chapter_card_compact",
        "label": "C) ranking/list / chapter-card + compact captions",
        "platform": "Shorts/Reels/TikTok 9:16",
        "templateTypes": ["ranking_list", "vs_comparison", "before_after"],
        "captionPreset": {
            "scene1": "top-hook or RankBadge/RankTitle",
            "body": "chapter-card + compact lower-info",
            "maxDisplaySec": {"top-hook": 1.35, "lower-info": 1.8},
        },
        "safeZone": {
            "content": "x=60-950, y=100-1440",
            "caption": "rank badge/title left-top safe, proof chip lower-mid, right/bottom UI clear",
            "mobileReadability": "rank number plus one proof phrase; no three-line item cards",
        },
        "hookTextPosition": "Scene 1 announces the list promise; each ranked scene uses a left-top badge and one lower proof chip.",
        "bgmVoicePolicy": "Voiceover required by default for ranking/list. No-voice requires explicit human visual-led approval; BGM must be real music, not beep/click/test-tone.",
        "cutTransition": "Crisp item-to-item cuts; repeat structure intentionally but change source clip/action every rank.",
        "thumbnailFirstFrameRule": "First frame must communicate the list promise or #1/#3 visual, not a generic stock background.",
        "sceneCountDurationRule": "3-6 ranked beats, 2.5-4.0s each. Repeated source IDs fail unless documented as a callback.",
        "longformExpansion": "Can become 16:9 countdown or chapter segment with larger chapter cards and source citations.",
    },
    "longform_16x9_extension": {
        "key": "longform_16x9_extension",
        "label": "Long-form / 16:9 expansion structure",
        "platform": "YouTube 16:9 or mixed 9:16 cutdown",
        "templateTypes": ["longform_deep_dive", "interview_documentary"],
        "captionPreset": {
            "scene1": "chapter-title",
            "body": "chapter-evidence + lower facts",
            "maxDisplaySec": {"chapter-title": 2.4, "lower-info": 2.0},
        },
        "safeZone": {
            "content": "keep essential subjects inside central 80%; avoid lower-third overload",
            "caption": "chapter title upper-left or center-safe; source chips lower-left, not full-width slides",
            "mobileReadability": "every chapter card must survive 9:16 crop planning",
        },
        "hookTextPosition": "Cold open visual first, then a chapter card; avoid Shorts-style giant captions.",
        "bgmVoicePolicy": "Voice or owned interview audio first. BGM is a bed, not the main event.",
        "cutTransition": "Slower chapter transitions with evidence B-roll; no slideshow as the primary visual proof.",
        "thumbnailFirstFrameRule": "Create a separate thumbnail candidate from the chapter claim plus a real evidence frame.",
        "sceneCountDurationRule": "6-12 scenes for a 2-5 minute segment; cutdowns reuse the strongest 4-6 evidence beats.",
        "longformExpansion": "Primary structure for 16:9; Shorts packets should point back to the long-form chapter source.",
    },
}

_TEMPLATE_TO_OPERATING_TEMPLATE = {
    "authentic_vlog": "authentic_vlog_no_voice",
    "persona_story": "authentic_vlog_no_voice",
    "live_recap": "authentic_vlog_no_voice",
    "news_explainer": "info_top_hook_lower_info",
    "myth_buster": "info_top_hook_lower_info",
    "tutorial_steps": "info_top_hook_lower_info",
    "hot_take": "info_top_hook_lower_info",
    "podcast_clip": "info_top_hook_lower_info",
    "ranking_list": "ranking_chapter_card_compact",
    "vs_comparison": "ranking_chapter_card_compact",
    "before_after": "ranking_chapter_card_compact",
    "longform_deep_dive": "longform_16x9_extension",
    "interview_documentary": "longform_16x9_extension",
}


def get_live_channel_operating_templates() -> dict[str, dict]:
    return deepcopy(LIVE_CHANNEL_OPERATING_TEMPLATES)


def operating_template_for(template_type: str, layout_variant_key: str = "") -> dict:
    normalized_template = str(template_type or "").strip()
    normalized_layout = str(layout_variant_key or "").strip()
    if normalized_layout.startswith(("rank-", "one-question")):
        key = "ranking_chapter_card_compact"
    elif normalized_layout.startswith(("chapter-", "documentary-", "timeline-", "headline-")):
        key = "longform_16x9_extension"
    else:
        key = _TEMPLATE_TO_OPERATING_TEMPLATE.get(normalized_template, "info_top_hook_lower_info")
    return deepcopy(LIVE_CHANNEL_OPERATING_TEMPLATES[key])

_CONTROLLED_CAMERA_STYLE_LEXICON = """
CONTROLLED CAMERA/STYLE LEXICON (use only when tied to a concrete subject + action):
- camera: handheld phone camera, locked close shot, macro close-up, over-the-shoulder, slow push-in, gentle pan, tilt, natural handheld drift.
- light/place: warm practical light, fluorescent office light, natural daylight, evening street light, cafe counter light, subway platform light.
- continuity: same subject, same outfit, same prop, same location, matching palette, visible first-second motion.
- Do NOT write standalone style words like "cinematic", "mood", "vibe", or "beautiful" unless the sentence also names the subject, action, camera/light, and first-second motion.
"""

_JSON_FORMAT = """Each element: {{ "scene_num": N, "narration": "full spoken text for TTS (60-100 Korean chars, 3-4 sentences)", "display_text": "KEY phrase extracted FROM narration (max 12 chars/line, max 2 lines)", "visual_action": "concrete Grok/local video shot seed with subject, action, place, camera/light, and first-second motion", "image_prompt": "English image search query for Google Images — be SPECIFIC (product name, brand, place name)", "emotion": "neutral|funny|serious|shock|sad", "fallback_prompt": "alt query", "transition": "Dissolve" }}"""

_VISUAL_LED_TEMPLATE_TYPES = frozenset({
    "authentic_vlog",
    "persona_story",
    "kculture_fandom",
    "live_recap",
})

_VISUAL_LED_JSON_FORMAT = """Each element: {{ "scene_num": N, "narration": "", "voiceover": "", "display_text": "short Korean viewer caption, max 12 chars/line and max 2 lines", "viewer_caption": "same compact caption text", "visual_action": "concrete visible action for Grok/local video, including first-second motion", "image_prompt": "English Grok/local video prompt seed with subject, action, place, light, camera", "caption_preset": "top-hook|lower-info|none", "audio_design_mode": "no-voice", "emotion": "neutral|funny|serious|shock|sad", "fallback_prompt": "alt visual action", "transition": "Dissolve" }}"""

_QUALITY_RULES = """
NARRATION QUALITY RULES (반드시 준수):
- Scene 1 (hook): 1-2 sentences, 25-40 Korean chars (= 2-3 seconds — 짧고 강렬하게)
- Scene 2+ (body): 3-4 natural spoken sentences, 60-100 Korean chars total (= 5-8 seconds when spoken at +35% speed)
- Every narration MUST contain a SPECIFIC fact: number, price, date, name, or quote
- NEVER use vague filler — every sentence must add new information
- BAD: "큰 변화가 예상돼요" / "많은 관심을 받고 있어요" / "주목할 만해요" / "정말 대단하죠"
- BAD: "이건 정말 놀라운 일이에요" / "다들 깜짝 놀랐어요" / "엄청난 인기를 끌고 있어요"
- GOOD: "채굴 보상이 6.25에서 3.125 비트코인으로 줄어들거든요. 공급이 반토막 나는 거예요."
- GOOD: "출시가가 16만원이었는데 지금 리셀가는 500만원을 넘겼어요. 무려 31배가 된 거예요."
- GOOD: "2024년 하버드 의대에서 38만 명을 대상으로 10년간 추적 조사했거든요."

LANGUAGE RULES (반드시 준수):
- Output MUST be 100% Korean (한국어). NO Japanese (ベッド, カタカナ), NO Chinese (漢字), NO English words unless they are brand names
- Use natural spoken Korean: 구어체, not 문어체
- Correct grammar: "피어요" not "핀이에요", "알려드릴게요" not "알려드릴겠습니다"

DISPLAY_TEXT RULES (반드시 준수):
- display_text MUST be a key phrase EXTRACTED from narration — never independent new text
- WRONG: narration="비트코인 가격이 10만 달러를 돌파했어요" / display_text="시장 급등"
- RIGHT: narration="비트코인 가격이 10만 달러를 돌파했어요" / display_text="10만 달러\\n돌파"
- Max 2 lines, max 12 chars per line — show the KEY number or keyword from narration

IMAGE_PROMPT RULES:
- image_prompt is used for Google Image Search — write it like a search query, NOT an art prompt
- GOOD: "Nike Air Max 1/97 Sean Wotherspoon sneaker" (specific product)
- GOOD: "Samsung 3nm chip wafer factory" (specific thing)
- BAD: "futuristic technology concept with blue glow" (abstract)
- BAD: "beautiful landscape with mountains" (generic)

VISUAL_ACTION RULES:
- visual_action is the Grok/local video prompt seed. It is NOT the same as image_prompt.
- Every scene MUST include visual_action with subject + action + place + camera/light + first-second motion.
- Never feed a raw Google image search query into visual_action.
"""

_VISUAL_LED_QUALITY_RULES = """
VISUAL-LED GROK/LOCAL VIDEO QUALITY RULES (반드시 준수):
- Default audio_design_mode MUST be "no-voice". narration and voiceover MUST be "" unless the operator explicitly asks for spoken narration.
- visual_action, not narration, is the source of the Grok/local video prompt. It must describe one concrete visible action, subject, place, light, camera, and first-second motion.
- NEVER explain production intent to the viewer: no "광고처럼 안 보이게", "AI 티가 나서", "컷마다 얼굴이 바뀌면", "자막 안전", "레이아웃", "프롬프트", "체크리스트" in narration/display_text/viewer_caption.
- display_text/viewer_caption must be a viewer-facing Korean phrase, max 2 lines and max 12 chars per line. It is not required to be extracted from narration for visual-led templates.
- caption_preset: scene 1 uses "top-hook" for a short hook; body scenes use "lower-info" only when the caption adds meaning, otherwise "none".
- Scene 1 must read visually in the first 2 seconds without TTS. Name the immediate motion in visual_action.
- Scenes must preserve the same subject/prop/location/palette/camera language when the format is Grok-first/persona/story.
- image_prompt must be a concrete video prompt seed for Grok/local video, not a generic stock search phrase.
"""

_HOOK_INSTRUCTION = """★★★ 씬 1은 반드시 시청자를 잡는 훅(Hook)이어야 합니다:
- narration: 말했을 때 3초 이내 (한국어 max 30자). 질문이나 충격적 사실로 시작
- emotion: 반드시 "shock" 또는 "funny" (절대 "neutral" 사용 금지)
- display_text: 한 줄, max 10자 — 질문 또는 놀라운 주장
- image_prompt: 영상에서 가장 눈에 띄는 이미지 검색어
- transition: "Fade_In"
- GOOD hooks: "이거 실화임?" / "진짜 500만원짜리 신발이래요" / "아직도 이렇게 먹어요?"
- BAD hooks: "오늘은 ~에 대해 알아볼게요" / "안녕하세요 여러분" (지루한 인사)
"""

_VISUAL_LED_HOOK_INSTRUCTION = """★★★ visual-led 씬 1은 TTS 없이도 보이는 훅이어야 합니다:
- narration/voiceover: 기본값은 빈 문자열. 제작 의도나 영상 설명을 말하지 마세요.
- visual_action: 첫 1초 안에 움직임이 시작되는 구체적인 행동을 쓰세요.
- display_text/viewer_caption: 짧은 한국어 훅 한 줄 또는 두 줄, max 12 chars/line.
- caption_preset: "top-hook". 이후 씬은 lower-info 또는 none 위주.
- emotion: "shock" 또는 "funny"가 가능하지만, 실제 브이로그/루틴이면 과장보다 관찰감이 우선입니다.
- BAD: "오늘은 이 영상을 만들었습니다" / "AI 티가 안 나게 구성합니다" / "자막 안전 영역을 남깁니다"
"""


_HOOK_EXEMPT = frozenset({"reddit_translation", "ranking_list", "tutorial_steps"})

# ---------------------------------------------------------------------------
# Golden examples — one per template, showing the quality bar we expect
# ---------------------------------------------------------------------------
_EXAMPLES = {
    "news_explainer": '''
Example (topic: "삼성전자 3나노 수율 돌파"):
[
  {"scene_num":1,"narration":"삼성이 3나노에서 역대급 성과를 냈어요. 반도체 업계가 완전 뒤집어졌거든요.","display_text":"3나노\\n수율 돌파","emotion":"shock","transition":"Fade_In"},
  {"scene_num":2,"narration":"3나노 공정 수율이 60%를 넘겼는데요. 이게 업계 최초 수치예요. 작년까지만 해도 30%대에 머물렀거든요. 1년 만에 2배가 뛴 거예요.","display_text":"수율 60%+\\n업계 최초","emotion":"serious","transition":"Dissolve"},
  {"scene_num":3,"narration":"경쟁사 TSMC는 현재 55% 수준이에요. 삼성이 처음으로 파운드리 수율에서 TSMC를 앞지른 건데요. 이게 왜 중요하냐면 수율이 곧 수익률이거든요.","display_text":"TSMC 55%\\nvs 삼성 60%","emotion":"serious","transition":"Dissolve"}
]
(continue — every narration 60-100 chars, 3-4 sentences, concrete numbers/names)
''',
    "community_read": '''
Example (topic: "자취방 월세 50만원인데 관리비가 30만원"):
[
  {"scene_num":1,"narration":"월세보다 관리비가 더 비싼 집이 실제로 있대요. 진짜 이게 말이 되나 싶은 사연인데요.","display_text":"관리비가\\n월세보다 비싸?","emotion":"shock","transition":"Fade_In"},
  {"scene_num":2,"narration":"원래 월세가 50만원이었거든요. 서울 외곽인데 50만원이면 저렴한 편이잖아요. 그래서 고민 없이 바로 계약했대요. 보증금도 500만원으로 적었거든요.","display_text":"월세 50만원\\n바로 계약","emotion":"neutral","transition":"Dissolve"},
  {"scene_num":3,"narration":"그런데 첫 달 관리비 고지서가 30만원이 찍혀 나온 거예요. 난방비만 18만원이었대요. 전기료 7만원에 수도세 5만원까지 합쳐진 금액이었거든요.","display_text":"관리비 30만원\\n난방비 18만","emotion":"shock","transition":"Dissolve"}
]
(continue — 60-100 chars, specific numbers, direct quotes)
''',
    "reddit_translation": '''
Example (topic: "미국인이 한국 편의점 가서 충격받은 이야기"):
[
  {"scene_num":1,"narration":"한국 편의점에서 삼각김밥을 처음 봤대요. 이 삼각형 모양이 뭐냐고 한참을 쳐다봤다고요. 뜯는 법도 몰라서 옆 사람한테 물어봤다고요.","display_text":"삼각김밥 충격","emotion":"funny","transition":"Dissolve"},
  {"scene_num":2,"narration":"참치마요 하나에 1200원이라고요. 미국 돈으로 90센트도 안 하는 거예요. 미국 편의점 샌드위치가 8달러인데 맛은 비교도 안 된대요.","display_text":"1200원\\n(약 $0.90)","emotion":"shock","transition":"Dissolve"},
  {"scene_num":3,"narration":"그리고 편의점에서 라면을 끓여 먹을 수 있다는 게 충격이었대요. 미국에선 상상도 못 하는 거거든요. 한국이 미쳤다고 했어요.","display_text":"편의점 라면\\n미국엔 없다","emotion":"funny","transition":"Dissolve","is_commentary":true}
]
(continue — 60-100 chars per narration, price/cultural comparisons)
''',
    "ranking_list": '''
Example (topic: "세계에서 가장 비싼 운동화 Top 5"):
[
  {"scene_num":1,"narration":"세계에서 가장 비싼 운동화 Top 5를 알려드릴게요. 진짜 집 한 채 값인 신발도 있거든요. 5위부터 시작합니다!","display_text":"Top 5\\n비싼 운동화","emotion":"shock","transition":"Fade_In"},
  {"scene_num":2,"narration":"5위, 나이키 에어맥스 1/97 숀 워더스푼이에요. 2017년에 나온 한정판인데요. 출시가가 16만원이었거든요. 근데 지금 리셀가는 무려 500만원을 넘겼어요.","display_text":"5위\\n숀 워더스푼\\n500만원","emotion":"shock","transition":"Slide_Left","rank":5},
  {"scene_num":3,"narration":"4위, 나이키 에어 조던 1 시카고예요. 1985년에 처음 나온 모델인데요. 마이클 조던이 직접 신었던 오리지널은 7000만원에 낙찰됐거든요.","display_text":"4위\\n에어 조던 1\\n7000만원","emotion":"shock","transition":"Slide_Left","rank":4}
]
(continue — EVERY rank scene MUST have "rank": N. 60-100 chars, product name + price/stat)
''',
    "origin_story": '''
Example (topic: "라면의 탄생"):
[
  {"scene_num":1,"narration":"라면이 원래 전쟁 때문에 생긴 거 알아요? 진짜 뜻밖의 탄생 배경이에요.","display_text":"전쟁이 만든\\n라면?","emotion":"shock","transition":"Fade_In"},
  {"scene_num":2,"narration":"1958년 일본에서 안도 모모후쿠라는 사람이 발명했어요. 당시 나이가 48세였거든요. 사업 실패하고 빈털터리였는데 라면으로 인생 역전한 거예요.","display_text":"1958년\\n안도 모모후쿠","emotion":"neutral","transition":"Dissolve"},
  {"scene_num":3,"narration":"2차 대전 후 일본이 식량난이었는데요. 미국이 밀가루를 원조했어요. 일본 정부는 빵을 만들라고 했는데 안도는 국수를 생각한 거예요. 동양인은 국수를 더 좋아하니까요.","display_text":"전후 식량난\\n밀가루 원조","emotion":"serious","transition":"Dissolve"}
]
(continue — 60-100 chars, years, names, specific historical events)
''',
    "vs_comparison": '''
Example (topic: "아이폰 vs 갤럭시"):
[
  {"scene_num":1,"narration":"아이폰이랑 갤럭시, 진짜 어느 쪽이 더 나을까요? 스펙으로 정면 비교해볼게요.","display_text":"아이폰 vs\\n갤럭시","emotion":"shock","transition":"Fade_In"},
  {"scene_num":2,"narration":"아이폰 16 프로 카메라는 4800만 화소예요. 근데 센서 크기가 1/1.14인치로 커졌거든요. 이전 모델보다 65% 더 많은 빛을 받아들인대요.","display_text":"아이폰\\n4800만 화소","emotion":"serious","transition":"Dissolve"},
  {"scene_num":3,"narration":"갤럭시 S25 울트라는 2억 화소예요. 숫자만 보면 4배 차이가 나는 거예요. 다만 화소 수가 높다고 무조건 좋은 건 아니거든요. 센서 크기가 더 중요해요.","display_text":"갤럭시\\n2억 화소","emotion":"shock","transition":"Dissolve"}
]
(continue — 60-100 chars, specific specs, prices, benchmark numbers)
''',
    "myth_buster": '''
Example (topic: "달걀 하루 3개 먹으면 콜레스테롤 위험할까"):
[
  {"scene_num":1,"narration":"달걀 하루 3개 먹으면 진짜 위험할까요? 오늘 팩트체크 해볼게요.","display_text":"달걀 3개\\n위험?","emotion":"shock","transition":"Fade_In"},
  {"scene_num":2,"narration":"예전엔 하루 1개 이상이면 콜레스테롤이 폭발한다고 했어요. 의사들도 그렇게 말했거든요. 2000년대까지만 해도 달걀은 건강의 적이었어요.","display_text":"콜레스테롤\\n폭발설","emotion":"serious","transition":"Dissolve"},
  {"scene_num":3,"narration":"그런데 2024년 하버드 의대 연구에서 하루 3개까지 안전하다는 결과가 나왔어요. 38만 명을 대상으로 10년간 추적 조사한 결과거든요. 심혈관 위험 증가가 없었대요.","display_text":"하버드 연구\\n38만명 대상","emotion":"shock","transition":"Dissolve"}
]
(continue — 60-100 chars, cite specific studies with numbers)
''',
    "tutorial_steps": '''
Example (topic: "에어팟 프로 노이즈캔슬링 설정법"):
[
  {"scene_num":1,"narration":"에어팟 프로 노캔이 안 되면 이거 확인해보세요. 설정 하나로 바로 해결돼요. 10초면 끝나요.","display_text":"노캔 안 될 때","emotion":"neutral","transition":"Dissolve"},
  {"scene_num":2,"narration":"먼저 설정 앱에서 블루투스로 들어가세요. 에어팟 옆에 있는 i 버튼을 눌러주세요. 파란색 원 안에 있는 작은 i 아이콘이에요.","display_text":"Step 1\\n설정 > 블루투스","emotion":"neutral","transition":"Dissolve","rank":1},
  {"scene_num":3,"narration":"노이즈 컨트롤 메뉴에서 소음 차단을 선택하세요. 이게 노이즈캔슬링 활성화 버튼이에요. 투명 모드랑 끄기도 여기서 바꿀 수 있어요.","display_text":"Step 2\\n소음 차단 선택","emotion":"neutral","transition":"Dissolve","rank":2}
]
(continue — 60-100 chars per step, specific and actionable)
''',
    "before_after": '''
Example (topic: "1년 운동 변화"):
[
  {"scene_num":1,"narration":"1년 전엔 계단 3층도 못 올라갔어요. 숨이 턱까지 차서 중간에 쉬어야 했거든요.","display_text":"Before\\n계단 3층 실패","emotion":"sad","transition":"Fade_In"},
  {"scene_num":2,"narration":"당시 체지방률이 32%였어요. 키 175에 몸무게가 92kg이었거든요. 건강검진에서 비만 판정 받고 충격 먹었대요. 의사가 이러다 당뇨 온다고 했거든요.","display_text":"체지방률 32%\\n92kg","emotion":"sad","transition":"Dissolve"},
  {"scene_num":3,"narration":"매일 아침 30분씩 러닝부터 시작했어요. 처음엔 1km도 못 뛰었거든요. 3개월 뒤에야 겨우 3km를 쉬지 않고 뛸 수 있게 됐대요.","display_text":"매일 30분\\n러닝 시작","emotion":"neutral","transition":"Dissolve"}
]
(continue — 60-100 chars, specific measurements and timelines)
''',
    "hot_take": '''
Example (topic: "대학교 안 가도 된다"):
[
  {"scene_num":1,"narration":"솔직히 대학 안 가도 된다고 생각해요. 근거가 있거든요.","display_text":"대학\\n필요 없다?","emotion":"shock","transition":"Fade_In"},
  {"scene_num":2,"narration":"빌 게이츠, 저커버그, 잡스 다 중퇴했잖아요. 세계 최고 부자들이 대학을 안 마친 거예요. 애플, 메타, 마이크로소프트가 전부 중퇴생 작품인 거거든요.","display_text":"빌 게이츠\\n저커버그 중퇴","emotion":"serious","transition":"Dissolve"},
  {"scene_num":3,"narration":"근데 통계를 보면 대졸 평균 연봉이 고졸보다 3400만원 높아요. 생애소득은 5억 차이가 나거든요. 중퇴 성공은 생존자 편향이라는 반론도 있어요.","display_text":"연봉 차이\\n3400만원","emotion":"serious","transition":"Dissolve"}
]
(continue — 60-100 chars, mix strong opinions with counter-data)
''',
    "authentic_vlog": '''
Example (topic: "성수동 혼밥 브이로그"):
[
  {"scene_num":1,"narration":"","voiceover":"","display_text":"12분 안에\\n들어간 집","viewer_caption":"12분 안에\\n들어간 집","visual_action":"A Korean office worker in a navy coat slows down outside a small Seongsu noodle shop; steam moves from the door in the first second, handheld phone camera, warm evening light.","image_prompt":"vertical handheld phone video of Korean office worker outside small Seongsu noodle shop, steam in first second, warm evening light","caption_preset":"top-hook","audio_design_mode":"no-voice","emotion":"neutral","transition":"Fade_In"},
  {"scene_num":2,"narration":"","voiceover":"","display_text":"손 씻고\\n주문 기다림","viewer_caption":"손 씻고\\n주문 기다림","visual_action":"Same worker washes hands at a tiny sink and checks the paper order slip; water and hand motion start immediately, low warm restaurant light, close handheld framing.","image_prompt":"vertical realistic handheld video, same Korean office worker washing hands beside paper order slip, warm restaurant light","caption_preset":"lower-info","audio_design_mode":"no-voice","emotion":"neutral","transition":"Dissolve"}
]
(continue — no-voice, real hand/space actions, compact lower captions only when useful)
''',
    "persona_story": '''
Example (topic: "AI 햄찌 직장 생존기"):
[
  {"scene_num":1,"narration":"","voiceover":"","display_text":"잠깐만\\n보자","viewer_caption":"잠깐만\\n보자","visual_action":"Recurring office persona pauses at a meeting-room door, one hand hovering over the handle while fluorescent light flickers in the first second; same gray laptop tucked under arm, documentary handheld camera.","image_prompt":"vertical photorealistic handheld video of recurring Korean office persona pausing at meeting room door with gray laptop, first second hand motion","caption_preset":"top-hook","audio_design_mode":"no-voice","emotion":"shock","transition":"Fade_In"},
  {"scene_num":2,"narration":"","voiceover":"","display_text":"노트북만\\n먼저 내려놓음","viewer_caption":"노트북만\\n먼저 내려놓음","visual_action":"Same persona enters the same office corner and quietly places the gray laptop on the desk before sitting; hand and laptop motion start immediately, muted office palette, same camera height.","image_prompt":"vertical photorealistic video, same Korean office persona placing gray laptop on desk, muted office palette, handheld continuity","caption_preset":"lower-info","audio_design_mode":"no-voice","emotion":"serious","transition":"Dissolve"}
]
(continue — same character/place/prop continuity, no explanatory TTS, visual action carries the story)
''',
    "kculture_fandom": '''
Example (topic: "케이팝 데몬 헌터스 팬덤 포인트"):
[
  {"scene_num":1,"narration":"이 장면이 팬들 사이에서 계속 돌았던 이유가 있어요. 안무보다 표정 타이밍이 먼저 터졌거든요.","display_text":"표정 타이밍","emotion":"shock","transition":"Fade_In"},
  {"scene_num":2,"narration":"직접 음원이나 원본 영상을 쓰지 말고, 커버 동작이나 팬아트 제작 과정처럼 대체 가능한 컷으로 가야 해요. 그래야 저작권 리스크가 줄어요.","display_text":"원본 대신\\n대체 컷","emotion":"serious","transition":"Dissolve"}
]
(continue — fandom context, copyright-safe substitute visuals, dance/cosplay/POV structure)
''',
    "podcast_clip": '''
Example (topic: "롱폼 인터뷰 핵심 30초"):
[
  {"scene_num":1,"narration":"이 인터뷰에서 제일 센 문장은 마지막이 아니라 18분 42초에 나왔어요. 여기만 잘라야 쇼츠가 됩니다.","display_text":"18분 42초","emotion":"shock","transition":"Fade_In"},
  {"scene_num":2,"narration":"원본 오디오는 직접 업로드하거나 사용 권한이 있을 때만 쓰세요. 없으면 핵심 문장을 TTS로 요약하고, 화면은 관련 B롤과 챕터 자막으로 구성합니다.","display_text":"권한 없으면\\n요약 TTS","emotion":"serious","transition":"Dissolve"}
]
(continue — long-form chapter hook, quote-to-context, lower-info captions)
''',
    "longform_deep_dive": '''
Example (topic: "한국 자영업 폐업률이 높아진 이유"):
[
  {"scene_num":1,"narration":"이 문제는 한 줄 요약으로 끝낼 수 없어요. 임대료, 인건비, 배달 수수료가 동시에 움직였거든요.","display_text":"세 비용이\\n동시에 상승","emotion":"serious","transition":"Fade_In"},
  {"scene_num":2,"narration":"첫 챕터는 숫자부터 봐야 합니다. 2025년 기준으로 음식점 운영비에서 인건비와 임대료 비중이 절반을 넘는 경우가 많았어요. 여기에 광고비까지 붙으면 손익분기점이 훨씬 높아집니다.","display_text":"Chapter 1\\n비용 구조","emotion":"serious","transition":"Dissolve"},
  {"scene_num":3,"narration":"두 번째 챕터는 소비 패턴이에요. 손님 수가 줄어든 것보다 더 큰 문제는 객단가와 재방문 주기가 흔들렸다는 점입니다. 그래서 매출은 비슷해 보여도 남는 돈이 줄어드는 구조가 됩니다.","display_text":"Chapter 2\\n소비 패턴","emotion":"neutral","transition":"Dissolve"}
]
(continue — chapter cards, source-backed numbers, slower pacing, lower-info captions)
''',
    "interview_documentary": '''
Example (topic: "동네 서점이 살아남는 방식"):
[
  {"scene_num":1,"narration":"이 이야기는 매출 그래프보다 한 사람의 반복되는 하루를 따라가야 보여요. 그래서 첫 컷은 문 여는 손동작으로 시작합니다.","display_text":"문 여는\\n첫 장면","emotion":"neutral","transition":"Fade_In"},
  {"scene_num":2,"narration":"인터뷰 핵심 문장은 짧게 보여주고, 바로 현장 B롤로 증명해야 합니다. 책을 정리하는 손, 계산대 위 영수증, 단골이 머무는 시간을 같이 보여주면 말이 화면에 붙습니다.","display_text":"말을\\n화면으로 증명","emotion":"serious","transition":"Dissolve"},
  {"scene_num":3,"narration":"권리 있는 원본 인터뷰가 있으면 그 음성을 살리고, 없으면 요약 TTS로 처리하세요. 중요한 건 실제 화자를 흉내 내지 않는 겁니다. 화면은 직접 촬영 컷과 공개 라이선스 자료만 씁니다.","display_text":"권리 없는\\n음성 금지","emotion":"serious","transition":"Dissolve"}
]
(continue — interview quote, observed evidence, restrained chapter captions)
''',
    "live_recap": '''
Example (topic: "성수 팝업 현장 5분 요약"):
[
  {"scene_num":1,"narration":"현장 영상은 화려한 무대보다 줄 선 사람들의 표정에서 시작하는 게 더 좋아요. 오늘 분위기를 5분 안에 정리해볼게요.","display_text":"현장 분위기\\n5분 요약","emotion":"neutral","transition":"Fade_In"},
  {"scene_num":2,"narration":"첫 번째 포인트는 동선이에요. 입장 줄, 포토존, 굿즈 테이블 순서가 보이면 시청자가 실제로 간 것처럼 이해합니다. 지도 카드 하나만 있어도 장면이 훨씬 정리돼요.","display_text":"Point 1\\n동선","emotion":"serious","transition":"Dissolve"},
  {"scene_num":3,"narration":"두 번째는 권리 확인입니다. 공연 음원이나 방송 화면은 넣지 말고, 직접 촬영한 외부 풍경과 저작권 안전한 BGM으로 분위기를 대신 만들어야 합니다.","display_text":"Point 2\\n권리 확인","emotion":"serious","transition":"Dissolve"}
]
(continue — event route, crowd/context, rights-safe ambience, chapter labels)
''',
}


def build_template_prompt(
    topic: str,
    lang_name: str,
    template_type: str,
    tone_rule: str = "",
    scene_count: int = 8,
    custom_instruction: str = "",
    target_duration: str = "30s",
) -> str:
    """Build a Gemini prompt. Topic is repeated at start and end to prevent drift.

    Templates in ``_HOOK_EXEMPT`` skip the hook instruction because their scene 1
    has a structural role (intro/rank/commentary) rather than a retention hook.
    *tone_rule* is appended when non-empty so Gemini respects the same speech style as Groq.
    """
    today = date.today().isoformat()
    body = f"★ 오늘 날짜: {today}. 과거 사건은 과거형으로, 미래 사건만 미래형으로 서술하세요.\n\n"
    body += _build_template_body(topic, lang_name, template_type)
    body += (
        _VISUAL_LED_QUALITY_RULES
        if template_type in _VISUAL_LED_TEMPLATE_TYPES
        else _QUALITY_RULES
    )
    body += _CONTROLLED_CAMERA_STYLE_LEXICON
    operating_template = operating_template_for(template_type)
    body += (
        "\nLIVE CHANNEL OPERATING TEMPLATE (반드시 준수):"
        f"\n- template: {operating_template['label']}"
        f"\n- caption preset: scene 1 {operating_template['captionPreset']['scene1']}; body {operating_template['captionPreset']['body']}"
        f"\n- safe zone: {operating_template['safeZone']['caption']}"
        f"\n- hook text position: {operating_template['hookTextPosition']}"
        f"\n- BGM/voice policy: {operating_template['bgmVoicePolicy']}"
        f"\n- cuts/transitions: {operating_template['cutTransition']}"
        f"\n- thumbnail/first-frame rule: {operating_template['thumbnailFirstFrameRule']}"
        f"\n- scene count/duration rule: {operating_template['sceneCountDurationRule']}"
    )
    per_scene_sec = round({"30s": 30, "1min": 60}.get(target_duration, 30) / scene_count, 1) if scene_count else 4
    body += f"\n★ 총 씬 수: 정확히 {scene_count}개 씬으로 구성하세요."
    body += f"\n★ 목표 영상 길이: {target_duration}. 씬당 약 {per_scene_sec}초 분량으로 작성하세요."
    example = _EXAMPLES.get(template_type, "")
    if example:
        body += f"\n{example}"
    if tone_rule:
        body += f"\n★ 말투 규칙 (절대 준수): {tone_rule}"
    if custom_instruction.strip():
        safe_instruction = custom_instruction.strip()[:300]
        body += f"\n★ 추가 지시: {safe_instruction}"
    if template_type in _HOOK_EXEMPT:
        return body
    hook_instruction = (
        _VISUAL_LED_HOOK_INSTRUCTION
        if template_type in _VISUAL_LED_TEMPLATE_TYPES
        else _HOOK_INSTRUCTION
    )
    return f"{hook_instruction}\n{body}"


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

    if template_type == "authentic_vlog":
        return f"""Write an authentic Korean YouTube vlog/food/travel Shorts script about: "{topic}"

Structure in {lang_name}: quiet human hook(1) -> place/action details(2-4) -> small tension or discovery(5-6) -> personal takeaway(7-8)
- no-voice by default: leave narration and voiceover empty; use BGM/native ambience instead of explanatory TTS
- visual_action: describe direct upload/Grok/local video shots with immediate motion, hands, walking, ordering, receipts, ambient sound
- visuals: direct upload/Grok/local video preferred; Pexels only as support B-roll, never random lifestyle filler
- captions: scene 1 top-hook only if needed, then lower-info or none; avoid giant center captions
- display_text/viewer_caption: viewer-facing Korean only, not production notes

Return ONLY a JSON array about "{topic}". {_VISUAL_LED_JSON_FORMAT}"""

    if template_type == "persona_story":
        return f"""Write a Korean persona/narrative Shorts script about: "{topic}"

Structure in {lang_name}: character hook(1) -> repeated setting/prop(2) -> conflict(3-5) -> small payoff(6-8)
- no-voice by default: leave narration and voiceover empty unless a human-owned voice track is provided
- visual_action: same character, outfit, place, and prop continuity across scenes, with a visible action in the first second
- image_prompt: describe the fixed character bible and camera move for Grok/local video
- captions: top-hook only on scene 1, then lower-info or none
- display_text/viewer_caption: short viewer-facing Korean story beats, never continuity/checklist instructions

Return ONLY a JSON array about "{topic}". {_VISUAL_LED_JSON_FORMAT}"""

    if template_type == "kculture_fandom":
        return f"""Write a Korean K-culture/fandom Shorts script about: "{topic}"

Structure in {lang_name}: fan insight hook(1) -> why it spread(2-3) -> safe substitute visuals(4-6) -> fan CTA(7-8)
- no-voice by default unless the operator asks for commentary; let visuals, safe BGM, and compact captions carry the edit
- visual_action: cover move, cosplay detail, fan-art process, public location, or generated/direct safe substitute with first-second motion
- do not ask to reuse copyrighted music/MV/anime/drama footage directly
- visuals: cover move, cosplay detail, fan-art process, public location, or generated/direct safe substitute
- mention what source must be manually verified for copyright/attribution
- captions: top hook + small lower context, not screen-covering lyrics

Return ONLY a JSON array about "{topic}". {_VISUAL_LED_JSON_FORMAT}"""

    if template_type == "podcast_clip":
        return f"""Write a Korean long-form-to-Shorts clip script about: "{topic}"

Structure in {lang_name}: timestamp/quote hook(1) -> context(2) -> 핵심 주장(3-5) -> why it matters(6-7) -> long-form bridge(8)
- if original audio rights are unavailable, summarize with free TTS instead of pretending it is the speaker
- visuals: speaker/direct clip when owned, otherwise relevant B-roll, waveform, chapter card, and lower-info captions
- keep captions compact and chapter-like, not karaoke-style giant text

Return ONLY a JSON array about "{topic}". {_JSON_FORMAT}"""

    if template_type == "longform_deep_dive":
        return f"""Write a Korean long-form deep-dive video outline about: "{topic}"

Structure in {lang_name}: cold open(1) -> chapter 1 context(2-3) -> chapter 2 evidence(4-5) -> chapter 3 implication(6-7) -> recap/next video bridge(8)
- narration: slower, trustworthy long-form commentary, not Shorts hype
- visuals: chapter cards, sourced B-roll, data/source cards, and calm motion clips
- captions: chapter/title cards and lower-info captions only when they clarify the argument
- every scene must name what visual evidence or free asset slot is needed

Return ONLY a JSON array about "{topic}". {_JSON_FORMAT}"""

    if template_type == "interview_documentary":
        return f"""Write a Korean interview/documentary video outline about: "{topic}"

Structure in {lang_name}: observed opening(1) -> interview quote/context(2-3) -> evidence B-roll(4-5) -> conflict/tension(6) -> takeaway(7-8)
- use owned interview audio/video when available; otherwise summarize with free TTS and do not impersonate the speaker
- visuals: direct interview clip, hands/location details, documents/photos only with rights, and restrained lower captions
- include interview timestamp or ownership note in narration whenever source audio/video is mentioned
- avoid generic stock people pretending to be the subject

Return ONLY a JSON array about "{topic}". {_JSON_FORMAT}"""

    if template_type == "live_recap":
        return f"""Write a Korean live/event recap video outline about: "{topic}"

Structure in {lang_name}: arrival hook(1) -> route/context(2) -> three key moments(3-6) -> crowd/atmosphere proof(7) -> practical takeaway(8)
- no-voice by default when direct event footage/ambience is available; use lower-info captions and BGM instead of explaining the edit
- visual_action: direct event footage or rights-safe context clip with immediate movement and a concrete place/action
- visuals: direct event footage first, then rights-safe venue/city/crowd context
- do not use copyrighted performance clips, broadcast footage, drama/anime clips, or commercial music without rights
- captions: small chapter labels and location/context notes; no lyric-like center captions
- audio: ambient sound or YouTube Audio Library/Mixkit BGM under native ambience or optional voiceover

Return ONLY a JSON array about "{topic}". {_VISUAL_LED_JSON_FORMAT}"""

    # origin_story (default fallback)
    return f"""Write a history/origin storytelling YouTube Shorts about: "{topic}"

Narrative arc in {lang_name}: Hook(1) → Origin(2-3) → Turning point(4-5) → Now(6-7) → Punchline(8)
- narration: storytelling "~였는데요", "~했다고 합니다"
- image_prompt: era-specific descriptions related to "{topic}"

Return ONLY a JSON array about "{topic}". {_JSON_FORMAT}"""
