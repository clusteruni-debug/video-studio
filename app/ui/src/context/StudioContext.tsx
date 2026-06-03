import { createContext, useContext, useEffect, useMemo, useReducer, useRef } from "react";
import {
  checkHealth, createDraft as apiCreateDraft, submitJob as apiSubmitJob,
  createBatch as apiCreateBatch, getBatchStatus, listBatches as apiListBatches,
  listJobs as apiListJobs, deleteBatch as apiDeleteBatch, deleteJob as apiDeleteJob,
  regenerateSceneTts as apiRegenerateTts, generateImage as apiGenerateImage,
  searchPexelsVideos as apiSearchPexelsVideos, renderSmoke as apiRenderSmoke,
  createFreeAssetSourcingPacket as apiCreateFreeAssetSourcingPacket,
  finalizeRender as apiFinalizeRender,
  generateLocalVideoScene as apiGenerateLocalVideoScene,
  importLocalVideoFolder as apiImportLocalVideoFolder,
  createGrokHandoff as apiCreateGrokHandoff, getGrokHandoffStatus as apiGetGrokHandoffStatus,
  openGrokHandoff as apiOpenGrokHandoff, getGrokHandoffRenderPayload as apiGetGrokHandoffRenderPayload,
  getGrokHandoffRenderPreviewPayload as apiGetGrokHandoffRenderPreviewPayload,
  getGrokAutomationPlan as apiGetGrokAutomationPlan, importGrokDownloads as apiImportGrokDownloads,
  uploadGrokSceneMp4 as apiUploadGrokSceneMp4,
  uploadGrokSceneMp4Batch as apiUploadGrokSceneMp4Batch,
  watchGrokDownloads as apiWatchGrokDownloads,
  startGrokManualDownloadWatch as apiStartGrokManualDownloadWatch,
  runGrokBrowserAutomation as apiRunGrokBrowserAutomation,
  resumeGrokBrowserAutomation as apiResumeGrokBrowserAutomation,
  focusGrokOperatorBrowser as apiFocusGrokOperatorBrowser,
  cleanupGrokOperatorTabs as apiCleanupGrokOperatorTabs,
  startGrokBackgroundAutomation as apiStartGrokBackgroundAutomation,
  saveGrokReviewDecision as apiSaveGrokReviewDecision,
  fetchUsageStats,
  type BridgeHealth, type DraftResult, type Scene, type TemplateType, type TonePreset, type GrokAuthProvider,
  type BatchStatus, type JobStatus, type UsageStats, type PexelsVideoCandidate,
  type FreeAssetSourcingPacket,
  type RenderSmokeResult, type SceneAssetPayload, type DraftScenePayload, type CaptionPreset,
  type VisualQualityVerdict, type BgmAssetPayload,
  type VisualSource, type LocalVideoProvider, type GrokHandoffResult, type GrokAutomationPlan,
  type GrokHandoffStatus, type GrokImportDownloadsResult, type GrokWatchDownloadsResult,
  type GrokManualDownloadWatchResult, type GrokOperatorRunResult, type GrokBrowserAutomationResult, type GrokHandoffRenderPayload, type GrokReviewDecision,
  type LocalVideoGenerateResult, type LocalVideoFolderImportResult, type GrokAutomationStatus, type GrokOperatorFocusResult, type GrokOperatorTabCleanupResult,
  type GrokOpenTarget,
} from "../lib/bridge";
import { type QueueItem, ImageGenerationQueue } from "../lib/image-queue";
import { loadStoredProjects, saveStoredProjects } from "../lib/storage";
import type { StudioProjectRecord } from "../lib/planner";
import type { BridgeStatus } from "../components/shared";

const GROK_OPERATOR_WAIT_DEFAULT_SECONDS = 600;
const GROK_OPERATOR_WAIT_MAX_SECONDS = 7200;
const GROK_BROWSER_PROFILE_DIRECTORY = "Default";
const GROK_AUTH_PROVIDER_DEFAULT: GrokAuthProvider = "google";

type GrokBrowserAutomationOptions = {
  operatorReadyTimeoutSeconds?: number;
  operatorReadyPollIntervalSeconds?: number;
  supersedeActiveJobApproved?: boolean;
  remoteDebuggingPort?: number;
  authProviderPreference?: GrokAuthProvider;
  useDefaultChromeProfile?: boolean;
  attachDefaultChromeApproved?: boolean;
  browserProfileDirectory?: string;
};

export type GrokBatchUploadMode = "auto" | "current-scene-candidates" | "scene-grouped-takes";

function grokBrowserProfilePayload(opts: GrokBrowserAutomationOptions = {}) {
  const useDefaultChromeProfile = opts.useDefaultChromeProfile === true;
  return {
    launchBrowserApproved: !useDefaultChromeProfile,
    profileApproved: !useDefaultChromeProfile,
    useDefaultChromeProfile,
    attachDefaultChromeApproved: useDefaultChromeProfile && opts.attachDefaultChromeApproved === true,
    browserProfileMode: useDefaultChromeProfile ? "default-chrome-cdp-attach" : "isolated-handoff-profile",
    browserProfileDirectory: opts.browserProfileDirectory ?? GROK_BROWSER_PROFILE_DIRECTORY,
    remoteDebuggingPort: opts.remoteDebuggingPort ?? 9222,
  };
}

