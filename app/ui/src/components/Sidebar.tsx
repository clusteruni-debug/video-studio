import { useState, useEffect, useRef } from "react";
import { ChevronDown, ChevronRight, Loader, Sparkles, Trash2 } from "lucide-react";
import { useStudioState, useStudioActions } from "../context/StudioContext";
import { TEMPLATE_LABELS, TONE_LABELS, TTS_LABELS, SUBTITLE_STYLE_LABELS } from "../lib/constants";
import type { TemplateType, TonePreset } from "../lib/bridge";
import UsageCard from "./UsageCard";

const TEMPLATE_GUIDANCE: Partial<Record<TemplateType, {
  pattern: string;
  sourceMix: string;
  layout: string;
  assets: string;
  avoid: string;
}>> = {
  news_explainer: {
    pattern: "뉴스/해설형",
    sourceMix: "Pexels/Pixabay/Wikimedia는 맥락 컷, 1번 컷은 강한 움직임",
    layout: "상단 hook 이후 작은 lower fact 중심",
    assets: "Pexels Video, Pixabay Video, Wikimedia Commons, YouTube Audio Library",
    avoid: "관련 있어 보이는 stock top-1 자동 채택",
  },
  ranking_list: {
    pattern: "랭킹/리스트형",
    sourceMix: "순위마다 다른 영상 후보를 직접 선택",
    layout: "고정 rank label + 빠르지만 규칙적인 컷",
    assets: "Pexels/Pixabay 후보 5개 이상, 직접 캡처는 권리 확인",
    avoid: "같은 B-roll 반복 루프",
  },
  tutorial_steps: {
    pattern: "튜토리얼형",
    sourceMix: "직접 화면/손 동작 촬영이 1순위",
    layout: "상단 step label, 세부 설명은 lower-info",
    assets: "직접 녹화, CC0 아이콘, Pexels 보조 컷",
    avoid: "실제 조작 없이 이미지 설명만 나열",
  },
  authentic_vlog: {
    pattern: "한국형 브이로그",
    sourceMix: "직접 촬영 MP4 + 필요한 보조 B-roll",
    layout: "전체 화면 움직임, caption은 none/lower-info",
    assets: "직접 업로드, Pexels/Pixabay, YouTube Audio Library/Mixkit BGM",
    avoid: "광고처럼 보이는 과장 자막과 반복 stock",
  },
  persona_story: {
    pattern: "페르소나/AI 스토리",
    sourceMix: "Grok/SuperGrok 또는 로컬 Wan/LTX/Hunyuan hero",
    layout: "동일 캐릭터/장소/소품, 첫 컷 top hook",
    assets: "Grok MP4 handoff, 로컬 모델 MP4, Pexels texture insert",
    avoid: "컷마다 얼굴·의상·소품이 바뀌는 AI slop",
  },
  kculture_fandom: {
    pattern: "K-컬처 팬덤형",
    sourceMix: "저작권 안전 대체 컷 + 직접/생성 fan process",
    layout: "비트 친화 컷, safe-zone callout만 작게",
    assets: "직접 이벤트 footage, CC/stock city-stage B-roll, YouTube Audio Library",
    avoid: "원본 MV/드라마/음원 무단 삽입",
  },
  podcast_clip: {
    pattern: "롱폼/팟캐스트 클립",
    sourceMix: "소유한 원본 클립 또는 TTS 요약 + B-roll",
    layout: "speaker crop, waveform/chapter card, lower caption",
    assets: "소유 원본, Freesound SFX, YouTube Audio Library bed",
    avoid: "권리 없는 발화를 실제 화자처럼 재현",
  },
  longform_deep_dive: {
    pattern: "롱폼 딥다이브",
    sourceMix: "챕터 카드 + 직접 만든 데이터 카드 + 무료 B-roll",
    layout: "느린 컷, chapter/title card, lower fact 중심",
    assets: "직접 제작 그래픽, Pexels/Pixabay/Wikimedia, YouTube Audio Library",
    avoid: "쇼츠식 과한 중앙 자막과 반복 stock 컷",
  },
  interview_documentary: {
    pattern: "인터뷰/다큐형",
    sourceMix: "소유 인터뷰/현장 MP4가 1순위, 없으면 TTS 요약",
    layout: "speaker/손동작/장소 중심, 작은 lower caption",
    assets: "직접 인터뷰, 현장 B-roll, Freesound ambience, Wikimedia 증빙 컷",
    avoid: "권리 없는 화자를 AI 음성으로 흉내내기",
  },
  live_recap: {
    pattern: "라이브/현장 리캡",
    sourceMix: "직접 촬영 현장 컷 + 권리 안전한 분위기 컷",
    layout: "동선/포인트별 chapter chip, 비트는 유지하되 자막은 작게",
    assets: "직접 촬영, Mixkit/Pexels city-stage B-roll, YouTube Audio Library",
    avoid: "공연 음원/MV/방송 화면 무단 삽입",
  },
};

