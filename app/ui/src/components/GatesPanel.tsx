import { useEffect, useMemo, useState } from "react";
import { AlertTriangle, ArrowRight, CheckCircle2, Clipboard, Loader, RotateCcw, Search, ShieldCheck, XCircle } from "lucide-react";
import {
  evaluateLongformDryrunGate,
  evaluateTopicDiscoveryGate,
  fetchHotTopicCandidates,
  type GateEvaluationResult,
  type GateUxCheckSummary,
  type HotTopicCandidate,
  type HotTopicCandidatesResult,
  type HotTopicQueryPlanEntry,
  type HotTopicSourceLedgerEntry,
} from "../lib/bridge";
import { useStudioActions, useStudioState } from "../context/StudioContext";
import MaterialLibraryPanel, { type MaterialProductionHandoff } from "./MaterialLibraryPanel";
import ProductionWorkflowGatePanel from "./ProductionWorkflowGatePanel";
import TopicSourceLedgerDraft, { type CandidateResearchLink } from "./TopicSourceLedgerDraft";

type GateMode = "discover" | "topic" | "longform";
type EvaluationMode = Exclude<GateMode, "discover">;
const HOT_DISCOVERY_SEED = "오늘 한국에서 가장 뜨거운 소재";
type DiscoveryCandidate = HotTopicCandidate & {
  researchLinks?: CandidateResearchLink[];
  scoreBreakdown?: Record<string, number>;
  rankingReason?: string;
  nextPipelineAction?: string;
};
type DiscoveryScaffoldOptions = {
  sourceLedger?: HotTopicSourceLedgerEntry[];
  researchQueryPlan?: HotTopicQueryPlanEntry[];
};

const STEP_COPY: Record<GateMode, {
  step: string;
  title: string;
  body: string;
  button: string;
  checks: string[];
}> = {
  discover: {
    step: "0단계",
    title: "오늘 뜨는 소재부터 찾기",
    body: "키워드가 없어도 시작합니다. 기본값은 오늘 한국에서 가장 뜨거운 소재이고, 입력값은 선택 필터로만 씁니다.",
    button: "오늘 핫한 소재 찾기",
    checks: ["실시간 관심", "트렌드", "영상 경쟁", "한국 커뮤니티"],
  },
  topic: {
    step: "1단계",
    title: "찾은 소재가 만들 가치가 있는지 확인",
    body: "소재 후보, 실제 출처, 한국 커뮤니티 신호, 트렌드 교차 확인, 롱폼 유지력을 한 번에 검사합니다.",
    button: "소재 검증 실행",
    checks: ["후보 비교", "실제 출처", "커뮤니티 신호", "롱폼 유지력"],
  },
  longform: {
    step: "2단계",
    title: "10분 영상 제작 준비 상태 확인",
    body: "소재 검증 결과, 제작 순서, 롱폼 조건, 렌더 전 점검이 모두 맞물리는지 사전 검사합니다.",
    button: "롱폼 준비 검증 실행",
    checks: ["소재 검증", "제작 순서", "롱폼 조건", "렌더 전 점검"],
  },
};

function isoToday() {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: "Asia/Seoul",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(new Date());
  const value = Object.fromEntries(parts.map((part) => [part.type, part.value]));
  return `${value.year}-${value.month}-${value.day}`;
}

const DISCOVERY_SURFACES = [
  {
    label: "Google 검색",
    role: "반복 질문과 설명 후보",
    query: (seed: string) => `${seed} 왜 궁금한가 한국어`,
    hotQuery: () => "오늘 한국에서 가장 뜨거운 이슈 궁금증",
    url: (query: string) => `https://www.google.com/search?q=${encodeURIComponent(query)}`,
  },
  {
    label: "트렌드 교차 확인",
    role: "현재성 확인",
    query: (seed: string) => seed,
    hotQuery: () => "Google Trends KR trending now",
    url: (query: string) => `https://trends.google.com/trends/explore?geo=KR&q=${encodeURIComponent(query)}`,
    hotUrl: () => "https://trends.google.com/trending?geo=KR",
  },
  {
    label: "YouTube 경쟁 영상",
    role: "제목/오프닝/댓글 질문",
    query: (seed: string) => `${seed} 설명`,
    hotQuery: () => "YouTube 인기 급상승",
    url: (query: string) => `https://www.youtube.com/results?search_query=${encodeURIComponent(query)}`,
    hotUrl: () => "https://www.youtube.com/feed/trending",
  },
  {
    label: "한국 커뮤니티",
    role: "실제 반응과 논쟁",
    query: (seed: string) => `${seed} 후기 OR 논란 OR 왜`,
    hotQuery: () => "오늘 한국 커뮤니티 인기글 논쟁",
    url: (query: string) => `https://www.google.com/search?q=${encodeURIComponent(`${query} site:dcinside.com OR site:fmkorea.com OR site:theqoo.net`)}`,
  },
];

function normalizeDiscoverySeed(seed: string) {
  return seed.trim() || HOT_DISCOVERY_SEED;
}

function isAutoHotDiscovery(seed: string) {
  return seed.trim().length === 0;
}

function discoveryQuery(surface: typeof DISCOVERY_SURFACES[number], seedValue: string) {
  return isAutoHotDiscovery(seedValue) && surface.hotQuery
    ? surface.hotQuery()
    : surface.query(normalizeDiscoverySeed(seedValue));
}

function discoveryHref(surface: typeof DISCOVERY_SURFACES[number], seedValue: string, query: string) {
  return isAutoHotDiscovery(seedValue) && surface.hotUrl
    ? surface.hotUrl()
    : surface.url(query);
}

function surfaceKind(label: string) {
  if (label.includes("YouTube")) return "video";
  if (label.includes("트렌드")) return "trend";
  if (label.includes("커뮤니티")) return "community";
  return "search";
}

function sourceTypeForSurface(surface: string) {
  if (surface === "video") return "youtube-search";
  if (surface === "trend") return "google-trends-kr";
  if (surface === "community") return "korean-community";
  return "google-search";
}

