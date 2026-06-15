"""FFmpeg primitive operations for compose.py.

Extracted from compose.py to keep the orchestrator file under the 660-line limit.
Contains: FFmpeg command wrappers, scene clip construction, audio mixing,
subtitle writers, manifest helpers, and shared constants.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import textwrap
from datetime import datetime
from pathlib import Path

from worker.bridge.templates import operating_template_for
from worker.quality_gate_system import build_render_gate_system
from worker.render.motion import zoompan_filter
from worker.render.transitions import gradient_source_filter
from worker.runtime.tools import probe_tool

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Shared constants (RENDERING-SPEC)
# ---------------------------------------------------------------------------
CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0
FRAME_SIZE = "1080x1920"
FRAME_RATE = "30"
SCENE_SCALE_CROP_FILTER = (
    "fps=30,"
    "scale=1080:1920:force_original_aspect_ratio=increase:flags=lanczos,"
    "crop=1080:1920"
)
SCENE_VISUAL_POLISH_FILTER = "unsharp=3:3:0.28:3:3:0.10,eq=contrast=1.025:saturation=1.030:gamma=1.010"
FINAL_VISUAL_POLISH_FILTER = "fps=30,scale=1080:1920:flags=lanczos,unsharp=3:3:0.18:3:3:0.06,eq=contrast=1.010:saturation=1.010:gamma=1.005,format=yuv420p"
VIDEO_FILTER = f"{SCENE_SCALE_CROP_FILTER},{SCENE_VISUAL_POLISH_FILTER},format=yuv420p"
H264_RENDER_ARGS = [
    "-c:v", "libx264",
    "-preset", "medium",
    "-crf", "18",
    "-profile:v", "high",
    "-level", "4.2",
    "-pix_fmt", "yuv420p",
]
QUALITY_RATCHET_REQUIRED_FIELDS = (
    "previousBaseline",
    "rejectionCause",
    "changedLever",
    "expectedVisibleImprovement",
    "actualProof",
    "nextRatchet",
)
QUALITY_RATCHET_VIEWER_FACING_TERMS = (
    "source",
    "asset",
    "storyboard",
    "script",
    "hook",
    "caption",
    "subtitle",
    "tts",
    "voice",
    "audio",
    "bgm",
    "layout",
    "edit",
    "cut",
    "pacing",
    "transition",
    "render",
    "filter",
    "sharp",
    "contrast",
    "color",
    "grok",
    "gemini",
    "stock",
)
AUDIENCE_INTEREST_GENERIC_TERMS = (
    "people are interested",
    "viral",
    "trending",
    "popular",
    "hot topic",
    "good topic",
    "interesting topic",
    "everyone likes",
    "요즘 관심",
    "사람들이 관심",
    "바이럴",
    "트렌딩",
    "인기 소재",
    "흥미로운 소재",
    "좋은 소재",
)
UPLOAD_CANDIDATE_FLAGS = (
    "uploadCandidate",
    "uploadCandidateRequired",
    "publishCandidate",
)
UPLOAD_CANDIDATE_ALLOWED_PROVIDER_MODES = {"grok-only", "gemini-only"}
CAPTION_PURPOSES = {"hook", "friction", "action", "payoff", "context", "proof", "none"}
SCENE_COLORS = ["#183153", "#3f5c7a", "#7c4d3a", "#556b2f", "#5f4b8b", "#7b3f61"]
DEFAULT_MOTION_PRESET = "none"
DEFAULT_TRANSITION_TYPE = "fade"
DEFAULT_TRANSITION_DURATION = 0.5

BGM_EXTENSIONS = {".mp3", ".wav", ".m4a", ".ogg", ".flac"}
BGM_VOLUME = float(os.environ.get("VIDEO_STUDIO_BGM_VOLUME", "0.28"))
BGM_MIX_GAIN = float(os.environ.get("VIDEO_STUDIO_BGM_MIX_GAIN", "0.55"))
BGM_DUCK_THRESHOLD = float(os.environ.get("VIDEO_STUDIO_BGM_DUCK_THRESHOLD", "0.08"))
BGM_DUCK_RATIO = float(os.environ.get("VIDEO_STUDIO_BGM_DUCK_RATIO", "2.6"))
BGM_DUCK_RELEASE_MS = int(os.environ.get("VIDEO_STUDIO_BGM_DUCK_RELEASE_MS", "180"))
SFX_VOLUME = 0.8  # SFX volume relative to narration
FINAL_AUDIO_LOUDNORM_ENABLED = os.environ.get("VIDEO_STUDIO_FINAL_AUDIO_LOUDNORM", "1").strip().lower() not in {
    "0",
    "false",
    "no",
}
FINAL_AUDIO_TARGET_I = float(os.environ.get("VIDEO_STUDIO_FINAL_AUDIO_TARGET_I", "-14.0"))
FINAL_AUDIO_TARGET_TP = float(os.environ.get("VIDEO_STUDIO_FINAL_AUDIO_TARGET_TP", "-1.5"))
FINAL_AUDIO_TARGET_LRA = float(os.environ.get("VIDEO_STUDIO_FINAL_AUDIO_TARGET_LRA", "11.0"))
FINAL_AUDIO_LIMITER_TP = float(
    os.environ.get("VIDEO_STUDIO_FINAL_AUDIO_LIMITER_TP", "-4.0")
)
FINAL_AUDIO_LIMITER_ATTACK_MS = float(os.environ.get("VIDEO_STUDIO_FINAL_AUDIO_LIMITER_ATTACK_MS", "5"))
FINAL_AUDIO_LIMITER_RELEASE_MS = float(os.environ.get("VIDEO_STUDIO_FINAL_AUDIO_LIMITER_RELEASE_MS", "50"))

FREE_STOCK_PROVIDERS = {"pexels-video", "pexels", "pixabay-video", "pixabay", "mixkit", "freesound", "klipy", "tenor"}
FREE_AUDIO_STOCK_PROVIDERS = {
    "local-bgm",
    "youtube-audio-library",
    "youtube-audio",
    "mixkit-audio",
    "mixkit",
    "pixabay-audio",
    "pixabay",
    "freesound",
    "local-sfx",
}
FREE_NARRATION_PROVIDERS = {"edge-tts", "windows-speech", "windows-tts", "edge"}
DRAFT_ONLY_NARRATION_PROVIDERS = {"windows-speech", "windows-tts"}
LOCAL_ORIGINAL_VIDEO_INTENTS = {"wan", "ltx-video", "hunyuan-video"}
INTERNET_SOURCE_TAGS = {
    "internet-source",
    "internet-image",
    "internet-gif",
    "internet-meme",
    "internet-meme-gif",
    "meme-image",
    "reaction-image",
    "community-image",
    "web-image",
    "meme-gif",
    "reaction-gif",
    "community-gif",
    "web-gif",
    "public-domain-image",
    "public-domain-gif",
    "cc-image",
    "cc-gif",
    "wikimedia-image",
    "wikimedia-gif",
}
STILL_IMAGE_PRIMARY_ALLOWED_TERMS = {
    "meme",
    "reaction",
    "jjalg",
    "screenshot",
    "screen-capture",
    "source-capture",
    "web-capture",
    "official-capture",
    "document-capture",
    "evidence-card",
    "reference-card",
    "source-card",
    "data-card",
    "chart",
    "graph",
    "table-source",
    "document-source",
    "짤",
    "움짤",
    "밈",
}
INTERNET_SOURCE_FETCH_PASS_STATUSES = {"fetched", "downloaded", "pass", "ok", "ready", "saved"}
INTERNET_SOURCE_MEDIA_KINDS = {"gif", "video", "image"}
SOURCE_FIRST_REQUIRED_FLAGS = (
    "sourceFirstRequired",
    "sourceFirstQualityGateRequired",
    "grokGeminiSourceRequired",
)
GEMINI_VIDEO_SOURCE_TAGS = {
    "gemini",
    "gemini-video",
    "gemini-handoff",
    "gemini-web-handoff",
    "gemini-web-video",
    "gemini-video-handoff",
}
GROK_SOURCE_PROVENANCE_ACCEPTABLE_STATUSES = {
    "accepted-source-library-proof",
    "browser-native-original-download",
    "browser-control-cache-origin-import",
    "browser-control-cache-range-reassembly",
    "local-mp4-download-unverified",
    "local-mp4-source-unverified",
}
GROK_SOURCE_CONFIRMATION_REQUIRED_STATUSES = {
    "local-mp4-download-unverified",
    "local-mp4-source-unverified",
}
GROK_PREVIEW_CAVEAT_TERMS = (
    "candidate preview only",
    "final grok-main approval still needs",
    "not a final publish packet",
    "needs extra original-download",
    "broader take curation",
    "two-take curation",
)
OWNED_UPLOAD_EVIDENCE_TERMS = (
    "owned phone footage",
    "operator-owned raw footage",
    "phone camera",
    "phone-camera",
    "camera footage",
    "raw camera",
    "raw-camera",
    "operator shot",
    "operator-shot",
    "operator filmed",
    "shot by operator",
    "filmed by operator",
    "screen recording",
    "screen-recorded",
    "direct capture",
    "direct recording",
    "original footage",
    "self-shot",
    "directly filmed",
    "직접 촬영",
    "본인 촬영",
    "직접 녹화",
    "소유 영상",
)
STOCK_REWRAPPED_UPLOAD_EVIDENCE_TERMS = (
    "pexels",
    "pixabay",
    "mixkit",
    "free stock",
    "stock footage",
    "stock video",
    "selected stock",
    "manual stock",
    "royalty-free stock",
    "rights-safe stock",
)
PROCEDURAL_PLACEHOLDER_EVIDENCE_TERMS = (
    "video-studio-local-render",
    "ffmpeg/direct motion",
    "ffmpeg direct motion",
    "local ffmpeg",
    "procedural motion",
    "procedural placeholder",
    "test pattern",
    "test-pattern",
    "color bar",
    "color bars",
    "colour bar",
    "colour bars",
    "colorbar",
    "smpte",
    "smptebars",
    "testsrc",
    "lavfi",
    "local/generated mp4 for video studio qa",
    "generated inside video studio",
)
SAFE_CAPTION_PRESETS = {"none", "center-short", "top-hook", "lower-info"}
CAPTION_LAYOUT_TERMS = (
    "caption", "subtitle", "safe", "occlusion", "subject", "top-safe", "lower",
    "center", "자막", "세이프", "가리지", "피사체", "하단", "상단",
)
SHORTS_CAPTION_SAFE_ZONE_POLICY = {
    "top-hook": "top-left safe area, short first-beat hook, away from right rail",
    "center-short": "center safe area, max two compact lines",
    "lower-info": "lower-mid safe area around 55-65 percent frame height, not bottom UI",
}
SHORTS_CAPTION_MAX_COMPACT_CHARS = {
    "top-hook": 24,
    "center-short": 22,
    "lower-info": 34,
}
SHORTS_CAPTION_MIN_SECONDS_BY_COMPACT_CHAR = {
    "top-hook": 1 / 9.0,
    "center-short": 1 / 10.0,
    "lower-info": 1 / 11.0,
}
SHORTS_CAPTION_READING_SLACK_SEC = 0.18
REFERENCE_EDIT_GRAMMAR_POLICY = {
    "source": "short-form reference extraction",
    "firstHookWindowSec": 2.0,
    "targetAverageCutSec": 3.0,
    "maxUnjustifiedHoldSec": 3.2,
    "requiredTerms": (
        "hook/first-frame",
        "cut rhythm/pacing",
        "caption safe-zone",
        "platform reference",
    ),
}
REFERENCE_EDIT_GRAMMAR_TERMS = (
    "shorts",
    "reels",
    "tiktok",
    "reference",
    "레퍼런스",
    "쇼츠",
    "릴스",
    "틱톡",
    "hook",
    "first frame",
    "first-frame",
    "first two",
    "first 2",
    "첫",
    "훅",
    "cut",
    "pacing",
    "rhythm",
    "beat",
    "tempo",
    "컷",
    "템포",
    "리듬",
    "전환",
    "caption",
    "subtitle",
    "safe zone",
    "safe-zone",
    "safezone",
    "자막",
    "세이프",
    "세이프존",
)
INTERNET_SOURCE_MOTION_EDITORIAL_TERMS = (
    "gif",
    "video",
    "motion",
    "moving",
    "animated",
    "loop",
    "movement",
    "움직",
    "동작",
    "낙하",
    "떨어",
    "움짤",
)
INTERNET_SOURCE_STILL_EDITORIAL_TERMS = (
    "image",
    "photo",
    "still",
    "frame",
    "picture",
    "사진",
    "정지",
    "이미지",
    "프레임",
    "현장",
    "맥락",
    "배경",
)
INTERNET_SOURCE_WEAK_CAPTION_TERMS = (
    "source beat",
    "proof beat",
    "proof scene",
    "motion proof",
    "source proof",
    "internet source",
    "generic source",
    "핵심 장면",
    "증거 장면",
    "소스 장면",
    "장면 설명",
    "맥락 장면",
    "에서 시작",
    "시작",
    "확인",
    "같이 떨어지는 장면",
    "공기 없는 달에서 시작",
)
CONVERSATIONAL_COPY_FORBIDDEN_TERMS = (
    "source beat",
    "proof beat",
    "proof scene",
    "motion proof",
    "source proof",
    "internet source",
    "generic source",
    "layout",
    "caption",
    "subtitle",
    "tts",
    "prompt",
    "핵심 장면",
    "증거 장면",
    "소스 장면",
    "장면 설명",
    "맥락 장면",
    "장면",
    "도입부",
    "제작",
    "프롬프트",
    "레이아웃",
    "자막",
    "내레이션",
    "에서 시작",
    "결론은",
    "확인한다",
    "보여준다",
    "같이 떨어지는 장면",
    "공기 없는 달에서 시작",
)
CONVERSATIONAL_COPY_PROMPT_KEYS = (
    "copyStylePrompt",
    "captionScriptPrompt",
    "scriptStylePrompt",
    "subtitleScriptPrompt",
    "conversationalCopyPrompt",
)
CONVERSATIONAL_COPY_TONE_TERMS = (
    "conversational",
    "spoken",
    "casual",
    "구어체",
    "말하듯",
    "친구한테",
    "대화체",
)
CONVERSATIONAL_COPY_KOREAN_MARKERS = (
    "?",
    "어,",
    "왜",
    "그래",
    "보이죠",
    "있죠",
    "없죠",
    "죠",
    "요",
    "잖",
    "거든",
    "네",
    "봐",
    "맞",
    "진짜",
    "잠깐",
)
CONVERSATIONAL_COPY_ENGLISH_MARKERS = (
    "?",
    "see",
    "look",
    "watch",
    "wait",
    "you",
    "here",
    "now",
    "let's",
)
SCRIPT_QUALITY_PROMPT_LABEL_TERMS = (
    "bare label",
    "label-only",
    "noun-only",
    "source label",
    "scene label",
    "라벨형",
    "라벨만",
    "명사만",
    "소스명",
)
SCRIPT_QUALITY_PROMPT_PAYOFF_TERMS = (
    "hook",
    "turn",
    "payoff",
    "reaction",
    "curiosity",
    "viewer task",
    "훅",
    "전환",
    "반응",
    "호기심",
    "payoff",
    "댓글",
)
SCRIPT_QUALITY_THIN_REACTION_ENDINGS = (
    "보여요",
    "보이죠",
    "바뀌죠",
    "갈리죠",
    "느껴요",
    "느껴지죠",
    "보이나요",
    "see?",
    "shows?",
    "changes?",
    "right?",
)
SCRIPT_QUALITY_SUBSTANTIVE_TURN_TERMS = (
    "에서",
    "순간",
    "때문",
    "같은",
    "다른",
    "정답",
    "댓글",
    "다시",
    "비교",
    "사람마다",
    "갈리는",
    "바로",
    "instead",
    "because",
    "before",
    "after",
    "same",
    "different",
    "comment",
    "answer",
    "real",
    "fake",
    "loop",
    "motion",
)
SCRIPT_QUALITY_MIN_NARRATION_CHARS_BY_PURPOSE = {
    "hook": 22,
    "proof": 22,
    "context": 22,
    "payoff": 26,
}
VIEWER_COPY_TURN_TERMS = (
    "왜",
    "뭐가",
    "먼저",
    "잠깐",
    "지금",
    "같이",
    "보여",
    "보이",
    "바뀌",
    "번갈",
    "뒤집",
    "갈리",
    "다르",
    "느껴",
    "기울",
    "착시",
    "댓글",
    "정답",
    "which",
    "why",
    "first",
    "wait",
    "switch",
    "turns",
    "changes",
    "comment",
)
VIEWER_COPY_ARC_TERMS_BY_PURPOSE = {
    "hook": ("왜", "뭐", "먼저", "잠깐", "지금", "보여", "보이", "wait", "why", "first"),
    "proof": ("바뀌", "번갈", "같은", "먼저", "보여", "보이", "switch", "changes", "same"),
    "context": ("왜", "바뀌", "뒤집", "같은", "다르", "느껴", "switch", "changes", "why"),
    "payoff": ("댓글", "갈리", "다르", "정답", "남겨", "comment", "different", "answer"),
}
CONVERSATIONAL_COPY_REPETITION_STOPWORDS = {
    "그리고",
    "그래서",
    "이번엔",
    "먼저",
    "보세요",
    "봐요",
    "이제",
    "정말",
    "거의",
    "scene",
    "this",
    "that",
    "with",
    "from",
    "here",
    "there",
}
KOREAN_FORMAL_ENDING_PATTERN = re.compile(r"(?:습니다|ㅂ니다|입니다|합니다|됩니다|했습니다|였습니다|니다)")
TTS_PACING_MAX_TEMPO_SPEED = 1.15
TTS_PACING_MAX_KOREAN_COMPACT_CHARS_PER_SEC = 7.6
TTS_PACING_MAX_ENGLISH_WORDS_PER_SEC = 3.4
TTS_PACING_MIN_SUBTITLE_NARRATION_RATIO = 0.30
ENDING_TAIL_MIN_HOLD_SEC = 1.1
ENDING_TAIL_MAX_HOLD_SEC = 1.8
ENDING_FADE_OUT_MIN_SEC = 0.7
ENDING_FINAL_VOICE_MAX_SEC = 4.8
ENDING_FINAL_CAPTION_MIN_VOICE_COVERAGE_RATIO = 0.4
CAPTION_RENDER_MAX_DURATION_BY_PRESET = {
    "top-hook": 1.35,
    "center-short": 1.6,
    "lower-info": 1.8,
}
CAPTION_RENDER_MAX_DURATION_BY_LAYOUT_VARIANT = {
    "korean-reference-caption": 1.95,
    "korean-reference-subtitle": 1.95,
    "korean-readable-caption": 1.95,
    "korean-punch": 1.45,
    "korean-large-caption": 1.45,
    "korean-shorts-caption": 1.45,
}
SOURCE_LOOP_RHYTHM_REVIEW_MIN_CHARS = 36
SOURCE_LOOP_REVIEW_TERMS = (
    "loop",
    "repeat",
    "replay",
    "callback",
    "rhythm",
    "timing",
    "caption",
    "beat",
    "루프",
    "반복",
    "다시",
    "콜백",
    "호흡",
    "타이밍",
    "자막",
)
SOURCE_INTENT_ROLES = {
    "hook",
    "setup",
    "context",
    "proof",
    "closeup",
    "replay",
    "payoff",
    "callback",
    "contrast",
    "reaction",
}
SOURCE_INTENT_GENERIC_TERMS = (
    "contextually",
    "relevant",
    "appropriate",
    "fits the scene",
    "for this scene",
    "맥락에 맞게",
    "어울리는",
    "적절한",
    "좋은 소스",
    "관련 소스",
)
VISUAL_FRAME_REVIEW_REQUIRED_VERDICTS = (
    "sourceDominanceVerdict",
    "captionOcclusionVerdict",
    "layoutNaturalnessVerdict",
    "ttsCaptionSyncVerdict",
    "captionTtsHumanVerdict",
    "motionStabilityVerdict",
    "sourceRepetitionVerdict",
    "endingResolutionVerdict",
)
INTERNET_SOURCE_INTEGRATION_STOPWORDS = {
    "source",
    "scene",
    "viewer",
    "visual",
    "video",
    "image",
    "internet",
    "media",
    "caption",
    "subtitle",
    "layout",
    "proof",
    "asset",
    "beat",
    "beats",
    "feel",
    "feels",
    "real",
    "concrete",
    "generic",
    "visible",
    "장면",
    "시청자",
    "소스",
    "자막",
    "레이아웃",
    "이미지",
    "영상",
    "미디어",
    "증거",
    "역할",
    "선택",
}
PRODUCTION_META_HARD_TERMS = (
    "tts",
    "b-roll",
    "broll",
    "prompt",
    "render",
    "safe zone",
    "youtube ui",
    "프롬프트",
    "렌더",
    "세이프존",
    "safe-zone",
    "제작 기준",
    "다음 제작",
    "체크리스트",
    "소스 선택",
    "후보",
)
PRODUCTION_META_SOFT_TERMS = (
    "컷",
    "씬",
    "장면",
    "화면",
    "자막",
    "시청자",
    "제작",
    "영상",
    "레이아웃",
    "구성",
    "편집",
    "전환",
    "검수",
)
PRODUCTION_META_VIEWER_INTENT_PHRASES = (
    "이영상은",
    "이번영상은",
    "영상의의도",
    "어떤의도",
    "의도를설명",
    "의도를보여",
    "영상의목적",
    "보는사람이",
    "영상을보는사람",
    "시청자가지금무엇을봐야",
    "시청자에게설명",
    "무엇을봐야",
    "화면은그대로",
    "나레이션으로설명",
    "자막으로설명",
    "티티에스",
)
VISUAL_VERDICT_PASS_VALUES = {
    "pass",
    "passed",
    "approved",
    "ready",
    "upload-ready",
    "channel-ready",
    "publish-ready",
    "top-tier-ready",
    "ok",
    "safe",
}
VISUAL_VERDICT_FAIL_VALUES = {
    "fail",
    "failed",
    "blocked",
    "reject",
    "rejected",
    "needs-rework",
    "needs-review",
    "not-ready",
    "not-top-tier",
}

TEMPLATE_SOURCE_GUIDES: dict[str, dict[str, str]] = {
    "news_explainer": {
        "family": "Korean news/fact explainer",
        "sourceMix": "context stock cuts are acceptable only with source-fit rationale; first hook still needs clear motion",
        "freeAssetPlan": "Pexels/Pixabay/Wikimedia context video plus YouTube Audio Library or Mixkit BGM",
    },
    "ranking_list": {
        "family": "Korean ranking/list Shorts",
        "sourceMix": "one distinct clip per rank; repeated stock loops are not acceptable",
        "freeAssetPlan": "Pexels/Pixabay candidates per rank, with source URL/ID retained",
    },
    "tutorial_steps": {
        "family": "Korean tutorial/step Shorts",
        "sourceMix": "direct screen or hand footage should carry the instructional steps",
        "freeAssetPlan": "direct capture first; Pexels/Pixabay or CC0 icons only as support",
    },
    "authentic_vlog": {
        "family": "authentic Korean vlog",
        "sourceMix": "direct operator footage or reviewed Grok/local handoff MP4 should lead; stock is support B-roll",
        "freeAssetPlan": "operator/Grok/local MP4, Pexels/Pixabay support video, YouTube Audio Library or Mixkit BGM",
    },
    "persona_story": {
        "family": "AI persona/story Shorts",
        "sourceMix": "Grok app/web or local Wan/LTX/Hunyuan MP4 should provide the hero motion",
        "freeAssetPlan": "Grok/SuperGrok browser handoff, local model output, Pexels texture inserts",
    },
    "kculture_fandom": {
        "family": "K-culture fandom Shorts",
        "sourceMix": "copyright-safe substitute visuals; direct fan/event footage only when rights are clear",
        "freeAssetPlan": "direct event footage, CC/stock city-stage B-roll, YouTube Audio Library/Mixkit music",
    },
    "podcast_clip": {
        "family": "long-form/podcast clip",
        "sourceMix": "owned long-form clip or TTS summary with B-roll/chapter cards",
        "freeAssetPlan": "owned source clip, Freesound SFX, YouTube Audio Library bed",
    },
    "longform_deep_dive": {
        "family": "Korean long-form deep dive",
        "sourceMix": "chapter cards and source/data cards should carry the argument; stock clips are evidence support only",
        "freeAssetPlan": "operator-made charts, Wikimedia/Pexels/Pixabay evidence media, YouTube Audio Library or Mixkit BGM",
    },
    "interview_documentary": {
        "family": "Korean interview/documentary",
        "sourceMix": "owned interview/location footage should lead; TTS summary is acceptable only with explicit rights fallback",
        "freeAssetPlan": "direct interview/location MP4, Freesound ambience, Wikimedia/Pexels evidence B-roll",
    },
    "live_recap": {
        "family": "Korean live/event recap",
        "sourceMix": "direct event footage should lead; venue/city/stage-light stock only supports atmosphere",
        "freeAssetPlan": "direct phone footage, Mixkit/Pexels/Pixabay context clips, YouTube Audio Library BGM",
    },
}

LONGFORM_NARRATION_TEMPLATES = {
    "longform_deep_dive",
    "interview_documentary",
    "podcast_clip",
}
SHORTFORM_TIGHT_NARRATION_TEMPLATES = {
    "authentic_vlog",
    "ranking_list",
    "tutorial_steps",
    "persona_story",
    "kculture_fandom",
    "live_recap",
}
NO_VOICE_ALLOWED_TEMPLATES = {
    "authentic_vlog",
    "persona_story",
    "kculture_fandom",
    "live_recap",
}
UPLOAD_SOURCE_MIX_REQUIRED_TEMPLATES = {
    "authentic_vlog",
    "ranking_list",
    "tutorial_steps",
    "persona_story",
    "kculture_fandom",
    "live_recap",
}
VOICEOVER_REQUIRED_TEMPLATES = {
    "news_explainer",
    "ranking_list",
    "tutorial_steps",
    "myth_buster",
    "hot_take",
    "vs_comparison",
    "before_after",
    "community_read",
    "reddit_translation",
    "origin_story",
    "podcast_clip",
    "longform_deep_dive",
    "interview_documentary",
}
VISUAL_LED_NO_VOICE_APPROVAL_FIELDS = {
    "visualLedNoVoiceApproved",
    "visual_led_no_voice_approved",
    "humanApprovedNoVoice",
    "human_approved_no_voice",
}
NO_VOICE_AUDIO_MODES = {
    "no-voice",
    "no-narration",
    "music-first",
    "ambient-first",
    "native-audio",
}
VOICEOVER_AUDIO_MODES = {
    "voiceover",
    "narration",
    "tts",
    "full-narration",
}


# ---------------------------------------------------------------------------
# Manifest / path helpers
# ---------------------------------------------------------------------------
def load_manifest(manifest_path: Path) -> dict:
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def safe_text(value: str) -> str:
    return " ".join(value.replace("\r", " ").replace("\n", " ").split())


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _scene_or_asset_value(scene: dict, visual_asset: dict, *keys: str) -> str:
    for container in (scene, visual_asset):
        if not isinstance(container, dict):
            continue
        for key in keys:
            value = str(container.get(key) or "").strip()
            if value:
                return value
    return ""


def _source_loop_group_id(scene: dict, visual_asset: dict | None = None) -> str:
    return _scene_or_asset_value(
        scene,
        visual_asset or {},
        "sourceLoopGroupId",
        "source_loop_group_id",
        "loopGroupId",
        "loop_group_id",
        "intentionalRepeatGroupId",
    )


def _source_loop_repeat_approved(scene: dict, visual_asset: dict | None = None) -> bool:
    visual_asset = visual_asset or {}
    return any(
        value is True or str(value or "").strip().lower() in {"1", "true", "yes", "pass", "approved", "intentional"}
        for value in (
            scene.get("sourceLoopRepeatApproved"),
            scene.get("intentionalSourceLoop"),
            scene.get("sourceLoopApproved"),
            visual_asset.get("sourceLoopRepeatApproved"),
            visual_asset.get("intentionalSourceLoop"),
            visual_asset.get("sourceLoopApproved"),
        )
    )


def _source_loop_review_text(scene: dict, visual_asset: dict | None = None) -> str:
    return _scene_or_asset_value(
        scene,
        visual_asset or {},
        "sourceLoopRhythmReview",
        "loopRhythmReview",
        "sourceLoopReview",
        "loopReview",
        "sourceLoopPurpose",
        "loopPurpose",
    )


def _source_loop_repeat_pair_approved(
    first_scene: dict,
    first_visual_asset: dict,
    scene: dict,
    visual_asset: dict,
) -> bool:
    group_id = _source_loop_group_id(scene, visual_asset)
    if not group_id or group_id != _source_loop_group_id(first_scene, first_visual_asset):
        return False
    return _source_loop_repeat_approved(first_scene, first_visual_asset) and _source_loop_repeat_approved(
        scene,
        visual_asset,
    )


def _ending_tail_hold_seconds(scene: dict, ending: dict | None = None) -> float:
    ending = ending or {}
    for container in (scene, ending):
        if not isinstance(container, dict):
            continue
        for key in ("endingTailHoldSec", "ending_tail_hold_sec", "tailHoldSec", "tail_hold_sec", "finalHoldSec"):
            try:
                value = float(container.get(key) or 0)
            except (TypeError, ValueError):
                continue
            if value > 0:
                return value
    return 0.0


def _ending_fade_out_seconds(scene: dict, ending: dict | None = None) -> float:
    ending = ending or {}
    for container in (scene, ending):
        if not isinstance(container, dict):
            continue
        for key in ("endingFadeOutSec", "ending_fade_out_sec", "fadeOutSec", "fade_out_sec", "finalFadeOutSec"):
            try:
                value = float(container.get(key) or 0)
            except (TypeError, ValueError):
                continue
            if value > 0:
                return value
    return 0.0


def scene_voiceover_target_duration(scene: dict) -> float:
    duration_sec = _scene_duration_seconds(scene)
    if duration_sec <= 0:
        return 0.0
    tail_hold_sec = min(_ending_tail_hold_seconds(scene), max(0.0, duration_sec - 0.5))
    return max(0.5, duration_sec - tail_hold_sec)


def manifest_ending_fade_out_duration(manifest: dict) -> float:
    scenes = manifest.get("scenes") if isinstance(manifest.get("scenes"), list) else []
    final_scene = scenes[-1] if scenes else {}
    ending = manifest.get("endingSystem") if isinstance(manifest.get("endingSystem"), dict) else {}
    return _ending_fade_out_seconds(final_scene, ending)


def _normalized_layout_variant_key(scene: dict) -> str:
    return str(
        scene.get("layoutVariantKey")
        or scene.get("layout_variant_key")
        or scene.get("layoutVariant")
        or scene.get("layout_variant")
        or ""
    ).strip().lower().replace("_", "-")


def _rendered_caption_duration_seconds(scene: dict, scene_duration_sec: float = 0.0) -> float:
    declared_sec = _scene_caption_duration(scene)
    if declared_sec <= 0:
        return 0.0
    cap_sec = CAPTION_RENDER_MAX_DURATION_BY_LAYOUT_VARIANT.get(_normalized_layout_variant_key(scene))
    if cap_sec is None:
        preset = str(scene.get("captionPreset") or scene.get("caption_preset") or "").strip().lower()
        cap_sec = CAPTION_RENDER_MAX_DURATION_BY_PRESET.get(preset)
    rendered_sec = min(declared_sec, cap_sec) if cap_sec else declared_sec
    if scene_duration_sec > 0:
        rendered_sec = min(rendered_sec, scene_duration_sec)
    return max(0.0, rendered_sec)


def _required_narration_chars(content_template: str, scene_id: str, first_scene_id: str) -> int:
    """Minimum compact narration length needed before TTS evidence is credible."""
    if content_template in LONGFORM_NARRATION_TEMPLATES:
        return 80
    if content_template in SHORTFORM_TIGHT_NARRATION_TEMPLATES:
        return 24
    if scene_id == first_scene_id:
        return 24
    return 40


def _short_voiceover_callout_approved(
    scene: dict,
    content_template: str,
    narration_length: int,
    subtitle_length: int,
    duration_sec: float,
) -> bool:
    """Allow deliberately short action callouts when the clip is too short for full narration."""
    source_loop_callout = _source_loop_repeat_approved(scene, {})
    if content_template not in SHORTFORM_TIGHT_NARRATION_TEMPLATES and not source_loop_callout:
        return False
    if not (0 < duration_sec <= 4.5):
        return False
    if narration_length < 8 or subtitle_length < 4:
        return False
    style = _normalized_audio_design_mode(
        scene.get("voiceoverStyle")
        or scene.get("voiceover_style")
        or scene.get("narrationStyle")
        or scene.get("narration_style")
        or scene.get("calloutStyle")
        or scene.get("callout_style")
    )
    layout_key = _normalized_audio_design_mode(scene.get("layoutVariantKey") or scene.get("layout_variant_key"))
    return source_loop_callout or style in {
        "short-action-callout",
        "short-callout",
        "action-callout",
        "source-loop-callout",
        "short-source-loop-callout",
    } or layout_key in {
        "routine-action-command",
        "short-action-callout",
        "source-loop-repeat",
    }


def _final_payoff_short_narration_approved(
    scene: dict,
    scene_id: str,
    final_scene_id: str,
    narration_length: int,
    subtitle_length: int,
) -> bool:
    if scene_id != final_scene_id:
        return False
    purpose = _normalized_audio_design_mode(scene.get("endingPurpose") or scene.get("ending_purpose"))
    if purpose not in {"payoff", "resolution", "takeaway", "final-payoff", "final-resolution"}:
        return False
    if _manual_visual_verdict_status(str(scene.get("endingVerdict") or "")) == "fail":
        return False
    has_ending_review = bool(str(scene.get("endingPacingReview") or "").strip())
    has_takeaway_review = bool(str(scene.get("finalTakeawayReview") or "").strip())
    return narration_length >= 24 and subtitle_length >= 8 and has_ending_review and has_takeaway_review


def _short_source_loop_callout_scene(scene: dict, content_template: str) -> bool:
    return _short_voiceover_callout_approved(
        scene,
        content_template,
        _compact_text_length(str(scene.get("narrationText") or "")),
        _compact_text_length(str(scene.get("subtitleText") or "")),
        _scene_duration_seconds(scene),
    )


def _normalized_audio_design_mode(value: object) -> str:
    return str(value or "").strip().lower().replace("_", "-")


def _scene_audio_design_mode(scene: dict, manifest_mode: str, content_template: str) -> str:
    raw = _normalized_audio_design_mode(
        scene.get("audioDesignMode")
        or scene.get("audio_design_mode")
        or scene.get("voiceMode")
        or scene.get("voice_mode")
        or manifest_mode
    )
    if raw in NO_VOICE_AUDIO_MODES:
        return "no-voice"
    if raw in VOICEOVER_AUDIO_MODES:
        return "voiceover"
    if content_template in NO_VOICE_ALLOWED_TEMPLATES and str(scene.get("narrationText") or "").strip() == "":
        return "no-voice"
    return "voiceover"


def _visual_led_no_voice_approved(scene: dict, manifest: dict) -> bool:
    for key in VISUAL_LED_NO_VOICE_APPROVAL_FIELDS:
        if scene.get(key) is True:
            return True
    approvals = manifest.get("visualLedNoVoiceApprovals")
    if isinstance(approvals, dict):
        scene_id = str(scene.get("sceneId") or "")
        if approvals.get(scene_id) is True:
            return True
    return False


def asset_lookup(manifest: dict, scene_id: str, role: str) -> dict:
    for asset in manifest["assets"]:
        if asset["sceneId"] == scene_id and asset["role"] == role:
            return asset
    raise KeyError(f"Missing asset for scene={scene_id} role={role}")


def sfx_asset_lookup(manifest: dict, scene_id: str) -> dict | None:
    """Soft lookup for SFX asset — returns None if not present."""
    for asset in manifest["assets"]:
        if asset["sceneId"] == scene_id and asset["role"] == "sfx":
            return asset
    return None


def resolve_relative_asset_path(project_root: Path, relative_path: str | None) -> Path | None:
    if not relative_path:
        return None
    candidate = project_root / relative_path
    return candidate if candidate.exists() else None


def get_manifest_transition(manifest: dict) -> tuple[str, float]:
    """Read transition settings from the manifest, with defaults."""
    transition_type = manifest.get("transitionType") or DEFAULT_TRANSITION_TYPE
    transition_duration = manifest.get("transitionDuration", DEFAULT_TRANSITION_DURATION)
    return transition_type, float(transition_duration)


def get_scene_motion_preset(scene: dict) -> str:
    """Read motionPreset from the scene dict, defaulting to none."""
    return scene.get("motionPreset") or DEFAULT_MOTION_PRESET


def write_concat_file(path: Path, clip_paths: list[Path]) -> None:
    # concat demuxer single-quotes each path; a literal ' must be closed/escaped/reopened
    # ('\'') so an NTFS filename containing a quote can't break or inject the file list.
    lines = [
        "file '" + clip_path.resolve().as_posix().replace("'", "'\\''") + "'"
        for clip_path in clip_paths
    ]
    write_text(path, "\n".join(lines) + "\n")


def ffmpeg_filter_path(path: Path) -> str:
    # ':' is the filter-arg separator; call sites single-quote the value
    # (filename='...', ass='...'), so a literal ' must also be escaped as '\''.
    return path.resolve().as_posix().replace(":", r"\:").replace("'", "'\\''")


def resolve_ffmpeg_executable(project_root: Path) -> tuple[str, dict]:
    ffmpeg = probe_tool("ffmpeg", project_root=project_root)
    executable = ffmpeg.resolvedPath or ffmpeg.path
    if not executable:
        raise RuntimeError(ffmpeg.detail or "FFmpeg is not available for local rendering")
    return executable, ffmpeg.to_dict()


def _run_ffprobe_json(project_root: Path, output_path: Path) -> tuple[dict | None, dict]:
    ffprobe = probe_tool("ffprobe", project_root=project_root)
    executable = ffprobe.resolvedPath or ffprobe.path
    if not executable or not output_path.exists():
        return None, ffprobe.to_dict()

    ffprobe_info = ffprobe.to_dict()
    completed = subprocess.run(
        [
            executable,
            "-v", "error",
            "-show_entries", "stream=index,codec_type,codec_name,width,height,r_frame_rate,avg_frame_rate,sample_rate,channels,duration",
            "-show_entries", "format=duration",
            "-of", "json",
            str(output_path),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=CREATE_NO_WINDOW,
        check=False,
    )
    if completed.returncode != 0:
        return {"error": completed.stderr.strip() or f"ffprobe exited {completed.returncode}"}, ffprobe_info
    try:
        ffprobe_info["ready"] = True
        return json.loads(completed.stdout or "{}"), ffprobe_info
    except json.JSONDecodeError as error:
        return {"error": f"ffprobe JSON parse failed: {error.msg}"}, ffprobe_info


def _resolve_source_motion_path(project_root: Path, asset: dict) -> Path | None:
    for key in ("sourcePath", "outputPath"):
        raw = str(asset.get(key) or "").strip()
        if not raw:
            continue
        candidate = Path(raw)
        paths = [candidate] if candidate.is_absolute() else [project_root / candidate]
        for path in paths:
            if path.exists() and path.is_file():
                return path
    return None


def _sum_freeze_duration(output: str, audited_seconds: float) -> float:
    durations: list[float] = []
    for match in re.finditer(r"freeze_duration:\s*([0-9.]+)", output):
        try:
            durations.append(float(match.group(1)))
        except ValueError:
            pass
    if durations:
        return round(sum(durations), 3)

    starts: list[float] = []
    for match in re.finditer(r"freeze_start:\s*([0-9.]+)", output):
        try:
            starts.append(float(match.group(1)))
        except ValueError:
            pass
    if starts:
        return round(max(0.0, audited_seconds - min(starts)), 3)
    return 0.0


def _build_source_motion_evidence(project_root: Path, manifest: dict) -> dict:
    video_assets = [
        asset
        for asset in manifest.get("assets", [])
        if asset.get("role") == "visual" and asset.get("kind") == "video"
    ]
    if not video_assets:
        return {
            "status": "fail",
            "detail": "No visual video source assets found.",
            "scenes": [],
            "lowMotionSceneIds": [],
            "unavailableSceneIds": [],
        }

    try:
        ffmpeg_executable, ffmpeg_info = resolve_ffmpeg_executable(project_root)
    except Exception as exc:
        return {
            "status": "unavailable",
            "detail": f"FFmpeg unavailable for source motion audit: {exc}",
            "tool": {},
            "scenes": [],
            "lowMotionSceneIds": [],
            "unavailableSceneIds": [str(asset.get("sceneId") or "") for asset in video_assets],
        }

    scenes: list[dict] = []
    low_motion_scene_ids: list[str] = []
    unavailable_scene_ids: list[str] = []
    for asset in video_assets:
        scene_id = str(asset.get("sceneId") or "")
        source_path = _resolve_source_motion_path(project_root, asset)
        if source_path is None:
            unavailable_scene_ids.append(scene_id)
            scenes.append({
                "sceneId": scene_id,
                "provider": asset.get("provider"),
                "status": "unavailable",
                "detail": "No readable sourcePath/outputPath for motion audit.",
            })
            continue

        try:
            requested_seconds = float(asset.get("durationSec") or 0)
        except (TypeError, ValueError):
            requested_seconds = 0.0
        audited_seconds = max(2.0, min(8.0, requested_seconds or 6.0))
        completed = subprocess.run(
            [
                ffmpeg_executable,
                "-hide_banner",
                "-nostats",
                "-t",
                f"{audited_seconds:.3f}",
                "-i",
                str(source_path),
                "-vf",
                "freezedetect=n=-50dB:d=1",
                "-an",
                "-f",
                "null",
                "-",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=CREATE_NO_WINDOW,
            check=False,
        )
        output = f"{completed.stdout}\n{completed.stderr}"
        if completed.returncode != 0:
            unavailable_scene_ids.append(scene_id)
            scenes.append({
                "sceneId": scene_id,
                "provider": asset.get("provider"),
                "path": str(source_path),
                "status": "unavailable",
                "detail": (completed.stderr or completed.stdout or f"ffmpeg exited {completed.returncode}").strip()[:240],
            })
            continue

        freeze_seconds = _sum_freeze_duration(output, audited_seconds)
        freeze_ratio = min(1.0, freeze_seconds / audited_seconds) if audited_seconds > 0 else 1.0
        low_motion = audited_seconds >= 2.0 and freeze_ratio >= 0.85
        if low_motion:
            low_motion_scene_ids.append(scene_id)
        scenes.append({
            "sceneId": scene_id,
            "provider": asset.get("provider"),
            "path": str(source_path),
            "status": "low-motion" if low_motion else "pass",
            "auditedSeconds": round(audited_seconds, 3),
            "freezeDurationSeconds": freeze_seconds,
            "freezeRatio": round(freeze_ratio, 3),
            "detail": "near-frozen source video" if low_motion else "source video has frame-to-frame motion evidence",
        })

    audited_count = sum(1 for item in scenes if item.get("status") in {"pass", "low-motion"})
    if low_motion_scene_ids:
        status = "fail"
        detail = f"Low-motion source scenes: {low_motion_scene_ids}"
    elif audited_count > 0:
        status = "pass"
        detail = f"Audited {audited_count}/{len(video_assets)} visual video sources."
    else:
        status = "unavailable"
        detail = "No visual video source files could be audited."
    return {
        "status": status,
        "detail": detail,
        "tool": ffmpeg_info,
        "scenes": scenes,
        "lowMotionSceneIds": low_motion_scene_ids,
        "unavailableSceneIds": unavailable_scene_ids,
        "auditedCount": audited_count,
        "totalVideoSources": len(video_assets),
    }


def _rate_is_30fps(value: str | None) -> bool:
    if not value or "/" not in value:
        return False
    left, right = value.split("/", 1)
    try:
        denominator = float(right)
        return denominator > 0 and abs(float(left) / denominator - 30.0) < 0.02
    except ValueError:
        return False


def _check(status: str, detail: str) -> dict:
    return {"status": status, "detail": detail}


def _quality_ratchet_field_present(value: object) -> bool:
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, dict):
        return any(_quality_ratchet_field_present(item) for item in value.values())
    if isinstance(value, list):
        return any(_quality_ratchet_field_present(item) for item in value)
    return value not in (None, "", False)


def _quality_ratchet_text(value: object) -> str:
    if isinstance(value, dict):
        return " ".join(_quality_ratchet_text(item) for item in value.values())
    if isinstance(value, list):
        return " ".join(_quality_ratchet_text(item) for item in value)
    return str(value or "")


def _build_quality_ratchet_review(manifest: dict) -> dict:
    raw = manifest.get("qualityRatchet") or manifest.get("qualityIterationRatchet") or {}
    if not isinstance(raw, dict):
        raw = {}
    required = bool(
        manifest.get("qualityRatchetRequired") is True
        or _upload_candidate_required(manifest)
        or manifest.get("qualityIteration")
        or raw
    )
    missing_fields = [
        field
        for field in QUALITY_RATCHET_REQUIRED_FIELDS
        if not _quality_ratchet_field_present(raw.get(field))
    ]
    changed_lever_text = _quality_ratchet_text(raw.get("changedLever")).lower()
    viewer_facing_lever = any(term in changed_lever_text for term in QUALITY_RATCHET_VIEWER_FACING_TERMS)
    issues: list[str] = []
    if missing_fields:
        issues.append(f"missingFields={missing_fields}")
    if required and not viewer_facing_lever:
        issues.append("changedLever must name a viewer-facing video lever")
    status = "pass"
    if required and (missing_fields or not viewer_facing_lever):
        status = "fail"
    return {
        "required": required,
        "status": status,
        "requiredFields": list(QUALITY_RATCHET_REQUIRED_FIELDS),
        "missingFields": missing_fields,
        "viewerFacingLever": viewer_facing_lever,
        "viewerFacingTerms": [
            term
            for term in QUALITY_RATCHET_VIEWER_FACING_TERMS
            if term in changed_lever_text
        ],
        "qualityIteration": manifest.get("qualityIteration") or "",
        "payload": raw,
        "issues": issues,
    }


def _sample_set_payload(manifest: dict) -> dict:
    raw = manifest.get("qualitySampleSet") or manifest.get("quality_sample_set") or {}
    return raw if isinstance(raw, dict) else {}


def _sample_text(value: object) -> str:
    if isinstance(value, list):
        return " ".join(_sample_text(item) for item in value)
    if isinstance(value, dict):
        return " ".join(_sample_text(item) for item in value.values())
    return str(value or "").strip()


def _sample_pass_value(value: object) -> bool:
    return str(value or "").strip().lower() in {"pass", "passed", "ok", "true", "accepted", "ready"}


def _sample_review_value_present(value: object) -> bool:
    return str(value or "").strip().lower() in {
        "pass",
        "passed",
        "ok",
        "true",
        "accepted",
        "ready",
        "fail",
        "failed",
        "rejected",
        "quality-fail",
        "baseline-rejected",
    }


def _sample_review_text_present(sample: dict, *keys: str, min_length: int = 48) -> bool:
    for key in keys:
        if len(_sample_text(sample.get(key))) >= min_length:
            return True
    return False


def _sample_status(sample: dict) -> str:
    return str(sample.get("status") or sample.get("verdict") or "").strip().lower()


def _sample_is_accepted(sample: dict) -> bool:
    status = _sample_status(sample)
    return sample.get("accepted") is True or status in {"accepted", "pass", "quality-pass", "ready"}


def _sample_is_rejected_baseline(sample: dict) -> bool:
    status = _sample_status(sample)
    return status in {"rejected", "baseline-rejected", "quality-fail", "fail"} or sample.get("accepted") is False


def _sample_source_families(sample: dict) -> set[str]:
    raw = sample.get("sourceFamilies") or sample.get("sourceTypes") or sample.get("mediaFamilies") or []
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, list):
        raw = []
    return {str(item).strip().lower() for item in raw if str(item).strip()}


def _sample_artifact_exists(value: object, project_root: Path | None) -> bool:
    text = _sample_text(value)
    if not text or project_root is None:
        return False
    path = Path(text)
    if path.is_absolute():
        return path.exists()
    return (project_root / path).exists()


def _build_quality_sample_set_review(manifest: dict, project_root: Path | None = None) -> dict:
    raw = _sample_set_payload(manifest)
    samples = raw.get("samples") or raw.get("proofs") or raw.get("videos") or []
    if not isinstance(samples, list):
        samples = []
    required = bool(manifest.get("qualitySampleSetRequired") is True or raw)
    try:
        min_accepted = int(raw.get("minAcceptedSamples") or manifest.get("minAcceptedQualitySamples") or 2)
    except (TypeError, ValueError):
        min_accepted = 2
    try:
        min_rejected = int(raw.get("minRejectedBaselines") or 1)
    except (TypeError, ValueError):
        min_rejected = 1
    min_accepted = max(2, min_accepted)
    min_rejected = max(1, min_rejected)

    accepted_samples: list[dict] = []
    rejected_baselines: list[dict] = []
    sample_issues: list[str] = []
    accepted_topics: set[str] = set()
    accepted_source_families: set[str] = set()
    current_project_id = str(manifest.get("projectId") or "").strip()
    current_project_included = False

    for index, sample in enumerate(samples):
        if not isinstance(sample, dict):
            sample_issues.append(f"sample-{index}:object")
            continue
        sample_id = str(sample.get("projectId") or sample.get("id") or f"sample-{index}").strip()
        if current_project_id and sample_id == current_project_id:
            current_project_included = True
        topic = str(sample.get("topic") or "").strip()
        families = _sample_source_families(sample)
        if _sample_is_accepted(sample):
            accepted_samples.append(sample)
            if topic:
                accepted_topics.add(topic.lower())
            accepted_source_families.update(families)
            missing: list[str] = []
            if not sample_id:
                missing.append("projectId")
            if not topic:
                missing.append("topic")
            mp4_path = sample.get("mp4Path") or sample.get("renderPath")
            contact_sheet_path = sample.get("contactSheetPath")
            if not _sample_text(mp4_path):
                missing.append("mp4Path")
            elif not _sample_artifact_exists(mp4_path, project_root):
                missing.append("mp4PathExists")
            if not _sample_text(contact_sheet_path):
                missing.append("contactSheetPath")
            elif not _sample_artifact_exists(contact_sheet_path, project_root):
                missing.append("contactSheetPathExists")
            if not families:
                missing.append("sourceFamilies")
            try:
                unique_source_count = int(sample.get("uniqueSourceCount") or sample.get("distinctSourceCount") or 0)
            except (TypeError, ValueError):
                unique_source_count = 0
            try:
                duplicate_source_count = int(
                    sample.get("duplicateSourceCount")
                    or sample.get("reusedSourceCount")
                    or sample.get("sourceReuseCount")
                    or 0
                )
            except (TypeError, ValueError):
                duplicate_source_count = 1
            if unique_source_count < 2:
                missing.append("uniqueSourceCount>=2")
            if duplicate_source_count > 0:
                if not _sample_pass_value(sample.get("intentionalSourceRepeatVerdict")):
                    missing.append("intentionalSourceRepeatVerdict=pass")
                if not _sample_review_text_present(
                    sample,
                    "intentionalSourceRepeatReview",
                    "sourceLoopReframeReview",
                    "sourceReuseJustification",
                    min_length=48,
                ):
                    missing.append("intentionalSourceRepeatReview>=48")
            if not _sample_pass_value(sample.get("renderQualityStatus")):
                missing.append("renderQualityStatus=pass")
            try:
                warn_count = int(sample.get("warnCount") or 0)
            except (TypeError, ValueError):
                warn_count = 1
            if warn_count != 0:
                missing.append("warnCount=0")
            for verdict_key in (
                "audienceInterestVerdict",
                "humanVisualVerdict",
                "sourceIntentVerdict",
                "captionTtsVerdict",
                "captionTtsHumanVerdict",
                "motionStabilityVerdict",
                "sourceRepetitionVerdict",
                "layoutVerdict",
                "endingVerdict",
            ):
                if not _sample_pass_value(sample.get(verdict_key)):
                    missing.append(f"{verdict_key}=pass")
            if not _sample_review_text_present(
                sample,
                "captionTtsReview",
                "captionTtsHumanReview",
                "ttsCaptionReview",
                min_length=48,
            ):
                missing.append("captionTtsReview>=48")
            if not _sample_review_text_present(
                sample,
                "motionStabilityReview",
                "cameraStabilityReview",
                "visualStabilityReview",
                min_length=48,
            ):
                missing.append("motionStabilityReview>=48")
            if not _sample_review_text_present(
                sample,
                "sourceRepetitionReview",
                "sourceReuseReview",
                "sourceVarietyReview",
                min_length=48,
            ):
                missing.append("sourceRepetitionReview>=48")
            try:
                audience_interest_score = int(sample.get("audienceInterestScore") or sample.get("interestScore") or -1)
            except (TypeError, ValueError):
                audience_interest_score = -1
            if audience_interest_score < 4:
                missing.append("audienceInterestScore>=4")
            if len(_sample_text(sample.get("interestEvidence") or sample.get("audienceInterestEvidence"))) < 24:
                missing.append("interestEvidence>=24")
            if missing:
                sample_issues.append(f"{sample_id}:{','.join(missing)}")
        elif _sample_is_rejected_baseline(sample):
            rejected_baselines.append(sample)
            missing: list[str] = []
            if not sample_id:
                missing.append("projectId")
            if not topic:
                missing.append("topic")
            mp4_path = sample.get("mp4Path") or sample.get("renderPath")
            contact_sheet_path = sample.get("contactSheetPath")
            if not _sample_text(mp4_path):
                missing.append("mp4Path")
            elif not _sample_artifact_exists(mp4_path, project_root):
                missing.append("mp4PathExists")
            if not _sample_text(contact_sheet_path):
                missing.append("contactSheetPath")
            elif not _sample_artifact_exists(contact_sheet_path, project_root):
                missing.append("contactSheetPathExists")
            if not _sample_text(sample.get("rejectionCause") or sample.get("visibleFailure")):
                missing.append("baselineRejectionCause")
            if not _sample_review_value_present(sample.get("humanVisualVerdict")):
                missing.append("humanVisualVerdict")
            if missing:
                sample_issues.append(f"{sample_id}:{','.join(missing)}")

    missing_fields: list[str] = []
    if len(accepted_samples) < min_accepted:
        missing_fields.append(f"acceptedSamples>={min_accepted}")
    if len(rejected_baselines) < min_rejected:
        missing_fields.append(f"rejectedBaselines>={min_rejected}")
    if len(accepted_topics) < min_accepted:
        missing_fields.append("distinctAcceptedTopics")
    if len(accepted_source_families) < 2:
        missing_fields.append("sourceFamilyDiversity>=2")
    if current_project_id and not current_project_included:
        missing_fields.append("currentProjectInSampleSet")
    missing_fields.extend(sample_issues)
    status = "pass"
    if required and missing_fields:
        status = "fail"
    return {
        "required": required,
        "status": status,
        "minAcceptedSamples": min_accepted,
        "minRejectedBaselines": min_rejected,
        "acceptedSampleIds": [
            str(sample.get("projectId") or sample.get("id") or "").strip()
            for sample in accepted_samples
        ],
        "rejectedBaselineIds": [
            str(sample.get("projectId") or sample.get("id") or "").strip()
            for sample in rejected_baselines
        ],
        "acceptedTopicCount": len(accepted_topics),
        "acceptedSourceFamilies": sorted(accepted_source_families),
        "currentProjectIncluded": current_project_included,
        "missingFields": missing_fields,
        "payload": raw,
        "policy": {
            "sampleRule": "Reusable quality claims need more than one accepted proof video.",
            "baselineRule": "At least one rejected baseline must remain with real MP4/contact-sheet artifacts, visible rejection cause, and human visual verdict so gate pass and human quality do not collapse into one claim.",
            "reviewRule": "Each accepted sample needs render pass, warn 0, real MP4/contact-sheet artifacts, audience-interest proof, unique source count/reuse accounting, and human visual verdicts for source intent, motion stability, source repetition, captions/TTS, layout, and ending.",
        },
    }


def _upload_candidate_required(manifest: dict) -> bool:
    if any(_truthy_metadata(manifest.get(flag)) for flag in UPLOAD_CANDIDATE_FLAGS):
        return True
    render_purpose = str(manifest.get("renderPurpose") or manifest.get("render_purpose") or "").strip().lower()
    return "upload-candidate" in render_purpose or "publish-candidate" in render_purpose


def _provider_consistency_review(manifest: dict, production_summary: dict) -> dict:
    required = _upload_candidate_required(manifest)
    mode = str(
        manifest.get("providerConsistencyMode")
        or manifest.get("finalProviderMode")
        or manifest.get("sourceProviderMode")
        or ""
    ).strip().lower()
    total_scenes = int(production_summary.get("totalScenes", 0) or 0)
    grok = int(production_summary.get("grokHandoffScenes", 0) or 0)
    gemini = int(production_summary.get("geminiHandoffScenes", 0) or 0)
    local_model = int(production_summary.get("localModelVideoScenes", 0) or 0)
    stock = int(production_summary.get("stockVideoScenes", 0) or 0)
    uploaded = int(production_summary.get("uploadedVideoScenes", 0) or 0)
    issues: list[str] = []
    if required and mode not in UPLOAD_CANDIDATE_ALLOWED_PROVIDER_MODES:
        issues.append("providerConsistencyMode must be grok-only or gemini-only for upload candidates")
    if required and total_scenes > 0:
        if mode == "grok-only" and (grok != total_scenes or gemini or local_model or stock or uploaded):
            issues.append(
                f"grok-only requires all scenes Grok handoff and no Gemini/local/stock/upload mix: "
                f"grok={grok}, gemini={gemini}, local={local_model}, stock={stock}, upload={uploaded}, total={total_scenes}"
            )
        elif mode == "gemini-only" and (gemini != total_scenes or grok or local_model or stock or uploaded):
            issues.append(
                f"gemini-only requires all scenes Gemini handoff and no Grok/local/stock/upload mix: "
                f"grok={grok}, gemini={gemini}, local={local_model}, stock={stock}, upload={uploaded}, total={total_scenes}"
            )
        if local_model == total_scenes and total_scenes > 0:
            issues.append("local-only is not allowed for upload candidates; keep it as proof/fallback only")
    return {
        "required": required,
        "status": "fail" if issues else "pass",
        "mode": mode,
        "allowedModes": sorted(UPLOAD_CANDIDATE_ALLOWED_PROVIDER_MODES),
        "counts": {
            "totalScenes": total_scenes,
            "grokHandoffScenes": grok,
            "geminiHandoffScenes": gemini,
            "localModelVideoScenes": local_model,
            "stockVideoScenes": stock,
            "uploadedVideoScenes": uploaded,
        },
        "issues": issues,
    }


def _scene_field_text(scene: dict, *keys: str) -> str:
    for key in keys:
        value = str(scene.get(key) or "").strip()
        if value:
            return value
    return ""


def _build_anti_ai_naturalness_review(manifest: dict) -> dict:
    required = _upload_candidate_required(manifest)
    missing: list[str] = []
    rejected: list[str] = []
    reviewed: list[str] = []
    for scene in manifest.get("scenes", []):
        scene_id = str(scene.get("sceneId") or "")
        verdict = _manual_visual_verdict_status(
            scene.get("antiAiNaturalnessVerdict")
            or scene.get("naturalnessVerdict")
            or scene.get("humanNaturalnessVerdict")
            or ""
        )
        note = _scene_field_text(scene, "naturalnessReviewNote", "antiAiNaturalnessNote")
        action_reason = _scene_field_text(scene, "actionMotivation", "actionReason", "physicalActionReason")
        continuity = _scene_field_text(scene, "worldContinuityNote", "continuityNote")
        scene_missing: list[str] = []
        if verdict != "pass":
            scene_missing.append("antiAiNaturalnessVerdict=pass")
        if len(note) < 48:
            scene_missing.append("naturalnessReviewNote>=48")
        if len(action_reason) < 16:
            scene_missing.append("actionMotivation>=16")
        if len(continuity) < 24:
            scene_missing.append("worldContinuityNote/continuityNote>=24")
        if scene_missing:
            missing.append(f"{scene_id}:{','.join(scene_missing)}")
        else:
            reviewed.append(scene_id)
        if verdict == "fail":
            rejected.append(scene_id)
    status = "pass"
    if required and (missing or rejected):
        status = "fail"
    return {
        "required": required,
        "status": status,
        "reviewedScenes": reviewed,
        "missingScenes": missing,
        "rejectedScenes": rejected,
    }


def _build_caption_system_review(manifest: dict, production_summary: dict) -> dict:
    required = _upload_candidate_required(manifest)
    policy = manifest.get("captionSystem") if isinstance(manifest.get("captionSystem"), dict) else {}
    fixed_preset = str(
        policy.get("fixedPreset")
        or manifest.get("captionFixedPreset")
        or manifest.get("captionPresetPolicy")
        or ""
    ).strip()
    if fixed_preset.startswith("fixed-"):
        fixed_preset = fixed_preset.removeprefix("fixed-")
    captioned = production_summary.get("captionedSceneIds") or []
    missing: list[str] = []
    mismatched: list[str] = []
    purpose_missing: list[str] = []
    purpose_by_scene = policy.get("purposeByScene") if isinstance(policy.get("purposeByScene"), dict) else {}
    for scene in manifest.get("scenes", []):
        scene_id = str(scene.get("sceneId") or "")
        preset = str(scene.get("captionPreset") or "lower-info").strip()
        subtitle_text = str(scene.get("subtitleText") or "").strip()
        if required and subtitle_text and not fixed_preset:
            missing.append(scene_id)
        if required and fixed_preset and subtitle_text and preset != fixed_preset:
            mismatched.append(f"{scene_id}:{preset}")
        purpose = str(scene.get("captionPurpose") or purpose_by_scene.get(scene_id) or "").strip().lower()
        if purpose.startswith("viewer-"):
            purpose = purpose.removeprefix("viewer-")
        if required and subtitle_text and purpose not in CAPTION_PURPOSES:
            purpose_missing.append(scene_id)
    missing_layout = production_summary.get("missingCaptionLayoutReviewScenes") or []
    long_top_hook = production_summary.get("longTopHookScenes") or []
    sparse = bool(production_summary.get("captionSparsePlan"))
    status = "pass"
    if required and (missing or mismatched or purpose_missing or missing_layout or long_top_hook or sparse):
        status = "fail"
    return {
        "required": required,
        "status": status,
        "fixedPreset": fixed_preset,
        "captionedScenes": captioned,
        "missingFixedPresetScenes": missing,
        "mismatchedPresetScenes": mismatched,
        "missingPurposeScenes": purpose_missing,
        "missingLayoutReviewScenes": missing_layout,
        "longTopHookScenes": long_top_hook,
        "captionSparsePlan": sparse,
    }


def _build_viewer_takeaway_review(manifest: dict) -> dict:
    required = _upload_candidate_required(manifest)
    raw = manifest.get("viewerTakeaway") if isinstance(manifest.get("viewerTakeaway"), dict) else {}
    understood = str(raw.get("understood") or raw.get("understanding") or "").strip()
    action = str(raw.get("action") or raw.get("viewerAction") or raw.get("takeawayAction") or "").strip()
    feeling = str(raw.get("feeling") or raw.get("emotionalState") or raw.get("state") or "").strip()
    missing = []
    if len(understood) < 8:
        missing.append("understood")
    if len(action) < 8:
        missing.append("action")
    if len(feeling) < 6:
        missing.append("feeling")
    return {
        "required": required,
        "status": "fail" if required and missing else "pass",
        "missingFields": missing,
        "payload": raw,
    }


def _source_editorial_layout_required(manifest: dict) -> bool:
    if manifest.get("sourceEditorialLayoutRequired") is True:
        return True
    if manifest.get("sourceCaptureDemo") is True or manifest.get("webImageMixDemo") is True:
        return True
    purpose = str(manifest.get("renderPurpose") or "").lower()
    return "source-first" in purpose or "source-editorial" in purpose or "webmix" in purpose


def _scene_layout_payload(scene: dict) -> dict:
    payload = scene.get("sourceEditorialLayout")
    return payload if isinstance(payload, dict) else {}


def _build_source_editorial_layout_review(manifest: dict) -> dict:
    """Gate image/source-first layouts before they can be treated as quality proof."""
    required = _source_editorial_layout_required(manifest)
    reviewed: list[str] = []
    missing: list[str] = []
    rejected: list[str] = []
    risky_fit: list[str] = []
    caption_collision: list[str] = []
    overlap_risk: list[str] = []
    divider_risk: list[str] = []
    for scene in manifest.get("scenes", []):
        scene_id = str(scene.get("sceneId") or "")
        visual_kind = str(scene.get("visualKind") or "").strip()
        caption_preset = str(scene.get("captionPreset") or "lower-info").strip()
        subtitle_text = str(scene.get("subtitleText") or "").strip()
        layout = _scene_layout_payload(scene)
        image_fit = _scene_field_text(scene, "imageFitPolicy", "imageFit", "visualFit") or _scene_field_text(layout, "imageFitPolicy", "imageFit", "visualFit")
        subject_zone = _scene_field_text(scene, "subjectSafeZone", "subjectZone") or _scene_field_text(layout, "subjectSafeZone", "subjectZone")
        caption_zone = _scene_field_text(scene, "captionSafeZone", "captionZone") or _scene_field_text(layout, "captionSafeZone", "captionZone")
        crop_note = _scene_field_text(scene, "layoutSafetyReview", "cropReviewNote", "sourceEditorialLayoutReview") or _scene_field_text(layout, "layoutSafetyReview", "cropReviewNote", "sourceEditorialLayoutReview")
        collision_note = _scene_field_text(scene, "captionCollisionReview", "captionOcclusionReview") or _scene_field_text(layout, "captionCollisionReview", "captionOcclusionReview")
        overlap_note = _scene_field_text(scene, "imageOverlapReview", "visualOverlapReview") or _scene_field_text(layout, "imageOverlapReview", "visualOverlapReview")
        divider_note = _scene_field_text(scene, "dividerLineReview", "blackLineReview") or _scene_field_text(layout, "dividerLineReview", "blackLineReview")
        verdict = _scene_field_text(scene, "layoutSafetyVerdict", "captionCollisionVerdict") or _scene_field_text(layout, "layoutSafetyVerdict", "captionCollisionVerdict")
        overlap_verdict = _scene_field_text(scene, "imageOverlapVerdict", "visualOverlapVerdict") or _scene_field_text(layout, "imageOverlapVerdict", "visualOverlapVerdict")
        divider_verdict = _scene_field_text(scene, "dividerLineVerdict", "blackLineVerdict") or _scene_field_text(layout, "dividerLineVerdict", "blackLineVerdict")
        verdict_status = _manual_visual_verdict_status(verdict)
        overlap_status = _manual_visual_verdict_status(overlap_verdict)
        divider_status = _manual_visual_verdict_status(divider_verdict)
        scene_missing: list[str] = []
        if visual_kind == "image":
            if image_fit.lower() not in {"cover-safe", "contain-stage", "split-stage", "top-crop-safe", "center-crop-safe"}:
                scene_missing.append("imageFitPolicy")
                risky_fit.append(scene_id)
            if len(subject_zone) < 16:
                scene_missing.append("subjectSafeZone>=16")
            if subtitle_text and len(caption_zone) < 16:
                scene_missing.append("captionSafeZone>=16")
            if len(crop_note) < 36:
                scene_missing.append("layoutSafetyReview>=36")
            if len(overlap_note) < 32:
                scene_missing.append("imageOverlapReview>=32")
                overlap_risk.append(scene_id)
            if overlap_status != "pass":
                scene_missing.append("imageOverlapVerdict=pass")
            if len(divider_note) < 24:
                scene_missing.append("dividerLineReview>=24")
                divider_risk.append(scene_id)
            if divider_status != "pass":
                scene_missing.append("dividerLineVerdict=pass")
        if subtitle_text and caption_preset != "none":
            if len(collision_note) < 32:
                scene_missing.append("captionCollisionReview>=32")
                caption_collision.append(scene_id)
            if verdict_status != "pass":
                scene_missing.append("captionCollisionVerdict=pass")
        if verdict_status == "fail":
            rejected.append(scene_id)
        if scene_missing:
            missing.append(f"{scene_id}:{','.join(dict.fromkeys(scene_missing))}")
        else:
            reviewed.append(scene_id)
    status = "pass"
    if required and (missing or rejected):
        status = "fail"
    return {
        "required": required,
        "status": status,
        "reviewedScenes": reviewed,
        "missingScenes": missing,
        "rejectedScenes": rejected,
        "riskyImageFitScenes": sorted(set(risky_fit)),
        "captionCollisionRiskScenes": sorted(set(caption_collision)),
        "imageOverlapRiskScenes": sorted(set(overlap_risk)),
        "dividerLineRiskScenes": sorted(set(divider_risk)),
        "policy": {
            "imageFitPolicy": ["cover-safe", "contain-stage", "split-stage", "top-crop-safe", "center-crop-safe"],
            "captionRule": "captioned source-editorial scenes need explicit subject zone, caption zone, collision review, and pass verdict",
            "overlapRule": "multi-image layouts need no-overlap review and no visible black-divider/gutter artifact verdict",
        },
    }


def _build_source_editorial_image_context_review(manifest: dict) -> dict:
    required = _source_editorial_layout_required(manifest)
    scenes = manifest.get("scenes", [])
    missing: list[str] = []
    reviewed: list[str] = []
    duplicate_scenes: list[str] = []
    seen: dict[str, str] = {}
    seen_asset_keys: dict[str, str] = {}
    for scene in scenes:
        scene_id = str(scene.get("sceneId") or "")
        visual_kind = str(scene.get("visualKind") or "").strip()
        if visual_kind != "image":
            continue
        layout = _scene_layout_payload(scene)
        situation = _scene_field_text(scene, "situationKey", "situationLabel", "sceneSituation") or _scene_field_text(layout, "situationKey", "situationLabel", "sceneSituation")
        distinct_id = _scene_field_text(scene, "sceneVisualDistinctId", "visualDistinctId") or _scene_field_text(layout, "sceneVisualDistinctId", "visualDistinctId")
        context_note = _scene_field_text(scene, "situationImageFitReview", "contextImageFitReview", "imageContextReview") or _scene_field_text(layout, "situationImageFitReview", "contextImageFitReview", "imageContextReview")
        context_verdict = _scene_field_text(scene, "situationImageFitVerdict", "contextImageFitVerdict") or _scene_field_text(layout, "situationImageFitVerdict", "contextImageFitVerdict")
        scene_missing: list[str] = []
        if len(situation) < 8:
            scene_missing.append("situationKey>=8")
        if len(distinct_id) < 8:
            scene_missing.append("sceneVisualDistinctId>=8")
        elif distinct_id in seen:
            duplicate_scenes.append(f"{scene_id}:same-as-{seen[distinct_id]}")
            scene_missing.append("sceneVisualDistinctId unique")
        else:
            seen[distinct_id] = scene_id
        asset_key = _scene_field_text(
            scene,
            "visualAssetFingerprint",
            "sourceUrl",
            "sourceExternalId",
            "uploadPath",
            "assetPath",
            "selectedFilePath",
        ) or _scene_field_text(
            layout,
            "visualAssetFingerprint",
            "sourceUrl",
            "sourceExternalId",
            "uploadPath",
            "assetPath",
            "selectedFilePath",
        )
        if len(asset_key) >= 8:
            if asset_key in seen_asset_keys:
                duplicate_scenes.append(f"{scene_id}:same-asset-as-{seen_asset_keys[asset_key]}")
                scene_missing.append("visualAssetFingerprint/source unique")
            else:
                seen_asset_keys[asset_key] = scene_id
        if len(context_note) < 40:
            scene_missing.append("situationImageFitReview>=40")
        if _manual_visual_verdict_status(context_verdict) != "pass":
            scene_missing.append("situationImageFitVerdict=pass")
        if scene_missing:
            missing.append(f"{scene_id}:{','.join(dict.fromkeys(scene_missing))}")
        else:
            reviewed.append(scene_id)
    status = "pass"
    if required and (missing or duplicate_scenes):
        status = "fail"
    return {
        "required": required,
        "status": status,
        "reviewedScenes": reviewed,
        "missingScenes": missing,
        "duplicateVisualScenes": duplicate_scenes,
        "policy": "Every source-editorial situation needs a unique visual identity, a non-reused source/image fingerprint when provided, and an explicit fit review for that scene's viewer job.",
    }


def _still_image_source_policy_required(manifest: dict) -> bool:
    return (
        _truthy_metadata(manifest.get("stillImageSourcePolicyRequired"))
        or _source_editorial_layout_required(manifest)
        or _internet_source_context_required(manifest)
    )


def _still_image_source_policy_text(scene: dict, visual_asset: dict) -> str:
    layout = _scene_layout_payload(scene)
    payload = _source_acquisition_payload(scene, visual_asset)
    keys = (
        "visualSourceIntent",
        "sourceOrigin",
        "sourceType",
        "sourceRole",
        "imageSourceRole",
        "stillImageSourceRole",
        "sourceCategory",
        "mediaCategory",
    )
    values: list[str] = []
    for container in (scene, visual_asset, layout, payload):
        if not isinstance(container, dict):
            continue
        for key in keys:
            values.append(str(container.get(key) or ""))
    return " ".join(values).strip().lower().replace("_", "-")


def _still_image_source_allowed_reason(policy_text: str) -> str:
    for term in sorted(STILL_IMAGE_PRIMARY_ALLOWED_TERMS, key=len, reverse=True):
        if term in policy_text:
            return term
    return ""


def _scene_uses_primary_still_image_source(scene: dict, visual_asset: dict) -> tuple[bool, dict]:
    if not _is_internet_source_candidate(scene, visual_asset):
        return False, {"candidate": False}
    _ready, _missing, acquisition_detail = _internet_source_acquisition_scene_status(scene, visual_asset)
    visual_kind = str(scene.get("visualKind") or visual_asset.get("kind") or "").strip().lower()
    media_kind = str(acquisition_detail.get("mediaKind") or "").strip().lower()
    if not media_kind and visual_kind == "image":
        media_kind = "image"
    source_role = _scene_field_text(
        scene,
        "visualRole",
        "sourceRole",
        "imageSourceRole",
        "stillImageSourceRole",
    ) or _scene_field_text(
        visual_asset,
        "visualRole",
        "sourceRole",
        "imageSourceRole",
        "stillImageSourceRole",
    )
    source_role_normalized = source_role.strip().lower().replace("_", "-")
    support_role = source_role_normalized in {
        "support",
        "supporting",
        "support-card",
        "evidence-card",
        "reference-card",
        "data-card",
        "caption-support",
    }
    primary = visual_kind == "image" and media_kind == "image" and not support_role
    return primary, {
        "candidate": True,
        "visualKind": visual_kind,
        "mediaKind": media_kind,
        "sourceRole": source_role_normalized,
        "supportRole": support_role,
    }


def _build_still_image_source_policy_review(manifest: dict) -> dict:
    """Block generic web stills from becoming the primary source of non-meme explainers."""
    required = _still_image_source_policy_required(manifest)
    reviewed: list[str] = []
    allowed: list[str] = []
    support_only: list[str] = []
    blocked: list[str] = []
    scene_details: list[dict] = []
    for scene in manifest.get("scenes", []):
        scene_id = str(scene.get("sceneId") or "")
        visual_asset = _visual_asset_for_scene(manifest, scene_id)
        primary_still, detail = _scene_uses_primary_still_image_source(scene, visual_asset)
        detail["sceneId"] = scene_id
        scene_details.append(detail)
        if not detail.get("candidate") or detail.get("mediaKind") != "image":
            continue
        reviewed.append(scene_id)
        if detail.get("supportRole") is True:
            support_only.append(scene_id)
            continue
        policy_text = _still_image_source_policy_text(scene, visual_asset)
        allowed_reason = _still_image_source_allowed_reason(policy_text)
        detail["allowedReason"] = allowed_reason
        if primary_still and not allowed_reason:
            blocked.append(f"{scene_id}:primary-still-image-source-not-meme-reaction-capture-card")
        else:
            allowed.append(scene_id)
    status = "pass"
    if required and blocked:
        status = "fail"
    return {
        "required": required,
        "status": status,
        "reviewedScenes": reviewed,
        "allowedPrimaryStillScenes": allowed,
        "supportOnlyStillScenes": support_only,
        "blockedScenes": blocked,
        "sceneDetails": scene_details,
        "policy": {
            "primaryStillAllowedOnlyFor": sorted(STILL_IMAGE_PRIMARY_ALLOWED_TERMS),
            "rule": "A fetched/web still image may be the primary visual only when the image itself is the subject: meme, reaction, screenshot/source capture, or evidence/reference/data card. General explainers need motion/generated footage as the primary visual.",
            "supportRule": "Set stillImageSourceRole/imageSourceRole to evidence-card, reference-card, data-card, or support when a still is only a supporting plate.",
        },
    }


def _build_internet_source_acquisition_review(manifest: dict) -> dict:
    required = _internet_source_acquisition_required(manifest)
    reviewed: list[str] = []
    motion_ready: list[str] = []
    missing: list[str] = []
    scene_details: list[dict] = []
    for scene in manifest.get("scenes", []):
        scene_id = str(scene.get("sceneId") or "")
        visual_asset = _visual_asset_for_scene(manifest, scene_id)
        is_candidate = _is_internet_source_candidate(scene, visual_asset)
        if not required and not is_candidate:
            continue
        ready, scene_missing, detail = _internet_source_acquisition_scene_status(scene, visual_asset)
        detail["sceneId"] = scene_id
        detail["candidate"] = is_candidate
        scene_details.append(detail)
        if scene_missing:
            missing.append(f"{scene_id}:{','.join(dict.fromkeys(scene_missing))}")
            continue
        reviewed.append(scene_id)
        if detail.get("motionReady") is True:
            motion_ready.append(scene_id)
    status = "pass"
    if required and (missing or not reviewed):
        status = "fail"
    return {
        "required": required,
        "status": status,
        "proofMode": _internet_source_proof_mode(manifest),
        "reviewedScenes": reviewed,
        "motionReadyScenes": motion_ready,
        "missingScenes": missing,
        "sceneDetails": scene_details,
        "policy": {
            "allowedMediaKinds": sorted(INTERNET_SOURCE_MEDIA_KINDS),
            "motionKinds": ["gif", "video"],
            "requiredEvidence": [
                "sourceUrl",
                "localPath/sourcePath",
                "sha256",
                "sizeBytes",
                "mediaKind",
                "sourceFetchStatus=fetched",
                "sourceAcquisitionVerdict=pass",
                "sourceAcquisitionReview",
            ],
        },
    }


def _build_internet_source_context_review(manifest: dict) -> dict:
    required = _internet_source_context_required(manifest)
    reviewed: list[str] = []
    missing: list[str] = []
    image_ready: list[str] = []
    motion_ready: list[str] = []
    media_kinds: set[str] = set()
    scene_details: list[dict] = []
    for scene in manifest.get("scenes", []):
        scene_id = str(scene.get("sceneId") or "")
        visual_asset = _visual_asset_for_scene(manifest, scene_id)
        is_candidate = _is_internet_source_candidate(scene, visual_asset)
        if not required and not is_candidate:
            continue
        ready, scene_missing, detail = _internet_source_context_scene_status(manifest, scene, visual_asset)
        detail["sceneId"] = scene_id
        detail["candidate"] = is_candidate
        scene_details.append(detail)
        media_kind = str(detail.get("mediaKind") or "")
        if media_kind:
            media_kinds.add(media_kind)
        if scene_missing:
            missing.append(f"{scene_id}:{','.join(dict.fromkeys(scene_missing))}")
            continue
        reviewed.append(scene_id)
        if media_kind == "image":
            image_ready.append(scene_id)
        elif media_kind in {"gif", "video"}:
            motion_ready.append(scene_id)
    mix_required = _truthy_metadata(manifest.get("sourceTypeMixRequired"))
    mix_missing = []
    if mix_required:
        if not image_ready:
            mix_missing.append("image")
        if not motion_ready:
            mix_missing.append("gif/video")
    status = "pass"
    if required and (missing or not reviewed or mix_missing):
        status = "fail"
    return {
        "required": required,
        "status": status,
        "proofMode": _internet_source_proof_mode(manifest),
        "mixRequired": mix_required,
        "mediaKinds": sorted(media_kinds),
        "reviewedScenes": reviewed,
        "imageReadyScenes": image_ready,
        "motionReadyScenes": motion_ready,
        "missingScenes": missing,
        "mixMissing": mix_missing,
        "sceneDetails": scene_details,
        "policy": {
            "sourceFirstRule": "Fetched internet media needs topic, scene purpose, viewer job, selection rationale, media-type decision, and source-fit verdict.",
            "mediaChoiceRule": "Use GIF/video or generated/local MP4 for general explainer motion; use primary still images only when the still itself is the subject, such as meme, reaction, screenshot/source capture, or evidence/reference/data card.",
            "mixRule": "When sourceTypeMixRequired is true, at least one image and one GIF/video source must be context-approved.",
        },
    }


def _internet_source_editorial_integration_required(manifest: dict) -> bool:
    return _internet_source_context_required(manifest) or (
        _internet_source_proof_mode(manifest) and _source_editorial_layout_required(manifest)
    )


def _source_context_keywords(*values: object) -> set[str]:
    keywords: set[str] = set()
    korean_suffixes = (
        "에서는",
        "에서",
        "으로",
        "에게",
        "보다",
        "처럼",
        "까지",
        "부터",
        "이라는",
        "라는",
        "입니다",
        "이다",
        "이라",
        "하고",
        "하게",
        "합니다",
        "한다",
        "이에요",
        "예요",
        "어요",
        "아요",
        "네요",
        "죠",
        "요",
        "네",
        "까",
        "되는",
        "하는",
        "있다",
        "없다",
        "이며",
        "은",
        "는",
        "이",
        "가",
        "을",
        "를",
        "과",
        "와",
        "도",
        "만",
        "의",
        "에",
    )
    for value in values:
        text = str(value or "").lower()
        for raw_token in re.findall(r"[a-z0-9]+|[가-힣]+", text):
            candidates = {raw_token}
            if re.fullmatch(r"[가-힣]+", raw_token):
                for suffix in korean_suffixes:
                    if raw_token.endswith(suffix) and len(raw_token) > len(suffix) + 1:
                        candidates.add(raw_token[: -len(suffix)])
                        break
            for token in candidates:
                if len(token) < 2 or token in INTERNET_SOURCE_INTEGRATION_STOPWORDS:
                    continue
                keywords.add(token)
    return keywords


def _source_context_overlap(context_keywords: set[str], *values: object) -> list[str]:
    return sorted(context_keywords & _source_context_keywords(*values))


def _contains_editorial_term(value: object, terms: tuple[str, ...]) -> bool:
    lowered = str(value or "").lower()
    compact = re.sub(r"\s+", "", lowered)
    return any(term.lower() in lowered or term.lower() in compact for term in terms)


def _internet_source_caption_quality_issue(subtitle_text: str) -> str:
    stripped = str(subtitle_text or "").strip()
    if not stripped:
        return "empty subtitle"
    lowered = stripped.lower()
    compact = re.sub(r"\s+", "", lowered)
    for term in INTERNET_SOURCE_WEAK_CAPTION_TERMS:
        term_lower = term.lower()
        if term_lower in lowered or re.sub(r"\s+", "", term_lower) in compact:
            return f"weak internal-label caption: {term}"
    if re.search(r"(?:scene|beat|proof)\s*\d*$", lowered) and len(stripped) <= 32:
        return "weak internal-label caption: scene/beat/proof"
    if re.search(r"장면$", compact) and _compact_text_length(stripped) <= 14:
        return "weak internal-label caption: short Korean caption ending with 장면"
    if compact in {"조건이다름", "맥락확인", "움직임확인", "소스확인"}:
        return "weak internal-label caption: fragment"
    return ""


def _internet_source_editorial_integration_scene_status(
    manifest: dict,
    scene: dict,
    visual_asset: dict,
) -> tuple[bool, list[str], dict]:
    context_ready, context_missing, context_detail = _internet_source_context_scene_status(
        manifest,
        scene,
        visual_asset,
    )
    source_context = _source_context_payload(scene, visual_asset)
    topic = str(context_detail.get("topic") or "").strip()
    scene_purpose = str(context_detail.get("scenePurpose") or "").strip()
    viewer_job = str(context_detail.get("viewerJob") or "").strip()
    media_kind = str(context_detail.get("mediaKind") or "").strip()
    visual_kind = str(context_detail.get("visualKind") or "").strip()
    selection_rationale = _source_context_value(
        scene,
        visual_asset,
        "selectionRationale",
        "sourceRationale",
        "contextRationale",
    ) or str(scene.get("sourceRationale") or "").strip()
    media_choice = _source_context_value(
        scene,
        visual_asset,
        "mediaChoiceRationale",
        "whyGifOrImage",
        "sourceTypeDecision",
    )
    motion_fit = _source_context_value(scene, visual_asset, "motionFit", "whyMotionFits")
    still_fit = _source_context_value(scene, visual_asset, "stillFit", "whyStillImageFits")
    title = str(scene.get("title") or "").strip()
    subtitle_text = str(scene.get("subtitleText") or "").strip()
    narration_text = str(scene.get("narrationText") or "").strip()
    caption_purpose = str(scene.get("captionPurpose") or "").strip().lower()
    layout_note = str(scene.get("layoutVariantNote") or "").strip()
    quality_review = str(scene.get("qualityReviewNote") or "").strip()
    caption_preset = str(scene.get("captionPreset") or "lower-info").strip()
    source_keywords = _source_context_keywords(
        topic,
        scene_purpose,
        viewer_job,
        selection_rationale,
        media_choice,
        motion_fit,
        still_fit,
    )
    subtitle_overlap = _source_context_overlap(source_keywords, subtitle_text)
    narration_overlap = _source_context_overlap(source_keywords, narration_text)
    layout_overlap = _source_context_overlap(source_keywords, layout_note, quality_review)
    combined_overlap = _source_context_overlap(
        source_keywords,
        subtitle_text,
        narration_text,
        layout_note,
        quality_review,
    )
    caption_quality_issue = _internet_source_caption_quality_issue(subtitle_text)
    editorial_text = " ".join([
        title,
        subtitle_text,
        narration_text,
        layout_note,
        quality_review,
        media_choice,
        motion_fit,
        still_fit,
    ])
    missing: list[str] = []
    if not context_ready:
        missing.append(f"internetSourceContextReady({','.join(context_missing)})")
    if len(source_keywords) < 3:
        missing.append("sourceContextKeywords>=3")
    if _compact_text_length(subtitle_text) < 4:
        missing.append("subtitleText>=4")
    if caption_quality_issue:
        missing.append("viewerFacingSubtitle")
    if caption_purpose.startswith("viewer-"):
        caption_purpose = caption_purpose.removeprefix("viewer-")
    if caption_purpose not in CAPTION_PURPOSES:
        missing.append("captionPurpose")
    if _compact_text_length(narration_text) < 24 and not _short_source_loop_callout_scene(scene, str(manifest.get("contentTemplate") or manifest.get("templateType") or "")):
        missing.append("narrationText>=24")
    if len(subtitle_overlap) < 1:
        missing.append("subtitleMatchesSourceContext")
    if len(narration_overlap) < 2:
        missing.append("narrationMatchesSourceContext>=2")
    if len(layout_overlap) < 2:
        missing.append("layoutOrQualityReviewMatchesSourceContext")
    if len(combined_overlap) < 4:
        missing.append("combinedEditorialContextOverlap>=4")
    if len(layout_note) < 36:
        missing.append("layoutVariantNote>=36")
    if len(quality_review) < 36:
        missing.append("qualityReviewNote>=36")
    if not _caption_layout_reviewed(caption_preset, quality_review):
        missing.append("captionLayoutReview")
    if media_kind in {"gif", "video"} and not _contains_editorial_term(
        editorial_text,
        INTERNET_SOURCE_MOTION_EDITORIAL_TERMS,
    ):
        missing.append("motionLanguageInSubtitleTtsLayout")
    if media_kind == "image" and not _contains_editorial_term(
        editorial_text,
        INTERNET_SOURCE_STILL_EDITORIAL_TERMS,
    ):
        missing.append("stillLanguageInSubtitleTtsLayout")
    return not missing, missing, {
        "topic": topic,
        "scenePurpose": scene_purpose,
        "viewerJob": viewer_job,
        "mediaKind": media_kind,
        "visualKind": visual_kind,
        "sourceContextKeys": sorted(source_context.keys()),
        "sourceContextKeywords": sorted(source_keywords),
        "subtitleOverlap": subtitle_overlap,
        "narrationOverlap": narration_overlap,
        "layoutOverlap": layout_overlap,
        "combinedOverlap": combined_overlap,
        "captionQualityIssue": caption_quality_issue,
        "layoutVariantNote": layout_note,
        "captionPurpose": caption_purpose,
        "captionPreset": caption_preset,
        "contextReady": context_ready,
    }


def _build_internet_source_editorial_integration_review(manifest: dict) -> dict:
    required = _internet_source_editorial_integration_required(manifest)
    reviewed: list[str] = []
    missing: list[str] = []
    duplicate_layout_note_scenes: list[str] = []
    scene_details: list[dict] = []
    seen_layout_notes: dict[str, str] = {}
    for scene in manifest.get("scenes", []):
        scene_id = str(scene.get("sceneId") or "")
        visual_asset = _visual_asset_for_scene(manifest, scene_id)
        is_candidate = _is_internet_source_candidate(scene, visual_asset)
        if not required and not is_candidate:
            continue
        ready, scene_missing, detail = _internet_source_editorial_integration_scene_status(
            manifest,
            scene,
            visual_asset,
        )
        detail["sceneId"] = scene_id
        detail["candidate"] = is_candidate
        layout_note_key = re.sub(r"\s+", " ", str(detail.get("layoutVariantNote") or "").strip().lower())
        if len(layout_note_key) >= 24:
            first_seen = seen_layout_notes.get(layout_note_key)
            if first_seen and first_seen != scene_id:
                duplicate_layout_note_scenes.append(f"{scene_id}:same-as-{first_seen}")
                scene_missing.append("layoutVariantNote unique")
            else:
                seen_layout_notes[layout_note_key] = scene_id
        scene_details.append(detail)
        if scene_missing:
            missing.append(f"{scene_id}:{','.join(dict.fromkeys(scene_missing))}")
            continue
        reviewed.append(scene_id)
    status = "pass"
    if required and (missing or not reviewed):
        status = "fail"
    return {
        "required": required,
        "status": status,
        "reviewedScenes": reviewed,
        "missingScenes": missing,
        "duplicateLayoutNoteScenes": duplicate_layout_note_scenes,
        "sceneDetails": scene_details,
        "policy": {
            "textRule": "Internet-source scenes must tie subtitle, TTS narration, and layout/quality review back to the same source context.",
            "captionRule": "Viewer-facing captions must be claims/hooks/payoffs, not internal labels such as source beat, proof scene, or short captions ending with 장면.",
            "mediaRule": "GIF/video scenes need motion language in viewer-facing or layout text; image scenes need still/context language.",
            "layoutRule": "Scene layout notes must be specific, not repeated boilerplate across internet source scenes.",
        },
    }


def _topic_hook_payoff_payload(manifest: dict) -> tuple[str, dict]:
    for key in (
        "topicHookPayoff",
        "topicHookPayoffStructure",
        "narrativeSpine",
        "sourceProofSpine",
        "storySpine",
    ):
        payload = manifest.get(key)
        if isinstance(payload, dict):
            return key, payload
    return "", {}


def _payload_text(payload: dict, manifest: dict, *keys: str) -> str:
    for key in keys:
        value = str(payload.get(key) or manifest.get(key) or "").strip()
        if value:
            return value
    return ""


def _scene_intent_role(scene: dict, visual_asset: dict) -> str:
    role = _source_context_value(
        scene,
        visual_asset,
        "intentRole",
        "sceneIntentRole",
        "sourceIntentRole",
        "proofRole",
        "storyRole",
    ).lower()
    return role.removeprefix("viewer-").strip()


def _build_topic_hook_payoff_structure_review(manifest: dict) -> dict:
    required = _internet_source_editorial_integration_required(manifest)
    payload_key, payload = _topic_hook_payoff_payload(manifest)
    topic = _payload_text(payload, manifest, "topic", "sourceTopic", "projectTopic")
    hook = _payload_text(payload, manifest, "hook", "topicHook", "openingHook", "viewerHook")
    payoff = _payload_text(payload, manifest, "payoff", "finalPayoff", "answer", "viewerPayoff")
    viewer_takeaway = _payload_text(
        payload,
        manifest,
        "viewerTakeaway",
        "takeaway",
        "finalTakeaway",
    )
    scenes = manifest.get("scenes", [])
    first_scene = scenes[0] if scenes else {}
    final_scene = scenes[-1] if scenes else {}
    first_asset = _visual_asset_for_scene(manifest, str(first_scene.get("sceneId") or "")) if first_scene else {}
    final_asset = _visual_asset_for_scene(manifest, str(final_scene.get("sceneId") or "")) if final_scene else {}
    first_purpose = str(first_scene.get("captionPurpose") or "").strip().lower().removeprefix("viewer-")
    final_purpose = str(
        final_scene.get("endingPurpose")
        or final_scene.get("captionPurpose")
        or ""
    ).strip().lower().removeprefix("viewer-")
    first_role = _scene_intent_role(first_scene, first_asset) if first_scene else ""
    final_role = _scene_intent_role(final_scene, final_asset) if final_scene else ""
    hook_scene_ready = first_purpose == "hook" or first_role == "hook"
    payoff_scene_ready = (
        final_purpose in {"payoff", "summary", "loop-close", "callback"}
        or final_role in {"payoff", "callback"}
    )
    source_scene_roles = sorted({
        _scene_intent_role(scene, _visual_asset_for_scene(manifest, str(scene.get("sceneId") or "")))
        for scene in scenes
        if _is_internet_source_candidate(scene, _visual_asset_for_scene(manifest, str(scene.get("sceneId") or "")))
        and _scene_intent_role(scene, _visual_asset_for_scene(manifest, str(scene.get("sceneId") or "")))
    })

    missing: list[str] = []
    if not payload:
        missing.append("topicHookPayoff/narrativeSpine")
    if len(topic) < 8:
        missing.append("topic>=8")
    if len(hook) < 8:
        missing.append("hook>=8")
    if len(payoff) < 12:
        missing.append("payoff>=12")
    if len(viewer_takeaway) < 16:
        missing.append("viewerTakeaway>=16")
    if not hook_scene_ready:
        missing.append("firstSceneHookRole")
    if not payoff_scene_ready:
        missing.append("finalScenePayoffRole")
    if "proof" not in source_scene_roles and "replay" not in source_scene_roles and "closeup" not in source_scene_roles:
        missing.append("sourceProofSceneRole")
    hook_copy_overlap = _source_context_overlap(
        _source_context_keywords(hook),
        first_scene.get("subtitleText"),
        first_scene.get("narrationText"),
    )
    payoff_copy_overlap = _source_context_overlap(
        _source_context_keywords(payoff),
        final_scene.get("subtitleText"),
        final_scene.get("narrationText"),
    )
    if len(_source_context_keywords(hook)) >= 2 and not hook_copy_overlap:
        missing.append("hookAppearsInViewerCopy")
    if len(_source_context_keywords(payoff)) >= 2 and not payoff_copy_overlap:
        missing.append("payoffAppearsInViewerCopy")

    return {
        "required": required,
        "status": "fail" if required and missing else "pass",
        "payloadKey": payload_key,
        "missingFields": missing,
        "topic": topic,
        "hook": hook,
        "payoff": payoff,
        "viewerTakeaway": viewer_takeaway,
        "firstSceneId": str(first_scene.get("sceneId") or ""),
        "firstScenePurpose": first_purpose,
        "firstSceneRole": first_role,
        "finalSceneId": str(final_scene.get("sceneId") or ""),
        "finalScenePurpose": final_purpose,
        "finalSceneRole": final_role,
        "hookCopyOverlap": hook_copy_overlap,
        "payoffCopyOverlap": payoff_copy_overlap,
        "sourceSceneRoles": source_scene_roles,
        "policy": {
            "spineRule": "Internet-source renders must start from topic/hook/payoff before selecting GIFs or images.",
            "hookRule": "The first scene must explicitly serve the viewer hook.",
            "payoffRule": "The final scene must close the same question with a payoff, summary, callback, or loop-close beat.",
            "copyRule": "The opening hook and final payoff must be visible in viewer-facing subtitle or TTS, not only in internal planning notes.",
        },
    }


def _audience_interest_payload(manifest: dict) -> tuple[str, dict]:
    for key in (
        "audienceInterest",
        "audienceInterestFit",
        "topicDemand",
        "topicDemandSignal",
        "trendFit",
        "viewerDemand",
    ):
        payload = manifest.get(key)
        if isinstance(payload, dict):
            return key, payload
    return "", {}


def _audience_interest_required(manifest: dict) -> bool:
    return bool(
        _truthy_metadata(manifest.get("audienceInterestRequired"))
        or _upload_candidate_required(manifest)
        or _truthy_metadata(manifest.get("qualitySampleSetRequired"))
        or _sample_set_payload(manifest)
    )


def _interest_score(payload: dict) -> int:
    for key in ("interestScore", "audienceInterestScore", "demandScore", "curiosityScore"):
        try:
            return int(payload.get(key))
        except (TypeError, ValueError):
            continue
    return -1


def _valid_interest_evidence_count(payload: dict) -> int:
    raw = payload.get("evidenceItems") or payload.get("signals") or payload.get("interestEvidenceItems") or []
    if isinstance(raw, dict):
        raw = [raw]
    if not isinstance(raw, list):
        return 0
    count = 0
    for item in raw:
        if not isinstance(item, dict):
            continue
        source = _sample_text(item.get("source") or item.get("surface") or item.get("url") or item.get("label"))
        signal = _sample_text(item.get("signal") or item.get("evidence") or item.get("metric"))
        relevance = _sample_text(item.get("relevance") or item.get("whyItMatters") or item.get("viewerReason"))
        if len(source) >= 4 and len(signal) >= 8 and len(relevance) >= 16:
            count += 1
    return count


def _build_audience_interest_source_fit_review(manifest: dict) -> dict:
    required = _audience_interest_required(manifest)
    concrete_signal_required = bool(
        _truthy_metadata(manifest.get("qualitySampleSetRequired"))
        or _sample_set_payload(manifest)
        or _upload_candidate_required(manifest)
    )
    payload_key, payload = _audience_interest_payload(manifest)
    topic_payload_key, topic_payload = _topic_hook_payoff_payload(manifest)
    target_audience = _payload_text(
        payload,
        manifest,
        "targetAudience",
        "audience",
        "viewerSegment",
        "market",
    )
    interest_driver = _payload_text(
        payload,
        manifest,
        "interestDriver",
        "whyPeopleCare",
        "curiosityAngle",
        "viewerCuriosity",
    )
    why_now = _payload_text(
        payload,
        manifest,
        "whyNow",
        "whyNowOrEvergreen",
        "evergreenReason",
        "recencyReason",
    )
    evidence = _payload_text(
        payload,
        manifest,
        "trendEvidence",
        "socialProofEvidence",
        "searchEvidence",
        "currentConversationEvidence",
        "interestEvidence",
    )
    scroll_stop_hook = _payload_text(
        payload,
        topic_payload,
        "scrollStopHook",
        "hook",
        "viewerHook",
        "openingHook",
    )
    source_strategy = _payload_text(
        payload,
        manifest,
        "sourceStrategy",
        "sourceSelectionBrief",
        "sourceFit",
        "sourcePlan",
    )
    comment_or_share_reason = _payload_text(
        payload,
        manifest,
        "commentPrompt",
        "shareReason",
        "viewerParticipation",
        "commentReason",
    )
    verdict = str(
        payload.get("audienceInterestVerdict")
        or payload.get("interestVerdict")
        or payload.get("verdict")
        or ""
    ).strip().lower()
    if verdict in {"ok", "approved", "good", "fit", "accepted"}:
        verdict = "pass"
    score = _interest_score(payload)
    evidence_count = _valid_interest_evidence_count(payload)
    combined_claim = " ".join(
        [
            str(manifest.get("topic") or ""),
            _payload_text(topic_payload, manifest, "topic", "hook", "payoff"),
            target_audience,
            interest_driver,
            why_now,
            evidence,
            scroll_stop_hook,
            source_strategy,
        ]
    ).lower()
    generic_hits = [
        term
        for term in AUDIENCE_INTEREST_GENERIC_TERMS
        if term.lower() in combined_claim
    ]

    missing: list[str] = []
    if not payload:
        missing.append("audienceInterest")
    if len(target_audience) < 8:
        missing.append("targetAudience>=8")
    if len(interest_driver) < 20:
        missing.append("interestDriver>=20")
    if len(why_now) < 20:
        missing.append("whyNowOrEvergreen>=20")
    if len(evidence) < 28 and evidence_count < 1:
        missing.append("interestEvidence>=28 or evidenceItems>=1")
    if concrete_signal_required and evidence_count < 2:
        missing.append("concreteInterestSignals>=2")
    if len(scroll_stop_hook) < 12:
        missing.append("scrollStopHook>=12")
    if len(source_strategy) < 24:
        missing.append("sourceStrategy>=24")
    if len(comment_or_share_reason) < 12:
        missing.append("commentOrShareReason>=12")
    if score < 4:
        missing.append("interestScore>=4")
    if verdict != "pass":
        missing.append("audienceInterestVerdict=pass")
    if generic_hits and evidence_count < 2:
        missing.append("nonGenericInterestEvidence")

    return {
        "required": required,
        "status": "fail" if required and missing else "pass",
        "payloadKey": payload_key,
        "topicPayloadKey": topic_payload_key,
        "targetAudience": target_audience,
        "interestDriver": interest_driver,
        "whyNowOrEvergreen": why_now,
        "interestEvidence": evidence,
        "validEvidenceCount": evidence_count,
        "concreteSignalRequired": concrete_signal_required,
        "scrollStopHook": scroll_stop_hook,
        "sourceStrategy": source_strategy,
        "commentOrShareReason": comment_or_share_reason,
        "interestScore": score,
        "verdict": verdict,
        "genericInterestTerms": generic_hits,
        "missingFields": missing,
        "policy": {
            "topicRule": "Source-led quality claims must prove why the topic is worth a viewer's attention before source/layout/TTS quality can count.",
            "evidenceRule": "Generic claims such as viral, trending, popular, or people are interested need at least two concrete source/signal/relevance evidence items for sample-set or upload-level claims.",
            "sourceRule": "The source plan must say how fetched GIF/image/video assets prove the curiosity hook, not just that they match context.",
            "sampleRule": "Accepted sample-set proofs need audience-interest evidence so engineering fixtures cannot stand in for viewer-worthy topics.",
        },
    }


def _source_intent_generic_hits(*values: object) -> list[str]:
    text = " ".join(str(value or "") for value in values).lower()
    compact = re.sub(r"\s+", "", text)
    hits: list[str] = []
    for term in SOURCE_INTENT_GENERIC_TERMS:
        term_lower = term.lower()
        if term_lower in text or re.sub(r"\s+", "", term_lower) in compact:
            hits.append(term)
    return hits


def _scene_source_intent_status(scene: dict, visual_asset: dict) -> tuple[bool, list[str], dict]:
    role = _scene_intent_role(scene, visual_asset)
    media_kind = _normalized_source_tag(
        _source_acquisition_value(scene, visual_asset, "sourceMediaKind", "mediaKind")
    )
    caption_purpose = str(scene.get("captionPurpose") or "").strip().lower().removeprefix("viewer-")
    proof_claim = _source_context_value(
        scene,
        visual_asset,
        "proofClaim",
        "sourceProofClaim",
        "visualProofClaim",
        "sceneClaim",
        "viewerClaim",
    )
    viewer_question = _source_context_value(
        scene,
        visual_asset,
        "viewerQuestion",
        "hookQuestion",
        "viewerQuestionAnswered",
        "questionAnswered",
    )
    viewer_task = _source_context_value(
        scene,
        visual_asset,
        "viewerTask",
        "sceneViewerTask",
        "sourceViewerTask",
        "visualProofTask",
        "viewerJob",
    )
    binding_review = _source_context_value(
        scene,
        visual_asset,
        "sceneSourceBindingReview",
        "sourceIntentBindingReview",
        "sourceProofReview",
    )
    binding_verdict = _source_context_value(
        scene,
        visual_asset,
        "sceneSourceBindingVerdict",
        "sourceIntentBindingVerdict",
        "sourceProofVerdict",
    )
    media_choice = _source_context_value(
        scene,
        visual_asset,
        "mediaChoiceRationale",
        "whyGifOrImage",
        "sourceTypeDecision",
    )
    motion_fit = _source_context_value(scene, visual_asset, "motionFit", "whyMotionFits")
    still_fit = _source_context_value(scene, visual_asset, "stillFit", "whyStillImageFits")
    subtitle_text = str(scene.get("subtitleText") or "").strip()
    narration_text = str(scene.get("narrationText") or "").strip()
    layout_note = str(scene.get("layoutVariantNote") or "").strip()
    quality_review = str(scene.get("qualityReviewNote") or "").strip()
    claim_keywords = _source_context_keywords(proof_claim, viewer_question, viewer_task)
    viewer_overlap = _source_context_overlap(
        claim_keywords,
        subtitle_text,
        narration_text,
        layout_note,
        quality_review,
    )
    generic_hits = _source_intent_generic_hits(proof_claim, viewer_question, viewer_task, binding_review)

    missing: list[str] = []
    if role not in SOURCE_INTENT_ROLES:
        missing.append("intentRole")
    if role == "hook" and caption_purpose != "hook":
        missing.append("hookCaptionPurpose")
    if role in {"payoff", "callback"} and caption_purpose not in {"payoff", "context", "proof"}:
        missing.append("payoffCaptionPurpose")
    if len(proof_claim) < 24:
        missing.append("sourceProofClaim>=24")
    if len(viewer_task) < 18:
        missing.append("sourceViewerTask>=18")
    if len(binding_review) < 40:
        missing.append("sourceIntentBindingReview>=40")
    if _manual_visual_verdict_status(binding_verdict) != "pass":
        missing.append("sourceIntentBindingVerdict=pass")
    if generic_hits:
        missing.append("sourceIntentNotGeneric")
    if len(claim_keywords) < 2:
        missing.append("sourceClaimKeywords>=2")
    elif len(viewer_overlap) < 1:
        missing.append("sourceClaimAppearsInViewerTextOrLayout")
    if media_kind in {"gif", "video"} and not _contains_editorial_term(
        " ".join([proof_claim, media_choice, motion_fit, binding_review]),
        INTERNET_SOURCE_MOTION_EDITORIAL_TERMS,
    ):
        missing.append("motionIntentForGifVideo")
    if media_kind == "image" and not _contains_editorial_term(
        " ".join([proof_claim, media_choice, still_fit, binding_review]),
        INTERNET_SOURCE_STILL_EDITORIAL_TERMS,
    ):
        missing.append("stillIntentForImage")

    return not missing, missing, {
        "role": role,
        "captionPurpose": caption_purpose,
        "mediaKind": media_kind,
        "proofClaim": proof_claim,
        "viewerQuestion": viewer_question,
        "viewerTask": viewer_task,
        "bindingReview": binding_review,
        "bindingVerdict": binding_verdict,
        "claimKeywords": sorted(claim_keywords),
        "viewerOverlap": viewer_overlap,
        "genericHits": generic_hits,
    }


def _build_scene_source_intent_binding_review(manifest: dict) -> dict:
    required = _internet_source_editorial_integration_required(manifest)
    reviewed: list[str] = []
    missing: list[str] = []
    scene_details: list[dict] = []
    role_counts: dict[str, int] = {}
    for scene in manifest.get("scenes", []):
        scene_id = str(scene.get("sceneId") or "")
        visual_asset = _visual_asset_for_scene(manifest, scene_id)
        is_candidate = _is_internet_source_candidate(scene, visual_asset)
        if not required and not is_candidate:
            continue
        ready, scene_missing, detail = _scene_source_intent_status(scene, visual_asset)
        detail["sceneId"] = scene_id
        detail["candidate"] = is_candidate
        scene_details.append(detail)
        role = str(detail.get("role") or "")
        if role:
            role_counts[role] = role_counts.get(role, 0) + 1
        if scene_missing:
            missing.append(f"{scene_id}:{','.join(dict.fromkeys(scene_missing))}")
        else:
            reviewed.append(scene_id)

    status = "pass"
    if required and (missing or not reviewed):
        status = "fail"
    return {
        "required": required,
        "status": status,
        "reviewedScenes": reviewed,
        "missingScenes": missing,
        "roleCounts": role_counts,
        "sceneDetails": scene_details,
        "policy": {
            "intentRule": "Every fetched source scene needs an explicit intent role, proof claim, viewer task, and pass verdict.",
            "bindingRule": "The source proof claim must appear in viewer-facing copy or layout review, not only in an internal note.",
            "mediaRule": "GIF/video must be selected because motion proves the beat; image must be selected because a still frame/context proves the beat.",
        },
    }


def _visual_frame_review_payload(manifest: dict) -> tuple[str, dict]:
    for key in (
        "visualFrameReview",
        "phoneFrameReview",
        "phoneSizedFrameReview",
        "contactSheetReview",
        "humanVisualReview",
    ):
        payload = manifest.get(key)
        if isinstance(payload, dict):
            return key, payload
    return "", {}


def _visual_frame_scene_reviews(payload: dict) -> dict[str, dict]:
    raw = payload.get("sceneReviews") or payload.get("scenes") or payload.get("sceneFrameReviews")
    if isinstance(raw, dict):
        return {
            str(scene_id): review
            for scene_id, review in raw.items()
            if isinstance(review, dict)
        }
    if isinstance(raw, list):
        reviews: dict[str, dict] = {}
        for item in raw:
            if not isinstance(item, dict):
                continue
            scene_id = str(item.get("sceneId") or item.get("id") or "").strip()
            if scene_id:
                reviews[scene_id] = item
        return reviews
    return {}


def _frame_review_verdict(payload: dict, *keys: str) -> str:
    for key in keys:
        value = payload.get(key)
        if value is not None:
            return _manual_visual_verdict_status(value)
    return ""


def _frame_review_text_present(payload: dict, *keys: str, min_length: int = 48) -> bool:
    for key in keys:
        value = payload.get(key)
        if len(str(value or "").strip()) >= min_length:
            return True
    return False


def _build_visual_frame_review_evidence(manifest: dict) -> dict:
    required = _internet_source_editorial_integration_required(manifest)
    payload_key, payload = _visual_frame_review_payload(manifest)
    contact_sheet = str(
        payload.get("contactSheetPath")
        or payload.get("frameReviewPath")
        or payload.get("phoneReviewPath")
        or ""
    ).strip()
    reviewer_type = str(payload.get("reviewerType") or payload.get("reviewMode") or "").strip()
    review_notes = str(payload.get("reviewNotes") or payload.get("notes") or payload.get("summary") or "").strip()
    scene_reviews = _visual_frame_scene_reviews(payload)
    source_scene_ids: list[str] = []
    missing_scenes: list[str] = []
    reviewed_scenes: list[str] = []
    loop_required = False
    for scene in manifest.get("scenes", []):
        scene_id = str(scene.get("sceneId") or "")
        visual_asset = _visual_asset_for_scene(manifest, scene_id)
        if not _is_internet_source_candidate(scene, visual_asset):
            continue
        source_scene_ids.append(scene_id)
        if _source_loop_group_id(scene, visual_asset):
            loop_required = True
        review = scene_reviews.get(scene_id) or {}
        scene_missing: list[str] = []
        if _frame_review_verdict(review, "sourceVisibleVerdict", "sourceVisibilityVerdict") != "pass":
            scene_missing.append("sourceVisibleVerdict=pass")
        if _frame_review_verdict(review, "sourceDominanceVerdict", "sourceFramingVerdict") != "pass":
            scene_missing.append("sourceDominanceVerdict=pass")
        if _frame_review_verdict(review, "captionClearVerdict", "captionOcclusionVerdict") != "pass":
            scene_missing.append("captionClearVerdict=pass")
        if _frame_review_verdict(review, "motionStabilityVerdict", "cameraStabilityVerdict") != "pass":
            scene_missing.append("motionStabilityVerdict=pass")
        if _frame_review_verdict(review, "sourceRepetitionVerdict", "sourceReuseVerdict") != "pass":
            scene_missing.append("sourceRepetitionVerdict=pass")
        if len(str(review.get("review") or review.get("notes") or "").strip()) < 32:
            scene_missing.append("sceneFrameReview>=32")
        if scene_missing:
            missing_scenes.append(f"{scene_id}:{','.join(dict.fromkeys(scene_missing))}")
        else:
            reviewed_scenes.append(scene_id)

    missing: list[str] = []
    if not payload:
        missing.append("visualFrameReview")
    if len(contact_sheet) < 8:
        missing.append("contactSheetPath/frameReviewPath")
    if len(reviewer_type) < 4:
        missing.append("reviewerType")
    if len(review_notes) < 80:
        missing.append("reviewNotes>=80")
    for key in VISUAL_FRAME_REVIEW_REQUIRED_VERDICTS:
        if _frame_review_verdict(payload, key) != "pass":
            missing.append(f"{key}=pass")
    if not _frame_review_text_present(
        payload,
        "captionTtsReview",
        "captionTtsHumanReview",
        "ttsCaptionReview",
        min_length=80,
    ):
        missing.append("captionTtsReview>=80")
    if not _frame_review_text_present(
        payload,
        "motionStabilityReview",
        "cameraStabilityReview",
        "visualStabilityReview",
        min_length=80,
    ):
        missing.append("motionStabilityReview>=80")
    if not _frame_review_text_present(
        payload,
        "sourceRepetitionReview",
        "sourceReuseReview",
        "sourceVarietyReview",
        min_length=80,
    ):
        missing.append("sourceRepetitionReview>=80")
    if loop_required and _frame_review_verdict(payload, "loopNaturalnessVerdict") != "pass":
        missing.append("loopNaturalnessVerdict=pass")
    if source_scene_ids and len(reviewed_scenes) < len(source_scene_ids):
        missing.append("allSourceScenesFrameReviewed")

    status = "pass"
    if required and (missing or missing_scenes):
        status = "fail"
    return {
        "required": required,
        "status": status,
        "payloadKey": payload_key,
        "contactSheetPath": contact_sheet,
        "reviewerType": reviewer_type,
        "reviewedScenes": reviewed_scenes,
        "missingFields": missing,
        "missingScenes": missing_scenes,
        "sourceSceneIds": source_scene_ids,
        "loopRequired": loop_required,
        "policy": {
            "evidenceRule": "Render-gate pass is not enough for source-led meme/GIF proof; phone-sized/contact-sheet review evidence must be structured in the manifest.",
            "layoutRule": "Frame review must confirm source dominance, caption non-occlusion, layout naturalness, TTS/caption sync, motion stability, source repetition control, and ending resolution.",
            "sceneRule": "Every internet source scene needs a per-scene frame review so tiny framed sources, hidden subjects, shaky derived motion, and repeated sources cannot pass by self-description only.",
        },
    }


def _copy_style_prompt_payload(manifest: dict) -> tuple[str, dict]:
    for key in CONVERSATIONAL_COPY_PROMPT_KEYS:
        payload = manifest.get(key)
        if isinstance(payload, dict):
            return key, payload
    return "", {}


def _copy_style_prompt_list(payload: dict, *keys: str) -> list[str]:
    values: list[str] = []
    for key in keys:
        raw = payload.get(key)
        if isinstance(raw, list):
            values.extend(str(item).strip() for item in raw if str(item).strip())
        elif isinstance(raw, str) and raw.strip():
            values.append(raw.strip())
    return values


def _copy_has_conversational_marker(text: str) -> bool:
    lowered = str(text or "").lower()
    if re.search(r"[가-힣]", lowered):
        return any(marker in lowered for marker in CONVERSATIONAL_COPY_KOREAN_MARKERS)
    return any(marker in lowered for marker in CONVERSATIONAL_COPY_ENGLISH_MARKERS)


def _copy_prompt_has_script_quality_rule(prompt: dict) -> bool:
    text = " ".join(
        str(prompt.get(key) or "")
        for key in (
            "captionRule",
            "subtitleRule",
            "onscreenTextRule",
            "narrationRule",
            "scriptRule",
            "ttsRule",
            "scriptQualityRule",
            "sceneCopyRule",
            "beatQualityRule",
            "captionNarrationQualityRule",
        )
    ).lower()
    compact = re.sub(r"\s+", "", text)
    if len(compact) < 48:
        return False
    has_label_guard = any(term in text or re.sub(r"\s+", "", term) in compact for term in SCRIPT_QUALITY_PROMPT_LABEL_TERMS)
    has_arc_rule = any(term in text or re.sub(r"\s+", "", term) in compact for term in SCRIPT_QUALITY_PROMPT_PAYOFF_TERMS)
    return has_label_guard and has_arc_rule


def _copy_has_viewer_turn(text: str, purpose: str = "") -> bool:
    lowered = str(text or "").lower()
    compact = re.sub(r"\s+", "", lowered)
    terms = VIEWER_COPY_ARC_TERMS_BY_PURPOSE.get(purpose, ()) + VIEWER_COPY_TURN_TERMS
    return any(term in lowered or re.sub(r"\s+", "", term) in compact for term in terms)


def _copy_bare_label_question_issue(text: str) -> bool:
    stripped = str(text or "").strip()
    if "?" not in stripped:
        return False
    compact = re.sub(r"[\s?!.,;:·'\"“”‘’()\[\]{}-]+", "", stripped.lower())
    if len(compact) > 14:
        return False
    tokens = re.findall(r"[가-힣]+|[a-z0-9']+", stripped.lower())
    if len(tokens) > 3:
        return False
    return not _copy_has_viewer_turn(stripped)


def _copy_is_thin_reaction_line(text: str) -> bool:
    stripped = str(text or "").strip()
    if not stripped or _compact_text_length(stripped) > 18:
        return False
    lowered = stripped.lower()
    compact = re.sub(r"[\s?!.,;:·'\"“”‘’()\[\]{}-]+", "", lowered)
    if not any(compact.endswith(re.sub(r"\s+", "", ending.lower()).rstrip("?")) for ending in SCRIPT_QUALITY_THIN_REACTION_ENDINGS):
        return False
    return not any(term in lowered or re.sub(r"\s+", "", term.lower()) in compact for term in SCRIPT_QUALITY_SUBSTANTIVE_TURN_TERMS)


def _viewer_copy_script_quality_issues(
    subtitle_text: str,
    narration_text: str,
    caption_purpose: str,
    short_source_loop_callout: bool,
) -> list[str]:
    issues: list[str] = []
    combined = " ".join([subtitle_text, narration_text])
    narration_len = _compact_text_length(narration_text)
    if _copy_bare_label_question_issue(subtitle_text):
        issues.append("subtitleBareLabelQuestion")
    if caption_purpose in {"proof", "context", "payoff"} and not _copy_has_viewer_turn(combined, caption_purpose):
        issues.append(f"{caption_purpose}ViewerTurn")
    min_narration_chars = SCRIPT_QUALITY_MIN_NARRATION_CHARS_BY_PURPOSE.get(caption_purpose, 0)
    if min_narration_chars and narration_len < min_narration_chars:
        issues.append(f"{caption_purpose}NarrationTooThin")
    if _copy_is_thin_reaction_line(narration_text):
        issues.append("narrationThinReactionLine")
    if short_source_loop_callout and caption_purpose in {"proof", "context", "payoff"} and narration_len < 10:
        issues.append("shortCalloutTooThinForScriptQuality")
    if caption_purpose == "payoff" and narration_len < 12:
        issues.append("payoffNarrationTooThin")
    return issues


def _conversational_copy_scene_status(scene: dict, content_template: str) -> tuple[bool, list[str], dict]:
    subtitle_text = str(scene.get("subtitleText") or "").strip()
    narration_text = str(scene.get("narrationText") or "").strip()
    caption_purpose = str(scene.get("captionPurpose") or "").strip().lower()
    if caption_purpose.startswith("viewer-"):
        caption_purpose = caption_purpose.removeprefix("viewer-")
    short_source_loop_callout = _short_source_loop_callout_scene(scene, content_template)
    combined_viewer_text = " ".join([subtitle_text, narration_text])
    forbidden_terms = [
        term
        for term in CONVERSATIONAL_COPY_FORBIDDEN_TERMS
        if _contains_editorial_term(combined_viewer_text, (term,))
    ]
    formal_endings = KOREAN_FORMAL_ENDING_PATTERN.findall(narration_text)
    missing: list[str] = []
    if _compact_text_length(subtitle_text) < 4:
        missing.append("subtitleText>=4")
    if not short_source_loop_callout and not _copy_has_conversational_marker(subtitle_text):
        missing.append("subtitleConversationalMarker")
    if caption_purpose == "hook" and "?" not in subtitle_text and "왜" not in subtitle_text:
        missing.append("hookSubtitleQuestionOrReaction")
    if _compact_text_length(narration_text) < 24 and not short_source_loop_callout:
        missing.append("narrationText>=24")
    if not _copy_has_conversational_marker(narration_text):
        missing.append("narrationConversationalMarker")
    if formal_endings:
        missing.append("narrationFormalEnding")
    if forbidden_terms:
        missing.append("viewerCopyForbiddenTerms")
    script_quality_issues = _viewer_copy_script_quality_issues(
        subtitle_text,
        narration_text,
        caption_purpose,
        short_source_loop_callout,
    )
    missing.extend(script_quality_issues)
    return not missing, missing, {
        "subtitleText": subtitle_text,
        "narrationLength": _compact_text_length(narration_text),
        "captionPurpose": caption_purpose,
        "formalEndings": formal_endings,
        "forbiddenTerms": sorted(set(forbidden_terms)),
        "subtitleConversational": _copy_has_conversational_marker(subtitle_text),
        "narrationConversational": _copy_has_conversational_marker(narration_text),
        "shortSourceLoopCallout": short_source_loop_callout,
        "scriptQualityIssues": script_quality_issues,
    }


def _viewer_copy_repetition_tokens(text: object) -> set[str]:
    normalized = str(text or "").replace("\\N", " ").lower()
    tokens = set(re.findall(r"[가-힣]{2,}|[a-z0-9']{3,}", normalized))
    stopwords = CONVERSATIONAL_COPY_REPETITION_STOPWORDS | INTERNET_SOURCE_INTEGRATION_STOPWORDS
    return {
        token
        for token in tokens
        if token not in stopwords and not token.endswith(("입니다", "합니다", "됩니다"))
    }


def _viewer_caption_repetition_review(manifest: dict) -> dict:
    token_scenes: dict[str, list[str]] = {}
    scene_tokens: dict[str, list[str]] = {}
    for scene in manifest.get("scenes", []):
        scene_id = str(scene.get("sceneId") or "")
        subtitle_text = str(scene.get("subtitleText") or "").strip()
        if not scene_id or not subtitle_text:
            continue
        tokens = sorted(_viewer_copy_repetition_tokens(subtitle_text))
        scene_tokens[scene_id] = tokens
        for token in tokens:
            token_scenes.setdefault(token, []).append(scene_id)

    repeated_terms = {
        token: scene_ids
        for token, scene_ids in sorted(token_scenes.items())
        if len(scene_ids) >= 3
    }
    affected_scenes = sorted({
        scene_id
        for scene_ids in repeated_terms.values()
        for scene_id in scene_ids
    })
    return {
        "status": "fail" if repeated_terms else "pass",
        "repeatedTerms": repeated_terms,
        "affectedScenes": affected_scenes,
        "sceneTokens": scene_tokens,
    }


def _build_conversational_copy_style_review(manifest: dict) -> dict:
    required = _internet_source_editorial_integration_required(manifest)
    prompt_key, prompt = _copy_style_prompt_payload(manifest)
    prompt_missing: list[str] = []
    if required and not prompt:
        prompt_missing.append("copyStylePrompt")
    tone = " ".join(str(prompt.get(key) or "") for key in ("tone", "style", "voice", "copyTone"))
    if required and not any(term in tone.lower() for term in CONVERSATIONAL_COPY_TONE_TERMS):
        prompt_missing.append("tone=conversational/구어체")
    subtitle_rule = " ".join(
        str(prompt.get(key) or "") for key in ("captionRule", "subtitleRule", "onscreenTextRule")
    )
    narration_rule = " ".join(
        str(prompt.get(key) or "") for key in ("narrationRule", "scriptRule", "ttsRule")
    )
    forbidden_patterns = _copy_style_prompt_list(prompt, "forbiddenPatterns", "banPatterns", "neverUse")
    reference_takeaways = _copy_style_prompt_list(
        prompt,
        "referenceTakeaways",
        "externalReferenceTakeaways",
        "shortformReferenceTakeaways",
    )
    if required and len(subtitle_rule.strip()) < 32:
        prompt_missing.append("captionRule>=32")
    if required and len(narration_rule.strip()) < 32:
        prompt_missing.append("narrationRule>=32")
    if required and not _copy_prompt_has_script_quality_rule(prompt):
        prompt_missing.append("scriptQualityRule=labelGuard+hookTurnPayoff")
    if required and len(forbidden_patterns) < 3:
        prompt_missing.append("forbiddenPatterns>=3")
    if required and len(reference_takeaways) < 2:
        prompt_missing.append("referenceTakeaways>=2")

    reviewed: list[str] = []
    missing_scenes: list[str] = []
    scene_details: list[dict] = []
    repetition_review = _viewer_caption_repetition_review(manifest)
    for scene in manifest.get("scenes", []):
        scene_id = str(scene.get("sceneId") or "")
        visual_asset = _visual_asset_for_scene(manifest, scene_id)
        is_candidate = _is_internet_source_candidate(scene, visual_asset)
        if not required and not is_candidate:
            continue
        ready, scene_missing, detail = _conversational_copy_scene_status(scene, str(manifest.get("contentTemplate") or manifest.get("templateType") or ""))
        detail["sceneId"] = scene_id
        detail["candidate"] = is_candidate
        scene_details.append(detail)
        if ready:
            reviewed.append(scene_id)
        else:
            missing_scenes.append(f"{scene_id}:{','.join(dict.fromkeys(scene_missing))}")

    status = "pass"
    if prompt_missing or missing_scenes or repetition_review["status"] == "fail" or (required and not reviewed):
        status = "fail"
    return {
        "required": required,
        "status": status,
        "promptKey": prompt_key,
        "promptMissing": prompt_missing,
        "reviewedScenes": reviewed,
        "missingScenes": missing_scenes,
        "repetitionReview": repetition_review,
        "sceneDetails": scene_details,
        "policy": {
            "promptRule": "Source-led renders must include a copyStylePrompt with conversational tone, caption/script rules, forbidden phrases, and external short-form reference takeaways.",
            "subtitleRule": "Viewer captions should read like a spoken question, reaction, or payoff; production labels and scene descriptions cannot pass.",
            "narrationRule": "TTS script should sound spoken, carry a hook/turn/payoff beat, and avoid Korean report-style endings such as -습니다/-입니다/-합니다.",
            "scriptQualityRule": "Bare label or noun-only questions cannot pass as viewer copy; proof/context/payoff scenes need a real perceptual turn or audience action.",
            "repetitionRule": "A viewer-facing caption keyword repeated across three or more scenes fails because it makes the edit feel like the same beat again.",
        },
    }


def _tts_pacing_prompt_has_timing_rule(prompt: dict) -> bool:
    text = " ".join(
        str(prompt.get(key) or "")
        for key in (
            "ttsPacingRule",
            "audioPacingRule",
            "narrationPacingRule",
            "scriptPacingRule",
            "narrationRule",
        )
    ).lower()
    if len(text.strip()) < 32:
        return False
    return any(term in text for term in ("속도", "호흡", "pause", "pacing", "tempo", "rate", "장면 길이", "자막"))


def _tts_pacing_scene_status(manifest: dict, scene: dict, visual_asset: dict) -> tuple[bool, list[str], dict]:
    scene_id = str(scene.get("sceneId") or "")
    audio_asset = _audio_asset_for_scene(manifest, scene_id)
    subtitle_text = str(scene.get("subtitleText") or "").strip()
    narration_text = str(scene.get("narrationText") or "").strip()
    duration_sec = _scene_duration_seconds(scene)
    subtitle_len = _compact_text_length(subtitle_text)
    narration_len = _compact_text_length(narration_text)
    korean_count = sum(1 for char in narration_text if "\uac00" <= char <= "\ud7a3" or "\u3131" <= char <= "\u318e")
    word_count = len(re.findall(r"[A-Za-z0-9']+", narration_text))
    narration_density = 0.0
    narration_density_kind = "none"
    if duration_sec > 0 and narration_len:
        if korean_count > max(1, len(narration_text)) * 0.3:
            narration_density = narration_len / duration_sec
            narration_density_kind = "koreanCompactCharsPerSec"
        else:
            narration_density = word_count / duration_sec
            narration_density_kind = "englishWordsPerSec"

    subtitle_narration_ratio = (subtitle_len / narration_len) if narration_len else 0.0
    audio_fit = audio_asset.get("audioDurationFit") if isinstance(audio_asset.get("audioDurationFit"), dict) else {}
    try:
        tempo_speed = float(audio_fit.get("speed") or 1.0)
    except (TypeError, ValueError):
        tempo_speed = 1.0
    fit_mode = str(audio_fit.get("mode") or "").strip()

    missing: list[str] = []
    if duration_sec <= 0:
        missing.append("sceneDurationSec")
    if narration_len >= 24 and subtitle_narration_ratio < TTS_PACING_MIN_SUBTITLE_NARRATION_RATIO:
        missing.append("subtitleNarrationRatio")
    if narration_density_kind == "koreanCompactCharsPerSec" and narration_density > TTS_PACING_MAX_KOREAN_COMPACT_CHARS_PER_SEC:
        missing.append("narrationKoreanCharsPerSec")
    if narration_density_kind == "englishWordsPerSec" and narration_density > TTS_PACING_MAX_ENGLISH_WORDS_PER_SEC:
        missing.append("narrationEnglishWordsPerSec")
    if fit_mode == "tempo-fit" and tempo_speed > TTS_PACING_MAX_TEMPO_SPEED:
        missing.append("audioTempoFitSpeed")

    return not missing, missing, {
        "sceneId": scene_id,
        "mediaKind": _normalized_source_tag(
            _source_acquisition_value(scene, visual_asset, "sourceMediaKind", "mediaKind")
        ),
        "durationSec": round(duration_sec, 3),
        "subtitleCompactLength": subtitle_len,
        "narrationCompactLength": narration_len,
        "subtitleNarrationRatio": round(subtitle_narration_ratio, 3),
        "narrationDensity": round(narration_density, 3),
        "narrationDensityKind": narration_density_kind,
        "audioDurationFit": audio_fit,
        "tempoSpeed": round(tempo_speed, 3),
    }


def _build_tts_pacing_alignment_review(manifest: dict) -> dict:
    required = _internet_source_editorial_integration_required(manifest)
    prompt_key, prompt = _copy_style_prompt_payload(manifest)
    prompt_missing: list[str] = []
    if required and not _tts_pacing_prompt_has_timing_rule(prompt):
        prompt_missing.append("ttsPacingRule>=32")

    reviewed: list[str] = []
    missing_scenes: list[str] = []
    scene_details: list[dict] = []
    for scene in manifest.get("scenes", []):
        scene_id = str(scene.get("sceneId") or "")
        visual_asset = _visual_asset_for_scene(manifest, scene_id)
        is_candidate = _is_internet_source_candidate(scene, visual_asset)
        if not required and not is_candidate:
            continue
        ready, scene_missing, detail = _tts_pacing_scene_status(manifest, scene, visual_asset)
        detail["candidate"] = is_candidate
        scene_details.append(detail)
        if ready:
            reviewed.append(scene_id)
        else:
            missing_scenes.append(f"{scene_id}:{','.join(dict.fromkeys(scene_missing))}")

    status = "pass"
    if prompt_missing or missing_scenes or (required and not reviewed):
        status = "fail"
    return {
        "required": required,
        "status": status,
        "promptKey": prompt_key,
        "promptMissing": prompt_missing,
        "reviewedScenes": reviewed,
        "missingScenes": missing_scenes,
        "sceneDetails": scene_details,
        "policy": {
            "tempoRule": f"TTS tempo-fit speed must stay <= {TTS_PACING_MAX_TEMPO_SPEED:.2f}; do not compress long narration into short scenes.",
            "densityRule": f"Korean narration density must stay <= {TTS_PACING_MAX_KOREAN_COMPACT_CHARS_PER_SEC:.1f} compact chars/sec for source-led proof scenes.",
            "alignmentRule": f"Subtitle compact length should be at least {TTS_PACING_MIN_SUBTITLE_NARRATION_RATIO:.2f} of narration compact length when narration is substantial.",
        },
    }


def _build_source_loop_rhythm_review(manifest: dict) -> dict:
    groups: dict[str, list[tuple[dict, dict]]] = {}
    for scene in manifest.get("scenes", []):
        scene_id = str(scene.get("sceneId") or "")
        visual_asset = _visual_asset_for_scene(manifest, scene_id)
        group_id = _source_loop_group_id(scene, visual_asset)
        if group_id:
            groups.setdefault(group_id, []).append((scene, visual_asset))

    reviewed_groups: list[str] = []
    missing_groups: list[str] = []
    group_details: list[dict] = []
    for group_id, members in groups.items():
        scene_ids = [str(scene.get("sceneId") or "") for scene, _asset in members]
        subtitles = [
            re.sub(r"\s+", "", str(scene.get("subtitleText") or "").strip().lower())
            for scene, _asset in members
            if str(scene.get("subtitleText") or "").strip()
        ]
        identities = sorted({
            _visual_asset_identity(asset)
            for _scene, asset in members
            if _visual_asset_identity(asset)
        })
        media_kinds = sorted({
            _normalized_source_tag(_source_acquisition_value(scene, asset, "sourceMediaKind", "mediaKind"))
            for scene, asset in members
        })
        reviews = [_source_loop_review_text(scene, asset) for scene, asset in members]
        combined_review = " ".join(reviews).strip()
        review_has_term = any(term in combined_review.lower() for term in SOURCE_LOOP_REVIEW_TERMS)
        render_paths = [
            str(
                scene.get("sourcePath")
                or asset.get("sourcePath")
                or asset.get("outputPath")
                or scene.get("sourceLocalPath")
                or asset.get("sourceLocalPath")
                or ""
            ).strip()
            for scene, asset in members
        ]
        reframe_evidence_by_scene = {
            str(scene.get("sceneId") or ""): _scene_field_text(
                scene,
                "sourceLoopReframeEvidence",
                "sourceLoopRetimingEvidence",
                "sourceLoopVisualChangeReview",
            ) or _scene_field_text(
                asset,
                "sourceLoopReframeEvidence",
                "sourceLoopRetimingEvidence",
                "sourceLoopVisualChangeReview",
            )
            for scene, asset in members
        }

        issues: list[str] = []
        if len(members) < 2:
            issues.append("sourceLoopGroupScenes>=2")
        if len(identities) != 1:
            issues.append("singleSourceIdentity")
        if any(kind not in {"gif", "video"} for kind in media_kinds):
            issues.append("loopMediaKind=gif/video")
        for scene, asset in members:
            scene_id = str(scene.get("sceneId") or "")
            if not _source_loop_repeat_approved(scene, asset):
                issues.append(f"{scene_id}:sourceLoopRepeatApproved")
            if len(_source_loop_review_text(scene, asset)) < SOURCE_LOOP_RHYTHM_REVIEW_MIN_CHARS:
                issues.append(f"{scene_id}:sourceLoopRhythmReview>={SOURCE_LOOP_RHYTHM_REVIEW_MIN_CHARS}")
        if len(set(subtitles)) < min(2, len(members)):
            issues.append("distinctSubtitles")
        if len(members) > 1:
            first_path = render_paths[0] if render_paths else ""
            for index, (scene, _asset) in enumerate(members):
                if index == 0:
                    continue
                scene_id = str(scene.get("sceneId") or "")
                evidence = reframe_evidence_by_scene.get(scene_id) or ""
                if len(evidence) < 24:
                    issues.append(f"{scene_id}:sourceLoopReframeEvidence>=24")
                if first_path and index < len(render_paths) and render_paths[index] == first_path:
                    issues.append(f"{scene_id}:sourceLoopDerivedPathDistinct")
        if not review_has_term:
            issues.append("loopRhythmReviewMentionsLoopOrCaptionRhythm")

        detail = {
            "groupId": group_id,
            "sceneIds": scene_ids,
            "sourceIdentities": identities,
            "mediaKinds": media_kinds,
            "renderPaths": render_paths,
            "reframeEvidenceScenes": sorted(
                scene_id for scene_id, evidence in reframe_evidence_by_scene.items() if len(evidence) >= 24
            ),
            "distinctSubtitleCount": len(set(subtitles)),
            "reviewChars": len(combined_review),
            "reviewHasLoopTerm": review_has_term,
            "issues": issues,
        }
        group_details.append(detail)
        if issues:
            missing_groups.append(f"{group_id}:{','.join(dict.fromkeys(issues))}")
        else:
            reviewed_groups.append(group_id)

    required = bool(groups)
    status = "fail" if missing_groups else "pass"
    return {
        "required": required,
        "status": status,
        "reviewedGroups": reviewed_groups,
        "missingGroups": missing_groups,
        "groupDetails": group_details,
        "policy": {
            "repeatRule": "Repeated internet GIF/video source reuse is allowed only as an intentional loop group, not as default asset recycling.",
            "captionRule": "Each loop pass needs a distinct viewer caption or callout so the repeat changes meaning.",
            "reframeRule": "A second pass over the same GIF/video source needs a distinct derived path plus reframe/retime evidence, or it reads as accidental replay.",
            "reviewRule": f"Each loop scene needs a rhythm review of at least {SOURCE_LOOP_RHYTHM_REVIEW_MIN_CHARS} chars that explains loop/caption timing.",
        },
    }


def _build_ending_payoff_review(manifest: dict) -> dict:
    required = _upload_candidate_required(manifest) or _source_editorial_layout_required(manifest)
    scenes = manifest.get("scenes", [])
    final_scene = scenes[-1] if scenes else {}
    final_scene_id = str(final_scene.get("sceneId") or "")
    ending = manifest.get("endingSystem") if isinstance(manifest.get("endingSystem"), dict) else {}
    purpose = str(
        final_scene.get("endingPurpose")
        or ending.get("purpose")
        or final_scene.get("captionPurpose")
        or ""
    ).strip().lower()
    if purpose.startswith("viewer-"):
        purpose = purpose.removeprefix("viewer-")
    pacing = _scene_field_text(final_scene, "endingPacingReview", "endingReview") or _scene_field_text(ending, "pacingReview", "endingPacingReview")
    takeaway = _scene_field_text(final_scene, "finalTakeawayReview", "payoffReview") or _scene_field_text(ending, "finalTakeawayReview", "payoffReview")
    verdict = _scene_field_text(final_scene, "endingVerdict", "abruptEndingVerdict") or _scene_field_text(ending, "endingVerdict", "abruptEndingVerdict")
    missing: list[str] = []
    if purpose not in {"payoff", "summary", "next-step", "loop-close", "callback"}:
        missing.append("endingPurpose=payoff/summary/next-step/loop-close/callback")
    if len(pacing) < 36:
        missing.append("endingPacingReview>=36")
    if len(takeaway) < 36:
        missing.append("finalTakeawayReview>=36")
    if _manual_visual_verdict_status(verdict) != "pass":
        missing.append("endingVerdict=pass")
    status = "pass"
    if required and (not scenes or missing):
        status = "fail"
    return {
        "required": required,
        "status": status,
        "finalSceneId": final_scene_id,
        "missingFields": missing,
        "purpose": purpose,
        "pacingReview": pacing,
        "finalTakeawayReview": takeaway,
    }


def _build_ending_tail_pacing_review(manifest: dict) -> dict:
    required = (
        _source_editorial_layout_required(manifest)
        or _internet_source_editorial_integration_required(manifest)
    )
    scenes = manifest.get("scenes", [])
    final_scene = scenes[-1] if scenes else {}
    final_scene_id = str(final_scene.get("sceneId") or "")
    ending = manifest.get("endingSystem") if isinstance(manifest.get("endingSystem"), dict) else {}
    tail_hold_sec = _ending_tail_hold_seconds(final_scene, ending)
    fade_out_sec = _ending_fade_out_seconds(final_scene, ending)
    duration_sec = _scene_duration_seconds(final_scene)
    voice_target_sec = scene_voiceover_target_duration(final_scene) if duration_sec > 0 else 0.0
    declared_caption_sec = _scene_caption_duration(final_scene)
    rendered_caption_sec = _rendered_caption_duration_seconds(final_scene, duration_sec)
    caption_voice_coverage = rendered_caption_sec / voice_target_sec if voice_target_sec > 0 else 0.0
    has_narration = bool(_scene_field_text(final_scene, "narrationText", "voiceoverText", "script"))
    audio_asset = _audio_asset_for_scene(manifest, final_scene_id)
    audio_fit = audio_asset.get("audioDurationFit") if isinstance(audio_asset.get("audioDurationFit"), dict) else {}
    try:
        rendered_tail_sec = float(audio_fit.get("tailHoldSec") or tail_hold_sec or 0.0)
    except (TypeError, ValueError):
        rendered_tail_sec = tail_hold_sec
    tail_review = (
        _scene_field_text(final_scene, "endingTailReview", "tailHoldReview", "endingPacingReview")
        or _scene_field_text(ending, "tailHoldReview", "endingTailReview", "pacingReview")
    )
    verdict = (
        _scene_field_text(final_scene, "endingTailVerdict", "endingVerdict", "abruptEndingVerdict")
        or _scene_field_text(ending, "endingTailVerdict", "endingVerdict", "abruptEndingVerdict")
    )
    resolution_review = (
        _scene_field_text(final_scene, "endingResolutionReview", "finalBeatSyncReview", "lastBeatReview")
        or _scene_field_text(ending, "endingResolutionReview", "finalBeatSyncReview", "lastBeatReview")
    )
    screen_action = (
        _scene_field_text(final_scene, "endingScreenAction", "finalVisualAction", "lastVisualBeat")
        or _scene_field_text(ending, "endingScreenAction", "finalVisualAction", "lastVisualBeat")
    )
    resolution_verdict = (
        _scene_field_text(final_scene, "endingResolutionVerdict", "finalBeatSyncVerdict")
        or _scene_field_text(ending, "endingResolutionVerdict", "finalBeatSyncVerdict")
    )

    missing: list[str] = []
    if tail_hold_sec < ENDING_TAIL_MIN_HOLD_SEC:
        missing.append(f"endingTailHoldSec>={ENDING_TAIL_MIN_HOLD_SEC:.1f}")
    if rendered_tail_sec < ENDING_TAIL_MIN_HOLD_SEC:
        missing.append(f"audioTailHoldSec>={ENDING_TAIL_MIN_HOLD_SEC:.1f}")
    if tail_hold_sec > ENDING_TAIL_MAX_HOLD_SEC:
        missing.append(f"endingTailHoldSec<={ENDING_TAIL_MAX_HOLD_SEC:.1f}")
    if rendered_tail_sec > ENDING_TAIL_MAX_HOLD_SEC:
        missing.append(f"audioTailHoldSec<={ENDING_TAIL_MAX_HOLD_SEC:.1f}")
    if fade_out_sec < ENDING_FADE_OUT_MIN_SEC:
        missing.append(f"endingFadeOutSec>={ENDING_FADE_OUT_MIN_SEC:.1f}")
    if has_narration and voice_target_sec > ENDING_FINAL_VOICE_MAX_SEC:
        missing.append(f"endingVoiceTargetSec<={ENDING_FINAL_VOICE_MAX_SEC:.1f}")
    if has_narration and caption_voice_coverage < ENDING_FINAL_CAPTION_MIN_VOICE_COVERAGE_RATIO:
        missing.append(f"endingCaptionVoiceCoverage>={ENDING_FINAL_CAPTION_MIN_VOICE_COVERAGE_RATIO:.2f}")
    if duration_sec <= tail_hold_sec + 0.5:
        missing.append("finalSceneHasVoiceOrVisualBeforeTail")
    if len(tail_review) < 36:
        missing.append("endingTailReview>=36")
    if _manual_visual_verdict_status(verdict) != "pass":
        missing.append("endingTailVerdict=pass")
    if len(resolution_review) < 40:
        missing.append("endingResolutionReview>=40")
    if len(screen_action) < 18:
        missing.append("endingScreenAction>=18")
    if _manual_visual_verdict_status(resolution_verdict) != "pass":
        missing.append("endingResolutionVerdict=pass")

    status = "pass"
    if required and (not scenes or missing):
        status = "fail"
    return {
        "required": required,
        "status": status,
        "finalSceneId": final_scene_id,
        "tailHoldSec": round(tail_hold_sec, 3),
        "fadeOutSec": round(fade_out_sec, 3),
        "renderedAudioTailHoldSec": round(rendered_tail_sec, 3),
        "durationSec": round(duration_sec, 3),
        "voiceTargetDurationSec": round(voice_target_sec, 3),
        "declaredCaptionDurationSec": round(declared_caption_sec, 3),
        "renderedCaptionDurationSec": round(rendered_caption_sec, 3),
        "captionVoiceCoverage": round(caption_voice_coverage, 3),
        "audioDurationFit": audio_fit,
        "missingFields": missing,
        "tailReview": tail_review,
        "endingResolutionReview": resolution_review,
        "endingScreenAction": screen_action,
        "policy": {
            "tailRule": (
                f"Source-led or upload-facing renders need {ENDING_TAIL_MIN_HOLD_SEC:.1f}-"
                f"{ENDING_TAIL_MAX_HOLD_SEC:.1f}s of final visual/BGM hold after the last spoken idea, "
                "not silent padding."
            ),
            "audioRule": "TTS must not be stretched to fill the entire final scene when an ending tail hold is requested.",
            "fadeRule": f"The final render needs at least {ENDING_FADE_OUT_MIN_SEC:.1f}s of visual/audio fade-out so the MP4 does not hard-cut at the tail.",
            "resolutionRule": (
                f"Final narration should stay <= {ENDING_FINAL_VOICE_MAX_SEC:.1f}s and the rendered payoff "
                f"caption should cover at least {ENDING_FINAL_CAPTION_MIN_VOICE_COVERAGE_RATIO:.0%} of that spoken close; "
                "the last visual, caption, and spoken idea must resolve the same beat instead of adding blank padding."
            ),
        },
    }


def _text_present(value: object) -> bool:
    return bool(str(value or "").strip())


def _visual_asset_for_scene(manifest: dict, scene_id: str) -> dict:
    for asset in manifest.get("assets", []):
        if asset.get("sceneId") == scene_id and asset.get("role") == "visual":
            return asset
    return {}


def _audio_asset_for_scene(manifest: dict, scene_id: str) -> dict:
    for asset in manifest.get("assets", []):
        if asset.get("sceneId") == scene_id and asset.get("role") == "audio":
            if str(asset.get("kind") or "").strip().lower() == "bgm":
                continue
            return asset
    return {}


def _scene_duration_seconds(scene: dict) -> float:
    for key in ("durationSec", "duration_sec"):
        try:
            value = float(scene.get(key) or 0)
            if value > 0:
                return value
        except (TypeError, ValueError):
            pass
    try:
        start = float(scene.get("startSec") if scene.get("startSec") is not None else scene.get("start_sec") or 0)
        end = float(scene.get("endSec") if scene.get("endSec") is not None else scene.get("end_sec") or 0)
        if end > start:
            return end - start
    except (TypeError, ValueError):
        pass
    return _scene_caption_duration(scene)


def _compact_text_length(value: object) -> int:
    return len(re.sub(r"\s+", "", str(value or "")))


def _production_meta_terms(value: object) -> list[str]:
    """Detect production notes that should not be spoken to viewers."""
    lowered = str(value or "").strip().lower()
    if not lowered:
        return []
    compact = re.sub(r"\s+", "", lowered)
    hits: list[str] = []
    for term in PRODUCTION_META_HARD_TERMS:
        if term in lowered:
            hits.append(term)
    for term in PRODUCTION_META_VIEWER_INTENT_PHRASES:
        if term in compact and term not in hits:
            hits.append(term)
    soft_hits = [term for term in PRODUCTION_META_SOFT_TERMS if term in lowered]
    if hits or len(set(soft_hits)) >= 2:
        hits.extend(term for term in soft_hits if term not in hits)
    return hits


def _scene_caption_duration(scene: dict) -> float:
    for key in ("captionDisplayDurationSec", "captionDurationSec", "caption_display_duration_sec", "caption_duration_sec"):
        try:
            value = float(scene.get(key) or 0)
            if value > 0:
                return value
        except (TypeError, ValueError):
            pass
    for key in ("durationSec", "duration_sec"):
        try:
            value = float(scene.get(key) or 0)
            if value > 0:
                return value
        except (TypeError, ValueError):
            pass
    try:
        start = float(scene.get("startSec") if scene.get("startSec") is not None else scene.get("start_sec") or 0)
        end = float(scene.get("endSec") if scene.get("endSec") is not None else scene.get("end_sec") or 0)
        return max(0.0, end - start)
    except (TypeError, ValueError):
        return 0.0


def _caption_layout_reviewed(caption_preset: str, quality_review_note: str) -> bool:
    if caption_preset == "none":
        return True
    lowered = quality_review_note.lower()
    return bool(quality_review_note) and any(term in lowered for term in CAPTION_LAYOUT_TERMS)


def _caption_density_issue(caption_preset: str, subtitle_text: str, duration_sec: float = 0.0) -> str:
    """Return a publish-blocking reason when burned-in Shorts text is too dense."""
    preset = str(caption_preset or "").strip()
    if preset == "none" or not subtitle_text.strip():
        return ""
    visible_lines = [
        line.strip()
        for line in re.split(r"(?:\\N|\r?\n)+", subtitle_text)
        if line.strip()
    ]
    if len(visible_lines) > 2:
        return f"{preset} caption has too many lines ({len(visible_lines)}/2)"
    korean_count = sum(1 for char in subtitle_text if "\uac00" <= char <= "\ud7a3" or "\u3131" <= char <= "\u318e")
    compact_length = _compact_text_length(subtitle_text)
    if korean_count > len(subtitle_text) * 0.3:
        max_compact = SHORTS_CAPTION_MAX_COMPACT_CHARS.get(preset)
        if max_compact and compact_length > max_compact:
            return f"{preset} caption is too dense ({compact_length}/{max_compact} compact chars)"
    else:
        word_count = len(re.findall(r"[A-Za-z0-9']+", subtitle_text))
        max_words = {"top-hook": 9, "center-short": 8, "lower-info": 12}.get(preset)
        if max_words and word_count > max_words:
            return f"{preset} caption is too dense ({word_count}/{max_words} words)"
    if duration_sec > 0:
        min_seconds_per_char = SHORTS_CAPTION_MIN_SECONDS_BY_COMPACT_CHAR.get(preset)
        if min_seconds_per_char:
            required_duration = compact_length * min_seconds_per_char
            if required_duration > duration_sec + SHORTS_CAPTION_READING_SLACK_SEC:
                return (
                    f"{preset} caption reads too fast "
                    f"({compact_length} compact chars in {duration_sec:.1f}s; needs {required_duration:.1f}s)"
                )
    return ""


def _reference_edit_grammar_terms(*values: object) -> list[str]:
    """Extract concrete short-form reference grammar terms from review notes."""
    text = " ".join(str(value or "") for value in values).strip().lower()
    if not text:
        return []
    compact = re.sub(r"[\s_]+", "", text)
    hits: list[str] = []
    for term in REFERENCE_EDIT_GRAMMAR_TERMS:
        term_lower = term.lower()
        normalized = re.sub(r"[\s_]+", "", term_lower)
        if term_lower in text or (normalized and normalized in compact):
            hits.append(term)
    return sorted(set(hits))


def _manual_visual_verdict_status(value: object) -> str:
    """Require a controlled operator verdict; free-text notes are not enough."""
    raw = str(value or "").strip().lower()
    if not raw:
        return "missing"
    normalized = re.sub(r"[\s_]+", "-", raw)
    if normalized in VISUAL_VERDICT_PASS_VALUES:
        return "pass"
    if normalized in VISUAL_VERDICT_FAIL_VALUES or normalized.startswith("needs-"):
        return "fail"
    return "missing"


def _is_specific_source_url(value: str) -> bool:
    lowered = value.strip().lower()
    if not lowered:
        return False
    if lowered.startswith(("local-cache-", "local-cache-from-", "uploaded-", "manual-upload")):
        return False
    return bool(re.match(r"^[a-z][a-z0-9+.-]*://", lowered) or lowered.startswith("www."))


def _visual_asset_identity(asset: dict) -> str:
    provider = str(asset.get("provider") or "visual")
    source_external_id = str(asset.get("sourceExternalId") or "").strip()
    if source_external_id:
        return f"{provider}:external:{source_external_id}"

    source_url = str(asset.get("sourceUrl") or "").strip()
    if source_url and _is_specific_source_url(source_url):
        return f"{provider}:url:{source_url}"

    for key in ("sourcePath", "outputPath", "sourceLabel"):
        value = str(asset.get(key) or "").strip()
        if value:
            return f"{provider}:{key}:{value}"

    if source_url:
        return f"{provider}:source:{source_url}"
    prompt = str(asset.get("prompt") or "").strip()
    return f"{provider}:prompt:{prompt}" if prompt else ""


def _asset_has_license_provenance(asset: dict, *, require_license_note: bool = False) -> bool:
    source_present = any(
        str(asset.get(key) or "").strip()
        for key in ("sourceUrl", "sourceExternalId", "sourceLabel", "sourcePath", "outputPath")
    )
    license_present = any(
        str(asset.get(key) or "").strip()
        for key in ("sourceLicense", "license", "licenseUrl", "attribution", "sourceAttribution")
    )
    return source_present and (license_present if require_license_note else True)


def _asset_evidence_label(asset: dict) -> str:
    scene_id = str(asset.get("sceneId") or "global")
    provider = str(asset.get("provider") or "unknown")
    kind = str(asset.get("kind") or asset.get("role") or "asset")
    label = str(asset.get("sourceLabel") or asset.get("sourcePath") or asset.get("outputPath") or "").strip()
    return f"{scene_id}:{provider}:{kind}:{label}" if label else f"{scene_id}:{provider}:{kind}"


def _bgm_asset_quality_risk_reason(asset: dict) -> str:
    values = []
    for key in (
        "sourcePath",
        "sourceLabel",
        "sourceUrl",
        "sourceOrigin",
        "sourceProvider",
        "sourceLicense",
        "license",
        "attribution",
        "sourceAttribution",
        "prompt",
    ):
        value = asset.get(key)
        if value not in (None, ""):
            values.append(str(value))
    return _bgm_quality_risk_reason_from_text(" ".join(values))


def _truthy_metadata(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "on", "required"}


def _compact_credit_part(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())


def _positive_int_metadata(value: object) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return 0
    return parsed if parsed > 0 else 0


def _build_free_audio_credit(asset: dict) -> dict | None:
    role = str(asset.get("role") or "")
    provider = str(asset.get("provider") or "")
    kind = str(asset.get("kind") or role or "")
    if role not in {"audio", "sfx"} or provider not in FREE_AUDIO_STOCK_PROVIDERS:
        return None
    if provider in FREE_NARRATION_PROVIDERS or kind in {"voiceover", "native"}:
        return None

    source_provider = _compact_credit_part(asset.get("sourceProvider") or provider)
    title = _compact_credit_part(
        asset.get("sourceLabel")
        or asset.get("title")
        or asset.get("sourcePath")
        or asset.get("outputPath")
    )
    creator = _compact_credit_part(asset.get("artist") or asset.get("creator") or source_provider)
    source_url = _compact_credit_part(asset.get("sourceUrl"))
    license_label = _compact_credit_part(asset.get("sourceLicense") or asset.get("license") or asset.get("licenseUrl"))
    license_url = _compact_credit_part(asset.get("licenseUrl"))
    attribution = _compact_credit_part(asset.get("attribution") or asset.get("sourceAttribution"))
    attribution_required = _truthy_metadata(asset.get("attributionRequired"))

    missing_fields: list[str] = []
    if not title:
        missing_fields.append("title")
    if not source_url:
        missing_fields.append("sourceUrl")
    if not license_label:
        missing_fields.append("license")
    if attribution_required and not attribution:
        missing_fields.append("attribution")

    if attribution:
        description_line = attribution
    else:
        credit_source = creator or source_provider or provider
        description_line = f"{title} - {credit_source}".strip(" -")
        if license_label:
            description_line = f"{description_line} ({license_label})" if description_line else license_label
    if source_url:
        description_line = f"{description_line} Source: {source_url}".strip()
    if license_url and license_url != source_url and license_url not in description_line:
        description_line = f"{description_line} License: {license_url}".strip()

    return {
        "assetId": asset.get("id") or "",
        "sceneId": asset.get("sceneId") or "global",
        "role": role,
        "kind": kind,
        "provider": provider,
        "sourceProvider": source_provider,
        "title": title,
        "creator": creator,
        "sourceUrl": source_url,
        "sourceLicense": license_label,
        "licenseUrl": license_url,
        "attributionRequired": attribution_required,
        "attribution": attribution,
        "youtubeDescriptionLine": description_line,
        "missingFields": missing_fields,
        "evidenceLabel": _asset_evidence_label(asset),
    }


def _normalized_source_tag(value: object) -> str:
    return str(value or "").strip().lower().replace("_", "-")


def _uploaded_video_originality_status(scene: dict, visual_asset: dict, source_intent: str) -> tuple[bool, str]:
    """Decide whether an uploaded MP4 can count as channel-owned original footage.

    A local file path only proves that the operator imported a clip. It does not
    prove the clip was shot, owned, generated, or handed off from Grok/local AI.
    """
    provider = _normalized_source_tag(visual_asset.get("provider"))
    intent = _normalized_source_tag(source_intent)
    generator = _normalized_source_tag(visual_asset.get("sourceGenerator"))
    if provider == "upload" and intent == "grok":
        return True, "grok-handoff"
    if provider in LOCAL_ORIGINAL_VIDEO_INTENTS or intent in LOCAL_ORIGINAL_VIDEO_INTENTS or generator in LOCAL_ORIGINAL_VIDEO_INTENTS:
        return True, "local-model"

    proof_text = " ".join(
        str(value or "")
        for value in (
            scene.get("originalityEvidence"),
            scene.get("sourceRationale"),
            scene.get("continuityNote"),
            visual_asset.get("sourceOwnership"),
            visual_asset.get("sourceLabel"),
            visual_asset.get("sourceLicense"),
            visual_asset.get("sourceProvider"),
            visual_asset.get("sourceUrl"),
            visual_asset.get("sourcePath"),
            visual_asset.get("sourceGenerator"),
            visual_asset.get("sourceGeneratorCommand"),
        )
    ).lower()
    if any(term in proof_text for term in PROCEDURAL_PLACEHOLDER_EVIDENCE_TERMS):
        return False, "procedural-placeholder"
    if any(term in proof_text for term in STOCK_REWRAPPED_UPLOAD_EVIDENCE_TERMS):
        return False, "stock-rewrapped-upload"
    if any(term in proof_text for term in OWNED_UPLOAD_EVIDENCE_TERMS):
        return True, "owned-upload-proof"
    return False, "needs-owned-source-proof"


def _is_grok_handoff_visual(provider: str, source_origin: str, source_intent: str, visual_asset: dict) -> bool:
    generator = _normalized_source_tag(visual_asset.get("sourceGenerator"))
    source_path = str(visual_asset.get("sourcePath") or "").strip().lower().replace("\\", "/")
    return (
        provider == "upload"
        and (
            source_intent == "grok"
            or source_origin == "grok-handoff"
            or generator == "grok-app-web-handoff"
            or "storage/grok-handoffs/" in source_path
        )
    )


def _is_gemini_handoff_visual(provider: str, source_origin: str, source_intent: str, visual_asset: dict) -> bool:
    generator = _normalized_source_tag(visual_asset.get("sourceGenerator"))
    source_path = str(visual_asset.get("sourcePath") or "").strip().lower().replace("\\", "/")
    return (
        provider in {"upload", *GEMINI_VIDEO_SOURCE_TAGS}
        and (
            source_intent in GEMINI_VIDEO_SOURCE_TAGS
            or source_origin in GEMINI_VIDEO_SOURCE_TAGS
            or generator in GEMINI_VIDEO_SOURCE_TAGS
            or "storage/gemini-handoffs/" in source_path
            or "browser-handoffs/gemini" in source_path
        )
    )


def _source_first_required(manifest: dict) -> bool:
    if any(_truthy_metadata(manifest.get(flag)) for flag in SOURCE_FIRST_REQUIRED_FLAGS):
        return True
    if str(manifest.get("referenceProfilePath") or manifest.get("reference_profile_path") or "").strip():
        return True
    project_id = str(manifest.get("projectId") or manifest.get("project_id") or "").strip().lower()
    render_purpose = str(manifest.get("renderPurpose") or manifest.get("render_purpose") or "").strip().lower()
    return project_id.startswith("reference-") or "source-first" in render_purpose or "reference-profile" in render_purpose


def _local_generated_video_source_ready(provider: str, source_intent: str, visual_asset: dict) -> bool:
    generator = _normalized_source_tag(visual_asset.get("sourceGenerator"))
    if provider not in LOCAL_ORIGINAL_VIDEO_INTENTS and source_intent not in LOCAL_ORIGINAL_VIDEO_INTENTS and generator not in LOCAL_ORIGINAL_VIDEO_INTENTS:
        return False
    return all(
        str(visual_asset.get(key) or "").strip()
        for key in (
            "sourceGenerator",
            "sourceGeneratorRequestPath",
            "sourceGeneratorPromptPath",
            "sourceGeneratorLogPath",
        )
    )


def _internet_source_proof_mode(manifest: dict) -> bool:
    if _truthy_metadata(manifest.get("internetSourceProofMode")):
        return True
    if _truthy_metadata(manifest.get("internetSourceAcquisitionRequired")):
        return True
    project_id = str(manifest.get("projectId") or manifest.get("project_id") or "").lower()
    render_purpose = str(manifest.get("renderPurpose") or manifest.get("render_purpose") or "").lower()
    return any(term in f"{project_id} {render_purpose}" for term in ("internet-meme", "meme-gif", "internet-gif", "web-gif"))


def _internet_source_acquisition_required(manifest: dict) -> bool:
    if _truthy_metadata(manifest.get("internetSourceAcquisitionRequired")):
        return True
    return _internet_source_proof_mode(manifest)


def _source_acquisition_payload(scene: dict, visual_asset: dict) -> dict:
    payload: dict = {}
    for container in (visual_asset.get("sourceFetch"), visual_asset.get("sourceAcquisition"), scene.get("sourceFetch"), scene.get("sourceAcquisition")):
        if isinstance(container, dict):
            payload.update(container)
    return payload


def _source_context_payload(scene: dict, visual_asset: dict) -> dict:
    payload: dict = {}
    for container in (visual_asset.get("sourceContext"), scene.get("sourceContext")):
        if isinstance(container, dict):
            payload.update(container)
    return payload


def _source_acquisition_value(scene: dict, visual_asset: dict, *keys: str) -> str:
    payload = _source_acquisition_payload(scene, visual_asset)
    for key in keys:
        for container in (payload, visual_asset, scene):
            if isinstance(container, dict):
                value = str(container.get(key) or "").strip()
                if value:
                    return value
    return ""


def _source_context_value(scene: dict, visual_asset: dict, *keys: str) -> str:
    payload = _source_context_payload(scene, visual_asset)
    for key in keys:
        for container in (payload, visual_asset, scene):
            if isinstance(container, dict):
                value = str(container.get(key) or "").strip()
                if value:
                    return value
    return ""


def _source_acquisition_int(scene: dict, visual_asset: dict, *keys: str) -> int:
    raw = _source_acquisition_value(scene, visual_asset, *keys)
    try:
        number = int(raw or 0)
    except (TypeError, ValueError):
        return 0
    return number if number > 0 else 0


def _is_internet_source_candidate(scene: dict, visual_asset: dict) -> bool:
    payload = _source_acquisition_payload(scene, visual_asset)
    text = " ".join(
        str(value or "")
        for value in (
            scene.get("visualSourceIntent"),
            scene.get("sourceOrigin"),
            scene.get("sourceType"),
            scene.get("sourceUrl"),
            scene.get("sourcePath"),
            visual_asset.get("provider"),
            visual_asset.get("sourceOrigin"),
            visual_asset.get("sourceType"),
            visual_asset.get("sourceUrl"),
            visual_asset.get("sourcePath"),
            payload.get("sourceUrl"),
            payload.get("localPath"),
            payload.get("mediaKind"),
        )
    ).strip().lower().replace("_", "-")
    return bool(payload) or any(tag in text for tag in INTERNET_SOURCE_TAGS)


def _internet_source_acquisition_scene_status(scene: dict, visual_asset: dict) -> tuple[bool, list[str], dict]:
    source_url = _source_acquisition_value(scene, visual_asset, "sourceUrl", "downloadUrl", "assetUrl", "url")
    local_path = _source_acquisition_value(scene, visual_asset, "sourceLocalPath", "localPath", "fetchedPath", "sourcePath")
    sha256 = _source_acquisition_value(scene, visual_asset, "sourceSha256", "sha256")
    size_bytes = _source_acquisition_int(scene, visual_asset, "sourceBytes", "sizeBytes", "bytes")
    content_type = _source_acquisition_value(scene, visual_asset, "contentType", "sourceContentType")
    media_kind = _normalized_source_tag(_source_acquisition_value(scene, visual_asset, "sourceMediaKind", "mediaKind"))
    fetch_status = _normalized_source_tag(_source_acquisition_value(scene, visual_asset, "sourceFetchStatus", "fetchStatus", "status"))
    verdict = _normalized_source_tag(
        _source_acquisition_value(scene, visual_asset, "sourceAcquisitionVerdict", "sourceFetchVerdict", "verdict")
    )
    review = _source_acquisition_value(scene, visual_asset, "sourceAcquisitionReview", "sourceFetchReview", "review")
    visual_kind = str(scene.get("visualKind") or visual_asset.get("kind") or "").strip()
    missing: list[str] = []
    if not source_url:
        missing.append("sourceUrl")
    if not local_path:
        missing.append("localPath")
    if len(sha256) < 12:
        missing.append("sha256")
    if size_bytes <= 0:
        missing.append("sizeBytes")
    if media_kind not in INTERNET_SOURCE_MEDIA_KINDS:
        missing.append("mediaKind")
    if visual_kind == "video" and media_kind not in {"gif", "video"}:
        missing.append("motionMediaKind=gif/video")
    if fetch_status not in INTERNET_SOURCE_FETCH_PASS_STATUSES:
        missing.append("sourceFetchStatus=fetched")
    if verdict not in {"pass", "approved", "ready", "ok"}:
        missing.append("sourceAcquisitionVerdict=pass")
    if len(review) < 32:
        missing.append("sourceAcquisitionReview>=32")
    detail = {
        "sourceUrl": source_url,
        "localPath": local_path,
        "sha256": sha256,
        "sizeBytes": size_bytes,
        "contentType": content_type,
        "mediaKind": media_kind,
        "fetchStatus": fetch_status,
        "verdict": verdict,
        "reviewReady": len(review) >= 32,
        "motionReady": visual_kind == "video" and media_kind in {"gif", "video"},
    }
    return not missing, missing, detail


def _internet_source_context_required(manifest: dict) -> bool:
    return (
        _internet_source_acquisition_required(manifest)
        or _truthy_metadata(manifest.get("internetSourceContextRequired"))
        or _truthy_metadata(manifest.get("sourceTypeMixRequired"))
    )


def _internet_source_context_scene_status(manifest: dict, scene: dict, visual_asset: dict) -> tuple[bool, list[str], dict]:
    acquisition_ready, _acquisition_missing, acquisition_detail = _internet_source_acquisition_scene_status(scene, visual_asset)
    manifest_topic = str(
        manifest.get("topic")
        or manifest.get("sourceTopic")
        or manifest.get("storyPremise")
        or manifest.get("prompt")
        or manifest.get("title")
        or ""
    ).strip()
    topic = _source_context_value(scene, visual_asset, "topic", "sourceTopic", "projectTopic") or manifest_topic
    scene_purpose = _source_context_value(scene, visual_asset, "scenePurpose", "storyBeat", "beatPurpose", "captionPurpose")
    viewer_job = _source_context_value(scene, visual_asset, "viewerJob", "sourceJob", "visualJob")
    selection_rationale = _source_context_value(
        scene,
        visual_asset,
        "selectionRationale",
        "sourceRationale",
        "contextRationale",
    ) or str(scene.get("sourceRationale") or "").strip()
    media_choice = _source_context_value(
        scene,
        visual_asset,
        "mediaChoiceRationale",
        "whyGifOrImage",
        "sourceTypeDecision",
    )
    motion_fit = _source_context_value(scene, visual_asset, "motionFit", "whyMotionFits")
    still_fit = _source_context_value(scene, visual_asset, "stillFit", "whyStillImageFits")
    verdict = _source_context_value(
        scene,
        visual_asset,
        "verdict",
        "sourceContextVerdict",
        "sourceFitVerdict",
        "contextFitVerdict",
    )
    verdict_status = _manual_visual_verdict_status(verdict)
    media_kind = str(acquisition_detail.get("mediaKind") or "").strip()
    visual_kind = str(scene.get("visualKind") or visual_asset.get("kind") or "").strip()
    missing: list[str] = []
    if not acquisition_ready:
        missing.append("sourceAcquisitionReady")
    if len(topic) < 8:
        missing.append("topic>=8")
    if len(scene_purpose) < 12:
        missing.append("scenePurpose>=12")
    if len(viewer_job) < 16:
        missing.append("viewerJob>=16")
    if len(selection_rationale) < 40:
        missing.append("selectionRationale>=40")
    if len(media_choice) < 32:
        missing.append("mediaChoiceRationale>=32")
    if media_kind in {"gif", "video"} and len(motion_fit) < 24:
        missing.append("motionFit>=24")
    if media_kind == "image" and len(still_fit) < 24:
        missing.append("stillFit>=24")
    if visual_kind == "image" and media_kind in {"gif", "video"}:
        missing.append("visualKind/mediaKind mismatch")
    if visual_kind == "video" and media_kind == "image":
        missing.append("visualKind/mediaKind mismatch")
    if verdict_status != "pass":
        missing.append("sourceContextVerdict=pass")
    detail = {
        "topic": topic,
        "scenePurpose": scene_purpose,
        "viewerJob": viewer_job,
        "selectionRationaleReady": len(selection_rationale) >= 40,
        "mediaChoiceRationaleReady": len(media_choice) >= 32,
        "motionFitReady": len(motion_fit) >= 24,
        "stillFitReady": len(still_fit) >= 24,
        "mediaKind": media_kind,
        "visualKind": visual_kind,
        "verdictStatus": verdict_status,
        "acquisitionReady": acquisition_ready,
    }
    return not missing, missing, detail


def _internet_context_source_ready(manifest: dict, scene: dict, visual_asset: dict, visual_kind: str) -> bool:
    if visual_kind not in {"image", "video"} or not _is_internet_source_candidate(scene, visual_asset):
        return False
    ready, _missing, detail = _internet_source_context_scene_status(manifest, scene, visual_asset)
    visual_verdict = _manual_visual_verdict_status(
        scene.get("visualQualityVerdict")
        or scene.get("manualVisualVerdict")
        or scene.get("sourceFitVerdict")
    )
    return ready and visual_verdict == "pass" and detail.get("mediaKind") in INTERNET_SOURCE_MEDIA_KINDS


def _internet_motion_source_ready(scene: dict, visual_asset: dict, visual_kind: str) -> bool:
    if visual_kind != "video" or not _is_internet_source_candidate(scene, visual_asset):
        return False
    ready, _missing, detail = _internet_source_acquisition_scene_status(scene, visual_asset)
    visual_verdict = _manual_visual_verdict_status(
        scene.get("visualQualityVerdict")
        or scene.get("manualVisualVerdict")
        or scene.get("sourceFitVerdict")
    )
    return ready and detail.get("motionReady") is True and visual_verdict == "pass"


def _source_provenance_confirmation_required(source_provenance: dict) -> bool:
    status = str(source_provenance.get("status") or "").strip()
    return status in GROK_SOURCE_CONFIRMATION_REQUIRED_STATUSES


def _has_grok_preview_caveat(*values: object) -> bool:
    text = " ".join(str(value or "") for value in values).lower()
    return any(term in text for term in GROK_PREVIEW_CAVEAT_TERMS)


def _source_review_verdict_value(*containers: object) -> str:
    verdict_keys = (
        "sourceReviewVerdict",
        "sourceFitVerdict",
        "manualSourceFitVerdict",
        "operatorSourceReviewVerdict",
        "grokSourceReviewVerdict",
        "localCandidateReviewVerdict",
        "sourceRecoveryReviewVerdict",
        "reviewDecision",
        "reviewVerdict",
        "operatorReviewStatus",
        "sourceReviewStatus",
    )
    accepted_keys = (
        "accepted",
        "sourceAccepted",
        "sourceReviewAccepted",
        "operatorAccepted",
    )
    for container in containers:
        if not isinstance(container, dict):
            continue
        for key in verdict_keys:
            value = str(container.get(key) or "").strip()
            if value:
                return value
        for key in accepted_keys:
            if key in container and container.get(key) is False:
                return "rejected"
    return ""


def _build_template_source_review(production_review: dict) -> dict:
    summary = production_review.get("summary") or {}
    template = str(summary.get("contentTemplate") or "").strip()
    guide = TEMPLATE_SOURCE_GUIDES.get(template)
    layout_counts = summary.get("layoutVariantCounts") if isinstance(summary.get("layoutVariantCounts"), dict) else {}
    primary_layout_variant = ""
    if layout_counts:
        primary_layout_variant = sorted(
            ((str(key), int(value or 0)) for key, value in layout_counts.items()),
            key=lambda item: item[1],
            reverse=True,
        )[0][0]
    operating_template = operating_template_for(template, primary_layout_variant)
    total_scenes = int(summary.get("totalScenes", 0) or 0)
    uploaded = int(summary.get("uploadedVideoScenes", 0) or 0)
    grok = int(summary.get("grokHandoffScenes", 0) or 0)
    local_model = int(summary.get("localModelVideoScenes", 0) or 0)
    stock = int(summary.get("stockVideoScenes", 0) or 0)
    image_fallback = int(summary.get("imageFallbackScenes", 0) or 0)
    image_fallback_scene_ids = [str(item) for item in summary.get("imageFallbackSceneIds") or []]
    internet_context_source_scene_ids = [str(item) for item in summary.get("internetContextSourceSceneIds") or []]
    blocking_image_fallback_scene_ids = [
        scene_id
        for scene_id in image_fallback_scene_ids
        if scene_id not in internet_context_source_scene_ids
    ]
    repeated = summary.get("repeatedVisualAssetScenes") or []
    missing_visual_provenance = summary.get("missingFreeAssetProvenanceScenes") or []
    missing_audio_provenance = summary.get("missingFreeAudioProvenanceAssets") or []
    missing_rationale = summary.get("missingRationaleScenes") or []
    missing_continuity = summary.get("missingContinuityScenes") or []
    layout_variant_scenes = summary.get("layoutVariantScenes") or []
    missing_layout_variant_scenes = summary.get("missingLayoutVariantScenes") or []
    caption_preset_counts = summary.get("captionPresetCounts") or {}
    production_meta_narration = summary.get("productionMetaNarrationScenes") or []
    production_meta_subtitles = summary.get("productionMetaSubtitleScenes") or []
    caption_sparse_plan = bool(summary.get("captionSparsePlan"))
    long_top_hook_scenes = summary.get("longTopHookScenes") or []
    first_hook_ready = summary.get("firstSceneHookReady") is True

    required_fixes: list[str] = []
    recommended_fixes: list[str] = []

    if not template:
        recommended_fixes.append("Choose a content template so source and layout expectations are explicit.")
    if repeated:
        required_fixes.append(f"Replace repeated visual assets: {repeated}.")
    if missing_visual_provenance or missing_audio_provenance:
        recommended_fixes.append(
            "Record free visual/audio source URL, ID, creator, license, and attribution evidence."
        )
    if blocking_image_fallback_scene_ids:
        recommended_fixes.append(
            f"Replace or context-approve still-image fallback scene(s): {blocking_image_fallback_scene_ids}."
        )
    if missing_rationale:
        recommended_fixes.append(f"Add source-selection rationale for scenes: {missing_rationale}.")
    if missing_continuity:
        recommended_fixes.append(f"Add color/subject/camera continuity notes for scenes: {missing_continuity}.")
    if missing_layout_variant_scenes:
        required_fixes.append(
            f"Select a visible template layout variant for scenes: {missing_layout_variant_scenes}."
        )
    if production_meta_narration or production_meta_subtitles:
        required_fixes.append(
            f"Rewrite production-meta viewer text: narration={production_meta_narration}, subtitles={production_meta_subtitles}."
        )
    if caption_sparse_plan:
        required_fixes.append(
            "Add a real caption layout plan; one long hook plus mostly no-caption scenes reads unfinished."
        )
    if long_top_hook_scenes:
        required_fixes.append(f"Shorten top-hook captions to the first two seconds: {long_top_hook_scenes}.")
    if total_scenes >= 4 and not layout_variant_scenes and len(caption_preset_counts) <= 1:
        required_fixes.append(
            "Multi-scene Korean templates need layout variation evidence; one repeated caption/layout pattern reads as templated filler."
        )
    if not first_hook_ready:
        recommended_fixes.append("Add a visible first-two-second hook note or top-hook treatment.")

    if template == "authentic_vlog" and uploaded + grok + local_model == 0:
        recommended_fixes.append(
            "This template should be led by direct operator footage or reviewed Grok/local handoff MP4; stock clips should only support the owned footage."
        )
    if template == "tutorial_steps" and uploaded == 0:
        recommended_fixes.append(
            "Tutorial templates should be led by direct screen or hand footage; stock clips should only support the owned footage."
        )
    if template == "persona_story" and grok + local_model == 0:
        recommended_fixes.append(
            "Persona/story templates need Grok app/web or local Wan/LTX/Hunyuan hero MP4 evidence to avoid slideshow output."
        )
    if template == "kculture_fandom" and uploaded + grok + local_model == 0:
        recommended_fixes.append(
            "Use copyright-safe direct/generated substitute footage; do not build the whole edit from generic stock."
        )
    if template == "podcast_clip" and uploaded == 0:
        recommended_fixes.append(
            "Podcast/long-form clips should use an owned source clip or explicitly document the TTS-summary fallback."
        )
    if template == "longform_deep_dive" and missing_rationale:
        recommended_fixes.append(
            "Long-form deep dives need source/data-card rationale per chapter so stock clips do not become generic filler."
        )
    if template == "interview_documentary" and uploaded == 0:
        recommended_fixes.append(
            "Interview/documentary templates should use owned interview/location footage or document the free TTS-summary fallback."
        )
    if template == "live_recap" and uploaded == 0:
        recommended_fixes.append(
            "Live/event recaps should be led by direct event footage; stock venue/city clips are support, not the whole edit."
        )
    if template == "ranking_list" and stock > 0 and missing_rationale:
        recommended_fixes.append("Each rank needs a distinct manually chosen source with candidate evidence.")
    if template == "news_explainer" and stock == total_scenes and not summary.get("curatedStockReady"):
        recommended_fixes.append("Stock-only explainers need complete curation proof before publish review.")

    if required_fixes:
        status = "fail"
    elif recommended_fixes:
        status = "warn"
    else:
        status = "pass"

    return {
        "status": status,
        "template": template,
        "family": (guide or {}).get("family") or template or "unspecified",
        "sourceMix": (guide or {}).get("sourceMix") or "no template-specific source mix registered",
        "freeAssetPlan": (guide or {}).get("freeAssetPlan") or "record source/license evidence for every free asset",
        "operatingTemplateKey": operating_template.get("key"),
        "operatingTemplate": operating_template,
        "counts": {
            "totalScenes": total_scenes,
            "uploadedVideoScenes": uploaded,
            "grokHandoffScenes": grok,
            "localModelVideoScenes": local_model,
            "stockVideoScenes": stock,
            "imageFallbackScenes": image_fallback,
            "layoutVariantScenes": len(layout_variant_scenes),
            "missingLayoutVariantScenes": len(missing_layout_variant_scenes),
            "productionMetaNarrationScenes": len(production_meta_narration),
            "captionSparsePlan": caption_sparse_plan,
            "longTopHookScenes": len(long_top_hook_scenes),
        },
        "requiredFixes": required_fixes,
        "recommendedFixes": recommended_fixes,
    }


def _build_production_review(manifest: dict, local_media: list[dict]) -> dict:
    """Summarize operator curation evidence and publish-readiness caveats."""
    local_media_by_scene = {
        str(item.get("sceneId")): item
        for item in local_media
        if item.get("sceneId")
    }
    scenes_payload: list[dict] = []
    missing_rationale: list[str] = []
    missing_continuity: list[str] = []
    missing_originality_evidence: list[str] = []
    missing_quality_review: list[str] = []
    originality_evidence_scenes: list[str] = []
    quality_review_scenes: list[str] = []
    stock_video_scenes = 0
    uploaded_video_scenes = 0
    grok_handoff_scenes = 0
    gemini_handoff_scenes = 0
    local_model_video_scenes = 0
    internet_motion_source_scenes = 0
    internet_context_source_scenes = 0
    image_fallback_scenes = 0
    video_scenes = 0
    stock_video_scene_ids: list[str] = []
    uploaded_video_scene_ids: list[str] = []
    grok_handoff_scene_ids: list[str] = []
    gemini_handoff_scene_ids: list[str] = []
    local_model_video_scene_ids: list[str] = []
    internet_motion_source_scene_ids: list[str] = []
    internet_context_source_scene_ids: list[str] = []
    source_first_generated_scene_ids: list[str] = []
    source_first_internet_source_scene_ids: list[str] = []
    source_first_internet_context_scene_ids: list[str] = []
    source_first_blocked_scene_ids: list[str] = []
    source_first_block_reasons_by_scene: dict[str, str] = {}
    original_clip_scene_ids: list[str] = []
    weak_uploaded_originality_scenes: list[str] = []
    procedural_placeholder_scenes: list[str] = []
    image_fallback_scene_ids: list[str] = []
    thumbnail_review_scenes: list[str] = []
    audio_mix_review_scenes: list[str] = []
    platform_comparison_scenes: list[str] = []
    visual_verdict_scenes: list[str] = []
    missing_visual_verdict_scenes: list[str] = []
    failed_visual_verdict_scenes: list[str] = []
    stock_ai_clip_fit_verdict_scenes: list[str] = []
    missing_stock_ai_clip_fit_verdict_scenes: list[str] = []
    failed_stock_ai_clip_fit_verdict_scenes: list[str] = []
    layout_variant_scenes: list[str] = []
    missing_layout_variant_scenes: list[str] = []
    narration_scenes: list[str] = []
    subtitle_only_narration_scenes: list[str] = []
    missing_narration_scenes: list[str] = []
    thin_narration_scenes: list[str] = []
    short_voiceover_callout_scenes: list[str] = []
    final_payoff_short_narration_scenes: list[str] = []
    production_meta_narration_scenes: list[str] = []
    production_meta_subtitle_scenes: list[str] = []
    production_meta_terms_by_scene: dict[str, list[str]] = {}
    narration_min_chars_by_scene: dict[str, int] = {}
    no_voice_audio_design_scenes: list[str] = []
    voiceover_required_no_voice_scenes: list[str] = []
    visual_led_no_voice_approved_scenes: list[str] = []
    missing_no_voice_audio_scenes: list[str] = []
    missing_no_voice_audio_review_scenes: list[str] = []
    audio_design_modes_by_scene: dict[str, str] = {}
    captioned_scene_ids: list[str] = []
    long_top_hook_scenes: list[str] = []
    caption_density_issue_scenes: list[str] = []
    caption_density_issues_by_scene: dict[str, str] = {}
    caption_layout_review_scenes: list[str] = []
    missing_caption_layout_review_scenes: list[str] = []
    scene_duration_by_id: dict[str, float] = {}
    long_hold_scene_ids: list[str] = []
    short_form_reference_scenes: list[str] = []
    missing_reference_edit_grammar_scenes: list[str] = []
    reference_edit_terms_by_scene: dict[str, list[str]] = {}
    repeated_visual_asset_scenes: list[str] = []
    free_asset_provenance_scenes: list[str] = []
    missing_free_asset_provenance_scenes: list[str] = []
    free_audio_provenance_assets: list[str] = []
    missing_free_audio_provenance_assets: list[str] = []
    free_audio_credits: list[dict] = []
    free_audio_credit_missing_assets: list[str] = []
    bgm_selection_assets: list[str] = []
    weak_bgm_selection_assets: list[str] = []
    placeholder_bgm_assets: list[str] = []
    placeholder_bgm_asset_reasons: dict[str, str] = {}
    stock_candidate_curation_scenes: list[str] = []
    stock_candidate_curation_ready_scenes: list[str] = []
    missing_stock_candidate_curation_scenes: list[str] = []
    missing_stock_candidate_count_scenes: list[str] = []
    missing_stock_candidate_creator_scenes: list[str] = []
    missing_stock_candidate_source_scenes: list[str] = []
    missing_stock_selection_summary_scenes: list[str] = []
    stock_candidate_curation_issues_by_scene: dict[str, list[str]] = {}
    grok_source_curation_scenes: list[str] = []
    grok_source_curation_ready_scenes: list[str] = []
    missing_grok_source_curation_scenes: list[str] = []
    missing_grok_candidate_comparison_scenes: list[str] = []
    missing_grok_selected_file_scenes: list[str] = []
    missing_grok_source_provenance_scenes: list[str] = []
    unacceptable_grok_source_provenance_scenes: list[str] = []
    missing_grok_source_confirmation_scenes: list[str] = []
    grok_source_review_verdict_scenes: list[str] = []
    rejected_grok_source_review_scenes: list[str] = []
    grok_preview_caveat_scenes: list[str] = []
    visual_identity_first_seen: dict[str, str] = {}
    approved_source_loop_repeat_scenes: list[str] = []
    approved_source_loop_repeat_groups: dict[str, list[str]] = {}
    caption_preset_counts: dict[str, int] = {}
    layout_variant_counts: dict[str, int] = {}
    content_template = str(manifest.get("templateType") or manifest.get("template_type") or manifest.get("contentTemplate") or "")
    upload_candidate_required = _upload_candidate_required(manifest)
    source_first_required = _source_first_required(manifest)
    internet_source_proof_mode = _internet_source_proof_mode(manifest)
    manifest_audio_design_mode = _normalized_audio_design_mode(
        manifest.get("audioDesignMode") or manifest.get("audio_design_mode")
    )
    global_audio_bed_available = False
    audio_bed_scene_ids: set[str] = set()

    for asset in manifest.get("assets", []):
        role = str(asset.get("role") or "")
        provider = str(asset.get("provider") or "")
        kind = str(asset.get("kind") or "")
        scene_id = str(asset.get("sceneId") or "").strip()
        is_fallback_audio = provider == "fallback-sine" or kind == "fallback-tone"
        is_narration_audio = provider in FREE_NARRATION_PROVIDERS or kind in {"voiceover"}
        is_audio_bed = (
            role in {"audio", "sfx"}
            and not is_fallback_audio
            and not is_narration_audio
            and (
                provider in FREE_AUDIO_STOCK_PROVIDERS
                or provider == "upload"
                or kind in {"bgm", "music", "ambient", "ambience", "native", "uploaded-audio", "sfx"}
            )
        )
        if is_audio_bed:
            if scene_id and scene_id not in {"global", "project"}:
                audio_bed_scene_ids.add(scene_id)
            else:
                global_audio_bed_available = True
        if role not in {"audio", "sfx"} or provider not in FREE_AUDIO_STOCK_PROVIDERS:
            continue
        if provider in FREE_NARRATION_PROVIDERS or kind in {"voiceover", "native"}:
            continue
        if role == "sfx" and not any(
            str(asset.get(key) or "").strip()
            for key in ("sourceOrigin", "sourcePath", "sourceUrl", "sourceExternalId", "sourceLabel")
        ):
            continue
        credit = _build_free_audio_credit(asset)
        if credit:
            free_audio_credits.append(credit)
            if credit["missingFields"]:
                free_audio_credit_missing_assets.append(
                    f"{credit['evidenceLabel']}:missing={','.join(credit['missingFields'])}"
                )
        evidence_label = _asset_evidence_label(asset)
        if _asset_has_license_provenance(asset, require_license_note=True):
            free_audio_provenance_assets.append(evidence_label)
        else:
            missing_free_audio_provenance_assets.append(evidence_label)
        if provider == "local-bgm" and kind == "bgm":
            try:
                candidate_count = int(asset.get("candidateCount") or 0)
            except (TypeError, ValueError):
                candidate_count = 0
            selection_method = str(asset.get("selectionMethod") or "").strip()
            selection_key = str(asset.get("selectionKey") or "").strip()
            operator_pinned = (
                selection_method == "operator-pinned"
                and selection_key
                and asset.get("operatorSelected") is True
            )
            bgm_quality_risk = _bgm_asset_quality_risk_reason(asset)
            if bgm_quality_risk:
                placeholder_bgm_assets.append(evidence_label)
                placeholder_bgm_asset_reasons[evidence_label] = bgm_quality_risk
            if (candidate_count >= 2 and selection_method == "stable-hash" and selection_key) or operator_pinned:
                bgm_selection_assets.append(evidence_label)
            else:
                weak_bgm_selection_assets.append(evidence_label)

    scenes = manifest.get("scenes", [])
    layout_variant_required_templates = {
        "ranking_list",
        "tutorial_steps",
        "persona_story",
        "kculture_fandom",
        "longform_deep_dive",
        "interview_documentary",
        "live_recap",
    }
    requires_layout_variant = bool(
        content_template
        and len(scenes) > 1
        and (
            content_template in layout_variant_required_templates
            or len(scenes) >= 4
        )
    )
    first_scene_id = str((scenes[0] if scenes else {}).get("sceneId") or "")
    final_scene_id = str((scenes[-1] if scenes else {}).get("sceneId") or "")
    for scene in scenes:
        scene_id = str(scene.get("sceneId") or "")
        visual_asset = _visual_asset_for_scene(manifest, scene_id)
        visual_kind = str(scene.get("visualKind") or visual_asset.get("kind") or "")
        provider = str(visual_asset.get("provider") or "")
        source_origin = str(visual_asset.get("sourceOrigin") or "")
        source_intent = str(scene.get("visualSourceIntent") or provider or "")
        rationale = str(scene.get("sourceRationale") or "").strip()
        continuity = str(scene.get("continuityNote") or "").strip()
        hook_note = str(scene.get("hookNote") or "").strip()
        narration_text = str(scene.get("narrationText") or "").strip()
        subtitle_text = str(scene.get("subtitleText") or "").strip()
        caption_preset = str(scene.get("captionPreset") or "lower-info")
        audio_design_mode = _scene_audio_design_mode(scene, manifest_audio_design_mode, content_template)
        originality_evidence = str(scene.get("originalityEvidence") or "").strip()
        quality_review_note = str(scene.get("qualityReviewNote") or "").strip()
        thumbnail_review_note = str(scene.get("thumbnailReviewNote") or "").strip()
        audio_mix_review_note = str(scene.get("audioMixReviewNote") or "").strip()
        platform_comparison_note = str(scene.get("platformComparisonNote") or "").strip()
        visual_led_no_voice_approved = _visual_led_no_voice_approved(scene, manifest)
        visual_quality_verdict = str(
            scene.get("visualQualityVerdict")
            or scene.get("qualityReviewVerdict")
            or scene.get("manualVisualVerdict")
            or scene.get("operatorVisualVerdict")
            or ""
        ).strip()
        visual_quality_verdict_status = _manual_visual_verdict_status(visual_quality_verdict)
        stock_ai_clip_fit_verdict = str(
            scene.get("stockAiClipFitVerdict")
            or scene.get("stockClipFitVerdict")
            or scene.get("sourceFitVerdict")
            or scene.get("manualStockFitVerdict")
            or ""
        ).strip()
        stock_ai_clip_fit_verdict_status = _manual_visual_verdict_status(stock_ai_clip_fit_verdict)
        layout_variant_key = str(scene.get("layoutVariantKey") or "").strip()
        layout_variant_label = str(scene.get("layoutVariantLabel") or "").strip()
        layout_variant_note = str(scene.get("layoutVariantNote") or "").strip()
        source_generator = str(visual_asset.get("sourceGenerator") or "").strip()
        source_generator_request_path = str(visual_asset.get("sourceGeneratorRequestPath") or "").strip()
        source_generator_prompt_path = str(visual_asset.get("sourceGeneratorPromptPath") or "").strip()
        source_generator_log_path = str(visual_asset.get("sourceGeneratorLogPath") or "").strip()
        source_generator_command = str(visual_asset.get("sourceGeneratorCommand") or "").strip()
        local_media_result = local_media_by_scene.get(scene_id, {})
        caveats: list[str] = []
        is_original_video = False
        upload_originality_status = ""
        caption_preset_counts[caption_preset] = caption_preset_counts.get(caption_preset, 0) + 1
        selected_candidate = scene.get("selectedCandidate") if isinstance(scene.get("selectedCandidate"), dict) else {}
        candidate_assets = visual_asset.get("candidateAssets") if isinstance(visual_asset.get("candidateAssets"), list) else []
        try:
            grok_candidate_count = int(visual_asset.get("candidateCount") or 0)
        except (TypeError, ValueError):
            grok_candidate_count = 0
        if grok_candidate_count <= 0 and candidate_assets:
            grok_candidate_count = len([item for item in candidate_assets if isinstance(item, dict)])
        if grok_candidate_count <= 0 and selected_candidate:
            grok_candidate_count = 1
        selected_file_name = str(
            scene.get("selectedFileName")
            or scene.get("selectedGrokFileName")
            or visual_asset.get("selectedFileName")
            or selected_candidate.get("fileName")
            or ""
        ).strip()
        selected_candidate_summary = str(scene.get("selectedCandidateSummary") or "").strip()
        source_recovery_replacement_ready = (
            visual_asset.get("sourceRecoveryReplacement") is True
            and bool(str(visual_asset.get("sourceRecoveryAcceptanceSha256") or "").strip())
            and bool(str(visual_asset.get("acceptedReplacementSha256") or "").strip())
        )
        source_provenance = (
            selected_candidate.get("sourceProvenance")
            if isinstance(selected_candidate.get("sourceProvenance"), dict)
            else visual_asset.get("sourceProvenance")
            if isinstance(visual_asset.get("sourceProvenance"), dict)
            else {}
        )
        source_provenance_status = str(source_provenance.get("status") or "").strip()
        source_provenance_confirmed = scene.get("sourceProvenanceConfirmed") is True
        source_provenance_note = str(scene.get("sourceProvenanceNote") or "").strip()
        source_provenance_requires_confirmation = _source_provenance_confirmation_required(source_provenance)
        grok_source_review_verdict = _source_review_verdict_value(
            scene,
            selected_candidate,
            visual_asset,
            source_provenance,
        )
        grok_source_review_verdict_status = _manual_visual_verdict_status(grok_source_review_verdict)
        is_grok_handoff_source = _is_grok_handoff_visual(
            _normalized_source_tag(provider),
            _normalized_source_tag(source_origin),
            _normalized_source_tag(source_intent),
            visual_asset,
        )
        is_gemini_handoff_source = _is_gemini_handoff_visual(
            _normalized_source_tag(provider),
            _normalized_source_tag(source_origin),
            _normalized_source_tag(source_intent),
            visual_asset,
        )
        local_generated_source_ready = _local_generated_video_source_ready(
            _normalized_source_tag(provider),
            _normalized_source_tag(source_intent),
            visual_asset,
        )
        internet_motion_source_ready = _internet_motion_source_ready(scene, visual_asset, visual_kind)
        internet_context_source_ready = _internet_context_source_ready(manifest, scene, visual_asset, visual_kind)
        if internet_motion_source_ready:
            internet_motion_source_scenes += 1
            internet_motion_source_scene_ids.append(scene_id)
        if internet_context_source_ready:
            internet_context_source_scenes += 1
            internet_context_source_scene_ids.append(scene_id)
        grok_source_curation_issues: list[str] = []
        if is_grok_handoff_source:
            grok_source_curation_scenes.append(scene_id)
            if grok_candidate_count < 2 and not source_recovery_replacement_ready:
                grok_source_curation_issues.append("candidateCount<2")
                missing_grok_candidate_comparison_scenes.append(scene_id)
            if not selected_file_name:
                grok_source_curation_issues.append("selectedFileName")
                missing_grok_selected_file_scenes.append(scene_id)
            if len(selected_candidate_summary) < 24 and not source_recovery_replacement_ready:
                grok_source_curation_issues.append("selectedCandidateSummary")
                if scene_id not in missing_grok_candidate_comparison_scenes:
                    missing_grok_candidate_comparison_scenes.append(scene_id)
            if not source_provenance:
                grok_source_curation_issues.append("sourceProvenance")
                missing_grok_source_provenance_scenes.append(scene_id)
            else:
                source_accepts_grok_main = source_provenance.get("acceptAsGrokMainSource")
                if (
                    source_accepts_grok_main is False
                    or source_provenance_status not in GROK_SOURCE_PROVENANCE_ACCEPTABLE_STATUSES
                ):
                    grok_source_curation_issues.append("sourceProvenanceUnacceptable")
                    unacceptable_grok_source_provenance_scenes.append(scene_id)
                if source_provenance_requires_confirmation and (
                    source_provenance_confirmed is not True
                    or len(source_provenance_note) < 24
                ):
                    grok_source_curation_issues.append("sourceProvenanceConfirmation")
                    missing_grok_source_confirmation_scenes.append(scene_id)
            if grok_source_review_verdict_status == "pass":
                grok_source_review_verdict_scenes.append(scene_id)
            elif grok_source_review_verdict_status == "fail":
                grok_source_curation_issues.append("sourceReviewRejected")
                rejected_grok_source_review_scenes.append(scene_id)
            if _has_grok_preview_caveat(
                rationale,
                originality_evidence,
                quality_review_note,
                thumbnail_review_note,
                audio_mix_review_note,
                platform_comparison_note,
            ):
                grok_source_curation_issues.append("previewCaveat")
                grok_preview_caveat_scenes.append(scene_id)
            if grok_source_curation_issues:
                missing_grok_source_curation_scenes.append(scene_id)
                caveats.append(f"missing Grok-main curation evidence: {grok_source_curation_issues}")
            else:
                grok_source_curation_ready_scenes.append(scene_id)

        if is_gemini_handoff_source:
            gemini_handoff_scenes += 1
            gemini_handoff_scene_ids.append(scene_id)

        if source_first_required:
            source_first_reason = ""
            if is_grok_handoff_source:
                if grok_source_curation_issues:
                    source_first_reason = "grok-source-curation-incomplete"
                else:
                    source_first_generated_scene_ids.append(scene_id)
            elif is_gemini_handoff_source:
                if visual_quality_verdict_status != "pass":
                    source_first_reason = "gemini-source-visual-review-missing"
                elif not selected_file_name:
                    source_first_reason = "gemini-source-selected-file-missing"
                else:
                    source_first_generated_scene_ids.append(scene_id)
            elif local_generated_source_ready:
                source_first_generated_scene_ids.append(scene_id)
            elif internet_motion_source_ready and (
                not _internet_source_context_required(manifest)
                or internet_context_source_ready
            ):
                source_first_internet_source_scene_ids.append(scene_id)
            elif internet_context_source_ready:
                source_first_internet_context_scene_ids.append(scene_id)
            else:
                source_first_reason = "requires-grok-gemini-local-generated-or-context-approved-internet-source"
            if source_first_reason:
                source_first_blocked_scene_ids.append(scene_id)
                source_first_block_reasons_by_scene[scene_id] = source_first_reason
                caveats.append(f"source-first gate blocked: {source_first_reason}")

        if visual_kind == "video":
            video_scenes += 1
            if provider == "pexels-video":
                stock_video_scenes += 1
                stock_video_scene_ids.append(scene_id)
                stock_candidate_curation_scenes.append(scene_id)
                stock_issues: list[str] = []
                stock_candidate_count = _positive_int_metadata(visual_asset.get("candidateCount"))
                stock_creator = str(
                    visual_asset.get("creator")
                    or visual_asset.get("artist")
                    or visual_asset.get("sourceAttribution")
                    or ""
                ).strip()
                stock_source = str(
                    visual_asset.get("sourcePageUrl")
                    or visual_asset.get("sourceExternalId")
                    or visual_asset.get("sourceLabel")
                    or visual_asset.get("sourceUrl")
                    or ""
                ).strip()
                stock_summary = str(
                    visual_asset.get("selectedCandidateSummary")
                    or visual_asset.get("selectionRationale")
                    or rationale
                    or ""
                ).strip()
                if stock_candidate_count < 2:
                    stock_issues.append("candidateCount<2")
                    missing_stock_candidate_count_scenes.append(scene_id)
                if not stock_creator:
                    stock_issues.append("creator")
                    missing_stock_candidate_creator_scenes.append(scene_id)
                if not stock_source:
                    stock_issues.append("sourceUrlOrId")
                    missing_stock_candidate_source_scenes.append(scene_id)
                if len(stock_summary) < 24:
                    stock_issues.append("selectionSummary")
                    missing_stock_selection_summary_scenes.append(scene_id)
                if stock_issues:
                    missing_stock_candidate_curation_scenes.append(scene_id)
                    stock_candidate_curation_issues_by_scene[scene_id] = stock_issues
                    caveats.append(f"missing selected stock candidate curation evidence: {stock_issues}")
                else:
                    stock_candidate_curation_ready_scenes.append(scene_id)
            elif provider == "upload" and source_intent == "grok":
                grok_handoff_scenes += 1
                grok_handoff_scene_ids.append(scene_id)
                upload_originality_status = "grok-handoff"
                is_original_video = True
            elif is_gemini_handoff_source:
                upload_originality_status = "gemini-handoff"
                is_original_video = True
            elif (
                provider in LOCAL_ORIGINAL_VIDEO_INTENTS
                or source_intent in LOCAL_ORIGINAL_VIDEO_INTENTS
            ):
                local_model_video_scenes += 1
                local_model_video_scene_ids.append(scene_id)
                upload_originality_status = "local-model"
                is_original_video = True
            elif provider == "upload":
                uploaded_video_scenes += 1
                uploaded_video_scene_ids.append(scene_id)
                is_original_video, upload_originality_status = _uploaded_video_originality_status(
                    scene,
                    visual_asset,
                    source_intent,
                )
                if not is_original_video:
                    if internet_motion_source_ready:
                        upload_originality_status = "internet-source-proof"
                    else:
                        weak_uploaded_originality_scenes.append(scene_id)
                    if upload_originality_status == "procedural-placeholder":
                        procedural_placeholder_scenes.append(scene_id)
                        caveats.append("uploaded MP4 appears to be procedural/test-pattern placeholder, not owned footage")
                    elif upload_originality_status == "stock-rewrapped-upload":
                        caveats.append("uploaded MP4 retains stock/free-source provenance, not owned footage")
                    elif upload_originality_status != "internet-source-proof":
                        caveats.append("uploaded MP4 lacks owned/direct source proof")
        else:
            image_fallback_scenes += 1
            image_fallback_scene_ids.append(scene_id)
            caveats.append("image fallback")

        visual_identity = _visual_asset_identity(visual_asset)
        if visual_identity:
            first_seen_scene = visual_identity_first_seen.get(visual_identity)
            if first_seen_scene and first_seen_scene != scene_id:
                first_scene = next(
                    (item for item in manifest.get("scenes", []) if str(item.get("sceneId") or "") == first_seen_scene),
                    {},
                )
                first_visual_asset = _visual_asset_for_scene(manifest, first_seen_scene)
                if _source_loop_repeat_pair_approved(first_scene, first_visual_asset, scene, visual_asset):
                    group_id = _source_loop_group_id(scene, visual_asset)
                    approved_source_loop_repeat_scenes.append(scene_id)
                    group_scenes = approved_source_loop_repeat_groups.setdefault(group_id, [])
                    if first_seen_scene not in group_scenes:
                        group_scenes.append(first_seen_scene)
                    if scene_id not in group_scenes:
                        group_scenes.append(scene_id)
                    caveats.append(f"intentional source loop repeat from {first_seen_scene}")
                else:
                    repeated_visual_asset_scenes.append(scene_id)
                    caveats.append(f"reused visual asset from {first_seen_scene}")
            else:
                visual_identity_first_seen[visual_identity] = scene_id

        if provider in FREE_STOCK_PROVIDERS:
            if _asset_has_license_provenance(visual_asset):
                free_asset_provenance_scenes.append(scene_id)
            else:
                missing_free_asset_provenance_scenes.append(scene_id)
                caveats.append("missing free visual asset provenance")

        narration_length = _compact_text_length(narration_text)
        subtitle_length = _compact_text_length(subtitle_text)
        narration_meta_terms = _production_meta_terms(narration_text)
        subtitle_meta_terms = _production_meta_terms(subtitle_text)
        caption_duration = _scene_caption_duration(scene)
        try:
            scene_duration = float(scene.get("durationSec") if scene.get("durationSec") is not None else scene.get("duration_sec") or 0)
        except (TypeError, ValueError):
            scene_duration = 0.0
        if scene_duration > 0:
            scene_duration_by_id[scene_id] = scene_duration
        edit_beat_note = str(
            scene.get("editBeatNote")
            or scene.get("cutPacingNote")
            or scene.get("shortFormEditNote")
            or scene.get("referenceEditNote")
            or ""
        ).strip()
        if (
            scene_duration > float(REFERENCE_EDIT_GRAMMAR_POLICY["maxUnjustifiedHoldSec"])
            and not edit_beat_note
        ):
            long_hold_scene_ids.append(scene_id)
            caveats.append(f"long hold without edit beat note ({scene_duration:.1f}s)")
        reference_terms = _reference_edit_grammar_terms(
            platform_comparison_note,
            quality_review_note,
            layout_variant_note,
            hook_note,
            edit_beat_note,
        )
        if reference_terms:
            short_form_reference_scenes.append(scene_id)
            reference_edit_terms_by_scene[scene_id] = reference_terms
        else:
            missing_reference_edit_grammar_scenes.append(scene_id)
            caveats.append("missing concrete reference edit grammar: hook/cut rhythm/caption safe-zone/platform reference")
        min_chars = _required_narration_chars(content_template, scene_id, first_scene_id)
        narration_min_chars_by_scene[scene_id] = min_chars
        if narration_text and audio_design_mode == "no-voice":
            audio_design_mode = "voiceover"
        audio_design_modes_by_scene[scene_id] = audio_design_mode
        if narration_text:
            narration_scenes.append(scene_id)
            short_callout_approved = _short_voiceover_callout_approved(
                scene,
                content_template,
                narration_length,
                subtitle_length,
                scene_duration,
            )
            final_payoff_short_narration_approved = _final_payoff_short_narration_approved(
                scene,
                scene_id,
                final_scene_id,
                narration_length,
                subtitle_length,
            )
            if short_callout_approved:
                short_voiceover_callout_scenes.append(scene_id)
            if final_payoff_short_narration_approved:
                final_payoff_short_narration_scenes.append(scene_id)
            if narration_length < min_chars and not short_callout_approved and not final_payoff_short_narration_approved:
                thin_narration_scenes.append(scene_id)
                caveats.append(f"thin narration for TTS ({narration_length}/{min_chars})")
            if narration_meta_terms:
                production_meta_narration_scenes.append(scene_id)
                production_meta_terms_by_scene[scene_id] = narration_meta_terms
                caveats.append(f"viewer-facing narration contains production meta terms: {narration_meta_terms}")
        else:
            if audio_design_mode == "no-voice":
                no_voice_audio_design_scenes.append(scene_id)
                if content_template in VOICEOVER_REQUIRED_TEMPLATES and not visual_led_no_voice_approved:
                    voiceover_required_no_voice_scenes.append(scene_id)
                    caveats.append(
                        "information/ranking template requires viewer-facing TTS/voiceover unless visual-led no-voice is explicitly human-approved"
                    )
                elif visual_led_no_voice_approved:
                    visual_led_no_voice_approved_scenes.append(scene_id)
                if not (global_audio_bed_available or scene_id in audio_bed_scene_ids):
                    missing_no_voice_audio_scenes.append(scene_id)
                    caveats.append("no-voice audio design lacks BGM, ambience, native audio, or SFX bed")
                if not audio_mix_review_note:
                    missing_no_voice_audio_review_scenes.append(scene_id)
                    caveats.append("no-voice audio design needs an audio mix review note")
            else:
                missing_narration_scenes.append(scene_id)
                if subtitle_text:
                    subtitle_only_narration_scenes.append(scene_id)
                    caveats.append("subtitle text is not TTS narration evidence")
                else:
                    caveats.append("missing TTS narration")
        if subtitle_meta_terms:
            production_meta_subtitle_scenes.append(scene_id)
            existing_terms = production_meta_terms_by_scene.get(scene_id, [])
            production_meta_terms_by_scene[scene_id] = sorted(set(existing_terms + subtitle_meta_terms))
            caveats.append(f"display caption contains production meta terms: {subtitle_meta_terms}")

        if is_original_video:
            original_clip_scene_ids.append(scene_id)

        if not rationale:
            missing_rationale.append(scene_id)
            caveats.append("missing source rationale")
        if not continuity:
            missing_continuity.append(scene_id)
            caveats.append("missing continuity note")
        if is_original_video:
            if originality_evidence:
                originality_evidence_scenes.append(scene_id)
            else:
                missing_originality_evidence.append(scene_id)
                caveats.append("missing originality evidence")
        if quality_review_note:
            quality_review_scenes.append(scene_id)
        else:
            missing_quality_review.append(scene_id)
            caveats.append("missing channel quality review")
        if visual_quality_verdict_status == "pass":
            visual_verdict_scenes.append(scene_id)
        elif visual_quality_verdict_status == "fail":
            failed_visual_verdict_scenes.append(scene_id)
            caveats.append(f"manual visual verdict is {visual_quality_verdict}")
        else:
            missing_visual_verdict_scenes.append(scene_id)
            caveats.append("missing explicit pass/fail visual verdict")
        if _caption_layout_reviewed(caption_preset, quality_review_note):
            caption_layout_review_scenes.append(scene_id)
        else:
            missing_caption_layout_review_scenes.append(scene_id)
            caveats.append("missing caption layout review")
        stock_or_ai_fit_verdict_required = (
            provider in FREE_STOCK_PROVIDERS
            or "stock" in _normalized_source_tag(source_intent)
            or source_provenance.get("notOwnedFootage") is True
        )
        if stock_or_ai_fit_verdict_required:
            if stock_ai_clip_fit_verdict_status == "pass":
                stock_ai_clip_fit_verdict_scenes.append(scene_id)
            elif stock_ai_clip_fit_verdict_status == "fail":
                failed_stock_ai_clip_fit_verdict_scenes.append(scene_id)
                caveats.append(f"stock/AI clip fit verdict is {stock_ai_clip_fit_verdict}")
            else:
                missing_stock_ai_clip_fit_verdict_scenes.append(scene_id)
                caveats.append("missing explicit stock/AI clip fit verdict")
        if caption_preset != "none" and subtitle_text:
            captioned_scene_ids.append(scene_id)
            density_issue = _caption_density_issue(caption_preset, subtitle_text, caption_duration)
            if density_issue:
                caption_density_issue_scenes.append(scene_id)
                caption_density_issues_by_scene[scene_id] = density_issue
                caveats.append(density_issue)
            if caption_preset == "top-hook" and caption_duration > 2.6:
                long_top_hook_scenes.append(scene_id)
                caveats.append(f"top-hook caption runs too long ({caption_duration:.1f}s)")
        if thumbnail_review_note:
            thumbnail_review_scenes.append(scene_id)
        if audio_mix_review_note:
            audio_mix_review_scenes.append(scene_id)
        if platform_comparison_note:
            platform_comparison_scenes.append(scene_id)
        if layout_variant_key:
            layout_variant_scenes.append(scene_id)
            layout_variant_counts[layout_variant_key] = layout_variant_counts.get(layout_variant_key, 0) + 1
        elif requires_layout_variant:
            missing_layout_variant_scenes.append(scene_id)
            caveats.append("missing layout variant evidence")
        if local_media_result.get("status") == "placeholder":
            caveats.append("placeholder media")

        provenance = {
            "sourceGenerator": source_generator,
            "sourceGeneratorRequestPath": source_generator_request_path,
            "sourceGeneratorPromptPath": source_generator_prompt_path,
            "sourceGeneratorLogPath": source_generator_log_path,
            "sourceGeneratorCommand": source_generator_command,
        }
        if is_original_video and (
            source_generator
            or source_generator_request_path
            or source_generator_prompt_path
            or source_generator_log_path
        ):
            provenance["hasGeneratorProvenance"] = True
        else:
            provenance["hasGeneratorProvenance"] = False

        scenes_payload.append(
            {
                "sceneId": scene_id,
                "visualKind": visual_kind,
                "visualProvider": provider,
                "sourceOrigin": source_origin,
                "sourceIntent": source_intent,
                "sourceRationale": rationale,
                "continuityNote": continuity,
                "hookNote": hook_note,
                "narrationTextLength": narration_length,
                "subtitleTextLength": subtitle_length,
                "requiredNarrationTextLength": min_chars,
                "shortVoiceoverCalloutApproved": scene_id in short_voiceover_callout_scenes,
                "finalPayoffShortNarrationApproved": scene_id in final_payoff_short_narration_scenes,
                "audioDesignMode": audio_design_mode,
                "voiceoverRequiredNoVoice": scene_id in voiceover_required_no_voice_scenes,
                "visualLedNoVoiceApproved": visual_led_no_voice_approved,
                "subtitleOnlyNarrationFallback": bool(
                    subtitle_text and not narration_text and audio_design_mode != "no-voice"
                ),
                "productionMetaNarrationTerms": narration_meta_terms,
                "productionMetaSubtitleTerms": subtitle_meta_terms,
                "captionPreset": caption_preset,
                "captionDurationSec": caption_duration,
                "originalityEvidence": originality_evidence,
                "qualityReviewNote": quality_review_note,
                "thumbnailReviewNote": thumbnail_review_note,
                "audioMixReviewNote": audio_mix_review_note,
                "platformComparisonNote": platform_comparison_note,
                "visualQualityVerdict": visual_quality_verdict,
                "visualQualityVerdictStatus": visual_quality_verdict_status,
                "stockAiClipFitVerdict": stock_ai_clip_fit_verdict,
                "stockAiClipFitVerdictStatus": stock_ai_clip_fit_verdict_status,
                "grokSourceReviewVerdict": grok_source_review_verdict,
                "grokSourceReviewVerdictStatus": grok_source_review_verdict_status,
                "layoutVariantKey": layout_variant_key,
                "layoutVariantLabel": layout_variant_label,
                "layoutVariantNote": layout_variant_note,
                "candidateCount": grok_candidate_count if is_grok_handoff_source else (
                    _positive_int_metadata(visual_asset.get("candidateCount"))
                    if provider == "pexels-video"
                    else 0
                ),
                "selectedFileName": selected_file_name,
                "selectedCandidateSummary": selected_candidate_summary
                or str(visual_asset.get("selectedCandidateSummary") or visual_asset.get("selectionRationale") or "").strip(),
                "sourceProvenanceStatus": source_provenance_status,
                "sourceProvenanceConfirmed": source_provenance_confirmed,
                "sourceProvenanceNote": source_provenance_note,
                "uploadOriginalityStatus": upload_originality_status,
                "internetMotionSourceReady": internet_motion_source_ready,
                "internetContextSourceReady": internet_context_source_ready,
                "internetSourceAcquisition": _internet_source_acquisition_scene_status(scene, visual_asset)[2]
                if _is_internet_source_candidate(scene, visual_asset)
                else {},
                "internetSourceContext": _internet_source_context_scene_status(manifest, scene, visual_asset)[2]
                if _is_internet_source_candidate(scene, visual_asset)
                else {},
                "sourceLoopGroupId": _source_loop_group_id(scene, visual_asset),
                "sourceLoopRepeatApproved": _source_loop_repeat_approved(scene, visual_asset),
                "approvedSourceLoopRepeat": scene_id in approved_source_loop_repeat_scenes,
                "sourceLoopRhythmReview": _source_loop_review_text(scene, visual_asset),
                "localGenerationProvenance": provenance,
                "grokSourceCuration": {
                    "required": is_grok_handoff_source,
                    "ready": is_grok_handoff_source and not grok_source_curation_issues,
                    "sourceRecoveryReplacement": source_recovery_replacement_ready,
                    "candidateCount": grok_candidate_count,
                    "selectedFileName": selected_file_name,
                    "selectedCandidateSummaryReady": len(selected_candidate_summary) >= 24,
                    "sourceProvenanceStatus": source_provenance_status,
                    "sourceProvenanceAcceptable": bool(source_provenance)
                    and source_provenance.get("acceptAsGrokMainSource") is not False
                    and source_provenance_status in GROK_SOURCE_PROVENANCE_ACCEPTABLE_STATUSES,
                    "sourceProvenanceConfirmationRequired": source_provenance_requires_confirmation,
                    "sourceProvenanceConfirmed": source_provenance_confirmed,
                    "sourceProvenanceNoteReady": len(source_provenance_note) >= 24,
                    "sourceReviewVerdict": grok_source_review_verdict,
                    "sourceReviewVerdictStatus": grok_source_review_verdict_status,
                    "issues": grok_source_curation_issues,
                },
                "caveats": caveats,
            }
        )

    first_scene = scenes[0] if scenes else {}
    first_scene_hook_ready = (
        bool(scenes)
        and (
            _text_present(first_scene.get("hookNote"))
            or first_scene.get("captionPreset") == "top-hook"
        )
        and (_text_present(first_scene.get("title")) or _text_present(first_scene.get("subtitleText")))
    )
    stock_only = (
        bool(scenes)
        and stock_video_scenes == len(scenes)
        and uploaded_video_scenes == 0
        and grok_handoff_scenes == 0
        and local_model_video_scenes == 0
        and image_fallback_scenes == 0
    )
    curated_stock_ready = (
        stock_only
        and not missing_rationale
        and not missing_continuity
        and first_scene_hook_ready
    )
    caption_sparse_plan = (
        len(scenes) >= 4
        and len(captioned_scene_ids) <= 1
        and int(caption_preset_counts.get("none", 0) or 0) >= len(scenes) - 1
    )
    source_context_cut_density_ready = (
        len(scenes) >= 4
        and internet_context_source_scenes == len(scenes)
        and video_scenes >= 1
        and not repeated_visual_asset_scenes
        and len(short_form_reference_scenes) == len(scenes)
        and not missing_caption_layout_review_scenes
    )
    shorts_cut_density_ready = (
        len(scenes) < 4
        or (
            video_scenes >= 4
            and image_fallback_scenes == 0
            and not repeated_visual_asset_scenes
        )
        or source_context_cut_density_ready
    )
    average_scene_duration_sec = (
        round(sum(scene_duration_by_id.values()) / len(scene_duration_by_id), 2)
        if scene_duration_by_id
        else 0.0
    )
    reference_edit_grammar_issues: list[str] = []
    if missing_reference_edit_grammar_scenes:
        reference_edit_grammar_issues.append(
            f"missing reference edit grammar scenes={missing_reference_edit_grammar_scenes}"
        )
    if long_hold_scene_ids:
        reference_edit_grammar_issues.append(
            f"long holds above {REFERENCE_EDIT_GRAMMAR_POLICY['maxUnjustifiedHoldSec']}s without beat notes={long_hold_scene_ids}"
        )
    if (
        len(scenes) >= 4
        and average_scene_duration_sec > float(REFERENCE_EDIT_GRAMMAR_POLICY["targetAverageCutSec"])
        and not source_context_cut_density_ready
    ):
        reference_edit_grammar_issues.append(
            f"average scene duration {average_scene_duration_sec:.2f}s exceeds {REFERENCE_EDIT_GRAMMAR_POLICY['targetAverageCutSec']}s reference pacing"
        )
    if not first_scene_hook_ready:
        reference_edit_grammar_issues.append("first scene lacks explicit first-two-second hook treatment")
    reference_edit_grammar_ready = not reference_edit_grammar_issues
    first_scene_id = str(first_scene.get("sceneId") or "scene-01")
    thumbnail_first_frame_ready = first_scene_id in thumbnail_review_scenes and first_scene_hook_ready
    min_original_scene_count = 1 if len(scenes) <= 1 else max(2, (len(scenes) + 1) // 2)
    source_mix_required = len(scenes) > 1 and content_template in UPLOAD_SOURCE_MIX_REQUIRED_TEMPLATES
    original_source_mix_ready = len(set(original_clip_scene_ids)) >= min_original_scene_count
    stock_source_mix_gap_scene_ids = (
        list(stock_video_scene_ids)
        if source_mix_required and not original_source_mix_ready and stock_video_scenes > 0
        else []
    )
    source_first_accepted_scene_ids = sorted(set(
        source_first_generated_scene_ids
        + source_first_internet_source_scene_ids
        + source_first_internet_context_scene_ids
    ))
    source_first_blocking_image_fallback_scene_ids = [
        scene_id
        for scene_id in image_fallback_scene_ids
        if scene_id not in source_first_internet_context_scene_ids
    ]
    source_first_ready = (
        not source_first_required
        or (
            not source_first_blocked_scene_ids
            and not source_first_blocking_image_fallback_scene_ids
            and len(source_first_accepted_scene_ids) == len(scenes)
        )
    )
    ai_slop_visual_fit_status = (
        "fail"
        if failed_visual_verdict_scenes
        else "warn"
        if missing_visual_verdict_scenes
        else "pass"
    )
    stock_ai_clip_fit_status = (
        "fail"
        if (
            procedural_placeholder_scenes
            or failed_visual_verdict_scenes
            or stock_source_mix_gap_scene_ids
            or failed_stock_ai_clip_fit_verdict_scenes
            or missing_stock_ai_clip_fit_verdict_scenes
            or source_first_blocked_scene_ids
        )
        else "warn"
        if stock_only or weak_uploaded_originality_scenes or missing_visual_verdict_scenes
        else "pass"
    )

    return {
        "summary": {
            "totalScenes": len(scenes),
            "videoScenes": video_scenes,
            "stockVideoScenes": stock_video_scenes,
            "uploadedVideoScenes": uploaded_video_scenes,
            "grokHandoffScenes": grok_handoff_scenes,
            "geminiHandoffScenes": gemini_handoff_scenes,
            "localModelVideoScenes": local_model_video_scenes,
            "internetMotionSourceScenes": internet_motion_source_scenes,
            "internetContextSourceScenes": internet_context_source_scenes,
            "imageFallbackScenes": image_fallback_scenes,
            "stockVideoSceneIds": stock_video_scene_ids,
            "uploadedVideoSceneIds": uploaded_video_scene_ids,
            "grokHandoffSceneIds": grok_handoff_scene_ids,
            "geminiHandoffSceneIds": gemini_handoff_scene_ids,
            "localModelVideoSceneIds": local_model_video_scene_ids,
            "internetMotionSourceSceneIds": internet_motion_source_scene_ids,
            "internetContextSourceSceneIds": internet_context_source_scene_ids,
            "originalClipSceneIds": original_clip_scene_ids,
            "originalSourceMixRequired": source_mix_required,
            "originalSourceMixReady": original_source_mix_ready,
            "minOriginalScenesForSourceMix": min_original_scene_count,
            "stockSourceMixGapSceneIds": stock_source_mix_gap_scene_ids,
            "sourceFirstRequired": source_first_required,
            "sourceFirstReady": source_first_ready,
            "sourceFirstGeneratedSceneIds": source_first_generated_scene_ids,
            "sourceFirstInternetSourceSceneIds": source_first_internet_source_scene_ids,
            "sourceFirstInternetContextSceneIds": source_first_internet_context_scene_ids,
            "sourceFirstAcceptedSceneIds": source_first_accepted_scene_ids,
            "sourceFirstBlockedSceneIds": source_first_blocked_scene_ids,
            "sourceFirstBlockReasonsByScene": source_first_block_reasons_by_scene,
            "sourceFirstBlockingImageFallbackSceneIds": source_first_blocking_image_fallback_scene_ids,
            "internetSourceProofMode": internet_source_proof_mode,
            "weakUploadedOriginalityScenes": weak_uploaded_originality_scenes,
            "proceduralPlaceholderScenes": procedural_placeholder_scenes,
            "imageFallbackSceneIds": image_fallback_scene_ids,
            "missingRationaleScenes": missing_rationale,
            "missingContinuityScenes": missing_continuity,
            "missingOriginalityEvidenceScenes": missing_originality_evidence,
            "missingQualityReviewScenes": missing_quality_review,
            "originalityEvidenceScenes": originality_evidence_scenes,
            "qualityReviewScenes": quality_review_scenes,
            "thumbnailReviewScenes": thumbnail_review_scenes,
            "audioMixReviewScenes": audio_mix_review_scenes,
            "platformComparisonScenes": platform_comparison_scenes,
            "visualVerdictScenes": visual_verdict_scenes,
            "missingVisualVerdictScenes": missing_visual_verdict_scenes,
            "failedVisualVerdictScenes": failed_visual_verdict_scenes,
            "stockAiClipFitVerdictScenes": stock_ai_clip_fit_verdict_scenes,
            "missingStockAiClipFitVerdictScenes": missing_stock_ai_clip_fit_verdict_scenes,
            "failedStockAiClipFitVerdictScenes": failed_stock_ai_clip_fit_verdict_scenes,
            "layoutVariantScenes": layout_variant_scenes,
            "missingLayoutVariantScenes": missing_layout_variant_scenes,
            "layoutVariantCounts": layout_variant_counts,
            "narrationScenes": narration_scenes,
            "subtitleOnlyNarrationScenes": subtitle_only_narration_scenes,
            "missingNarrationScenes": missing_narration_scenes,
            "thinNarrationScenes": thin_narration_scenes,
            "shortVoiceoverCalloutScenes": short_voiceover_callout_scenes,
            "finalPayoffShortNarrationScenes": final_payoff_short_narration_scenes,
            "productionMetaNarrationScenes": production_meta_narration_scenes,
            "productionMetaSubtitleScenes": production_meta_subtitle_scenes,
            "productionMetaTermsByScene": production_meta_terms_by_scene,
            "narrationMinCharsByScene": narration_min_chars_by_scene,
            "noVoiceAudioDesignScenes": no_voice_audio_design_scenes,
            "voiceoverRequiredNoVoiceScenes": voiceover_required_no_voice_scenes,
            "visualLedNoVoiceApprovedScenes": visual_led_no_voice_approved_scenes,
            "missingNoVoiceAudioScenes": missing_no_voice_audio_scenes,
            "missingNoVoiceAudioReviewScenes": missing_no_voice_audio_review_scenes,
            "audioDesignModesByScene": audio_design_modes_by_scene,
            "captionedSceneIds": captioned_scene_ids,
            "captionSparsePlan": caption_sparse_plan,
            "longTopHookScenes": long_top_hook_scenes,
            "captionDensityIssueScenes": caption_density_issue_scenes,
            "captionDensityIssuesByScene": caption_density_issues_by_scene,
            "captionSafeZonePolicy": SHORTS_CAPTION_SAFE_ZONE_POLICY,
            "captionMaxCompactChars": SHORTS_CAPTION_MAX_COMPACT_CHARS,
            "captionLayoutReviewScenes": caption_layout_review_scenes,
            "missingCaptionLayoutReviewScenes": missing_caption_layout_review_scenes,
            "captionPresetCounts": caption_preset_counts,
            "referenceEditGrammarPolicy": REFERENCE_EDIT_GRAMMAR_POLICY,
            "referenceEditGrammarReady": reference_edit_grammar_ready,
            "referenceEditGrammarIssues": reference_edit_grammar_issues,
            "referenceEditTermsByScene": reference_edit_terms_by_scene,
            "sourceContextCutDensityReady": source_context_cut_density_ready,
            "shortFormReferenceScenes": short_form_reference_scenes,
            "missingReferenceEditGrammarScenes": missing_reference_edit_grammar_scenes,
            "longHoldSceneIds": long_hold_scene_ids,
            "averageSceneDurationSec": average_scene_duration_sec,
            "sceneDurationById": scene_duration_by_id,
            "repeatedVisualAssetScenes": repeated_visual_asset_scenes,
            "approvedSourceLoopRepeatScenes": approved_source_loop_repeat_scenes,
            "approvedSourceLoopRepeatGroups": approved_source_loop_repeat_groups,
            "freeAssetProvenanceScenes": free_asset_provenance_scenes,
            "missingFreeAssetProvenanceScenes": missing_free_asset_provenance_scenes,
            "freeAudioProvenanceAssets": free_audio_provenance_assets,
            "missingFreeAudioProvenanceAssets": missing_free_audio_provenance_assets,
            "freeAudioCredits": free_audio_credits,
            "freeAudioCreditMissingAssets": free_audio_credit_missing_assets,
            "youtubeDescriptionAudioCredits": [
                credit["youtubeDescriptionLine"]
                for credit in free_audio_credits
                if credit.get("youtubeDescriptionLine")
            ],
            "bgmSelectionAssets": bgm_selection_assets,
            "weakBgmSelectionAssets": weak_bgm_selection_assets,
            "placeholderBgmAssets": placeholder_bgm_assets,
            "placeholderBgmAssetReasons": placeholder_bgm_asset_reasons,
            "stockCandidateCurationScenes": stock_candidate_curation_scenes,
            "stockCandidateCurationReadyScenes": stock_candidate_curation_ready_scenes,
            "missingStockCandidateCurationScenes": missing_stock_candidate_curation_scenes,
            "missingStockCandidateCountScenes": missing_stock_candidate_count_scenes,
            "missingStockCandidateCreatorScenes": missing_stock_candidate_creator_scenes,
            "missingStockCandidateSourceScenes": missing_stock_candidate_source_scenes,
            "missingStockSelectionSummaryScenes": missing_stock_selection_summary_scenes,
            "stockCandidateCurationIssuesByScene": stock_candidate_curation_issues_by_scene,
            "grokSourceCurationScenes": grok_source_curation_scenes,
            "grokSourceCurationReadyScenes": grok_source_curation_ready_scenes,
            "missingGrokSourceCurationScenes": missing_grok_source_curation_scenes,
            "missingGrokCandidateComparisonScenes": missing_grok_candidate_comparison_scenes,
            "missingGrokSelectedFileScenes": missing_grok_selected_file_scenes,
            "missingGrokSourceProvenanceScenes": missing_grok_source_provenance_scenes,
            "unacceptableGrokSourceProvenanceScenes": unacceptable_grok_source_provenance_scenes,
            "missingGrokSourceConfirmationScenes": missing_grok_source_confirmation_scenes,
            "grokSourceReviewVerdictScenes": grok_source_review_verdict_scenes,
            "rejectedGrokSourceReviewScenes": rejected_grok_source_review_scenes,
            "grokPreviewCaveatScenes": grok_preview_caveat_scenes,
            "firstSceneHookReady": first_scene_hook_ready,
            "shortsCutDensityReady": shorts_cut_density_ready,
            "thumbnailFirstFrameReady": thumbnail_first_frame_ready,
            "aiSlopVisualFitStatus": ai_slop_visual_fit_status,
            "stockAiClipFitStatus": stock_ai_clip_fit_status,
            "stockOnly": stock_only,
            "curatedStockReady": curated_stock_ready,
            "contentTemplate": content_template,
            "uploadCandidateRequired": upload_candidate_required,
        },
        "scenes": scenes_payload,
    }


def _build_publish_readiness(
    checks: dict,
    production_review: dict,
    local_media_summary: dict,
) -> dict:
    """Convert low-level QA checks into an operator-facing publish gate."""
    production_summary = production_review.get("summary") or {}
    criteria: list[dict] = []
    required_fixes: list[str] = []
    recommended_fixes: list[str] = []
    strengths: list[str] = []

    def add_criterion(
        key: str,
        label: str,
        status: str,
        detail: str,
        fix: str,
        required: bool,
    ) -> None:
        criteria.append(
            {
                "key": key,
                "label": label,
                "status": status,
                "detail": detail,
                "required": required,
            }
        )
        if status == "fail" and required:
            required_fixes.append(fix)
        elif status in {"fail", "warn"} and not required:
            recommended_fixes.append(fix)
        elif status == "pass":
            strengths.append(label)

    def check_status(key: str) -> str:
        return str((checks.get(key) or {}).get("status") or "warn")

    def check_detail(key: str) -> str:
        return str((checks.get(key) or {}).get("detail") or "")

    add_criterion(
        "outputSpec",
        "1080x1920 30fps audio output",
        check_status("outputSpec"),
        check_detail("outputSpec"),
        "Re-render to 1080x1920 at 30fps with an audio stream and positive duration.",
        True,
    )
    add_criterion(
        "noPlaceholders",
        "No placeholder media",
        check_status("noPlaceholders"),
        check_detail("noPlaceholders"),
        "Replace every placeholder with uploaded, Grok handoff, local-model, or curated stock video.",
        True,
    )
    procedural_placeholder_scenes = production_summary.get("proceduralPlaceholderScenes") or []
    add_criterion(
        "proceduralPlaceholderClips",
        "No procedural test-pattern clips",
        "fail" if procedural_placeholder_scenes else "pass",
        f"proceduralPlaceholderScenes={procedural_placeholder_scenes}",
        "Replace color-bar/test-pattern/procedural local-render clips with real uploaded, Grok handoff, local-model, or curated stock MP4s.",
        True,
    )
    add_criterion(
        "movingClipPriority",
        "Uses moving video clips",
        check_status("movingClipPriority"),
        check_detail("movingClipPriority"),
        "Add at least one real video clip before treating this as a finished Shorts/long-form render.",
        True,
    )
    add_criterion(
        "zeroPaidProviders",
        "Zero paid providers",
        check_status("zeroPaidProviders"),
        check_detail("zeroPaidProviders"),
        "Remove paid API/provider assets from the manifest before publishing.",
        True,
    )
    add_criterion(
        "captionSafePresets",
        "Caption safe-zone presets",
        check_status("captionSafePresets"),
        check_detail("captionSafePresets"),
        "Use only none, center-short, top-hook, or lower-info caption presets.",
        True,
    )
    add_criterion(
        "providerConsistency",
        "Provider-homogeneous final candidate",
        check_status("providerConsistency"),
        check_detail("providerConsistency"),
        "For upload candidates, use Grok-only or Gemini-only sources; local-only is proof/fallback only and mixed providers require a separate proof path.",
        check_status("providerConsistency") == "fail",
    )
    add_criterion(
        "antiAiNaturalness",
        "Anti-AI naturalness review",
        check_status("antiAiNaturalness"),
        check_detail("antiAiNaturalness"),
        "Record per-scene naturalness proof: not generic AI/ad footage, same-world hands/objects/light, and a physical reason for each action.",
        check_status("antiAiNaturalness") == "fail",
    )
    add_criterion(
        "captionSystem",
        "Caption system consistency",
        check_status("captionSystem"),
        check_detail("captionSystem"),
        "Use a fixed caption position policy and record hook/friction/action/payoff/context purpose plus subject/UI clearance for every captioned scene.",
        check_status("captionSystem") == "fail",
    )
    add_criterion(
        "viewerTakeaway",
        "Viewer takeaway",
        check_status("viewerTakeaway"),
        check_detail("viewerTakeaway"),
        "State what the viewer understands, what action they can take, and what emotional state the video should leave.",
        check_status("viewerTakeaway") == "fail",
    )
    add_criterion(
        "subtitleArtifact",
        "Subtitle artifact exists",
        check_status("subtitleArtifact"),
        check_detail("subtitleArtifact"),
        "Regenerate subtitles so the final render has a matching ASS or SRT artifact.",
        True,
    )
    add_criterion(
        "ttsNarrationEvidence",
        "Intentional audio design",
        check_status("ttsNarrationEvidence"),
        check_detail("ttsNarrationEvidence"),
        "Use natural viewer-facing narration only when it helps; for Grok-first raw footage, mark no-voice audio design and keep BGM/native audio plus mix review evidence.",
        True,
    )
    voiceover_required_no_voice = production_summary.get("voiceoverRequiredNoVoiceScenes") or []
    add_criterion(
        "voicePolicyCompliance",
        "Template voice policy compliance",
        "fail" if voiceover_required_no_voice else "pass",
        (
            f"voiceoverRequiredNoVoiceScenes={voiceover_required_no_voice}, "
            f"visualLedNoVoiceApprovedScenes={production_summary.get('visualLedNoVoiceApprovedScenes') or []}"
        ),
        "Add TTS/voiceover for information, ranking, and list templates, or record explicit human approval that the scene is visual-led no-voice.",
        True,
    )
    add_criterion(
        "captionLayoutReview",
        "Caption layout and subject-clear review",
        check_status("captionLayoutReview"),
        check_detail("captionLayoutReview"),
        "Choose no caption, top hook, center short caption, or lower info intentionally and record that captions do not cover the subject or Shorts UI.",
        True,
    )
    add_criterion(
        "captionDensityAndSafeZone",
        "Caption density and Shorts safe-zone fit",
        check_status("captionDensityAndSafeZone"),
        check_detail("captionDensityAndSafeZone"),
        "Shorten burned-in captions and keep lower captions in the lower-mid Shorts safe zone instead of the bottom UI area.",
        True,
    )
    add_criterion(
        "sourceEditorialLayout",
        "Source/editorial image layout fit",
        check_status("sourceEditorialLayout"),
        check_detail("sourceEditorialLayout"),
        "For source-first/editorial image renders, record image fit, subject zone, caption zone, crop review, caption-collision, no-overlap, and no black-divider pass verdict for every captioned image scene.",
        check_status("sourceEditorialLayout") == "fail",
    )
    add_criterion(
        "sourceEditorialImageContext",
        "Source/editorial situation-image fit",
        check_status("sourceEditorialImageContext"),
        check_detail("sourceEditorialImageContext"),
        "Give every source-editorial situation a distinct visual identity and a scene-specific image fit review; repeated or mismatched images cannot pass.",
        check_status("sourceEditorialImageContext") == "fail",
    )
    add_criterion(
        "stillImageSourcePolicy",
        "Still image source role is appropriate",
        check_status("stillImageSourcePolicy"),
        check_detail("stillImageSourcePolicy"),
        "Do not use generic web still images as the main visual source for non-meme explainers; replace them with Grok/Gemini/local MP4 or mark stills as support/evidence/reference cards.",
        check_status("stillImageSourcePolicy") == "fail",
    )
    add_criterion(
        "internetSourceAcquisition",
        "Internet source acquisition proof",
        check_status("internetSourceAcquisition"),
        check_detail("internetSourceAcquisition"),
        "Fetch each internet GIF/image/video source into local storage with source URL, local path, sha256, byte size, media kind, and manual source-fit verdict before render proof.",
        check_status("internetSourceAcquisition") == "fail",
    )
    add_criterion(
        "internetSourceContext",
        "Internet source topic and scene fit",
        check_status("internetSourceContext"),
        check_detail("internetSourceContext"),
        "Bind every fetched internet source to an explicit topic, scene purpose, viewer job, and GIF/image choice rationale; do not pass random source dumps.",
        check_status("internetSourceContext") == "fail",
    )
    add_criterion(
        "internetSourceEditorialIntegration",
        "Internet source text/layout integration",
        check_status("internetSourceEditorialIntegration"),
        check_detail("internetSourceEditorialIntegration"),
        "Make subtitle, TTS narration, and layout notes explicitly match the selected internet source context and media choice; repeated boilerplate source notes cannot pass.",
        check_status("internetSourceEditorialIntegration") == "fail",
    )
    add_criterion(
        "topicHookPayoffStructure",
        "Topic, hook, and payoff spine",
        check_status("topicHookPayoffStructure"),
        check_detail("topicHookPayoffStructure"),
        "Define the topic, opening hook, final payoff, and viewer takeaway before attaching internet GIF/image sources; random context-fit source dumps cannot pass.",
        check_status("topicHookPayoffStructure") == "fail",
    )
    add_criterion(
        "sceneSourceIntentBinding",
        "Scene-source intent binding",
        check_status("sceneSourceIntentBinding"),
        check_detail("sceneSourceIntentBinding"),
        "For every internet source scene, record what the source proves, why GIF/video or image is the right medium, and how that claim appears in caption, TTS, or layout.",
        check_status("sceneSourceIntentBinding") == "fail",
    )
    add_criterion(
        "visualFrameReviewEvidence",
        "Contact-sheet/phone-frame visual evidence",
        check_status("visualFrameReviewEvidence"),
        check_detail("visualFrameReviewEvidence"),
        "Add structured contact-sheet or phone-sized frame review evidence confirming source visibility, caption non-occlusion, TTS/caption sync, and a resolved final beat.",
        check_status("visualFrameReviewEvidence") == "fail",
    )
    add_criterion(
        "conversationalCopyStyle",
        "Conversational subtitle/script prompt",
        check_status("conversationalCopyStyle"),
        check_detail("conversationalCopyStyle"),
        "Rewrite source-led subtitles and TTS script with a conversational copy prompt, explicit forbidden phrases, and short-form reference takeaways.",
        check_status("conversationalCopyStyle") == "fail",
    )
    add_criterion(
        "ttsPacingAlignment",
        "TTS pacing and subtitle alignment",
        check_status("ttsPacingAlignment"),
        check_detail("ttsPacingAlignment"),
        "Shorten narration, lengthen scene timing, or revise captions until TTS no longer needs aggressive tempo compression and captions match the spoken density.",
        check_status("ttsPacingAlignment") == "fail",
    )
    add_criterion(
        "sourceLoopRhythm",
        "Intentional source-loop rhythm",
        check_status("sourceLoopRhythm"),
        check_detail("sourceLoopRhythm"),
        "When reusing the same internet GIF/video source as a loop, mark it as an intentional loop group with distinct captions and a loop rhythm review; otherwise replace the repeated asset.",
        check_status("sourceLoopRhythm") == "fail",
    )
    add_criterion(
        "endingPayoff",
        "Ending payoff and pacing",
        check_status("endingPayoff"),
        check_detail("endingPayoff"),
        "Define the final scene as payoff, summary, next-step, loop-close, or callback, with pacing and final-takeaway review so the video does not end abruptly.",
        check_status("endingPayoff") == "fail",
    )
    add_criterion(
        "endingTailPacing",
        "Ending tail hold",
        check_status("endingTailPacing"),
        check_detail("endingTailPacing"),
        "Leave a short visual/BGM tail after the final spoken idea instead of stretching TTS to the exact end of the video.",
        check_status("endingTailPacing") == "fail",
    )
    add_criterion(
        "grokSourceCuration",
        "Grok-main selected take and source provenance",
        check_status("grokSourceCuration"),
        check_detail("grokSourceCuration"),
        "Before publish, every Grok-main scene must carry 2-take comparison, selected MP4 filename, direct-import or already-saved-local provenance, and no rejected source review verdict.",
        True,
    )
    add_criterion(
        "sourceFirstSourceGate",
        "Reference/profile source-first footage gate",
        check_status("sourceFirstSourceGate"),
        check_detail("sourceFirstSourceGate"),
        "Generate/import Grok/Gemini/local model MP4 sources, or fetch context-approved internet GIF/image/video sources, for every reference/profile scene before using local prototype or generic stock fallback footage.",
        True,
    )

    image_fallback_scenes = int(production_summary.get("imageFallbackScenes", 0) or 0)
    image_fallback_blocking_scenes = production_summary.get("sourceFirstBlockingImageFallbackSceneIds") or []
    stock_only = bool(production_summary.get("stockOnly"))
    curated_stock_ready = bool(production_summary.get("curatedStockReady"))
    missing_rationale = production_summary.get("missingRationaleScenes") or []
    missing_continuity = production_summary.get("missingContinuityScenes") or []
    originality_evidence_scenes = production_summary.get("originalityEvidenceScenes") or []
    quality_review_scenes = production_summary.get("qualityReviewScenes") or []
    missing_originality_evidence = production_summary.get("missingOriginalityEvidenceScenes") or []
    missing_quality_review = production_summary.get("missingQualityReviewScenes") or []
    first_hook_ready = bool(production_summary.get("firstSceneHookReady"))
    repeated_visual_asset_scenes = production_summary.get("repeatedVisualAssetScenes") or []
    missing_free_asset_provenance = production_summary.get("missingFreeAssetProvenanceScenes") or []
    missing_free_audio_provenance = production_summary.get("missingFreeAudioProvenanceAssets") or []
    missing_free_audio_credits = production_summary.get("freeAudioCreditMissingAssets") or []
    weak_bgm_selection_assets = production_summary.get("weakBgmSelectionAssets") or []
    placeholder_bgm_assets = production_summary.get("placeholderBgmAssets") or []
    placeholder_bgm_reasons = production_summary.get("placeholderBgmAssetReasons") or {}
    template_source_review = production_review.get("templateSourceReview") or {}
    cut_density_ready = production_summary.get("shortsCutDensityReady") is True
    reference_edit_grammar_ready = production_summary.get("referenceEditGrammarReady") is True
    ai_slop_status = check_status("aiSlopVisualFit")
    stock_ai_fit_status = check_status("stockAiClipFit")
    thumbnail_strength_status = check_status("thumbnailFirstFrameStrength")
    quality_ratchet_status = check_status("qualityRatchet")

    add_criterion(
        "imageFallback",
        "Video-first scene mix",
        "warn" if image_fallback_blocking_scenes else "pass",
        (
            f"imageFallbackScenes={image_fallback_scenes}, "
            f"contextApprovedImageFallbackScenes={production_summary.get('sourceFirstInternetContextSceneIds') or []}, "
            f"blockingImageFallbackScenes={image_fallback_blocking_scenes}"
        ),
        "Replace static fallback scenes with short MP4 clips unless the still frame is context-approved for that scene.",
        False,
    )
    add_criterion(
        "sourceAuthorship",
        "Creator-owned or generated source mix",
        "warn" if stock_only else "pass",
        f"stockOnly={stock_only}, curatedStockReady={curated_stock_ready}",
        "Keep stock-only curated exports as review drafts; add direct upload, Grok handoff, or local Wan/LTX/Hunyuan footage before marking the render publish-ready.",
        False,
    )
    add_criterion(
        "manualSelectionEvidence",
        "Manual source rationale",
        "warn" if missing_rationale else "pass",
        f"missingRationaleScenes={missing_rationale}",
        "Fill source-rationale notes for every scene so stock and generated clips have a selection reason.",
        False,
    )
    add_criterion(
        "continuityEvidence",
        "Scene continuity notes",
        "warn" if missing_continuity else "pass",
        f"missingContinuityScenes={missing_continuity}",
        "Add continuity notes for color, camera motion, subject, and prop consistency across scenes.",
        False,
    )
    add_criterion(
        "firstTwoSecondHook",
        "First two-second hook",
        "pass" if first_hook_ready else "warn",
        f"firstSceneHookReady={first_hook_ready}",
        "Strengthen the first scene with a visible hook note or top-hook caption and an immediate visual payoff.",
        False,
    )
    add_criterion(
        "cutDensityPacing",
        "Shorts cut density and pacing",
        "pass" if cut_density_ready else "warn",
        check_detail("cutDensityPacing"),
        "Use at least four distinct moving clips for short-form operating templates unless a slower visual-led edit is explicitly approved.",
        False,
    )
    add_criterion(
        "referenceEditGrammar",
        "Reference edit grammar reflected",
        "pass" if reference_edit_grammar_ready else "fail",
        check_detail("referenceEditGrammar"),
        "Translate the reference pass into concrete edit grammar: first-two-second hook, 2-3s cut rhythm, caption safe-zone, and platform comparison notes.",
        True,
    )
    add_criterion(
        "aiSlopVisualFit",
        "AI slop / visual artifact fit",
        "fail" if ai_slop_status == "fail" else "pass",
        check_detail("aiSlopVisualFit"),
        "Separate visual artifact, AI-slop, watermark, compression, and subject-fit failures from generic render success before upload review.",
        ai_slop_status == "fail",
    )
    add_criterion(
        "stockAiClipFit",
        "Stock/AI clip source fit",
        "fail" if stock_ai_fit_status == "fail" else "pass",
        check_detail("stockAiClipFit"),
        "Replace mismatched stock/AI clips or record why each clip fits the topic, motion, and continuity.",
        stock_ai_fit_status == "fail",
    )
    add_criterion(
        "thumbnailFirstFrameStrength",
        "Thumbnail / first-frame strength",
        "pass",
        check_detail("thumbnailFirstFrameStrength"),
        "Pick a strong first-frame or thumbnail candidate instead of assuming the render's first frame is channel-ready.",
        False,
    )
    add_criterion(
        "assetReuseDiversity",
        "No repeated visual asset reuse",
        "pass" if not repeated_visual_asset_scenes else "warn",
        f"repeatedVisualAssetScenes={repeated_visual_asset_scenes}",
        "Replace repeated visual assets with distinct free stock/direct/Grok/local clips so the result does not feel recycled.",
        False,
    )
    add_criterion(
        "freeAssetProvenance",
        "Free visual/audio source provenance",
        "pass" if not missing_free_asset_provenance and not missing_free_audio_provenance and not missing_free_audio_credits else "warn",
        (
            f"missingFreeAssetProvenanceScenes={missing_free_asset_provenance}, "
            f"missingFreeAudioProvenanceAssets={missing_free_audio_provenance}, "
            f"freeAudioCreditMissingAssets={missing_free_audio_credits}"
        ),
        "Keep source URL/ID/label for free stock assets and source/license/YouTube description credits for BGM/SFX before publishing.",
        False,
    )
    add_criterion(
        "bgmAssetRotation",
        "BGM selected from reusable free-library candidates",
        "pass" if not weak_bgm_selection_assets else "warn",
        f"weakBgmSelectionAssets={weak_bgm_selection_assets}",
        "Add at least two free/local BGM candidates per mood, or pin an operator-selected free BGM with source/license metadata for this project.",
        False,
    )
    add_criterion(
        "bgmSoundQuality",
        "BGM is not beep/test-tone/procedural",
        "fail" if placeholder_bgm_assets else "pass",
        f"placeholderBgmAssets={placeholder_bgm_assets}, reasons={placeholder_bgm_reasons}",
        "Replace procedural sine, beep, click, lavfi, or test-tone BGM with a real free music bed before upload review.",
        True,
    )
    add_criterion(
        "templateSourcePlan",
        "Template-specific source mix",
        check_status("templateSourcePlan"),
        check_detail("templateSourcePlan"),
        "Match the selected Korean YouTube template with an intentional source mix, free asset plan, and layout proof.",
        False,
    )
    add_criterion(
        "qualityRatchet",
        "Quality iteration ratchet evidence",
        "fail" if quality_ratchet_status == "fail" else "pass",
        check_detail("qualityRatchet"),
        "Record previousBaseline, rejectionCause, changedLever, expectedVisibleImprovement, actualProof, and nextRatchet before treating a quality iteration as improved.",
        quality_ratchet_status == "fail",
    )

    passed = sum(1 for item in criteria if item["status"] == "pass")
    total = len(criteria)
    if required_fixes:
        status = "blocked"
    elif recommended_fixes:
        status = "needs-rework"
    else:
        status = "ready"

    return {
        "status": status,
        "score": {"passed": passed, "total": total},
        "requiredFixes": required_fixes,
        "recommendedFixes": recommended_fixes,
        "strengths": strengths[:6],
        "criteria": criteria,
        "summary": {
            "placeholderCount": int(local_media_summary.get("placeholder", 0) or 0),
            "imageFallbackScenes": image_fallback_scenes,
            "stockOnly": stock_only,
            "curatedStockReady": curated_stock_ready,
            "missingRationaleScenes": missing_rationale,
            "missingContinuityScenes": missing_continuity,
            "firstSceneHookReady": first_hook_ready,
            "repeatedVisualAssetScenes": repeated_visual_asset_scenes,
            "missingFreeAssetProvenanceScenes": missing_free_asset_provenance,
            "missingFreeAudioProvenanceAssets": missing_free_audio_provenance,
            "weakBgmSelectionAssets": weak_bgm_selection_assets,
            "placeholderBgmAssets": placeholder_bgm_assets,
            "placeholderBgmAssetReasons": placeholder_bgm_reasons,
            "proceduralPlaceholderScenes": procedural_placeholder_scenes,
            "missingGrokSourceCurationScenes": production_summary.get("missingGrokSourceCurationScenes") or [],
            "grokSourceCurationReadyScenes": production_summary.get("grokSourceCurationReadyScenes") or [],
            "rejectedGrokSourceReviewScenes": production_summary.get("rejectedGrokSourceReviewScenes") or [],
            "templateSourceReview": template_source_review,
        },
    }


def _audio_design_ready(production_summary: dict) -> bool:
    """Accept either real voiceover narration or explicit no-voice audio design."""
    return not (
        production_summary.get("missingNarrationScenes")
        or production_summary.get("thinNarrationScenes")
        or production_summary.get("productionMetaNarrationScenes")
        or production_summary.get("productionMetaSubtitleScenes")
        or production_summary.get("voiceoverRequiredNoVoiceScenes")
        or production_summary.get("missingNoVoiceAudioScenes")
        or production_summary.get("missingNoVoiceAudioReviewScenes")
    )


def _build_channel_readiness(
    checks: dict,
    publish_readiness: dict,
    production_review: dict,
    local_media_summary: dict,
) -> dict:
    """Grade whether a publish-ready render has enough original footage proof for channel use."""
    production_summary = production_review.get("summary") or {}
    publish_status = str(publish_readiness.get("status") or "needs-rework")
    criteria: list[dict] = []
    required_fixes: list[str] = []
    recommended_fixes: list[str] = []
    strengths: list[str] = []

    def add_criterion(
        key: str,
        label: str,
        status: str,
        detail: str,
        fix: str,
        required: bool,
    ) -> None:
        criteria.append(
            {
                "key": key,
                "label": label,
                "status": status,
                "detail": detail,
                "required": required,
            }
        )
        if status == "fail" and required:
            required_fixes.append(fix)
        elif status in {"fail", "warn"} and not required:
            recommended_fixes.append(fix)
        elif status == "pass":
            strengths.append(label)

    def check_status(key: str) -> str:
        return str((checks.get(key) or {}).get("status") or "warn")

    def check_detail(key: str) -> str:
        return str((checks.get(key) or {}).get("detail") or "")

    uploaded_video_scenes = int(production_summary.get("uploadedVideoScenes", 0) or 0)
    grok_handoff_scenes = int(production_summary.get("grokHandoffScenes", 0) or 0)
    local_model_video_scenes = int(production_summary.get("localModelVideoScenes", 0) or 0)
    stock_video_scenes = int(production_summary.get("stockVideoScenes", 0) or 0)
    total_scenes = int(production_summary.get("totalScenes", 0) or 0)
    original_clip_scene_ids = [str(item) for item in production_summary.get("originalClipSceneIds") or []]
    gemini_handoff_scenes = int(production_summary.get("geminiHandoffScenes", 0) or 0)
    internet_source_proof_mode = bool(production_summary.get("internetSourceProofMode"))
    internet_motion_source_scene_ids = [str(item) for item in production_summary.get("internetMotionSourceSceneIds") or []]
    internet_context_source_scene_ids = [str(item) for item in production_summary.get("internetContextSourceSceneIds") or []]
    source_proof_clip_scene_ids = sorted(
        set(original_clip_scene_ids + internet_motion_source_scene_ids + internet_context_source_scene_ids)
    ) if internet_source_proof_mode else original_clip_scene_ids
    original_clip_scenes = len(source_proof_clip_scene_ids)
    ai_or_web_clip_scenes = grok_handoff_scenes + gemini_handoff_scenes + (
        len(set(internet_motion_source_scene_ids + internet_context_source_scene_ids))
        if internet_source_proof_mode
        else 0
    )
    review_scenes = production_review.get("scenes") or []
    first_scene_id = str((review_scenes[0] if review_scenes else {}).get("sceneId") or "scene-01")
    grok_handoff_scene_ids = [str(item) for item in production_summary.get("grokHandoffSceneIds") or []]
    gemini_handoff_scene_ids = [str(item) for item in production_summary.get("geminiHandoffSceneIds") or []]
    local_model_video_scene_ids = [str(item) for item in production_summary.get("localModelVideoSceneIds") or []]
    weak_uploaded_originality_scenes = production_summary.get("weakUploadedOriginalityScenes") or []
    procedural_placeholder_scenes = production_summary.get("proceduralPlaceholderScenes") or []
    stock_only = bool(production_summary.get("stockOnly"))
    curated_stock_ready = bool(production_summary.get("curatedStockReady"))
    missing_rationale = production_summary.get("missingRationaleScenes") or []
    missing_continuity = production_summary.get("missingContinuityScenes") or []
    originality_evidence_scenes = production_summary.get("originalityEvidenceScenes") or []
    quality_review_scenes = production_summary.get("qualityReviewScenes") or []
    visual_verdict_scenes = production_summary.get("visualVerdictScenes") or []
    missing_originality_evidence = production_summary.get("missingOriginalityEvidenceScenes") or []
    missing_quality_review = production_summary.get("missingQualityReviewScenes") or []
    missing_visual_verdict = production_summary.get("missingVisualVerdictScenes") or []
    failed_visual_verdict = production_summary.get("failedVisualVerdictScenes") or []
    first_hook_ready = bool(production_summary.get("firstSceneHookReady"))
    narration_ready = _audio_design_ready(production_summary)
    caption_layout_ready = (
        not production_summary.get("missingCaptionLayoutReviewScenes")
        and not production_summary.get("captionSparsePlan")
        and not production_summary.get("longTopHookScenes")
    )
    reference_edit_grammar_ready = production_summary.get("referenceEditGrammarReady") is True
    visual_verdict_ready = total_scenes > 0 and len(visual_verdict_scenes) == total_scenes and not failed_visual_verdict
    asset_diversity_ready = not production_summary.get("repeatedVisualAssetScenes")
    free_asset_provenance_ready = (
        not production_summary.get("missingFreeAssetProvenanceScenes")
        and not production_summary.get("missingFreeAudioProvenanceAssets")
        and not production_summary.get("freeAudioCreditMissingAssets")
    )
    placeholder_bgm_assets = production_summary.get("placeholderBgmAssets") or []
    bgm_rotation_ready = not production_summary.get("weakBgmSelectionAssets") and not placeholder_bgm_assets
    template_source_review = production_review.get("templateSourceReview") or {}
    template_source_ready = template_source_review.get("status") == "pass"
    provider_consistency_ready = check_status("providerConsistency") == "pass"
    anti_ai_naturalness_ready = check_status("antiAiNaturalness") == "pass"
    caption_system_ready = check_status("captionSystem") == "pass"
    viewer_takeaway_ready = check_status("viewerTakeaway") == "pass"
    internet_source_editorial_integration_ready = check_status("internetSourceEditorialIntegration") == "pass"
    conversational_copy_style_ready = check_status("conversationalCopyStyle") == "pass"
    tts_pacing_alignment_ready = check_status("ttsPacingAlignment") == "pass"
    source_loop_rhythm_ready = check_status("sourceLoopRhythm") == "pass"
    ending_tail_pacing_ready = check_status("endingTailPacing") == "pass"
    audio_mix_review_ready = bool(production_summary.get("audioMixReviewScenes"))
    platform_comparison_ready = bool(production_summary.get("platformComparisonScenes"))
    hero_original_clip_ready = first_scene_id in source_proof_clip_scene_ids
    hero_originality_evidence_ready = first_scene_id in originality_evidence_scenes or (
        internet_source_proof_mode and first_scene_id in source_proof_clip_scene_ids
    )
    hero_ai_or_web_ready = (
        first_scene_id in grok_handoff_scene_ids
        or first_scene_id in gemini_handoff_scene_ids
        or first_scene_id in local_model_video_scene_ids
        or (internet_source_proof_mode and first_scene_id in source_proof_clip_scene_ids)
    )

    add_criterion(
        "publishGate",
        "Publish gate already passed",
        "pass" if publish_status == "ready" else "fail",
        f"publishReadiness={publish_status}",
        "Resolve publishReadiness required and recommended fixes before channel-level review.",
        True,
    )
    add_criterion(
        "originalFootageMix",
        "Original or handoff MP4 present",
        "pass" if original_clip_scenes > 0 else "fail",
        (
            f"originalClipScenes={original_clip_scenes}, stockVideoScenes={stock_video_scenes}, "
            f"uploadedVideoScenes={uploaded_video_scenes}, totalScenes={total_scenes}, "
            f"weakUploadedOriginalityScenes={weak_uploaded_originality_scenes}, "
            f"proceduralPlaceholderScenes={procedural_placeholder_scenes}"
        ),
        "Add or prove at least one owned/direct upload, Grok app/web handoff, or local Wan/LTX/Hunyuan MP4 clip before treating this as channel-ready original work.",
        True,
    )
    add_criterion(
        "heroOriginalFootage",
        "First hook scene uses original MP4",
        "pass" if hero_original_clip_ready else "fail",
        f"firstSceneId={first_scene_id}, originalClipSceneIds={original_clip_scene_ids}",
        "Move a direct upload, Grok app/web handoff, or Gemini/Veo web handoff MP4 into the first hook scene before channel upload.",
        True,
    )
    add_criterion(
        "heroOriginalityEvidence",
        "Hero clip originality evidence",
        "pass" if hero_originality_evidence_ready else "fail",
        (
            f"firstSceneId={first_scene_id}, "
            f"originalityEvidenceScenes={originality_evidence_scenes}, "
            f"missingOriginalityEvidenceScenes={missing_originality_evidence}, "
            f"weakUploadedOriginalityScenes={weak_uploaded_originality_scenes}, "
            f"proceduralPlaceholderScenes={procedural_placeholder_scenes}"
        ),
        "Add explicit evidence that the first hook MP4 is direct footage, a Grok app/web handoff, or a Gemini/Veo web handoff, including prompt/source notes.",
        True,
    )
    add_criterion(
        "channelQualityReview",
        "Per-scene channel quality review",
        "pass" if total_scenes > 0 and len(quality_review_scenes) == total_scenes else "fail",
        f"qualityReviewScenes={quality_review_scenes}, missingQualityReviewScenes={missing_quality_review}",
        "Complete channel quality review notes for every scene: subject visibility, caption occlusion, watermark/compression, cut continuity, and platform fit.",
        True,
    )
    add_criterion(
        "manualVisualVerdict",
        "Explicit pass/fail visual verdict",
        "pass" if visual_verdict_ready else "fail",
        (
            f"visualVerdictScenes={visual_verdict_scenes}, "
            f"missingVisualVerdictScenes={missing_visual_verdict}, "
            f"failedVisualVerdictScenes={failed_visual_verdict}"
        ),
        "Watch the render/contact sheet and set an explicit visualQualityVerdict=pass per scene; free-text notes alone cannot mark a weak video channel-ready.",
        True,
    )
    add_criterion(
        "ttsNarrationEvidence",
        "Audio design or viewer-facing narration present",
        "pass" if narration_ready else "fail",
        (
            f"narrationScenes={production_summary.get('narrationScenes') or []}, "
            f"subtitleOnlyNarrationScenes={production_summary.get('subtitleOnlyNarrationScenes') or []}, "
            f"missingNarrationScenes={production_summary.get('missingNarrationScenes') or []}, "
            f"thinNarrationScenes={production_summary.get('thinNarrationScenes') or []}, "
            f"shortVoiceoverCalloutScenes={production_summary.get('shortVoiceoverCalloutScenes') or []}, "
            f"finalPayoffShortNarrationScenes={production_summary.get('finalPayoffShortNarrationScenes') or []}, "
            f"noVoiceAudioDesignScenes={production_summary.get('noVoiceAudioDesignScenes') or []}, "
            f"voiceoverRequiredNoVoiceScenes={production_summary.get('voiceoverRequiredNoVoiceScenes') or []}, "
            f"visualLedNoVoiceApprovedScenes={production_summary.get('visualLedNoVoiceApprovedScenes') or []}, "
            f"missingNoVoiceAudioScenes={production_summary.get('missingNoVoiceAudioScenes') or []}, "
            f"missingNoVoiceAudioReviewScenes={production_summary.get('missingNoVoiceAudioReviewScenes') or []}, "
            f"productionMetaNarrationScenes={production_summary.get('productionMetaNarrationScenes') or []}, "
            f"requiredChars={production_summary.get('narrationMinCharsByScene') or {}}"
        ),
        "Use viewer-facing Edge/Windows TTS only when narration helps; otherwise mark an intentional no-voice design with BGM/native audio and mix review evidence.",
        True,
    )
    add_criterion(
        "bgmSoundQuality",
        "BGM is not beep/test-tone/procedural",
        "pass" if not placeholder_bgm_assets else "fail",
        (
            f"placeholderBgmAssets={placeholder_bgm_assets}, "
            f"reasons={production_summary.get('placeholderBgmAssetReasons') or {}}"
        ),
        "Replace procedural sine, beep, click, lavfi, or test-tone BGM with a real free music bed before upload review.",
        True,
    )
    add_criterion(
        "captionLayoutReview",
        "Caption layout does not cover subject/UI",
        "pass" if caption_layout_ready else "fail",
        (
            f"missingCaptionLayoutReviewScenes={production_summary.get('missingCaptionLayoutReviewScenes') or []}, "
            f"captionSparsePlan={production_summary.get('captionSparsePlan')}, "
            f"longTopHookScenes={production_summary.get('longTopHookScenes') or []}"
        ),
        "Record caption layout review, avoid one long hook plus empty caption plan, and keep lower-info y<=1536 / right-side danger zone clear.",
        True,
    )
    add_criterion(
        "providerConsistency",
        "Provider mode is channel-safe",
        "pass" if provider_consistency_ready else "fail",
        check_detail("providerConsistency"),
        "Use Grok-only or Gemini-only for upload candidates; keep local-only as proof/fallback and block unexplained mixed-provider output.",
        True,
    )
    add_criterion(
        "antiAiNaturalness",
        "Anti-AI naturalness review",
        "pass" if anti_ai_naturalness_ready else "fail",
        check_detail("antiAiNaturalness"),
        "Record that scenes do not read as generic AI samples, same-world continuity is intact, and every action has a human reason.",
        True,
    )
    add_criterion(
        "captionSystem",
        "Caption position and purpose system",
        "pass" if caption_system_ready else "fail",
        check_detail("captionSystem"),
        "Fix caption position and purpose across scenes before channel review; random caption movement is not channel-ready.",
        True,
    )
    add_criterion(
        "viewerTakeaway",
        "Viewer takeaway is recorded",
        "pass" if viewer_takeaway_ready else "fail",
        check_detail("viewerTakeaway"),
        "Record what the viewer understands, what action they can take, and what feeling/state remains.",
        True,
    )
    add_criterion(
        "internetSourceEditorialIntegration",
        "Internet source drives text and layout",
        "pass" if internet_source_editorial_integration_ready else "fail",
        check_detail("internetSourceEditorialIntegration"),
        "When internet GIF/image sources are used, the subtitle, TTS, and layout note must all point back to the same scene context and media choice.",
        True,
    )
    add_criterion(
        "conversationalCopyStyle",
        "Subtitles and TTS sound spoken",
        "pass" if conversational_copy_style_ready else "fail",
        check_detail("conversationalCopyStyle"),
        "When source-led scenes use TTS, the prompt and viewer copy must be conversational, not report-style or production-label copy.",
        True,
    )
    add_criterion(
        "ttsPacingAlignment",
        "TTS pace matches caption density",
        "pass" if tts_pacing_alignment_ready else "fail",
        check_detail("ttsPacingAlignment"),
        "Keep TTS at a natural pace and make captions substantial enough that voiceover and on-screen text feel like the same edit.",
        True,
    )
    add_criterion(
        "sourceLoopRhythm",
        "Repeated source loops are intentional",
        "pass" if source_loop_rhythm_ready else "fail",
        check_detail("sourceLoopRhythm"),
        "Approve repeated GIF/video source loops only when the repeat has a distinct caption beat and documented loop rhythm.",
        True,
    )
    add_criterion(
        "endingTailPacing",
        "Final beat has breathing room",
        "pass" if ending_tail_pacing_ready else "fail",
        check_detail("endingTailPacing"),
        "Leave a short visual/BGM tail after the final spoken idea so channel candidates do not stop abruptly.",
        True,
    )
    add_criterion(
        "referenceEditGrammar",
        "Reference edit grammar is reflected in the edit",
        "pass" if reference_edit_grammar_ready else "fail",
        (
            f"ready={reference_edit_grammar_ready}, "
            f"avgSceneDurationSec={production_summary.get('averageSceneDurationSec')}, "
            f"missingReferenceEditGrammarScenes={production_summary.get('missingReferenceEditGrammarScenes') or []}, "
            f"longHoldSceneIds={production_summary.get('longHoldSceneIds') or []}, "
            f"issues={production_summary.get('referenceEditGrammarIssues') or []}"
        ),
        "Apply researched Shorts/Reels/TikTok grammar as render data: first-two-second hook, 2-3s cut rhythm, caption safe-zone, and platform comparison evidence.",
        True,
    )
    add_criterion(
        "assetReuseDiversity",
        "Distinct visual assets across scenes",
        "pass" if asset_diversity_ready else "fail",
        f"repeatedVisualAssetScenes={production_summary.get('repeatedVisualAssetScenes') or []}",
        "Replace repeated clip/image reuse with distinct free stock, direct, Grok, or local-model assets.",
        True,
    )
    add_criterion(
        "freeAssetProvenance",
        "Free asset source/license provenance",
        "pass" if free_asset_provenance_ready else "fail",
        (
            f"missingFreeAssetProvenanceScenes={production_summary.get('missingFreeAssetProvenanceScenes') or []}, "
            f"missingFreeAudioProvenanceAssets={production_summary.get('missingFreeAudioProvenanceAssets') or []}, "
            f"freeAudioCreditMissingAssets={production_summary.get('freeAudioCreditMissingAssets') or []}"
        ),
        "Keep source URL/ID/label for each free stock scene and BGM/SFX source/license/description-credit notes so the operator can verify rights and avoid blind reuse.",
        True,
    )
    add_criterion(
        "bgmAssetRotation",
        "BGM rotation evidence",
        "pass" if bgm_rotation_ready else "warn",
        (
            f"weakBgmSelectionAssets={production_summary.get('weakBgmSelectionAssets') or []}, "
            f"placeholderBgmAssets={placeholder_bgm_assets}"
        ),
        "Use at least two free/local BGM candidates per mood, or keep an operator-pinned BGM choice with source/license metadata before final upload review.",
        False,
    )
    add_criterion(
        "aiOrLocalClipEvidence",
        "Grok or Gemini web clip evidence",
        "pass" if ai_or_web_clip_scenes > 0 else "warn",
        f"grokHandoffScenes={grok_handoff_scenes}, geminiHandoffScenes={gemini_handoff_scenes}, localModelVideoScenes={local_model_video_scenes}",
        "For upload candidates, prefer Grok app/web or Gemini/Veo web MP4 evidence; local-only remains a proof/fallback path.",
        False,
    )
    add_criterion(
        "heroAiOrLocalEvidence",
        "First hook has Grok/Gemini web option",
        "pass" if hero_ai_or_web_ready else "warn",
        (
            f"firstSceneId={first_scene_id}, grokHandoffSceneIds={grok_handoff_scene_ids}, "
            f"geminiHandoffSceneIds={gemini_handoff_scene_ids}, localModelVideoSceneIds={local_model_video_scene_ids}"
        ),
        "For AI-assisted channel targets, prefer the first hook scene as a Grok app/web or Gemini/Veo web MP4.",
        False,
    )
    add_criterion(
        "manualCurationEvidence",
        "Manual curation notes complete",
        "pass" if not missing_rationale and not missing_continuity else "warn",
        f"missingRationaleScenes={missing_rationale}, missingContinuityScenes={missing_continuity}",
        "Complete source rationale and continuity notes for every scene before channel release.",
        False,
    )
    add_criterion(
        "firstTwoSecondHook",
        "First two-second hook survives channel review",
        "pass" if first_hook_ready else "warn",
        f"firstSceneHookReady={first_hook_ready}",
        "Tighten the first two seconds with an immediate visual payoff and a safe-zone hook.",
        False,
    )
    add_criterion(
        "stockOnlyOriginality",
        "Not stock-only",
        "pass" if not stock_only else "warn",
        f"stockOnly={stock_only}, curatedStockReady={curated_stock_ready}",
        "Keep curated stock as support footage, but add original/direct/Grok/local footage for a channel-owned final.",
        False,
    )
    add_criterion(
        "audioMixReview",
        "Audio mix review recorded",
        "pass" if audio_mix_review_ready else "warn",
        f"audioMixReviewScenes={production_summary.get('audioMixReviewScenes') or []}",
        "Watch once with headphones and speakers; confirm BGM/native audio is audible, and confirm narration stays intelligible when voiceover is used.",
        False,
    )
    add_criterion(
        "platformComparison",
        "Korean YouTube reference comparison recorded",
        "pass" if platform_comparison_ready else "warn",
        f"platformComparisonScenes={production_summary.get('platformComparisonScenes') or []}",
        "Compare hook, pacing, caption scale, and asset fit against current Korean Shorts/long-form references before upload.",
        False,
    )

    recommended_fixes.append(
        "Before upload, review thumbnail/first-frame choice and audio mix against the final platform target."
    )

    passed = sum(1 for item in criteria if item["status"] == "pass")
    total = len(criteria)
    if publish_status == "blocked":
        status = "blocked"
    elif publish_status != "ready":
        status = "needs-publish-rework"
    elif original_clip_scenes == 0 and weak_uploaded_originality_scenes:
        status = "needs-originality-proof"
    elif original_clip_scenes == 0:
        status = "needs-original-footage"
    elif not hero_original_clip_ready:
        status = "needs-hero-original-footage"
    elif not hero_originality_evidence_ready:
        status = "needs-originality-proof"
    elif total_scenes <= 0 or len(quality_review_scenes) != total_scenes:
        status = "needs-quality-review"
    elif not visual_verdict_ready:
        status = "needs-visual-verdict"
    elif (
        not narration_ready
        or not caption_layout_ready
        or not reference_edit_grammar_ready
        or not asset_diversity_ready
        or not free_asset_provenance_ready
        or not template_source_ready
        or not provider_consistency_ready
        or not anti_ai_naturalness_ready
        or not caption_system_ready
        or not viewer_takeaway_ready
        or not internet_source_editorial_integration_ready
        or not conversational_copy_style_ready
        or not tts_pacing_alignment_ready
        or not source_loop_rhythm_ready
        or not ending_tail_pacing_ready
    ):
        status = "needs-top-tier-evidence"
    else:
        status = "channel-ready"

    return {
        "status": status,
        "score": {"passed": passed, "total": total},
        "requiredFixes": required_fixes,
        "recommendedFixes": recommended_fixes,
        "strengths": strengths[:6],
        "criteria": criteria,
        "summary": {
            "publishStatus": publish_status,
            "totalScenes": total_scenes,
            "originalClipScenes": original_clip_scenes,
            "firstSceneId": first_scene_id,
            "heroOriginalClipReady": hero_original_clip_ready,
            "heroOriginalityEvidenceReady": hero_originality_evidence_ready,
            "heroAiOrLocalReady": hero_ai_or_web_ready,
            "originalClipSceneIds": original_clip_scene_ids,
            "sourceProofClipSceneIds": source_proof_clip_scene_ids,
            "internetSourceProofMode": internet_source_proof_mode,
            "internetMotionSourceSceneIds": internet_motion_source_scene_ids,
            "internetContextSourceSceneIds": internet_context_source_scene_ids,
            "weakUploadedOriginalityScenes": weak_uploaded_originality_scenes,
            "proceduralPlaceholderScenes": procedural_placeholder_scenes,
            "grokHandoffSceneIds": grok_handoff_scene_ids,
            "geminiHandoffSceneIds": gemini_handoff_scene_ids,
            "localModelVideoSceneIds": local_model_video_scene_ids,
            "uploadedVideoScenes": uploaded_video_scenes,
            "grokHandoffScenes": grok_handoff_scenes,
            "geminiHandoffScenes": gemini_handoff_scenes,
            "localModelVideoScenes": local_model_video_scenes,
            "stockVideoScenes": stock_video_scenes,
            "stockOnly": stock_only,
            "curatedStockReady": curated_stock_ready,
            "missingRationaleScenes": missing_rationale,
            "missingContinuityScenes": missing_continuity,
            "missingOriginalityEvidenceScenes": missing_originality_evidence,
            "missingQualityReviewScenes": missing_quality_review,
            "missingVisualVerdictScenes": missing_visual_verdict,
            "failedVisualVerdictScenes": failed_visual_verdict,
            "originalityEvidenceScenes": originality_evidence_scenes,
            "qualityReviewScenes": quality_review_scenes,
            "visualVerdictScenes": visual_verdict_scenes,
            "firstSceneHookReady": first_hook_ready,
            "narrationReady": narration_ready,
            "captionLayoutReady": caption_layout_ready,
            "referenceEditGrammarReady": reference_edit_grammar_ready,
            "visualVerdictReady": visual_verdict_ready,
            "assetDiversityReady": asset_diversity_ready,
            "freeAssetProvenanceReady": free_asset_provenance_ready,
            "bgmSoundReady": not placeholder_bgm_assets,
            "placeholderBgmAssets": placeholder_bgm_assets,
            "bgmRotationReady": bgm_rotation_ready,
            "templateSourceReady": template_source_ready,
            "providerConsistencyReady": provider_consistency_ready,
            "antiAiNaturalnessReady": anti_ai_naturalness_ready,
            "captionSystemReady": caption_system_ready,
            "viewerTakeawayReady": viewer_takeaway_ready,
            "internetSourceEditorialIntegrationReady": internet_source_editorial_integration_ready,
            "conversationalCopyStyleReady": conversational_copy_style_ready,
            "ttsPacingAlignmentReady": tts_pacing_alignment_ready,
            "sourceLoopRhythmReady": source_loop_rhythm_ready,
            "endingTailPacingReady": ending_tail_pacing_ready,
            "audioMixReviewReady": audio_mix_review_ready,
            "platformComparisonReady": platform_comparison_ready,
            "placeholderCount": int(local_media_summary.get("placeholder", 0) or 0),
        },
    }


def _build_upload_review(
    checks: dict,
    publish_readiness: dict,
    channel_readiness: dict,
    production_review: dict,
) -> dict:
    """Create a final human upload checklist for platform-facing review."""
    production_summary = production_review.get("summary") or {}
    channel_summary = channel_readiness.get("summary") or {}
    publish_status = str(publish_readiness.get("status") or "needs-rework")
    channel_status = str(channel_readiness.get("status") or "needs-review")
    criteria: list[dict] = []
    required_fixes: list[str] = []
    manual_reviews: list[str] = []
    strengths: list[str] = []

    def add_criterion(
        key: str,
        label: str,
        status: str,
        detail: str,
        fix: str,
        required: bool,
    ) -> None:
        criteria.append(
            {
                "key": key,
                "label": label,
                "status": status,
                "detail": detail,
                "required": required,
            }
        )
        if status == "fail" and required:
            required_fixes.append(fix)
        elif status in {"fail", "warn"} and not required:
            manual_reviews.append(fix)
        elif status == "pass":
            strengths.append(label)

    def check_status(key: str) -> str:
        return str((checks.get(key) or {}).get("status") or "warn")

    def check_detail(key: str) -> str:
        return str((checks.get(key) or {}).get("detail") or "")

    first_scene_id = str(channel_summary.get("firstSceneId") or "scene-01")
    hero_original_ready = channel_summary.get("heroOriginalClipReady") is True
    hero_evidence_ready = channel_summary.get("heroOriginalityEvidenceReady") is True
    hero_ai_or_local_ready = channel_summary.get("heroAiOrLocalReady") is True
    total_scenes = int(production_summary.get("totalScenes", 0) or 0)
    content_template = str(
        production_summary.get("contentTemplate")
        or (production_review.get("templateSourceReview") or {}).get("template")
        or ""
    ).strip()
    uploaded_video_scenes = int(production_summary.get("uploadedVideoScenes", 0) or 0)
    grok_handoff_scenes = int(production_summary.get("grokHandoffScenes", 0) or 0)
    local_model_video_scenes = int(production_summary.get("localModelVideoScenes", 0) or 0)
    stock_video_scenes = int(production_summary.get("stockVideoScenes", 0) or 0)
    original_clip_scene_ids = [str(item) for item in production_summary.get("originalClipSceneIds") or []]
    internet_source_proof_mode = bool(production_summary.get("internetSourceProofMode"))
    internet_motion_source_scene_ids = [str(item) for item in production_summary.get("internetMotionSourceSceneIds") or []]
    internet_context_source_scene_ids = [str(item) for item in production_summary.get("internetContextSourceSceneIds") or []]
    source_proof_clip_scene_ids = sorted(
        set(original_clip_scene_ids + internet_motion_source_scene_ids + internet_context_source_scene_ids)
    ) if internet_source_proof_mode else original_clip_scene_ids
    original_clip_scenes = len(set(source_proof_clip_scene_ids))
    min_original_scene_count = 1 if total_scenes <= 1 else max(2, (total_scenes + 1) // 2)
    source_mix_required = total_scenes > 1 and content_template in UPLOAD_SOURCE_MIX_REQUIRED_TEMPLATES
    original_source_mix_ready = original_clip_scenes >= min_original_scene_count
    quality_review_scenes = production_summary.get("qualityReviewScenes") or []
    visual_verdict_scenes = production_summary.get("visualVerdictScenes") or []
    missing_visual_verdict = production_summary.get("missingVisualVerdictScenes") or []
    failed_visual_verdict = production_summary.get("failedVisualVerdictScenes") or []
    first_hook_ready = production_summary.get("firstSceneHookReady") is True
    thumbnail_review_scenes = production_summary.get("thumbnailReviewScenes") or []
    audio_mix_review_scenes = production_summary.get("audioMixReviewScenes") or []
    platform_comparison_scenes = production_summary.get("platformComparisonScenes") or []
    thumbnail_review_ready = first_scene_id in thumbnail_review_scenes
    audio_mix_review_ready = bool(audio_mix_review_scenes)
    platform_comparison_ready = bool(platform_comparison_scenes)
    narration_ready = _audio_design_ready(production_summary)
    caption_layout_ready = (
        not production_summary.get("missingCaptionLayoutReviewScenes")
        and not production_summary.get("captionSparsePlan")
        and not production_summary.get("longTopHookScenes")
    )
    reference_edit_grammar_ready = production_summary.get("referenceEditGrammarReady") is True
    visual_verdict_ready = total_scenes > 0 and len(visual_verdict_scenes) == total_scenes and not failed_visual_verdict
    asset_diversity_ready = not production_summary.get("repeatedVisualAssetScenes")
    free_asset_provenance_ready = (
        not production_summary.get("missingFreeAssetProvenanceScenes")
        and not production_summary.get("missingFreeAudioProvenanceAssets")
        and not production_summary.get("freeAudioCreditMissingAssets")
    )
    placeholder_bgm_assets = production_summary.get("placeholderBgmAssets") or []
    bgm_rotation_ready = not production_summary.get("weakBgmSelectionAssets") and not placeholder_bgm_assets
    template_source_review = production_review.get("templateSourceReview") or {}
    template_source_ready = template_source_review.get("status") == "pass"
    provider_consistency_ready = check_status("providerConsistency") == "pass"
    anti_ai_naturalness_ready = check_status("antiAiNaturalness") == "pass"
    caption_system_ready = check_status("captionSystem") == "pass"
    viewer_takeaway_ready = check_status("viewerTakeaway") == "pass"
    internet_source_editorial_integration_ready = check_status("internetSourceEditorialIntegration") == "pass"
    conversational_copy_style_ready = check_status("conversationalCopyStyle") == "pass"
    tts_pacing_alignment_ready = check_status("ttsPacingAlignment") == "pass"
    source_loop_rhythm_ready = check_status("sourceLoopRhythm") == "pass"
    ending_tail_pacing_ready = check_status("endingTailPacing") == "pass"

    add_criterion(
        "publishPacketReady",
        "Publish packet gate passed",
        "pass" if publish_status == "ready" else "fail",
        f"publishReadiness={publish_status}",
        "Resolve publishReadiness before creating an upload candidate.",
        True,
    )
    add_criterion(
        "channelPacketReady",
        "Channel originality gate passed",
        "pass" if channel_status == "channel-ready" else "fail",
        f"channelReadiness={channel_status}",
        "Create a channel-ready packet with first-scene original MP4 evidence before upload.",
        True,
    )
    add_criterion(
        "firstFrameHook",
        "First-frame / first 2s hook",
        "pass" if first_hook_ready and hero_original_ready else "fail",
        f"firstSceneId={first_scene_id}, firstSceneHookReady={first_hook_ready}, heroOriginalClipReady={hero_original_ready}",
        "Make the first scene the strongest original moving hook before choosing a thumbnail or first frame.",
        True,
    )
    add_criterion(
        "cutDensityPacing",
        "Cut density is short-form ready",
        "pass" if check_status("cutDensityPacing") == "pass" else "fail",
        check_detail("cutDensityPacing"),
        "Increase clip count or reduce repeated/static sections so the edit does not feel like a low-density slideshow.",
        True,
    )
    add_criterion(
        "aiSlopVisualFit",
        "AI slop / visual artifact fit",
        check_status("aiSlopVisualFit"),
        check_detail("aiSlopVisualFit"),
        "Block upload when visual verdicts flag AI slop, watermark/compression artifacts, subject mismatch, or weak source fit.",
        True,
    )
    add_criterion(
        "stockAiClipFit",
        "Stock/AI clip fit",
        check_status("stockAiClipFit"),
        check_detail("stockAiClipFit"),
        "Replace mismatched stock/AI clips or record stronger source-fit notes before upload.",
        True,
    )
    add_criterion(
        "providerConsistency",
        "Provider mode is upload-candidate safe",
        check_status("providerConsistency"),
        check_detail("providerConsistency"),
        "Keep upload candidates provider-homogeneous: Grok-only or Gemini-only. Local-only stays proof/fallback only.",
        True,
    )
    add_criterion(
        "antiAiNaturalness",
        "Naturalness is reviewed",
        check_status("antiAiNaturalness"),
        check_detail("antiAiNaturalness"),
        "Block upload when scenes still read like generic AI samples, ad footage, or unexplained pretty transitions.",
        True,
    )
    add_criterion(
        "captionSystem",
        "Caption system is fixed and purposeful",
        check_status("captionSystem"),
        check_detail("captionSystem"),
        "Fix caption position/purpose before upload; random top/center/lower movement makes the edit feel automated.",
        True,
    )
    add_criterion(
        "viewerTakeaway",
        "Viewer takeaway is clear",
        check_status("viewerTakeaway"),
        check_detail("viewerTakeaway"),
        "Do not upload until the render records what the viewer understands, what they can do, and what feeling/state remains.",
        True,
    )
    add_criterion(
        "internetSourceEditorialIntegration",
        "Internet source controls subtitle/TTS/layout",
        "pass" if internet_source_editorial_integration_ready else "fail",
        check_detail("internetSourceEditorialIntegration"),
        "Rewrite source-led scenes until the selected GIF/image source is reflected in the viewer-facing caption, TTS, and layout note.",
        True,
    )
    add_criterion(
        "conversationalCopyStyle",
        "Subtitles and TTS are conversational",
        "pass" if conversational_copy_style_ready else "fail",
        check_detail("conversationalCopyStyle"),
        "Rewrite upload-facing subtitles and TTS so they sound spoken, avoid report-style Korean endings, and follow the recorded short-form reference takeaways.",
        True,
    )
    add_criterion(
        "ttsPacingAlignment",
        "TTS pace matches caption density",
        "pass" if tts_pacing_alignment_ready else "fail",
        check_detail("ttsPacingAlignment"),
        "Upload review must block rap-speed TTS or overly tiny captions that do not match the spoken script.",
        True,
    )
    add_criterion(
        "sourceLoopRhythm",
        "Repeated GIF/video loops are deliberate",
        "pass" if source_loop_rhythm_ready else "fail",
        check_detail("sourceLoopRhythm"),
        "Upload review must block repeated internet GIF/video reuse unless it is an intentional loop group with distinct captions and rhythm review.",
        True,
    )
    add_criterion(
        "endingTailPacing",
        "Ending has a tail hold",
        "pass" if ending_tail_pacing_ready else "fail",
        check_detail("endingTailPacing"),
        "Upload review must leave a short visual/BGM tail after the final spoken line instead of stopping on the last syllable.",
        True,
    )
    add_criterion(
        "heroOriginalityEvidence",
        "Hero originality evidence recorded",
        "pass" if hero_evidence_ready else "fail",
        f"heroOriginalityEvidenceReady={hero_evidence_ready}",
        "Record direct/Grok/local generation evidence for the first-scene hero clip.",
        True,
    )
    add_criterion(
        "captionSafeZone",
        "Caption safe-zone preset",
        check_status("captionSafePresets"),
        check_detail("captionSafePresets"),
        "Fix caption presets before upload so Shorts UI danger zones stay clear.",
        True,
    )
    add_criterion(
        "referenceEditGrammar",
        "Reference edit grammar reflected",
        "pass" if reference_edit_grammar_ready else "fail",
        check_detail("referenceEditGrammar"),
        "Do not upload until researched reference grammar is visible in render data: first-two-second hook, 2-3s cut rhythm, safe-zone captions, and platform comparison.",
        True,
    )
    add_criterion(
        "outputAudioSpec",
        "1080x1920 / 30fps / audio stream",
        check_status("outputSpec"),
        check_detail("outputSpec"),
        "Re-render with 1080x1920, 30fps, audio stream, and positive duration.",
        True,
    )
    add_criterion(
        "ttsNarrationEvidence",
        "Audio design is intentional",
        "pass" if narration_ready else "fail",
        (
            f"subtitleOnlyNarrationScenes={production_summary.get('subtitleOnlyNarrationScenes') or []}, "
            f"missingNarrationScenes={production_summary.get('missingNarrationScenes') or []}, "
            f"thinNarrationScenes={production_summary.get('thinNarrationScenes') or []}, "
            f"shortVoiceoverCalloutScenes={production_summary.get('shortVoiceoverCalloutScenes') or []}, "
            f"finalPayoffShortNarrationScenes={production_summary.get('finalPayoffShortNarrationScenes') or []}, "
            f"noVoiceAudioDesignScenes={production_summary.get('noVoiceAudioDesignScenes') or []}, "
            f"voiceoverRequiredNoVoiceScenes={production_summary.get('voiceoverRequiredNoVoiceScenes') or []}, "
            f"visualLedNoVoiceApprovedScenes={production_summary.get('visualLedNoVoiceApprovedScenes') or []}, "
            f"missingNoVoiceAudioScenes={production_summary.get('missingNoVoiceAudioScenes') or []}, "
            f"missingNoVoiceAudioReviewScenes={production_summary.get('missingNoVoiceAudioReviewScenes') or []}, "
            f"productionMetaNarrationScenes={production_summary.get('productionMetaNarrationScenes') or []}, "
            f"requiredChars={production_summary.get('narrationMinCharsByScene') or {}}"
        ),
        "Either use natural viewer-facing narration, or explicitly ship a no-voice edit with BGM/native audio and audio mix review proof.",
        True,
    )
    add_criterion(
        "bgmSoundQuality",
        "BGM is not beep/test-tone/procedural",
        "pass" if not placeholder_bgm_assets else "fail",
        (
            f"placeholderBgmAssets={placeholder_bgm_assets}, "
            f"reasons={production_summary.get('placeholderBgmAssetReasons') or {}}"
        ),
        "Replace procedural sine, beep, click, lavfi, or test-tone BGM with a real free music bed before upload.",
        True,
    )
    add_criterion(
        "sceneQualityReview",
        "Per-scene visual quality review",
        "pass" if total_scenes > 0 and len(quality_review_scenes) == total_scenes else "fail",
        f"qualityReviewScenes={quality_review_scenes}, totalScenes={total_scenes}",
        "Complete per-scene quality review for subject visibility, caption occlusion, watermark/compression, and cut continuity.",
        True,
    )
    add_criterion(
        "manualVisualVerdict",
        "Contact-sheet visual verdict",
        "pass" if visual_verdict_ready else "fail",
        (
            f"visualVerdictScenes={visual_verdict_scenes}, "
            f"missingVisualVerdictScenes={missing_visual_verdict}, "
            f"failedVisualVerdictScenes={failed_visual_verdict}"
        ),
        "Before upload, watch the final render/contact sheet and mark every scene with visualQualityVerdict=pass; review text alone is not upload evidence.",
        True,
    )
    add_criterion(
        "captionLayoutReview",
        "Caption placement reviewed",
        "pass" if caption_layout_ready else "fail",
        (
            f"missingCaptionLayoutReviewScenes={production_summary.get('missingCaptionLayoutReviewScenes') or []}, "
            f"captionSparsePlan={production_summary.get('captionSparsePlan')}, "
            f"longTopHookScenes={production_summary.get('longTopHookScenes') or []}"
        ),
        "Move, shorten, or disable captions intentionally; one slow hook plus no later captions is not an upload-ready layout.",
        True,
    )
    add_criterion(
        "assetReuseDiversity",
        "No repeated visual asset reuse",
        "pass" if asset_diversity_ready else "fail",
        f"repeatedVisualAssetScenes={production_summary.get('repeatedVisualAssetScenes') or []}",
        "Replace repeated assets before upload; repeated B-roll should be a deliberate callback, not a default fallback.",
        True,
    )
    add_criterion(
        "freeAssetProvenance",
        "Free asset provenance retained",
        "pass" if free_asset_provenance_ready else "fail",
        (
            f"missingFreeAssetProvenanceScenes={production_summary.get('missingFreeAssetProvenanceScenes') or []}, "
            f"missingFreeAudioProvenanceAssets={production_summary.get('missingFreeAudioProvenanceAssets') or []}, "
            f"freeAudioCreditMissingAssets={production_summary.get('freeAudioCreditMissingAssets') or []}"
        ),
        "Keep source URL/ID/label, license notes, and YouTube description credits for Pexels/Pixabay/Mixkit/Freesound/YouTube Audio Library assets.",
        True,
    )
    add_criterion(
        "bgmAssetRotation",
        "BGM is not default-reused",
        "pass" if bgm_rotation_ready else "warn",
        (
            f"weakBgmSelectionAssets={production_summary.get('weakBgmSelectionAssets') or []}, "
            f"placeholderBgmAssets={placeholder_bgm_assets}"
        ),
        "Before upload, add more free BGM candidates or pin a deliberate free BGM choice with provenance.",
        False,
    )
    add_criterion(
        "templateSourcePlan",
        "Template/source plan matches format",
        "pass" if template_source_ready else "warn",
        (
            f"template={template_source_review.get('template')}, "
            f"status={template_source_review.get('status')}, "
            f"counts={template_source_review.get('counts')}"
        ),
        "Fix the template source mix before upload: avoid repeated assets, document free sources, and use the right direct/Grok/local/stock mix.",
        False,
    )
    add_criterion(
        "grokOrLocalHero",
        "Direct/Grok/local original hero option",
        "pass" if hero_original_ready or hero_ai_or_local_ready else "warn",
        f"heroOriginalClipReady={hero_original_ready}, heroAiOrLocalReady={hero_ai_or_local_ready}",
        "For AI-assisted channel targets, prefer Grok app/web or local Wan/LTX/Hunyuan for the first hook, but direct original uploads are publishable.",
        False,
    )
    if source_mix_required:
        add_criterion(
            "originalSourceMix",
            "Live-channel original source mix",
            "pass" if original_source_mix_ready else "fail",
            (
                f"template={content_template}, originalClipScenes={original_clip_scenes}, "
                f"minOriginalScenes={min_original_scene_count}, stockVideoScenes={stock_video_scenes}, "
                f"uploadedVideoScenes={uploaded_video_scenes}, grokHandoffScenes={grok_handoff_scenes}, "
                f"localModelVideoScenes={local_model_video_scenes}, totalScenes={total_scenes}, "
                f"originalClipSceneIds={original_clip_scene_ids}"
            ),
            "For this live-channel template, rerender with at least half of scenes backed by reviewed Grok/local/direct/owned MP4 clips; stock B-roll can support but cannot carry the edit.",
            True,
        )
    add_criterion(
        "thumbnailFirstFrame",
        "Thumbnail / first-frame manual review",
        check_status("thumbnailFirstFrameStrength"),
        check_detail("thumbnailFirstFrameStrength"),
        "Pick or generate a thumbnail/first-frame candidate before publishing.",
        False,
    )
    add_criterion(
        "audioMixReview",
        "BGM/native/TTS volume manual review",
        "pass" if audio_mix_review_ready else "warn",
        f"audioMixReviewScenes={audio_mix_review_scenes}",
        "Confirm BGM/native/TTS balance on headphones and speakers before publishing.",
        False,
    )
    add_criterion(
        "platformComparison",
        "YouTube Shorts/long-form comparison",
        "pass" if platform_comparison_ready else "warn",
        f"platformComparisonScenes={platform_comparison_scenes}",
        "Record a final comparison pass against current channel references before upload.",
        False,
    )

    passed = sum(1 for item in criteria if item["status"] == "pass")
    total = len(criteria)
    if required_fixes:
        status = "blocked"
    elif manual_reviews:
        status = "needs-manual-review"
    else:
        status = "ready"

    return {
        "status": status,
        "score": {"passed": passed, "total": total},
        "requiredFixes": required_fixes,
        "manualReviewItems": manual_reviews,
        "strengths": strengths[:8],
        "criteria": criteria,
        "summary": {
            "publishStatus": publish_status,
            "channelStatus": channel_status,
            "contentTemplate": content_template,
            "firstSceneId": first_scene_id,
            "heroOriginalClipReady": hero_original_ready,
            "heroOriginalityEvidenceReady": hero_evidence_ready,
            "heroAiOrLocalReady": hero_ai_or_local_ready,
            "originalSourceMixRequired": source_mix_required,
            "originalSourceMixReady": original_source_mix_ready,
            "originalClipScenes": original_clip_scenes,
            "minOriginalScenes": min_original_scene_count,
            "stockVideoScenes": stock_video_scenes,
            "uploadedVideoScenes": uploaded_video_scenes,
            "grokHandoffScenes": grok_handoff_scenes,
            "localModelVideoScenes": local_model_video_scenes,
            "originalClipSceneIds": original_clip_scene_ids,
            "sourceProofClipSceneIds": source_proof_clip_scene_ids,
            "internetSourceProofMode": internet_source_proof_mode,
            "internetMotionSourceSceneIds": internet_motion_source_scene_ids,
            "internetContextSourceSceneIds": internet_context_source_scene_ids,
            "firstSceneHookReady": first_hook_ready,
            "qualityReviewScenes": quality_review_scenes,
            "visualVerdictScenes": visual_verdict_scenes,
            "missingVisualVerdictScenes": missing_visual_verdict,
            "failedVisualVerdictScenes": failed_visual_verdict,
            "thumbnailReviewScenes": thumbnail_review_scenes,
            "audioMixReviewScenes": audio_mix_review_scenes,
            "platformComparisonScenes": platform_comparison_scenes,
            "thumbnailReviewReady": thumbnail_review_ready,
            "audioMixReviewReady": audio_mix_review_ready,
            "platformComparisonReady": platform_comparison_ready,
            "narrationReady": narration_ready,
            "captionLayoutReady": caption_layout_ready,
            "referenceEditGrammarReady": reference_edit_grammar_ready,
            "visualVerdictReady": visual_verdict_ready,
            "assetDiversityReady": asset_diversity_ready,
            "freeAssetProvenanceReady": free_asset_provenance_ready,
            "bgmSoundReady": not placeholder_bgm_assets,
            "placeholderBgmAssets": placeholder_bgm_assets,
            "bgmRotationReady": bgm_rotation_ready,
            "templateSourceReady": template_source_ready,
            "providerConsistencyReady": provider_consistency_ready,
            "antiAiNaturalnessReady": anti_ai_naturalness_ready,
            "captionSystemReady": caption_system_ready,
            "viewerTakeawayReady": viewer_takeaway_ready,
            "internetSourceEditorialIntegrationReady": internet_source_editorial_integration_ready,
            "conversationalCopyStyleReady": conversational_copy_style_ready,
            "ttsPacingAlignmentReady": tts_pacing_alignment_ready,
            "sourceLoopRhythmReady": source_loop_rhythm_ready,
            "endingTailPacingReady": ending_tail_pacing_ready,
            "totalScenes": total_scenes,
        },
    }


def _build_top_tier_readiness(
    checks: dict,
    publish_readiness: dict,
    channel_readiness: dict,
    upload_review: dict,
    production_review: dict,
) -> dict:
    """Grade the stricter Korean AI-assisted channel benchmark separately from upload readiness."""
    production_summary = production_review.get("summary") or {}
    channel_summary = channel_readiness.get("summary") or {}
    upload_summary = upload_review.get("summary") if isinstance(upload_review.get("summary"), dict) else {}
    template_source_review = production_review.get("templateSourceReview") or {}
    publish_status = str(publish_readiness.get("status") or "needs-rework")
    channel_status = str(channel_readiness.get("status") or "needs-review")
    upload_status = str(upload_review.get("status") or "needs-review")
    first_scene_id = str(channel_summary.get("firstSceneId") or "scene-01")
    total_scenes = int(production_summary.get("totalScenes", 0) or 0)
    uploaded_video_scenes = int(production_summary.get("uploadedVideoScenes", 0) or 0)
    grok_handoff_scenes = int(production_summary.get("grokHandoffScenes", 0) or 0)
    local_model_video_scenes = int(production_summary.get("localModelVideoScenes", 0) or 0)
    stock_video_scenes = int(production_summary.get("stockVideoScenes", 0) or 0)
    original_clip_scene_ids = [str(item) for item in production_summary.get("originalClipSceneIds") or []]
    internet_source_proof_mode = bool(production_summary.get("internetSourceProofMode"))
    internet_motion_source_scene_ids = [str(item) for item in production_summary.get("internetMotionSourceSceneIds") or []]
    internet_context_source_scene_ids = [str(item) for item in production_summary.get("internetContextSourceSceneIds") or []]
    source_proof_clip_scene_ids = sorted(
        set(original_clip_scene_ids + internet_motion_source_scene_ids + internet_context_source_scene_ids)
    ) if internet_source_proof_mode else original_clip_scene_ids
    original_clip_scenes = len(set(source_proof_clip_scene_ids))
    min_original_scene_count = 1 if total_scenes <= 1 else max(2, (total_scenes + 1) // 2)
    original_source_mix_ready = original_clip_scenes >= min_original_scene_count
    hero_ai_or_local_ready = channel_summary.get("heroAiOrLocalReady") is True
    hero_original_ready = channel_summary.get("heroOriginalClipReady") is True
    hero_evidence_ready = channel_summary.get("heroOriginalityEvidenceReady") is True
    narration_ready = channel_summary.get("narrationReady") is True or upload_summary.get("narrationReady") is True
    caption_layout_ready = channel_summary.get("captionLayoutReady") is True or upload_summary.get("captionLayoutReady") is True
    reference_edit_grammar_ready = (
        channel_summary.get("referenceEditGrammarReady") is True
        or upload_summary.get("referenceEditGrammarReady") is True
        or production_summary.get("referenceEditGrammarReady") is True
    )
    visual_verdict_ready = channel_summary.get("visualVerdictReady") is True or upload_summary.get("visualVerdictReady") is True
    asset_diversity_ready = channel_summary.get("assetDiversityReady") is True or upload_summary.get("assetDiversityReady") is True
    free_asset_provenance_ready = (
        channel_summary.get("freeAssetProvenanceReady") is True
        or upload_summary.get("freeAssetProvenanceReady") is True
    )
    stock_candidate_curation_ready = not (production_summary.get("missingStockCandidateCurationScenes") or [])
    placeholder_bgm_assets = production_summary.get("placeholderBgmAssets") or []
    bgm_sound_ready = not placeholder_bgm_assets and (checks.get("bgmSoundQuality") or {}).get("status") == "pass"
    bgm_rotation_ready = (
        (channel_summary.get("bgmRotationReady") is True or upload_summary.get("bgmRotationReady") is True)
        and bgm_sound_ready
    )
    audio_mix_review_ready = channel_summary.get("audioMixReviewReady") is True or upload_summary.get("audioMixReviewReady") is True
    platform_comparison_ready = (
        channel_summary.get("platformComparisonReady") is True
        or upload_summary.get("platformComparisonReady") is True
    )
    template_source_ready = (
        channel_summary.get("templateSourceReady") is True
        or upload_summary.get("templateSourceReady") is True
        or template_source_review.get("status") == "pass"
    )
    provider_consistency_ready = (
        upload_summary.get("providerConsistencyReady") is True
        and (checks.get("providerConsistency") or {}).get("status") == "pass"
    )
    anti_ai_naturalness_ready = (
        upload_summary.get("antiAiNaturalnessReady") is True
        and (checks.get("antiAiNaturalness") or {}).get("status") == "pass"
    )
    caption_system_ready = (
        upload_summary.get("captionSystemReady") is True
        and (checks.get("captionSystem") or {}).get("status") == "pass"
    )
    viewer_takeaway_ready = (
        upload_summary.get("viewerTakeawayReady") is True
        and (checks.get("viewerTakeaway") or {}).get("status") == "pass"
    )
    internet_source_editorial_integration_ready = (
        upload_summary.get("internetSourceEditorialIntegrationReady") is True
        and (checks.get("internetSourceEditorialIntegration") or {}).get("status") == "pass"
    )
    conversational_copy_style_ready = (
        upload_summary.get("conversationalCopyStyleReady") is True
        and (checks.get("conversationalCopyStyle") or {}).get("status") == "pass"
    )
    tts_pacing_alignment_ready = (
        upload_summary.get("ttsPacingAlignmentReady") is True
        and (checks.get("ttsPacingAlignment") or {}).get("status") == "pass"
    )
    source_loop_rhythm_ready = (
        upload_summary.get("sourceLoopRhythmReady") is True
        and (checks.get("sourceLoopRhythm") or {}).get("status") == "pass"
    )
    ending_tail_pacing_ready = (
        upload_summary.get("endingTailPacingReady") is True
        and (checks.get("endingTailPacing") or {}).get("status") == "pass"
    )
    first_hook_ready = production_summary.get("firstSceneHookReady") is True

    criteria: list[dict] = []
    required_fixes: list[str] = []
    strengths: list[str] = []

    def add_criterion(
        key: str,
        label: str,
        ok: bool,
        detail: str,
        fix: str,
    ) -> None:
        status = "pass" if ok else "fail"
        criteria.append({
            "key": key,
            "label": label,
            "status": status,
            "detail": detail,
            "required": True,
        })
        if ok:
            strengths.append(label)
        else:
            required_fixes.append(fix)

    add_criterion(
        "publishGate",
        "Publish gate passed",
        publish_status == "ready",
        f"publishReadiness={publish_status}",
        "Resolve publish-readiness before judging top-tier quality.",
    )
    add_criterion(
        "channelGate",
        "Channel gate passed",
        channel_status == "channel-ready",
        f"channelReadiness={channel_status}",
        "Create a channel-ready packet with reviewed original/direct/Grok/local first-scene evidence.",
    )
    add_criterion(
        "uploadReviewGate",
        "Upload review passed",
        upload_status == "ready",
        f"uploadReview={upload_status}",
        "Complete thumbnail, audio mix, caption layout, and platform upload review before top-tier claim.",
    )
    add_criterion(
        "firstHookOriginal",
        "First hook has original MP4",
        hero_original_ready and hero_evidence_ready and first_hook_ready,
        (
            f"firstSceneId={first_scene_id}, heroOriginalClipReady={hero_original_ready}, "
            f"heroOriginalityEvidenceReady={hero_evidence_ready}, firstSceneHookReady={first_hook_ready}"
        ),
        "Replace or review the first hook so it has original/direct/Grok/local MP4 evidence and an immediate visual payoff.",
    )
    add_criterion(
        "grokOrLocalHero",
        "First hook has Grok/local AI MP4",
        hero_ai_or_local_ready,
        (
            f"firstSceneId={first_scene_id}, grokHandoffScenes={grok_handoff_scenes}, "
            f"localModelVideoScenes={local_model_video_scenes}"
        ),
        "For top-tier AI-assisted output, replace the first hook with a reviewed Grok app/web or local Wan/LTX/Hunyuan MP4, not only direct upload or stock.",
    )
    add_criterion(
        "originalSourceMix",
        "Original/Grok/local/direct scenes outweigh stock",
        original_source_mix_ready,
        (
            f"originalClipScenes={original_clip_scenes}, minOriginalScenes={min_original_scene_count}, "
            f"stockVideoScenes={stock_video_scenes}, uploadedVideoScenes={uploaded_video_scenes}, "
            f"grokHandoffScenes={grok_handoff_scenes}, localModelVideoScenes={local_model_video_scenes}, "
            f"totalScenes={total_scenes}, originalClipSceneIds={original_clip_scene_ids}"
        ),
        "For top-tier output, at least half of scenes should be reviewed Grok/local/direct/owned MP4 clips; keep Pexels as support B-roll, not the main visual source.",
    )
    add_criterion(
        "audioDesign",
        "Intentional audio design",
        narration_ready and (checks.get("ttsNarrationEvidence") or {}).get("status") == "pass",
        (checks.get("ttsNarrationEvidence") or {}).get("detail") or f"narrationReady={narration_ready}",
        "Use viewer-facing voiceover for information/ranking/list output unless a visual-led no-voice edit is explicitly human-approved.",
    )
    add_criterion(
        "captionLayout",
        "Caption layout is subject-clear",
        caption_layout_ready and (checks.get("captionLayoutReview") or {}).get("status") == "pass",
        (checks.get("captionLayoutReview") or {}).get("detail") or f"captionLayoutReady={caption_layout_ready}",
        "Record per-scene caption placement review and keep captions out of subject and Shorts UI danger zones.",
    )
    add_criterion(
        "providerConsistency",
        "Provider mode is homogeneous",
        provider_consistency_ready,
        (checks.get("providerConsistency") or {}).get("detail") or "provider consistency check missing",
        "Top-tier candidates should be Grok-only or Gemini-only; do not rely on local-only or unexplained mixed-provider output.",
    )
    add_criterion(
        "antiAiNaturalness",
        "Anti-AI naturalness passed",
        anti_ai_naturalness_ready,
        (checks.get("antiAiNaturalness") or {}).get("detail") or "anti-AI naturalness check missing",
        "Reject output that still reads as generic AI/ad footage, same-looking samples, or action without human cause.",
    )
    add_criterion(
        "captionSystem",
        "Caption system supports the edit",
        caption_system_ready,
        (checks.get("captionSystem") or {}).get("detail") or "caption system check missing",
        "Use a fixed caption position/purpose policy so captions feel intentionally edited, not randomly generated.",
    )
    add_criterion(
        "viewerTakeaway",
        "Viewer takeaway is explicit",
        viewer_takeaway_ready,
        (checks.get("viewerTakeaway") or {}).get("detail") or "viewer takeaway check missing",
        "Do not call the output top-tier until the viewer understanding, action, and emotional state are recorded.",
    )
    add_criterion(
        "internetSourceEditorialIntegration",
        "Internet source is integrated into text/layout",
        internet_source_editorial_integration_ready,
        (checks.get("internetSourceEditorialIntegration") or {}).get("detail")
        or "internet source editorial integration check missing",
        "Source-led scenes must prove the chosen GIF/image source shaped the subtitle, TTS, and layout rather than only passing acquisition.",
    )
    add_criterion(
        "conversationalCopyStyle",
        "Subtitle/TTS copy sounds spoken",
        conversational_copy_style_ready,
        (checks.get("conversationalCopyStyle") or {}).get("detail")
        or "conversational copy style check missing",
        "Top-tier source-led videos need a conversational subtitle/script prompt and viewer copy that avoids report-style or production-label wording.",
    )
    add_criterion(
        "ttsPacingAlignment",
        "TTS pacing matches captions",
        tts_pacing_alignment_ready,
        (checks.get("ttsPacingAlignment") or {}).get("detail")
        or "TTS pacing alignment check missing",
        "Top-tier source-led videos cannot use aggressively compressed TTS or tiny captions that do not match the spoken script density.",
    )
    add_criterion(
        "sourceLoopRhythm",
        "Repeated source loops have edit rhythm",
        source_loop_rhythm_ready,
        (checks.get("sourceLoopRhythm") or {}).get("detail")
        or "source loop rhythm check missing",
        "Top-tier source-led videos can repeat a GIF/video source only when the repeat is a documented loop beat with distinct captions.",
    )
    add_criterion(
        "endingTailPacing",
        "Ending leaves a final hold",
        ending_tail_pacing_ready,
        (checks.get("endingTailPacing") or {}).get("detail")
        or "ending tail pacing check missing",
        "Top-tier videos need a short visual/BGM tail after the final spoken idea instead of cutting on the last syllable.",
    )
    add_criterion(
        "captionDensityAndSafeZone",
        "Caption density and safe zone fit Shorts",
        (checks.get("captionDensityAndSafeZone") or {}).get("status") == "pass",
        (checks.get("captionDensityAndSafeZone") or {}).get("detail") or "caption density check missing",
        "Shorten burned-in captions and keep lower captions in the lower-mid Shorts safe zone, not the bottom UI area.",
    )
    add_criterion(
        "referenceEditGrammar",
        "Reference edit grammar reflected",
        reference_edit_grammar_ready and (checks.get("referenceEditGrammar") or {}).get("status") == "pass",
        (checks.get("referenceEditGrammar") or {}).get("detail") or f"referenceEditGrammarReady={reference_edit_grammar_ready}",
        "Apply researched short-form reference grammar before top-tier review: first-two-second hook, 2-3s cut rhythm, caption safe-zone, and platform comparison evidence.",
    )
    add_criterion(
        "manualVisualVerdict",
        "Contact-sheet visual verdict passed",
        visual_verdict_ready,
        (
            f"visualVerdictReady={visual_verdict_ready}, "
            f"visualVerdictScenes={production_summary.get('visualVerdictScenes') or []}, "
            f"missingVisualVerdictScenes={production_summary.get('missingVisualVerdictScenes') or []}, "
            f"failedVisualVerdictScenes={production_summary.get('failedVisualVerdictScenes') or []}"
        ),
        "Do a real visual review of the rendered frames/contact sheet and mark every scene visualQualityVerdict=pass before claiming top-tier quality.",
    )
    add_criterion(
        "cutDensityPacing",
        "Cut density fits short-form pacing",
        (checks.get("cutDensityPacing") or {}).get("status") == "pass",
        (checks.get("cutDensityPacing") or {}).get("detail") or "cut density check missing",
        "Increase the number of distinct moving clips or shorten static/reused sections before claiming top-tier short-form quality.",
    )
    add_criterion(
        "aiSlopVisualFit",
        "AI slop / visual artifact fit passed",
        (checks.get("aiSlopVisualFit") or {}).get("status") == "pass",
        (checks.get("aiSlopVisualFit") or {}).get("detail") or "AI slop and source-fit check missing",
        "Separate and resolve AI slop, watermark/compression artifacts, subject mismatch, or weak visual verdicts before top-tier review.",
    )
    add_criterion(
        "stockAiClipFit",
        "Stock/AI clip fit passed",
        (checks.get("stockAiClipFit") or {}).get("status") == "pass",
        (checks.get("stockAiClipFit") or {}).get("detail") or "Stock/AI source-fit check missing",
        "Resolve selected-stock/source-fit mismatch with an explicit pass verdict or replace the scene with accepted direct/Grok/local/owned footage.",
    )
    add_criterion(
        "thumbnailFirstFrameStrength",
        "Thumbnail / first frame is strong",
        (checks.get("thumbnailFirstFrameStrength") or {}).get("status") == "pass",
        (checks.get("thumbnailFirstFrameStrength") or {}).get("detail") or "thumbnail and first-frame check missing",
        "Select or generate a first-frame/thumbnail candidate strong enough for the channel feed before top-tier review.",
    )
    add_criterion(
        "assetDiversity",
        "Distinct visual assets",
        asset_diversity_ready and (checks.get("assetReuseDiversity") or {}).get("status") == "pass",
        (checks.get("assetReuseDiversity") or {}).get("detail") or f"assetDiversityReady={asset_diversity_ready}",
        "Replace repeated free clips/images or document a deliberate visual callback before claiming top-tier quality.",
    )
    add_criterion(
        "freeAssetProvenance",
        "Free asset provenance retained",
        free_asset_provenance_ready and (checks.get("freeAssetProvenance") or {}).get("status") == "pass",
        (checks.get("freeAssetProvenance") or {}).get("detail") or f"freeAssetProvenanceReady={free_asset_provenance_ready}",
        "Keep source URL/ID/license notes for free visual/audio assets so repeated or risky assets are traceable.",
    )
    add_criterion(
        "stockCandidateCuration",
        "Stock B-roll has candidate-pool proof",
        stock_candidate_curation_ready and (checks.get("stockCandidateCuration") or {}).get("status") == "pass",
        (checks.get("stockCandidateCuration") or {}).get("detail") or "stock candidate curation check missing",
        "For Pexels/Pixabay/Mixkit B-roll, select from 2+ candidates and retain creator/source URL or ID plus the manual selection summary.",
    )
    add_criterion(
        "bgmSoundQuality",
        "BGM is not beep/test-tone/procedural",
        bgm_sound_ready,
        (checks.get("bgmSoundQuality") or {}).get("detail") or f"placeholderBgmAssets={placeholder_bgm_assets}",
        "Replace procedural sine, beep, click, lavfi, or test-tone BGM with a real free music bed before top-tier review.",
    )
    add_criterion(
        "bgmRotation",
        "BGM rotation evidence",
        bgm_rotation_ready and (checks.get("bgmAssetRotation") or {}).get("status") == "pass",
        (checks.get("bgmAssetRotation") or {}).get("detail") or f"bgmRotationReady={bgm_rotation_ready}",
        "Use a reusable free/local BGM candidate pool and retain project/template selection evidence.",
    )
    add_criterion(
        "audioMixReview",
        "Audio mix reviewed",
        audio_mix_review_ready,
        f"audioMixReviewScenes={production_summary.get('audioMixReviewScenes') or []}",
        "Watch the full render and record that BGM/native audio supports the edit; if narration exists, confirm speech stays intelligible.",
    )
    add_criterion(
        "platformComparison",
        "Korean YouTube benchmark compared",
        platform_comparison_ready,
        f"platformComparisonScenes={production_summary.get('platformComparisonScenes') or []}",
        "Record a comparison against current Korean Shorts/long-form references for hook, pacing, layout, asset fit, and artifact level.",
    )
    add_criterion(
        "templateSourcePlan",
        "Template/source plan fits format",
        template_source_ready and (checks.get("templateSourcePlan") or {}).get("status") == "pass",
        (checks.get("templateSourcePlan") or {}).get("detail") or f"templateSourceReady={template_source_ready}",
        "Use the chosen template's intended source mix instead of one fixed layout or repeated stock/BGM pattern.",
    )

    passed = sum(1 for item in criteria if item["status"] == "pass")
    top_tier_ready = not required_fixes
    if top_tier_ready:
        status = "top-tier-ready"
    elif publish_status != "ready":
        status = "needs-publish-rework"
    elif channel_status != "channel-ready":
        status = "needs-channel-evidence"
    elif not visual_verdict_ready:
        status = "needs-visual-verdict"
    elif not hero_ai_or_local_ready:
        status = "needs-grok-local-hero"
    elif not original_source_mix_ready:
        status = "needs-original-source-mix"
    elif upload_status != "ready":
        status = "needs-upload-review"
    else:
        status = "needs-top-tier-review"

    return {
        "status": status,
        "score": {"passed": passed, "total": len(criteria)},
        "requiredFixes": required_fixes,
        "recommendedFixes": [],
        "strengths": strengths[:8],
        "criteria": criteria,
        "summary": {
            "publishStatus": publish_status,
            "channelStatus": channel_status,
            "uploadStatus": upload_status,
            "firstSceneId": first_scene_id,
            "grokOrLocalHeroReady": hero_ai_or_local_ready,
            "originalHeroReady": hero_original_ready,
            "heroOriginalityEvidenceReady": hero_evidence_ready,
            "originalSourceMixReady": original_source_mix_ready,
            "originalClipScenes": original_clip_scenes,
            "minOriginalScenes": min_original_scene_count,
            "stockVideoScenes": stock_video_scenes,
            "uploadedVideoScenes": uploaded_video_scenes,
            "grokHandoffScenes": grok_handoff_scenes,
            "localModelVideoScenes": local_model_video_scenes,
            "originalClipSceneIds": original_clip_scene_ids,
            "sourceProofClipSceneIds": source_proof_clip_scene_ids,
            "internetSourceProofMode": internet_source_proof_mode,
            "internetMotionSourceSceneIds": internet_motion_source_scene_ids,
            "internetContextSourceSceneIds": internet_context_source_scene_ids,
            "firstSceneHookReady": first_hook_ready,
            "narrationReady": narration_ready,
            "captionLayoutReady": caption_layout_ready,
            "visualVerdictReady": visual_verdict_ready,
            "cutDensityReady": (checks.get("cutDensityPacing") or {}).get("status") == "pass",
            "aiSlopVisualFitReady": (checks.get("aiSlopVisualFit") or {}).get("status") == "pass",
            "thumbnailFirstFrameReady": (checks.get("thumbnailFirstFrameStrength") or {}).get("status") == "pass",
            "assetDiversityReady": asset_diversity_ready,
            "freeAssetProvenanceReady": free_asset_provenance_ready,
            "stockCandidateCurationReady": stock_candidate_curation_ready,
            "bgmSoundReady": bgm_sound_ready,
            "bgmRotationReady": bgm_rotation_ready,
            "audioMixReviewReady": audio_mix_review_ready,
            "platformComparisonReady": platform_comparison_ready,
            "templateSourceReady": template_source_ready,
            "internetSourceEditorialIntegrationReady": internet_source_editorial_integration_ready,
            "conversationalCopyStyleReady": conversational_copy_style_ready,
            "ttsPacingAlignmentReady": tts_pacing_alignment_ready,
            "sourceLoopRhythmReady": source_loop_rhythm_ready,
            "endingTailPacingReady": ending_tail_pacing_ready,
            "topTierEvidenceReady": top_tier_ready,
            "benchmarkGap": "none" if top_tier_ready else "; ".join(required_fixes[:4]),
        },
    }


def _audio_asset_has_narration_voice(asset: dict) -> bool:
    provider = str(asset.get("provider") or "").strip().lower()
    kind = str(asset.get("kind") or "").strip()
    if provider in FREE_NARRATION_PROVIDERS:
        return kind != "fallback-tone"
    if provider == "upload" and kind in {"uploaded-audio", "voiceover", "native"}:
        return bool(str(asset.get("sourcePath") or asset.get("outputPath") or "").strip())
    return False


def _is_live_channel_strict_manifest(manifest: dict) -> bool:
    project_id = str(
        manifest.get("projectId")
        or manifest.get("project_id")
        or ""
    ).strip().lower()
    render_purpose = str(
        manifest.get("renderPurpose")
        or manifest.get("render_purpose")
        or ""
    ).strip().lower()
    if project_id.startswith("live-channel-"):
        return True
    if "live-channel" in render_purpose or render_purpose in {"grok-final-handoff", "grok-final"}:
        return True
    return _truthy_metadata(manifest.get("grokMainSourceRequired")) and _truthy_metadata(
        manifest.get("qualityGateRequired")
    )


def _stream_duration_seconds(stream: dict) -> float | None:
    try:
        value = float(stream.get("duration"))
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def _stream_duration_matches(stream_duration: float | None, format_duration: float | None) -> bool:
    if stream_duration is None or format_duration is None:
        return True
    return abs(stream_duration - format_duration) <= 0.75


def write_render_quality_report(
    render_dir: Path,
    manifest: dict,
    manifest_path: Path,
    output_path: Path,
    project_root: Path,
    local_media_summary: dict,
    local_media: list[dict],
    subtitle_file_path: Path,
) -> str:
    """Write a machine-readable render QA report next to the MP4."""
    ffprobe_payload, ffprobe_info = _run_ffprobe_json(project_root, output_path)
    streams = (ffprobe_payload or {}).get("streams", []) if isinstance(ffprobe_payload, dict) else []
    video_stream = next((stream for stream in streams if stream.get("codec_type") == "video"), {})
    audio_stream = next((stream for stream in streams if stream.get("codec_type") == "audio"), {})
    duration = None
    try:
        duration = float(((ffprobe_payload or {}).get("format") or {}).get("duration"))
    except (TypeError, ValueError, AttributeError):
        duration = None

    width = video_stream.get("width")
    height = video_stream.get("height")
    fps = video_stream.get("avg_frame_rate") or video_stream.get("r_frame_rate")
    video_duration = _stream_duration_seconds(video_stream)
    audio_duration = _stream_duration_seconds(audio_stream)
    stream_duration_ok = (
        _stream_duration_matches(video_duration, duration)
        and _stream_duration_matches(audio_duration, duration)
    )
    output_spec_ok = (
        width == 1080
        and height == 1920
        and _rate_is_30fps(fps)
        and bool(audio_stream)
        and bool(duration and duration > 0)
        and stream_duration_ok
    )

    providers = sorted({
        str(asset.get("provider"))
        for asset in manifest.get("assets", [])
        if asset.get("provider")
    })
    try:
        from worker.media.provider_policy import is_paid_provider
        paid_providers = [provider for provider in providers if is_paid_provider(provider)]
    except Exception:
        paid_providers = []

    caption_presets = [
        {
            "sceneId": scene.get("sceneId"),
            "captionPreset": scene.get("captionPreset", "lower-info"),
        }
        for scene in manifest.get("scenes", [])
    ]
    unsafe_caption_scenes = [
        item["sceneId"]
        for item in caption_presets
        if item["captionPreset"] not in {"none", "center-short", "top-hook", "lower-info"}
    ]
    moving_scene_count = sum(
        1
        for scene in manifest.get("scenes", [])
        if scene.get("visualKind") == "video"
    )
    source_motion_evidence = _build_source_motion_evidence(project_root, manifest)
    source_motion_status = str(source_motion_evidence.get("status") or "unavailable")
    moving_clip_status = "pass" if moving_scene_count > 0 and source_motion_status != "fail" else "fail"
    production_review = _build_production_review(manifest, local_media)
    production_review["templateSourceReview"] = _build_template_source_review(production_review)
    production_summary = production_review["summary"]
    audio_assets = [
        asset
        for asset in manifest.get("assets", [])
        if asset.get("role") == "audio"
    ]
    audio_providers = sorted({
        str(asset.get("provider") or "")
        for asset in audio_assets
        if asset.get("provider")
    })
    narration_scene_ids = {
        str(scene_id)
        for scene_id in production_summary["narrationScenes"]
    }
    inferred_single_scene_id = next(iter(narration_scene_ids)) if len(narration_scene_ids) == 1 else ""

    def audio_scene_id(asset: dict) -> str:
        return str(asset.get("sceneId") or inferred_single_scene_id or "")

    narration_audio_scene_ids = {
        audio_scene_id(asset)
        for asset in audio_assets
        if audio_scene_id(asset) in narration_scene_ids and _audio_asset_has_narration_voice(asset)
    }
    fallback_tone_scene_ids = sorted({
        audio_scene_id(asset)
        for asset in audio_assets
        if str(asset.get("provider") or "") == "fallback-sine" or str(asset.get("kind") or "") == "fallback-tone"
    })
    strict_live_channel = _is_live_channel_strict_manifest(manifest)
    draft_only_voice_scene_ids = sorted({
        audio_scene_id(asset)
        for asset in audio_assets
        if strict_live_channel
        and audio_scene_id(asset) in narration_scene_ids
        and str(asset.get("provider") or "").strip().lower() in DRAFT_ONLY_NARRATION_PROVIDERS
        and _audio_asset_has_narration_voice(asset)
    })
    production_summary["draftOnlyVoiceoverScenes"] = draft_only_voice_scene_ids
    missing_narration_audio_scenes = sorted(narration_scene_ids - narration_audio_scene_ids)
    narration_status = "pass"
    if production_summary["missingNarrationScenes"] or production_summary["thinNarrationScenes"]:
        narration_status = "fail"
    elif production_summary["productionMetaNarrationScenes"] or production_summary["productionMetaSubtitleScenes"]:
        narration_status = "fail"
    elif production_summary.get("voiceoverRequiredNoVoiceScenes"):
        narration_status = "fail"
    elif production_summary["missingNoVoiceAudioScenes"] or production_summary["missingNoVoiceAudioReviewScenes"]:
        narration_status = "fail"
    elif fallback_tone_scene_ids or missing_narration_audio_scenes:
        narration_status = "fail"
    elif draft_only_voice_scene_ids:
        narration_status = "fail"
    caption_layout_status = (
        "pass"
        if not production_summary["missingCaptionLayoutReviewScenes"]
        and not production_summary["captionSparsePlan"]
        and not production_summary["longTopHookScenes"]
        else "fail"
    )
    caption_density_status = "pass" if not production_summary["captionDensityIssueScenes"] else "fail"
    reference_edit_grammar_status = "pass" if production_summary.get("referenceEditGrammarReady") else "fail"
    asset_diversity_status = "pass" if not production_summary["repeatedVisualAssetScenes"] else "fail"
    free_asset_provenance_status = (
        "pass"
        if not production_summary["missingFreeAssetProvenanceScenes"]
        and not production_summary["missingFreeAudioProvenanceAssets"]
        and not production_summary["freeAudioCreditMissingAssets"]
        else "warn"
    )
    stock_candidate_curation_status = (
        "pass"
        if not production_summary["missingStockCandidateCurationScenes"]
        else "warn"
    )
    bgm_sound_status = "fail" if production_summary.get("placeholderBgmAssets") else "pass"
    bgm_rotation_status = (
        "fail"
        if production_summary.get("placeholderBgmAssets")
        else "pass"
        if not production_summary["weakBgmSelectionAssets"]
        else "warn"
    )
    grok_source_curation_status = (
        "pass"
        if not production_summary["missingGrokSourceCurationScenes"]
        else "fail"
    )
    source_first_source_status = (
        "pass"
        if not production_summary.get("sourceFirstRequired") or production_summary.get("sourceFirstReady")
        else "fail"
    )
    quality_ratchet = _build_quality_ratchet_review(manifest)
    quality_sample_set = _build_quality_sample_set_review(manifest, project_root)
    provider_consistency = _provider_consistency_review(manifest, production_summary)
    anti_ai_naturalness = _build_anti_ai_naturalness_review(manifest)
    caption_system = _build_caption_system_review(manifest, production_summary)
    viewer_takeaway = _build_viewer_takeaway_review(manifest)
    source_editorial_layout = _build_source_editorial_layout_review(manifest)
    source_editorial_image_context = _build_source_editorial_image_context_review(manifest)
    still_image_source_policy = _build_still_image_source_policy_review(manifest)
    internet_source_acquisition = _build_internet_source_acquisition_review(manifest)
    internet_source_context = _build_internet_source_context_review(manifest)
    internet_source_editorial_integration = _build_internet_source_editorial_integration_review(manifest)
    topic_hook_payoff_structure = _build_topic_hook_payoff_structure_review(manifest)
    audience_interest_source_fit = _build_audience_interest_source_fit_review(manifest)
    scene_source_intent_binding = _build_scene_source_intent_binding_review(manifest)
    visual_frame_review_evidence = _build_visual_frame_review_evidence(manifest)
    conversational_copy_style = _build_conversational_copy_style_review(manifest)
    tts_pacing_alignment = _build_tts_pacing_alignment_review(manifest)
    source_loop_rhythm = _build_source_loop_rhythm_review(manifest)
    ending_payoff = _build_ending_payoff_review(manifest)
    ending_tail_pacing = _build_ending_tail_pacing_review(manifest)

    checks = {
        "outputSpec": _check(
            "pass" if output_spec_ok else "fail",
            (
                f"{width}x{height}, fps={fps}, audio={audio_stream.get('codec_name')}, "
                f"duration={duration}, videoDuration={video_duration}, audioDuration={audio_duration}"
            ),
        ),
        "noPlaceholders": _check(
            "pass" if int(local_media_summary.get("placeholder", 0) or 0) == 0 else "fail",
            f"placeholder={local_media_summary.get('placeholder', 0)}",
        ),
        "movingClipPriority": _check(
            moving_clip_status,
            (
                f"videoScenes={moving_scene_count}/{len(manifest.get('scenes', []))}, "
                f"sourceMotion={source_motion_status}, "
                f"lowMotionScenes={source_motion_evidence.get('lowMotionSceneIds') or []}"
            ),
        ),
        "sourceMotionEvidence": _check(
            "pass" if source_motion_status == "pass" else ("fail" if source_motion_status == "fail" else "warn"),
            source_motion_evidence.get("detail") or "source motion audit unavailable",
        ),
        "zeroPaidProviders": _check(
            "pass" if not paid_providers else "fail",
            f"paidProviders={paid_providers}",
        ),
        "captionSafePresets": _check(
            "pass" if not unsafe_caption_scenes else "fail",
            f"unsafeCaptionScenes={unsafe_caption_scenes}",
        ),
        "providerConsistency": _check(
            provider_consistency["status"],
            (
                f"required={provider_consistency['required']}, "
                f"mode={provider_consistency['mode']}, "
                f"counts={provider_consistency['counts']}, "
                f"issues={provider_consistency['issues']}"
            ),
        ),
        "antiAiNaturalness": _check(
            anti_ai_naturalness["status"],
            (
                f"required={anti_ai_naturalness['required']}, "
                f"reviewedScenes={anti_ai_naturalness['reviewedScenes']}, "
                f"missingScenes={anti_ai_naturalness['missingScenes']}, "
                f"rejectedScenes={anti_ai_naturalness['rejectedScenes']}"
            ),
        ),
        "captionSystem": _check(
            caption_system["status"],
            (
                f"required={caption_system['required']}, "
                f"fixedPreset={caption_system['fixedPreset']}, "
                f"mismatchedPresetScenes={caption_system['mismatchedPresetScenes']}, "
                f"missingPurposeScenes={caption_system['missingPurposeScenes']}, "
                f"missingLayoutReviewScenes={caption_system['missingLayoutReviewScenes']}, "
                f"longTopHookScenes={caption_system['longTopHookScenes']}, "
                f"captionSparsePlan={caption_system['captionSparsePlan']}"
            ),
        ),
        "viewerTakeaway": _check(
            viewer_takeaway["status"],
            (
                f"required={viewer_takeaway['required']}, "
                f"missingFields={viewer_takeaway['missingFields']}, "
                f"payload={viewer_takeaway['payload']}"
            ),
        ),
        "sourceEditorialLayout": _check(
            source_editorial_layout["status"],
            (
                f"required={source_editorial_layout['required']}, "
                f"reviewedScenes={source_editorial_layout['reviewedScenes']}, "
                f"missingScenes={source_editorial_layout['missingScenes']}, "
                f"rejectedScenes={source_editorial_layout['rejectedScenes']}, "
                f"riskyImageFitScenes={source_editorial_layout['riskyImageFitScenes']}, "
                f"captionCollisionRiskScenes={source_editorial_layout['captionCollisionRiskScenes']}, "
                f"imageOverlapRiskScenes={source_editorial_layout['imageOverlapRiskScenes']}, "
                f"dividerLineRiskScenes={source_editorial_layout['dividerLineRiskScenes']}, "
                f"policy={source_editorial_layout['policy']}"
            ),
        ),
        "sourceEditorialImageContext": _check(
            source_editorial_image_context["status"],
            (
                f"required={source_editorial_image_context['required']}, "
                f"reviewedScenes={source_editorial_image_context['reviewedScenes']}, "
                f"missingScenes={source_editorial_image_context['missingScenes']}, "
                f"duplicateVisualScenes={source_editorial_image_context['duplicateVisualScenes']}, "
                f"policy={source_editorial_image_context['policy']}"
            ),
        ),
        "stillImageSourcePolicy": _check(
            still_image_source_policy["status"],
            (
                f"required={still_image_source_policy['required']}, "
                f"reviewedScenes={still_image_source_policy['reviewedScenes']}, "
                f"allowedPrimaryStillScenes={still_image_source_policy['allowedPrimaryStillScenes']}, "
                f"supportOnlyStillScenes={still_image_source_policy['supportOnlyStillScenes']}, "
                f"blockedScenes={still_image_source_policy['blockedScenes']}, "
                f"policy={still_image_source_policy['policy']}"
            ),
        ),
        "internetSourceAcquisition": _check(
            internet_source_acquisition["status"],
            (
                f"required={internet_source_acquisition['required']}, "
                f"proofMode={internet_source_acquisition['proofMode']}, "
                f"reviewedScenes={internet_source_acquisition['reviewedScenes']}, "
                f"motionReadyScenes={internet_source_acquisition['motionReadyScenes']}, "
                f"missingScenes={internet_source_acquisition['missingScenes']}, "
                f"policy={internet_source_acquisition['policy']}"
            ),
        ),
        "internetSourceContext": _check(
            internet_source_context["status"],
            (
                f"required={internet_source_context['required']}, "
                f"proofMode={internet_source_context['proofMode']}, "
                f"mixRequired={internet_source_context['mixRequired']}, "
                f"mediaKinds={internet_source_context['mediaKinds']}, "
                f"reviewedScenes={internet_source_context['reviewedScenes']}, "
                f"imageReadyScenes={internet_source_context['imageReadyScenes']}, "
                f"motionReadyScenes={internet_source_context['motionReadyScenes']}, "
                f"missingScenes={internet_source_context['missingScenes']}, "
                f"mixMissing={internet_source_context['mixMissing']}, "
                f"policy={internet_source_context['policy']}"
            ),
        ),
        "internetSourceEditorialIntegration": _check(
            internet_source_editorial_integration["status"],
            (
                f"required={internet_source_editorial_integration['required']}, "
                f"reviewedScenes={internet_source_editorial_integration['reviewedScenes']}, "
                f"missingScenes={internet_source_editorial_integration['missingScenes']}, "
                f"duplicateLayoutNoteScenes={internet_source_editorial_integration['duplicateLayoutNoteScenes']}, "
                f"policy={internet_source_editorial_integration['policy']}"
            ),
        ),
        "topicHookPayoffStructure": _check(
            topic_hook_payoff_structure["status"],
            (
                f"required={topic_hook_payoff_structure['required']}, "
                f"payloadKey={topic_hook_payoff_structure['payloadKey']}, "
                f"missingFields={topic_hook_payoff_structure['missingFields']}, "
                f"firstScene={topic_hook_payoff_structure['firstSceneId']}:{topic_hook_payoff_structure['firstSceneRole']}/{topic_hook_payoff_structure['firstScenePurpose']}, "
                f"finalScene={topic_hook_payoff_structure['finalSceneId']}:{topic_hook_payoff_structure['finalSceneRole']}/{topic_hook_payoff_structure['finalScenePurpose']}, "
                f"hookCopyOverlap={topic_hook_payoff_structure['hookCopyOverlap']}, "
                f"payoffCopyOverlap={topic_hook_payoff_structure['payoffCopyOverlap']}, "
                f"sourceSceneRoles={topic_hook_payoff_structure['sourceSceneRoles']}, "
                f"policy={topic_hook_payoff_structure['policy']}"
            ),
        ),
        "audienceInterestSourceFit": _check(
            audience_interest_source_fit["status"],
            (
                f"required={audience_interest_source_fit['required']}, "
                f"payloadKey={audience_interest_source_fit['payloadKey']}, "
                f"targetAudience={audience_interest_source_fit['targetAudience']}, "
                f"interestScore={audience_interest_source_fit['interestScore']}, "
                f"validEvidenceCount={audience_interest_source_fit['validEvidenceCount']}, "
                f"concreteSignalRequired={audience_interest_source_fit['concreteSignalRequired']}, "
                f"genericInterestTerms={audience_interest_source_fit['genericInterestTerms']}, "
                f"missingFields={audience_interest_source_fit['missingFields']}, "
                f"policy={audience_interest_source_fit['policy']}"
            ),
        ),
        "sceneSourceIntentBinding": _check(
            scene_source_intent_binding["status"],
            (
                f"required={scene_source_intent_binding['required']}, "
                f"reviewedScenes={scene_source_intent_binding['reviewedScenes']}, "
                f"missingScenes={scene_source_intent_binding['missingScenes']}, "
                f"roleCounts={scene_source_intent_binding['roleCounts']}, "
                f"policy={scene_source_intent_binding['policy']}"
            ),
        ),
        "visualFrameReviewEvidence": _check(
            visual_frame_review_evidence["status"],
            (
                f"required={visual_frame_review_evidence['required']}, "
                f"payloadKey={visual_frame_review_evidence['payloadKey']}, "
                f"contactSheetPath={visual_frame_review_evidence['contactSheetPath']}, "
                f"reviewerType={visual_frame_review_evidence['reviewerType']}, "
                f"reviewedScenes={visual_frame_review_evidence['reviewedScenes']}, "
                f"missingFields={visual_frame_review_evidence['missingFields']}, "
                f"missingScenes={visual_frame_review_evidence['missingScenes']}, "
                f"policy={visual_frame_review_evidence['policy']}"
            ),
        ),
        "conversationalCopyStyle": _check(
            conversational_copy_style["status"],
            (
                f"required={conversational_copy_style['required']}, "
                f"promptKey={conversational_copy_style['promptKey']}, "
                f"promptMissing={conversational_copy_style['promptMissing']}, "
                f"reviewedScenes={conversational_copy_style['reviewedScenes']}, "
                f"missingScenes={conversational_copy_style['missingScenes']}, "
                f"repeatedCaptionTerms={conversational_copy_style['repetitionReview']['repeatedTerms']}, "
                f"policy={conversational_copy_style['policy']}"
            ),
        ),
        "ttsPacingAlignment": _check(
            tts_pacing_alignment["status"],
            (
                f"required={tts_pacing_alignment['required']}, "
                f"promptKey={tts_pacing_alignment['promptKey']}, "
                f"promptMissing={tts_pacing_alignment['promptMissing']}, "
                f"reviewedScenes={tts_pacing_alignment['reviewedScenes']}, "
                f"missingScenes={tts_pacing_alignment['missingScenes']}, "
                f"policy={tts_pacing_alignment['policy']}"
            ),
        ),
        "sourceLoopRhythm": _check(
            source_loop_rhythm["status"],
            (
                f"required={source_loop_rhythm['required']}, "
                f"reviewedGroups={source_loop_rhythm['reviewedGroups']}, "
                f"missingGroups={source_loop_rhythm['missingGroups']}, "
                f"groupDetails={source_loop_rhythm['groupDetails']}, "
                f"policy={source_loop_rhythm['policy']}"
            ),
        ),
        "endingPayoff": _check(
            ending_payoff["status"],
            (
                f"required={ending_payoff['required']}, "
                f"finalSceneId={ending_payoff['finalSceneId']}, "
                f"purpose={ending_payoff['purpose']}, "
                f"missingFields={ending_payoff['missingFields']}, "
                f"pacingReview={ending_payoff['pacingReview']}, "
                f"finalTakeawayReview={ending_payoff['finalTakeawayReview']}"
            ),
        ),
        "endingTailPacing": _check(
            ending_tail_pacing["status"],
            (
                f"required={ending_tail_pacing['required']}, "
                f"finalSceneId={ending_tail_pacing['finalSceneId']}, "
                f"tailHoldSec={ending_tail_pacing['tailHoldSec']}, "
                f"fadeOutSec={ending_tail_pacing['fadeOutSec']}, "
                f"renderedAudioTailHoldSec={ending_tail_pacing['renderedAudioTailHoldSec']}, "
                f"voiceTargetDurationSec={ending_tail_pacing['voiceTargetDurationSec']}, "
                f"renderedCaptionDurationSec={ending_tail_pacing['renderedCaptionDurationSec']}, "
                f"captionVoiceCoverage={ending_tail_pacing['captionVoiceCoverage']}, "
                f"endingScreenAction={ending_tail_pacing['endingScreenAction']}, "
                f"endingResolutionReview={ending_tail_pacing['endingResolutionReview']}, "
                f"missingFields={ending_tail_pacing['missingFields']}, "
                f"policy={ending_tail_pacing['policy']}"
            ),
        ),
        "subtitleArtifact": _check(
            "pass" if subtitle_file_path.with_suffix(".ass").exists() or subtitle_file_path.exists() else "fail",
            str(subtitle_file_path.with_suffix(".ass") if subtitle_file_path.with_suffix(".ass").exists() else subtitle_file_path),
        ),
        "manualSelectionEvidence": _check(
            "pass" if not production_summary["missingRationaleScenes"] else "warn",
            f"missingRationaleScenes={production_summary['missingRationaleScenes']}",
        ),
        "continuityEvidence": _check(
            "pass" if not production_summary["missingContinuityScenes"] else "warn",
            f"missingContinuityScenes={production_summary['missingContinuityScenes']}",
        ),
        "firstTwoSecondHook": _check(
            "pass" if production_summary["firstSceneHookReady"] else "warn",
            f"firstSceneHookReady={production_summary['firstSceneHookReady']}",
        ),
        "cutDensityPacing": _check(
            "pass" if production_summary.get("shortsCutDensityReady") else "warn",
            (
                f"shortsCutDensityReady={production_summary.get('shortsCutDensityReady')}, "
                f"totalScenes={production_summary.get('totalScenes')}, "
                f"videoScenes={production_summary.get('videoScenes')}, "
                f"imageFallbackScenes={production_summary.get('imageFallbackScenes')}, "
                f"repeatedVisualAssetScenes={production_summary.get('repeatedVisualAssetScenes') or []}"
            ),
        ),
        "aiSlopVisualFit": _check(
            production_summary.get("aiSlopVisualFitStatus") or "warn",
            (
                f"visualVerdictScenes={production_summary.get('visualVerdictScenes') or []}, "
                f"missingVisualVerdictScenes={production_summary.get('missingVisualVerdictScenes') or []}, "
                f"failedVisualVerdictScenes={production_summary.get('failedVisualVerdictScenes') or []}"
            ),
        ),
        "stockAiClipFit": _check(
            production_summary.get("stockAiClipFitStatus") or "warn",
            (
                f"stockOnly={production_summary.get('stockOnly')}, "
                f"originalSourceMixRequired={production_summary.get('originalSourceMixRequired')}, "
                f"originalSourceMixReady={production_summary.get('originalSourceMixReady')}, "
                f"minOriginalScenes={production_summary.get('minOriginalScenesForSourceMix')}, "
                f"stockSourceMixGapSceneIds={production_summary.get('stockSourceMixGapSceneIds') or []}, "
                f"weakUploadedOriginalityScenes={production_summary.get('weakUploadedOriginalityScenes') or []}, "
                f"proceduralPlaceholderScenes={production_summary.get('proceduralPlaceholderScenes') or []}, "
                f"failedVisualVerdictScenes={production_summary.get('failedVisualVerdictScenes') or []}, "
                f"stockAiClipFitVerdictScenes={production_summary.get('stockAiClipFitVerdictScenes') or []}, "
                f"missingStockAiClipFitVerdictScenes={production_summary.get('missingStockAiClipFitVerdictScenes') or []}, "
                f"failedStockAiClipFitVerdictScenes={production_summary.get('failedStockAiClipFitVerdictScenes') or []}, "
                f"sourceFirstBlockedSceneIds={production_summary.get('sourceFirstBlockedSceneIds') or []}"
            ),
        ),
        "thumbnailFirstFrameStrength": _check(
            "pass" if production_summary.get("thumbnailFirstFrameReady") else "warn",
            (
                f"thumbnailFirstFrameReady={production_summary.get('thumbnailFirstFrameReady')}, "
                f"firstSceneHookReady={production_summary.get('firstSceneHookReady')}, "
                f"thumbnailReviewScenes={production_summary.get('thumbnailReviewScenes') or []}"
            ),
        ),
        "grokSourceCuration": _check(
            grok_source_curation_status,
            (
                f"grokSourceCurationScenes={production_summary['grokSourceCurationScenes']}, "
                f"readyScenes={production_summary['grokSourceCurationReadyScenes']}, "
                f"missingScenes={production_summary['missingGrokSourceCurationScenes']}, "
                f"missingComparison={production_summary['missingGrokCandidateComparisonScenes']}, "
                f"missingSelectedFile={production_summary['missingGrokSelectedFileScenes']}, "
                f"missingSourceProvenance={production_summary['missingGrokSourceProvenanceScenes']}, "
                f"unacceptableSourceProvenance={production_summary['unacceptableGrokSourceProvenanceScenes']}, "
                f"missingSourceConfirmation={production_summary['missingGrokSourceConfirmationScenes']}, "
                f"sourceReviewVerdictScenes={production_summary['grokSourceReviewVerdictScenes']}, "
                f"rejectedSourceReviewScenes={production_summary['rejectedGrokSourceReviewScenes']}, "
                f"previewCaveats={production_summary['grokPreviewCaveatScenes']}"
            ),
        ),
        "sourceFirstSourceGate": _check(
            source_first_source_status,
            (
                f"sourceFirstRequired={production_summary.get('sourceFirstRequired')}, "
                f"sourceFirstReady={production_summary.get('sourceFirstReady')}, "
                f"grokScenes={production_summary.get('grokHandoffSceneIds') or []}, "
                f"geminiScenes={production_summary.get('geminiHandoffSceneIds') or []}, "
                f"localGeneratedScenes={production_summary.get('localModelVideoSceneIds') or []}, "
                f"internetMotionScenes={production_summary.get('internetMotionSourceSceneIds') or []}, "
                f"sourceFirstGeneratedSceneIds={production_summary.get('sourceFirstGeneratedSceneIds') or []}, "
                f"sourceFirstInternetSourceSceneIds={production_summary.get('sourceFirstInternetSourceSceneIds') or []}, "
                f"sourceFirstInternetContextSceneIds={production_summary.get('sourceFirstInternetContextSceneIds') or []}, "
                f"sourceFirstAcceptedSceneIds={production_summary.get('sourceFirstAcceptedSceneIds') or []}, "
                f"sourceFirstBlockedSceneIds={production_summary.get('sourceFirstBlockedSceneIds') or []}, "
                f"sourceFirstBlockingImageFallbackSceneIds={production_summary.get('sourceFirstBlockingImageFallbackSceneIds') or []}, "
                f"sourceFirstBlockReasonsByScene={production_summary.get('sourceFirstBlockReasonsByScene') or {}}"
            ),
        ),
        "stockOnlyCaveat": _check(
            "warn" if production_summary["stockOnly"] else "pass",
            (
                "all scenes use selected stock video; curated stock is a review draft until at least one creator-owned/Grok/local source is present"
                if production_summary["stockOnly"]
                else "source mix includes non-stock footage or image fallback"
            ),
        ),
        "ttsNarrationEvidence": _check(
            narration_status,
            (
                f"audioProviders={audio_providers}, "
                f"strictLiveChannel={strict_live_channel}, "
                f"narrationScenes={production_summary['narrationScenes']}, "
                f"subtitleOnlyNarrationScenes={production_summary['subtitleOnlyNarrationScenes']}, "
                f"missingNarrationScenes={production_summary['missingNarrationScenes']}, "
                f"thinNarrationScenes={production_summary['thinNarrationScenes']}, "
                f"shortVoiceoverCalloutScenes={production_summary.get('shortVoiceoverCalloutScenes') or []}, "
                f"finalPayoffShortNarrationScenes={production_summary.get('finalPayoffShortNarrationScenes') or []}, "
                f"noVoiceAudioDesignScenes={production_summary['noVoiceAudioDesignScenes']}, "
                f"voiceoverRequiredNoVoiceScenes={production_summary.get('voiceoverRequiredNoVoiceScenes') or []}, "
                f"visualLedNoVoiceApprovedScenes={production_summary.get('visualLedNoVoiceApprovedScenes') or []}, "
                f"missingNoVoiceAudioScenes={production_summary['missingNoVoiceAudioScenes']}, "
                f"missingNoVoiceAudioReviewScenes={production_summary['missingNoVoiceAudioReviewScenes']}, "
                f"audioDesignModesByScene={production_summary['audioDesignModesByScene']}, "
                f"productionMetaNarrationScenes={production_summary['productionMetaNarrationScenes']}, "
                f"productionMetaSubtitleScenes={production_summary['productionMetaSubtitleScenes']}, "
                f"productionMetaTermsByScene={production_summary['productionMetaTermsByScene']}, "
                f"requiredChars={production_summary['narrationMinCharsByScene']}, "
                f"narrationAudioScenes={sorted(narration_audio_scene_ids)}, "
                f"missingNarrationAudioScenes={missing_narration_audio_scenes}, "
                f"draftOnlyVoiceoverScenes={draft_only_voice_scene_ids}, "
                f"fallbackToneScenes={fallback_tone_scene_ids}"
            ),
        ),
        "voicePolicyCompliance": _check(
            "pass" if not production_summary.get("voiceoverRequiredNoVoiceScenes") else "fail",
            (
                f"template={production_summary.get('contentTemplate')}, "
                f"voiceoverRequiredNoVoiceScenes={production_summary.get('voiceoverRequiredNoVoiceScenes') or []}, "
                f"visualLedNoVoiceApprovedScenes={production_summary.get('visualLedNoVoiceApprovedScenes') or []}"
            ),
        ),
        "captionLayoutReview": _check(
            caption_layout_status,
            (
                f"captionPresetCounts={production_summary['captionPresetCounts']}, "
                f"captionedScenes={production_summary['captionedSceneIds']}, "
                f"captionSparsePlan={production_summary['captionSparsePlan']}, "
                f"longTopHookScenes={production_summary['longTopHookScenes']}, "
                f"reviewed={production_summary['captionLayoutReviewScenes']}, "
                f"missing={production_summary['missingCaptionLayoutReviewScenes']}"
            ),
        ),
        "captionDensityAndSafeZone": _check(
            caption_density_status,
            (
                f"policy={production_summary['captionSafeZonePolicy']}, "
                f"maxCompactChars={production_summary['captionMaxCompactChars']}, "
                f"issues={production_summary['captionDensityIssuesByScene']}"
            ),
        ),
        "referenceEditGrammar": _check(
            reference_edit_grammar_status,
            (
                f"policy={production_summary.get('referenceEditGrammarPolicy')}, "
                f"ready={production_summary.get('referenceEditGrammarReady')}, "
                f"avgSceneDurationSec={production_summary.get('averageSceneDurationSec')}, "
                f"shortFormReferenceScenes={production_summary.get('shortFormReferenceScenes') or []}, "
                f"missing={production_summary.get('missingReferenceEditGrammarScenes') or []}, "
                f"longHolds={production_summary.get('longHoldSceneIds') or []}, "
                f"issues={production_summary.get('referenceEditGrammarIssues') or []}"
            ),
        ),
        "assetReuseDiversity": _check(
            asset_diversity_status,
            f"repeatedVisualAssetScenes={production_summary['repeatedVisualAssetScenes']}",
        ),
        "freeAssetProvenance": _check(
            free_asset_provenance_status,
            (
                f"freeAssetProvenanceScenes={production_summary['freeAssetProvenanceScenes']}, "
                f"missingFreeAssetProvenanceScenes={production_summary['missingFreeAssetProvenanceScenes']}, "
                f"freeAudioProvenanceAssets={production_summary['freeAudioProvenanceAssets']}, "
                f"missingFreeAudioProvenanceAssets={production_summary['missingFreeAudioProvenanceAssets']}, "
                f"freeAudioCreditMissingAssets={production_summary['freeAudioCreditMissingAssets']}"
            ),
        ),
        "stockCandidateCuration": _check(
            stock_candidate_curation_status,
            (
                f"stockCandidateCurationScenes={production_summary['stockCandidateCurationScenes']}, "
                f"readyScenes={production_summary['stockCandidateCurationReadyScenes']}, "
                f"missingScenes={production_summary['missingStockCandidateCurationScenes']}, "
                f"missingCandidateCount={production_summary['missingStockCandidateCountScenes']}, "
                f"missingCreator={production_summary['missingStockCandidateCreatorScenes']}, "
                f"missingSource={production_summary['missingStockCandidateSourceScenes']}, "
                f"missingSummary={production_summary['missingStockSelectionSummaryScenes']}, "
                f"issues={production_summary['stockCandidateCurationIssuesByScene']}"
            ),
        ),
        "freeAudioCreditsExport": _check(
            "pass" if not production_summary["freeAudioCreditMissingAssets"] else "warn",
            (
                f"youtubeDescriptionAudioCredits={production_summary['youtubeDescriptionAudioCredits']}, "
                f"missing={production_summary['freeAudioCreditMissingAssets']}"
            ),
        ),
        "bgmAssetRotation": _check(
            bgm_rotation_status,
            (
                f"bgmSelectionAssets={production_summary['bgmSelectionAssets']}, "
                f"weakBgmSelectionAssets={production_summary['weakBgmSelectionAssets']}, "
                f"placeholderBgmAssets={production_summary.get('placeholderBgmAssets') or []}"
            ),
        ),
        "bgmSoundQuality": _check(
            bgm_sound_status,
            (
                f"placeholderBgmAssets={production_summary.get('placeholderBgmAssets') or []}, "
                f"reasons={production_summary.get('placeholderBgmAssetReasons') or {}}"
            ),
        ),
        "templateSourcePlan": _check(
            production_review["templateSourceReview"]["status"],
            (
                f"template={production_review['templateSourceReview']['template']}, "
                f"sourceMix={production_review['templateSourceReview']['sourceMix']}, "
                f"counts={production_review['templateSourceReview']['counts']}, "
                f"required={production_review['templateSourceReview']['requiredFixes']}, "
                f"recommended={production_review['templateSourceReview']['recommendedFixes']}"
            ),
        ),
        "qualitySampleSet": _check(
            quality_sample_set["status"],
            (
                f"required={quality_sample_set['required']}, "
                f"minAccepted={quality_sample_set['minAcceptedSamples']}, "
                f"accepted={quality_sample_set['acceptedSampleIds']}, "
                f"rejectedBaselines={quality_sample_set['rejectedBaselineIds']}, "
                f"acceptedTopicCount={quality_sample_set['acceptedTopicCount']}, "
                f"sourceFamilies={quality_sample_set['acceptedSourceFamilies']}, "
                f"currentProjectIncluded={quality_sample_set['currentProjectIncluded']}, "
                f"missingFields={quality_sample_set['missingFields']}"
            ),
        ),
        "qualityRatchet": _check(
            quality_ratchet["status"],
            (
                f"required={quality_ratchet['required']}, "
                f"qualityIteration={quality_ratchet['qualityIteration']}, "
                f"missingFields={quality_ratchet['missingFields']}, "
                f"viewerFacingLever={quality_ratchet['viewerFacingLever']}, "
                f"viewerFacingTerms={quality_ratchet['viewerFacingTerms']}"
            ),
        ),
    }
    publish_readiness = _build_publish_readiness(checks, production_review, local_media_summary)
    channel_readiness = _build_channel_readiness(checks, publish_readiness, production_review, local_media_summary)
    upload_review = _build_upload_review(checks, publish_readiness, channel_readiness, production_review)
    checks["publishReadinessGate"] = _check(
        "pass" if publish_readiness["status"] == "ready" else ("fail" if publish_readiness["status"] == "blocked" else "warn"),
        (
            f"status={publish_readiness['status']}, "
            f"required={len(publish_readiness['requiredFixes'])}, "
            f"recommended={len(publish_readiness['recommendedFixes'])}"
        ),
    )
    checks["channelReadinessGate"] = _check(
        "pass" if channel_readiness["status"] == "channel-ready" else ("fail" if channel_readiness["status"] == "blocked" else "warn"),
        (
            f"status={channel_readiness['status']}, "
            f"required={len(channel_readiness['requiredFixes'])}, "
            f"recommended={len(channel_readiness['recommendedFixes'])}"
        ),
    )
    checks["uploadReviewGate"] = _check(
        "pass" if upload_review["status"] == "ready" else ("fail" if upload_review["status"] == "blocked" else "warn"),
        (
            f"status={upload_review['status']}, "
            f"required={len(upload_review['requiredFixes'])}, "
            f"manual={len(upload_review['manualReviewItems'])}"
        ),
    )
    top_tier_readiness = _build_top_tier_readiness(
        checks,
        publish_readiness,
        channel_readiness,
        upload_review,
        production_review,
    )
    checks["topTierReadinessGate"] = _check(
        "pass" if top_tier_readiness["status"] == "top-tier-ready" else "warn",
        (
            f"status={top_tier_readiness['status']}, "
            f"required={len(top_tier_readiness['requiredFixes'])}"
        ),
    )

    report = {
        "projectId": manifest.get("projectId"),
        "generatedAt": datetime.now().isoformat(timespec="seconds"),
        "manifestPath": str(manifest_path),
        "outputPath": str(output_path),
        "ffprobe": {
            "tool": ffprobe_info,
            "raw": ffprobe_payload,
        },
        "providers": providers,
        "captionPresets": caption_presets,
        "localMediaSummary": local_media_summary,
        "localMedia": local_media,
        "productionReview": production_review,
        "operatingTemplate": (production_review.get("templateSourceReview") or {}).get("operatingTemplate"),
        "sourceMotionEvidence": source_motion_evidence,
        "qualitySampleSet": quality_sample_set,
        "qualityRatchet": quality_ratchet,
        "providerConsistency": provider_consistency,
        "antiAiNaturalness": anti_ai_naturalness,
        "captionSystem": caption_system,
        "viewerTakeaway": viewer_takeaway,
        "sourceEditorialLayout": source_editorial_layout,
        "sourceEditorialImageContext": source_editorial_image_context,
        "stillImageSourcePolicy": still_image_source_policy,
        "internetSourceAcquisition": internet_source_acquisition,
        "internetSourceContext": internet_source_context,
        "internetSourceEditorialIntegration": internet_source_editorial_integration,
        "topicHookPayoffStructure": topic_hook_payoff_structure,
        "audienceInterestSourceFit": audience_interest_source_fit,
        "sceneSourceIntentBinding": scene_source_intent_binding,
        "visualFrameReviewEvidence": visual_frame_review_evidence,
        "conversationalCopyStyle": conversational_copy_style,
        "ttsPacingAlignment": tts_pacing_alignment,
        "sourceLoopRhythm": source_loop_rhythm,
        "endingPayoff": ending_payoff,
        "endingTailPacing": ending_tail_pacing,
        "publishReadiness": publish_readiness,
        "channelReadiness": channel_readiness,
        "uploadReview": upload_review,
        "topTierReadiness": top_tier_readiness,
        "checks": checks,
        "gateSystem": build_render_gate_system(checks),
    }
    report_path = render_dir / "render-quality-report.json"
    write_text(report_path, json.dumps(report, ensure_ascii=False, indent=2))
    return str(report_path)


# ---------------------------------------------------------------------------
# ASS / SRT subtitle helpers
# ---------------------------------------------------------------------------
def format_srt_timestamp(seconds: float) -> str:
    total_ms = int(round(seconds * 1000))
    hours, remainder = divmod(total_ms, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1000)
    return f"{hours:02}:{minutes:02}:{secs:02},{millis:03}"


def _ass_escape(value: str) -> str:
    hard_newline = "\uE000"
    text = safe_text(value).replace(r"\N", hard_newline)
    escaped = text.replace("\\", r"\\").replace("{", r"\{").replace("}", r"\}")
    return escaped.replace(hard_newline, r"\N")


def _wrap_ass_text(value: str, width: int) -> str:
    escaped = _ass_escape(value)
    wrapped = textwrap.wrap(escaped, width=width, break_long_words=False, break_on_hyphens=False)
    return r"\N".join(wrapped) if wrapped else escaped


def write_scene_card_ass(
    path: Path,
    scene_index: int,
    scene_title: str,
    prompt_text: str,
    subtitle_text: str,
    route_label: str,
) -> None:
    title = _wrap_ass_text(scene_title, 18)
    body = _wrap_ass_text(prompt_text, 26)
    caption = _wrap_ass_text(subtitle_text, 28)
    meta = _ass_escape(f"장면 {scene_index:02d} · {route_label}")
    content = "\n".join(
        [
            "[Script Info]",
            "ScriptType: v4.00+",
            "PlayResX: 1080",
            "PlayResY: 1920",
            "WrapStyle: 2",
            "ScaledBorderAndShadow: yes",
            "",
            "[V4+ Styles]",
            "Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding",
            "Style: Meta,Malgun Gothic,26,&H00F5F0E8,&H000000FF,&H7F000000,&H28000000,-1,0,0,0,100,100,0,0,1,1,0,7,96,96,110,1",
            "Style: Title,Malgun Gothic,72,&H00FFF8F0,&H000000FF,&H6F000000,&H22000000,-1,0,0,0,100,100,0,0,1,2,0,7,92,92,208,1",
            "Style: Body,Malgun Gothic,30,&H00EFE7DA,&H000000FF,&H5F000000,&H22000000,0,0,0,0,100,100,0,0,1,1,0,7,98,98,430,1",
            "Style: Caption,Malgun Gothic,34,&H00FFF8F4,&H000000FF,&H76000000,&H22000000,-1,0,0,0,100,100,0,0,1,2,0,2,108,108,190,1",
            "",
            "[Events]",
            "Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text",
            f"Dialogue: 0,0:00:00.00,0:00:20.00,Meta,,0,0,0,,{meta}",
            f"Dialogue: 0,0:00:00.00,0:00:20.00,Title,,0,0,0,,{title}",
            f"Dialogue: 0,0:00:00.00,0:00:20.00,Body,,0,0,0,,{body}",
            f"Dialogue: 0,0:00:00.00,0:00:20.00,Caption,,0,0,0,,{caption}",
        ]
    )
    write_text(path, content)


def write_scene_subtitle(path: Path, subtitle_text: str, duration_sec: float) -> None:
    write_text(
        path,
        "\n".join(
            [
                "1",
                f"00:00:00,000 --> {format_srt_timestamp(duration_sec)}",
                safe_text(subtitle_text),
                "",
            ]
        ),
    )


def write_project_subtitles(
    path: Path,
    scenes: list[dict],
    subtitle_style: str = "",
) -> None:
    from worker.render.subtitles import generate_ass_subtitle, STYLE_PRESETS

    entries = [
        {
            "start_sec": s["startSec"],
            "end_sec": s["endSec"],
            "title": s.get("title", ""),
            "text": s["subtitleText"],
            "caption_preset": s.get("captionPreset", "lower-info"),
            "layout_variant_key": s.get("layoutVariantKey", ""),
            "layout_variant_label": s.get("layoutVariantLabel", ""),
            "layout_variant_note": s.get("layoutVariantNote", ""),
        }
        for s in scenes
    ]

    # Always emit ASS (RENDERING-SPEC mandate)
    ass_path = path.with_suffix(".ass")
    preset = subtitle_style if subtitle_style in STYLE_PRESETS else "default"

    try:
        generate_ass_subtitle(
            words=entries,
            style_preset=preset,
            highlight_mode="none",  # Word-level highlight requires align.py timestamps
            output_path=str(ass_path),
        )
        return
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as e:
        # ASS generation can fail on font loading, malformed entries (missing
        # keys, non-string ``subtitleText``), or missing style presets — fall
        # back to SRT so the render still ships captioned output.
        logger.warning("ASS generation failed, falling back to SRT: %s", e)

    # SRT fallback (kept for resilience)
    lines: list[str] = []
    for index, scene in enumerate(scenes, start=1):
        lines.extend(
            [
                str(index),
                f"{format_srt_timestamp(scene['startSec'])} --> {format_srt_timestamp(scene['endSec'])}",
                safe_text(scene["subtitleText"]),
                "",
            ]
        )
    write_text(path, "\n".join(lines))


# ---------------------------------------------------------------------------
# FFmpeg execution primitives
# ---------------------------------------------------------------------------
def run_ffmpeg(ffmpeg_path: str, args: list[str], log_lines: list[str], cwd: Path | None = None) -> None:
    command = [ffmpeg_path, *args]
    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=CREATE_NO_WINDOW,
        cwd=str(cwd) if cwd else None,
        check=False,
    )
    log_lines.append("$ " + " ".join(command))
    if completed.stdout:
        log_lines.append(completed.stdout.strip())
    if completed.stderr:
        log_lines.append(completed.stderr.strip())
    log_lines.append("")
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or f"ffmpeg exited with code {completed.returncode}")


def create_scene_poster_gradient(
    ffmpeg_path: str,
    output_path: Path,
    ass_path: Path,
    color_index: int,
    log_lines: list[str],
) -> None:
    """Create a poster image with a gradient background + ASS text overlay."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    gradient_src = gradient_source_filter(color_index, size=FRAME_SIZE)
    run_ffmpeg(
        ffmpeg_path,
        [
            "-y",
            "-f", "lavfi",
            "-i", gradient_src,
            "-vf", f"ass='{ffmpeg_filter_path(ass_path)}'",
            "-frames:v", "1",
            str(output_path),
        ],
        log_lines,
    )


def create_visual_clip_from_poster(
    ffmpeg_path: str,
    poster_path: Path,
    output_path: Path,
    duration_sec: float,
    motion_preset: str = DEFAULT_MOTION_PRESET,
    log_lines: list[str] | None = None,
) -> None:
    """Create a video clip from a still poster, optionally with motion."""
    if log_lines is None:
        log_lines = []
    output_path.parent.mkdir(parents=True, exist_ok=True)

    motion_filter = zoompan_filter(
        preset=motion_preset,
        duration_sec=duration_sec,
        fps=int(FRAME_RATE),
        width=1080,
        height=1920,
    )

    if motion_filter:
        # zoompan produces video from a single image — no -loop needed
        vf = f"{motion_filter},format=yuv420p"
        run_ffmpeg(
            ffmpeg_path,
            [
                "-y",
                "-i", str(poster_path),
                "-vf", vf,
                *H264_RENDER_ARGS,
                "-an",
                str(output_path),
            ],
            log_lines,
        )
    else:
        run_ffmpeg(
            ffmpeg_path,
            [
                "-y",
                "-loop", "1",
                "-framerate", FRAME_RATE,
                "-t", f"{duration_sec:.2f}",
                "-i", str(poster_path),
                "-vf", VIDEO_FILTER,
                *H264_RENDER_ARGS,
                "-an",
                str(output_path),
            ],
            log_lines,
        )


def create_fallback_audio(
    ffmpeg_path: str,
    output_path: Path,
    duration_sec: float,
    frequency: int,
    log_lines: list[str],
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    run_ffmpeg(
        ffmpeg_path,
        [
            "-y",
            "-f", "lavfi",
            "-i", f"sine=frequency={frequency}:sample_rate=48000",
            "-t", f"{duration_sec:.2f}",
            "-c:a", "pcm_s16le",
            str(output_path),
        ],
        log_lines,
    )


def create_silent_audio(
    ffmpeg_path: str,
    output_path: Path,
    duration_sec: float,
    log_lines: list[str],
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    run_ffmpeg(
        ffmpeg_path,
        [
            "-y",
            "-f", "lavfi",
            "-i", "anullsrc=channel_layout=stereo:sample_rate=48000",
            "-t", f"{duration_sec:.2f}",
            "-c:a", "pcm_s16le",
            str(output_path),
        ],
        log_lines,
    )


def _ffprobe_for_ffmpeg(ffmpeg_path: str) -> str:
    candidate = Path(ffmpeg_path)
    if candidate.name.lower().startswith("ffmpeg"):
        sibling = candidate.with_name(candidate.name.replace("ffmpeg", "ffprobe", 1))
        if os.path.lexists(str(sibling)):
            return str(sibling)
    return shutil.which("ffprobe") or "ffprobe"


def _audio_duration_seconds(ffmpeg_path: str, input_path: Path) -> float | None:
    try:
        completed = subprocess.run(
            [
                _ffprobe_for_ffmpeg(ffmpeg_path),
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=nokey=1:noprint_wrappers=1",
                str(input_path),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
            creationflags=CREATE_NO_WINDOW,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode != 0:
        return None
    try:
        duration = float((completed.stdout or "").strip())
    except ValueError:
        return None
    return duration if duration > 0 else None


def _media_duration_seconds(ffmpeg_path: str, input_path: Path) -> float | None:
    try:
        completed = subprocess.run(
            [
                _ffprobe_for_ffmpeg(ffmpeg_path),
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=nokey=1:noprint_wrappers=1",
                str(input_path),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
            creationflags=CREATE_NO_WINDOW,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode != 0:
        return None
    try:
        duration = float((completed.stdout or "").strip())
    except ValueError:
        return None
    return duration if duration > 0 else None


def apply_final_outro_fade(
    ffmpeg_path: str,
    video_path: Path,
    output_path: Path,
    fade_out_sec: float,
    log_lines: list[str],
) -> bool:
    """Apply final visual/audio fade-out so an accepted tail does not hard-cut."""
    try:
        fade_out_sec = float(fade_out_sec)
    except (TypeError, ValueError):
        fade_out_sec = 0.0
    if fade_out_sec <= 0:
        log_lines.append("final_outro_fade=skipped fade_out_sec=0")
        return False
    if not video_path.exists():
        log_lines.append(f"final_outro_fade=skipped missing_input={video_path}")
        return False

    duration_sec = _media_duration_seconds(ffmpeg_path, video_path)
    if not duration_sec or duration_sec <= fade_out_sec + 0.2:
        log_lines.append(
            f"final_outro_fade=skipped duration={duration_sec} fade_out={fade_out_sec:.2f}"
        )
        return False

    output_path.parent.mkdir(parents=True, exist_ok=True)
    same_path = video_path.resolve() == output_path.resolve()
    source_path = video_path
    preserved_path = output_path.with_name(f"{output_path.stem}.pre-outro-fade{output_path.suffix}")
    temp_output = output_path.with_name(f"{output_path.stem}.outro-fade.tmp{output_path.suffix}")
    if same_path:
        shutil.copy2(output_path, preserved_path)
        source_path = preserved_path

    fade_start = max(0.0, duration_sec - fade_out_sec)
    run_ffmpeg(
        ffmpeg_path,
        [
            "-y",
            "-i", str(source_path),
            "-vf", f"fade=t=out:st={fade_start:.3f}:d={fade_out_sec:.3f}:color=black,format=yuv420p",
            "-af", f"afade=t=out:st={fade_start:.3f}:d={fade_out_sec:.3f}",
            *H264_RENDER_ARGS,
            "-c:a", "aac",
            "-movflags", "+faststart",
            str(temp_output if same_path else output_path),
        ],
        log_lines,
    )
    if same_path:
        temp_output.replace(output_path)
    log_lines.append(
        f"final_outro_fade=applied duration={duration_sec:.2f}s "
        f"fade_start={fade_start:.2f}s fade_out={fade_out_sec:.2f}s"
    )
    return True


def _atempo_filter_chain(speed: float) -> str:
    filters: list[str] = []
    remaining = max(speed, 0.01)
    while remaining > 2.0:
        filters.append("atempo=2.00000")
        remaining /= 2.0
    while remaining < 0.5:
        filters.append("atempo=0.50000")
        remaining /= 0.5
    filters.append(f"atempo={remaining:.5f}")
    return ",".join(filters)


def normalize_audio_duration(
    ffmpeg_path: str,
    input_path: Path,
    output_path: Path,
    duration_sec: float,
    log_lines: list[str],
    voice_duration_sec: float | None = None,
) -> dict:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    input_duration = _audio_duration_seconds(ffmpeg_path, input_path)
    try:
        voice_target = float(voice_duration_sec) if voice_duration_sec is not None else float(duration_sec)
    except (TypeError, ValueError):
        voice_target = float(duration_sec)
    voice_target = max(0.5, min(float(duration_sec), voice_target))
    tail_hold_sec = max(0.0, float(duration_sec) - voice_target)
    audio_filter = f"apad=pad_dur={duration_sec:.2f},atrim=0:{duration_sec:.2f}"
    fit_info = {
        "inputDurationSec": round(float(input_duration), 3) if input_duration else None,
        "targetDurationSec": round(float(duration_sec), 3),
        "voiceTargetDurationSec": round(float(voice_target), 3),
        "tailHoldSec": round(float(tail_hold_sec), 3),
        "speed": 1.0,
        "mode": "pad-trim",
    }
    if input_duration and input_duration > voice_target + 0.12:
        speed = min(max(input_duration / voice_target, 1.0), 4.0)
        audio_filter = f"{_atempo_filter_chain(speed)},{audio_filter}"
        fit_info["speed"] = round(speed, 3)
        fit_info["mode"] = "tempo-fit"
        log_lines.append(
            f"audio_duration_fit=input={input_duration:.2f}s target={duration_sec:.2f}s "
            f"voice_target={voice_target:.2f}s tail={tail_hold_sec:.2f}s "
            f"speed={speed:.3f} mode=tempo-fit"
        )
    elif input_duration:
        log_lines.append(
            f"audio_duration_fit=input={input_duration:.2f}s target={duration_sec:.2f}s "
            f"voice_target={voice_target:.2f}s tail={tail_hold_sec:.2f}s mode=pad-trim"
        )
    else:
        log_lines.append(
            f"audio_duration_fit=input=unknown target={duration_sec:.2f}s "
            f"voice_target={voice_target:.2f}s tail={tail_hold_sec:.2f}s mode=pad-trim"
        )
    run_ffmpeg(
        ffmpeg_path,
        [
            "-y",
            "-i", str(input_path),
            "-af", audio_filter,
            "-ar", "48000",
            "-ac", "1",
            "-c:a", "pcm_s16le",
            str(output_path),
        ],
        log_lines,
    )
    return fit_info


def mix_sfx_into_scene_audio(
    ffmpeg_path: str,
    audio_path: Path,
    sfx_path: Path,
    output_path: Path,
    volume: float,
    log_lines: list[str],
) -> None:
    """Mix SFX track into scene audio using amix, writing to output_path."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    run_ffmpeg(
        ffmpeg_path,
        [
            "-y",
            "-i", str(audio_path),
            "-i", str(sfx_path),
            "-filter_complex", f"[1:a]volume={volume}[sfx];[0:a][sfx]amix=inputs=2:duration=first[aout]",
            "-map", "[aout]",
            "-ar", "48000",
            "-ac", "1",
            "-c:a", "pcm_s16le",
            str(output_path),
        ],
        log_lines,
    )


def create_scene_clip(
    ffmpeg_path: str,
    visual_kind: str,
    visual_path: Path,
    audio_path: Path,
    clip_path: Path,
    duration_sec: float,
    motion_preset: str = DEFAULT_MOTION_PRESET,
    log_lines: list[str] | None = None,
) -> None:
    if log_lines is None:
        log_lines = []
    clip_path.parent.mkdir(parents=True, exist_ok=True)

    if visual_kind == "image":
        motion_filter = zoompan_filter(
            preset=motion_preset,
            duration_sec=duration_sec,
            fps=int(FRAME_RATE),
            width=1080,
            height=1920,
        )

        if motion_filter:
            # zoompan reads image once and produces video frames
            run_ffmpeg(
                ffmpeg_path,
                [
                    "-y",
                    "-i", str(visual_path),
                    "-i", str(audio_path),
                    "-vf", f"{motion_filter},format=yuv420p",
                    "-t", f"{duration_sec:.2f}",
                    *H264_RENDER_ARGS,
                    "-c:a", "aac",
                    str(clip_path),
                ],
                log_lines,
            )
            return

        # Fallback: static loop (no motion)
        input_args = [
            "-loop", "1",
            "-framerate", FRAME_RATE,
            "-t", f"{duration_sec:.2f}",
            "-i", str(visual_path),
        ]
    else:
        input_args = ["-stream_loop", "-1", "-i", str(visual_path)]

    run_ffmpeg(
        ffmpeg_path,
        [
            "-y",
            *input_args,
            "-i", str(audio_path),
            "-map", "0:v:0",
            "-map", "1:a:0",
            "-t", f"{duration_sec:.2f}",
            "-vf", VIDEO_FILTER,
            *H264_RENDER_ARGS,
            "-c:a", "aac",
            str(clip_path),
        ],
        log_lines,
    )


# ---------------------------------------------------------------------------
# BGM / TTS helpers
# ---------------------------------------------------------------------------
BGM_MOOD_FOLDER_ALIASES: dict[str, tuple[str, ...]] = {
    "calm": ("calm", "tech-house"),
    "upbeat": ("upbeat", "energetic", "tech-house"),
    "energetic": ("energetic", "upbeat", "tech-house"),
    "tense": ("tense", "cinematic"),
    "cinematic": ("cinematic",),
    "tech-house": ("tech-house", "upbeat", "energetic"),
}

BGM_REPETITION_RISK_TERMS = ("coffee", "cafe", "café", "espresso")
BGM_PLACEHOLDER_RISK_TERMS = (
    "procedural",
    "ffmpeg-procedural",
    "local://ffmpeg",
    "local://video-studio/procedural",
    "sine",
    "beep",
    "bleep",
    "click",
    "test-tone",
    "test tone",
    "fallback-tone",
    "lavfi",
)


def _normalized_bgm_mood(value: object) -> str:
    return str(value or "").strip().lower().replace("_", "-")


def _bgm_mood_dirs(bgm_dir: Path, mood: str | None) -> list[Path]:
    normalized = _normalized_bgm_mood(mood)
    if not normalized:
        return []
    candidates = BGM_MOOD_FOLDER_ALIASES.get(normalized, (normalized,))
    dirs: list[Path] = []
    seen: set[str] = set()
    for name in (normalized, *candidates):
        folder_name = _normalized_bgm_mood(name)
        if not folder_name or folder_name in seen:
            continue
        seen.add(folder_name)
        candidate = bgm_dir / folder_name
        if candidate.is_dir():
            dirs.append(candidate)
    return dirs


def _bgm_track_repetition_risk(track: Path) -> bool:
    label = " ".join((track.name, track.stem, track.parent.name)).lower()
    return any(term in label for term in BGM_REPETITION_RISK_TERMS)


def _bgm_quality_risk_reason_from_text(value: object) -> str:
    lowered = str(value or "").strip().lower()
    if not lowered:
        return ""
    compact = re.sub(r"[\s_]+", "-", lowered)
    for term in BGM_PLACEHOLDER_RISK_TERMS:
        normalized = re.sub(r"[\s_]+", "-", term.lower())
        if term.lower() in lowered or normalized in compact:
            return term
    return ""


def _bgm_track_metadata(track: Path) -> dict:
    sidecar_candidates = (
        track.with_suffix(f"{track.suffix}.json"),
        track.with_suffix(".json"),
        track.parent / "sources.json",
        track.parent.parent / "sources.json",
    )
    for sidecar in sidecar_candidates:
        if not sidecar.exists():
            continue
        try:
            payload = json.loads(sidecar.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict) and track.name in payload and isinstance(payload[track.name], dict):
            return payload[track.name]
        if isinstance(payload, dict) and track.stem in payload and isinstance(payload[track.stem], dict):
            return payload[track.stem]
        if isinstance(payload, dict) and any(
            key in payload
            for key in ("sourceUrl", "sourceLicense", "license", "licenseUrl", "attribution", "sourceAttribution")
        ):
            return payload
    return {}


def _bgm_track_quality_risk_reason(track: Path) -> str:
    metadata = _bgm_track_metadata(track)
    values = [track.as_posix(), track.name, track.stem, track.parent.name]
    if metadata:
        values.extend(str(value) for value in metadata.values() if value not in (None, ""))
    return _bgm_quality_risk_reason_from_text(" ".join(values))


def _stable_bgm_choice(tracks: list[Path], selection_key: str | None) -> tuple[Path, str]:
    ordered_tracks = sorted(tracks, key=lambda item: item.as_posix().lower())
    if not ordered_tracks:
        raise ValueError("tracks must not be empty")
    if selection_key:
        digest = hashlib.sha256(selection_key.encode("utf-8")).hexdigest()
        index = int(digest[:12], 16) % len(ordered_tracks)
        return ordered_tracks[index], "stable-hash"
    return ordered_tracks[0], "stable-first"


def _bgm_track_has_provenance(track: Path) -> bool:
    payload = _bgm_track_metadata(track)
    return bool(
        payload
        and any(
            str(payload.get(key) or "").strip()
            for key in ("sourceUrl", "sourceLicense", "license", "licenseUrl", "attribution", "sourceAttribution")
        )
    )


def _bgm_selection_pool(tracks: list[Path]) -> tuple[list[Path], int]:
    provenance_ready = [track for track in tracks if _bgm_track_has_provenance(track)]
    clean_provenance_ready = [track for track in provenance_ready if not _bgm_track_quality_risk_reason(track)]
    clean_tracks = [track for track in tracks if not _bgm_track_quality_risk_reason(track)]
    if len(clean_provenance_ready) >= 2:
        low_repetition = [track for track in clean_provenance_ready if not _bgm_track_repetition_risk(track)]
        if len(low_repetition) >= 2:
            return low_repetition, len(provenance_ready)
        return clean_provenance_ready, len(provenance_ready)
    if len(clean_tracks) >= 2:
        low_repetition = [track for track in clean_tracks if not _bgm_track_repetition_risk(track)]
        return (low_repetition or clean_tracks), len(provenance_ready)
    if len(provenance_ready) >= 2:
        low_repetition = [track for track in provenance_ready if not _bgm_track_repetition_risk(track)]
        if len(low_repetition) >= 2:
            return low_repetition, len(provenance_ready)
        return provenance_ready, len(provenance_ready)
    low_repetition = [track for track in tracks if not _bgm_track_repetition_risk(track)]
    return (low_repetition or tracks), len(provenance_ready)


def select_bgm_track(
    project_root: Path,
    mood: str | None = None,
    emotion: str | None = None,
    selection_key: str | None = None,
) -> dict:
    """Select a BGM track with deterministic project/template-aware rotation evidence."""
    from worker.render.bgm import EMOTION_MOOD_MAP

    bgm_dir = project_root / "assets" / "bgm"
    if not bgm_dir.is_dir():
        return {"path": None, "candidateCount": 0, "mood": mood or "", "selectionMethod": "missing-library"}

    # Map emotion to mood if mood not directly specified
    if not mood and emotion:
        mood = EMOTION_MOOD_MAP.get(emotion.lower(), "calm")

    # If a mood is specified, look in that subfolder and its proven free-audio aliases first.
    if mood:
        requested_mood = _normalized_bgm_mood(mood)
        mood_dirs = _bgm_mood_dirs(bgm_dir, requested_mood)
        if mood_dirs:
            tracks = [
                f
                for mood_dir in mood_dirs
                for f in mood_dir.iterdir()
                if f.is_file() and f.suffix.lower() in BGM_EXTENSIONS
            ]
            if tracks:
                selection_pool, provenance_count = _bgm_selection_pool(tracks)
                if provenance_count < 2:
                    all_tracks = [f for f in bgm_dir.rglob("*") if f.is_file() and f.suffix.lower() in BGM_EXTENSIONS]
                    fallback_pool, fallback_provenance_count = _bgm_selection_pool(all_tracks)
                    if fallback_provenance_count >= 2:
                        path, method = _stable_bgm_choice(
                            fallback_pool,
                            f"{selection_key}|provenance-fallback" if selection_key else None,
                        )
                        return {
                            "path": path,
                            "candidateCount": len(all_tracks),
                            "provenanceReadyCandidateCount": fallback_provenance_count,
                            "mood": "provenance-fallback",
                            "requestedMood": requested_mood,
                            "selectionKey": selection_key or "",
                            "selectionMethod": method,
                        }
                path, method = _stable_bgm_choice(
                    selection_pool,
                    f"{selection_key}|{requested_mood}|mood-alias" if selection_key else None,
                )
                return {
                    "path": path,
                    "candidateCount": len(tracks),
                    "provenanceReadyCandidateCount": provenance_count,
                    "mood": path.parent.name,
                    "requestedMood": requested_mood,
                    "moodCandidateDirs": [item.name for item in mood_dirs],
                    "selectionKey": selection_key or "",
                    "selectionMethod": method,
                }
    # Collect all tracks from all subdirectories
    tracks = [f for f in bgm_dir.rglob("*") if f.is_file() and f.suffix.lower() in BGM_EXTENSIONS]
    if not tracks:
        return {"path": None, "candidateCount": 0, "mood": mood or "", "selectionMethod": "empty-library"}
    selection_pool, provenance_count = _bgm_selection_pool(tracks)
    path, method = _stable_bgm_choice(selection_pool, f"{selection_key}|all" if selection_key else None)
    return {
        "path": path,
        "candidateCount": len(tracks),
        "provenanceReadyCandidateCount": provenance_count,
        "mood": mood or "all",
        "selectionKey": selection_key or "",
        "selectionMethod": method,
    }


def find_bgm_track(
    project_root: Path,
    mood: str | None = None,
    emotion: str | None = None,
    selection_key: str | None = None,
) -> Path | None:
    """Find a BGM track from the local assets/bgm/ library.

    Uses RENDERING-SPEC §4.1 emotion→mood mapping when emotion is provided.
    """
    selection = select_bgm_track(project_root, mood=mood, emotion=emotion, selection_key=selection_key)
    path = selection.get("path")
    return path if isinstance(path, Path) else None


def prepare_bgm_track(
    ffmpeg_path: str,
    bgm_source: Path,
    output_path: Path,
    duration_sec: float,
    volume: float,  # kept for backward compat but unused (RENDERING-SPEC mandates -8dB)
    log_lines: list[str],
) -> None:
    """Trim/loop BGM to duration with RENDERING-SPEC §4.2 volume rules.

    - Base volume: -8dB (non-narration segments)
    - Fade-in: 0.5s, Fade-out: 1.0s
    - Sidechain ducking to -18dB is handled in mix_bgm_into_output.
    """
    from worker.render.bgm import prepare_bgm_for_video
    try:
        prepare_bgm_for_video(
            bgm_path=str(bgm_source),
            output_path=str(output_path),
            duration_sec=duration_sec,
            ffmpeg_path=ffmpeg_path,
        )
    except RuntimeError as e:
        log_lines.append(f"bgm_prepare_error={e}")


def mix_bgm_into_output(
    ffmpeg_path: str,
    video_path: Path,
    bgm_path: Path,
    output_path: Path,
    log_lines: list[str],
) -> None:
    """Mix BGM into video with audible sidechain ducking (RENDERING-SPEC §4.3).

    Narration present: BGM is ducked under speech without disappearing.
    Narration absent: BGM at prepared volume (-8dB from prepare step).
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    # Sidechain ducking: compress BGM when narration audio is present
    filter_complex = (
        "[0:a]asplit=2[narr][sc];"
        "[sc]aformat=channel_layouts=mono,"
        "compand=attacks=0:decays=0.3:"
        "points=-80/-80|-45/-45|-27/-30|0/-30,"
        "aformat=channel_layouts=stereo[sidechain];"
        f"[1:a]volume={BGM_MIX_GAIN:.3f}[bgm_in];"
        "[bgm_in][sidechain]sidechaincompress="
        f"threshold={BGM_DUCK_THRESHOLD:.3f}:ratio={BGM_DUCK_RATIO:.2f}:"
        f"attack=10:release={BGM_DUCK_RELEASE_MS}:level_sc=1[bgm_ducked];"
        "[narr][bgm_ducked]amix=inputs=2:duration=first[aout]"
    )
    run_ffmpeg(
        ffmpeg_path,
        [
            "-y",
            "-i", str(video_path),
            "-i", str(bgm_path),
            "-filter_complex", filter_complex,
            "-map", "0:v",
            "-map", "[aout]",
            "-c:v", "copy",
            "-c:a", "aac",
            "-movflags", "+faststart",
            str(output_path),
        ],
        log_lines,
    )


def normalize_final_audio_loudness(
    ffmpeg_path: str,
    video_path: Path,
    output_path: Path,
    log_lines: list[str],
) -> bool:
    """Normalize final render audio for Shorts-style playback loudness."""
    if not FINAL_AUDIO_LOUDNORM_ENABLED:
        log_lines.append("audio_loudnorm=disabled")
        return False
    if not video_path.exists():
        log_lines.append(f"audio_loudnorm=skipped missing_input={video_path}")
        return False

    output_path.parent.mkdir(parents=True, exist_ok=True)
    same_path = video_path.resolve() == output_path.resolve()
    source_path = video_path
    preserved_path = output_path.with_name(f"{output_path.stem}.pre-loudnorm{output_path.suffix}")
    temp_output = output_path.with_name(f"{output_path.stem}.loudnorm.tmp{output_path.suffix}")
    if same_path:
        shutil.copy2(output_path, preserved_path)
        source_path = preserved_path

    limiter_limit = max(0.0625, min(1.0, 10 ** (FINAL_AUDIO_LIMITER_TP / 20)))
    loudnorm_filter = (
        f"loudnorm=I={FINAL_AUDIO_TARGET_I:.1f}:"
        f"TP={FINAL_AUDIO_TARGET_TP:.1f}:"
        f"LRA={FINAL_AUDIO_TARGET_LRA:.1f}:print_format=summary,"
        f"alimiter=limit={limiter_limit:.3f}:"
        f"attack={FINAL_AUDIO_LIMITER_ATTACK_MS:.1f}:"
        f"release={FINAL_AUDIO_LIMITER_RELEASE_MS:.1f}:level=false"
    )
    try:
        run_ffmpeg(
            ffmpeg_path,
            [
                "-y",
                "-i", str(source_path),
                "-map", "0:v:0",
                "-map", "0:a:0",
                "-c:v", "copy",
                "-af", loudnorm_filter,
                "-ar", "48000",
                "-c:a", "aac",
                "-movflags", "+faststart",
                str(temp_output),
            ],
            log_lines,
        )
        if temp_output.exists():
            os.replace(temp_output, output_path)
            log_lines.append(
                "audio_loudnorm=applied "
                f"I={FINAL_AUDIO_TARGET_I:.1f} TP={FINAL_AUDIO_TARGET_TP:.1f} LRA={FINAL_AUDIO_TARGET_LRA:.1f}"
            )
            log_lines.append(
                "audio_peak_limiter=applied "
                f"TP={FINAL_AUDIO_LIMITER_TP:.1f} limit={limiter_limit:.3f} "
                f"attack={FINAL_AUDIO_LIMITER_ATTACK_MS:.1f} release={FINAL_AUDIO_LIMITER_RELEASE_MS:.1f}"
            )
            return True
    except Exception as exc:
        log_lines.append(f"audio_loudnorm=failed error={exc}")
        logger.warning("Final audio loudness normalization failed: %s", exc)
    finally:
        if temp_output.exists():
            try:
                temp_output.unlink()
            except OSError:
                pass
    return False


def synthesize_edge_tts(
    text: str,
    output_path: Path,
    scene_cache_dir: Path,
    project_root: Path,
) -> bool:
    """Try Edge TTS adapter. Returns True if audio file was created."""
    from worker.media.adapters import AdapterExecutionContext, run_local_media_adapter

    prompt_file = scene_cache_dir / f"{output_path.stem}.tts-prompt.txt"
    prompt_file.parent.mkdir(parents=True, exist_ok=True)
    prompt_file.write_text(text.strip(), encoding="utf-8")

    context = AdapterExecutionContext(
        adapterKey="edge-tts",
        sceneId=output_path.stem,
        sceneTitle="",
        prompt=text.strip(),
        durationSec=0,
        projectRoot=str(project_root),
        cacheDir=str(scene_cache_dir),
        route="edge-tts",
        manifestPath="",
        promptPath=str(prompt_file),
        outputPath=str(output_path),
        requestPath=str(scene_cache_dir / f"{output_path.stem}.tts-request.json"),
        logPath=str(scene_cache_dir / f"{output_path.stem}.tts-log.txt"),
    )
    result = run_local_media_adapter("edge-tts", context, project_root=project_root)
    return result.succeeded is True and output_path.exists()