function grokManualWatchDownloadDirs(downloadDir: string): string[] {
  const trimmed = downloadDir.trim();
  if (!trimmed) return [];
  const normalized = trimmed.replace(/[\\/]+$/, "");
  const separator = normalized.includes("\\") ? "\\" : "/";
  const parts = normalized.split(/[\\/]/).filter(Boolean);
  const candidates = [normalized];
  if (parts[parts.length - 1]?.toLowerCase() === "downloads") {
    const parent = normalized.slice(0, Math.max(0, normalized.length - parts[parts.length - 1].length)).replace(/[\\/]+$/, "");
    if (parent) {
      candidates.push(`${parent}${separator}Desktop`, `${parent}${separator}Videos`);
    }
  }
  const seen = new Set<string>();
  return candidates.filter((item) => {
    const key = item.toLowerCase();
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function selectedHandoffCandidateCountForScene(assets: GrokHandoffResult["assets"] | undefined, sceneId: string): number {
  const asset = assets?.find((item) => item.sceneId === sceneId && item.status === "ready");
  if (!asset) return 0;
  return Math.max(1, asset.candidateAssets?.length || 0);
}

function selectedHandoffCandidateForScene(
  assets: GrokHandoffResult["assets"] | undefined,
  sceneId: string,
  selectedFileName: string,
) {
  const asset = assets?.find((item) => item.sceneId === sceneId && item.status === "ready");
  if (!asset) return undefined;
  const candidatePool = asset.candidateAssets?.length ? asset.candidateAssets : [asset];
  const trimmed = selectedFileName.trim();
  return (
    (trimmed ? candidatePool.find((item) => item.fileName === trimmed) : undefined)
    || candidatePool.find((item) => item.selected)
    || candidatePool[0]
    || asset
  );
}

function grokSourceProvenanceConfirmationRequired(status?: string): boolean {
  return status === "local-mp4-download-unverified" || status === "local-mp4-source-unverified";
}

// ── Tab type ──

export type StudioTab = "storyboard" | "images" | "sources" | "batch" | "jobs";

// ── State ──

export interface StudioState {
  bridgeStatus: BridgeStatus;
  bridgeHealth: BridgeHealth | null;
  availableProviders: string[];
  availableTemplates: TemplateType[];

  prompt: string;
  lang: "ko" | "en";
  templateType: TemplateType;
  tone: TonePreset;
  ttsProvider: string;
  voiceGender: "female" | "male";
  subtitleStyle: string;
  bgmEnabled: boolean;
  selectedBgmAsset: BgmAssetPayload | null;
  targetDuration: "30s" | "1min" | "custom";
  customInstruction: string;

  activeTab: StudioTab;
  selectedSceneIndex: number | null;
  debugOpen: boolean;

  creating: boolean;
  rendering: boolean;
  error: string | null;
  draftResult: DraftResult | null;
  renderResult: RenderSmokeResult | null;
  grokHandoff: GrokHandoffResult | null;
  freeAssetPacket: FreeAssetSourcingPacket | null;

  projects: StudioProjectRecord[];
  activeProjectId: string | null;

  imageItems: QueueItem[];
  imageQueueProcessing: boolean;

  activeBatchId: string | null;
  batchStatus: BatchStatus | null;
  batches: BatchStatus[];

  jobs: JobStatus[];

  usageStats: UsageStats | null;

  paidConfirmDialog: {
    provider: string;
    action: string;
    estimatedCost: string;
    freeAlternative: string;
    pendingAction: "regenerate-image";
    pendingIndex: number;
  } | null;
}

const initialState: StudioState = {
  bridgeStatus: "checking",
  bridgeHealth: null,
  availableProviders: ["edge"],
  availableTemplates: ["community_read", "news_explainer", "reddit_translation", "ranking_list", "origin_story", "vs_comparison", "myth_buster", "tutorial_steps", "before_after", "hot_take", "authentic_vlog", "persona_story", "kculture_fandom", "podcast_clip", "longform_deep_dive", "interview_documentary", "live_recap"],

  prompt: "",
  lang: "ko",
  templateType: "news_explainer",
  tone: "casual_heyo",
  ttsProvider: "edge",
  voiceGender: "female",
  subtitleStyle: "",
  bgmEnabled: true,
  selectedBgmAsset: null,
  targetDuration: "30s",
  customInstruction: "",

  activeTab: "storyboard",
  selectedSceneIndex: null,
  debugOpen: false,

  creating: false,
  rendering: false,
  error: null,
  draftResult: null,
  renderResult: null,
  grokHandoff: null,
  freeAssetPacket: null,

  projects: [],
  activeProjectId: null,

  imageItems: [],
  imageQueueProcessing: false,

  activeBatchId: null,
  batchStatus: null,
  batches: [],

  jobs: [],

  usageStats: null,

  paidConfirmDialog: null,
};

// ── Reducer ──

type Action =
  | { type: "SET_FIELD"; field: keyof StudioState; value: unknown }
  | { type: "BRIDGE_READY"; health: BridgeHealth }
  | { type: "BRIDGE_OFFLINE" }
  | { type: "DRAFT_START" }
  | { type: "DRAFT_OK"; result: DraftResult }
  | { type: "DRAFT_FAIL"; error: string }
  | { type: "RENDER_START" }
  | { type: "RENDER_OK"; result: RenderSmokeResult }
  | { type: "RENDER_FAIL"; error: string }
  | { type: "SET_PROJECTS"; projects: StudioProjectRecord[] }
  | { type: "DELETE_PROJECT"; id: string }
  | { type: "IMAGE_QUEUE_UPDATE"; items: QueueItem[]; processing: boolean }
  | { type: "BATCH_UPDATE"; status: BatchStatus }
  | { type: "BATCHES_LOADED"; batches: BatchStatus[] }
  | { type: "JOBS_LOADED"; jobs: JobStatus[] }
  | { type: "EDIT_SCENE"; index: number; field: keyof Scene; value: unknown }
  | { type: "DELETE_SCENE"; index: number }
  | { type: "ADD_SCENE"; afterIndex: number }
  | { type: "REORDER_SCENE"; fromIndex: number; toIndex: number }
  | { type: "USAGE_STATS_LOADED"; stats: UsageStats }
  | { type: "SHOW_PAID_CONFIRM"; dialog: NonNullable<StudioState["paidConfirmDialog"]> }
  | { type: "CLOSE_PAID_CONFIRM" };

function reducer(state: StudioState, action: Action): StudioState {
  switch (action.type) {
    case "SET_FIELD":
      return { ...state, [action.field]: action.value };
    case "BRIDGE_READY":
      return {
        ...state,
        bridgeStatus: "connected",
        bridgeHealth: action.health,
        availableProviders: action.health.tts_providers ?? ["edge"],
        availableTemplates: (action.health.template_types?.length ? action.health.template_types : state.availableTemplates),
      };
    case "BRIDGE_OFFLINE":
      return { ...state, bridgeStatus: "offline", bridgeHealth: null };
    case "DRAFT_START":
      return {
        ...state,
        creating: true,
        error: null,
        draftResult: null,
        renderResult: null,
        freeAssetPacket: null,
        selectedBgmAsset: null,
        selectedSceneIndex: null,
      };
    case "DRAFT_OK":
      return {
        ...state,
        creating: false,
        freeAssetPacket: null,
        draftResult: {
          ...action.result,
          scenes: action.result.scenes?.map((scene, index) => ({
            ...scene,
            image_source: scene.image_source || "pexels-video",
            caption_preset: scene.caption_preset || (index === 0 ? "top-hook" : "lower-info"),
            grok_prompt: scene.grok_prompt || defaultGrokPrompt(scene),
            source_rationale: scene.source_rationale || "",
            continuity_note: scene.continuity_note || "",
            hook_note: scene.hook_note || (index === 0 ? "First 2 seconds: open with the strongest visual payoff." : ""),
            originality_evidence: scene.originality_evidence || "",
            quality_review_note: scene.quality_review_note || "",
            visual_quality_verdict: scene.visual_quality_verdict || "",
            thumbnail_review_note: scene.thumbnail_review_note || "",
            audio_mix_review_note: scene.audio_mix_review_note || "",
            platform_comparison_note: scene.platform_comparison_note || "",
            layout_variant_key: scene.layout_variant_key || "",
            layout_variant_label: scene.layout_variant_label || "",
            layout_variant_note: scene.layout_variant_note || "",
          })),
        },
      };
    case "DRAFT_FAIL":
      return { ...state, creating: false, error: action.error };
    case "RENDER_START":
      return { ...state, rendering: true, error: null, renderResult: null };
    case "RENDER_OK":
      return { ...state, rendering: false, renderResult: action.result };
    case "RENDER_FAIL":
      return { ...state, rendering: false, error: action.error };
    case "SET_PROJECTS":
      return { ...state, projects: action.projects };
    case "DELETE_PROJECT":
      return { ...state, projects: state.projects.filter((p) => p.id !== action.id) };
    case "IMAGE_QUEUE_UPDATE":
      return { ...state, imageItems: action.items, imageQueueProcessing: action.processing };
    case "BATCH_UPDATE":
      return { ...state, batchStatus: action.status };
    case "BATCHES_LOADED":
      return { ...state, batches: action.batches };
    case "JOBS_LOADED":
      return { ...state, jobs: action.jobs };
    case "EDIT_SCENE": {
      if (!state.draftResult?.scenes) return state;
      const scenes = [...state.draftResult.scenes];
      scenes[action.index] = { ...scenes[action.index], [action.field]: action.value };
      return { ...state, draftResult: { ...state.draftResult, scenes } };
    }
    case "DELETE_SCENE": {
      if (!state.draftResult?.scenes || state.draftResult.scenes.length <= 1) return state;
      const scenes = state.draftResult.scenes
        .filter((_, i) => i !== action.index)
        .map((s, i) => ({ ...s, scene_num: i + 1 }));
      const sel = state.selectedSceneIndex;
      let newSel: number | null = sel;
      if (sel !== null) {
        if (sel === action.index) newSel = null;
        else if (sel > action.index) newSel = sel - 1;
        if (newSel !== null && newSel >= scenes.length) newSel = scenes.length - 1;
      }
      return { ...state, draftResult: { ...state.draftResult, scenes }, selectedSceneIndex: newSel };
    }
    case "ADD_SCENE": {
      if (!state.draftResult?.scenes) return state;
      const raw = [...state.draftResult.scenes];
      const newScene: Scene = {
        scene_num: 0, narration: "", display_text: "", image_prompt: "",
        emotion: "neutral", duration: 4, has_image: false, rank: null,
        _tts_url: null, is_commentary: false, transition: "Dissolve",
        image_source: "pexels-video", caption_preset: "lower-info",
        source_rationale: "", continuity_note: "", hook_note: "",
        originality_evidence: "", quality_review_note: "",
        visual_quality_verdict: "",
        thumbnail_review_note: "", audio_mix_review_note: "", platform_comparison_note: "",
        layout_variant_key: "", layout_variant_label: "", layout_variant_note: "",
      };
      raw.splice(action.afterIndex + 1, 0, newScene);
      const scenes = raw.map((s, i) => ({ ...s, scene_num: i + 1 }));
      return { ...state, draftResult: { ...state.draftResult, scenes }, selectedSceneIndex: action.afterIndex + 1 };
    }
    case "REORDER_SCENE": {
      if (!state.draftResult?.scenes) return state;
      if (action.fromIndex === action.toIndex) return state;
      const raw = [...state.draftResult.scenes];
      const [moved] = raw.splice(action.fromIndex, 1);
      raw.splice(action.toIndex, 0, moved);
      const scenes = raw.map((s, i) => ({ ...s, scene_num: i + 1 }));
      return { ...state, draftResult: { ...state.draftResult, scenes }, selectedSceneIndex: action.toIndex };
    }
    case "USAGE_STATS_LOADED":
      return { ...state, usageStats: action.stats };
    case "SHOW_PAID_CONFIRM":
      return { ...state, paidConfirmDialog: action.dialog };
    case "CLOSE_PAID_CONFIRM":
      return { ...state, paidConfirmDialog: null };
    default:
      return state;
  }
}

// ── Actions interface ──

export interface StudioActions {
  setPrompt(v: string): void;
  setLang(v: "ko" | "en"): void;
  setTemplateType(v: TemplateType): void;
  setTone(v: TonePreset): void;
  setTtsProvider(v: string): void;
  setVoiceGender(v: "female" | "male"): void;
  setSubtitleStyle(v: string): void;
  setBgmEnabled(v: boolean): void;
  setSelectedBgmAsset(asset: BgmAssetPayload | null): void;
  setTargetDuration(v: "30s" | "1min" | "custom"): void;
  setCustomInstruction(v: string): void;
  setActiveTab(tab: StudioTab): void;
  selectScene(index: number | null): void;
  toggleDebug(): void;
  handleCreate(): Promise<void>;
  setDraftResult(result: DraftResult): void;
  recheckBridge(): Promise<void>;
  enqueueImages(scenes: Scene[]): void;
  retryImage(id: string): void;
  clearImages(): void;
  editScene(index: number, field: keyof Scene, value: unknown): void;
  deleteScene(index: number): void;
  addScene(afterIndex: number): void;
  reorderScene(fromIndex: number, toIndex: number): void;
  clearDraft(): void;
  deleteBatch(batchId: string): Promise<void>;
  deleteJob(jobId: string): Promise<void>;
  uploadSceneImage(index: number, file: File): void;
  uploadSceneVisual(index: number, file: File, source?: VisualSource): void;
  searchPexelsVideos(index: number): Promise<void>;
  selectPexelsVideo(index: number, candidate: PexelsVideoCandidate): void;
  createFreeAssetSourcingPacket(): Promise<FreeAssetSourcingPacket | null>;
  generateLocalSceneVideo(index: number): Promise<LocalVideoGenerateResult | null>;
  importLocalVideoFolder(sourceDir: string, providerHint?: LocalVideoProvider): Promise<LocalVideoFolderImportResult | null>;
  createGrokHandoff(): Promise<GrokHandoffResult | null>;
  openGrokHandoff(target?: GrokOpenTarget, browserPreference?: "default" | "chrome" | "edge", sceneId?: string): Promise<void>;
  loadGrokAutomationPlan(): Promise<GrokAutomationPlan | null>;
  uploadGrokSceneMp4(index: number, file: File): Promise<GrokImportDownloadsResult | null>;
  uploadGrokSceneMp4Batch(index: number, files: File[], mode?: GrokBatchUploadMode): Promise<GrokImportDownloadsResult | null>;
  importGrokDownloads(downloadDir: string): Promise<GrokImportDownloadsResult | null>;
  watchGrokDownloads(downloadDir: string): Promise<GrokWatchDownloadsResult | null>;
  startGrokManualDownloadWatch(downloadDir: string, sceneId?: string): Promise<GrokManualDownloadWatchResult | null>;
  startGrokManualDownloadWatchAll(downloadDir: string): Promise<GrokManualDownloadWatchResult | null>;
  runGrokOperatorLoop(downloadDir: string): Promise<GrokOperatorRunResult | null>;
  runGrokBrowserAutomation(index: number, downloadDir?: string, opts?: GrokBrowserAutomationOptions): Promise<GrokBrowserAutomationResult | null>;
  startGrokBackgroundAutomation(index: number, downloadDir?: string, opts?: GrokBrowserAutomationOptions): Promise<GrokBrowserAutomationResult | null>;
  startNextGrokBackgroundAutomation(downloadDir?: string, opts?: GrokBrowserAutomationOptions): Promise<GrokBrowserAutomationResult | null>;
  resumeGrokBrowserAutomation(index: number, opts?: GrokBrowserAutomationOptions): Promise<GrokBrowserAutomationResult | null>;
  focusGrokOperatorBrowser(): Promise<GrokOperatorFocusResult | null>;
  cleanupGrokOperatorTabs(): Promise<GrokOperatorTabCleanupResult | null>;
  syncGrokHandoff(options?: { silent?: boolean; fromBackgroundPoll?: boolean }): Promise<void>;
  saveGrokReviewDecision(index: number, accepted: boolean, operatorNote?: string, checks?: {
    firstTwoSecondHook?: boolean;
    artifactFree?: boolean;
    continuityOk?: boolean;
    captionSafe?: boolean;
  }, selectedFileName?: string, candidateSummary?: string, qualityFields?: {
    captionLayoutReviewNote?: string;
    visualQualityVerdict?: string;
    shotLockMatch?: boolean;
    sceneAssemblyOk?: boolean;
    shotLockEvidenceNote?: string;
    sceneAssemblyRoleNote?: string;
    continuityNote?: string;
    hookNote?: string;
    layoutVariantKey?: string;
    layoutVariantLabel?: string;
    layoutVariantNote?: string;
    thumbnailReviewNote?: string;
    audioMixReviewNote?: string;
    platformComparisonNote?: string;
    sourceProvenanceConfirmed?: boolean;
    sourceProvenanceNote?: string;
  }): Promise<boolean>;
  renderGrokHandoff(): Promise<RenderSmokeResult | null>;
  renderGrokHandoffPreview(): Promise<RenderSmokeResult | null>;
  setSceneCaptionPreset(index: number, preset: CaptionPreset): void;
  renderCurrentDraft(): Promise<RenderSmokeResult | null>;
  regenerateSceneImage(index: number): Promise<void>;
  regenerateSceneTts(index: number): Promise<void>;
  deleteProject(id: string): void;
  startBatch(variants: number): Promise<string | null>;
  refreshBatches(): Promise<void>;
  submitJob(): Promise<string | null>;
  refreshJobs(): Promise<void>;
  refreshUsageStats(): Promise<void>;
  confirmPaidProceed(): Promise<void>;
  confirmPaidUseFree(): Promise<void>;
  closePaidConfirm(): void;
}

// ── Contexts ──

const StateCtx = createContext<StudioState>(initialState);
const ActionsCtx = createContext<StudioActions>(null!);

export function useStudioState() { return useContext(StateCtx); }
export function useStudioActions() { return useContext(ActionsCtx); }

type GrokHandoffStatePatch = Partial<GrokHandoffResult> & {
  automationStatus?: GrokAutomationStatus;
  renderPayload?: GrokHandoffRenderPayload | null;
  reviewDecision?: GrokReviewDecision;
} & Partial<GrokBrowserAutomationResult>;

function sceneIdFor(scene: Scene, index: number): string {
  const n = Number.isFinite(scene.scene_num) && scene.scene_num > 0 ? scene.scene_num : index + 1;
  return `scene-${String(n).padStart(2, "0")}`;
}

function defaultGrokPrompt(scene: Scene): string {
  const visualPrompt = scene.image_prompt || scene.display_text || scene.narration || "cinematic short-form scene";
  return [
    visualPrompt,
    "Vertical 9:16 MP4, 4-6 seconds, natural camera movement, consistent subject and setting.",
    "No subtitles, no logos, no watermark, no text baked into the video.",
  ].join(" ");
}

function summarizeGrokAutomation(result: Partial<GrokBrowserAutomationResult>): GrokAutomationStatus | undefined {
  const hasAutomationFields = Boolean(
    result.browserAutomationMode
    || typeof result.preflightOnly === "boolean"
    || typeof result.promptInjected === "boolean"
    || typeof result.generateRequested === "boolean"
    || typeof result.downloadResultRequested === "boolean"
    || typeof result.watchDownloadsRequested === "boolean"
    || typeof result.requiresOperatorAction === "boolean"
  );
  if (!hasAutomationFields) return undefined;

  const needsOperator = Boolean(result.requiresOperatorAction || result.authRequired || result.cookieChoiceRequired);
  const operatorReadyTimedOut = Boolean(result.operatorReadyTimedOut);
  const ready = typeof result.readyScenes === "number" && typeof result.totalScenes === "number"
    ? `${result.readyScenes}/${result.totalScenes}`
    : "";
  const blockers = [
    result.authRequired ? "Grok login" : null,
    result.cookieChoiceRequired ? "cookie choice" : null,
    result.operatorAuthStageLabel ? `stage=${result.operatorAuthStageLabel}` : null,
    result.browserBlocker ? `blocker=${result.browserBlocker}` : null,
  ].filter(Boolean);
  const status: GrokAutomationStatus["status"] = result.allReady
    ? "imported"
    : needsOperator
      ? "needs-operator"
      : result.promptInjected
        ? "injected"
        : result.preflightOnly
          ? "preflight"
          : "pending";
  const downloadClicked = Boolean(result.downloadClick?.["clicked"]);
  const downloadClickReason = typeof result.downloadClick?.["reason"] === "string"
    ? String(result.downloadClick["reason"])
    : typeof result.downloadClick?.["error"] === "string"
      ? String(result.downloadClick["error"])
      : undefined;
  const detail = [
    result.preflightOnly ? "preflight checked" : null,
    result.operatorReadyWait ? `operator ready wait${operatorReadyTimedOut ? " timed out" : ""}` : null,
    result.promptInjected ? "prompt injected" : null,
    result.generateRequested ? `generation requested${result.generateAction ? `:${result.generateAction}` : ""}` : null,
    result.downloadResultRequested ? (downloadClicked ? "download clicked" : `download fallback${downloadClickReason ? `: ${downloadClickReason}` : ""}`) : null,
    result.watchDownloadsRequested ? `watch/import ${ready || "pending"}` : null,
    result.operatorNextAction || result.manualDownloadInstruction || null,
    blockers.length ? `operator action: ${blockers.join(", ")}` : null,
  ].filter(Boolean).join(" / ");

  return {
    sceneId: result.filledSceneId || result.sceneId,
    expectedFileName: result.expectedFileName,
    status,
    detail: detail || status,
    mode: result.browserAutomationMode,
    browserBlocker: result.browserBlocker,
    operatorAuthStage: result.operatorAuthStage,
    operatorAuthStageLabel: result.operatorAuthStageLabel,
    authRequired: result.authRequired,
    cookieChoiceRequired: result.cookieChoiceRequired,
    promptInjected: result.promptInjected,
    generateRequested: result.generateRequested,
    downloadResultRequested: result.downloadResultRequested,
    watchDownloadsRequested: result.watchDownloadsRequested,
    readyScenes: result.readyScenes,
    totalScenes: result.totalScenes,
    remoteDebuggingPort: result.remoteDebuggingPort,
    targetUrl: result.targetUrl,
    targetTitle: result.targetTitle,
    launched: result.launched,
    useDefaultChromeProfile: result.useDefaultChromeProfile,
    browserProfileDirectory: result.browserProfileDirectory,
    downloadDir: result.downloadDir,
    manualDownloadInstruction: result.manualDownloadInstruction,
    operatorNextAction: result.operatorNextAction,
    downloadClickReason,
    operatorReadyTimedOut: result.operatorReadyTimedOut,
    operatorReadyWait: result.operatorReadyWait,
  };
}

const LOCAL_VIDEO_SOURCES = new Set<VisualSource>(["wan", "ltx-video", "hunyuan-video"]);

function isLocalVideoSource(source?: string): source is LocalVideoProvider {
  return source === "wan" || source === "ltx-video" || source === "hunyuan-video";
}

function parseCommandTemplateJson(value?: string): string[] | null {
  const raw = (value || "").trim();
  if (!raw) return null;
  try {
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) && parsed.every((item) => typeof item === "string" && item.trim())
      ? parsed
      : null;
  } catch {
    return null;
  }
}

function defaultSourceRationale(scene: Scene, index: number): string {
  const source = scene.image_source || "pexels-video";
  if (scene.source_rationale?.trim()) return scene.source_rationale.trim();
  if (source === "grok") return `Manual Grok handoff clip for scene ${index + 1}.`;
  if (source === "upload") return `Uploaded operator-selected visual: ${scene._upload_name || "local file"}.`;
  if (source === "pexels-video" && scene._selected_pexels_video) {
    const selected = scene._selected_pexels_video;
    const poolCount = selected.candidateCount ? ` from ${selected.candidateCount} candidates` : "";
    const creator = selected.author ? ` by ${selected.author}` : "";
    const page = selected.sourceUrl ? `; source ${selected.sourceUrl}` : "";
    return `Manually selected Pexels video ${selected.id}${poolCount}${creator} for scene intent${page}.`;
  }
  if (isLocalVideoSource(source)) {
    return scene._upload_name
      ? `Manual ${source} local-model MP4 handoff uploaded: ${scene._upload_name}.`
      : `Local ${source} video generation selected for motion-first scene.`;
  }
  return "";
}

function isGenericGrokAcceptanceEvidence(value?: string): boolean {
  const normalized = String(value || "").trim().toLowerCase();
  if (!normalized) return true;
  return [
    "manual grok handoff clip for scene",
    "operator-approved grok web handoff mp4 synced",
    "uploaded operator-selected visual",
    "dashboard accepted grok handoff clip",
    "dashboard rejected grok handoff clip",
  ].some((prefix) => normalized.startsWith(prefix));
}

function sceneIdFromGrokUploadName(fileName: string): string {
  const match = String(fileName || "").match(/scene[-_\s]?(\d{1,3})/i);
  return match ? `scene-${String(Number(match[1])).padStart(2, "0")}` : "";
}

function readFileBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(new Error("업로드 파일을 읽지 못했습니다"));
    reader.onload = () => {
      const value = String(reader.result ?? "");
      resolve(value.includes(",") ? value.split(",", 2)[1] : value);
    };
    reader.readAsDataURL(file);
  });
}