function localResearchLinks(seedValue: string): CandidateResearchLink[] {
  return DISCOVERY_SURFACES.map((surface) => {
    const query = surface.query(normalizeDiscoverySeed(seedValue));
    const surfaceType = surfaceKind(surface.label);
    return {
      label: surface.label,
      provider: sourceTypeForSurface(surfaceType),
      surface: surfaceType,
      sourceType: sourceTypeForSurface(surfaceType),
      intent: `${surface.role} 확인`,
      query,
      url: surface.url(query),
      requiredForGate: surfaceType !== "search",
      ledgerAction: "열어서 실제 관찰을 확인한 뒤 sourceLedger에 추가",
    };
  });
}

function buildDiscoveryCandidates(seedValue: string): DiscoveryCandidate[] {
  const seed = normalizeDiscoverySeed(seedValue);
  const autoHot = isAutoHotDiscovery(seedValue);
  if (autoHot) {
    return [
      {
        id: "hot-trend-why-now",
        label: "1순위",
        title: "오늘 갑자기 뜬 검색어의 이유",
        centralQuestion: "왜 이 검색어가 오늘 갑자기 올라왔고, 사람들은 무엇을 확인하려고 하는가?",
        whyHot: "급상승 검색은 현재성은 강하지만 맥락이 비어 있어 해설형 롱폼으로 확장하기 좋습니다.",
        viewerPromise: "흩어진 검색 관심을 사건, 배경, 오해, 다음 질문 순서로 정리합니다.",
        searchSeed: "오늘 한국 급상승 검색어 왜",
        first30SecPromise: "오늘 갑자기 모두가 검색한 이유와 가장 큰 오해를 먼저 보여준다.",
        score: 84,
        evidencePlan: ["Google Trends KR", "Google News KR", "YouTube 급상승", "한국 커뮤니티 반응"],
        researchLinks: localResearchLinks("오늘 한국 급상승 검색어 왜"),
      },
      {
        id: "community-split-issue",
        label: "2순위",
        title: "한국 커뮤니티에서 갈리는 생활형 논쟁",
        centralQuestion: "사람들이 같은 이슈를 두고 왜 정반대로 해석하는가?",
        whyHot: "댓글 논쟁은 훅과 반론 구조가 자연스럽고, 10분 영상에서 관점 비교로 유지력을 만들 수 있습니다.",
        viewerPromise: "양쪽 주장을 근거 단위로 분리해 시청자가 판단할 수 있게 만듭니다.",
        searchSeed: "오늘 한국 커뮤니티 논쟁 왜",
        first30SecPromise: "가장 갈리는 댓글 두 개를 먼저 보여주고, 실제 쟁점을 분리한다.",
        score: 79,
        evidencePlan: ["FMKorea/Theqoo/DCInside", "Google 검색", "관련 뉴스", "YouTube 댓글"],
        researchLinks: localResearchLinks("오늘 한국 커뮤니티 논쟁 왜"),
      },
      {
        id: "youtube-comment-question",
        label: "3순위",
        title: "YouTube 급상승 댓글의 반복 질문",
        centralQuestion: "인기 영상 댓글에서 반복되는 질문은 무엇이고, 답이 왜 부족한가?",
        whyHot: "이미 영상 소비가 있는 소재라 제목/오프닝/댓글 반응을 롱폼 설계에 바로 연결할 수 있습니다.",
        viewerPromise: "댓글에서 반복되는 질문을 근거, 예시, 반례로 풀어냅니다.",
        searchSeed: "YouTube 인기 급상승 댓글 질문 한국",
        first30SecPromise: "반복 질문 하나를 띄우고 왜 답이 갈리는지 바로 제시한다.",
        score: 74,
        evidencePlan: ["YouTube 급상승", "댓글 반복 질문", "Google 검색", "커뮤니티 재반응"],
        researchLinks: localResearchLinks("YouTube 인기 급상승 댓글 질문 한국"),
      },
    ];
  }
  return [
    {
      id: "keyword-why-now",
      label: "1순위",
      title: `${seed}이 지금 뜨는 이유`,
      centralQuestion: `${seed}은 왜 지금 다시 관심을 받고 있고, 사람들이 무엇을 확인하려 하는가?`,
      whyHot: "입력 키워드를 현재성 중심으로 좁혀 검색/트렌드/영상 표면에서 검증합니다.",
      viewerPromise: "현재 관심, 실제 근거, 오해, 판단 기준을 한 편으로 정리합니다.",
      searchSeed: `${seed} 왜 지금`,
      first30SecPromise: `${seed}을 검색한 사람이 가장 먼저 궁금해할 이유를 제시한다.`,
      score: 82,
      evidencePlan: ["Google 검색", "Google Trends KR", "YouTube 검색", "한국 커뮤니티"],
      researchLinks: localResearchLinks(`${seed} 왜 지금`),
    },
    {
      id: "keyword-community-split",
      label: "2순위",
      title: `${seed}을 두고 갈리는 반응`,
      centralQuestion: `${seed}에 대한 반응은 왜 갈리고, 어떤 근거가 더 설득력 있는가?`,
      whyHot: "커뮤니티 반론 구조가 있으면 롱폼의 중반 이탈을 줄이는 비교 구성이 가능합니다.",
      viewerPromise: "찬반/오해/반례를 분리해 시청자가 판단하게 만듭니다.",
      searchSeed: `${seed} 논란 후기 반응`,
      first30SecPromise: "가장 강한 찬반 반응을 먼저 보여주고 판단 기준을 예고한다.",
      score: 77,
      evidencePlan: ["커뮤니티 검색", "뉴스", "YouTube 댓글", "검색 추이"],
      researchLinks: localResearchLinks(`${seed} 논란 후기 반응`),
    },
    {
      id: "keyword-proof-gap",
      label: "3순위",
      title: `${seed}에 대해 아직 검증되지 않은 주장`,
      centralQuestion: `${seed} 관련 반복 주장 중 실제로 확인해야 할 것은 무엇인가?`,
      whyHot: "검증 공백이 있는 키워드는 출처 기반 해설과 시청 지속 구조를 만들기 쉽습니다.",
      viewerPromise: "반복 주장과 확인된 근거를 분리합니다.",
      searchSeed: `${seed} 진짜 근거 검증`,
      first30SecPromise: "가장 많이 반복되는 주장을 먼저 제시하고 확인할 기준을 보여준다.",
      score: 71,
      evidencePlan: ["원문 출처", "검색 결과", "영상 경쟁", "반례 자료"],
      researchLinks: localResearchLinks(`${seed} 진짜 근거 검증`),
    },
  ];
}

