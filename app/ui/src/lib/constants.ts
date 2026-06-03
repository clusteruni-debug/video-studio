import type { TemplateType, TonePreset } from "./bridge";

export const TEMPLATE_LABELS: Record<TemplateType, string> = {
  community_read: "커뮤니티 글 읽기",
  news_explainer: "뉴스/팩트 해설",
  reddit_translation: "해외 글 번역",
  ranking_list: "Top N 랭킹",
  origin_story: "기원/역사 스토리",
  vs_comparison: "A vs B 비교",
  myth_buster: "팩트체크/오해와진실",
  tutorial_steps: "단계별 튜토리얼",
  before_after: "비포/애프터",
  hot_take: "핫테이크/논쟁",
  authentic_vlog: "한국형 브이로그",
  persona_story: "캐릭터/페르소나 스토리",
  kculture_fandom: "K-컬처 팬덤형",
  podcast_clip: "팟캐스트/롱폼 클립",
  longform_deep_dive: "롱폼 딥다이브",
  interview_documentary: "인터뷰/다큐형",
  live_recap: "라이브/현장 리캡",
};

export const TONE_LABELS: Record<TonePreset, string> = {
  casual_heyo: "해요체 (캐주얼)",
  commentary: "해설체",
  banmal: "반말",
  story: "이야기체",
  formal_soft: "존댓말 (부드러운)",
};

export const TTS_LABELS: Record<string, string> = {
  edge: "Edge TTS (무료)",
  elevenlabs: "ElevenLabs",
  google: "Google Cloud TTS",
  "openai-tts": "OpenAI TTS",
};

export const SUBTITLE_STYLE_LABELS: Record<string, string> = {
  "": "기본 (SRT)",
  default: "표준 스타일",
  news: "뉴스/해설",
  story: "스토리텔링",
  ranking: "랭킹/퀴즈",
  minimal: "미니멀",
  impact: "임팩트 (노랑 강조)",
};
