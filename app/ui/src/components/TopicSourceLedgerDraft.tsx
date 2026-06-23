import { useMemo, useState } from "react";
import { ArrowRight, Clipboard, ExternalLink } from "lucide-react";
import type { HotTopicSourceLedgerEntry } from "../lib/bridge";

export type CandidateResearchLink = {
  label: string;
  provider?: string;
  surface: string;
  sourceType?: string;
  intent?: string;
  query: string;
  url: string;
  capturedAt?: string;
  sourceRef?: string;
  requiredForGate?: boolean;
  ledgerAction?: string;
};

type DraftValue = {
  actualUrl: string;
  observation: string;
  title: string;
};

type Props = {
  candidateId: string;
  candidateTitle: string;
  links: CandidateResearchLink[];
  capturedAt: string;
  onApply: (entries: HotTopicSourceLedgerEntry[]) => void;
};

function draftKey(link: CandidateResearchLink, index: number) {
  return `${link.surface}:${link.sourceRef ?? "candidate"}:${index}`;
}

function sourceTypeFor(link: CandidateResearchLink) {
  if (link.sourceType) return link.sourceType;
  if (link.surface === "video") return "youtube-search";
  if (link.surface === "trend") return "google-trends-kr";
  if (link.surface === "community") return "korean-community";
  return "google-search";
}

export default function TopicSourceLedgerDraft({ candidateId, candidateTitle, links, capturedAt, onApply }: Props) {
  const [drafts, setDrafts] = useState<Record<string, DraftValue>>({});
  const entries = useMemo(() => links.flatMap((link, index) => {
    const draft = drafts[draftKey(link, index)];
    const actualUrl = draft?.actualUrl.trim() ?? "";
    const observation = draft?.observation.trim() ?? "";
    if (!actualUrl || !observation) return [];
    return [{
      sourceId: `operator-${candidateId}-${link.surface}-${index + 1}`,
      sourceType: sourceTypeFor(link),
      title: draft?.title.trim() || `${candidateTitle} ${link.label} observation`,
      url: actualUrl,
      capturedAt: link.capturedAt ?? capturedAt,
      observation,
    } satisfies HotTopicSourceLedgerEntry];
  }), [candidateId, candidateTitle, capturedAt, drafts, links]);

  function updateDraft(key: string, patch: Partial<DraftValue>) {
    setDrafts((current) => ({
      ...current,
      [key]: {
        ...(current[key] ?? {
          actualUrl: "",
          observation: "",
          title: "",
        }),
        ...patch,
      },
    }));
  }

  function emptyDraft(key: string) {
    return drafts[key] ?? {
        actualUrl: "",
        observation: "",
        title: "",
      };
  }

  return (
    <details className="gate-advanced-panel">
      <summary>sourceLedger 반자동 입력</summary>
      <div className="gate-advanced-body">
        <div className="gate-help-note">
          <Clipboard size={14} />
          <span>링크를 열고 실제 URL과 관찰 메모를 적으면 검증 데이터의 sourceLedger에 반영합니다.</span>
        </div>
        {links.map((link, index) => {
          const key = draftKey(link, index);
          const draft = emptyDraft(key);
          return (
            <div className="gate-action-card" key={key}>
              <div className="gate-editor-toolbar">
                <div>
                  <span>{link.label}</span>
                  <small>{link.intent ?? link.query}</small>
                </div>
                <a className="chip" href={link.url} target="_blank" rel="noreferrer">
                  <ExternalLink size={12} /> 열기
                </a>
              </div>
              <label className="gate-discovery-field">
                <span>실제 출처 URL</span>
                <input
                  value={draft.actualUrl}
                  onChange={(event) => updateDraft(key, { actualUrl: event.target.value })}
                  placeholder={link.url}
                />
              </label>
              <label className="gate-discovery-field">
                <span>관찰 메모</span>
                <textarea
                  value={draft.observation}
                  onChange={(event) => updateDraft(key, { observation: event.target.value })}
                  placeholder="반복 질문, 조회/댓글 맥락, 트렌드 움직임, 커뮤니티 반응처럼 실제로 본 내용을 적습니다."
                  rows={2}
                />
              </label>
              <label className="gate-discovery-field">
                <span>출처 제목 (선택)</span>
                <input
                  value={draft.title}
                  onChange={(event) => updateDraft(key, { title: event.target.value })}
                  placeholder={`${candidateTitle} ${link.label} observation`}
                />
              </label>
            </div>
          );
        })}
        <button className="generate-button gate-primary-action" onClick={() => onApply(entries)} disabled={!entries.length}>
          <ArrowRight size={14} />
          sourceLedger 초안에 반영 ({entries.length})
        </button>
      </div>
    </details>
  );
}