function candidateToTopic(candidate: DiscoveryCandidate, strong: boolean) {
  const sourceRefs = candidate.sourceRefs ?? [];
  return {
    topicId: candidate.id,
    workingTitle: candidate.title,
    centralQuestion: candidate.centralQuestion,
    knowledgeGap: "현재 관심은 보이지만 실제 출처와 판단 경로는 아직 채워야 합니다.",
    whyNow: candidate.whyHot,
    viewerPromise: candidate.viewerPromise,
    communitySignals: [],
    trendEvidence: [],
    sourcePlan: {
      primarySourceCount: sourceRefs.length,
      evidenceRefs: sourceRefs,
    },
    longformPlan: {
      chapterCount: strong ? 6 : 4,
      segmentCount: strong ? 18 : 10,
      retentionHooks: ["초반 질문", "중반 반론", "결론 예고"],
      first30SecPromise: candidate.first30SecPromise,
      titleThumbnailExpectation: "제목과 썸네일은 후보의 핵심 질문을 그대로 건드려야 합니다.",
      topMomentPreview: "가장 강한 증거 장면은 실제 sourceLedger를 채운 뒤 확정합니다.",
      dipRiskMitigations: [
        { risk: "출처가 비어 있어 자기 주장처럼 보임", mitigation: "실제 URL과 관찰 메모를 먼저 채운다." },
        { risk: "핫하다는 주장만 있고 롱폼 깊이가 부족함", mitigation: "반론/오해/후속 질문 챕터를 만든다." },
      ],
      chapterPromises: Array.from({ length: strong ? 6 : 4 }, (_, index) => ({
        chapterId: `chapter-${String(index + 1).padStart(2, "0")}`,
        promise: `${index + 1}번째 챕터에서 후보 질문의 일부를 출처 기반으로 확인한다.`,
      })),
    },
    riskReview: {
      unverifiedRumor: true,
      defamationRisk: false,
      privacyRisk: false,
      protectedClassAttack: false,
      minorSafetyRisk: false,
      medicalLegalFinancialHighStakes: false,
      factCheckPlan: "검증 전에는 주장하지 않고, 실제 URL/sourceLedger를 채운 뒤 스크립트를 작성한다.",
    },
    originalityReview: {
      notSinglePostCopy: false,
      transformativeAngle: true,
      sourceAttributionPlan: "검색/트렌드/커뮤니티/영상 출처를 reference ledger에 남긴다.",
    },
  };
}

function topicDiscoveryScaffoldPacket(
  seedValue: string,
  selectedCandidate?: DiscoveryCandidate,
  options: DiscoveryScaffoldOptions = {},
) {
  const today = isoToday();
  const autoHot = isAutoHotDiscovery(seedValue);
  const seed = selectedCandidate?.searchSeed ?? normalizeDiscoverySeed(seedValue);
  const candidates = buildDiscoveryCandidates(seedValue);
  const selected = selectedCandidate ?? candidates[0];
  const orderedCandidates = selected
    ? [selected, ...candidates.filter((candidate) => candidate.id !== selected.id)]
    : candidates;
  const selectedResearchLinks = selected?.researchLinks ?? [];
  return {
    evaluationDate: today,
    targetLocale: "ko-KR",
    targetFormat: "longform_10m",
    discoveryMode: autoHot ? "auto-hot-topic" : "keyword-filtered",
    discoverySeed: seed,
    researchQueryPlan: options.researchQueryPlan?.length
      ? options.researchQueryPlan
      : selectedResearchLinks.length
        ? selectedResearchLinks.map((link) => ({
          provider: link.provider ?? link.label,
          surface: link.surface,
          query: link.query,
          intent: link.intent ?? "후보 검증 표면 확인",
          capturedAt: link.capturedAt ?? today,
        }))
      : DISCOVERY_SURFACES.map((surface) => ({
        provider: surface.label,
        surface: surfaceKind(surface.label),
        query: selectedCandidate ? surface.query(seed) : discoveryQuery(surface, seedValue),
        intent: `${surface.role} 확인`,
        capturedAt: today,
      })),
    sourceLedger: options.sourceLedger ?? [],
    topicCandidates: orderedCandidates.map((candidate, index) => candidateToTopic(candidate, index === 0)),
    selection: {
      selectedTopicId: selected?.id ?? "",
      rejections: orderedCandidates.slice(1).map((candidate) => ({
        topicId: candidate.id,
        reason: "예비 후보입니다. 실제 출처를 채운 뒤 선택/탈락 이유를 다시 써야 합니다.",
      })),
    },
    operatorTodo: [
      autoHot
        ? (options.sourceLedger?.length ? "뉴스 후보는 들어왔지만 트렌드/영상/커뮤니티 URL을 추가로 채워 교차 확인하세요." : "키워드 없이 시작했으므로 오늘의 트렌드/인기글/인기 영상에서 실제 후보를 먼저 골라 sourceLedger에 채우세요.")
        : "검색/트렌드/YouTube/한국 커뮤니티에서 실제 URL을 sourceLedger에 채우세요.",
      "최소 3개 후보 소재를 topicCandidates에 만들고 선택/탈락 이유를 분리하세요.",
      "선택 소재는 첫 30초 약속, 챕터 약속, 중반 이탈 방지책까지 적은 뒤 검증하세요.",
    ],
  };
}