function baseNameFromPath(path: string | null | undefined): string {
  return String(path || "").split(/[\\/]/).filter(Boolean).pop() || "";
}

function audioMimeFromPath(path: string | null | undefined): string {
  const lower = String(path || "").toLowerCase();
  if (lower.endsWith(".wav")) return "audio/wav";
  if (lower.endsWith(".ogg")) return "audio/ogg";
  if (lower.endsWith(".m4a")) return "audio/mp4";
  if (lower.endsWith(".flac")) return "audio/flac";
  return "audio/mpeg";
}

async function buildSceneAssets(scenes: Scene[]): Promise<SceneAssetPayload[]> {
  const assets: SceneAssetPayload[] = [];
  for (let index = 0; index < scenes.length; index += 1) {
    const scene = scenes[index];
    const sceneId = sceneIdFor(scene, index);
    const provenance = {
      ...(scene.local_generation_request_path ? { sourceGenerator: scene.local_video_provider || scene.image_source } : {}),
      ...(scene.local_generation_request_path ? { sourceGeneratorRequestPath: scene.local_generation_request_path } : {}),
      ...(scene.local_generation_prompt_path ? { sourceGeneratorPromptPath: scene.local_generation_prompt_path } : {}),
      ...(scene.local_generation_log_path ? { sourceGeneratorLogPath: scene.local_generation_log_path } : {}),
      ...(scene.local_generation_command_preview ? { sourceGeneratorCommand: scene.local_generation_command_preview } : {}),
    };
    if (scene._upload_file) {
      assets.push({
        sceneId,
        role: "visual",
        fileName: scene._upload_file.name,
        mimeType: scene._upload_file.type || scene._upload_mime || undefined,
        base64: await readFileBase64(scene._upload_file),
        ...provenance,
      });
    } else if (scene._server_asset_path) {
      assets.push({
        sceneId,
        role: "visual",
        fileName: scene._upload_name || `${sceneId}.mp4`,
        mimeType: scene._server_asset_mime || "video/mp4",
        sourcePath: scene._server_asset_path,
        ...provenance,
      });
    }
    if (scene._sfx_asset_path) {
      const fileName = scene._sfx_asset_name || baseNameFromPath(scene._sfx_asset_path) || `${sceneId}-sfx.wav`;
      assets.push({
        sceneId,
        role: "sfx",
        fileName,
        mimeType: scene._sfx_asset_mime || audioMimeFromPath(scene._sfx_asset_path),
        sourcePath: scene._sfx_asset_path,
        provider: "local-sfx",
        sourceProvider: scene._sfx_asset_provider || undefined,
        sourceUrl: scene._sfx_asset_source_url || undefined,
        sourceLicense: scene._sfx_asset_source_license || undefined,
        licenseUrl: scene._sfx_asset_license_url || undefined,
        attribution: scene._sfx_asset_attribution || undefined,
        sourceAttribution: scene._sfx_asset_attribution || undefined,
        sourceLabel: scene._sfx_asset_title || fileName,
      });
    }
  }
  return assets;
}

function buildDraftScenes(scenes: Scene[]): DraftScenePayload[] {
  return scenes.map((scene, index) => ({
    sceneId: sceneIdFor(scene, index),
    scene_num: index + 1,
    title: scene.display_text || scene.image_prompt || `Scene ${index + 1}`,
    narration: scene.narration || scene.display_text || "",
    display_text: scene.display_text || scene.narration || "",
    image_prompt: scene.image_prompt || scene.display_text || scene.narration || "",
    image_source: scene.image_source || "pexels-video",
    emotion: scene.emotion || "neutral",
    duration: Number(scene.duration || 4),
    upload_kind: scene._upload_kind || null,
    caption_preset: (scene.caption_preset || "lower-info") as CaptionPreset,
    grok_prompt: scene.grok_prompt || defaultGrokPrompt(scene),
    source_rationale: defaultSourceRationale(scene, index),
    continuity_note: scene.continuity_note || "",
    hook_note: scene.hook_note || (index === 0 ? "First 2 seconds: open with the strongest visual payoff." : ""),
    originality_evidence: scene.originality_evidence || "",
    quality_review_note: scene.quality_review_note || "",
    visual_quality_verdict: (scene.visual_quality_verdict || "") as VisualQualityVerdict | "",
    thumbnail_review_note: scene.thumbnail_review_note || "",
    audio_mix_review_note: scene.audio_mix_review_note || "",
    platform_comparison_note: scene.platform_comparison_note || "",
    layout_variant_key: scene.layout_variant_key || "",
    layout_variant_label: scene.layout_variant_label || "",
    layout_variant_note: scene.layout_variant_note || "",
    selected_pexels_video: scene._selected_pexels_video || null,
    local_video_provider: scene.local_video_provider,
  }));
}

function buildProviderOverrides(scenes: Scene[]): Record<string, string> {
  const overrides: Record<string, string> = {};
  scenes.forEach((scene, index) => {
    const sceneId = sceneIdFor(scene, index);
    const source = scene.image_source;
    if (source === "pexels-video" && scene._selected_pexels_video) overrides[sceneId] = "pexels-video";
    if (source === "wan") overrides[sceneId] = "wan";
    if (source === "ltx-video") overrides[sceneId] = "ltx-video";
    if (source === "hunyuan-video") overrides[sceneId] = "hunyuan-video";
  });
  return overrides;
}

function buildSelectedPexelsVideos(scenes: Scene[]): Record<string, PexelsVideoCandidate> {
  const selected: Record<string, PexelsVideoCandidate> = {};
  scenes.forEach((scene, index) => {
    if (scene._selected_pexels_video) selected[sceneIdFor(scene, index)] = scene._selected_pexels_video;
  });
  return selected;
}

// ── Provider ──

