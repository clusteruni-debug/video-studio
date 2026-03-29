import { useState, useEffect, useRef } from "react";
import { ChevronDown, ChevronRight, Loader, Sparkles, Trash2 } from "lucide-react";
import { useStudioState, useStudioActions } from "../context/StudioContext";
import { TEMPLATE_LABELS, TONE_LABELS, TTS_LABELS, SUBTITLE_STYLE_LABELS } from "../lib/constants";
import type { TemplateType, TonePreset } from "../lib/bridge";
import UsageCard from "./UsageCard";

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
    prompt, lang, templateType, tone, ttsProvider, voiceGender, subtitleStyle,
    targetDuration, customInstruction,
    bridgeStatus, availableProviders, availableTemplates, creating, error,
    projects, activeProjectId, usageStats,
  } = state;

  return (
    <aside className="sidebar">
      {/* Prompt */}
      <div className="sidebar-section">
        <div className="sidebar-field">
          <span>주제 / 프롬프트</span>
          <textarea
            value={prompt}
            onChange={(e) => actions.setPrompt(e.target.value)}
            placeholder="영상 주제를 입력하세요 (예: 비트코인의 역사)"
            rows={3}
          />
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
          <><Sparkles size={14} /> 초안 생성</>
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