function topicPassingExamplePacket() {
  const today = isoToday();
  const selectedTopicId = "ai-study-proof";
  const candidate = (topicId: string, strong: boolean) => {
    const chapterCount = strong ? 6 : 3;
    const evidenceRefs = Array.from({ length: strong ? 6 : 2 }, (_, index) => `source-${index + 1}`);
    return {
      topicId,
      workingTitle: strong ? "AI 공부 인증은 실제로 효과가 있을까" : `${topicId} 후보 소재`,
      centralQuestion: "시청자가 영상이 끝난 뒤 답할 수 있어야 하는 핵심 질문은 무엇인가?",
      knowledgeGap: "커뮤니티 관심은 있지만 검증된 판단 경로가 부족하다.",
      whyNow: "최근 한국 커뮤니티, 검색, 영상 표면에서 다시 관심이 보인다.",
      viewerPromise: "흩어진 관심을 근거 있는 판단으로 정리한다.",
      communitySignals: [
        {
          sourceId: "dcinside-hot",
          signalType: "repeat-question",
          observation: "실제 효과를 묻는 질문이 반복된다.",
          capturedAt: today,
        },
        {
          sourceId: strong ? "fmkorea-best" : "dcinside-hot",
          signalType: "debate-thread",
          observation: "댓글이 같은 근거 공백을 두고 갈린다.",
          capturedAt: today,
        },
      ],
      trendEvidence: [
        {
          sourceId: "google-trends-kr",
          trendDirection: "rising",
          metricLabel: "관련 검색어 상승",
          observation: "관련 질의 움직임이 현재성을 뒷받침한다.",
        },
        {
          sourceId: strong ? "naver-datalab" : "google-trends-kr",
          trendDirection: "stable-high",
          metricLabel: "검색 추이 비교",
          observation: "최근 구간에서 검색 관심이 유지된다.",
        },
      ],
      sourcePlan: {
        primarySourceCount: evidenceRefs.length,
        evidenceRefs,
      },
      longformPlan: {
        chapterCount,
        segmentCount: strong ? 18 : 9,
        retentionHooks: strong ? ["초반 질문", "중반 반례", "결론 예고"] : ["초반 질문"],
        first30SecPromise: "가장 강한 질문, 이해관계, 볼 이유를 첫 30초에 보여준다.",
        titleThumbnailExpectation: "오프닝이 제목과 썸네일의 궁금증을 바로 건드린다.",
        topMomentPreview: "첫 챕터 전에 가장 강한 근거 장면을 예고한다.",
        dipRiskMitigations: [
          { risk: "검색 근거가 추상적으로 보임", mitigation: "구체적 비교 장면으로 전환" },
          { risk: "커뮤니티 논쟁이 반복됨", mitigation: "반례 챕터를 중간에 배치" },
        ],
        chapterPromises: Array.from({ length: chapterCount }, (_, index) => ({
          chapterId: `chapter-${String(index + 1).padStart(2, "0")}`,
          promise: `${index + 1}번째 챕터에서 시청자 질문 하나를 해결한다.`,
        })),
      },
      riskReview: {
        unverifiedRumor: false,
        defamationRisk: false,
        privacyRisk: false,
        protectedClassAttack: false,
        minorSafetyRisk: false,
        medicalLegalFinancialHighStakes: false,
        factCheckPlan: "스크립트 작성 전에 모든 주장을 지속 가능한 출처로 재확인한다.",
      },
      originalityReview: {
        notSinglePostCopy: true,
        transformativeAngle: true,
        sourceAttributionPlan: "인용한 출처는 reference ledger에 남긴다.",
      },
    };
  };

  return {
    evaluationDate: today,
    targetLocale: "ko-KR",
    targetFormat: "longform_10m",
    researchQueryPlan: [
      {
        provider: "google-search",
        surface: "search",
        query: "AI 공부 인증 진짜 효과",
        intent: "한국어 웹에서 반복되는 질문과 설명 후보를 찾는다.",
        capturedAt: today,
      },
      {
        provider: "google-trends-kr",
        surface: "trend",
        query: "AI 공부",
        intent: "한국 검색 관심의 현재성을 확인한다.",
        capturedAt: today,
      },
      {
        provider: "youtube-search",
        surface: "video",
        query: "AI 공부 인증",
        intent: "영상 경쟁 구도와 시청자 약속 패턴을 확인한다.",
        capturedAt: today,
      },
      {
        provider: "korean-community-scan",
        surface: "community",
        query: "AI 공부 인증 후기",
        intent: "한국 커뮤니티의 질문과 반론을 확인한다.",
        capturedAt: today,
      },
      {
        provider: "naver-datalab",
        surface: "trend",
        query: "AI 공부, 공부 인증",
        intent: "네이버 검색 수요로 교차 확인한다.",
        capturedAt: today,
      },
    ],
    sourceLedger: [
      {
        sourceId: "google-search",
        sourceType: "google-search",
        title: "Google 한국어 웹 검색",
        url: "https://www.google.com/search?q=AI+%EA%B3%B5%EB%B6%80+%EC%9D%B8%EC%A6%9D",
        capturedAt: today,
        observation: "일반 검색에서 반복 질문 구도가 보인다.",
      },
      {
        sourceId: "google-trends-kr",
        sourceType: "google-trends-kr",
        title: "Google Trends KR",
        url: "https://trends.google.com/trending?geo=KR",
        capturedAt: today,
        observation: "트렌드 표면이 현재성을 뒷받침한다.",
      },
      {
        sourceId: "naver-datalab",
        sourceType: "naver-datalab",
        title: "Naver DataLab",
        url: "https://datalab.naver.com/",
        capturedAt: today,
        observation: "한국 검색 추이를 교차 확인한다.",
      },
      {
        sourceId: "youtube-search",
        sourceType: "youtube-search",
        title: "YouTube 검색",
        url: "https://www.youtube.com/results?search_query=AI+%EA%B3%B5%EB%B6%80+%EC%9D%B8%EC%A6%9D",
        capturedAt: today,
        observation: "영상 경쟁과 시청자 약속 패턴을 확인한다.",
      },
      {
        sourceId: "dcinside-hot",
        sourceType: "korean-community",
        title: "한국 커뮤니티 반복 질문",
        url: "https://www.dcinside.com/",
        capturedAt: today,
        observation: "커뮤니티 글에서 같은 실용 질문이 반복된다.",
      },
      {
        sourceId: "fmkorea-best",
        sourceType: "community-forum",
        title: "한국 커뮤니티 댓글 묶음",
        url: "https://www.fmkorea.com/",
        capturedAt: today,
        observation: "댓글에서 구체적인 전후 비교 요구가 보인다.",
      },
    ],
    topicCandidates: [
      candidate(selectedTopicId, true),
      candidate("summer-power-bill", false),
      candidate("commute-heat-map", false),
    ],
    selection: {
      selectedTopicId,
      rejections: [
        { topicId: "summer-power-bill", reason: "10분짜리 근거 체인으로 만들기에는 깊이가 부족하다." },
        { topicId: "commute-heat-map", reason: "트렌드 근거가 충분히 교차 확인되지 않았다." },
      ],
    },
  };
}