export function StudioProvider({ children }: { children: React.ReactNode }) {
  const [state, dispatch] = useReducer(reducer, initialState, (init) => ({
    ...init,
    projects: loadStoredProjects(),
  }));

  const stateRef = useRef(state);
  stateRef.current = state;

  // Image queue ref
  const queueRef = useRef<ImageGenerationQueue | null>(null);
  if (!queueRef.current) {
    queueRef.current = new ImageGenerationQueue({
      onItemUpdate(items) {
        dispatch({ type: "IMAGE_QUEUE_UPDATE", items: [...items], processing: true });
      },
      onComplete() {
        dispatch({ type: "IMAGE_QUEUE_UPDATE", items: queueRef.current?.getItems() ?? [], processing: false });
      },
      async bridgeGenerateImage(input) {
        const source = ["pexels", "imagen", "tenor"].includes(input.model) ? input.model : "imagen";
        const res = await apiGenerateImage(input.prompt, source, input.emotion);
        if (!res.ok || !res.image_url) {
          throw new Error(res.error || "브리지에서 이미지 생성 실패");
        }
        // Fetch the image and convert to base64 (chunked to avoid OOM on large images)
        const resp = await fetch(res.image_url, { signal: AbortSignal.timeout(30_000) });
        if (!resp.ok) throw new Error(`이미지 다운로드 실패 (HTTP ${resp.status})`);
        const blob = await resp.blob();
        const buffer = await blob.arrayBuffer();
        const bytes = new Uint8Array(buffer);
        const CHUNK = 8192;
        const parts: string[] = [];
        for (let i = 0; i < bytes.length; i += CHUNK) {
          parts.push(String.fromCharCode(...bytes.subarray(i, i + CHUNK)));
        }
        return { imageBase64: btoa(parts.join("")), mimeType: blob.type || "image/png" };
      },
    });
  }

  // Persist projects
  const prevProjectsRef = useRef(state.projects);
  useEffect(() => {
    if (state.projects !== prevProjectsRef.current) {
      prevProjectsRef.current = state.projects;
      saveStoredProjects(state.projects);
    }
  }, [state.projects]);

  // Bridge health on mount
  useEffect(() => {
    checkHealth()
      .then((h) => {
        if (h) dispatch({ type: "BRIDGE_READY", health: h });
        else dispatch({ type: "BRIDGE_OFFLINE" });
      })
      .catch(() => dispatch({ type: "BRIDGE_OFFLINE" }));
  }, []);

  // Usage stats polling — every 30s when bridge is connected
  useEffect(() => {
    if (state.bridgeStatus !== "connected") return;
    // Fetch immediately on connect
    fetchUsageStats().then((s) => {
      if (s.ok) dispatch({ type: "USAGE_STATS_LOADED", stats: s });
    });
    const id = setInterval(async () => {
      if (!document.hidden) {
        const s = await fetchUsageStats();
        if (s.ok) dispatch({ type: "USAGE_STATS_LOADED", stats: s });
      }
    }, 30_000);
    return () => clearInterval(id);
  }, [state.bridgeStatus]);

  // Batch polling — use stateRef to avoid stale closure
  useEffect(() => {
    if (!state.activeBatchId) return;
    const batchId = state.activeBatchId;
    const id = setInterval(async () => {
      if (document.hidden) return;
      const s = await getBatchStatus(batchId);
      if (s.ok) {
        dispatch({ type: "BATCH_UPDATE", status: s });
        // Use progress/total (backend) with completed/failed as fallback.
        // Only terminate when the server reported a real variant/total count —
        // the synthetic fallback must not stop polling before the count arrives.
        const done = (s.completed ?? s.progress ?? 0) + (s.failed ?? 0);
        const total = s.variants ?? s.total ?? 0;
        if (total > 0 && done >= total) {
          dispatch({ type: "SET_FIELD", field: "activeBatchId", value: null });
        }
      }
    }, 3000);
    return () => clearInterval(id);
  }, [state.activeBatchId]);

  // Actions
  const actions = useMemo<StudioActions>(() => {
    async function _doGenerateImage(index: number, source: string) {
      const scene = stateRef.current.draftResult?.scenes?.[index];
      if (!scene?.image_prompt) return;
      try {
        const res = await apiGenerateImage(scene.image_prompt, source, scene.emotion);
        if (res.ok && res.image_url) {
          const oldPreview = scene._upload_preview;
          if (oldPreview) {
            URL.revokeObjectURL(oldPreview);
            dispatch({ type: "EDIT_SCENE", index, field: "_upload_preview", value: null });
          }
          dispatch({ type: "EDIT_SCENE", index, field: "_image_url", value: res.image_url });
          dispatch({ type: "EDIT_SCENE", index, field: "has_image", value: true });
          if (res.source) dispatch({ type: "EDIT_SCENE", index, field: "image_source", value: res.source });
        } else {
          dispatch({ type: "SET_FIELD", field: "error", value: res.error || "이미지 생성 실패" });
        }
      } catch (e: unknown) {
        dispatch({ type: "SET_FIELD", field: "error", value: e instanceof Error ? e.message : "이미지 생성 연결 실패" });
      }
    }

    function _applyGrokAssets(status: Pick<GrokHandoffStatus, "assets">): number {
      const scenes = stateRef.current.draftResult?.scenes ?? [];
      let synced = 0;
      for (const asset of status.assets ?? []) {
        if (asset.status !== "ready" || !asset.sceneId || !asset.sourcePath) continue;
        const index = scenes.findIndex((scene, sceneIndex) => sceneIdFor(scene, sceneIndex) === asset.sceneId);
        if (index < 0) continue;
        const current = scenes[index];
        const oldPreview = current._upload_preview;
        if (oldPreview?.startsWith("blob:")) URL.revokeObjectURL(oldPreview);
        dispatch({ type: "EDIT_SCENE", index, field: "_upload_preview", value: asset.previewUrl || null });
        dispatch({ type: "EDIT_SCENE", index, field: "_upload_file", value: null });
        dispatch({ type: "EDIT_SCENE", index, field: "_upload_kind", value: "video" });
        dispatch({ type: "EDIT_SCENE", index, field: "_upload_name", value: asset.fileName || `${asset.sceneId}.grok.mp4` });
        dispatch({ type: "EDIT_SCENE", index, field: "_upload_mime", value: asset.mimeType || "video/mp4" });
        dispatch({ type: "EDIT_SCENE", index, field: "_server_asset_path", value: asset.sourcePath });
        dispatch({ type: "EDIT_SCENE", index, field: "_server_asset_preview_url", value: asset.previewUrl || null });
        dispatch({ type: "EDIT_SCENE", index, field: "_server_asset_mime", value: asset.mimeType || "video/mp4" });
        dispatch({ type: "EDIT_SCENE", index, field: "_video_url", value: asset.previewUrl || null });
        dispatch({ type: "EDIT_SCENE", index, field: "_selected_pexels_video", value: null });
        dispatch({ type: "EDIT_SCENE", index, field: "image_source", value: "grok" });
        dispatch({ type: "EDIT_SCENE", index, field: "has_image", value: true });
        dispatch({
          type: "EDIT_SCENE",
          index,
          field: "source_rationale",
          value: current.source_rationale || `Operator-approved Grok web handoff MP4 synced: ${asset.fileName}.`,
        });
        dispatch({
          type: "EDIT_SCENE",
          index,
          field: "originality_evidence",
          value: current.originality_evidence || `Grok web/app Imagine output synced from local handoff folder: ${asset.sourcePath}.`,
        });
        synced += 1;
      }
      return synced;
    }

    function _mergeGrokHandoffState(patch: GrokHandoffStatePatch): void {
      const current = stateRef.current.grokHandoff;
      if (!current && !patch.projectId) return;
      const renderPayload = patch.renderPayload;
      const reviewDecision = patch.reviewDecision;
      const automationStatus = patch.automationStatus ?? summarizeGrokAutomation(patch);
      const reviewDecisions = patch.reviewDecisions ?? renderPayload?.reviewDecisions ?? (
        reviewDecision?.sceneId
          ? { ...(current?.reviewDecisions ?? {}), [reviewDecision.sceneId]: reviewDecision }
          : undefined
      );
      const readyScenes = typeof patch.readyScenes === "number" ? patch.readyScenes : renderPayload?.readyScenes;
      const totalScenes = typeof patch.totalScenes === "number" ? patch.totalScenes : renderPayload?.totalScenes;
      const allReady = typeof patch.allReady === "boolean" ? patch.allReady : renderPayload?.allReady;
      dispatch({
        type: "SET_FIELD",
        field: "grokHandoff",
        value: {
          ...(current ?? { ok: true }),
          ...(patch.projectId ? { projectId: patch.projectId } : {}),
          ...(patch.incomingDir ? { incomingDir: patch.incomingDir } : {}),
          ...(patch.grokUrl ? { grokUrl: patch.grokUrl } : {}),
          ...(patch.worksheetUrl ? { worksheetUrl: patch.worksheetUrl } : {}),
          ...(patch.automationPlanUrl ? { automationPlanUrl: patch.automationPlanUrl } : {}),
          ...(patch.reviewPacketUrl ? { reviewPacketUrl: patch.reviewPacketUrl } : {}),
          ...(patch.reviewDecisionUrl ? { reviewDecisionUrl: patch.reviewDecisionUrl } : {}),
          ...(patch.defaultDownloadDir ? { defaultDownloadDir: patch.defaultDownloadDir } : {}),
          ...(typeof patch.defaultDownloadDirExists === "boolean" ? { defaultDownloadDirExists: patch.defaultDownloadDirExists } : {}),
          ...(patch.assets ? { assets: patch.assets } : {}),
          ...(patch.mainSourceGate ? { mainSourceGate: patch.mainSourceGate } : {}),
          ...(typeof readyScenes === "number" ? { readyScenes } : {}),
          ...(typeof totalScenes === "number" ? { totalScenes } : {}),
          ...(typeof allReady === "boolean" ? { allReady } : {}),
          ...(reviewDecisions ? { reviewDecisions } : {}),
          ...(patch.scenes ? { scenes: patch.scenes } : {}),
          ...(patch.shotBible ? { shotBible: patch.shotBible } : {}),
          ...(automationStatus ? { automationStatus } : {}),
          ...(patch.automationReplay ? { automationReplay: patch.automationReplay } : {}),
          ...(patch.automationJob ? { automationJob: patch.automationJob } : {}),
          ...(patch.chromeCompanionExtension ? { chromeCompanionExtension: patch.chromeCompanionExtension } : {}),
        } satisfies GrokHandoffResult,
      });
    }

    async function _renderGrokPayload(
      projectId: string,
      payload: GrokHandoffRenderPayload,
      opts: { finalizeChannelPacket?: boolean } = {},
    ): Promise<RenderSmokeResult | null> {
      const s = stateRef.current;
      dispatch({ type: "RENDER_START" });
      try {
        let result = await apiRenderSmoke({
          prompt: payload.prompt || s.prompt || "Grok handoff render",
          budgetMode: payload.budgetMode || "free",
          plannerMode: payload.plannerMode || "sample",
          projectId: payload.projectId || `${projectId}-render`,
          draftScenes: payload.draftScenes || [],
          sceneAssets: payload.sceneAssets || [],
          bgmAsset: s.bgmEnabled ? (payload.bgmAsset || s.selectedBgmAsset) : null,
          providerOverrides: payload.providerOverrides || {},
          selectedPexelsVideos: payload.selectedPexelsVideos || {},
          subtitleStyle: s.subtitleStyle,
          bgmEnabled: s.bgmEnabled,
        });
        if (result.ok) {
          if (opts.finalizeChannelPacket && result.renderResult?.outputPath) {
            const packet = await apiFinalizeRender({
              outputPath: result.renderResult.outputPath,
              qualityReportPath: result.renderResult.qualityReportPath,
              projectId: result.renderResult.qualityReport?.projectId || result.renderResult.projectId,
              requireChannelReady: true,
            });
            result = { ...result, finalizeResult: packet };
            if (!packet.ok) {
              dispatch({
                type: "SET_FIELD",
                field: "error",
                value: packet.error || "Grok channel final packet 저장 실패",
              });
            }
          }
          dispatch({ type: "RENDER_OK", result });
          return result;
        }
        dispatch({ type: "RENDER_FAIL", error: result.error || "Grok handoff 렌더 실패" });
        return null;
      } catch (e: unknown) {
        const message = e instanceof Error ? e.message : "Grok handoff 렌더 연결 실패";
        dispatch({ type: "RENDER_FAIL", error: message });
        return null;
      }
    }

    async function _ensureGrokHandoffPacket(): Promise<GrokHandoffResult | null> {
      const s = stateRef.current;
      const current = s.grokHandoff;
      if (current?.projectId) return current;

      const scenes = s.draftResult?.scenes ?? [];
      if (!s.draftResult?.ok || scenes.length === 0) {
        dispatch({ type: "SET_FIELD", field: "error", value: "Grok handoff에 보낼 씬이 없습니다" });
        return null;
      }

      const projectId = `grok-ui-${Date.now()}`;
      const result = await apiCreateGrokHandoff({
        projectId,
        prompt: s.prompt || s.draftResult.message || "Grok web handoff",
        draftScenes: buildDraftScenes(scenes),
        qualityGateRequired: true,
        grokMainSourceRequired: true,
        templateType: s.templateType,
        tone: s.tone,
        lang: s.lang,
        targetDuration: s.targetDuration,
        subtitleStyle: s.subtitleStyle,
      });
      if (!result.ok) {
        dispatch({ type: "SET_FIELD", field: "error", value: result.error || "Grok handoff 생성 실패" });
        return null;
      }

      _mergeGrokHandoffState(result);
      dispatch({ type: "SET_FIELD", field: "grokHandoff", value: result });
      return result;
    }

    return ({
    setPrompt(v) { dispatch({ type: "SET_FIELD", field: "prompt", value: v }); },
    setLang(v) { dispatch({ type: "SET_FIELD", field: "lang", value: v }); },
    setTemplateType(v) { dispatch({ type: "SET_FIELD", field: "templateType", value: v }); },
    setTone(v) { dispatch({ type: "SET_FIELD", field: "tone", value: v }); },
    setTtsProvider(v) { dispatch({ type: "SET_FIELD", field: "ttsProvider", value: v }); },
    setVoiceGender(v) { dispatch({ type: "SET_FIELD", field: "voiceGender", value: v }); },
    setSubtitleStyle(v) { dispatch({ type: "SET_FIELD", field: "subtitleStyle", value: v }); },
    setBgmEnabled(v) { dispatch({ type: "SET_FIELD", field: "bgmEnabled", value: v }); },
    setSelectedBgmAsset(asset) { dispatch({ type: "SET_FIELD", field: "selectedBgmAsset", value: asset }); },
    setTargetDuration(v) { dispatch({ type: "SET_FIELD", field: "targetDuration", value: v }); },
    setCustomInstruction(v) { dispatch({ type: "SET_FIELD", field: "customInstruction", value: v }); },
    setActiveTab(tab) { dispatch({ type: "SET_FIELD", field: "activeTab", value: tab }); },
    selectScene(index) { dispatch({ type: "SET_FIELD", field: "selectedSceneIndex", value: index }); },
    toggleDebug() {
      dispatch({ type: "SET_FIELD", field: "debugOpen", value: !stateRef.current.debugOpen });
    },

    async handleCreate() {
      const s = stateRef.current;
      if (!s.prompt.trim() || s.creating) return;
      dispatch({ type: "DRAFT_START" });
      try {
        const result = await apiCreateDraft(s.prompt, s.lang, s.ttsProvider, s.voiceGender, s.templateType, s.subtitleStyle, s.tone, s.targetDuration, s.customInstruction, s.bgmEnabled);
        if (result.ok) {
          dispatch({ type: "DRAFT_OK", result });
          // Refresh usage stats after a successful creation
          fetchUsageStats().then((stats) => {
            if (stats.ok) dispatch({ type: "USAGE_STATS_LOADED", stats });
          });
        } else {
          dispatch({ type: "DRAFT_FAIL", error: result.error || "초안 생성 실패" });
        }
      } catch (e: unknown) {
        dispatch({ type: "DRAFT_FAIL", error: e instanceof Error ? e.message : "브릿지 연결 실패 — 서버가 실행 중인지 확인하세요" });
      }
    },

    setDraftResult(result) {
      dispatch({ type: "DRAFT_OK", result });
    },

    async recheckBridge() {
      dispatch({ type: "SET_FIELD", field: "bridgeStatus", value: "checking" });
      const h = await checkHealth();
      if (h) dispatch({ type: "BRIDGE_READY", health: h });
      else dispatch({ type: "BRIDGE_OFFLINE" });
    },

    enqueueImages(scenes) {
      const q = queueRef.current!;
      for (const scene of scenes) {
        if (scene.image_prompt) {
          q.enqueue({
            id: `scene-${scene.scene_num}-${Date.now()}`,
            prompt: scene.image_prompt,
            originalPrompt: scene.image_prompt,
            width: 1080,
            height: 1920,
            engine: scene.image_source || "imagen",
            emotion: scene.emotion || "neutral",
            filename: `scene_${scene.scene_num}.webp`,
          });
        }
      }
      q.start();
    },

    retryImage(id) {
      queueRef.current?.retry(id);
    },

    clearImages() {
      queueRef.current?.stop();
      queueRef.current?.clear();
      dispatch({ type: "IMAGE_QUEUE_UPDATE", items: [], processing: false });
    },

    editScene(index, field, value) {
      dispatch({ type: "EDIT_SCENE", index, field, value });
    },
    deleteScene(index) {
      dispatch({ type: "DELETE_SCENE", index });
    },
    addScene(afterIndex) {
      dispatch({ type: "ADD_SCENE", afterIndex });
    },
    reorderScene(fromIndex, toIndex) {
      dispatch({ type: "REORDER_SCENE", fromIndex, toIndex });
    },
    uploadSceneImage(index, file) {
      const oldPreview = stateRef.current.draftResult?.scenes?.[index]?._upload_preview;
      if (oldPreview) URL.revokeObjectURL(oldPreview);
      const previewUrl = URL.createObjectURL(file);
      const uploadKind = file.type.startsWith("video/") ? "video" : "image";
      dispatch({ type: "EDIT_SCENE", index, field: "_upload_preview", value: previewUrl });
      dispatch({ type: "EDIT_SCENE", index, field: "_upload_file", value: file });
      dispatch({ type: "EDIT_SCENE", index, field: "_upload_kind", value: uploadKind });
      dispatch({ type: "EDIT_SCENE", index, field: "_upload_name", value: file.name });
      dispatch({ type: "EDIT_SCENE", index, field: "_upload_mime", value: file.type || null });
      dispatch({ type: "EDIT_SCENE", index, field: "_server_asset_path", value: null });
      dispatch({ type: "EDIT_SCENE", index, field: "_server_asset_preview_url", value: null });
      dispatch({ type: "EDIT_SCENE", index, field: "_server_asset_mime", value: null });
      dispatch({ type: "EDIT_SCENE", index, field: "_video_url", value: uploadKind === "video" ? previewUrl : null });
      dispatch({ type: "EDIT_SCENE", index, field: "_selected_pexels_video", value: null });
      dispatch({ type: "EDIT_SCENE", index, field: "image_source", value: "upload" });
      dispatch({ type: "EDIT_SCENE", index, field: "has_image", value: true });
      dispatch({ type: "EDIT_SCENE", index, field: "source_rationale", value: `Uploaded operator-selected visual: ${file.name}.` });
    },
    uploadSceneVisual(index, file, source = "upload") {
      const oldPreview = stateRef.current.draftResult?.scenes?.[index]?._upload_preview;
      if (oldPreview) URL.revokeObjectURL(oldPreview);
      const previewUrl = URL.createObjectURL(file);
      const uploadKind = file.type.startsWith("video/") ? "video" : "image";
      dispatch({ type: "EDIT_SCENE", index, field: "_upload_preview", value: previewUrl });
      dispatch({ type: "EDIT_SCENE", index, field: "_upload_file", value: file });
      dispatch({ type: "EDIT_SCENE", index, field: "_upload_kind", value: uploadKind });
      dispatch({ type: "EDIT_SCENE", index, field: "_upload_name", value: file.name });
      dispatch({ type: "EDIT_SCENE", index, field: "_upload_mime", value: file.type || null });
      dispatch({ type: "EDIT_SCENE", index, field: "_server_asset_path", value: null });
      dispatch({ type: "EDIT_SCENE", index, field: "_server_asset_preview_url", value: null });
      dispatch({ type: "EDIT_SCENE", index, field: "_server_asset_mime", value: null });
      dispatch({ type: "EDIT_SCENE", index, field: "_video_url", value: uploadKind === "video" ? previewUrl : null });
      dispatch({ type: "EDIT_SCENE", index, field: "_selected_pexels_video", value: null });
      dispatch({ type: "EDIT_SCENE", index, field: "image_source", value: source });
      if (LOCAL_VIDEO_SOURCES.has(source)) {
        dispatch({ type: "EDIT_SCENE", index, field: "local_video_provider", value: source });
      }
      dispatch({ type: "EDIT_SCENE", index, field: "has_image", value: true });
      dispatch({
        type: "EDIT_SCENE",
        index,
        field: "source_rationale",
        value: source === "grok"
          ? `Manual Grok handoff MP4 uploaded: ${file.name}.`
          : LOCAL_VIDEO_SOURCES.has(source)
            ? `Manual ${source} local-model MP4 handoff uploaded: ${file.name}.`
          : `Uploaded operator-selected visual: ${file.name}.`,
      });
    },
    async searchPexelsVideos(index) {
      const scene = stateRef.current.draftResult?.scenes?.[index];
      if (!scene) return;
      const query = scene.image_prompt || scene.display_text || scene.narration;
      if (!query.trim()) {
        dispatch({ type: "SET_FIELD", field: "error", value: "Pexels 검색어가 비어 있습니다" });
        return;
      }
      try {
        const res = await apiSearchPexelsVideos(query, Number(scene.duration || 0), 8);
        if (res.ok && res.videos?.length) {
          dispatch({ type: "EDIT_SCENE", index, field: "_pexels_video_candidates", value: res.videos });
          dispatch({ type: "EDIT_SCENE", index, field: "image_source", value: "pexels-video" });
        } else {
          dispatch({ type: "SET_FIELD", field: "error", value: res.error || "Pexels 영상 후보가 없습니다" });
        }
      } catch (e: unknown) {
        dispatch({ type: "SET_FIELD", field: "error", value: e instanceof Error ? e.message : "Pexels 검색 연결 실패" });
      }
    },
    selectPexelsVideo(index, candidate) {
      const currentScene = stateRef.current.draftResult?.scenes?.[index];
      const oldPreview = currentScene?._upload_preview;
      const candidatePool = currentScene?._pexels_video_candidates || [];
      const candidateCount = Math.max(1, candidatePool.length);
      const sceneId = currentScene ? sceneIdFor(currentScene, index) : `scene-${String(index + 1).padStart(2, "0")}`;
      const selectionKey = `${sceneId}:${candidate.id}`;
      const creator = candidate.author || "unknown creator";
      const sourcePage = candidate.sourceUrl || "Pexels source page unavailable";
      const selectionRationale = (
        `Selected from ${candidateCount} Pexels candidates: ${candidate.duration.toFixed(1)}s `
        + `${candidate.width}x${candidate.height} motion by ${creator}; source ${sourcePage}.`
      );
      const enrichedCandidate = {
        ...candidate,
        candidateCount,
        selectionMethod: "operator-selected-from-candidates",
        selectionKey,
        selectionRationale,
      };
      if (oldPreview) URL.revokeObjectURL(oldPreview);
      dispatch({ type: "EDIT_SCENE", index, field: "_upload_preview", value: null });
      dispatch({ type: "EDIT_SCENE", index, field: "_upload_file", value: null });
      dispatch({ type: "EDIT_SCENE", index, field: "_upload_kind", value: null });
      dispatch({ type: "EDIT_SCENE", index, field: "_selected_pexels_video", value: enrichedCandidate });
      dispatch({ type: "EDIT_SCENE", index, field: "_video_url", value: candidate.url });
      dispatch({ type: "EDIT_SCENE", index, field: "image_source", value: "pexels-video" });
      dispatch({ type: "EDIT_SCENE", index, field: "has_image", value: true });
      dispatch({
        type: "EDIT_SCENE",
        index,
        field: "source_rationale",
        value: selectionRationale,
      });
    },
    async createFreeAssetSourcingPacket() {
      const s = stateRef.current;
      const scenes = s.draftResult?.scenes ?? [];
      if (!s.draftResult?.ok || scenes.length === 0) {
        dispatch({ type: "SET_FIELD", field: "error", value: "에셋 패킷을 만들 씬이 없습니다" });
        return null;
      }
      try {
        const packet = await apiCreateFreeAssetSourcingPacket({
          projectId: s.activeProjectId || `free-assets-ui-${Date.now()}`,
          templateType: s.templateType,
          draftScenes: buildDraftScenes(scenes),
        });
        if (!packet.ok) {
          dispatch({ type: "SET_FIELD", field: "error", value: packet.error || "무료 에셋 패킷 생성 실패" });
          return packet;
        }
        dispatch({ type: "SET_FIELD", field: "freeAssetPacket", value: packet });
        return packet;
      } catch (e: unknown) {
        const message = e instanceof Error ? e.message : "무료 에셋 패킷 연결 실패";
        dispatch({ type: "SET_FIELD", field: "error", value: message });
        return null;
      }
    },
    async generateLocalSceneVideo(index) {
      const scene = stateRef.current.draftResult?.scenes?.[index];
      if (!scene) return null;
      const provider = isLocalVideoSource(scene.image_source)
        ? scene.image_source
        : (isLocalVideoSource(scene.local_video_provider) ? scene.local_video_provider : "wan");
      const sceneId = sceneIdFor(scene, index);
      const prompt = scene.grok_prompt || scene.image_prompt || scene.display_text || scene.narration || defaultGrokPrompt(scene);
      const commandTemplate = parseCommandTemplateJson(scene.local_command_template_json);
      if (scene.local_command_template_json?.trim() && !commandTemplate) {
        dispatch({
          type: "SET_FIELD",
          field: "error",
          value: "로컬 command override는 JSON string array 형식이어야 합니다",
        });
        return null;
      }
      try {
        const res = await apiGenerateLocalVideoScene({
          projectId: `local-video-ui-${Date.now()}`,
          sceneId,
          provider,
          prompt,
          title: scene.display_text || scene.image_prompt || `Scene ${index + 1}`,
          durationSec: Number(scene.duration || 5),
          operatorApproved: true,
          ...(commandTemplate ? { commandOverrideApproved: true, commandTemplate } : {}),
        });
        if (!res.ok) {
          dispatch({ type: "SET_FIELD", field: "error", value: res.error || "로컬 영상 생성 실패" });
          return res;
        }
        dispatch({ type: "EDIT_SCENE", index, field: "image_source", value: provider });
        dispatch({ type: "EDIT_SCENE", index, field: "local_video_provider", value: provider });
        dispatch({ type: "EDIT_SCENE", index, field: "local_generation_status", value: res.status || "unknown" });
        dispatch({ type: "EDIT_SCENE", index, field: "local_generation_detail", value: res.detail || "" });
        dispatch({ type: "EDIT_SCENE", index, field: "local_generation_request_path", value: res.requestPath || "" });
        dispatch({ type: "EDIT_SCENE", index, field: "local_generation_prompt_path", value: res.promptPath || "" });
        dispatch({ type: "EDIT_SCENE", index, field: "local_generation_log_path", value: res.logPath || "" });
        dispatch({ type: "EDIT_SCENE", index, field: "local_generation_command_preview", value: res.commandPreview || "" });

        if (res.asset?.sourcePath) {
          const current = stateRef.current.draftResult?.scenes?.[index];
          const oldServerPreview = current?._upload_preview;
          if (oldServerPreview?.startsWith("blob:")) URL.revokeObjectURL(oldServerPreview);
          dispatch({ type: "EDIT_SCENE", index, field: "_upload_preview", value: res.asset.previewUrl || null });
          dispatch({ type: "EDIT_SCENE", index, field: "_upload_file", value: null });
          dispatch({ type: "EDIT_SCENE", index, field: "_upload_kind", value: "video" });
          dispatch({ type: "EDIT_SCENE", index, field: "_upload_name", value: res.asset.fileName || `${sceneId}.${provider}.mp4` });
          dispatch({ type: "EDIT_SCENE", index, field: "_upload_mime", value: res.asset.mimeType || "video/mp4" });
          dispatch({ type: "EDIT_SCENE", index, field: "_server_asset_path", value: res.asset.sourcePath });
          dispatch({ type: "EDIT_SCENE", index, field: "_server_asset_preview_url", value: res.asset.previewUrl || null });
          dispatch({ type: "EDIT_SCENE", index, field: "_server_asset_mime", value: res.asset.mimeType || "video/mp4" });
          dispatch({ type: "EDIT_SCENE", index, field: "_video_url", value: res.asset.previewUrl || null });
          dispatch({ type: "EDIT_SCENE", index, field: "_selected_pexels_video", value: null });
          dispatch({ type: "EDIT_SCENE", index, field: "has_image", value: true });
          dispatch({
            type: "EDIT_SCENE",
            index,
            field: "source_rationale",
            value: scene.source_rationale || `Operator-approved ${provider} command generated MP4: ${res.asset.sourcePath}.`,
          });
          dispatch({
            type: "EDIT_SCENE",
            index,
            field: "originality_evidence",
            value: scene.originality_evidence || `Local ${provider} request packet created and rendered from ${res.requestPath || "Video Studio local command"}.`,
          });
        }
        return res;
      } catch (e: unknown) {
        const message = e instanceof Error ? e.message : "로컬 영상 생성 연결 실패";
        dispatch({ type: "SET_FIELD", field: "error", value: message });
        return null;
      }
    },
    async importLocalVideoFolder(sourceDir, providerHint) {
      const scenes = stateRef.current.draftResult?.scenes ?? [];
      if (!scenes.length) {
        dispatch({ type: "SET_FIELD", field: "error", value: "로컬 MP4를 매칭할 씬이 없습니다" });
        return null;
      }
      const trimmed = sourceDir.trim();
      if (!trimmed) {
        dispatch({ type: "SET_FIELD", field: "error", value: "로컬 MP4 폴더 경로를 입력하세요" });
        return null;
      }
      try {
        const res = await apiImportLocalVideoFolder({
          projectId: `local-folder-ui-${Date.now()}`,
          sourceDir: trimmed,
          draftScenes: buildDraftScenes(scenes),
          operatorApproved: true,
        });
        if (!res.ok) {
          dispatch({ type: "SET_FIELD", field: "error", value: res.error || "로컬 MP4 폴더 가져오기 실패" });
          return res;
        }
        let synced = 0;
        for (const asset of res.assets ?? []) {
          if (!asset.sceneId || !asset.sourcePath) continue;
          const index = scenes.findIndex((scene, sceneIndex) => sceneIdFor(scene, sceneIndex) === asset.sceneId);
          if (index < 0) continue;
          const current = scenes[index];
          const provider = providerHint
            || (isLocalVideoSource(current.image_source) ? current.image_source : undefined)
            || (isLocalVideoSource(current.local_video_provider) ? current.local_video_provider : undefined)
            || "wan";
          const oldPreview = current._upload_preview;
          if (oldPreview?.startsWith("blob:")) URL.revokeObjectURL(oldPreview);
          dispatch({ type: "EDIT_SCENE", index, field: "image_source", value: provider });
          dispatch({ type: "EDIT_SCENE", index, field: "local_video_provider", value: provider });
          dispatch({ type: "EDIT_SCENE", index, field: "local_generation_status", value: "imported-folder" });
          dispatch({ type: "EDIT_SCENE", index, field: "local_generation_detail", value: `${asset.importMatch || "matched"} from ${res.sourceDir || trimmed}` });
          dispatch({ type: "EDIT_SCENE", index, field: "local_generation_request_path", value: res.manifestPath || asset.sourceGeneratorRequestPath || "" });
          dispatch({ type: "EDIT_SCENE", index, field: "local_generation_prompt_path", value: "" });
          dispatch({ type: "EDIT_SCENE", index, field: "local_generation_log_path", value: "" });
          dispatch({ type: "EDIT_SCENE", index, field: "local_generation_command_preview", value: "local-folder-import" });
          dispatch({ type: "EDIT_SCENE", index, field: "_upload_preview", value: asset.previewUrl || null });
          dispatch({ type: "EDIT_SCENE", index, field: "_upload_file", value: null });
          dispatch({ type: "EDIT_SCENE", index, field: "_upload_kind", value: "video" });
          dispatch({ type: "EDIT_SCENE", index, field: "_upload_name", value: asset.fileName || `${asset.sceneId}.local-folder.mp4` });
          dispatch({ type: "EDIT_SCENE", index, field: "_upload_mime", value: asset.mimeType || "video/mp4" });
          dispatch({ type: "EDIT_SCENE", index, field: "_server_asset_path", value: asset.sourcePath });
          dispatch({ type: "EDIT_SCENE", index, field: "_server_asset_preview_url", value: asset.previewUrl || null });
          dispatch({ type: "EDIT_SCENE", index, field: "_server_asset_mime", value: asset.mimeType || "video/mp4" });
          dispatch({ type: "EDIT_SCENE", index, field: "_video_url", value: asset.previewUrl || null });
          dispatch({ type: "EDIT_SCENE", index, field: "_selected_pexels_video", value: null });
          dispatch({ type: "EDIT_SCENE", index, field: "has_image", value: true });
          dispatch({
            type: "EDIT_SCENE",
            index,
            field: "source_rationale",
            value: current.source_rationale || `Operator-approved local MP4 folder import: ${asset.sourcePath}.`,
          });
          dispatch({
            type: "EDIT_SCENE",
            index,
            field: "originality_evidence",
            value: current.originality_evidence || `Local ${provider} or operator-controlled MP4 output imported from ${res.sourceDir || trimmed}; no paid API or stock auto-pick.`,
          });
          synced += 1;
        }
        dispatch({
          type: "SET_FIELD",
          field: "error",
          value: synced ? null : "로컬 MP4가 씬에 매칭되지 않았습니다",
        });
        return res;
      } catch (e: unknown) {
        const message = e instanceof Error ? e.message : "로컬 MP4 폴더 가져오기 연결 실패";
        dispatch({ type: "SET_FIELD", field: "error", value: message });
        return null;
      }
    },
    async createGrokHandoff() {
      return _ensureGrokHandoffPacket();
    },
    async openGrokHandoff(
      target: GrokOpenTarget = "worksheet",
      browserPreference: "default" | "chrome" | "edge" = "default",
      sceneId?: string,
    ) {
      let projectId = stateRef.current.grokHandoff?.projectId;
      if (!projectId) {
        const created = await _ensureGrokHandoffPacket();
        projectId = created?.projectId;
      }
      if (!projectId) {
        dispatch({ type: "SET_FIELD", field: "error", value: "먼저 Grok handoff 패킷을 생성하세요" });
        return;
      }
      const result = await apiOpenGrokHandoff(projectId, target, browserPreference, sceneId);
      if (!result.ok) {
        dispatch({ type: "SET_FIELD", field: "error", value: result.error || "Grok 작업 시트 열기 실패" });
      } else {
        _mergeGrokHandoffState(result);
      }
    },
    async loadGrokAutomationPlan() {
      const projectId = stateRef.current.grokHandoff?.projectId;
      if (!projectId) {
        dispatch({ type: "SET_FIELD", field: "error", value: "먼저 Grok handoff 패킷을 생성하세요" });
        return null;
      }
      const result = await apiGetGrokAutomationPlan(projectId);
      if (!result.ok) {
        dispatch({ type: "SET_FIELD", field: "error", value: result.error || "Grok 자동화 플랜 확인 실패" });
        return null;
      }
      _mergeGrokHandoffState(result);
      return result;
    },
    async uploadGrokSceneMp4(index, file) {
      const s = stateRef.current;
      const projectId = s.grokHandoff?.projectId;
      const scene = s.draftResult?.scenes?.[index];
      if (!projectId || !scene) {
        dispatch({ type: "SET_FIELD", field: "error", value: "먼저 Grok handoff 패킷을 생성하세요" });
        return null;
      }
      if (!file.type.startsWith("video/") && !file.name.toLowerCase().endsWith(".mp4")) {
        dispatch({ type: "SET_FIELD", field: "error", value: "Grok handoff에는 MP4 영상 파일만 업로드할 수 있습니다" });
        return null;
      }
      try {
        const sceneId = sceneIdFor(scene, index);
        const result = await apiUploadGrokSceneMp4(projectId, {
          sceneId,
          fileName: file.name,
          fileBase64: await readFileBase64(file),
          operatorApproved: true,
          preserveCandidates: true,
        });
        if (!result.ok) {
          dispatch({ type: "SET_FIELD", field: "error", value: result.error || "Grok MP4 업로드 반입 실패" });
          return result;
        }
        _mergeGrokHandoffState(result);
        const synced = _applyGrokAssets(result);
        dispatch({
          type: "SET_FIELD",
          field: "error",
          value: synced > 0
            ? null
            : `${sceneId} Grok MP4 candidate는 반입됐지만 대시보드 preview가 아직 동기화되지 않았습니다`,
        });
        return result;
      } catch (e: unknown) {
        const message = e instanceof Error ? e.message : "Grok MP4 업로드 연결 실패";
        dispatch({ type: "SET_FIELD", field: "error", value: message });
        return null;
      }
    },
    async uploadGrokSceneMp4Batch(index, files, mode = "auto") {
      const s = stateRef.current;
      const projectId = s.grokHandoff?.projectId;
      const scenes = s.draftResult?.scenes || [];
      if (!projectId || !scenes.length) {
        dispatch({ type: "SET_FIELD", field: "error", value: "먼저 Grok handoff 패킷을 생성하세요" });
        return null;
      }
      const videoFiles = files.filter((file) => file.type.startsWith("video/") || file.name.toLowerCase().endsWith(".mp4"));
      if (!videoFiles.length) {
        dispatch({ type: "SET_FIELD", field: "error", value: "Grok handoff에는 MP4 영상 파일만 업로드할 수 있습니다" });
        return null;
      }
      try {
        const sceneIdsInOrder = scenes.map((scene, sceneIndex) => sceneIdFor(scene, sceneIndex));
        const sceneIds = new Set(sceneIdsInOrder);
        const currentSceneId = sceneIdsInOrder[index] || sceneIdsInOrder[0] || "";
        const genericGrokNames = videoFiles.every((file) => !sceneIdFromGrokUploadName(file.name));
        const groupedTakeMode = mode === "scene-grouped-takes" || (
          mode === "auto"
          && genericGrokNames
          && videoFiles.length > sceneIdsInOrder.length
        );
        const groupedTakeSize = groupedTakeMode && sceneIdsInOrder.length
          ? Math.max(1, Math.ceil(videoFiles.length / sceneIdsInOrder.length))
          : 0;
        const uploads = await Promise.all(videoFiles.map(async (file, offset) => {
          const inferredSceneId = sceneIdFromGrokUploadName(file.name);
          let sceneId = "";
          if (sceneIds.has(inferredSceneId)) {
            sceneId = inferredSceneId;
          } else if (mode === "current-scene-candidates") {
            sceneId = currentSceneId;
          } else if (groupedTakeMode && groupedTakeSize > 0) {
            sceneId = sceneIdsInOrder[Math.min(Math.floor(offset / groupedTakeSize), sceneIdsInOrder.length - 1)] || "";
          } else {
            const sequentialScene = scenes[index + offset] || scenes[offset] || scenes[index];
            sceneId = sequentialScene
              ? sceneIdFor(sequentialScene, scenes.indexOf(sequentialScene))
              : "";
          }
          return {
            sceneId,
            fileName: file.name,
            fileBase64: await readFileBase64(file),
          };
        }));
        const result = await apiUploadGrokSceneMp4Batch(projectId, {
          files: uploads,
          operatorApproved: true,
          preserveCandidates: true,
          sceneMappingMode: groupedTakeMode ? "scene-grouped-takes" : undefined,
        });
        if (!result.ok) {
          dispatch({ type: "SET_FIELD", field: "error", value: result.error || "Grok MP4 일괄 반입 실패" });
          return result;
        }
        _mergeGrokHandoffState(result);
        const synced = _applyGrokAssets(result);
        const imported = result.imported?.length || 0;
        const skipped = result.skipped?.length || 0;
        dispatch({
          type: "SET_FIELD",
          field: "error",
          value: imported > 0
            ? `Grok MP4 ${imported}개 반입, ${synced}개 씬 preview 동기화${skipped ? `, ${skipped}개 skip` : ""}`
            : `Grok MP4 일괄 반입 결과가 없습니다${skipped ? ` (${skipped}개 skip)` : ""}`,
        });
        return result;
      } catch (e: unknown) {
        const message = e instanceof Error ? e.message : "Grok MP4 일괄 업로드 연결 실패";
        dispatch({ type: "SET_FIELD", field: "error", value: message });
        return null;
      }
    },
    async importGrokDownloads(downloadDir) {
      const projectId = stateRef.current.grokHandoff?.projectId;
      if (!projectId) {
        dispatch({ type: "SET_FIELD", field: "error", value: "먼저 Grok handoff 패킷을 생성하세요" });
        return null;
      }
      const trimmed = downloadDir.trim();
      if (!trimmed) {
        dispatch({ type: "SET_FIELD", field: "error", value: "Grok MP4가 저장된 다운로드 폴더 경로를 입력하세요" });
        return null;
      }
      const result = await apiImportGrokDownloads(projectId, {
        downloadDir: trimmed,
        operatorApproved: true,
        allowNewestFallback: true,
      });
      if (!result.ok) {
        dispatch({ type: "SET_FIELD", field: "error", value: result.error || "Grok 다운로드 가져오기 실패" });
        return null;
      }
      _mergeGrokHandoffState(result);
      const synced = _applyGrokAssets(result);
      if (synced === 0) {
        dispatch({ type: "SET_FIELD", field: "error", value: "가져온 Grok MP4가 씬에 매칭되지 않았습니다" });
      } else {
        dispatch({ type: "SET_FIELD", field: "error", value: null });
      }
      return result;
    },
    async watchGrokDownloads(downloadDir) {
      const projectId = stateRef.current.grokHandoff?.projectId;
      if (!projectId) {
        dispatch({ type: "SET_FIELD", field: "error", value: "먼저 Grok handoff 패킷을 생성하세요" });
        return null;
      }
      const trimmed = downloadDir.trim();
      if (!trimmed) {
        dispatch({ type: "SET_FIELD", field: "error", value: "Grok MP4가 저장될 다운로드 폴더 경로를 입력하세요" });
        return null;
      }
      const result = await apiWatchGrokDownloads(projectId, {
        downloadDir: trimmed,
        downloadDirs: grokManualWatchDownloadDirs(trimmed),
        operatorApproved: true,
        allowNewestFallback: true,
        timeoutSeconds: 45,
        pollIntervalSeconds: 2,
      });
      if (!result.ok) {
        dispatch({ type: "SET_FIELD", field: "error", value: result.error || "Grok 다운로드 감시 실패" });
        return null;
      }
      _mergeGrokHandoffState(result);
      const synced = _applyGrokAssets(result);
      if (!result.allReady) {
        dispatch({ type: "SET_FIELD", field: "error", value: "제한 시간 안에 모든 Grok MP4가 준비되지 않았습니다" });
        return result;
      }
      if (synced === 0) {
        dispatch({ type: "SET_FIELD", field: "error", value: "감시된 Grok MP4가 씬에 매칭되지 않았습니다" });
        return result;
      }
      if (result.renderPayload?.allReady) {
        await _renderGrokPayload(projectId, result.renderPayload, { finalizeChannelPacket: true });
      } else {
        dispatch({ type: "SET_FIELD", field: "error", value: null });
      }
      return result;
    },
    async startGrokManualDownloadWatch(downloadDir, sceneId = "") {
      const projectId = stateRef.current.grokHandoff?.projectId;
      if (!projectId) {
        dispatch({ type: "SET_FIELD", field: "error", value: "먼저 Grok handoff 패킷을 생성하세요" });
        return null;
      }
      const trimmed = downloadDir.trim();
      if (!trimmed) {
        dispatch({ type: "SET_FIELD", field: "error", value: "Grok MP4가 저장될 다운로드 폴더 경로를 입력하세요" });
        return null;
      }
      const targetSceneId = (sceneId || stateRef.current.grokHandoff?.nextMissingSceneId || "").trim();
      const result = await apiStartGrokManualDownloadWatch(projectId, {
        downloadDir: trimmed,
        downloadDirs: grokManualWatchDownloadDirs(trimmed),
        operatorApproved: true,
        sceneId: targetSceneId || undefined,
        allowNewestFallback: true,
        sinceHandoff: true,
        preserveCandidates: true,
        stopOnImport: true,
        timeoutSeconds: 900,
        pollIntervalSeconds: 2,
      });
      if (!result.ok) {
        dispatch({ type: "SET_FIELD", field: "error", value: result.error || "Grok 수동 다운로드 감시 시작 실패" });
        return null;
      }
      _mergeGrokHandoffState(result);
      dispatch({
        type: "SET_FIELD",
        field: "error",
        value: result.alreadyRunning
          ? `${result.manualDownloadWatchJob?.sceneId || targetSceneId || "Grok"} MP4 수동 감시가 이미 실행 중입니다.`
          : `${result.manualDownloadWatchJob?.sceneId || targetSceneId || "Grok"} MP4 수동 감시 시작. Grok에서 생성 후 Downloads/Desktop/Videos 중 저장하면 자동 반입됩니다.`,
      });
      return result;
    },
    async startGrokManualDownloadWatchAll(downloadDir) {
      const projectId = stateRef.current.grokHandoff?.projectId;
      if (!projectId) {
        dispatch({ type: "SET_FIELD", field: "error", value: "먼저 Grok handoff 패킷을 생성하세요" });
        return null;
      }
      const trimmed = downloadDir.trim();
      if (!trimmed) {
        dispatch({ type: "SET_FIELD", field: "error", value: "Grok MP4가 저장될 다운로드 폴더 경로를 입력하세요" });
        return null;
      }
      const result = await apiStartGrokManualDownloadWatch(projectId, {
        downloadDir: trimmed,
        downloadDirs: grokManualWatchDownloadDirs(trimmed),
        operatorApproved: true,
        watchAllScenes: true,
        allowNewestFallback: true,
        sinceHandoff: true,
        preserveCandidates: true,
        sceneMappingMode: "scene-grouped-takes",
        sceneGroupedTakeSize: 2,
        stopOnImport: false,
        replaceExisting: true,
        timeoutSeconds: 1800,
        pollIntervalSeconds: 2,
      });
      if (!result.ok) {
        dispatch({ type: "SET_FIELD", field: "error", value: result.error || "Grok 전체 다운로드 감시 시작 실패" });
        return null;
      }
      _mergeGrokHandoffState(result);
      dispatch({
        type: "SET_FIELD",
        field: "error",
        value: result.alreadyRunning
          ? "Grok 전체 씬 다운로드 감시가 이미 실행 중입니다."
          : result.replacedExisting
            ? "기존 단일 씬 Grok 감시를 전체 씬 2-take 감시로 교체했습니다. 생산 큐 순서대로 씬당 2개 MP4를 저장하면 후보군으로 자동 반입됩니다."
          : "Grok 전체 씬 후보 감시 시작. 생산 큐 순서대로 씬당 2개 MP4를 Downloads/Desktop/Videos 중 저장하면 scene-01 후보 2개, scene-02 후보 2개...로 자동 반입됩니다.",
      });
      return result;
    },
    async runGrokOperatorLoop(downloadDir) {
      void downloadDir;
      dispatch({
        type: "SET_FIELD",
        field: "error",
        value: "Grok 승인 실행+Downloads 감시는 native download prompt 함정 때문에 차단되었습니다. Companion/pageAssets direct import 또는 이미 소유한 로컬 MP4 반입만 사용하세요.",
      });
      return null;
    },
    async runGrokBrowserAutomation(index, downloadDir = "", opts = {}) {
      const s = stateRef.current;
      const projectId = s.grokHandoff?.projectId;
      const scene = s.draftResult?.scenes?.[index];
      if (!projectId || !scene) {
        dispatch({ type: "SET_FIELD", field: "error", value: "자동 입력할 Grok handoff 씬이 없습니다" });
        return null;
      }
      const sceneId = sceneIdFor(scene, index);
      void downloadDir;
      const profilePayload = grokBrowserProfilePayload(opts);
      const preflight = await apiRunGrokBrowserAutomation(projectId, {
        sceneId,
        operatorApproved: true,
        browserAutomationApproved: true,
        ...profilePayload,
        preflightOnly: true,
        authProviderPreference: opts.authProviderPreference ?? GROK_AUTH_PROVIDER_DEFAULT,
      });
      if (!preflight.ok) {
        dispatch({ type: "SET_FIELD", field: "error", value: preflight.error || "Grok 브라우저 준비 확인 실패" });
        return null;
      }
      _mergeGrokHandoffState(preflight);
      if (preflight.requiresOperatorAction || preflight.authRequired || preflight.cookieChoiceRequired) {
        const blockers = [
          preflight.authRequired ? "Grok 로그인" : null,
          preflight.cookieChoiceRequired ? "쿠키 선택" : null,
        ].filter(Boolean).join(" / ");
        dispatch({
          type: "SET_FIELD",
          field: "error",
          value: `${sceneId} Grok preflight: ${blockers} 대기 중. 승인된 대기 시간 안에 완료되면 자동 재개합니다.`,
        });
      }
      const result = await apiRunGrokBrowserAutomation(projectId, {
        sceneId,
        operatorApproved: true,
        browserAutomationApproved: true,
        ...profilePayload,
        waitForOperatorReadyApproved: true,
        authKickoffApproved: true,
        authProviderKickoffApproved: true,
        authProviderPreference: opts.authProviderPreference ?? GROK_AUTH_PROVIDER_DEFAULT,
        cookieRejectApproved: true,
        operatorReadyTimeoutSeconds: opts.operatorReadyTimeoutSeconds ?? GROK_OPERATOR_WAIT_DEFAULT_SECONDS,
        operatorReadyPollIntervalSeconds: opts.operatorReadyPollIntervalSeconds ?? 2,
        submitPromptApproved: false,
        generatePromptApproved: true,
        downloadResultApproved: false,
        watchDownloadsApproved: false,
        allowNewestFallback: false,
        sinceHandoff: true,
        downloadClickTimeoutSeconds: 0,
        watchTimeoutSeconds: 0,
        watchPollIntervalSeconds: 2,
      });
      if (!result.ok) {
        dispatch({ type: "SET_FIELD", field: "error", value: result.error || "Grok 브라우저 자동 입력 실패" });
        return null;
      }
      _mergeGrokHandoffState(result);
      const synced = result.assets ? _applyGrokAssets(result) : 0;
      if (result.renderPayload?.allReady) {
        await _renderGrokPayload(projectId, result.renderPayload, { finalizeChannelPacket: true });
        return result;
      }
      if (result.operatorReadyTimedOut) {
        dispatch({
          type: "SET_FIELD",
          field: "error",
          value: `${result.filledSceneId || sceneId} Grok 로그인/쿠키 대기 시간이 끝났습니다. 열린 브라우저에서 완료 후 다시 승인 생성+감시를 실행하세요.`,
        });
        return result;
      }
      if (result.requiresOperatorAction || result.authRequired || result.cookieChoiceRequired) {
        const blockers = [
          result.authRequired ? "Grok 로그인" : null,
          result.cookieChoiceRequired ? "쿠키 선택" : null,
        ].filter(Boolean).join(" / ");
        dispatch({
          type: "SET_FIELD",
          field: "error",
          value: `${result.filledSceneId || sceneId} prompt injected; ${blockers} 처리 후 승인 생성+감시를 다시 실행하세요.`,
        });
        return result;
      }
      dispatch({
        type: "SET_FIELD",
        field: "error",
        value: [
          `${result.filledSceneId || sceneId} prompt injected`,
          result.generateRequested ? `generation requested (${result.generateAction || "browser action"})` : null,
          `no download/watch; use direct import or local MP4 upload/import for source proof; synced ${synced || result.readyScenes || 0}/${result.totalScenes || 0}`,
        ].filter(Boolean).join(" / "),
      });
      return result;
    },
    async startGrokBackgroundAutomation(index, downloadDir = "", opts = {}) {
      const s = stateRef.current;
      let projectId = s.grokHandoff?.projectId;
      const scene = s.draftResult?.scenes?.[index];
      if (!scene) {
        dispatch({ type: "SET_FIELD", field: "error", value: "백그라운드 실행할 Grok handoff 씬이 없습니다" });
        return null;
      }
      let fallbackDownloadDir = s.grokHandoff?.defaultDownloadDir || "";
      if (!projectId) {
        const created = await _ensureGrokHandoffPacket();
        projectId = created?.projectId;
        fallbackDownloadDir = created?.defaultDownloadDir || fallbackDownloadDir;
      }
      if (!projectId) return null;
      const sceneId = sceneIdFor(scene, index);
      void downloadDir;
      void fallbackDownloadDir;
      const waitSeconds = Math.max(30, Math.min(GROK_OPERATOR_WAIT_MAX_SECONDS, opts.operatorReadyTimeoutSeconds ?? GROK_OPERATOR_WAIT_DEFAULT_SECONDS));
      const profilePayload = grokBrowserProfilePayload(opts);
      const result = await apiStartGrokBackgroundAutomation(projectId, {
        sceneId,
        operatorApproved: true,
        browserAutomationApproved: true,
        ...profilePayload,
        waitForOperatorReadyApproved: true,
        authKickoffApproved: true,
        authProviderKickoffApproved: true,
        authProviderPreference: opts.authProviderPreference ?? GROK_AUTH_PROVIDER_DEFAULT,
        cookieRejectApproved: true,
        generatePromptApproved: true,
        downloadResultApproved: false,
        watchDownloadsApproved: false,
        allowNewestFallback: false,
        sinceHandoff: true,
        operatorReadyTimeoutSeconds: waitSeconds,
        operatorReadyPollIntervalSeconds: opts.operatorReadyPollIntervalSeconds ?? 2,
        downloadClickTimeoutSeconds: 0,
        watchTimeoutSeconds: 0,
        watchPollIntervalSeconds: 2,
        supersedeActiveJobApproved: opts.supersedeActiveJobApproved === true,
      });
      if (!result.ok) {
        dispatch({ type: "SET_FIELD", field: "error", value: result.error || "Grok 백그라운드 자동화 시작 실패" });
        return null;
      }
      _mergeGrokHandoffState(result);
      const profileLabel = profilePayload.useDefaultChromeProfile ? "operator-launched logged-in Chrome CDP attach" : "isolated Grok login profile";
      dispatch({
        type: "SET_FIELD",
        field: "error",
        value: result.alreadyRunning
          ? `${result.automationJob?.sceneId || sceneId} Grok background job already running. 열린 브라우저에서 로그인만 완료하면 기존 대기가 자동으로 이어집니다.`
          : result.supersededJob
          ? `${result.automationJob?.sceneId || sceneId} Grok background job restarted with ${profileLabel}. 이전 대기 job은 취소 요청했고, 열린 브라우저에서 로그인/동의만 완료하면 이어집니다.`
          : `${result.automationJob?.sceneId || sceneId} Grok background job started with ${profileLabel}. 브라우저에서 로그인만 완료하면 prompt generation까지만 이어집니다; MP4 source proof는 direct import 또는 로컬 업로드로 처리하세요.`,
      });
      return result;
    },
    async startNextGrokBackgroundAutomation(downloadDir = "", opts = {}) {
      let s = stateRef.current;
      let handoff = s.grokHandoff;
      let projectId = handoff?.projectId;
      let fallbackDownloadDir = handoff?.defaultDownloadDir || "";
      if (!projectId) {
        handoff = await _ensureGrokHandoffPacket();
        projectId = handoff?.projectId;
        fallbackDownloadDir = handoff?.defaultDownloadDir || fallbackDownloadDir;
        s = stateRef.current;
      }
      if (!projectId) return null;
      const sceneId = handoff?.nextMissingSceneId || s.grokHandoff?.nextMissingSceneId || "__next_missing__";
      void downloadDir;
      void fallbackDownloadDir;
      const waitSeconds = Math.max(30, Math.min(GROK_OPERATOR_WAIT_MAX_SECONDS, opts.operatorReadyTimeoutSeconds ?? GROK_OPERATOR_WAIT_DEFAULT_SECONDS));
      const profilePayload = grokBrowserProfilePayload(opts);
      const result = await apiStartGrokBackgroundAutomation(projectId, {
        sceneId,
        operatorApproved: true,
        browserAutomationApproved: true,
        ...profilePayload,
        waitForOperatorReadyApproved: true,
        authKickoffApproved: true,
        authProviderKickoffApproved: true,
        authProviderPreference: opts.authProviderPreference ?? GROK_AUTH_PROVIDER_DEFAULT,
        cookieRejectApproved: true,
        generatePromptApproved: true,
        downloadResultApproved: false,
        watchDownloadsApproved: false,
        allowNewestFallback: false,
        sinceHandoff: true,
        operatorReadyTimeoutSeconds: waitSeconds,
        operatorReadyPollIntervalSeconds: opts.operatorReadyPollIntervalSeconds ?? 2,
        downloadClickTimeoutSeconds: 0,
        watchTimeoutSeconds: 0,
        watchPollIntervalSeconds: 2,
        supersedeActiveJobApproved: opts.supersedeActiveJobApproved === true,
      });
      if (!result.ok) {
        dispatch({ type: "SET_FIELD", field: "error", value: result.error || "다음 Grok 씬 백그라운드 자동화 시작 실패" });
        return null;
      }
      _mergeGrokHandoffState(result);
      const profileLabel = profilePayload.useDefaultChromeProfile ? "operator-launched logged-in Chrome CDP attach" : "isolated Grok login profile";
      dispatch({
        type: "SET_FIELD",
        field: "error",
        value: result.alreadyRunning
          ? `${result.automationJob?.sceneId || sceneId} Grok background job already running.`
          : result.supersededJob
          ? `${result.automationJob?.sceneId || result.sceneId || sceneId} Grok background job restarted with ${profileLabel}.`
          : `${result.automationJob?.sceneId || result.sceneId || sceneId} next Grok scene background job started with ${profileLabel}.`,
      });
      return result;
    },
    async resumeGrokBrowserAutomation(index, opts = {}) {
      const s = stateRef.current;
      const projectId = s.grokHandoff?.projectId;
      const scene = s.draftResult?.scenes?.[index];
      if (!projectId || !scene) {
        dispatch({ type: "SET_FIELD", field: "error", value: "재개할 Grok handoff 씬이 없습니다" });
        return null;
      }
      const sceneId = sceneIdFor(scene, index);
      const replay = s.grokHandoff?.automationReplay;
      const waitSeconds = Math.max(30, Math.min(GROK_OPERATOR_WAIT_MAX_SECONDS, opts.operatorReadyTimeoutSeconds ?? GROK_OPERATOR_WAIT_DEFAULT_SECONDS));
      const profilePayload = grokBrowserProfilePayload(opts);
      const result = await apiResumeGrokBrowserAutomation(projectId, {
        sceneId: replay?.sceneId || sceneId,
        operatorApproved: true,
        browserAutomationApproved: true,
        ...profilePayload,
        waitForOperatorReadyApproved: true,
        authKickoffApproved: true,
        authProviderKickoffApproved: true,
        authProviderPreference: opts.authProviderPreference ?? GROK_AUTH_PROVIDER_DEFAULT,
        cookieRejectApproved: true,
        operatorReadyTimeoutSeconds: waitSeconds,
        operatorReadyPollIntervalSeconds: opts.operatorReadyPollIntervalSeconds ?? 2,
      });
      if (!result.ok) {
        dispatch({ type: "SET_FIELD", field: "error", value: result.error || "Grok 자동화 재개 실패" });
        return null;
      }
      _mergeGrokHandoffState(result);
      const synced = result.assets ? _applyGrokAssets(result) : 0;
      if (result.renderPayload?.allReady) {
        await _renderGrokPayload(projectId, result.renderPayload, { finalizeChannelPacket: true });
        return result;
      }
      if (result.requiresOperatorAction || result.authRequired || result.cookieChoiceRequired || result.operatorReadyTimedOut) {
        dispatch({
          type: "SET_FIELD",
          field: "error",
          value: `${result.filledSceneId || replay?.sceneId || sceneId} Grok 자동화 재개 대기 중: ${result.browserBlocker || "operator action required"}`,
        });
        return result;
      }
      dispatch({
        type: "SET_FIELD",
        field: "error",
        value: [
          `${result.filledSceneId || replay?.sceneId || sceneId} Grok 자동화 재개`,
          result.generateRequested ? `generation requested (${result.generateAction || "browser action"})` : null,
          `synced ${synced || result.readyScenes || 0}/${result.totalScenes || 0}`,
        ].filter(Boolean).join(" / "),
      });
      return result;
    },
    async focusGrokOperatorBrowser() {
      const projectId = stateRef.current.grokHandoff?.projectId;
      if (!projectId) {
        dispatch({ type: "SET_FIELD", field: "error", value: "포커스할 Grok handoff 패킷이 없습니다" });
        return null;
      }
      const result = await apiFocusGrokOperatorBrowser(projectId, {
        operatorApproved: true,
        browserAutomationApproved: true,
        focusApproved: true,
        openGrokIfMissing: true,
        remoteDebuggingPort: 9222,
      });
      if (!result.ok) {
        dispatch({ type: "SET_FIELD", field: "error", value: result.error || "Grok 로그인 탭 포커스 실패" });
        return null;
      }
      const target = result.bestTarget || result.openedTarget || null;
      _mergeGrokHandoffState({
        projectId,
        automationStatus: {
          ...(stateRef.current.grokHandoff?.automationStatus ?? {}),
          status: "needs-operator",
          targetUrl: target?.url,
          targetTitle: target?.title,
          remoteDebuggingPort: result.remoteDebuggingPort,
          operatorNextAction: result.operatorNextAction,
          detail: [
            result.focused ? "operator tab focused" : "operator tab inspected",
            target?.kind ? `target=${target.kind}` : null,
            typeof result.signInTabCount === "number" ? `sign-in tabs=${result.signInTabCount}` : null,
          ].filter(Boolean).join(" / "),
        },
      });
      dispatch({
        type: "SET_FIELD",
        field: "error",
        value: [
          result.focused ? "Grok 로그인/Imagine 탭을 앞으로 가져왔습니다" : "Grok operator 탭을 확인했습니다",
          target?.kind ? target.kind : null,
          result.operatorNextAction,
        ].filter(Boolean).join(" / "),
      });
      return result;
    },
    async cleanupGrokOperatorTabs() {
      const projectId = stateRef.current.grokHandoff?.projectId;
      if (!projectId) {
        dispatch({ type: "SET_FIELD", field: "error", value: "정리할 Grok handoff 패킷이 없습니다" });
        return null;
      }
      const result = await apiCleanupGrokOperatorTabs(projectId, {
        operatorApproved: true,
        browserAutomationApproved: true,
        closeDuplicatesApproved: true,
        keepCount: 1,
        remoteDebuggingPort: 9222,
      });
      if (!result.ok) {
        dispatch({ type: "SET_FIELD", field: "error", value: result.error || "Grok 중복 탭 정리 실패" });
        return null;
      }
      const target = result.bestTarget || result.keptTargets?.[0] || null;
      _mergeGrokHandoffState({
        projectId,
        automationStatus: {
          ...(stateRef.current.grokHandoff?.automationStatus ?? {}),
          status: "needs-operator",
          targetUrl: target?.url,
          targetTitle: target?.title,
          remoteDebuggingPort: result.remoteDebuggingPort,
          operatorNextAction: result.operatorNextAction,
          detail: [
            `closed ${result.closedCount ?? 0} duplicate tabs`,
            target?.kind ? `kept=${target.kind}` : null,
            typeof result.signInTabCount === "number" ? `sign-in tabs=${result.signInTabCount}` : null,
          ].filter(Boolean).join(" / "),
        },
      });
      dispatch({
        type: "SET_FIELD",
        field: "error",
        value: [
          `Grok 중복 탭 ${result.closedCount ?? 0}개 정리`,
          target?.kind ? `${target.kind} 유지` : null,
          result.failedCount ? `실패 ${result.failedCount}` : null,
          result.operatorNextAction,
        ].filter(Boolean).join(" / "),
      });
      return result;
    },
    async syncGrokHandoff(options = {}) {
      const projectId = stateRef.current.grokHandoff?.projectId;
      const scenes = stateRef.current.draftResult?.scenes ?? [];
      if (!projectId || scenes.length === 0) {
        if (!options.silent) {
          dispatch({ type: "SET_FIELD", field: "error", value: "동기화할 Grok handoff 패킷이 없습니다" });
        }
        return;
      }
      const status = await apiGetGrokHandoffStatus(projectId);
      if (!status.ok) {
        if (!options.silent) {
          dispatch({ type: "SET_FIELD", field: "error", value: status.error || "Grok MP4 동기화 실패" });
        }
        return;
      }
      _mergeGrokHandoffState(status);
      const synced = _applyGrokAssets(status);
      if (status.allReady && synced > 0) {
        dispatch({
          type: "SET_FIELD",
          field: "error",
          value: options.fromBackgroundPoll
            ? "Grok background job imported MP4s. Open Grok 검수, then run Grok 렌더."
            : null,
        });
        return;
      }
      if (synced === 0 && !options.silent) {
        dispatch({ type: "SET_FIELD", field: "error", value: "아직 동기화할 Grok MP4가 없습니다. incoming 폴더에 scene-01.grok.mp4 형식으로 저장하세요" });
      }
    },
    async saveGrokReviewDecision(index, accepted, operatorNote = "", checks = {}, selectedFileName = "", candidateSummary = "", qualityFields = {}) {
      const s = stateRef.current;
      const projectId = s.grokHandoff?.projectId;
      const scene = s.draftResult?.scenes?.[index];
      if (!projectId || !scene) {
        dispatch({ type: "SET_FIELD", field: "error", value: "검수할 Grok handoff 씬이 없습니다" });
        return false;
      }
      const sceneId = sceneIdFor(scene, index);
      const selectedGrokFileName = String(selectedFileName || "").trim();
      const candidateSummaryText = String(candidateSummary || "").trim();
      const grokCandidateCount = selectedHandoffCandidateCountForScene(s.grokHandoff?.assets, sceneId);
      const selectedCandidate = selectedHandoffCandidateForScene(s.grokHandoff?.assets, sceneId, selectedGrokFileName);
      const sourceProvenanceStatus = String(selectedCandidate?.sourceProvenance?.status || "");
      const sourceProvenanceFields = {
        sourceProvenanceConfirmed: qualityFields.sourceProvenanceConfirmed === true,
        sourceProvenanceNote: String(qualityFields.sourceProvenanceNote || "").trim(),
      };
      const sourceRationale = String(scene.source_rationale || "").trim();
      const qualityReviewNote = String(scene.quality_review_note || "").trim();
      const detailedReviewRequired = Boolean(accepted && s.grokHandoff?.mainSourceGate?.required);
      const sourceProvenanceConfirmationRequired = Boolean(
        accepted
        && s.grokHandoff?.mainSourceGate?.required
        && grokSourceProvenanceConfirmationRequired(sourceProvenanceStatus),
      );
      const detailedReviewFields = {
        captionLayoutReviewNote: String(qualityFields.captionLayoutReviewNote || "").trim(),
        visualQualityVerdict: String(qualityFields.visualQualityVerdict || "").trim(),
        shotLockMatch: qualityFields.shotLockMatch === true,
        sceneAssemblyOk: qualityFields.sceneAssemblyOk === true,
        shotLockEvidenceNote: String(qualityFields.shotLockEvidenceNote || "").trim(),
        sceneAssemblyRoleNote: String(qualityFields.sceneAssemblyRoleNote || "").trim(),
        continuityNote: String(qualityFields.continuityNote || "").trim(),
        hookNote: String(qualityFields.hookNote || "").trim(),
        layoutVariantKey: String(qualityFields.layoutVariantKey || "").trim(),
        layoutVariantLabel: String(qualityFields.layoutVariantLabel || "").trim(),
        layoutVariantNote: String(qualityFields.layoutVariantNote || "").trim(),
        thumbnailReviewNote: String(qualityFields.thumbnailReviewNote || "").trim(),
        audioMixReviewNote: String(qualityFields.audioMixReviewNote || "").trim(),
        platformComparisonNote: String(qualityFields.platformComparisonNote || "").trim(),
      };
      if (accepted) {
        if (isGenericGrokAcceptanceEvidence(sourceRationale) || sourceRationale.length < 24) {
          dispatch({
            type: "SET_FIELD",
            field: "error",
            value: "Grok 승인에는 generic 문구가 아닌 선택 근거가 필요합니다. 아래 '선택 근거'에 왜 이 take를 골랐는지 적어주세요.",
          });
          return false;
        }
        if (qualityReviewNote.length < 24) {
          dispatch({
            type: "SET_FIELD",
            field: "error",
            value: "Grok 승인에는 품질 검수 메모가 필요합니다. 워터마크, artifact, 자막 safe zone, 컷 자연스러움을 확인해 적어주세요.",
          });
          return false;
        }
        if (s.grokHandoff?.mainSourceGate?.required) {
          if (grokCandidateCount < 2) {
            dispatch({
              type: "SET_FIELD",
              field: "error",
              value: "Grok-main 승인은 씬당 Grok MP4 take 2개 이상을 가져온 뒤 비교해야 합니다. Grok에서 다른 take를 하나 더 생성해 다운로드하세요.",
            });
            return false;
          }
          if (candidateSummaryText.length < 24) {
            dispatch({
              type: "SET_FIELD",
              field: "error",
              value: "Grok-main 승인에는 후보 비교 메모가 필요합니다. 선택한 take가 다른 후보보다 나은 이유를 적어주세요.",
            });
            return false;
          }
          if (sourceProvenanceConfirmationRequired) {
            if (!sourceProvenanceFields.sourceProvenanceConfirmed || sourceProvenanceFields.sourceProvenanceNote.length < 24) {
              dispatch({
                type: "SET_FIELD",
                field: "error",
                value: "Grok-main 로컬 MP4 승인은 Grok Download/Save/Export에서 저장한 원본 파일인지 확인 체크와 메모가 필요합니다.",
              });
              return false;
            }
          }
        }
        if (detailedReviewRequired) {
          const missingDetailed = [
            detailedReviewFields.visualQualityVerdict === "pass" ? "" : "visual verdict pass",
            detailedReviewFields.shotLockMatch ? "" : "shot-lock match",
            detailedReviewFields.sceneAssemblyOk ? "" : "scene assembly",
            detailedReviewFields.shotLockEvidenceNote.length >= 24 ? "" : "shot-lock evidence",
            detailedReviewFields.sceneAssemblyRoleNote.length >= 24 ? "" : "scene assembly role",
            detailedReviewFields.captionLayoutReviewNote.length >= 24 ? "" : "caption/layout",
            detailedReviewFields.continuityNote.length >= 24 ? "" : "continuity",
            detailedReviewFields.hookNote.length >= 24 ? "" : "first 2s hook",
            detailedReviewFields.layoutVariantNote.length >= 24 ? "" : "layout variant",
            detailedReviewFields.thumbnailReviewNote.length >= 24 ? "" : "thumbnail/first frame",
            detailedReviewFields.audioMixReviewNote.length >= 24 ? "" : "audio mix",
            detailedReviewFields.platformComparisonNote.length >= 24 ? "" : "platform benchmark",
          ].filter(Boolean);
          if (missingDetailed.length > 0) {
            dispatch({
              type: "SET_FIELD",
              field: "error",
              value: `Grok-main 승인에는 상세 품질 검수 필드가 필요합니다: ${missingDetailed.join(", ")}`,
            });
            return false;
          }
        }
      }
      const result = await apiSaveGrokReviewDecision(projectId, {
        sceneId,
        accepted,
        ...(selectedGrokFileName ? { selectedFileName: selectedGrokFileName } : {}),
        firstTwoSecondHook: accepted ? checks.firstTwoSecondHook === true : false,
        artifactFree: accepted ? checks.artifactFree === true : false,
        continuityOk: accepted ? checks.continuityOk === true : false,
        captionSafe: accepted ? checks.captionSafe === true : false,
        sourceRationale: sourceRationale || `Dashboard rejected Grok handoff clip${selectedGrokFileName ? ` ${selectedGrokFileName}` : ""} for ${sceneId}.`,
        qualityReviewNote: qualityReviewNote || (
          accepted
            ? ""
            : "Dashboard review rejected: clip needs replacement before channel render."
        ),
        ...detailedReviewFields,
        ...sourceProvenanceFields,
        selectedCandidateSummary: candidateSummaryText,
        singleCandidateJustification: "",
        operatorNote,
      });
      if (!result.ok || !result.reviewDecision) {
        dispatch({ type: "SET_FIELD", field: "error", value: result.error || "Grok 검수 저장 실패" });
        return false;
      }
      _mergeGrokHandoffState(result);
      if (result.reviewDecision.sourceRationale) {
        dispatch({ type: "EDIT_SCENE", index, field: "source_rationale", value: result.reviewDecision.sourceRationale });
      }
      if (result.reviewDecision.qualityReviewNote) {
        dispatch({ type: "EDIT_SCENE", index, field: "quality_review_note", value: result.reviewDecision.qualityReviewNote });
      }
      dispatch({ type: "EDIT_SCENE", index, field: "visual_quality_verdict", value: accepted ? "pass" : "needs-rework" });
      dispatch({ type: "SET_FIELD", field: "error", value: accepted ? null : `${sceneId} Grok clip rejected. Replace or regenerate before channel render.` });
      return true;
    },
    async renderGrokHandoff() {
      const s = stateRef.current;
      const projectId = s.grokHandoff?.projectId;
      if (!projectId || s.rendering) {
        dispatch({ type: "SET_FIELD", field: "error", value: "렌더할 Grok handoff 패킷이 없습니다" });
        return null;
      }
      try {
        const payload = await apiGetGrokHandoffRenderPayload(projectId);
        if (!payload.ok) {
          _mergeGrokHandoffState({ projectId, renderPayload: payload });
          const missing = payload.missingSceneIds?.length ? ` (${payload.missingSceneIds.join(", ")})` : "";
          const rejected = payload.rejectedSceneIds?.length ? ` rejected: ${payload.rejectedSceneIds.join(", ")}` : "";
          const curation = payload.mainSourceGate?.candidateCurationGapSceneIds?.length
            ? ` candidate curation: ${payload.mainSourceGate.candidateCurationGapSceneIds.join(", ")}`
            : "";
          dispatch({ type: "SET_FIELD", field: "error", value: `${payload.error || "Grok MP4가 아직 준비되지 않았습니다"}${missing}${rejected}${curation}` });
          return null;
        }
        _mergeGrokHandoffState({ projectId, renderPayload: payload });
        return _renderGrokPayload(projectId, payload);
      } catch (e: unknown) {
        const message = e instanceof Error ? e.message : "Grok handoff 렌더 연결 실패";
        dispatch({ type: "SET_FIELD", field: "error", value: message });
        return null;
      }
    },
    async renderGrokHandoffPreview() {
      const s = stateRef.current;
      const projectId = s.grokHandoff?.projectId;
      if (!projectId || s.rendering) {
        dispatch({ type: "SET_FIELD", field: "error", value: "미리 렌더할 Grok handoff 패킷이 없습니다" });
        return null;
      }
      try {
        const payload = await apiGetGrokHandoffRenderPreviewPayload(projectId);
        if (!payload.ok) {
          _mergeGrokHandoffState({ projectId, renderPayload: payload });
          const missing = payload.missingSceneIds?.length ? ` missing: ${payload.missingSceneIds.join(", ")}` : "";
          dispatch({
            type: "SET_FIELD",
            field: "error",
            value: `${payload.error || "가져온 Grok MP4가 아직 없습니다"}${missing}`,
          });
          return null;
        }
        _mergeGrokHandoffState({ projectId, renderPayload: payload });
        return _renderGrokPayload(projectId, payload);
      } catch (e: unknown) {
        const message = e instanceof Error ? e.message : "Grok preview 렌더 연결 실패";
        dispatch({ type: "SET_FIELD", field: "error", value: message });
        return null;
      }
    },
    setSceneCaptionPreset(index, preset) {
      dispatch({ type: "EDIT_SCENE", index, field: "caption_preset", value: preset });
    },
    async renderCurrentDraft() {
      const s = stateRef.current;
      const scenes = s.draftResult?.scenes ?? [];
      if (!s.draftResult?.ok || scenes.length === 0 || s.rendering) return null;
      dispatch({ type: "RENDER_START" });
      try {
        const sceneAssets = await buildSceneAssets(scenes);
        const projectId = `ui-manual-${Date.now()}`;
        const result = await apiRenderSmoke({
          prompt: s.prompt || s.draftResult.message || "Manual Video Studio render",
          budgetMode: "free",
          plannerMode: "sample",
          projectId,
          draftScenes: buildDraftScenes(scenes),
          sceneAssets,
          bgmAsset: s.bgmEnabled ? s.selectedBgmAsset : null,
          providerOverrides: buildProviderOverrides(scenes),
          selectedPexelsVideos: buildSelectedPexelsVideos(scenes),
          subtitleStyle: s.subtitleStyle,
          bgmEnabled: s.bgmEnabled,
          templateType: s.templateType,
        });
        if (result.ok) {
          dispatch({ type: "RENDER_OK", result });
          return result;
        }
        dispatch({ type: "RENDER_FAIL", error: result.error || "렌더 실패" });
        return null;
      } catch (e: unknown) {
        const message = e instanceof Error ? e.message : "렌더 연결 실패";
        dispatch({ type: "RENDER_FAIL", error: message });
        return null;
      }
    },
    async regenerateSceneImage(index) {
      const scene = stateRef.current.draftResult?.scenes?.[index];
      if (!scene?.image_prompt) return;
      const source = scene.image_source === "upload" ? "" : (scene.image_source ?? "");
      const PAID_PROVIDERS = ["imagen", "dalle3", "veo3", "elevenlabs", "openai-tts", "suno"];
      if (source && PAID_PROVIDERS.includes(source)) {
        dispatch({
          type: "SHOW_PAID_CONFIRM",
          dialog: {
            provider: "Imagen 4",
            action: "이미지 1장 재생성",
            estimatedCost: "$0.02",
            freeAlternative: "Pexels 검색으로 대체",
            pendingAction: "regenerate-image",
            pendingIndex: index,
          },
        });
        return;
      }
      await _doGenerateImage(index, source);
    },
    async regenerateSceneTts(index) {
      const s = stateRef.current;
      const scene = s.draftResult?.scenes?.[index];
      if (!scene) return;
      try {
        const res = await apiRegenerateTts(scene.narration, scene.scene_num, s.lang, s.ttsProvider, s.voiceGender);
        if (res.ok && res._tts_url) {
          dispatch({ type: "EDIT_SCENE", index, field: "_tts_url", value: res._tts_url });
          if (res.duration) dispatch({ type: "EDIT_SCENE", index, field: "duration", value: res.duration });
        } else if (!res.ok) {
          dispatch({ type: "SET_FIELD", field: "error", value: res.error || "TTS 재생성 실패" });
        }
      } catch (e: unknown) {
        dispatch({ type: "SET_FIELD", field: "error", value: e instanceof Error ? e.message : "TTS 연결 실패" });
      }
    },
    clearDraft() {
      const scenes = stateRef.current.draftResult?.scenes;
      if (scenes) {
        for (const s of scenes) {
          if (s._upload_preview) URL.revokeObjectURL(s._upload_preview);
        }
      }
      dispatch({ type: "SET_FIELD", field: "draftResult", value: null });
      dispatch({ type: "SET_FIELD", field: "selectedSceneIndex", value: null });
    },
    async deleteBatch(batchId) {
      await apiDeleteBatch(batchId);
      if (stateRef.current.activeBatchId === batchId) {
        dispatch({ type: "SET_FIELD", field: "activeBatchId", value: null });
      }
      const res = await apiListBatches();
      if (res.ok && res.batches) dispatch({ type: "BATCHES_LOADED", batches: res.batches });
    },
    async deleteJob(jobId) {
      await apiDeleteJob(jobId);
      const res = await apiListJobs();
      if (res.ok && res.jobs) dispatch({ type: "JOBS_LOADED", jobs: res.jobs });
    },
    deleteProject(id) {
      dispatch({ type: "DELETE_PROJECT", id });
    },

    async startBatch(variants) {
      const s = stateRef.current;
      if (!s.prompt.trim()) return null;
      const res = await apiCreateBatch({
        prompt: s.prompt, variants,
        template_type: s.templateType, lang: s.lang,
        tts_provider: s.ttsProvider, voice_gender: s.voiceGender,
        subtitle_style: s.subtitleStyle, tone: s.tone,
        target_duration: s.targetDuration,
        ...(s.customInstruction ? { custom_instruction: s.customInstruction } : {}),
      });
      if (res.ok && res.batch_id) {
        dispatch({ type: "SET_FIELD", field: "activeBatchId", value: res.batch_id });
        return res.batch_id;
      }
      dispatch({ type: "DRAFT_FAIL", error: res.error || "Batch creation failed" });
      return null;
    },

    async refreshBatches() {
      const res = await apiListBatches();
      if (res.ok && res.batches) dispatch({ type: "BATCHES_LOADED", batches: res.batches });
    },

    async submitJob() {
      const s = stateRef.current;
      if (!s.prompt.trim()) return null;
      const res = await apiSubmitJob({
        prompt: s.prompt, lang: s.lang, tts_provider: s.ttsProvider,
        voice_gender: s.voiceGender, template_type: s.templateType,
        tone: s.tone, subtitle_style: s.subtitleStyle,
        target_duration: s.targetDuration,
        ...(s.customInstruction ? { custom_instruction: s.customInstruction } : {}),
      });
      if (res.ok) {
        const list = await apiListJobs();
        if (list.ok && list.jobs) dispatch({ type: "JOBS_LOADED", jobs: list.jobs });
        return res.job_id ?? null;
      }
      dispatch({ type: "DRAFT_FAIL", error: res.error || "Job submission failed" });
      return null;
    },

    async refreshJobs() {
      const res = await apiListJobs();
      if (res.ok && res.jobs) {
        dispatch({ type: "JOBS_LOADED", jobs: res.jobs });
      }
    },

    async refreshUsageStats() {
      const stats = await fetchUsageStats();
      if (stats.ok) dispatch({ type: "USAGE_STATS_LOADED", stats });
    },

    async confirmPaidProceed() {
      const dialog = stateRef.current.paidConfirmDialog;
      if (!dialog) return;
      dispatch({ type: "CLOSE_PAID_CONFIRM" });
      if (dialog.pendingAction === "regenerate-image") {
        const scene = stateRef.current.draftResult?.scenes?.[dialog.pendingIndex];
        const source = scene?.image_source === "upload" ? "" : (scene?.image_source ?? "");
        await _doGenerateImage(dialog.pendingIndex, source);
      }
    },

    async confirmPaidUseFree() {
      const dialog = stateRef.current.paidConfirmDialog;
      if (!dialog) return;
      dispatch({ type: "CLOSE_PAID_CONFIRM" });
      if (dialog.pendingAction === "regenerate-image") {
        await _doGenerateImage(dialog.pendingIndex, "pexels");
      }
    },

    closePaidConfirm() {
      dispatch({ type: "CLOSE_PAID_CONFIRM" });
    },
  }); }, []);

  useEffect(() => {
    const projectId = state.grokHandoff?.projectId;
    const jobStatus = state.grokHandoff?.automationJob?.status;
    const manualWatchStatus = state.grokHandoff?.manualDownloadWatchJob?.status;
    const shouldPoll = jobStatus === "queued" || jobStatus === "running"
      || manualWatchStatus === "queued" || manualWatchStatus === "running";
    if (!projectId || !shouldPoll) return;

    let cancelled = false;
    let inFlight = false;
    const poll = async () => {
      if (cancelled || inFlight || document.hidden) return;
      inFlight = true;
      try {
        await actions.syncGrokHandoff({ silent: true, fromBackgroundPoll: true });
      } finally {
        inFlight = false;
      }
    };

    void poll();
    const id = window.setInterval(() => {
      void poll();
    }, 5000);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, [
    actions,
    state.grokHandoff?.automationJob?.jobId,
    state.grokHandoff?.automationJob?.status,
    state.grokHandoff?.manualDownloadWatchJob?.jobId,
    state.grokHandoff?.manualDownloadWatchJob?.status,
    state.grokHandoff?.projectId,
  ]);

  return (
    <StateCtx.Provider value={state}>
      <ActionsCtx.Provider value={actions}>
        {children}
      </ActionsCtx.Provider>
    </StateCtx.Provider>
  );
}