export default function Sidebar() {
  const state = useStudioState();
  const actions = useStudioActions();
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    if (state.creating) {
      setElapsed(0);
      timerRef.current = setInterval(() => setElapsed((e) => e + 1), 1000);
    } else {
      if (timerRef.current) { clearInterval(timerRef.current); timerRef.current = null; }
    }
    return () => { if (timerRef.current) clearInterval(timerRef.current); };
  }, [state.creating]);

  const {
    prompt, lang, templateType, tone, ttsProvider, voiceGender, subtitleStyle, bgmEnabled,
    targetDuration, customInstruction,
    bridgeStatus, availableProviders, availableTemplates, creating, error,
    projects, activeProjectId, usageStats,
  } = state;
  const templateGuidance = TEMPLATE_GUIDANCE[templateType];

  return (
    <aside className="sidebar">
      {/* Production seed memo */}
      <div className="sidebar-section">
        <div className="sidebar-field">
          <span>소재 메모</span>
          <textarea
            value={prompt}
            onChange={(e) => actions.setPrompt(e.target.value)}
            placeholder="아직 소재가 없으면 비워두고 상단의 소재 탭에서 후보부터 찾으세요."
            rows={3}
          />
          <small className="sidebar-help-text">검증한 소재의 핵심 질문과 선택 이유를 여기에 붙이면 기획 초안에 반영됩니다.</small>
        </div>
      </div>

      {/* Template + Tone */}
      <div className="sidebar-section">
        <div className="sidebar-field compact">
          <span>템플릿</span>
          <select
            value={templateType}
            onChange={(e) => actions.setTemplateType(e.target.value as TemplateType)}
          >
            {availableTemplates.map((t) => (
              <option key={t} value={t}>{TEMPLATE_LABELS[t] || t}</option>
            ))}
          </select>
        </div>
        {templateGuidance && (
          <div className="template-guidance-card">
            <div className="template-guidance-head">
              <strong>{templateGuidance.pattern}</strong>
              <span>{templateGuidance.sourceMix}</span>
            </div>
            <dl className="template-guidance-list">
              <div>
                <dt>화면 구성</dt>
                <dd>{templateGuidance.layout}</dd>
              </div>
              <div>
                <dt>사용 소스</dt>
                <dd>{templateGuidance.assets}</dd>
              </div>
              <div>
                <dt>피할 것</dt>
                <dd>{templateGuidance.avoid}</dd>
              </div>
            </dl>
          </div>
        )}
        <div className="sidebar-field compact">
          <span>어조</span>
          <select
            value={tone}
            onChange={(e) => actions.setTone(e.target.value as TonePreset)}
          >
            {(Object.keys(TONE_LABELS) as TonePreset[]).map((t) => (
              <option key={t} value={t}>{TONE_LABELS[t]}</option>
            ))}
          </select>
        </div>
      </div>

      {/* Duration + Custom instruction */}
      <div className="sidebar-section">
        <div className="sidebar-field compact">
          <span>영상 길이</span>
          <div className="mode-toggle duration-toggle">
            {(["30s", "1min", "custom"] as const).map((d) => (
              <button
                key={d}
                className={`mode-toggle-btn duration-toggle-btn ${targetDuration === d ? "active" : ""}`}
                onClick={() => actions.setTargetDuration(d)}
              >
                {d === "30s" ? "30초" : d === "1min" ? "1분" : "자유"}
              </button>
            ))}
          </div>
        </div>
        <div className="sidebar-field compact">
          <span>추가 지시 (선택)</span>
          <textarea
            value={customInstruction}
            onChange={(e) => actions.setCustomInstruction(e.target.value)}
            placeholder="예: 숫자 데이터를 많이 포함해줘"
            rows={2}
            style={{ fontSize: "0.82rem" }}
          />
        </div>
      </div>

      {/* Advanced settings */}
      <button
        className="sidebar-collapse-toggle"
        onClick={() => setAdvancedOpen(!advancedOpen)}
      >
        {advancedOpen ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
        상세 설정
      </button>

      {advancedOpen && (
        <div className="sidebar-advanced">
          <div className="sidebar-field compact">
            <span>언어</span>
            <select value={lang} onChange={(e) => actions.setLang(e.target.value as "ko" | "en")}>
              <option value="ko">한국어</option>
              <option value="en">English</option>
            </select>
          </div>
          <div className="sidebar-field compact">
            <span>TTS 엔진</span>
            <select value={ttsProvider} onChange={(e) => actions.setTtsProvider(e.target.value)}>
              {availableProviders.map((p) => (
                <option key={p} value={p}>{TTS_LABELS[p] || p}</option>
              ))}
            </select>
          </div>
          <div className="sidebar-field compact">
            <span>음성</span>
            <select value={voiceGender} onChange={(e) => actions.setVoiceGender(e.target.value as "female" | "male")}>
              <option value="female">여성</option>
              <option value="male">남성</option>
            </select>
          </div>
          <div className="sidebar-field compact">
            <span>자막 스타일</span>
            <select value={subtitleStyle} onChange={(e) => actions.setSubtitleStyle(e.target.value)}>
              {Object.entries(SUBTITLE_STYLE_LABELS).map(([k, v]) => (
                <option key={k} value={k}>{v}</option>
              ))}
            </select>
          </div>
          <div className="sidebar-field compact">
            <span>BGM</span>
            <label style={{ display: "flex", alignItems: "center", gap: 6, cursor: "pointer" }}>
              <input
                type="checkbox"
                checked={bgmEnabled}
                onChange={(e) => actions.setBgmEnabled(e.target.checked)}
              />
              <span style={{ fontSize: 13 }}>자동 BGM 매칭</span>
            </label>
          </div>
        </div>
      )}

      {/* Usage stats */}
      <UsageCard stats={usageStats} onRefresh={actions.refreshUsageStats} />

      <div className="sidebar-divider" />

      {/* Generate button */}
      <button
        className="generate-button"
        disabled={creating || bridgeStatus !== "connected" || !prompt.trim()}
        onClick={actions.handleCreate}
      >
        {creating ? (
          <><Loader size={14} style={{ animation: "spin 1s linear infinite" }} /> 생성 중... {elapsed}s</>
        ) : (
          <><Sparkles size={14} /> 기획 초안 생성</>
        )}
      </button>

      {/* Error */}
      {error && (
        <div style={{ padding: "8px 10px", background: "var(--error-dim)", borderRadius: "var(--radius-sm)", color: "var(--error)", fontSize: "0.82rem" }}>
          {error}
        </div>
      )}

      <div className="sidebar-divider" />

      {/* History */}
      <div className="sidebar-history">
        <span className="sidebar-history-label">히스토리</span>
        <div className="sidebar-history-list">
          {projects.length === 0 ? (
            <div className="sidebar-history-empty">아직 생성된 프로젝트가 없습니다</div>
          ) : (
            projects.map((p) => (
              <div
                key={p.id}
                className={`sidebar-history-item ${activeProjectId === p.id ? "active" : ""}`}
              >
                <div className="sidebar-history-text">
                  <strong>{p.plan.title || p.plan.sourcePrompt.slice(0, 30)}</strong>
                  <span>{new Date(p.createdAt).toLocaleDateString("ko-KR")}</span>
                </div>
                <button
                  className="sidebar-history-remove"
                  onClick={(e) => { e.stopPropagation(); actions.deleteProject(p.id); }}
                >
                  <Trash2 size={12} />
                </button>
              </div>
            ))
          )}
        </div>
      </div>
    </aside>
  );
}