function longformSkeletonPacket(topicDiscoveryPacket: Record<string, unknown> = topicDiscoveryScaffoldPacket("소재 키워드")) {
  return {
    targetStage: "rough-cut",
    topicDiscoveryPacket,
    workflowPacket: {
      formatProfile: "longform_10m",
      workflowStages: [],
      workflowImprovementLoop: {},
      seededFailureSuite: [],
    },
    productionModePacket: {
      formatProfile: "longform_10m",
    },
    renderManifest: {
      formatProfile: "longform_10m",
      projectId: "dashboard-longform-dryrun",
    },
  };
}

function stringify(value: unknown) {
  return JSON.stringify(value, null, 2);
}

function parseJson(value: string): { packet?: Record<string, unknown>; error?: string } {
  try {
    const parsed = JSON.parse(value);
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
      return { error: "원본 데이터는 JSON 객체여야 합니다." };
    }
    return { packet: parsed as Record<string, unknown> };
  } catch (error) {
    const message = error instanceof Error ? error.message : "JSON 형식이 올바르지 않습니다.";
    return { error: `원본 데이터 형식을 확인하세요. ${message}` };
  }
}

function statusClass(status?: string) {
  if (status === "pass") return "pass";
  if (status === "fail") return "fail";
  return "warn";
}

function StatusIcon({ status }: { status?: string }) {
  if (status === "pass") return <CheckCircle2 size={14} />;
  if (status === "fail") return <XCircle size={14} />;
  return <AlertTriangle size={14} />;
}

function fallbackCheckSummaries(result: GateEvaluationResult): GateUxCheckSummary[] {
  const checks = result.report?.checks ?? {};
  return Object.entries(checks).map(([key, check]) => ({
    key,
    label: key,
    status: check.status,
    detail: check.detail,
  }));
}

function ResultPanel({ mode, result }: { mode: EvaluationMode; result: GateEvaluationResult | null }) {
  const step = STEP_COPY[mode];
  if (!result) {
    return (
      <div className="gate-result-empty">
        <ShieldCheck size={18} />
        <strong>아직 검사 전입니다.</strong>
        <span>{step.button} 버튼을 누르면 막힌 항목만 정리해서 보여줍니다.</span>
      </div>
    );
  }

  const checks = result.ux?.checkSummaries?.length ? result.ux.checkSummaries : fallbackCheckSummaries(result);
  const failed = result.ux?.failedChecks ?? result.failedChecks?.map((key) => ({ key, label: key })) ?? [];
  const selectedTopic = result.report?.selectedTopicId;
  const score = result.report?.selectedScore;
  const minimumScore = result.report?.minimumScore;

  return (
    <div className={`gate-result ${result.ready ? "pass" : "fail"}`}>
      <div className="gate-result-head">
        <div>
          <span>{result.ux?.title ?? step.title}</span>
          <strong>{result.ux?.statusLabel ?? (result.ready ? "통과" : "보완 필요")}</strong>
        </div>
        <small>{result.status || result.report?.status || "상태 확인"}</small>
      </div>

      <div className="gate-result-message">
        <p>{result.ux?.primaryMessage ?? (result.ready ? "기준을 통과했습니다." : "막힌 항목이 있습니다.")}</p>
        {result.ux?.nextAction ? (
          <div className="gate-next-action">
            <ArrowRight size={14} />
            <span>{result.ux.nextAction}</span>
          </div>
        ) : null}
      </div>

      {selectedTopic ? (
        <div className="gate-score-strip">
          <span>선택 소재: {selectedTopic}</span>
          <span>점수: {score ?? 0}/{minimumScore ?? 0}</span>
        </div>
      ) : null}

      {failed.length ? (
        <div className="gate-fail-list">
          <strong>먼저 고칠 항목</strong>
          <div>
            {failed.map((item) => (
              <span key={item.key}>{item.label}</span>
            ))}
          </div>
        </div>
      ) : null}

      <div className="gate-check-list">
        {checks.map((check) => (
          <div key={check.key} className={`gate-check-row ${statusClass(check.status)}`}>
            <StatusIcon status={check.status} />
            <div className="gate-check-meta">
              <span>{check.label}</span>
              <p>{check.detail || "세부 설명 없음"}</p>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

export default function GatesPanel() {
  const { prompt } = useStudioState();
  const actions = useStudioActions();
  const [mode, setMode] = useState<GateMode>("discover");
  const [discoverySeed, setDiscoverySeed] = useState(prompt);
  const [selectedCandidateId, setSelectedCandidateId] = useState<string | null>(null);
  const [candidateResult, setCandidateResult] = useState<HotTopicCandidatesResult | null>(null);
  const [candidateLoading, setCandidateLoading] = useState(false);
  const [candidateError, setCandidateError] = useState<string | null>(null);
  const [candidateAutoLoaded, setCandidateAutoLoaded] = useState(false);
  const defaultTopicJson = useMemo(() => stringify(topicDiscoveryScaffoldPacket("소재 키워드")), []);
  const defaultLongformJson = useMemo(() => stringify(longformSkeletonPacket()), []);
  const [topicJson, setTopicJson] = useState(defaultTopicJson);
  const [longformJson, setLongformJson] = useState(defaultLongformJson);
  const [topicResult, setTopicResult] = useState<GateEvaluationResult | null>(null);
  const [longformResult, setLongformResult] = useState<GateEvaluationResult | null>(null);
  const [running, setRunning] = useState<GateMode | null>(null);
  const [parseError, setParseError] = useState<string | null>(null);

  useEffect(() => {
    if (!discoverySeed.trim() && prompt.trim()) {
      setDiscoverySeed(prompt);
    }
  }, [discoverySeed, prompt]);

  const activeStep = STEP_COPY[mode];
  const evaluationMode: EvaluationMode = mode === "longform" ? "longform" : "topic";
  const activeJson = evaluationMode === "topic" ? topicJson : longformJson;
  const activeResult = evaluationMode === "topic" ? topicResult : longformResult;
  const topicPassed = topicResult?.ready === true;
  const rawDiscoverySeed = (discoverySeed || prompt).trim();
  const autoHotDiscovery = isAutoHotDiscovery(rawDiscoverySeed);
  const fallbackDiscoveryCandidates = useMemo(() => buildDiscoveryCandidates(rawDiscoverySeed), [rawDiscoverySeed]);
  const routedCandidates = candidateResult?.candidates?.length ? candidateResult.candidates as DiscoveryCandidate[] : null;
  const discoveryCandidates = routedCandidates ?? fallbackDiscoveryCandidates;
  const selectedCandidate = discoveryCandidates.find((candidate) => candidate.id === selectedCandidateId) ?? discoveryCandidates[0];
  const discoveryLinks = DISCOVERY_SURFACES.map((surface) => {
    const query = selectedCandidate ? surface.query(selectedCandidate.searchSeed) : discoveryQuery(surface, rawDiscoverySeed);
    return { ...surface, query, href: discoveryHref(surface, rawDiscoverySeed, query) };
  });
  const selectedResearchLinks = selectedCandidate.researchLinks?.length
    ? selectedCandidate.researchLinks
    : discoveryLinks.map((surface) => ({
      label: surface.label,
      provider: sourceTypeForSurface(surfaceKind(surface.label)),
      surface: surfaceKind(surface.label),
      sourceType: sourceTypeForSurface(surfaceKind(surface.label)),
      intent: `${surface.role} 확인`,
      query: surface.query,
      url: surface.href,
      requiredForGate: surfaceKind(surface.label) !== "search",
      ledgerAction: "열어서 실제 관찰을 확인한 뒤 sourceLedger에 추가",
    }));
  const selectedTopicPacket = useMemo(
    () => topicDiscoveryScaffoldPacket(rawDiscoverySeed, selectedCandidate, {
      sourceLedger: candidateResult?.sourceLedger ?? [],
      researchQueryPlan: candidateResult?.researchQueryPlan ?? [],
    }) as Record<string, unknown>,
    [rawDiscoverySeed, selectedCandidate, candidateResult],
  );
  const parsedTopicPacket = useMemo(() => parseJson(topicJson).packet ?? selectedTopicPacket, [topicJson, selectedTopicPacket]);

  useEffect(() => {
    if (!candidateAutoLoaded) {
      setCandidateAutoLoaded(true);
      void loadHotCandidates(rawDiscoverySeed);
    }
  }, [candidateAutoLoaded, rawDiscoverySeed]);

  useEffect(() => {
    if (!discoveryCandidates.some((candidate) => candidate.id === selectedCandidateId)) {
      setSelectedCandidateId(discoveryCandidates[0]?.id ?? null);
    }
  }, [discoveryCandidates, selectedCandidateId]);

  async function loadHotCandidates(seed = rawDiscoverySeed) {
    setCandidateLoading(true);
    setCandidateError(null);
    const result = await fetchHotTopicCandidates(seed, 3);
    if (result.ok && result.candidates?.length) {
      setCandidateResult(result);
      setSelectedCandidateId(result.candidates[0].id);
    } else {
      setCandidateResult(null);
      setSelectedCandidateId(fallbackDiscoveryCandidates[0]?.id ?? null);
      setCandidateError(result.error || "후보를 불러오지 못해 로컬 fallback 후보를 보여줍니다.");
    }
    setCandidateLoading(false);
  }

  function scaffoldOptions(): DiscoveryScaffoldOptions {
    return {
      sourceLedger: candidateResult?.sourceLedger ?? [],
      researchQueryPlan: candidateResult?.researchQueryPlan ?? [],
    };
  }

  function mergedSourceLedger(draftedEntries: HotTopicSourceLedgerEntry[]) {
    const ledger = new Map<string, HotTopicSourceLedgerEntry>();
    for (const entry of candidateResult?.sourceLedger ?? []) {
      ledger.set(entry.sourceId, entry);
    }
    for (const entry of draftedEntries) {
      ledger.set(entry.sourceId, entry);
    }
    return Array.from(ledger.values());
  }

  function applyResearchLedgerDrafts(draftedEntries: HotTopicSourceLedgerEntry[]) {
    const sourceLedger = mergedSourceLedger(draftedEntries);
    setTopicJson(stringify(topicDiscoveryScaffoldPacket(rawDiscoverySeed, selectedCandidate, {
      ...scaffoldOptions(),
      sourceLedger,
    })));
    setTopicResult(null);
    setMode("topic");
    setParseError(null);
  }

  function buildDiscoveryScaffold(candidate: DiscoveryCandidate = selectedCandidate) {
    setSelectedCandidateId(candidate.id);
    setTopicJson(stringify(topicDiscoveryScaffoldPacket(rawDiscoverySeed, candidate, scaffoldOptions())));
    setTopicResult(null);
    setMode("topic");
    setParseError(null);
  }

  function copyDiscoverySeedToSidebar() {
    actions.setPrompt(`${selectedCandidate.title}\n${selectedCandidate.centralQuestion}`);
  }

  function useProductionHandoff(handoff: MaterialProductionHandoff) {
    actions.setPrompt(handoff.promptMemo);
    actions.setActiveTab("plan");
    setParseError(null);
  }

  async function runGate() {
    if (mode === "discover") {
      buildDiscoveryScaffold();
      return;
    }
    setParseError(null);
    const parsed = parseJson(activeJson);
    if (parsed.error || !parsed.packet) {
      setParseError(parsed.error || "원본 데이터 형식이 올바르지 않습니다.");
      return;
    }
    setRunning(mode);
    try {
      const result = mode === "topic"
        ? await evaluateTopicDiscoveryGate(parsed.packet)
        : await evaluateLongformDryrunGate(parsed.packet);
      if (mode === "topic") {
        setTopicResult(result);
        if (result.ready) {
          setLongformJson(stringify(longformSkeletonPacket(parsed.packet)));
        }
      } else {
        setLongformResult(result);
      }
    } finally {
      setRunning(null);
    }
  }

  function resetScaffold() {
    setParseError(null);
    if (mode === "topic") {
      const next = stringify(topicDiscoveryScaffoldPacket(rawDiscoverySeed, selectedCandidate, scaffoldOptions()));
      setTopicJson(next);
      setTopicResult(null);
    } else {
      const next = stringify(longformSkeletonPacket(topicDiscoveryScaffoldPacket(rawDiscoverySeed, selectedCandidate, scaffoldOptions())));
      setLongformJson(next);
      setLongformResult(null);
    }
  }

  function loadPassingExample() {
    setParseError(null);
    if (mode === "topic") {
      setTopicJson(stringify(topicPassingExamplePacket()));
      setTopicResult(null);
    } else {
      setLongformJson(stringify(longformSkeletonPacket(topicPassingExamplePacket())));
      setLongformResult(null);
    }
  }

  function copyTopicIntoDryrun() {
    const parsed = parseJson(topicJson);
    if (parsed.error || !parsed.packet) {
      setParseError(parsed.error || "소재 원본 데이터가 올바르지 않습니다.");
      return;
    }
    setLongformJson(stringify(longformSkeletonPacket(parsed.packet)));
    setMode("longform");
    setParseError(null);
  }

  return (
    <div className="gate-workbench">
      <div className="gate-workbench-head">
        <div>
          <div className="render-review-kicker">제작 전 필수 검문</div>
          <h2>소재를 먼저 찾고, 그다음 검증합니다</h2>
          <p>소재 후보와 실제 출처가 없으면 검증 점수는 의미가 없습니다. 찾기, 후보 비교, 검증, 롱폼 준비 순서로 진행합니다.</p>
        </div>
      </div>

      <div className="gate-step-strip">
        {(Object.keys(STEP_COPY) as GateMode[]).map((stepKey) => {
          const step = STEP_COPY[stepKey];
          const result = stepKey === "topic" ? topicResult : stepKey === "longform" ? longformResult : null;
          return (
            <button
              key={stepKey}
              className={`gate-step-card ${mode === stepKey ? "active" : ""} ${result?.ready ? "pass" : result ? "fail" : ""}`}
              onClick={() => {
                setMode(stepKey);
                setParseError(null);
              }}
            >
              <span>{step.step}</span>
              <strong>{stepKey === "discover" ? "소재 찾기" : stepKey === "topic" ? "소재 검증" : "롱폼 준비"}</strong>
              <small>{stepKey === "discover" ? "시작" : result ? (result.ready ? "통과" : "보완 필요") : "대기"}</small>
            </button>
          );
        })}
      </div>

      <ProductionWorkflowGatePanel focus="topic" />

      {mode === "discover" ? (
        <div className="gate-main-grid">
          <section className="gate-action-card">
            <span className="gate-step-badge">{activeStep.step}</span>
            <h3>{activeStep.title}</h3>
            <p>{activeStep.body}</p>

            <label className="gate-discovery-field">
              <span>탐색 키워드 (선택)</span>
              <textarea
                value={discoverySeed}
                onChange={(event) => {
                  setDiscoverySeed(event.target.value);
                  setCandidateResult(null);
                  setSelectedCandidateId(null);
                  setCandidateError(null);
                }}
                placeholder="비워두면 오늘 한국에서 가장 뜨거운 소재부터 찾습니다."
                rows={3}
              />
              <small>{autoHotDiscovery ? "현재는 무키워드 핫 토픽 모드입니다. 키워드를 넣으면 그 주제로 좁혀 찾습니다." : "입력한 키워드는 필터일 뿐이고, 실제 후보와 URL은 다음 단계에서 검증합니다."}</small>
            </label>

            <div className="gate-action-list">
              {activeStep.checks.map((item) => (
                <span key={item}>{item}</span>
              ))}
            </div>

            <div className="gate-candidate-stack">
              <div className="gate-candidate-stack-head">
                <div>
                  <strong>{autoHotDiscovery ? "추천 탐색 후보" : "키워드 기반 후보"}</strong>
                  <span>{candidateResult?.live ? "실시간 뉴스 후보" : candidateResult ? "fallback 후보" : "로컬 예비 후보"}</span>
                </div>
                <button className="subtle-button" onClick={() => loadHotCandidates(rawDiscoverySeed)} disabled={candidateLoading}>
                  {candidateLoading ? <Loader size={13} className="spin" /> : <Search size={13} />}
                  후보 새로고침
                </button>
              </div>
              {candidateResult?.operatorWarning ? (
                <div className={`gate-help-note ${candidateResult.live ? "" : "warn"}`}>
                  <AlertTriangle size={14} />
                  <span>{candidateResult.operatorWarning}</span>
                </div>
              ) : null}
              {candidateError ? (
                <div className="gate-help-note warn">
                  <AlertTriangle size={14} />
                  <span>{candidateError}</span>
                </div>
              ) : null}
              {discoveryCandidates.map((candidate) => (
                <button
                  key={candidate.id}
                  className={`gate-topic-candidate ${selectedCandidate.id === candidate.id ? "active" : ""}`}
                  onClick={() => setSelectedCandidateId(candidate.id)}
                >
                  <span className="gate-topic-candidate-rank">{candidate.label}</span>
                  <div className="gate-topic-candidate-main">
                    <strong>{candidate.title}</strong>
                    <p>{candidate.centralQuestion}</p>
                    <small>{candidate.whyHot}</small>
                    {candidate.rankingReason ? <small>{candidate.rankingReason}</small> : null}
                  </div>
                  <span className="gate-topic-candidate-score">{candidate.sourceStatus === "live-news-seed" ? "LIVE" : candidate.score}</span>
                </button>
              ))}
            </div>

            <div className="gate-discovery-surface-grid">
              {selectedResearchLinks.map((surface) => (
                <a key={`${surface.surface}-${surface.query}`} href={surface.url} target="_blank" rel="noreferrer" className="gate-discovery-surface">
                  <strong>{surface.label}</strong>
                  <span>{surface.intent}</span>
                  <small>{surface.query}</small>
                </a>
              ))}
            </div>

            <button className="generate-button gate-primary-action" onClick={() => buildDiscoveryScaffold()}>
              <Search size={14} />
              {selectedCandidate.title} 검증 준비
            </button>

            <div className="gate-secondary-actions">
              <button className="subtle-button" onClick={copyDiscoverySeedToSidebar}>
                <Clipboard size={13} /> 왼쪽 메모에 반영
              </button>
            </div>

            {parseError ? <div className="gate-parse-error">{parseError}</div> : null}
          </section>

          <section className="gate-result-panel">
            <div className="gate-discovery-brief">
              <Search size={20} />
              <strong>{selectedCandidate.title}</strong>
              <p>{selectedCandidate.viewerPromise}</p>
              <div className="gate-selected-candidate-plan">
                {selectedCandidate.evidencePlan.map((item) => (
                  <span key={item}>{item}</span>
                ))}
              </div>
              {selectedCandidate.scoreBreakdown ? (
                <div className="gate-selected-candidate-plan">
                  {Object.entries(selectedCandidate.scoreBreakdown).map(([key, value]) => (
                    <span key={key}>{key}: {value}</span>
                  ))}
                </div>
              ) : null}
              {selectedCandidate.nextPipelineAction ? <p>{selectedCandidate.nextPipelineAction}</p> : null}
              <strong>선택 후보 검증 링크</strong>
              <div className="gate-discovery-surface-grid">
                {selectedResearchLinks.map((link) => (
                  <a key={`${link.surface}-${link.query}`} href={link.url} target="_blank" rel="noreferrer" className="gate-discovery-surface">
                    <strong>{link.label}</strong>
                    <span>{link.ledgerAction ?? "확인 후 sourceLedger에 추가"}</span>
                    <small>{link.query}</small>
                  </a>
                ))}
              </div>
              <TopicSourceLedgerDraft
                candidateId={selectedCandidate.id}
                candidateTitle={selectedCandidate.title}
                links={selectedResearchLinks}
                capturedAt={isoToday()}
                onApply={applyResearchLedgerDrafts}
              />
              <MaterialLibraryPanel
                candidate={selectedCandidate}
                topicPacket={selectedTopicPacket}
                topicGateResult={topicResult}
                onUseProductionHandoff={useProductionHandoff}
              />
              <ol>
                <li>위 표면에서 실제 URL을 확인합니다.</li>
                <li>후보 소재 3개 이상과 실제 URL을 기록합니다.</li>
                <li>선택 이유와 탈락 이유를 분리한 뒤 소재 검증을 실행합니다.</li>
              </ol>
            </div>
          </section>
        </div>
      ) : (
        <div className="gate-main-grid">
        <section className="gate-action-card">
          <span className="gate-step-badge">{activeStep.step}</span>
          <h3>{activeStep.title}</h3>
          <p>{activeStep.body}</p>

          <div className="gate-action-list">
            {activeStep.checks.map((item) => (
              <span key={item}>{item}</span>
            ))}
          </div>

          {mode === "longform" && !topicPassed ? (
            <div className="gate-help-note warn">
              <AlertTriangle size={14} />
              <span>권장 순서: 먼저 1단계 소재 검증을 통과한 뒤 실행하세요.</span>
            </div>
          ) : null}

          {mode === "topic" ? (
            <MaterialLibraryPanel
              candidate={selectedCandidate}
              topicPacket={parsedTopicPacket}
              topicGateResult={topicResult}
              onUseProductionHandoff={useProductionHandoff}
            />
          ) : null}

          <button className="generate-button gate-primary-action" onClick={runGate} disabled={running !== null}>
            {running === mode ? <Loader size={14} className="spin" /> : <ShieldCheck size={14} />}
            {activeStep.button}
          </button>

          <div className="gate-secondary-actions">
            <button className="subtle-button" onClick={resetScaffold} title="빈 검증 데이터 복원">
              <RotateCcw size={13} /> 빈 데이터 복원
            </button>
            <button className="subtle-button" onClick={loadPassingExample} title="구조 참고용 예시">
              <Clipboard size={13} /> 예시 데이터 보기
            </button>
            {mode === "topic" ? (
              <button className="subtle-button" onClick={copyTopicIntoDryrun}>
                <ArrowRight size={13} /> 2단계에 반영
              </button>
            ) : null}
          </div>

          <details className="gate-advanced-panel">
            <summary>고급: 원본 데이터 보기/수정</summary>
            <div className="gate-advanced-body">
              <div className="gate-editor-toolbar">
                <div>
                  <span>{mode === "topic" ? "소재 검증 데이터" : "롱폼 준비 검증 데이터"}</span>
                  <small>게이트가 실제로 검사하는 원본입니다.</small>
                </div>
                <button className="chip" onClick={() => navigator.clipboard?.writeText(activeJson)} title="원본 복사">
                  <Clipboard size={12} /> 원본 복사
                </button>
              </div>
              <textarea
                className="gate-json-editor"
                spellCheck={false}
                value={activeJson}
                onChange={(event) => {
                  if (mode === "topic") setTopicJson(event.target.value);
                  else setLongformJson(event.target.value);
                }}
              />
            </div>
          </details>

          {parseError ? <div className="gate-parse-error">{parseError}</div> : null}
        </section>

        <section className="gate-result-panel">
          <ResultPanel mode={mode} result={activeResult} />
        </section>
      </div>
      )}
    </div>
  );
}
